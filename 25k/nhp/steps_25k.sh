

# 1. get list of avaialble 25k sheets
uv run scrape_available.py

# 2. download the sheets
uv run scrape_sheets.py

# 3. collect the available sheet numbers to data/sheet_nos.txt
uv run collect_sheet_nos.py

# 4. get the kml file for the sheets
# TODO: automate this if needed - this was manually downloaded and upload to soi-ancillary
gh release download soi-ancillary -p "NHP_3-5m.kml" -D data
ogr2ogr -f GeoJSON data/NHP_3-5m.geojson data/NHP_3-5m.kml

# 5. process the geojson to get the sheet nos and correct the coordinates
# creates data/NHP_3-5m_parsed.geojson
# the collect sheet nos from geojson to data/sheet_nos_kml.txt
uv run process_geojson.py
cat data/NHP_3-5m_parsed.geojson| jq -r '.features[].properties.id' > data/sheet_nos_kml.txt

# 6. download sheets from both sheet_nos.txt and sheet_nos_kml.txt
uv run scrape_sheets.py data/sheet_nos.txt
uv run scrape_sheets.py data/sheet_nos_kml.txt

# 7. get the list of sheet nos around the periphary of the available sheets and scrape them
# TODO: add steps used to create 25k index
gh release download soi-ancillary -p "index_25k.geojson" -D data
# create data/index_annotated.geoj with available and unavailable marked
uv run annotate_geojson.py
uv run find_unprobed_neighbors.py > data/sheet_nos_periphery.txt
uv run scrape_sheets.py data/sheet_nos_periphery.txt

# 8. upload the files to github
uvx --from gh-release-tools upload-to-release --release 25k-nhp-orig --extension pdf --folder data/raw -x
uvx --from gh-release-tools generate-lists --release 25k-nhp-orig --extension pdf

# 8. process the downloaded sheets to crop and georeference them
uv run parse.py

# 9. upload the georeferenced tifs to github
uvx --from gh-release-tools upload-to-release --release 25k-nhp-georef --extension tif --folder export/gtiffs -x
uvx --from gh-release-tools generate-lists --release 25k-nhp-georef --extension tif

# 10. create bounds file
uvx --from topo-map-processor collect-bounds --bounds-dir export/bounds --output-file export/bounds.geojson
gh release upload 25k-nhp-georef export/bounds.geojson

# 11. tile the georeferenced tifs
GDAL_VERSION=$(gdalinfo --version | cut -d"," -f1 | cut -d" " -f2)
uvx --with numpy --with pillow --with gdal==$GDAL_VERSION --from topo_map_processor tile --tiles-dir export/tiles --tiffs-dir export/gtiffs --max-zoom 15 --name "SOI 1:25k" --description "SOI 1:25k maps" --attribution-file attribution.txt

# 12. create pmtiles files
uvx --from pmtiles-mosaic partition --from-source export/tiles --to-pmtiles export/pmtiles/SOI-NHP-25k.pmtiles --no-cache

# 13. upload the pmtiles files
gh release upload 25k-nhp-pmtiles export/pmtiles/SOI-NHP-25k.*

# 14. upload the listing file to track whats been tiled
# TODO: Consider uploading bounds file instead as it provides more info needed for retiling
gh release download 25k-nhp-georef -p listing_files.csv 
gh release upload 25k-nhp-pmtiles listing_files.csv
rm listing_files.csv
