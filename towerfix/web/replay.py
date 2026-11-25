"""Replay a recording without the browser: one fix per chunk, then a summary.

Usage (from towerfix/web):
  uv run replay.py ../recordings/FILE.cu8 [--seconds 5] [--true LAT LON]
  uv run replay.py ../recordings/FILE.cu8 --calibrate LAT LON --site "name"

--true is only used to score the fixes. --calibrate writes offsets.json
from the whole recording at a known position instead of fixing.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from towerfix.fix import (  # noqa: E402
    Solver, distance_m, load_offsets, load_towers, save_offsets,
)
from towerfix.stream import FileChunks  # noqa: E402
from towerfix.timing import measure  # noqa: E402

TOWERS_JSON = HERE.parent / "towers.json"
OFFSETS_JSON = HERE / "offsets.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("recording", type=Path)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--true", nargs=2, type=float, metavar=("LAT", "LON"))
    ap.add_argument("--calibrate", nargs=2, type=float, metavar=("LAT", "LON"))
    ap.add_argument("--site", default="")
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--offsets", type=Path, default=OFFSETS_JSON)
    ap.add_argument("--json", type=Path, help="write every fix to this file")
    args = ap.parse_args()

    solver = Solver(load_towers(TOWERS_JSON))
    chunks = FileChunks(args.recording, args.seconds)
    print(f"{args.recording.name}: {chunks.count} chunks of {chunks.frames} frames")

    if args.calibrate:
        ms = [measure(chunks.read(i)) for i in range(chunks.count)]
        lat, lon = args.calibrate
        cal = solver.calibrate(ms, lat, lon)
        save_offsets(args.offsets, cal, lat, lon, args.site, args.recording.name)
        for tii, c in cal.items():
            print(f"  {tii} {solver.towers[tii]['name']:20s} offset {c['offset_us']:9.4f} us  "
                  f"(measured {c['measured_us']:.4f}, geometric {c['geometric_us']:.4f}, "
                  f"spread {c['spread_us'] * 1000:.0f} ns, {c['chunks']} chunks)")
        print(f"Wrote {args.offsets}")
        return

    offsets = load_offsets(args.offsets)
    fixes = []
    prior = last_fix = None     # last unambiguous fix, last fix of any kind
    for i in range(chunks.count):
        res = solver.solve(measure(chunks.read(i)), offsets, set(args.exclude), prior or last_fix)
        f = res["fix"]
        if f is not None:
            last_fix = (f["lat"], f["lon"])
            if not res["ambiguous"]:
                prior = last_fix
        used = [r["tii"] for r in res["towers"] if r["used"]]
        if f is None:
            print(f"  {i:4d}  no fix ({res.get('why')}), towers {used}")
            continue
        err = distance_m(f["lat"], f["lon"], *args.true) if args.true else None
        e, n = solver.frame.to_en(f["lat"], f["lon"])
        fixes.append({"chunk": i, "lat": f["lat"], "lon": f["lon"], "e": float(e), "n": float(n),
                      "drms_m": f["drms_m"], "chi2": f["chi2"], "dof": f["dof"],
                      "error_m": err, "towers": used, "ambiguous": res["ambiguous"]})
        print(f"  {i:4d}  {f['lat']:.6f} {f['lon']:.6f}  1sd {f['sd_major_m']:5.1f} x "
              f"{f['sd_minor_m']:5.1f} m  chi2 {f['chi2']:5.2f}/{f['dof']}  "
              + (f"error {err:6.1f} m  " if err is not None else "")
              + f"{len(used)} towers" + (f"  ambiguous, chose {res['chosen_by']}"
                                          if res["ambiguous"] else ""))
    if not fixes:
        return
    e = np.array([x["e"] for x in fixes])
    n = np.array([x["n"] for x in fixes])
    me, mn = e.mean(), n.mean()
    lat, lon = solver.frame.to_ll(me, mn)
    scatter = float(np.sqrt(np.mean((e - me) ** 2 + (n - mn) ** 2)))
    print(f"\n{len(fixes)} fixes of {chunks.count} chunks. Mean {float(lat):.6f} {float(lon):.6f}")
    print(f"Scatter about the mean: {scatter:.1f} m RMS (east sd {e.std():.1f} m, "
          f"north sd {n.std():.1f} m). Predicted 1-sd size (drms), median: "
          f"{np.median([x['drms_m'] for x in fixes]):.1f} m")
    if args.true:
        errs = np.array([x["error_m"] for x in fixes])
        print(f"Error of the mean fix: {distance_m(float(lat), float(lon), *args.true):.1f} m. "
              f"Per-chunk error: median {np.median(errs):.1f} m, 95th percentile "
              f"{np.percentile(errs, 95):.1f} m, max {errs.max():.1f} m")
    if args.json:
        args.json.write_text(json.dumps(fixes, indent=1))


if __name__ == "__main__":
    main()
