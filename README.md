# Space EXE tools

Software from Space EXE, the University of Exeter space society. The
society builds hobby rockets and flies them under the UKRA safety code.

## What's here

- `towerfix/` positions a receiver without GPS, using timing signals from
  the BBC National DAB towers around Exeter (block 12B, 225.648 MHz). It
  has a Python package, scripts for the ground test, and a map tool in the
  browser, Lattice, that replays recordings or reads an RTL-SDR dongle
  live. Start with `towerfix/web/README.md`.

## Licence

MIT, see `LICENSE`. Leaflet in `towerfix/web/static/vendor/` has its own
BSD-2-Clause licence, and the Archivo fonts in `vendor/fonts/` use the SIL
Open Font Licence.

## Design

`PRODUCT.md` and `DESIGN.md` describe who Lattice is for and its visual
rules. Claude Code reads them through the impeccable skill in
`.claude/skills/impeccable/`.
