# Ethics and Privacy Notes

This package is organized for anonymous review and reproducibility.

## Template Sources

The benchmark is based on form/table templates and derived annotations rather than
real completed user submissions. Public release should be preceded by a source-level
redistribution audit using `source_provenance_manifest_v1.csv`.

## Synthetic Filled Values

Filled instances and context files may contain realistic-looking values. These values
are treated as synthetic experimental artifacts and are intentionally not edited in
this package, because changing them can alter benchmark results.

## Annotator Privacy

Raw annotator spreadsheets and feedback documents are excluded. The package includes
inter-annotator agreement scripts, aggregate result files, and JSON annotation
directories under anonymized labels such as `annotator_A`. The original mapping
from anonymized labels to annotators is intentionally not included in this review
package.

## Model Outputs

Prediction files are included to allow evaluation without re-calling commercial APIs
or re-running local model inference. These predictions may reproduce synthetic values
from the prompts or generate additional realistic-looking strings. They should be
treated as benchmark artifacts, not as real personal records.

## Public Release Checklist

Before de-anonymized public release:

- Complete and verify `source_provenance_manifest_v1.csv`, including source URLs,
  source organizations, source/license notes, source terms URLs, and redistribution
  status.
- Exclude original third-party PDFs, images, and office documents from the public
  package. Clear normalized benchmark HTML and its rendered PNGs for distribution or
  replace affected rows with NEST-authored equivalents so the released benchmark
  remains reproducible.
- Add final author/citation metadata.
- Apply the intended release boundary: MIT for code/scripts, CC BY 4.0 for
  NEST-created artifacts, and original source-site terms for third-party elements
  retained in normalized benchmark HTML or rendered PNGs.
- Re-scan the final package for API keys, local paths, annotator identities, and accidental metadata.
