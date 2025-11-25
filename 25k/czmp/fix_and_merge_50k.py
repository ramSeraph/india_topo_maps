#!/usr/bin/env python3
import json

print("Loading index_50k.geojson...")
with open('index_50k.geojson', 'r') as f:
    index_50k = json.load(f)

print(f"  index_50k.geojson: {len(index_50k['features'])} features")

# Fix index_50k_extra.geojson - line 38 has ], should be just ]
# and line 39 starts a new feature but it's outside the features array
print("\nFixing and loading index_50k_extra.geojson...")
with open('index_50k_extra.geojson', 'r') as f:
    content = f.read()

# Replace the problematic pattern: close array, start new object
# Change:  }
#   ],
#   {
# To:     },
#   {
content = content.replace('  }\n  ],\n  {', '  },\n  {')

index_50k_extra = json.loads(content)
print(f"  index_50k_extra.geojson: {len(index_50k_extra['features'])} features")

# Merge features
merged = {
    "type": "FeatureCollection",
    "features": index_50k['features'] + index_50k_extra['features']
}

print(f"\nMerged total: {len(merged['features'])} features")

# Check for duplicates
soi_ids = {}
duplicates = []
for feature in merged['features']:
    soi_id = feature['properties']['id']
    if soi_id in soi_ids:
        duplicates.append(soi_id)
    else:
        soi_ids[soi_id] = True

if duplicates:
    print(f"\n⚠️  Found {len(duplicates)} duplicate SOI IDs")
else:
    print("✓ No duplicate SOI IDs found")

# Save merged file
with open('index_50k_full.geojson', 'w') as f:
    json.dump(merged, f)

print(f"\n✓ Saved to index_50k_full.geojson")
