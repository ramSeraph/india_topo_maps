"""Match native band alternation on a scan, with both printed rules bracketing it."""
import numpy as np,cv2
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
from atlas_scan_frame import refine

def station(im,u,divs):
 h,w=im.shape; span=int(w*.25); l,r=int(u-span/2),int(u+span/2)
 depth=int(h*.36); step=max(1.,w/7000)
 strip=cv2.resize(im[:depth,l:r],(520,round(depth/step)),interpolation=cv2.INTER_AREA)
 nr,nc=strip.shape; ratio=span/nc; cross=depth/nr
 pitch=(.92*w/divs)/ratio
 taper=np.hanning(nc).astype('float32')
 nfft=1024;freq=np.fft.rfftfreq(nfft);target=[(freq>=1/(2*pitch*f*1.16))&(freq<=1/(2*pitch*f*.63)) for f in (1,2,5) if nc/(2*pitch*f)>2.2]
 yy,xx=np.mgrid[:nr,:nc].astype('float32')
 hits=[]
 for slope in (0,-.009,.009,-.023,.023,-.045,.045):
  g=cv2.remap(strip,xx,yy+(xx-nc/2)*(ratio/cross*slope),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
  arr=g.astype('float32')
  # Reject slowly varying blank paper and dense non-periodic topographic ink.
  norm=arr-arr.mean(axis=1)[:,None];power=np.abs(np.fft.rfft(norm*taper,nfft,axis=1))/taper.sum()
  amp=2*np.max(power[:,np.logical_or.reduce(target)],axis=1)
  coherence=amp/(np.std(gaussian_filter1d(norm,max(1,pitch*.09),axis=1),axis=1)+2)
  strength=amp*np.minimum(coherence,1.45)**3
  row=g.mean(axis=1);line=gaussian_filter1d(row,3.0)-gaussian_filter1d(row,.45)
  peaks=find_peaks(line,height=1.6,distance=2)[0]
  for y in peaks:
   for z in peaks[(peaks<y-2)&(peaks>=y-min(65,round(.007*w/cross)))]:
    a=z+max(1,round(.18*(y-z)));b=y-max(1,round(.18*(y-z)))+1
    val=np.median(strength[a:b])
    if val<8:continue
    outside=strength[max(0,z-14):max(1,z-3)]
    inside=strength[y+4:y+15]
    if len(outside)==0 or len(inside)==0:continue
    contrast=val-.65*max(np.median(outside),np.median(inside))
    if contrast<4:continue
    # Prefer a band that fills the interval between the pair of continuous strokes.
    score=contrast*max(0,min(1.5,np.median(coherence[a:b])))**2*(min(25,line[y],line[z])+1)**.36
    hits.append((float(score),(y+.5)*cross-.5,(y-z)*cross))
 best=[]
 for e in sorted(hits,reverse=True):
  if all(abs(e[1]-p[1])>4 for p in best):best.append(e)
  if len(best)>=24:break
 return best

def detect(gray,quarter):
 lines=[];bands=[]
 for i in range(4):
  im=gray if i%2==0 else gray.T
  if i in (1,2):im=im[::-1]
  h,w=im.shape;us=w*np.array([.27,.50,.73])
  choices=[station(im,u,(76 if i%2==0 else 43)*(1 if quarter else 2)) for u in us]
  best=None
  for a in choices[0]:
   for b in choices[2]:
    if abs(a[1]-b[1])>.065*(us[2]-us[0]):continue
    for c in choices[1]:
     dy=abs(c[1]-(a[1]+b[1])/2)
     if dy>max(22,.006*h):continue
     widths=np.array([q[2] for q in [a,c,b]])
     if widths.max()/widths.min()>1.9:continue
     score=np.mean(np.log([a[0],c[0],b[0]]))-.035*dy-.9*np.std(widths)/max(1,widths.mean())
     if best is None or score>best[0]:
      v=np.array([a[1],c[1],b[1]])
      if i in (1,2):v=h-1-v
      best=score,np.polyfit(us,v,1),round(np.median(widths))
  if best is None:raise ValueError('No matched repeated block band on '+str(i))
  lines.append(best[1]);bands.append(best[2])
 pts=[]
 for hi,vi in [(0,3),(0,1),(2,1),(2,3)]:
  (m,b),(n,c)=lines[hi],lines[vi];x=(c+n*b)/(1-n*m);pts.append([x,m*x+b])
 return refine(gray,np.array(pts),bands,max(24,min(75,round(gray.shape[1]*.004))))
