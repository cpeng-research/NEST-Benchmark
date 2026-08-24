# Step 7: Generate Filled HTML B

This step generates another filled HTML instance (B) from the filled HTML instance (A) in `workflow/3-filled_html-a/data_{lang}`.

## Purpose

For each filled-A HTML table, the script asks the model to create a new plausible filled version while preserving the exact table structure. It changes filled values such as names, dates, IDs, numbers, notes, signatures, selected options, and checked states.

## Input/Output

- Input: `workflow/3-filled_html-a/data_{lang}/*.html`
- Optional reference: `workflow/0-html_template/data_{lang}/*.{HTML,html}`
- Output: `workflow/7-html-b/data_{lang}/{id}.html`

## Usage

Run from the project root:

```bash
python workflow/7-html-b/step7_gen_html_b.py --lang en
```

Process a specific ID range:

```bash
python workflow/7-html-b/step7_gen_html_b.py --lang en --start_id 87 --end_id 88
```

Reprocess outputs whose filled-A input changed:

```bash
python workflow/7-html-b/step7_gen_html_b.py --lang en --check-updates
```

Force regeneration:

```bash
python workflow/7-html-b/step7_gen_html_b.py --lang en --force
```

Use a custom OpenAI-compatible endpoint:

```bash
python workflow/7-html-b/step7_gen_html_b.py \
  --lang en \
  --model gpt-5 \
  --base-url https://api.openai.com/v1 \
  --api-key "$OPENAI_API_KEY"
```

## Validation

Before saving, the script checks that:

- The response is pure HTML with no markdown code fences.
- A table exists in the response.
- Table/cell structure matches the source HTML.
- Visible text is not identical to instance A.

## Dependencies

```bash
pip install openai beautifulsoup4
```
