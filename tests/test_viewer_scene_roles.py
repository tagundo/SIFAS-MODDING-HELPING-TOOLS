"""Actual neutral Unity bundles exercise the production scene pipeline."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from webtools.core import model_edits as edits, model_viewer, viewer_archive
from webtools.core import viewer_mod_flow as flow, viewer_scene_format as fmt, viewer_scene_roles as roles
from webtools.jobs import Job
from viewer_scene_fixture import bundle_fixture, _copy_typetree
from UnityPy.helpers.Tpk import get_typetree_node


class SceneFixtureTests(unittest.TestCase):
    def test_typetree_clone_does_not_pickle_or_mutate_the_shared_cache(self):
        cached = get_typetree_node(142, (2018, 4, 36, 0))
        snapshot = [{key: value for key, value in row.items() if key != "m_Children"}
                    for row in cached.to_dict_list()]
        original_nodes = list(cached.traverse())
        cloned = _copy_typetree(cached)
        self.assertEqual(snapshot, [{key: value for key, value in row.items() if key != "m_Children"}
                                    for row in cloned.to_dict_list()])
        self.assertFalse({id(node) for node in original_nodes} & {id(node) for node in cloned.traverse()})
        cloned.m_Children[0].m_Name = "owned_fixture_name"
        cloned.m_Children.clear()
        self.assertEqual(snapshot, [{key: value for key, value in row.items() if key != "m_Children"}
                                    for row in cached.to_dict_list()])
        self.assertEqual([id(node) for node in original_nodes], [id(node) for node in cached.traverse()])


class SceneRolesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with edits._LOCK: edits._SESSIONS.clear()
        self.originals = {}

    def source(self, platforms=("android",), data=None):
        path = self.root / ("source-" + "-".join(platforms) + ".zip")
        values = {"chara_id": 209, "thumbnail_file": ""}
        for field in ("costume_name_en", "costume_name_ko", "costume_name_ja", "costume_name_zh", "costume_description"):
            values[field] = "Neutral Rina"
        with zipfile.ZipFile(path, "w") as archive:
            for platform in platforms:
                for variant in fmt.VARIANTS:
                    raw = data[platform, variant] if data is not None else bundle_fixture(fmt.PLATFORMS[platform], variant)
                    self.originals[platform, variant] = raw
                    name = platform + "_" + variant + ".unity"; archive.writestr(name, raw)
                    field = "costume_file" if variant == "primary" else "rina_unmask_costume_file"
                    if platform == "ios" and "android" in platforms: field += "_ios"
                    values[field] = name
            archive.writestr("modinstall.txt", "\n".join(key + " = " + repr(value) for key, value in values.items()) + "\n")
        return path

    def prepare(self, path, variant=None):
        choices = None if variant is None else {str(path): variant}
        with viewer_archive.expand_inputs([str(path)], self.root / "cache", variant_choices=choices) as expanded:
            prepared = model_viewer.prepare(expanded.paths, rigged=True, face_context={"enabled": False, "allow_download": False})
            metadata = edits.register_session(prepared["id"], expanded.paths, prepared["rig"],
                originals=expanded.editing_originals or [str(path)], origins=expanded.origins,
                archive_members=expanded.archive_members,
                variants=expanded.editing_variants if expanded.editing_variants is not None else {str(path): "primary"})
            state = roles.register_reopened(prepared["id"], expanded.scene_context) if expanded.scene_context else None
        return prepared["id"], {row["name"]: row for row in metadata["nodes"]}, state

    def state(self, nodes, mesh=False):
        return {"version": 1, "savedSettingsEnabled": True, "edits": [
            {"node": nodes["BreastSize"]["node"], "method": "mesh" if mesh else "node", "scale": [.8, 1.1, 1.2]},
            {"node": nodes["HipsSize"]["node"], "method": "node", "scale": [1.25, 1.05, 1.15]}]}

    def package(self, token, state):
        job = Job("scene", "viewer_body_mod")
        result = flow.create_package(token, state, output_root=self.root / "exports", repo_root=self.root,
            cache_root=self.root / "game-cache", display_name="Neutral scene", character_id=209, job=job)
        return result, fmt.read_package(result["mod_package"]["package_path"])

    @staticmethod
    def golden(decoded, platform, variant):
        role = "mv_board" if variant == "primary" else "mv_unmasked"
        return decoded["files"][decoded["manifest"]["canonical_goldens"][platform][role]["member"]]

    def test_supplied_platforms_get_complete_native_roles_and_unchanged_goldens(self):
        for platforms in (("android",), ("ios",), ("android", "ios")):
            with self.subTest(platforms=platforms):
                token, nodes, _ = self.prepare(self.source(platforms))
                result, decoded = self.package(token, self.state(nodes))
                self.assertEqual(set(decoded["manifest"]["platforms"]), set(platforms))
                with zipfile.ZipFile(result["mod_package"]["package_path"].replace("-scene.zip", ".zip")) as legacy:
                    goldens = {legacy.read(name) for name in legacy.namelist() if name.endswith(".unity")}
                for platform in platforms:
                    family = decoded["manifest"]["platforms"][platform]
                    self.assertEqual(set(family), set(fmt.ROLES))
                    self.assertEqual(family["navi_board"], family["mv_board"])
                    self.assertEqual(len({row["member"] for row in family.values()}), 2)
                    self.assertEqual(decoded["manifest"]["version"], fmt.SHARED_VERSION)
                    self.assertEqual(decoded["manifest"]["target_member_id"], 209)
                    self.assertEqual(decoded["manifest"]["default_variant"], "primary")
                    for variant in fmt.VARIANTS:
                        self.assertIn(self.golden(decoded, platform, variant), goldens)

    def test_reopen_repeat_mesh_migration_and_reset_keep_original_authority(self):
        original = self.source(); token, nodes, _ = self.prepare(original)
        first, before = self.package(token, self.state(nodes))
        source_archive = before["manifest"]["source_archives"][0]["file"]["member"]
        self.assertEqual(before["files"][source_archive], original.read_bytes())
        reopened, current_nodes, restored = self.prepare(first["mod_package"]["package_path"])
        self.assertNotEqual(current_nodes["BreastSize"]["authored"]["scale"], [.8, 1.1, 1.2])
        _, repeated = self.package(reopened, restored)
        for variant in fmt.VARIANTS: self.assertEqual(self.golden(before, "android", variant), self.golden(repeated, "android", variant))
        mixed = copy.deepcopy(restored)
        next(row for row in mixed["edits"] if row["node"] == current_nodes["BreastSize"]["node"])["method"] = "mesh"
        _, migrated = self.package(reopened, mixed)
        self.assertEqual(set(migrated["manifest"]["navi_sync"]["android"]), {"HipsSize"})
        fresh, fresh_nodes, _ = self.prepare(original)
        _, direct = self.package(fresh, self.state(fresh_nodes, mesh=True))
        for variant in fmt.VARIANTS: self.assertEqual(self.golden(migrated, "android", variant), self.golden(direct, "android", variant))
        _, reset = self.package(reopened, {"version": 1, "savedSettingsEnabled": True, "edits": []})
        for variant in fmt.VARIANTS: self.assertEqual(self.golden(reset, "android", variant), self.originals["android", variant])

    def test_shared_board_sync_is_absolute_idempotent_and_preserves_every_other_object(self):
        token, nodes, _ = self.prepare(self.source())
        _, decoded = self.package(token, self.state(nodes))
        recipe_ref = decoded["manifest"]["authoring"]["android"]["primary"]["recipe"]["member"]
        recipe = json.loads(decoded["files"][recipe_ref]); golden = self.golden(decoded, "android", "primary")
        first, endpoints = roles._sync_navi(golden, recipe)
        second, repeated_endpoints = roles._sync_navi(first, recipe)
        self.assertEqual(first, second); self.assertEqual(endpoints, repeated_endpoints)
        before, after = edits._inspect(golden), edits._inspect(first)
        touched = {key for key, name in before["names"].items() if name in fmt.SUPPORTED_SCALES}
        for key, obj in before["objects"].items():
            actual = after["objects"][key]
            if key in touched:
                old, new = obj.read_typetree(), actual.read_typetree()
                self.assertEqual(new["m_LocalScale"], edits._d3(after["effective"][key]["scale"]))
                new["m_LocalScale"] = old["m_LocalScale"]; self.assertEqual(old, new)
            else:
                self.assertEqual(obj.get_raw_data(), actual.get_raw_data())

    def test_v1_reopen_upgrades_v2_without_using_derived_model_as_original(self):
        token, nodes, _ = self.prepare(self.source())
        _, decoded = self.package(token, self.state(nodes))
        old = copy.deepcopy(decoded["manifest"]); files = dict(decoded["files"])
        old.update(version=fmt.VERSION, requires=[fmt.CAPABILITY])
        old.pop("target_member_id"); old.pop("default_variant")
        golden = self.golden(decoded, "android", "primary")
        member = "models/android_v1_mv_board.unity"; files[member] = golden
        old["platforms"]["android"]["mv_board"] = fmt.reference(member, golden, "android")
        path = self.root / "old-v1.zip"; path.write_bytes(fmt.encode_package(old, files))
        reopened, current_nodes, restored = self.prepare(path)
        self.assertEqual(roles.session_metadata(reopened)["target_member_id"], 209)
        _, upgraded = self.package(reopened, restored)
        self.assertEqual(upgraded["manifest"]["version"], fmt.SHARED_VERSION)
        for variant in fmt.VARIANTS:
            self.assertEqual(self.golden(decoded, "android", variant), self.golden(upgraded, "android", variant))
        self.assertEqual(current_nodes["BreastSize"]["authored"]["scale"], nodes["BreastSize"]["authored"]["scale"])

    def test_reopened_clone_target_and_default_survive_repeated_export(self):
        token, nodes, _ = self.prepare(self.source())
        _, decoded = self.package(token, self.state(nodes))
        manifest = decoded["manifest"]; manifest.update(target_member_id=6, default_variant="unmasked")
        path = self.root / "clone-scene.zip"; path.write_bytes(fmt.encode_package(manifest, decoded["files"]))
        reopened, _, restored = self.prepare(path)
        metadata = roles.session_metadata(reopened)
        self.assertEqual(edits._session(reopened)["sources"][0]["sha256"], fmt.sha(self.originals["android", "unmasked"]))
        explicit, _, _ = self.prepare(path, variant="primary")
        self.assertEqual(edits._session(explicit)["sources"][0]["sha256"], fmt.sha(self.originals["android", "primary"]))
        self.assertEqual((metadata["target_member_id"], metadata["default_variant"]), (6, "unmasked"))
        self.assertTrue(roles.should_package({}, {}, {"chara_id": 6}, reopened))
        _, exported = self.package(reopened, restored)
        self.assertEqual((exported["manifest"]["target_member_id"], exported["manifest"]["default_variant"]), (6, "unmasked"))
        for variant in fmt.VARIANTS:
            self.assertEqual(self.golden(decoded, "android", variant), self.golden(exported, "android", variant))

    def test_unsupported_derived_node_edits_refuse_instead_of_omitting_home_change(self):
        token, nodes, _ = self.prepare(self.source())
        state = self.state(nodes)
        state["edits"].append({"node": nodes["Spine"]["node"], "method": "node", "scale": [1.1, 1, 1]})
        with self.assertRaisesRegex(ValueError, "only BreastSize/HipsSize"):
            self.package(token, state)
        state = self.state(nodes); state["edits"][0]["position"] = [.1, 0, 0]
        with self.assertRaisesRegex(ValueError, "scale-only"):
            self.package(token, state)

    def test_loaded_unsupported_node_override_is_refused_without_new_edits(self):
        info = edits._inspect(bundle_fixture())
        key = next(key for key, name in info["names"].items() if name == "Spine")
        component, tree = info["components"][0]
        tree["scaleValues"].append({"target": {"m_FileID": 0, "m_PathID": key[1]},
                                   "originValue": edits._d3(info["authored"][key]["scale"]),
                                   "scaledValue": edits._d3([1.1, 1, 1])})
        component.save_typetree(tree)
        raw = info["env"].file.save(packer="original")
        with self.assertRaisesRegex(ValueError, "only BreastSize/HipsSize"):
            roles._sync_navi(raw, {"nodeIdentities": [], "state": {"edits": []}})

    def test_named_but_not_directly_bound_target_is_refused(self):
        info = edits._inspect(bundle_fixture())
        key = next(key for key, name in info["names"].items() if name == "BreastSize")
        for obj in info["env"].objects:
            if obj.type.name == "SkinnedMeshRenderer":
                tree = obj.read_typetree()
                tree["m_Bones"] = [ptr for ptr in tree["m_Bones"] if ptr["m_PathID"] != key[1]]
                obj.save_typetree(tree)
        raw = info["env"].file.save(packer="original")
        recipe = {"nodeIdentities": [{"node": 1, "serializedFile": key[0], "transformId": str(key[1])}],
                  "state": {"edits": [{"node": 1, "method": "node", "scale": info["effective"][key]["scale"]}]}}
        with self.assertRaisesRegex(ValueError, "directly bound"):
            roles._sync_navi(raw, recipe)

    def test_canonical_source_zip_face_companion_must_match_before_exact_reuse(self):
        token, nodes, _ = self.prepare(self.source())
        _, decoded = self.package(token, self.state(nodes))
        manifest, files = decoded["manifest"], decoded["files"]
        face = bundle_fixture(13, "primary", unit_breast=True)
        private_face = bundle_fixture(13, "unmasked")
        member = "dependencies/original-face.unity"; files[member] = face
        manifest["dependencies"]["android"]["facedynamic"] = fmt.reference(member, face, "android")
        source = manifest["source_archives"][0]["file"]
        original_zip = files[source["member"]]
        def with_face(raw):
            with zipfile.ZipFile(io.BytesIO(original_zip)) as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            entries["modinstall.txt"] += b"costume_facedynamic_file = 'face.unity'\n"
            entries["face.unity"] = raw
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as archive:
                archive.comment = b"Preserve the complete original source exactly"
                for name, value in entries.items(): archive.writestr(name, value)
            return output.getvalue()
        good_zip = with_face(face)
        files[source["member"]] = good_zip
        manifest["source_archives"][0]["file"] = fmt.reference(source["member"], good_zip)
        path = self.root / "correct-face-scene.zip"; path.write_bytes(fmt.encode_package(manifest, files))
        directory = self.root / "correct-face"; directory.mkdir()
        expanded = roles.expand_scene(path, directory)
        self.assertEqual(Path(expanded["path"]).read_bytes(), good_zip)
        wrong_zip = with_face(private_face)
        files[source["member"]] = wrong_zip
        manifest["source_archives"][0]["file"] = fmt.reference(source["member"], wrong_zip)
        path.write_bytes(fmt.encode_package(manifest, files))
        with self.assertRaisesRegex(ValueError, "declared face companion"):
            roles.expand_scene(path, directory)

    def test_private_execution_graph_does_not_become_canonical_face_or_reexport_authority(self):
        token, nodes, _ = self.prepare(self.source())
        _, decoded = self.package(token, self.state(nodes))
        manifest, files = decoded["manifest"], decoded["files"]
        # Distinct neutral native fixtures test routing, not real face rendering.
        face_info = edits._inspect(bundle_fixture(13, "primary", unit_breast=True))
        # Real face dependencies do not declare another costume owner through
        # body textures. Keep this neutral companion outside Rina pair inference.
        for obj in face_info["env"].objects:
            if obj.type.name == "Texture2D":
                tree = obj.read_typetree(); tree["m_Name"] = "neutral_face_texture"; obj.save_typetree(tree)
        canonical_face = face_info["env"].file.save(packer="original")
        from webtools.core import bundle_identity
        private_face, _ = bundle_identity.isolate_verified_bundle(canonical_face, "private-face-neutral-fixture")
        original_member, private_member = "dependencies/original-face.unity", "execution/private-face.unity"
        files[original_member], files[private_member] = canonical_face, private_face
        manifest["dependencies"]["android"]["facedynamic"] = fmt.reference(original_member, canonical_face, "android")
        refs = manifest["platforms"]["android"]
        manifest.update(target_member_id=109, default_variant="unmasked")
        manifest["execution_model_graph"] = {"android": {
            "nodes": {
                "board": {"resource": refs["mv_board"], "model_dependencies": ["face"], "shared_shader_dependencies": []},
                "bare": {"resource": refs["mv_unmasked"], "model_dependencies": ["face"], "shared_shader_dependencies": []},
                "face": {"resource": fmt.reference(private_member, private_face, "android"), "model_dependencies": [],
                         "shared_shader_dependencies": ["original-public-shader"]}},
            "role_bindings": {"navi_board": "board", "mv_board": "board", "mv_unmasked": "bare"}}}
        # No exact source ZIP fallback: the canonical face must be constructed
        # from the authoring reference even when a private execution face exists.
        for source in manifest.pop("source_archives"):
            del files[source["file"]["member"]]
        path = self.root / "private-graph-scene.zip"; path.write_bytes(fmt.encode_package(manifest, files))
        directory = self.root / "private-graph"; directory.mkdir()
        expanded = roles.expand_scene(path, directory)
        self.assertNotIn("execution_model_graph", expanded["metadata"])
        self.assertEqual((expanded["metadata"]["target_member_id"], expanded["variant"]), (109, "unmasked"))
        with zipfile.ZipFile(expanded["path"]) as archive:
            self.assertEqual(archive.read("android_face.unity"), canonical_face)
            self.assertNotIn(fmt.sha(private_face), [fmt.sha(archive.read(name)) for name in archive.namelist()])
        reopened, _, restored = self.prepare(path)
        _, exported = self.package(reopened, restored)
        self.assertNotIn("execution_model_graph", exported["manifest"])
        self.assertEqual((exported["manifest"]["target_member_id"], exported["manifest"]["default_variant"]), (109, "unmasked"))
        face_ref = exported["manifest"]["dependencies"]["android"]["facedynamic"]
        self.assertEqual(exported["files"][face_ref["member"]], canonical_face)
        for variant in fmt.VARIANTS:
            self.assertEqual(self.golden(decoded, "android", variant), self.golden(exported, "android", variant))

    def test_direct_skin_bone_limits_reject_instead_of_clamping(self):
        for value in (.19, -.8, 2.51):
            with self.subTest(value=value):
                token, nodes, _ = self.prepare(self.source())
                state = self.state(nodes); state["edits"][0]["scale"] = [value, 1, 1]
                with self.assertRaisesRegex(ValueError, "0.2–2.5"):
                    self.package(token, state)

    def test_existing_saved_node_values_can_be_repaired_without_new_edits(self):
        token, nodes, _ = self.prepare(self.source())
        _, edited = self.package(token, self.state(nodes))
        originals = {("android", variant): self.golden(edited, "android", variant) for variant in fmt.VARIANTS}
        token, _, _ = self.prepare(self.source(data=originals))
        self.assertTrue(roles.pending_supported_nodes(edits.mod_source_context(token)))
        edits._session(token)["allowEmptySceneReset"] = True
        _, repaired = self.package(token, {"version": 1, "savedSettingsEnabled": True, "edits": []})
        self.assertEqual(set(repaired["manifest"]["navi_sync"]["android"]), {"BreastSize", "HipsSize"})
        for variant in fmt.VARIANTS: self.assertEqual(self.golden(repaired, "android", variant), originals["android", variant])


if __name__ == "__main__": unittest.main()
