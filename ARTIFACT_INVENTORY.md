# Benchmark Release Inventory

The numbered text-task workflow contains 420 English, 421 Chinese, 13 French,
and 15 Spanish records (869 total). The original 828-record snapshot remains
unchanged. For the 41 additions, Stages 0-6 and 9 are present; Stages 7-8 are not.

The original English and Chinese records include:

- Empty-template HTML and schema annotations.
- Filled JSON/HTML, contexts, placeholder HTML, CGA metadata, and second-instance
  HTML/JSON artifacts.
- 1,656 original rendered PNG inputs covering Empty/Filled and English/Chinese.
- Prepared fine-tuning train/test records and benchmark evaluation code.
- An unchanged 828-record provenance manifest and an 869-record current index.

The expansion adds 82 rendered PNG inputs, for 1,738 in total. No model
predictions or reference scores are claimed for these added images.

Run `python scripts/verify_dataset.py` to validate expected counts and every file
listed in `SHA256SUMS`.

Paper-specific cached predictions and frozen numerical results are maintained in
the linked EMNLP 2026 reproduction repository.

## Versioned Additions: 15 October 2026

The counts above describe the main `workflow/` directory. Including the separate
versioned additions, the text-task inventory now contains 1,200 distinct
language/ID records: 449 English, 431 Chinese, 170 Spanish, and 150 French.
The additional 331 records remain under `extensions/`, not in the main workflow.

The [current release index](extensions/RELEASE_1200.md) lists the latest 100
records, all batch paths, and the stages supplied for each. It links to the
preceding 1,100-template inventory. These latest records provide stages 0-6;
the image counts above do not include newly rendered versions of these forms.

The root `scripts/verify_dataset.py` checks the main-workflow counts and files
listed in the root `SHA256SUMS`; it does not discover extension batches.
Use the existing [shared workflow entry point](extensions/workflow-support-v1/README.md)
to load the main workflow and selected additions together. To verify a batch's
files, run `shasum -a 256 -c SHA256SUMS` from that batch directory.

## Versioned Additions: 16 October 2026

Including the latest 100 additions, the combined text-task inventory contains
1,300 distinct language/ID records: 449 English, 431 Chinese, 215 Spanish, and 205 French.
The main workflow retains its 869 records; versioned additions provide 431.

The [1,300-template release index](extensions/RELEASE_1300.md) lists each new
batch and sample ID. All 100 new records provide numbered stages 0-6, source
and field annotations, and batch checksums. Stages 7-9 and model baseline
predictions are not included in this increment. Earlier image counts and
main-workflow counts above remain unchanged.

## Versioned Additions: 19 October 2026

The combined text-task inventory contains 1,500 distinct language/ID records:
449 English, 431 Chinese, 315 Spanish, and 305 French. The main workflow
retains its 869 records; versioned additions supply 631 more.

The latest 200 templates are in two batches:

| Batch | Languages and stable IDs | Templates |
| --- | --- | ---: |
| [2026-10-19-multilingual-v0.1](extensions/2026-10-19-multilingual-v0.1/README.md) | French and Spanish, each 700-749 | 100 |
| [2026-10-19-multilingual-v0.2](extensions/2026-10-19-multilingual-v0.2/README.md) | French and Spanish, each 750-799 | 100 |

Each provides all seven numbered stages 0-6, source and collection records,
field annotations, `manifest.json`, and `SHA256SUMS`. Stages 7-9 and model
predictions are not included. Earlier image and main-workflow counts remain
unchanged. The [1,400-template](extensions/RELEASE_1400.md) and
[1,500-template](extensions/RELEASE_1500.md) indexes list every new sample
and its source, domain, page count, and field count.
