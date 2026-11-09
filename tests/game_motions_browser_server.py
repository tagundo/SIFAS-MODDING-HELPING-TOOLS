"""Isolated encrypted original motion fixture for the real browser import flow."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from test_game_motions import GameMotionTests, extractor
from webtools.server import Handler
import UnityPy

original_index, original_roots = extractor.indexed_pack_file, extractor.build_pack_roots
fixture = GameMotionTests("test_categories_use_actual_relations_and_date_windows")
fixture.setUp()
extractor.indexed_pack_file, extractor.build_pack_roots = original_index, original_roots
extractor.COPIED_PACKS_DIR = str(fixture.packs)
os.environ["SUKUSTA_DIR"] = str(fixture.root / "library")
os.environ["LLAS_INDEX_CACHE_DIR"] = str(fixture.root / ".pack-index")

env = UnityPy.load((Path(__file__).parent / "fixtures/viewer_persistence.unity").read_bytes())
for obj in list(env.objects):
    if obj.type.name != "AnimationClip":
        del obj.assets_file.objects[obj.path_id]
    else:
        tree = obj.read_typetree()
        tree["m_Name"] = "Imported motion fixture"
        obj.save_typetree(tree)
plain = env.file.save()
encrypted = bytearray(plain)
extractor.decrypt_section(encrypted, extractor.FIXED_KEY0, 7, 11)
for path in fixture.packs.iterdir():
    path.write_bytes(encrypted)
with sqlite3.connect(fixture.assets) as db:
    db.execute("UPDATE navi_motion SET size=?", (len(encrypted),))
    db.execute("UPDATE live_timeline SET size=?", (len(encrypted),))
    db.execute("UPDATE m_asset_package_mapping SET file_size=?", (len(encrypted),))
model = fixture.root / "library/extracted/model.unity"
model.parent.mkdir(parents=True, exist_ok=True)
model.write_bytes((Path(__file__).parent / "fixtures/viewer_persistence.unity").read_bytes())
alternate = model.parent / "alternate-motion.unity"
alternate.write_bytes(plain)
replacement = model.parent / "replacement-model.unity"
replacement.write_bytes(model.read_bytes())
os.chdir(fixture.root)
server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(json.dumps({"url": "http://127.0.0.1:" + str(server.server_port), "root": str(fixture.root), "model": str(model), "alternate": str(alternate), "replacement": str(replacement), "motion_sha256": hashlib.sha256(plain).hexdigest()}), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    fixture.doCleanups()
