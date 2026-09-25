# Data Statement

This targeted sample contains ten independent source forms: five Healthcare, three Chinese GovPublic and two Education forms. Within these fixed domain counts, selection prioritizes native Spanish sources and different issuers, subject to evidenced reuse terms and complete annotation. The resulting languages are Spanish (5), English (2) and Traditional Chinese (3), with no translations counted as new forms. The six original domain labels are retained; business topics are secondary metadata. This is not proportional sampling of the existing dataset, nor a balanced or representative survey of institutions, languages or administrative practice.

The batch covers nine issuer identifiers and ten form families. Both education forms come from the same regional education authority but serve different purposes. These are within-batch counts, not verified net-new issuer or family counts relative to all earlier data. No new train/test split is supplied; related forms, versions and translations require family-level grouping before constructing one.

Forms retain substantive source instructions, fields and choices in a normalized semantic layout, not a pixel-identical facsimile. Per-form changes are documented in the annotations. Source versions may be historical; this is an evaluation resource, not a current administrative service.

All completion values and narrative cases are synthetic. They are not real applications, personal records or genuine signatures. Preprinted official contact details remain source text. Do not submit the specimens to an institution.

Inactive text fields remain targets and use context-grounded synthetic not-applicable markers where documented in the annotations. These markers are an annotation convention, not a claim that the source institution requires such entries. Internal-office, signature and seal fields represent a fictional completed workflow, not applicant authority or authentic execution.

No model predictions or performance baselines are included.

## Existing Metric Limitations

- zh/415: the original CHA fallback can still award credit after removing a target name marker for `agent`. Source fields are retained; no batch-specific scoring correction is applied.

Source material remains subject to the terms listed in SOURCE.md, including exclusions and attribution. NEST-authored annotations, synthetic contexts and other original additions are offered under CC BY 4.0.
