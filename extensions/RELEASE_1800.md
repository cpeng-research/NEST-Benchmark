# NEST Balanced View: 450 Templates per Language

This increment adds 225 complete source forms to the previous [1,600-record inventory](RELEASE_1600.md). The selected evaluation view contains **1,800 distinct table inputs: 450 English, 450 Chinese, 450 French and 450 Spanish**.

The cumulative archive has 1825 records. Its 24 historical duplicate records remain unchanged and are excluded only from the balanced view. A further 1 historical record with an unavailable task input is excluded separately, not counted as a duplicate. No identifiers are renumbered.

## Coverage

| Language | Added | Archive | Selected |
| --- | ---: | ---: | ---: |
| en | 15 | 464 | 450 |
| zh | 30 | 461 | 450 |
| fr | 90 | 450 | 450 |
| es | 90 | 450 | 450 |
| **Total** | **225** | **1825** | **1,800** |

The following domain counts refer to the selected view, not the archive.

| Language | GovPublic | Business | Finance | Healthcare | Education | WorkplaceHR | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| en | 100 | 91 | 91 | 57 | 45 | 66 | 450 |
| zh | 28 | 105 | 40 | 37 | 40 | 200 | 450 |
| fr | 83 | 82 | 75 | 69 | 85 | 56 | 450 |
| es | 78 | 73 | 83 | 76 | 82 | 58 | 450 |

Languages are balanced by count. The six original domain categories are retained; domain and structural-complexity counts are reported separately rather than described as uniform. Historical inputs retain their original table-level units: complementary tables from the same source document are not treated as duplicates merely because they share a source or procedure.

## Use the Existing Workflow

New files: [2026-10-25-balanced-450-v0.1](2026-10-25-balanced-450-v0.1/README.md). Each new form follows workflow stages 0-6 and has a stable language-specific numeric ID. Multipage source forms count once. Sources, editions and retrieval dates are recorded in the batch's source credits and provenance files. Completed examples and contexts are synthetic.

The [balanced selection](2026-10-25-balanced-450-v0.1/evaluation_view.json) is an ID/path/hash manifest, not another evaluator. To select it with the existing shared runner, run this from the repository root:

```python
import importlib.util
import json
from pathlib import Path

root = Path.cwd().resolve()
path = root / 'extensions/workflow-support-v1/comparative_eval/run_workflow.py'
spec = importlib.util.spec_from_file_location('workflow', path)
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)
view = json.loads((root / 'extensions/2026-10-25-balanced-450-v0.1/evaluation_view.json').read_text())
wanted = {(s['language'], s['id']) for s in view['samples']}
roots = [root / 'workflow', *sorted((root / 'extensions').glob('*/workflow'))]
samples = [s for s in workflow.discover(roots)
           if (s['lang'], s['sample_id']) in wanted]
assert len(samples) == len(wanted) == 1800

core = workflow.load_core(root)
prepared = workflow.prepare(core, samples, 'your/model', workflow.TASKS,
                            workflow.CONDITIONS, 'py_tree')
```

The existing prompts, task functions and scoring metrics are unchanged. Discovery rejects conflicting IDs and counts byte-identical copies only once. Do not concatenate inventory counts without applying the selected IDs.

## Historical Alias Exclusions

| Excluded | Retained | Reason |
| --- | --- | --- |
| en/54 | en/43 | Repeated SS-4 employer-identification application: fields 1-12 reproduce the corresponding portion of the earlier form. |
| en/68 | en/44 | Two reconstructions of IRS Form W-7 repeat the same ITIN application and its numbered applicant, eligibility, identity and signature fields. |
| en/111 | en/46 | Repeated portions of IRS Form 56 are already present in the earlier complete fiduciary-relationship notice. |
| en/112 | en/46 | Repeated portions of IRS Form 56 are already present in the earlier complete fiduciary-relationship notice. |
| en/113 | en/47 | Repeated portions of IRS Form 56-F are already present in the earlier financial-institution fiduciary notice. |
| en/114 | en/47 | Repeated portions of IRS Form 56-F are already present in the earlier financial-institution fiduciary notice. |
| en/210 | en/69 | The venue-booking application repeats the same contact, hire, event, equipment, alcohol and insurance fields in a different table layout. |
| en/203 | en/70 | The venue-hire cost worksheet repeats the same day/hour rates, equipment, bonds, discounts, insurance and grand-total calculation. |
| en/219 | en/81 | The office-lease form repeats the same lease introduction and twelve substantive fields; only title/intro cell grouping changes. |
| en/227 | en/141 | The later HTML repeats Part B of the earlier telecommunications fair-trading complaint form. |
| en/152 | en/150 | The two self-service hard-copy request HTML files are byte-identical. |
| en/384 | en/154 | The bilingual GF340 reconstruction repeats the job and personal-particulars fields of the earlier HKSAR government employment application. |
| en/339 | en/335 | The media-description tables repeat the same motion-media, recording, wall-chart and model specification form. |
| zh/292 | zh/12 | The entry-registration form repeats the same personal, employment-history, family and departmental-approval fields. |
| zh/218 | zh/21 | The purchase-requisition form repeats the same item-cost table, four supplier quotations, delivery/payment conditions and approval roles. |
| zh/32 | zh/28 | The resignation applications have identical fields and structure, differing only in four colon labels. |
| zh/299 | zh/62 | The weekly work summary/plan repeats the same past-work and future-plan tables; changes are a heading typo and blank cells. |
| zh/305 | zh/71 | The external-lecturer approval forms have identical substantive text, fields and structure after removing intra-label whitespace. |
| zh/186 | zh/120 | The higher-education grant applications repeat the same field inventory and cell structure. |
| zh/188 | zh/129 | The meeting-budget approval form repeats the same budget lines and approval fields. |
| zh/190 | zh/133 | The civilized-unit application HTML files are byte-identical. |
| zh/191 | zh/134 | The job-description form repeats the same position profile, reporting lines, responsibilities and self-summary fields. |
| zh/202 | zh/163 | The customer-profile forms repeat the same personal labels and care-history columns. |
| zh/334 | zh/329 | The personal-information registration repeats the same personal, pay/tax, recruitment-source, education, work and family fields. |

## Unavailable Historical Inputs

- `en/189`: The original empty-template HTML is a zero-byte file, so the three empty-condition task requests have no input. The archive is unchanged; exclude this record from the selected view rather than scoring source failures as zero.

## Integration Checks

The 225 additions passed source/field checks, duplicate screening and 675 empty/filled/mobile rendering checks. All 22,302 pre-existing files retained their hashes. A disposable combined workflow produced the same 1,350 new-sample requests and reference-score checks as the isolated extension. These are integration checks, not new model-performance results.
