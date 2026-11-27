"""A disposable Elichika-like root for the "another MV slot" browser test (mv_studio_crossslot_browser.js).

The apply test's synthetic GL root (tests/mv_studio_apply_browser_server.py) with the cross-slot store of
tests/test_mv_crossslot.py (FakeStore: apply_mv_timeline with source_asset_id and stage) and a stand-in
mv_timeline_pack, so the panel's choices run end to end against the real modtools server without the
Elichika lane. Prints one JSON line {url, base, root, library, controllerLog, nativeProject} and serves
until killed; the caller deletes ``base``. Needs the Elichika server app (ELICHIKA_DIR) for KEEP and the
database guard.
"""
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

from mv_studio_apply_browser_server import native_project  # noqa: E402
from mv_studio_register_browser_server import Controller, stand_in_timelines  # noqa: E402
from test_mv_crossslot import FakeStore, fake_pack_module  # noqa: E402
from test_mv_studio_apply import fake_rewrite  # noqa: E402
from test_mv_studio_register import build_root  # noqa: E402


def main():
    base = Path(tempfile.mkdtemp(prefix="mv-crossslot-browser-"))
    root = build_root(base / "root")
    library = base / "library"
    (library / "modded").mkdir(parents=True)
    os.environ.update(SUKUSTA_DIR=str(library), SUKUSTA_BACKUP_ROOT=str(base / "backups"),
                      LLAS_INDEX_CACHE_DIR=str(base / "pack-index"))
    from adminui import serverctl
    log = base / "controller.log"
    serverctl.register_controller(Controller(log))
    from webtools.core import mv_studio_register as register, mv_studio_timeline
    from webtools.server import Handler
    import mimetypes
    mimetypes.add_type("application/javascript", ".js")
    os.chdir(root)
    stock = stand_in_timelines()
    mv_studio_timeline._rewrite_timeline = fake_rewrite
    mv_studio_timeline.prepare_tracks = lambda raw, name, tracks, original, **options: tracks
    store = FakeStore()
    register.store = lambda: store
    sys.modules["mv_timeline_pack"] = fake_pack_module([])
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
