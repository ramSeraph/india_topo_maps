#!/bin/bash

PDF_FILE="data/misc/WB Draft CZMP 2019 for North 24 Parganas.pdf"
OUTPUT_DIR="data/WB_pdfs"

# WB sheet numbers in order from page 1 to 11
SHEET_NUMBERS=(60 61 64 65 66 67 68 69 70 71 72)

echo "Extracting WB sheets from PDF..."

for i in {0..10}; do
    page=$((i + 1))
    sheet_no=${SHEET_NUMBERS[$i]}
    output_file="${OUTPUT_DIR}/${sheet_no}.jpg"
    
    echo "[$((i+1))/11] Extracting page $page as ${sheet_no}.jpg..."
    
    # Extract page as JPG using pdftoppm
    pdftoppm -jpeg -f $page -l $page -r 300 "$PDF_FILE" "${OUTPUT_DIR}/temp_${sheet_no}" >/dev/null 2>&1
    
    # Rename the output file (pdftoppm adds -1 suffix)
    mv "${OUTPUT_DIR}/temp_${sheet_no}-1.jpg" "$output_file" 2>/dev/null
    
    if [ -f "$output_file" ]; then
        echo "  ✓ Created ${sheet_no}.jpg"
    else
        echo "  ✗ Failed to create ${sheet_no}.jpg"
    fi
done

echo ""
echo "Extraction complete!"
echo "Created files: $(ls -1 ${OUTPUT_DIR}/*.jpg 2>/dev/null | wc -l)"
