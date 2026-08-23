# NEST Benchmark

NEST is a benchmark for evaluating whether language models understand the explicit structure of native empty document templates.

> **Looking for the EMNLP 2026 paper artifact?**  
> The frozen code, data, configurations, and results used to reproduce the EMNLP 2026 paper are maintained separately in [NEST-EMNLP2026-Reproduction](https://github.com/cpeng-research/NEST-EMNLP2026-Reproduction).

## Repository Scope

This is the actively maintained NEST Benchmark repository. Its datasets, annotations, evaluation logic, and documentation may continue to evolve after the EMNLP 2026 publication.

The benchmark materials will be migrated here from the development repository before the public release.

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
