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

## Included Materials

- `workflow/`: normalized Empty/Filled HTML, annotations and metadata,
  synthetic artifacts, and HTML-rendered PNG benchmark inputs.
- `table3_comparative_eval/`: prompts, inference entry points, canonical task
  metrics, and aggregation code. Paper-specific cached predictions are kept in
  the reproduction repository.
- `finetune_experiments/`: prepared data and code for the Infilling fine-tuning
  study. Paper-specific predictions/results are kept in the reproduction
  repository.
- `json_algorithm/`: third-party headers and integration files used by the
  optional C++ JEDIS structural-similarity evaluator. Building the evaluator
  requires a compatible local toolchain; the Python evaluator fails explicitly
  if the executable is unavailable.

Paper-specific inter-annotator agreement materials are retained in the frozen
[EMNLP 2026 reproduction repository](https://github.com/cpeng-research/NEST-EMNLP2026-Reproduction),
not in this actively maintained benchmark repository.

## Data Provenance and Distribution

The repository provides a provenance manifest covering all 828 research records at
`data/source_provenance_manifest.csv`. Each row records the template ID, dataset
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
