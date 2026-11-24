"""Compare affine and quadratic historical-plane fits on a frozen dataset."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
import georeference_atlas001 as h

ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
dataset=json.loads(args.dataset.read_text());sid=dataset['id']
config=json.loads((ROOT/f'data/{sid}-scan.json').read_text());old=json.loads((ROOT/f'output/{sid}/fit-report.json').read_text())
table=json.loads((ROOT/dataset['table']).read_text())
h.LATS=np.array(table['latitudes']);h.RADII=np.array(table['radius_fathoms']);h.ANGLES=np.array(table['angle_arcseconds_per_longitude_degree']);h.R0=table['reference_radius_fathoms']
controls,checks=dataset['controls'],dataset['checks'];centre=np.array(old['source_size'])/2;scale=max(old['source_size'])/2
old_model=(np.array(old['affine_plane_centre_fathoms']),np.array(old['affine_coefficients']))
def positions(records):return np.array([[p['pixel'],p['line']] for p in records])
def design(xy,order):
    x,y=((np.asarray(xy)-centre)/scale).T
    return np.column_stack([np.ones(len(x)),x,y]+([x*x,x*y,y*y] if order==2 else []))
def errors(records,ll):
    return np.array([v for p,q in zip(records,ll) for v in ((q-np.array([p['longitude'],p['latitude']]))*3600 if p['kind']=='crossing' else [(q[0 if p['known_axis']=='longitude' else 1]-p['known_value'])*3600])])
def fit(records,order):
    xy=positions(records);d=design(xy,order)
    plane=(xy-old_model[1][0])@np.linalg.inv(old_model[1][1:])*100000+old_model[0]
    start=np.linalg.lstsq(d,plane/100000,rcond=None)[0]
    solution=least_squares(lambda flat:errors(records,h.inverse(d@flat.reshape(-1,2)*100000)),start.ravel(),xtol=1e-12,ftol=1e-12,gtol=1e-10,max_nfev=300)
    assert solution.success and np.linalg.matrix_rank(solution.jac)==start.size
    return solution.x.reshape(-1,2),float(np.linalg.cond(solution.jac))
def predict(xy,c,order):return h.inverse(design(xy,order)@c*100000)
trials=[];fitted=[]
frame=np.array(config['frame_corners'])+.5
for order in (1,2):
    coef,condition=fit(controls,order);loo=[]
    for i,p in enumerate(controls):
        c,_=fit(controls[:i]+controls[i+1:],order);xy=positions([p]);ll=predict(xy,c,order)[0]
        jac=np.column_stack([(predict(xy+[[.1,0]],c,order)[0]-ll)/.1,(predict(xy+[[0,.1]],c,order)[0]-ll)/.1])*3600
        e=errors([p],[ll]);loo.append(float(np.linalg.norm(np.linalg.solve(jac,e))) if p['kind']=='crossing' else float(abs(e[0])/np.linalg.norm(jac[0 if p['known_axis']=='longitude' else 1])))
    fitted.append(coef)
    trials.append(dict(order=order,coefficients=coef.tolist(),condition=condition,loo_rms_pixels=float(np.sqrt(np.mean(np.square(loo)))),loo_errors_pixels=loo))
chosen=min(trials,key=lambda t:t['loo_rms_pixels'])['order']
for trial,coef in zip(trials,fitted):
    order=trial['order'];err=errors(checks,predict(positions(checks),coef,order));corners=predict(frame,coef,order);corners[:,0]-=216.18/3600
    xx,yy=np.meshgrid(np.linspace(frame[:,0].min(),frame[:,0].max(),81),np.linspace(frame[:,1].min(),frame[:,1].max(),61));xy=np.c_[xx.ravel(),yy.ravel()]
    base=design(xy,order)@coef*100000;dx=(design(xy+[[.1,0]],order)@coef*100000-base)/.1;dy=(design(xy+[[0,.1]],order)@coef*100000-base)/.1;det=dx[:,0]*dy[:,1]-dy[:,0]*dx[:,1]
    trial.update(withheld_rms_arcseconds=float(np.sqrt(np.mean(err**2))),withheld_max_arcseconds=float(abs(err).max()),withheld_errors_arcseconds=err.tolist(),corrected_frame_corners_lonlat=corners.tolist(),sampled_orientation_consistent=bool(np.all(det<0)),jacobian_determinant_range=[float(det.min()),float(det.max())])
report=dict(id=sid,dataset=str(args.dataset),control_count=len(controls),check_count=len(checks),pixel_centre=centre.tolist(),pixel_scale=scale,plane_scale=100000,selected_order=chosen,selection='Lowest training leave-one-observation-out RMS, before evaluating withheld checks or corner positions. Original controls unchanged.',trials=trials)
args.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'id':sid,'selected_order':chosen,'trials':[{k:t[k] for k in ('order','loo_rms_pixels','withheld_rms_arcseconds','withheld_max_arcseconds','sampled_orientation_consistent')} for t in trials]},indent=2))
