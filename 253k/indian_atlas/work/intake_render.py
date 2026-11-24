import os
os.environ['OPENBLAS_NUM_THREADS']='1'
import sys,cv2,traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import render_atlas_book_edges as r
from audit_atlas_tps_rollout import ROOT,read,write
cv2.setNumThreads(1)
d=ROOT/'work/atlas-intake';q=read(d/'queue.json')
r.OUT=d/'models';r.REVIEW=d/'cogs'
def render(i):
 sid=q[i]['id']; folder=r.OUT/sid;stage=d/sid
 try:
  st=read(stage/'fit-status.json')
  if st['status']!='fitted': return
  m=read(folder/'model.json');ds=read(ROOT/m['dataset']);ref=read(ROOT/ds['affine_reference'])
  if ('unusable_margin_strokes' not in ref or m['withheld_rms_arcseconds']!=st['withheld']
      or len(m['withheld_errors_arcseconds'])!=ref['independent_scalar_checks']
      or read(stage/'intake-status.json')['status']!='measured'
      or (folder/'model.json').stat().st_mtime<(d/'baselines'/sid/'tps.json').stat().st_mtime):return
  if st['withheld']>6:return
  r.render(sid)
  z=read(r.REVIEW/sid/'web-alignment.json');out=r.REVIEW/sid/z['files'][0]['file']
  assert r.sha(out)==z['files'][0]['sha256']
  write(folder/'render-status.json',dict(status='rendered'));print(sid,'COG',flush=True)
 except Exception as e: print(sid,repr(e),flush=True)
if __name__=='__main__':
 with ProcessPoolExecutor(3) as pool:list(pool.map(render,map(int,sys.argv[1:])))
