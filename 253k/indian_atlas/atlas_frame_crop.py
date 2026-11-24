"""Crop geometry from verified scan-frame corners, without inspecting map ink."""
import numpy as np


def measured_frame_crop(corners, guides, inset):
    """Inset reviewed piecewise-linear frame sides, keeping their shared vertices."""
    names = ('north', 'east', 'south', 'west')
    if not np.isfinite(inset) or inset < 0:
        raise ValueError('Expected a finite, nonnegative frame inset')
    pieces = []
    for i, name in enumerate(names):
        along = i % 2
        points = np.asarray(guides[name], float)
        if not np.isfinite(points).all() or not np.all(np.diff(points[:, 0]) > 0):
            raise ValueError(f'Invalid frame guides on {name}')
        if along:
            points = points[:, ::-1]
        if i >= 2:
            points = points[::-1]
        if not np.allclose(points[[0,-1]], [corners[i], corners[(i+1)%4]], atol=.01, rtol=0):
            raise ValueError(f'{name} endpoints differ from the reviewed corners')
        pieces.append(points[:-1])
    vertices = np.vstack(pieces)
    delta = np.roll(vertices, -1, axis=0) - vertices
    normals = np.column_stack([-delta[:,1], delta[:,0]]) / np.linalg.norm(delta, axis=1)[:,None]
    previous = np.roll(normals, 1, axis=0)
    divisor = 1 + np.sum(previous*normals, axis=1)
    if np.any(divisor < .2):
        raise ValueError('Frame guides reverse direction')
    inner = vertices + inset * (previous+normals) / divisor[:,None]
    if np.any(np.sum((np.roll(inner,-1,axis=0)-inner)*delta, axis=1) <= 0):
        raise ValueError('Inset collapses a frame segment')
    ring = np.vstack([inner,inner[0]])
    offsets = np.r_[0,np.cumsum([len(piece) for piece in pieces])]
    edges = [dict(side=name,points=ring[offsets[i]:offsets[i+1]+1].tolist()) for i,name in enumerate(names)]
    return inner[offsets[:-1]].tolist(), edges, ring.tolist()


def straight_frame_crop(corners, inset=4.0, samples=150):
    """Inset a convex NW, NE, SE, SW pixel quadrilateral by a normal distance.

    Densify straight source edges for subsequent nonlinear reprojection; the
    added vertices are collinear, not independent image measurements.
    """
    corners = np.asarray(corners, dtype=float)
    if corners.shape != (4, 2) or not np.all(np.isfinite(corners)):
        raise ValueError('Four finite frame corners required')
    if not np.isfinite(inset) or inset < 0 or samples < 2:
        raise ValueError('Invalid inset or sample count')
    delta = np.roll(corners, -1, axis=0) - corners
    length = np.linalg.norm(delta, axis=1)
    turns = delta[:, 0] * np.roll(delta[:, 1], -1) - delta[:, 1] * np.roll(delta[:, 0], -1)
    if np.any(length == 0) or np.any(turns <= 0):
        raise ValueError('Frame must be convex and ordered NW, NE, SE, SW in image coordinates')
    normals = np.column_stack([-delta[:, 1], delta[:, 0]]) / length[:, None]
    limits = np.sum(normals * corners, axis=1) + inset
    inner = np.array([np.linalg.solve(normals[[i-1, i]], limits[[i-1, i]]) for i in range(4)])
    if np.any(inner @ normals.T < limits[None, :] - 1e-7):
        raise ValueError('Inset collapses the frame')
    edges = [dict(side=side, points=np.linspace(inner[i], inner[(i+1) % 4], samples).tolist(),
                  maximum_stroke_intensity=None)
             for i, side in enumerate(('north', 'east', 'south', 'west'))]
    ring = [point for edge in edges for point in edge['points'][:-1]] + [inner[0].tolist()]
    return inner.tolist(), edges, ring
