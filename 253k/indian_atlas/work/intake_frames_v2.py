from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import json,cv2,numpy as np,sys
from work.intake_band import detect
cv2.setNumThreads(1)
b=Path('work/atlas-intake');q=json.loads((b/'queue.json').read_text())
def run(i):
 e=q[i];s=e['id'];d=b/s;d.mkdir(exist_ok=True)
 if (d/'frame-v2.json').exists():return 'cached'
 im=cv2.imread(e['source'],cv2.IMREAD_GRAYSCALE)
 ignore=False
 if im.shape[1]<im.shape[0]:
  raw=cv2.imread(e['source'],cv2.IMREAD_GRAYSCALE|cv2.IMREAD_IGNORE_ORIENTATION)
  if raw.shape[1]>raw.shape[0]:im=raw;ignore=True
  else:raise ValueError('Portrait original needs orientation review')
 c,g,bands=detect(im,bool(e['quarter']))
 spec=dict(frame_corners=c.tolist(),crop_edge_guides=g,bands=bands,source_size=list(im.shape[::-1]),ignore_exif_orientation=ignore)
 (d/'frame-v2.json').write_text(json.dumps(spec))
 return 'measured'
def task(i):
 try:return run(i)
 except Exception as e:return repr(e)
if __name__=='__main__':
 jobs=[int(j) for j in sys.argv[1:]] or list(range(len(q)))
 with ProcessPoolExecutor(6) as pool:
  futures={pool.submit(task,j):j for j in jobs}
  for fut in as_completed(futures):print(futures[fut],q[futures[fut]]['id'],fut.result(),flush=True)
