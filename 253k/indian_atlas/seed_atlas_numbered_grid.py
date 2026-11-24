"""Seed a sheet from its manually read margin values and corner positions.

Each side has the first/last rule positions in a 2200-pixel-wide preview,
the first rule in arcminutes, the number of five-minute intervals, and any
indices hidden by scale bars. Measurements are candidates for native review.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates


SIDES = ('north','east','south','west')


def margin_rule(image, origin, boundary, outward, search, band):
    # Rows of this local array follow the numbered line out from the frame.
    low,high = sorted([round(boundary+outward*(band+6)),round(boundary+outward*(band+86))])
    centre = round(origin)
    left = centre-search
    patch = image[low:high,left:centre+search+1].astype(np.float32)
    if patch.shape!=(high-low,2*search+1):
        raise ValueError('Numbered margin window extends outside the scan')
    contrast = gaussian_filter1d(patch,4,axis=1)-gaussian_filter1d(patch,.6,axis=1)
    score = np.mean(np.clip(contrast,-12,32),axis=0)
    best = int(np.argmax(score[3:-3]))+3
    # Choose a continuous run of the rule so lettering in a nearby part of
    # the same margin does not pull the local line fit off its engraved stroke.
    length = 25
    support = np.max(contrast[:,best-1:best+2],axis=1)
    row = int(np.argmax(np.convolve(np.clip(support,-12,30),np.ones(length),mode='valid')))
    return left+best,[low+row,low+row+length]


def long_line(image, along, cross, search=65, length=640):
    along,cross = round(along),round(cross)
    half=length//2
    pad=search+24
    patch=image[along-half:along+half,cross-pad:cross+pad+1].astype('float32')
    if patch.shape!=(length,2*pad+1):
        raise ValueError('Interior line window extends outside the scan')
    contrast=gaussian_filter1d(patch,4.5,axis=1)-gaussian_filter1d(patch,.6,axis=1)
    contrast=np.clip(contrast,-20,45)
    offsets=np.arange(-search,search+1)
    shift,run=np.meshgrid(offsets,np.arange(-half,half,2),indexing='ij')
    best=(-np.inf,0)
    for slope in np.linspace(-.055,.055,23):
        values=map_coordinates(contrast,[half+run,pad+shift+slope*run],order=1)
        quarters=values.reshape(len(offsets),4,-1).mean(axis=2)
        score=quarters.mean(axis=1)+.3*quarters.min(axis=1)
        i=int(score.argmax())
        best=max(best,(float(score[i]),int(offsets[i])))
    return cross+best[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec',type=Path)
    parser.add_argument('out',type=Path)
    args=parser.parse_args()
    spec=json.loads(args.spec.read_text())
    config=spec['config']
    gray=cv2.imread(config['source'],cv2.IMREAD_GRAYSCALE)
    scale=gray.shape[1]/2200
    corners=np.array(config['frame_corners'])
    rules={}
    for side in SIDES:
        index=SIDES.index(side)
        axis=index%2
        image=gray if axis==0 else gray.T
        outward=(-1,1,1,-1)[index]
        ends=corners[[index,(index+1)%4]]
        ends=ends[np.argsort(ends[:,axis])]
        first,last,minutes,intervals,missing=spec['margins'][side]
        records=[]
        for i,guess in enumerate(np.linspace(first,last,intervals+1)*scale):
            if i in missing:
                continue
            boundary=np.interp(guess,ends[:,axis],ends[:,1-axis])
            pos,window=margin_rule(image,guess,boundary,outward,spec.get('margin_search',32),spec['band_pixels'])
            records.append(dict(index=i,arcminutes=minutes+5*i*(1 if axis==0 else -1),
                                position=pos,window=window))
        rules[side]=records
    config['longitude_tick_samples']=[
        dict(side=side,longitude=p['arcminutes']/60,pixel=p['position'],line_window=p['window'],
             half_window=4,role='fit' if (p['index']+int(side=='south'))%2==0 else 'withheld')
        for side in ('north','south') for p in rules[side]]
    config['tick_preview_seeds']={}
    config['tick_search_overrides']={}
    k=0
    for side in ('west','east'):
        ticks=rules[side]
        if len(ticks)!=spec['margins'][side][3]+1:
            raise ValueError('Non-contiguous latitude ticks require explicit omitted observations')
        config['tick_preview_seeds'][side]=dict(first_latitude=ticks[0]['arcminutes']/60,
                                                ys=[p['position']/scale for p in ticks])
        for p in ticks:
            config['tick_search_overrides'][str(k)]=dict(initial_line=p['position'],half_window=4,
                pixel_window=p['window'],reason='Native numbered rule located on the margin.')
            k+=1
    def position(side,value):
        p=sorted(rules[side],key=lambda t:t['arcminutes'])
        coordinates=[t['arcminutes'] for t in p]
        if not coordinates[0]<=60*value<=coordinates[-1]:
            raise ValueError(f'Grid seed outside the numbered range on {side}')
        return np.interp(60*value,coordinates,[t['position'] for t in p])
    def guess(lon,lat):
        xn,xs=position('north',lon),position('south',lon)
        yw,ye=position('west',lat),position('east',lat)
        x=xn
        for _ in range(3):
            y=np.interp(x,[corners[[0,3],0].mean(),corners[[1,2],0].mean()],[yw,ye])
            x=np.interp(y,[corners[:2,1].mean(),corners[2:,1].mean()],[xn,xs])
        return x,y
    def horizontal_search(x,y):
        top=np.interp(x,corners[:2,0],corners[:2,1])
        bottom=np.interp(x,corners[[3,2],0],corners[[3,2],1])
        return max(5,min(65,int(min(y-top,bottom-y)-12)))
    centres=[]
    for lon,lat in spec['crossings']:
        x,y=guess(lon,lat)
        centres.append(dict(longitude=lon,latitude=lat,pixel=long_line(gray,y,x),
                            line=long_line(gray.T,x,y,search=horizontal_search(x,y))))
    config['crossing_preview_seeds']=[[p['longitude'],p['latitude'],p['pixel']/scale,p['line']/scale] for p in centres]
    config['crossing_local_seeds']=[[200,200] for p in centres]
    config['crossing_search_window']=4
    config['affine_initialization']=dict(approximate_positions=centres,reason='Initial map positions from the labelled half-degree crossings.')
    for axis,kind in [(0,'meridian'),(1,'parallel')]:
        samples=[]
        for lon,lat in spec[kind+'_checks']:
            x,y=guess(lon,lat)
            if axis==0:
                samples.append(dict(longitude=lon,pixel=long_line(gray,y,x),line=round(y),search_window=5,role='withheld'))
            else:
                samples.append(dict(latitude=lat,pixel=round(x),line=long_line(gray.T,x,y,search=horizontal_search(x,y)),search_window=5,role='withheld'))
        config[kind+'_samples']=samples
    config['seed_provenance']='Numbered five-minute rulers on this edition and long continuous interior graticule strokes. Alternating numbered rules and additional interior line observations withheld. Scale-obscured labels omitted.'
    config['line_slope_bounds']={'vertical':[-.055,.055],'horizontal':[-.055,.055]}
    args.out.write_text(json.dumps(config,indent=2)+'\n')
    print('Measured margin rules', {s:len(v) for s,v in rules.items()}, 'Interior crossings',centres)


if __name__=='__main__':
    main()
