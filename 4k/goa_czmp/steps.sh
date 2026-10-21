#!/bin/bash

# 1. Download the pdfs to data/pdfs and reame them to the format <num>.pdf

# 2. Use mutool to extract images to data/raw/
for f in data/pdfs/*.pdf; do base=$(basename "$f" .pdf); mutool draw -o "data/raw/${base}.png" -r 300 "$f" 1; done

# 3. Generate the grid geojsons from the grid csv file
uv run --with pyproj grid_to_geojson.py

# 4. Georeference and create the COGs
uv run parse_crz.py

# 5. Create the bounds file
uvx --from 'topo-map-processor>=0.1.25' collect-bounds -b export/bounds -o data/bounds.geojson

# 6. Tile the COGs to PMTiles
uvx --from 'topo-map-processor>=0.1.25' --with gdal==3.11.4 tile --tiles-dir export/tiles --tiffs-dir export/gtiffs --max-zoom 18 --name "CZMP 2019 Goa 4k" --description "CZMP 2019 (Draft), Department of Environment and Climate Change, Government of Goa" --attribution "CZMP 2019 (Draft), Department of Environment and Climate Change, Government of Goa"
uvx --from pmtiles-mosaic partition --from-source export/tiles --no-cache --to-pmtiles export/pmtiles/CZMP-2019-Goa-4k.pmtiles

# 7. upload to github releases and update lists
uvx --from gh-release-tools upload-to-release --repo ramSeraph/india_topo_maps --release 4k-goa-2019-czmp-orig --folder data/raw --extension .png
uvx --from gh-release-tools upload-to-release --repo ramSeraph/india_topo_maps --release 4k-goa-2019-czmp-georef --folder export/gtiffs --extension .tif
uvx --from gh-release-tools generate-lists --repo ramSeraph/india_topo_maps --release 4k-goa-2019-czmp-orig --extension .png
uvx --from gh-release-tools generate-lists --repo ramSeraph/india_topo_maps --release 4k-goa-2019-czmp-georef --extension .tif
gh release upload 4k-goa-2019-czmp-georef data/bounds.geojson
gh release upload 4k-goa-2019-czmp-pmtiles data/bounds.geojson
gh release upload 4k-goa-2019-czmp-pmtiles export/pmtiles/CZMP-2019-Goa-4k.pmtiles

