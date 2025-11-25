#!/usr/bin/env python3
import json
import os
import csv
from pathlib import Path

# Define attributes
plan_year_map = {
    'GA': 2011,
    'GJ': 2011,
    'TN': 2011,
    'AP': 2011,
    'WB': 2011
}

# Load state codes
state_names = {}
with open('state_codes.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        state_names[row['code']] = row['state_name']

# Load and merge all sheetmaps
merged = {}
sheetmaps_dir = Path('data/sheetmaps')

for json_file in sorted(sheetmaps_dir.glob('*.json')):
    state_code = json_file.stem
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    # Determine map_type
    map_type = 'Draft' if state_code == 'WB' else 'Approved'
    
    # Add attributes to each entry
    for key, value in data.items():
        value['map_type'] = map_type
        if state_code in plan_year_map:
            value['plan_year'] = plan_year_map[state_code]
        else:
            value['plan_year'] = 2019
        if state_code in state_names:
            value['state_name'] = state_names[state_code]
        merged[key] = value

# Write merged data
output_path = Path('data/sheetmap.json')
with open(output_path, 'w') as f:
    json.dump(merged, f, indent=2)

print(f"Merged {len(merged)} entries from {len(list(sheetmaps_dir.glob('*.json')))} files")
print(f"Output written to {output_path}")
