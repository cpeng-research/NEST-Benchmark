# Numbered Workflow Support

This additive entry point reads the existing numbered workflow format and calls
the original `comparative_eval` prompts and metrics. It does not provide another
metric implementation, an API client, or a language-specific evaluation rule.

## Layout and Future Merge

Each workflow root has the same seven stages. A sample has one positive decimal
ID per language, without leading zeroes. Use that ID in every stage:

```text
workflow/
  0-html_template/data_<lang>/<id>.html
  1-annotated_json/data_<lang>/<id>.json
  2-filled_json-a/data_<lang>/<id>.json
  3-filled_html-a/data_<lang>/<id>.html
  4-context-a/data_<lang>/<id>.txt
  5-ph_html-a/data_<lang>/<id>.html
  6-meta-a/data_<lang>/<id>.json
```

`--workflow-root` can be repeated to read the original workflow and unmerged
additions together. Without it, the adapter reads the core repository's
`workflow` directory. Languages are discovered from `data_*` directories;
repeat `--lang` to select languages explicitly. An explicitly requested language
without numbered samples is an error. ID filters retain the original
`--start_id` and `--end_id` spelling.

Identity is `(language, numeric ID)`. The union of numbered IDs in all seven
stages is checked, so a missing Stage 0 file does not hide a sample. Copies with
identical seven-file hashes are counted once. Conflicting copies or numeric
aliases are rejected; incomplete samples from different roots are never pieced
together. Reserve new IDs within each language before adding later batches.

ID reservations also include Stage 7 HTML, Stage 8 JSON, and Stage 9 empty/filled
PNGs. An auxiliary-only identity in one root cannot be reused by a core sample in
another root. When two copies have identical seven core artifacts, auxiliary
files present on only one side are allowed; auxiliary files present on both
sides must match byte-for-byte. Auxiliary-only copies without core identity
evidence must match their entire available auxiliary set. Conflicts are checked
before applying ID-range filters. Auxiliary files are not required for the three
text tasks and do not create extra evaluation jobs.

Once additions are ready to merge, their `workflow` trees can be copied into the
root `workflow` without renaming their IDs. This support directory's
`comparative_eval/run_workflow.py` and
`comparative_eval/tests/test_workflow_adapter.py` can likewise be copied into the
core `comparative_eval` directory, provided the destination paths do not already
exist. Original code and data do not need replacing. The adapter locates core
code by walking upwards to `comparative_eval/config.py`; `--benchmark-root`
explicitly selects a core checkout for standalone or temporary merge checks.

No Stage 7/8 generation or Stage 9 image evaluation is implemented here.

## Prepare Requests

Run from the benchmark checkout, using the existing project environment:

```sh
conda run -n nest_dataworkflow python -B \
  extensions/workflow-support-v1/comparative_eval/run_workflow.py prepare \
  --workflow-root workflow \
  --workflow-root extensions/2026-09-balanced100-v0.1/workflow \
  --lang fr --task all --condition both \
  --model MODEL --schema-metric py_tree \
  --output /tmp/nest-fr-requests.json
```

Task choices are `schema`, `alignment`, `infill`, or `all`; conditions are
`empty`, `filled`, or `both`. Schema evaluation requires an explicit
`--schema-metric py_tree` or `--schema-metric cpp`. Neither backend falls back to
the other. `cpp` needs the original JEDI executable and is not numerically
interchangeable with `py_tree`.

The output is `{"model": "...", "jobs": [...]}`. Each job contains its identity,
eligibility status, target count, all seven source-file SHA-256 hashes, source
read issues, and the original `messages` to send to a model. Missing source hashes
are `null`. Only jobs with `status: "ready"` have messages.

Messages contain only the original task inputs: the selected HTML condition,
plus context for infilling. They do not contain reference JSON, metadata, or
placeholder gold. **Send only `job["messages"]` to the model, not the full job.**

Use an external/local model client to execute those messages. This adapter does
not run inference. The original inference CLI's hard-coded language/root choices
are not changed. Do not recreate requests after generation to associate old
predictions with newer data: retain the requests actually used for generation.

## Predictions and Evaluation

Use the original per-file prediction layout below. `--prediction-root` points
directly to the directory containing the task/condition directories:

```text
predictions/{task}_{condition}/{lang}/{model_directory}/{id}.json
```

The model-directory transformation is the existing one: replace `/` and `-`
with `_`. Labels must otherwise contain only letters, digits, `_`, or `.`.
Different labels can sanitize to the same directory, so keep runs separate and
retain the exact `model` label in every envelope.

```json
{
  "sample_id": 1,
  "model": "MODEL",
  "raw_response": "THE MODEL'S ACTUAL RESPONSE"
}
```

Original optional metadata such as `backend` and `created_at` can remain. If
`lang`, `task`, or `condition` are supplied, they must match the file's job.
Use `status: "transport_error"` for a failed model call and
`status: "completed"` for a completed call, including an empty model answer.
An envelope without a status is treated as completed, matching original files.
Do not write a transport failure as an empty completed answer.

Evaluate with the same roots and selection used for preparation:

```sh
conda run -n nest_dataworkflow python -B \
  extensions/workflow-support-v1/comparative_eval/run_workflow.py evaluate \
  --workflow-root workflow \
  --workflow-root extensions/2026-09-balanced100-v0.1/workflow \
  --lang fr --task all --condition both \
  --model MODEL --schema-metric py_tree \
  --prediction-root /tmp/nest-predictions \
  --prepared /tmp/nest-fr-requests.json \
  --output /tmp/nest-fr-results.json
```

Alternatively, store the complete original job under each prediction's `request`
field and omit `--prepared`. Both mechanisms check identity, hashes, messages,
target count, and the selected schema backend. If both are present, both must
match. Without matching evidence, an existing prediction is unscored with
`source_mismatch`; it is not paired with whatever data happen to be current.
This is an integrity check, not proof of how an external client generated data.

## Scores and Coverage

The implementation calls the original functions:

- SSP: `eval_schema.parse_schema_json`, then
  `metrics.jedi_py.compare_json_similarity(mode="tree_edit")` or
  `metrics.jedi_cpp.compare_json_similarity_cpp`.
- CHA: `expand_meta`, `choose_coordinate_strategy`,
  `resolve_expected_names_from_gold`, then `compare_alignment` from
  `eval_alignment`. The name-resolution step is not omitted.
- Infilling: `metrics.infill.compare_infill` with `source_faithful_v3`.

The result retains every selected sample/task/condition row. Summaries are
separate for each task, language, and condition. SSP uses the table-level mean;
CHA and Infilling use summed correct targets divided by summed scored targets.
Scores are fractions between 0 and 1. An incomplete summary is explicitly marked
`complete: false`; its score, if any, describes only scored rows.

`source_error`, `not_run`, `transport_error`, `backend_error`,
`prediction_error`, and `source_mismatch` are unscored, with `score: null`.
Zero-target samples are retained as `ineligible_no_targets`. A completed empty
answer or malformed schema is scored zero as `model_format_failure`, retaining
its target denominator. Nonempty HTML responses are passed to the original
HTML evaluators. With matching preparation evidence, a corrupt prediction JSON
is also treated as a malformed completed output. C++ timeout/missing-distance
failures are reported as unscored backend errors rather than model failures.

All output files are created exclusively, outside the core checkout, all input
workflow roots, and the prediction root. Existing outputs are never overwritten.
Exit codes: `0` means all jobs ready/scored; `1` means the saved output reports
incomplete coverage; `2` means invalid configuration or conflicting inputs.

## Offline Checks and Limits

```sh
conda run -n nest_dataworkflow python -B -m unittest discover \
  -s extensions/workflow-support-v1/comparative_eval/tests \
  -p test_workflow_adapter.py -v
```

Tests include real English, Chinese, and French samples, comparing adapter
results directly with original function calls. Reference/self-check responses
are not model-performance results. C++ failure handling is tested with mocks;
no actual C++ or model API run is implied.

Reading an artifact successfully does not establish that its annotation is
perfect. The French `choices/value` JSON representation, nested bracket text,
and existing cell-type labels are not rewritten here. Original permissive CHA
matching and text-normalization behavior remain in effect. There is no stricter
French-only score, custom prompt, schema normalization, or legacy-data repair.
