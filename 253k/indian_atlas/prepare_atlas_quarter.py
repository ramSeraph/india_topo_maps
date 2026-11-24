"""Prepare measured-search windows from 2200px scan-preview seeds.
Configuration remains authoritative; this script never overwrites it.
"""
from pathlib import Path
import argparse,json,cv2,numpy as np
from scipy.signal import find_peaks
parser=argparse.ArgumentParser();parser.add_argument('config',type=Path);args=parser.parse_args()
ROOT=Path(__file__).resolve().parent;config=json.loads(args.config.read_text())
WORK=ROOT/'work'/config['id'];WORK.mkdir(exist_ok=True)
flags=cv2.IMREAD_COLOR | (cv2.IMREAD_IGNORE_ORIENTATION if config.get('ignore_exif_orientation',False) else 0)
im=cv2.imread(str(ROOT/config['source']),flags);gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY);scale=im.shape[1]/2200
records=[];canvas=np.full((440*((len(config['crossing_preview_seeds'])+1)//2),840,3),250,np.uint8)
for i,(lon,lat,x,y) in enumerate(config['crossing_preview_seeds']):
 cx,cy=round(x*scale),round(y*scale);ox,oy=cx-200,cy-200
 records.append(dict(id=i,longitude=lon,latitude=lat,crop_origin=[ox,oy]))
 r,c=divmod(i,2)
 canvas[r*440+30:r*440+430,c*420:c*420+400]=im[oy:oy+400,ox:ox+400]
 cv2.putText(canvas,f'{lon}, {lat} origin {ox},{oy}',(c*420,r*440+20),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),1)
(WORK/'initial-points.json').write_text(json.dumps(records,indent=2)+'\n');cv2.imwrite(str(WORK/'crossing-seeds.jpg'),canvas)
ticks=[]
for side,spec in config.get('tick_preview_seeds',{}).items():
 for i,y in enumerate(spec['ys']):ticks.append(dict(side=side,known_axis='latitude',known_value=spec['first_latitude']-i/12,initial_line=round(y*scale)))
(WORK/'tick-seeds.json').write_text(json.dumps(ticks,indent=2)+'\n')
corners=np.array(config['frame_corners'],float)
for i in range(4):
 for t in [.02,.25,.5,.75,.98]:
  x,y=np.rint(corners[i]*(1-t)+corners[(i+1)%4]*t).astype(int)
  p=np.median(gray[y-30:y+31,x-30:x+31],axis=1 if i%2==0 else 0).astype(float)
  peaks=find_peaks(-p,prominence=25,distance=6)[0];origin=(y if i%2==0 else x)-30
  print(['north','east','south','west'][i],x if i%2==0 else y,[(int(z+origin),int(p[z])) for z in peaks])
