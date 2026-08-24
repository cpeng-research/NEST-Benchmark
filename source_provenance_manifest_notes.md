# Source Provenance Manifest Notes

`source_provenance_manifest_v1.csv` is the compact, reader-facing provenance record
for the 828 NEST templates. It is encoded as UTF-8 with a BOM for spreadsheet
compatibility; use `encoding="utf-8-sig"` when reading it from Python.

## Manifest Contents

The manifest contains `id`, `language`, `domain`, `template_html`, `title`, `source`,
and `license_redistribution_note`.

- There are 414 English-split and 414 Chinese-split rows.
- `en (bilingual en/zh)` marks an English-split Hong Kong form with visible English
  and Chinese content. The split label denotes the primary evaluation language, not a
  guarantee that the original form is monolingual.
- `title` uses an explicit source or document title where available. For a fragment
  without a literal title, it gives a concise description of the form's purpose.
- `source` gives the best available named organization or website and its URL. When
  the exact originating site cannot be resolved below a finite known set, the field
  lists that set under `Source Websites` rather than guessing a per-template URL.
- `license_redistribution_note` states a source-specific rule when the row is
  attributable to a source with mapped terms; otherwise it uses the concise
  source-site-terms fallback. The current manifest contains 110 source-specific rows
  across six notes and 718 fallback rows.

The Chinese source set is Ooopic, 51miz, 58pic, and Ibaotu. The primary recorded
source set for unresolved English records is Vertex42 and Template.net; identified
government forms use their item-level URLs.

## Redistribution Boundary

Public accessibility does not by itself imply permission to redistribute an original
document. The intended public NEST release therefore does not redistribute original
third-party PDFs, images, or office documents. It includes the normalized empty and
filled HTML and the PNG image inputs rendered from that HTML because they are required
to reproduce the benchmark, together with this provenance manifest and source-terms
notices.

Code is intended for release under MIT and NEST-authored annotations, prompts,
synthetic artifacts, and evaluation metadata under CC BY 4.0. Third-party elements
retained in normalized HTML or rendered PNGs are excluded from that CC BY 4.0 grant
and remain subject to their original source terms.
