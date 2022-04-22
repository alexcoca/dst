import pathlib
from collections import defaultdict
from pathlib import Path
from typing import Optional

import torch
from omegaconf import DictConfig
from tqdm import tqdm

from dst.utils import infer_data_version_from_path, infer_schema_variant_from_path


def remove_padding(output_strings: list[str], pad_token: str) -> list(str):
    """When doing batched decoding, shorter sequences are padded. This
    function removes the padding from the output sequences.

    Note:
    ----
    The addition of `pad_token` at the end of each sequence is specific to the T5
    model where the pad symbol is <EOS>. The T5 parser requires an <EOS> symbol at the
    end of the sequence, which is why it is added to every string.
    """
    padding_free = []
    for s in output_strings:
        pad_token_start = s.find(pad_token)
        while pad_token_start != -1:
            s = f"{s[:pad_token_start]}{s[pad_token_start+len(pad_token):].lstrip()}"
            pad_token_start = s.find(pad_token)
        padding_free.append(f"{s} {pad_token}")
    return padding_free


def decode(args, batch, model, tokenizer, device) -> list[str]:
    input_ids = batch["input_ids"]
    attention_mask = batch["attention_mask"]
    if args.generate_api == "huggingface":
        output_seqs = model.generate(
            input_ids=input_ids.to(device),
            attention_mask=attention_mask.to(device),
            max_length=args.decoder_max_seq_len,
            bos_token_id=tokenizer.bos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
            use_cache=True,
        )
    else:
        raise ValueError(
            f"Unknown generation API: {args.generate_API}. Only `huggingface' option is valid for batched decoding."
        )
    output_strings = tokenizer.batch_decode(output_seqs)
    return remove_padding(output_strings, tokenizer.pad_token)


def run_inference(args, tokenizer, model, data_loader, device):
    model.eval()
    collector = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    description = (
        f"Decoding {len(data_loader.dataset)} batches from split {data_loader.dataset.split}. "
        f"Schema variants: {data_loader.dataset.schema_variants}"
    )
    with torch.no_grad():
        iterator = enumerate(
            tqdm(
                data_loader,
                desc=description,
                disable=args.verbose.disable_display,
            )
        )
        for step, batch in iterator:
            bs_pred_str_batch = decode(args, batch, model, tokenizer, device)
            for i, bs_pred_str in enumerate(bs_pred_str_batch):
                schema_variant, dial_turn = batch["example_id"][i].split("_", 1)
                dialogue_id, turn_idx = dial_turn.rsplit("_", 1)
                usr_utterance = batch["user_utterance"][i]
                service = batch["service"][i]
                collector[dialogue_id][turn_idx]["utterance"] = usr_utterance
                collector[dialogue_id][turn_idx][service]["predicted_str"] = bs_pred_str
    return dict(collector)


def setup_inference_config(
    args: DictConfig, hyp_dir: Optional[pathlib.Path] = None, override: bool = False
):
    """Helper function to setup configuration for running inference during training."""

    inference_config = args.decode
    experiment = args.train.experiment_name
    inference_config.dst_test_path = [str(args.dev.dst_dev_path)]
    inference_config.orig_train_schema_path = str(args.train.orig_train_schema_path)
    inference_config.override = override
    schema_variant_identifier = infer_schema_variant_from_path(
        str(args.dev.dst_dev_path)
    )
    data_version = infer_data_version_from_path(str(args.dev.dst_dev_path))
    assert int(data_version.split("_")[1]) == args.data.version
    try:
        hyp_path = hyp_dir.joinpath(
            experiment,
            schema_variant_identifier,
            "dev",
            data_version,
        )
    # Retrieve path from args
    except AttributeError:
        if not inference_config.hyp_dir:
            raise ValueError(
                "You must provide a path for hypothesis to be saved via args.decode.hyp_path or -hyp/--hyp-path."
            )
        hyp_path = Path(inference_config.hyp_dir).joinpath(
            experiment,
            schema_variant_identifier,
            "dev",
            data_version,
        )
    if not hyp_path.exists():
        hyp_path.mkdir(exist_ok=True, parents=True)
    return inference_config