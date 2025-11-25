#!/bin/bash

# Download KA PDFs based on grid geojson
GEOJSON_FILE="data/layers/KA_OSM_25K_Grid_1.geojson"
OUTPUT_DIR="data/KA_pdfs"
BASE_URL="https://czmp.ncscm.res.in/files/KA/pdf"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Extract INDEX_NO values and download PDFs
echo "Extracting INDEX_NO values from $GEOJSON_FILE..."
map_numbers=$(jq -r '.features[] | .properties.INDEX_NO' "$GEOJSON_FILE" | sed 's/"//g' | sort -n | uniq)

total=$(echo "$map_numbers" | wc -l)
count=0

echo "Found $total unique map numbers"
echo "Starting downloads..."

for map_no in $map_numbers; do
    count=$((count + 1))
    # Format map number with leading zero if needed (01, 02, etc.)
    formatted_no=$(printf "%02d" $map_no)
    url="${BASE_URL}/${formatted_no}.pdf"
    output_file="${OUTPUT_DIR}/${formatted_no}.pdf"
    
    # Skip if file already exists
    if [ -f "$output_file" ]; then
        echo "[$count/$total] Skipping ${formatted_no}.pdf (already exists)"
        continue
    fi
    
    echo "[$count/$total] Downloading ${formatted_no}.pdf..."
    
    # Download with curl, follow redirects, fail on error
    if curl -f -L -o "$output_file" "$url" 2>/dev/null; then
        echo "  ✓ Success"
    else
        echo "  ✗ Failed (HTTP error or file not found)"
        # Remove empty/failed file
        rm -f "$output_file"
    fi
    
    # Small delay to be nice to the server
    sleep 0.5
done

echo ""
echo "Download complete!"
echo "Downloaded files: $(ls -1 "$OUTPUT_DIR" | wc -l)"
