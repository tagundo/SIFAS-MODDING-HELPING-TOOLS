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

    def scene(self, name, owner=207, platform=13):
        env = self.UnityPy.load(FIXTURE.read_bytes())
        # Author the intended platform of this test input.
        for asset in env.assets:
            asset.target_platform = platform
            asset._m_target_platform = platform
        for obj in env.objects:
            if obj.type.name in ("GameObject", "Mesh", "Material"):
                tree = obj.read_typetree()
                tree["m_Name"] = (f"ch{owner:04}_co0000_head" if owner is not None else "GenericMaterial") if obj.type.name == "Material" else name
                obj.save_typetree(tree)
        return next(iter(env.files.values())).save()

    def donor(self, owner=207, platform=13):
        return bundle([(name + ".assets", self.scene(name, owner, platform)) for name in ("Body", "Hair", "Face", "Eyes")])

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

    def write_companion_hint(self, companion, *, body_digest=None, face_digest=None, file_name=None):
        hint = {"version": 1, "body": {"file": self.body.name,
            "sha256": body_digest or hashlib.sha256(self.body.read_bytes()).hexdigest()},
            "companions": [{"file": file_name or companion.name,
                "sha256": face_digest or hashlib.sha256(companion.read_bytes()).hexdigest()}]}
        (self.selected / faces.COMPANION_HINT).write_text(json.dumps(hint), encoding='utf-8')

    def test_verified_saved_face_precedes_owner_named_original_and_catalog(self):
        edited = self.selected / 'custom-edited-face.unity'
        edited.write_bytes(self.donor())
        (self.library / 'ch0207_facedynamic.unity').write_bytes(self.donor())
        self.write_companion_hint(edited)
        plan = self.plan()
        with patch.object(plan, '_known_local') as known, patch.object(plan, '_descriptor_iter') as catalog:
            self.assertEqual(plan.resolve(), [str(edited)])
        known.assert_not_called(); catalog.assert_not_called()
        self.assertEqual(plan.status, 'added')

    def test_saved_face_hint_requires_both_current_body_and_face_hashes(self):
        edited = self.selected / 'edited.unity'
        edited.write_bytes(self.donor())
        for body_digest, face_digest in (('0' * 64, None), (None, '0' * 64)):
            with self.subTest(body=body_digest, face=face_digest):
                self.write_companion_hint(edited, body_digest=body_digest, face_digest=face_digest)
                plan = self.plan()
                self.assertEqual(list(plan._verified_companions()), [])
                self.assertEqual(plan._hint_sources, {})

    def test_saved_face_hint_rejects_outside_paths_symlinks_and_large_json(self):
        outside = self.root / 'outside.unity'
        outside.write_bytes(self.donor())
        link = self.selected / 'linked.unity'
        link.symlink_to(outside)
        for name in ('../outside.unity', str(outside), 'linked.unity'):
            with self.subTest(name=name):
                self.write_companion_hint(outside, file_name=name)
                self.assertEqual(list(self.plan()._verified_companions()), [])
        (self.selected / faces.COMPANION_HINT).write_bytes(b' ' * (faces.MAX_HINT_BYTES + 1))
        self.assertEqual(list(self.plan()._verified_companions()), [])

    def test_saved_face_hint_still_rejects_wrong_character(self):
        edited = self.selected / 'edited.unity'
        edited.write_bytes(bundle([(role + '.assets', self.scene(role, owner=208)) for role in ('Face', 'Eyes')]))
        self.write_companion_hint(edited)
        plan = self.plan()
        candidates = list(plan._verified_companions())
        self.assertEqual(candidates, [str(edited)])
        self.assertFalse(plan._accept(candidates[0]))
        self.assertEqual(plan.auto_paths, [])

    def test_compatible_saved_edited_face_keeps_priority_for_generic_or_known_body(self):
        for body_platform, face_platform, stock_platform in [(-2, 9, 13), (9, -2, 9)]:
            with self.subTest(body=body_platform, face=face_platform):
                self.body.write_bytes(self.scene('Body', platform=body_platform))
                saved = self.selected / 'saved-edited-face.unity'
                environment = self.UnityPy.load(self.donor(platform=face_platform))
                for obj in environment.objects:
                    if obj.type.name == 'Texture2D':
                        tree = obj.read_typetree(); tree['image data'] = bytes([90, 20, 210, 255]) * 4; obj.save_typetree(tree)
                edited = environment.file.save(); saved.write_bytes(edited)
                (self.library / 'ch0207_facedynamic.unity').write_bytes(self.donor(platform=stock_platform))
                self.write_companion_hint(saved)
                plan = self.plan()
                with patch.object(plan, '_known_local') as known, patch.object(plan, '_descriptor_iter') as catalogs:
                    paths = plan.resolve()
                    known.assert_not_called(); catalogs.assert_not_called()
                self.assertEqual(paths, [str(saved)])
                self.assertEqual(saved.read_bytes(), edited)
                self.assertEqual({int(a.target_platform) for a in self.UnityPy.load(edited).assets}, {face_platform})

    def test_saved_face_of_same_character_takes_priority_with_either_mobile_header(self):
        for body_platform, face_platform in ((9, 13), (13, 9)):
            with self.subTest(body=body_platform, face=face_platform):
                self.body.write_bytes(self.scene('Body', platform=body_platform))
                saved = self.selected / 'saved-edited-face.unity'
                original = bundle([(role + '.assets', self.scene(role, platform=face_platform)) for role in ('Face', 'Eyes')])
                saved.write_bytes(original)
                (self.library / 'ch0207_facedynamic.unity').write_bytes(self.donor(platform=body_platform))
                self.write_companion_hint(saved)
                plan = self.plan()
                with patch.object(plan, '_known_local') as known:
                    self.assertEqual(plan.resolve(), [str(saved)])
                known.assert_not_called()
                self.assertEqual(saved.read_bytes(), original)

    def test_saved_face_stays_bound_when_body_already_has_a_complete_face(self):
        self.body.write_bytes(bundle([(role + '.assets', self.scene(role)) for role in ('Body', 'Face', 'Eyes')]))
        saved = self.selected / 'custom-edited-face.unity'
        saved.write_bytes(bundle([(role + '.assets', self.scene(role)) for role in ('Face', 'Eyes')]))
        self.write_companion_hint(saved)
        plan = self.plan()
        self.assertFalse(plan.needed)
        self.assertEqual(plan.resolve(), [str(saved)])
        self.assertEqual(plan.saved_paths, {str(saved)})
        self.assertEqual(plan.source_roles[str(saved)], set())
        self.assertEqual(plan.status, 'already_present')

    def test_ambiguous_bound_face_is_not_silently_replaced_with_stock(self):
        self.body.write_bytes(self.scene('Body', platform=9))
        saved = self.selected / 'saved-mixed-face.unity'
        original = bundle([('face.assets', self.scene('Face', platform=9)),
                           ('eyes.assets', self.scene('Eyes', platform=13))])
        saved.write_bytes(original)
        (self.library / 'ch0207_facedynamic.unity').write_bytes(self.donor(platform=9))
        self.write_companion_hint(saved)
        with self.assertRaisesRegex(viewer.ModelViewerError, "saved-mixed-face.unity.*ambiguous"):
            viewer.prepare([str(self.body)], face_context=self.context)
        self.assertEqual(saved.read_bytes(), original)

    def test_ios_body_rejects_android_face_from_known_cache_and_database_routes(self):
        self.body.write_bytes(self.scene('Body', platform=9))
        correct = self.library / 'correct-ios-face.unity'; correct.write_bytes(self.donor(platform=9))
        for route in ('known', 'cache', 'database'):
            with self.subTest(route=route):
                if route == 'cache':
                    wrong = Path(self.context['cache_dir']) / 'models' / ('ch0207_' + 'a' * 24 + '.unity')
                    faces._save(wrong, self.donor(platform=13), 207)
                else:
                    wrong = self.library / ('ch0207_facedynamic.unity' if route == 'known' else 'database-android-face.unity')
                    wrong.write_bytes(self.donor(platform=13))
                plan = self.plan()
                if route == 'database':
                    def resource(*args, **kwargs):
                        plan.database_paths.add(str(wrong)); return str(wrong)
                    with patch.object(plan, '_known_local', return_value=iter(())), \
                            patch.object(plan, '_descriptor_iter', return_value=iter([{'test':'descriptor'}])), \
                            patch.object(plan, '_resource', side_effect=resource), \
                            patch.object(plan, '_local', return_value=[str(correct)]):
                        paths = plan.resolve()
                else:
                    with patch.object(plan, '_descriptor_iter', return_value=iter(())), \
                            patch.object(plan, '_local', return_value=[str(correct)]):
                        paths = plan.resolve()
                self.assertEqual(paths, [str(correct)])
                self.assertNotIn(str(wrong), plan.auto_paths)

    @EXTRACTOR_REQUIRED
    def test_catalog_candidates_follow_concrete_body_platform_without_guessing_notarget(self):
        self.databases(self.donor())
        root = Path(self.context['repo_root']) / 'assets/db/gl'
        (root / 'asset_i_en.db').write_bytes((root / 'asset_a_en.db').read_bytes())
        with sqlite3.connect(root / 'asset_i_en.db') as db:
            db.execute("UPDATE member_model SET pack_name='ios207'")
            db.execute("UPDATE m_asset_package_mapping SET pack_name='ios207'")
        for platform, expected in [(9, ['ios207']), (13, ['pack207']), (-2, ['pack207', 'ios207'])]:
            with self.subTest(platform=platform):
                self.body.write_bytes(self.scene('Body', platform=platform))
                self.assertEqual([row['pack_name'] for row in self.plan()._descriptor_iter()], expected)

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

    def test_eight_selected_inputs_still_complete_original_face_from_offline_cache(self):
        donor = self.donor()
        cached = Path(self.context["cache_dir"]) / "models" / ("ch0207_" + hashlib.sha256(donor).hexdigest()[:24] + ".unity")
        cached.parent.mkdir(parents=True)
        faces._save(cached, donor, 207)
        selected = [str(self.body)]
        for index in range(7):
            env = self.UnityPy.load(FIXTURE.with_name("viewer_rig.unity").read_bytes())
            for obj in list(env.objects):
                if obj.type.name == "AnimationClip":
                    tree = obj.read_typetree(); tree["m_Name"] = "User motion " + str(index); obj.save_typetree(tree)
                else:
                    del obj.assets_file.objects[obj.path_id]
            path = self.selected / ("motion-" + str(index) + ".unity")
            path.write_bytes(env.file.save()); selected.append(str(path))
        originals = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in [*selected, str(cached)]}
        def geometry(metadata):
            raw = viewer.get_model(metadata["id"]); length, = struct.unpack_from("<I", raw, 12)
            document, binary = json.loads(raw[20:20 + length]), raw[28 + length:]
            result = []
            for mesh in document["meshes"]:
                for primitive in mesh["primitives"]:
                    for name, ident in sorted({**primitive["attributes"], "indices": primitive["indices"]}.items()):
                        accessor = document["accessors"][ident]; view = document["bufferViews"][accessor["bufferView"]]
                        start = view.get("byteOffset", 0)
                        result.append((mesh["name"], name, binary[start:start + view["byteLength"]]))
            return result
        with patch.object(faces.FacePlan, "_descriptor_iter", side_effect=AssertionError("Offline face completion must not query a catalog")) as catalog, \
                patch.object(faces, "_download_with_deadline", side_effect=AssertionError("Offline cached face must not download")) as download:
            initial = viewer.prepare([str(self.body)], face_context=self.context)
            expected = geometry(initial)
            full = viewer.prepare(selected, face_context=self.context)
        self.assertEqual(full["source_names"], [Path(path).name for path in selected])
        self.assertEqual(full["faces"], initial["faces"])
        self.assertEqual(full["faces"]["status"], "added")
        self.assertEqual(glb_names(full), ["Body", "Face", "Eyes"])
        self.assertEqual(full["stats"], initial["stats"])
        self.assertEqual(geometry(full), expected)
        catalog.assert_not_called(); download.assert_not_called()
        self.assertEqual(originals, {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in originals})
        with self.assertRaisesRegex(viewer.ModelViewerError, "between one and eight"):
            viewer.prepare([*selected, str(cached)], face_context=self.context)

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

    def test_body_part_manager_reference_names_only_its_own_external_face_cab(self):
        # Neutral component stand-ins: only the serialized reference fields
        # FacePlan reads are declared, with no game assets bundled.
        def scene(face, *, script="BodyPartManager", namespace="LLAS.Components.Members",
                  head_material=True, source="costume", externals=2):
            paths = ["archive:/CAB-00ff/CAB-00ff", "archive:/cab-a1b2/CAB-A1B2"][:externals]
            assets = SimpleNamespace(objects={}, externals=[SimpleNamespace(path=path) for path in paths],
                                     preview_source_path=source, parent=None)
            definition = SimpleNamespace(type=SimpleNamespace(name="MonoScript"), path_id=7, assets_file=assets,
                                         tree={"m_ClassName": script, "m_Namespace": namespace,
                                               "m_AssemblyName": "Assembly-CSharp.dll"})
            tree = {"m_Script": {"m_FileID": 0, "m_PathID": 7}, "face": face}
            if head_material:
                tree["headMaterial"] = {"m_FileID": 0, "m_PathID": 9}
            manager = SimpleNamespace(type=SimpleNamespace(name="MonoBehaviour"), path_id=5, assets_file=assets, tree=tree)
            assets.objects.update({5: manager, 7: definition})
            return SimpleNamespace(env=SimpleNamespace(objects=[manager, definition]), tree=lambda obj: obj.tree)
        plan = faces.FacePlan.__new__(faces.FacePlan)
        external = {"m_FileID": 2, "m_PathID": 11}
        self.assertEqual(plan._face_references(scene(external), {"costume"}), {"cab-a1b2"})
        self.assertEqual(plan._face_references(scene({"m_FileID": 1, "m_PathID": 11}), {"costume"}), {"cab-00ff"})
        for label, value, sources in (
                ("internal face", scene({"m_FileID": 0, "m_PathID": 11}), {"costume"}),
                ("missing external", scene(external, externals=1), {"costume"}),
                ("null face", scene({"m_FileID": 2, "m_PathID": 0}), {"costume"}),
                ("boolean file id", scene({"m_FileID": True, "m_PathID": 11}), {"costume"}),
                ("other component", scene(external, script="MemberFace"), {"costume"}),
                ("other namespace", scene(external, namespace="Other"), {"costume"}),
                ("no head material", scene(external, head_material=False), {"costume"}),
                ("unselected source", scene(external, source="face"), {"costume"})):
            with self.subTest(label):
                self.assertEqual(plan._face_references(value, sources), set())

    def referenced_donor(self, cab):
        """One same-owner face/eyes donor whose serialized files carry ``cab``."""
        return bundle([(cab, self.scene("Face")), (cab + "-eyes", self.scene("Eyes"))])

    def test_cached_face_the_body_references_precedes_another_cached_member_face(self):
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        # The first name in cache order is another prefab of the same member,
        # e.g. an installed costume's private face cached by an earlier open.
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        referenced = directory / ("ch0207_" + "b" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        faces._save(referenced, self.referenced_donor("CAB-" + "2" * 32), 207)
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces.FacePlan, "_local", return_value=[]) as broad, \
                patch.object(faces, "_download") as fetch:
            plan = self.plan()
            self.assertEqual(plan.resolve(), [str(referenced)])
        self.assertEqual(plan.status, "added")
        self.assertEqual(plan.source_roles[str(referenced)], {"face", "eyes"})
        broad.assert_not_called()
        fetch.assert_not_called()

    def test_member_faces_without_the_referenced_one_keep_their_earlier_order(self):
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        first = directory / ("ch0207_" + "a" * 24 + ".unity")
        second = directory / ("ch0207_" + "b" * 24 + ".unity")
        faces._save(first, self.referenced_donor("CAB-" + "1" * 32), 207)
        faces._save(second, self.referenced_donor("CAB-" + "2" * 32), 207)
        # A mod renamed its face but left it out: neither cached face is it.
        # The library is searched for it once, then the earlier order applies.
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                patch.object(faces.FacePlan, "_local", return_value=[]) as broad, \
                patch.object(faces, "_download") as fetch:
            plan = self.plan()
            self.assertEqual(plan.resolve(), [str(first)])
        self.assertEqual(plan.status, "added")
        broad.assert_called_once_with()
        fetch.assert_not_called()
        # Without any body reference the same order applies, as before.
        with patch.object(faces.FacePlan, "_face_references", return_value=set()):
            self.assertEqual(self.plan().resolve(), [str(first)])

    def game_catalog(self, model, dependencies, rows, name="asset_a_en.db"):
        root = Path(self.context["repo_root"]) / "assets" / "db" / "gl"
        root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(root / name) as db:
            db.executescript("CREATE TABLE member_model(asset_path TEXT,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);"
                             "CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT);"
                             "CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER);")
            db.executemany("INSERT INTO member_model_dependency VALUES(?,?)", [(model, value) for value in dependencies])
            db.executemany("INSERT INTO member_model VALUES(?,?,?,?,?,?)", rows)
            db.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?,?)",
                           [("suit:900000001", row[1], row[3]) for row in rows])

    def test_game_import_uses_its_own_suit_face_before_a_cached_member_face(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        stock = self.donor()
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        cached = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(cached, stock, 207)
        private = self.library / "installed_private_face.unity"
        private.write_bytes(bundle([(name + ".assets", self.scene(name)) for name in ("Face", "Eyes", "Private")]))
        self.game_catalog("installedbody", ["privateface", "§shader", "installedbody"],
                          [("privateface", "privatepack", 0, private.stat().st_size, 0, 0),
                           ("installedbody", "bodypack", 0, self.body.stat().st_size, 0, 0)])
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": False,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "en"}
        requested = []

        def resource(plan, descriptor, download=True):
            # The decrypted installed pack; the catalog row selects it.
            requested.append(descriptor["asset_path"])
            if descriptor["asset_path"] != "privateface":
                raise faces.FaceUnavailable("Only the private face pack is local")
            return str(private)

        with patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), \
                patch.object(faces.FacePlan, "_resource", resource), \
                patch.object(faces.FacePlan, "_local", return_value=[]):
            viewer_mod_sources.register_game_import(str(self.body), record)
            plan = self.plan()
            # Its own catalog dependencies, never the selected body again.
            self.assertEqual([row["asset_path"] for row in plan._selected_iter()], ["privateface"])
            self.assertEqual(plan.resolve(), [str(private)])
            self.assertEqual(requested[0], "privateface")
            self.assertNotIn("installedbody", requested)
            # The receipt binds the bytes: an edited body is no longer that
            # game costume, and falls back to the member's cached face.
            original = self.body.read_bytes()
            self.body.write_bytes(self.scene("Body2"))
            self.assertEqual(self.plan().resolve(), [str(cached)])
            self.body.write_bytes(original)
            self.assertEqual(self.plan().resolve(), [str(private)])
            digest = hashlib.sha256(original).hexdigest()
            found = viewer_mod_sources.imported_record(str(self.body), digest)
            self.assertEqual(found, record)
            found["model"] = "changed"
            self.assertEqual(viewer_mod_sources.imported_record(str(self.body), digest)["model"], "installedbody")
            for path, value in ((str(self.body), "0" * 64), (str(self.body), digest.upper()), (str(self.body), None),
                                (str(self.selected / "other.unity"), digest)):
                self.assertIsNone(viewer_mod_sources.imported_record(path, value))
            # Another imported path does not lend its suit to this body.
            viewer_mod_sources._REGISTRY.clear()
            other = self.selected / "other.unity"
            other.write_bytes(original)
            viewer_mod_sources.register_game_import(str(other), record)
            self.assertEqual(self.plan().resolve(), [str(cached)])

    def test_selected_suit_face_download_precedes_another_cached_member_face(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        private = self.library / "downloaded_private_face.unity"
        private.write_bytes(self.referenced_donor("CAB-" + "2" * 32))
        self.game_catalog("installedbody", ["privateface"], [("privateface", "privatepack", 0, private.stat().st_size, 0, 0)])
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": True,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "en"}
        calls = []

        def resource(plan, descriptor, download=True):
            calls.append((descriptor["asset_path"], download))
            if not download:
                raise faces.FaceUnavailable("The suit's face pack is not local yet")
            return str(private)

        self.context["allow_download"] = True
        with patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), \
                patch.object(faces.FacePlan, "_resource", resource), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces.FacePlan, "_local", return_value=[]) as broad:
            viewer_mod_sources.register_game_import(str(self.body), record)
            self.assertEqual(self.plan().resolve(), [str(private)])
            self.assertEqual(calls, [("privateface", False), ("privateface", True)])
            # Local files are searched once before anything is downloaded.
            broad.assert_called_once_with()
            # Offline, the earlier same-owner choice remains the fallback.
            calls.clear()
            self.context["allow_download"] = False
            self.assertEqual(self.plan().resolve(), [str(other)])
            self.assertEqual(calls, [("privateface", False)])

    def face_files(self, **faces_by_name):
        """Same-member face bundles outside every automatic search root."""
        directory = self.root / "packs"
        directory.mkdir(exist_ok=True)
        paths = {}
        for name, raw in faces_by_name.items():
            paths[name] = directory / (name + ".unity")
            paths[name].write_bytes(raw)
        return paths

    def recording_resource(self, files, calls, *, local=(), fail=()):
        """A catalog resource stand-in: ``local`` names need no download."""
        def resource(plan, descriptor, download=True):
            name = descriptor["asset_path"]
            calls.append((name, download))
            if name in fail or name not in files or not download and name not in local:
                raise faces.FaceUnavailable("Not available here")
            return str(files[name])
        return resource

    @staticmethod
    def catalog_descriptor(name, size=1000):
        return {"asset_path": name, "pack_name": name + "pack", "head": 0, "size": size,
                "key1": 0, "key2": 0, "pack_size": None}

    def test_plain_body_downloads_its_referenced_face_before_another_cached_member_face(self):
        # A stock body opened as a file after an installed costume's private
        # face was cached: the stock face it references is only on the CDN.
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        files = self.face_files(stockface=self.referenced_donor("CAB-" + "2" * 32))
        descriptor = self.catalog_descriptor("stockface")
        for allow, references, expected, requested in (
                (True, {"cab-" + "2" * 32}, files["stockface"], [("stockface", False), ("stockface", True)]),
                # Offline, the other cached prefab stays the fallback.
                (False, {"cab-" + "2" * 32}, other, [("stockface", False)]),
                # Without a body reference the old order never downloads first.
                (True, set(), other, [])):
            calls = []
            self.context["allow_download"] = allow
            with self.subTest(allow=allow, references=references), \
                    patch.object(faces.FacePlan, "_face_references", return_value=references), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([dict(descriptor)])), \
                    patch.object(faces.FacePlan, "_resource", self.recording_resource(files, calls)):
                plan = self.plan()
                self.assertEqual(plan.resolve(), [str(expected)])
                self.assertEqual(calls, requested)
                self.assertEqual(plan.status, "added")

    def test_failed_exact_download_is_tried_once(self):
        files = self.face_files(stockface=self.referenced_donor("CAB-" + "2" * 32))
        calls = []
        self.context["allow_download"] = True
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                patch.object(faces.FacePlan, "_resource", self.recording_resource(files, calls, fail={"stockface"})):
            plan = self.plan()
            self.assertEqual(plan.resolve(), [])
        self.assertEqual(calls, [("stockface", False), ("stockface", True)])
        self.assertEqual(plan.status, "unavailable")

    def test_downloaded_member_face_that_is_not_referenced_keeps_its_place_after_the_local_search(self):
        # The body references a face that exists nowhere. The default suit's
        # face is fetched to compare it, but the old order still applies: a
        # local same-member face comes before a downloaded original.
        local = self.library / "costume_face_copy.unity"
        local.write_bytes(self.referenced_donor("CAB-" + "4" * 32))
        files = self.face_files(stockface=self.referenced_donor("CAB-" + "2" * 32))
        calls = []
        self.context["allow_download"] = True
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                patch.object(faces.FacePlan, "_resource", self.recording_resource(files, calls)):
            self.assertEqual(self.plan().resolve(), [str(local)])
        self.assertEqual(calls, [("stockface", False), ("stockface", True)])
        # Without a body reference nothing is fetched before the local search.
        calls.clear()
        with patch.object(faces.FacePlan, "_face_references", return_value=set()), \
                patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                patch.object(faces.FacePlan, "_resource", self.recording_resource(files, calls)):
            self.assertEqual(self.plan().resolve(), [str(local)])
        self.assertEqual(calls, [("stockface", False)])
        # Without that local face the downloaded one is still used, once fetched.
        local.unlink()
        calls.clear()
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                patch.object(faces.FacePlan, "_resource", self.recording_resource(files, calls)):
            self.assertEqual(self.plan().resolve(), [str(files["stockface"])])
        self.assertEqual(calls, [("stockface", False), ("stockface", True)])

    def test_hung_exact_download_leaves_time_for_another_member_face(self):
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        observed = []

        def resource(plan, descriptor, download=True):
            if not download:
                raise faces.FaceUnavailable("Not local")
            # An unreachable CDN: the download waits for the caller's deadline.
            observed.append(plan.deadline)
            while time.monotonic() < plan.deadline:
                time.sleep(.02)
            raise faces.FaceUnavailable("Timed out")

        self.context["allow_download"] = True
        with patch.object(faces, "FACE_SECONDS", 8), patch.object(faces, "FALLBACK_SECONDS", 5), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                patch.object(faces.FacePlan, "_resource", resource):
            plan = self.plan()
            deadline = plan.deadline
            self.assertEqual(plan.resolve(), [str(other)])
        self.assertEqual(len(observed), 1)
        self.assertAlmostEqual(observed[0], deadline - 5, delta=.5)
        self.assertEqual(plan.deadline, deadline)

    @EXTRACTOR_REQUIRED
    def test_slow_referenced_download_with_nothing_else_at_hand_has_the_whole_face_time(self):
        # The referenced stock face is only on a slow but working CDN and no
        # other face exists: it is downloaded as before, with the face time.
        stock = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = self.databases(stock)
        payload = self.encrypted(stock, descriptor)
        calls = []

        def slow(url, expected, deadline, byte_limit=faces.MAX_PACK_BYTES):
            calls.append(deadline)
            time.sleep(1.5)
            return payload

        self.context["allow_download"] = True
        with patch.object(faces, "FACE_SECONDS", faces.FALLBACK_SECONDS + 1), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces, "_download", slow):
            plan = self.plan()
            deadline, started = plan.deadline, time.monotonic()
            chosen = plan.resolve()
        self.assertEqual([Path(path).read_bytes() for path in chosen], [stock])
        self.assertEqual(plan.status, "added")
        self.assertGreater(time.monotonic() - started, 1.4)
        # One download, given the whole face budget, and one byte reservation.
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0], deadline, delta=.01)
        self.assertEqual(plan.transferred, descriptor["pack_size"])

    @EXTRACTOR_REQUIRED
    def test_named_download_with_another_face_at_hand_goes_on_only_while_it_can_finish(self):
        # Another prefab of the member is cached; the referenced stock face is
        # on a slow but working CDN, about five seconds for the pack. With a
        # face time that leaves it room it is awaited and used; with one it
        # cannot meet, it is stopped once measured and the cached face is used.
        # The roomy case leaves several times the transfer time, because
        # packaged runs on shared CI machines read each chunk much slower.
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        stock = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = self.databases(stock)
        payload = self.encrypted(stock, descriptor)
        step = max(1, len(payload) // 100)
        self.context["allow_download"] = True
        for face_seconds, expected in ((faces.FALLBACK_SECONDS + 25, stock), (faces.FALLBACK_SECONDS + 4, None)):
            reads = []

            class Response(io.BytesIO):
                headers = {"Content-Length": str(len(payload))}

                def read(self, size=-1):
                    reads.append(time.monotonic())
                    time.sleep(.05)
                    return super().read(min(size, step))

            opener = type("Opener", (), {"open": lambda self, *a, **kw: Response(payload)})()
            slot = threading.BoundedSemaphore(1)
            for path in (Path(self.context["cache_dir"]) / "packs").glob("*"):
                path.unlink()
            for path in directory.glob("*.unity"):
                if path != other:
                    path.unlink()
            with self.subTest(face_seconds=face_seconds), \
                    patch.object(faces, "FACE_SECONDS", face_seconds), \
                    patch.object(faces, "_DOWNLOAD_SLOT", slot), patch.object(faces, "build_opener", return_value=opener), \
                    patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}):
                plan = self.plan()
                started = time.monotonic()
                chosen = plan.resolve()
                returned = time.monotonic()
                # Either way the one worker is free at once.
                self.assertTrue(slot.acquire(timeout=.5), "The stopped download kept running")
                slot.release()
                self.assertEqual(plan.transferred, descriptor["pack_size"])
                if expected is not None:
                    self.assertEqual([Path(path).read_bytes() for path in chosen], [expected])
                    self.assertGreater(returned - started, 4)
                    continue
                self.assertEqual(chosen, [str(other)])
                # Measured for MEASURE_SECONDS, then stopped at its next chunk.
                self.assertLess(returned - started, faces.MEASURE_SECONDS + 1)
                self.assertLess(reads[-1], returned + .2)
                # Its bytes were never published to the face cache.
                self.assertFalse((Path(self.context["cache_dir"]) / "packs" / descriptor["pack_name"]).exists())
                self.assertEqual(sorted(directory.glob("*.unity")), [other])

    @EXTRACTOR_REQUIRED
    def test_a_pack_is_requested_once_and_its_bytes_are_reserved_once(self):
        # The first pack answers 404 (a transient one: it would answer the
        # next time). Its second asset is not fetched again, so each pack is
        # requested, and its bytes reserved, once; the old order goes on with
        # the next candidate, used as the earlier choice when it is not the
        # face the body names.
        first, second, stock = (self.referenced_donor("CAB-" + digit * 32) for digit in "456")
        descriptors = [dict(self.descriptor(first, name="sharedpack"), asset_path="firstface"),
                       dict(self.descriptor(second, name="sharedpack"), asset_path="secondface", head=len(first)),
                       dict(self.descriptor(stock, name="stockpack"), asset_path="stockface")]
        descriptors[0]["pack_size"] = descriptors[1]["pack_size"] = len(first) + len(second)
        shared = self.encrypted(first, descriptors[0]) + self.encrypted(second, descriptors[1])
        self.context["allow_download"] = True
        for references in ({"cab-" + "6" * 32}, {"cab-" + "3" * 32}):
            answered = []

            def download(url, expected_size, deadline, byte_limit=faces.MAX_PACK_BYTES):
                from urllib.error import HTTPError
                name = url.rsplit("/", 1)[1]
                answered.append(name)
                if name == "stockpack":
                    time.sleep(1.5)
                    return self.encrypted(stock, descriptors[2])
                if answered.count("sharedpack") == 1:
                    raise HTTPError(url, 404, "Not Found", {}, None)
                return shared

            for path in Path(self.context["cache_dir"]).glob("*/*"):
                path.unlink()
            with self.subTest(references=references), \
                    patch.object(faces, "FACE_SECONDS", faces.FALLBACK_SECONDS + 1), \
                    patch.object(faces.FacePlan, "_face_references", return_value=references), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([dict(row) for row in descriptors])), \
                    patch.object(faces, "_download", download):
                plan = self.plan()
                self.assertEqual([Path(path).read_bytes() for path in plan.resolve()], [stock])
            self.assertEqual(answered, ["sharedpack", "stockpack"])
            self.assertEqual(plan.transferred, descriptors[0]["pack_size"] + descriptors[2]["pack_size"])
            # It was used, so it is an ordinary download for later opens.
            stocked, = [path for path in (Path(self.context["cache_dir"]) / "models").glob("*.unity")
                        if path.read_bytes() == stock]
            self.assertFalse(faces._compared(stocked))

    @EXTRACTOR_REQUIRED
    def test_the_running_named_download_itself_has_the_whole_face_time(self):
        # Nothing else is at hand: it is downloaded with the face time, as
        # before, and never measured or stopped early.
        stock = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = self.databases(stock)
        payload, calls = self.encrypted(stock, descriptor), []

        def slow(url, expected, deadline, byte_limit=faces.MAX_PACK_BYTES):
            calls.append(deadline)
            time.sleep(2.6)
            return payload

        self.context["allow_download"] = True
        with patch.object(faces, "FACE_SECONDS", 4), patch.object(faces, "FALLBACK_SECONDS", 3), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces, "_download", slow):
            plan = self.plan()
            chosen = plan.resolve()
        self.assertEqual([Path(path).read_bytes() for path in chosen], [stock])
        self.assertEqual(len(calls), 1)

    @EXTRACTOR_REQUIRED
    def test_selected_suit_download_cut_off_at_the_reserve_is_finished_by_the_late_pass(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        private = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = {"asset_path": "privateface", "pack_name": "privatepack", "head": 0, "size": len(private),
                      "key1": -12345, "key2": 23456, "pack_size": len(private)}
        self.game_catalog("installedbody", ["privateface"],
                          [tuple(descriptor[key] for key in ("asset_path", "pack_name", "head", "size", "key1", "key2"))])
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": True,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "en"}
        payload, calls = self.encrypted(private, descriptor), []

        def slow(url, expected, deadline, byte_limit=faces.MAX_PACK_BYTES):
            calls.append(url)
            time.sleep(1.5)
            return payload

        self.context["allow_download"] = True
        with patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), \
                patch.object(faces, "FACE_SECONDS", faces.FALLBACK_SECONDS + 1), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces, "_download", slow):
            viewer_mod_sources.register_game_import(str(self.body), record)
            chosen = self.plan().resolve()
        self.assertEqual([Path(path).read_bytes() for path in chosen], [private])
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/privatepack"))

    @EXTRACTOR_REQUIRED
    def test_fallback_first_in_the_old_order_is_downloaded_first_and_a_named_download_too_slow_stops(self):
        # The default suit's own model comes first in the old order and is
        # downloaded first, as before. The named face's download then cannot
        # finish in the face time: once measured it is stopped and the
        # fallback is used, instead of waiting for it.
        suit, named = self.referenced_donor("CAB-" + "1" * 32), self.referenced_donor("CAB-" + "2" * 32)
        descriptors = [dict(self.descriptor(suit, name="suitpack"), asset_path="suitbody"),
                       dict(self.descriptor(named, name="namedpack"), asset_path="namedface")]
        payloads = {"suitpack": self.encrypted(suit, descriptors[0]), "namedpack": self.encrypted(named, descriptors[1])}
        opened = []

        class Response(io.BytesIO):
            def __init__(self, pack):
                super().__init__(payloads[pack])
                self.pack, self.headers = pack, {"Content-Length": str(len(payloads[pack]))}

            def read(self, size=-1):
                if self.pack == "namedpack":
                    # About five seconds for the pack: past the face time.
                    time.sleep(.05)
                    size = max(1, len(payloads["namedpack"]) // 100)
                return super().read(size)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class Opener:
            def open(self, request, timeout=None):
                pack = request.full_url.rsplit("/", 1)[1]
                opened.append(pack)
                return Response(pack)

        def iterate(plan):
            plan._suit_models.add(tuple(descriptors[0][key] for key in ("pack_name", "head", "size", "key1", "key2", "pack_size")))
            return iter([dict(row) for row in descriptors])

        slot = threading.BoundedSemaphore(1)
        self.context["allow_download"] = True
        with patch.object(faces, "FACE_SECONDS", 4), patch.object(faces, "FALLBACK_SECONDS", 3), \
                patch.object(faces, "_DOWNLOAD_SLOT", slot), patch.object(faces, "build_opener", return_value=Opener()), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces.FacePlan, "_descriptor_iter", iterate):
            plan = self.plan()
            started = time.monotonic()
            chosen = plan.resolve()
            elapsed = time.monotonic() - started
            # The stopped download frees the one worker.
            self.assertTrue(slot.acquire(timeout=.5), "The stopped download kept running")
            slot.release()
        self.assertEqual([Path(path).read_bytes() for path in chosen], [suit])
        self.assertEqual(plan.status, "added")
        self.assertEqual(opened, ["suitpack", "namedpack"])
        # Stopped within its measuring time, not at the deadline.
        self.assertLess(elapsed, faces.MEASURE_SECONDS + .8)
        self.assertEqual(plan.transferred, len(payloads["suitpack"]) + len(payloads["namedpack"]))
        self.assertFalse((Path(self.context["cache_dir"]) / "packs" / "namedpack").exists())

    def test_a_step_bound_never_extends_the_face_deadline(self):
        plan = self.plan()
        deadline = plan.deadline
        with plan._until(deadline + 50):
            self.assertEqual(plan.deadline, deadline)
        with plan._until(deadline - 1):
            self.assertEqual(plan.deadline, deadline - 1)
            with plan._until(deadline + 5):
                self.assertEqual(plan.deadline, deadline - 1)
        self.assertEqual(plan.deadline, deadline)
        # A download measured while another face is at hand ends early; the
        # selected costume's own downloads are measured with the face time.
        with plan._download_step(True, True):
            self.assertEqual((plan.deadline, plan._measured), (deadline - faces.FALLBACK_SECONDS, True))
        with plan._download_step(True, False):
            self.assertEqual((plan.deadline, plan._measured), (deadline, True))
        self.assertEqual((plan.deadline, plan._measured), (deadline, False))
        # The bounded broad search (8 s while a download is pending) still
        # stops at a face deadline that is nearer.
        def walk(plan):
            while time.monotonic() < started + 3:
                faces._check(plan.deadline)
                time.sleep(.01)
            return []

        self.context["allow_download"] = True
        with patch.object(faces, "FACE_SECONDS", .5), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                patch.object(faces.FacePlan, "_resource", self.recording_resource({}, [])), \
                patch.object(faces.FacePlan, "_local", walk):
            plan = self.plan()
            started = time.monotonic()
            self.assertEqual(plan.resolve(), [])
            self.assertLess(time.monotonic() - started, 1.5)

    def test_another_size_of_a_compared_asset_path_is_still_compared(self):
        # Another catalog lists the same asset path with another section size:
        # other bytes, so it may still be the face the body references.
        files = self.face_files(glface=self.referenced_donor("CAB-" + "1" * 32),
                                jpface=self.referenced_donor("CAB-" + "2" * 32))
        for jp_size, expected, fetched in ((2000, "jpface", ["glpack", "jppack"]),
                                           # The same path and size is the same asset.
                                           (1000, "glface", ["glpack"])):
            descriptors = [dict(self.catalog_descriptor("face207"), pack_name="glpack"),
                           dict(self.catalog_descriptor("face207", size=jp_size), pack_name="jppack")]
            calls = []

            def resource(plan, descriptor, download=True):
                calls.append((descriptor["pack_name"], download))
                if not download:
                    raise faces.FaceUnavailable("Not local")
                return str(files["glface" if descriptor["pack_name"] == "glpack" else "jpface"])

            self.context["allow_download"] = True
            with self.subTest(jp_size=jp_size), \
                    patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([dict(row) for row in descriptors])), \
                    patch.object(faces.FacePlan, "_resource", resource), \
                    patch.object(faces.FacePlan, "_local", return_value=[]):
                self.assertEqual(self.plan().resolve(), [str(files[expected])])
                self.assertEqual([name for name, download in calls if download][:len(fetched)], fetched)
                if expected == "glface":
                    self.assertNotIn(("jppack", True), calls)

    def test_referenced_face_beside_a_body_selected_through_a_linked_folder(self):
        # macOS /tmp is a link to /private/tmp: the selected path and the
        # files the search finds name the same folder differently.
        real = self.root / "real-library"
        (real / "models").mkdir(parents=True)
        link = self.root / "linked-library"
        link.symlink_to(real, target_is_directory=True)
        self.body = link / "models" / "costume.unity"
        self.body.write_bytes(self.scene("Body"))
        beside = link / "models" / ("ch0207_" + "b" * 24 + ".unity")
        beside.write_bytes(self.referenced_donor("CAB-" + "2" * 32))
        files = self.face_files(stockface=self.referenced_donor("CAB-" + "2" * 32))
        self.context["allow_download"] = True
        for roots in ([str(link)], []):
            calls = []
            self.context["library_roots"] = roots
            with self.subTest(library=bool(roots)), \
                    patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                    patch.object(faces.FacePlan, "_resource", self.recording_resource(files, calls)):
                self.assertEqual(self.plan().resolve(), [os.path.realpath(beside)])
            # Used at once: nothing is downloaded to compare it.
            self.assertEqual(calls, [("stockface", False)])

    def test_natively_named_referenced_face_waits_for_the_catalog_copy_only_outside_extractor_folders(self):
        # The extractor's own file names in the library and its 3d_model and
        # extracted/3d_model folders are used at once, as before, so a library
        # of extracted models needs no download; so is one beside the body.
        # The same name in any other folder may be an edited copy with the
        # stock face's serialized names: it waits for the catalog's own copy.
        files = self.face_files(stockface=self.referenced_donor("CAB-" + "2" * 32))
        cases = [(self.library, "ch0207_facedynamic.unity", False),
                 (self.library, "3d_model/ch0207_facedynamic.unity", False),
                 (self.library, "extracted/3d_model/ch0207_face.unity", False),
                 (self.selected, "ch0207_facedynamic.unity", False),
                 # The body's own folder is not an extractor folder.
                 (self.selected, "3d_model/ch0207_facedynamic.unity", True),
                 (self.selected, "extracted/3d_model/ch0207_face.unity", True)]
        for root, relative, waits in cases:
            edited = root / relative
            edited.parent.mkdir(parents=True, exist_ok=True)
            edited.write_bytes(self.referenced_donor("CAB-" + "2" * 32))
            for allow in (True, False):
                calls = []
                self.context["allow_download"] = allow
                with self.subTest(root=root.name, relative=relative, allow=allow), \
                        patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                        patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                        patch.object(faces.FacePlan, "_resource", self.recording_resource(files, calls)):
                    plan = self.plan()
                    self.assertIn(str(edited), [os.path.realpath(path) for path in plan._known_local()])
                    chosen = [os.path.realpath(path) for path in plan.resolve()]
                if not waits:
                    self.assertEqual((chosen, calls), ([str(edited)], []))
                elif allow:
                    self.assertEqual((chosen, calls), ([str(files["stockface"])], [("stockface", False), ("stockface", True)]))
                else:
                    # Offline it is still the referenced face, before other prefabs.
                    self.assertEqual((chosen, calls), ([str(edited)], [("stockface", False)]))
            edited.unlink()

    def test_extracted_library_face_is_used_without_any_download(self):
        # A library of extracted models: each member's referenced stock face
        # is there under the extractor's name, and the catalog's copy is only
        # on the CDN. Nothing is downloaded, on the first open or later.
        directory = self.library / "extracted" / "3d_model"
        directory.mkdir(parents=True)
        for owner in (1, 207, 301):
            with self.subTest(owner=owner):
                self.body.write_bytes(self.scene("Body", owner=owner))
                face = directory / f"ch{owner:04}_facedynamic.unity"
                face.write_bytes(bundle([("CAB-" + "2" * 32, self.scene("Face", owner=owner)),
                                         ("CAB-" + "2" * 32 + "-eyes", self.scene("Eyes", owner=owner))]))
                self.context["allow_download"] = True
                for attempt in range(2):
                    with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                            patch.object(faces.FacePlan, "_descriptor_iter",
                                         lambda plan: iter([self.catalog_descriptor("stockface")])), \
                            patch.object(faces, "_download", side_effect=AssertionError("No download needed")) as fetch:
                        plan = self.plan()
                        self.assertEqual(plan.resolve(), [str(face)])
                    self.assertEqual(plan.status, "added")
                    fetch.assert_not_called()
                    self.assertFalse((Path(self.context["cache_dir"]) / "packs").exists())

    def test_referenced_library_face_kept_for_later_has_the_face_time_after_a_slow_walk(self):
        # The referenced face waits for the catalog's own copy, which answers
        # 404; the broad library walk used its whole share of the time.
        edited = self.selected / "3d_model" / "ch0207_facedynamic.unity"
        edited.parent.mkdir()
        edited.write_bytes(self.referenced_donor("CAB-" + "2" * 32))
        calls = []

        def slow_walk(plan):
            # A large or slow library: the walk is cut off by its share.
            while True:
                faces._check(plan.deadline)
                time.sleep(.01)

        def resource(plan, descriptor, download=True):
            from urllib.error import HTTPError
            calls.append(download)
            if not download:
                raise faces.FaceUnavailable("Not local")
            raise HTTPError("https://cdn.invalid/stockfacepack", 404, "Not Found", {}, None)

        self.context["allow_download"] = True
        with patch.object(faces, "LOCAL_SECONDS", .3), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                patch.object(faces.FacePlan, "_resource", resource), \
                patch.object(faces.FacePlan, "_local", slow_walk):
            plan = self.plan()
            started = time.monotonic()
            self.assertEqual([os.path.realpath(path) for path in plan.resolve()], [str(edited)])
        self.assertEqual(plan.status, "added")
        self.assertEqual(calls, [False, True])
        self.assertLess(time.monotonic() - started, 5)

    @EXTRACTOR_REQUIRED
    def test_referenced_face_search_never_reads_the_default_suit_body(self):
        data = self.donor()
        descriptor = self.databases(data)
        body = self.scene("Body2")
        body_descriptor = dict(descriptor, asset_path="body207", pack_name="bodypack207", size=len(body), pack_size=len(body))
        catalog = Path(self.context["repo_root"]) / "assets" / "db" / "gl" / "asset_a_en.db"
        with sqlite3.connect(catalog) as db:
            db.execute("INSERT INTO member_model VALUES(?,?,?,?,?,?)",
                       tuple(body_descriptor[key] for key in ("asset_path", "pack_name", "head", "size", "key1", "key2")))
            db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?)", (body_descriptor["pack_name"], len(body)))
        for value, raw in ((descriptor, data), (body_descriptor, body)):
            (self.library / value["pack_name"]).write_bytes(self.encrypted(raw, value))
        real, calls = faces.FacePlan._resource, []

        def resource(plan, value, download=True):
            calls.append((value["asset_path"], download))
            return real(plan, value, download=download)

        self.context["allow_download"] = True
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "f" * 32}), \
                patch.object(faces.FacePlan, "_resource", resource), patch.object(faces, "_download") as fetch:
            plan = self.plan()
            chosen = plan.resolve()
        fetch.assert_not_called()
        # No face declares the reference: the member's stock face is the
        # fallback, and the default suit's own body was never decrypted.
        self.assertEqual(calls, [("face207", False)])
        self.assertEqual([Path(path).read_bytes() for path in chosen], [data])
        self.assertEqual(plan._suit_models, {tuple(body_descriptor[key] for key in
                                                    ("pack_name", "head", "size", "key1", "key2", "pack_size"))})
        # Without a body reference the old order is unchanged.
        calls.clear()
        for path in (Path(self.context["cache_dir"]) / "models").iterdir():
            path.unlink()
        with patch.object(faces.FacePlan, "_face_references", return_value=set()), \
                patch.object(faces.FacePlan, "_resource", resource), patch.object(faces, "_download") as fetch:
            self.assertEqual([Path(path).read_bytes() for path in self.plan().resolve()], [data])
        self.assertEqual(calls, [("face207", False)])

    def test_ios_game_import_reads_its_own_platform_catalog(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        files = self.face_files(
            iosface=bundle([(name + ".assets", self.scene(name, platform=9)) for name in ("Face", "Eyes", "Private")]),
            androidface=bundle([(name + ".assets", self.scene(name)) for name in ("Face", "Eyes", "Decoy")]))
        # Both platform catalogs list the same model path with their own face.
        self.game_catalog("installedbody", ["iosface"], [("iosface", "iospack", 0, 900, 0, 0)], name="asset_i_en.db")
        self.game_catalog("installedbody", ["androidface"], [("androidface", "androidpack", 0, 900, 0, 0)])
        calls = []
        for platform, native, expected in (("ios", 9, "iosface"), ("android", 13, "androidface")):
            self.body.write_bytes(self.scene("Body", platform=native))
            record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": False,
                      "model": "installedbody", "purpose": "viewer", "platform": platform, "selection_language": "en"}
            with self.subTest(platform=platform), patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), \
                    patch.object(faces.FacePlan, "_resource",
                                 self.recording_resource(files, calls, local={"iosface", "androidface"})), \
                    patch.object(faces.FacePlan, "_local", return_value=[]):
                viewer_mod_sources.register_game_import(str(self.body), record)
                plan = self.plan()
                self.assertEqual([row["asset_path"] for row in plan._selected_iter()], [expected])
                self.assertEqual(plan.resolve(), [str(files[expected])])

    def test_selected_suit_uses_its_largest_dependencies_and_only_the_referenced_face(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        files = self.face_files(otherface=self.referenced_donor("CAB-" + "1" * 32),
                                privateface=self.referenced_donor("CAB-" + "2" * 32))
        # A larger other prefab of the member is listed first; small shared
        # packs past the four-file bound must not push the faces out.
        rows = [("otherface", "otherpack", 0, 5000, 0, 0), ("privateface", "privatepack", 0, 4000, 0, 0)]
        rows += [(f"tiny{index}", f"tinypack{index}", 0, 10 * index, 0, 0) for index in range(1, 5)]
        self.game_catalog("installedbody", [row[0] for row in reversed(rows)] + ["installedbody"], rows)
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": False,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "en"}
        # Both faces local, or both only downloadable for this suit.
        for local, expected in (({"otherface", "privateface"}, [("otherface", False), ("privateface", False)]),
                                (set(), [("otherface", False), ("privateface", False), ("tiny4", False), ("tiny3", False),
                                         ("otherface", True), ("privateface", True)])):
            calls = []
            self.context["allow_download"] = not local
            with self.subTest(local=sorted(local)), patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), \
                    patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                    patch.object(faces.FacePlan, "_resource", self.recording_resource(files, calls, local=local)), \
                    patch.object(faces.FacePlan, "_local", return_value=[]):
                viewer_mod_sources.register_game_import(str(self.body), record)
                plan = self.plan()
                self.assertEqual([row["asset_path"] for row in plan._selected_iter()],
                                 ["otherface", "privateface", "tiny4", "tiny3"])
                self.assertEqual(plan.resolve(), [str(files["privateface"])])
                self.assertEqual(calls, expected)

    def test_restart_reads_the_import_cache_receipt_for_the_same_body_bytes(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        models = self.root / "game-models"
        imported = models / "gl-900000001-abcdefgh" / "ch0207_suit900000001_primary.unity"
        imported.parent.mkdir(parents=True)
        imported.write_bytes(self.body.read_bytes())
        self.body = imported
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        files = self.face_files(privateface=self.referenced_donor("CAB-" + "2" * 32))
        self.game_catalog("installedbody", ["privateface"], [("privateface", "privatepack", 0, 900, 0, 0)])
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": False,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "en"}
        manifest = models / (".selection-" + "0" * 32 + ".json")

        def receipt(digest, selection=record):
            manifest.write_text(json.dumps({"model": "gl-900000001-abcdefgh/" + imported.name, "sha256": digest,
                                            "source": [], "selection_record": selection}), encoding="utf-8")

        receipt(hashlib.sha256(imported.read_bytes()).hexdigest())
        calls = []
        # A restarted server has no in-memory import registry.
        with patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces.FacePlan, "_resource",
                             self.recording_resource(files, calls, local={"privateface"})), \
                patch.object(faces.FacePlan, "_local", return_value=[]):
            self.context["game_models_dir"] = str(models)
            plan = self.plan()
            self.assertEqual(plan._game_records, [record])
            self.assertEqual(plan.resolve(), [str(files["privateface"])])
            # The receipt binds other bytes, or the application's cache root
            # is not given: no suit is inferred and the old choice remains.
            receipt("0" * 64)
            self.assertEqual(self.plan()._game_records, [])
            # A receipt whose selection is not a valid import record is ignored.
            receipt(hashlib.sha256(imported.read_bytes()).hexdigest(), {key: value for key, value in record.items() if key != "download"})
            self.assertEqual(self.plan()._game_records, [])
            receipt(hashlib.sha256(imported.read_bytes()).hexdigest())
            del self.context["game_models_dir"]
            plan = self.plan()
            self.assertEqual(plan._game_records, [])
            self.assertEqual(plan.resolve(), [str(other)])

    def test_restart_finds_the_body_receipt_behind_many_other_selections(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_flow, viewer_mod_sources
        models = self.root / "game-models"
        imported = models / "gl-900000001-abcdefgh" / "ch0207_suit900000001_primary.unity"
        imported.parent.mkdir(parents=True)
        imported.write_bytes(self.body.read_bytes())
        self.body = imported
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": False,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "en"}
        # Each distinct Game-assets selection keeps one receipt.
        for index in range(600):
            (models / f".selection-{index:032x}.json").write_text(json.dumps({
                "model": f"gl-{index}-abcdefgh/ch0207_suit{index}_primary.unity", "sha256": "0" * 64,
                "source": [], "selection_record": dict(record, suit_id=index + 1)}), encoding="utf-8")
        digest = hashlib.sha256(imported.read_bytes()).hexdigest()
        target = models / (".selection-" + "f" * 32 + ".json")
        target.write_text(json.dumps({"model": "gl-900000001-abcdefgh/" + imported.name, "sha256": digest,
                                      "source": [], "selection_record": record}), encoding="utf-8")
        listed = Path.iterdir

        def last(path):
            # This body's receipt is listed after every other one.
            return iter(sorted(listed(path), key=lambda entry: entry == target))

        self.context["game_models_dir"] = str(models)
        with patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), patch.object(Path, "iterdir", last):
            # The packaging scan reads a bounded number of receipts.
            self.assertEqual(viewer_mod_flow.cached_receipts(
                {"containers": [{"path": str(imported), "sha256": digest}]}, str(models)), [])
            self.assertEqual(self.plan()._game_records, [record])
            # Only the receipt that binds these bytes counts.
            imported.write_bytes(self.scene("Body2"))
            self.assertEqual(self.plan()._game_records, [])
            # A model outside the game-model cache never lists its receipts;
            # only its own path-named provenance receipt is looked at.
            outside = self.selected / "costume.unity"
            with patch.object(viewer_mod_flow, "_receipt_row", wraps=viewer_mod_flow._receipt_row) as read:
                self.assertIsNone(viewer_mod_flow.stored_receipt(str(outside), digest, str(models)))
            self.assertEqual([call.args[1].name for call in read.call_args_list],
                             [viewer_mod_flow._provenance(models, str(outside.resolve())).name])

    def test_referenced_face_saved_beside_the_body_precedes_another_cached_member_face(self):
        # The viewer saves an edited body and its face side by side. Opening
        # the body alone must find that face, not a face prefab cached earlier.
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        beside = self.selected / ("ch0207_" + "b" * 24 + ".unity")
        self.context["allow_download"] = True
        for cab, references, expected in (
                ("CAB-" + "2" * 32, {"cab-" + "2" * 32}, beside),
                # A same-member face beside the body that is not the one it
                # references keeps its old place after the cached face.
                ("CAB-" + "3" * 32, {"cab-" + "2" * 32}, other),
                # Without a reference the old order applies.
                ("CAB-" + "2" * 32, set(), other)):
            beside.write_bytes(self.referenced_donor(cab))
            calls = []
            with self.subTest(cab=cab, references=references), \
                    patch.object(faces.FacePlan, "_face_references", return_value=references), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                    patch.object(faces.FacePlan, "_resource", self.recording_resource({}, calls)):
                plan = self.plan()
                self.assertEqual(plan.resolve(), [str(expected)])
                if expected == beside:
                    # Found before anything is downloaded only to compare it.
                    self.assertEqual(calls, [("stockface", False)])

    def test_referenced_face_elsewhere_in_the_library_waits_for_the_catalog_copy(self):
        # A saved outline edit of the stock face keeps the stock face's
        # serialized names. Opening the stock body must preview the stock
        # face, which the catalog has, not that edited copy.
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        edited = self.library / "modded" / "body-edit" / "models" / ("ch0207_" + "c" * 24 + ".unity")
        edited.parent.mkdir(parents=True)
        edited.write_bytes(self.referenced_donor("CAB-" + "2" * 32))
        files = self.face_files(stockface=self.referenced_donor("CAB-" + "2" * 32))
        for allow, expected, requested in ((True, files["stockface"], [("stockface", False), ("stockface", True)]),
                                           # Offline it is still the referenced face, before other prefabs.
                                           (False, edited, [("stockface", False)])):
            calls = []
            self.context["allow_download"] = allow
            with self.subTest(allow=allow), \
                    patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                    patch.object(faces.FacePlan, "_resource", self.recording_resource(files, calls)):
                self.assertEqual(self.plan().resolve(), [str(expected)])
            self.assertEqual(calls, requested)

    @EXTRACTOR_REQUIRED
    def test_compared_download_never_overtakes_a_library_face_through_the_cache(self):
        # The body references a face that exists nowhere. The member's stock
        # face is fetched to compare it and is saved in the face cache, which
        # the broad local search reads first; the library face still wins.
        stock = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = self.databases(stock)
        library_face = self.library / "costume_face_copy.unity"
        library_face.write_bytes(self.referenced_donor("CAB-" + "4" * 32))
        self.context["allow_download"] = True
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                patch.object(faces, "_download", return_value=self.encrypted(stock, descriptor)) as fetch:
            self.assertEqual(self.plan().resolve(), [str(library_face)])
        fetch.assert_called_once()
        cached = sorted((Path(self.context["cache_dir"]) / "models").glob("ch0207_*.unity"))
        self.assertEqual([path.read_bytes() for path in cached], [stock])
        # Every later open finds the downloaded original in the face cache
        # (by its cache name, its catalog row and the broad search) and still
        # chooses the library face, as the first open did, with no download.
        for attempt in range(2):
            with self.subTest(open=attempt + 2), \
                    patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                    patch.object(faces, "_download") as fetch:
                plan = self.plan()
                self.assertIn(str(cached[0]), list(plan._known_local()))
                self.assertEqual(plan.resolve(), [str(library_face)])
            fetch.assert_not_called()
        # The cache may keep only the downloaded pack; the face decrypted
        # from it again is still that download.
        cached[0].unlink()
        Path(str(cached[0]) + ".json").unlink()
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                patch.object(faces, "_download") as fetch:
            self.assertEqual(self.plan().resolve(), [str(library_face)])
        fetch.assert_not_called()
        self.assertEqual(cached[0].read_bytes(), stock)
        # Without the library face the compared original is used, from cache.
        library_face.unlink()
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                patch.object(faces, "_download") as fetch:
            self.assertEqual([Path(path).read_bytes() for path in self.plan().resolve()], [stock])
        fetch.assert_not_called()
        # A cached face the viewer did not download (e.g. decrypted from a
        # local game pack) keeps its old, early place.
        library_face.write_bytes(self.referenced_donor("CAB-" + "4" * 32))
        meta = Path(str(cached[0]) + ".json")
        meta.write_text(json.dumps({key: value for key, value in json.loads(meta.read_text()).items()
                                    if key != "downloaded"}), encoding="utf-8")
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                patch.object(faces, "_download") as fetch:
            self.assertEqual(self.plan().resolve(), [str(cached[0])])
        fetch.assert_not_called()

    @EXTRACTOR_REQUIRED
    def test_a_face_downloaded_only_to_compare_never_changes_a_later_open_of_any_body(self):
        # Opens of a body that names no face, and of one that names a face
        # found nowhere (which fetches the stock face only to compare it),
        # alternate on one face cache. Every open chooses what the first did.
        stock = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = self.databases(stock)
        library_face = self.library / "costume_face_copy.unity"
        library_face.write_bytes(self.referenced_donor("CAB-" + "4" * 32))
        self.context["allow_download"] = True
        models, packs = Path(self.context["cache_dir"]) / "models", Path(self.context["cache_dir"]) / "packs"

        def open_body(references):
            with patch.object(faces.FacePlan, "_face_references", return_value=references), \
                    patch.object(faces, "_download", return_value=self.encrypted(stock, descriptor)) as fetch:
                chosen = self.plan().resolve()
            return [Path(path).name for path in chosen], fetch.call_count

        for label, references, downloads in (("no reference", set(), 0), ("reference", {"cab-" + "3" * 32}, 1),
                                             ("no reference", set(), 0), ("reference", {"cab-" + "3" * 32}, 0),
                                             ("no reference", set(), 0)):
            with self.subTest(label, downloads=downloads):
                self.assertEqual(open_body(references), ([library_face.name], downloads))
        cached, = models.glob("ch0207_*.unity")
        self.assertEqual(cached.read_bytes(), stock)
        self.assertTrue(faces._compared(cached) and faces._downloaded(cached))
        self.assertTrue(faces._compared(packs / descriptor["pack_name"]))
        # The face cache may keep only the pack: the face decrypted from it
        # again is still only a compared download.
        cached.unlink()
        Path(str(cached) + ".json").unlink()
        self.assertEqual(open_body(set()), ([library_face.name], 0))
        self.assertTrue(faces._compared(cached))
        # Once it is chosen it is a face the viewer downloaded and used:
        # a body that names no face reuses it from the cache, as before.
        library_face.unlink()
        self.assertEqual(open_body(set()), ([cached.name], 0))
        self.assertFalse(faces._compared(cached))
        self.assertTrue(faces._downloaded(cached))
        library_face.write_bytes(self.referenced_donor("CAB-" + "4" * 32))
        self.assertEqual(open_body(set()), ([cached.name], 0))
        # A body that names another face still gives it a download's place.
        self.assertEqual(open_body({"cab-" + "3" * 32}), ([library_face.name], 0))

    @EXTRACTOR_REQUIRED
    def test_a_compared_download_that_is_used_is_an_ordinary_download(self):
        # The compared stock face is the one the body names: it is used at
        # once, and neither it nor its pack keeps the compare-only mark.
        stock = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = self.databases(stock)
        library_face = self.library / "costume_face_copy.unity"
        library_face.write_bytes(self.referenced_donor("CAB-" + "4" * 32))
        self.context["allow_download"] = True
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces, "_download", return_value=self.encrypted(stock, descriptor)) as fetch:
            chosen = self.plan().resolve()
        fetch.assert_called_once()
        cached = Path(chosen[0])
        pack = Path(self.context["cache_dir"]) / "packs" / descriptor["pack_name"]
        self.assertEqual(cached.read_bytes(), stock)
        self.assertEqual([faces._compared(path) for path in (cached, pack)], [False, False])
        self.assertEqual([faces._downloaded(path) for path in (cached, pack)], [True, True])
        # With only the pack left, a body that names no face decrypts it at
        # its catalog place again, before the library face, as before.
        cached.unlink()
        Path(str(cached) + ".json").unlink()
        with patch.object(faces.FacePlan, "_face_references", return_value=set()), \
                patch.object(faces, "_download") as fetch:
            self.assertEqual(self.plan().resolve(), [str(cached)])
        fetch.assert_not_called()

    def test_a_cached_download_with_no_catalog_is_still_the_last_fallback(self):
        # No catalog, no library face: only a face the viewer downloaded
        # earlier, which is not the one the body names, or which was only
        # compared. It keeps a download's place, the end of the late pass.
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        cached = directory / ("ch0207_" + "a" * 24 + ".unity")
        self.context["allow_download"] = True
        for references, compared in (({"cab-" + "3" * 32}, False), ({"cab-" + "3" * 32}, True), (set(), True)):
            faces._save(cached, self.referenced_donor("CAB-" + "2" * 32), 207, downloaded=True, compared=compared)
            with self.subTest(references=references, compared=compared), \
                    patch.object(faces.FacePlan, "_face_references", return_value=references), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([])), \
                    patch.object(faces, "_download", side_effect=AssertionError("No catalog to download from")):
                plan = self.plan()
                self.assertEqual(plan.resolve(), [str(cached)])
                self.assertEqual(plan._late, [str(cached)])
            self.assertEqual(plan.status, "added")
            self.assertFalse(faces._compared(cached))

    def test_the_selected_costume_own_face_is_used_even_if_it_was_only_compared(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        compared = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(compared, self.referenced_donor("CAB-" + "2" * 32), 207, downloaded=True, compared=True)
        library_face = self.library / "costume_face_copy.unity"
        library_face.write_bytes(self.referenced_donor("CAB-" + "4" * 32))
        self.game_catalog("installedbody", ["privateface"], [("privateface", "privatepack", 0, 900, 0, 0)])
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": False,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "en"}
        calls = []
        with patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), \
                patch.object(faces.FacePlan, "_face_references", return_value=set()), \
                patch.object(faces.FacePlan, "_resource",
                             self.recording_resource({"privateface": compared}, calls, local={"privateface"})):
            # Without the game selection it keeps a download's place.
            self.assertEqual(self.plan().resolve(), [str(library_face)])
            viewer_mod_sources.register_game_import(str(self.body), record)
            self.assertEqual(self.plan().resolve(), [str(compared)])
        self.assertEqual(calls, [("privateface", False)])
        self.assertFalse(faces._compared(compared))

    @EXTRACTOR_REQUIRED
    def test_a_cached_download_keeps_its_catalog_place_among_later_downloads(self):
        # Neither catalog face is the referenced one. The first open gets only
        # the first (the second's pack answers 404); the next open can fetch
        # the second too, and the first, now cached, still comes first.
        first, second = self.referenced_donor("CAB-" + "4" * 32), self.referenced_donor("CAB-" + "5" * 32)
        descriptors = [dict(self.descriptor(first, name="firstpack"), asset_path="firstface"),
                       dict(self.descriptor(second, name="secondpack"), asset_path="secondface")]
        payloads = {"firstpack": self.encrypted(first, descriptors[0]), "secondpack": self.encrypted(second, descriptors[1])}
        self.context["allow_download"] = True
        for attempt, missing in ((1, {"secondpack"}), (2, set()), (3, set())):
            def download(url, expected, deadline, byte_limit=faces.MAX_PACK_BYTES):
                from urllib.error import HTTPError
                name = url.rsplit("/", 1)[1]
                if name in missing:
                    raise HTTPError(url, 404, "Not Found", {}, None)
                return payloads[name]

            with self.subTest(open=attempt), \
                    patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([dict(row) for row in descriptors])), \
                    patch.object(faces, "_download", side_effect=download) as fetch:
                self.assertEqual([Path(path).read_bytes() for path in self.plan().resolve()], [first])
            self.assertEqual([call.args[0].rsplit("/", 1)[1] for call in fetch.call_args_list],
                             {1: ["firstpack", "secondpack"], 2: ["secondpack"], 3: []}[attempt])

    @EXTRACTOR_REQUIRED
    def test_other_region_copy_of_a_compared_face_is_not_downloaded(self):
        stock = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = self.databases(stock)
        (self.library / descriptor["pack_name"]).write_bytes(self.encrypted(stock, descriptor))
        gl = Path(self.context["repo_root"]) / "assets" / "db" / "gl"
        jp = gl.parent / "jp"
        jp.mkdir()
        (jp / "masterdata.db").write_bytes((gl / "masterdata.db").read_bytes())
        (jp / "asset_a_ja.db").write_bytes((gl / "asset_a_en.db").read_bytes())
        # JP lists the same asset in its own pack with its own keys.
        with sqlite3.connect(jp / "asset_a_ja.db") as db:
            db.execute("UPDATE member_model SET pack_name='jp207',key1=32457,key2=-49532")
            db.execute("UPDATE m_asset_package_mapping SET pack_name='jp207'")
        self.context["allow_download"] = True
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                patch.object(faces, "_download") as fetch:
            self.assertEqual([Path(path).read_bytes() for path in self.plan().resolve()], [stock])
        fetch.assert_not_called()
        # Another asset of the other catalog may still be the referenced face.
        other = self.referenced_donor("CAB-" + "5" * 32)
        with sqlite3.connect(jp / "asset_a_ja.db") as db:
            db.execute("UPDATE member_model SET asset_path='jpface207',size=?", (len(other),))
            db.execute("UPDATE member_model_dependency SET dependency='jpface207'")
            db.execute("UPDATE m_asset_package_mapping SET file_size=?", (len(other),))
        jp_descriptor = dict(self.descriptor(other, name="jp207"), asset_path="jpface207", key1=32457, key2=-49532)
        with patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                patch.object(faces, "_download", return_value=self.encrypted(other, jp_descriptor)) as fetch:
            self.assertEqual([Path(path).read_bytes() for path in self.plan().resolve()], [stock])
        fetch.assert_called_once()
        self.assertTrue(fetch.call_args.args[0].endswith("/jp207"))

    def test_unanswered_cdn_is_not_waited_for_again(self):
        from urllib.error import HTTPError, URLError
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        descriptors = [dict(self.catalog_descriptor("first"), pack_name="sharedpack"),
                       dict(self.catalog_descriptor("second"), pack_name="sharedpack"),
                       dict(self.catalog_descriptor("third"), pack_name="thirdpack")]
        self.context["allow_download"] = True
        for error, fetched in ((TimeoutError("timed out"), ["first"]),
                               (URLError("no route to host"), ["first"]),
                               # The CDN answered: only that pack is missing.
                               (HTTPError("https://cdn.invalid/sharedpack", 404, "Not Found", {}, None), ["first", "third"])):
            calls = []

            def resource(plan, descriptor, download=True):
                calls.append((descriptor["asset_path"], download))
                if not download:
                    raise faces.FaceUnavailable("Not local")
                raise error

            with self.subTest(error=type(error).__name__), \
                    patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([dict(row) for row in descriptors])), \
                    patch.object(faces.FacePlan, "_resource", resource), \
                    patch.object(faces.FacePlan, "_local", return_value=[]):
                self.assertEqual(self.plan().resolve(), [str(other)])
            self.assertEqual([name for name, download in calls if download], fetched)

    @EXTRACTOR_REQUIRED
    def test_a_stopped_pack_is_never_requested_or_reserved_again(self):
        # A download stopped early (or not answered) leaves its pack requested:
        # another asset of it, or the same one again, is refused without a
        # second request or a second reservation of its bytes.
        stock = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = self.descriptor(stock)
        calls = []

        def stopped(url, expected, deadline, byte_limit=faces.MAX_PACK_BYTES, *, limit=None):
            calls.append(url)
            raise faces._NoAnswer("Finding the original face took too long.")

        self.context["allow_download"] = True
        plan = self.plan()
        with patch.object(faces, "_download_with_deadline", stopped):
            with self.assertRaises(faces._NoAnswer):
                plan._resource(dict(descriptor))
            for other in (dict(descriptor), dict(descriptor, asset_path="other207", head=0, size=len(stock) - 1)):
                with self.assertRaisesRegex(faces.FaceUnavailable, "already requested"):
                    plan._resource(other)
        self.assertEqual(len(calls), 1)
        self.assertEqual(plan.transferred, descriptor["pack_size"])

    @EXTRACTOR_REQUIRED
    def test_stalled_selected_suit_download_is_stopped_and_frees_the_worker_for_the_old_order(self):
        # Nothing is at hand. The selected costume's own face pack never sends
        # a byte: it is measured anyway, stopped, and the catalog's stock face
        # (the one the body names) still gets the one network worker.
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        stock = self.referenced_donor("CAB-" + "2" * 32)
        descriptor = self.databases(stock)
        payload = self.encrypted(stock, descriptor)
        self.game_catalog("installedbody", ["privateface"], [("privateface", "privatepack", 0, 900, 0, 0)],
                          name="asset_a_ko.db")
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": True,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "ko"}
        opened = []

        class Response(io.BytesIO):
            def __init__(self, data, hang):
                super().__init__(data)
                self.hang, self.headers = hang, {"Content-Length": str(len(data))}

            def read(self, size=-1):
                while self.hang:
                    # The worker stops at its next chunk once abandoned.
                    if threading.current_thread().face_stop.wait(.05):
                        return b""
                return super().read(size)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class Opener:
            def open(self, request, timeout=None):
                pack = request.full_url.rsplit("/", 1)[1]
                opened.append(pack)
                return Response(b"\0" * 900, True) if pack == "privatepack" else Response(payload, False)

        slot = threading.BoundedSemaphore(1)
        self.context["allow_download"] = True
        with patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), \
                patch.object(faces, "_DOWNLOAD_SLOT", slot), patch.object(faces, "build_opener", return_value=Opener()), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}):
            viewer_mod_sources.register_game_import(str(self.body), record)
            plan = self.plan()
            started = time.monotonic()
            chosen = plan.resolve()
            elapsed = time.monotonic() - started
        self.assertEqual([Path(path).read_bytes() for path in chosen], [stock])
        self.assertEqual(opened, ["privatepack", descriptor["pack_name"]])
        self.assertLess(elapsed, faces.MEASURE_SECONDS + 1)

    def test_unanswered_cdn_for_the_selected_suit_skips_compared_downloads(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        directory = Path(self.context["cache_dir"]) / "models"
        directory.mkdir(parents=True)
        other = directory / ("ch0207_" + "a" * 24 + ".unity")
        faces._save(other, self.referenced_donor("CAB-" + "1" * 32), 207)
        self.game_catalog("installedbody", ["privateface"], [("privateface", "privatepack", 0, 900, 0, 0)])
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": True,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "en"}
        calls = []

        def resource(plan, descriptor, download=True):
            calls.append((descriptor["asset_path"], download))
            if not download:
                raise faces.FaceUnavailable("Not local")
            raise TimeoutError("timed out")

        self.context["allow_download"] = True
        with patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()), \
                patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "2" * 32}), \
                patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([self.catalog_descriptor("stockface")])), \
                patch.object(faces.FacePlan, "_resource", resource), \
                patch.object(faces.FacePlan, "_local", return_value=[]):
            viewer_mod_sources.register_game_import(str(self.body), record)
            self.assertEqual(self.plan().resolve(), [str(other)])
        self.assertEqual(calls, [("privateface", False), ("stockface", False), ("privateface", True)])

    def test_local_candidates_kept_for_the_fallback_keep_the_old_search_bound(self):
        library_face = self.library / "costume_face_copy.unity"
        library_face.write_bytes(self.referenced_donor("CAB-" + "4" * 32))
        real, observed = faces.FacePlan._inspect, {}

        def inspect(plan, path):
            # The first reading, in the search; using it reads it again.
            observed.setdefault(path, plan.deadline)
            return real(plan, path)

        self.context["allow_download"] = True
        for catalog in ([self.catalog_descriptor("stockface")], []):
            observed.clear()
            with self.subTest(catalog=bool(catalog)), \
                    patch.object(faces.FacePlan, "_face_references", return_value={"cab-" + "3" * 32}), \
                    patch.object(faces.FacePlan, "_descriptor_iter", lambda plan: iter([dict(row) for row in catalog])), \
                    patch.object(faces.FacePlan, "_resource", self.recording_resource({}, [])), \
                    patch.object(faces.FacePlan, "_inspect", inspect):
                plan = self.plan()
                deadline, started = plan.deadline, time.monotonic()
                self.assertEqual(plan.resolve(), [str(library_face)])
                self.assertEqual(plan.deadline, deadline)
                if catalog:
                    # The walk and its kept candidates share the 8 s that
                    # leave time for a catalog original.
                    self.assertLessEqual(observed[str(library_face)], started + 8.01)
                else:
                    self.assertEqual(observed[str(library_face)], deadline)

    def test_archive_members_and_scene_records_never_lend_a_selected_suit(self):
        from collections import OrderedDict
        from webtools.core import viewer_mod_sources
        self.game_catalog("installedbody", ["privateface"], [("privateface", "privatepack", 0, 900, 0, 0)])
        record = {"region": "gl", "suit_id": 900000001, "variant": "primary", "download": False,
                  "model": "installedbody", "purpose": "viewer", "platform": "android", "selection_language": "en"}
        with patch.object(viewer_mod_sources, "_REGISTRY", OrderedDict()):
            viewer_mod_sources.register_game_import(str(self.body), record)
            self.assertEqual(self.plan()._game_records, [record])
            # The same bytes as an archive member or motion copy: another origin.
            self.context["origins"] = {str(self.body): str(self.root / "costume.zip")}
            self.assertEqual(self.plan()._game_records, [])
            del self.context["origins"]
            # A Rina scene costume's record selects a scene package, not the
            # catalog dependencies of a model.
            plan = self.plan()
            self.assertEqual([row["asset_path"] for row in plan._selected_iter()], ["privateface"])
            plan._game_records = [dict(record, scene_source={"sha256": "0" * 64})]
            self.assertEqual(list(plan._selected_iter()), [])

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
        for native_owner in (1, 101, 209, 211, 212):
            owner = faces.member_from_native(native_owner)
            with self.subTest(native_owner=native_owner, runtime_member=owner):
                self.body.write_bytes(self.scene("Body", owner=native_owner))
                data = self.donor(owner=native_owner)
                descriptor = self.descriptor(data, name=f"pack{native_owner}")
                plan = self.plan()
                self.assertEqual(plan.owner, owner)
                self.context["allow_download"] = True
                with patch.object(faces.FacePlan, "_descriptor_iter", return_value=[descriptor]), \
                        patch.object(faces, "_download", return_value=self.encrypted(data, descriptor)) as fetch:
                    metadata = viewer.prepare([str(self.body)], face_context=self.context)
                self.assertEqual(metadata["faces"], {"enabled": True, "status": "added", "added": 2, "characters": [owner]})
                self.assertEqual(glb_names(metadata), ["Body", "Face", "Eyes"])
                fetch.assert_called_once()
                self.assertTrue(fetch.call_args.args[0].endswith(f"/pack{native_owner}"))
        self.assertEqual(list(self.library.iterdir()), [])

    @EXTRACTOR_REQUIRED
    def test_jp_ios_downloaded_pack_wins_before_preferred_gl_network(self):
        # The source catalog and the actual serialized iOS headers must agree.
        self.body.write_bytes(self.scene("Body", platform=9))
        donor = self.donor(platform=9)
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

    def test_mia_lanzhu_native_names_and_known_local_faces_use_runtime_members(self):
        for native_owner, runtime_member in ((212, 211), (211, 212)):
            with self.subTest(native_owner=native_owner, runtime_member=runtime_member):
                self.body.write_bytes(self.scene("Body", owner=native_owner))
                correct = self.library / f"ch{native_owner:04}_facedynamic.unity"
                other = self.library / f"ch{runtime_member:04}_facedynamic.unity"
                correct.write_bytes(self.donor(owner=native_owner))
                other.write_bytes(self.donor(owner=runtime_member))
                plan = self.plan()
                self.assertEqual(plan.owner, runtime_member)
                self.assertIn(str(correct), list(plan._known_local()))
                self.assertNotIn(str(other), list(plan._known_local()))
                self.assertIsNone(plan._inspect(str(other)), "The other member's face is rejected")
                metadata = viewer.prepare([str(self.body)], face_context=self.context)
                self.assertEqual(metadata["faces"]["characters"], [runtime_member])
                self.assertEqual(metadata["faces"]["status"], "added")
                self.assertEqual(set(glb_names(metadata)), {"Body", "Face", "Eyes"})
                correct.unlink()
                other.unlink()

    def test_legacy_installer_manifest_native_owner_is_converted_exactly_once(self):
        for native_owner, runtime_member in ((212, 211), (211, 212), (209, 209)):
            with self.subTest(native_owner=native_owner):
                manifest = self.selected / "modinstall.txt"
                manifest.write_text(f"chara_id = {native_owner}\ncostume_file = 'costume.unity'\n")
                owners = faces._manifest_owners([str(self.body)], [str(manifest)])
                self.assertEqual(owners[str(self.body)], {runtime_member})


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
