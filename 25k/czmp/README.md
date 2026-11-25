# Rebuild the CZMP 1:25,000 maps

Run the commands from `25k/czmp` on a Linux machine. The published build used Python 3.12, GDAL 3.8.4 and the package versions in `requirements-georef.txt`. Install the GDAL command-line tools and development headers, a C++ compiler, and the Python development and venv packages first.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-georef.txt setuptools wheel
python -m pip install --no-build-isolation "GDAL[numpy]==$(gdal-config --version)"
```

## Fetch the originals and export the sheets

```sh
python release_files.py fetch
python georeference.py catalog
python georeference.py export --release-controls -j 4
python georeference.py verify
python release_files.py verify-cogs
```

`release/files.csv` identifies each asset by path, release tag and SHA-256, including the supplementary releases. The fetch command verifies existing files and downloads missing ones. It retrieves 1,018 originals plus `sheetmap.json` and `overlaps.geojson`. The sheet map carries the edition, source URL, printed-ID corrections, page rotation and the originals-only flag for West Bengal’s 11 draft JPEGs. The 71 approved West Bengal PDFs go into the mosaic.

The unresolved state-index entries are Andhra Pradesh 5, 42, 43, 48, 49 and 50, Gujarat 218, 231 and 236, and West Bengal 16 and 56. Tamil Nadu supplies the grid cell shared with Andhra Pradesh 5. West Bengal’s portal file 56 prints the adjacent northeast quarter.

`release/grid.csv` records the WGS84 sheet extents from the NCSCM grids. `release/maharashtra-taluks.geojson` preserves the publisher’s taluk features in the seven shared Maharashtra cells. The state masks come from the released overlap file. Both editions of a shared cell use complementary polygons on the same pixel grid, including offshore coverage. To regenerate the catalog from a local copy of the original publisher layers, run `python georeference.py catalog --layers data/layers`.

`--release-controls` uses the accepted NW, SW, SE and NE page coordinates in `release/controls.csv` and verifies their source checksums. The units are PDF points from the top left of the oriented page. The detector also measures the printed frame and records the difference in `work/corners/`. For an independent measurement, omit `--release-controls` in a separate working directory. `reviewed_corners.csv` records individually reviewed intersections and the matching source digest.

For a single-sheet check, use the same source basename with fetch and export. The final check takes the output COG basename.

```sh
python release_files.py fetch OD-73O_6_NW.pdf
python georeference.py export --release-controls OD-73O_6_NW.pdf
python release_files.py verify-cogs OD-73O_6_NW.tif
```

`CZMPProcessor` uses `topo_map_processor` for georeferencing, warping and COG export. The output is north-up EPSG:3857 on the Google Maps tile grid. The collection-wide verify command checks the grid, source identities, COG layout, and the mask pixels and overviews of all 31 shared state or union territory pairs and seven district pairs. It writes `georef/footprints.geojson` and `georef/corner-audit.csv`.

## Build the mosaic and bounds

```sh
python tile_czmp.py --output export/tiles -j 8
python package_czmp.py archive
python package_czmp.py bounds
```

The processor renders WebP at quality 75 through zoom 15. The archive command uses `partition` and checks every archived tile against its XYZ file before installing `export/pmtiles/CZMP-25k.pmtiles`. To check an existing archive, run `python package_czmp.py verify-archive`. The published mosaic contains 189,005 tiles, including 138,524 at zoom 15. The tile-content SHA-256 reported by the verifier is `3a0e0fa8a1300a7a5c0baaa1d243de6d0b9e5a902281ad619e7d3a2136f9e096`. PMTiles 3.4.1 timestamps its internal gzip streams during packing, so the archive checksum can vary across builds. The bounds command uses `collect-bounds` and includes the COG digest and clipped footprint for each of the 1,007 sheets.

## Build the STAC collection

The bounds command also writes `cogs.csv` and `source-links.csv` with each asset’s actual release URL. For sheets whose printed ID differs from the original filename, the listings pair the assets by output ID and retain the original download URL. The catalog build used the IndianOpenMaps CLI at commit `9e3d6163e763883e1a683abbd6d0b8cc2e00c5fa`. Install the CLI in a separate environment with `uv tool install 'iomaps[admin] @ git+https://github.com/ramSeraph/indianopenmaps.git@9e3d6163e763883e1a683abbd6d0b8cc2e00c5fa#subdirectory=python'`.

```sh
out=export/pmtiles
iomaps admin stac --listing "$out/cogs.csv" --original-listing "$out/source-links.csv" \
  --bounds "$out/bounds.geojson" --collection-id india-czmp-25k \
  --title 'India Coastal Zone Management Plan maps, 1:25,000' \
  --description 'Coastal Zone Management Plan map sheets at 1:25,000. Each item links to a north-up EPSG:3857 Cloud Optimized GeoTIFF and its original scan. The mosaic uses approved 2011-notification maps for West Bengal. Shared state and Maharashtra district editions are clipped at their boundaries.' \
  --license other --datetime 2026-11-25T19:02:41Z \
  --datetime-description 'Collection revision time. Survey, approval and edition dates vary by sheet.' \
  --source-url https://czmp.ncscm.res.in/ --output "$out/CZMP_25k.stac.parquet" \
  --cache-dir work/stac-cache --workers 6
```

Check `CZMP_25k.stac.report.json` for 1,007 prepared items and zero failures, metadata warnings and missing originals. Publication uses `gh-release-tools` for release assets and `iomaps admin make-release` for the STAC collection.
