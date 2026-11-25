"""Locate each inner frame corner using the two strokes and the outward mitre."""

import cv2
import numpy as np
import pymupdf


def stroke_response(rgb, dx, dy):
    """Dark ink between two flanks, with a gradient term for dark filled bars."""

    def offset(k):
        return np.roll(rgb, (-dy * k, -dx * k), (0, 1))

    luma = rgb.mean(axis=2)
    left, right = offset(-4).mean(axis=2), offset(4).mean(axis=2)
    ridge = np.maximum(0, np.minimum(left - luma, right - luma))
    gradient = np.linalg.norm(offset(1) - offset(-1), axis=2) / np.sqrt(3)
    return ridge + 0.35 * gradient


def locate(patch, origin, limit=20):
    rgb = cv2.GaussianBlur(patch.astype("f"), (3, 3), 0.65)
    horizontal = stroke_response(rgb, 0, 1)
    vertical = stroke_response(rgb, 1, 0)
    mitre = stroke_response(rgb, 1, -1)
    coords = np.arange(-limit, limit + 1)
    yy, xx = np.meshgrid(coords + origin, coords + origin, indexing="ij")

    def peak(a):
        # Weighted centre of the peak gives a subpixel centre for ink strokes
        # with a flat or double-pixel core.
        y, x = np.unravel_index(np.argmax(a), a.shape)
        near = (np.abs(yy - yy[y, x]) <= 2) & (np.abs(xx - xx[y, x]) <= 2)
        weights = np.where(near, np.maximum(0, a - a[y, x] * 0.84), 0)
        if weights.sum() < 1e-6:
            raise ValueError("No corner response")
        return (
            np.array([np.average(xx, weights=weights), np.average(yy, weights=weights)])
            - origin
        )

    def rays(start, stop):
        r = np.arange(start, stop, 2)
        h = np.median(horizontal[yy[:, :, None], xx[:, :, None] + r], axis=2)
        v = np.median(vertical[yy[:, :, None] + r, xx[:, :, None]], axis=2)
        return h, v

    h, v = rays(5, 40)
    far_h, far_v = rays(42, 90)
    r = np.arange(4, 15, 2)
    diag = np.median(mitre[yy[:, :, None] - r, xx[:, :, None] - r], axis=2)

    def norm(a):
        return a / max(2, a.max())

    # Both rays must be visible. The diagonal points out of the map at the
    # inner corner, distinguishing it from the outer corner of the same box.
    joint = np.sqrt(norm(h) * norm(v))
    far = np.sqrt(norm(far_h) * norm(far_v))
    prior = np.exp(-0.5 * ((xx - origin) ** 2 + (yy - origin) ** 2) / 35**2)
    score = (joint * 0.65 + far * 0.35) * (0.80 + 0.20 * norm(diag)) * prior
    pos = peak(score)
    idx = tuple(np.rint(pos[::-1]).astype(int) + limit)
    split_near = peak(joint * (0.8 + 0.2 * norm(diag)) * prior)
    split_far = peak(far * (0.8 + 0.2 * norm(diag)) * prior)
    evidence = {
        "horizontal": round(float(h[idx]), 2),
        "vertical": round(float(v[idx]), 2),
        "mitre": round(float(diag[idx]), 2),
        "near_far_px": round(float(np.linalg.norm(split_near - split_far)), 2),
        "score": round(float(score[idx]), 3),
        "at_search_limit": bool(np.max(np.abs(pos)) > limit - 1),
    }
    return pos, evidence


def refine(page, points):
    """Measure native-page controls in a 6144-pixel-per-sheet coordinate frame."""
    points = np.asarray(points)
    zoom = 6144 / max(np.ptp(points[:, 0]), np.ptp(points[:, 1]))
    normalized = np.arange(-42, 120, dtype="f")
    yy, xx = np.meshgrid(normalized, normalized, indexing="ij")
    corrected = []
    evidence = []
    for i, point in enumerate(points):
        prev, nxt = points[(i - 1) % 4] - point, points[(i + 1) % 4] - point
        horizontal, vertical = (
            (prev, nxt) if abs(prev[0]) > abs(nxt[0]) else (nxt, prev)
        )
        basis = np.column_stack(
            [
                horizontal / np.linalg.norm(horizontal),
                vertical / np.linalg.norm(vertical),
            ]
        )
        grid = (
            point * zoom + xx[:, :, None] * basis[:, 0] + yy[:, :, None] * basis[:, 1]
        )
        lo = (grid.min((0, 1)) - 2) / zoom
        hi = (grid.max((0, 1)) + 2) / zoom
        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom),
            clip=pymupdf.Rect(*lo, *hi) & page.rect,
            colorspace=pymupdf.csRGB,
        )
        rgb = np.frombuffer(pix.samples_mv, np.uint8).reshape(pix.height, pix.width, 3)
        xy = (grid - [pix.x + 0.5, pix.y + 0.5]).astype("f")
        patch = cv2.remap(rgb, xy[:, :, 0], xy[:, :, 1], cv2.INTER_LINEAR)
        pos, metrics = locate(patch, 42)
        corrected.append(point + basis @ pos / zoom)
        evidence.append(metrics)
    return np.array(corrected), evidence
