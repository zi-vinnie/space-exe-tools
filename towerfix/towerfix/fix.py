"""Turn tower arrival times into a 2D position fix (TDOA).

Each tower's delay from `timing.measure` is relative to the strongest
impulse response peak. Subtracting the reference tower's delay gives a time
difference of arrival (TDOA). Each tower also has a fixed network delay
compared with St Thomas (its "offset"), which comes from a calibration at a
known site. With offsets removed, each TDOA puts the receiver on one
hyperbola. Two TDOAs (three towers) give a fix. A third TDOA checks it.

Positions are solved in a local east/north frame in metres around St Thomas.
Ranges are worked out exactly in Earth-centred coordinates, so the flat
frame only sets the solver's step directions.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

C_M_PER_US = 299.792458        # metres per microsecond
REFERENCE_TII = "0E09"         # St Thomas; offsets are relative to it
RX_HEIGHT_M = 60.0             # receiver height above the ellipsoid, a guess
# Slow wander of each tower's delay from one 5 s chunk to the next, on top of
# the noise within a chunk. In the 10-minute desk recording the TDOAs moved
# by 12 to 18 ns (1 sd) between chunks, which is about 10 ns per tower. It
# is only measured at one indoor site, so treat it as a guess elsewhere. It
# does not cover multipath bias or a wrong offset, which can be far bigger.
WANDER_NS = 10.0

_A = 6378137.0                 # WGS84
_E2 = 6.69437999014e-3


def load_towers(path):
    data = json.loads(Path(path).read_text())
    return data["towers"]


def _ecef(lat, lon, h):
    lat, lon = np.radians(lat), np.radians(lon)
    n = _A / np.sqrt(1 - _E2 * np.sin(lat) ** 2)
    return np.stack([(n + h) * np.cos(lat) * np.cos(lon),
                     (n + h) * np.cos(lat) * np.sin(lon),
                     (n * (1 - _E2) + h) * np.sin(lat)], axis=-1)


class Frame:
    """Local east/north frame in metres. Maps (e, n) to lat/lon and back."""

    def __init__(self, lat0, lon0):
        self.lat0, self.lon0 = lat0, lon0
        s = math.sin(math.radians(lat0))
        # Radii of curvature at the origin (meridian and prime vertical).
        self.m = _A * (1 - _E2) / (1 - _E2 * s * s) ** 1.5
        self.nv = _A / math.sqrt(1 - _E2 * s * s)
        self.coslat = math.cos(math.radians(lat0))

    def to_ll(self, e, n):
        lat = self.lat0 + np.degrees(np.asarray(n) / self.m)
        lon = self.lon0 + np.degrees(np.asarray(e) / (self.nv * self.coslat))
        return lat, lon

    def to_en(self, lat, lon):
        n = np.radians(np.asarray(lat) - self.lat0) * self.m
        e = np.radians(np.asarray(lon) - self.lon0) * self.nv * self.coslat
        return e, n


class Solver:
    def __init__(self, towers, rx_height_m=RX_HEIGHT_M, wander_ns=WANDER_NS):
        self.towers = {t["tii"]: t for t in towers}
        ref = self.towers[REFERENCE_TII]
        self.frame = Frame(ref["lat"], ref["lon"])
        self.rx_h = rx_height_m
        self.wander_us = wander_ns / 1000.0
        self.xyz = {k: _ecef(t["lat"], t["lon"], t.get("site_height_m", 0.0))
                    for k, t in self.towers.items()}
        self.en = {k: self.frame.to_en(t["lat"], t["lon"]) for k, t in self.towers.items()}

    # Ranges -----------------------------------------------------------------

    def _rx_xyz(self, e, n):
        lat, lon = self.frame.to_ll(e, n)
        return _ecef(lat, lon, self.rx_h)

    def _dd(self, e, n, tii, ref):
        """Range to `tii` minus range to `ref`, in metres, at (e, n)."""
        p = self._rx_xyz(e, n)
        return (np.linalg.norm(p - self.xyz[tii], axis=-1)
                - np.linalg.norm(p - self.xyz[ref], axis=-1))

    def geometric_us(self, lat, lon, tii, ref=REFERENCE_TII):
        e, n = self.frame.to_en(lat, lon)
        return float(self._dd(e, n, tii, ref)) / C_M_PER_US

    # Measurements -----------------------------------------------------------

    def observations(self, measurement, offsets, excluded=()):
        """Pick the towers to use from one `timing.measure` result.

        A tower is used if it is in towers.json, has an offset, matched an
        impulse response peak, and isn't excluded. If two towers matched the
        same peak, only the one with the stronger TII is kept. Returns
        (reference, rows) where rows describe every tower in towers.json.
        """
        scores = {r["comb_hex"]: r["score_db"] for r in measurement["towers"]}
        delays = {d["comb_hex"]: d for d in measurement["tower_delays"]}
        claimed = {}
        for d in sorted(measurement["tower_delays"],
                        key=lambda d: -scores.get(d["comb_hex"], 0)):
            pk = d["matched_peak_us"]
            if pk is not None and pk not in claimed:
                claimed[pk] = d["comb_hex"]

        rows = []
        for tii, t in self.towers.items():
            comb = tii[2:]
            d = delays.get(comb)
            row = {"tii": tii, "name": t["name"], "score_db": scores.get(comb),
                   "heard": d is not None, "delay_us": d["delay_us"] if d else None,
                   "delay_sd_us": d.get("delay_sd_us") if d else None,
                   "matched_peak_us": d["matched_peak_us"] if d else None,
                   "offset_us": offsets.get(tii), "excluded": tii in excluded,
                   "used": False, "why": None}
            if d is None:
                row["why"] = "TII not heard"
            elif d["matched_peak_us"] is None:
                row["why"] = "no impulse response peak matched"
            elif claimed.get(d["matched_peak_us"]) != comb:
                row["why"] = "peak taken by a stronger tower"
            elif tii not in offsets:
                row["why"] = "no offset; calibrate first"
            elif tii in excluded:
                row["why"] = "excluded"
            else:
                row["used"] = True
            rows.append(row)

        usable = [r for r in rows if r["used"]]
        ref = next((r for r in usable if r["tii"] == REFERENCE_TII), None)
        if ref is None and usable:
            ref = max(usable, key=lambda r: r["score_db"] or 0)
        for r in rows:
            r["is_reference"] = ref is not None and r["tii"] == ref["tii"]
        return ref, rows

    def _sigma_us(self, r):
        sd = r["delay_sd_us"] or 0.0
        return math.hypot(sd, self.wander_us)

    # Solving ------------------------------------------------------------------

    def solve(self, measurement, offsets, excluded=(), prior=None):
        """Least-squares fix. Never uses a true position.

        With three towers the two hyperbolas often cross twice, and both
        crossings fit exactly. Then the fix is the crossing nearest `prior`
        (lat, lon), which should be the last fix that wasn't ambiguous, or
        else the last fix of any kind. With no prior it is the crossing
        nearest the tower with the strongest TII, which is a guess that
        you're closest to the loudest tower.
        The result says "ambiguous" and lists the other crossing.
        """
        ref, rows = self.observations(measurement, offsets, excluded)
        result = {"towers": rows, "reference": ref["tii"] if ref else None, "fix": None,
                  "hyperbolas": [], "alternates": [], "ambiguous": False, "chosen_by": None}
        if ref is None:
            result["why"] = "no usable towers"
            return result
        others = [r for r in rows if r["used"] and not r["is_reference"]]
        # Measured TDOA with network offsets removed, in metres of range.
        target = np.array([((r["delay_us"] - r["offset_us"]) - (ref["delay_us"] - ref["offset_us"]))
                           * C_M_PER_US for r in others])
        for r, t in zip(others, target):
            r["tdoa_us"] = round(float(r["delay_us"] - ref["delay_us"]), 4)
            result["hyperbolas"].append({"tii": r["tii"], "ref": ref["tii"], "excluded": False,
                                         "points": self.hyperbola(r["tii"], ref["tii"], t)})
        # Excluded towers still get a hyperbola, so you can see if they agree.
        for r in rows:
            if r["why"] == "excluded" and not r["is_reference"]:
                t = ((r["delay_us"] - r["offset_us"]) - (ref["delay_us"] - ref["offset_us"])) * C_M_PER_US
                r["tdoa_us"] = round(float(r["delay_us"] - ref["delay_us"]), 4)
                result["hyperbolas"].append({"tii": r["tii"], "ref": ref["tii"], "excluded": True,
                                             "points": self.hyperbola(r["tii"], ref["tii"], t)})
        if len(others) < 2:
            result["why"] = "need 3 towers for a fix"
            return result

        sig = np.array([self._sigma_us(r) for r in others]) * C_M_PER_US
        sig_ref = self._sigma_us(ref) * C_M_PER_US
        cov = np.diag(sig ** 2) + sig_ref ** 2       # every TDOA shares the reference
        w = np.linalg.inv(cov)
        tiis = [r["tii"] for r in others]

        def resid(e, n):
            return np.stack([self._dd(e, n, k, ref["tii"]) for k in tiis], axis=-1) - target

        def chi2(e, n):
            r = resid(e, n)
            return np.einsum("...i,ij,...j->...", r, w, r)

        # Coarse grid over the area round the towers, then Gauss-Newton from
        # each local minimum. With 3 towers two hyperbolas can cross twice.
        es = [v[0] for v in self.en.values()]
        nsv = [v[1] for v in self.en.values()]
        ge = np.arange(min(es) - 20e3, max(es) + 20e3, 1000.0)
        gn = np.arange(min(nsv) - 20e3, max(nsv) + 20e3, 1000.0)
        E, N = np.meshgrid(ge, gn)
        c = chi2(E, N)
        starts = []
        for i in range(1, c.shape[0] - 1):
            for j in range(1, c.shape[1] - 1):
                if c[i, j] <= c[i - 1:i + 2, j - 1:j + 2].min():
                    starts.append((c[i, j], E[i, j], N[i, j]))
        starts = sorted(starts)[:6]

        sols = []
        for _, e, n in starts:
            p = np.array([e, n])
            for _ in range(20):
                r0 = resid(p[0], p[1])
                jac = np.stack([(resid(p[0] + 1, p[1]) - r0), (resid(p[0], p[1] + 1) - r0)], axis=1)
                a = jac.T @ w @ jac
                step = np.linalg.solve(a, -jac.T @ w @ r0)
                p = p + step
                if np.hypot(*step) < 0.01:
                    break
            r0 = resid(p[0], p[1])
            jac = np.stack([(resid(p[0] + 1, p[1]) - r0), (resid(p[0], p[1] + 1) - r0)], axis=1)
            pcov = np.linalg.inv(jac.T @ w @ jac)
            sols.append((float(r0 @ w @ r0), p, r0, pcov))
        uniq = []
        for s in sorted(sols, key=lambda s: s[0]):
            if all(np.hypot(*(s[1] - u[1])) > 50 for u in uniq):
                uniq.append(s)

        dof = len(others) - 2
        # Crossings that fit nearly as well as the best one (chi-squared
        # within 9, about 3 sd) count as real alternatives.
        good = [s for s in uniq if s[0] < uniq[0][0] + 9]
        result["ambiguous"] = len(good) > 1
        if result["ambiguous"]:
            if prior is not None:
                pe, pn = self.frame.to_en(*prior)
                result["chosen_by"] = "nearest an earlier fix"
            else:
                loud = max((r for r in rows if r["used"]), key=lambda r: r["score_db"] or 0)
                pe, pn = self.en[loud["tii"]]
                result["chosen_by"] = f"nearest the strongest tower ({loud['name']})"
            good.sort(key=lambda s: np.hypot(s[1][0] - pe, s[1][1] - pn))
        best = good[0]
        result["fix"] = self._describe(best, dof)
        for r, res in zip(others, best[2]):
            r["residual_ns"] = round(float(res / C_M_PER_US * 1000), 1)
        for s in good[1:]:
            result["alternates"].append(self._describe(s, dof))
        return result

    def _describe(self, sol, dof):
        chi, p, _, pcov = sol
        lat, lon = self.frame.to_ll(p[0], p[1])
        vals, vecs = np.linalg.eigh(pcov)
        vals = np.clip(vals, 0, None)
        # 95% ellipse for 2 dimensions: sqrt(chi-squared 2 dof, 0.95) = 2.448.
        k = 2.448
        t = np.linspace(0, 2 * np.pi, 73)
        circle = np.stack([np.cos(t), np.sin(t)])
        pts = (vecs @ (np.sqrt(vals)[:, None] * circle)) * k + p[:, None]
        elat, elon = self.frame.to_ll(pts[0], pts[1])
        return {
            "lat": float(lat), "lon": float(lon),
            "chi2": round(chi, 2), "dof": dof,
            "sd_major_m": round(float(np.sqrt(vals[1])), 1),
            "sd_minor_m": round(float(np.sqrt(vals[0])), 1),
            "drms_m": round(float(np.sqrt(vals.sum())), 1),
            "ellipse95": [[round(float(a), 6), round(float(b), 6)] for a, b in zip(elat, elon)],
        }

    def hyperbola(self, tii, ref, target_m, reach_m=70e3, n=160):
        """Points (lat, lon) where range to tii minus range to ref is target_m."""
        f1 = np.array(self.en[ref])
        f2 = np.array(self.en[tii])
        mid = (f1 + f2) / 2
        af = np.linalg.norm(f2 - f1) / 2
        u = (f2 - f1) / (2 * af)
        v = np.array([-u[1], u[0]])
        a = abs(target_m) / 2
        if a >= af * 0.999:
            return []
        b = math.sqrt(af ** 2 - a ** 2)
        tmax = math.asinh(reach_m / max(b, 1.0))
        t = np.linspace(-tmax, tmax, n)
        # Positive target: farther from tii, so the branch on ref's side.
        x = -np.sign(target_m) * a * np.cosh(t) if target_m != 0 else np.zeros_like(t)
        pts = mid[:, None] + np.outer(u, x) + np.outer(v, b * np.sinh(t))
        e, nn = pts
        # Newton steps onto the exact curve (the flat formula is a start).
        for _ in range(3):
            f = self._dd(e, nn, tii, ref) - target_m
            ge = self._dd(e + 1, nn, tii, ref) - target_m - f
            gn = self._dd(e, nn + 1, tii, ref) - target_m - f
            g2 = ge ** 2 + gn ** 2
            e, nn = e - f * ge / g2, nn - f * gn / g2
        lat, lon = self.frame.to_ll(e, nn)
        return [[round(float(p), 6), round(float(q), 6)] for p, q in zip(lat, lon)]

    # Calibration --------------------------------------------------------------

    def calibrate(self, measurements, lat, lon):
        """Offsets of every tower against St Thomas, given the true position.

        Averages over all `measurements` (timing.measure results) in which
        both the tower and St Thomas matched a peak. Only calibration uses a
        true position.
        """
        per = {}
        for m in measurements:
            ref, rows = self.observations(m, {k: 0.0 for k in self.towers})
            got = {r["tii"]: r for r in rows if r["used"]}
            if REFERENCE_TII not in got:
                continue
            for tii, r in got.items():
                if tii == REFERENCE_TII:
                    continue
                per.setdefault(tii, []).append(r["delay_us"] - got[REFERENCE_TII]["delay_us"])
        out = {}
        for tii, vals in per.items():
            geo = self.geometric_us(lat, lon, tii)
            out[tii] = {"offset_us": round(float(np.mean(vals) - geo), 4),
                        "measured_us": round(float(np.mean(vals)), 4),
                        "geometric_us": round(geo, 4),
                        "spread_us": round(float(np.std(vals)), 4),
                        "chunks": len(vals)}
        return out


def load_offsets(path):
    """{tii: offset_us}, with St Thomas at 0. Empty if there's no file."""
    p = Path(path)
    if not p.exists():
        return {REFERENCE_TII: 0.0}
    data = json.loads(p.read_text())
    offs = {k: v["offset_us"] for k, v in data["towers"].items()}
    offs[REFERENCE_TII] = 0.0
    return offs


def save_offsets(path, cal, lat, lon, site, source):
    data = {
        "_about": "Fixed network delay of each tower compared with St Thomas (0E09), "
                  "in microseconds: measured TDOA minus geometric TDOA at a known site.",
        "reference": REFERENCE_TII,
        "site": site, "lat": lat, "lon": lon, "source": source,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "towers": cal,
    }
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def distance_m(lat1, lon1, lat2, lon2):
    p1 = _ecef(lat1, lon1, 0.0)
    p2 = _ecef(lat2, lon2, 0.0)
    return float(np.linalg.norm(p1 - p2))
