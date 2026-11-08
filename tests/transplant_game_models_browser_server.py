"""Disposable native Android/iOS catalogs for transplant picker browser QA.

The original generated rig fixture is never changed. A separate generated iOS
container changes its serialized-file target only; object and texture payloads
stay untouched. No product pack, user database, or original costume is used.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import UnityPy
from UnityPy.enums import BuildTarget
from test_game_models import GameModelTests, extractor
from test_model_viewer import unity_bundle
from webtools.server import Handler


original_index = extractor.build_pack_index
original_roots = extractor.build_pack_roots
fixture = GameModelTests("test_catalog_region_language_search_and_exact_suit_identity")
fixture.setUp()
extractor.build_pack_index = original_index
extractor.build_pack_roots = original_roots
extractor.COPIED_PACKS_DIR = str(fixture.packs)
os.environ["LLAS_INDEX_CACHE_DIR"] = str(fixture.root / ".pack-index")

environment = UnityPy.load(fixture.payload)
before_objects = {obj.path_id: hashlib.sha256(obj.get_raw_data()).hexdigest() for obj in environment.objects}
assert all(int(asset.target_platform) == 13 for asset in environment.assets)
for asset in environment.assets:
    asset.target_platform = BuildTarget.iOS
    # UnityPy's writer serializes this original numeric metadata field; the
    # public enum attribute alone is read-time convenience, not a save setter.
    asset._m_target_platform = int(BuildTarget.iOS)
ios_raw = environment.file.save(packer="none")
android_payload = unity_bundle([("CAB-original-transplant-rig", fixture.payload)])
ios_payload = unity_bundle([("CAB-original-transplant-rig", ios_raw)])
saved = UnityPy.load(ios_payload)
assert all(int(asset.target_platform) == 9 for asset in saved.assets)
assert {obj.path_id: hashlib.sha256(obj.get_raw_data()).hexdigest() for obj in saved.objects} == before_objects
assert {obj.path_id: hashlib.sha256(obj.get_raw_data()).hexdigest() for obj in UnityPy.load(android_payload).objects} == before_objects
android_encrypted = bytearray(android_payload)
extractor.decrypt_section(android_encrypted, extractor.FIXED_KEY0, 7, 11)
ios_encrypted = bytearray(ios_payload)
extractor.decrypt_section(ios_encrypted, extractor.FIXED_KEY0, 7, 11)
for region in ("gl", "jp"):
    directory = fixture.root / "assets/db" / region
    locale = "ko" if region == "gl" else "ja"
    android = directory / f"asset_a_{locale}.db"
    ios = directory / f"asset_i_{locale}.db"
    with sqlite3.connect(android) as database:
        database.execute("UPDATE member_model SET size=?", (len(android_encrypted),))
        database.execute("UPDATE m_asset_package_mapping SET file_size=?", (len(android_encrypted),))
    shutil.copyfile(android, ios)
    with sqlite3.connect(ios) as database:
        database.execute("UPDATE member_model SET pack_name=pack_name || '_ios', size=?", (len(ios_encrypted),))
        database.execute("UPDATE m_asset_package_mapping SET pack_name=pack_name || '_ios', file_size=?", (len(ios_encrypted),))
for name in ("basepack", "maskpack", "barepack", "colourpack"):
    (fixture.packs / name).write_bytes(android_encrypted)
    (fixture.packs / (name + "_ios")).write_bytes(ios_encrypted)
(fixture.library / "modded").mkdir(parents=True)

os.chdir(fixture.root)
server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(json.dumps({
    "url": "http://127.0.0.1:" + str(server.server_port),
    "root": str(fixture.root), "library": str(fixture.library),
    "android_sha256": hashlib.sha256(android_payload).hexdigest(),
    "ios_sha256": hashlib.sha256(ios_payload).hexdigest(),
    "source_objects_unchanged": True,
}), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    fixture.doCleanups()
