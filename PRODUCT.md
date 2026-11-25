# Product

<!-- impeccable:product-schema 1 -->

This file covers the TowerFix map app in `towerfix/web/`. Other tools in
this repo may get their own section later.

## Platform

web

## Users

Space EXE members working on TowerFix, the society's project to position a
rocket without GPS. Today that is mainly one person replaying recordings at
a desk. From early 2027 the team will also run it live on a laptop outdoors:
first on a drone test, then at a Crayon 2 launch. In the field the user
reads it in daylight, often standing, with little time and a dongle plugged
in.

## Product Purpose

The app shows where an RTL-SDR antenna is, worked out only from the timing
of BBC National DAB signals (block 12B) from towers around Exeter. It
replays `.cu8` recordings or reads the dongle live, and makes one position
fix per chunk (5 s by default). Success means a user can tell at a glance
whether the fix is good, which towers it used, and how far it is from the
true position when that is known.

## Positioning

Positioning from existing broadcast towers, with no GPS and no ground
beacons of our own. The app shows the working: each tower's signal
strength, arrival time and residual, plus a hyperbola per tower pair on the
map, so a user can see why a fix landed where it did.

## Operating Context

- A local Python server (`server.py`) on the user's laptop, opened in a
  browser at 127.0.0.1. It only listens on that computer.
- It must work offline: OpenStreetMap tiles come from a local cache and
  Leaflet is vendored.
- Replay mode: open a recording, step Back and Next, Play, or seek.
- Live mode: set gain, Start and Stop the dongle.
- Map clicks can mark the true position or calibrate tower offsets, which
  rewrites `offsets.json`.

## Capabilities and Constraints

- Plain HTML, CSS and JavaScript with Leaflet 1.9.4. No build step, no
  framework, no CDN at runtime.
- Desktop first. A phone-width layout exists and should keep working.
- Must stay readable in light and dark mode, and in sunlight.
- Flights follow the UKRA safety code. Keep defence or targeting uses out
  of anything public, including copy in the app.

## Brand Commitments

- The project and Python package stay "TowerFix". The map app gets its own
  name and logo (decided 2026-11-25).
- The app belongs to the Space EXE family. Space EXE's logo is a navy
  roundel with a gold ring, a white rocket, gold, orange and blue planet
  dots, and serif capitals ("UNIVERSITY OF EXETER", "SPACE EXE", "Ad Astra
  Per Aspera"). The app's mark can borrow its navy and gold but must not
  copy the roundel.
- Credit "Space EXE, University of Exeter" in small type. Do not use the
  University of Exeter's own logo or crest, which needs the university's
  permission.

## Evidence on Hand

- Two desk recordings from 2026-11-25 and their results in
  `towerfix/ground-test/results/`.
- Society logo: in the society's private repo as
  `assets/space-exe-logo-cropped.png`, not in this repo.
- No field results yet. Don't invent accuracy figures.

## Product Principles

1. The fix quality is the first thing a user sees. A bad fix must look bad.
2. Show the working. Every number on screen should trace back to a tower.
3. Field first when it matters. Big targets, high contrast, no hover-only
   information for anything needed live.
4. Works offline, every time.

## Accessibility & Inclusion

Colour must not be the only signal for tower status or fix quality, because
the team reads it outdoors and some members may be colour-blind.
