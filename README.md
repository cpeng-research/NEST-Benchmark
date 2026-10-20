# NEST Benchmark

NEST is a benchmark for evaluating whether language models understand the explicit structure of native empty document templates.

> **Looking for the EMNLP 2026 paper artifact?**  
> The frozen code, data, configurations, and results used to reproduce the EMNLP 2026 paper are maintained separately in [NEST-EMNLP2026-Reproduction](https://github.com/cpeng-research/NEST-EMNLP2026-Reproduction).

## Repository Scope

This is the actively maintained NEST Benchmark repository. Its datasets,
annotations, evaluation logic, and documentation may continue to evolve after
the EMNLP 2026 publication. Versioned releases preserve stable benchmark
snapshots; the exact paper artifact remains frozen in the reproduction
repository linked above.

## Current Dataset: 1,500 Templates

The combined text-task inventory contains **1,500 templates**: 449 English,
431 Chinese, 315 Spanish, and 305 French. The main `workflow/` contains 869
records; versioned batches under `extensions/` provide another 631.

See the [extension index](extensions/README.md) for release history and the
[latest batch list](extensions/RELEASE_1500.md) for source records and stable
sample IDs. The [shared workflow entry point](extensions/workflow-support-v1/README.md)
loads the main workflow and selected additions together using the existing
prompts and task metrics.

## Included Materials

- `workflow/`: normalized Empty/Filled HTML, annotations and metadata,
  synthetic artifacts, and HTML-rendered PNG benchmark inputs.
- `comparative_eval/`: prompts, inference entry points, canonical task
  metrics, and aggregation code. Paper-specific cached predictions are kept in
  the reproduction repository.
- `finetune_experiments/`: prepared data and code for the Infilling fine-tuning
  study. Paper-specific predictions/results are kept in the reproduction
  repository.
- `json_algorithm/`: third-party headers and integration files used by the
  optional C++ JEDIS structural-similarity evaluator. Building the evaluator
  requires a compatible local toolchain; the Python evaluator fails explicitly
  if the executable is unavailable.

## September 2026 Extension

The numbered `workflow/` now contains 869 template records: 420 English, 421
Chinese, 13 French, and 15 Spanish. The 41 additions occupy the same Stage 0-6
paths and use the same prompts and text-task metrics as the original records.

Stage 9 contains rendered Empty/Filled PNG inputs for all 869 templates.
Stages 7-8 (a second filled instance) still cover only the original 414
English and 414 Chinese records. New PNG inputs are not new model baseline
results.
Batch dates, sources, reuse notes, and annotation records are under
[`data/extension_batches/`](data/extension_batches/README.md).

## Versioned Additions Through October 2026

The main `workflow/` retains its 869 records. A further 231 distinct templates
are packaged in versioned directories under `extensions/`: 77 in the September
batch and 154 in 24 October batches. Reading the main workflow together with
these additions yields 1,100 text-task templates (435 English, 426 Chinese,
125 Spanish, and 114 French). The additions provide numbered stages 0-6 and
source records; they do not add model baseline predictions. See the
[extension release index](extensions/RELEASE_1100.md) for batch paths and the
shared workflow entry point.

Paper-specific inter-annotator agreement materials are retained in the frozen
[EMNLP 2026 reproduction repository](https://github.com/cpeng-research/NEST-EMNLP2026-Reproduction),
not in this actively maintained benchmark repository.

## Data Provenance and Distribution

The original 828-record provenance manifest remains unchanged at
`data/source_provenance_manifest.csv`. The current 869-record index is
`data/source_provenance_manifest_current.csv`. Each row records the template ID, dataset
split, domain, title, normalized HTML path, best available source information, and
a concise source-terms note. Exact item URLs are provided where recoverable;
otherwise, the manifest records the known source website or finite source pool.

NEST does not distribute original third-party PDFs, source images, or Office
documents. Distribution terms for code, NEST-authored artifacts, normalized
benchmark inputs, and retained third-party elements are described in
[`DATA_LICENSE.md`](DATA_LICENSE.md).

Validate the released benchmark file inventory before use:

```bash
python scripts/verify_dataset.py
```

Expected release contents and counts are summarized in
[`ARTIFACT_INVENTORY.md`](ARTIFACT_INVENTORY.md).

## Additions: 15 October 2026

A further 100 templates are available in separate versioned directories under
`extensions/`, bringing the combined text-task inventory to 1,200: 449 English,
170 Spanish, 150 French, and 431 Chinese. This increment adds 32 Healthcare,
28 Education, 20 Finance, 15 GovPublic, and 5 Business templates. The existing
workflow files and identifiers are retained.

Each new record provides numbered stages 0-6, source and collection records,
field annotations, and integrity manifests. Use the existing shared workflow
entry point and original task metrics; no new model baseline results are
included. See the [1,200-template release index](extensions/RELEASE_1200.md)
for all new batch paths and sample IDs.

## Additions: 16 October 2026

A further 100 complete source forms are available in versioned directories
under `extensions/`, bringing the combined text-task inventory to 1,300:
449 English, 431 Chinese, 215 Spanish, and 205 French. Existing workflow
files and identifiers are retained.

Each new record provides numbered stages 0-6, source and collection records,
field annotations, and integrity manifests. Use the existing shared workflow
entry point and original task metrics. See the
[1,300-template release index](extensions/RELEASE_1300.md) for coverage,
all new batch paths, and sample IDs.

## Latest Additions: 19 October 2026

Two further batches add 200 complete source forms: 100 French and 100 Spanish.
The combined inventory is now 1,500 templates: 449 English, 431 Chinese,
315 Spanish, and 305 French. Existing files and identifiers are retained.

- [First increment](extensions/RELEASE_1400.md): 100 templates, French and
  Spanish IDs 700-749, in `extensions/2026-10-19-multilingual-v0.1/`.
- [Second increment](extensions/RELEASE_1500.md): 100 templates, French and
  Spanish IDs 750-799, in `extensions/2026-10-19-multilingual-v0.2/`.

Each sample provides numbered workflow stages 0-6, source attribution,
collection dates, field annotations, and checksums. Stages 7-9 and model
predictions are not included in these batches. Use the existing shared
workflow entry point and original task metrics to evaluate the additions
alongside the main workflow.
