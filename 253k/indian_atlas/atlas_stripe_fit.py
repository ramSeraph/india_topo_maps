"""Compare the published fits with fits augmented by frame-derived intersections."""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
import csv
from pathlib import Path

import numpy as np
from scipy.linalg import null_space
from scipy.optimize import least_squares
from scipy.spatial.distance import cdist

import georeference_atlas001 as hist
from atlas_tps_transform import AtlasTPS
from audit_atlas_tps_rollout import read

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'output'
def pixels(records):
    return np.array([[p['pixel'], p['line']] for p in records])

def constraints(records):
    rows, axes, values = [], [], []
    for i, p in enumerate(records):
        items = enumerate((p['longitude'],p['latitude'])) if p['kind']=='crossing' else [
            (int(p['known_axis']=='latitude'),p['known_value'])]
        for axis, value in items:
            rows.append(i)
            axes.append(axis)
            values.append(value)
    return np.array(rows), np.array(axes), np.array(values)

def fit(records, original_count, weight, method, reference, smoothing, size, *, fixed_corners=(), frame_normals=()):
    xy = pixels(records)
    centre, scale = size/2, max(size)/2
    knot_pixels = np.vstack((xy, pixels(fixed_corners))) if fixed_corners else xy
    if frame_normals:
        if not fixed_corners:
            raise ValueError('Frame directions require a registered frame')
        knot_pixels = np.vstack((knot_pixels, pixels(frame_normals)))
    knots = (knot_pixels-centre)/scale
    def kernel(uv):
        r2 = cdist(uv,knots,'sqeuclidean')
        return .5*r2*np.log(np.maximum(r2,1e-300))
    def tail(uv):
        return np.column_stack((np.ones(len(uv)),uv))
    if method=='tps':
        z = null_space(tail(knots).T)
        eig,vec = np.linalg.eigh(z.T@kernel(knots)@z)
        assert eig.min()>0
        weights = (z@vec)/np.sqrt(eig)
    def design(coords):
        uv = (coords-centre)/scale
        return np.column_stack((tail(uv),kernel(uv)@weights)) if method=='tps' else tail(uv)
    d = design(xy)
    rows,axes,values = constraints(records)
    multiplier = np.where(rows<original_count,1.,np.sqrt(weight))
    n = d.shape[1]
    reg = np.zeros((2*(n-3),2*n))
    reg[:,6:] = np.eye(2*(n-3))*6000*np.sqrt(smoothing)
    start = np.zeros((n,2))
    start[:3] = np.linalg.lstsq(d[:,:3],reference(xy)/100000,rcond=None)[0]
    def objective(flat):
        ll = hist.inverse(d@flat.reshape(n,2)*100000)
        return np.r_[(ll[rows,axes]-values)*3600*multiplier,reg@flat]
    def jacobian(flat):
        plane = d@flat.reshape(n,2)*100000
        ll = hist.inverse(plane)
        grad = np.stack([(hist.inverse(plane+offset)-ll)/.01 for offset in ([.01,0],[0,.01])],axis=2)
        jac = np.einsum('ij,ik->ijk',d[rows],grad[rows,axes,:]).reshape(len(rows),2*n)
        return np.vstack((jac*(3600*100000*multiplier[:,None]),reg))
    initial = start.ravel()
    residual, jac = objective, jacobian
    if fixed_corners:
        # Eliminate the corner equations in the projection plane. The remaining
        # coefficients can vary freely while the corner positions stay exact.
        corner_design = design(pixels(fixed_corners))
        targets = hist.project([[p['longitude'], p['latitude']] for p in fixed_corners])/100000
        particular, _, rank, _ = np.linalg.lstsq(corner_design, targets, rcond=None)
        if rank < len(fixed_corners):
            raise ValueError('Dependent fixed corner constraints')
        basis = np.kron(null_space(corner_design), np.eye(2))
        origin = particular.ravel()
        if frame_normals:
            # Each measured frame point supplies one scalar equation n·F(p)=c.
            # The along-edge coordinate remains free in the reduced system.
            normals = np.asarray([p['plane_normal'] for p in frame_normals])
            limits = np.asarray([p['normal_fathoms'] for p in frame_normals])/100000
            equations = (design(pixels(frame_normals))[:,:,None]*normals[:,None,:]).reshape(len(normals),2*n)
            reduced = equations@basis
            shift, _, rank, _ = np.linalg.lstsq(reduced,limits-equations@origin,rcond=None)
            if rank != len(normals):
                raise ValueError('Dependent frame-normal constraints')
            origin = origin+basis@shift
            basis = basis@null_space(reduced)
        initial = basis.T @ (initial-origin)
        def residual(reduced):
            return objective(origin+basis@reduced)
        def jac(reduced):
            return jacobian(origin+basis@reduced)@basis
    result = least_squares(residual,initial,jac=jac,method='lm',
                           ftol=1e-11,xtol=1e-11,gtol=1e-9)
    assert result.success
    solution = origin+basis@result.x if fixed_corners else result.x
    coef = solution.reshape(n,2)
    if fixed_corners and not np.allclose(corner_design@coef, targets, rtol=0, atol=1e-10):
        raise ValueError('TPS solution missed a fixed corner')
    if frame_normals and not np.allclose(equations@solution,limits,rtol=0,atol=1e-10):
        raise ValueError('TPS solution missed a measured frame direction')
    def forward(coords):
        return design(coords)@coef*100000
    if method == 'tps':
        forward.parameters = dict(pixel_centre=centre.tolist(),pixel_scale=float(scale),plane_scale=100000,
                                  knots=knots.tolist(),kernel_weights=(weights@coef[3:]).tolist(),
                                  affine_tail=coef[:3].tolist())
    return forward

def load_published(s):
    old = read(OUTPUT/s/'fit-report.json')
    c = np.array(old['affine_coefficients'])
    tps = AtlasTPS(read(OUTPUT/(s+'-tps-trial')/'fit-report.json')['selected_model'],old)
    def affine(xy):
        return (xy-c[0])@np.linalg.inv(c[1:])*100000+old['affine_plane_centre_fathoms']
    return {'affine':affine,'tps':tps.forward}

def stripe_controls(s, data):
    originals = {(round(p['longitude']*60),round(p['latitude']*60)) for p in data if p['kind']=='crossing'}
    added = []
    with (ROOT/'work'/s/'stripe-derived-gcps.csv').open() as f:
        for r in csv.DictReader(f):
            lon, lat = float(r['printed_longitude']),float(r['printed_latitude'])
            if r['construction']=='table_curve' and (round(lon*60),round(lat*60)) not in originals:
                added.append(dict(kind='crossing',longitude=lon,latitude=lat,
                                  pixel=float(r['estimated_pixel']),line=float(r['estimated_line'])))
    weight = len(constraints(data)[0])/(2*len(added))
    return added, weight
