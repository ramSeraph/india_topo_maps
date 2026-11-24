import os
os.environ['OPENBLAS_NUM_THREADS']='1'
import sys,traceback,cv2
from concurrent.futures import ProcessPoolExecutor
import fit_atlas_book_edges as f
import render_atlas_book_edges as r
import audit_atlas_tps_rollout as a
from audit_atlas_tps_rollout import ROOT,read,write
from pathlib import Path
cv2.setNumThreads(1)
d=ROOT/'work/atlas-intake';a.WORK=f.WORK=d/'baselines';f.OUT=r.OUT=d/'models';r.REVIEW=d/'cogs'
def one(sid):
    q=d/sid; status=q/'fit-status.json'
    try:
        if not (q/'affine.json').exists():return
        if status.exists() and '--redo' not in sys.argv:return
        cfg=read(q/'config.json');ref=read(q/'affine.json')
        ds=a.OUTPUT/sid
        ds.mkdir(parents=True,exist_ok=True)
        official=ROOT/f'data/{sid}-scan.json'
        if official.exists() and read(official).get('source')!=cfg['source']:raise ValueError('ID in use')
        write(official,cfg);write(ds/'fit-report.json',ref)
        a.run(dict(id=sid,directory=sid),{})
        ans=f.process(sid)
        model=f.OUT/sid
        result=read(model/'status.json')
        if ans=='fitted':
            print(sid, 'TPS',result['withheld'], result['previous'],result['edge_max_departure_3857_m'],flush=True)
        else: print(sid,result.get('reason'),flush=True)
    except Exception as e:result=dict(id=sid,status='review',reason=repr(e),trace=traceback.format_exc())
    write(status,result)
    if result.get('status')!='fitted':print(sid,result.get('reason'),flush=True)
if __name__=='__main__':
    a0,b=map(int,sys.argv[1:3])
    with ProcessPoolExecutor(int(sys.argv[3])) as pool:list(pool.map(one,[i['id'] for i in read(d/'queue.json')[a0:b]]))
