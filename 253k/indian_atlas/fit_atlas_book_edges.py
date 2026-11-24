"""Batch all four Walker edges for prepared Atlas scans. Run on the raster host.

python fit_atlas_book_edges.py [--jobs 4] [sheet-id ...]
Output models and exceptions are written separately under work/atlas-book-edges.
"""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import re

import cv2
import numpy as np
from scipy.interpolate import interp1d
from scipy.optimize import brentq
from scipy.signal import find_peaks

from atlas_book_frame import SIDES, edge_departures_3857, edge_profile_3857, locate_stripes, printed, rectangle, target
from atlas_frame_crop import measured_frame_crop, straight_frame_crop
from atlas_plate_registration import PlateRegistration
from atlas_stripe_fit import constraints, fit, pixels
from atlas_tps_transform import AtlasTPS
from measure_atlas_frame_pair import trace
from audit_atlas_tps_rollout import ROOT, WORK, OUTPUT, read, write
import georeference_atlas001 as hist

OUT = ROOT/'work/atlas-book-edges'
DEFAULT_EDGE_LIMIT_3857_M = 25.
cv2.setNumThreads(1)


def rms(values):
    return float(np.sqrt(np.mean(np.square(values))))


def curves(marks, ideal, minute, axis, coords):
    sides = ('north','south') if axis==0 else ('west','east')
    a,b = [marks[s][minute] for s in sides]
    t = 1-axis
    ll = np.empty((len(coords),2))
    ll[:,axis],ll[:,t] = minute/60,coords
    p = ideal(ll)
    order = np.argsort(p[:,t])
    shape = interp1d(p[order,t],p[order,axis],bounds_error=False,fill_value='extrapolate')
    da,db = a[axis]-shape(a[t]), b[axis]-shape(b[t])
    return lambda u: shape(u)+da+(u-a[t])/(b[t]-a[t])*(db-da)


def intersections(marks, affine, ll, originals):
    mer = sorted(m for m in marks['north'].keys() & marks['south'].keys() if m%5==0)
    par = sorted(m for m in marks['west'].keys() & marks['east'].keys() if m%5==0)
    if not mer or not par:
        return []
    # Retain balanced spatial sampling on full sheets as well as quarters.
    stride = max(1,int(np.ceil(np.sqrt(len(mer)*len(par)/160))))
    mer,par = mer[::stride],par[::stride]
    coef,centre = np.array(affine['affine_coefficients']),affine['affine_plane_centre_fathoms']
    def ideal(coords):
        return (hist.project(coords)-centre)@coef[1:]/100000+coef[0]
    lat = np.linspace(max(hist.LATS[0],ll[:,1].min()-.1),min(hist.LATS[-1],ll[:,1].max()+.1),100)
    lon = np.linspace(ll[:,0].min()-.1,ll[:,0].max()+.1,100)
    fx = {m:curves(marks,ideal,m,0,lat) for m in mer}
    fy = {m:curves(marks,ideal,m,1,lon) for m in par}
    used = {(round(p['longitude']*60),round(p['latitude']*60)) for p in originals if p['kind']=='crossing'}
    output = []
    for m in mer:
        for n in par:
            if (m,n) in used:
                continue
            x,y = ideal([[m/60,n/60]])[0]
            for _ in range(6):
                x,y = float(fx[m](y)),float(fy[n](x))
            if max(abs(fx[m](y)-x),abs(fy[n](x)-y)) < .02:
                output.append(dict(kind='crossing',longitude=m/60,latitude=n/60,pixel=x,line=y))
    return output


def frame(cfg):
    corners = np.asarray(cfg['frame_corners'],float)
    guides = cfg.get('crop_edge_guides',{})
    if cfg.get('crop_mode')=='straight_corners' or not guides:
        _,edges,ring = straight_frame_crop(corners,0)
        traced = cfg.get('book_frame_normal_sides',[])
        if not traced:
            return corners,edges,ring
        # Replace only the remeasured sides of a corner-to-corner crop.
        guides = {s:guides[s] if s in traced else np.asarray(edges[i]['points'])[:,[i%2,1-i%2]]
                  for i,s in enumerate(SIDES)}
    # Older guides sometimes stop short of the verified common vertices.
    normalized = {}
    for i,s in enumerate(SIDES):
        axis = i%2
        ends = corners[[i,(i+1)%4]][:,[axis,1-axis]]
        lo,hi = ends[np.argsort(ends[:,0])]
        g = np.asarray(guides.get(s,[])).reshape(-1,2)
        interior = g[(g[:,0]>lo[0]+1)&(g[:,0]<hi[0]-1)]
        interior = interior[np.unique(interior[:,0],return_index=True)[1]]
        normalized[s] = np.vstack((lo,interior,hi))
    _,edges,ring = measured_frame_crop(corners,normalized,0)
    return corners,edges,ring


def constrain_traced_edges(model, edges, nominal, offset, limit, knots, ref, probe, refit):
    """Add cross-edge constraints on measured rules where the TPS misses Walker."""
    controls = []
    for _ in range(16):
        additions = []
        for edge in edges:
            side = edge['side']
            axis = SIDES.index(side)%2
            xy,along,curve,error = edge_profile_3857(edge,nominal,offset,lambda p: hist.inverse(model(p)))
            if np.any(np.diff(along)*(-1 if axis else 1)<=0):
                raise ValueError(f'Traced {side} edge reverses along its coordinate axis')
            if max(abs(error))<=limit:
                continue
            peaks = find_peaks(abs(error),height=limit,distance=5)[0]
            plane = hist.project(curve)
            for k in sorted(peaks,key=lambda k:-abs(error[k]))[:16]:
                if np.min(np.linalg.norm(knots-xy[k],axis=1))<.5:
                    continue
                # Estimate the local direction in the actual fitted historical
                # plane. Walker's curve is sampled at four scan pixels or finer.
                j = np.clip(curve[:,axis].searchsorted(along[k]),1,len(curve)-1)
                tangent = plane[j]-plane[j-1]
                normal = np.array([-tangent[1],tangent[0]])/np.linalg.norm(tangent)
                additions.append(dict(side=side,pixel=xy[k,0],line=xy[k,1],plane_normal=normal.tolist(),
                                      normal_fathoms=float(plane[j]@normal)))
            if not any(p['side']==side for p in additions):
                raise ValueError(f'No distinct frame measurement resolves the residual on {side}')
        if not additions:
            fitted = AtlasTPS(model.parameters,ref)
            if not np.all(np.linalg.det(fitted.forward(probe,True)[1])<0):
                raise ValueError('Frame-normal constraints fold the fitted sheet')
            for edge in edges:
                xy = edge_profile_3857(edge,nominal,offset,lambda p: hist.inverse(model(p)))[0]
                inward = np.array([[0,1],[-1,0],[0,-1],[1,0]])[SIDES.index(edge['side'])]
                for distance in (0,8,32,128):
                    for chunk in np.array_split(xy+inward*distance,max(1,len(xy)//512)):
                        if np.any(np.linalg.det(fitted.forward(chunk,True)[1])>=0):
                            raise ValueError('Frame-normal constraints fold the scan near its edge')
            return model,controls
        controls.extend(additions)
        knots = np.vstack((knots,pixels(additions)))
        model = refit(controls)
    raise ValueError('Traced frame did not reach the Walker tolerance')


def fit_sheet(sid):
    base = WORK/sid
    ds = read(base/'dataset.json')
    folder = OUT/sid
    cfg = read(ROOT/ds['frame_config'])
    if sid.endswith('-part'):
        raise ValueError('Surviving strip has no complete nominal rectangle')
    for name in ('tps-west-longitudes.json','tps-stripe-weighted.json','tps.json'):
        prior_path = base/name
        if prior_path.exists():
            prior = read(prior_path)
            observations = read(ROOT/prior['dataset'])
            if (prior['source_sha256']==ds['source_sha256']
                    and observations.get('input_signature')==ds.get('input_signature')):
                ds = observations
                break
    else:
        raise ValueError('Rebuild the baseline for the current source and observations')
    ref = read(ROOT/ds['affine_reference'])
    src = ROOT/ds['source']
    table = read(ROOT/ds['table'])
    hist.LATS,hist.RADII,hist.ANGLES = [np.array(table[k]) for k in
        ('latitudes','radius_fathoms','angle_arcseconds_per_longitude_degree')]
    hist.R0 = table['reference_radius_fathoms']
    raw,edges,ring = frame(cfg)
    off = cfg.get('frame_pixel_offset',.5)
    corners = raw+off
    coef = np.asarray(ref['affine_coefficients'])
    def affine(p):
        return (p-coef[0])@np.linalg.inv(coef[1:])*100000+ref['affine_plane_centre_fathoms']
    match = re.search(r'-(nw|ne|sw|se)-',sid)
    nominal,cell = rectangle(affine(corners), cfg.get('quarter') or (match[1].upper() if match else None))
    lonlat = printed(nominal)
    registration = None
    if cfg.get('register_native_graticule_to_book_frame'):
        # The affine is estimated from the source training observations.
        # Use its four corner differences to relate the two coordinate frames.
        native_corners = np.asarray(cfg['measured_native_corners'],float) if 'measured_native_corners' in cfg else hist.inverse(affine(corners))
        if native_corners.shape!=(4,2) or not np.isfinite(native_corners).all():
            raise ValueError('Invalid source graticule corner measurements')
        registration = PlateRegistration(corners, native_corners, lonlat)
    def frame_target(side, minute, pixel):
        if registration is not None:
            minute += 60 * registration.offset(pixel)[0, SIDES.index(side) % 2]
        return target(nominal, side, minute)
    reference = AtlasTPS(prior['selected_model'],ref).forward
    def baseline(array_indices):
        return hist.inverse(reference(array_indices+off))
    flags = cv2.IMREAD_GRAYSCALE | (cv2.IMREAD_IGNORE_ORIENTATION if cfg.get('ignore_exif_orientation') else 0)
    gray = cv2.imread(str(src),flags)
    if gray is None or list(gray.shape[::-1])!=ref['source_size']:
        raise ValueError('Source shape differs from the calibrated scan')
    marks,diagnostics = {},{}
    for i,e in enumerate(edges):
        s = e['side']
        edge = np.array(e['points'])
        predict = baseline
        if cfg.get('decode_stripes_from_numbered_ticks'):
            axis = i%2
            ticks = [p for p in ds['controls'] if p.get('side')==s and p['kind']=='margin_tick']
            if len(ticks)<2:
                raise ValueError('Too few measured training ticks to number the '+s+' stripes')
            observations = pixels(ticks)-off
            tick_stations = observations[:,axis]
            residual = np.array([p['known_value'] for p in ticks])-baseline(observations)[:,axis]
            order = np.argsort(tick_stations)
            def predict(array_indices):
                result = baseline(array_indices)
                result[:,axis] += np.interp(array_indices[:,axis],tick_stations[order],residual[order])
                return result
        try:
            points,diagnostics[s] = locate_stripes(gray,edge,s,predict)
        except ValueError as exc:
            # Faded or interrupted sections can defeat a full-edge profile.
            axis = SIDES.index(s)%2
            ordered = edge[np.argsort(edge[:,axis])]
            stations = np.linspace(*ordered[[0,-1],axis],9)
            points,parts = {},[]
            for first,last in zip(stations[::2],stations[2::2]):
                u = np.linspace(first,last,40)
                arr = np.empty((len(u),2))
                arr[:,axis],arr[:,1-axis] = u,np.interp(u,ordered[:,axis],ordered[:,1-axis])
                try:
                    found,meta = locate_stripes(gray,arr,s,predict)
                    points.update(found)
                    parts.append(meta)
                except ValueError:
                    continue
            diagnostics[s] = dict(parts=parts,step_minutes=min((p['step_minutes'] for p in parts),default=1),
                                  reason=str(exc),transitions=len(points))
            if len(points)<15:
                # A straight seed can miss the ruler on a bowed scan. Track its
                # two parallel rules and accept the path only if more labelled
                # transitions are actually visible there.
                for band in (18,24,12):
                    try:
                        g,_ = trace(gray,raw[i],raw[(i+1)%4],i,band)
                        path = np.asarray(g)
                        if i%2: path=path[:,::-1]
                        recovered,quality = locate_stripes(gray,path,s,predict)
                    except (ValueError,IndexError):
                        continue
                    if len(recovered)>len(points) and quality['polarity_agreement']>=.75:
                        points = recovered
                        diagnostics[s] = dict(quality,frame_trace_band=band)
                        e['points']=(path if i<2 else path[::-1]).tolist()
                        break
        marks[s] = {m:p+off for m,p in points.items()}
    if any('frame_trace_band' in v for v in diagnostics.values()):
        ring = [p for e in edges for p in e['points'][:-1]]+[edges[0]['points'][0]]
    del gray
    measured,checks = ds['controls'],ds['checks']
    fixed = [dict(kind='crossing',pixel=p[0],line=p[1],longitude=q[0],latitude=q[1],side='corner') for p,q in zip(corners,lonlat)]
    held = []
    for i,s in enumerate(SIDES):
        reserved = {round(p['known_value']*60) for p in checks if p.get('side')==s}
        measured_minutes = {round(p['known_value']*60) for p in measured if p.get('side')==s}
        step = diagnostics[s].get('step_minutes',1)
        selected,spare = [],[]
        for m,p in sorted(marks[s].items()):
            if m in reserved or (step==1 and m in measured_minutes):
                continue
            ll = frame_target(s,m,p)
            if ll is None:
                continue
            # A mark almost coincident with a corner amplifies even a one-pixel
            # measurement discrepancy into a sharp local stretch.
            nearest = min(np.linalg.norm(p-corners[i]),np.linalg.norm(p-corners[(i+1)%4]))
            size_minutes = abs(lonlat[i,i%2]-lonlat[(i+1)%4,i%2])*60
            if nearest < .4*np.linalg.norm(corners[i]-corners[(i+1)%4])/size_minutes:
                continue
            rec = dict(kind='crossing',pixel=p[0],line=p[1],longitude=ll[0],latitude=ll[1],minute=m,side=s)
            if (step==1 and m%5==3) or (step>1 and m//step%3!=1):
                selected.append(rec)
            elif ((step==1 and m%5==1) or step>1) and m not in measured_minutes:
                spare.append(rec)
        fixed.extend(selected)
        axis=i%2
        span=abs(lonlat[i,axis]-lonlat[(i+1)%4,axis])*60
        if len(selected)<2 or np.ptp([p['minute'] for p in selected])/span<.5:
            # Some old frames are only legible in stretches. Use independently
            # measured training ticks elsewhere on the same margin, carrying
            # the measured rule slope from its margin observation to the frame.
            edge=np.asarray(edges[i]['points'])+off
            edge=edge[np.argsort(edge[:,axis])]
            taken={p['minute'] for p in selected}
            supplementary=[]
            for obs in measured:
                if obs.get('side')!=s or obs['kind']!='margin_tick' or obs.get('line_slope') is None: continue
                m=round(obs['known_value']*60)
                if m in taken or m in reserved or abs(obs['known_value']*60-m)>1e-6: continue
                uv=np.array([obs['pixel'],obs['line']])
                def residual(u):
                    v=np.interp(u,edge[:,axis],edge[:,1-axis])
                    return u-uv[axis]-obs['line_slope']*(v-uv[1-axis])
                lo,hi=edge[[0,-1],axis]
                if residual(lo)*residual(hi)>=0: continue
                u=brentq(residual,lo,hi)
                p=uv.copy()
                p[axis],p[1-axis]=u,np.interp(u,edge[:,axis],edge[:,1-axis])
                ll=frame_target(s,m,p)
                if ll is None: continue
                if np.linalg.norm(p-uv)<.5 or min(u-lo,hi-u)<.4*(hi-lo)/span: continue
                supplementary.append(dict(kind='crossing',pixel=p[0],line=p[1],longitude=ll[0],
                                          latitude=ll[1],minute=m,side=s,provenance='numbered training tick'))
                taken.add(m)
            fixed.extend(supplementary)
            selected.extend(supplementary)
            diagnostics[s]['numbered_tick_supplements']=len(supplementary)
        held.extend(spare)
        diagnostics[s].update(anchors=len(selected),withheld_bands=len(spare))
    partial = [s for s in SIDES if diagnostics[s]['anchors']<2]
    if partial:
        return dict(status='review',reason='Insufficient decoded edge controls',edges=diagnostics,cell=cell)
    derived = prior.get('derived_controls')
    if derived is None:
        source_marks = marks
        excluded_crossings = measured
        if cfg.get('decode_stripes_from_numbered_ticks'):
            source_marks = {s:{m:p for m,p in points.items() if m not in {
                round(c['known_value']*60) for c in checks if c.get('side')==s}}
                for s,points in marks.items()}
            excluded_crossings = measured + [c for c in checks if c['kind']=='crossing']
        derived = intersections(source_marks,ref,lonlat,excluded_crossings)
    weight = prior.get('derived_scalar_weight',len(constraints(measured)[0])/max(2*len(derived),1))
    source_derived = derived
    if registration is not None:
        measured = registration.controls(measured)
        derived = registration.controls(derived)
    probe = np.vstack((corners,pixels(fixed),np.array(ring)+off,
                       np.array(np.meshgrid(*[np.linspace(min(x),max(x),21) for x in corners.T])).reshape(2,-1).T))
    smoothing = prior['selected_smoothing']
    edge_limit = cfg.get('book_edge_max_departure_3857_m',DEFAULT_EDGE_LIMIT_3857_M)
    strengths = {max(smoothing,s) for s in (0,1e-6,1e-4,.001,.01,.1,1.,10.)}
    candidates = []
    for strength in sorted(strengths):
        model = fit(measured+derived,len(measured),weight,'tps',affine,strength,
                    np.array(ref['source_size']),fixed_corners=fixed)
        fitted = AtlasTPS(model.parameters,ref)
        if not np.all(np.linalg.det(fitted.forward(probe,True)[1])<0):
            continue
        departures = edge_departures_3857(edges,nominal,off,lambda p: hist.inverse(model(p)))
        peak = max(departures.values())
        candidates.append((peak,strength,model,departures))
        if peak <= edge_limit:
            break
    if not candidates:
        raise ValueError('Fixed frame targets fold the scan at all tested TPS smoothing levels')
    # If the frame cannot reach tolerance, avoid extra bending penalty for an
    # improvement smaller than a quarter of the allowed output-pixel error.
    minimum = min(item[0] for item in candidates)
    ceiling = edge_limit if minimum <= edge_limit else minimum + .25*edge_limit
    peak,strength,model,departures = next(item for item in candidates if item[0]<=ceiling)
    normals = []
    traced = cfg.get('book_frame_normal_sides',[])
    if traced:
        if not set(traced)<=set(SIDES) or any(not cfg.get('crop_edge_guides',{}).get(s) for s in traced):
            raise ValueError('Frame-normal controls require measured guides on each requested side')
        model,normals = constrain_traced_edges(model,[e for e in edges if e['side'] in traced],
            nominal,off,cfg.get('book_frame_normal_tolerance_3857_m',edge_limit),pixels(measured+derived+fixed),ref,probe,
            lambda cs:fit(measured+derived,len(measured),weight,'tps',affine,strength,
                          np.array(ref['source_size']),fixed_corners=fixed,frame_normals=cs))
        departures = edge_departures_3857(edges,nominal,off,lambda p: hist.inverse(model(p)))
    if np.max(abs(hist.inverse(model(pixels(fixed)))-np.array([[p['longitude'],p['latitude']] for p in fixed])))>1e-8:
        raise ValueError('Fixed targets missed in fitted transform')
    rows,axes,values = constraints(checks)
    def errors(fn):
        return (hist.inverse(fn(pixels(checks)))[rows,axes]-values)*3600
    before,after = errors(reference),errors(model)
    for s in SIDES:
        h = [p for p in held if p['side']==s]
        if h:
            axis = SIDES.index(s)%2
            expected = np.array([p['minute']/60 for p in h])
            if registration is not None:
                expected += registration.offset(pixels(h))[:,axis]
            diagnostics[s]['band_check_rms_arcseconds'] = rms(
                (hist.inverse(model(pixels(h)))[:,axis]-expected)*3600)
    # A deliberately extended map has a different display cutline from its
    # theoretical frame. Carry the existing reviewed extension into the raster.
    extended = any('extend' in r.get('reason','').lower() and 'map' in r.get('reason','').lower()
                   for segments in cfg.get('crop_edge_manual_segments',{}).values() for r in segments)
    if extended:
        ring = read(OUTPUT/sid/'crop-boundary.json')['ring_pixels']
    report = dict(id=sid,source=ds['source'],source_sha256=ds['source_sha256'],dataset=prior['dataset'],
                  table=ds['table'],affine_reference=ds['affine_reference'],frame_config=ds['frame_config'],
                  frame_offset=off,crop_ring=ring,source_size=ref['source_size'],ignore_exif_orientation=cfg.get('ignore_exif_orientation',False),
                  cell=cell,display_uses_reviewed_extension=extended,selected_model=model.parameters,selected_smoothing=strength,
                  baseline=prior_path.name,fixed_controls=fixed,derived_controls=derived,derived_scalar_weight=weight,
                  withheld_band_controls=held,edges=diagnostics,withheld_errors_arcseconds=after.tolist(),
                  previous_withheld_rms_arcseconds=rms(before),withheld_rms_arcseconds=rms(after))
    if registration is not None:
        intrinsic = after - registration.offset(pixels(checks))[rows,axes]*3600
        report['plate_registration'] = dict(
            method='Bilinear interpolation of native training-affine to Walker differences at the four measured corners.',
            order=['NW','NE','SE','SW'],native_corners=native_corners.tolist(),book_corners=lonlat.tolist(),
            corner_offsets_arcseconds=(registration.corner_offsets*3600).tolist(),
            source_derived_controls=source_derived,
            native_frame_withheld_errors_arcseconds=intrinsic.tolist(),
            native_frame_withheld_rms_arcseconds=rms(intrinsic),
            mosaic_minus_printed_withheld_rms_arcseconds=rms(after))
        if 'measured_native_corners' in cfg:
            report['plate_registration'].update(method='Bilinear registration from native corner coordinates measured on adjacent printed minute bands to Walker frame corners.',
                                                corner_measurements=cfg['native_corner_evidence'])
    margin_file = ROOT/'data'/f'{sid}-margin.json'
    if margin_file.exists():
        from atlas_margin_extensions import resolve
        rule = read(margin_file)
        if rule['source_sha256'] != ds['source_sha256']:
            raise ValueError('Margin trace belongs to a different scan')
        published = {}
        if rule['policy'] == 'where_uncovered':
            review = OUTPUT/'atlas-book-edges'
            inventory = read(review/'report.json')['sheets']
            published = {s['id']:inventory[s['id']]['cell'] for s in read(review/'sheets.json')}
        polygons, evidence = resolve(rule,ring,cell,AtlasTPS(model.parameters,ref),off,published)
        report['margin_extension'] = evidence
        if evidence['retained_extra_source_pixels'] > 0.5:
            report['display_polygons'] = polygons
            report['display_uses_reviewed_extension'] = True
    report['edge_max_departure_3857_m'] = departures
    if normals:
        report['frame_normal_controls'] = normals
    paths = {}
    for i,e in enumerate(edges):
        p = np.array(e['points'])+off
        t = np.linspace(0,len(p)-1,201)
        p = np.column_stack([np.interp(t,np.arange(len(p)),v) for v in p.T])
        paths[e['side']] = {k:hist.inverse(fn(p)).tolist() for k,fn in [('prior',reference),('fit',model)]}
    write(folder/'model.json',report)
    write(folder/'paths.json',paths)
    return dict(status='fitted',cell=cell,edges=diagnostics,withheld=rms(after),previous=rms(before),
                edge_max_departure_3857_m=departures,edge_limit_3857_m=edge_limit,
                checks=len(after),fixed=len(fixed),derived=len(derived))


def process(sid):
    folder = OUT/sid
    folder.mkdir(exist_ok=True,parents=True)
    try:
        result = fit_sheet(sid)
    except (ValueError,KeyError,FileNotFoundError,AssertionError,np.linalg.LinAlgError) as exc:
        result = dict(status='review',reason=f'{type(exc).__name__}: {exc}')
    write(folder/'status.json',dict(id=sid,**result))
    print(sid,result['status'],result.get('reason',''),flush=True)
    return result['status']


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sheets',nargs='*')
    parser.add_argument('--jobs',type=int,default=3)
    args = parser.parse_args()
    sheets = args.sheets or sorted(p.parent.name for p in WORK.glob('*/dataset.json'))
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(process,sheets))
