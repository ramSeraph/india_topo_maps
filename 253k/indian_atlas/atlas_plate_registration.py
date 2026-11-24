"""Relate a sheet's measured printed graticule to its nominal Walker rectangle."""
import numpy as np


class PlateRegistration:
    """Interpolate four angular differences across the scanned plate."""

    def __init__(self, corners, native, nominal):
        corners = np.asarray(corners, dtype=float)
        self.origin = corners.mean(axis=0)
        self.scale = np.ptp(corners, axis=0)
        self.corner_offsets = np.asarray(nominal) - np.asarray(native)
        self.coefficients = np.linalg.solve(self._basis(corners), self.corner_offsets)

    def _basis(self, points):
        x, y = ((np.atleast_2d(points) - self.origin) / self.scale).T
        return np.column_stack((np.ones_like(x), x, y, x * y))

    def offset(self, points):
        return self._basis(points) @ self.coefficients

    def controls(self, records):
        if not records:
            return []
        points = [[r['pixel'], r['line']] for r in records]
        out = []
        for record, delta in zip(records, self.offset(points), strict=True):
            item = dict(record)
            if item['kind'] == 'crossing':
                item['longitude'] += delta[0]
                item['latitude'] += delta[1]
            else:
                item['known_value'] += delta[int(item['known_axis'] == 'latitude')]
            out.append(item)
        return out
