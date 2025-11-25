#!/bin/bash

# Download Great Nicobar PDFs based on grid geojson
GEOJSON_FILE="data/layers/AN_Great_Nicobar_Grid.geojson"
OUTPUT_DIR="data/GN_pdfs"
BASE_URL="https://czmp.ncscm.res.in/files/AN/GN/pdf"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Extract Page_No values and download PDFs
echo "Extracting Page_No values from $GEOJSON_FILE..."
map_numbers=$(jq -r '.features[] | .properties.Page_No' "$GEOJSON_FILE" | sort -n | uniq)

total=$(echo "$map_numbers" | wc -l)
count=0

echo "Found $total unique map numbers"
echo "Starting downloads..."

for map_no in $map_numbers; do
    count=$((count + 1))
    url="${BASE_URL}/GN_${map_no}.pdf"
    output_file="${OUTPUT_DIR}/GN_${map_no}.pdf"
    
    # Skip if file already exists
    if [ -f "$output_file" ]; then
        echo "[$count/$total] Skipping GN_${map_no}.pdf (already exists)"
        continue
    fi
    
    echo "[$count/$total] Downloading GN_${map_no}.pdf..."
    
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
