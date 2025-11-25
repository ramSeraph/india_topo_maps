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

# Load DD grids (Daman and Diu)
grid_files = [
    'data/layers/DAMAN_OSM_25K_Grid_Taluk.geojson',
    'data/layers/Diu_OSM_25K_Grid.geojson'
]

# Generate sheet map
sheet_map = {}
base_url = "https://czmp.ncscm.res.in/files/DD/pdf"

for grid_file in grid_files:
    with open(grid_file, 'r') as f:
        grid = json.load(f)
    
    for feature in grid['features']:
        osm_25k = feature['properties']['OSM_25K_IN']
        map_no = feature['properties']['Map_No']
        
        # Extract number from Map_No (e.g., "DD 03" -> "03")
        map_no_num = map_no.replace('DD ', '').strip()
        
        # Extract 50K part (remove quadrant suffix)
        # Format: "F 43 S 15 / NW" -> "F 43 S 15"
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
        
        # Generate key: DD-<SOI_SHEET_ID>.pdf
        key = f"DD-{soi_sheet}.pdf"
        
        # Check if PDF exists
        pdf_filename = f"{map_no_num}.pdf"
        pdf_path = f"data/DD_pdfs/{pdf_filename}"
        
        if os.path.exists(pdf_path):
            sheet_map[key] = {
                "osm_sheet_id": osm_25k,
                "soi_sheet_id": soi_sheet,
                "state_series_no": map_no,
                "source_url": f"{base_url}/{pdf_filename}",
                "local_path": pdf_path
            }

# Save sheet map
os.makedirs('data/sheetmaps', exist_ok=True)
with open('data/sheetmaps/DD.json', 'w') as f:
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
