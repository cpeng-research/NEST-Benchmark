# Table 3 Comparative Evaluation

This directory contains the implementation and checked-in prediction artifacts
for the paper's filled-table vs. empty-template comparison.

## Inputs

For each language, the scripts read the following package-local artifacts:

- Empty HTML: `workflow/0-html_template/data_<lang>`
- Empty JSON gold: `workflow/1-annotated_json/data_<lang>`
- Filled JSON gold: `workflow/2-filled_json-a/data_<lang>`
- Filled HTML gold: `workflow/3-filled_html-a/data_<lang>`
- Context for infilling: `workflow/4-context-a/data_<lang>`
- Placeholder HTML gold: `workflow/5-ph_html-a/data_<lang>`
- Cell metadata: `workflow/6-meta-a/data_<lang>`
- Empty-template PNGs: `workflow/9-png-a/data_<lang>/empty`
- Filled-instance PNGs: `workflow/9-png-a/data_<lang>/filled`

## Models

The package is scoped to the eight models reported in the paper.

Closed-source/API models:

- `gpt-5`
- `gpt-4o`
- `gpt-4o-mini`
- `gpt-3.5-turbo`

Open-weight local models:

- `Llama-3.1-8B-Instruct`
- `Qwen2.5-7B-Instruct`
- `Gemma-2-9B-it`
- `Mistral-7B-Instruct-v0.3`

For local inference, configure model paths in
`comparative_eval/config.py` or pass `--model_path` to
`run_inference.py`.

## Re-evaluate Existing Predictions

```bash
MODELS="gpt-5 gpt-4o gpt-4o-mini gpt-3.5-turbo Llama-3.1-8B-Instruct Qwen2.5-7B-Instruct Gemma-2-9B-it Mistral-7B-Instruct-v0.3"

python comparative_eval/run_all_evals.py --lang en --models $MODELS
python comparative_eval/run_all_evals.py --lang zh --models $MODELS
python comparative_eval/aggregate_table3.py --lang both --models $MODELS
```

Reference outputs are under:

- `comparative_eval/results/details/`
- `comparative_eval/results/summaries/`
- `comparative_eval/results/table3_both_partial.*`

## Re-run Inference

Small API-model smoke test:

```bash
python comparative_eval/run_inference.py --task schema --condition empty --model gpt-4o-mini --lang en --start_id 1 --end_id 3
python comparative_eval/eval_schema.py --condition empty --model gpt-4o-mini --lang en
```

Run one task across both languages and both empty/filled conditions:

```bash
python comparative_eval/run_task_matrix_inference.py --task schema --model_group api
python comparative_eval/run_task_matrix_inference.py --task schema --model_group open_source
```

For `--task infill`, inference reads the selected HTML input plus the matching
context text from `workflow/4-context-a/data_<lang>/<id>.txt`; filled JSON is
not provided as model input.

## Image-Input Reference Experiment

Construct one dry-run job for every task, condition, and language:

```bash
python comparative_eval/run_image_inference.py --task all --condition both --lang both --limit 1 --dry_run
```

The corresponding OpenAI Batch API entry point is:

```bash
python comparative_eval/run_image_inference_batch.py --mode prepare --task all --condition both --lang both --limit 1 --dry_run
```

Both runners store executed outputs under the normal prediction tree using a separate
`<api-model>-image` model label. The package includes the rendered image inputs but not
QA-evaluation annotations.

## JSON Similarity

`metrics/jedi_py.py` implements the Python JSON-tree similarity used for
schema parsing evaluation. `metrics/jedi_cpp.py` can optionally call the
bundled C++ JEDI binary under `json_algorithm/` if it has been built locally.

```bash
python -m comparative_eval.metrics.validate_jedi_py --lang en --limit 20 --mode tree_edit
```
