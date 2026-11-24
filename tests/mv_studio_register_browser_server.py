"""A disposable Elichika-like root for the MV-only registration browser test.

Builds the synthetic GL databases of tests/test_mv_studio_register.py in a temporary folder,
registers a stand-in app server controller (so the jobs stop and restart "the game server"
without touching any real process) and serves the WebUI from that root. Prints one JSON line
{url, root, library} and serves until killed; the caller deletes ``root`` and ``library``.
Needs the Elichika server app on PYTHONPATH (ELICHIKA_DIR is added when set).
"""
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

from test_mv_studio_register import build_root, stage_chart  # noqa: E402


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
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    print(json.dumps({"url": "http://127.0.0.1:" + str(server.server_port), "base": str(base), "root": str(root),
                      "library": str(library), "controllerLog": str(log)}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
