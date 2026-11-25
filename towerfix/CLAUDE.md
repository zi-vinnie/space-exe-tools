# TowerFix

Code for positioning a rocket without GPS, using timing signals from BBC
DAB towers around Exeter. The plan is on the society wiki: "TowerFix: tracking a
rocket with BBC radio towers" (Leaders) and "2026-11-10 : Ground test
plan" (Meeting Notes).

## Layout

- `ground-test/` holds scripts for the ground test: recording the BBC
  National DAB multiplex (block 12B, 225.648 MHz) and analysing the
  recordings afterwards.
- `towerfix/` is the shared Python package. `timing.py` finds each
  tower's arrival time from raw samples (`ground-test/analyse.py` imports
  it). `fix.py` turns arrival times into a position and does calibration.
  `stream.py` reads a recording or a live dongle in chunks. Code the
  drone test and Crayon 2 will reuse goes here.
- `web/` is Lattice, the browser map tool: a local server (`server.py`) that
  replays recordings or reads the dongle live, and a Leaflet page with
  cached OpenStreetMap tiles. `web/offsets.json` holds each tower's
  network offset against St Thomas. See `web/README.md`. Its look is in
  `../DESIGN.md`; use the impeccable skill for UI changes.
- `recordings/` holds raw recordings. Git ignores it, because a
  10-minute recording is about 2.5 GB. Name files
  `YYYY-MM-DD_HHMM_site.cu8` and keep a note of the site's GPS position
  next to each one.

## Kit

- RTL-SDR Blog V3 kit: dongle (R860 tuner, which reports itself as
  R820T, serial 00000001) and the Blog's multipurpose dipole antenna kit.
  The ground test draft lists a Nooelec RaTLSnake antenna instead, but
  that isn't what we bought.
- For DAB block 12B, extend each long telescopic arm to about 32 cm and
  stand the dipole vertically, because UK DAB is vertically polarised.
  Leave the bias tee off.
- Tested on Linux on 2026-11-25 with `rtl-sdr` 2.0.1 and
  `welle-io` 2.7. The kernel TV driver is blocked by
  `/etc/modprobe.d/blacklist-rtl-sdr.conf`.
