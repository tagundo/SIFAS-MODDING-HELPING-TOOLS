"""Automatic facial-source discovery, tested with original synthetic geometry."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
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
            if context:
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
        clock, order = [0.], []
        geometry = viewer._geometry

        def slow_body(*args, **kwargs):
            order.append("body")
            clock[0] = 119
            return geometry(*args, **kwargs)

        def expired_resolution(plan):
            order.append("faces")
            self.assertEqual(plan.deadline, 120.)
            clock[0] = 120
            return []

        with patch.object(viewer.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(viewer, "_geometry", side_effect=slow_body), \
                patch.object(faces.FacePlan, "resolve", expired_resolution):
            metadata = viewer.prepare([str(self.body)], face_context=self.context)
            result = viewer.get_model(metadata["id"])
        self.assertEqual(order, ["body", "faces"])
        self.assertEqual(result, base_bytes)
        self.assertEqual(metadata["faces"]["added"], 0)

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


if __name__ == "__main__":
    unittest.main()
