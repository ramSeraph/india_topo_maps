"""CZMP source controls, masks and the topo_map_processor Web Mercator export."""

import json
import math
import shlex
import subprocess
import tempfile
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pymupdf
from osgeo import gdal, ogr, osr
from topo_map_processor.processor import TopoMapProcessor

PROCESSOR = "topo_map_processor"
# GoogleMapsCompatible's nearest level to the processor's 1:25,000 warp resolution.
WORLD_HALF = math.pi * 6378137
RES = 2 * WORLD_HALF / (256 * 2**16)


def spatial_ref(epsg):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def sheet_ring(bounds):
    w, s, e, n = bounds
    return [[w, n], [w, s], [e, s], [e, n], [w, n]]


def sheet_grid(bounds):
    """Use the same XYZ tile grid for either jurisdiction and its full sheet."""
    forward = osr.CoordinateTransformation(spatial_ref(4326), spatial_ref(3857))
    w, s, e, n = bounds
    x0, y0, _ = forward.TransformPoint(w, s)
    x1, y1, _ = forward.TransformPoint(e, n)
    step = 256 * RES
    left = math.floor((x0 + WORLD_HALF) / step)
    right = math.ceil((x1 + WORLD_HALF) / step)
    top = math.floor((WORLD_HALF - y1) / step)
    bottom = math.ceil((WORLD_HALF - y0) / step)
    transform = (left * step - WORLD_HALF, RES, 0, WORLD_HALF - top * step, 0, -RES)
    return transform, (256 * (right - left), 256 * (bottom - top))


def coverage_mask(geometry, transform, size):
    geographic, projected = spatial_ref(4326), spatial_ref(3857)
    geom = ogr.CreateGeometryFromJson(json.dumps(geometry))
    geom.Transform(osr.CoordinateTransformation(geographic, projected))
    vector = ogr.GetDriverByName("Memory").CreateDataSource("")
    layer = vector.CreateLayer("coverage", projected)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(geom)
    layer.CreateFeature(feature)
    mask = gdal.GetDriverByName("MEM").Create("", *size, 1, gdal.GDT_Byte)
    mask.SetGeoTransform(transform)
    mask.SetProjection(projected.ExportToWkt())
    gdal.RasterizeLayer(mask, [1], layer, burn_values=[255])
    return mask.GetRasterBand(1).ReadRaster()


class CZMPProcessor(TopoMapProcessor):
    def __init__(self, name, entry, workdir, points):
        super().__init__(
            Path(name), {"jpeg_export_quality": 90}, sheet_ring(entry["bounds"])
        )
        self.workdir = Path(workdir)
        self.mapbox_corners = points
        self.state_clipped = bool(entry["cut"])
        self.transform, self.size = sheet_grid(entry["bounds"])

    def get_workdir(self):
        return self.workdir

    def get_full_file_path(self):
        return self.workdir / "source.ppm"

    def get_crs_proj(self):
        return "EPSG:4326"

    def get_scale(self):
        return 25000

    def get_resolution(self):
        return RES

    def get_cutline_props(self):
        return {"id": self.get_id()}

    def run_external(self, cmd):
        args = shlex.split(cmd)
        # Process multiple sheets in parallel, with lossless scratch files.
        if args[0] == "gdalwarp":
            x, dx, _, y, _, dy = self.transform
            width, height = self.size
            bounds = [x, y + height * dy, x + width * dx, y]
            i = args.index("-crop_to_cutline")
            args[i : i + 1] = ["-te", *map(str, bounds)]
            if int(gdal.VersionInfo()) < 3090000:
                # The processor writes an RFC 7946 WGS84 cutline, GDAL's default.
                i = args.index("-cutline_srs")
                del args[i : i + 2]
            args[args.index("COMPRESS=JPEG")] = "COMPRESS=NONE"
            i = args.index("-co", args.index("COMPRESS=NONE") + 1)
            assert args[i + 1].startswith("JPEG_QUALITY=")
            del args[i : i + 2]
            args = [a.replace("NUM_THREADS=ALL_CPUS", "NUM_THREADS=1") for a in args]
            args = ["64" if a == "1024" else a for a in args]
        elif "-gcp" in args:
            # A VRT carries the processor's GCPs and reads the lossless page render directly.
            i = args.index("-of")
            args[i + 1] = "VRT"
            while "-co" in args:
                i = args.index("-co")
                del args[i : i + 2]
        elif self.state_clipped and "COG" in args:
            # Aggregate mask resampling makes both jurisdictions opaque at a
            # shared edge. Nearest uses the same source pixel in both editions.
            args[1:1] = ["-co", "OVERVIEW_RESAMPLING=NEAREST"]
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL)

    def write_cog(self, entry, method, destination):
        self.georeference()
        self.warp()
        final = self.workdir / "final.tif"
        with gdal.Open(str(final), gdal.GA_Update) as ds:
            if (ds.RasterXSize, ds.RasterYSize) != self.size or not np.allclose(
                ds.GetGeoTransform(), self.transform, rtol=0, atol=1e-7
            ):
                raise ValueError("Processor warp missed the shared XYZ grid")
            geom = entry["cut"] or {"type": "Polygon", "coordinates": [self.index_box]}
            mask = coverage_mask(geom, self.transform, self.size)
            ds.GetRasterBand(4).WriteRaster(0, 0, *self.size, mask)
            ds.SetMetadata(
                {
                    "SOURCE_SHEET": self.filepath.name,
                    "OSM_SHEET_ID": entry["osm_sheet_id"],
                    "CONTROL_METHOD": method,
                    "EXPORT_PROCESSOR": PROCESSOR,
                    "PROCESSOR_VERSION": version("topo-map-processor"),
                }
            )
            if self.state_clipped:
                ds.SetMetadataItem("MASK_OVERVIEW_RESAMPLING", "NEAREST")
        self.export_gtiff(str(final), str(destination), self.jpeg_export_quality)


def export_sheet(name, entry, points, page, destination, method):
    # Coordinates in points refer to page edges. GDAL GCPs use that same
    # convention in the clipped pixmap, including its integer render origin.
    lo, hi = points.min(axis=0) - 2, points.max(axis=0) + 2
    zoom = 6144 / max(np.ptp(points[:, 0]), np.ptp(points[:, 1]))
    with tempfile.TemporaryDirectory() as directory:
        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom),
            clip=pymupdf.Rect(*lo, *hi) & page.rect,
            colorspace=pymupdf.csRGB,
            alpha=False,
        )
        processor = CZMPProcessor(
            name, entry, directory, (points * zoom - [pix.x, pix.y]).tolist()
        )
        pix.save(str(processor.get_full_file_path()))
        del pix
        processor.write_cog(entry, method, destination)
