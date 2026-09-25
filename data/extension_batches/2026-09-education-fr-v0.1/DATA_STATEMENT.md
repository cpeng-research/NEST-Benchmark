# Extension Data Statement

## Scope

One French-language, three-page source form is represented as a continuous
normalized HTML table. All six sections and the third-page privacy continuation
are retained. This is a complete semantic transcription, not a facsimile of the
source typography or pagination. The ministry graphic, embedded fonts, page
numbers, and page-margin whitespace are not reproduced.

The document concerns the historical Dix Mots 2024 competition. Its historical
institution names, communication channels, and fixed links are retained, not
updated or presented as current instructions.

## Construction

Source anchors and normalization notes are provided in `data/annotations/fr/1.json`.

All case-specific names, addresses, dates, contact details and signature
placeholders in the Filled specimen are synthetic. The source's fixed ministry
and CNIL contact details remain institutional source text. No actual pupil
record, recording, or signature was collected for this sample.

Checkbox groups preserve single-choice versus multi-choice meaning. The source
contains an implicit `Autre (précisez)` completion cue without a separate dotted
line; it is explicitly annotated as an input, not silently omitted. The data
controller placeholder is an institution-level template-configuration field.

## Coverage and Use

This is an addition to the existing `Education` domain and adds native French
coverage. It does not establish a new top-level domain or demonstrate model
generalization. The issuer is not present among the baseline's recorded
candidate institution names, but incomplete historical provenance prevents a
verified full-baseline institution or template-family novelty claim.

No train/test split is assigned. Related school image/voice consent variants,
translations and activity-year versions should remain in the same family when
designing future splits. One specimen is insufficient for language comparisons
or population-level performance estimates.

Reference checks and deliberately altered fixtures are integrity and
target-coverage tests, not model results. No model predictions are included.
The existing infilling text matcher removes some punctuation, including decimal
commas and minus signs; its scores must not be interpreted as strict numeric
validation. Typed signature targets assess completion, not signature validity.

## Licensing

NEST-authored annotations, synthetic additions and metadata follow the root
repository's CC BY 4.0 terms. Added code follows its MIT License. Retained source
text and structural content follow the source's Etalab 2.0 grant and exclusions,
with attribution in [SOURCE.md](SOURCE.md); they are not represented as wholly
NEST-authored. Dependencies retain their respective licenses.
