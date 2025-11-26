
import json
import os

def create_25k_index():
    source_file = 'data/index_50k.geojson'
    target_file = 'data/index_25k_full.geojson'

    with open(source_file) as f:
        data_50k = json.load(f)

    features_25k = []
    for feature_50k in data_50k['features']:
        props_50k = feature_50k['properties']
        geom_50k = feature_50k['geometry']

        if geom_50k['type'] != 'Polygon' or not geom_50k['coordinates']:
            continue

        sheet_no_50k = props_50k.get('id')
        if not sheet_no_50k:
            continue
        
        sheet_no_50k = sheet_no_50k.replace('/', '_')

        coords = geom_50k['coordinates'][0]
        
        min_lon = min(p[0] for p in coords)
        max_lon = max(p[0] for p in coords)
        min_lat = min(p[1] for p in coords)
        max_lat = max(p[1] for p in coords)

        mid_lon = (min_lon + max_lon) / 2
        mid_lat = (min_lat + max_lat) / 2

        # Create 4 new features for the 4 quadrants
        
        # NW
        features_25k.append({
            "type": "Feature",
            "properties": {"id": f"{sheet_no_50k}_NW"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[min_lon, max_lat], [min_lon, mid_lat], [mid_lon, mid_lat], [mid_lon, max_lat], [min_lon, max_lat]]]
            }
        })
        
        # NE
        features_25k.append({
            "type": "Feature",
            "properties": {"id": f"{sheet_no_50k}_NE"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[mid_lon, max_lat], [mid_lon, mid_lat], [max_lon, mid_lat], [max_lon, max_lat], [mid_lon, max_lat]]]
            }
        })
        
        # SW
        features_25k.append({
            "type": "Feature",
            "properties": {"id": f"{sheet_no_50k}_SW"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[min_lon, mid_lat], [min_lon, min_lat], [mid_lon, min_lat], [mid_lon, mid_lat], [min_lon, mid_lat]]]
            }
        })
        
        # SE
        features_25k.append({
            "type": "Feature",
            "properties": {"id": f"{sheet_no_50k}_SE"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[mid_lon, mid_lat], [mid_lon, min_lat], [max_lon, min_lat], [max_lon, mid_lat], [mid_lon, mid_lat]]]
            }
        })

    geojson_25k = {
        "type": "FeatureCollection",
        "name": "index_25k_full",
        "crs": data_50k.get("crs", {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}),
        "features": features_25k
    }

    with open(target_file, 'w') as f:
        json.dump(geojson_25k, f, indent=2)

if __name__ == '__main__':
    create_25k_index()
