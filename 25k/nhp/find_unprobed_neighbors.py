import json
import sys
from decimal import Decimal, getcontext

# Set precision for Decimal calculations to avoid floating point inaccuracies
getcontext().prec = 10

def get_geometry_key(feature):
    """Creates a hashable key from a feature's geometry coordinates."""
    try:
        coords = feature['geometry']['coordinates'][0]
        # Use Decimal for precision
        return tuple((Decimal(p[0]), Decimal(p[1])) for p in coords)
    except (KeyError, IndexError, TypeError):
        return None

def get_bbox(feature):
    """Calculates the bounding box from a feature's geometry."""
    try:
        coords = feature['geometry']['coordinates'][0]
        lons = [Decimal(c[0]) for c in coords]
        lats = [Decimal(c[1]) for c in coords]
        return (min(lons), min(lats), max(lons), max(lats))
    except (KeyError, IndexError, TypeError):
        return None

def generate_key_from_bbox(bbox):
    """Generates a geometry ring tuple from a bounding box."""
    x1, y1, x2, y2 = bbox
    # This specific order must match the data in the GeoJSON file.
    # (x_min, y_max), (x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)
    return (
        (x1, y2),
        (x1, y1),
        (x2, y1),
        (x2, y2),
        (x1, y2)
    )

def main():
    """
    Finds and prints 'unprobed' sheets that are neighbors of 'available' sheets.
    """
    filepath = 'data/index_annotated.geojson'
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: '{filepath}' not found.", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{filepath}'.", file=sys.stderr)
        sys.exit(1)

    features = data.get('features', [])
    if not features:
        print("No features found in the GeoJSON file.")
        return

    geom_to_id_map = {}
    id_to_bbox_map = {}
    all_sheets_by_id = {}

    for f in features:
        if 'properties' in f and 'id' in f['properties']:
            sheet_id = f['properties']['id']
            key = get_geometry_key(f)
            bbox = get_bbox(f)
            if key and bbox:
                geom_to_id_map[key] = sheet_id
                id_to_bbox_map[sheet_id] = bbox
                all_sheets_by_id[sheet_id] = f

    available_sheet_ids = [
        id for id, sheet in all_sheets_by_id.items()
        if sheet.get('properties', {}).get('status') == 'available'
    ]

    if not available_sheet_ids:
        print("No sheets with status 'available' found.")
        return

    SHEET_WIDTH = Decimal('0.125')
    SHEET_HEIGHT = Decimal('0.125')
    unprobed_neighbors = set()

    for available_id in available_sheet_ids:
        bbox = id_to_bbox_map.get(available_id)
        if not bbox:
            continue
        
        x1, y1, x2, y2 = bbox

        for dx_multiplier in [-1, 0, 1]:
            for dy_multiplier in [-1, 0, 1]:
                if dx_multiplier == 0 and dy_multiplier == 0:
                    continue

                neighbor_x1 = x1 + (dx_multiplier * SHEET_WIDTH)
                neighbor_y1 = y1 + (dy_multiplier * SHEET_HEIGHT)
                neighbor_x2 = x2 + (dx_multiplier * SHEET_WIDTH)
                neighbor_y2 = y2 + (dy_multiplier * SHEET_HEIGHT)
                
                neighbor_bbox = (neighbor_x1, neighbor_y1, neighbor_x2, neighbor_y2)
                neighbor_key = generate_key_from_bbox(neighbor_bbox)

                neighbor_id = geom_to_id_map.get(neighbor_key)

                if neighbor_id:
                    neighbor_sheet = all_sheets_by_id.get(neighbor_id)
                    if neighbor_sheet and neighbor_sheet.get('properties', {}).get('status') == 'unprobed':
                        unprobed_neighbors.add(neighbor_id)

    for neighbor_id in sorted(list(unprobed_neighbors)):
        print(neighbor_id)

if __name__ == "__main__":
    main()
