"""Measure and validate the intact 001 NE (1871) sheet's printed graticule.
Run with uv run --with numpy --with scipy --with opencv-python python georeference_atlas001.py
"""
from pathlib import Path
import json,hashlib
import numpy as np,cv2
from scipy.ndimage import gaussian_filter,map_coordinates
from scipy.optimize import differential_evolution,brentq

ROOT=Path(__file__).resolve().parent;WORK=ROOT/'work/atlas001-ne-1871';OUT=ROOT/'output/atlas001-ne-1871'
SOURCE=ROOT/'sources/zenodo-19431985/sheets/001 NE Quarter Sheet Indian Atlas (1871).jpg'
TABLE=json.loads((ROOT/'data/atlas001-ne-1871-projection.json').read_text())
LATS=np.array(TABLE['latitudes']);RADII=np.array(TABLE['radius_fathoms']);ANGLES=np.array(TABLE['angle_arcseconds_per_longitude_degree']);R0=TABLE['reference_radius_fathoms']
def project(ll):
 lon,lat=np.asarray(ll,dtype=float).reshape(-1,2).T
 if np.any((lat<LATS[0])|(lat>LATS[-1])):raise ValueError('Outside transcribed projection table.')
 r=np.interp(lat,LATS,RADII);e=np.interp(lat,LATS,ANGLES);theta=np.deg2rad((lon-76.5)*e/3600)
 return np.column_stack([r*np.sin(theta),R0-r*np.cos(theta)])
def inverse(plane):
 x,y=np.asarray(plane,dtype=float).reshape(-1,2).T;r=np.hypot(x,R0-y)
 if np.any((r<RADII.min())|(r>RADII.max())):raise ValueError('Outside transcribed projection table.')
 lat=np.interp(r,RADII[::-1],LATS[::-1]);e=np.interp(lat,LATS,ANGLES)
 return np.column_stack([76.5+np.rad2deg(np.arctan2(x,R0-y))*3600/e,lat])
def fit(plane,pixels):
 centre=plane.mean(axis=0);coef=np.linalg.lstsq(np.column_stack([np.ones(len(plane)),(plane-centre)/100000]),pixels,rcond=None)[0]
 return centre,coef
def predict(plane,model):return np.column_stack([np.ones(len(plane)),(plane-model[0])/100000])@model[1]
def pixel_to_ll(pixels,model):return inverse((np.asarray(pixels)-model[1][0])@np.linalg.inv(model[1][1:])*100000+model[0])

def line_fit(crop,vertical,seed,window=10,excluded_intervals=(),slope_bounds=None):
 if slope_bounds is None:slope_bounds=(-.11,-.025) if vertical else (.015,.10)
 if len(slope_bounds)!=2 or not np.all(np.isfinite(slope_bounds)) or slope_bounds[0]>=slope_bounds[1]:
  raise ValueError('Line slope bounds must be two finite increasing values')
 a=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY).astype(float)
 contrast=gaussian_filter(a,(0,4) if vertical else (4,0))-a;contrast=gaussian_filter(contrast,.6)
 t=np.arange(20,len(a)-20,dtype=float);mid=(len(a)-1)/2
 for low,high in excluded_intervals:t=t[(t<low)|(t>high)]
 assert len(t)>=60,'Too little unmasked line remains to measure'
 def score(v):
  z=v[0]+v[1]*(t-mid)
  values=map_coordinates(contrast,[t,z] if vertical else [z,t],order=1)
  return -np.clip(values,-10,22).mean()
 result=differential_evolution(score,[(seed-window,seed+window),slope_bounds],seed=11,tol=1e-8)
 return result.x

def main():
 im=cv2.imread(str(SOURCE));h,w=im.shape[:2]
 points=json.loads((WORK/'initial-points.json').read_text());seeds=[(207,183),(211,188),(210,198),(223,194)]
 canvas=np.full((880,840,3),250,np.uint8)
 for p,seed in zip(points,seeds):
  ox,oy=p['crop_origin'];crop=im[oy:oy+400,ox:ox+400].copy()
  vx,vs=line_fit(crop,True,seed[0]);hy,hs=line_fit(crop,False,seed[1]);mid=199.5
  x=(vx+vs*(hy-mid)-vs*hs*mid)/(1-vs*hs);y=hy+hs*(x-mid)
  p.update(pixel=float(ox+x+.5),line=float(oy+y+.5),local_line_fits={'vertical':[vx,vs],'horizontal':[hy,hs]})
  cv2.circle(crop,(round(x),round(y)),7,(0,0,255),1)
  r,c=divmod(p['id'],2);canvas[r*440+30:r*440+430,c*420:c*420+400]=crop
  cv2.putText(canvas,f'{p["id"]}: {p["longitude"]}, {p["latitude"]}',(c*420,r*440+20),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),1)
 ll=np.array([[p['longitude'],p['latitude']] for p in points]);xy=np.array([[p['pixel'],p['line']] for p in points]);plane=project(ll);model=fit(plane,xy)
 loo=[]
 for i in range(4):
  keep=np.arange(4)!=i;loo.append(float(np.linalg.norm(predict(plane[i:i+1],fit(plane[keep],xy[keep]))[0]-xy[i])))
 fit_errors=np.linalg.norm(predict(plane,model)-xy,axis=1)
 cv2.imwrite(str(OUT/'control-point-crops.jpg'),canvas,[cv2.IMWRITE_JPEG_QUALITY,96])
 # Independent single-coordinate observations near the map edges, not fitted.
 specs=[('north',True,620,v) for v in [67.5,68]]+[('south',True,3880,v) for v in [67.5,68]]
 specs += [('west',False,700,v) for v in [27,27.5]]+[('east',False,5900,v) for v in [27,27.5]]
 checks=[];inspection=np.full((4*340,2*320,3),250,np.uint8)
 for k,(edge,vertical,fixed,value) in enumerate(specs):
  def residual(z):return pixel_to_ll([[z,fixed]] if vertical else [[fixed,z]],model)[0,0 if vertical else 1]-value
  predicted=brentq(residual,400,6200) if vertical else brentq(residual,400,4100)
  cx,cy=(predicted,fixed) if vertical else (fixed,predicted);ox,oy=round(cx)-150,round(cy)-150
  crop=im[oy:oy+300,ox:ox+300].copy();z,slope=line_fit(crop,vertical,150,20)
  px,py=(ox+z+.5,fixed+.5) if vertical else (fixed+.5,oy+z+.5)
  error=(pixel_to_ll([[px,py]],model)[0,0 if vertical else 1]-value)*3600
  checks.append(dict(edge=edge,known_axis='longitude' if vertical else 'latitude',known_value=value,pixel=float(px),line=float(py),error_arcseconds=float(error),line_slope=float(slope)))
  cv2.circle(crop,(round(z),150) if vertical else (150,round(z)),7,(0,0,255),1)
  r,c=divmod(k,2);inspection[r*340+30:r*340+330,c*320:c*320+300]=crop
  cv2.putText(inspection,f'{edge} {value}: {error:+.2f} arcsec',(c*320,r*340+20),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,0,0),1)
 cv2.imwrite(str(OUT/'independent-edge-checks.jpg'),inspection,[cv2.IMWRITE_JPEG_QUALITY,96])
 q=np.array([[76.5-offset,lat] for lat in LATS for offset in TABLE['sine_check_longitude_offsets']]);delta=-project(q)[:,0]-np.array(TABLE['sine_check_fathoms']).ravel()
 assert np.max(abs(delta))<.3,delta
 assert np.max(abs(inverse(project(ll))-ll))<1e-9
 report=dict(source=str(SOURCE.relative_to(ROOT)),source_size=[w,h],source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
  table='data/atlas001-ne-1871-projection.json',model='Historical detailed-angle/radius projection plus six-coefficient affine scan registration',
  pixel_convention='GDAL pixel/line from upper-left pixel edge; pixel centres include +0.5',points=points,
  affine_plane_centre_fathoms=model[0].tolist(),affine_coefficients=model[1].tolist(),
  fit_pixel_errors=fit_errors.tolist(),leave_one_out_pixel_errors=loo,leave_one_out_rmse_pixels=float(np.sqrt(np.mean(np.square(loo)))),
  independent_edge_checks=checks,edge_rmse_arcseconds=float(np.sqrt(np.mean([p['error_arcseconds']**2 for p in checks]))),
  sine_check_max_error_fathoms=float(np.max(abs(delta))),
  validation_scope='Four measured full-coordinate graticule intersections, leave-one-out tests, and eight withheld one-coordinate edge observations. Printed-coordinate fit only; not modern ground accuracy.')
 (OUT/'fit-report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:report[k] for k in ['fit_pixel_errors','leave_one_out_pixel_errors','leave_one_out_rmse_pixels','edge_rmse_arcseconds','sine_check_max_error_fathoms']},indent=2))
 # Native-resolution neatline inspection: four corners, before choosing a crop.
 sheet_corners=[(470,410),(6120,410),(6120,4030),(450,4030)]
 corners=np.full((720,720,3),250,np.uint8)
 for i,(x,y) in enumerate(sheet_corners):
  r,c=divmod(i,2);crop=im[y-160:y+160,x-160:x+160]
  corners[r*360+30:r*360+350,c*360:c*360+320]=crop
  cv2.putText(corners,f'{i} origin {x-160},{y-160}',(c*360,r*360+20),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),1)
 cv2.imwrite(str(WORK/'neatline-corners.jpg'),corners,[cv2.IMWRITE_JPEG_QUALITY,96])
 overlay=cv2.resize(im,(2200,round(h*2200/w)));scale=2200/w
 for lon in [67.5,68]:
  coords=np.column_stack([np.full(150,lon),np.linspace(26.85,27.8,150)]);line=predict(project(coords),model)*scale
  cv2.polylines(overlay,[np.rint(line).astype(np.int32)],False,(255,90,0),1)
 for lat in [27,27.5]:
  coords=np.column_stack([np.linspace(66.9,68.5,150),np.full(150,lat)]);line=predict(project(coords),model)*scale
  cv2.polylines(overlay,[np.rint(line).astype(np.int32)],False,(255,90,0),1)
 cv2.imwrite(str(OUT/'graticule-overlay.jpg'),overlay,[cv2.IMWRITE_JPEG_QUALITY,93])

if __name__=='__main__':main()
