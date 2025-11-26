# 1. download and process ancilliary files
uv run download_ancilliary.py
uv run process_ancilliary.py
gh release upload soi-ancilliary data/SOI_FONTS.zip
gh release upload soi-ancilliary data/OSM_SHEET_INDEX.zip
gh release upload soi-ancilliary data/index_50k.geojson

# 2. download and process SOI data
