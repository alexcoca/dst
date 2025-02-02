Original:

`<SVC> service_name : service_description <INT> intent_name : intent_description <INT> ...`

`<SVC> service_name : service_description <SLT> slot_name : slot_description [<VAL> value <VAL> ...]`

New:

`Intent: Service: service_description 1: intent_description 2: ...`

`Categorical: Service: service_description Slot: slot_description 1: value 2: ...`

`Non-categorical: Service: service_description Slot: slot_description`

| Model            | Intent Accuracy    | Requested Slots F1 | Joint Goal Accuracy |
|------------------|--------------------|--------------------|---------------------|
| Original         | 85.2 (97.6 / 81.0) | 99.2 (99.7 / 99.0) | 57.6 (90.2 / 46.7)  |
| New              | 95.6 (96.2 / 95.4) | 98.8 (99.6 / 98.5) | 59.1 (87.9 / 49.4)  |
| D3ST (Base)      | 97.2               | 98.9               | 72.9 (92.5 / 66.4)  |
| D3ST (XXL)       | 98.8               | 99.4               | 86.4 (95.8 / 83.3)  |
| State-of-the-Art | 94.8 (95.7 / 94.5) | 98.5 (99.4 / 98.2) | 86.5 (92.4 / 84.6)  |

| Model    | Cat  | Non-cat |
|----------|------|---------|
| Original | 62.5 | 72.0    |
| New      | 72.7 | 64.6    |

* Training for more epochs; hyperparameter settings
* Including service, intent and slot names in the input
* Combining original input format (angled brackets for tags) with indices and random ordering
* T5 instead of GPT-2