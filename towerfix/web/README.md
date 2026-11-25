# TowerFix map

A map page that positions the RTL-SDR antenna from BBC National DAB
(block 12B) timing, without GPS. It replays `.cu8` recordings or reads
the dongle live, and makes one fix every chunk (5 s by default).

## Run it

From `towerfix/web`:

```
uv run server.py
```

Then open <http://127.0.0.1:8765/>. Stop the server with Ctrl+C. `uv`
makes a `.venv` here the first time, with numpy as the only dependency.
The server only listens on this computer.

Map tiles come from a local cache in `tiles/` (git ignores it). To fill
the cache on a new computer, run `uv run fetch_tiles.py` once. It fetches
879 OpenStreetMap tiles: zoom 0 to 13 over all the towers, and 14 to 16
for about 3 km round Exeter centre, with a pause between requests. Leaflet
1.9.4 is in `static/vendor/`, so the page works offline.

## Using the page

- Replay: pick a recording from `../recordings/`, press Open, then Next,
  Back or Play. The slider jumps to any chunk.
- Live: set the gain (about 20 dB indoors) and press Start. The server runs
  `rtl_sdr` and analyses the newest whole chunk. Stop ends it.
- Towers: the table shows each tower's TII strength, arrival time after the
  strongest signal, and its residual in the fix. Untick a tower to leave
  it out. An unticked tower still gets a dashed hyperbola, so you can see
  whether it agrees.
- Map click, "True position": marks where the antenna really is and shows
  each fix's error. It stays in the page and is never used for fixes.
- Map click, "Calibrate here": re-measures every tower's offset against St
  Thomas from all chunks of the current run, assuming the click is the true
  position, and saves `offsets.json`. The old file is kept as
  `offsets.prev.json`.

Without the browser, `uv run replay.py ../recordings/FILE.cu8 --true LAT LON`
prints one fix per chunk and the scatter. `--calibrate LAT LON` writes
`offsets.json` from a whole recording.

## How the fix works

- `../towerfix/timing.py` finds each tower's arrival time from its TII
  carriers, matched to an impulse response peak. Only towers in
  `../towers.json` that matched a peak are used.
- Each arrival time minus St Thomas's gives a time difference (TDOA).
  Taking off each tower's fixed network offset (`offsets.json`) leaves a
  range difference, which is one hyperbola on the map.
- `../towerfix/fix.py` finds the least-squares point. Ranges use exact
  Earth-centred coordinates. The receiver is assumed to be 60 m above the
  ellipsoid, which changes ranges by about 1 m at most.
- With 3 towers the two hyperbolas often cross twice and both fit
  exactly. The page then says "ambiguous" and picks the crossing nearest
  the last unambiguous fix, or else the last fix of any kind. Only the
  first fix of a run, with nothing before it, picks the crossing nearest
  the strongest tower. That is a guess. Unticking a tower keeps the
  earlier fixes, so the choice doesn't jump to the other crossing. A 4th tower settles it and also checks the fix (the chi-squared).
- The ellipse is 95% from timing noise only: the noise inside the chunk
  plus 10 ns of wander per tower between chunks, measured on the desk
  recordings. It does not include multipath bias or a wrong offset, which
  can be much larger at a new site.
- The TII timing repeats every 20.83 us (6.2 km of range). The timing code
  picks the repeat as `analyse.py` does, using the nearest impulse
  response peak and the rough delay from each carrier pair.
