import os
os.environ['OPENBLAS_NUM_THREADS']='1'
import sys, traceback, cv2
import numpy as np
from concurrent.futures import ProcessPoolExecutor
from register_atlas_scan import ROOT,read,write,acquire
cv2.setNumThreads(1)
base=ROOT/'work/atlas-intake'
def one(item):
    sid=item['id'];d=base/sid; status=d/'intake-status.json'
    if not (d/'frame-v2.json').exists():return
    if status.exists() and '--redo' not in sys.argv:return
    try:
        c,r=acquire(item,read(d/'frame-v2.json'))
        c.update(book_frame_normal_sides=['north','east','south','west'],book_frame_normal_tolerance_3857_m=12.5)
        write(d/'config.json',c);write(d/'affine.json',r)
        result=dict(id=sid,status='measured',train=len(r['control_observations']),checks=r['independent_scalar_checks'],rms=r['edge_rmse_arcseconds'],median=float(np.median(abs(np.array(r['withheld_errors_arcseconds'])))),cross=r['interior_crossings'])
    except Exception as e:result=dict(id=sid,status='review',reason=repr(e),trace=traceback.format_exc())
    write(status,result)
    print(sid,result.get('rms',result.get('reason')),flush=True)
if __name__=='__main__':
    a,b=map(int,sys.argv[1:3])
    with ProcessPoolExecutor(int(sys.argv[3])) as pool:list(pool.map(one,read(base/'queue.json')[a:b]))
