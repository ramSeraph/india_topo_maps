"""Walker's plate lattice and detection of numbered broad frame divisions."""
import math

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import brentq
from scipy.signal import find_peaks


SIDES = ('north', 'east', 'south', 'west')
# 1902 Tables, PDF pp. 4–8. Radii on 76°30′ E at successive 86-minute belts.
RADII = np.array([8757874,8671211,8584541,8497865,8411182,8324483,8237777,8151076,
                  8064362,7977622,7890870,7804104,7717322,7630526,7543714,7456886,
                  7370039,7283174,7196291,7109389,7022469,6935526])
LATS = (386 + 86*np.arange(len(RADII)))/60
# Page 4 angles per longitude degree, in arcseconds, for latitudes 6 through 37.
ANGLES = np.r_[23*60+np.array([41.24,48.26,54.94]),24*60+np.array([
    1.30,7.30,12.94,18.22,23.12,27.66,31.82,35.60,38.96,41.94,44.52,46.68,
    48.42,49.72,50.58,51.02,51.02,50.54,49.60,48.20,46.32,43.94,41.08,
    37.72,33.84,29.46,24.54,19.10,13.10])]
R0 = 7331657.
# At the south edge of the last belt, off-meridian corners fall just below
# 6°26′. Walker's 6° radius on PDF page 9 brackets those points.
INTERPOLATION_RADII = np.r_[8784123.3,RADII]
INTERPOLATION_LATS = np.r_[6.,LATS]
YS = np.empty(2*len(RADII)-1)
YS[::2] = R0-RADII
YS[1::2] = (YS[:-1:2]+YS[2::2])/2


def printed(xy):
    x,y = np.asarray(xy,float).T
    radius = np.hypot(x,R0-y)
    if np.any((radius<RADII[-1])|(radius>INTERPOLATION_RADII[0])):
        raise ValueError('Corner outside Walker governing-radius table')
    lat = np.interp(radius,INTERPOLATION_RADII[::-1],INTERPOLATION_LATS[::-1])
    angle = np.interp(lat,np.arange(6,38),ANGLES)
    return np.stack((76.5+np.degrees(np.arctan2(x,R0-y))*3600/angle,lat),axis=-1)


def rectangle(plane, quarter):
    gx = np.rint((plane[:,0]+37100)/67425).astype(int)
    gy = np.abs(YS[:,None]-plane[:,1]).argmin(axis=0)
    w,e,_,_ = gx
    n,_,s,_ = gy
    span = 1 if quarter else 2
    if not (list(gx)==[w,e,e,w] and list(gy)==[n,n,s,s] and e-w==n-s==span):
        raise ValueError('Measured frame does not identify a complete nominal rectangle')
    if (w%2,s%2) != ((int('E' in quarter),int('N' in quarter)) if quarter else (0,0)):
        raise ValueError('Measured lattice position disagrees with sheet quarter')
    corners = np.c_[-37100+67425*gx,YS[gy]]
    if np.max(abs((plane-corners)/[67425,43400]))>.25:
        raise ValueError('Measured corner is ambiguous on the quarter-sheet lattice')
    return corners, [int(w),int(s),int(e),int(n)]


def target(corners, side, minute):
    i = SIDES.index(side)
    a,b = corners[i],corners[(i+1)%4]
    if i%2:
        latitude = minute/60
        radius = np.interp(latitude,INTERPOLATION_LATS,INTERPOLATION_RADII)
        xy = [a[0], R0-math.sqrt(radius**2-a[0]**2)]
        if not min(a[1],b[1]) < xy[1] < max(a[1],b[1]):
            return None
    else:
        lo,hi = sorted([a[0],b[0]])
        if not printed([lo,a[1]])[0] < minute/60 < printed([hi,a[1]])[0]:
            return None
        x = brentq(lambda x:printed([x,a[1]])[0]-minute/60,lo,hi)
        xy = [x,a[1]]
    ll = printed(xy)
    if abs(ll[i%2]-minute/60)>1e-9:
        raise ValueError('Stripe target failed longitude/latitude round trip')
    return ll


def edge_profile_3857(edge, corners, offset, pixel_to_printed):
    """Sample the source rule and its displacement from Walker at matching lon/lat."""
    i = SIDES.index(edge['side'])
    axis = i % 2
    pts = np.asarray(edge['points'])
    pts = pts[np.argsort(pts[:, axis])]
    lo, hi = pts[[0, -1], axis]
    u = np.union1d(pts[:, axis], np.linspace(lo, hi, int(np.ceil((hi-lo)/4))+1))
    xy = np.empty((len(u), 2))
    xy[:, axis] = u
    xy[:, 1-axis] = np.interp(u, pts[:, axis], pts[:, 1-axis])
    xy += offset
    along, across = pixel_to_printed(xy)[:, [axis, 1-axis]].T
    nominal = printed(np.linspace(corners[i], corners[(i+1)%4], len(u)))
    nominal = nominal[np.argsort(nominal[:, axis])]
    expected = np.interp(along, nominal[:, axis], nominal[:, 1-axis])
    a, b = np.deg2rad([across, expected])
    if axis == 0:
        a, b = np.arcsinh(np.tan([a, b]))
    return xy, along, nominal, 6378137*(a-b)


def edge_departures_3857(edges, corners, offset, pixel_to_printed):
    """Check the fitted inner frame against Walker between the fixed marks."""
    return {e['side']: float(np.max(np.abs(edge_profile_3857(e,corners,offset,pixel_to_printed)[3])))
            for e in edges}


def locate_stripes(gray, edge, side, predict):
    """Find alternating filled/empty intervals; test several band widths and depths.

    The previous fit resolves whole-minute labels. Measure positions on native
    pixels and reject weak transitions and labels too close to a competing mark.
    """
    i = SIDES.index(side)
    axis = i%2
    sign = (-1,1,1,-1)[i]
    guide = edge[:,[axis,1-axis]]
    guide = guide[np.argsort(guide[:,0])]
    u = np.arange(math.ceil(guide[0,0])+2, math.floor(guide[-1,0])-1)
    v = np.interp(u,*guide.T)
    def pixels(along,across):
        return np.c_[along,across] if axis==0 else np.c_[across,along]
    subset = np.unique(np.r_[np.arange(0,len(u),40),len(u)-1])
    # Coordinates here are image-array indices, while predict uses the GCP pixel convention.
    minute = predict(pixels(u[subset],v[subset]))[:,axis]*60
    if not np.all(np.diff(minute)*(-1 if axis else 1)>0):
        raise ValueError('Prior graticule reverses along the frame')
    def position(m):
        return np.interp(m,minute[::-1],u[subset][::-1]) if axis else np.interp(m,minute,u[subset])
    pitch = abs((u[-1]-u[0])/(minute[-1]-minute[0]))
    lo,hi = sorted(minute[[0,-1]])
    img = gray if axis==0 else gray.T
    best = None
    for step in (1,5,2,10):
        labels = np.arange(math.ceil((lo+.38*step)/step),math.floor((hi-.38*step)/step)+1)*step
        if len(labels)<5:
            continue
        predicted = position(labels)
        half = max(3, int(.28*pitch*step))
        kernel = np.arange(-half,half+1)
        idx = np.rint(predicted-u[0]).astype(int)[:,None]+kernel
        if idx.min()<0 or idx.max()>=len(u):
            continue
        flank = max(2, round(.15*pitch*step))
        # A broad alternating band reverses polarity at every successive transition.
        parity = np.where(labels//step%2==0,1,-1)
        for depth in range(3,48,2):
            vv = np.rint(v).astype(int)+sign*depth
            if vv.min()<2 or vv.max()>=img.shape[0]-2:
                continue
            signal = np.median(img[vv[:,None]+[-1,0,1],u[:,None]],axis=1)
            smooth = gaussian_filter1d(signal,1.3)
            delta = smooth[np.minimum(idx+flank,len(u)-1)]-smooth[np.maximum(idx-flank,0)]
            centre_delta = np.median(delta[:,half-1:half+2],axis=1)
            phase = np.sign(np.median(centre_delta*parity))
            contrast = phase*parity*centre_delta
            fraction = np.mean(contrast>22)
            # An odd multiple of the true pitch can also alternate at its ends.
            # Check that the interior of each purported block has one polarity.
            broad = []
            centre = idx[:,half]
            for f in (.22,.32,.42):
                shift = round(f*pitch*step)
                delta_f = smooth[np.minimum(centre+shift,len(u)-1)]-smooth[np.maximum(centre-shift,0)]
                broad.append(phase*parity*delta_f)
            plateau = np.median(np.min(broad,axis=0))
            score = fraction*max(0,min(np.median(contrast),plateau))
            if score<18 or (best and score<=best[0]):
                continue
            grad = gaussian_filter1d(signal,1.45,order=1)
            signed = grad[idx]*(phase*parity)[:,None]
            peak = np.argmax(signed,axis=1)
            best = score,step,depth,labels,idx,peak,signed,contrast,fraction
    positions = {}
    if best is None or best[-1]<.62:
        # Older engraved bands can be systematically displaced from the prior
        # transform. Detect the entire periodic train first, then resolve its
        # minute labels. Check alternation, pitch and absolute phase separately.
        winner = 0
        for d in range(3,46,2):
            vv = np.rint(v).astype(int)+sign*d
            if vv.min()<2 or vv.max()>=img.shape[0]-2: continue
            signal = np.median(img[vv[:,None]+[-1,0,1],u[:,None]],axis=1)
            grad = gaussian_filter1d(signal,3.,order=1)
            peaks = find_peaks(abs(grad),height=3.5,distance=max(2,.70*pitch))[0]
            peaks = peaks[(peaks>=2)&(peaks<len(u)-2)]
            if len(peaks)<.88*(hi-lo) or len(peaks)<5: continue
            q = np.interp(u[peaks],u[subset],minute)
            labels = np.rint(q).astype(int)
            if (np.max(abs(q-labels))>.46 or not np.all(abs(np.diff(labels))==1)
                    or not np.all(grad[peaks][1:]*grad[peaks][:-1]<0)
                    or np.max(abs(np.diff(peaks)/pitch-1))>.22):
                continue
            strength = np.median(abs(grad[peaks]))
            if strength>winner:
                winner,depth = strength,d
                positions = {int(m):np.average(u[k-2:k+3],weights=abs(grad[k-2:k+3]))
                             for m,k in zip(labels,peaks)}
        if not positions: raise ValueError('No broad alternating band with consistent graticule labels')
        step,score,fraction = 1,winner,1.
    else:
        score,step,depth,labels,idx,peak,signed,contrast,fraction = best
        for k,m in enumerate(labels):
            j = peak[k]
            if j<2 or j+2>=signed.shape[1] or signed[k,j]<8 or contrast[k]<18:
                continue
            positions[m] = np.average(u[idx[k,j-2:j+3]],weights=np.maximum(signed[k,j-2:j+3],0))
    found = {}
    for m,pos in positions.items():
        # Estimate the printed rule direction locally, then carry the band onto
        # the inner frame. Only the direction comes from the previous fit.
        cross = np.interp(pos,*guide.T)
        probe = pixels(np.array([pos,pos+1,pos]),np.array([cross,cross,cross+1]))
        z,z_u,z_v = predict(probe)[:,axis]
        slope = -(z_v-z)/(z_u-z)
        src = pos
        for _ in range(3):
            src = pos+slope*(np.interp(src,*guide.T)-cross-sign*depth)
        if guide[0,0]<src<guide[-1,0]:
            found[int(m)] = pixels([src],[np.interp(src,*guide.T)])[0]
    return found, dict(step_minutes=step,offset_px=depth,polarity_agreement=float(fraction),
                       contrast_score=float(score),transitions=len(found))
