import json
from collections import defaultdict

# Load the sheetmap.json file
with open('data/sheetmap.json', 'r') as f:
    data = json.load(f)

# Group sheets by soi_sheet_id
sheet_groups = defaultdict(list)
for pdf_name, sheet_info in data.items():
    soi_sheet = sheet_info.get('soi_sheet_id')
    if soi_sheet:
        sheet_groups[soi_sheet].append((pdf_name, sheet_info))

# Find sheets with overlaps (same soi_sheet_id)
overlaps = {k: v for k, v in sheet_groups.items() if len(v) > 1}

print(f"Found {len(overlaps)} soi_sheet_id values with overlaps:")
print(f"Total overlapping sheets: {sum(len(v) for v in overlaps.values())}\n")

# Print details of each overlap
for soi_sheet, sheets in sorted(overlaps.items()):
    print(f"\n{'='*80}")
    print(f"SOI Sheet ID: {soi_sheet} ({len(sheets)} sheets)")
    print(f"{'='*80}")
    for i, (pdf_name, sheet_info) in enumerate(sheets, 1):
        print(f"\n  Sheet {i}:")
        print(f"    PDF Name: {pdf_name}")
        print(f"    State: {sheet_info.get('state_name', 'N/A')}")
        print(f"    Local Path: {sheet_info.get('local_path', 'N/A')}")
        print(f"    OSM Sheet ID: {sheet_info.get('osm_sheet_id', 'N/A')}")
        print(f"    State Series No: {sheet_info.get('state_series_no', 'N/A')}")
        print(f"    Map Type: {sheet_info.get('map_type', 'N/A')}")
        print(f"    Plan Year: {sheet_info.get('plan_year', 'N/A')}")
