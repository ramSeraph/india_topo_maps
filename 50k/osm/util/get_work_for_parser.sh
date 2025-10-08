#!/bin/bash

gh release download 50k-osm-orig -p listing_files.csv -O pdfs_listing.csv --clobber
gh release download 50k-osm-georef -p listing_files.csv -O tiffs_listing.csv --clobber

comm -23 <(cat pdfs_listing.csv| cut -d"," -f1 | cut -d"." -f1 | sort) <(cat tiffs_listing.csv | cut -d"," -f1 | cut -d"." -f1 | sort) | cut -f1 | sed '/^[[:space:]]*$/d' > temp.txt

comm -23 <(cat temp.txt | sort) <(cat bad_files.txt | sort) | cut -f1 | sed '/^[[:space:]]*$/d' > $1

rm pdfs_listing.csv tiffs_listing.csv temp.txt
