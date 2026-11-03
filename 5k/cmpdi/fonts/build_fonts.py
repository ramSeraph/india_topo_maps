# /// script
# requires-python = ">=3.12"
# dependencies = ["fonttools==4.68.0"]
# ///
"""Rebuild the CMPDI replacement fonts from recorded SOI_cel outlines and fits."""
import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(record, families, output, settings):
    upm = settings['units_per_em']
    widths = {int(code): width for code, width in record['advance_widths'].items()}
    glyphs = {'.notdef': TTGlyphPen(None).glyph(), 'space': TTGlyphPen(None).glyph()}
    cmap = {32: 'space'}
    metrics = {'.notdef': (1000, 0), 'space': (widths[32], 0)}
    for char, choice in record['glyphs'].items():
        outline = families[choice['review_id']]
        if outline['id'] != choice['source_outline_sha256']:
            raise ValueError(f'Outline fingerprint mismatch: {char!r}')
        pen = TTGlyphPen(None)
        parse_path(outline['svg_path'], TransformPen(
            Cu2QuPen(pen, max_err=settings['cubic_to_quadratic_max_error'], reverse_direction=False),
            tuple(choice['affine_transform'])))
        glyph = pen.glyph()
        glyph.recalcBounds(None)
        name = f'uni{ord(char):04X}'
        glyphs[name] = glyph
        cmap[ord(char)] = name
        metrics[name] = (widths[ord(char)], getattr(glyph, 'xMin', 0))
    fb = FontBuilder(upm, isTTF=True)
    fb.setupGlyphOrder(list(glyphs))
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=2400, descent=-600)
    fb.setupNameTable({})
    for nid, value in record['name_records'].items():
        fb.font['name'].setName(value, int(nid), 3, 1, 0x409)
        fb.font['name'].setName(value, int(nid), 1, 0, 0)
    fb.setupOS2(sTypoAscender=2400, sTypoDescender=-600, usWinAscent=2400, usWinDescent=600)
    fb.setupPost()
    fb.setupMaxp()
    fb.font.recalcTimestamp = False
    for key, value in record['head_timestamps'].items():
        setattr(fb.font['head'], key, value)
    path = output / record['file']
    fb.save(path)
    validate(path, record)
    return path


def validate(path, record):
    with TTFont(path) as font:
        if font['name'].getDebugName(1) != record['family_name']:
            raise ValueError(f'Incorrect family name in {path}')
        if font['name'].getDebugName(6) != record['postscript_name']:
            raise ValueError(f'Incorrect PostScript name in {path}')
        cmap = font.getBestCmap()
        expected = {int(code) for code in record['advance_widths']}
        if set(cmap) != expected:
            raise ValueError(f'Character coverage mismatch in {path}')
        for char, width in record['advance_widths'].items():
            if font['hmtx'][cmap[int(char)]][0] != width:
                raise ValueError(f'Advance width mismatch in {path}: {char}')
    return sha256(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Directory for rebuilt TTFs')
    parser.add_argument('--check', action='store_true', help='Check committed fonts and byte-for-byte rebuilds in a temporary directory')
    args = parser.parse_args()
    if not args.check and args.output is None:
        parser.error('supply --output or --check')
    manifest = json.loads((ROOT/'manifest.json').read_text())
    families = {f['review_id']: f for f in json.loads((ROOT/'outlines.json').read_text())['families']}
    if args.check:
        with TemporaryDirectory(prefix='cmpdi-fonts-') as tmp:
            for name, record in manifest['fonts'].items():
                if validate(ROOT/record['file'], record) != record['sha256']:
                    raise ValueError(f'Committed {name} differs from its manifest checksum')
                rebuilt = build(record, families, Path(tmp), manifest['build'])
                if sha256(rebuilt) != record['sha256']:
                    raise ValueError(f'Rebuilt {name} differs from the committed font')
                print(f'{name}: coverage, names, widths and byte-for-byte rebuild OK')
    if args.output is not None:
        args.output.mkdir(parents=True, exist_ok=True)
        for record in manifest['fonts'].values():
            path = build(record, families, args.output, manifest['build'])
            print(f'{path}: {sha256(path)}')


if __name__ == '__main__':
    main()
