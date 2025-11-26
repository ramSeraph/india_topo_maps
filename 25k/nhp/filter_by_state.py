
import json
from shapely.geometry import shape, MultiPolygon
from shapely.ops import unary_union

# Load the states geometries from the GeoJSONL file
states_geometries = []
with open('data/SOI_States.geojsonl', 'r') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        feature = json.loads(line)
        states_geometries.append(shape(feature['geometry']))

# Create a single unified geometry for all states for efficient intersection checking
india_boundary = unary_union(states_geometries)

# Load the main index GeoJSON file
with open('data/index_25k_full.geojson', 'r') as f:
    index_data = json.load(f)

initial_feature_count = len(index_data['features'])
print(f"Initial number of features: {initial_feature_count}")

# Filter features that intersect with the India boundary
intersecting_features = []
for feature in index_data['features']:
    feature_geom = shape(feature['geometry'])
    if feature_geom.intersects(india_boundary):
        intersecting_features.append(feature)

final_feature_count = len(intersecting_features)
print(f"Number of features after filtering: {final_feature_count}")

# Write the filtered data to a new file with each feature on a separate line
output_filename = 'data/index_25k_filtered.geojson'
with open(output_filename, 'w') as f:
    # Write the header of the FeatureCollection
    f.write('{\n')
    f.write('  "type": "FeatureCollection",\n')
    f.write(f'  "name": "index_25k_filtered",\n')
    # Write CRS if it exists
    if "crs" in index_data:
        crs_str = json.dumps(index_data["crs"])
        f.write(f'  "crs": {crs_str},\n')
    f.write('  "features": [\n')

    # Write each feature on a single line
    for i, feature in enumerate(intersecting_features):
        f.write('    ' + json.dumps(feature, separators=(',', ':')))
        if i < len(intersecting_features) - 1:
            f.write(',\n')
        else:
            f.write('\n')

    # Write the footer
    f.write('  ]\n')
    f.write('}\n')

print(f"Filtered GeoJSON saved to '{output_filename}'")
