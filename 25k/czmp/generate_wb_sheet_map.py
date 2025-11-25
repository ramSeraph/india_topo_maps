#!/usr/bin/env python3
import json
import os
import re

# Load 50K index
with open('index_50k.geojson', 'r') as f:
    index_50k = json.load(f)

# Build mapping from normalized OSM 50K sheet ID to SOI sheet ID
def normalize_osm_sheet(sheet_id):
    """Remove spaces and normalize sheet ID"""
    return re.sub(r'\s+', '', sheet_id).upper()

osm_to_soi = {}
for feature in index_50k['features']:
    osm_sheet = feature['properties']['OSM_SHEET_']
    soi_sheet = feature['properties']['id']
    normalized = normalize_osm_sheet(osm_sheet)
    osm_to_soi[normalized] = (osm_sheet, soi_sheet)

# Load WB grid
with open('data/layers/WB_OSM_25K_Grid.geojson', 'r') as f:
    wb_grid = json.load(f)

# Generate sheet map
sheet_map = {}
base_url = "https://czmp.ncscm.res.in/files/WB/pdf"

for feature in wb_grid['features']:
    osm_25k = feature['properties']['OSM_25K_IN']
    map_no_1 = feature['properties']['Map_No_1']
    
    # Extract 50K part (remove quadrant suffix)
    # Format: "F 45 P 6/SE" -> "F 45 P 6"
    if '/' in osm_25k:
        osm_50k_part, quadrant = osm_25k.rsplit('/', 1)
        quadrant = quadrant.strip()
    else:
        osm_50k_part = osm_25k
        quadrant = ''
    
    # Normalize and lookup
    normalized = normalize_osm_sheet(osm_50k_part)
    
    if normalized in osm_to_soi:
        osm_50k, soi_50k = osm_to_soi[normalized]
        # Create 25K SOI sheet ID: <50K_SOI>_<quadrant>
        soi_sheet = f"{soi_50k}_{quadrant}" if quadrant else soi_50k
    else:
        soi_sheet = "UNKNOWN"
    
    # Check if file exists (JPG or PDF)
    pdf_filename = f"{map_no_1}.pdf"
    jpg_filename = f"{map_no_1}.jpg"
    pdf_path = f"data/WB_pdfs/{pdf_filename}"
    jpg_path = f"data/WB_pdfs/{jpg_filename}"
    
    # Use JPG if it exists, otherwise PDF
    if os.path.exists(jpg_path):
        key = f"WB-{soi_sheet}.jpg"
        sheet_map[key] = {
            "osm_sheet_id": osm_25k,
            "soi_sheet_id": soi_sheet,
            "state_series_no": map_no_1,
            "source_url": "https://ieswm.wb.gov.in/admin/pdf_upload_file/WB%20Draft%20CZMP%202019%20for%20North%2024%20Parganas.pdf",
            "local_path": jpg_path
        }
    elif os.path.exists(pdf_path):
        key = f"WB-{soi_sheet}.pdf"
        sheet_map[key] = {
            "osm_sheet_id": osm_25k,
            "soi_sheet_id": soi_sheet,
            "state_series_no": map_no_1,
            "source_url": f"{base_url}/{pdf_filename}",
            "local_path": pdf_path
        }

# Save sheet map
os.makedirs('data/sheetmaps', exist_ok=True)
with open('data/sheetmaps/WB.json', 'w') as f:
    json.dump(sheet_map, f, indent=2, sort_keys=True)

print(f"Generated sheet map with {len(sheet_map)} entries")
if sheet_map:
    sample_key = sorted(sheet_map.keys())[0]
    print(f"\nSample entry: {sample_key}")
    print(json.dumps(sheet_map[sample_key], indent=2))
    
    # Show a few more examples
    print(f"\nFirst 5 keys:")
    for key in sorted(sheet_map.keys())[:5]:
        print(f"  {key}: {sheet_map[key]['osm_sheet_id']}")
