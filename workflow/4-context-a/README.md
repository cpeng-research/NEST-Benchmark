# Step 4: Context Generation

This step converts each filled HTML instance into the narrative context used by the
Infilling task. Run it from the repository root.

## Inputs and Outputs

- Input: `workflow/3-filled_html-a/data_{lang}/`
- Output: `workflow/4-context-a/data_{lang}/`

`{lang}` is `en` or `zh`. Each numeric-ID HTML file produces one text file with the
same ID.

## Configuration

Set `OPENAI_API_KEY` before making API requests. `OPENAI_BASE_URL` may select an
OpenAI-compatible endpoint. A project-root `.env` file is also supported.

## Recommended Runner

```bash
python workflow/run_workflow_step.py --step 04-context-a --lang en --update-mode missing-only --workers 10
```

Use `--lang zh` for Chinese or `--lang both` for both splits. Optional
`--start_id` and `--end_id` arguments restrict the template-ID range.

`--update-mode check` reprocesses outputs whose inputs changed. `missing-only` skips
existing outputs.

## Direct Invocation

```bash
python workflow/4-context-a/step4_gen_context.py --lang en
python workflow/4-context-a/step4_gen_context.py --lang en --start_id 87 --end_id 88 --max-concurrency 10
```

The generation prompt is embedded in `step4_gen_context.py`, as documented in the
root `README.md` prompt-location list.
