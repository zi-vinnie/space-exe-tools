"""Cache OpenStreetMap tiles for the Exeter area, for offline use.

Usage (from towerfix/web):  uv run fetch_tiles.py [--count-only]

Follows the OSM tile usage policy (operations.osmfoundation.org/policies/tiles):
a small area, zoom 16 at most, one request at a time with a pause between
them, a User-Agent that names the tool, and tiles that are already on disk
are never fetched again. Tiles go to web/tiles/{z}/{x}/{y}.png, which git
ignores. The map must show "© OpenStreetMap contributors".
"""

import argparse
import math
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "tiles"
URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "towerfix-tile-cache/0.1"
PAUSE_S = 0.5

# Every tower in towers.json, with a margin of about 5 km.
AREA = {"south": 50.40, "north": 50.95, "west": -3.70, "east": -3.00, "zooms": range(0, 14)}
# About 3 km round Exeter city centre, which takes in the Streatham campus.
CENTRE = {"south": 50.696, "north": 50.751, "west": -3.570, "east": -3.485, "zooms": range(14, 17)}


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tiles(box):
    for z in box["zooms"]:
        x0, y0 = tile_xy(box["north"], box["west"], z)
        x1, y1 = tile_xy(box["south"], box["east"], z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield z, x, y


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count-only", action="store_true")
    args = ap.parse_args()
    todo = sorted(set(tiles(AREA)) | set(tiles(CENTRE)))
    print(f"{len(todo)} tiles in the area")
    if args.count_only:
        return
    fetched = skipped = failed = 0
    for z, x, y in todo:
        path = OUT / str(z) / str(x) / f"{y}.png"
        if path.exists():
            skipped += 1
            continue
        req = urllib.request.Request(URL.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  failed {z}/{x}/{y}: {e}")
            if failed > 20:
                print("Too many failures, stopping.")
                break
            time.sleep(5)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        fetched += 1
        if fetched % 100 == 0:
            print(f"  {fetched} fetched")
        time.sleep(PAUSE_S)
    print(f"Fetched {fetched}, already cached {skipped}, failed {failed}")


if __name__ == "__main__":
    main()
