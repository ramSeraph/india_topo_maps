"""Resolve reviewed map overprints against the published Atlas sheet grid."""
import numpy as np
from osgeo import ogr

from atlas_book_frame import YS


def polygon(points):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in points:
        ring.AddPoint_2D(float(x), float(y))
    ring.CloseRings()
    geometry = ogr.Geometry(ogr.wkbPolygon)
    geometry.AddGeometry(ring)
    if not geometry.IsValid():
        raise ValueError("Invalid margin cutline")
    return geometry


def polygon_parts(geometry):
    if geometry.IsEmpty():
        return
    name = geometry.GetGeometryName()
    if name == "POLYGON":
        yield geometry
    elif name in ("MULTIPOLYGON", "GEOMETRYCOLLECTION"):
        for member in geometry:
            yield from polygon_parts(member)


def coordinates(poly):
    return [np.array(r.GetPoints())[:, :2] for r in poly]


def box(xmin, ymin, xmax, ymax):
    return polygon([(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)])


def lattice_box(cell):
    west, south, east, north = cell
    return box(-37100 + 67425 * west, YS[south], -37100 + 67425 * east, YS[north])


def transform_polygon(poly, transform, spacing):
    # Segmentize before applying the nonlinear transform, including at holes.
    shape = poly.Clone()
    shape.Segmentize(spacing)
    result = ogr.Geometry(ogr.wkbPolygon)
    for xy in coordinates(shape):
        ring = ogr.Geometry(ogr.wkbLinearRing)
        for x, y in transform(xy):
            ring.AddPoint_2D(float(x), float(y))
        ring.CloseRings()
        result.AddGeometry(ring)
    return result


def resolve(rule, frame_ring, cell, tps, offset, published):
    base = polygon(frame_ring)
    ink = ogr.Geometry(ogr.wkbPolygon)
    for points in rule["include"]:
        ink = ink.Union(polygon(points))
    for points in rule.get("exclude", []):
        ink = ink.Difference(polygon(points))
    extra = ink.Difference(base)
    available = []
    if rule["policy"] == "where_uncovered":
        plane = ogr.Geometry(ogr.wkbPolygon)
        for part in polygon_parts(ink):
            plane = plane.Union(transform_polygon(part, lambda p: tps.forward(p + offset), 12))
        intended = plane.Difference(lattice_box(cell))
        occupied = ogr.Geometry(ogr.wkbPolygon)
        for sid, candidate in published.items():
            if candidate == cell:
                continue
            neighbour = lattice_box(candidate)
            if intended.Intersects(neighbour) and intended.Intersection(neighbour).GetArea() > 1:
                available.append(sid)
                occupied = occupied.Union(neighbour)
        if intended.Difference(occupied).GetArea() < 1:
            extra = ogr.Geometry(ogr.wkbPolygon)
        elif not occupied.IsEmpty():
            xmin, xmax, ymin, ymax = plane.GetEnvelope()
            # Limit inversion to the local source area; neighbouring cells can be
            # much larger than the overprint and extend beyond this scan's TPS.
            overlap = occupied.Intersection(box(xmin-20, ymin-20, xmax+20, ymax+20))
            for part in polygon_parts(overlap):
                cover = transform_polygon(part, lambda p: tps.inverse(p) - offset, 100)
                extra = extra.Difference(cover)
    elif rule["policy"] != "always":
        raise ValueError("Unknown printed margin policy")
    result = base.Union(extra)
    if not result.IsValid():
        raise ValueError("The final display cutline is invalid")
    polygons = [[xy.round(5).tolist() for xy in coordinates(p)] for p in polygon_parts(result)]
    if not polygons:
        raise ValueError("Empty display cutline")
    evidence = dict(policy=rule["policy"], covering_editions=sorted(available),
                    traced_extra_source_pixels=ink.Difference(base).GetArea(),
                    retained_extra_source_pixels=result.GetArea()-base.GetArea())
    return polygons, evidence
