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
