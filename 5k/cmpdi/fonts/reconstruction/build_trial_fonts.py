# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf==2.1", "fonttools==4.68.0"]
# ///
"""Build experimental CEL-based DGN fonts and embed them in review copies.

Only font-resource names change in the source page content. Unmapped characters
keep their original font resource. Every outline choice and transform is saved.
"""
from collections import Counter
from io import BytesIO
import base64
import hashlib
import html
import json
from pathlib import Path
import re

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont
import pymupdf

from reconstruction_config import ROOT, SOURCE
OUT = ROOT / 'font_trials'
FAMILIES = {f['review_id']: f for f in json.loads((ROOT/'available_symbols.json').read_text())}
UPM = 2000
MAP = {'U':'G020', '$':'G114', ']':'G020', 'O':'G001', 'g':'G027',
       'y':'G046', '%':'G069', 'T':'G075', 'I':'G114', '~':'G090', "'":'G058'}
SCALES = {'U':1.0, 'I':1.0, '~':2.2, ']':1.0}
VARIANTS = [
    {'id':'native', 'title':'CEL native outlines', 'fitted':False},
    {'id':'fitted', 'title':'Centred and scaled trial', 'fitted':True},
    {'id':'H_circle', 'title':'GCP: inner circle hypothesis', 'fitted':True, 'H':'G056'},
    {'id':'H_square', 'title':'GCP: inner square hypothesis', 'fitted':True, 'H':'G046'},
    {'id':'H_triangle', 'title':'GCP: inner triangle hypothesis', 'fitted':True, 'H':'G082'},
    {'id':'percent_blank', 'title':'Station: blank percent hypothesis', 'fitted':True, 'percent_blank':True},
    {'id':'aqueduct_unrotated', 'title':'Aqueduct: unrotated CEL candidate', 'fitted':True, 'aqueduct_unrotated':True},
]
BT = re.compile(rb'\bBT\b.*?\bET\b', re.S)
TF = re.compile(rb'/(DGNSymbols(?:_new)?)\s+[-+.\d]+\s+Tf\b')
TJ = re.compile(rb'\(((?:\\.|[^\\()])*)\)\s*Tj\b', re.S)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_metrics(doc, font_xref):
    value = doc.xref_get_key(font_xref, 'Widths')[1]
    if value.endswith(' R'):
        value = doc.xref_object(int(value.split()[0]))
    widths = [float(v) for v in re.findall(r'[-+]?\d+(?:\.\d+)?', value)]
    first = int(doc.xref_get_key(font_xref, 'FirstChar')[1])
    return {first+i:round(w*UPM/1000) for i,w in enumerate(widths)}


def glyph_for(code, family_id, variant, font_name):
    pen = TTGlyphPen(None)
    if code == '%' and variant.get('percent_blank'):
        return pen.glyph(), {'blank':True, 'reason':'Unverified blank-glyph hypothesis'}
    family = FAMILIES[family_id]
    x0,y0,x1,y1 = family['bounds']
    scale = UPM/family['units_per_em']
    matrix = (scale, 0, 0, scale, 0, 0)
    if variant['fitted']:
        scale *= SCALES.get(code, 2.0)
        if code == 'H':
            scale = .6*UPM/max(x1-x0,y1-y0)
        cx,cy = (x0+x1)/2,(y0+y1)/2
        a,b,c,d = scale,0,0,scale
        if code == ']' and not variant.get('aqueduct_unrotated'):
            a,b,c,d = 0,scale,-scale,0
        matrix = (a,b,c,d,UPM/2-a*cx-c*cy,UPM/2-b*cx-d*cy)
    fit = variant.get('glyph_fits',{}).get(font_name,{}).get(code)
    if fit:
        a = fit['width_em']*UPM/(x1-x0)
        d = fit['height_em']*UPM/(y1-y0)
        cx,cy = fit['centre_em']
        matrix = (a,0,0,d,cx*UPM-a*(x0+x1)/2,cy*UPM-d*(y0+y1)/2)
    parse_path(family['svg_path'], TransformPen(Cu2QuPen(pen, max_err=.25, reverse_direction=False), matrix))
    return pen.glyph(), {
        'review_id':family_id, 'cel_codes':family['codes'], 'source_outline_sha256':family['id'],
        'source_fonts':family['sources'], 'affine_transform':list(matrix),
        'status':'visual_trial_only', 'fit':fit,
    }


def build_font(font_name, widths, mapping, variant, folder):
    psname = 'CELTrial'+('New' if font_name.endswith('_new') else 'DGN')+'-'+variant['id'].replace('_','')
    glyphs = {'.notdef':TTGlyphPen(None).glyph(), 'space':TTGlyphPen(None).glyph()}
    cmap = {32:'space'}
    metrics = {'.notdef':(1000,0), 'space':(widths[32],0)}
    evidence = {}
    for code,fid in mapping.items():
        name = f'uni{ord(code):04X}'
        glyph,evidence[code] = glyph_for(code,fid,variant,font_name)
        glyphs[name] = glyph
        cmap[ord(code)] = name
        glyph.recalcBounds(None)
        metrics[name] = (widths[ord(code)],getattr(glyph,'xMin',0))
    fb = FontBuilder(UPM,isTTF=True)
    fb.setupGlyphOrder(list(glyphs))
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=2400,descent=-600)
    fb.setupNameTable({'familyName':psname,'styleName':'Regular','uniqueFontIdentifier':psname+'-v1',
                      'fullName':psname,'psName':psname,'version':'Version 0.1 visual trial',
                      'description':'Experimental SOI_cel-derived reconstruction; glyph identities and placement unverified.'})
    fb.setupOS2(sTypoAscender=2400,sTypoDescender=-600,usWinAscent=2400,usWinDescent=600)
    fb.setupPost()
    fb.setupMaxp()
    path = folder/(font_name+'.ttf')
    fb.save(path)
    with TTFont(path) as font:
        assert set(cmap) <= set(font.getBestCmap())
        for code,name in cmap.items():
            assert font['hmtx'][name][0] == widths[code]
        head = font['head']
        bbox = [v*1000/UPM for v in (head.xMin,head.yMin,head.xMax,head.yMax)]
    return path,psname,bbox,evidence


def embed_copy(original, variant, font_sources, metrics):
    folder = OUT/variant['id']
    folder.mkdir(parents=True,exist_ok=True)
    mapping = dict(MAP)
    mapping.update(variant.get('additional_mappings',{}))
    if variant.get('H'):
        mapping['H'] = variant['H']
    doc = pymupdf.open(stream=original,filetype='pdf')
    page = doc[0]
    resource_kind,resource_value = doc.xref_get_key(page.xref,'Resources')
    assert resource_kind == 'xref'
    resources = int(resource_value.split()[0])
    font_kind,font_value = doc.xref_get_key(resources,'Font')
    font_resource_xref = int(font_value.split()[0]) if font_kind=='xref' else resources
    font_resource_prefix = '' if font_kind=='xref' else 'Font/'
    font_evidence = {}
    names = {}
    for name,xref in font_sources.items():
        path,psname,bbox,evidence = build_font(name,metrics[name],mapping,variant,folder)
        stream_xref = doc.get_new_xref()
        doc.update_object(stream_xref,'<<>>')
        doc.update_stream(stream_xref,path.read_bytes(),compress=True)
        doc.xref_set_key(stream_xref,'Length1',str(path.stat().st_size))
        descriptor = doc.get_new_xref()
        doc.update_object(descriptor, f'<< /Type /FontDescriptor /FontName /{psname} /Flags 32 '
            f'/FontBBox [{" ".join(str(v) for v in bbox)}] /ItalicAngle 0 /Ascent 1200 '
            f'/Descent -300 /CapHeight 1000 /StemV 80 /FontFile2 {stream_xref} 0 R >>')
        newfont = doc.get_new_xref()
        doc.update_object(newfont,doc.xref_object(xref))
        doc.xref_set_key(newfont,'BaseFont','/'+psname)
        doc.xref_set_key(newfont,'FontDescriptor',f'{descriptor} 0 R')
        resource_name = 'CELTrialNew' if name.endswith('_new') else 'CELTrialDGN'
        doc.xref_set_key(font_resource_xref,font_resource_prefix+resource_name,f'{newfont} 0 R')
        names[name] = resource_name
        font_evidence[name] = {'path':str(path.relative_to(OUT)), 'sha256':sha(path.read_bytes()),
                               'postscript_name':psname, 'glyphs':evidence}
    changed,unchanged = Counter(),Counter()
    for content_xref in page.get_contents():
        before = doc.xref_stream(content_xref)
        def replace_block(match):
            block = match.group()
            font = TF.search(block)
            if not font:
                return block
            name = font[1].decode()
            texts = TJ.findall(block)
            assert len(texts)==1, block
            raw = re.sub(rb'\\([0-7]{1,3}|.)',
                         lambda m:bytes([int(m[1],8)]) if m[1][:1] in b'01234567' else m[1],texts[0])
            assert len(raw)==1, block
            code = raw.decode('ascii')
            if code not in mapping:
                unchanged[name+':'+code] += 1
                return block
            changed[name+':'+code] += 1
            return block[:font.start(1)]+names[name].encode()+block[font.end(1):]
        after = BT.sub(replace_block,before)
        restored = after
        for name,newname in names.items():
            restored = restored.replace(('/'+newname+' ').encode(),('/'+name+' ').encode())
        assert restored==before, 'A source command other than font resource selection changed'
        doc.update_stream(content_xref,after,compress=True)
    path = folder/f'AURANGA_10_trial_{variant["id"]}.pdf'
    doc.save(path,garbage=0,deflate=True)
    doc.close()
    with pymupdf.open(path) as check:
        assert check[0].rect==pymupdf.open(stream=original,filetype='pdf')[0].rect
        embedded = [f for f in check[0].get_fonts() if f[3].startswith('CELTrial')]
        assert len(embedded)==2
        assert all(check.extract_font(f[0])[3] for f in embedded)
        actual = Counter()
        for span in check[0].get_texttrace():
            for ch in span['chars']:
                if span['font'].startswith('CELTrial'):
                    actual[chr(ch[0])] += 1
        expected = Counter()
        for key,count in changed.items():expected[key.split(':',1)[1]] += count
        assert actual==expected,(actual,expected)
    return {'variant':variant,'pdf':str(path.relative_to(OUT)), 'fonts':font_evidence,
            'replaced_occurrences':dict(changed),'preserved_unmapped_occurrences':dict(unchanged)}


def main():
    OUT.mkdir(exist_ok=True)
    original=SOURCE.read_bytes()
    with pymupdf.open(stream=original,filetype='pdf') as d:
        font_sources={item[3]:item[0] for item in d[0].get_fonts() if item[3] in ('DGNSymbols','DGNSymbols_new')}
        assert len(font_sources)==2
        metrics={name:source_metrics(d,xref) for name,xref in font_sources.items()}
        expected=Counter(s['font']+':'+chr(c[0]) for s in d[0].get_texttrace()
                         if s['font'] in font_sources for c in s['chars'])
    trials=[]
    for variant in VARIANTS:
        entry=embed_copy(original,variant,font_sources,metrics)
        assert Counter(entry['replaced_occurrences'])+Counter(entry['preserved_unmapped_occurrences'])==expected
        trials.append(entry)
        print(variant['id'],sum(entry['replaced_occurrences'].values()),'substitutions',flush=True)
    manifest={'source_pdf':str(SOURCE),'source_sha256':sha(original),'scope':'Experimental missing-DGN-font reconstruction',
              'source_content_changes':'Font resource names only; unmapped text retains original resources.',
              'fitted_assumptions':{'centre_em':[.5,.5],'default_cel_scale':2,'scale_overrides':SCALES,
                                   'aqueduct_rotation_degrees':90,'H_comparison_max_extent_em':.6},
              'trials':trials}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    assert sha(SOURCE.read_bytes())==manifest['source_sha256']
    print('Wrote',OUT/'manifest.json')


if __name__=='__main__':main()
