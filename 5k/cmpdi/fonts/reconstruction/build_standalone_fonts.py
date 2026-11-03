# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf==2.1", "fonttools==4.68.0"]
# ///
"""Build renderer-substitution fonts; leave the source PDF untouched."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from fontTools.ttLib import TTFont
import pymupdf

import build_trial_fonts as trial

ROOT = trial.ROOT
OUT = ROOT/'standalone_fonts'


def contour_bounds(font, char):
    glyph = font['glyf'][font.getBestCmap()[ord(char)]]
    coords, ends, _ = glyph.getCoordinates(font['glyf'])
    boxes, first = [], 0
    for end in ends:
        points = coords[first:end+1]
        boxes.append((min(x for x,y in points), min(y for x,y in points),
                      max(x for x,y in points), max(y for x,y in points)))
        first = end+1
    return boxes


def main():
    OUT.mkdir(exist_ok=True)
    original = trial.SOURCE.read_bytes()
    source = pymupdf.open(stream=original, filetype='pdf')
    spans = source[0].get_texttrace()
    sources = {f[3]:f[0] for f in source[0].get_fonts() if f[3] in ('DGNSymbols','DGNSymbols_new')}
    counts = {name:Counter(chr(c[0]) for s in spans if s['font']==name for c in s['chars']) for name in sources}
    manifest = json.loads((trial.OUT/'manifest.json').read_text())
    previous = next(t for t in manifest['trials'] if t['variant']['id']=='point_dot_well_hollow')
    variant = deepcopy(previous['variant'])
    variant.update(id='open_well_gcp_dot', title='Standalone fonts: provisional open well and GCP filled dot')
    variant['additional_mappings']['H'] = 'G027'
    square = next(s for s in spans if s['font']=='DGNSymbols' and [c[0] for c in s['chars']]==[ord('y')])
    dot = next(s for s in spans if s['font']=='DGNSymbols_new' and [c[0] for c in s['chars']]==[ord('H')])
    assert square['dir']==dot['dir']==(1.0,0.0)
    with TTFont(trial.OUT/previous['fonts']['DGNSymbols']['path']) as font:
        inner = min(contour_bounds(font,'y'),key=lambda b:(b[2]-b[0])*(b[3]-b[1]))
        upm = font['head'].unitsPerEm
    sx, sy = square['chars'][0][2]
    hx, hy = dot['chars'][0][2]
    square_centre = (sx+(inner[0]+inner[2])/2/upm*square['size'],
                     sy-(inner[1]+inner[3])/2/upm*square['size'])
    opening = min(inner[2]-inner[0],inner[3]-inner[1])/upm*square['size']
    diameter = opening/2
    fit = {'width_em':diameter/dot['size'], 'height_em':diameter/dot['size'],
           'centre_em':[(square_centre[0]-hx)/dot['size'],(hy-square_centre[1])/dot['size']],
           'reason':'User requested a filled circular H dot fitting inside the square. Centre on the square opening; diameter is half its inner width.'}
    variant['glyph_fits']['DGNSymbols_new']['H'] = fit
    mapping = {**trial.MAP, **variant['additional_mappings']}
    records = {}
    for name, xref in sources.items():
        used_mapping = {char:mapping[char] for char in counts[name]}
        widths = trial.source_metrics(source,xref)
        path, _, _, glyphs = trial.build_font(name,widths,used_mapping,variant,OUT)
        with TTFont(path) as font:
            # Exact original family and PostScript names allow renderer substitution.
            font['name'].names = []
            names = {1:name,2:'Regular',3:name+'-CEL-reconstruction-v1',4:name,
                     5:'Version 1.000; reconstructed',6:name,16:name,17:'Regular',
                     10:'SOI_cel-derived reconstruction for symbols used in AURANGA_10. See manifest.json for choices and evidence.'}
            for nid,value in names.items():
                font['name'].setName(value,nid,3,1,0x409)
                font['name'].setName(value,nid,1,0,0)
            font.save(path)
        with TTFont(path) as font:
            cmap = font.getBestCmap()
            assert set(map(ord,counts[name])) <= set(cmap)
            assert font['name'].getDebugName(1)==font['name'].getDebugName(6)==name
            assert all(font['hmtx'][cmap[ord(c)]][0]==widths[ord(c)] for c in counts[name])
            if name=='DGNSymbols_new':
                box = contour_bounds(font,'H')[0]
                u = font['head'].unitsPerEm
                actual = (hx+(box[0]+box[2])/2/u*dot['size'],hy-(box[1]+box[3])/2/u*dot['size'])
                assert max(abs(a-b) for a,b in zip(actual,square_centre))<0.003
                assert max(box[2]-box[0],box[3]-box[1])/u*dot['size']<opening
        records[name] = {'file':path.name,'sha256':trial.sha(path.read_bytes()),
                         'family_name':name,'postscript_name':name,
                         'source_occurrences':dict(counts[name]),'glyphs':glyphs}
    assert trial.sha(trial.SOURCE.read_bytes())==trial.sha(original)
    result = {'source_pdf':str(trial.SOURCE),'source_sha256':trial.sha(original),
              'delivery':'Standalone TrueType substitution fonts; source PDF unchanged; fonts not installed system-wide.',
              'coverage':'All DGNSymbols and DGNSymbols_new characters used in AURANGA_10; not a recovery of the complete original font character sets.',
              'base_variant':'point_dot_well_hollow','fonts':records,
              'open_well':{'source_code':'(','feature':'open well','status':'provisionally_selected',
                           'user_statement':'do open well for now','glyph':'G056 / U+00CA, hollow circle',
                           'glyph_choice_basis':'Provisional rendering choice; open well does not establish lined/unlined or original glyph fill.',
                           'imagery_evidence':'../imagery_check/findings.json'},
              'gcp_dot':{'source_code':'H','glyph':'G027 / U+0067, filled circle',
                         'user_statements':['make H a circular dot','filled dot','which fits into the square'],
                         'status':'user_selected_shape','square_opening_pt':opening,'dot_diameter_pt':diameter,
                         'square_centre_pt':square_centre,'fit':fit},
              'unmapped_observed_symbol_characters':[],
              'validation':['Exact family and PostScript names','All observed symbol codes covered',
                            'Original advance widths retained','H centred within square opening',
                            'Source PDF SHA256 unchanged']}
    (OUT/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    manifest['current_standalone_fonts'] = '../standalone_fonts/manifest.json'
    (trial.OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    p = ROOT/'benchmark_well_reference/point_well_candidates.json'
    candidates = json.loads(p.read_text())
    candidates['('].update(status='open_well_provisionally_selected', selected_feature='open well',
                            selected_shape='hollow circle', selected_cel_outline='G056 / U+00CA',
                            decision_source='User: do open well for now. Hollow circle chosen as a provisional rendering.',
                            feature_interpretation='Open well selected provisionally; open tank remains an alternative interpretation of the imagery.',
                            standalone_fonts_local='../standalone_fonts/manifest.json')
    p.write_text(json.dumps(candidates,indent=2)+'\n')
    p = trial.OUT/'review_decisions.json'
    decisions = json.loads(p.read_text())
    for key in ('open_well','gcp_dot'):
        decisions['reviews'].append({'recorded_at':datetime.now(timezone.utc).isoformat(),
                                    'scope':[key], **result[key], 'standalone_manifest':'../standalone_fonts/manifest.json'})
    p.write_text(json.dumps(decisions,indent=2)+'\n')
    print(json.dumps({'fonts':{n:{k:v[k] for k in ('file','family_name','postscript_name','source_occurrences')} for n,v in records.items()},
                      'dot_diameter_pt':diameter,'square_opening_pt':opening,'unmapped_observed_symbols':0},indent=2))


if __name__=='__main__':
    main()
