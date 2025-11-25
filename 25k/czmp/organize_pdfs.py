#!/usr/bin/env python3
import json
import os
import shutil
from pathlib import Path
from collections import defaultdict

# Load all sheet maps
sheetmap_dir = Path('data/sheetmaps')
sheet_maps = {}

print("Loading sheet maps...")
for json_file in sheetmap_dir.glob('*.json'):
    state = json_file.stem
    with open(json_file, 'r') as f:
        sheet_maps[state] = json.load(f)
    print(f"  Loaded {state}: {len(sheet_maps[state])} entries")

# Build key to file mapping and check for duplicates
key_to_file = {}
duplicates = defaultdict(list)

print("\nBuilding key mapping and checking for duplicates...")
for state, mappings in sheet_maps.items():
    for key, info in mappings.items():
        local_path = info['local_path']
        if key in key_to_file:
            duplicates[key].append((state, local_path))
            duplicates[key].append(key_to_file[key])
        else:
            key_to_file[key] = (state, local_path)

# Report duplicates
if duplicates:
    print("\n⚠️  DUPLICATE KEYS FOUND:")
    for key, entries in duplicates.items():
        print(f"\n  Key: {key}")
        for state, path in entries:
            print(f"    - {state}: {path}")
    print("\n❌ Cannot proceed due to duplicate keys!")
    exit(1)
else:
    print("✓ No duplicate keys found")

# Check if all source files exist
print("\nChecking source files...")
missing_files = []
for key, (state, local_path) in key_to_file.items():
    if not os.path.exists(local_path):
        missing_files.append((key, local_path))

if missing_files:
    print(f"\n⚠️  WARNING: {len(missing_files)} files missing:")
    for key, path in missing_files[:10]:  # Show first 10
        print(f"  - {key}: {path}")
    if len(missing_files) > 10:
        print(f"  ... and {len(missing_files) - 10} more")
else:
    print("✓ All source files exist")

# Create destination directory
dest_dir = Path('data/raw')
dest_dir.mkdir(exist_ok=True)

# Move files
print(f"\nMoving {len(key_to_file)} files to data/raw/...")
moved = 0
skipped = 0
failed = 0

for key, (state, local_path) in sorted(key_to_file.items()):
    source = Path(local_path)
    dest = dest_dir / key
    
    if not source.exists():
        skipped += 1
        continue
    
    try:
        # Check if destination already exists
        if dest.exists():
            print(f"  ⚠️  Destination exists: {key}")
            skipped += 1
            continue
        
        # Copy file (not move, to preserve originals)
        shutil.copy2(source, dest)
        moved += 1
        
        if moved % 50 == 0:
            print(f"  Progress: {moved}/{len(key_to_file)} files...")
    except Exception as e:
        print(f"  ❌ Failed to copy {key}: {e}")
        failed += 1

print(f"\n✓ Complete!")
print(f"  Moved: {moved}")
print(f"  Skipped: {skipped}")
print(f"  Failed: {failed}")
print(f"  Total files in data/raw/: {len(list(dest_dir.glob('*')))}")
