"""Build the 0–15 CZMP WebP mosaic with topo_map_processor's spatially batched tiler."""

import argparse
import hashlib
import json
import os
from multiprocessing import Pool
from pathlib import Path

import mercantile
from osgeo import gdal
from osgeo_utils.gdal2tiles import DividedCache
from shapely.geometry import shape
from topo_map_processor.tools.retile import Tiler, get_base_tile_sheet_mappings
from topo_map_processor.tools.utils import relax_open_file_limit


def tile(cogs, dest, jobs):
    features = json.loads((cogs / "footprints.geojson").read_text())["features"]
    bounds = {
        f["properties"]["file"]: mercantile.LngLatBbox(*shape(f["geometry"]).bounds)
        for f in features
    }
    if set(bounds) != {p.name for p in cogs.glob("*.tif")}:
        raise ValueError("The COG directory and coverage index disagree")

    # The coastline occupies a small fraction of its rectangular envelope.
    # Plan only covered XYZ cells, using a common VRT so both state editions
    # participate when they fall in the same tile.
    _, sheets_by_tile = get_base_tile_sheet_mappings(bounds, 15)
    base = set(sheets_by_tile)
    digest = hashlib.sha256((cogs / "footprints.geojson").read_bytes())
    for name in sorted(bounds):
        with (cogs / name).open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    revision = digest.hexdigest()
    checkpoint = dest.parent / f".{dest.name}.source-sha256"
    relax_open_file_limit()
    os.environ["GDAL_DISABLE_READDIR_ON_OPEN"] = "TRUE"
    os.environ["GDAL_MAX_DATASET_POOL_SIZE"] = "128"
    gdal.SetCacheMax(2048 * 1024**2)
    with DividedCache(jobs), Pool(jobs) as pool:
        tiler = Tiler(dest, cogs, None, "webp", 75, pool)
        tiler.disk_handler.init()
        # The processor publishes each completed batch atomically. A rerun
        # with the same input can resume from the existing full-resolution tiles.
        existing = set(tiler.disk_handler.all_z_tiles(15))
        if not existing:
            checkpoint.write_text(revision)
        same_inputs = checkpoint.exists() and checkpoint.read_text() == revision
        tiler.create_base_tiles(bounds, 15, base - existing if same_inputs else base)
        tiler.disk_handler.delete_unwanted_tiles(base, 15)
        if set(tiler.disk_handler.all_z_tiles(15)) != base:
            raise ValueError("Incomplete or unexpected base tiles")
        level = base
        for z in range(14, -1, -1):
            level = {mercantile.parent(t) for t in level}
            # GDAL can keep an existing overview. Rebuild parents from the
            # completed children, including transparent tiles at sheet edges.
            for t in level:
                tiler.disk_handler.get_tile_file(t).unlink(missing_ok=True)
            tiler.create_upper_tiles(z, level)
            tiler.disk_handler.delete_unwanted_tiles(level, z)
            if set(tiler.disk_handler.all_z_tiles(z)) != level:
                raise ValueError(f"Incomplete overview level {z}")
        tiler.disk_handler.save_metadata(
            {
                "type": "baselayer",
                "format": "webp",
                "version": "1",
                "name": "India CZMP 1:25,000",
                "description": "Georeferenced Coastal Zone Management Plan map sheets at 1:25,000.",
                "attribution": "National Centre for Sustainable Coastal Management",
                "minzoom": 0,
                "maxzoom": 15,
            }
        )
        checkpoint.write_text(revision)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cogs", type=Path, default=Path("georef"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("-j", type=int, default=8)
    args = parser.parse_args()
    tile(args.cogs, args.output, args.j)
