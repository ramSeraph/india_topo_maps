
import json
import csv
import sys

def main():
    # Read sheet years into a dictionary
    sheet_years = {}
    with open('sheet_years.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sheet_years[row['sheet_no']] = {
                'edition': row['edition'],
                'year': row['year']
            }

    # Read bounds.geojson from stdin
    bounds_data = json.load(sys.stdin)

    # Update features with year and edition
    for feature in bounds_data['features']:
        sheet_no = feature['properties']['id']
        if sheet_no in sheet_years:
            feature['properties']['edition'] = sheet_years[sheet_no]['edition']
            feature['properties']['year'] = sheet_years[sheet_no]['year']

    # Write the updated geojson to stdout
    sys.stdout.write('{ "type": "FeatureCollection", "features": [\n')
    for i, feature in enumerate(bounds_data['features']):
        json.dump(feature, sys.stdout)
        if i < len(bounds_data['features']) - 1:
            sys.stdout.write(',\n')
    sys.stdout.write('\n]}')

if __name__ == '__main__':
    main()
