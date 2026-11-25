# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "matplotlib"]
# ///
"""Analyse a raw recording of BBC National DAB (block 12B) for the ground test.

Usage:  uv run analyse.py ../recordings/<file>.cu8

The input is what `rtl_sdr -s 2048000` writes: unsigned 8-bit I/Q pairs at
2.048 MS/s. The script reports two things.

1. Which towers it can hear. In the null symbol at the start of each frame,
   every tower sends its TII code on its own set of carriers. The script
   measures the power on each tower's carriers.
2. When each signal arrives. The phase reference symbol after the null is the
   same in every frame, so correlating against it gives the channel impulse
   response. Each tower, and each strong reflection, shows up as a peak. The
   script tracks the gap between every peak and the strongest one across the
   recording.
3. Which peak is which tower. Each tower's TII carriers carry that tower's
   own delay in their phases, so they give a delay profile for one tower.
   The profile repeats every 20.83 us (the 48-carrier spacing), so the
   script matches it against the impulse response peaks, and uses the phase
   step inside each carrier pair as a rough delay to pick the repeat.

DAB transmission mode I numbers come from ETSI EN 300 401.

Results go to results/<recording name>/: summary.json and three PNG plots.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# The timing code lives in towerfix/towerfix/timing.py, shared with the web tool.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from towerfix.timing import (  # noqa: E402
    FS, T_FRAME, PRE, UP, load, process_frames, tii_report, peak_report,
    track_peaks, tower_delays,
)


def analyse(path, out_dir):
    raw, _ = load(path)
    fd = process_frames(raw)
    cir = fd["cir"]
    eps = fd["eps"]
    towers = tii_report(fd["tii_power"], fd["ks"])
    peaks = peak_report(cir)
    track_peaks(cir, peaks)
    delays = tower_delays(fd["null_spec"], fd["rolls"], towers, peaks, fd["ks"], fd["z"])

    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "recording": str(path.name),
        "frames": fd["n_frames"],
        "seconds": round(fd["n_frames"] * T_FRAME / FS, 2),
        "frequency_offset_hz": round(eps * FS, 1),
        "frequency_offset_ppm": round(eps * FS / 225.648e6 * 1e6, 3),
        "timing_jumps": fd["jumps"],
        "towers": towers,
        "peaks": peaks,
        "tower_delays": delays,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    plot(cir, peaks, towers, delays, out_dir, path.name)
    return summary


def plot(cir, peaks, towers, delays, out_dir, name):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, muted, line = "#1f2328", "#6e7781", "#2f6fdf"
    plt.rcParams.update({
        "font.size": 10, "axes.edgecolor": muted, "axes.labelcolor": ink,
        "xtick.color": muted, "ytick.color": muted, "axes.spines.top": False,
        "axes.spines.right": False, "axes.grid": True, "grid.color": "#d8dee4",
        "grid.linewidth": 0.6,
    })

    # 1. Average impulse response.
    avg = cir.mean(axis=0)
    db = 10 * np.log10(avg / avg[PRE * UP])
    delay_us = (np.arange(len(avg)) / UP - PRE) / FS * 1e6
    keep = (delay_us > -20) & (delay_us < 160)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(delay_us[keep], db[keep], color=line, linewidth=1.2)
    for pk in peaks:
        if pk.get("tower") or (pk["rel_db"] > -37 and pk["delay_us"] > 20):
            label = f'{pk["delay_us"]:.1f} µs'
            if pk.get("tower"):
                label = f'{pk["tower"]}\n' + label
            ax.annotate(label,
                        (pk["delay_us"], pk["rel_db"]), textcoords="offset points",
                        xytext=(0, 6), ha="center", fontsize=8, color=ink)
    ax.set_ylim(-45, 5)
    ax.set_xlabel("Delay after the strongest signal (µs). 1 µs is 300 m of extra path.")
    ax.set_ylabel("Power relative to strongest (dB)")
    ax.set_title(f"Signal arrivals, averaged over {len(cir)} frames: {name}",
                 loc="left", color=ink)
    fig.tight_layout()
    fig.savefig(out_dir / "arrivals.png", dpi=130)
    plt.close(fig)

    # 2. TII score per comb.
    fig, ax = plt.subplots(figsize=(10, 3.6))
    combs = [r["comb"] for r in towers]
    scores = [r["score_db"] for r in towers]
    ax.bar(combs, scores, color=line, width=0.7)
    for r in towers:
        if r["tower"]:
            ax.annotate(r["tower"], (r["comb"], r["score_db"]), textcoords="offset points",
                        xytext=(0, 4), ha="center", fontsize=8, color=ink, rotation=90,
                        va="bottom")
    ax.set_xticks(combs, [f"{c:02X}" for c in combs], fontsize=8)
    ax.set_xlabel("TII sub ID (comb), hex")
    ax.set_ylabel("Lit minus dark blocks (dB)")
    ax.set_title("Tower identity codes heard in the null symbol", loc="left", color=ink)
    ax.margins(y=0.35)
    fig.tight_layout()
    fig.savefig(out_dir / "towers.png", dpi=130)
    plt.close(fig)

    # 3. Delay of each secondary peak over time, as change from its mean.
    tracked = [p for p in peaks if p["index"] != PRE * UP and p["rel_db"] > -37]
    if tracked:
        t = np.arange(len(cir)) * T_FRAME / FS
        fig, axes = plt.subplots(len(tracked), 1, figsize=(10, 1.8 * len(tracked)),
                                 sharex=True, squeeze=False)
        for ax, pk in zip(axes[:, 0], tracked):
            d = np.array(pk["track_ns"])
            ax.plot(t, d - d.mean(), color=line, linewidth=1)
            ax.set_ylabel("ns")
            ax.set_title(f'Peak at {pk["delay_us"]:.1f} µs ({pk["rel_db"]} dB): '
                         f'spread {pk["std_ns"]} ns', loc="left", fontsize=9, color=ink)
        axes[-1, 0].set_xlabel("Time into recording (s)")
        fig.tight_layout()
        fig.savefig(out_dir / "timing.png", dpi=130)
        plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("recording", type=Path)
    args = ap.parse_args()
    out = Path(__file__).resolve().parent / "results" / args.recording.stem
    s = analyse(args.recording, out)

    print(f'{s["recording"]}: {s["frames"]} frames, {s["seconds"]} s, '
          f'frequency offset {s["frequency_offset_hz"]} Hz ({s["frequency_offset_ppm"]} ppm), '
          f'{len(s["timing_jumps"])} timing jumps (dropped samples?)')
    print("\nTowers (TII sub ID, lit minus dark blocks):")
    for r in sorted(s["towers"], key=lambda r: -r["score_db"])[:8]:
        print(f'  {r["comb_hex"]}  {r["score_db"]:5.1f} dB  blocks {r["lit_blocks"]}  '
              f'{r["tower"] or ""}')
    print("\nArrival peaks (relative to the strongest):")
    for p in s["peaks"]:
        print(f'  {p["delay_us"]:8.2f} µs  {p["path_km"]:7.2f} km  {p["rel_db"]:6.1f} dB  '
              f'spread {p.get("std_ns", 0):6.1f} ns  drift {p.get("drift_ns_per_min", 0):6.1f} ns/min')
    print("\nTower arrival times from TII phases:")
    for d in s["tower_delays"]:
        m = f'peak at {d["matched_peak_us"]} µs' if d["matched_peak_us"] is not None else "no peak"
        print(f'  {d["comb_hex"]}  {d["delay_us"]:8.2f} µs (rough {d["rough_delay_us"]:6.1f})  '
              f'profile {d["profile_peak_db"]:4.1f} dB  pairs "{d["pair_rule"]}"  {m}  '
              f'{d["tower"] or ""}')
    print(f"\nResults in {out}")


if __name__ == "__main__":
    main()
