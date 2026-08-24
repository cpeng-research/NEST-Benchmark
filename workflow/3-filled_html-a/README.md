# JSON and HTML Filling Workflow

Steps 2 and 3 create the synthetic filled instances used by the benchmark:

1. `workflow/2-filled_json-a/step2_fill_json.py` fills the annotated JSON.
2. `workflow/3-filled_html-a/step3_fill_html.py` inserts those values into the
   corresponding normalized HTML template.

Run both steps from the repository root. Language-specific inputs and outputs use
`data_en/` and `data_zh/` directories.

## Inputs and Outputs

| Step | Input | Output |
|---|---|---|
| 2 | `workflow/1-annotated_json/data_{lang}/` | `workflow/2-filled_json-a/data_{lang}/` |
| 3 | Step 2 output and `workflow/0-html_template/data_{lang}/` | `workflow/3-filled_html-a/data_{lang}/` |

## Configuration

Set `OPENAI_API_KEY` before making API requests. Set `OPENAI_BASE_URL` only when using
an OpenAI-compatible endpoint instead of the official default. A project-root `.env`
file is also supported.

Install the package dependencies first:

```bash
pip install -r requirements.txt
```

## Recommended Runner

Generate only missing English outputs:

```bash
python workflow/run_workflow_step.py --step 02-filled-json-a --lang en --update-mode missing-only
python workflow/run_workflow_step.py --step 03-filled-html-a --lang en --update-mode missing-only
```

Use `--lang zh` for Chinese or `--lang both` for both splits. Optional
`--start_id` and `--end_id` arguments restrict the numeric template-ID range.

`--update-mode check` reprocesses outputs whose inputs changed. `missing-only` skips
existing outputs. The scripts support concurrent processing; use the runner's
`--workers` option only for steps listed as worker-enabled in its help output.

## Direct Invocation

The scripts can also be run directly:

```bash
python workflow/2-filled_json-a/step2_fill_json.py --lang en
python workflow/3-filled_html-a/step3_fill_html.py --lang en
```

Each output is stored as an individual numeric-ID file so interrupted runs can resume
without regenerating completed items.
