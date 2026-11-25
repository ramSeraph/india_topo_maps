"""Build the release bounds, PMTiles and paired STAC input listings."""

import argparse
import csv
import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from pmtiles_mosaic.pmtiles_source import PMTilesSource

from release_files import files, sha256, url


def bounds_and_listings(cogs, output):
    manifest = files()
    features = json.loads((cogs / "footprints.geojson").read_text())["features"]
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as temp:
        stage = Path(temp)
        records = []
        for feature in sorted(features, key=lambda f: f["properties"]["file"]):
            props = feature["properties"]
            tif = cogs / props["file"]
            original = Path("data/raw") / props["source"]
            cog_path = Path("georef") / tif.name
            digest = sha256(tif)
            if digest != manifest[cog_path]["sha256"]:
                raise ValueError(f"{tif} differs from the published COG linked by STAC")
            identity = tif.stem
            feature["id"] = identity
            props.update(id=identity, digest=digest)
            (stage / f"{identity}.geojsonl").write_text(json.dumps(feature))
            # iomaps matches both listings by basename. Some printed sheet IDs
            # correct the source filename, so retain the actual original URL.
            records.append(
                (
                    (
                        tif.name,
                        url(cog_path, manifest[cog_path]),
                        tif.stat().st_size,
                        digest,
                    ),
                    (
                        identity + original.suffix,
                        url(original, manifest[original]),
                        original.stat().st_size,
                        manifest[original]["sha256"],
                    ),
                )
            )
        bound = stage / "bounds.geojson"
        subprocess.run(["collect-bounds", "-b", stage, "-o", bound], check=True)
        result = sorted(
            json.loads(bound.read_text())["features"], key=lambda f: f["id"]
        )
        if {f["id"] for f in result} != {Path(r[0][0]).stem for r in records} or len(
            result
        ) != len(records):
            raise ValueError("Collected bounds disagree with the COG inventory")
        bound.write_text(
            '{ "type": "FeatureCollection", "features": [\n'
            + ",\n".join(json.dumps(f) for f in result)
            + "\n]}\n"
        )
        for index, name in enumerate(("cogs.csv", "source-links.csv")):
            with (stage / name).open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("name", "url", "size", "sha256"))
                writer.writerows(pair[index] for pair in records)
            os.replace(stage / name, output / name)
        os.replace(bound, output / bound.name)


def verify_archive(archive, tiles):
    source = PMTilesSource(str(archive))
    count = Counter()
    tile_digests = {}
    try:
        if source.get_metadata()["format"] != "webp" or source.max_zoom != 15:
            raise ValueError("Unexpected PMTiles metadata")
        for tile, data in source.all():
            path = tiles / str(tile.z) / str(tile.x) / f"{tile.y}.webp"
            if (
                tile in tile_digests
                or data[:4] != b"RIFF"
                or data[8:12] != b"WEBP"
                or data != path.read_bytes()
            ):
                raise ValueError(f"Archive differs from the WebP tile at {path}")
            tile_digests[tile] = hashlib.sha256(data).hexdigest()
            count[tile.z] += 1
    finally:
        source.cleanup()
    for z in range(16):
        if not count[z] or count[z] != sum(
            1 for _ in (tiles / str(z)).glob("*/*.webp")
        ):
            raise ValueError(f"Tile count differs at zoom {z}")
    content = hashlib.sha256()
    for tile in sorted(tile_digests, key=lambda t: (t.z, t.x, t.y)):
        content.update(
            f"{tile.z}/{tile.x}/{tile.y} {tile_digests[tile]}\n".encode("ascii")
        )
    print(
        f"Verified {len(tile_digests):,} WebP tiles. Tile-content SHA-256 {content.hexdigest()}"
    )
    print(f"Archive SHA-256 {sha256(archive)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("bounds", "archive", "verify-archive"))
    parser.add_argument("--cogs", type=Path, default=Path("georef"))
    parser.add_argument("--tiles", type=Path, default=Path("export/tiles"))
    parser.add_argument("--output", type=Path, default=Path("export/pmtiles"))
    args = parser.parse_args()
    archive = args.output / "CZMP-25k.pmtiles"
    if args.operation == "bounds":
        bounds_and_listings(args.cogs, args.output)
    elif args.operation == "archive":
        args.output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=args.output) as tmp:
            fresh = Path(tmp) / archive.name
            subprocess.run(
                [
                    "partition",
                    "--from-source",
                    args.tiles,
                    "--to-pmtiles",
                    fresh,
                    "--no-cache",
                ],
                check=True,
            )
            verify_archive(fresh, args.tiles)
            os.replace(fresh, archive)
    else:
        verify_archive(archive, args.tiles)
