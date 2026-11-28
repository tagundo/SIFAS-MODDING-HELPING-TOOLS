"""A disposable Elichika-like root for the apply-to-game browser test.

Builds the synthetic GL databases of tests/test_mv_studio_register.py in a temporary folder, registers
a stand-in app server controller (the jobs stop and restart "the game server" without touching any
real process) and serves the WebUI from that root. Native timelines are the registration tests' JSON
stand-ins: their parse, export, native rewrite, stock loads and the store's validator are replaced in
this process only. Prints one JSON line {url, base, root, library, controllerLog, nativeProject} and
serves until killed; the caller deletes ``base``. Needs the Elichika server app (ELICHIKA_DIR).
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
if os.environ.get("ELICHIKA_DIR"):
    sys.path.append(os.environ["ELICHIKA_DIR"])

from http.server import ThreadingHTTPServer  # noqa: E402

from mv_studio_register_browser_server import Controller, stand_in_timelines  # noqa: E402
from test_mv_studio_apply import fake_rewrite  # noqa: E402
from test_mv_studio_register import base_tracks, build_root  # noqa: E402


def native_project(stock):
    """A game import of stock MV 21 / asset 2101 (Android) as the game plays it: the stock timeline."""
    from webtools.core import mv_studio
    project = mv_studio._blank("Native sample", {"kind": "game", "region": "gl", "platform": "android", "liveId": 21,
                                                 "assetId": 2101, "mvOnly": False, "registered": False,
                                                 "timelineKey": "A2101"})
    project["tracks"] = copy.deepcopy(base_tracks())
    project["duration"] = 4.0
    return mv_studio._register(project, stock["tl2101"])


def main():
    base = Path(tempfile.mkdtemp(prefix="mv-apply-browser-"))
    root = build_root(base / "root")
    library = base / "library"
    (library / "modded").mkdir(parents=True)
    os.environ.update(SUKUSTA_DIR=str(library), SUKUSTA_BACKUP_ROOT=str(base / "backups"),
                      LLAS_INDEX_CACHE_DIR=str(base / "pack-index"))
    from adminui import serverctl
    log = base / "controller.log"
    serverctl.register_controller(Controller(log))
    from webtools.core import mv_studio_timeline
    from webtools.server import Handler
    import mimetypes
    mimetypes.add_type("application/javascript", ".js")
    os.chdir(root)
    stock = stand_in_timelines()
    mv_studio_timeline._rewrite_timeline = fake_rewrite
    mv_studio_timeline.prepare_tracks = lambda raw, name, tracks, original, **options: tracks
    project = native_project(stock)
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
