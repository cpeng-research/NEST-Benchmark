# IAA Round Naming

The paper reports only the two validated post-pilot IAA rounds:

| Paper label | Repository directory | Unique table IDs | Valid comparisons | Notes |
| --- | --- | ---: | ---: | --- |
| Refinement round | `IAA/stage2` | 6 | 6 | Pairwise annotator comparison on the validated refinement subset. |
| Final audit | `IAA/stage3` | 89 | 90 | Audit against the human-verified workflow JSON. |

`IAA/stage1` is retained for provenance, but it is treated as pilot data and is not reported in the paper.

`IAA/stage3` currently contains 90 JSON files, including files with upper-case `.JSON` extensions.
There is one duplicate `(language, table ID)` entry: `zh/182` appears under both `annotator_A` and `annotator_D`, so the final audit has 89 unique table IDs but 90 valid comparisons.
