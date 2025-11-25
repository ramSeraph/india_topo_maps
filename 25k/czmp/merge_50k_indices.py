#!/usr/bin/env python3
import json

print("Loading index files...")

# Load both index files
with open('index_50k.geojson', 'r') as f:
    index_50k = json.load(f)

with open('index_50k_extra.geojson', 'r') as f:
    index_50k_extra = json.load(f)

print(f"  index_50k.geojson: {len(index_50k['features'])} features")
print(f"  index_50k_extra.geojson: {len(index_50k_extra['features'])} features")

# Merge features
merged = {
    "type": "FeatureCollection",
    "features": index_50k['features'] + index_50k_extra['features']
}

print(f"\nMerged total: {len(merged['features'])} features")

# Check for duplicate SOI sheet IDs
soi_ids = {}
duplicates = []
for feature in merged['features']:
    soi_id = feature['properties']['id']
    if soi_id in soi_ids:
        duplicates.append(soi_id)
    else:
        soi_ids[soi_id] = True

if duplicates:
    print(f"\n⚠️  Found {len(duplicates)} duplicate SOI sheet IDs:")
    for dup in duplicates[:10]:
        print(f"  - {dup}")
    if len(duplicates) > 10:
        print(f"  ... and {len(duplicates) - 10} more")
else:
    print("✓ No duplicate SOI sheet IDs found")

# Save merged file
with open('index_50k_full.geojson', 'w') as f:
    json.dump(merged, f, indent=2)

print(f"\n✓ Saved to index_50k_full.geojson")
