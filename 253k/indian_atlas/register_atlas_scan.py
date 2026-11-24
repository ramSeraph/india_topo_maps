"""Measure an intact Atlas scan using its registered index cell and native engraved rules."""

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares
from atlas_book_frame import SIDES, YS, printed
from atlas_stripe_fit import constraints, pixels
from audit_atlas_tps_rollout import ROOT, read, write
from render_atlas_book_edges import sha
import georeference_atlas001 as hist

TABLE = "data/atlas-graticule-projection.json"


def index_cell(sheet, quarter):
    # Columns and their northern rows read from the collection's printed index.
    if sheet in ("027A", "063A"):
        w, n = {"027A": (-2, 42), "063A": (2, 40)}[sheet]
    else:
        no = int(sheet)
        for first, last, w, n in [
            (17, 17, -4, 34),
            (28, 44, -2, 40),
            (45, 63, 0, 40),
            (64, 83, 2, 38),
            (84, 95, 4, 36),
            (100, 109, 6, 34),
            (110, 116, 8, 32),
            (117, 122, 10, 32),
            (123, 128, 12, 32),
            (129, 137, 14, 32),
            (138, 146, 16, 32),
        ]:
            if first <= no <= last:
                n -= 2 * (no - first)
                break
        else:
            raise ValueError("Sheet absent from intake index transcription")
    e, s = w + 2, n - 2
    if quarter:
        if "N" in quarter:
            s += 1
        else:
            n -= 1
        if "E" in quarter:
            w += 1
        else:
            e -= 1
    return np.c_[-37100 + 67425 * np.array([w, e, e, w]), YS[[n, n, s, s]]]


def stroke(img, u, v, across, slope, search):
    # The coordinate being measured is u. Look along the expected printed rule
    # at a range of displacements across it, without constraining position along it.
    ds = np.arange(-search, search + 1)
    xx = np.rint(u + ds[None, :] + slope * (across - v)[:, None]).astype(int)
    if (
        min(across) < 0
        or max(across) >= img.shape[0]
        or xx.min() < 0
        or xx.max() >= img.shape[1]
    ):
        return
    patch = img[across[:, None], xx].astype(float)
    response = gaussian_filter1d(patch, 3.5, axis=1) - gaussian_filter1d(
        patch, 0.65, axis=1
    )
    groups = np.array(
        [g.mean(axis=0) for g in np.array_split(np.clip(response, -22, 50), 4)]
    )
    score = (groups.mean(axis=0) + np.percentile(groups, 25, axis=0)) * 0.5
    k = 2 + int(np.argmax(score[2:-2]))
    if score[k] < 4.3 or np.count_nonzero(groups[:, k] > 2) < 3:
        return
    weights = np.maximum(0, score[k - 1 : k + 2])
    return float(u + np.average(ds[k - 1 : k + 2], weights=weights)), float(score[k])


def extended_stroke(img, u, v, across, slope):
    """Require two disjoint sets of source strips to locate the same ruled line."""
    offsets = np.arange(-76, 77)
    best = []
    for delta_slope in np.linspace(-0.009, 0.009, 7):
        direction = slope + delta_slope
        xx = np.rint(u + direction * (across - v)[:, None] + offsets).astype(int)
        if xx.min() < 0 or xx.max() >= img.shape[1]:
            continue
        sampled = img[across[:, None], xx].astype(float)
        contrast = gaussian_filter1d(sampled, 4.0, axis=1) - gaussian_filter1d(sampled, 0.65, axis=1)
        groups = np.stack([np.mean(np.clip(g, -12, 24), axis=0) for g in np.array_split(contrast, 12)])
        profiles = [np.median(g, axis=0) for g in (groups[::2], groups[1::2])]
        combined = np.minimum(*profiles)
        peak = int(np.argmax(combined[3:-3])) + 3
        if min(p[peak] - np.median(p) for p in profiles) < 2.4:
            continue
        if max(abs(int(np.argmax(p[3:-3])) + 3 - peak) for p in profiles) > 4:
            continue
        best.append((combined[peak], offsets[peak], direction))
    if best:
        score, displacement, direction = max(best)
        return float(u + displacement), float(score), float(direction)


def affine_fit(obs, start):
    xy = pixels(obs)
    rows, axes, vals = constraints(obs)
    centre, coef = start
    pc = xy.mean(axis=0)
    scale = np.ptp(xy, axis=0).max()
    uv = np.c_[np.ones(len(xy)), (xy - pc) / scale]
    p0 = np.linalg.lstsq(uv, (xy - coef[0]) @ np.linalg.inv(coef[1:]), rcond=None)[0]

    def err(z):
        ll = hist.inverse(uv @ z.reshape(3, 2) * 100000 + centre)
        return (ll[rows, axes] - vals) * 3600

    sol = least_squares(err, p0.ravel(), loss="soft_l1", f_scale=3.0)
    if not sol.success:
        raise ValueError("Affine graticule fit failed")
    plane = uv @ sol.x.reshape(3, 2) * 100000 + centre
    return hist.fit(plane, xy)


def acquire(item, spec):
    sid = item["id"]
    q = item["quarter"]
    nom = index_cell(item["sheet"], q)
    table = read(ROOT / TABLE)
    hist.LATS, hist.RADII, hist.ANGLES = [
        np.array(table[k])
        for k in (
            "latitudes",
            "radius_fathoms",
            "angle_arcseconds_per_longitude_degree",
        )
    ]
    hist.R0 = table["reference_radius_fathoms"]
    corners = np.array(spec["frame_corners"])
    bands = spec["bands"]
    source = ROOT / item["source"]
    gray = cv2.imread(
        str(source),
        cv2.IMREAD_GRAYSCALE
        | (cv2.IMREAD_IGNORE_ORIENTATION if spec.get("ignore_exif_orientation") else 0),
    )
    if list(gray.shape[::-1]) != spec["source_size"]:
        raise ValueError("Orientation differs from the measured frame")
    approximate = hist.fit(hist.project(printed(nom)), corners + 0.5)
    ticks = []
    skipped = []
    for i, side in enumerate(SIDES):
        axis = i % 2
        key = ("longitude", "latitude")[axis]
        signed = (-1, 1, 1, -1)[i]
        g = np.array(spec["crop_edge_guides"][side])
        lo, hi = g[[0, -1], 0]
        vline = np.linspace(lo, hi, 2049)
        # Nominal along-frame coordinates seed the search for the extended
        # five-minute strokes. The actual line locations are measured in the image.
        ideal = printed(np.linspace(nom[i], nom[(i + 1) % 4], 2049))
        if i in (2, 3):
            ideal = ideal[::-1]
        # A manually read printed label can move the search window on an edition.
        # This offset affects the search window only. All saved values come
        # from the numbered ticks in the edition's original convention.
        minute = ideal[:, axis] * 60 + spec.get("margin_seed_minutes", {}).get(side, 0)
        pitch = (hi - lo) / np.ptp(minute)
        order = np.argsort(minute)
        img = gray if not axis else gray.T
        for m in range(
            5 * int(np.ceil((min(minute) + 0.65) / 5)), int(max(minute) - 0.65) + 1, 5
        ):
            u = np.interp(m, minute[order], vline[order])
            fraction = (u - lo) / (hi - lo)
            if any(
                a <= fraction <= b
                for a, b in spec.get("excluded_margin_fractions", {}).get(side, [])
            ):
                skipped.append(
                    dict(
                        side=side,
                        minute=m,
                        reason=spec.get("excluded_margin_notes", {}).get(
                            side, "Scale bar occupies this part of the margin"
                        ),
                    )
                )
                continue
            v = np.interp(u, *g.T)
            sample = np.array([u, v]) if axis == 0 else np.array([v, u])
            f = hist.pixel_to_ll(
                [sample, sample + [1, 0], sample + [0, 1]], approximate
            )[:, axis]
            grad = f[1:] - f[0]
            slope = -grad[1 - axis] / grad[axis]
            across = np.rint(
                v
                + signed
                * (bands[i] + np.arange(4, min(70, max(23, round(1.6 * bands[i])))))
            ).astype(int)
            mid = across.mean()
            result = stroke(
                img,
                u + slope * (mid - v),
                mid,
                across,
                slope,
                max(8, round(1.65 * pitch)),
            )
            if result is None:
                continue
            z, contrast = result
            x, y = (z, mid) if not axis else (mid, z)
            # A label or bar scale can have a strong stem at the sampled depth.
            # Accept the observation only when the same stroke runs out from
            # the edge of the band to the measured position in the margin.
            start = round(np.interp(z, *g.T) + signed * (bands[i] + 3))
            column = np.arange(start, round(mid) + signed, signed)
            if len(column) < 5:
                continue
            centre = np.rint(z + slope * (column - mid)).astype(int)
            if (
                min(column) < 0
                or max(column) >= img.shape[0]
                or centre.min() < 6
                or centre.max() >= img.shape[1] - 6
            ):
                continue
            line = np.min(
                img[column[:, None], centre[:, None] + [-1, 0, 1]], axis=1
            ).astype(float)
            paper = np.minimum(img[column, centre - 5], img[column, centre + 5]).astype(
                float
            )
            ink = paper - line
            if np.mean(ink > 6) < 0.68 or np.median(ink[: min(8, len(ink))]) < 6:
                skipped.append(
                    dict(
                        side=side,
                        minute=m,
                        reason="No continuous printed stroke from band to measured margin point",
                    )
                )
                continue
            ticks.append(
                dict(
                    kind="margin_tick",
                    side=side,
                    known_axis=key,
                    known_value=m / 60,
                    pixel=x + 0.5,
                    line=y + 0.5,
                    line_slope=float(slope),
                    contrast=contrast,
                    role="fit" if (m // 5 + i) % 2 == 0 else "withheld",
                )
            )
    revisions = spec.get("native_observation_revisions", [])
    for revision in revisions:
        if revision["kind"] == "margin_tick":
            matches = [
                tick for tick in ticks
                if tick["side"] == revision["side"]
                and abs(tick["known_value"] - revision["known_value"]) < 1e-9
            ]
            if not matches and revision.get("role") == "withheld":
                ticks.append(dict(revision, known_axis="longitude" if
                                  revision["side"] in ("north", "south") else "latitude"))
                continue
            if len(matches) != 1:
                raise ValueError("Reviewed margin observation could not be identified")
            matches[0].update(pixel=revision["pixel"], line=revision["line"],
                              measurement_note=revision["measurement_note"])
    train, checks = [], []
    for side in SIDES:
        obs = sorted(
            (p for p in ticks if p["side"] == side), key=lambda p: p["known_value"]
        )
        if len(obs) < 3:
            raise ValueError(
                f"Only {len(obs)} continuous numbered margin strokes on {side}"
            )
        if min(sum(p["role"] == role for p in obs) for role in ("fit", "withheld")) < 2:
            # Some rulers number only ten-minute intervals. Alternating the
            # surviving measured strokes keeps both groups on this margin.
            for j, p in enumerate(obs):
                p["role"] = "fit" if j % 2 == 0 else "withheld"
        train.extend(p for p in obs if p["role"] == "fit")
        checks.extend(p for p in obs if p["role"] == "withheld")
    initial = affine_fit(train, approximate)

    def affine_errors(obs, model):
        rr, aa, vv = constraints(obs)
        return (hist.pixel_to_ll(pixels(obs), model)[rr, aa] - vv) * 3600

    ll = printed(nom)
    crosses = []
    for lon in np.arange(np.ceil(ll[:, 0].min() * 2) / 2, ll[:, 0].max(), 0.5):
        for lat in np.arange(np.ceil(ll[:, 1].min() * 2) / 2, ll[:, 1].max(), 0.5):
            if [float(lon), float(lat)] in spec.get("absent_crossings", []):
                continue
            p, px, py = hist.predict(
                hist.project([[lon, lat], [lon + 0.001, lat], [lon, lat + 0.001]]),
                initial,
            )
            if cv2.pointPolygonTest(corners.astype("float32"), tuple(p), True) < 230:
                continue
            slopes = [(py - p)[0] / (py - p)[1], (px - p)[1] / (px - p)[0]]
            observed = []
            for a, slope in enumerate(slopes):
                if spec.get("require_extended_graticule_strokes"):
                    img = gray if a == 0 else gray.T
                    # Stay in the map interior, including when a crossing is close
                    # to a ruled margin. Each arm contributes separately to recognition.
                    along = corners[:, 1 - a]
                    lo = max(round(p[1 - a]) - 1100, int(min(along)) + 90)
                    hi = min(round(p[1 - a]) + 1100, int(max(along)) - 90)
                    if hi - lo < 800:
                        break
                    result = extended_stroke(img, p[a] - .5, p[1 - a] - .5,
                                             np.arange(lo, hi, 2), slope)
                    if result is None:
                        break
                    observed.append(result[:2])
                    slopes[a] = result[2]
                    continue
                across = np.arange(round(p[1 - a]) - 200, round(p[1 - a]) + 200, 2)
                result = stroke(
                    gray if a == 0 else gray.T,
                    p[a] - 0.5,
                    p[1 - a] - 0.5,
                    across,
                    slope,
                    55,
                )
                if result is None:
                    break
                observed.append(result)
            if len(observed) != 2:
                continue
            (vx, ss), (hy, tt) = observed
            m, n = slopes
            x = (vx + m * (hy - (p[1] - 0.5)) - m * n * (p[0] - 0.5)) / (1 - m * n)
            y = hy + n * (x - (p[0] - 0.5))
            crosses.append(
                dict(
                    kind="crossing",
                    pixel=x + 0.5,
                    line=y + 0.5,
                    longitude=float(lon),
                    latitude=float(lat),
                    contrast=min(ss, tt),
                )
            )
    for revision in revisions:
        if revision["kind"] == "crossing":
            matches = [
                crossing for crossing in crosses
                if crossing["longitude"] == revision["longitude"]
                and crossing["latitude"] == revision["latitude"]
            ]
            if len(matches) != 1:
                raise ValueError("Reviewed interior crossing could not be identified")
            matches[0].update(pixel=revision["pixel"], line=revision["line"],
                              measurement_note=revision["measurement_note"])
    if "matched_native_crossings" in spec:
        # Correspondences have been measured in two scans of the same engraved
        # plate. Preserve the source plate's split when fitting the second copy.
        crosses = list(spec["matched_native_crossings"])
    # Fix the interior holdout by spatial order before the combined fit.
    ct = [z for i, z in enumerate(crosses) if i % 3 != 1]
    ch = [z for i, z in enumerate(crosses) if i % 3 == 1]
    if len(crosses) == 1:
        ct = []
        ch = crosses
    if "matched_native_crossings" in spec:
        ct = [z for z in crosses if z["role"] == "fit"]
        ch = [z for z in crosses if z["role"] == "withheld"]
    controls = train + ct
    checks += ch
    model = affine_fit(controls, initial)
    err = affine_errors(checks, model)
    ae = affine_errors(train, model)
    check = float(np.mean(err**2) ** 0.5)
    cfg = dict(
        id=sid,
        title="Indian Atlas "
        + item["sheet"]
        + " "
        + (q or "full sheet")
        + " · "
        + item["date_label"],
        sheet=item["sheet"],
        quarter=q,
        year=item["year"],
        source=item["source"],
        table=TABLE,
        frame_corners=spec["frame_corners"],
        crop_mode="measured_frame",
        crop_inset_pixels=0,
        crop_edge_guides=spec["crop_edge_guides"],
        ignore_exif_orientation=spec.get("ignore_exif_orientation", False),
        decode_stripes_from_numbered_ticks=True,
        margin_review=spec.get("margin_review", ""),
        excluded_margin_fractions=spec.get("excluded_margin_fractions", {}),
        excluded_margin_notes=spec.get("excluded_margin_notes", {}),
        native_observation_revisions=revisions,
        absent_crossings=spec.get("absent_crossings", []),
        require_extended_graticule_strokes=spec.get("require_extended_graticule_strokes", False),
        matched_native_crossings=spec.get("matched_native_crossings", []),
        source_identification_note="Edition and quarter from the collection catalogue. Cell located on the printed Atlas index.",
        longitude_convention_status="Project two-step longitude shift of −216.18 arcseconds.",
    )
    ref = dict(
        source=item["source"],
        source_size=spec["source_size"],
        source_sha256=sha(source),
        table=TABLE,
        points=ct,
        control_observations=controls,
        independent_edge_checks=checks,
        affine_plane_centre_fathoms=model[0].tolist(),
        affine_coefficients=model[1].tolist(),
        edge_rmse_arcseconds=check,
        independent_scalar_checks=len(err),
        withheld_errors_arcseconds=err.tolist(),
        interior_crossings=len(crosses),
        unusable_margin_strokes=skipped,
        margin_search_seed_minutes=spec.get("margin_seed_minutes", {}),
        corner_minus_walker_arcseconds=(
            (hist.pixel_to_ll(corners + 0.5, model) - printed(nom)) * 3600
        ).tolist(),
        training_tick_rms_arcseconds=float(np.mean(ae**2) ** 0.5),
    )
    return cfg, ref


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from atlas_scan_frame import detect

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queue", type=Path, required=True, help="Catalogue inventory JSON"
    )
    parser.add_argument("--sheet", required=True, help="Unique scan ID")
    parser.add_argument(
        "--frame", type=Path, help="Measured frame JSON. Omit to measure native bands."
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="Candidate directory for source review"
    )
    args = parser.parse_args()
    item = next(e for e in read(args.queue) if e["id"] == args.sheet)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.frame:
        spec = read(args.frame)
    else:
        gray = cv2.imread(str(ROOT / item["source"]), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError("Cannot open source scan")
        if gray.shape[0] > gray.shape[1]:
            raise ValueError("Portrait scan requires a reviewed orientation or frame")
        corners, guides, bands = detect(gray, bool(item["quarter"]))
        spec = dict(
            frame_corners=corners.tolist(),
            crop_edge_guides=guides,
            bands=bands,
            source_size=list(gray.shape[::-1]),
            ignore_exif_orientation=False,
        )
        write(args.out / "frame.json", spec)
    config, reference = acquire(item, spec)
    config.update(
        book_frame_normal_sides=list(SIDES), book_frame_normal_tolerance_3857_m=12.5
    )
    write(args.out / "config.json", config)
    write(args.out / "affine.json", reference)
