# Data Statement

NEST contains native empty structural templates and derived artifacts for evaluating
template-level table understanding. The package includes English and Chinese form-like
tables across multiple domains, including workplace/HR, business, public service,
education, finance, and healthcare.

The English/Chinese label denotes the dataset split and primary evaluation language,
not a guarantee of monolingual source content. In particular, some Hong Kong public
forms assigned to the English split retain parallel English and Chinese text. Their
provenance-manifest titles may consequently be bilingual or contain Chinese.

## Data Artifacts

The main data artifacts are organized in `workflow/`:

- `0-html_template/`: empty HTML table templates.
- `1-annotated_json/`: gold structural annotations.
- `2-filled_json-a/`: filled JSON artifacts.
- `3-filled_html-a/`: filled HTML instances.
- `4-context-a/`: context passages used for generative infilling.
- `5-ph_html-a/`: placeholder HTML templates.
- `6-meta-a/`: cell-level metadata.
- `7-html-b/` and `8-json-b/`: additional generated/derived artifacts.
- `9-png-a/`: rendered empty-template and filled-instance inputs for the image-input reference experiment, separated by language and condition.

The filled values are synthetic/generated experimental artifacts. They are preserved
exactly in this package to keep the benchmark inputs and reported results stable.

## Source and Redistribution Audit

`source_provenance_manifest_v1.csv` is the compact reader-facing per-template
source/provenance manifest. It records sample IDs, split-language and domain labels,
template paths, titles, the best available source, and a combined license/redistribution
note.

Because collection spanned an extended period and multiple channels, not every
template can still be assigned an exact item URL. The public `source` field therefore
names the known organization or website and provides its URL; where only a finite set
of possible source sites is available, it lists them under `Source Websites`.
Chinese templates come from Ooopic, 51miz, 58pic, or Ibaotu. The primary source set for
still-unresolved English records is Vertex42 and Template.net; government forms use
their identified item URLs.

The source-provenance manifest is not final. Source metadata and redistribution
rights still need to be checked source by source before a de-anonymized public
release. Rows without verified source/license information should not be treated as
confirmed licensed sources.

The review package is intended for anonymous peer review and reproduction. Before
public release, each source template should be checked against its source terms. The
public release will not redistribute original third-party PDFs, images, or office
documents. It will include the normalized empty and filled HTML and the PNG image inputs
rendered directly from them, as required to reproduce the benchmark, together with
provenance locators, NEST-authored annotations/metadata, prompts, synthetic artifacts,
and code. The PNGs are not copied from original documents. Third-party elements retained
in normalized HTML or rendered PNGs remain subject to their source terms and are
excluded from NEST's CC BY 4.0 grant.

## Privacy

The package does not contain real user-submitted form records. Some fields may look
like names, phone numbers, addresses, identity numbers, or emails because they are
synthetic filled values or model-generated predictions. These values were not
normalized during package assembly because modifying them would change experimental
inputs/outputs.

Raw annotator workbooks and feedback documents are not included in this anonymous
package. IAA JSON annotation directories are included under anonymized labels only.
