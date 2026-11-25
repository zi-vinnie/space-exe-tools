"""Find when each BBC DAB tower's signal arrives, from raw RTL-SDR samples.

The input is what `rtl_sdr -s 2048000` writes: unsigned 8-bit I/Q pairs at
2.048 MS/s, as a numpy uint8 array (a memmap of a whole file, or one chunk
read from a file or a live dongle).

1. Which towers it can hear. In the null symbol at the start of each frame,
   every tower sends its TII code on its own set of carriers. `tii_report`
   measures the power on each tower's carriers.
2. When each signal arrives. The phase reference symbol after the null is the
   same in every frame, so correlating against it gives the channel impulse
   response. Each tower, and each strong reflection, shows up as a peak.
3. Which peak is which tower. Each tower's TII carriers carry that tower's
   own delay in their phases, so they give a delay profile for one tower.
   The profile repeats every 20.83 us (the 48-carrier spacing), so
   `tower_delays` matches it against the impulse response peaks, and uses
   the phase step inside each carrier pair as a rough delay to pick the
   repeat.

All delays are relative to the strongest impulse response peak.

DAB transmission mode I numbers come from ETSI EN 300 401.
"""

import numpy as np

FS = 2_048_000          # samples per second
T_FRAME = 196_608       # 96 ms
T_NULL = 2_656
T_U = 2_048             # useful part of an OFDM symbol, and the FFT size
T_G = 504               # guard interval
T_S = T_U + T_G
N_SYMBOLS = 76
K_HALF = 768            # active carriers are -768..768, without 0
C_LIGHT = 299_792_458.0
UP = 8                  # zero-padding factor for the impulse response
PRE = 200               # samples of impulse response kept before the main peak

# Phase reference symbol, mode I (EN 300 401, tables 43 and 44).
H = [
    [0, 2, 0, 0, 0, 0, 1, 1, 2, 0, 0, 0, 2, 2, 1, 1, 0, 2, 0, 0, 0, 0, 1, 1, 2, 0, 0, 0, 2, 2, 1, 1],
    [0, 3, 2, 3, 0, 1, 3, 0, 2, 1, 2, 3, 2, 3, 3, 0, 0, 3, 2, 3, 0, 1, 3, 0, 2, 1, 2, 3, 2, 3, 3, 0],
    [0, 0, 0, 2, 0, 2, 1, 3, 2, 2, 0, 2, 2, 0, 1, 3, 0, 0, 0, 2, 0, 2, 1, 3, 2, 2, 0, 2, 2, 0, 1, 3],
    [0, 1, 2, 1, 0, 3, 3, 2, 2, 3, 2, 1, 2, 1, 3, 2, 0, 1, 2, 1, 0, 3, 3, 2, 2, 3, 2, 1, 2, 1, 3, 2],
]
# (first carrier of the 32-carrier group, row i of H, n)
PRS_GROUPS = [
    (-768, 0, 1), (-736, 1, 2), (-704, 2, 0), (-672, 3, 1), (-640, 0, 3), (-608, 1, 2),
    (-576, 2, 2), (-544, 3, 3), (-512, 0, 2), (-480, 1, 1), (-448, 2, 2), (-416, 3, 3),
    (-384, 0, 1), (-352, 1, 2), (-320, 2, 3), (-288, 3, 3), (-256, 0, 2), (-224, 1, 2),
    (-192, 2, 2), (-160, 3, 1), (-128, 0, 1), (-96, 1, 3), (-64, 2, 1), (-32, 3, 2),
    (1, 0, 3), (33, 3, 1), (65, 2, 1), (97, 1, 1), (129, 0, 2), (161, 3, 2),
    (193, 2, 1), (225, 1, 0), (257, 0, 2), (289, 3, 2), (321, 2, 3), (353, 1, 3),
    (385, 0, 0), (417, 3, 2), (449, 2, 1), (481, 1, 3), (513, 0, 3), (545, 3, 3),
    (577, 2, 3), (609, 1, 0), (641, 0, 3), (673, 3, 0), (705, 2, 1), (737, 1, 1),
]

# TII sub IDs for BBC National DAB sites in main ID 0x0E (Devon and nearby).
# Source: BDXC "Ensemble_List" (bdxc.org.uk/ukdab.pdf), which writes codes in
# decimal, e.g. 1412 is main 14 (0x0E), sub 12 (0x0C). Powers are kW.
TOWERS = {
    0x01: "Sidmouth",             # 0.1 kW
    0x02: "Okehampton",           # 0.6 kW
    0x05: "Bampton",              # 0.6 kW
    0x06: "Lyme Regis",           # 0.4 kW
    0x07: "Beacon Hill North",    # 5 kW, Torbay
    0x08: "Huntshaw Cross",       # 2.5 kW, North Devon
    0x09: "St Thomas",            # 4 kW, Exeter
    0x0A: "Brixham",              # 0.3 kW
    0x0B: "Stockland Hill",       # 5 kW
    0x0C: "Holcombe Down",        # 0.5 kW, near Teignmouth
    0x0D: "Bridport",             # 0.2 kW; BDXC says it has been heard as 0410
    0x0E: "Tiverton",             # 0.2 kW
    0x10: "Kingswear",            # 0.4 kW
    0x11: "Beer",                 # 0.05 kW
    0x13: "Budleigh Salterton",   # 0.6 kW
    0x17: "Ashburton",            # 0.3 kW
}
TII_QUARTERS = (-768, -384, 1, 385)
TII_ALIAS = T_U / 48     # samples; the TII delay profile repeats at this spacing
NULL_WIN = 304           # FFT window for the null starts this far into it
# The TII signal is timed like a normal OFDM symbol whose useful part is the
# last T_U samples of the null. Found from the data on 2026-11-25: with this,
# St Thomas lands on the strongest impulse response peak.
TII_REF = T_NULL - T_U


def prs_reference():
    """Phase reference symbol as complex carrier values, indexed by FFT bin."""
    z = np.zeros(T_U, dtype=np.complex128)
    for k0, i, n in PRS_GROUPS:
        for k in range(k0, k0 + 32):
            z[k % T_U] = np.exp(1j * np.pi / 2 * (H[i][k - k0] + n))
    return z


def active_carriers():
    return np.array([k for k in range(-K_HALF, K_HALF + 1) if k != 0])


def load(path):
    """A whole .cu8 file as a read-only memmap, and its length in samples."""
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    return raw, len(raw) // 2


def chunk(raw, start, length, eps):
    """Samples [start, start+length) as complex, with frequency offset removed."""
    b = np.asarray(raw[2 * start: 2 * (start + length)], dtype=np.float32) - 127.4
    x = b[0::2] + 1j * b[1::2]
    n = np.arange(start, start + length)
    return x * np.exp(-2j * np.pi * eps * n)


def moving_power(x, w):
    c = np.concatenate([[0.0], np.cumsum(np.abs(x) ** 2)])
    return (c[w:] - c[:-w]) / w


def first_null(raw):
    x = chunk(raw, 0, 2 * T_FRAME, 0.0)
    return int(np.argmin(moving_power(x, T_NULL)[:T_FRAME]))


def frequency_offset(raw, ns, n_frames):
    """Fine frequency offset in cycles per sample, from the guard intervals."""
    acc = 0j
    for f in range(n_frames):
        start = ns + f * T_FRAME + T_NULL
        x = chunk(raw, start, N_SYMBOLS * T_S, 0.0)
        for m in range(N_SYMBOLS):
            s = m * T_S + 50  # skip the start of the guard, where echoes land
            g = T_G - 100
            acc += np.sum(x[s:s + g] * np.conj(x[s + T_U:s + T_U + g]))
    return -np.angle(acc) / (2 * np.pi * T_U)


def parabolic(y, i):
    """Sub-bin peak position around integer index i."""
    a, b, c = y[i - 1], y[i], y[i + 1]
    d = a - 2 * b + c
    return i + (0.5 * (a - c) / d if d != 0 else 0.0)


def process_frames(raw):
    """Run through every whole frame in `raw`.

    Returns a dict with the impulse response of each frame (strongest peak
    rolled to PRE*UP), the null symbol carriers of each frame, the average
    null power per FFT bin, the frequency offset and any timing jumps.
    Needs at least three frames of samples.
    """
    n_samples = len(raw) // 2
    n_frames = (n_samples - 2 * T_FRAME) // T_FRAME
    if n_frames < 1:
        raise ValueError("need at least 3 frames (0.3 s) of samples")
    ns = first_null(raw)
    eps = frequency_offset(raw, ns, min(20, n_frames))

    z = prs_reference()
    ks = active_carriers()
    bins = ks % T_U
    taper = 0.5 + 0.5 * np.cos(np.pi * ks / (K_HALF + 1))   # Hann across the band
    big = T_U * UP
    big_bins = ks % big

    cir = np.zeros((n_frames, big), dtype=np.float32)
    main_pos = np.zeros(n_frames)
    tii_power = np.zeros(T_U)
    null_spec = np.zeros((n_frames, len(ks)), dtype=np.complex64)
    rolls = np.zeros(n_frames, dtype=int)
    # Puts the null carriers on the same delay grid as the impulse response.
    null_fix = np.exp(-2j * np.pi * ks * (PRE - (TII_REF - NULL_WIN)) / T_U)
    jumps = []   # frames where tracking moved by more than 2 samples

    for f in range(n_frames):
        # Impulse response from the phase reference symbol.
        w0 = ns + T_NULL + T_G - PRE
        y = np.fft.fft(chunk(raw, w0, T_U, eps))
        hf = np.zeros(big, dtype=np.complex128)
        hf[big_bins] = y[bins] * np.conj(z[bins]) * taper
        h = np.abs(np.fft.ifft(hf)) ** 2
        p = int(np.argmax(h))
        rolls[f] = PRE * UP - p
        cir[f] = np.roll(h, rolls[f])              # strongest peak at PRE
        main_pos[f] = parabolic(h, p) / UP if 0 < p < big - 1 else p / UP

        # The null symbol, windowed from the same frame start as the PRS so
        # that its delays line up with the impulse response.
        yn = np.fft.fft(chunk(raw, ns + NULL_WIN, T_U, eps))
        tii_power += np.abs(yn) ** 2
        null_spec[f] = yn[bins] * null_fix

        shift = int(np.clip(round(main_pos[f] - PRE), -50, 50)) if p < big // 2 else 0
        if abs(shift) > 2 and f > 0:
            jumps.append((f, shift))
        ns = ns + T_FRAME + shift
        if ns + 2 * T_FRAME > n_samples:
            cir, main_pos = cir[:f + 1], main_pos[:f + 1]
            null_spec, rolls = null_spec[:f + 1], rolls[:f + 1]
            n_frames = f + 1
            break

    return {
        "n_frames": n_frames,
        "eps": eps,
        "cir": cir,
        "main_pos": main_pos,
        "null_spec": null_spec,
        "rolls": rolls,
        "tii_power": tii_power / n_frames,
        "jumps": jumps,
        "ks": ks,
        "z": z,
    }


def measure(raw, min_score_db=3.0, n_sub=8):
    """TII scores, impulse response peaks and tower arrival times for `raw`.

    This is what the web tool runs on each chunk. It skips the per-frame
    peak tracking that analyse.py does. `n_sub` splits the frames into that
    many blocks to estimate the noise on each tower's delay.
    """
    fd = process_frames(raw)
    towers = tii_report(fd["tii_power"], fd["ks"])
    peaks = peak_report(fd["cir"])
    delays = tower_delays(fd["null_spec"], fd["rolls"], towers, peaks, fd["ks"], fd["z"],
                          min_score_db=min_score_db, n_sub=n_sub)
    return {
        "frames": fd["n_frames"],
        "seconds": round(fd["n_frames"] * T_FRAME / FS, 2),
        "frequency_offset_hz": round(fd["eps"] * FS, 1),
        "timing_jumps": fd["jumps"],
        "towers": towers,
        "peaks": peaks,
        "tower_delays": delays,
    }


def tii_report(power, ks):
    floor = np.median(power[ks % T_U])
    rows = []
    for comb in range(24):
        blocks = np.zeros(8)
        for b in range(8):
            for q in TII_QUARTERS:
                k = q + 2 * comb + 48 * b
                blocks[b] += power[k % T_U] + power[(k + 1) % T_U]
        blocks /= 2 * len(TII_QUARTERS)
        db = 10 * np.log10(blocks / floor)
        order = np.sort(db)
        score = float(order[4:].mean() - order[:4].mean())   # lit blocks minus dark ones
        lit = [int(b) for b in np.argsort(db)[4:]]
        rows.append({
            "comb": comb,
            "comb_hex": f"{comb:02X}",
            "tower": TOWERS.get(comb),
            "score_db": round(score, 2),
            "lit_blocks": sorted(lit),
            "block_db": [round(float(v), 2) for v in db],
        })
    return rows


def _sub_peak(prof, i, half):
    """Sub-bin peak of `prof` within `half` bins of index i, allowing wrap."""
    n = len(prof)
    idx = np.arange(i - half, i + half + 1) % n
    j = int(np.argmax(prof[idx]))
    j = min(max(j, 1), len(idx) - 2)
    seg = prof[idx]
    return i - half + parabolic(seg, j)


def tower_delays(null_spec, rolls, towers, peaks, ks, z, min_score_db=3.0, n_sub=0):
    """Arrival time of each heard tower, from the phases of its TII carriers.

    Towers use one of two rules for the second carrier of each pair. Some give
    it the PRS phase of the first carrier ("same"), others its own PRS phase
    ("own"). St Thomas uses "same", Stockland Hill and Holcombe Down "own".
    The code tries both and keeps the one with the sharper profile.

    With n_sub > 1, the frames are also split into n_sub blocks, and the
    spread of the delay across blocks gives "delay_sd_us", the standard
    error of the delay from noise alone.
    """
    big = T_U * UP
    pos = {int(k): i for i, k in enumerate(ks)}
    heard = sorted((r for r in towers if r["score_db"] >= min_score_db),
                   key=lambda r: -r["score_db"])
    if not heard:
        return []
    blocks = heard[0]["lit_blocks"]          # every tower shares the main ID
    us_per_sample = 1e6 / FS
    n_frames = len(null_spec)
    use_sub = n_sub > 1 and n_frames >= 2 * n_sub
    out = []
    for r in heard:
        base = [q + 2 * r["comb"] + 48 * b for q in TII_QUARTERS for b in blocks]
        k1 = np.array(base + [k + 1 for k in base])
        cols = np.array([pos[k] for k in k1])
        y = null_spec[:, cols]

        # Rough delay from the phase step inside each pair. It has no repeats
        # but is only good to a few microseconds.
        half = len(base)
        step = y[:, half:] * np.conj(y[:, :half])
        best = None
        for rule in ("same", "own"):
            ref_k = np.array(base + base) if rule == "same" else k1
            ref = z[ref_k % T_U]
            prof = np.zeros(big)
            subs = np.zeros((n_sub, big)) if use_sub else None
            for f0 in range(0, len(y), 256):
                yb = y[f0:f0 + 256]
                g = np.zeros((len(yb), big), dtype=np.complex128)
                g[:, k1 % big] = yb * np.conj(ref)
                hb = np.abs(np.fft.ifft(g, axis=1)) ** 2
                for i, h in enumerate(hb):
                    hr = np.roll(h, rolls[f0 + i])
                    prof += hr
                    if use_sub:
                        subs[(f0 + i) * n_sub // n_frames] += hr
            sharp = prof.max() / np.median(prof)
            if best is None or sharp > best[0]:
                pair = np.conj(ref[half:]) * ref[:half]
                best = (sharp, rule, prof, np.sum(step * pair), subs)
        sharp, rule, prof, pair_sum, subs = best

        # Fine delay, modulo the repeat spacing, on the impulse response grid.
        i = int(np.argmax(prof))
        fine = (parabolic(prof, i) if 0 < i < big - 1 else i) / UP - PRE
        rough = -np.angle(pair_sum) / (2 * np.pi) * T_U - PRE
        # Pick the repeat: one that lands within 2 samples (1 us) of an impulse
        # response peak and within one repeat of the rough delay, nearest the
        # rough delay. If none does, the repeat nearest the rough delay.
        n0 = round((rough - fine) / TII_ALIAS)
        delay, match = fine + n0 * TII_ALIAS, None
        options = []
        for n in range(n0 - 1, n0 + 2):
            cand = fine + n * TII_ALIAS
            for pk in peaks:
                gap = abs(pk["delay_us"] / us_per_sample - cand)
                if gap < 2 and abs(cand - rough) < TII_ALIAS:
                    options.append((abs(cand - rough), cand, pk))
        if options:
            _, delay, match = min(options, key=lambda o: o[0])
        row = {
            "comb_hex": r["comb_hex"],
            "tower": r["tower"],
            "pair_rule": rule,
            "profile_peak_db": round(float(10 * np.log10(sharp)), 1),
            "rough_delay_us": round(float(rough * us_per_sample), 1),
            "delay_us": round(float(delay * us_per_sample), 3),
            "matched_peak_us": match["delay_us"] if match else None,
        }
        if use_sub:
            fines = np.array([_sub_peak(s, i, 2 * UP) for s in subs]) / UP
            sd = fines.std(ddof=1) / np.sqrt(n_sub)
            row["delay_sd_us"] = round(float(sd * us_per_sample), 4)
        if match:
            match["tower"] = r["tower"] or r["comb_hex"]
        out.append(row)
    return out


def peak_report(cir, rel_floor_db=-37.0):
    avg = cir.mean(axis=0, dtype=np.float64)
    main = avg[PRE * UP]
    noise = np.median(avg)
    thresh = max(main * 10 ** (rel_floor_db / 10), noise * 10)
    guard = 3 * UP
    peaks = []
    for i in range(guard, len(avg) - guard):
        if avg[i] < thresh or avg[i] != avg[i - guard:i + guard + 1].max():
            continue
        d = float(parabolic(avg, i) / UP) - PRE        # samples after the main peak
        if d > T_U - 2 * PRE:                     # wrapped round: negative delay
            d -= T_U
        peaks.append({
            "index": i,
            "delay_us": round(d / FS * 1e6, 3),
            "path_km": round(d / FS * C_LIGHT / 1000, 3),
            "rel_db": round(float(10 * np.log10(avg[i] / main)), 1),
        })
    peaks.sort(key=lambda p: p["delay_us"])
    return peaks


def track_peaks(cir, peaks):
    """For each average peak, its delay from the main peak in every frame."""
    half = int(1.5 * UP)
    t = np.arange(len(cir)) * T_FRAME / FS
    for pk in peaks:
        i = pk["index"]
        d = []
        for h in cir:
            j = i - half + int(np.argmax(h[i - half:i + half + 1]))
            j = min(max(j, 1), len(h) - 2)
            # The main peak sits within 1/16 sample of PRE*UP after the roll.
            # Subtract its exact position, or that rounding shows up as a
            # 60 ns sawtooth.
            m = parabolic(h, PRE * UP)
            d.append((parabolic(h, j) - m) / UP / FS * 1e9)
        d = np.array(d)
        pk["track_ns"] = [round(float(v), 1) for v in d]
        if pk["index"] == PRE * UP:
            pk["std_ns"] = pk["drift_ns_per_min"] = pk["peak_to_peak_ns"] = 0.0
            continue
        slope = np.polyfit(t, d, 1)[0] if len(t) > 2 else 0.0
        pk["std_ns"] = round(float(d.std()), 1)
        pk["peak_to_peak_ns"] = round(float(d.max() - d.min()), 1)
        pk["drift_ns_per_min"] = round(float(slope * 60), 1)
