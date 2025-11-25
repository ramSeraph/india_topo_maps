#!/usr/bin/env python3
"""
Generate coverage.geojson from overlaps.geojson.

For each soi_sheet_id:
1. Identify the two states involved
2. For each state, collect features with non-empty TALUK_NAME
3. Merge those geometries and assign sheet_id as <state_code>-<soi_sheet_id>
4. The remaining features (empty/null TALUK_NAME) get assigned to the other state
5. Merge and assign sheet_id as <other_state_code>-<soi_sheet_id>
"""

import json
from collections import defaultdict
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

def get_taluk_name(props):
    """Get TALUK_NAME from properties, checking multiple possible field names."""
    taluk = props.get('TALUK_NAME') or props.get('Mandal')
    if taluk and isinstance(taluk, str) and taluk.strip():
        return taluk.strip()
    return None

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

print("="*80)
print("GENERATING coverage.geojson from overlaps.geojson")
print("="*80)

# Load sheetmap.json to determine expected states for each overlap
print("\nLoading sheetmap.json...")
with open('data/sheetmap.json', 'r') as f:
    sheetmap = json.load(f)

# Build a lookup: soi_sheet_id -> list of state codes
soi_to_states = defaultdict(set)
for pdf_name, sheet_info in sheetmap.items():
    soi_id = sheet_info.get('soi_sheet_id')
    state_name = sheet_info.get('state_name')
    if soi_id and state_name:
        state_code = STATE_CODE_MAP.get(state_name)
        if state_code:
            soi_to_states[soi_id].add(state_code)

print(f"Built lookup for {len(soi_to_states)} soi_sheet_ids")

# Load overlaps.geojson
print("\nLoading overlaps.geojson...")
with open('overlaps.geojson', 'r') as f:
    data = json.load(f)

print(f"Loaded {len(data['features'])} features")

# Group features by soi_sheet_id
groups_by_soi = defaultdict(list)
for feature in data['features']:
    props = feature['properties']
    soi_sheet_id = props.get('soi_sheet_id')
    if soi_sheet_id:
        groups_by_soi[soi_sheet_id].append(feature)

print(f"Found {len(groups_by_soi)} unique soi_sheet_id values")

# Process each soi_sheet_id
all_merged_features = []

for soi_sheet_id, features in sorted(groups_by_soi.items()):
    print(f"\nProcessing {soi_sheet_id} ({len(features)} features)...")
    
    # Group by state_code
    by_state = defaultdict(list)
    for feature in features:
        state_code = feature['properties'].get('state_code')
        if state_code:
            by_state[state_code].append(feature)
    
    states = list(by_state.keys())
    print(f"  States involved: {states}")
    
    if len(states) < 1:
        print(f"  ⚠️  No states found. Skipping.")
        continue
    elif len(states) == 1:
        print(f"  ⚠️  Only 1 state found (missing data for other state). Processing anyway...")
        state1 = states[0]
        # Get the other state from the soi_sheet_id - check sheetmap to find it
        # For now, we'll use a placeholder that will be obvious
        other_state = "MISSING"
    else:
        state1, state2 = states[0], states[1]
    
    # Process only the first state (state1) to generate 2 features
    state_code = state1
    if len(states) == 1:
        # Need to determine the other state from sheetmap
        expected_states = soi_to_states.get(soi_sheet_id, set())
        remaining_states = expected_states - {state_code}
        if remaining_states:
            other_state = list(remaining_states)[0]
            print(f"    Determined other state from sheetmap: {other_state}")
        else:
            other_state = "UNKNOWN"
            print(f"    ⚠️  Could not determine other state from sheetmap")
    else:
        other_state = state2
    state_features = by_state[state_code]
    
    # Separate features with non-empty TALUK_NAME from those without
    with_taluk = []
    without_taluk = []
    
    for feature in state_features:
        taluk_name = get_taluk_name(feature['properties'])
        if taluk_name:
            with_taluk.append(feature)
        else:
            without_taluk.append(feature)
    
    print(f"  {state_code}: {len(with_taluk)} with TALUK_NAME, {len(without_taluk)} without")
    
    # Merge features WITH TALUK_NAME for this state
    if with_taluk:
        geometries = []
        for feature in with_taluk:
            try:
                geom = shape(feature['geometry'])
                if geom.is_valid:
                    geometries.append(geom)
            except Exception as e:
                print(f"    Warning: Invalid geometry: {e}")
        
        if geometries:
            try:
                if len(geometries) == 1:
                    merged_geom = geometries[0]
                else:
                    merged_geom = unary_union(geometries)
                
                sheet_id = f"{state_code}-{soi_sheet_id}"
                merged_feature = {
                    "type": "Feature",
                    "properties": {
                        "sheet_id": sheet_id
                    },
                    "geometry": mapping(merged_geom)
                }
                all_merged_features.append(merged_feature)
                print(f"    ✓ Created {sheet_id}")
            except Exception as e:
                print(f"    Error merging geometries for {state_code}: {e}")
    
    # Merge features WITHOUT TALUK_NAME for the OTHER state
    if without_taluk:
        geometries = []
        for feature in without_taluk:
            try:
                geom = shape(feature['geometry'])
                if geom.is_valid:
                    geometries.append(geom)
            except Exception as e:
                print(f"    Warning: Invalid geometry: {e}")
        
        if geometries:
            try:
                if len(geometries) == 1:
                    merged_geom = geometries[0]
                else:
                    merged_geom = unary_union(geometries)
                
                sheet_id = f"{other_state}-{soi_sheet_id}"
                merged_feature = {
                    "type": "Feature",
                    "properties": {
                        "sheet_id": sheet_id
                    },
                    "geometry": mapping(merged_geom)
                }
                all_merged_features.append(merged_feature)
                print(f"    ✓ Created {sheet_id} (from {state_code}'s empty TALUK_NAME)")
            except Exception as e:
                print(f"    Error merging geometries for {other_state}: {e}")

print(f"\n{'='*80}")
print(f"Total merged features: {len(all_merged_features)}")
print(f"{'='*80}")

# Create output GeoJSON
output = {
    "type": "FeatureCollection",
    "features": all_merged_features
}

# Write to coverage.geojson
output_file = 'coverage.geojson'
with open(output_file, 'w') as f:
    json.dump(output, f, indent=2)

print(f"\n✅ Saved {len(all_merged_features)} merged features to {output_file}")

# Show sample sheet_ids
print("\nSample sheet_ids created:")
for feature in all_merged_features[:20]:
    print(f"  {feature['properties']['sheet_id']}")

print("\n✅ Done!")
