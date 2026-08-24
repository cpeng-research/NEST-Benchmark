# Step 2: JSON Filling

This step uses an LLM to populate every value in the human-annotated JSON schemas.
Run it from the repository root.

## Inputs and Outputs

- Input: `workflow/1-annotated_json/data_{lang}/`
- Output: `workflow/2-filled_json-a/data_{lang}/`

`{lang}` is `en` or `zh`. Outputs are stored as individual numeric-ID JSON files so
interrupted runs can resume without regenerating completed items.

## Configuration

Set `OPENAI_API_KEY` before making API requests. Set `OPENAI_BASE_URL` only when using
an OpenAI-compatible endpoint instead of the official default. A project-root `.env`
file is also supported.

## Recommended Runner

```bash
python workflow/run_workflow_step.py --step 02-filled-json-a --lang en --update-mode missing-only
```

Use `--lang zh` for Chinese or `--lang both` for both splits. Optional
`--start_id` and `--end_id` arguments restrict the template-ID range.

`--update-mode check` reprocesses outputs whose inputs changed. `missing-only` skips
existing outputs.

## Direct Invocation

```bash
python workflow/2-filled_json-a/step2_fill_json.py --lang en
python workflow/2-filled_json-a/step2_fill_json.py --lang en --start_id 87 --end_id 88
```

After this step, run Step 3 to insert the generated values into the corresponding HTML
templates.
