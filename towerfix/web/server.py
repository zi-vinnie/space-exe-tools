"""Local web server for the TowerFix map.

Usage (from towerfix/web):  uv run server.py [--port 8765]
Then open http://127.0.0.1:8765/ in a browser.

It replays .cu8 recordings from ../recordings in chunks, or reads a live
RTL-SDR through rtl_sdr, and sends one fix per chunk to the page over
server-sent events (/api/events). It only listens on 127.0.0.1.
"""

import argparse
import json
import queue
import shutil
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from towerfix.fix import Solver, load_offsets, load_towers, save_offsets  # noqa: E402
from towerfix.stream import FileChunks, LiveChunks  # noqa: E402
from towerfix.timing import measure  # noqa: E402

STATIC = HERE / "static"
TILES = HERE / "tiles"
RECORDINGS = ROOT / "recordings"
TOWERS_JSON = ROOT / "towers.json"
OFFSETS_JSON = HERE / "offsets.json"
PLAY_PAUSE_S = 0.4      # gap between chunks when playing a recording
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".png": "image/png", ".json": "application/json"}


class App:
    def __init__(self):
        self.lock = threading.RLock()
        self.solver = Solver(load_towers(TOWERS_JSON))
        self.offsets = load_offsets(OFFSETS_JSON)
        self.excluded = set()
        self.clients = []
        self.mode = None            # "replay" or "live"
        self.chunks = None          # FileChunks
        self.live = None            # LiveChunks
        self.index = 0
        self.playing = False
        self.history = {}           # {chunk: measurement} from this run, for calibration
        self.run_source = None      # recording name, or "live", for offsets.json
        self.last_measurement = None
        self.last_meta = None
        self.last_result = None
        self.prior = None           # last unambiguous fix, picks between crossings
        self.last_fix = None        # last fix of any kind, used when there's no prior
        self.status = "idle"
        self.error = None
        # Bumped whenever a chunk being analysed stops being wanted (Open,
        # Start, Stop, a seek). A result whose generation changed while it
        # was analysed is dropped.
        self.gen = 0
        self.wake = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    # Events -------------------------------------------------------------------

    def subscribe(self):
        q = queue.Queue(maxsize=50)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def broadcast(self, kind, data):
        msg = f"event: {kind}\ndata: {json.dumps(data)}\n\n"
        with self.lock:
            for q in list(self.clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def status_dict(self):
        with self.lock:
            d = {"mode": self.mode, "status": self.status, "error": self.error,
                 "playing": self.playing, "excluded": sorted(self.excluded),
                 "chunks_in_run": len(self.history)}
            if self.chunks is not None and self.mode == "replay":
                d.update({"file": self.chunks.path.name, "index": self.index,
                          "count": self.chunks.count,
                          "chunk_s": round(self.chunks.frames * 0.096, 2)})
            if self.mode == "live" and self.live is not None:
                d.update({"chunk_s": round(self.live.frames * 0.096, 2)})
            return d

    def send_status(self):
        # Under the lock, so two status messages can't overtake each other.
        with self.lock:
            self.broadcast("status", self.status_dict())

    # Sources ------------------------------------------------------------------

    def stop_source(self):
        # Detach the live source under the lock, then close it outside, so
        # waiting for rtl_sdr to exit doesn't hold up other requests.
        with self.lock:
            self.gen += 1
            self.playing = False
            live, self.live = self.live, None
            self.mode = None
            self.status = "idle"
        if live is not None:
            live.close()

    def open_replay(self, name, seconds):
        path = (RECORDINGS / name).resolve()
        if path.parent != RECORDINGS.resolve() or path.suffix != ".cu8" or not path.exists():
            raise ValueError("no such recording")
        self.stop_source()
        with self.lock:
            self.chunks = FileChunks(path, seconds)
            self.mode = "replay"
            self.index = 0
            self.reset_run()
            self.run_source = path.name
            self.status = "ready"
            gen = self.gen
        self.process_replay(0, gen)

    def seek(self, i):
        with self.lock:
            self.playing = False
            self.gen += 1
            gen = self.gen
        self.process_replay(i, gen)

    def reset_run(self):
        with self.lock:
            self.gen += 1
            self.history = {}
            self.prior = self.last_fix = None
            self.last_measurement = self.last_result = None

    def process_replay(self, i, gen):
        """Analyse chunk i. `gen` is the generation the caller decided under."""
        with self.lock:
            if self.mode != "replay" or self.chunks is None or self.gen != gen:
                return
            i = max(0, min(i, self.chunks.count - 1))
            self.index = i
            chunks = self.chunks
            self.status = "working"
        self.send_status()
        raw = chunks.read(i)
        meta = {"source": chunks.path.name, "chunk": i, "count": chunks.count,
                "t_s": round(chunks.seconds_at(i), 1)}
        self.handle(raw, meta, gen)
        with self.lock:
            if self.mode == "replay" and self.gen == gen:
                self.status = "ready"
            self.send_status()

    def start_live(self, gain, seconds):
        if shutil.which("rtl_sdr") is None:
            raise ValueError("rtl_sdr is not installed")
        self.stop_source()
        with self.lock:
            self.live = LiveChunks(seconds, gain)
            self.mode = "live"
            self.reset_run()
            self.run_source = "live"
            self.status = "listening"
            self.wake.set()
        self.send_status()

    # Work ---------------------------------------------------------------------

    def handle(self, raw, meta, gen):
        try:
            m = measure(raw)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            with self.lock:
                if self.gen == gen:
                    self.error = f"analysis failed: {e}"
                    self.send_status()
            return
        m.pop("peaks", None)
        meta.update({"frames": m["frames"], "frequency_offset_hz": m["frequency_offset_hz"],
                     "timing_jumps": len(m["timing_jumps"]), "time": time.strftime("%H:%M:%S")})
        with self.lock:
            if self.gen != gen:
                return      # Open, Start, Stop or a seek came in meanwhile
            self.error = None
            # Keyed by chunk, so going back to a chunk replaces it.
            self.history[meta["chunk"]] = m
            self.last_measurement, self.last_meta = m, meta
            self.solve_and_send()

    def solve_and_send(self):
        # Solve and send under one hold of the lock, so results go out in
        # the order they were recorded.
        with self.lock:
            m, meta = self.last_measurement, self.last_meta
            if m is None:
                return
            res = self.solver.solve(m, self.offsets, self.excluded, self.prior or self.last_fix)
            if res["fix"] is not None:
                self.last_fix = (res["fix"]["lat"], res["fix"]["lon"])
                if not res["ambiguous"]:
                    self.prior = self.last_fix
            heard_other = [{"comb_hex": r["comb_hex"], "tower": r["tower"], "score_db": r["score_db"]}
                           for r in m["towers"] if r["score_db"] >= 3.0
                           and f"0E{r['comb_hex']}" not in self.solver.towers]
            res.update({"meta": meta, "other_tii": heard_other})
            self.last_result = res
            self.broadcast("result", res)

    def _worker(self):
        while True:
            self.wake.wait(timeout=0.5)
            self.wake.clear()
            while True:
                with self.lock:
                    mode, playing, live, gen = self.mode, self.playing, self.live, self.gen
                    nxt = self.index + 1
                    if mode == "replay" and playing and nxt >= self.chunks.count:
                        self.playing = False
                        self.send_status()
                        break
                if mode == "replay" and playing:
                    self.process_replay(nxt, gen)
                    time.sleep(PLAY_PAUSE_S)
                elif mode == "live" and live is not None:
                    raw = live.next(timeout=15)
                    if raw is None:
                        dead = None
                        with self.lock:
                            if self.live is live:
                                self.error = live.error or "no samples from rtl_sdr"
                                if live.error:
                                    dead = live
                                    self.live, self.mode, self.status = None, None, "idle"
                        if dead is not None:
                            dead.close()
                        self.send_status()
                        continue
                    with self.lock:
                        if self.live is not live:
                            continue
                        n = len(self.history)
                    self.handle(raw, {"source": "live", "chunk": n, "count": None,
                                      "t_s": None}, gen)
                else:
                    break

    # Calibration --------------------------------------------------------------

    def calibrate(self, lat, lon, site):
        with self.lock:
            ms = list(self.history.values())
            source = self.run_source
        if not ms:
            raise ValueError("no chunks analysed yet in this run")
        cal = self.solver.calibrate(ms, lat, lon)
        if not cal:
            raise ValueError("no tower matched a peak along with St Thomas")
        if OFFSETS_JSON.exists():
            shutil.copy(OFFSETS_JSON, HERE / "offsets.prev.json")
        save_offsets(OFFSETS_JSON, cal, lat, lon, site, source)
        with self.lock:
            self.offsets = load_offsets(OFFSETS_JSON)
            self.prior = None
        self.solve_and_send()
        return cal

    def state(self):
        with self.lock:
            offsets_file = json.loads(OFFSETS_JSON.read_text()) if OFFSETS_JSON.exists() else None
            return {
                "towers": list(self.solver.towers.values()),
                "reference": "0E09",
                "offsets": offsets_file,
                "recordings": sorted(p.name for p in RECORDINGS.glob("*.cu8")),
                "status": self.status_dict(),
                "last_result": self.last_result,
                "tile_max_zoom": max((int(p.name) for p in TILES.iterdir() if p.name.isdigit()),
                                     default=0) if TILES.exists() else 0,
            }


APP = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if not self.path.startswith("/tiles/"):
            sys.stderr.write("%s\n" % (fmt % args))

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        if path.suffix == ".png":
            self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self._file(STATIC / "index.html")
        if p.startswith("/static/") or p.startswith("/tiles/"):
            base = STATIC if p.startswith("/static/") else TILES
            rel = p.split("/", 2)[2]
            target = (base / rel).resolve()
            if not str(target).startswith(str(base.resolve())):
                return self.send_error(404)
            return self._file(target)
        if p == "/api/state":
            return self._json(APP.state())
        if p == "/api/events":
            return self._events()
        self.send_error(404)

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = APP.subscribe()
        try:
            self.wfile.write(f"event: status\ndata: {json.dumps(APP.status_dict())}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    msg = ": keep-alive\n\n"
                self.wfile.write(msg.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            APP.unsubscribe(q)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad JSON"}, 400)
        p = self.path
        try:
            if p == "/api/replay/open":
                APP.open_replay(body["file"], float(body.get("seconds", 5)))
            elif p == "/api/replay/seek":
                APP.seek(int(body["index"]))
            elif p == "/api/replay/play":
                with APP.lock:
                    if APP.mode != "replay":
                        raise ValueError("open a recording first")
                    APP.playing = True
                APP.wake.set()
                APP.send_status()
            elif p == "/api/replay/pause":
                with APP.lock:
                    APP.playing = False
                APP.send_status()
            elif p == "/api/live/start":
                APP.start_live(float(body.get("gain", 20)), float(body.get("seconds", 5)))
            elif p == "/api/stop":
                APP.stop_source()
                APP.send_status()
            elif p == "/api/exclude":
                with APP.lock:
                    if body.get("excluded"):
                        APP.excluded.add(body["tii"])
                    else:
                        APP.excluded.discard(body["tii"])
                APP.send_status()
                APP.solve_and_send()
            elif p == "/api/calibrate":
                cal = APP.calibrate(float(body["lat"]), float(body["lon"]), body.get("site", ""))
                return self._json({"ok": True, "towers": cal,
                                   "offsets": json.loads(OFFSETS_JSON.read_text())})
            else:
                return self._json({"error": "not found"}, 404)
        except (KeyError, ValueError) as e:
            return self._json({"error": str(e)}, 400)
        return self._json({"ok": True, "status": APP.status_dict()})


def main():
    global APP
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    APP = App()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.daemon_threads = True
    print(f"TowerFix map on http://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        APP.stop_source()
        srv.server_close()


if __name__ == "__main__":
    main()
