# NEST Extension: 2026-10-25-balanced-450-v0.1

Added 225 templates on 2026-10-25. Languages: {'en': 15, 'es': 90, 'fr': 90, 'zh': 30}. Domains: {'Education': 30, 'Healthcare': 18, 'GovPublic': 53, 'WorkplaceHR': 40, 'Business': 44, 'Finance': 40}.

Each sample follows the original numbered `workflow/` stages 0-6 with a stable language-specific ID. Source and field annotations are in `data/`; stages 7-9 were not generated. Use the existing workflow runner at `extensions/workflow-support-v1/comparative_eval/run_workflow.py` and the original task metrics. This batch contains synthetic filled values and contexts but no model baselines.

See [SOURCE.md](SOURCE.md), [DATA_STATEMENT.md](DATA_STATEMENT.md), `manifest.json`, `data/provenance/`, `data/annotations/` and `SHA256SUMS`.

## Balanced Evaluation View

[evaluation_view.json](evaluation_view.json) selects 1,800 distinct table inputs, 450 in each language, from the cumulative inventory. Its paths are relative to the repository root and its hashes bind the seven task artifacts. Historical duplicate records remain in the archive but are listed as excluded aliases in this view; do not add their counts to the selected set. Historical records with unavailable task inputs are separately listed as excluded unusable records. Use the existing shared runner and metrics after selecting these language/ID pairs. See [the release index](../RELEASE_1800.md) for the selection example.
