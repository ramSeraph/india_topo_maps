# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf==2.1", "fonttools==4.68.0", "pillow"]
# ///
"""Reference-guided, font-only refinement; retains the first trial for comparison."""
import base64
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
from fontTools.ttLib import TTFont
import pymupdf
import build_trial_fonts as trial

ROOT=trial.ROOT
OUT=trial.OUT
coverage=json.loads((ROOT/'coverage.json').read_text())


def observation(font,code):
    return next(o for r in coverage['rows'] if r['character']==code for o in r['observations']
                if o['font']==font)


def fit(width,height,cx,cy,reason):
    return {'width_em':width,'height_em':height,'centre_em':[cx,cy],'reason':reason}


def image(path):
    return '<img src="data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()+'">'


def main():
    source=trial.SOURCE.read_bytes()
    original=pymupdf.open(stream=source,filetype='pdf')
    # Both legends use approximately six-point row labels. Normalize NHP 6 pt
    # lettering to AURANGA's measured 5.93998 pt lettering for this visual trial.
    label_ratio=5.9399800300598145/6.000410079956055
    cel_size=12.00082015991211*label_ratio
    tank_width=620/2000*cel_size
    body_height=415/2000*cel_size
    leg_height=420/2000*cel_size
    leg_width=75/2000*cel_size
    # The supplied bitmap places the leg bottoms near the row's text baseline.
    tank_bottom=584.0205078125
    body_bottom=tank_bottom-leg_height
    body_centre_y=body_bottom-body_height/2
    leg_centre_y=tank_bottom-leg_height/2
    body=observation('DGNSymbols_new','~')
    leg=observation('DGNSymbols_new','I')
    tick=observation('DGNSymbols_new','$')
    # NHP SOI_BDR summation's last contour is the distance tick: 38 units wide,
    # 122 units tall at 26.161779 pt / 2000 em. Only thicken the existing trial.
    tick_width=38/2000*26.161779403686523*label_ratio
    # NHP braceleft combines railway + frame. Frame exterior x=673..1023;
    # it hangs from y=578 (track bottom) to y=395. Red franc is separate.
    bdr_size=25.441730499267578*label_ratio
    frame_width=350/2000*bdr_size
    frame_visible_height=183/2000*bdr_size
    frame_height=frame_visible_height/(1-41/447)
    track_bottom=432.10589599609375
    frame_bottom=track_bottom+frame_visible_height
    red_width=137/2000*bdr_size
    red_height=150/2000*bdr_size
    red_top=track_bottom-12/2000*bdr_size
    frame=observation('DGNSymbols_new','y')
    red=observation('DGNSymbols','T')
    power=json.loads((ROOT/'powerline_alignment_evidence.json').read_text())
    hollow=[p for p in power['paths'] if p['fill']==[1.0,1.0,1.0]]
    hollow_y=sum((p['rect'][1]+p['rect'][3])/2 for p in hollow)/len(hollow)
    dot=power['spans'][0]
    dot_centre_y=(dot['origin'][0][1]-hollow_y)/dot['size']
    fits={
        'DGNSymbols':{
            'g':fit(.197,.197,.5,dot_centre_y,
                    'Match the vertical centres of the neighbouring original hollow circles.'),
            'T':fit(red_width/red['font_size_pt'],red_height/red['font_size_pt'],.5,
                    (red['origin_pt'][1]-(red_top+red_height/2))/red['font_size_pt'],
                    'NHP red station block proportions and offset below the original railway.'),
        },
        'DGNSymbols_new':{
            '$':fit(1.34,tick_width/tick['font_size_pt'],.5,.5,
                    'Thicken the native horizontal bar to the NHP tick width; retain PDF rotation.'),
            '~':fit(tank_width/body['font_size_pt'],body_height/body['font_size_pt'],.5,
                    (body['origin_pt'][1]-body_centre_y)/body['font_size_pt'],
                    'NHP whole-tank body proportions; baseline placement guided by supplied legend.'),
            'I':fit(leg_height/leg['font_size_pt'],leg_width/leg['font_size_pt'],
                    (leg['origin_pt'][1]-leg_centre_y)/leg['font_size_pt'],.5,
                    'NHP leg length/thickness; both identical I occurrences retain their fixed spacing.'),
            'y':fit(frame_width/frame['font_size_pt'],frame_height/frame['font_size_pt'],.5,
                    (frame['origin_pt'][1]-(frame_bottom-frame_height/2))/frame['font_size_pt'],
                    'NHP station frame width and visible depth; hide its top stroke under the original rail.'),
        },
    }
    assert trial.MAP['%']=='G069' and trial.MAP['T']=='G075'
    variant={'id':'refined','title':'Refined sizes and alignment','fitted':True,'glyph_fits':fits}
    font_sources={f[3]:f[0] for f in original[0].get_fonts() if f[3] in ('DGNSymbols','DGNSymbols_new')}
    metrics={name:trial.source_metrics(original,xref) for name,xref in font_sources.items()}
    entry=trial.embed_copy(source,variant,font_sources,metrics)
    before_manifest=json.loads((OUT/'manifest.json').read_text())
    before_manifest['trials']=[t for t in before_manifest['trials'] if t['variant']['id']!='refined']+[entry]
    (OUT/'manifest.json').write_text(json.dumps(before_manifest,indent=2)+'\n')
    # Verify the embedded font itself, rather than a screen-rendered estimate.
    newdoc=pymupdf.open(OUT/entry['pdf'])
    fontinfo=next(f for f in newdoc[0].get_fonts() if f[3]=='CELTrialDGN-refined')
    font=TTFont(BytesIO(newdoc.extract_font(fontinfo[0])[3]))
    g=font['glyf'][font.getBestCmap()[ord('g')]]
    centre_em=(g.yMin+g.yMax)/2/font['head'].unitsPerEm
    new_dot_y=dot['origin'][0][1]-dot['size']*centre_em
    assert abs(new_dot_y-hollow_y)<.003
    measurement={
        'reference_label_ratio':label_ratio,
        'tank':{'width_pt':tank_width,'height_pt':body_height+leg_height,
                'body_height_pt':body_height,'leg_width_pt':leg_width,'bottom_pt':tank_bottom,
                'limitation':'Leg-centre spacing remains 1.44006 pt because both source I glyphs are identical. '
                             'The NHP complete glyph would have wider leg spacing at this body size.'},
        'tick':{'previous_width_pt':.08*tick['font_size_pt'],'width_pt':tick_width},
        'station':{'outer_width_pt':frame_width,'visible_height_below_track_pt':frame_visible_height,
                   'red_width_pt':red_width,'red_height_pt':red_height,
                   'note':'Outer-frame stroke proportions remain an affine fit of the CEL hollow square.'},
        'power_line':{'previous_dot_centre_y':dot['origin'][0][1]-.5*dot['size'],
                      'hollow_circle_centre_y':hollow_y,'new_dot_centre_y':new_dot_y,
                      'line_y':635.317138671875},
        'square_assignment':{'%':'G069 / U+00E2','T':'G075 / U+00F3'},
        'status':'reference_guided_visual_trial',
        'source_content_check':'Only font resource names changed; positions and all vector commands verified unchanged.',
        'glyph_fits':fits,
    }
    (OUT/'refinement_measurements.json').write_text(json.dumps(measurement,indent=2)+'\n')
    assert trial.sha(trial.SOURCE.read_bytes())==trial.sha(source)
    print(json.dumps({k:v for k,v in measurement.items() if k in ('tank','tick','station','power_line')},indent=2))
    newdoc.close();original.close()



if __name__=='__main__':main()
