---
name: Lattice
description: The TowerFix map app, drawn as a Decca lattice chart in Space EXE navy.
colors:
  paper: "#ffffff"
  sheet: "#f4f5f7"
  ink: "#0b1450"
  ink-2: "#3d4677"
  rule: "#c9cedc"
  lane-a: "#c8302a"
  lane-b: "#1f7a3a"
  lane-c: "#6b2e8f"
  lane-d: "#1d5fa8"
  lane-e: "#0f7c7c"
  lane-f: "#a3306b"
  lane-g: "#7a5230"
  lane-h: "#5a6270"
  truth: "#d46b00"
  ok: "#1f7a3a"
  warn: "#8a4b00"
  bad: "#b3261e"
typography:
  title:
    fontFamily: "Archivo Narrow, Arial Narrow, sans-serif"
    fontSize: "28px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.01em"
  readout:
    fontFamily: "Archivo Narrow, Arial Narrow, sans-serif"
    fontSize: "34px"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.01em"
  heading:
    fontFamily: "Archivo Narrow, Arial Narrow, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.12em"
  control:
    fontFamily: "Archivo Narrow, Arial Narrow, sans-serif"
    fontSize: "15px"
    fontWeight: 500
    lineHeight: 1.2
  body:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
  small:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  none: "0px"
  control: "2px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "12px"
  lg: "18px"
  panel-x: "22px"
components:
  button:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
    height: "38px"
  button-hover:
    backgroundColor: "{colors.sheet}"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
    height: "38px"
  tab-on:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  tab-danger:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.bad}"
  tab-danger-on:
    backgroundColor: "{colors.bad}"
    textColor: "{colors.paper}"
  lane-chip:
    backgroundColor: "{colors.lane-a}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    height: "22px"
  lane-chip-master:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    height: "22px"
---

# Design System: Lattice

## Overview

**Creative North Star: "The lattice chart"**

Lattice is drawn like a Decca Navigator chart. Those charts overprinted families of coloured hyperbolas, called lanes, on the sea, and a navigator found their position where the lanes crossed. TowerFix works the same way with BBC DAB towers, so the app shows its working in the same form. St Thomas is the master station in navy. Every other tower is a lane with its own colour and letter, and the fix is the navy ring where the lanes cross.

The app is used at a desk and outdoors in daylight, so it is light only. Navy ink on white paper is the highest-contrast pair the world offers. The world shows up in four places only: chart lettering, lane colours, the double-ruled neat line round the map, and lane tags on the hyperbolas. Controls are ordinary web controls drawn square, with navy rules.

**Key Characteristics:**
- White chart paper, navy ink, and one colour plus one letter per tower lane.
- Condensed chart lettering for headings, labels and every number.
- A double-ruled neat line frames the map like a printed chart.
- Square corners and navy rules. No shadows.

## Colors

Navy ink on white does almost all of the work. Lane colours are data and appear only where a tower is shown.

### Primary
- **Chart Ink** (#0b1450): text, rules, the master station, the fix symbol, selected tabs and the primary button. This is the navy from the Space EXE badge.

### Neutral
- **Paper** (#ffffff): the map surround, the panel and control fills.
- **Sheet** (#f4f5f7): the page behind the chart, and button hover.
- **Ink 2** (#3d4677): secondary text, 8.9:1 on paper. Secondary text is tinted from the ink, never grey.
- **Rule** (#c9cedc): row and section dividers.

### Lane colours
Lanes are given in towers.json order, skipping the master: A red #c8302a, B green #1f7a3a, C purple #6b2e8f, then D blue #1d5fa8, E teal #0f7c7c, F magenta #a3306b, G brown #7a5230 and H slate #5a6270. The first three are Decca's own red, green and purple.

### State
- **Truth** (#d46b00): the true position marker only. It stays out of the lane palette so it never reads as a tower.
- **OK** (#1f7a3a), **Warn** (#8a4b00), **Bad** (#b3261e): fix verdicts, connection state, and the Calibrate control.

### Named Rules
**The Letter Rule.** A lane colour never appears without its letter: on the tower label, the lane tag on the map and the chip in the table. Colour is never the only signal.

**The Ink Rule.** Anything that isn't a tower is navy, white or a state colour. Lane colours are never used for decoration.

## Typography

**Chart lettering:** Archivo Narrow, weights 500 and 700, self-hosted in `static/vendor/fonts/`.
**Body:** Archivo, weight 400.

Every number on the page uses tabular figures, so columns line up and values don't jump as they update.

### Hierarchy
- **Title** (700, 28px, uppercase): "LATTICE" in the panel header.
- **Readout** (700, 34px): the fix position. This is the largest thing in the panel.
- **Heading** (700, 14px, uppercase, 0.12em tracking): section names (Source, Fix, Towers, Map click).
- **Control** (500, 15px): buttons, tabs, inputs and the numbers in the tower table.
- **Body** (400, 15px) and **Small** (400, 13px): status lines, explanations and fix details.

## Layout

The map fills the left side inside a 12px white margin and the neat line. The panel is a fixed 400px column on the right with a 2px navy rule between them. Sections stack in task order (Source, Fix, Towers, Map click), split by 1px rules, with 18px headings above each one.

Below 760px wide, the map takes the top 58% of the screen and the panel follows underneath at full width, with a 16px gutter.

## Elevation & Depth

The page is flat, like a printed chart. Depth comes only from rules: the 1px plus 2px double neat line round the map (drawn with `box-shadow` spread and no blur) and the navy panel rule. There are no drop shadows anywhere, including on Leaflet's controls.

## Shapes

Corners are square. Controls get a 2px radius so they don't look sharp-edged. Lane chips, lane tags and tower labels have 0px.

## Components

### Buttons
- **Default:** white with a 1.5px navy rule, 38px tall, Archivo Narrow 15px.
- **Primary** (Open, Start): navy fill, white text. One per source mode.
- **Quiet** (Clear track): pale rule and a smaller size, for actions that are cheap to undo.

### Segmented tabs
These are a row of tabs sharing one navy outline. The selected tab is filled navy. Used for Replay or Live, and for map click mode.

### Calibrate here
Calibrate rewrites `offsets.json`, so it sits 12px apart from the other click modes, outlined and lettered in red, and fills red when selected. The page then asks for confirmation before calibrating.

### Lane chip
This is a square 22px chip with the lane letter in white on the lane colour. The master is navy-outlined white with "M". It appears in the first column of the tower table.

### Lane tag (signature)
The lane letter is set on the hyperbola in its lane colour, about 110px along the line from the fix, so it labels the lane without covering the crossing. The tags move whenever you zoom. A lane that isn't used gets a dashed outline tag over a dashed line.

### Fix symbol and verdict
The fix is a navy ring with a white centre, inside a navy 95% ellipse. Under the readout, a bordered verdict names how far to trust the fix: "Checked by N spare towers" (green with a tick), "Towers disagree" (red, when χ² is over its 95% point), "Unchecked: only 3 towers" or "Two crossings fit" (amber with a warning triangle), or "No fix" (red).

### Inputs
Inputs share the button's rule and height. Numbers are right-aligned. Checkboxes and range sliders use the navy accent colour.

## Do's and Don'ts

### Do:
- **Do** give every new tower view its lane colour and letter together.
- **Do** keep numbers in Archivo Narrow with tabular figures.
- **Do** keep destructive or file-writing actions apart from the rest and in red.
- **Do** let a bad fix look bad: the verdict changes colour, icon and words.

### Don't:
- **Don't** add a dark mode for the field. The scene is daylight, and navy on white is the contrast the world has.
- **Don't** use lane colours for decoration, headers or buttons.
- **Don't** add drop shadows, rounded cards or gradients. The chart is flat print.
- **Don't** put the University of Exeter crest or the Space EXE roundel in the app. Credit them in text.
