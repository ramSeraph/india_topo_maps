# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf==2.1", "fonttools==4.68.0"]
# ///
"""Collect all nonempty embedded glyph outlines, including unused cmap entries.

This is a coverage aid for comparing symbol fonts, not a replacement font.
Blank glyphs in PDF subsets are not evidence that the original font lacks them.
"""
import argparse
from collections import defaultdict
import csv
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import time

from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
import pymupdf


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    temporary.replace(path)


def collect(paths, output, font_filter):
    output.mkdir(parents=True, exist_ok=True)
    families, font_cache, errors, codepoints = {}, {}, [], set()
    font_sources = defaultdict(list)
    processed = source_count = 0
    started = time.monotonic()

    def save(done=False):
        for family in families.values():
            family['codes'] = sorted(family['codes'])
            family['glyph_names'] = sorted(family['glyph_names'])
        summary = {
            'status': 'complete' if done else 'running', 'processed': processed,
            'total': len(paths), 'pdfs_with_font': source_count,
            'distinct_embedded_fonts': len(font_cache), 'outline_families': len(families),
            'cmap_codepoints': len(codepoints),
            'codepoints_with_outlines': len({c for f in families.values() for c in f['codes']}),
            'errors': errors, 'elapsed_seconds': round(time.monotonic()-started, 2),
        }
        atomic_json(output/'outlines.json', {
            'summary': summary, 'font_filter': font_filter,
            'qualification': 'Union of nonempty embedded outlines. Missing outlines in subsets '
                             'do not establish absence from the original complete font. '
                             'Shape candidates do not establish exact symbol equivalence.',
            'families': list(families.values()),
        })
        atomic_json(output/'status.json', summary)
        print(json.dumps(summary), flush=True)
        for family in families.values():
            family['codes'] = set(family['codes'])
            family['glyph_names'] = set(family['glyph_names'])

    for path in paths:
        try:
            with pymupdf.open(path) as doc:
                if not len(doc):
                    raise ValueError('PDF has no pages')
                references = {item[0]: item for page in doc for item in page.get_fonts(full=True)
                              if font_filter.casefold() in item[3].casefold()}
                source_count += bool(references)
                for xref, item in references.items():
                    _, _, _, data = doc.extract_font(xref)
                    if not data:
                        errors.append({'file': path.name, 'xref': xref, 'error': 'Font not embedded'})
                        continue
                    font_hash = hashlib.sha256(data).hexdigest()
                    source = {'sheet': path.stem, 'font_xref': xref, 'font_sha256': font_hash}
                    if font_hash in font_cache:
                        descriptions = font_cache[font_hash]
                    else:
                        descriptions = []
                        with TTFont(BytesIO(data)) as font:
                            units = font['head'].unitsPerEm
                            glyphs = font.getGlyphSet()
                            names_to_codes = defaultdict(set)
                            for table in font['cmap'].tables:
                                if table.isUnicode():
                                    for code, name in table.cmap.items():
                                        names_to_codes[name].add(code)
                                        codepoints.add(code)
                            for name in glyphs:
                                recording = DecomposingRecordingPen(glyphs)
                                glyphs[name].draw(recording)
                                bounds = BoundsPen(glyphs)
                                glyphs[name].draw(bounds)
                                if bounds.bounds is None:
                                    continue
                                normalized = [[operation, [None if p is None else
                                    [round(v/units, 9) for v in p] for p in points]]
                                    for operation, points in recording.value]
                                fingerprint = hashlib.sha256(json.dumps(normalized, separators=(',', ':')).encode()).hexdigest()
                                if fingerprint not in families:
                                    svg = SVGPathPen(glyphs)
                                    glyphs[name].draw(svg)
                                    families[fingerprint] = {
                                        'id': fingerprint, 'units_per_em': units,
                                        'bounds': bounds.bounds, 'svg_path': svg.getCommands(),
                                        'codes': set(), 'glyph_names': set(), 'sources': [],
                                        'font_occurrences': 0,
                                    }
                                descriptions.append((fingerprint, name, sorted(names_to_codes[name])))
                        font_cache[font_hash] = descriptions
                    for fingerprint, name, codes in descriptions:
                        family = families[fingerprint]
                        family['codes'].update(codes)
                        family['glyph_names'].add(name)
                        family['font_occurrences'] += 1
                        if len(family['sources']) < 5 and source not in family['sources']:
                            family['sources'].append(source)
        except Exception as exc:
            errors.append({'file': path.name, 'error': f'{type(exc).__name__}: {exc}'})
        processed += 1
        if processed % 100 == 0:
            save()
    save(done=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', nargs='*', type=Path)
    parser.add_argument('--listing', type=Path)
    parser.add_argument('--raw', type=Path, default=Path('data/raw'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font', default='SOI_cel')
    args = parser.parse_args()
    if args.listing:
        with args.listing.open() as stream:
            paths = [args.raw/r['name'] for r in csv.DictReader(stream)]
    else:
        paths = args.pdf or sorted(args.raw.glob('*.pdf'))
    os.nice(10)
    collect(paths, args.output, args.font)


if __name__ == '__main__':
    main()
