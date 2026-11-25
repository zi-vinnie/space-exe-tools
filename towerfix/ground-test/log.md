# Ground test log

## 2026-11-25, first desk checks

Site for every recording today: Physics Building, University of Exeter
(Streatham campus), 7th floor, indoors. Phone GPS 50.736875, -3.536434 (Google Maps, 11:58).

- `rtl_test` ran for 2 minutes at 2.048 MS/s and lost no samples.
- welle.io scan found 9A Exeter, 11A SDL National, 11C Devon, 11D D1
  National and 12B BBC National DAB. 12B decoded all 16 BBC stations.
- Recorded 30 s of 12B indoors at a gain of 29.7 dB:
  `recordings/2026-11-25_1138_desk.cu8`. The in-band signal is 30 dB above
  the noise, and the null symbol repeats every 96 ms. 1.3% of samples clip,
  so use a gain of about 20 dB next time.
- `welle-cli` on that file decoded the ensemble (ID CE15) and reported TII
  pattern 14, comb 9, which is `0E 09`, St Thomas. It reported no other
  tower. Its delay estimates (85 to 469 samples) jump around too much to
  use.

## 2026-11-25, first run of analyse.py on the desk recording

- `uv run analyse.py ../recordings/2026-11-25_1138_desk.cu8`, results in
  `results/2026-11-25_1138_desk/`.
- Frequency offset 3.3 Hz (0.014 ppm), so the dongle's TCXO is good.
- TII, as lit minus dark blocks: `09` St Thomas 31 dB, `0B` Stockland Hill
  11.6 dB, `0C` (not in our tower list) 11.4 dB. Everything else is under
  5 dB, so not convincing. All lit blocks are 2 to 5, which is pattern 14
  (`0E`). That matches the main ID in the notes and confirms the TII carrier
  layout in the script.
- The impulse response has clear secondary peaks at 28.7 µs and 73.9 µs
  (about -24 dB) and weaker ones at 58.2 µs and 114.5 µs (about -35 dB).
  We can't yet say which peak is which tower.
- Over 30 s the gaps to the strongest peak wander by roughly ±50 ns. The
  strongest peaks all wander together, which suggests the reference (St
  Thomas, indoors) is moving because of nearby reflections, not the other
  towers. That is well inside the 300 ns pass limit, but 30 s is too short
  to judge drift.
- First version had a 60 ns sawtooth from rounding the main peak to 1/8
  sample. Fixed by subtracting the main peak's exact position each frame.

## 2026-11-25, 10-minute recording

- `recordings/2026-11-25_1148_desk-10min.cu8`, same site, gain 19.7 dB.
  `rtl_sdr -n 1228800000` didn't stop at 10 minutes. It seems to overflow
  above about 2^31 bytes, so I stopped it by hand at 10.9 minutes (6,866
  frames). Record long runs in parts under 2 GB, or stop them with a timer.
- No timing jumps, so the dongle dropped no samples. Frequency offset
  -22 Hz (-0.1 ppm).
- TII at the lower gain: St Thomas 27 dB, Stockland Hill 6.9 dB, Holcombe
  Down 6.3 dB. Brixham, Huntshaw Cross and Beacon Hill North show at 2 to
  4 dB, which is too weak to call.
- Peaks and their stability over 11 minutes, as the gap to the strongest
  peak:

  | Delay | Level | Spread (1 sd) | Peak to peak | Drift |
  |---|---|---|---|---|
  | 6.6 µs | -25 dB | 36 ns | 260 ns | -3.8 ns/min |
  | 13.3 µs | -35 dB | 32 ns | 279 ns | 1.4 ns/min |
  | 28.7 µs | -23 dB | 37 ns | 213 ns | 0.2 ns/min |
  | 58.1 µs | -35 dB | 62 ns | 328 ns | 4.8 ns/min |
  | 73.9 µs | -24 dB | 16 ns | 103 ns | 2.0 ns/min |

- There's no steady drift. The 28.7 and 58.1 µs peaks swing ±100 ns in
  30 to 60 s cycles that speed up and slow down. That looks like a moving
  reflection beating with them (a guess, possibly aircraft).
- Expected extra path compared with St Thomas, from `../towers.json` and
  the site position: Budleigh 48 µs, Tiverton 53 µs, Holcombe Down 55 µs,
  Stockland Hill 96 µs, Beer 96 µs, Beacon Hill North 100 µs. The measured
  peaks (28.7, 58.1, 73.9 µs) don't line up neatly, so the network probably
  adds fixed delays at some transmitters. We need per-tower timing from TII
  to match peaks to towers.

## 2026-11-25: which peak is which tower

`analyse.py` now finds each tower's arrival time from the phases of its TII
carriers. That gives a delay profile for one tower. It repeats every
20.83 µs, so the script matches it to an impulse response peak, and a
rough delay from the phase step inside each carrier pair picks the repeat.

Two things had to be found from the data:

- The TII signal is timed as if its useful part were the last 2048 samples
  of the null (608 samples in), not from the start of the null.
- Towers differ in the phase of the second carrier of each pair. St Thomas
  and Beacon Hill North give it the first carrier's PRS phase. Stockland
  Hill and Holcombe Down give it its own PRS phase. The script tries both.

| Peak | Tower (TII) | TII delay | Geometric | Offset |
|---|---|---|---|---|
| 0 µs | St Thomas (0E09) | 0.04 µs | 0 | reference |
| 28.7 µs | Stockland Hill (0E0B) | 28.79 µs | 96 µs | -67 µs |
| 58.1 µs | Beacon Hill North (0E07) | 58.16 µs | 100 µs | -42 µs |
| 73.9 µs | Holcombe Down (0E0C) | 73.99 µs | 55 µs | +19 µs |

The TII delay is within 0.1 µs of the matched peak in both recordings.
Beacon Hill North only clears the TII threshold in the 30 s recording.
The 6.6 and 13.3 µs peaks have no tower, so they are probably reflections
of St Thomas. The 114.5 µs peak is unmatched.

"Offset" is measured minus geometric, and is the network's fixed delay at
each transmitter compared with St Thomas. If that's right, a second site
should give the same offsets. Checking that is the next recording.

## 2026-11-25: browser map tool and replay fixes

Built a map tool in `web/` (see `web/README.md`). The timing code moved
into `towerfix/timing.py`, and `analyse.py` gives the same `summary.json`
on the 30 s recording as before. `towerfix/fix.py` solves a 2D TDOA fix
against St Thomas. Fixes never use GPS. Only "calibrate here" and the
scoring click use a known position.

Offsets from the 30 s recording at the phone GPS position, now in
`web/offsets.json`: Stockland Hill -67.138 µs, Holcombe Down +19.341 µs,
Beacon Hill North -41.853 µs. The 10-minute recording gives Stockland
Hill and Holcombe Down within 4 ns of these.

Replay in 5 s chunks, scored against the phone GPS position. Both
recordings are at the calibration site, so this only checks the code:

| Recording | Fixes | Towers | Mean fix error | Scatter (RMS) | Worst chunk |
|---|---|---|---|---|---|
| 30 s | 5 | 4 | 0.2 m | 5.1 m | 8.2 m |
| 10 min | 132 | 3 | 1.6 m | 5.3 m | 14.2 m |

- With 3 towers the two hyperbolas cross twice and both crossings fit
  exactly. On the 10-minute recording the first version picked the wrong
  one, 11.9 km away near 50.794, -3.679. The tool now picks the crossing
  nearest the last fix with 4 towers, or else nearest the strongest tower,
  and flags the fix as ambiguous. That rule is a guess. A 4th tower fixes
  it properly.
- Between chunks the TDOAs move by 12 to 18 ns (1 sd), against 2 to 7 ns
  of noise inside a chunk. The solver adds 10 ns of wander per tower. Its
  predicted 1 sd size (about 6 to 7 m) matches the 5 m scatter.
- Live mode ran for 30 s at 20 dB gain (6 fixes, no timing jumps, same 3
  towers). The fixes were 19 to 26 m north of the phone GPS position. I
  don't know if the antenna was still at the desk site. The frequency
  offset moved from -36 to -13 Hz as the dongle warmed up.

## 2026-11-25: map tool bug fixes

A browser test pass (`web/tests/test_ui.py`) found 21 failing checks out
of 124. Fixed in seven commits:

1. A ticked or unticked tower box snapped back after the update. The page
   now draws each box from the result, and the server sends the status
   first.
2. Unticking St Thomas moved the fix 20 km to the other crossing. A toggle
   no longer forgets the earlier fixes. With 3 towers the solver picks the
   crossing nearest the last 4-tower fix, or else the last fix of any
   kind. Only a run's first fix uses the strongest tower.
3. Live mode left rtl_sdr's output pipe and error file open after Stop.
4. Stop held the server's lock for up to 3 s while rtl_sdr exited.
5. A chunk still being analysed when Open, Back or Stop came in could
   still land in the run and on the page. Those results are now dropped,
   and results go out in order.
6. Calibration counted a chunk twice if you went back to it, and named the
   source "live" when run after Stop in replay mode.
7. A chunk that lost its fix (after unticking towers) kept its old point
   in the track. Each chunk now has at most one track point.

The browser test now has 130 checks and all pass, twice in a row. Replay
numbers are the same as before the fixes: 30 s recording median 1.8 m and
max 8.2 m, 10-minute recording median 4.4 m and max 14.2 m. A short live
run (2 chunks of 2 s, 3 towers) gave a fix, and Stop took 0.07 s and left
no rtl_sdr running.
