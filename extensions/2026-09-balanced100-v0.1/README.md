# NEST Extension: Education and Healthcare, 2026-09-26

Added on September 26, 2026: 77 independent native templates.

| Language | Education | Healthcare | Total |
| --- | ---: | ---: | ---: |
| French | 23 | 4 | 27 |
| Spanish | 25 | 25 | 50 |
| Total | 48 | 29 | 77 |

Each sample follows the original numbered `workflow/` stages 0-6 and keeps one language-specific numeric ID across all stages. Sources and field annotations are recorded separately under `data/`. Stages 7-9 are not generated.

Use `extensions/workflow-support-v1/comparative_eval/run_workflow.py` with this batch's `workflow/` passed through `--workflow-root`. Existing prompts and task metrics apply without form-specific rules. Synthetic filled values and contexts support SSP, CHA and Infilling. No model baseline results are included.

Future integration copies new numbered artifacts into the corresponding root stages without renumbering or overwriting existing paths. Keep this batch's manifest and source attribution.

See [SOURCE.md](SOURCE.md), [DATA_STATEMENT.md](DATA_STATEMENT.md), `manifest.json`, `data/provenance/`, `data/annotations/` and `SHA256SUMS`.
