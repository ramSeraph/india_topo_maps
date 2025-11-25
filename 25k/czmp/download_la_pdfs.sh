#!/bin/bash

# Download Little Andaman JPGs based on grid geojson
GEOJSON_FILE="data/layers/AN_Little_Andaman_Grid.geojson"
OUTPUT_DIR="data/LA_pdfs"
BASE_URL="https://czmp.ncscm.res.in/files/AN/LA/pdf"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Extract Page_no values and download files
echo "Extracting Page_no values from $GEOJSON_FILE..."
map_numbers=$(jq -r '.features[] | .properties.Page_no' "$GEOJSON_FILE" | sort -n | uniq)

total=$(echo "$map_numbers" | wc -l)
count=0

echo "Found $total unique map numbers"
echo "Starting downloads..."

for map_no in $map_numbers; do
    count=$((count + 1))
    url="${BASE_URL}/LA_${map_no}.jpg"
    output_file="${OUTPUT_DIR}/LA_${map_no}.jpg"
    
    # Skip if file already exists
    if [ -f "$output_file" ]; then
        echo "[$count/$total] Skipping LA_${map_no}.jpg (already exists)"
        continue
    fi
    
    echo "[$count/$total] Downloading LA_${map_no}.jpg..."
    
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
