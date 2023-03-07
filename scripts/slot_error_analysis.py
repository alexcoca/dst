from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Optional

import click

from dst.scoring_utils import get_dataset_as_dict
from dst.sgd_utils import (
    dialogue_iterator,
    infer_schema_variant_from_path,
    turn_iterator,
)
from dst.utils import load_json

logger = logging.getLogger(__name__)


def load_hyps_and_refs(hyp_path: Path, ref_path: Path, decoded_only: list[str] = None):
    hyp_data = load_json(hyp_path.joinpath("metrics_and_dialogues.json"))
    hyp_keys = list(hyp_data.keys())
    for key in hyp_keys:
        if decoded_only is not None and key not in decoded_only:
            hyp_data.pop(key)

    ref_data = get_dataset_as_dict(
        str(ref_path.joinpath("dialogues_*.json")), decoded_only=decoded_only
    )
    data = {"dataset_hyp": hyp_data, "dataset_ref": ref_data}
    return data


def slot_error_anaylsis(hyps: dict, refs: dict, service: str):
    raise NotImplementedError("API needs updating")
    additional_slot_properties = {"in_previous_sys_turn": [], "all": []}
    errors = {"missing_slots": {}, "additional_slots": {}}
    for dial_id in hyps:
        ref_dial, hyp_dial = refs[dial_id], hyps[dial_id]
        for turn_idx, (turn_ref, turn_hyp) in enumerate(
            zip(
                dialogue_iterator(ref_dial, system=False),
                dialogue_iterator(hyp_dial, system=False),
            )
        ):
            for frame_ref, frame_hyp in zip(
                turn_iterator(turn_ref, service=service),
                turn_iterator(turn_hyp, service=service),
            ):
                if frame_hyp["metrics"]["joint_goal_accuracy"] != 1.0:
                    hyp_state = frame_hyp["state"]["slot_values"]
                    ref_state = frame_ref["state"]["slot_values"]
                    if len(hyp_state) != len((set(hyp_state))):
                        slot_counts = Counter(hyp_state)
                        for s in slot_counts:
                            if slot_counts[s] > 1:
                                logger.info(f"Repeated slot: {s}")
                    hyp_active = [h for h in hyp_state]
                    ref_active = [r for r in ref_state]
                    additional_slots = set(hyp_active) - set(ref_active)
                    missing_slots = set(ref_active) - set(hyp_active)
                    if hyp_state.keys() == ref_state.keys():
                        logger.info(
                            f"{dial_id}({turn_idx}): All slots correct but values wrong"
                        )
                    if additional_slots:
                        logger.info(
                            f"{dial_id}({turn_idx}): Additional slots were predicted: {additional_slots}"
                        )
                    if missing_slots:
                        logger.info(
                            f"{dial_id}({turn_idx}): Additional slots were predicted: {additional_slots}"
                        )
                    assert (
                        sorted(hyp_active) == sorted(ref_active)
                        or additional_slots
                        or missing_slots
                    )


def hash_frame(slots_values: dict) -> str:
    this_dict_hash = ""
    for i, (slot, values) in enumerate(sorted(slots_values.items())):
        val_string = " ".join(sorted([v.lower() for v in values])).strip()
        sep = "" if i == 0 else " || "
        this_dict_hash += f"{sep}{slot}:: {val_string} "
    return this_dict_hash.strip()


def find_state_differences(
    hyps: list[dict], service: str, refs: Optional[dict] = None
) -> list[str]:
    """Print state sequences generated by different models to enable visual comparisons."""

    hyps_lens = [len(h) for h in hyps]
    if len(hyps) == 1:
        assert refs is not None, (
            "You must either compare multiple systems or one system and ground truth. "
            "Got one set of results and no references!"
        )
        hyps = [refs, hyps[0]]
        refs = None
    assert (
        len(set(hyps_lens)) == 1
    ), f"Not all hypotheses were input. Hyps lens: {hyps_lens}"
    disagreements = []
    indicators = ["BAS"] + [f"MOD{i}" for i in range(len(hyps))]
    for dial_id in hyps[0].keys():
        compared_dialogues = [hyp[dial_id] for hyp in hyps]
        compared_dial_iterators = [
            dialogue_iterator(d, system=False) for d in compared_dialogues
        ]
        baseline_iter, *comp_iters = compared_dial_iterators
        if refs is not None:
            ref_dial_iterator = dialogue_iterator(refs[dial_id], system=False)
        for turn_idx, baseline_turn in enumerate(baseline_iter):
            other_preds = next(zip(*comp_iters))  # type: tuple[dict]
            if refs is not None:
                ref_turn = next(ref_dial_iterator)
            for baseline_frame in turn_iterator(baseline_turn, service=service):
                other_frames = [
                    next(turn_iterator(pred, service=service)) for pred in other_preds
                ]
                jga = [baseline_frame["metrics"]["joint_goal_accuracy"]] + [
                    f["metrics"]["joint_goal_accuracy"] for f in other_frames
                ]
                if sum(jga) == float(len(jga)):
                    continue
                # if we have a reference, we add it as the first string
                if refs is not None:
                    ref_frame = next(turn_iterator(ref_turn, service=service))
                    this_frame_state_comparison = [
                        hash_frame(ref_frame["state"]["slot_values"])
                    ]
                else:
                    this_frame_state_comparison = []
                for f in [baseline_frame] + other_frames:
                    this_frame_state_comparison.append(
                        hash_frame(f["state"]["slot_values"])
                    )
                disagreements.append(baseline_turn["utterance"])
                print(f"{dial_id}({turn_idx}): {baseline_turn['utterance']}")
                if refs is not None:
                    ref_state = f"REF: {this_frame_state_comparison[0]}"
                    disagreements.append(ref_state)
                print(*this_frame_state_comparison, sep="\n")
                if refs:
                    if any(acc == 1.0 for acc in jga):
                        index = jga.index(1.0)
                        print(f"System {index} got it right, {jga}")
                print()
                disagreements.extend(this_frame_state_comparison)
                disagreements.append("\n")

    return disagreements


@click.command()
@click.option("--quiet", "log_level", flag_value=logging.WARNING, default=True)
@click.option("-v", "--verbose", "log_level", flag_value=logging.INFO)
@click.option("-vv", "--very-verbose", "log_level", flag_value=logging.DEBUG)
@click.option(
    "-m",
    "--metrics_data_paths",
    "metrics_data_paths",
    required=True,
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Absolute path to the directory containing the metrics file to be decoded",
)
@click.option(
    "-g",
    "--ground_data_path",
    "ground_truth_data_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Absolute path to the directory containing the metrics file to be decoded",
)
@click.option(
    "-rpath",
    "--resource_dir_path",
    "resource_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    default="/scratches/neuron/dev/d3st/resources",
    help="Path to resources directory. Used to load mapping from services to dialogue ID",
)
@click.option(
    "-s",
    "--service",
    "service",
    help="SGD service name for which errors are to be analysed",
    required=True,
)
@click.option(
    "--compare_models",
    is_flag=True,
    default=False,
    help="If True, multiple models passed via --metrics_data_path are compared. Otherwise ground truth data must be specified",
)
def main(
    metrics_data_paths: Path,
    ground_truth_data_path: Path,
    resource_path: Path,
    service: str,
    log_level: int,
    compare_models: bool,
):
    logging.basicConfig(
        level=log_level,
        datefmt="%Y-%m-%d %H:%M",
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    this_service_dialogues = load_json(
        resource_path.joinpath("service_to_dialogues.json")
    )[service]
    schema_variant = infer_schema_variant_from_path(
        str(ground_truth_data_path),
    )
    if schema_variant != "original":
        schema_variant_idx = schema_variant[-1]
        service = f"{service}{schema_variant_idx}"
    metrics_and_dialogues = {}
    if not compare_models and ground_truth_data_path is None:
        raise ValueError(
            "You must specify ground truth data if running without --compare_models flag"
        )
    # compare multiple models with GT
    ground_truth_data = None
    # TODO: Ugly code
    if ground_truth_data_path is not None:
        for metrics_data_path in metrics_data_paths:
            data = load_hyps_and_refs(
                metrics_data_path,
                ground_truth_data_path,
                decoded_only=this_service_dialogues,
            )
            ground_truth_data = data.pop("dataset_ref", None)
            metrics_and_dialogues[str(metrics_data_path)] = data

    differences = find_state_differences(
        [d["dataset_hyp"] for d in metrics_and_dialogues.values()],
        service,
        ground_truth_data,
    )
    logger.info(f"Found {len(differences)} differences")
    with open("differences.txt", "w") as f:
        f.writelines(differences)


if __name__ == "__main__":
    main()