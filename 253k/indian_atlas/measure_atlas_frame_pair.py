"""Estimate a bowed neatline from both parallel rules around the striped band.

Write a candidate configuration for inspection. Inputs remain unchanged.
"""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter


def trace(gray, a, b, side, band, search_radius=44):
    axis = side % 2
    sign = (1, -1, -1, 1)[side]
    start, stop = sorted((a[axis], b[axis]))
    stations = np.linspace(start+28,stop-28,round((stop-start)/45)).round().astype(int)
    centres = a[1-axis]+(stations-a[axis])*(b[1-axis]-a[1-axis])/(b[axis]-a[axis])
    offsets = np.arange(-search_radius,search_radius+1)
    candidates = centres.round().astype(int)[:,None]+offsets
    scores = []
    for u,coords in zip(stations,candidates):
        # Remove broad paper shading and use a median along the frame to reject
        # individual hatch strokes, tick labels, and terrain lines.
        image=gray if axis==0 else gray.T
        strip=image[:,max(0,u-19):min(image.shape[1],u+20)]
        start_v=coords[0]-band-12
        stop_v=coords[-1]+band+13
        lo,hi=max(0,start_v),min(len(strip),stop_v)
        if lo>=hi or strip.shape[1]==0:
            raise ValueError('Frame search lies outside the source scan')
        intensity=np.median(strip[lo:hi],axis=1)
        if lo!=start_v or hi!=stop_v:
            intensity=np.pad(intensity,(lo-start_v,stop_v-hi),mode='edge')
        response=gaussian_filter1d(intensity,4)-gaussian_filter1d(intensity,.65)
        k=coords-start_v
        outer=np.stack([response[k-sign*(band+d)] for d in range(-2,3)])
        score=response[k]*.55+outer.max(axis=0)*.45
        visible=(coords>=0)&(coords<len(strip))&(coords-sign*band>=0)&(coords-sign*band<len(strip))
        if not np.any(visible):
            raise ValueError('Both lines of the graticule band must be visible')
        score[~visible]=-np.inf
        scores.append(score)
    scores=np.array(scores)
    # Track a continuous pair of rules along the whole side.
    penalty=1.7*(offsets[:,None]-offsets[None,:])**2
    cumulative=scores[0]-offsets**2
    parents=[]
    for row in scores[1:]:
        next_scores=cumulative[:,None]-penalty
        parents.append(next_scores.argmax(axis=0))
        cumulative=next_scores.max(axis=0)+row
    indices=[int(np.argmax(cumulative-offsets**2))]
    for parent in reversed(parents):
        indices.append(int(parent[indices[-1]]))
    measured=candidates[np.arange(len(stations)),indices[::-1]]
    smoothed=gaussian_filter1d(median_filter(measured.astype(float),3,mode='nearest'),1.3,mode='nearest')
    endpts=sorted((a,b),key=lambda p:p[axis])
    knots=[[start,endpts[0][1-axis]],*np.column_stack([stations,smoothed]).tolist(),[stop,endpts[1][1-axis]]]
    return np.round(knots,3).tolist(),round(float(np.max(abs(measured-smoothed))),2)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path)
    parser.add_argument('out',type=Path)
    parser.add_argument('--band-pixels',required=True,type=int)
    parser.add_argument('--search-radius',type=int,default=44,
                        help='Maximum source-pixel distance from the corner-to-corner chord')
    args=parser.parse_args()
    config=json.loads(args.config.read_text())
    flags=cv2.IMREAD_GRAYSCALE | (cv2.IMREAD_IGNORE_ORIENTATION if config.get('ignore_exif_orientation') else 0)
    gray=cv2.imread(config['source'],flags)
    corners=config['frame_corners']
    guides={}
    for i,side in enumerate(('north','east','south','west')):
        guides[side],deviation=trace(gray,corners[i],corners[(i+1)%4],i,args.band_pixels,args.search_radius)
        print(side,'maximum difference between measured and smoothed samples, pixels',deviation)
    config.update(crop_mode='measured_frame',crop_edge_guides=guides)
    args.out.write_text(json.dumps(config,indent=2)+'\n')
