"""Automatic facial-source discovery, tested with original synthetic geometry."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from webtools.core import model_faces as faces
from webtools.core import model_viewer as viewer


FIXTURE = Path(__file__).parent / "fixtures" / "viewer_textured_triangle.unity"
HAS_EXTRACTOR = importlib.util.find_spec("llas_asset_extractor") is not None
EXTRACTOR_REQUIRED = unittest.skipUnless(HAS_EXTRACTOR, "Elichika's parent llas_asset_extractor is needed for DB/download roundtrips")


def bundle(entries):
    payload = b"".join(value for _, value in entries)
    info = bytes(16) + struct.pack(">iIIHi", 1, len(payload), len(payload), 0, len(entries))
    offset = 0
    for name, value in entries:
        info += struct.pack(">qqI", offset, len(value), 0) + name.encode() + b"\0"
        offset += len(value)
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + b"2019.4.0f1\0"
    return prefix + struct.pack(">QIII", len(prefix) + 20 + len(info) + len(payload), len(info), len(info), 64) + info + payload


def glb_names(metadata):
    data = viewer.get_model(metadata["id"])
    size, = struct.unpack_from("<I", data, 12)
    return [mesh["name"] for mesh in json.loads(data[20:20 + size])["meshes"]]


class PackageSizeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,PRIMARY KEY(package_key,pack_name))")
        self.queries = []
        class RecordingConnection:
            def execute(inner, query, parameters):
                self.queries.append((query, list(parameters)))
                return self.db.execute(query, parameters)
        self.recording = RecordingConnection()

    def test_selected_suit_sizes_do_not_scan_other_groups(self):
        self.db.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?,?)", [("suit:2", "a", 11), ("suit:2", "b", 22)])
        self.assertEqual(faces._pack_sizes(self.recording, ["a", "b"], 2), {"a": 11, "b": 22})
        self.assertEqual(len(self.queries), 1)
        self.assertIn("package_key=?", self.queries[0][0])
        self.assertEqual(self.queries[0][1], ["suit:2", "a", "b"])

    def test_legacy_scan_only_receives_names_missing_from_selected_suit(self):
        self.db.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?,?)", [("suit:2", "a", 11), ("other", "b", 22)])
        self.assertEqual(faces._pack_sizes(self.recording, ["a", "b"], 2), {"a": 11, "b": 22})
        self.assertEqual(len(self.queries), 2)
        self.assertNotIn("package_key", self.queries[1][0])
        self.assertEqual(self.queries[1][1], ["b"])

    def test_unknown_suit_and_legacy_schema_keep_old_first_mapping(self):
        self.db.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?,?)", [("other1", "a", 11), ("other2", "a", 22)])
        self.assertEqual(faces._pack_sizes(self.recording, ["a"], 99), {"a": 11})
        self.db.execute("DROP TABLE m_asset_package_mapping")
        self.db.execute("CREATE TABLE m_asset_package_mapping(pack_name TEXT,file_size INTEGER)")
        self.db.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?)", [("a", 33), ("a", 44)])
        self.assertEqual(faces._pack_sizes(self.recording, ["a"], 2), {"a": 33})

    def test_selected_suit_record_is_explicitly_preferred_for_conflicting_custom_catalog(self):
        self.db.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?,?)", [("other", "a", 11), ("suit:2", "a", 22)])
        self.assertEqual(faces._pack_sizes(self.recording, ["a"], 2), {"a": 22})

    def test_empty_pack_list_does_not_open_a_query(self):
        self.assertEqual(faces._pack_sizes(self.recording, [], 2), {})
        self.assertEqual(self.queries, [])


class FaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import UnityPy
        except ImportError as error:
            raise unittest.SkipTest("UnityPy is required") from error
        cls.UnityPy = UnityPy

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.selected = self.root / "selected"
        self.library = self.root / "library"
        self.selected.mkdir()
        self.library.mkdir()
        self.body = self.selected / "costume.unity"
        self.body.write_bytes(self.scene("Body"))
        self.context = {"enabled": True, "library_roots": [str(self.library)],
                        "cache_dir": str(self.root / "cache"), "repo_root": str(self.root / "repo"),
                        "allow_download": False}

    def tearDown(self):
        viewer._SESSIONS.clear()
        self.temporary.cleanup()

    def scene(self, name, owner=207):
        env = self.UnityPy.load(FIXTURE.read_bytes())
        for obj in env.objects:
            if obj.type.name in ("GameObject", "Mesh", "Material"):
                tree = obj.read_typetree()
                tree["m_Name"] = (f"ch{owner:04}_co0000_head" if owner is not None else "GenericMaterial") if obj.type.name == "Material" else name
                obj.save_typetree(tree)
        return next(iter(env.files.values())).save()

    def donor(self, owner=207):
        return bundle([(name + ".assets", self.scene(name, owner)) for name in ("Body", "Hair", "Face", "Eyes")])

    def board_part(self, *, owner=209, overlay=False, shell=False, head="Head_Face", active=True):
        """Neutral rig geometry below the game's verified mask transform paths."""
        env = self.UnityPy.load(FIXTURE.with_name("viewer_rig.unity").read_bytes())
        names = {2: f"ch{owner:04}_member", 4: head,
                 6: "mesh_mask" if overlay or shell else "mesh_facedots", 8: "unusedBone",
                 10: "Mask_DisplayOverlayparts" if overlay else "UnknownShellLeaf" if shell else "UnknownDisplayLeaf"}
        for obj in env.objects:
            if obj.type.name == "GameObject":
                tree = obj.read_typetree()
                tree["m_Name"] = names[obj.path_id]
                if obj.path_id == 10:
                    tree["m_IsActive"] = active
                obj.save_typetree(tree)
            elif obj.type.name == "Transform":
                tree = obj.read_typetree()
                if obj.path_id == 3:
                    tree["m_Children"] = [r for r in tree["m_Children"] if r["m_PathID"] != 11]
                if obj.path_id == 7:
                    tree["m_Children"].append({"m_FileID": 0, "m_PathID": 11})
                if obj.path_id == 11:
                    tree["m_Father"] = {"m_FileID": 0, "m_PathID": 7}
                obj.save_typetree(tree)
            elif obj.type.name == "Mesh":
                tree = obj.read_typetree()
                tree["m_Name"] = "BoardOverlay" if overlay else "BoardShell" if shell else "BoardPixels"
                obj.save_typetree(tree)
        return next(iter(env.files.values())).save()

    def plan(self):
        deadline = time.monotonic() + 100
        scene = viewer._Scene(viewer._environment([str(self.body)], deadline), deadline)
        return faces.FacePlan(scene, [str(self.body)], self.context, deadline)

    def descriptor(self, data, name="pack207"):
        return {"asset_path": "face207", "pack_name": name, "head": 0, "size": len(data),
                "key1": -12345, "key2": 23456, "pack_size": len(data)}

    def encrypted(self, data, descriptor):
        import llas_asset_extractor as extractor
        encrypted = bytearray(data)
        extractor.decrypt_section(encrypted, extractor.FIXED_KEY0, descriptor["key1"], descriptor["key2"])
        return bytes(encrypted)

    def databases(self, data):
        root = Path(self.context["repo_root"]) / "assets" / "db" / "gl"
        root.mkdir(parents=True)
        descriptor = self.descriptor(data)
        with sqlite3.connect(root / "masterdata.db") as db:
            db.executescript("CREATE TABLE m_suit(id INTEGER, member_m_id INTEGER, model_asset_path TEXT); CREATE TABLE m_member_init(member_m_id INTEGER,suit_m_id INTEGER);")
            db.execute("INSERT INTO m_suit VALUES(207001,207,'body207')")
            db.execute("INSERT INTO m_suit VALUES(101001,101,'wrongbody')")
            db.execute("INSERT INTO m_member_init VALUES(207,207001)")
        with sqlite3.connect(root / "asset_a_en.db") as db:
            db.executescript("CREATE TABLE member_model(asset_path TEXT,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER); CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT); CREATE TABLE m_asset_package_mapping(pack_name TEXT,file_size INTEGER);")
            db.execute("INSERT INTO member_model_dependency VALUES('body207','face207')")
            db.execute("INSERT INTO member_model VALUES(?,?,?,?,?,?)", tuple(descriptor[k] for k in ("asset_path", "pack_name", "head", "size", "key1", "key2")))
            db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?)", (descriptor["pack_name"], descriptor["pack_size"]))
        return descriptor

    def test_same_owner_donor_only_adds_face_roles_and_preserves_sources(self):
        donor = self.library / "original.unity"
        donor.write_bytes(self.donor())
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.body, donor)}
        with patch.object(faces, "missing_dynamic", return_value=True):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
        self.assertEqual(metadata["faces"], {"enabled": True, "status": "added", "added": 2, "characters": [207]})
        self.assertEqual(metadata["stats"]["meshes"], 3)
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), digest)

    def test_other_character_and_filename_spoof_do_not_supply_face(self):
        (self.library / "ch0207_original.unity").write_bytes(self.donor(owner=101))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body"])
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertIn("face_source_unavailable", [warning["code"] for warning in metadata["warnings"]])

    def test_canonical_character_filename_is_ranked_before_large_other_library(self):
        for number in range(40):
            (self.library / f"Ai_id{number}_original.unity").write_bytes(self.scene("Face", owner=205))
        expected = self.library / "Setsuna_id402072005_original.unity"
        expected.write_bytes(self.donor())
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(set(glb_names(metadata)), {"Body", "Face", "Eyes"})
        self.assertEqual(metadata["faces"]["status"], "added")

    def test_local_discovery_works_without_parent_extractor_package(self):
        (self.library / "Setsuna_original.unity").write_bytes(self.donor())
        with patch.dict("sys.modules", {"llas_asset_extractor": None}):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(set(glb_names(metadata)), {"Body", "Face", "Eyes"})
        self.assertEqual(metadata["faces"]["status"], "added")

    def test_known_owner_originals_complete_before_catalog_or_broad_scan_for_all_owners(self):
        for owner in (1, 101, 207, 209, 301):
            with self.subTest(owner=owner):
                self.body.write_bytes(self.scene("Body", owner=owner))
                path = self.library / f"ch{owner:04}_facedynamic.unity"
                path.write_bytes(self.donor(owner=owner))
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                with patch.object(faces.FacePlan, "_descriptor_iter", side_effect=AssertionError("No catalog needed")) as catalog, \
                        patch.object(faces.FacePlan, "_local", side_effect=AssertionError("No broad scan needed")) as broad, \
                        patch.object(faces, "_download") as fetch:
                    metadata = viewer.prepare([str(self.body)], face_context=self.context)
                self.assertEqual(metadata["faces"]["status"], "added")
                self.assertEqual(metadata["faces"]["characters"], [owner])
                self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
                catalog.assert_not_called()
                broad.assert_not_called()
                fetch.assert_not_called()
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_known_extracted_model_ignores_large_library_and_suit_origin_before_sql(self):
        directory = self.library / "extracted" / "3d_model"
        directory.mkdir(parents=True)
        (directory / "ch0207_facedynamic.unity").write_bytes(self.donor())
        for number in range(faces.MAX_LOCAL_FILES + 10):
            (self.library / f"unrelated-{number}.unity").write_bytes(b"unrelated")
        origin = self.root / "suit" / "costume.zip"
        origin.parent.mkdir()
        origin.write_bytes(b"original costume placeholder")
        self.context["origins"] = {str(self.body): str(origin)}
        with patch.object(faces.sqlite3, "connect", side_effect=AssertionError("Known original must precede SQL")) as connect, \
                patch.object(faces.FacePlan, "_descriptor_iter", side_effect=AssertionError("No catalog needed")) as catalog, \
                patch.object(faces.FacePlan, "_local", side_effect=AssertionError("No broad scan needed")) as broad:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        connect.assert_not_called()
        catalog.assert_not_called()
        broad.assert_not_called()
        self.assertEqual(origin.read_bytes(), b"original costume placeholder")

    def test_managed_same_owner_cache_precedes_catalog_and_keeps_prune_protection(self):
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        cached = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(cached, self.donor(), 207)
        before = {path: path.read_bytes() for path in (cached, Path(str(cached) + ".json"))}
        with patch.object(faces.FacePlan, "_descriptor_iter", side_effect=AssertionError("No catalog needed")) as catalog, \
                patch.object(faces.FacePlan, "_local", side_effect=AssertionError("No broad scan needed")) as broad, \
                patch.object(faces, "_prune_cache", wraps=faces._prune_cache) as prune:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        catalog.assert_not_called()
        broad.assert_not_called()
        self.assertTrue(any(str(cached) in call.args[1] for call in prune.call_args_list))
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_partial_known_original_retains_roles_then_uses_existing_fallback(self):
        canonical = self.library / "ch0207_face.unity"
        canonical.write_bytes(self.scene("Face"))
        companion = self.library / "original_eyes.unity"
        companion.write_bytes(self.scene("Eyes"))
        plan = self.plan()
        with patch.object(plan, "_descriptor_iter", return_value=iter(())) as catalog, \
                patch.object(plan, "_local", wraps=plan._local) as broad:
            paths = plan.resolve()
        self.assertEqual(set(paths), {str(canonical), str(companion)})
        self.assertEqual(plan.status, "added")
        self.assertEqual(plan.needed, set())
        self.assertEqual(plan.source_roles[str(canonical)], {"face"})
        catalog.assert_called_once()
        broad.assert_called_once()

    def test_partial_known_original_completes_from_verified_cache_before_catalog(self):
        canonical = self.library / "ch0207_face.unity"
        canonical.write_bytes(self.scene("Face"))
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        companion = directory / ("ch0207_" + "d" * 24 + ".unity")
        faces._save(companion, self.scene("Eyes"), 207)
        with patch.object(faces.FacePlan, "_descriptor_iter", side_effect=AssertionError("No catalog needed")) as catalog, \
                patch.object(faces.FacePlan, "_local", side_effect=AssertionError("No broad scan needed")) as broad:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
        catalog.assert_not_called()
        broad.assert_not_called()

    def test_rejected_known_filename_does_not_modify_owner_or_accepted_state(self):
        canonical = self.library / "ch0207_facedynamic.unity"
        for owner in (101, None):
            with self.subTest(owner=owner):
                canonical.write_bytes(self.donor(owner=owner))
                plan = self.plan()
                before = set(plan.needed)
                with patch.object(plan, "_descriptor_iter", return_value=iter(())) as catalog, \
                        patch.object(plan, "_local", return_value=[]):
                    self.assertEqual(plan.resolve(), [])
                self.assertEqual(plan.owner, 207)
                self.assertEqual(plan.needed, before)
                self.assertEqual(plan.auto_paths, [])
                self.assertEqual(plan.dynamic_sources, set())
                self.assertEqual(plan.source_adjustments, {})
                self.assertEqual(plan.database_paths, set())
                catalog.assert_called_once()

    def test_normal_rina_rejects_known_masked_donor_before_fallback(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name, owner=209)) for name in ("Body", "Face")]))
        (self.library / "ch0209_facedynamic.unity").write_bytes(self.board_part(owner=9999))
        plan = self.plan()
        with patch.object(plan, "_descriptor_iter", return_value=iter(())) as catalog, \
                patch.object(plan, "_local", return_value=[]):
            self.assertEqual(plan.resolve(), [])
        self.assertEqual(plan.owner, 209)
        self.assertEqual(plan.face_mode, "normal")
        self.assertEqual(plan.needed, {"eyes"})
        self.assertEqual(plan.auto_paths, [])
        catalog.assert_called_once()

    def test_known_rina_board_donor_keeps_overlay_and_shell_without_normal_eyes(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name, owner=9999)) for name in ("Body", "Face")]))
        manifest = self.selected / "modinstall.txt"
        manifest.write_text("costume_file='costume.unity'\nchara_id=209\n")
        self.context["manifest_paths"] = [str(manifest)]
        (self.library / "ch0209_facedynamic.unity").write_bytes(bundle([
            ("pixels.assets", self.board_part(owner=9999)),
            ("overlay.assets", self.board_part(owner=9999, overlay=True)),
            ("shell.assets", self.board_part(owner=9999, shell=True)),
            ("normal_eyes.assets", self.scene("Eyes", owner=209))]))
        with patch.object(faces.FacePlan, "_descriptor_iter", side_effect=AssertionError("No catalog needed")) as catalog, \
                patch.object(faces.FacePlan, "_local", side_effect=AssertionError("No broad scan needed")) as broad:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"], {"enabled": True, "status": "added", "added": 3, "characters": [209]})
        self.assertEqual(glb_names(metadata), ["Body", "Face", "BoardPixels", "BoardOverlay", "BoardShell"])
        catalog.assert_not_called()
        broad.assert_not_called()

    def test_invalid_managed_cache_and_escaped_links_are_not_fast_candidates(self):
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        cached = directory / ("ch0207_" + "b" * 24 + ".unity")
        faces._save(cached, self.donor(), 207)
        cached.write_bytes(b"corrupt cached bytes")
        outside = self.root / "outside.unity"
        outside.write_bytes(self.donor())
        (self.library / "ch0207_facedynamic.unity").symlink_to(outside)
        linked_cache = directory / ("ch0207_" + "c" * 24 + ".unity")
        linked_cache.symlink_to(outside)
        plan = self.plan()
        with patch.object(plan, "_descriptor_iter", return_value=iter(())), patch.object(plan, "_local", return_value=[]):
            self.assertEqual(plan.resolve(), [])
        self.assertEqual(plan.auto_paths, [])
        self.assertEqual(cached.read_bytes(), b"corrupt cached bytes")
        cached.unlink()
        linked_cache.unlink()
        Path(str(cached) + ".json").unlink()
        directory.rmdir()
        directory.symlink_to(self.library, target_is_directory=True)
        self.assertEqual(list(self.plan()._known_local()), [])

    def test_known_candidate_and_cache_entry_bounds_are_applied_before_sorting(self):
        roots = []
        for number in range(faces.MAX_CANDIDATES):
            directory = self.root / f"named-{number}"
            directory.mkdir()
            (directory / "ch0207_facedynamic.unity").write_bytes(b"candidate")
            (directory / "ch0207_face.unity").write_bytes(b"candidate")
            roots.append(str(directory))
        self.context["library_roots"] = roots
        self.assertEqual(len(list(self.plan()._known_local())), faces.MAX_CANDIDATES)
        self.context["library_roots"] = []
        consumed = []
        class Entries:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def __iter__(self):
                for index in range(faces.MAX_LOCAL_FILES + 10):
                    consumed.append(index)
                    yield SimpleNamespace(name=f"unrelated-{index}")
        with patch.object(faces.os, "scandir", return_value=Entries()):
            self.assertEqual(list(self.plan()._known_local()), [])
        # One source root produces six deterministic probes before cache scan.
        self.assertEqual(len(consumed), faces.MAX_LOCAL_FILES - 6)

    def test_optional_textures_can_append_after_untextured_base_is_finished(self):
        env = self.UnityPy.load(FIXTURE.with_name("viewer_triangle.unity").read_bytes())
        for obj in env.objects:
            if obj.type.name in ("GameObject", "Mesh"):
                tree = obj.read_typetree()
                tree["m_Name"] = "ch0207_co0000_member" if obj.type.name == "GameObject" else "Body"
                obj.save_typetree(tree)
        self.body.write_bytes(next(iter(env.files.values())).save())
        (self.library / "donor.unity").write_bytes(self.donor())
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(set(glb_names(metadata)), {"Body", "Face", "Eyes"})
        self.assertGreater(metadata["stats"]["textures"], 0)

    def test_literal_manifest_cannot_override_internal_owner_or_execute(self):
        marker = self.root / "executed"
        manifest = self.selected / "modinstall.txt"
        manifest.write_text("costume_file='costume.unity'\nchara_id=101\nopen(" + repr(str(marker)) + ",'w').write('bad')\n")
        self.context["manifest_paths"] = [str(manifest)]
        plan = self.plan()
        self.assertEqual(plan.owner, 207)
        self.assertFalse(marker.exists())
        self.assertIn("face_owner_conflict", [warning["code"] for warning in plan.warnings])

    def test_manifest_must_name_selected_bundle(self):
        manifest = self.selected / "modinstall.txt"
        manifest.write_text("costume_file='other.unity'\nchara_id=101\n")
        self.assertEqual(faces._manifest_owner([str(self.body)], [str(manifest)]), set())

    def test_manifest_basename_from_an_unrelated_directory_is_ignored(self):
        unrelated = self.root / "other_archive"
        unrelated.mkdir()
        manifest = unrelated / "modinstall.txt"
        manifest.write_text("costume_file='costume.unity'\nchara_id=101\n")
        self.assertEqual(faces._manifest_owner([str(self.body)], [str(manifest)]), set())

    def test_manifest_requires_matching_trusted_archive_origins(self):
        manifest = self.selected / "modinstall.txt"
        manifest.write_text("costume_file='costume.unity'\nchara_id=207\n")
        origins = {str(manifest): str(self.root / "archive-a.zip"), str(self.body): str(self.root / "archive-b.zip")}
        self.assertEqual(faces._manifest_owner([str(self.body)], [str(manifest)], origins), set())
        origins[str(manifest)] = origins[str(self.body)]
        self.assertEqual(faces._manifest_owner([str(self.body)], [str(manifest)], origins), {207})

    def test_unknown_owner_uses_only_its_own_manifest(self):
        self.body.write_bytes(self.scene("Body", owner=None))
        manifest = self.selected / "modinstall.txt"
        manifest.write_text("costume_file='costume.unity'\nchara_id=207\n")
        self.context["manifest_paths"] = [str(manifest)]
        self.context["origins"] = {str(manifest): str(self.root / "other.zip"), str(self.body): str(self.root / "selected.zip")}
        self.assertIsNone(self.plan().owner)
        self.context["origins"][str(manifest)] = self.context["origins"][str(self.body)]
        self.assertEqual(self.plan().owner, 207)

    def test_unknown_body_does_not_inherit_another_selected_bundles_owner(self):
        unknown = self.selected / "unknown.unity"
        unknown.write_bytes(self.scene("Body", owner=None))
        deadline = time.monotonic() + 100
        paths = [str(self.body), str(unknown)]
        scene = viewer._Scene(viewer._environment(paths, deadline), deadline)
        plan = faces.FacePlan(scene, paths, self.context, deadline)
        self.assertIsNone(plan.owner)

    def test_unknown_and_ambiguous_owner_do_not_fetch(self):
        plan = self.plan()
        with patch.object(faces, "_names", return_value=({101, 207}, set())), patch.object(faces, "_download") as fetch:
            deadline = time.monotonic() + 100
            scene = viewer._Scene(viewer._environment([str(self.body)], deadline), deadline)
            unsafe = faces.FacePlan(scene, [str(self.body)], self.context, deadline)
            self.assertIsNone(unsafe.owner)
            self.assertEqual(unsafe.resolve(), [])
            fetch.assert_not_called()

    def test_disabled_never_discovers_or_fetches(self):
        self.context["enabled"] = False
        with patch.object(faces.FacePlan, "_local") as local, patch.object(faces, "_download") as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body"])
        self.assertFalse(metadata["faces"]["enabled"])
        local.assert_not_called()
        fetch.assert_not_called()

    def test_missing_source_keeps_valid_body_preview(self):
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body"])
        self.assertEqual(metadata["faces"]["status"], "unavailable")

    def test_manual_face_already_present_does_not_download(self):
        self.body.write_bytes(self.donor())
        with patch.object(faces, "_download") as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "already_present")
        fetch.assert_not_called()

    @EXTRACTOR_REQUIRED
    def test_download_existing_db_route_decrypts_and_reuses_hashed_cache(self):
        data = self.donor()
        descriptor = self.databases(data)
        self.context["allow_download"] = True
        encrypted = self.encrypted(data, descriptor)
        with patch.object(faces, "_download", return_value=encrypted) as fetch:
            first = viewer.prepare([str(self.body)], face_context=self.context)
            self.assertEqual(glb_names(first), ["Body", "Face", "Eyes"])
            self.assertEqual(first["faces"]["status"], "added")
            fetch.assert_called_once()
            self.assertTrue(fetch.call_args.args[0].endswith("/static/pack207"))
            second = viewer.prepare([str(self.body)], face_context=self.context)
            self.assertEqual(second["faces"]["status"], "added")
            fetch.assert_called_once()
        model = next((self.root / "cache" / "models").glob("*.unity"))
        model.write_bytes(b"corrupt")
        with patch.object(faces, "_download") as fetch:
            rebuilt = self.plan()._resource(descriptor)
            self.assertEqual(Path(rebuilt).read_bytes(), data)
            fetch.assert_not_called()

    def test_wrong_size_or_unsafe_pack_names_fail_before_download(self):
        plan = self.plan()
        for changes in ({"pack_name": "../escape"}, {"pack_name": "https://other"}, {"head": -1}, {"pack_size": faces.MAX_PACK_BYTES + 1}):
            descriptor = self.descriptor(b"1234")
            descriptor.update(changes)
            with self.subTest(changes=changes), patch.object(faces, "_download") as fetch, self.assertRaises(faces.FaceUnavailable):
                plan._resource(descriptor)
            fetch.assert_not_called()

    def test_symlink_cache_cannot_write_or_prune_library(self):
        cache = self.root / "cache"
        cache.mkdir()
        original = self.library / "pack207"
        faces._save(original, b"original user bytes")
        (cache / "models").symlink_to(self.library, target_is_directory=True)
        plan = self.plan()
        with patch.object(faces, "_download") as fetch, self.assertRaises(faces.FaceUnavailable):
            plan._resource(self.descriptor(b"1234"))
        fetch.assert_not_called()
        with patch.object(faces, "MAX_CACHE_BYTES", 0):
            faces._prune_cache(cache)
        self.assertEqual(original.read_bytes(), b"original user bytes")

    def test_symlink_cache_root_cannot_write_prune_or_hide_body(self):
        cache = self.root / "cache"
        cache.symlink_to(self.library, target_is_directory=True)
        original = self.library / "pack207"
        faces._save(original, b"original user bytes")
        with patch.object(faces, "_download") as fetch, self.assertRaises(faces.FaceUnavailable):
            self.plan()._resource(self.descriptor(b"1234"))
        fetch.assert_not_called()
        with self.assertRaises(faces.FaceUnavailable):
            faces._prune_cache(cache)
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body"])
        self.assertEqual(original.read_bytes(), b"original user bytes")
        self.assertFalse((self.library / "models").exists())

    @EXTRACTOR_REQUIRED
    def test_all_member_groups_complete_faces_from_automatic_download_only(self):
        # Different character ranges, including Rina and the final roster
        # member, must use their own model and must not depend on a 207 file.
        for owner in (1, 101, 209, 212):
            with self.subTest(owner=owner):
                self.body.write_bytes(self.scene("Body", owner=owner))
                data = self.donor(owner=owner)
                descriptor = self.descriptor(data, name=f"pack{owner}")
                plan = self.plan()
                self.assertEqual(plan.owner, owner)
                self.context["allow_download"] = True
                with patch.object(faces.FacePlan, "_descriptor_iter", return_value=[descriptor]), \
                        patch.object(faces, "_download", return_value=self.encrypted(data, descriptor)) as fetch:
                    metadata = viewer.prepare([str(self.body)], face_context=self.context)
                self.assertEqual(metadata["faces"], {"enabled": True, "status": "added", "added": 2, "characters": [owner]})
                self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
                fetch.assert_called_once()
                self.assertTrue(fetch.call_args.args[0].endswith(f"/pack{owner}"))
        self.assertEqual(list(self.library.iterdir()), [])

    @EXTRACTOR_REQUIRED
    def test_jp_ios_downloaded_pack_wins_before_preferred_gl_network(self):
        donor = self.donor()
        self.databases(donor)
        repo = Path(self.context["repo_root"])
        jp = repo / "assets" / "db" / "jp"
        jp.mkdir()
        (jp / "masterdata.db").write_bytes((jp.parent / "gl" / "masterdata.db").read_bytes())
        (jp / "asset_i_ja.db").write_bytes((jp.parent / "gl" / "asset_a_en.db").read_bytes())
        with sqlite3.connect(jp / "asset_i_ja.db") as db:
            db.execute("UPDATE member_model SET pack_name='jpios207',key1=32457,key2=-49532")
            db.execute("UPDATE m_asset_package_mapping SET pack_name='jpios207'")
        descriptor = dict(self.descriptor(donor), pack_name="jpios207", key1=32457, key2=-49532)
        pack = self.library / "files" / "pkgj" / "jpios207"
        pack.parent.mkdir(parents=True)
        packed = self.encrypted(donor, descriptor)
        pack.write_bytes(packed)
        self.context["allow_download"] = True
        with patch.object(faces, "_download") as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
        fetch.assert_not_called()
        self.assertEqual(pack.read_bytes(), packed)

    @EXTRACTOR_REQUIRED
    def test_exact_cached_pack_completes_before_a_large_library_scan(self):
        donor = self.donor()
        descriptor = self.databases(donor)
        pack = self.library / descriptor["pack_name"]
        packed = self.encrypted(donor, descriptor)
        pack.write_bytes(packed)
        with patch.object(faces.FacePlan, "_local", side_effect=AssertionError("Unrelated models must not consume the face budget")) as local, \
                patch.object(faces, "_download") as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
        local.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(pack.read_bytes(), packed)

    @EXTRACTOR_REQUIRED
    def test_cached_face_is_used_before_opening_later_catalogs(self):
        donor = self.donor()
        descriptor = self.databases(donor)
        (self.library / descriptor["pack_name"]).write_bytes(self.encrypted(donor, descriptor))
        gl = Path(self.context["repo_root"]) / "assets/db/gl"
        jp = gl.parent / "jp"
        jp.mkdir()
        (jp / "masterdata.db").write_bytes((gl / "masterdata.db").read_bytes())
        (jp / "asset_a_ja.db").write_bytes((gl / "asset_a_en.db").read_bytes())
        connect, opened = sqlite3.connect, []

        def guarded_connect(path, *args, **kwargs):
            opened.append(str(path))
            if "/jp/" in str(path):
                raise AssertionError("An available GL face must not wait for the later JP catalog")
            return connect(path, *args, **kwargs)

        with patch.object(faces.sqlite3, "connect", side_effect=guarded_connect):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertFalse(any("/jp/" in path for path in opened))
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])

    def test_broken_catalog_lookup_still_uses_existing_local_unity_face(self):
        (self.library / "original.unity").write_bytes(self.donor())
        with patch.object(faces.FacePlan, "_descriptor_iter", side_effect=OSError("Optional catalog unavailable")), \
                patch.object(faces, "_download") as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
        fetch.assert_not_called()

    @EXTRACTOR_REQUIRED
    def test_library_scan_expiry_preserves_time_for_automatic_cdn_download(self):
        donor = self.donor()
        descriptor = self.databases(donor)
        self.context["allow_download"] = True
        plan = self.plan()
        original_deadline = plan.deadline

        def expired_local_search(current):
            self.assertLess(current.deadline, original_deadline)
            self.assertLessEqual(current.deadline - time.monotonic(), 8.01)
            raise faces.FaceUnavailable("Local search reached its separate budget")

        def downloaded(*args, **kwargs):
            self.assertEqual(plan.deadline, original_deadline)
            return self.encrypted(donor, descriptor)

        with patch.object(faces.FacePlan, "_local", expired_local_search), \
                patch.object(faces, "_download", side_effect=downloaded) as fetch:
            result = plan.resolve()
        self.assertEqual(plan.deadline, original_deadline)
        self.assertEqual(plan.status, "added")
        self.assertEqual(len(result), 1)
        fetch.assert_called_once()

    @EXTRACTOR_REQUIRED
    def test_incomplete_gl_catalog_does_not_hide_valid_jp_catalog(self):
        donor = self.donor()
        self.databases(donor)
        gl = Path(self.context["repo_root"]) / "assets" / "db" / "gl"
        jp = gl.parent / "jp"
        jp.mkdir()
        (jp / "masterdata.db").write_bytes((gl / "masterdata.db").read_bytes())
        (jp / "asset_a_ja.db").write_bytes((gl / "asset_a_en.db").read_bytes())
        (gl / "asset_a_en.db").write_bytes(b"incomplete catalog")
        self.context["allow_download"] = True
        with patch.object(faces, "_download", return_value=self.encrypted(donor, self.descriptor(donor))) as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        fetch.assert_called_once()

    @EXTRACTOR_REQUIRED
    def test_own_original_body_can_complete_eyes_without_dynamic_dependency(self):
        # Rina's board model has no shared FaceDynamic dependency. The selected
        # mod may retain its Face shell while omitting the separate eyes.
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name, owner=209)) for name in ("Body", "Face")]))
        donor = self.donor(owner=209)
        descriptor = self.databases(donor)
        gl = Path(self.context["repo_root"]) / "assets" / "db" / "gl"
        with sqlite3.connect(gl / "masterdata.db") as db:
            db.execute("UPDATE m_suit SET member_m_id=209 WHERE member_m_id=207")
            db.execute("UPDATE m_member_init SET member_m_id=209 WHERE member_m_id=207")
        with sqlite3.connect(gl / "asset_a_en.db") as db:
            db.execute("DELETE FROM member_model_dependency")
            db.execute("UPDATE member_model SET asset_path='body207'")
        self.context["allow_download"] = True
        with patch.object(faces, "_download", return_value=self.encrypted(donor, descriptor)) as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"], {"enabled": True, "status": "added", "added": 1, "characters": [209]})
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
        fetch.assert_called_once()

    def test_native_board_subtree_completes_missing_eyes_and_keeps_overlay(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name, owner=9999)) for name in ("Body", "Face")]))
        manifest = self.selected / "modinstall.txt"
        manifest.write_text("costume_file='costume.unity'\nchara_id=209\n")
        self.context["manifest_paths"] = [str(manifest)]
        (self.library / "original_board.unity").write_bytes(bundle([
            ("pixels.assets", self.board_part()), ("overlay.assets", self.board_part(overlay=True)),
            ("shell.assets", self.board_part(shell=True))]))
        with patch.object(faces, "_download") as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"], {"enabled": True, "status": "added", "added": 3, "characters": [209]})
        self.assertEqual(glb_names(metadata), ["Body", "Face", "BoardPixels", "BoardOverlay", "BoardShell"])
        self.assertEqual(metadata["warnings"], [])
        fetch.assert_not_called()

    def test_existing_native_board_does_not_request_normal_iris_eyes(self):
        self.body.write_bytes(bundle([("body.assets", self.scene("Body", owner=209)),
                                     ("face.assets", self.scene("Face", owner=209)),
                                     ("board.assets", self.board_part())]))
        with patch.object(faces, "_download") as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "already_present")
        self.assertEqual(glb_names(metadata), ["Body", "Face", "BoardPixels"])
        fetch.assert_not_called()

    def test_overlay_alone_never_completes_missing_facial_display(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name, owner=209)) for name in ("Body", "Face")]))
        (self.library / "overlay_only.unity").write_bytes(bundle([
            ("overlay.assets", self.board_part(overlay=True)), ("shell.assets", self.board_part(shell=True))]))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(glb_names(metadata), ["Body", "Face"])

    def test_costume_mask_names_and_hidden_or_other_owner_boards_are_excluded(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name, owner=209)) for name in ("Body", "Face")]))
        for name, data in (("hair_board", self.board_part(head="Head_Hair")),
                           ("hat_overlay", self.board_part(overlay=True, head="Hat")),
                           ("hidden_board", self.board_part(active=False)),
                           ("wrong_owner", self.board_part(owner=207))):
            (self.library / f"{name}.unity").write_bytes(data)
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(glb_names(metadata), ["Body", "Face"])

    def test_ch9999_board_identity_is_rina_only_with_same_source_active_board(self):
        self.body.write_bytes(bundle([("body.assets", self.scene("Body", owner=9999)),
                                     ("face.assets", self.scene("Face", owner=9999)),
                                     ("board.assets", self.board_part(owner=9999))]))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["characters"], [209])
        self.assertEqual(metadata["faces"]["status"], "already_present")
        for body in (self.scene("Body", owner=9999), self.board_part(owner=9999, active=False),
                     bundle([("board.assets", self.board_part(owner=9999)), ("other.assets", self.scene("Hair", owner=101))])):
            self.body.write_bytes(body)
            deadline = time.monotonic() + 20
            scene = viewer._Scene(viewer._environment([str(self.body)], deadline), deadline)
            self.assertIn(9999, faces._names(scene, str(self.body))[0])
        self.body.write_bytes(self.scene("ch9999_Body", owner=9999))
        other = self.library / "other_board.unity"
        other.write_bytes(self.board_part(owner=209))
        deadline = time.monotonic() + 20
        scene = viewer._Scene(viewer._environment([str(self.body), str(other)], deadline), deadline)
        self.assertEqual(faces._names(scene, str(self.body))[0], {9999})
        self.assertEqual(faces._names(scene, str(other))[0], {209})
        self.assertEqual(faces._names(scene)[0], {9999, 209})

    @EXTRACTOR_REQUIRED
    def test_normal_rina_uses_unmasked_view_and_rejects_local_board_donor(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name, owner=209)) for name in ("Body", "Face")]))
        (self.library / "ch0209_masked.unity").write_bytes(self.board_part(owner=9999))
        donor = self.donor(owner=209)
        descriptor = self.databases(donor)
        catalog = Path(self.context["repo_root"]) / "assets" / "db" / "gl"
        with sqlite3.connect(catalog / "masterdata.db") as db:
            db.execute("UPDATE m_suit SET member_m_id=209 WHERE member_m_id=207")
            db.execute("UPDATE m_member_init SET member_m_id=209 WHERE member_m_id=207")
            db.execute("CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,model_asset_path TEXT)")
            db.execute("INSERT INTO m_suit_view VALUES(207001,2,'unmasked209')")
        with sqlite3.connect(catalog / "asset_a_en.db") as db:
            db.execute("UPDATE member_model_dependency SET asset_path='unmasked209'")
            db.execute("INSERT INTO member_model VALUES('body207','masked209',0,?,123,456)", (len(donor),))
        self.context["allow_download"] = True
        with patch.object(faces, "_download", return_value=self.encrypted(donor, descriptor)) as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["characters"], [209])
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
        fetch.assert_called_once()
        self.assertTrue(fetch.call_args.args[0].endswith("/pack207"))

    def test_auxiliary_eye_surfaces_cannot_replace_missing_iris(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name)) for name in ("Body", "Face")]))
        names = ("Eye_Around", "LeftEyeWhiteLine", "RightEyeWhiteLine", "RinNyaEye_Overlay")
        (self.library / "eye_details.unity").write_bytes(bundle([(name + ".assets", self.scene(name)) for name in names]))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(glb_names(metadata), ["Body", "Face"])

    @EXTRACTOR_REQUIRED
    def test_original_body_keeps_a_slot_when_shared_dependencies_fill_limit(self):
        donor = self.donor()
        self.databases(donor)
        catalog = Path(self.context["repo_root"]) / "assets" / "db" / "gl" / "asset_a_en.db"
        with sqlite3.connect(catalog) as db:
            for number in range(4):
                db.execute("INSERT INTO member_model_dependency VALUES('body207',?)", (f"extra{number}",))
                db.execute("INSERT INTO member_model VALUES(?,?,0,?,123,456)", (f"extra{number}", f"extra_pack{number}", len(donor) + number))
            db.execute("INSERT INTO member_model VALUES('body207','body_pack207',0,?,123,456)", (len(donor),))
        descriptors = self.plan()._descriptors()
        self.assertEqual(len(descriptors), faces.MAX_AUTO_FILES)
        self.assertEqual(descriptors[-1]["asset_path"], "body207")

    @EXTRACTOR_REQUIRED
    def test_bad_local_pack_does_not_block_automatic_original_download(self):
        donor = self.donor()
        descriptor = self.databases(donor)
        damaged = self.library / descriptor["pack_name"]
        damaged.write_bytes(b"bad original pack")
        self.context["allow_download"] = True
        with patch.object(faces, "_download", return_value=self.encrypted(donor, descriptor)) as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(damaged.read_bytes(), b"bad original pack")
        fetch.assert_called_once()

    @EXTRACTOR_REQUIRED
    def test_transfer_budget_is_reserved_before_any_http_request(self):
        plan = self.plan()
        self.context["allow_download"] = True
        plan.transferred = faces.MAX_TRANSFER_BYTES - 2
        with patch.object(faces, "_download") as fetch, self.assertRaisesRegex(faces.FaceUnavailable, "budget"):
            plan._resource(self.descriptor(b"1234"))
        fetch.assert_not_called()

    @EXTRACTOR_REQUIRED
    def test_wrong_platform_response_is_not_published_to_pack_cache(self):
        self.context["allow_download"] = True
        descriptor = self.descriptor(b"wrong data has no UnityFS header")
        with patch.object(faces, "_download", return_value=b"x" * descriptor["size"]), self.assertRaises(faces.FaceUnavailable):
            self.plan()._resource(descriptor)
        self.assertFalse((self.root / "cache" / "packs" / descriptor["pack_name"]).exists())

    @EXTRACTOR_REQUIRED
    def test_timed_out_network_worker_never_publishes_late_cache_files(self):
        self.context["allow_download"] = True
        donor = self.donor()
        descriptor = self.databases(donor)
        packed = self.encrypted(donor, descriptor)
        base = viewer.prepare([str(self.body)])
        base_bytes = viewer.get_model(base["id"])
        gate, entered = threading.Event(), threading.Event()
        slot = threading.BoundedSemaphore(1)

        def blocked_download(*args):
            entered.set()
            gate.wait(2)
            # Simulate a resolver returning valid bytes after the deadline;
            # publication must still stay impossible on the abandoned worker.
            return packed

        with patch.object(faces, "_DOWNLOAD_SLOT", slot), patch.object(faces, "_download", side_effect=blocked_download), \
                patch.object(faces, "FACE_SECONDS", .05), patch.object(faces, "_save") as save:
            try:
                start = time.monotonic()
                metadata = viewer.prepare([str(self.body)], face_context=self.context)
                self.assertLess(time.monotonic() - start, .5)
                self.assertEqual(viewer.get_model(metadata["id"]), base_bytes)
                self.assertEqual(metadata["stats"], base["stats"])
                self.assertEqual(metadata["faces"]["status"], "unavailable")
                self.assertTrue(entered.is_set())
                save.assert_not_called()
            finally:
                gate.set()
                self.assertTrue(slot.acquire(timeout=1), "The bounded download worker did not finish")
                slot.release()
            save.assert_not_called()
        self.assertFalse((self.root / "cache" / "packs" / descriptor["pack_name"]).exists())
        self.assertEqual(list((self.root / "cache" / "models").glob("*.unity")), [])

    def test_local_facial_sources_still_work_while_download_slot_is_busy(self):
        (self.library / "local_original.unity").write_bytes(self.donor())
        slot = threading.BoundedSemaphore(1)
        slot.acquire()
        with patch.object(faces, "_DOWNLOAD_SLOT", slot), patch.object(faces, "_download") as download:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(set(glb_names(metadata)), {"Body", "Face", "Eyes"})
        download.assert_not_called()

    def test_failed_optional_face_does_not_fail_body(self):
        with patch.object(faces.FacePlan, "_local", side_effect=OSError("offline")):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body"])
        self.assertEqual(metadata["faces"]["status"], "unavailable")

    def test_invalid_optional_face_geometry_does_not_hide_valid_body(self):
        donor = self.library / "original.unity"
        donor.write_bytes(self.donor())
        geometry = viewer._geometry

        def fail_face(mesh, *args):
            if mesh.read().m_Name == "Eyes":
                raise viewer.ModelViewerError("invalid optional skin")
            return geometry(mesh, *args)

        with patch.object(viewer, "_geometry", side_effect=fail_face):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body", "Face"])
        self.assertEqual(metadata["faces"]["status"], "partial")

    def test_hair_only_does_not_append_or_download_faces(self):
        self.body.write_bytes(self.scene("Hair"))
        with patch.object(faces.FacePlan, "_local") as local, patch.object(faces, "_download") as fetch:
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Hair"])
        self.assertEqual(metadata["faces"]["status"], "not_needed")
        local.assert_not_called()
        fetch.assert_not_called()

    def test_face_shell_only_never_claims_complete_when_eyes_are_missing(self):
        (self.library / "original_face_shell.unity").write_bytes(self.scene("Face"))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body", "Face"])
        self.assertEqual(metadata["faces"]["status"], "partial")
        self.assertIn("face_source_unavailable", [warning["code"] for warning in metadata["warnings"]])

    def test_selected_stripped_body_and_face_still_receive_missing_eyes_only(self):
        self.body.write_bytes(bundle([("body.assets", self.scene("Body")), ("face.assets", self.scene("Face"))]))
        (self.library / "complete_original.unity").write_bytes(self.donor())
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(metadata["faces"]["added"], 1)

    def test_selected_stripped_body_and_eyes_receive_missing_face_only(self):
        self.body.write_bytes(bundle([("body.assets", self.scene("Body")), ("eyes.assets", self.scene("Eyes"))]))
        (self.library / "complete_original.unity").write_bytes(self.donor())
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body", "Eyes", "Face"])
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(metadata["faces"]["added"], 1)

    def test_selected_mouth_does_not_claim_eyes_are_complete(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name)) for name in ("Body", "Face", "Mouth")]))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Mouth"])
        self.assertEqual(metadata["faces"]["status"], "unavailable")

    def test_mouth_only_donor_cannot_supply_missing_eyes(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name)) for name in ("Body", "Face")]))
        (self.library / "mouth_only.unity").write_bytes(self.scene("Mouth"))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body", "Face"])
        self.assertEqual(metadata["faces"]["status"], "unavailable")
        self.assertEqual(metadata["faces"]["added"], 0)

    def test_accepted_eye_donor_retains_missing_auxiliary_parts_only(self):
        self.body.write_bytes(bundle([(name + ".assets", self.scene(name)) for name in ("Body", "Face", "Mouth")]))
        names = ("Body", "Hair", "Face", "Eyes", "Mouth", "EyeBrow", "Teeth", "Tongue")
        (self.library / "original_facial_parts.unity").write_bytes(bundle([(name + ".assets", self.scene(name)) for name in names]))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Mouth", "Eyes", "EyeBrow", "Teeth", "Tongue"])
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(metadata["faces"]["added"], 4)

    def test_two_accepted_donors_do_not_duplicate_auxiliary_mouth(self):
        for filename, names in (("a_face.unity", ("Face", "Mouth")), ("b_eyes.unity", ("Eyes", "Mouth"))):
            (self.library / filename).write_bytes(bundle([(name + ".assets", self.scene(name)) for name in names]))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(glb_names(metadata), ["Body", "Face", "Mouth", "Eyes"])
        self.assertEqual(metadata["faces"]["status"], "added")
        self.assertEqual(metadata["faces"]["added"], 3)

    def test_face_and_eyes_can_come_from_separate_same_owner_sources(self):
        (self.library / "base_face.unity").write_bytes(self.scene("Face"))
        (self.library / "dynamic_eyes.unity").write_bytes(self.scene("Eyes"))
        metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(set(glb_names(metadata)), {"Body", "Face", "Eyes"})
        self.assertEqual(metadata["faces"]["status"], "added")


class DownloadTests(unittest.TestCase):
    def test_eye_completion_excludes_auxiliary_facials_even_in_dynamic_prefab(self):
        for name in ("Mouth", "Teeth", "Tongue", "EyeBrow", "EyeLash", "EyeClose", "FaceClosed"):
            with self.subTest(name=name):
                self.assertNotEqual(faces.facial_role(name, "Face", dynamic=True), "eyes")
        for name in ("Eyes", "LeftEye", "EyeL", "Eye_L", "Iris", "Pupil"):
            with self.subTest(name=name):
                self.assertEqual(faces.facial_role(name, name), "eyes")
        self.assertEqual(faces.facial_role("Face", "Face", dynamic=True), "eyes")

    def test_stream_is_bounded_without_content_length(self):
        class Response(io.BytesIO):
            headers = {}
        response = Response(b"123456789")
        opener = type("Opener", (), {"open": lambda self, *a, **kw: response})()
        with patch.object(faces, "build_opener", return_value=opener), self.assertRaises(faces.FaceUnavailable):
            faces._download("https://example.invalid/static/pack", None, time.monotonic() + 10, 4)

    def test_cache_hash_validation_rejects_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack"
            faces._save(path, b"1234")
            self.assertEqual(faces._cached(path, 4), b"1234")
            path.write_bytes(b"4321")
            self.assertIsNone(faces._cached(path, 4))


class DownloadWorkerTests(unittest.TestCase):
    def setUp(self):
        self.slot = threading.BoundedSemaphore(1)
        self.patch_slot = patch.object(faces, "_DOWNLOAD_SLOT", self.slot)
        self.patch_slot.start()
        self.gates = []

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        self.assertTrue(self.slot.acquire(timeout=1), "The test left a network worker running")
        self.slot.release()
        self.patch_slot.stop()

    def test_blocked_dns_returns_on_deadline_with_one_daemon_and_no_queue(self):
        entered, gate = threading.Event(), threading.Event()
        self.gates.append(gate)
        calls = []

        class Response(io.BytesIO):
            headers = {"Content-Length": "4"}

        def open_request(*args, **kwargs):
            calls.append(kwargs["timeout"])
            entered.set()
            gate.wait(2)  # Model an OS getaddrinfo that ignores socket timeout.
            return Response(b"data")

        opener = type("Opener", (), {"open": staticmethod(open_request)})()
        with patch.object(faces, "build_opener", return_value=opener):
            start = time.monotonic()
            with self.assertRaises(faces.FaceUnavailable):
                faces._download_with_deadline("https://example.invalid/static/pack", 4, start + .03)
            self.assertLess(time.monotonic() - start, .5)
            self.assertTrue(entered.is_set())
            self.assertEqual(len(calls), 1)
            workers = [thread for thread in threading.enumerate() if thread.name == "viewer-face-download"]
            self.assertEqual(len(workers), 1)
            self.assertTrue(workers[0].daemon)
            with self.assertRaisesRegex(faces.FaceUnavailable, "still finishing"):
                faces._download_with_deadline("https://example.invalid/static/another", 4, time.monotonic() + 1)
            self.assertEqual(len(calls), 1)
            gate.set()
            self.assertTrue(self.slot.acquire(timeout=1))
            self.slot.release()
            self.assertEqual(faces._download_with_deadline("https://example.invalid/static/recovered", 4, time.monotonic() + 1), b"data")
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(0 < timeout <= 8 for timeout in calls))

    def test_deadline_is_rechecked_even_when_wait_reports_completion(self):
        with patch.object(faces, "_download", return_value=b"data"), \
                patch.object(faces.time, "monotonic", side_effect=[0., 0., 2.]):
            with self.assertRaises(faces.FaceUnavailable):
                faces._download_with_deadline("https://example.invalid/static/pack", 4, 1.)

    def test_worker_exception_releases_slot_and_normal_success_is_unchanged(self):
        with patch.object(faces, "_download", side_effect=OSError("network failed")):
            with self.assertRaisesRegex(OSError, "network failed"):
                faces._download_with_deadline("https://example.invalid/static/pack", 4, time.monotonic() + 1)
        with patch.object(faces, "_download", return_value=b"data"):
            self.assertEqual(faces._download_with_deadline("https://example.invalid/static/pack", 4, time.monotonic() + 1), b"data")

    def test_thread_start_failure_releases_the_reserved_slot(self):
        with patch.object(faces.threading, "Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("thread unavailable")
            with self.assertRaises(faces.FaceUnavailable):
                faces._download_with_deadline("https://example.invalid/static/pack", 4, time.monotonic() + 1)
        self.assertTrue(self.slot.acquire(blocking=False))
        self.slot.release()


class OptionalBudgetTests(unittest.TestCase):
    """Clock-driven integration checks: optional work cannot erase a valid GLB."""

    setUpClass = classmethod(FaceTests.setUpClass.__func__)
    setUp = FaceTests.setUp
    tearDown = FaceTests.tearDown
    scene = FaceTests.scene
    donor = FaceTests.donor
    plan = FaceTests.plan

    def baseline(self):
        metadata = viewer.prepare([str(self.body)])
        return viewer.get_model(metadata["id"]), dict(metadata["stats"])

    def test_constructor_uses_optional_deadline_after_body_finishes(self):
        base_bytes, base_stats = self.baseline()
        clock = [0.]
        geometry, initialize = viewer._geometry, faces.FacePlan.__init__
        calls = []

        def body_geometry(*args, **kwargs):
            calls.append(clock[0])
            clock[0] += 70
            return geometry(*args, **kwargs)

        def costly_metadata(plan, scene, paths, context, deadline):
            if context and context.get("enabled", True):
                self.assertEqual(deadline, 110.)
                self.assertEqual(scene.deadline, deadline)
                clock[0] = deadline + 1
            initialize(plan, scene, paths, context, deadline)

        with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(viewer, "_geometry", side_effect=body_geometry), \
                patch.object(faces.FacePlan, "__init__", costly_metadata):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
            result = viewer.get_model(metadata["id"])
        self.assertEqual(calls, [0.])
        self.assertEqual(result, base_bytes)
        self.assertEqual(metadata["stats"], base_stats)
        self.assertEqual(metadata["faces"]["status"], "unavailable")

    def test_body_retains_original_allowance_when_optional_resolution_expires(self):
        base_bytes, _ = self.baseline()
        clock, order, body_deadlines = [0.], [], []
        geometry, environment = viewer._geometry, viewer._environment

        def load_body(paths, deadline, base_env=None):
            if base_env is None:
                body_deadlines.append(deadline)
            return environment(paths, deadline, base_env=base_env)

        def slow_body(*args, **kwargs):
            order.append("body")
            clock[0] = 119
            return geometry(*args, **kwargs)

        def expired_resolution(plan):
            order.append("faces")
            self.assertEqual(plan.deadline, 159.)
            clock[0] = 159
            return []

        with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(viewer, "_geometry", side_effect=slow_body), \
                patch.object(viewer, "_environment", side_effect=load_body), \
                patch.object(faces.FacePlan, "resolve", expired_resolution):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
            result = viewer.get_model(metadata["id"])
        self.assertEqual(order, ["body", "faces"])
        self.assertEqual(body_deadlines, [120.])
        self.assertEqual(result, base_bytes)
        self.assertEqual(metadata["faces"]["added"], 0)

    def test_optional_allowance_does_not_extend_selected_body_deadline(self):
        geometry = viewer._geometry

        for expired_at in (120., 121.):
            with self.subTest(body_finished_at=expired_at):
                clock = [0.]

                def expired_body(*args, **kwargs):
                    clock[0] = expired_at
                    return geometry(*args, **kwargs)

                with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                        patch.object(viewer, "_geometry", side_effect=expired_body), \
                        patch.object(faces.FacePlan, "resolve") as resolve:
                    with self.assertRaisesRegex(viewer.ModelViewerError, "took too long"):
                        viewer.prepare([str(self.body)], face_context=self.context)
                resolve.assert_not_called()
                self.assertFalse(viewer._SESSIONS)

    def test_partial_optional_append_timeout_returns_immutable_base(self):
        base_bytes, base_stats = self.baseline()
        (self.library / "donor.unity").write_bytes(self.donor())
        clock, converted = [0.], []
        geometry = viewer._geometry

        def timed_geometry(mesh, *args, **kwargs):
            name = mesh.peek_name()
            converted.append(name)
            clock[0] = {"Body": 50., "Face": 60., "Eyes": 91.}[name]
            return geometry(mesh, *args, **kwargs)

        with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(viewer, "_geometry", side_effect=timed_geometry):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
            result = viewer.get_model(metadata["id"])
        self.assertEqual(converted, ["Body", "Face", "Eyes"])
        self.assertEqual(result, base_bytes)
        self.assertEqual(metadata["stats"], base_stats)
        self.assertEqual(metadata["faces"]["added"], 0)

    def test_failed_optional_load_does_not_reload_selected_body(self):
        base_bytes, _ = self.baseline()
        donor = self.library / "donor.unity"
        donor.write_bytes(self.donor())
        environment = viewer._environment
        selected_loads = []

        def fail_additional(paths, deadline, base_env=None):
            if base_env is not None:
                self.assertEqual(paths, [str(donor)])
                raise viewer.ModelViewerError("optional file failed")
            selected_loads.append(list(paths))
            return environment(paths, deadline)

        with patch.object(viewer, "_environment", side_effect=fail_additional):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(selected_loads.count([str(self.body)]), 1)
        self.assertEqual(viewer.get_model(metadata["id"]), base_bytes)

    def test_name_discovery_never_reads_full_mesh_or_texture_typetree(self):
        from UnityPy.files.ObjectReader import ObjectReader
        original = ObjectReader.read_typetree
        reads = []

        def guarded(obj, *args, **kwargs):
            if obj.type.name in ("Mesh", "Texture2D") and kwargs.get("nodes") is None:
                reads.append(obj.type.name)
                raise AssertionError("Metadata must peek names, not expand vertex/pixel payloads")
            return original(obj, *args, **kwargs)

        with patch.object(ObjectReader, "read_typetree", guarded):
            plan = self.plan()
        self.assertEqual(plan.owner, 207)
        self.assertEqual(plan.needed, {"face", "eyes"})
        self.assertEqual(reads, [])


class ActualFacialSourceTests(unittest.TestCase):
    """Optional local user-source proof; proprietary assets are never committed."""

    @classmethod
    def setUpClass(cls):
        cls.costume = os.environ.get("SIFAS_FACE_TEST_COSTUME")
        cls.facial = os.environ.get("SIFAS_FACE_TEST_BUNDLE")
        cls.eye_table = os.environ.get("SIFAS_FACE_TEST_EYE_TABLE")
        if not cls.costume or not cls.facial:
            raise unittest.SkipTest("Set SIFAS_FACE_TEST_COSTUME and SIFAS_FACE_TEST_BUNDLE for actual facial-source checks")

    def test_actual_local_facial_meshes_align_and_reuse_unchanged_costume_material(self):
        paths = [Path(self.costume), Path(self.facial)]
        if self.eye_table:
            paths.append(Path(self.eye_table))
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        baseline = viewer.prepare([self.costume])
        base_bytes = viewer.get_model(baseline["id"])

        def unpack(data):
            length, = struct.unpack_from("<I", data, 12)
            return json.loads(data[20:20 + length]), data[28 + length:]

        base_doc, base_binary = unpack(base_bytes)
        with tempfile.TemporaryDirectory() as directory, patch.object(faces, "_download_with_deadline") as download:
            metadata = viewer.prepare([self.costume], face_context={
                "enabled": True, "allow_download": False, "cache_dir": directory,
                "library_roots": [str(path.parent) for path in paths[1:]]})
        download.assert_not_called()
        doc, binary = unpack(viewer.get_model(metadata["id"]))
        self.assertEqual(metadata["faces"], {"enabled": True, "status": "added", "added": 5, "characters": [207]})
        self.assertEqual(metadata["stats"], {"meshes": 8, "vertices": 10525, "triangles": 13173, "materials": 2, "textures": 2})
        self.assertEqual(metadata["warnings"], [])
        self.assertEqual(binary[:len(base_binary)], base_binary)  # exact geometry/UV/PNG bytes of the selected costume
        self.assertEqual(doc["meshes"][:3], base_doc["meshes"])
        head_material = next(mesh["primitives"][0]["material"] for mesh in base_doc["meshes"] if mesh["name"] == "Face")
        self.assertEqual(doc["materials"][head_material]["pbrMetallicRoughness"]["baseColorFactor"], [1, 1, 1, 1])
        added = doc["meshes"][3:]
        self.assertEqual({mesh["name"] for mesh in added}, {"Eye", "Eye_Around", "Mouth", "LeftEyeWhiteLine", "RightEyeWhiteLine"})
        self.assertTrue(all(primitive["material"] == head_material for mesh in added for primitive in mesh["primitives"]))
        eye = next(mesh for mesh in added if mesh["name"] == "Eye")
        bounds = doc["accessors"][eye["primitives"][0]["attributes"]["POSITION"]]
        self.assertEqual(bounds["count"], 98)
        self.assertTrue(1.45 < bounds["min"][1] < bounds["max"][1] < 1.49)
        self.assertTrue(0.07 < bounds["min"][2] < bounds["max"][2] < .08)
        self.assertEqual({str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}, before)


if __name__ == "__main__":
    unittest.main()
