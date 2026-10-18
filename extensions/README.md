# NEST extensions

Each versioned batch supplies additional templates, source records, and numbered
workflow files. Language-specific IDs remain stable across batches and stages;
the main workflow files are retained.

## Current Inventory

The combined text-task inventory contains **1,300 distinct language/ID records**:
449 English, 431 Chinese, 215 Spanish, and 205 French. The main `workflow/`
contains 869 records, and versioned additions supply 431 more.

| Release index | Added templates | Combined inventory |
| --- | ---: | ---: |
| [Through early October 2026](RELEASE_1100.md) | 231 beyond the main workflow | 1,100 |
| [15 October 2026](RELEASE_1200.md) | 100 in 26 batches | 1,200 |
| [16 October 2026](RELEASE_1300.md) | 100 in 37 batches | 1,300 |

Each release index lists its batch paths, sample IDs, language and domain
coverage. The 41 September additions already integrated into the main workflow
are documented under [`data/extension_batches/`](../data/extension_batches/README.md)
and are counted only once.

## Files and Evaluation

Each batch provides `manifest.json`, `SOURCE.md`, source/field annotations,
`SHA256SUMS`, and the original numbered `workflow/` layout. The latest two
increments provide stages 0-6; stages 7-9 and model predictions are not included.

Use the [shared workflow entry point](workflow-support-v1/README.md) to read the
main workflow and selected batches together. It reuses the existing prompts
and task metrics, counts byte-identical copies once, and rejects conflicting
IDs. `workflow-support-v1/` contains that adapter, not additional templates.

To verify a batch, run `shasum -a 256 -c SHA256SUMS` from its directory.
