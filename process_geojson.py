
import json
import re

def process_feature(feature):
    """Processes a single GeoJSON feature."""
    new_feature = feature.copy()
    new_feature['properties'] = {}

    # 1. Update ID from TOPO_SHEET
    description = feature['properties'].get('description', '')
    match = re.search(r'>TOPO_SHEET</td>\s*<td>(.*?)</td>', description)
    if match:
        original_id = match.group(1)
        id_match = re.match(r'(\d+[A-P])(\d+)(NE|SE|SW|NW)', original_id)
        if id_match:
            p1p2, n1, q1 = id_match.groups()
            new_id = f"{p1p2}_{n1}_{q1}"
            new_feature['properties']['id'] = new_id
        else:
            new_feature['properties']['id'] = original_id

    # 2. Transform coordinates
    geometry = new_feature.get('geometry')
    if not geometry:
        return new_feature

    original_coords = []
    if geometry['type'] == 'MultiPolygon':
        if geometry['coordinates'] and geometry['coordinates'][0]:
            original_coords = geometry['coordinates'][0][0]
    elif geometry['type'] == 'Polygon':
        if geometry['coordinates']:
            original_coords = geometry['coordinates'][0]

    if not original_coords:
        return new_feature

    # Drop Z value
    coords_2d = [(c[0], c[1]) for c in original_coords if len(c) >= 2]

    if not coords_2d:
        return new_feature

    # Find bounding box
    min_x = min(c[0] for c in coords_2d)
    max_x = max(c[0] for c in coords_2d)
    min_y = min(c[1] for c in coords_2d)
    max_y = max(c[1] for c in coords_2d)

    # Round to 3 decimal places
    min_x = round(min_x, 3)
    max_x = round(max_x, 3)
    min_y = round(min_y, 3)
    max_y = round(max_y, 3)

    # Anti-clockwise from top-left
    new_coords = [
        [min_x, max_y],  # top-left
        [min_x, min_y],  # bottom-left
        [max_x, min_y],  # bottom-right
        [max_x, max_y],  # top-right
        [min_x, max_y]   # close the loop
    ]

    # Create new geometry
    new_geometry = {
        'type': 'Polygon',
        'coordinates': [new_coords]
    }
    new_feature['geometry'] = new_geometry

    return new_feature

def main():
    """Main function to read, process, and write GeoJSON."""
    input_path = 'data/NHP_3-5m.geojson'
    output_path = 'data/NHP_3-5m_parsed.geojson'

    try:
        with open(input_path, 'r') as f:
            geojson_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading or parsing {input_path}: {e}")
        return

    processed_features = [process_feature(f) for f in geojson_data.get('features', [])]

    try:
        with open(output_path, 'w') as f:
            f.write('{\n')
            f.write('  "type": "FeatureCollection",\n')
            f.write('  "features": [\n')

            for i, feature in enumerate(processed_features):
                f.write('    ' + json.dumps(feature))
                if i < len(processed_features) - 1:
                    f.write(',\n')
                else:
                    f.write('\n')

            f.write('  ]\n')
            f.write('}\n')
        print(f"Successfully created '{output_path}'")
    except IOError as e:
        print(f"Error writing to {output_path}: {e}")

if __name__ == '__main__':
    main()
