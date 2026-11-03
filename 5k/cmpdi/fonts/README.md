# CMPDI replacement symbol fonts

`DGNSymbols.ttf` and `DGNSymbols_new.ttf` reconstruct the missing symbol fonts
used in **AURANGA_10.pdf**, a Survey of India/CMPDI 1:5,000 map. Their outlines
come from embedded **SOI_cel** font subsets in the SOI **1:25,000 NHP** series,
remapped and fitted to the CMPDI document. These are replacements assembled
from available evidence, not recovered copies of the original DGN fonts.

Both fonts are standalone files for PDF-renderer font substitution. Their
family, full and PostScript names are `DGNSymbols` and `DGNSymbols_new`.
All scaling, offsets and outline rotations are in the fonts. The original PDF
does not need to be modified or have these fonts embedded into it.

## Files and use

| File | Purpose |
| --- | --- |
| [DGNSymbols.ttf](DGNSymbols.ttf) | Replacement for `DGNSymbols`: 5 observed symbol codes |
| [DGNSymbols_new.ttf](DGNSymbols_new.ttf) | Replacement for `DGNSymbols_new`: 12 observed symbol codes |
| [manifest.json](manifest.json) | Output checksums, original advances, mappings, transforms and decisions |
| [outlines.json](outlines.json) | The 10 SOI_cel outline families used by the delivered fonts |
| [build_fonts.py](build_fonts.py) | Portable, deterministic rebuild from the recorded outlines and fits |
| [extract_soi_cel.py](extract_soi_cel.py) | Original embedded-outline inventory script, with pinned dependencies |
| [reconstruction/](reconstruction/) | Original trial, refinement, point/well and standalone-font construction stages |
| [imagery_evidence.json](imagery_evidence.json) | Georeferencing, imagery provenance and provisional well interpretation |
| [gcp_dot_preview.png](gcp_dot_preview.png) | Filled `H` dot fitted inside the separate square glyph |

Configure the renderer's substitution mechanism to associate each PDF font name
with the corresponding TTF. Merely placing the files beside a PDF does not
necessarily register them. Avoid a generic fallback that maps both names to the
same font: some shared character codes deliberately have different geometry.
Keep the original PDF text positions, font sizes, rotations, colours and drawing
order; do not add another scaling correction in the renderer.

Coverage is **all 17 font/character pairs, totalling 1,011 source occurrences**,
seen in the two symbol fonts in AURANGA_10. It is not coverage of the complete
original DGNSymbols character sets or every CMPDI sheet. The separate ordinary
text font named `SOI` is also missing from that PDF and is **not** reconstructed
here. Colour comes from the PDF, not from these monochrome TTFs.

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
| DGNSymbols | `(` | 22 | Provisional open well; hollow circle | G056, U+00CA |
| DGNSymbols | `w` | 2 | Height-point marker; filled dot | G027, U+0067 |
| DGNSymbols | `T` | 1 | Station's red centre; fitted rectangle | G075, U+00F3 |
| DGNSymbols | `g` | 5 | Height/power-line dots; adjusted vertical alignment | G027, U+0067 |
| DGNSymbols | `y` | 1 | GCP pillar's surrounding square | G046, U+00B3 |
| DGNSymbols_new | `O` | 943 | Embankment/cutting triangular hatching | G001, U+0028 |
| DGNSymbols_new | `g` | 23 | Relative-height and legend dots | G027, U+0067 |
| DGNSymbols_new | `U` | 1 | Road bridge | G020, U+0054 |
| DGNSymbols_new | `]` | 1 | Aqueduct; quarter-turned bridge outline | G020, U+0054 |
| DGNSymbols_new | `y` | 1 | Station's fitted hollow frame | G046, U+00B3 |
| DGNSymbols_new | `%` | 1 | Provisional white filled square | G069, U+00E2 |
| DGNSymbols_new | `T` | 2 | Building/boundary-pillar filled squares | G075, U+00F3 |
| DGNSymbols_new | `$` | 1 | Distance-stone tick; native horizontal bar | G114, U+0178 |
| DGNSymbols_new | `H` | 1 | GCP pillar's filled circular centre | G027, U+0067 |
| DGNSymbols_new | `I` | 2 | Overhead-tank legs; native bars | G114, U+0178 |
| DGNSymbols_new | `~` | 1 | Overhead-tank body | G090, U+010B |
| DGNSymbols_new | `'` | 3 | Cross marker | G058, U+00CF |

## Placement decisions and gotchas

- **Filled versus hollow is not inferred from the word “open”.** The `(`
  occurrences belong to the PDF's `WELL` layer. Six locations were inspected in
  georeferenced satellite imagery; three show circular rims and dark openings,
  and three are unclear. Those views do not establish depth or use and cannot
  exclude an open tank. “Open well” and the hollow-circle rendering are current
  provisional choices. The reference legends distinguish lined and unlined
  wells using filled and hollow circles, which is a different distinction.
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
  some identities and dimensions remain assumptions. Fits were reviewed on
  AURANGA, not validated across the CMPDI collection. Missing codes in another
  sheet must be inventoried and mapped before using these fonts there. These
  are ordinary character cmaps for the observed ASCII codes, not a claim of
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
those two example PDFs contain all ten delivered outline families.

The actual font-construction stages used during review are retained under
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
timestamps, so use the top-level `build_fonts.py` for a byte-for-byte rebuild.
The reference measurements are retained, not automatically rediscovered from
arbitrary new legends. Installing fonts or configuring a particular renderer
is left to the caller.
