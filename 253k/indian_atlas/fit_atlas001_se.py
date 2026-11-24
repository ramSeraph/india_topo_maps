"""Fit full crossings and one-coordinate graticule observations without inventing
the missing coordinate of margin ticks. Held-out observations remain separate.
"""
from pathlib import Path
import json,hashlib,argparse
import numpy as np,cv2
from scipy.ndimage import gaussian_filter,map_coordinates
from scipy.optimize import differential_evolution,least_squares
import georeference_atlas001 as h

parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path);args=parser.parse_args()
ROOT=h.ROOT
config=json.loads(args.config.read_text()) if args.config else json.loads((ROOT/'data/atlas001-se-1873-scan.json').read_text())
WORK=ROOT/'work'/config['id'];OUT=ROOT/'output'/config['id'];OUT.mkdir(exist_ok=True)
SOURCE=ROOT/config['source']
line_slopes=config.get('line_slope_bounds',{})
vertical_slopes=line_slopes.get('vertical',[-.11,-.025])
horizontal_slopes=line_slopes.get('horizontal',[.015,.10])
for bounds in (vertical_slopes,horizontal_slopes):
 if len(bounds)!=2 or not np.all(np.isfinite(bounds)) or bounds[0]>=bounds[1]:
  raise ValueError('Line slope bounds must be two finite increasing values')
table=json.loads((ROOT/config['table']).read_text())
h.LATS=np.array(table['latitudes']);h.RADII=np.array(table['radius_fathoms']);h.ANGLES=np.array(table['angle_arcseconds_per_longitude_degree']);h.R0=table['reference_radius_fathoms']
q=np.array([[76.5-offset,lat] for lat in h.LATS for offset in table['sine_check_longitude_offsets']])
sine_error=float(np.max(abs(-h.project(q)[:,0]-np.array(table['sine_check_fathoms']).ravel())))
assert sine_error<.3,sine_error
flags=cv2.IMREAD_COLOR | (cv2.IMREAD_IGNORE_ORIENTATION if config.get('ignore_exif_orientation',False) else 0)
im=cv2.imread(str(SOURCE),flags);gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
crossings=json.loads((WORK/'initial-points.json').read_text());seeds=config.get('crossing_local_seeds',[(201,193),(195,187)])
assert len(crossings)==len(seeds),'Each crossing needs a local search seed'
for p,seed in zip(crossings,seeds):
 ox,oy=p['crop_origin'];crop=im[oy:oy+400,ox:ox+400]
 window=config.get('crossing_search_window',15)
 override=config.get('crossing_search_overrides',{}).get(str(p['id']),{})
 if override:
  window=override['half_window']
  assert np.isfinite(window) and window>0 and override.get('reason'),'Crossing override needs a positive window and measurement reason'
  p['measurement_note']=override['reason'];p['search_half_window_pixels']=window
 exclusions=config.get('crossing_line_exclusions',{}).get(str(p['id']),{})
 vx,vs=h.line_fit(crop,True,seed[0],window,exclusions.get('vertical',[]),slope_bounds=vertical_slopes);hy,hs=h.line_fit(crop,False,seed[1],window,exclusions.get('horizontal',[]),slope_bounds=horizontal_slopes);mid=199.5
 if exclusions:p['line_sample_exclusions']=exclusions
 x=(vx+vs*(hy-mid)-vs*hs*mid)/(1-vs*hs);y=hy+hs*(x-mid)
 p.update(pixel=float(ox+x+.5),line=float(oy+y+.5),kind='crossing',vertical_slope=float(vs),horizontal_slope=float(hs))

tick_seeds=json.loads((WORK/'tick-seeds.json').read_text())
tick_exclusions=config.get('unmeasurable_tick_observations',{})
assert set(tick_exclusions)<=set(map(str,range(len(tick_seeds)))), 'Unknown excluded tick index'
ticks=[];unmeasurable_ticks=[]
for i,p in enumerate(tick_seeds):
 if str(i) in tick_exclusions:
  reason=tick_exclusions[str(i)]
  assert isinstance(reason,str) and reason.strip(), 'Unmeasurable tick needs a native-inspection reason'
  unmeasurable_ticks.append(dict(p,original_index=i,role='fit' if i%2==0 else 'withheld',reason=reason))
  continue
 override=config.get('tick_search_overrides',{}).get(str(i),{})
 if override:
  p['initial_line']=override.get('initial_line',p['initial_line'])
  p['measurement_note']=override.get('reason','Narrow search window inspected visually')
 x0,x1=override['pixel_window'] if 'pixel_window' in override else config.get('tick_windows',{'west':[440,535],'east':[6195,6285]})[p['side']];y0=p['initial_line']-80
 assert x1-x0>10, 'Latitude tick window must exceed the two five-pixel sampling margins'
 a=gray[y0:y0+160,x0:x1].astype(float);contrast=gaussian_filter(a,(5,0))-a;contrast=gaussian_filter(contrast,.5)
 t=np.arange(5,x1-x0-5,dtype=float);mid=(x1-x0-1)/2
 def score(v):
  values=map_coordinates(contrast,[v[0]+v[1]*(t-mid),t],order=1)
  return -np.clip(values,-10,25).mean()
 half_window=override.get('half_window',55)
 result=differential_evolution(score,[(80-half_window,80+half_window),horizontal_slopes],seed=13,tol=1e-9)
 p.update(pixel=x0+mid+.5,line=float(y0+result.x[0]+.5),kind='margin_tick',line_slope=float(result.x[1]),role='fit' if i%2==0 else 'withheld')
 ticks.append(p)

longitude_ticks=[]
for spec in config.get('longitude_tick_samples',[]):
 assert spec['side'] in ('north','south') and spec['role'] in ('fit','withheld')
 y0,y1=spec['line_window'];x0=round(spec['pixel'])-80
 assert 0<=y0<y1<=gray.shape[0] and y1-y0>10 and 0<=x0 and x0+160<=gray.shape[1]
 # Transpose so the same cross-line contrast measurement applies to a
 # vertical longitude tick. Only longitude enters the fit, never latitude.
 a=gray[y0:y1,x0:x0+160].T.astype(float)
 contrast=gaussian_filter(a,(5,0))-a;contrast=gaussian_filter(contrast,.5)
 t=np.arange(5,y1-y0-5,dtype=float);mid=(y1-y0-1)/2
 def score(v):
  values=map_coordinates(contrast,[v[0]+v[1]*(t-mid),t],order=1)
  return -np.clip(values,-10,25).mean()
 half_window=spec.get('half_window',10)
 assert 0<half_window<75
 result=differential_evolution(score,[(80-half_window,80+half_window),vertical_slopes],seed=13,tol=1e-9)
 longitude_ticks.append(dict(kind='margin_tick',side=spec['side'],known_axis='longitude',known_value=spec['longitude'],pixel=float(x0+result.x[0]+.5),line=y0+mid+.5,line_slope=float(result.x[1]),role=spec['role'],measurement_window=dict(line_window=[y0,y1],initial_pixel=spec['pixel'],half_window=half_window)))

meridians=[]
samples=config.get('meridian_samples')
if samples is None:
 samples=[dict(longitude=p['longitude'],pixel=p['pixel']+p['vertical_slope']*(y-p['line']),line=y,role=role) for p in crossings for y,role in [(1000,'fit'),(3700,'fit'),(1600,'withheld'),(3200,'withheld')]]
for p in samples:
 x,y=p['pixel'],p['line'];ox,oy=round(x)-150,y-150
 crop=im[oy:oy+300,ox:ox+300];z,slope=h.line_fit(crop,True,150,p.get('search_window',config.get('meridian_search_window',30)),slope_bounds=vertical_slopes)
 meridians.append(dict(kind='meridian',known_axis='longitude',known_value=p['longitude'],pixel=float(ox+z+.5),line=y+.5,line_slope=float(slope),role=p['role']))

parallels=[]
for p in config.get('parallel_samples',[]):
 x,y=p['pixel'],p['line'];ox,oy=round(x)-150,round(y)-150
 crop=im[oy:oy+300,ox:ox+300];z,slope=h.line_fit(crop,False,150,p.get('search_window',30),slope_bounds=horizontal_slopes)
 parallels.append(dict(kind='parallel',known_axis='latitude',known_value=p['latitude'],pixel=x+.5,line=float(oy+z+.5),line_slope=float(slope),role=p['role']))
controls=crossings+[p for p in ticks+longitude_ticks+meridians+parallels if p['role']=='fit'];checks=[p for p in ticks+longitude_ticks+meridians+parallels if p['role']=='withheld']
# Seed only; final coefficients use measured full and partial constraints.
seed_ll=[[p['longitude'],p['latitude']] for p in crossings]+[[crossings[0]['longitude'],config.get('seed_north_latitude',26.87)]]
seed_xy=[[p['pixel'],p['line']] for p in crossings]+[[meridians[0]['pixel'],meridians[0]['line']]]
if config.get('affine_initialization'):
 initialization=config['affine_initialization'];assert initialization.get('reason')
 seed_ll=[[p['longitude'],p['latitude']] for p in initialization['approximate_positions']]
 seed_xy=[[p['pixel'],p['line']] for p in initialization['approximate_positions']]
 assert len(seed_ll)>=3 and np.linalg.matrix_rank(np.column_stack([np.ones(len(seed_xy)),seed_xy]))==3,'Affine initialization needs noncollinear positions'
seed_model=h.fit(h.project(seed_ll),np.array(seed_xy));pixel_centre=np.mean([[p['pixel'],p['line']] for p in controls],axis=0)
seed_plane=(pixel_centre-seed_model[1][0])@np.linalg.inv(seed_model[1][1:])*100000+seed_model[0]
initial=np.vstack([seed_plane/100000,5000*np.linalg.inv(seed_model[1][1:])])
def estimate(records,start=initial):
 xy=np.array([[p['pixel'],p['line']] for p in records]);design=np.column_stack([np.ones(len(xy)),(xy-pixel_centre)/5000])
 def residual(flat):
  ll=h.inverse(design@flat.reshape(3,2)*100000);errors=[]
  for p,q in zip(records,ll):
   if p['kind']=='crossing':errors.extend((q-[p['longitude'],p['latitude']])*3600)
   else:errors.append((q[0 if p['known_axis']=='longitude' else 1]-p['known_value'])*3600)
  return np.array(errors)
 solution=least_squares(residual,start.ravel(),xtol=1e-12,ftol=1e-12,gtol=1e-10,max_nfev=200)
 assert solution.success,solution.message
 coef=solution.x.reshape(3,2);model=(coef[0]*100000,np.vstack([pixel_centre,5000*np.linalg.inv(coef[1:])]))
 assert np.linalg.matrix_rank(solution.jac)==6
 return model,coef,residual(solution.x),float(np.linalg.cond(solution.jac))
model,coef,residuals,condition=estimate(controls)
def error(p,model):
 xy=np.array([[p['pixel'],p['line']]]);ll=h.pixel_to_ll(xy,model)[0]
 if p['kind']=='crossing':return float(np.linalg.norm(h.predict(h.project([[p['longitude'],p['latitude']]]),model)[0]-xy[0])),np.array(ll-[p['longitude'],p['latitude']])*3600
 axis=0 if p['known_axis']=='longitude' else 1;angular=(ll[axis]-p['known_value'])*3600
 gradient=(h.pixel_to_ll(xy+[[.1,0],[0,.1]],model)[:,axis]-ll[axis])*36000
 return float(angular/np.linalg.norm(gradient)),float(angular)
loo=[]
for i,p in enumerate(controls):
 trial,_,_,_=estimate(controls[:i]+controls[i+1:],coef);loo.append(float(error(p,trial)[0]))
for p in controls:
 p['fit_pixel_error'],arc=error(p,model);p['fit_arcsecond_error']=arc.tolist() if isinstance(arc,np.ndarray) else arc
for p in checks:p['cross_line_pixel_error'],p['error_arcseconds']=error(p,model)

def contact(records,path):
 canvas=np.full((((len(records)+2)//3)*280,3*320,3),250,np.uint8)
 for k,p in enumerate(records):
  x,y=round(p['pixel']-.5),round(p['line']-.5);r,c=divmod(k,3);crop=im[y-120:y+120,x-150:x+150].copy();cv2.circle(crop,(150,120),6,(0,0,255),1)
  canvas[r*280+30:r*280+270,c*320:c*320+300]=crop
  label=f'{p["longitude"]}, {p["latitude"]}' if p['kind']=='crossing' else f'{p.get("side", p["kind"])} {p["known_value"]:.4f}'
  label+=' fit' if p in controls else f' {p["error_arcseconds"]:+.2f}"'
  cv2.putText(canvas,label,(c*320,r*280+20),cv2.FONT_HERSHEY_SIMPLEX,.43,(0,0,0),1)
 cv2.imwrite(str(OUT/path),canvas,[cv2.IMWRITE_JPEG_QUALITY,96])
contact(controls,'control-point-crops.jpg');contact(checks,'independent-edge-checks.jpg')
record=dict(source=str(SOURCE.relative_to(ROOT)),source_size=[im.shape[1],im.shape[0]],source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
 ignore_exif_orientation=config.get('ignore_exif_orientation',False),source_orientation_note=config.get('source_orientation_note'),
 quality_note=config.get('quality_note'),
 line_slope_bounds=dict(vertical=vertical_slopes,horizontal=horizontal_slopes),
 source_identification_note=config.get('source_identification_note'),
 seed_provenance=config.get('seed_provenance','Search windows identified from scan preview; printed rules measured at original resolution.'),
 affine_initialization=config.get('affine_initialization'),
 unmeasurable_tick_observations=unmeasurable_ticks,
 table=config['table'],sine_check_max_error_fathoms=sine_error,model='Historical detailed-angle/radius projection plus six-coefficient affine registration using full and one-coordinate graticule observations',
 pixel_convention='GDAL pixel/line convention, +0.5 at pixel centres',points=crossings,control_observations=controls,
 affine_plane_centre_fathoms=model[0].tolist(),affine_coefficients=model[1].tolist(),fit_pixel_errors=[p['fit_pixel_error'] for p in crossings],
 leave_one_out_pixel_errors=loo,leave_one_out_rmse_pixels=float(np.sqrt(np.mean(np.square(loo)))),
 independent_edge_checks=checks,edge_rmse_arcseconds=float(np.sqrt(np.mean([p['error_arcseconds']**2 for p in checks]))),
 jacobian_condition_number=condition,ground_review_required=False,
 validation_scope=f'{len(controls)} control observations: {len(crossings)} full-coordinate crossings and {len(controls)-len(crossings)} one-coordinate graticule observations. Leave-one-observation-out pixel errors are 2D for crossings and perpendicular to the known graticule coordinate for partial observations. {len(checks)} separate withheld observations. No modern ground checks required.')
(OUT/'fit-report.json').write_text(json.dumps(record,indent=2)+'\n')
preview=cv2.resize(im,(2200,round(im.shape[0]*2200/im.shape[1])));scale=2200/im.shape[1]
lat_low=max(h.LATS[0],min(p['latitude'] for p in crossings)-.5);lat_high=min(h.LATS[-1],max(p['latitude'] for p in crossings)+.5)
lon_low=min(p['longitude'] for p in crossings)-.5;lon_high=max(p['longitude'] for p in crossings)+.5
for longitude in sorted({p['longitude'] for p in crossings}):
 ll=np.column_stack([np.full(200,longitude),np.linspace(lat_low,lat_high,200)]);cv2.polylines(preview,[np.rint(h.predict(h.project(ll),model)*scale).astype(np.int32)],False,(255,100,0),1)
for latitude in sorted({p['latitude'] for p in crossings}):
 ll=np.column_stack([np.linspace(lon_low,lon_high,200),np.full(200,latitude)]);cv2.polylines(preview,[np.rint(h.predict(h.project(ll),model)*scale).astype(np.int32)],False,(255,100,0),1)
cv2.imwrite(str(OUT/'graticule-overlay.jpg'),preview,[cv2.IMWRITE_JPEG_QUALITY,94])
print(json.dumps({k:record[k] for k in ['fit_pixel_errors','leave_one_out_rmse_pixels','edge_rmse_arcseconds','jacobian_condition_number']},indent=2))
print([(p.get('side',p['kind']),p.get('known_value'),round(p.get('error_arcseconds',0),2)) for p in checks])
