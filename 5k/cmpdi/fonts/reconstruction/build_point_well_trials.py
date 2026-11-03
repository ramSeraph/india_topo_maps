# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf==2.1", "fonttools==4.68.0"]
# ///
"""Compare reference-supported point dots and both conventional well symbols."""
from copy import deepcopy
import json
from pathlib import Path
import re

import pymupdf
import build_trial_fonts as trial

ROOT=trial.ROOT
OUT=ROOT/'benchmark_well_reference'
OUT.mkdir(exist_ok=True)


def place_image(page,box,path):
    page.insert_image(pymupdf.Rect(box),filename=str(path),keep_proportion=True)


def main():
    original=trial.SOURCE.read_bytes()
    source=pymupdf.open(stream=original,filetype='pdf')
    spans=source[0].get_texttrace()
    markers=[s for s in spans if s['font']=='DGNSymbols' and ''.join(chr(c[0]) for c in s['chars'])=='w']
    labels=[s for s in spans if re.fullmatch(r'\d+\.\d+',''.join(chr(c[0]) for c in s['chars']))]
    matches=[]
    diameter=1.2960880622863726  # Measured NHP ordinary height-point dot.
    for marker in markers:
        x,y=marker['chars'][0][2]
        choices=[s for s in labels if 0<s['chars'][0][2][0]-x<12 and abs(s['chars'][0][2][1]-y)<2]
        assert len(choices)==1
        label=choices[0]
        centre=(y-label['chars'][0][2][1]+diameter/2)/marker['size']
        matches.append({'origin_pt':[x,y],'label':''.join(chr(c[0]) for c in label['chars']),
                        'label_origin_pt':label['chars'][0][2],'centre_y_em':centre,'font_size_pt':marker['size']})
    cy=sum(m['centre_y_em'] for m in matches)/len(matches)
    assert max(m['centre_y_em'] for m in matches)-min(m['centre_y_em'] for m in matches)<.00002
    size=markers[0]['size']
    manifest=json.loads((trial.OUT/'manifest.json').read_text())
    refined=next(t for t in manifest['trials'] if t['variant']['id']=='refined')
    fits=deepcopy(refined['variant']['glyph_fits'])
    fits['DGNSymbols']['w']={'width_em':diameter/size,'height_em':diameter/size,'centre_em':[.5,cy],
        'reason':'Solid-dot hypothesis supported by NHP height-point and benchmark legends; dot bottom aligned with adjacent numeric label baseline.'}
    fits['DGNSymbols']['(']={'width_em':1,'height_em':1,'centre_em':[.5,.5],
        'reason':'Trial circular well footprint at one source em; lined/unlined interpretation remains unresolved.'}
    sources={f[3]:f[0] for f in source[0].get_fonts() if f[3] in ('DGNSymbols','DGNSymbols_new')}
    metrics={name:trial.source_metrics(source,xref) for name,xref in sources.items()}
    entries=[]
    for kind,fid in [('hollow','G056'),('filled','G123')]:
        variant={'id':'point_dot_well_'+kind,'title':'Height-point dot; '+kind+' well candidate','fitted':True,
                 'glyph_fits':fits,'additional_mappings':{'w':'G027','(':fid}}
        entry=trial.embed_copy(original,variant,sources,metrics)
        assert entry['replaced_occurrences']['DGNSymbols:w']==2
        assert entry['replaced_occurrences']['DGNSymbols:(']==22
        assert entry['preserved_unmapped_occurrences']=={'DGNSymbols_new:H':1}
        entries.append(entry)
        print(variant['id'],'all 24 observations rendered',flush=True)
    ids={t['variant']['id'] for t in entries}
    manifest['trials']=[t for t in manifest['trials'] if t['variant']['id'] not in ids]+entries
    (trial.OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    evidence={'w':{'status':'shape_accepted','selected_shape':'solid dot','candidate_shapes':['dot'],
                   'trial_shape':'solid dot','cel_outline':'G027 / U+0067',
                   'source_layer':'HEIGHT_POINT','count':2,'diameter_pt':diameter,'label_matches':matches,
                   'pdf_clues_local':'w_pdf_clues.json',
                   'decision_source':'User clarified: w is a dot; the square hypothesis concerns the well symbol.',
                   'qualification':'Dot shape accepted by the user; exact original font outline and survey-point category remain unrecovered.'},
              '(':{'status':'shape_and_subtype_unresolved','source_layer':'WELL','count':22,
                    'candidate_shapes':['circle','square'],'pdf_clues_local':'well_pdf_clues.json',
                    'reference_convention':{'lined':'filled cyan circle','unlined':'hollow cyan circle'},
                    'candidates':{'filled':'G123 / U+02D9','hollow':'G056 / U+00CA'},
                    'qualification':'The reference legends favour a circle, but the missing PDF outline does not exclude a square. The generic WELL layer and colour also do not distinguish lined from unlined.'},
              'reference_files':['data/raw/43J_10_NE.pdf','reference_legend.webp'],
              'trial_pdfs':[t['pdf'] for t in entries],'source_content_changes':'Font-resource selection only; original drawing commands retained.'}
    (OUT/'point_well_candidates.json').write_text(json.dumps(evidence,indent=2)+'\n')
    assert trial.sha(trial.SOURCE.read_bytes())==trial.sha(original)



if __name__=='__main__':main()
