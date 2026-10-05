# NEST Versioned Additions Through October 2026

The main `workflow/` contains 869 templates. The batches below add 231 distinct
templates, bringing the combined text-task inventory to 1,100. Use the same
language-specific numeric ID across each batch's numbered stages 0-6. Source
records, annotations, and integrity manifests remain with their batches.
Stages 7-9 and model baseline predictions are not included for these additions.

| Batch | Templates |
| --- | ---: |
| [2026-09-balanced100-v0.1](2026-09-balanced100-v0.1/README.md) | 77 |
| [2026-10-education-es-v0.1](2026-10-education-es-v0.1/README.md) | 8 |
| [2026-10-education-public-fr-v0.1](2026-10-education-public-fr-v0.1/README.md) | 15 |
| [2026-10-es-business-gov-v0.1](2026-10-es-business-gov-v0.1/README.md) | 12 |
| [2026-10-es-finance-business-gov-v0.1](2026-10-es-finance-business-gov-v0.1/README.md) | 8 |
| [2026-10-es-finance-business-gov-v0.2](2026-10-es-finance-business-gov-v0.2/README.md) | 6 |
| [2026-10-es-health-finance-v0.1](2026-10-es-health-finance-v0.1/README.md) | 10 |
| [2026-10-fr-finance-business-v0.1](2026-10-fr-finance-business-v0.1/README.md) | 8 |
| [2026-10-fr-finance-business-v0.2](2026-10-fr-finance-business-v0.2/README.md) | 10 |
| [2026-10-fr-finance-business-v0.3](2026-10-fr-finance-business-v0.3/README.md) | 5 |
| [2026-10-fr-gov-edu-v0.1](2026-10-fr-gov-edu-v0.1/README.md) | 4 |
| [2026-10-fr-gov-edu-v0.2](2026-10-fr-gov-edu-v0.2/README.md) | 4 |
| [2026-10-fr-gov-edu-v0.3](2026-10-fr-gov-edu-v0.3/README.md) | 4 |
| [2026-10-fr-gov-edu-v0.4](2026-10-fr-gov-edu-v0.4/README.md) | 6 |
| [2026-10-fr-gov-edu-v0.5](2026-10-fr-gov-edu-v0.5/README.md) | 2 |
| [2026-10-fr-health-public-v0.1](2026-10-fr-health-public-v0.1/README.md) | 5 |
| [2026-10-fr-health-public-v0.2](2026-10-fr-health-public-v0.2/README.md) | 1 |
| [2026-10-has-healthcare-fr-v0.1](2026-10-has-healthcare-fr-v0.1/README.md) | 10 |
| [2026-10-mhra-healthcare-en-v0.1](2026-10-mhra-healthcare-en-v0.1/README.md) | 2 |
| [2026-10-mixed-es-v0.1](2026-10-mixed-es-v0.1/README.md) | 15 |
| [2026-10-sead-education-es-v0.1](2026-10-sead-education-es-v0.1/README.md) | 1 |
| [2026-10-sfe-education-en-v0.1](2026-10-sfe-education-en-v0.1/README.md) | 10 |
| [2026-10-ukhsa-flu-en-v0.1](2026-10-ukhsa-flu-en-v0.1/README.md) | 1 |
| [2026-10-ukhsa-healthcare-en-v0.1](2026-10-ukhsa-healthcare-en-v0.1/README.md) | 2 |
| [2026-10-zh-education-v0.1](2026-10-zh-education-v0.1/README.md) | 5 |

The [shared workflow entry point](workflow-support-v1/README.md) reads the main
workflow and any selected additions together while retaining the original
prompts and task metrics. Exact duplicate records count once; conflicting IDs
are rejected. These directories are separate additions and do not overwrite
the main workflow.
