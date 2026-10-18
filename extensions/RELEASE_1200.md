# NEST Additions: 15 October 2026

This increment adds 100 templates to the [1,100-template inventory](RELEASE_1100.md),
bringing the combined text-task inventory to 1,200. The main `workflow/` retains
its 869 records; versioned additions provide the other 331. Each new record is
a complete source form, including its continuation pages and annexes where
applicable, rather than a separately counted page or section.

## Coverage

| Language | Added | Combined inventory |
| --- | ---: | ---: |
| English | 14 | 449 |
| Spanish | 45 | 170 |
| French | 36 | 150 |
| Chinese | 5 | 431 |
| **Total** | **100** | **1,200** |

| Domain | Added | Combined inventory |
| --- | ---: | ---: |
| GovPublic | 15 | 178 |
| Business | 5 | 224 |
| Finance | 20 | 188 |
| Healthcare | 32 | 160 |
| Education | 28 | 178 |
| WorkplaceHR | 0 | 272 |
| **Total** | **100** | **1,200** |

The increment prioritizes Healthcare, Education, and Finance, and expands
Spanish and French coverage while retaining the six existing domain labels.

## New Batch Paths

IDs are language-specific and remain unchanged across stages. All links below
lead to batch directories containing the corresponding `workflow/` and source
records.

| Batch | Language | IDs | Templates |
| --- | --- | --- | ---: |
| [2026-10-15-education-fr-v0.1](2026-10-15-education-fr-v0.1/README.md) | fr | 348 | 1 |
| [2026-10-15-education-fr-v0.2](2026-10-15-education-fr-v0.2/README.md) | fr | 349-350 | 2 |
| [2026-10-15-education-fr-v0.3](2026-10-15-education-fr-v0.3/README.md) | fr | 351 | 1 |
| [2026-10-15-education-fr-v0.4](2026-10-15-education-fr-v0.4/README.md) | fr | 358 | 1 |
| [2026-10-15-education-fr-v0.5](2026-10-15-education-fr-v0.5/README.md) | fr | 356 | 1 |
| [2026-10-15-education-fr-v0.6](2026-10-15-education-fr-v0.6/README.md) | fr | 353, 357, 359 | 3 |
| [2026-10-15-education-health-es-v0.1](2026-10-15-education-health-es-v0.1/README.md) | es | 440, 443, 445, 451-452 | 5 |
| [2026-10-15-education-health-es-v0.2](2026-10-15-education-health-es-v0.2/README.md) | es | 441-442, 444, 446-450, 453-454 | 10 |
| [2026-10-15-education-health-zh-v0.1](2026-10-15-education-health-zh-v0.1/README.md) | zh | 500-504 | 5 |
| [2026-10-15-finance-business-fr-v0.1](2026-10-15-finance-business-fr-v0.1/README.md) | fr | 385-394 | 10 |
| [2026-10-15-finance-es-v0.1](2026-10-15-finance-es-v0.1/README.md) | es | 400-404 | 5 |
| [2026-10-15-finance-es-v0.2](2026-10-15-finance-es-v0.2/README.md) | es | 405-409 | 5 |
| [2026-10-15-finance-fr-v0.1](2026-10-15-finance-fr-v0.1/README.md) | fr | 380-384 | 5 |
| [2026-10-15-health-en-v0.1](2026-10-15-health-en-v0.1/README.md) | en | 500-504 | 5 |
| [2026-10-15-health-en-v0.2](2026-10-15-health-en-v0.2/README.md) | en | 505-513 | 9 |
| [2026-10-15-health-es-v0.1](2026-10-15-health-es-v0.1/README.md) | es | 470-472 | 3 |
| [2026-10-15-health-es-v0.2](2026-10-15-health-es-v0.2/README.md) | es | 473-474 | 2 |
| [2026-10-15-health-es-v0.3](2026-10-15-health-es-v0.3/README.md) | es | 475 | 1 |
| [2026-10-15-health-es-v0.4](2026-10-15-health-es-v0.4/README.md) | es | 476-478 | 3 |
| [2026-10-15-health-es-v0.5](2026-10-15-health-es-v0.5/README.md) | es | 479 | 1 |
| [2026-10-15-health-fr-v0.1](2026-10-15-health-fr-v0.1/README.md) | fr | 300 | 1 |
| [2026-10-15-public-education-fr-v0.1](2026-10-15-public-education-fr-v0.1/README.md) | fr | 340-344 | 5 |
| [2026-10-15-public-education-fr-v0.2](2026-10-15-public-education-fr-v0.2/README.md) | fr | 345-347 | 3 |
| [2026-10-15-public-education-fr-v0.3](2026-10-15-public-education-fr-v0.3/README.md) | fr | 352, 354-355 | 3 |
| [2026-10-15-public-es-v0.1](2026-10-15-public-es-v0.1/README.md) | es | 410-414 | 5 |
| [2026-10-15-public-es-v0.2](2026-10-15-public-es-v0.2/README.md) | es | 415-419 | 5 |
| **Total** | | | **100** |

## Files Within Each Batch

- `workflow/0-html_template/data_<language>/<ID>.html`: empty template.
- `workflow/1-annotated_json/data_<language>/<ID>.json`: structural annotation.
- `workflow/2-filled_json-a/data_<language>/<ID>.json`: filled structural annotation.
- `workflow/3-filled_html-a/data_<language>/<ID>.html`: filled instance.
- `workflow/4-context-a/data_<language>/<ID>.txt`: infilling context.
- `workflow/5-ph_html-a/data_<language>/<ID>.html`: placeholder HTML.
- `workflow/6-meta-a/data_<language>/<ID>.json`: task metadata.
- `data/provenance/<batch>.csv` and `SOURCE.md`: source URLs, attribution,
  edition and collection dates, and reuse information.
- `data/annotations/<language>/<ID>.json`: source-to-field annotations.
- `manifest.json` and `SHA256SUMS`: sample inventory and integrity checks.

Stages 0-6 are provided for all 100 records. Filled values and contexts are
synthetic. Stages 7-9 and model baseline predictions are not generated for this
increment.

## Shared Workflow

Use the existing [shared workflow entry point](workflow-support-v1/README.md)
to read the main workflow and selected versioned additions together. It retains
the original prompts and task metrics. Exact duplicate records count once;
conflicting IDs are rejected. The new directories do not overwrite existing
data or change their identifiers.
