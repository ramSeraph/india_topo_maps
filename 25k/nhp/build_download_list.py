"""Join the NHP index and catalogue, excluding published and local PDFs."""
import argparse
import csv
from datetime import datetime, timezone
import html
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from nhp_portal import normalize_sheet_no


def kml_documents(data, depth=0):
    if depth > 3:
        raise ValueError('Too many nested index archives')
    stream = io.BytesIO(data)
    if zipfile.is_zipfile(stream):
        with zipfile.ZipFile(stream) as archive:
            for name in archive.namelist():
                if name.lower().endswith(('.kml', '.kmz', '.zip')):
                    yield from kml_documents(archive.read(name), depth + 1)
    else:
        yield ET.fromstring(data)


def read_index(path):
    sheets = set()
    entries = 0
    for document in kml_documents(Path(path).read_bytes()):
        for placemark in document.findall('.//{*}Placemark'):
            entries += 1
            name = placemark.findtext('{*}name', '')
            for field in placemark.findall('.//{*}SimpleData'):
                if field.get('name') == 'TOPO_SHEET':
                    name = field.text or ''
            for field in placemark.findall('.//{*}Data'):
                if field.get('name') == 'TOPO_SHEET':
                    name = field.findtext('{*}value', '')
            description = placemark.findtext('{*}description', '')
            match = re.search(r'<td\b[^>]*>\s*TOPO_SHEET\s*</td>\s*<td\b[^>]*>(.*?)</td>',
                              description, re.IGNORECASE | re.DOTALL)
            if match:
                name = html.unescape(re.sub(r'<[^>]+>', '', match[1]))
            sheets.add(normalize_sheet_no(name))
    if not entries:
        raise ValueError('No index placemarks found')
    return sheets, entries


def read_catalogue(directory):
    directory = Path(directory)
    manifest_file = directory / 'manifest.json'
    if not manifest_file.exists():
        raise ValueError('Refresh the catalogue with scrape_available.py before building the lookup list')
    manifest = json.loads(manifest_file.read_text())
    if not manifest.get('complete'):
        raise ValueError('The catalogue refresh is incomplete; resume it before building the lookup list')
    if manifest.get('filtered'):
        raise ValueError('The catalogue covers selected states only; rerun scrape_available.py without --state')
    locations = {}
    for district in manifest['districts']:
        path = directory / district['file']
        sheets = {normalize_sheet_no(s) for s in path.read_text().splitlines() if s.strip()}
        if len(sheets) != district['sheet_count']:
            raise ValueError(f'Catalogue count mismatch for {path}')
        for sheet in sheets:
            locations.setdefault(sheet, set()).add((district['state'], district['district']))
    return locations, manifest


def read_published(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if 'name' not in (reader.fieldnames or []):
            raise ValueError('Published inventory is missing its name column')
        return {normalize_sheet_no(row['name']) for row in reader
                if row['name'].lower().endswith('.pdf')}


def read_local_pdfs(directory):
    sheets = set()
    for path in Path(directory).glob('*.pdf'):
        with path.open('rb') as stream:
            if stream.read(5) == b'%PDF-':
                sheets.add(normalize_sheet_no(path.name))
    return sheets


def build(index_path, catalogue_dir, published_path, raw_dir, output_dir):
    index, entries = read_index(index_path)
    catalogue, manifest = read_catalogue(catalogue_dir)
    published = read_published(published_path)
    local = read_local_pdfs(raw_dir)
    catalogue_sheets = set(catalogue)
    candidates = index | catalogue_sheets
    available = published | local
    needed = candidates - available
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'sheet_nos_to_lookup.txt').write_text(''.join(s + '\n' for s in sorted(needed)))
    (output_dir / 'sheet_nos_combined.txt').write_text(''.join(s + '\n' for s in sorted(candidates)))
    columns = ['sheet_no', 'in_index', 'in_catalogue', 'published', 'local_pdf',
               'needs_lookup', 'prior_failure_marker', 'state_districts']
    retry_count = 0
    with (output_dir / 'sheet_availability.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for sheet in sorted(candidates):
            prior_failure = any((Path(raw_dir) / (sheet + suffix)).exists()
                                for suffix in ('.html', '.pdf.unavailable', '.unavailable'))
            retry_count += int(prior_failure and sheet in needed)
            writer.writerow({
                'sheet_no': sheet, 'in_index': int(sheet in index),
                'in_catalogue': int(sheet in catalogue), 'published': int(sheet in published),
                'local_pdf': int(sheet in local), 'needs_lookup': int(sheet in needed),
                'prior_failure_marker': int(prior_failure),
                'state_districts': '; '.join(f'{s} / {d}' for s, d in sorted(catalogue.get(sheet, set()))),
            })
    summary = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'index_archive': str(Path(index_path).resolve()), 'index_entries': entries,
        'index_sheets': len(index), 'catalogue_sheets': len(catalogue),
        'catalogue_states': len(manifest['states']), 'catalogue_districts': len(manifest['districts']),
        'catalogue_finished_at': manifest['finished_at'],
        'both_sources': len(index & catalogue_sheets), 'index_only': len(index - catalogue_sheets),
        'catalogue_only': len(catalogue_sheets - index), 'combined_candidates': len(candidates),
        'published_inventory': str(Path(published_path).resolve()), 'published_pdfs': len(published),
        'local_pdfs': len(local), 'already_available_candidates': len(candidates & available),
        'published_outside_sources': len(published - candidates), 'to_lookup': len(needed),
        'prior_failures_to_retry': retry_count,
        'index_only_to_lookup': len((index - catalogue_sheets) & needed),
        'catalogue_only_to_lookup': len((catalogue_sheets - index) & needed),
        'both_sources_to_lookup': len((index & catalogue_sheets) & needed),
    }
    (output_dir / 'sheet_availability_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('index', type=Path, help='SOI index ZIP, KMZ, or KML')
    parser.add_argument('--catalogue-dir', type=Path, default=Path('data/list_current'))
    parser.add_argument('--published', type=Path, default=Path('data/listing_files.csv'))
    parser.add_argument('--raw-dir', type=Path, default=Path('data/raw'))
    parser.add_argument('--output-dir', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(build(args.index, args.catalogue_dir, args.published, args.raw_dir, args.output_dir), indent=2))
