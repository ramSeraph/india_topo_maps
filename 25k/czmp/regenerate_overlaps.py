#!/usr/bin/env python3
"""
Regenerate overlaps.geojson with correct state matching.

This script finds all overlapping sheets from sheetmap.json and extracts
the corresponding features from taluk sheetmaps, ensuring that features
are only included if they match the state from the sheetmap entry.
"""

import json
from collections import defaultdict
import os
import glob
import re

# Normalize OSM sheet ID
def normalize_osm_id(osm_id):
    if not osm_id:
        return ""
    normalized = re.sub(r'\s*/\s*', '/', osm_id.strip())
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized

# State code mapping
STATE_CODE_MAP = {
    'Andhra Pradesh': 'AP',
    'Puducherry': 'PY',
    'Tamil Nadu': 'TN',
    'Odisha': 'OD',
    'Gujarat': 'GJ',
    'Goa': 'GA',
    'Karnataka': 'KA',
    'Kerala': 'KL',
    'Maharashtra': 'MH',
    'West Bengal': 'WB',
    'Daman and Diu': 'DD',
}

# Mapping from taluk file to state codes
TALUK_FILE_TO_STATE_CODES = {
    'AP_OSM_25K_Grid_Taluk.geojson': ['AP'],
    'DAMAN_OSM_25K_Grid_Taluk.geojson': ['DD'],
    'Diu_OSM_25K_Grid_Taluk.geojson': ['DD'],
    'GA_OSM_25K_Grid_Taluk.geojson': ['GA'],
    'GJ_OSM_25K_Grid_Taluk.geojson': ['GJ'],
    'KA_OSM_25K_Grid_Taluk.geojson': ['KA'],
    'KL_OSM_25K_Grid_Taluk.geojson': ['KL'],
    'MH_OSM_25K_Grid_Taluk.geojson': ['MH'],
    'OD_OSM_25K_Grid_Taluk.geojson': ['OD'],
    'PY_OSM_25K_Grid_Taluk.geojson': ['PY'],
    'TN_OSM_25K_Grid_Taluk.geojson': ['TN'],
    'WB_OSM_25K_Grid_Taluk.geojson': ['WB'],
}

print("="*80)
print("REGENERATING overlaps.geojson with correct state matching")
print("="*80)

# Load sheetmap.json
print("\nLoading sheetmap.json...")
with open('data/sheetmap.json', 'r') as f:
    sheetmap = json.load(f)

# Group sheets by soi_sheet_id to find overlaps
sheet_groups = defaultdict(list)
for pdf_name, sheet_info in sheetmap.items():
    soi_sheet = sheet_info.get('soi_sheet_id')
    if soi_sheet:
        sheet_groups[soi_sheet].append((pdf_name, sheet_info))

# Find overlaps (excluding UNKNOWN)
overlaps = {k: v for k, v in sheet_groups.items() if len(v) > 1}
print(f"Found {len(overlaps)} overlapping soi_sheet_id values")

print('overlaps found:')
for soi_sheet, sheets in overlaps.items():
    print(f"  {soi_sheet}:")
    for pdf_name, sheet_info in sheets:
        state_name = sheet_info.get('state_name', 'UNKNOWN')
        osm_sheet_id = sheet_info.get('osm_sheet_id', 'UNKNOWN')
        print(f"    - {pdf_name}: state={state_name}, osm_sheet_id={osm_sheet_id}")

# Build a lookup: (osm_normalized, state_code) -> list of sheet_info
osm_state_lookup = {}
for soi_sheet, sheets in overlaps.items():
    for pdf_name, sheet_info in sheets:
        state_name = sheet_info.get('state_name')
        osm_sheet_id = sheet_info.get('osm_sheet_id')
        
        if state_name and osm_sheet_id:
            state_code = STATE_CODE_MAP.get(state_name)
            if state_code:
                # Handle Daman and Diu which can be list
                if isinstance(state_code, list):
                    state_codes = state_code
                else:
                    state_codes = [state_code]
                
                normalized_osm = normalize_osm_id(osm_sheet_id)
                
                for sc in state_codes:
                    key = (normalized_osm, sc)
                    if key not in osm_state_lookup:
                        osm_state_lookup[key] = []
                    osm_state_lookup[key].append({
                        'soi_sheet_id': soi_sheet,
                        'pdf_name': pdf_name,
                        'state_name': state_name,
                        'local_path': sheet_info.get('local_path'),
                    })
        else:
            print(f"  WARNING: Missing state_name or osm_sheet_id for {pdf_name}")

print(f"Built lookup with {len(osm_state_lookup)} (OSM_ID, state_code) combinations")

# Load taluk files and match with lookup
print("\nLoading taluk files...")
taluk_files = glob.glob('data/layers/*_Taluk.geojson')

all_features = []
found_count = 0
not_found = []

for taluk_file in sorted(taluk_files):
    basename = os.path.basename(taluk_file)
    state_codes = TALUK_FILE_TO_STATE_CODES.get(basename, [])
    
    if not state_codes:
        continue
    
    print(f"  Processing {basename}...")
    
    try:
        with open(taluk_file, 'r') as f:
            taluk_data = json.load(f)
        
        features = taluk_data.get('features', [])
        for feature in features:
            props = feature.get('properties', {})
            osm_id = props.get('OSM_25K_IN')
            
            if osm_id:
                normalized = normalize_osm_id(osm_id)
                
                # Check if this (OSM_ID, state_code) combo exists in our overlap lookup
                for state_code in state_codes:
                    key = (normalized, state_code)
                    if key in osm_state_lookup:
                        # Match found! This feature belongs to an overlap
                        sheet_infos = osm_state_lookup[key]
                        
                        for sheet_info in sheet_infos:
                            feature_copy = feature.copy()
                            feature_copy['properties']['state_code'] = state_code
                            feature_copy['properties']['soi_sheet_id'] = sheet_info['soi_sheet_id']
                            feature_copy['properties']['_overlap_info'] = {
                                'soi_sheet_id': sheet_info['soi_sheet_id'],
                                'pdf_name': sheet_info['pdf_name'],
                                'state_name': sheet_info['state_name'],
                                'local_path': sheet_info['local_path'],
                                'source_taluk_file': basename,
                            }
                            all_features.append(feature_copy)
    except Exception as e:
        print(f"    ERROR: {e}")

print(f"\nCollected {len(all_features)} features")

# Create output GeoJSON
output = {
    "type": "FeatureCollection",
    "features": all_features
}

# Write to overlaps.geojson
output_file = 'overlaps.geojson'
with open(output_file, 'w') as f:
    json.dump(output, f, indent=2)

print(f"\n✅ Saved {len(all_features)} features to {output_file}")

# Verification
print("\nVerifying 48E_10_NE...")
count_by_state = defaultdict(int)
for feature in all_features:
    props = feature['properties']
    if props.get('soi_sheet_id') == '48E_10_NE':
        state_code = props.get('state_code')
        count_by_state[state_code] += 1

print("48E_10_NE features by state:")
for state, count in sorted(count_by_state.items()):
    print(f"  {state}: {count}")

print("\n✅ Done!")
