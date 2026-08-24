# Benchmark Release Inventory

The versioned NEST Benchmark release contains the complete normalized benchmark
data for 414 English and 414 Chinese records:

- Empty-template HTML and human-verified schema annotations.
- Filled JSON/HTML, contexts, placeholder HTML, CGA metadata, and second-instance
  HTML/JSON artifacts.
- 1,656 rendered PNG inputs covering Empty/Filled and English/Chinese.
- Prepared fine-tuning train/test records and benchmark evaluation code.
- An 828-record provenance manifest.

Run `python scripts/verify_dataset.py` to validate expected counts and every file
listed in `SHA256SUMS`.

Paper-specific cached predictions and frozen numerical results are maintained in
the linked EMNLP 2026 reproduction repository.
