"""Render all-edge TPS COGs directly from scan pixels on the remote disk."""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np
from osgeo import gdal, osr
from scipy.interpolate import RegularGridInterpolator

from atlas_tps_transform import AtlasTPS
from fit_atlas_book_edges import OUT, OUTPUT, ROOT, hist, read, write

REVIEW = OUTPUT/'atlas-book-edges'
SHIFT = -216.18/3600
RES = 25.
R = 6378137.


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def mapping(exact, width, height):
    """Use bilinear coordinates in smooth cells and exact TPS in flagged cells."""
    gx,gy = (np.unique(np.r_[np.arange(0,n,32),n-1]) for n in (width,height))
    def grid(y,x):
        yy,xx = np.meshgrid(y,x,indexing='ij')
        return np.c_[yy.ravel(),xx.ravel()]
    interp = RegularGridInterpolator((gy,gx),exact(grid(gy,gx)).reshape(len(gy),len(gx),2))
    mx,my = (gx[:-1]+gx[1:])/2,(gy[:-1]+gy[1:])/2
    def error(y,x):
        points = grid(y,x)
        return np.linalg.norm(interp(points)-exact(points),axis=1).reshape(len(y),len(x))
    h,v = error(gy,mx),error(my,gx)
    worst = np.maximum.reduce([error(my,mx),h[:-1],h[1:],v[:,:-1],v[:,1:]])
    bad = worst>=.02
    # Refine only failed cells. Check the centre and all edge midpoints of
    # each child; evaluate every native output sample exactly in failed children.
    iy,ix = np.nonzero(bad)
    index = np.full(bad.shape,-1,int)
    index[iy,ix] = np.arange(len(iy))
    child_nodes = np.empty((len(iy),5,5,2))
    child_error = np.empty((len(iy),4,4))
    fractions = np.linspace(0,1,9)
    for start in range(0,len(iy),64):
        sl = slice(start,start+64)
        y,x = iy[sl],ix[sl]
        yr = gy[y,None]+(gy[y+1]-gy[y])[:,None]*fractions
        xr = gx[x,None]+(gx[x+1]-gx[x])[:,None]*fractions
        ys,xs = np.broadcast_arrays(yr[:,:,None],xr[:,None,:])
        measured = exact(np.stack((ys,xs),axis=-1).reshape(-1,2)).reshape(len(y),9,9,2)
        corners = measured[:,::2,::2]
        child_nodes[sl] = corners
        a,b,c,d = corners[:,:-1,:-1],corners[:,:-1,1:],corners[:,1:,:-1],corners[:,1:,1:]
        child_error[sl] = np.maximum.reduce([np.linalg.norm(delta,axis=-1) for delta in [
            (a+b+c+d)/4-measured[:,1::2,1::2],(a+b)/2-measured[:,:-1:2,1::2],
            (c+d)/2-measured[:,2::2,1::2],(a+c)/2-measured[:,1::2,:-1:2],
            (b+d)/2-measured[:,1::2,2::2]]])
    def sample(points):
        xy = interp(points)
        iy = np.minimum(points[:,0].astype(int)//32,len(gy)-2)
        ix = np.minimum(points[:,1].astype(int)//32,len(gx)-2)
        mask = bad[iy,ix]
        if mask.any():
            yy,xx = iy[mask],ix[mask]
            ids = index[yy,xx]
            p = points[mask]
            fy = 4*(p[:,0]-gy[yy])/(gy[yy+1]-gy[yy])
            fx = 4*(p[:,1]-gx[xx])/(gx[xx+1]-gx[xx])
            cy,cx = np.minimum(fy.astype(int),3),np.minimum(fx.astype(int),3)
            fy,fx = (fy-cy)[:,None],(fx-cx)[:,None]
            a = child_nodes[ids,cy,cx]*(1-fx)+child_nodes[ids,cy,cx+1]*fx
            b = child_nodes[ids,cy+1,cx]*(1-fx)+child_nodes[ids,cy+1,cx+1]*fx
            refined = a*(1-fy)+b*fy
            failed = child_error[ids,cy,cx]>=.02
            if failed.any(): refined[failed] = exact(p[failed])
            xy[mask] = refined
        return xy
    return sample, dict(total_cells=int(bad.size),refined_cells=int(bad.sum()),
                        exact_child_cells=int(np.sum(child_error>=.02)),
                        max_accepted_check_error_pixels=float(max(worst[~bad].max(initial=0),
                            child_error[child_error<.02].max(initial=0))))


def render(sid):
    gdal.UseExceptions()
    gdal.SetCacheMax(80*1024**2)
    source_report = OUT/sid/'model.json'
    m = read(source_report)
    quality_note = 'Four corners and measured longitude and latitude stripes use Walker’s printed grid.'
    fill = m.get('display_seam_fill')
    if fill and sha(ROOT/fill['file']) != fill['sha256']:
        raise ValueError('Display seam patch differs from its recorded checksum')
    plate = m.get('plate_registration')
    native = m.get('native_graticule_only', False)
    label = 'Printed graticule · TPS' if native else 'All four edges · weighted TPS'
    if native:
        quality_note = ('This placement follows the edition’s printed graticule using TPS '
                        'and the project longitude correction. The cutline follows its measured inner frame.')
    if plate:
        quality_note = (f'The four inner corners place this edition in the Walker mosaic. '
                        f'Withheld marks have {plate["native_frame_withheld_rms_arcseconds"]:.2f}″ RMS '
                        f'in the registered plate grid. Their RMS difference from the original engraved '
                        f'coordinates is {m["withheld_rms_arcseconds"]:.2f}″.')
    normals = m.get('frame_normal_controls',[])
    if normals:
        sides = ', '.join(sorted({p['side'] for p in normals}))
        quality_note += (f' On the {sides} frame, {len(normals)} additional measurements constrain'
                         ' displacement across the engraved rule. Position along the rule remains free.')
    margin = m.get('margin_extension')
    if margin:
        if margin['policy'] == 'always':
            quality_note += ' The cutline includes the printed map extension at the north margin.'
        else:
            quality_note += ' Marginal geography is retained only in cells without a published neighbouring sheet.'
    if fill:
        quality_note += ' Narrow losses at the internal paper cut are interpolated from adjacent scan pixels for display.'
    model_digest = sha(source_report)
    signature = model_digest+'-25m-bilinear-v1'
    out = REVIEW/sid
    out.mkdir(parents=True,exist_ok=True)
    manifest = out/'web-alignment.json'
    if manifest.exists():
        meta = read(manifest)
        prev = out/meta['files'][0]['file']
        compatible = {signature,model_digest+'-0fe47beaa209',model_digest+'-'+sha(Path(__file__))[:12]}
        if (meta['render_signature'] in compatible and prev.exists()
                and prev.stat().st_size==meta['files'][0]['bytes']
                and meta['transformation_grid_validation']['max_accepted_check_error_pixels']<.02):
            if sha(ROOT/m['source'])!=m['source_sha256']:
                raise ValueError('Source checksum differs from the cached registration')
            if meta['render_signature']!=signature or meta.get('quality_note')!=quality_note or meta.get('model_label')!=label:
                write(manifest,dict(meta,render_signature=signature,quality_note=quality_note,model_label=label))
            return
    table = read(ROOT/m['table'])
    hist.LATS,hist.RADII,hist.ANGLES = [np.array(table[k]) for k in
        ('latitudes','radius_fathoms','angle_arcseconds_per_longitude_degree')]
    hist.R0 = table['reference_radius_fathoms']
    tps = AtlasTPS(m['selected_model'],read(ROOT/m['affine_reference']))
    off = m['frame_offset']
    polygons = m.get('display_polygons', [[m['crop_ring']]])
    def to_lonlat(points):
        ring = np.array(points)
        dense = np.vstack([np.linspace(a,b,max(1,int(np.ceil(np.linalg.norm(a-b)/24))),endpoint=False)
                           for a,b in zip(ring[:-1],ring[1:])] + [ring[:1]])
        ll = hist.inverse(tps.forward(dense+off))
        ll[:,0] += SHIFT
        return ll.tolist()
    geographic = [[to_lonlat(ring) for ring in poly] for poly in polygons]
    vertices = np.vstack([poly[0] for poly in geographic])
    world = R*np.c_[np.deg2rad(vertices[:,0]),np.arcsinh(np.tan(np.deg2rad(vertices[:,1])))]
    west,south = RES*np.floor(world.min(axis=0)/RES)
    east,north = RES*np.ceil(world.max(axis=0)/RES)
    width,height = round((east-west)/RES),round((north-south)/RES)
    path = ROOT/m['source']
    if sha(path)!=m['source_sha256']:
        raise ValueError('Source checksum differs from the GCP dataset')
    preserve_alpha=m.get('preserve_source_alpha',False)
    flags=cv2.IMREAD_UNCHANGED if preserve_alpha else (cv2.IMREAD_COLOR | (cv2.IMREAD_IGNORE_ORIENTATION if m['ignore_exif_orientation'] else 0))
    im = cv2.imread(str(path),flags)
    if im is None or list(im.shape[1::-1])!=m['source_size']:
        raise ValueError('Source dimensions changed')
    if preserve_alpha and (im.ndim!=3 or im.shape[2]!=4):
        raise ValueError('Expected a four-channel source assembly')
    if fill:
        patch=cv2.imread(str(ROOT/fill['file']),cv2.IMREAD_UNCHANGED)
        x,y=fill['origin']
        if not preserve_alpha or patch is None or patch.ndim!=3 or patch.shape[2]!=4 or min(x,y)<0:
            raise ValueError('Invalid display seam patch')
        dst=im[y:y+patch.shape[0],x:x+patch.shape[1]]
        if dst.shape!=patch.shape or not np.isin(patch[:,:,3],[0,255]).all():
            raise ValueError('Display seam patch extent or mask is invalid')
        take=patch[:,:,3]==255
        dst[take]=patch[take]
    image = cv2.cvtColor(im,cv2.COLOR_BGRA2RGBA if preserve_alpha else cv2.COLOR_BGR2RGBA)
    del im
    mask = np.zeros(image.shape[:2],np.uint8)
    for poly in polygons:
        cv2.fillPoly(mask,[np.rint(ring).astype(np.int32) for ring in poly],255)
    image[:,:,3] = np.minimum(image[:,:,3],mask) if preserve_alpha else mask
    if preserve_alpha:
        for chan in range(3):
            for y0 in range(0,len(image),128):
                block=image[y0:y0+128]
                block[:,:,chan]=np.rint(block[:,:,chan]*(block[:,:,3].astype("float32")/255)).astype("uint8")
    del mask
    def exact(points):
        result = []
        for j in range(0,len(points),2048):
            row,col = points[j:j+2048].T
            lon = np.rad2deg((west+(col+.5)*RES)/R)-SHIFT
            lat = np.rad2deg(np.arctan(np.sinh((north-(row+.5)*RES)/R)))
            result.append(tps.inverse(hist.project(np.c_[lon,lat]))-off)
        return np.vstack(result)
    sample,validation = mapping(exact,width,height)
    crs = osr.SpatialReference()
    crs.ImportFromEPSG(3857)
    with TemporaryDirectory(dir=out) as work:
        raw = str(Path(work)/'raster.tif')
        ds = gdal.GetDriverByName('GTiff').Create(raw,width,height,4,gdal.GDT_Byte,options=['TILED=YES','INTERLEAVE=PIXEL'])
        ds.SetGeoTransform((west,RES,0,north,0,-RES))
        ds.SetProjection(crs.ExportToWkt())
        ds.SetMetadataItem('LONGITUDE_CORRECTION_ARCSECONDS','-216.18')
        for i,color in enumerate([gdal.GCI_RedBand,gdal.GCI_GreenBand,gdal.GCI_BlueBand,gdal.GCI_AlphaBand],1):
            ds.GetRasterBand(i).SetColorInterpretation(color)
        for start in range(0,height,64):
            stop = min(start+64,height)
            yy,xx = np.mgrid[start:stop,0:width]
            xy = sample(np.c_[yy.ravel(),xx.ravel()]).reshape(stop-start,width,2).astype('float32')
            block = cv2.remap(image,xy,None,cv2.INTER_LINEAR)
            if preserve_alpha:
                partial=(block[:,:,3]>0)&(block[:,:,3]<255)
                block[:,:,:3][partial]=np.clip(np.rint(block[:,:,:3][partial]*(255./block[:,:,3][partial,None])),0,255).astype("uint8")
            ds.WriteArray(block.transpose(2,0,1),yoff=start)
        ds.FlushCache()
        ds = None
        cog = Path(work)/'map.tif'
        result = gdal.Translate(str(cog),raw,format='COG',creationOptions=[
            'BLOCKSIZE=512','COMPRESS=DEFLATE','PREDICTOR=YES','OVERVIEW_RESAMPLING=AVERAGE'])
        result = None
        from osgeo_utils.samples.validate_cloud_optimized_geotiff import validate
        ds = gdal.Open(str(cog))
        _,errors,_ = validate(ds,full_check=True)
        if errors or ds.GetRasterBand(4).GetColorInterpretation()!=gdal.GCI_AlphaBand or ds.GetSpatialRef().GetAuthorityCode(None)!='3857':
            raise ValueError(f'COG validation failed: {errors}')
        ds = None
        ref = read(ROOT/m['frame_config'])
        dst = out/'all-edges-3857.cog.tif'
        digest = sha(cog)
        cog.replace(dst)
    geometry = (dict(type='Polygon',coordinates=geographic[0]) if len(geographic)==1
                else dict(type='MultiPolygon',coordinates=geographic))
    write(out/'footprint.geojson',dict(type='FeatureCollection',features=[dict(type='Feature',
          properties=dict(sheet=sid),geometry=geometry)]))
    meta = dict(id=sid,title=ref.get('title',sid),model_label=label,
                default_longitude_shift_arcseconds=-216.18,render_signature=signature,pixel_size_metres=RES,
                projection='EPSG:3857',quality_note=quality_note,
                validation=dict(controls=len(read(ROOT/m['dataset'])['controls']),fixed_frame_controls=len(m['fixed_controls']),
                                independent_edge_checks=len(m['withheld_errors_arcseconds']),
                                edge_rmse_arcseconds=m['withheld_rms_arcseconds'],
                                max_edge_error_arcseconds=max(map(abs,m['withheld_errors_arcseconds']))),
                files=[dict(key='corrected',file=dst.name,bytes=dst.stat().st_size,sha256=digest,
                            extent_3857=[west,south,east,north])],
                diagnostics=[],transformation_grid_validation=validation)
    if plate:
        meta['plate_registration'] = {k:plate[k] for k in (
            'method','order','corner_offsets_arcseconds','native_frame_withheld_rms_arcseconds',
            'mosaic_minus_printed_withheld_rms_arcseconds')}
    if fill:
        meta['display_seam_fill']={k:fill[k] for k in ('method','max_width_px','transparent_pixels_filled','interpolated_pixels')}
    write(manifest,meta)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sheets', nargs='+', help='Sheet IDs with fitted four-edge models')
    for sheet in parser.parse_args().sheets:
        render(sheet)
