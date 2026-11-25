# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Browser test of the TowerFix map page.

Run from towerfix/web:

    uv run tests/test_ui.py [--headed] [--shots DIR] [--port 8799]

It starts server.py on its own port, drives the page in Chromium with
Playwright, and prints PASS or FAIL for each check, then the totals. It
needs the two desk recordings in ../recordings. It never starts live mode.

The calibrate step rewrites offsets.json, so the test copies it first and
puts it back at the end, and deletes the offsets.prev.json it leaves.

If Playwright's own Chromium is missing, it falls back to the installed
Google Chrome. To install Playwright's: uv run --with playwright playwright
install chromium.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

WEB = Path(__file__).resolve().parent.parent
OFFSETS = WEB / "offsets.json"
OFFSETS_PREV = WEB / "offsets.prev.json"
SHORT = "2026-11-25_1138_desk.cu8"      # 30 s, 4 towers
LONG = "2026-11-25_1148_desk-10min.cu8"  # 10 min, 3 towers
TRUE_POS = (50.736875, -3.536434)        # phone GPS, desk recordings
FOUR = ["0E09", "0E0B", "0E0C", "0E07"]  # St Thomas, Stockland Hill, Holcombe Down, Beacon Hill North

# Records every SSE message the page gets, in order, so the test can wait
# for the next result and compare it with what the page shows.
INIT_JS = """
window.__events = [];
const _add = EventSource.prototype.addEventListener;
EventSource.prototype.addEventListener = function (type, fn, opts) {
  return _add.call(this, type, (ev) => {
    window.__events.push({ type, data: JSON.parse(ev.data), t: performance.now() });
    return fn(ev);
  }, opts);
};
"""

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
    return ok


class Page:
    def __init__(self, page, base, shots):
        self.p = page
        self.base = base
        self.shots = shots
        self.console_errors = []
        self.failed = []
        self.exclude_posts = []
        # Tile 404s show up as console errors too; those are counted apart.
        # Failed loads also show as console errors; the network check covers those.
        page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource")
                and self.console_errors.append(m.text))
        page.on("request", lambda r: "/api/exclude" in r.url and self.exclude_posts.append(json.loads(r.post_data)))
        page.on("pageerror", lambda e: self.console_errors.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: self.failed.append(f"{r.url} {r.failure}")
                if "/api/events" not in r.url else None)
        page.on("response", lambda r: r.status >= 400 and self.failed.append(f"{r.status} {r.url}"))

    # Helpers -----------------------------------------------------------------

    def api(self, path, body=None):
        req = urllib.request.Request(self.base + path, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def server_excluded(self):
        return set(self.api("/api/state")["status"]["excluded"])

    def n_events(self, kind="result"):
        return self.p.evaluate(f"window.__events.filter(e => e.type === '{kind}').length")

    def wait_results(self, after, n=1, timeout=30):
        """Wait until `n` more result events than `after` have arrived."""
        end = time.time() + timeout
        while time.time() < end:
            if self.n_events() >= after + n:
                return True
            self.p.wait_for_timeout(50)
        return False

    def total(self):
        return self.p.evaluate("window.__events.length")

    def act(self, fn, n=1, quiet_ms=1200):
        """Do `fn`, wait for `n` new SSE messages, then wait for quiet."""
        before = self.total()
        fn()
        end = time.time() + 30
        while time.time() < end and self.total() < before + n:
            self.p.wait_for_timeout(50)
        self.settle(quiet_ms)

    def settle(self, quiet_ms=1200, timeout=30):
        """Wait until no SSE message has arrived for `quiet_ms`."""
        end = time.time() + timeout
        while time.time() < end:
            age = self.p.evaluate("window.__events.length ? performance.now() - window.__events.at(-1).t : 1e9")
            if age > quiet_ms:
                return True
            self.p.wait_for_timeout(100)
        return False

    def last(self, kind):
        return self.p.evaluate(f"(window.__events.filter(e => e.type === '{kind}').at(-1) || {{}}).data")

    def boxes(self):
        """{tii: checked} as the page shows it."""
        return self.p.evaluate("""Object.fromEntries([...document.querySelectorAll('#towers tbody input')]
            .map(b => [b.dataset.tii, b.checked]))""")

    def layer_counts(self):
        return self.p.evaluate("""(() => {
            const c = (g) => g.getLayers().length;
            const hyp = layers.hyper.getLayers();
            return { hyper: hyp.length, dashed: hyp.filter(l => l.options.dashArray).length,
                     fix: c(layers.fix), track: c(layers.track), truth: c(layers.truth),
                     onMap: (() => { let n = 0; map.eachLayer(() => n++); return n; })() };
        })()""")

    def click_box(self, tii):
        self.p.click(f"#towers input[data-tii='{tii}']")

    def shot(self, name):
        if self.shots:
            self.p.screenshot(path=str(Path(self.shots) / f"{name}.png"))

    def open(self, name, seconds=5):
        self.p.select_option("#file", name)
        self.p.fill("#seconds", str(seconds))
        n = self.n_events()
        self.p.click("#open")
        ok = self.wait_results(n, 1, timeout=60)
        self.settle()
        return ok

    def set_all_used(self):
        for t in list(self.server_excluded()):
            self.act(lambda: self.api("/api/exclude", {"tii": t, "excluded": False}), 2, 300)


# Tests ------------------------------------------------------------------------

def test_load(pg, n_towers):
    pg.p.goto(pg.base + "/")
    pg.p.wait_for_selector("#conn.ok", timeout=10000)
    check("page loads and SSE connects", pg.p.text_content("#conn") == "connected")
    opts = pg.p.eval_on_selector_all("#file option", "o => o.map(x => x.value)")
    check("recording list has both desk recordings", SHORT in opts and LONG in opts, str(opts))
    check("tower table lists every tower in towers.json", len(pg.boxes()) == n_towers, str(pg.boxes()))
    check("offsets are shown", "Offsets vs St Thomas" in pg.p.text_content("#offsets"))
    tiles = pg.p.evaluate("document.querySelectorAll('.leaflet-tile-loaded').length")
    check("map tiles load", tiles > 0, f"{tiles} tiles")


def test_open_and_layers(pg):
    check(f"open {SHORT} gives a result", pg.open(SHORT))
    res = pg.last("result")
    check("4-tower chunk gives a fix", res and res["fix"] is not None, res and res.get("why"))
    lc = pg.layer_counts()
    check("3 solid hyperbolas, none dashed", lc["hyper"] == 3 and lc["dashed"] == 0, str(lc))
    check("fix layer has ellipse and marker only", lc["fix"] == 2 + 2 * len(res["alternates"]), str(lc))
    check("track has 1 point", lc["track"] == 1, str(lc))
    st = pg.p.text_content("#status")
    check("status names the file and chunk 1 of 5", SHORT in st and "chunk 1 of 5" in st, st)
    pg.shot("01-open-short")


def test_seek_controls(pg):
    n = pg.n_events()
    pg.p.click("#next")
    pg.wait_results(n)
    pg.settle()
    check("Next goes to chunk 2", pg.last("status")["index"] == 1 and pg.last("result")["meta"]["chunk"] == 1)
    n = pg.n_events()
    pg.p.click("#prev")
    pg.wait_results(n)
    pg.settle()
    check("Back goes to chunk 1", pg.last("status")["index"] == 0 and pg.last("result")["meta"]["chunk"] == 0)
    n = pg.n_events()
    pg.p.click("#prev")
    pg.wait_results(n)
    pg.settle()
    check("Back at chunk 1 stays at chunk 1", pg.last("status")["index"] == 0)
    n = pg.n_events()
    pg.p.eval_on_selector("#seek", "s => { s.value = 4; s.dispatchEvent(new Event('change')); }")
    pg.wait_results(n)
    pg.settle()
    check("slider jumps to chunk 5", pg.last("status")["index"] == 4 and pg.last("result")["meta"]["chunk"] == 4)
    n = pg.n_events()
    pg.p.click("#next")
    pg.wait_results(n)
    pg.settle()
    check("Next at the last chunk stays there", pg.last("status")["index"] == 4)
    check("track keeps one point per visited chunk (chunks 1, 2 and 5)", pg.layer_counts()["track"] == 3,
          str(pg.layer_counts()))
    runs = pg.api("/api/state")["status"]["chunks_in_run"]
    check("run counts each visited chunk once (chunks 1, 2 and 5)", runs == 3, f"chunks_in_run = {runs}")


def toggle_and_check(pg, tii, label):
    """Untick one tower while paused, then tick it again."""
    before = pg.layer_counts()
    pg.act(lambda: pg.click_box(tii), 2)
    srv = pg.server_excluded()
    shown = pg.boxes()
    lc = pg.layer_counts()
    ok_srv = check(f"{label}: untick {tii}, server excludes it", tii in srv, str(srv))
    check(f"{label}: untick {tii}, box stays unticked after the update", shown.get(tii) is False,
          f"page shows {shown.get(tii)}, server excluded {sorted(srv)}")
    res = pg.last("result")
    used = [r["tii"] for r in res["towers"] if r["used"]]
    check(f"{label}: untick {tii}, result leaves it out", tii not in used, str(used))
    check(f"{label}: untick {tii}, page and server agree on every box",
          all(shown[t] == (t not in srv) for t in shown), f"page {shown}, server {sorted(srv)}")
    check(f"{label}: untick {tii}, hyperbola count matches result",
          lc["hyper"] == sum(1 for h in res["hyperbolas"] if h["points"]), f"{before} -> {lc}")
    sent = len(pg.exclude_posts)
    pg.act(lambda: pg.click_box(tii), 2)
    srv = pg.server_excluded()
    shown = pg.boxes()
    check(f"{label}: tick {tii} again, page sent excluded=false",
          pg.exclude_posts[sent:] == [{"tii": tii, "excluded": False}], str(pg.exclude_posts[sent:]))
    check(f"{label}: tick {tii} again, server uses it", tii not in srv, str(srv))
    check(f"{label}: tick {tii} again, page and server agree on every box",
          all(shown[t] == (t not in srv) for t in shown), f"page {shown}, server {sorted(srv)}")
    return ok_srv


def test_toggle_paused(pg):
    pg.open(SHORT)
    for tii in FOUR:
        toggle_and_check(pg, tii, "paused")
        pg.set_all_used()
        pg.open(SHORT)


def test_fix_jump_on_exclude(pg):
    pg.open(SHORT)
    base = pg.last("result")["fix"]
    pg.act(lambda: pg.api("/api/exclude", {"tii": "0E09", "excluded": True}), 2)
    res = pg.last("result")
    f = res["fix"]
    d = _dist(TRUE_POS, (f["lat"], f["lon"])) if f else None
    d0 = _dist(TRUE_POS, (base["lat"], base["lon"]))
    check("excluding St Thomas keeps the fix near the 4-tower fix",
          d is not None and d < 500, f"4-tower fix {d0:.0f} m from truth, 3-tower fix {d:.0f} m, "
          f"ambiguous={res['ambiguous']}, chosen {res['chosen_by']}")
    pg.p.wait_for_timeout(300)
    pg.shot("02-exclude-st-thomas")
    pg.set_all_used()


def test_below_three(pg):
    pg.open(SHORT)
    for t in ("0E0B", "0E0C"):
        pg.act(lambda: pg.api("/api/exclude", {"tii": t, "excluded": True}), 2)
    res = pg.last("result")
    lc = pg.layer_counts()
    txt = pg.p.text_content("#fix")
    check("2 towers left: no fix", res["fix"] is None, res.get("why"))
    check("2 towers left: page says why", "need 3 towers" in txt, txt)
    check("2 towers left: fix layer is empty", lc["fix"] == 0, str(lc))
    check("2 towers left: 1 solid and 2 dashed hyperbolas", lc["hyper"] == 3 and lc["dashed"] == 2, str(lc))
    check("2 towers left: the chunk's old fix leaves the track", lc["track"] == 0, str(lc))
    check("2 towers left: track text is empty", pg.p.text_content("#track") == "", pg.p.text_content("#track"))
    for t in ("0E09", "0E07"):
        pg.act(lambda: pg.api("/api/exclude", {"tii": t, "excluded": True}), 2)
    res = pg.last("result")
    lc = pg.layer_counts()
    check("all excluded: no fix and no hyperbolas", res["fix"] is None and lc["hyper"] == 0 and lc["fix"] == 0,
          f"{res.get('why')} {lc}")
    pg.shot("03-all-excluded")
    pg.set_all_used()
    lc = pg.layer_counts()
    check("towers ticked again: the chunk's fix is back in the track once", lc["track"] == 1, str(lc))


def test_rapid_toggle(pg, label):
    want = {t: True for t in FOUR}
    sent = len(pg.exclude_posts)
    for t in FOUR:
        pg.click_box(t)
        want[t] = False
        pg.p.wait_for_timeout(60)
    for t in FOUR[:2]:
        pg.click_box(t)
        want[t] = True
        pg.p.wait_for_timeout(60)
    pg.settle(2000)
    if pg.p.evaluate("status.playing"):
        pg.wait_results(pg.n_events(), 1)
    srv = pg.server_excluded()
    shown = pg.boxes()
    shown4 = {t: shown[t] for t in FOUR}
    posts = pg.exclude_posts[sent:]
    check(f"{label}: rapid clicks, every click sent a request", len(posts) == 6, f"{len(posts)} of 6")
    check(f"{label}: rapid clicks, each request sent what the click meant",
          [p["excluded"] for p in posts] == [True] * 4 + [False] * 2, str([(p["tii"], p["excluded"]) for p in posts]))
    check(f"{label}: rapid clicks, server ends with the clicked state",
          {t for t, on in want.items() if not on} == srv, f"wanted off {[t for t in want if not want[t]]}, server {sorted(srv)}")
    check(f"{label}: rapid clicks, page boxes match the server",
          all(shown4[t] == (t not in srv) for t in FOUR), f"page {shown4}, server {sorted(srv)}")
    pg.set_all_used()


def test_toggle_while_playing(pg):
    pg.open(LONG)
    pg.p.click("#play")
    pg.wait_results(pg.n_events(), 2)
    check("Play advances chunks", pg.last("status")["playing"] and pg.last("status")["index"] >= 1,
          str(pg.last("status")))
    check("Play button reads Pause while playing", pg.p.text_content("#play") == "Pause")
    # Count how often the tower table is rebuilt while playing.
    pg.p.evaluate("""window.__rebuilds = 0; new MutationObserver(() => window.__rebuilds++)
        .observe(document.querySelector('#towers tbody'), { childList: true });""")
    t0 = time.time()
    n0 = pg.n_events()
    pg.p.wait_for_timeout(3000)
    rebuilds = pg.p.evaluate("window.__rebuilds")
    check("info: tower table rebuilds while playing", True,
          f"{rebuilds} rebuilds, {pg.n_events() - n0} results in {time.time() - t0:.1f} s")
    # Untick Beacon Hill North (not heard here) and Holcombe Down while playing.
    lost = 0
    for t in ("0E0C",):
        n = pg.n_events()
        pg.click_box(t)
        pg.wait_results(n, 3)
        srv = pg.server_excluded()
        shown = pg.boxes()
        check(f"playing: untick {t}, server excludes it", t in srv, str(srv))
        check(f"playing: untick {t}, box stays unticked over the next fixes", shown[t] is False,
              f"page {shown[t]}, server {sorted(srv)}")
        res = pg.last("result")
        check(f"playing: untick {t}, later fixes leave it out",
              all(r["tii"] != t or not r["used"] for r in res["towers"]))
        check(f"playing: untick {t}, no stale fix marker with 2 towers",
              pg.layer_counts()["fix"] == 0, str(pg.layer_counts()))
        pg.click_box(t)
        pg.wait_results(pg.n_events(), 2)
        srv = pg.server_excluded()
        shown = pg.boxes()
        check(f"playing: tick {t} again, page and server agree",
              shown[t] == (t not in srv), f"page {shown[t]}, server {sorted(srv)}")
    # Clicks that land just as the table is rebuilt can be lost.
    wrong = 0
    for i in range(10):
        before = pg.server_excluded()
        shown_before = pg.boxes()["0E07"]
        sent = len(pg.exclude_posts)
        pg.click_box("0E07")
        pg.p.wait_for_timeout(250)
        posts = pg.exclude_posts[sent:]
        if not posts:
            lost += 1
        elif posts[-1]["excluded"] == ("0E07" in before):
            wrong += 1     # the click asked for the state the server already had
    check("playing: every click on a box sends a request", lost == 0, f"{lost} of 10 clicks sent nothing")
    check("playing: every click flips the server state", wrong == 0,
          f"{wrong} of 10 clicks asked for the state the server already had")
    test_rapid_toggle(pg, "playing")
    pg.act(lambda: pg.p.click("#play"), 1)
    check("Pause stops playing", not pg.last("status")["playing"] and pg.p.text_content("#play") == "Play")
    pg.set_all_used()


def test_play_to_end(pg):
    pg.open(SHORT)
    pg.p.click("#play")
    end = time.time() + 30
    while time.time() < end and not (pg.last("status")["index"] == 4 and not pg.last("status")["playing"]):
        pg.p.wait_for_timeout(200)
    st = pg.last("status")
    check("Play stops by itself at the last chunk", st["index"] == 4 and not st["playing"], str(st))
    check("Play button reads Play at the end", pg.p.text_content("#play") == "Play")


def test_seek_while_playing(pg):
    for delay in (0, 150, 300, 450, 550):
        if not _seek_while_playing(pg, delay):
            break


def _seek_while_playing(pg, delay):
    pg.open(LONG)
    pg.p.click("#play")
    pg.wait_results(pg.n_events(), 3)
    # Back at different points in the worker's analyse-then-sleep cycle.
    pg.p.wait_for_timeout(delay)
    pg.p.click("#prev")
    pg.settle(2000)
    st = pg.last("status")
    res = pg.last("result")
    check(f"Back while playing ({delay} ms after a fix): last fix shown is the chunk the status names",
          res["meta"]["chunk"] == st["index"], f"status chunk {st['index'] + 1}, result chunk {res['meta']['chunk'] + 1}")
    state = pg.api("/api/state")
    return check(f"Back while playing ({delay} ms after a fix): server's last result matches its index",
                 state["last_result"]["meta"]["chunk"] == state["status"]["index"],
                 f"index {state['status']['index']}, last_result chunk {state['last_result']['meta']['chunk']}")


def test_open_while_playing(pg):
    for delay in (0, 150, 300, 450, 550):
        if not _open_while_playing(pg, delay):
            break


def _open_while_playing(pg, delay):
    pg.open(LONG)
    pg.p.click("#play")
    pg.wait_results(pg.n_events(), 2)
    pg.p.wait_for_timeout(delay)
    pg.p.select_option("#file", SHORT)
    pg.p.click("#open")
    pg.settle(2500)
    state = pg.api("/api/state")
    res = state["last_result"]
    a = check(f"Open while playing ({delay} ms after a fix): last result is from the new file",
          res["meta"]["source"] == SHORT, f"last result from {res['meta']['source']} chunk {res['meta']['chunk'] + 1}")
    b = check(f"Open while playing ({delay} ms after a fix): run holds only the new file's chunks",
          state["status"]["chunks_in_run"] == 1, f"chunks_in_run = {state['status']['chunks_in_run']}")
    shown = pg.p.text_content("#fix")
    c = check(f"Open while playing ({delay} ms after a fix): page shows the new file", SHORT in shown, shown[:80])
    return a and b and c


def test_truth_and_clear(pg):
    pg.open(SHORT)
    pg.p.click("#click-mode [data-mode=truth]")
    check("True position mode explains itself", "really is" in pg.p.text_content("#click-help"))
    pg.p.evaluate(f"map.setView([{TRUE_POS[0]}, {TRUE_POS[1]}], 15)")
    pg.p.wait_for_timeout(500)
    pt = pg.p.evaluate(f"(() => {{ const p = map.latLngToContainerPoint([{TRUE_POS[0]}, {TRUE_POS[1]}]); return [p.x, p.y]; }})()")
    pg.p.click("#map", position={"x": pt[0], "y": pt[1]})
    txt = pg.p.text_content("#truth")
    check("True position click shows the error", "Last fix error" in txt, txt)
    lc = pg.layer_counts()
    check("True position draws one marker pair", lc["truth"] == 2, str(lc))
    try:
        err = float(txt.split("Last fix error")[1].split("m")[0])
    except (IndexError, ValueError):
        err = None
    check("fix error at the desk is under 100 m", err is not None and err < 100, f"{err} m")
    pg.p.click("#map", position={"x": pt[0] + 40, "y": pt[1]})
    check("second True position click replaces the marker", pg.layer_counts()["truth"] == 2)
    pg.shot("04-truth")
    pg.p.click("#clear-track")
    check("Clear track empties the track", pg.layer_counts()["track"] == 0 and pg.p.text_content("#track") == "")
    pg.p.click("#click-mode [data-mode=none]")
    before = pg.layer_counts()["truth"]
    pg.p.click("#map", position={"x": pt[0], "y": pt[1] + 40})
    check("Nothing mode ignores map clicks", pg.layer_counts()["truth"] == before)


def test_calibrate(pg, backup):
    pg.open(SHORT)
    pg.p.click("#click-mode [data-mode=calibrate]")
    pg.p.evaluate(f"map.setView([{TRUE_POS[0]}, {TRUE_POS[1]}], 15)")
    pg.p.wait_for_timeout(500)
    pt = pg.p.evaluate(f"(() => {{ const p = map.latLngToContainerPoint([{TRUE_POS[0]}, {TRUE_POS[1]}]); return [p.x, p.y]; }})()")
    # Cancel first: nothing should change.
    pg.p.once("dialog", lambda d: d.dismiss())
    pg.p.click("#map", position={"x": pt[0], "y": pt[1]})
    pg.p.wait_for_timeout(500)
    check("Calibrate cancel leaves offsets.json alone", OFFSETS.read_text() == backup.read_text())
    pg.p.once("dialog", lambda d: d.accept("Playwright test site"))
    pg.p.click("#map", position={"x": pt[0], "y": pt[1]})
    pg.p.wait_for_function("document.querySelector('#offsets').textContent.includes('Playwright test site')",
                           timeout=15000)
    data = json.loads(OFFSETS.read_text())
    check("Calibrate writes offsets.json with the site name", data["site"] == "Playwright test site")
    check("Calibrate keeps the old file as offsets.prev.json", OFFSETS_PREV.exists())
    check("Calibrate measures 3 towers", len(data["towers"]) == 3, str(list(data["towers"])))
    check("Calibrate source names the recording", data["source"] == SHORT, data["source"])
    pg.settle()
    check("Calibrate clears the track", pg.layer_counts()["track"] == 0)
    pg.p.click("#click-mode [data-mode=none]")


def test_calibrate_revisits_and_stop(pg):
    """Calibrate over revisited chunks, after Stop, through the API."""
    pg.open(SHORT)
    for i in (1, 0, 1):
        pg.act(lambda: pg.api("/api/replay/seek", {"index": i}), 2)
    pg.act(lambda: pg.api("/api/stop", {}), 1)
    r = pg.api("/api/calibrate", {"lat": TRUE_POS[0], "lon": TRUE_POS[1], "site": "revisit test"})
    counts = {t: c["chunks"] for t, c in r["offsets"]["towers"].items()}
    check("Calibrate counts a revisited chunk once", counts and all(n == 2 for n in counts.values()),
          f"chunks per tower {counts}, want 2")
    check("Calibrate after Stop still names the recording", r["offsets"]["source"] == SHORT,
          r["offsets"]["source"])
    pg.settle()


def test_tabs_and_stop(pg):
    pg.p.click("#tab-live")
    check("Live tab shows live controls", pg.p.is_visible("#live-start") and not pg.p.is_visible("#open"))
    pg.act(lambda: pg.p.click("#live-stop"), 1)
    check("Stop returns to idle", pg.last("status")["mode"] is None and pg.last("status")["status"] == "idle")
    pg.p.click("#tab-replay")
    check("Replay tab shows replay controls", pg.p.is_visible("#open") and not pg.p.is_visible("#live-start"))
    pg.p.click("#play")
    pg.p.wait_for_timeout(500)
    check("Play with nothing open shows an error", "open a recording first" in pg.p.text_content("#status"),
          pg.p.text_content("#status"))


def test_phone(pg):
    pg.p.set_viewport_size({"width": 375, "height": 800})
    pg.p.wait_for_timeout(500)
    sw = pg.p.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    check("phone width: no horizontal scroll", sw[0] <= sw[1], f"scrollWidth {sw[0]}, clientWidth {sw[1]}")
    wide = pg.p.evaluate("""[...document.querySelectorAll('#panel *')].filter(e => e.getBoundingClientRect().right > innerWidth + 1)
        .map(e => e.tagName + (e.id ? '#' + e.id : '')).slice(0, 5)""")
    check("phone width: nothing in the panel sticks out", not wide, str(wide))
    pg.shot("05-phone")
    pg.p.set_viewport_size({"width": 1280, "height": 800})


def _dist(a, b):
    import math
    R = 6371000
    dn = math.radians(b[0] - a[0]) * R
    de = math.radians(b[1] - a[1]) * R * math.cos(math.radians(a[0]))
    return math.hypot(dn, de)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--shots", help="folder for screenshots")
    ap.add_argument("--app-js", help="serve this file as /static/app.js, to try a fix before making it")
    args = ap.parse_args()
    if args.shots:
        Path(args.shots).mkdir(parents=True, exist_ok=True)

    n_towers = len(json.loads((WEB.parent / "towers.json").read_text())["towers"])
    backup = Path(tempfile.mkdtemp()) / "offsets.json"
    shutil.copy(OFFSETS, backup)
    had_prev = OFFSETS_PREV.exists()
    log = open(Path(tempfile.gettempdir()) / "towerfix-test-server.log", "w+")
    srv = subprocess.Popen(["uv", "run", "server.py", "--port", str(args.port)], cwd=WEB,
                           stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/state", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=not args.headed)
            except Exception:  # noqa: BLE001
                browser = p.chromium.launch(headless=not args.headed, channel="chrome")
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            ctx.add_init_script(INIT_JS)
            if args.app_js:
                js = Path(args.app_js).read_text()
                ctx.route("**/static/app.js", lambda r: r.fulfill(body=js, content_type="text/javascript"))
            pg = Page(ctx.new_page(), base, args.shots)
            tests = [
                lambda: test_load(pg, n_towers),
                lambda: test_open_and_layers(pg),
                lambda: test_seek_controls(pg),
                lambda: test_toggle_paused(pg),
                lambda: test_rapid_toggle(pg, "paused"),
                lambda: test_below_three(pg),
                lambda: test_fix_jump_on_exclude(pg),
                lambda: test_toggle_while_playing(pg),
                lambda: test_play_to_end(pg),
                lambda: test_seek_while_playing(pg),
                lambda: test_open_while_playing(pg),
                lambda: test_truth_and_clear(pg),
                lambda: test_calibrate(pg, backup),
                lambda: test_calibrate_revisits_and_stop(pg),
                lambda: test_tabs_and_stop(pg),
                lambda: test_phone(pg),
            ]
            for t in tests:
                try:
                    t()
                except Exception as e:  # noqa: BLE001
                    check(f"no exception in {t.__code__.co_names[0]}", False, repr(e)[:300])
                    try:
                        pg.api("/api/replay/pause", {})
                        pg.set_all_used()
                    except Exception:  # noqa: BLE001
                        pass
            check("no console errors", not pg.console_errors, "; ".join(pg.console_errors[:5]))
            bad = [f for f in pg.failed if "/tiles/" not in f]
            tiles = [f for f in pg.failed if "/tiles/" in f]
            # A 400 from Play with nothing open is expected.
            bad = [f for f in bad if not f.startswith("400 ") or "/api/replay/play" not in f]
            check("no failed requests (tiles aside)", not bad, "; ".join(bad[:5]))
            check("info: missing tiles", True, f"{len(tiles)} tile requests failed")
            browser.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()
        shutil.copy(backup, OFFSETS)
        if not had_prev and OFFSETS_PREV.exists():
            OFFSETS_PREV.unlink()
        log.seek(0)
        server_log = log.read()
        log.close()
    tb = server_log.count("Traceback")
    check("server printed no tracebacks", tb == 0, f"{tb} tracebacks")
    if tb:
        print(server_log[server_log.find("Traceback"):][:2000])
    fails = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
