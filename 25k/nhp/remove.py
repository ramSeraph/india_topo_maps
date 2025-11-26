import csv
from pathlib import Path

files = Path('export/gtiffs').glob('*.tif')
files = [ f.name for f in files ]
files = set(files)


with open('listing_files_new.csv', 'w') as of:
    writer = csv.writer(of)
    with open('listing_files.csv', 'r') as f:
        reader = csv.reader(f)
        r1 = next(reader)  # Skip header
        print(r1)
        writer.writerow(r1)
        for r in reader:
            fname = r[0]
            if fname in files:
                continue
            writer.writerow(r)
