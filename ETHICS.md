# Ethics and Privacy Notes

This public repository supports benchmark use and reproducibility.

## Template Sources

The benchmark is based on form/table templates and derived annotations rather than
real completed user submissions. Source provenance and source-terms notes are recorded
in `data/source_provenance_manifest.csv`.

## Synthetic Filled Values

Filled instances and context files may contain realistic-looking values. These values
are treated as synthetic experimental artifacts and are intentionally not edited in
this package, because changing them can alter benchmark results.

## Annotator Privacy

Raw annotator spreadsheets, feedback documents, and identity mappings are excluded.
Paper-specific anonymized inter-annotator agreement materials are retained in the
frozen EMNLP 2026 reproduction repository rather than in this actively maintained
benchmark repository.

## Model Outputs

Prediction files are included to allow evaluation without re-calling commercial APIs
or re-running local model inference. These predictions may reproduce synthetic values
from the prompts or generate additional realistic-looking strings. They should be
treated as benchmark artifacts, not as real personal records.

## Release Safeguards

- The repository provides an 828-record provenance manifest.
- Original third-party PDFs, images, and Office documents are not distributed.
- Code is released under MIT; NEST-created artifacts are released under CC BY 4.0;
  retained third-party elements remain subject to their source terms.
- Public files are checked for credentials, local paths, annotator identities, and
  accidental machine metadata.
