"""Outline-editable member faces survive every round trip, on a real costume.

Set ELICHIKA_ROOT to an Elichika checkout with the GL Android catalogs and the
selected costume's packs; its databases and packs are only read. A disposable
runtime holds just the rows and packs this costume needs, and the real viewer
HTTP routes open, edit, save, package and reopen it. "Adding it to the game"
reproduces what costume_face_installer.prepare_package writes for a generated
Face/Mouth costume: the same second private face-graph isolation, a fresh suit
whose body depends on its private face instead of the stock face, and packs
with the fixed installer key. No game data is committed.
"""
from collections import OrderedDict
from contextlib import closing
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import uuid
import zipfile

_ROOT = os.environ.get("ELICHIKA_ROOT")
SUIT = int(os.environ.get("SIFAS_OUTLINE_ROUNDTRIP_SUIT", "402032004"))
INSTALLED_SUIT = 990000001
# The face prefab meshes whose placeholder material the game replaces with
# BodyPartManager.headMaterial at runtime (Face itself lives on the body).
FACE_PREFAB = {"Mouth", "Eye", "Eye_Around", "RightEyeWhiteLine", "LeftEyeWhiteLine"}


def _available():
    return bool(_ROOT) and all(Path(_ROOT, name).is_file() for name in (
        "llas_asset_extractor.py", "costume_installer_defaults.py",
        "assets/db/gl/masterdata.db", "assets/db/gl/asset_a_en.db"))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@unittest.skipUnless(_available(), "Set ELICHIKA_ROOT to an Elichika checkout with the GL Android catalogs and packs")
class OutlineFaceRoundTripTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, _ROOT)
        self.addCleanup(sys.path.remove, _ROOT)
        import llas_asset_extractor
        self.extractor = llas_asset_extractor
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.runtime, self.library = self.root / "runtime", self.root / "library"
        (self.runtime / "static").mkdir(parents=True)
        self.library.mkdir()
        self.member = self.copy_catalogs()
        from webtools.core import viewer_mod_sources
        patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()).start()
        patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)}).start()
        self.addCleanup(patch.stopall)
        cwd = os.getcwd()
        os.chdir(self.runtime)
        self.addCleanup(os.chdir, cwd)
        from webtools.server import Handler
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"

    # ---- disposable runtime with only this costume's catalog rows and packs
    def copy_catalogs(self):
        source = Path(_ROOT) / "assets" / "db" / "gl"
        target = self.runtime / "assets" / "db" / "gl"
        target.mkdir(parents=True)

        def copy(old, new, table, where="", parameters=()):
            schema = old.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if schema is None:
                return []
            new.execute(schema[0])
            rows = old.execute(f'SELECT * FROM "{table}"' + (" WHERE " + where if where else ""), parameters).fetchall() if where else []
            if rows:
                new.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in rows[0])})', rows)
            return rows

        with closing(sqlite3.connect((source / "masterdata.db").resolve().as_uri() + "?mode=ro", uri=True)) as old, \
                closing(sqlite3.connect(target / "masterdata.db")) as new:
            row = old.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (SUIT,)).fetchone()
            if row is None:
                self.skipTest("The selected costume is missing from this Elichika catalog")
            member, model = row
            initial = old.execute("SELECT suit_m_id FROM m_member_init WHERE member_m_id=?", (member,)).fetchone()
            suits = [SUIT] + ([initial[0]] if initial and initial[0] != SUIT else [])
            copy(old, new, "m_suit", f"id IN ({','.join('?' for _ in suits)})", suits)
            copy(old, new, "m_member_init", "member_m_id=?", (member,))
            if copy(old, new, "m_suit_attach", "suit_master_id=?", (SUIT,)):
                self.skipTest("Choose a costume without a colour attachment")
            copy(old, new, "m_suit_view", "suit_master_id=?", (SUIT,))
            models = [value for (value,) in new.execute("SELECT model_asset_path FROM m_suit")]
            new.commit()
        with closing(sqlite3.connect((source / "asset_a_en.db").resolve().as_uri() + "?mode=ro", uri=True)) as old, \
                closing(sqlite3.connect(target / "asset_a_en.db")) as new:
            marks = ",".join("?" for _ in models)
            dependencies = copy(old, new, "member_model_dependency", f"asset_path IN ({marks})", models)
            assets = list(dict.fromkeys(models + [row[1] for row in dependencies]))
            rows = copy(old, new, "member_model", f"asset_path IN ({','.join('?' for _ in assets)})", assets)
            packs = sorted({row[1] for row in rows})
            copy(old, new, "m_asset_package_mapping", f"pack_name IN ({','.join('?' for _ in packs)})", packs)
            new.commit()
        for pack in packs:
            original = Path(_ROOT) / "static" / pack
            if original.is_file():
                shutil.copyfile(original, self.runtime / "static" / pack)
        self.stock_model = model
        if not (self.runtime / "static" / dict((row[0], row[1]) for row in rows)[model]).is_file():
            self.skipTest("The selected costume's pack is not available locally")
        return member

    def install(self, package):
        """costume_face_installer.prepare_package's catalog and pack effects."""
        from costume_installer_defaults import DEPENDENCIES
        from webtools.core import viewer_mod_package
        execution = self.root / ("install-" + uuid.uuid4().hex)
        execution.mkdir()
        copy = execution / "package.zip"
        shutil.copyfile(package, copy)
        # "Producer file names are not a trust boundary": the installer
        # rebases the whole body/face graph once more for this installation.
        viewer_mod_package._isolate_face_graph(copy, execution, lambda: False)
        with zipfile.ZipFile(copy) as archive:
            fields, _ = viewer_mod_package._manifest(archive.read("modinstall.txt"), "Face costume")
            files = {"C": archive.read(fields["costume_file"]), "F": archive.read(fields["costume_facedynamic_file"])}
        roles = {role: "face" + uuid.uuid4().hex for role in files}
        catalog = self.runtime / "assets" / "db" / "gl"
        with closing(sqlite3.connect(catalog / "asset_a_en.db")) as db:
            for role, raw in files.items():
                encoded = bytearray(raw)
                self.extractor.decrypt_section(encoded, self.extractor.FIXED_KEY0, 0, 0)
                pack = "installed" + role.lower() + uuid.uuid4().hex[:12]
                (self.runtime / "static" / pack).write_bytes(encoded)
                db.execute("INSERT INTO member_model(asset_path,pack_name,head,size,key1,key2) VALUES(?,?,0,?,0,0)",
                           (roles[role], pack, len(encoded)))
                db.execute("INSERT INTO m_asset_package_mapping(package_key,pack_name,file_size,metapack_name,metapack_offset,category) "
                           "VALUES(?,?,?,NULL,0,3)", ("suit:" + str(INSTALLED_SUIT), pack, len(encoded)))
            edges = {(roles["C"], roles["F"] if kind == "face_or" else value)
                     for kind, _, value in DEPENDENCIES[self.member]}
            db.executemany("INSERT INTO member_model_dependency(asset_path,dependency) VALUES(?,?)", sorted(edges))
            db.commit()
        with closing(sqlite3.connect(catalog / "masterdata.db")) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(m_suit)")]
            row = dict(zip(columns, db.execute("SELECT * FROM m_suit WHERE id=?", (SUIT,)).fetchone()))
            row.update(id=INSTALLED_SUIT, model_asset_path=roles["C"])
            db.execute(f"INSERT INTO m_suit({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
            db.commit()
        return files

    # ---- the real viewer routes
    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method="GET" if body is None else "POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def job(self, job_id):
        from webtools.jobs import MANAGER
        job, deadline = MANAGER.get(job_id), time.monotonic() + 600
        while not job.is_done:
            self.assertLess(time.monotonic(), deadline, "The viewer job did not finish")
            time.sleep(.2)
        return job

    def game_import(self, suit):
        status, data = self.call("/api/viewer/game/import", {"region": "gl", "suit": f"suit:{suit}", "variant": "primary",
                                                             "download": False, "purpose": "viewer", "platform": "android"})
        self.assertEqual(status, 200, data)
        job = self.job(data["job_id"])
        self.assertEqual(job.status, "done")
        return job.output_paths()[0]

    def open(self, paths, platform=None):
        body = {"paths": [str(path) for path in paths], "auto_face": True, "rigged": True}
        if platform:
            body["game_platform"] = platform
        status, data = self.call("/api/viewer/prepare", body)
        self.assertEqual(status, 200, data)
        from webtools.core import model_viewer
        editing = data["editing"]
        self.assertTrue(editing["available"], editing)
        return editing, model_viewer.get_editing_companions(data["id"])

    def run_edit(self, route, token, state, **extra):
        status, data = self.call(route, {"token": token, "state": state, **extra})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.job(data["job_id"]).status, "done")
        status, result = self.call("/api/viewer/edit/result/" + data["job_id"])
        self.assertEqual(status, 200, result)
        return result

    def assert_face_editable(self, editing):
        outlines = editing["outlines"]
        editable = {row["name"]: row for row in outlines["meshes"]}
        excluded = {row["name"]: [reason["code"] for reason in row["reasons"]] for row in outlines["excludedMeshes"]}
        self.assertLessEqual(FACE_PREFAB, set(editable), excluded)
        proofs = {json.dumps(proof, sort_keys=True) for name in FACE_PREFAB for proof in editable[name].get("runtimeBindings", [])}
        self.assertEqual(len(proofs), 1, "Every face prefab mesh is bound by the body's one BodyPartManager")
        return editable, json.loads(proofs.pop())

    def test_face_meshes_stay_editable_after_save_mod_zip_and_installed_reopen(self):
        from webtools.core import bundle_identity
        # First open through Game assets: the stock face completes the body.
        body = self.game_import(SUIT)
        editing, companions = self.open([body], "android")
        editable, proof = self.assert_face_editable(editing)
        self.assertEqual(len(companions), 1)
        stock_companion = companions[0]["path"]
        stock_face = Path(stock_companion).read_bytes()
        self.assertEqual({proof["faceAsset"]}, {name.casefold() for name in bundle_identity._cab_names(stock_face)})
        state = {"version": 1, "edits": [], "outlines": [{"id": editable["Mouth"]["id"], "factor": 1.5}]}

        # (a) Save the edited copy and reopen it.
        saved = self.run_edit("/api/viewer/edit/export", editing["token"], state)
        self.assert_face_editable(self.open(saved["preview_paths"])[0])

        # (b) Create the Mod ZIP with the face edit and reopen the ZIP itself.
        packaged = self.run_edit("/api/viewer/edit/package", editing["token"], state, display_name="Outline round trip",
                                 character_id=None, counterpart_path=None, selected_variant=None, include_face_edits=True)
        package = packaged["mod_package"]["package_path"]
        self.assert_face_editable(self.open([package])[0])

        # (c) Add it to the game and reopen the installed costume from Game assets.
        installed = self.install(package)
        editing, companions = self.open([self.game_import(INSTALLED_SUIT)], "android")
        editable, proof = self.assert_face_editable(editing)
        self.assertEqual([_sha(Path(row["path"]).read_bytes()) for row in companions], [_sha(installed["F"])])
        self.assertEqual({proof["faceAsset"]}, {name.casefold() for name in bundle_identity._cab_names(installed["F"])})
        self.assertNotEqual(proof["faceAsset"], next(iter(bundle_identity._cab_names(stock_face))).casefold())

        # The installed face is now cached under the same member, and the
        # stock face may have been pruned. A copy of the stock body that is
        # not a game import still gets the face its BodyPartManager names.
        cached_stock = Path(stock_companion)
        cached_stock.unlink()
        Path(str(cached_stock) + ".json").unlink()
        stock_copy = self.library / "extracted" / "stock_copy.unity"
        stock_copy.parent.mkdir(parents=True)
        shutil.copyfile(body, stock_copy)
        for paths, platform in (([stock_copy], None), ([self.game_import(SUIT)], "android")):
            with self.subTest(paths=[Path(path).name for path in paths]):
                editing, companions = self.open(paths, platform)
                self.assert_face_editable(editing)
                self.assertEqual([_sha(Path(row["path"]).read_bytes()) for row in companions], [_sha(stock_face)])

        # (d) After a restart the import registry is empty and the face cache
        # may be gone. Reloading the installed body file itself still gets
        # its private face, through the Game-assets cache's own receipt.
        from webtools.core import viewer_mod_sources
        installed_body = self.game_import(INSTALLED_SUIT)
        viewer_mod_sources._REGISTRY.clear()
        shutil.rmtree(self.library / ".viewer-cache" / "models")
        editing, companions = self.open([installed_body], "android")
        _, proof = self.assert_face_editable(editing)
        self.assertEqual([_sha(Path(row["path"]).read_bytes()) for row in companions], [_sha(installed["F"])])
        self.assertEqual({proof["faceAsset"]}, {name.casefold() for name in bundle_identity._cab_names(installed["F"])})

        # (e) The private face is cached again, and the stock face is neither
        # cached nor in the local packs, only on the CDN. The stock body
        # opened as a file downloads its own face instead of borrowing it.
        from webtools.core import model_faces
        stock_pack = self.pack_of(stock_face)
        cdn = self.root / "cdn"
        cdn.mkdir()
        shutil.move(self.runtime / "static" / stock_pack, cdn / stock_pack)
        for path in list((self.library / ".viewer-cache" / "models").glob("*.unity")):
            if path.read_bytes() == stock_face:
                path.unlink()
                Path(str(path) + ".json").unlink(missing_ok=True)
        served = []

        def download(url, expected, deadline, byte_limit):
            name = url.rsplit("/", 1)[1]
            served.append(name)
            if not (cdn / name).is_file():
                raise model_faces.FaceUnavailable("Not on this CDN")
            return (cdn / name).read_bytes()

        with patch.object(model_faces, "_download", download):
            editing, companions = self.open([stock_copy])
        self.assert_face_editable(editing)
        self.assertEqual([_sha(Path(row["path"]).read_bytes()) for row in companions], [_sha(stock_face)])
        self.assertEqual(served, [stock_pack])

    def pack_of(self, raw):
        """The runtime pack whose decrypted catalog section is ``raw``."""
        catalog = self.runtime / "assets" / "db" / "gl" / "asset_a_en.db"
        with closing(sqlite3.connect(catalog)) as db:
            rows = db.execute("SELECT pack_name,head,size,key1,key2 FROM member_model").fetchall()
        for pack, head, size, key1, key2 in rows:
            path = self.runtime / "static" / pack
            if size != len(raw) or not path.is_file():
                continue
            data = bytearray(path.read_bytes()[head:head + size])
            self.extractor.decrypt_section(data, self.extractor.FIXED_KEY0, key1, key2)
            if bytes(data) == raw:
                return pack
        self.fail("The stock face pack is not in the runtime catalog")


if __name__ == "__main__":
    unittest.main()
