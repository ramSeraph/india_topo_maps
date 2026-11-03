# CMPDI replacement symbol fonts

`DGNSymbols.ttf` and `DGNSymbols_new.ttf` reconstruct the missing symbol fonts
observed across **1,430 Survey of India/CMPDI 1:5,000 PDFs**. Version 2 extends
the original AURANGA_10 reconstruction to all 34 observed font/character pairs.
Their outlines come from embedded **SOI_cel** font subsets in the SOI
**1:25,000 NHP** series, remapped and fitted to the CMPDI documents. These are replacements assembled
from available evidence, not recovered copies of the original DGN fonts.

Both fonts are standalone files for PDF-renderer font substitution. Their
family, full and PostScript names are `DGNSymbols` and `DGNSymbols_new`.
All scaling, offsets and outline rotations are in the fonts. The original PDF
does not need to be modified or have these fonts embedded into it.

## Files and use

| File | Purpose |
| --- | --- |
| [DGNSymbols.ttf](DGNSymbols.ttf) | Replacement for `DGNSymbols`: 13 observed symbol codes |
| [DGNSymbols_new.ttf](DGNSymbols_new.ttf) | Replacement for `DGNSymbols_new`: 21 observed symbol codes |
| [manifest.json](manifest.json) | Output checksums, original advances, mappings, transforms and decisions |
| [outlines.json](outlines.json) | The 25 SOI_cel outline families used by the delivered fonts |
| [build_fonts.py](build_fonts.py) | Portable, deterministic rebuild from the recorded outlines and fits |
| [extract_soi_cel.py](extract_soi_cel.py) | Original embedded-outline inventory script, with pinned dependencies |
| [reconstruction/](reconstruction/) | Original trial, refinement, point/well and standalone-font construction stages |
| [reconstruction/extend_collection_fonts.py](reconstruction/extend_collection_fonts.py) | Repeat the version 2 extension from the frozen AURANGA manifest and recorded collection evidence |
| [reconstruction/preview_fonts.py](reconstruction/preview_fonts.py) | Validate glyphs and render before/after contexts using original PDFs |
| [validation.json](validation.json) | Coverage, metrics, source-file hashes and sampled rendering checks |
| [imagery_evidence.json](imagery_evidence.json) | Georeferencing, imagery provenance and provisional well interpretation |
| [gcp_dot_preview.png](gcp_dot_preview.png) | Filled `H` dot fitted inside the separate square glyph |

Configure the renderer's substitution mechanism to associate each PDF font name
with the corresponding TTF. Merely placing the files beside a PDF does not
necessarily register them. Avoid a generic fallback that maps both names to the
same font: some shared character codes deliberately have different geometry.
Keep the original PDF text positions, font sizes, rotations, colours and drawing
order; do not add another scaling correction in the renderer.

Coverage is **all 34 font/character pairs, totalling 686,581 source draws**,
found in the two symbol fonts across the completed 1,430-PDF audit. The fonts
occur on 1,388 PDFs; 42 PDFs have no extracted text and were not OCR-audited.
This does not recover the complete original character sets or establish the
correct interpretation of every feature. The separate ordinary text font `SOI`
is supplied by [SOI_FONTS.zip](https://github.com/ramSeraph/india_topo_maps/releases/download/soi-ancillary/SOI_FONTS.zip);
it is not reconstructed here. Colour comes from the PDF, not these monochrome TTFs.

## Where the outlines came from

The CMPDI PDF references `DGNSymbols`, `DGNSymbols_new` and `SOI` without
embedding their outlines. It does not reference SOI_cel. Directly substituting
SOI_cel fails because its character assignments and advance widths differ:
for example, SOI_cel `T` supplies a bridge outline, whereas CMPDI `T` is used
for filled square/rectangular features.

The source collection is the [NHP original-PDF release](https://github.com/ramSeraph/india_topo_maps/releases/tag/25k-nhp-orig).
Retained outline provenance includes sheets `43J_10_NE`, `53H_12_NE`,
`72O_13_NW`, `73M_4_NE`, `73M_7_SW`, `73N_10_SE`, `73N_5_NW`,
`74E_6_NW`, `78C_2_SW` and `79B_10_SE`. Each outline record identifies example
source sheets, the PDF font xref, and the extracted font's SHA256. Source lists
are capped at five examples per outline; they are not a complete input inventory.
The CMPDI source belongs to the [CMPDI original-PDF collection](https://github.com/ramSeraph/india_topo_maps/releases/tag/5k-cmpdi-orig);
the exact AURANGA file is identified by SHA256 in `manifest.json`.

The extraction and fitting process was:

1. Use PyMuPDF to find embedded fonts whose names contain `SOI_cel` and extract
   their font programs. Use FontTools to inspect every glyph, including unused
   cmap entries. Ignore empty outlines, but do not interpret them as evidence
   that the complete original font lacked that symbol.
2. Decompose outlines, normalize pen coordinates by units per em, round to nine
   decimal places and hash the serialized pen operations. Group matching
   fingerprints, retaining original-coordinate SVG paths and provenance. This
   groups matching representations, not every geometrically equivalent shape.
   The working catalogue contained 126 outline families covering 131 codepoints;
   it was a union of subsets, not the complete SOI_cel font.
3. Inventory AURANGA symbol characters with their font, layer, origin, size,
   rotation and colour. Compare its legend with the intact `43J_10_NE` legend
   and the [supplied SOI legend image](https://storage.googleapis.com/soi_data/legend.webp).
   Match visual roles to CEL outlines; the character letters themselves are
   not semantic descriptions.
4. Build experimental fonts, then adjust glyph size and origin to match the
   composite symbols. Some reference proportions also came from intact NHP
   `SOI_BDR` legend symbols. The final replacement outlines themselves use
   SOI_cel families. Trial PDFs changed only font-resource selection; the script
   checked that reversing those substitutions restored the original page streams.
5. Build the final standalone TTFs at 2,000 units per em, preserving AURANGA's
   original `/Widths` advances, converted from thousandths of an em. Convert SVG
   curves through FontTools' `Cu2QuPen` with a 0.25-font-unit error bound. Set
   the original DGN font names so a renderer can select these replacements.
6. Audit all downloaded CMPDI PDFs for additional nonembedded-font characters.
   Locate the extra symbol shapes in the NHP legends and supplied reference
   legend, retaining source font/code identity. Compare the observed `/Widths`
   across the collection: every observed font/code pair has a consistent
   advance. Add 17 glyphs while retaining the existing fits, except for the
   explicitly selected lined-well correction described below. Record choices,
   source layers, outline provenance and the provisional tree interpretation.
   Render 18 before/after examples from 14 source PDFs with the replacement
   programs attached in memory; verify that page streams and source files stay
   byte-for-byte unchanged.

Review IDs such as `G027` are local catalogue identifiers, not original SOI
glyph IDs. `source_outline_sha256` identifies the normalized pen-operation
fingerprint; it is not a hash of the SVG text or a semantic-certainty score.
The six-element transforms in the manifest map source font coordinates into
the output font: `x' = a*x + c*y + e`, `y' = b*x + d*y + f`.

## Current mappings

Counts are source text occurrences, including clipped or obscured text. They
are not counts of visible features or surveyed objects.

| Font | Code | Count | Role / current rendering | CEL outline |
| --- | --- | ---: | --- | --- |
| DGNSymbols | `$` | 4 | Distance-stone tick | G114, U+0178 |
| DGNSymbols | `(` | 20,145 | Lined well: filled circle | G123, U+02D9 |
| DGNSymbols | `9` | 189 | Grave: single arc | G043, U+00AE |
| DGNSymbols | `I` | 13 | Weir (point symbol) | G122, U+02C9 |
| DGNSymbols | `N` | 734 | Unlined well: hollow circle | G056, U+00CA |
| DGNSymbols | `O` | 80 | Tube-well | G074, U+00F1 |
| DGNSymbols | `P` | 221 | Hand pump | G044, U+00B0 |
| DGNSymbols | `Q` | 2 | Spring | G072, U+00EA |
| DGNSymbols | `T` | 1,391 | Station's red centre; fitted rectangle | G075, U+00F3 |
| DGNSymbols | `g` | 35,018 | Height/power-line dots; adjusted vertical alignment | G027, U+0067 |
| DGNSymbols | `t` | 8 | Surveyed tree (hypothesis) | G073, U+00EE |
| DGNSymbols | `w` | 15 | Height-point marker; filled dot | G027, U+0067 |
| DGNSymbols | `y` | 1,391 | GCP pillar's surrounding square | G046, U+00B3 |
| DGNSymbols_new | `$` | 2,047 | Distance-stone tick; native horizontal bar | G114, U+0178 |
| DGNSymbols_new | `%` | 1,389 | Provisional white filled square | G069, U+00E2 |
| DGNSymbols_new | `&` | 50 | Building point: hollow square | G046, U+00B3 |
| DGNSymbols_new | `'` | 756 | Cross marker | G058, U+00CF |
| DGNSymbols_new | `+` | 2 | Church | G035, U+007C |
| DGNSymbols_new | `/` | 1 | Tomb | G078, U+00F7 |
| DGNSymbols_new | `1` | 51 | Mosque | G053, U+00C0 |
| DGNSymbols_new | `2` | 13 | Idgah | G047, U+00B4 |
| DGNSymbols_new | `5` | 6 | Watch tower | G121, U+02C6 |
| DGNSymbols_new | `6` | 93 | Chhatri | G033, U+007A |
| DGNSymbols_new | `:` | 863 | Temple | G077, U+00F5 |
| DGNSymbols_new | `H` | 1,391 | GCP pillar's filled circular centre | G027, U+0067 |
| DGNSymbols_new | `I` | 4,209 | Overhead-tank legs; native bars | G114, U+0178 |
| DGNSymbols_new | `O` | 574,753 | Embankment/cutting triangular hatching | G001, U+0028 |
| DGNSymbols_new | `Q` | 5 | Dispensary | G010, U+003E |
| DGNSymbols_new | `T` | 24,119 | Building/boundary-pillar filled squares | G075, U+00F3 |
| DGNSymbols_new | `U` | 2,546 | Road bridge | G020, U+0054 |
| DGNSymbols_new | `]` | 1,496 | Aqueduct; quarter-turned bridge outline | G020, U+0054 |
| DGNSymbols_new | `g` | 8,943 | Relative-height and legend dots | G027, U+0067 |
| DGNSymbols_new | `y` | 2,540 | Station's fitted hollow frame | G046, U+00B3 |
| DGNSymbols_new | `~` | 2,097 | Overhead-tank body | G090, U+010B |

## Placement decisions and gotchas

- **The well pair is an explicit reconstruction choice.** Version 2 assigns
  `(` to a filled lined-well circle (G123) and `N` to a hollow unlined-well circle
  (G056), following the selected distinction and the two reference legends.
  The earlier font actually used a hollow circle for `(`; that rendering has
  now been corrected to keep the pair distinct. The `(` occurrences belong to
  the PDF's `WELL` layer. Six locations were inspected in
  georeferenced satellite imagery; three show circular rims and dark openings,
  and three are unclear. Those views do not establish depth or use and cannot
  exclude an open tank. Neither imagery nor the phrase “open well” establishes
  lining or the original missing glyph. The previous interpretation remains
  recorded in `previous_open_well` in the manifest.
- **Four new choices were accepted explicitly.** `9` uses one grave arc G043,
  even though the legends arrange three arcs together. `&` uses hollow square
  G046, with the solid square already assigned to `T`. `P` uses pump-shaped
  G044, found in NHP's `WATER_COLLECTION_POINT` layer. `N` uses the hollow well.
- **The surveyed tree remains provisional.** `DGNSymbols:t` uses G073/U+00EE.
  Its four distinct black locations lie around a playground boundary; the PDF
  paints each twice. Both legends show a black surveyed-tree mark, while nearby
  ordinary tree marks are green. The source has no semantic layer confirming
  that interpretation. The taller tree uses native CEL scale rather than the
  2x scale used for most new glyphs, giving about 5.35 pt height at its original
  9.72 pt PDF font size.
- **Repeated and point weirs differ.** `DGNSymbols:I` uses the explicit point-weir
  glyph G122/U+02C9 from the extended NHP legend. The long-weir legend row uses
  repeated triangular teeth. `DGNSymbols:O` is a tube-well triangle, whereas
  `DGNSymbols_new:O` remains triangular hatching. `DGNSymbols:Q` is a thin spring
  cross; `DGNSymbols_new:Q` is the heavier dispensary cross.
- **Legend fonts and white backing glyphs need care.** Some matching shapes in
  the NHP legend use SOI_BDR or ESRIDefaultMarker rather than SOI_cel. The delivered
  glyphs still come from SOI_cel. Religious/tower symbols may also have separate
  white knockout glyphs in NHP; those are not the visible symbol outline and
  are not automatically reproduced in a monochrome substitute font.
- **`H` is a chosen reconstruction.** Its filled dot is centred in the opening
  of the separate `DGNSymbols:y` square. The opening is about 4.074 pt; the dot
  diameter is 2.037 pt. Neither the original missing `H` outline nor its exact
  dimensions have been recovered. The NHP GCP legend did not settle its shape.
- **The two square outlines stay distinct.** `%` uses CEL G069/U+00E2 and `T`
  uses G075/U+00F3. They are similar filled squares, but are not collapsed into
  one assignment. A font code is qualified by its font: the station `T` and
  building `T` need different fits.
- **Station draw order matters.** Its black frame, white `%`, red centre and
  later railway strokes overlap. The white track gap is drawn separately; it
  is not proof of the `%` shape. In the reviewed fit, white-square and blank
  `%` alternatives rendered identically because later painting concealed the
  difference. `%` remains provisional.
- **Rotation already exists in the PDF.** `$` is a horizontal font bar turned
  vertically by the original text matrix. `I` similarly contributes tank legs.
  The `]` aqueduct choice has a quarter-turn baked into its outline; its
  backslash-looking companion is a separate vector stroke, not another missing
  character. That aqueduct choice is provisionally accepted.
- **Composite symbols constrain fitting.** The tank body and its two repeated
  `I` glyphs can be resized, but one common glyph cannot change the original
  spacing between the two leg origins. It remains about 1.440 pt. The chosen
  body width is 3.683 pt and total height 4.960 pt, guided by the NHP legend.
- **Small offsets were intentional.** The road tick was thickened from about
  0.173 to 0.492 pt. Power-line dots were lowered about 0.810 pt to match the
  adjacent original hollow circles. `w` dots were fitted with their bottoms
  on the adjacent height-label baselines. Text-origin or bounding-box centres
  alone do not establish the correct physical or visual anchor.
- **Coverage is not certainty.** Every observed symbol now has a glyph, but
  some identities and dimensions remain assumptions. Version 2 rendering checks
  sample 18 examples in 14 PDFs, not every occurrence. Most new glyphs use the
  established centred 2x CEL scale; source dimensions and PDF font sizes still
  determine their physical size. Previously unseen codes must be inventoried
  and mapped before using these fonts there. These are ordinary character cmaps
  for the observed ASCII codes, not a claim of
  compatibility with arbitrary legacy symbol-font encodings.
- **Font caches and clipping can mask results.** A renderer may keep an earlier
  font with the same name, use an embedded font in preference to a substitute,
  or clip a glyph that extends beyond its advance. Confirm the selected font
  file and actual page rendering. Some fitted outlines extend outside a nominal
  em; do not clamp them or rescale the PDF layout to an outline's bounding box.

## Rebuilding and auditing

From the repository root, rebuild without the original PDFs or a local font
installation:

```sh
uv run 5k/cmpdi/fonts/build_fonts.py --check
uv run 5k/cmpdi/fonts/build_fonts.py --output /tmp/cmpdi-fonts
```

The pinned FontTools build reproduces the committed TTFs byte for byte, including
recorded font timestamps. `--check` also checks exact names, cmap coverage and
advance widths. This verifies reconstruction consistency, not that a hypothesis
matches the missing original glyph. No network downloads of source maps are
performed by these scripts; `uv` may need to fetch Python dependencies.

To repeat SOI_cel extraction from local NHP PDFs:

```sh
uv run 5k/cmpdi/fonts/extract_soi_cel.py \
  /path/to/43J_10_NE.pdf /path/to/53H_12_NE.pdf \
  --output /tmp/soi-cel-outlines
```

The extractor also accepts `--listing` with `--raw` for a larger inventory. It
writes `outlines.json` and `status.json`; check `errors` in the status output.
Its outline hashes can be compared with this directory's provenance. New
extractions do not automatically inherit the catalogue's `Gxxx` review IDs or
determine DGN mappings. Recorded source lists are examples, not a guarantee that
those two example PDFs contain all 25 delivered outline families.

To repeat the version 2 extension or its rendering checks:

```sh
uv run 5k/cmpdi/fonts/reconstruction/extend_collection_fonts.py --output /tmp/cmpdi-v2
uv run 5k/cmpdi/fonts/reconstruction/preview_fonts.py \
  --sources /path/to/cmpdi-pdfs --output /tmp/cmpdi-font-review
```

The extension uses the frozen `inputs/auranga_manifest.json`, the full CEL
catalogue and `collection_matches.json`, `collection_metrics.json` and
`collection_usage.json`. It writes the same version 2 fonts, manifest and outline
set as the top-level rebuild. The rendering tool expects the original PDFs
listed in `inputs/render_examples.json`; it writes a review PDF and validation
JSON. It does not save modified copies of the source maps. Source filenames,
release links and hashes identify the evidence without requiring the original
workstation's directory layout. Outline details are stored once in the CEL
catalogue; selection records retain their review IDs and fingerprints.

The original AURANGA font-construction stages used during review are retained under
`reconstruction/`. Paths were made configurable and report-only HTML/PDF/image
rendering was removed; the font construction and fitting calculations are
retained. Their committed inputs preserve the full candidate catalogue, AURANGA
observations and power-line measurements. They deliberately retain exploratory
alternatives; the top-level manifest describes the delivered choices.

```sh
export CMPDI_SOURCE_PDF=/path/to/AURANGA_10.pdf
export CMPDI_FONT_WORK=/tmp/cmpdi-font-reconstruction
uv run 5k/cmpdi/fonts/reconstruction/build_trial_fonts.py
uv run 5k/cmpdi/fonts/reconstruction/refine_trial_fonts.py
uv run 5k/cmpdi/fonts/reconstruction/build_point_well_trials.py
uv run 5k/cmpdi/fonts/reconstruction/build_standalone_fonts.py
```

These stages check the AURANGA source hash. Intermediate review PDFs embed
uniquely named trial fonts in copies so their rendering can be inspected; they
never overwrite the source PDF. The last stage writes the standalone fonts to
`$CMPDI_FONT_WORK/standalone_fonts/`. This historical pipeline uses generation
timestamps and produces the earlier AURANGA-only font set, so use the top-level
`build_fonts.py` for a byte-for-byte rebuild of the current fonts, or the extension
script to repeat the version 2 expansion.
The reference measurements are retained, not automatically rediscovered from
arbitrary new legends. Installing fonts or configuring a particular renderer
is left to the caller.
