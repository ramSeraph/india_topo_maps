
import json
from pathlib import Path

def annotate_geojson(index_geojson_paths, raw_dir, output_geojson_path):
    """
    Reads a GeoJSON file and a list of sheet numbers, then creates a new
    annotated GeoJSON file with a 'status' property for each feature.

    Args:
        index_geojson_path (str): The path to the input GeoJSON file.
        sheet_nos_path (str): The path to the text file containing sheet numbers.
        output_geojson_path (str): The path to write the annotated GeoJSON file.
    """
    try:

        available_sheets = set()
        for p in raw_dir.glob('*.pdf'):
            available_sheets.add(p.stem)
        unavailable_sheets = set()
        for p in raw_dir.glob('*.unavailable'):
            unavailable_sheets.add(p.stem.replace('.pdf', ''))
        for p in raw_dir.glob('*.html'):
            unavailable_sheets.add(p.stem)

        all_features = []
        for index_geojson_path in index_geojson_paths:
            # Read the available sheet numbers into a set for efficient lookup

            # Read the input GeoJSON file
            with open(index_geojson_path, 'r') as f:
                geojson_data = json.load(f)

            # Annotate each feature with the availability status
            for feature in geojson_data.get('features', []):
                properties = feature.get('properties', {})
                sheet_id = properties.get('id')
                if sheet_id in available_sheets:
                    properties['status'] = 'available'
                elif sheet_id in unavailable_sheets:
                    properties['status'] = 'unavailable'
                else:
                    properties['status'] = 'unprobed'
                feature['properties'] = properties
                all_features.append(feature)

        # Write the annotated GeoJSON data to the output file
        with open(output_geojson_path, 'w') as f:
            data = {
                "type": "FeatureCollection",
                "features": all_features
            }
            json.dump(data, f, indent=2)

    except FileNotFoundError as e:
        print(f"Error: {e}. Please check if the file paths are correct.")
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {index_geojson_path}.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    INDEX_GEOJSON = 'data/index.geojson'
    INDEX_25K_GEOJSON = 'data/index_25k.geojson'
    EXTRA_GEOJSON = 'data/extra.geojson'
    OUTPUT_GEOJSON = 'data/index_annotated.geojson'
    annotate_geojson([INDEX_25K_GEOJSON], Path('data/raw'), OUTPUT_GEOJSON)
