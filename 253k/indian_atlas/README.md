# Indian Atlas 1:253k

The automatic workflow measures the engraved grid on an intact Survey of India scan, places it in the Walker sheet lattice and renders a 25 m EPSG:3857 Cloud Optimized GeoTIFF with an alpha channel. [Compare the mosaic with a modern map](https://ramseraph.github.io/india_topo_maps/253k/indian_atlas/compare/) or [download the georeferenced editions](https://github.com/ramSeraph/india_topo_maps/releases/tag/253k-indian-atlas-georef).

## Run one sheet

Use a fresh working copy on the raster disk. Run the commands from this directory with Python 3.11 or newer, the system GDAL Python bindings and COG driver, and the NumPy, SciPy and OpenCV versions in `requirements.txt`. On the production host the GDAL bindings are installed alongside the system GDAL library and use the NumPy 1.x ABI.

Place the original JPEG at the `source` path in [the intake queue](work/atlas-intake/queue.json). The queue uses the original archive filenames. If downloading an individual renamed release asset, look up its archive filename in [the originals manifest](https://github.com/ramSeraph/india_topo_maps/releases/download/253k-indian-atlas-orig/253k-indian-atlas-orig-manifest.csv). The originals also come from [John Brown’s Zenodo collection](https://doi.org/10.5281/zenodo.19431985).

For Sheet 51 SE (1876), queue index 11, the source path is `sources/zenodo-19431985/sheets/051 SE Quarter Sheet Indian Atlas (1876).jpg`.

```bash
python -m work.intake_frames_v2 11
python -m work.intake_acquire 11 12 1
python -m work.intake_fit 11 12 1
python -m work.intake_render 11
```

The first and last commands take individual zero-based queue indices. The middle commands take a half-open range. Both take the worker count as their final argument. Detection measures the inner rule around all four striped margins. Acquisition numbers the divisions and measures interior crossings. Fitting builds the training affine, baseline TPS and four-edge weighted TPS. Rendering checks the scan checksum and validates the resulting COG.

Inspect `work/atlas-intake/atlas051-se-1876/{intake-status,fit-status}.json` for the fit decision. A successful render writes `all-edges-3857.cog.tif`, `footprint.geojson` and `web-alignment.json` under `work/atlas-intake/cogs/atlas051-se-1876/`. A failed fit or quality check leaves the edition for review. These scripts cache intermediate stages and write scan configurations under `data/`. Use a fresh working copy when repeating detection with changed inputs.

Some earlier editions used reviewed overview seeds. For configs containing `crossing_preview_seeds`, run `prepare_atlas_quarter.py CONFIG` to generate the native search windows and `fit_atlas001_se.py --config CONFIG` to measure the affine baseline. Create `work/` and `output/` first. For the earliest configs with precomputed windows, the two small seed files are under `work/<edition>/`. For example, to take an earlier seeded scan through to a COG, place the source file at the path in its config and run

```bash
sheet=atlas002-ne-1875
mkdir -p work output
python prepare_atlas_quarter.py "data/${sheet}-scan.json"
python fit_atlas001_se.py --config "data/${sheet}-scan.json"
python audit_atlas_tps_rollout.py --sheet "$sheet"
python fit_atlas_book_edges.py "$sheet"
python render_atlas_book_edges.py "$sheet"
```

Check the fit decision in `work/atlas-book-edges/<edition>/status.json` before rendering. The renderer writes to `output/atlas-book-edges/<edition>/` for this workflow. The intake queue covers the later automatic batch. Reassemblies, incomplete sheets and specially reviewed placements required additional edition-specific work.

## How the 1902 graticule tables enter the fit

Page numbers below count from the cover of the 329-page [Tables for Computing and Projecting the Graticules of the Sheets of the Indian Atlas](https://github.com/ramSeraph/india_topo_maps/releases/download/soi-ancillary/graticules_indian_atlas.pdf), archive identifier NAIDLB00092229.

| PDF pages | Evidence in the book | Use in the code |
|---|---|---|
| 2–3 | Worked example for Sheet 78 and subdivision of a full plate into NW, NE, SW and SE | A quarter occupies half the plate width and height. Its corner targets depend on the named quadrant. |
| 4–5 | Angles of projection, interpolation and Walker’s memorandum on deriving corners from the engraved grid | Interpolate the printed angles. Walker explains that replacing the original projection-table values, including their errors, would disagree with the engraved intersections. The workflow applies no additional adjustment from Auxiliary Table X. |
| 6–8 | Separate Walker and Atkinson governing tables, plate index, central meridian and dimensions | The mosaic uses the Walker lattice. Its central meridian is 76°30′ E. The central full plate extends 37,100 fathoms west and 97,750 east of it. Full plates are 134,850 fathoms wide, quarters are 67,425. Governing parallels on the central meridian are 86 arcminutes apart. The band radii determine the north and south edges. |
| 9 and the detailed latitude tables through 46 | Meridional radii and angles per degree of longitude | The affine reference and TPS use interpolated radius and angle for the sheet’s latitude range. The earlier per-edition transcriptions also carry printed sine values used to check the projection against the book. |

For a printed longitude λ and latitude φ, let R be the interpolated radius in fathoms. Multiply the difference λ − 76.5° (in degrees) by the interpolated angle per longitude degree (in arcseconds), then convert the result to radians to obtain θ. The coordinates in the historical plane are **x = R sin θ** and **y = 7,331,657 − R cos θ**. The inverse recovers printed latitude from radius and printed longitude from angle. The [projection tables](data/atlas-graticule-projection.json), [projection functions](georeference_atlas001.py) and [Walker plate geometry](atlas_book_frame.py) implement these calculations.

In that plane the shared sheet edges are straight. Converting points along an edge back to longitude and latitude gives its geographic curve. The four measured inner corners and identified stripe transitions on each edge receive fixed targets on that curve. A numbered longitude tick alone supplies one longitude observation, and a latitude tick supplies one latitude observation. Opposing sets of marks can supply additional interior intersections. In the default weighted fit their total scalar weight equals the number of measured scalar controls. Held-out ticks and crossings measure residuals. The code checks departures between anchors and rejects folded fits. Editions registered from another engraved frame can also carry a four-corner registration into the common Walker lattice. [Four-edge fitter](fit_atlas_book_edges.py) · [Weighted TPS](atlas_stripe_fit.py)

Page 8 distinguishes the Atlas and Great Trigonometrical Survey longitudes of Madras. Rendering applies the project’s working westward longitude shift of **216.18″** once, comprising 69″ for the Atlas-to-GTS convention and 147.18″ for the adopted second shift. The book supplies the historical grid and the first convention difference. Absolute alignment with modern ground positions remains approximate. The raster renderer then converts the shifted longitude and latitude to Web Mercator. [COG renderer](render_atlas_book_edges.py)
