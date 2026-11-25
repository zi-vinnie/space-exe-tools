---
version: 1
slug: "towerfix-web-static-index-html"
primary_target: "towerfix/web/static/index.html"
related_targets: []
---

# Lattice map (towerfix/web/static/index.html)

Scope: the Lattice map app, Operate mode. Desk replay now; live on a laptop outdoors in daylight from early 2027.
Job: see where the antenna is, which towers made the fix, and whether to trust it.
Constraints: offline (vendored Leaflet, fonts, cached tiles), no build step, test IDs in tests/test_ui.py stay, colour never the only signal.

## Direction contract

THESIS: The map is a Decca lattice chart. Each tower is a lettered lane against St Thomas, the master, and the fix is where the lanes cross. It refuses the grey-panel-plus-blue-accent map tool.

OWN-WORLD: White chart paper, navy ink (#0b1450) for the master, text and fix, and lane colours red, green and purple first (then blue, ochre, teal, magenta) carried on hyperbolas, tower markers and table chips. Each lane also has a letter, so colour is never alone. Archivo Narrow for chart lettering (headings, lane tags, numbers), Archivo for body. Square-cornered controls with navy rules. The map has a double-ruled chart neat line.

STORY: The user opens a recording or goes live, reads the fix and its trust line first, checks the lanes in the table, unticks a bad tower, and marks the true position to score it.

FIRST VIEWPORT: Map fills the left with the neat line; lane tags sit on each hyperbola in lane colour. The right panel (400px) has the Lattice mark and name, then Source (Replay or Live, transport buttons), then Fix with the position large in tabular condensed figures and a one-line trust verdict, then Towers with lane chips, then Map click with Calibrate set apart.

FORM: Decca lattice chart, IMPECCABLE'S PICK (position 1 of 7 on the grounded list), seed:9d07999c687fa29c.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
