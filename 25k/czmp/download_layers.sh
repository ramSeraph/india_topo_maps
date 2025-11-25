#!/bin/bash

# Base URL from steps.sh
BASE_URL="https://gisportal.ncscm.res.in/server/rest/services/CZMP_STATES/INDIA_CZMPPDF/MapServer"

# Create layers directory if it doesn't exist
mkdir -p data/layers

# Parse layers.json and download each layer
jq -r '.layers[] | "\(.id)|\(.name)"' data/layers.json | while IFS='|' read -r layer_id layer_name; do
    echo "Downloading layer: $layer_name (ID: $layer_id)"
    
    # Construct the full URL with layer ID
    LAYER_URL="${BASE_URL}/${layer_id}"
    
    # Output file path
    OUTPUT_FILE="data/layers/${layer_name}.geojson"

    if [[ -f "$OUTPUT_FILE" ]]; then
        echo "File already exists: $OUTPUT_FILE. Skipping download."
        echo "---"
        continue
    fi
    
    # Download using esri2geojson via uvx
    uvx --from esridump esri2geojson "$LAYER_URL" "$OUTPUT_FILE"
    
    echo "Saved to: $OUTPUT_FILE"
    echo "---"
done

echo "All layers downloaded!"
