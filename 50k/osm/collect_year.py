import json
import re
from pathlib import Path
import csv

def extract_edition_and_year(text):
    """
    Extracts the latest edition and year from a string.
    Handles cases like "1st Edition 2010; 2nd 2019."
    Returns a tuple of (edition, year).
    """
    pairs = []
    # Split by common delimiters to handle multiple edition entries in one line.
    parts = re.split(r'[;.]', text)

    word_map = {
        "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
        "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10
    }

    for part in parts:
        part = part.strip()
        if not part:
            continue

        year_match = re.search(r'\b(19\d{2}|20\d{2})\b', part)
        if not year_match:
            continue
        year = int(year_match.group(1))

        edition = None
        # 1. Look for number with suffix, e.g., "2nd", "3rd"
        edition_match_suffix = re.search(r'\b(\d+)(?:st|nd|rd|th)\b', part, re.IGNORECASE)
        if edition_match_suffix:
            edition = int(edition_match_suffix.group(1))
        
        # 2. Look for word editions if no suffix number found
        if edition is None:
            for word, num in word_map.items():
                if re.search(r'\b' + word + r'\b', part, re.IGNORECASE):
                    edition = num
                    break
        
        # 3. Look for a plain number if "edition" is mentioned
        if edition is None:
            if 'edition' in part.lower():
                # Find numbers that are not the year and look like an edition number
                num_matches = re.findall(r'\b(\d+)\b', part)
                for num_str in num_matches:
                    num = int(num_str)
                    if num != year and 0 < num < 100:  # Plausible edition number
                        edition = num
                        break
        
        if edition:
            pairs.append({'edition': edition, 'year': year})

    if pairs:
        # Sort by year descending, then by edition descending to find the definitive one.
        pairs.sort(key=lambda p: (p['year'], p['edition']), reverse=True)
        return pairs[0]['edition'], pairs[0]['year']

    # Fallback: if no edition-year pairs found, just return the latest year.
    all_years = re.findall(r'\b(19\d{2}|20\d{2})\b', text)
    if all_years:
        return None, max(int(y) for y in all_years)
    
    return None, None

def extract_max_year(text):
    """Extracts the maximum year from a string."""
    all_years = re.findall(r'\b(19\d{2}|20\d{2})\b', text)
    if all_years:
        return max(int(y) for y in all_years)
    return None

# Load overrides
with open('overrides.json') as f:
    overrides_raw = json.load(f)
overrides = {k.replace('.pdf', ''): v for k, v in overrides_raw.items()}

results = []

for p in Path('data/texts/').rglob('*.json'):
    sheet_no = p.stem
    final_year = None
    final_edition = None

    if sheet_no in overrides:
        override_data = overrides[sheet_no]
        final_year = override_data.get('year')
        final_edition = override_data.get('edition')
    else:
        data = json.loads(p.read_text())
        
        edition_texts = []
        copyright_texts = []

        for item in data:
            text = item.get('text', '')
            if not text:
                continue
            
            text_lower = text.lower()

            if 'edition' in text_lower:
                edition_texts.append(text)

            if 'copyright' in text_lower:
                copyright_texts.append(text)

        if edition_texts:
            full_edition_text = " ; ".join(edition_texts)
            edition, year = extract_edition_and_year(full_edition_text)
            if year:
                final_year = year
                final_edition = edition

        # If no year found from edition texts, try copyright texts
        if final_year is None and copyright_texts:
            full_copyright_text = " ".join(copyright_texts)
            final_year = extract_max_year(full_copyright_text)

    results.append({'sheet_no': sheet_no, 'edition': final_edition, 'year': final_year})

# Write CSV
with open('sheet_years.csv', 'w', newline='') as csvfile:
    fieldnames = ['sheet_no', 'edition', 'year']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

    writer.writeheader()
    for result in results:
        edition_val = result['edition'] if result['edition'] is not None else 'NA'
        year_val = result['year'] if result['year'] is not None else 'ND'
        writer.writerow({'sheet_no': result['sheet_no'], 'edition': edition_val, 'year': year_val})

# Write JSON
json_output = {}
for result in results:
    json_output[result['sheet_no']] = {
        'edition': result['edition'] if result['edition'] is not None else 'NA',
        'year': result['year'] if result['year'] is not None else 'ND'
    }

with open('sheet_years.json', 'w') as f:
    json.dump(json_output, f, indent=2)

print("Wrote sheet_years.csv and sheet_years.json")