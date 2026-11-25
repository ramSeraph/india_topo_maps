"""Georeference CZMP release sheets using their printed graticule frames.

Run release_files.py fetch to populate data/raw and the two metadata files.
The release/ directory preserves the source grid extents and Maharashtra taluk
boundaries. Use --layers to rebuild the catalog from downloaded publisher grids.
See README.md for the commands to export sheets, verify the masks and tile.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from osgeo import gdal, ogr

from corner_audit import refine
from czmp_cog import PROCESSOR, coverage_mask, export_sheet, sheet_grid, sheet_ring

DATA = Path("data")
WORK = Path("work")
OUT = Path("georef")
SIDES = ("top", "bottom", "left", "right")
# North 24 Parganas draft, pages 1–11. Printed sheet numbers and the embedded
# WGS84 viewports independently agree. The published grid uses another sequence.
WB_PRINTED = {
    60: "F45K16/NE",
    61: "F45L4/NW",
    64: "F45K15/SW",
    65: "F45K15/SE",
    66: "F45L3/SW",
    67: "F45K11/NE",
    68: "F45K15/NW",
    69: "F45K15/NE",
    70: "F45K10/SE",
    71: "F45K14/SW",
    72: "F45K14/SE",
}
# The first four Puducherry release files follow the printed sequence below.
PY_PRINTED = {1: "C44H13/SW", 2: "C44H13/NW", 3: "C44B16/SW", 4: "C43D10/NW"}
# Both release PDFs are scans of blank pages. Limit the exception to these
# exact bytes so a corrected edition will be processed normally.
BLANK_RELEASE = {
    "OD-73O_6_NW.pdf": "2222ed6721f05b27e000f9cee85b9fd89c94e5c9026b89c75c4e664b5b9beaa8",
    "OD-73O_6_SE.pdf": "e96f7bef610954d9fd47494243e063e621d66cfa18f76a5f8e12e9cc357386f8",
}
# The signed OD 94 PDF stores the map sideways. Preserve the publisher's PDF
# and present a north-up page to the frame detector and the raster exporter.
SIDEWAYS_SOURCES = {
    "OD-73O_6_NW.pdf": "9771b934c684c4fb9c70069aa6ea804e09c3f16f7027d6aa0793f153be84458d"
}
gdal.UseExceptions()
cv2.setNumThreads(1)


def read(path):
    return json.loads(path.read_text())


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", delete=False) as stream:
        json.dump(obj, stream, allow_nan=False)
    os.replace(stream.name, path)


def polygon(geometry):
    return ogr.CreateGeometryFromJson(json.dumps(geometry)).MakeValid()


def polygon_parts(geom):
    if geom.GetGeometryName() == "POLYGON":
        yield geom
    elif geom.GetGeometryName() in ("MULTIPOLYGON", "GEOMETRYCOLLECTION"):
        for child in geom:
            yield from polygon_parts(child)


def mumbai_district_masks(frame, features, names, sheets):
    mumbai = next(n for n in names if sheets[n]["district_edition"] == "Mumbai")
    other = next(n for n in names if n != mumbai)
    # The Mumbai edition also carries the offshore map west of the city.
    # The adjoining district's edition covers its named taluks in the grid.
    pieces = ogr.Geometry(ogr.wkbMultiPolygon)
    for feature in features:
        district = feature["properties"]["DISTRICT"].strip().casefold()
        if not district or district in {"mumbai city", "mumbai suburban"}:
            continue
        for part in polygon_parts(polygon(feature["geometry"])):
            pieces.AddGeometry(part)
    if not pieces.GetGeometryCount():
        raise ValueError(f"No adjoining district coverage for {other}")
    adjoining = frame.Intersection(pieces.UnionCascaded()).MakeValid()
    return {other: adjoining, mumbai: frame.Difference(adjoining).MakeValid()}


def publisher_grids(layers):
    grids = {}
    for path in sorted(layers.glob("*.geojson")):
        if "Taluk" in path.name:
            continue
        for feature in read(path)["features"]:
            key = "".join(feature["properties"]["OSM_25K_IN"].upper().split())
            region = polygon(feature["geometry"])
            west, east, south, north = region.GetEnvelope()
            bounds = [west, south, east, north]
            if key in grids and grids[key] != bounds:
                raise ValueError(f"Inconsistent grid {key}")
            grids[key] = bounds
    return grids


def catalog(layers=None):
    sheets = read(DATA / "sheetmap.json")
    reference = Path(__file__).with_name("release")
    if layers is None:
        with (reference / "grid.csv").open() as stream:
            grids = {
                row["sheet"]: [
                    float(row[k]) for k in ("west", "south", "east", "north")
                ]
                for row in csv.DictReader(stream)
            }
        taluks = reference / "maharashtra-taluks.geojson"
    else:
        grids = publisher_grids(layers)
        taluks = layers / "MH_OSM_25K_Grid_Taluk.geojson"
    groups = defaultdict(list)
    blocks = {}
    for name, meta in sheets.items():
        if meta.get("georeference") is False:
            continue
        indexed = "".join(meta["osm_sheet_id"].upper().split())
        block = re.fullmatch(r"([A-Z]\d{2}[A-Z])\d+/[NS][EW]", indexed).group(1)
        soi_block = meta["soi_sheet_id"].split("_")[0]
        if blocks.setdefault(block, soi_block) != soi_block:
            raise ValueError(f"Conflicting 1-degree sheet for {block}")
        series = meta["state_series_no"]
        printed = indexed
        if name.startswith("WB-") and meta.get("map_type") == "Draft":
            printed = WB_PRINTED[series]
        elif name.startswith("PY-"):
            printed = PY_PRINTED.get(series, indexed)
        # The original, mislabeled release scan of GJ 112 actually prints 122.
        if name == "GJ-46B_4_SE.pdf" and not meta.get("printed_sheet_verified"):
            printed = "F42L16/NE"
        groups[printed].append(name)
    parts = defaultdict(lambda: defaultdict(list))
    for feature in read(DATA / "overlaps.geojson")["features"]:
        props = feature["properties"]
        osm_id = "".join(props["OSM_25K_IN"].upper().split())
        parts[osm_id][props["state_code"]].append(feature)

    mh_districts = defaultdict(list)
    if any("district_edition" in row for row in sheets.values()):
        for f in read(taluks)["features"]:
            mh_districts["".join(f["properties"]["OSM_25K_IN"].upper().split())].append(
                f
            )

    entries = {}
    for osm_id, names in groups.items():
        block, number, quad = re.fullmatch(
            r"([A-Z]\d{2}[A-Z])(\d+)/(\w+)", osm_id
        ).groups()
        sheet_id = f"{blocks[block]}_{number}_{quad}"
        bounds = grids[osm_id]
        w, s, e, n = bounds
        frame = polygon(
            {
                "type": "Polygon",
                "coordinates": [[[w, n], [w, s], [e, s], [e, n], [w, n]]],
            }
        )
        cuts = {}
        district_pair = len(names) == 2 and all(
            n.startswith("MH-") and "district_edition" in sheets[n] for n in names
        )
        if district_pair:
            cuts = mumbai_district_masks(frame, mh_districts[osm_id], names, sheets)
            if min(g.GetArea() for g in cuts.values()) <= 0:
                raise ValueError(f"Empty district coverage for {sheet_id}")
        elif len(names) > 1:
            if len(names) != 2:
                raise ValueError(f"Expected two editions for {sheet_id}")
            states = [name.split("-")[0] for name in names]
            # Prefer an enclave's own surveyed territory, then the first available
            # state layer, as in generate_coverage.py. The complementary polygon
            # must use the very same line, including offshore and unnamed areas.
            state = next(
                code
                for code in sorted(states, key=lambda c: (c not in ("PY", "DD"), c))
                if code in parts[osm_id]
            )
            covered = ogr.Geometry(ogr.wkbMultiPolygon)
            for feature in parts[osm_id][state]:
                props = feature["properties"]
                if not (props.get("TALUK_NAME") or props.get("Mandal") or "").strip():
                    continue
                geom = polygon(feature["geometry"])
                for piece in polygon_parts(geom):
                    covered.AddGeometry(piece)
            primary = frame.Intersection(covered.UnionCascaded()).MakeValid()
            other = next(code for code in states if code != state)
            cuts = {state: primary, other: frame.Difference(primary).MakeValid()}
            if (
                min(g.GetArea() for g in cuts.values()) <= 0
                or abs(sum(g.GetArea() for g in cuts.values()) - frame.GetArea()) > 1e-9
            ):
                raise ValueError(f"Invalid partition for {sheet_id}")
        for name in names:
            code = name.split("-")[0]
            edition = sheets[name].get("district_edition")
            entries[name] = {
                "output": f"{code}-{sheet_id}{'-' + edition if edition else ''}.tif",
                "osm_sheet_id": osm_id,
                "bounds": bounds,
                "cut": json.loads(cuts[name if district_pair else code].ExportToJson())
                if cuts
                else None,
            }
            if edition:
                entries[name]["district_edition"] = edition
                entries[name]["district_clipped"] = district_pair
            if sheets[name].get("page_rotation"):
                entries[name]["page_rotation"] = sheets[name]["page_rotation"]
                entries[name]["source_sha256"] = sheets[name]["source_sha256"]
            if code == "WB" and sheets[name].get("map_type") == "Draft":
                entries[name]["geopdf_page"] = (
                    list(WB_PRINTED).index(sheets[name]["state_series_no"]) + 1
                )
    with Path(__file__).with_name("reviewed_corners.csv").open() as stream:
        for row in csv.DictReader(stream):
            entry = entries[row["source"]]
            entry["source_sha256"] = row["source_sha256"]
            entry.setdefault("reviewed", {})[row["corner"]] = [
                float(row["page_x_pt"]),
                float(row["page_y_pt"]),
            ]
    for name, digest in BLANK_RELEASE.items():
        path = DATA / "raw" / name
        if path.is_file():
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() == digest:
                    entries[name]["unavailable"] = "Published release scan is blank"
    return entries


def apply_release_controls(entries):
    """Attach the exact page points and checksums used to publish these editions."""
    from release_files import files

    checksums = files()
    with (Path(__file__).with_name("release") / "controls.csv").open() as stream:
        controls = {row["source"]: row for row in csv.DictReader(stream)}
    for name, entry in entries.items():
        if entry.get("unavailable"):
            continue
        row = controls[name]
        entry["release_points"] = [
            [float(row[f"{corner}_{axis}_pt"]) for axis in ("x", "y")]
            for corner in ("NW", "SW", "SE", "NE")
        ]
        entry["release_sha256"] = checksums[Path("data/raw") / name]["sha256"]


def render(page, width):
    scale = width / page.rect.width
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False
    )
    return np.frombuffer(pix.samples_mv, np.uint8).reshape(
        pix.height, pix.width, 3
    ).copy(), scale


def side_strip(image, side):
    # All four strips have the direction along the edge in columns. Row
    # numbers increase down the page for horizontal edges, right for vertical.
    horizontal = side in ("top", "bottom")
    a = image if horizontal else image.T
    h, w = a.shape
    along = (0.20, 0.56) if horizontal else (0.24, 0.76)
    normal = {
        "top": (0, 0.29),
        "bottom": (0.68, 1),
        "left": (0, 0.28),
        "right": (0.51, 0.84),
    }[side]
    x0, x1 = [round(w * v) for v in along]
    y0, y1 = [round(h * v) for v in normal]
    return np.ascontiguousarray(a[y0:y1, x0:x1]), x0, y0


def coarse_edge(image, side):
    # The CZMP graticule has regularly alternating bars. A line contour from
    # a legend or page border has no energy at this spatial frequency.
    strip, x0, y0 = side_strip(image, side)
    h, w = strip.shape
    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)[:, None]
    page_width = image.shape[1]
    nfft = cv2.getOptimalDFTSize(w * 2)
    freqs = np.fft.rfftfreq(nfft)
    use = (freqs > 10 / page_width) & (freqs < 26 / page_width)
    window = np.hanning(w)
    best = None
    for angle in (0, -0.009, 0.009, -0.021, 0.021, -0.038, 0.038):
        sampled = cv2.remap(
            strip,
            np.broadcast_to(xs, (h, w)).copy(),
            ys + (xs - w / 2) * angle,
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        centred = sampled - np.average(sampled, axis=1, weights=window)[:, None]
        spectrum = (
            np.abs(np.fft.rfft(centred * window, n=nfft, axis=1))[:, use] / window.sum()
        )
        idx, freq = np.unravel_index(spectrum.argmax(), spectrum.shape)
        strength = spectrum[idx, freq]
        if best is None or strength > best[0]:
            best = (
                strength,
                angle,
                y0 + idx - angle * (x0 + w / 2),
                1 / freqs[use][freq],
            )
    return best


def refine_edge(a, side, guess, span, scale):
    # As in TopoMapProcessor.find_lines, use elongated one-dimensional
    # morphological filtering to suppress lettering. In each printed bar,
    # locate its inner boundary and robustly fit the neatline through it.
    a = a if side in ("top", "bottom") else a.T
    _, slope, intercept, period = guess
    xs = np.arange(
        math.ceil(span[0] * scale), math.floor(span[1] * scale), 2, dtype=np.int32
    )
    width = max(6, round(0.011 * scale * 1600))
    offsets = np.arange(-width, width + 1)
    centres = slope * xs + intercept * scale
    yy = np.rint(centres).astype(int)[None, :] + offsets[:, None]
    strip = a[np.clip(yy, 0, a.shape[0] - 1), np.clip(xs, 0, a.shape[1] - 1)]
    length = max(3, round(period * scale / 2 * 0.20))
    smooth = cv2.morphologyEx(strip, cv2.MORPH_CLOSE, np.ones((1, length), np.uint8))
    lower, upper = np.percentile(smooth, [15, 85], axis=1)
    contrast = upper - lower
    # Use the spectral seed. Map detail beside the frame can have higher
    # contrast than the bars, but lacks their regular spacing.
    centre = width
    row = smooth[centre].astype(float)
    dark = row < lower[centre] + 0.28 * contrast[centre]
    light = row > upper[centre] - 0.28 * contrast[centre]
    if contrast[centre] < 15 or min(dark.sum(), light.sum()) < 10:
        raise ValueError(f"{side} frame bars have insufficient contrast")
    direction = 1 if side in ("top", "left") else -1
    # At the map side of the band its alternating signal disappears. Estimate
    # this position in overlapping windows to follow slight skew and bending.
    points = []
    step = max(12, round(period * scale / 4))
    for i in range(0, len(xs) - 2 * step, step):
        sl = slice(i, i + 2 * step)
        dark_bars, light_bars = dark[sl], light[sl]
        if min(dark_bars.sum(), light_bars.sum()) < step * 0.18:
            continue
        local = strip[:, sl].astype(float)
        profile = np.median(local[:, light_bars], axis=1) - np.median(
            local[:, dark_bars], axis=1
        )
        threshold = 0.50 * profile[centre]
        if threshold < 9:
            continue
        j = centre
        while 0 <= j + direction < len(profile) and profile[j + direction] > threshold:
            j += direction
        k = j + direction
        if not 0 <= k < len(profile):
            continue
        fraction = np.clip(
            (profile[j] - threshold) / max(1, profile[j] - profile[k]), 0, 1
        )
        x = float(xs[sl].mean())
        points.append(
            [x, slope * x + intercept * scale + offsets[j] + direction * fraction + 0.5]
        )
    if len(points) < 5:
        raise ValueError(f"{side} has only {len(points)} measured frame sections")
    x, y = np.array(points).T
    keep = np.ones(len(x), dtype=bool)
    for _ in range(3):
        m, b = np.polyfit(x[keep], y[keep], 1)
        residual = np.abs(y - m * x - b)
        keep = residual < max(0.9 * scale, np.median(residual) * 3)
        if keep.sum() < 4:
            raise ValueError(f"{side} has inconsistent frame sections")
    error = np.sqrt(np.mean(residual[keep] ** 2))
    return (m, b), {
        "contrast": round(float(contrast[centre]), 1),
        "sections": int(keep.sum()),
        "span": round(float(np.ptp(x[keep]) / (xs[-1] - xs[0])), 2),
        "rms": round(float(error), 2),
        "strength": round(float(guess[0]), 2),
    }


def intersections(lines):
    corners = []
    for horiz, vert in (
        ("top", "left"),
        ("bottom", "left"),
        ("bottom", "right"),
        ("top", "right"),
    ):
        h, k = lines[horiz]
        v, b = lines[vert]
        x = (v * k + b) / (1 - v * h)
        corners.append([x, h * x + k])
    return np.array(corners)


def frame(page):
    image, factor = render(page, 1600)
    gray = image.min(axis=2)
    seeds = {s: coarse_edge(gray, s) for s in SIDES}
    approx = intersections({s: seeds[s][1:3] for s in SIDES})
    xmin, ymin = approx.min(axis=0)
    xmax, ymax = approx.max(axis=0)
    if min(xmax - xmin, ymax - ymin) < 450:
        raise ValueError("Implausible map frame")
    lines, metrics = {}, {}
    for side in SIDES:
        a, b = (xmin, xmax) if side in ("top", "bottom") else (ymin, ymax)
        span = (a + (b - a) * 0.025, b - (b - a) * 0.025)
        lines[side], metrics[side] = refine_edge(gray, side, seeds[side], span, 1)
    corners = intersections(lines)
    return corners / factor, metrics, image, factor


def detect(name):
    path = DATA / "raw" / name
    try:
        with pymupdf.open(path) as doc:
            if len(doc) != 1:
                raise ValueError(f"{len(doc)} pages")
            corners, metrics, image, scale = frame(doc[0])
        stem = Path(name).stem
        audit = {"name": name, "corners_pt": corners.tolist(), "edges": metrics}
        write(WORK / "review" / (stem + ".json"), audit)
        overlay = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        for i, p in enumerate(corners * scale):
            cv2.circle(overlay, tuple(np.rint(p).astype(int)), 9, (255, 0, 255), 2)
        cv2.imwrite(
            str(WORK / "review" / (stem + ".jpg")),
            cv2.resize(overlay, (640, round(image.shape[0] * 0.4))),
        )
        return name, metrics
    except Exception as exc:  # noqa: BLE001 - report the failing sheet to the batch caller
        return name, str(exc)


def geopdf_controls(page, entry):
    """Invert the original page transform at the four graticule coordinates."""
    booklet = DATA / "misc" / "WB Draft CZMP 2019 for North 24 Parganas.pdf"
    number = entry["geopdf_page"]
    w, s, e, n = entry["bounds"]
    with gdal.Open(f"PDF:{number}:{booklet}") as ds:
        if (
            not ds.GetSpatialRef().IsGeographic()
            or "WGS" not in ds.GetSpatialRef().GetName()
        ):
            raise ValueError("Unexpected GeoPDF coordinate system")
        transform = ds.GetGeoTransform()
        inverse = gdal.InvGeoTransform(transform)
        pixels = np.array(
            [
                gdal.ApplyGeoTransform(inverse, x, y)
                for x, y in ((w, n), (w, s), (e, s), (e, n))
            ]
        )
        dimensions = np.array([ds.RasterXSize, ds.RasterYSize])
        if not np.all((pixels > 0) & (pixels < dimensions)):
            raise ValueError("Grid falls outside the original GeoPDF page")
        points = pixels / dimensions * [page.rect.width, page.rect.height]
    with pymupdf.open(booklet) as original:
        native_page = original[number - 1]
        if native_page.rect != page.rect:
            raise ValueError("Release image and original GeoPDF page sizes differ")
        # Verify page identity and full-page registration against the release JPEG.
        first, _ = render(native_page, 1000)
        second, _ = render(page, 1000)
        a = cv2.cvtColor(first, cv2.COLOR_RGB2GRAY)[70:-65, 75:665]
        b = cv2.cvtColor(second, cv2.COLOR_RGB2GRAY)[70:-65, 75:665]
        shift, response = cv2.phaseCorrelate(a.astype("f"), b.astype("f"))
        if np.linalg.norm(shift) > 0.8 or response < 0.65:
            raise ValueError(
                f"Release JPEG registration failed on page {number}: {shift}, {response}"
            )
    return points, {
        "geopdf_page": number,
        "geopdf": booklet.name,
        "transform": transform,
        "page_registration_shift_px_at_1000": shift,
        "page_registration_response": response,
    }


def process(item):
    name, entry = item
    path = DATA / "raw" / name
    stem = Path(name).stem
    if entry.get("unavailable"):
        return name, "blank source"
    target = OUT / entry["output"]
    method = (
        "publisher GeoPDF"
        if "geopdf_page" in entry
        else "local inner-frame intersection"
    )
    if entry.get("reviewed"):
        method = "visually reviewed inner-frame intersection"
    audit_path = WORK / "corners" / (stem + ".json")
    with path.open("rb") as source:
        source_digest = hashlib.file_digest(source, "sha256").hexdigest()
    inputs = hashlib.sha256(
        json.dumps([source_digest, entry], sort_keys=True).encode()
    ).hexdigest()
    if (
        target.exists()
        and audit_path.exists()
        and read(audit_path).get("input_sha256") == inputs
    ):
        with gdal.Open(str(target)) as previous:
            if (
                previous.GetSpatialRef().GetAuthorityCode(None) == "3857"
                and previous.GetMetadataItem("EXPORT_PROCESSOR") == PROCESSOR
                and (
                    not entry["cut"]
                    or previous.GetMetadataItem("MASK_OVERVIEW_RESAMPLING") == "NEAREST"
                )
                and previous.GetMetadataItem("CONTROL_METHOD") == method
                and previous.GetMetadataItem("SOURCE_SHEET") == name
                and previous.GetMetadataItem("OSM_SHEET_ID") == entry["osm_sheet_id"]
            ):
                return name, "exists"
    try:
        if entry.get("release_points") and source_digest != entry["release_sha256"]:
            raise ValueError(
                "Released control points belong to a different source revision"
            )
        if entry.get("reviewed") and source_digest != entry["source_sha256"]:
            raise ValueError("Reviewed controls belong to a different source revision")
        with pymupdf.open(path) as doc, pymupdf.open() as oriented:
            if len(doc) != 1:
                raise ValueError(f"{len(doc)} pages")
            page = doc[0]
            rotation = entry.get("page_rotation") or (
                90 if name in SIDEWAYS_SOURCES else 0
            )
            if rotation and page.rect.height > page.rect.width:
                expected_hash = entry.get("source_sha256") or SIDEWAYS_SOURCES[name]
                if source_digest != expected_hash:
                    raise ValueError("Review the orientation of this source revision")
                page = oriented.new_page(width=page.rect.height, height=page.rect.width)
                page.show_pdf_page(page.rect, doc, 0, rotate=-rotation)
            points, metrics, _, _ = frame(page)
            if any(
                edge["strength"] < 11 or edge["span"] < 0.40 or edge["rms"] > 2
                for edge in metrics.values()
            ):
                raise ValueError("Weak printed frame: " + json.dumps(metrics))
            bbox = points.max(axis=0) - points.min(axis=0)
            if not 0.8 < bbox[0] / bbox[1] < 1.17:
                raise ValueError(
                    f"Unexpected printed graticule aspect {bbox[0] / bbox[1]:.3f}"
                )
            coarse = points.copy()
            joints, evidence = refine(page, coarse)
            reference = {}
            if "geopdf_page" in entry:
                points, reference = geopdf_controls(page, entry)
            else:
                points = joints.copy()
                for i, corner in enumerate(evidence):
                    label = ("NW", "SW", "SE", "NE")[i]
                    if label in entry.get("reviewed", {}):
                        points[i] = entry["reviewed"][label]
                        continue
                    if (
                        min(corner["horizontal"], corner["vertical"]) < 6
                        or corner["at_search_limit"]
                        or corner["near_far_px"] > 3
                    ):
                        raise ValueError(f"Review corner {i}: {corner}")
            if "release_points" in entry:
                measured = points
                points = np.array(entry["release_points"])
                reference["released_controls"] = True
                reference["remeasured_max_delta_pt"] = float(
                    np.linalg.norm(measured - points, axis=1).max()
                )
            audit = {
                "input_sha256": inputs,
                "method": method,
                "reviewed": entry.get("reviewed", {}),
                "first_pass_pt": coarse.tolist(),
                "inner_intersections_pt": joints.tolist(),
                "inner_line_evidence": evidence,
                **reference,
                "source": name,
                "page_size_pt": list(page.rect)[2:],
                "corners_pt": points.tolist(),
                "order": ["NW", "SW", "SE", "NE"],
                "edges": metrics,
                "bounds": entry["bounds"],
                "state_mask": entry["cut"] is not None
                and not entry.get("district_clipped"),
                "district_mask": entry.get("district_clipped", False),
            }
            with tempfile.TemporaryDirectory(dir=OUT) as directory:
                tmp = Path(directory) / target.name
                export_sheet(name, entry, points, page, tmp, method)
                os.replace(tmp, target)
            write(audit_path, audit)
        return name, "ok"
    except Exception as exc:  # noqa: BLE001 - report the failing sheet to the batch caller
        return name, f"{type(exc).__name__}: {exc}"


def verify(entries):
    """Check the on-disk products, including the pixel partition of each shared sheet."""
    footprints = []
    controls = []
    pairs = defaultdict(list)
    unavailable = {
        name: entry["unavailable"]
        for name, entry in entries.items()
        if entry.get("unavailable")
    }
    entries = {
        name: entry for name, entry in entries.items() if name not in unavailable
    }
    expected_files = {entry["output"] for entry in entries.values()}
    actual_files = {path.name for path in OUT.glob("*.tif")}
    if actual_files != expected_files:
        raise ValueError(
            f"Missing outputs: {sorted(expected_files - actual_files)}. "
            f"Extra outputs: {sorted(actual_files - expected_files)}"
        )
    if len(expected_files) != len(entries):
        raise ValueError("More than one source points to the same output")
    for name, entry in entries.items():
        w, s, e, n = entry["bounds"]
        with gdal.Open(str(OUT / entry["output"])) as ds:
            nx, ny = ds.RasterXSize, ds.RasterYSize
            transform, size = sheet_grid(entry["bounds"])
            if not np.allclose(ds.GetGeoTransform(), transform, rtol=0, atol=1e-7):
                raise ValueError(f"Wrong extent for {name}")
            if (
                ds.GetSpatialRef().GetAuthorityCode(None) != "3857"
                or ds.GetMetadataItem("EXPORT_PROCESSOR") != PROCESSOR
                or ds.GetMetadataItem("LAYOUT", "IMAGE_STRUCTURE") != "COG"
                or ds.GetMetadataItem("NAME", "TILING_SCHEME") != "GoogleMapsCompatible"
                or ds.GetMetadataItem("ZOOM_LEVEL", "TILING_SCHEME") != "16"
            ):
                raise ValueError(f"Wrong CRS or layout for {name}")
            if (
                ds.GetMetadataItem("SOURCE_SHEET") != name
                or ds.GetMetadataItem("OSM_SHEET_ID") != entry["osm_sheet_id"]
            ):
                raise ValueError(f"Wrong sheet identity for {name}")
            audit = read(WORK / "corners" / (Path(name).stem + ".json"))
            expected_method = (
                "publisher GeoPDF"
                if "geopdf_page" in entry
                else "visually reviewed inner-frame intersection"
                if entry.get("reviewed")
                else "local inner-frame intersection"
            )
            if (
                ds.GetMetadataItem("CONTROL_METHOD") != expected_method
                or audit.get("method") != expected_method
            ):
                raise ValueError(f"Stale corner solution for {name}")
            final = np.array(audit["corners_pt"], np.float32)
            initial = np.array(audit["first_pass_pt"], np.float32)
            unit_square = np.array([[0, 0], [0, 1], [1, 1], [1, 0]], np.float32)
            matrix = cv2.getPerspectiveTransform(final, unit_square)

            page_points = np.array(
                [initial, audit["inner_intersections_pt"]], np.float32
            )
            uv = cv2.perspectiveTransform(page_points, matrix)
            metres = [(e - w) * 111320 * math.cos(math.radians(n)), -(n - s) * 110700]
            displacement, visual = (uv - unit_square) * metres
            for i, label in enumerate(audit["order"]):
                if label in entry.get("reviewed", {}):
                    method = "visual review"
                elif "geopdf_page" in entry:
                    method = "publisher GeoPDF"
                else:
                    method = "local inner-frame intersection"
                controls.append(
                    {
                        "source": name,
                        "file": entry["output"],
                        "corner": label,
                        "method": method,
                        "first_pass_x_pt": round(float(initial[i, 0]), 5),
                        "first_pass_y_pt": round(float(initial[i, 1]), 5),
                        "final_x_pt": round(float(final[i, 0]), 5),
                        "final_y_pt": round(float(final[i, 1]), 5),
                        "first_pass_to_final_m": round(
                            float(np.linalg.norm(displacement[i])), 2
                        ),
                        "detected_to_geopdf_m": round(
                            float(np.linalg.norm(visual[i])), 2
                        )
                        if "geopdf_page" in entry
                        else "",
                        "near_far_px": audit["inner_line_evidence"][i]["near_far_px"],
                    }
                )
            geom = entry["cut"] or {
                "type": "Polygon",
                "coordinates": [sheet_ring(entry["bounds"])],
            }
            if (nx, ny) != size or ds.RasterCount != 3:
                raise ValueError(f"Wrong output grid for {name}")
            expected_mask = coverage_mask(geom, transform, size)
            band = ds.GetRasterBand(1)
            if (
                not band.GetMaskFlags() & gdal.GMF_PER_DATASET
                or band.GetMaskBand().ReadRaster() != expected_mask
            ):
                raise ValueError(f"Raster disagrees with footprint for {name}")
            overview = ds.GetRasterBand(1).GetOverview(0)
            if overview is None:
                raise ValueError(f"Missing overviews for {name}")
            # Read the image from the actual overview IFD as a smoke test.
            pixels = overview.ReadAsArray(buf_xsize=96, buf_ysize=96)
            if pixels is None or not pixels.size:
                raise ValueError(f"Unreadable image for {name}")
        footprint = entry["cut"] or {
            "type": "Polygon",
            "coordinates": [[[w, n], [w, s], [e, s], [e, n], [w, n]]],
        }
        footprints.append(
            {
                "type": "Feature",
                "geometry": footprint,
                "properties": {
                    "source": name,
                    "file": entry["output"],
                    "osm_sheet_id": entry["osm_sheet_id"],
                    "state_clipped": entry["cut"] is not None
                    and not entry.get("district_clipped"),
                    **(
                        {
                            "district_edition": entry["district_edition"],
                            "district_clipped": entry["district_clipped"],
                        }
                        if "district_edition" in entry
                        else {}
                    ),
                },
            }
        )
        if entry["cut"]:
            pairs[entry["osm_sheet_id"]].append(entry["output"])
    for osm_id, names in pairs.items():
        if len(names) != 2:
            raise ValueError(f"Missing an edition of {osm_id}")
        with (
            gdal.Open(str(OUT / names[0])) as first,
            gdal.Open(str(OUT / names[1])) as second,
        ):
            left = first.GetRasterBand(1).GetMaskBand()
            right = second.GetRasterBand(1).GetMaskBand()
            entry = next(e for e in entries.values() if e["output"] == names[0])
            grid, size = sheet_grid(entry["bounds"])
            footprint = {
                "type": "Polygon",
                "coordinates": [sheet_ring(entry["bounds"])],
            }
            inside = np.frombuffer(
                coverage_mask(footprint, grid, size), dtype=np.uint8
            ).reshape(size[::-1])
            count = 0
            for y in range(0, left.YSize, 512):
                height = min(512, left.YSize - y)
                a = left.ReadAsArray(0, y, left.XSize, height)
                b = right.ReadAsArray(0, y, right.XSize, height)
                count += np.count_nonzero(
                    (a.astype(np.uint16) + b) != inside[y : y + height]
                )
            if count:
                raise ValueError(f"{osm_id}: {count} pixels are gaps or overlaps")
            first_band, second_band = first.GetRasterBand(1), second.GetRasterBand(1)
            if first_band.GetOverviewCount() != second_band.GetOverviewCount():
                raise ValueError(f"Mismatched overview levels for {osm_id}")
            for i in range(first_band.GetOverviewCount()):
                a = first_band.GetOverview(i).GetMaskBand().ReadAsArray()
                b = second_band.GetOverview(i).GetMaskBand().ReadAsArray()
                step = 2 ** (i + 1)
                if np.any(a & b) or not np.array_equal(a | b, inside[::step, ::step]):
                    raise ValueError(
                        f"{osm_id}: overview {i} masks disagree with the full sheet"
                    )
    write(
        OUT / "footprints.geojson",
        {"type": "FeatureCollection", "features": footprints},
    )
    with tempfile.NamedTemporaryFile(
        dir=OUT, mode="w", delete=False, newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(controls[0]))
        writer.writeheader()
        writer.writerows(controls)
    os.replace(stream.name, OUT / "corner-audit.csv")
    write(OUT / "unavailable.json", unavailable)
    district_count = len(
        {e["osm_sheet_id"] for e in entries.values() if e.get("district_clipped")}
    )
    print(
        f"Verified {len(entries)} COGs, {len(pairs) - district_count} complementary state-mask pairs "
        f"and {district_count} district-mask pairs. "
        f"{len(unavailable)} blank release scans."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["catalog", "detect", "export", "verify"])
    parser.add_argument("names", nargs="*")
    parser.add_argument("-j", type=int, default=4)
    parser.add_argument(
        "--layers", type=Path, help="Use original publisher grids in this directory"
    )
    parser.add_argument(
        "--release-controls",
        action="store_true",
        help="Export with the published source-page control points",
    )
    args = parser.parse_intermixed_args()
    if args.release_controls and args.operation != "export":
        parser.error("--release-controls applies to export")
    if args.operation == "catalog":
        write(WORK / "catalog.json", catalog(args.layers))
    elif args.operation == "verify":
        verify(catalog(args.layers))
    else:
        (WORK / "review").mkdir(parents=True, exist_ok=True)
        OUT.mkdir(parents=True, exist_ok=True)
        gdal.SetCacheMax(64 * 1024**2)
        catalog_data = catalog(args.layers)
        if args.release_controls:
            apply_release_controls(catalog_data)
        names = args.names or sorted(catalog_data)
        with ProcessPoolExecutor(args.j) as pool:
            if args.operation == "detect":
                results = pool.map(detect, names)
            else:
                results = pool.map(process, ((n, catalog_data[n]) for n in names))
            failures = 0
            for name, result in results:
                print(name, json.dumps(result), flush=True)
                if isinstance(result, str) and result not in (
                    "ok",
                    "exists",
                    "blank source",
                ):
                    failures += 1
            if failures:
                raise SystemExit(f"{failures} sheet(s) need review")
