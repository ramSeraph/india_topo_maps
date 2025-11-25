#!/bin/bash

# Download DD (Daman & Diu) PDFs based on grid geojson
OUTPUT_DIR="data/DD_pdfs"
BASE_URL="https://czmp.ncscm.res.in/files/DD/pdf"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Extract Map_No values from both Daman and Diu files and download PDFs
echo "Extracting Map_No values from Daman and Diu geojson files..."
# Extract numbers from Map_No field (e.g., "DD 03" -> "03")
map_numbers=$(cat <(jq -r '.features[] | .properties.Map_No' "data/layers/DAMAN_OSM_25K_Grid_Taluk.geojson" 2>/dev/null) \
                  <(jq -r '.features[] | .properties.Map_No' "data/layers/Diu_OSM_25K_Grid.geojson" 2>/dev/null) \
              | sed 's/DD //' | sort -n | uniq)

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
