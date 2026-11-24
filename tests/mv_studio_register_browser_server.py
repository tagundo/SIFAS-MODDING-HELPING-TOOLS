"""A disposable Elichika-like root for the MV-only registration browser test.

Builds the synthetic GL databases of tests/test_mv_studio_register.py in a temporary folder,
registers a stand-in app server controller (so the jobs stop and restart "the game server"
without touching any real process) and serves the WebUI from that root. Native timelines are
the test module's JSON stand-ins: their parse, export, stock loads and the store's validator
are replaced in this process only. Prints one JSON line {url, base, root, library,
controllerLog, nativeProject} and serves until killed; the caller deletes ``base``.
Needs the Elichika server app on PYTHONPATH (ELICHIKA_DIR is added when set).
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
if os.environ.get("ELICHIKA_DIR"):
    sys.path.append(os.environ["ELICHIKA_DIR"])

from http.server import ThreadingHTTPServer  # noqa: E402

from test_mv_studio_register import (base_tracks, build_root, fake_export, fake_parse, stage_chart,  # noqa: E402
                                     timeline_bytes, wav_bytes)


def stand_in_timelines():
    """JSON stand-in timelines for the synthetic root: stock packs tl2101 (Android) and tl2101i (iOS)."""
    import mv_studio_native_assets as native
    from webtools.core import mv_studio_register as register, mv_studio_timeline
    stock = {"tl2101": timeline_bytes("android"), "tl2101i": timeline_bytes("ios"),
             "tl2201": timeline_bytes("android", tag="other"), "tl2201i": timeline_bytes("ios", tag="other")}
    register._load = lambda repo_root, descriptor, *, download, deadline=None: stock.get(descriptor["pack_name"])
    register._blob_platform = lambda raw: json.loads(raw[8:].rstrip(b" "))["platform"]
    mv_studio_timeline.parse_timeline = fake_parse
    mv_studio_timeline.export_timeline = fake_export
    native._stock_timeline = lambda repo_root, row, physical, deadline: stock.get(row["pack_name"])
    native._validate_timeline = lambda raw, original, platform, deadline: None
    return stock


def native_project(stock):
    """A game import of base MV 21 (Android) with its stand-in native timeline."""
    from webtools.core import mv_studio
    project = mv_studio._blank("Native sample", {"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                                 "assetId": 2101, "mvOnly": False, "registered": False})
    project["tracks"] = copy.deepcopy(base_tracks())
    project["duration"] = 4.0
    # A 10 s soundtrack imported the way mp3/ogg/m4a/flac are: no recorded duration (the page measures it).
    project["soundtrack"] = {"offset": 0, "url": mv_studio._media(wav_bytes(441000), "wav")}
    return mv_studio._register(project, stock["tl2101"])


class Controller:
    """The Android/macOS app's server controller, as adminui.serverctl drives it; records every call."""

    def __init__(self, log):
        self.running, self.log, self.lock = True, log, threading.Lock()

    def _note(self, name):
        with self.lock, open(self.log, "a", encoding="utf-8") as stream:
            stream.write(name + "\n")

    def is_running(self):
        return self.running

    def stop(self):
        self._note("stop")
        self.running = False
        return True

    def start(self):
        self._note("start")
        self.running = True
        return True

    def restart_is_pending(self):
        return False

    def finish(self):
        self._note("finish")

    def begin_job(self):
        self._note("begin_job")
        return True

    def finish_job(self, successful):
        self._note("finish_job:" + ("ok" if successful else "failed"))
        return True


def main():
    base = Path(tempfile.mkdtemp(prefix="mv-register-browser-"))
    root = build_root(base / "root")
    library = base / "library"
    (library / "modded").mkdir(parents=True)
    from PIL import Image
    wide = Image.new("RGB", (600, 400), (30, 60, 120))
    for x in range(600):
        for y in range(0, 400, 40):
            wide.putpixel((x, y), (255, 200, 40))
    wide.save(library / "modded" / "jacket-wide.png")
    chart = stage_chart(1)
    del chart["live_difficulty_id"]
    (library / "modded" / "advanced-chart.json").write_text(json.dumps(chart), encoding="utf-8")
    os.environ.update(SUKUSTA_DIR=str(library), SUKUSTA_BACKUP_ROOT=str(base / "backups"),
                      LLAS_INDEX_CACHE_DIR=str(base / "pack-index"))
    from adminui import serverctl
    log = base / "controller.log"
    serverctl.register_controller(Controller(log))
    from webtools.server import Handler
    import mimetypes
    mimetypes.add_type("application/javascript", ".js")
    os.chdir(root)
    project = native_project(stand_in_timelines())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    print(json.dumps({"url": "http://127.0.0.1:" + str(server.server_port), "base": str(base), "root": str(root),
                      "library": str(library), "controllerLog": str(log), "nativeProject": project}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
