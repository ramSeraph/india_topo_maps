"""TPS trials with full and one-coordinate observations in the historical plane.

Smoothing is selected using leave-one-observation-out on training controls only.
The fixed independent checks and neighbouring corners never select the model.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
from pathlib import Path
import json,argparse
import numpy as np
from scipy.linalg import null_space
from scipy.optimize import least_squares
from scipy.interpolate import RBFInterpolator
import georeference_atlas001 as h

ROOT=Path(__file__).resolve().parent;OUT=ROOT/'work/atlas-continuity-audit'
parser=argparse.ArgumentParser();parser.add_argument('--sheet',default='atlas004-1862');parser.add_argument('--dataset',type=Path,default=OUT/'004-1862-model-comparison.json');parser.add_argument('--output',type=Path,default=OUT/'004-1862-tps-comparison.json');args=parser.parse_args()
comparison=json.loads(args.dataset.read_text())
controls=comparison['controls'];checks=comparison['checks']
table=json.loads((ROOT/comparison['table']).read_text())
h.LATS=np.array(table['latitudes']);h.RADII=np.array(table['radius_fathoms']);h.ANGLES=np.array(table['angle_arcseconds_per_longitude_degree']);h.R0=table['reference_radius_fathoms']
config=json.loads((ROOT/comparison.get('frame_config',f'data/{args.sheet}-scan.json')).read_text())
old=json.loads((ROOT/comparison.get('affine_reference',f'output/{args.sheet}/fit-report.json')).read_text())
old_model=(np.array(old['affine_plane_centre_fathoms']),np.array(old['affine_coefficients']))
centre=np.array([5800.,3900.]) if args.sheet=='atlas004-1862' else np.array(old['source_size'])/2
scale=5000. if args.sheet=='atlas004-1862' else max(old['source_size'])/2
plane_scale=100000.;penalty_scale=6000.
frame=np.array(config['frame_corners'],float)+config.get('frame_pixel_offset',.5);lower=frame.min(axis=0);upper=frame.max(axis=0)

def xy(records):return np.array([[p['pixel'],p['line']] for p in records])
def kernel(a,b):
    r2=np.sum((a[:,None,:]-b[None,:,:])**2,axis=2)
    return .5*r2*np.log(np.maximum(r2,1e-300))
def affine_plane(pixels):return (np.array(pixels)-old_model[1][0])@np.linalg.inv(old_model[1][1:])*plane_scale+old_model[0]

class Basis:
    def __init__(self,locations):
        self.knots=(locations-centre)/scale
        p=np.column_stack([np.ones(len(locations)),self.knots])
        if len(p)==3:
            if np.linalg.matrix_rank(p)!=3:
                raise ValueError('Three non-collinear knots are required for the affine tail')
            self.weights=np.empty((3,0))
            return
        z=null_space(p.T);k=kernel(self.knots,self.knots)
        eigenvectors=None
        values,vectors=np.linalg.eigh(z.T@k@z)
        assert values.min()>0
        self.weights=z@vectors@np.diag(1/np.sqrt(values))
        assert np.max(abs(p.T@self.weights))<1e-10
        assert np.max(abs(self.weights.T@k@self.weights-np.eye(len(values))))<1e-9
    def design(self,pixels):
        p=(np.array(pixels)-centre)/scale
        return np.column_stack([np.ones(len(p)),p,kernel(p,self.knots)@self.weights])

def axes_values(records):
    rows=[];axes=[];values=[]
    for i,p in enumerate(records):
        if p['kind']=='crossing':
            rows.extend([i,i]);axes.extend([0,1]);values.extend([p['longitude'],p['latitude']])
        else:
            rows.append(i);axes.append(0 if p['known_axis']=='longitude' else 1);values.append(p['known_value'])
    return np.array(rows),np.array(axes),np.array(values)

def fit(records,smoothing):
    locations=xy(records);basis=Basis(locations);d=basis.design(locations);n=d.shape[1]
    rows,axes,values=axes_values(records)
    start=np.zeros((n,2));start[:3]=np.linalg.lstsq(d[:,:3],affine_plane(locations)/plane_scale,rcond=None)[0]
    weight=np.sqrt(smoothing)*penalty_scale
    reg=np.zeros((2*(n-3),2*n));reg[:,6:]=np.eye(2*(n-3))*weight
    def residual(flat):
        ll=h.inverse(d@flat.reshape(n,2)*plane_scale)
        return np.r_[(ll[rows,axes]-values)*3600,reg@flat]
    def jacobian(flat):
        plane=d@flat.reshape(n,2)*plane_scale;ll=h.inverse(plane)
        grad=np.stack([(h.inverse(plane+[[.01,0]])-ll)/.01,(h.inverse(plane+[[0,.01]])-ll)/.01],axis=2)*3600*plane_scale
        data=np.einsum('ij,ik->ijk',d[rows],grad[rows,axes,:]).reshape(len(rows),2*n)
        return np.vstack([data,reg])
    solution=least_squares(residual,start.ravel(),jac=jacobian,method='lm',xtol=1e-11,ftol=1e-11,gtol=1e-9,max_nfev=100)
    assert solution.success,solution.message
    return basis,solution.x.reshape(n,2)

def predict(model,pixels):return h.inverse(model[0].design(pixels)@model[1]*plane_scale)
def errors(model,records):
    rows,axes,values=axes_values(records);return (predict(model,xy(records))[rows,axes]-values)*3600
def pixel_error(model,p):
    loc=xy([p]);ll=predict(model,loc)[0];err=errors(model,[p])
    jac=np.column_stack([(predict(model,loc+[[.1,0]])[0]-ll)/.1,(predict(model,loc+[[0,.1]])[0]-ll)/.1])*3600
    if p['kind']=='crossing':return float(np.linalg.norm(np.linalg.solve(jac,err)))
    return float(abs(err[0])/np.linalg.norm(jac[0 if p['known_axis']=='longitude' else 1]))

# Verify the TPS kernel, affine tail and bending-energy normalization against
# SciPy's standard full-coordinate TPS before using partial-coordinate fitting.
locations=xy(controls);basis=Basis(locations);d=basis.design(locations)
targets=affine_plane(locations)/plane_scale+np.column_stack([np.sin(locations[:,0]/3000),np.cos(locations[:,1]/2000)])*.001
smoothing=.01;reg=np.zeros((len(locations)-3,len(locations)));reg[:,3:]=np.eye(len(locations)-3)*np.sqrt(smoothing)
coef=np.linalg.lstsq(np.vstack([d,reg]),np.vstack([targets,np.zeros((len(locations)-3,2))]),rcond=None)[0]
probe=np.array([[250,350],[11000,7300],[5800,3900],[5000,1500]]) if args.sheet=='atlas004-1862' else np.vstack([frame,frame.mean(axis=0)])
reference=RBFInterpolator((locations-centre)/scale,targets,kernel='thin_plate_spline',degree=1,smoothing=smoothing)
verification=float(np.max(abs(basis.design(probe)@coef-reference((probe-centre)/scale))))
assert verification<1e-10,verification

trials=[]
for smoothing in (1e-8,1e-4,.001,.01,.1,1.):
    model=fit(controls,smoothing);loo=[]
    for i,p in enumerate(controls):
        held=fit(controls[:i]+controls[i+1:],smoothing);loo.append(pixel_error(held,p))
    train=errors(model,controls)
    trial=dict(smoothing=smoothing,loo_rms_pixels=float(np.sqrt(np.mean(np.square(loo)))),loo_errors_pixels=loo,
        train_rms_arcseconds=float(np.sqrt(np.mean(train**2))),train_max_arcseconds=float(abs(train).max()))
    trials.append(trial);print(json.dumps({k:v for k,v in trial.items() if k!='loo_errors_pixels'}),flush=True)

# Freeze selection before evaluating any held-out observations.
chosen=min(trials,key=lambda t:t['loo_rms_pixels'])
for trial in trials:
    model=fit(controls,trial['smoothing']);err=errors(model,checks)
    trial.update(withheld_rms_arcseconds=float(np.sqrt(np.mean(err**2))),withheld_max_arcseconds=float(abs(err).max()),withheld_errors_arcseconds=err.tolist())
    xx,yy=np.meshgrid(np.linspace(lower[0],upper[0],81),np.linspace(lower[1],upper[1],61));grid=np.c_[xx.ravel(),yy.ravel()]
    base=model[0].design(grid)@model[1]*plane_scale
    dx=model[0].design(grid+[[.1,0]])@model[1]*plane_scale-base
    dy=model[0].design(grid+[[0,.1]])@model[1]*plane_scale-base
    det=(dx[:,0]*dy[:,1]-dy[:,0]*dx[:,1])/.01
    trial.update(jacobian_determinant_range=[float(det.min()),float(det.max())],sampled_orientation_consistent=bool(np.all(det<0)))
    corners=predict(model,frame);corners[:,0]-=216.18/3600
    trial['corrected_frame_corners_lonlat']=corners.tolist()
    trial['neighbour_corners']=[]
    # The bulk audit evaluates both transforms along shared edges on the same stations.
    groups=[] if comparison.get('paired_edge_audit') else json.loads((ROOT/'output/atlas-continuity-audit/continuity.json').read_text())['junctions']
    for group in groups:
        own=next((p for p in group['members'] if p['id']==args.sheet),None)
        if own is None:continue
        for other in group['members']:
            if other['id']==args.sheet:continue
            a=corners[['NW','NE','SE','SW'].index(own['corner'])];b=np.array(other['lonlat'])
            delta=np.deg2rad(b-a)*6378137;delta[0]*=np.cos(np.deg2rad((a[1]+b[1])/2))
            trial['neighbour_corners'].append(dict(own_corner=own['corner'],neighbour=other['id'],neighbour_corner=other['corner'],distance_metres=float(np.linalg.norm(delta))))
    print(json.dumps({k:v for k,v in trial.items() if k not in ('loo_errors_pixels','withheld_errors_arcseconds')}),flush=True)

selected=fit(controls,chosen['smoothing']);basis,coef=selected
report=dict(id=args.sheet,status='TPS diagnostic trial; published COG unchanged',source=comparison['source'],source_sha256=comparison['source_sha256'],
    method='Historical projection table plus thin-plate spline in the scan-to-historical-plane direction, with affine tail and minimum-bending-energy penalty. Full crossings constrain both coordinates; margin and internal line observations constrain only their printed coordinate.',
    table=comparison['table'],control_count=len(controls),independent_check_count=len(checks),
    selection=f'Lowest leave-one-observation-out RMS on the {len(controls)} training observations, before evaluating the fixed {len(checks)} withheld observations. No corner or neighbour fitting.',dataset=str(args.dataset.relative_to(ROOT) if args.dataset.is_absolute() else args.dataset),
    kernel_reference='https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html',
    implementation_verification_max_error=verification,penalty_scale=penalty_scale,trials=trials,selected_smoothing=chosen['smoothing'],
    selected_model=dict(pixel_centre=centre.tolist(),pixel_scale=scale,plane_scale=plane_scale,knots=basis.knots.tolist(),kernel_weights=(basis.weights@coef[3:]).tolist(),affine_tail=coef[:3].tolist()),
    limits='Orientation checked on a sampled grid, not a global proof. Near-interpolating smoothing=1e-8 approximates the zero-smoothing minimum-bending solution. Causes of scan distortion are not determined.')
args.output.write_text(json.dumps(report,indent=2)+'\n')
print('SELECTED',chosen['smoothing'],flush=True)
