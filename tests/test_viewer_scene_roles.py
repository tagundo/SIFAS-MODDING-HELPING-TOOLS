"""Actual neutral Unity bundles exercise the production scene pipeline."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from webtools.core import model_edits as edits, model_viewer, viewer_archive
from webtools.core import viewer_mod_flow as flow, viewer_scene_format as fmt, viewer_scene_roles as roles
from webtools.core import viewer_mod_pair_edits as pair_edits
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

    def prepare(self, path, variant=None, *, game_platform=None):
        choices = None if variant is None else {str(path): variant}
        with viewer_archive.expand_inputs([str(path)], self.root / "cache", variant_choices=choices,
                                          game_platform=game_platform) as expanded:
            prepared = model_viewer.prepare(expanded.paths, rigged=True, face_context={"enabled": False, "allow_download": False})
            metadata = edits.register_session(prepared["id"], expanded.paths, prepared["rig"],
                originals=expanded.editing_originals or [str(path)], origins=expanded.origins,
                archive_members=expanded.archive_members,
                variants=(expanded.editing_variants if expanded.editing_variants is not None else
                          # As the HTTP route: the variant picked for a plain costume ZIP.
                          {item["source_path"]: item["selected"] for item in expanded.variants} if variant is not None else
                          {str(path): "primary"}))
            state = roles.register_reopened(prepared["id"], expanded.scene_context) if expanded.scene_context else None
        return prepared["id"], {row["name"]: row for row in metadata["nodes"]}, state

    def test_explicit_ios_scene_preview_restores_its_recipe_and_preserves_both_originals(self):
        token, nodes, _ = self.prepare(self.source(("android", "ios")))
        result, original = self.package(token, self.state(nodes))
        path = Path(result["mod_package"]["package_path"])
        reopened, _, state = self.prepare(path, "unmasked", game_platform="ios")
        context = edits.mod_source_context(reopened)
        body, = context["sources"]
        self.assertEqual(body["member"], "ios_unmasked.unity")
        self.assertIsNotNone(state)
        self.assertEqual(set(original["manifest"]["platforms"]), {"android", "ios"})
        with zipfile.ZipFile(io.BytesIO(context["containers"][body["container"]]["raw"])) as archive:
            for (platform, variant), raw in self.originals.items():
                self.assertEqual(archive.read(f"{platform}_{variant}.unity"), raw)

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
                # The scene ZIP is published to mods/saved; the installer ZIP it
                # was built from stays in the edit folder's work files.
                published = Path(result["mod_package"]["package_path"])
                self.assertEqual(published.parent.name, "saved")
                self.assertTrue(published.name.endswith("_scene.zip"), published.name)
                built = sorted((Path(result["recipe_path"]).parent / "mod").glob("*.zip"))
                self.assertEqual(len(built), 1, built)
                with zipfile.ZipFile(built[0]) as legacy:
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

    def raw_pair(self):
        """A raw game body with its automatic face companion and its pair."""
        primary, unmasked = (bundle_fixture(fmt.PLATFORMS["android"], variant) for variant in fmt.VARIANTS)
        face = bundle_fixture(fmt.PLATFORMS["android"], "primary", unit_breast=True)
        paths = {}
        for name, raw in (("primary", primary), ("unmasked", unmasked), ("face", face)):
            paths[name] = self.root / (name + ".unity")
            paths[name].write_bytes(raw)
        context = {"containers": [{"raw": face}, {"raw": unmasked}],
                   "sources": [{"container": 0, "member": None, "sha256": fmt.sha(face)},
                               {"container": 1, "member": None, "sha256": fmt.sha(unmasked)}],
                   "outline_only_sources": [0]}
        result = {"preview_paths": [str(paths["face"]), str(paths["unmasked"])],
                  "recipe": {"format": "elichika-viewer-body-edit", "version": 1, "nodeIdentities": [],
                             "sources": [{"name": "face.unity", "sha256": fmt.sha(face), "container": 0, "member": None},
                                         {"name": "unmasked.unity", "sha256": fmt.sha(unmasked), "container": 1, "member": None}],
                             "originals": [], "state": {}}}
        pair = {variant: {"path": str(paths[variant])} for variant in fmt.VARIANTS}
        goldens = {("android", "primary"): primary, ("android", "unmasked"): unmasked}
        return context, result, pair, goldens

    def test_face_only_outline_edits_keep_both_scene_bodies_original(self):
        context, result, pair, goldens = self.raw_pair()
        face_row = {"id": "0:0:111", "factor": 1.0, "absolute": 40}
        state = {"version": 1, "savedSettingsEnabled": True, "edits": [], "unsupported": [],
                 "compensationReference": [], "outlines": [face_row]}
        result["recipe"]["state"] = copy.deepcopy(state)
        originals, recipes = roles._originals_and_recipes(context, result, pair, goldens, state)
        self.assertEqual(originals, goldens)
        for key in goldens:
            self.assertFalse(recipes[key]["state"].get("outlines"))
            self.assertEqual(recipes[key]["sources"][0]["sha256"], fmt.sha(goldens[key]))
        # A body outline edit still needs its edited counterpart.
        state["outlines"].append({"id": "1:0:222", "factor": 0.75})
        with self.assertRaisesRegex(ValueError, "no complete native original family"):
            roles._originals_and_recipes(context, result, pair, goldens, state)

    def test_a_costume_zip_declared_face_is_a_face_source(self):
        face = bundle_fixture(fmt.PLATFORMS["android"], "primary", unit_breast=True)
        path = self.source()
        with zipfile.ZipFile(path) as archive:
            members = {info.filename: archive.read(info.filename) for info in archive.infolist()}
        members["modinstall.txt"] += b"costume_facedynamic_file = 'face.unity'\n"
        members["face.unity"] = face
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in members.items():
                archive.writestr(name, raw)
        raw = path.read_bytes()
        context = {"containers": [{"raw": raw}],
                   "sources": [{"container": 0, "member": "face.unity", "sha256": fmt.sha(face)},
                               {"container": 0, "member": "android_unmasked.unity",
                                "sha256": fmt.sha(self.originals["android", "unmasked"])}]}
        self.assertEqual(roles._face_sources(context), {0})
        self.assertEqual(roles._face_sources(dict(context, outline_only_sources=[1])), {0, 1})
        # A reopened costume ZIP whose only edit is on its declared face keeps
        # both bodies as their own originals with no body edit.
        unmasked = self.originals["android", "unmasked"]
        state = {"version": 1, "savedSettingsEnabled": True, "edits": [], "unsupported": [],
                 "compensationReference": [], "outlines": [{"id": "0:0:111", "factor": 1.0, "absolute": 40}]}
        result = {"preview_paths": [str(path)], "recipe": {
            "format": "elichika-viewer-body-edit", "version": 1, "nodeIdentities": [], "originals": [],
            "sources": [{"name": "face.unity", "sha256": fmt.sha(face), "container": 0, "member": "face.unity"},
                        {"name": "android_unmasked.unity", "sha256": fmt.sha(unmasked), "container": 0,
                         "member": "android_unmasked.unity"}], "state": copy.deepcopy(state)}}
        goldens = {key: value for key, value in self.originals.items()}
        originals, recipes = roles._originals_and_recipes(context, result, None, goldens, state)
        self.assertEqual(originals, goldens)
        self.assertFalse(any(recipe["state"].get("outlines") for recipe in recipes.values()))

    def test_reopened_scene_passes_every_face_row_to_restore(self):
        face_id = "0:0:-3871884669349275213"
        session = {"sources": [{"name": "android_face.unity", "sha256": "f" * 64, "container": 0, "member": "f"},
                               {"name": "android_primary.unity", "sha256": "b" * 64, "container": 0, "member": "b"}],
                   "containers": [{"name": "canonical-originals.zip", "sha256": "c" * 64}]}

        def recipe(sha, rows):
            return {"sources": [{"sha256": sha}], "nodeIdentities": [], "state": {"edits": [], "outlines": rows}}

        restored = []

        def restore(token, value):
            restored.append(copy.deepcopy(value))
            return value["state"]

        scene = {"recipe": recipe("b" * 64, [{"id": "0:0:5538708582486367566", "factor": 1.5}]),
                 "face_recipes": [recipe("f" * 64, [{"id": face_id, "factor": 1.0, "absolute": 40}])],
                 "metadata": {}}
        for variant in ("primary", "unmasked"):
            restored.clear()
            with self.subTest(variant=variant), \
                    patch.object(edits, "_session", return_value=copy.deepcopy(session)), \
                    patch.object(edits, "restore", side_effect=restore):
                roles.register_reopened("a" * 32, dict(scene, variant=variant))
            # Each face row is bound to the face source; restore decides
            # whether this view edits it or holds it.
            self.assertEqual([row["id"] for row in restored[0]["state"]["outlines"]],
                             ["1:0:5538708582486367566", face_id])

    def held_session(self):
        session = {"sources": [{"sha256": "f" * 64}, {"sha256": "b" * 64}],
                   "outlines": {"meshes": [{"id": "1:0:5"}, {"id": "0:0:6"}],
                                "excludedMeshes": [{"id": "0:0:7"}, {"id": "0:0:8"}, {"id": "1:0:9"}]}}
        proof = [{"id": "0:0:7", "sourceIndex": 0, "vertexCount": 4, "runtimeBindings": [{"headSourceIndex": 2}]},
                 # Editable in this view as well (the Normal face view): never held.
                 {"id": "0:0:6", "sourceIndex": 0, "vertexCount": 4, "runtimeBindings": [{"headSourceIndex": 2}]}]
        return session, proof

    def test_held_face_rows_are_only_rows_the_unmasked_counterpart_proves(self):
        session, proof = self.held_session()
        rows = [{"id": "1:0:5", "factor": 1.5},
                {"id": "0:0:6", "factor": 0.5},
                {"id": "0:0:7", "factor": 1, "absolute": 40},
                # Not editable here and not proven by the counterpart.
                {"id": "0:0:8", "factor": 1.0},
                # Excluded on the body itself: the face proof never covers it.
                {"id": "1:0:9", "factor": 1.0},
                # Not a mesh of this session at all.
                {"id": "0:0:999", "factor": 1.0}]
        with patch.object(roles, "counterpart_face_proof", side_effect=lambda value, index: proof if index == 0 else None) as find:
            kept, held, catalog = roles.split_held_face_outlines(session, copy.deepcopy(rows))
        self.assertEqual(held, [{"id": "0:0:7", "factor": 1.0, "absolute": 40}])
        self.assertEqual(kept, [rows[0], rows[1], rows[3], rows[4], rows[5]])
        self.assertEqual(catalog, {"meshes": proof})
        self.assertEqual(sorted(call.args[1] for call in find.call_args_list), [0, 1])
        # Without a counterpart body nothing is held: the strict validation
        # of the remaining rows still refuses them.
        with patch.object(roles, "counterpart_face_proof", return_value=None):
            self.assertEqual(roles.split_held_face_outlines(session, copy.deepcopy(rows)), (rows, [], None))
        # A held row keeps the outline writer's own limits.
        with patch.object(roles, "counterpart_face_proof", return_value=proof), \
                self.assertRaisesRegex(ValueError, "between zero and two"):
            roles.split_held_face_outlines(session, [{"id": "0:0:7", "factor": 3}])

    def test_counterpart_proof_needs_the_declared_face_and_its_unmasked_body(self):
        face = bundle_fixture(fmt.PLATFORMS["android"], "primary", unit_breast=True)
        path = self.source()
        with zipfile.ZipFile(path) as archive:
            members = {info.filename: archive.read(info.filename) for info in archive.infolist()}
        members["modinstall.txt"] += b"costume_facedynamic_file = 'face.unity'\n"
        members["face.unity"] = face
        family = self.root / "family.zip"
        with zipfile.ZipFile(family, "w") as archive:
            for name, raw in members.items():
                archive.writestr(name, raw)

        def session(raw, member="face.unity", source=face):
            return {"sources": [{"container": 0, "member": member, "sha256": fmt.sha(source), "raw": source}],
                    "containers": [{"raw": raw}]}

        from webtools.core import model_outlines
        unmasked = members["android_unmasked.unity"]
        with patch.object(model_outlines, "catalogue_sources", wraps=model_outlines.catalogue_sources) as catalogue, \
                patch.object(edits, "_inspect", wraps=edits._inspect) as inspect:
            # These neutral bodies have no BodyPartManager: nothing is proven.
            self.assertEqual(roles.counterpart_face_proof(session(family.read_bytes()), 0), [])
        # The proof pairs this face with the family's unmasked body, which
        # supplies the proof only and is never a session source.
        self.assertEqual([call.args[0] for call in inspect.call_args_list], [face, unmasked])
        self.assertEqual([index for _, index in catalogue.call_args.args[0]], [0, 1])
        # No face declaration, another face, a loose file, or no unmasked body.
        plain = path.read_bytes()
        without_unmasked = self.root / "no-unmasked.zip"
        with zipfile.ZipFile(without_unmasked, "w") as archive:
            for name, raw in members.items():
                if name != "android_unmasked.unity":
                    archive.writestr(name, raw.replace(b"rina_unmask_costume_file = 'android_unmasked.unity'\n", b"")
                                     if name == "modinstall.txt" else raw)
        for label, value in (("undeclared", session(plain)), ("other face", session(family.read_bytes(), source=unmasked)),
                             ("loose file", session(face, member=None)),
                             ("no unmasked body", session(without_unmasked.read_bytes()))):
            with self.subTest(label):
                self.assertIsNone(roles.counterpart_face_proof(value, 0))

    def test_held_face_rows_reach_every_save_of_the_masked_view(self):
        from webtools.core import model_outlines
        token, _, _ = self.prepare(self.source(), "primary")
        session = edits._session(token)
        empty = {"version": 1, "savedSettingsEnabled": True, "edits": [], "unsupported": [], "compensationReference": []}
        held = [{"id": "0:0:7", "factor": 1.0, "absolute": 40}]
        proof = {"meshes": [{"id": "0:0:7", "sourceIndex": 0}]}
        recipe = {"format": "elichika-viewer-body-edit", "version": 1, "sources": edits._source_signature(session),
                  "originals": [{"name": item["name"], "sha256": item["sha256"]} for item in session["containers"]],
                  "state": dict(empty, outlines=held), "nodeIdentities": []}
        with patch.object(roles, "split_held_face_outlines", return_value=([], copy.deepcopy(held), proof)):
            restored = edits.restore(token, copy.deepcopy(recipe))
        # The view's own state has no face row; the session holds it.
        self.assertNotIn("outlines", restored)
        self.assertEqual((session["heldFaceOutlines"], session["heldFaceProof"]), (held, proof))
        self.assertEqual(edits.validate_state(token, empty, allow_empty=True), restored)
        writes = []

        def apply(raw, index, values, catalog, *, original_raw=None):
            writes.append((index, values, catalog, original_raw == session["sources"][index]["raw"]))
            return raw + b"held"

        with patch.object(model_outlines, "apply_edits", side_effect=apply):
            result = edits.export(token, empty, self.root / "saved", allow_empty=True)
        self.assertEqual(writes, [(0, held, proof, True)])
        # The saved model carries the written face bytes and the recipe the rows.
        self.assertEqual(result["recipe"]["state"]["outlines"], held)
        member = session["sources"][0]["member"]
        with zipfile.ZipFile(result["preview_paths"][0]) as archive:
            self.assertEqual(archive.read(member), session["sources"][0]["raw"] + b"held")
        self.assertEqual(result["summary"][0]["outlines"], 1)
        self.assertEqual(json.loads(Path(result["recipe_path"]).read_text())["state"]["outlines"], held)
        # A recipe with no row for that face keeps them held: this view
        # cannot edit them, so it cannot mean to drop them.
        edits.restore(token, dict(recipe, state=empty), allow_empty=True)
        self.assertEqual((session["heldFaceOutlines"], session["heldFaceProof"]), (held, proof))

    def held_view(self):
        """A masked view of the neutral family holding one row of source 0."""
        token, _, _ = self.prepare(self.source(), "primary")
        session = edits._session(token)
        empty = {"version": 1, "savedSettingsEnabled": True, "edits": [], "unsupported": [], "compensationReference": []}
        recipe = {"format": "elichika-viewer-body-edit", "version": 1, "sources": edits._source_signature(session),
                  "originals": [{"name": item["name"], "sha256": item["sha256"]} for item in session["containers"]],
                  "state": empty, "nodeIdentities": []}
        held = [{"id": "0:0:7", "factor": 1.0, "absolute": 40}]
        proof = {"meshes": [{"id": "0:0:7", "sourceIndex": 0, "name": "Mouth"}]}
        with patch.object(roles, "split_held_face_outlines", return_value=([], copy.deepcopy(held), proof)):
            edits.restore(token, dict(recipe, state=dict(empty, outlines=held)))
        return token, session, recipe, empty, held, proof

    def test_restore_keeps_held_rows_unless_the_recipe_sets_their_face(self):
        token, session, recipe, empty, held, proof = self.held_view()
        self.assertEqual(edits.held_summary(session), {"count": 1, "meshes": ["Mouth"], "rows": held})
        before = edits.held_snapshot(token)
        edits.restore(token, recipe, allow_empty=True)
        self.assertEqual(edits.held_response(token, before),
                         {"heldFaceOutlines": {"count": 1, "meshes": ["Mouth"], "rows": held}})
        # A recipe that sets that face itself (here an editable row of the same
        # source) releases the held rows, and the response says so.
        mesh = next(row["id"] for row in session["outlines"]["meshes"] if row["id"].startswith("0:"))
        own = dict(recipe, state=dict(empty, outlines=[{"id": mesh, "factor": 0.5}]))
        edits.restore(token, own)
        self.assertEqual((session["heldFaceOutlines"], session["heldFaceProof"]), ([], None))
        response = edits.held_response(token, before)
        self.assertEqual(response["heldFaceOutlines"], {"count": 0, "meshes": [], "rows": []})
        self.assertEqual(response["notice"], {"text": edits.HELD_RELEASED_ONE, "values": {}})
        from webtools import i18n
        for text in (edits.HELD_RELEASED, edits.HELD_RELEASED_ONE):
            for language in ("ko", "ja"):
                self.assertNotEqual(i18n.tr(text, language), text)
        two = [{"id": "0:0:7", "factor": 1.0}, {"id": "0:0:8", "factor": 0.5}]
        self.assertEqual(edits.held_response(token, two)["notice"], {"text": edits.HELD_RELEASED, "values": {"count": 2}})
        # Replaced rows are released as well: the recipe's own face rows hold.
        with patch.object(roles, "split_held_face_outlines", return_value=([], copy.deepcopy(held), proof)):
            edits.restore(token, dict(recipe, state=dict(empty, outlines=held)))
        replaced = [{"id": "0:0:7", "factor": 0.5}]
        before = edits.held_snapshot(token)
        with patch.object(roles, "split_held_face_outlines", return_value=([], copy.deepcopy(replaced), proof)):
            edits.restore(token, dict(recipe, state=dict(empty, outlines=replaced)))
        self.assertEqual(session["heldFaceOutlines"], replaced)
        self.assertIn("notice", edits.held_response(token, before))

    def test_a_refused_restore_keeps_the_earlier_held_rows(self):
        token, session, recipe, empty, held, proof = self.held_view()
        other = [{"id": "0:0:7", "factor": 0.25}]
        # The new held rows split fine, but the rest of the recipe is invalid.
        with patch.object(roles, "split_held_face_outlines", return_value=([], copy.deepcopy(other), {"meshes": []})), \
                self.assertRaisesRegex(ValueError, "preview-only"):
            edits.restore(token, dict(recipe, state=dict(empty, outlines=other, unsupported=["pose"])))
        self.assertEqual((session["heldFaceOutlines"], session["heldFaceProof"]), (held, proof))

    def test_reedit_of_a_reopened_scene_original_packages_the_scene(self):
        token, nodes, _ = self.prepare(self.source())
        result, original = self.package(token, self.state(nodes))
        reopened, nodes, state = self.prepare(Path(result["mod_package"]["package_path"]), "primary")
        save = lambda token, value, folder: flow.export_current(token, value, self.root / folder,
            repo_root=self.root, cache_root=self.root / "game-cache")
        saved = save(reopened, state, "saved")
        # Saving copies the canonical originals ZIP unchanged; re-edit opens that copy.
        raw = edits._session(reopened)["containers"][0]["raw"]
        self.assertEqual(Path(saved["original_paths"][0]).read_bytes(), raw)
        reedit, _, none = self.prepare(Path(saved["original_paths"][0]), "primary")
        self.assertIsNone(none)
        self.assertIsNone(roles.session_metadata(reedit))
        context = edits.mod_source_context(reedit)
        changed = dict(context, containers=[dict(context["containers"][0], sha256="0" * 64)])
        self.assertIsNone(roles.register_preserved(reedit, changed))
        metadata = roles.register_preserved(reedit, context)
        self.assertEqual(metadata, roles.session_metadata(reopened))
        self.assertEqual(roles.session_metadata(reedit), metadata)
        self.assertTrue(edits._session(reedit)["allowEmptySceneReset"])
        restored = edits.restore(reedit, saved["recipe"])
        again, decoded = self.package(reedit, restored)
        self.assertTrue(fmt.is_scene_package(again["mod_package"]["package_path"]))
        self.assertEqual(decoded["manifest"]["source_suit_id"], original["manifest"]["source_suit_id"])
        # A save of the re-edit is re-editable as the scene again.
        twice, _, _ = self.prepare(Path(save(reedit, restored, "saved-again")["original_paths"][0]), "primary")
        self.assertEqual(roles.register_preserved(twice, edits.mod_source_context(twice)), metadata)
        # The same original bytes anywhere else (the person's own copy of the
        # costume they first opened) stay an ordinary costume source.
        copied = self.root / "own-copy.zip"; copied.write_bytes(raw)
        plain, nodes, _ = self.prepare(copied)
        self.assertIsNone(roles.register_preserved(plain, edits.mod_source_context(plain)))
        self.assertIsNone(roles.session_metadata(plain))
        # Nor is a save of an ordinary costume.
        ordinary, _, _ = self.prepare(Path(save(plain, self.state(nodes), "saved-plain")["original_paths"][0]))
        self.assertIsNone(roles.register_preserved(ordinary, edits.mod_source_context(ordinary)))
        self.assertFalse(edits._session(ordinary).get("allowEmptySceneReset"))

    @staticmethod
    def outline_width(raw, name):
        from webtools.core import model_outlines
        catalog = model_outlines.catalogue_sources([(edits._inspect(raw), 0)])
        return next(row["originalWidth"] for row in catalog["meshes"] if row["name"] == name)

    def test_board_only_outline_edit_survives_packaging_from_either_view(self):
        import UnityPy
        env = UnityPy.load(bundle_fixture(fmt.PLATFORMS["android"], "primary"))
        for obj in env.objects:
            if obj.type.name == "Mesh":
                tree = obj.read_typetree(); tree["m_Name"] = "BoardOnlyNeutral"; obj.save_typetree(tree)
        data = {("android", "primary"): env.file.save(),
                ("android", "unmasked"): bundle_fixture(fmt.PLATFORMS["android"], "unmasked")}
        token, nodes, _ = self.prepare(self.source(data=data))
        scene, _ = self.package(token, self.state(nodes))
        token, _, state = self.prepare(Path(scene["mod_package"]["package_path"]), "primary")
        mesh = next(row["id"] for row in edits._session(token)["outlines"]["meshes"] if row["name"] == "BoardOnlyNeutral")
        result, first = self.package(token, dict(state, outlines=[{"id": mesh, "factor": 0.5}]))
        # The save status names the part kept on this variant only.
        self.assertEqual(result["notes"], [{"text": pair_edits.SELECTED_ONLY, "values": {"names": ["BoardOnlyNeutral"]}}])
        # The unmasked body has no such mesh: it stays its original, with no rows.
        self.assertEqual([row["factor"] for row in json.loads(first["files"][first["manifest"]["authoring"]["android"]["primary"]["recipe"]["member"]])["state"]["outlines"]], [0.5])
        self.assertFalse(json.loads(first["files"][first["manifest"]["authoring"]["android"]["unmasked"]["recipe"]["member"]])["state"].get("outlines"))
        edited = self.outline_width(self.golden(first, "android", "primary"), "BoardOnlyNeutral")
        self.assertNotEqual(edited, self.outline_width(data["android", "primary"], "BoardOnlyNeutral"))
        self.assertEqual(self.outline_width(self.golden(first, "android", "unmasked"), "BodyControlNeutral"),
                         self.outline_width(data["android", "unmasked"], "BodyControlNeutral"))
        # Repackaging from the Normal face view, which cannot show that mesh,
        # writes the board's own row back instead of dropping it.
        reopened, _, state = self.prepare(Path(result["mod_package"]["package_path"]), "unmasked")
        self.assertEqual(edits.mod_source_context(reopened)["held_counterpart"][0]["outlines"], [{"id": "0" + mesh[mesh.index(":"):], "factor": 0.5}])
        again, second = self.package(reopened, state)
        # Nothing of this view stays on it alone; the board's carried row is no note.
        self.assertNotIn("notes", again)
        self.assertEqual(json.loads(second["files"][second["manifest"]["authoring"]["android"]["primary"]["recipe"]["member"]])["state"]["outlines"],
                         [{"id": "0" + mesh[mesh.index(":"):], "factor": 0.5}])
        self.assertEqual(self.outline_width(self.golden(second, "android", "primary"), "BoardOnlyNeutral"), edited)
        # Saving this view with no body edits at all (a reset) still writes the
        # board's own row back; only the node edits go.
        _, reset = self.package(reopened, {"version": 1, "savedSettingsEnabled": True, "edits": []})
        board = json.loads(reset["files"][reset["manifest"]["authoring"]["android"]["primary"]["recipe"]["member"]])["state"]
        self.assertEqual((board["edits"], board["outlines"]), ([], [{"id": "0" + mesh[mesh.index(":"):], "factor": 0.5}]))
        self.assertEqual(self.outline_width(self.golden(reset, "android", "primary"), "BoardOnlyNeutral"), edited)
        held = copy.deepcopy(edits._session(reopened)["heldCounterpart"])
        saved = flow.export_current(reopened, state, self.root / "saved", repo_root=self.root, cache_root=self.root / "game-cache")
        # Without the held rows the board would have been rebuilt unedited.
        edits._session(reopened)["heldCounterpart"] = []
        _, third = self.package(reopened, state)
        self.assertFalse(json.loads(third["files"][third["manifest"]["authoring"]["android"]["primary"]["recipe"]["member"]])["state"].get("outlines"))
        # Re-edit of that save keeps the board's row as well.
        reedit, _, _ = self.prepare(Path(saved["original_paths"][0]), "unmasked")
        self.assertIsNotNone(roles.register_preserved(reedit, edits.mod_source_context(reedit)))
        self.assertEqual(edits._session(reedit)["heldCounterpart"], held)
        _, fourth = self.package(reedit, edits.restore(reedit, saved["recipe"]))
        self.assertEqual(self.outline_width(self.golden(fourth, "android", "primary"), "BoardOnlyNeutral"), edited)
        # Those rows are the board's own: a board view of the same copy does not hold them.
        board, _, _ = self.prepare(Path(saved["original_paths"][0]), "primary")
        self.assertIsNotNone(roles.register_preserved(board, edits.mod_source_context(board)))
        self.assertEqual(edits._session(board).get("heldCounterpart", []), [])

    def test_a_saved_scene_reopens_as_the_scene_after_a_restart(self):
        token, nodes, _ = self.prepare(self.source())
        result, original = self.package(token, self.state(nodes))
        reopened, _, state = self.prepare(Path(result["mod_package"]["package_path"]), "primary")
        metadata = roles.session_metadata(reopened)
        saved = flow.export_current(reopened, state, self.root / "saved", repo_root=self.root, cache_root=self.root / "game-cache")
        copied = Path(saved["original_paths"][0])
        sidecar = copied.with_name(edits.SCENE_BINDING)
        binding = json.loads(sidecar.read_text())
        self.assertEqual(set(binding), {"format", "version", "original", "variant", "metadata", "held"})
        self.assertEqual((binding["format"], binding["version"], binding["variant"], binding["metadata"]),
                         (roles.BINDING_FORMAT, 1, "primary", metadata))
        self.assertEqual(binding["original"], {"file": copied.name, "sha256": fmt.sha(copied.read_bytes())})
        # A restart keeps nothing in memory: no session, no scene.
        with roles._LOCK: roles._SCENES.clear()
        with edits._LOCK: edits._SESSIONS.clear()
        reedit, _, _ = self.prepare(copied, "primary")
        self.assertEqual(roles.register_preserved(reedit, edits.mod_source_context(reedit)), metadata)
        again, decoded = self.package(reedit, edits.restore(reedit, saved["recipe"]))
        self.assertTrue(fmt.is_scene_package(again["mod_package"]["package_path"]))
        self.assertEqual(decoded["manifest"]["source_suit_id"], original["manifest"]["source_suit_id"])
        self.assertEqual(decoded["manifest"]["display_name"], metadata["display_name"])
        # The binding counts only as written, for exactly that file and bytes.
        good = json.loads(sidecar.read_text())
        for label, changed in (("other bytes", dict(good, original=dict(good["original"], sha256="0" * 64))),
                               ("other file", dict(good, original=dict(good["original"], file="other.zip"))),
                               ("unknown field", dict(good, extra=True)), ("other format", dict(good, format="other")),
                               ("bad name", dict(good, metadata=dict(good["metadata"], display_name=" "))),
                               ("bad target", dict(good, metadata=dict(good["metadata"], target_member_id=0))),
                               ("bad held", dict(good, held=[{"sha256": "0" * 64, "nodes": []}]))):
            with self.subTest(label):
                sidecar.write_text(json.dumps(changed))
                probe, _, _ = self.prepare(copied, "primary")
                self.assertIsNone(roles.register_preserved(probe, edits.mod_source_context(probe)))
                self.assertIsNone(roles.session_metadata(probe))
        sidecar.unlink()
        probe, _, _ = self.prepare(copied, "primary")
        self.assertIsNone(roles.register_preserved(probe, edits.mod_source_context(probe)))
        # A binding beside something that is not a scene's originals family counts for nothing.
        plain = copied.with_name("plain.zip")
        with zipfile.ZipFile(plain, "w") as archive:
            archive.writestr("body.unity", self.originals["android", "primary"])
            archive.writestr("modinstall.txt", "chara_id = 209\\ncostume_file = 'body.unity'\\n")
        sidecar.write_text(json.dumps(dict(good, original={"file": plain.name, "sha256": fmt.sha(plain.read_bytes())})))
        self.assertIsNone(roles._read_binding({"path": str(plain), "raw": plain.read_bytes(), "sha256": fmt.sha(plain.read_bytes())}))
        # Only a save of exactly one reopened container keeps the scene.
        with roles._LOCK: roles._SCENES[probe] = copy.deepcopy(metadata)
        context = {"containers": [{"sha256": "1" * 64}, {"sha256": "2" * 64}], "variants": {}}
        for index, (containers, count) in enumerate(((context["containers"], 2), (context["containers"], 1),
                                                     (context["containers"][:1], 2), (context["containers"][:1], 1))):
            folder = self.root / ("saved-%d" % index); folder.mkdir()
            paths = [str(folder / ("a%d.zip" % n)) for n in range(count)]
            roles.remember_saved_originals(probe, dict(context, containers=containers), paths)
            self.assertEqual((folder / edits.SCENE_BINDING).exists(), index == 3, index)

    def test_other_variant_texture_edit_survives_a_mod_zip_of_the_other_view(self):
        from PIL import Image
        import base64
        token, nodes, _ = self.prepare(self.source())
        result, _ = self.package(token, self.state(nodes))
        scene = Path(result["mod_package"]["package_path"])
        unmasked, _, state = self.prepare(scene, "unmasked")
        session = edits._session(unmasked)
        row = next(row for row in session["textures"]["textures"] if row["available"] and row["texture"]["source"] == 0)
        buffer = io.BytesIO(); Image.new("RGBA", (row["width"], row["height"]), (200, 30, 30, 255)).save(buffer, "PNG")
        paint = {"texture": row["texture"], "sourceSha256": row["sourceSha256"], "kind": "paint",
                 "png": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()}
        painted, first = self.package(unmasked, dict(state, textures=[paint]))
        recipe = lambda decoded, variant: json.loads(decoded["files"][decoded["manifest"]["authoring"]["android"][variant]["recipe"]["member"]])
        self.assertEqual(len(recipe(first, "unmasked")["state"]["textures"]), 1)
        painted_bare = self.golden(first, "android", "unmasked")
        # The board view cannot show that texture edit; a Mod ZIP made there keeps it.
        board, _, board_state = self.prepare(Path(painted["mod_package"]["package_path"]), "primary")
        held = edits.mod_source_context(board)["held_counterpart"]
        self.assertEqual([entry["textures"][0]["sourceSha256"] for entry in held], [row["sourceSha256"]])
        _, second = self.package(board, board_state)
        self.assertEqual(recipe(second, "unmasked")["state"]["textures"], recipe(first, "unmasked")["state"]["textures"])
        self.assertEqual(self.golden(second, "android", "unmasked"), painted_bare)
        self.assertNotEqual(painted_bare, self.golden(fmt.read_package(result["mod_package"]["package_path"]), "android", "unmasked"))
        # Its save keeps them for a re-edit in a later session too.
        saved = flow.export_current(board, board_state, self.root / "saved-board", repo_root=self.root, cache_root=self.root / "game-cache")
        with roles._LOCK: roles._SCENES.clear()
        reedit, _, _ = self.prepare(Path(saved["original_paths"][0]), "primary")
        self.assertIsNotNone(roles.register_preserved(reedit, edits.mod_source_context(reedit)))
        _, third = self.package(reedit, edits.restore(reedit, saved["recipe"]))
        self.assertEqual(self.golden(third, "android", "unmasked"), painted_bare)

    def test_authored_sources_name_every_kind_of_row(self):
        token, _, _ = self.prepare(self.source(), "primary")
        session = edits._session(token)
        node = next(iter(session["targets"]))
        state = {"edits": [{"node": node}, {"node": -1}], "outlines": [{"id": "1:0:5"}, {"id": "x"}],
                 "physics": [{"id": "2:0:1"}], "textures": [{"texture": {"source": 3}}, {"texture": {"source": "4"}}]}
        self.assertEqual(edits._authored_sources(session, state),
                         {session["targets"][node]["sourceIndex"]: {"edits"}, 1: {"outlines"}, 2: {"physics"}, 3: {"textures"}})

    def test_release_notice_names_the_kind_of_face_rows_that_released_them(self):
        from webtools.core import viewer_texture_tools
        token, session, recipe, empty, held, proof = self.held_view()
        before = edits.held_snapshot(token)
        texture = {"texture": {"source": 0, "file": 0, "id": "5"}, "sourceSha256": "0" * 64, "png": "", "kind": "paint"}
        with patch.object(viewer_texture_tools, "validate", side_effect=lambda session, rows: rows):
            edits.restore(token, dict(recipe, state=dict(empty, textures=[texture])))
        self.assertEqual(session["heldFaceOutlines"], [])
        self.assertEqual(edits.held_response(token, before)["notice"], {"text": edits.HELD_RELEASED_TEXTURES_ONE, "values": {}})
        self.assertEqual(edits.held_response(token, before * 2)["notice"], {"text": edits.HELD_RELEASED_TEXTURES, "values": {"count": 2}})
        # A Node row of that face's source releases them too.
        token, session, recipe, empty, held, proof = self.held_view()
        node, target = next((node, target) for node, target in session["targets"].items() if target["sourceIndex"] == 0)
        method = "node" if "node" in target["methods"] else "mesh"
        identity = {"node": node, "sourceIndex": 0, "transformId": target["transformId"], "serializedFile": target["serializedFile"]}
        edits.restore(token, dict(recipe, nodeIdentities=[identity],
                                  state=dict(empty, edits=[{"node": node, "method": method, "scale": [1.1, 1.1, 1.1]}])))
        self.assertEqual(session["heldFaceOutlines"], [])
        self.assertEqual(edits.held_response(token, before)["notice"], {"text": edits.HELD_RELEASED_EDITS_ONE, "values": {}})
        from webtools import i18n
        for text in (edits.HELD_RELEASED_TEXTURES, edits.HELD_RELEASED_TEXTURES_ONE, edits.HELD_RELEASED_EDITS, edits.HELD_RELEASED_EDITS_ONE):
            for language in ("ko", "ja"):
                self.assertNotEqual(i18n.tr(text, language), text)
        self.assertEqual(i18n.tr(edits.HELD_RELEASED_ONE, "ja"), "この編集レシピは顔の輪郭線を指定しているため、素顔の表示で編集した顔の輪郭線1件は保持されません。")
        self.assertEqual(i18n.tr(", ", "ja"), "、")

    def test_a_named_pair_refusal_is_sent_to_the_page_with_its_part_name(self):
        token, nodes, _ = self.prepare(self.source())
        job = Job("refusal", "viewer_body_mod")
        error = pair_edits.PairEditError(pair_edits.MISSING_OUTLINE, "Hair")
        with patch.object(pair_edits, "apply_pair_edits", side_effect=error), \
                self.assertRaisesRegex(pair_edits.PairEditError, "outline mesh: Hair"):
            flow.create_package(token, self.state(nodes), output_root=self.root / "exports", repo_root=self.root,
                cache_root=self.root / "game-cache", display_name="Neutral scene", character_id=209, job=job)
        self.assertIn({"type": "message", "text": pair_edits.MISSING_OUTLINE, "values": {"name": "Hair"}}, job._events)

    def test_counterpart_without_the_edited_parts_keeps_its_original_and_no_recipe(self):
        context, result, pair, goldens = self.raw_pair()
        body_row = {"id": "1:0:222", "factor": 0.75}
        state = {"version": 1, "savedSettingsEnabled": True, "edits": [], "unsupported": [],
                 "compensationReference": [], "outlines": [body_row]}
        result["recipe"]["state"] = copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError, "no complete native original family"):
            roles._originals_and_recipes(context, result, pair, goldens, state)
        # With no body edits both variants stay their originals, unless the
        # other variant has rows of its own: those come back only through pairing.
        empty = dict(state, outlines=[])
        self.assertEqual(roles._originals_and_recipes(context, result, pair, goldens, empty)[0], goldens)
        held = dict(context, held_counterpart=[{"sha256": fmt.sha(goldens["android", "primary"]), "outlines": [{"id": "0:0:7", "factor": .5}]}])
        with self.assertRaisesRegex(ValueError, "no complete native original family"):
            roles._originals_and_recipes(held, result, pair, goldens, empty)
        # Pair editing reported the board as unchanged (it has no such mesh).
        result["paired_edits"] = [{"variant": "primary", "unchanged": True, "original_sha256": fmt.sha(goldens["android", "primary"]),
                                   "kept": {"physics": [], "outlines": ["1:0:222"], "names": ["Mask"]}}]
        originals, recipes = roles._originals_and_recipes(context, result, pair, goldens, state)
        self.assertEqual(originals, goldens)
        self.assertEqual(recipes["android", "primary"]["state"]["edits"], [])
        self.assertFalse(recipes["android", "primary"]["state"].get("outlines"))
        self.assertEqual(recipes["android", "unmasked"]["state"]["outlines"], [{"id": "0:0:222", "factor": 0.75}])
        # The unchanged report must be about the bytes in the pair.
        result["paired_edits"][0]["original_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "paired canonical original is missing"):
            roles._originals_and_recipes(context, result, pair, goldens, state)

    def face_scene(self, shipped):
        """A scene keeping a face for authoring; its Mod ZIP shipped a runtime face or not."""
        token, nodes, _ = self.prepare(self.source())
        _, decoded = self.package(token, self.state(nodes))
        manifest, files = decoded["manifest"], decoded["files"]
        info = edits._inspect(bundle_fixture(fmt.PLATFORMS["android"], "primary", unit_breast=True))
        for obj in info["env"].objects:
            if obj.type.name == "Texture2D":
                tree = obj.read_typetree(); tree["m_Name"] = "neutral_face_texture"; obj.save_typetree(tree)
        face = info["env"].file.save(packer="original")
        for source in manifest.pop("source_archives"):
            del files[source["file"]["member"]]
        recipe = json.dumps(roles._empty_recipe(face, "android_face.unity")).encode()
        files["originals/android_face.unity"], files["recipes/android_face.json"] = face, recipe
        manifest["requires"] = [fmt.SHARED_CAPABILITY, fmt.FACE_AUTHORING_CAPABILITY]
        manifest["face_authoring"] = {"android": {"original": fmt.reference("originals/android_face.unity", face, "android"),
                                                  "recipe": fmt.reference("recipes/android_face.json", recipe)}}
        if shipped:
            from webtools.core import bundle_identity
            runtime, _ = bundle_identity.isolate_verified_bundle(face, "private-runtime-face")
            files["dependencies/android_face.unity"] = runtime
            manifest["dependencies"]["android"]["facedynamic"] = fmt.reference("dependencies/android_face.unity", runtime, "android")
        path = self.root / ("face-scene-%s.zip" % shipped)
        path.write_bytes(fmt.encode_package(manifest, files))
        return path, face

    def test_a_reopened_scene_includes_its_face_only_when_its_mod_zip_shipped_it(self):
        for shipped in (False, True):
            path, _ = self.face_scene(shipped)
            for variant in fmt.VARIANTS:
                with self.subTest(shipped=shipped, variant=variant):
                    token, _, _ = self.prepare(path, variant)
                    context = edits.mod_source_context(token)
                    # Its originals ZIP always declares the face kept for authoring.
                    self.assertTrue(flow._manifest_metadata(context, "en")["has_face"])
                    self.assertIs(roles.session_metadata(token)["face_included"], shipped)
                    self.assertIs(flow.ships_own_face(context), shipped)
                    packaging = flow.metadata(context, repo_root=self.root, cache_root=self.root / "game-cache")
                    self.assertEqual((packaging["hasFaceCompanions"], packaging["faceIncluded"]), (True, shipped))
            # A save of the reopened scene keeps that choice for Re-edit from original, after a restart too.
            token, _, state = self.prepare(path, "primary")
            saved = flow.export_current(token, state, self.root / ("saved-%s" % shipped), repo_root=self.root,
                                        cache_root=self.root / "game-cache")
            copied = Path(saved["original_paths"][0])
            self.assertIs(json.loads(copied.with_name(edits.SCENE_BINDING).read_text())["metadata"]["face_included"], shipped)
            with roles._LOCK: roles._SCENES.clear()
            reedit, _, _ = self.prepare(copied, "primary")
            context = edits.mod_source_context(reedit)
            # Until the scene is bound it is a costume ZIP with its own face.
            self.assertIs(flow.ships_own_face(context), True)
            self.assertIs(roles.register_preserved(reedit, context)["face_included"], shipped)
            self.assertIs(flow.ships_own_face(context), shipped)
            self.assertIs(flow.metadata(context, repo_root=self.root, cache_root=self.root / "game-cache")["faceIncluded"], shipped)
        # A binding written before the record existed counts as no shipped face;
        # anything but a true/false record is no binding at all.
        sidecar = copied.with_name(edits.SCENE_BINDING)
        good = json.loads(sidecar.read_text())
        older = dict(good, metadata={key: value for key, value in good["metadata"].items() if key != "face_included"})
        for label, binding, expected in (("older", older, False), ("not a boolean", dict(good, metadata=dict(good["metadata"], face_included=1)), None),
                                         ("text", dict(good, metadata=dict(good["metadata"], face_included="true")), None)):
            with self.subTest(label):
                sidecar.write_text(json.dumps(binding))
                probe, _, _ = self.prepare(copied, "primary")
                context = edits.mod_source_context(probe)
                metadata = roles.register_preserved(probe, context)
                if expected is None:
                    self.assertIsNone(metadata)
                else:
                    self.assertNotIn("face_included", metadata)
                    self.assertIs(flow.ships_own_face(context), expected)

    def test_a_scene_face_kept_for_authoring_is_the_games_own_only_by_its_catalog_bytes(self):
        from webtools.core import bundle_identity, model_faces, viewer_mod_package
        path, face = self.face_scene(False)
        token, _, state = self.prepare(path, "unmasked")
        context = edits.mod_source_context(token)
        cache = self.root / "face-cache"
        cabs = frozenset(name.lower() for name in bundle_identity._cab_names(face))
        self.assertEqual(flow.catalog_face_cabs(context, cache), frozenset(), "Nothing is cached yet")
        cached = cache / "models" / ("ch0209_" + "0" * 24 + ".unity")
        model_faces._save(cached, face, 209)
        self.assertEqual(flow.catalog_face_cabs(context, cache), cabs)
        self.assertEqual(flow.catalog_face_cabs(context, None), frozenset())
        # Only a catalog face file of the face cache, with its recorded bytes, counts.
        renamed = cached.with_name("face.unity"); cached.rename(renamed); Path(str(cached) + ".json").rename(str(renamed) + ".json")
        self.assertEqual(flow.catalog_face_cabs(context, cache), frozenset())
        renamed.rename(cached); Path(str(renamed) + ".json").rename(str(cached) + ".json")
        cached.write_bytes(face[:-1] + bytes([face[-1] ^ 1]))
        self.assertEqual(flow.catalog_face_cabs(context, cache), frozenset(), "Changed cached bytes prove nothing")
        model_faces._save(cached, self.originals["android", "unmasked"], 209)
        self.assertEqual(flow.catalog_face_cabs(context, cache), frozenset(), "Another face's bytes prove nothing")
        model_faces._save(cached, face, 209)
        record = json.loads(Path(str(cached) + ".json").read_text())
        Path(str(cached) + ".json").write_text(json.dumps(dict(record, size=record["size"] + 1)))
        self.assertEqual(flow.catalog_face_cabs(context, cache), frozenset(), "A damaged cache record proves nothing")
        model_faces._save(cached, face, 209)
        # Only the cached file recorded with the face's bytes is read.
        model_faces._save(cached.with_name("ch0209_" + "1" * 24 + ".unity"), self.originals["android", "primary"], 209)
        with patch.object(model_faces, "_cached", wraps=model_faces._cached) as read:
            self.assertEqual(flow.catalog_face_cabs(context, cache), cabs)
        self.assertEqual([call.args[0] for call in read.call_args_list], [str(cached)])
        # A scene that ships its own face, or any other costume ZIP, has no such face.
        shipped, _ = self.face_scene(True)
        other, _, _ = self.prepare(shipped, "unmasked")
        self.assertEqual(flow.catalog_face_cabs(edits.mod_source_context(other), cache), frozenset())
        plain = self.root / "plain-face.zip"; plain.write_bytes(context["containers"][0]["raw"])
        ordinary, _, _ = self.prepare(plain, "unmasked")
        self.assertIsNone(roles.session_metadata(ordinary))
        self.assertEqual(flow.catalog_face_cabs(edits.mod_source_context(ordinary), cache), frozenset())
        # Save mod ZIP hands the proof to the exclusion check only when the face is left out.
        calls = []
        def spy(*args, **kwargs):
            calls.append(kwargs.get("catalog_face_cabs"))
            return package(*args, **kwargs)
        package = viewer_mod_package.package_saved_export
        token, _, state = self.prepare(path, "unmasked")
        for include, root in ((False, cache), (True, cache), (False, None)):
            with self.subTest(include=include, root=root), patch.object(viewer_mod_package, "package_saved_export", side_effect=spy):
                result = flow.create_package(token, state, output_root=self.root / "exports", repo_root=self.root,
                    cache_root=self.root / "game-cache", display_name="Face scene", character_id=209,
                    include_face_edits=include, face_cache_root=root, job=Job("face", "viewer_body_mod"))
            decoded = fmt.read_package(result["mod_package"]["package_path"])
            self.assertEqual(decoded["manifest"]["dependencies"]["android"]["facedynamic"] is not None, include)
            # The face stays the authoring original either way.
            original = decoded["manifest"]["face_authoring"]["android"]["original"]
            self.assertEqual(decoded["files"][original["member"]], face)
        self.assertEqual(calls, [cabs, None, None])

    def test_a_scene_face_without_a_cached_original_is_checked_as_automatic_faces_are_read(self):
        import catalog_face_fixture
        from webtools.core import bundle_identity, model_faces, viewer_mod_package
        self.addCleanup(catalog_face_fixture.install_extractor(self.root))
        path, face = self.face_scene(False)
        token, _, state = self.prepare(path, "unmasked")
        context = edits.mod_source_context(token)
        cache, cabs = self.root / "face-cache", frozenset(name.lower() for name in bundle_identity._cab_names(face))
        # The game's catalog lists Rina's face; this device has it in a local pack only.
        descriptors = catalog_face_fixture.write_catalog(self.root, 209, {"face209": ("packface209", face)})
        cached = cache / "models" / model_faces._cache_name(209, descriptors["face209"])
        self.assertEqual(flow.catalog_face_cabs(context, cache), frozenset(), "The face cache alone proves nothing yet")
        with patch.object(model_faces, "_download_with_deadline", side_effect=AssertionError("The local pack comes first")) as never:
            self.assertEqual(flow.scene_face_proof(context, cache, repo_root=self.root, download=True),
                             {"cabs": cabs, "unchecked": False})
        never.assert_not_called()
        self.assertEqual(model_faces._cached(cached), face, "Read into the face cache as automatic faces are")
        self.assertEqual(flow.face_option(context, repo_root=self.root, face_cache_root=cache), {"faceIncluded": False})
        self.assertEqual(flow.catalog_face_cabs(context, cache), cabs, "Later checks need only the cache")
        # Neither a cache copy nor a pack: it cannot be checked here...
        cached.unlink(); Path(str(cached) + ".json").unlink(); (self.root / "static" / "packface209").unlink()
        self.assertEqual(flow.scene_face_proof(context, cache, repo_root=self.root), {"cabs": frozenset(), "unchecked": True})
        self.assertEqual(flow.face_option(context, repo_root=self.root, face_cache_root=cache),
                         {"faceIncluded": False, "faceCheck": "unchecked"})
        # A check that fails, or a catalog that does not list the member's
        # costume, proves nothing either.
        with patch.object(flow, "_catalog_proof", side_effect=RuntimeError("The catalog could not be read")):
            self.assertEqual(flow.scene_face_proof(context, cache, repo_root=self.root), {"cabs": frozenset(), "unchecked": True})
        import sqlite3
        with sqlite3.connect(self.root / "assets" / "db" / "gl" / "masterdata.db") as db:
            db.execute("DELETE FROM m_member_init WHERE member_m_id=209")
            db.execute("DELETE FROM m_suit WHERE member_m_id=209")
        self.assertEqual(flow.scene_face_proof(context, cache, repo_root=self.root), {"cabs": frozenset(), "unchecked": True})
        catalog_face_fixture.write_catalog(self.root, 209, {"face209": ("packface209", face)}, local=False)
        # ...unless the open may download it, and then it keeps a download's place.
        with patch.object(model_faces, "_download_with_deadline", return_value=face) as download:
            self.assertEqual(flow.face_option(context, repo_root=self.root, face_cache_root=cache, download=True),
                             {"faceIncluded": False})
        self.assertEqual(download.call_count, 1)
        self.assertTrue(model_faces._compared(cached))
        # Another face of the original's size is not the game's own: no proof, but checked.
        catalog_face_fixture.write_catalog(self.root, 209, {"face209": ("packface209", face[:-1] + bytes([face[-1] ^ 1]))})
        cached.unlink(); Path(str(cached) + ".json").unlink()
        self.assertEqual(flow.scene_face_proof(context, cache, repo_root=self.root), {"cabs": frozenset(), "unchecked": False})
        # A scene that ships its face, or no face cache, is never checked.
        shipped, _ = self.face_scene(True)
        other, _, _ = self.prepare(shipped, "unmasked")
        self.assertEqual(flow.scene_face_proof(edits.mod_source_context(other), cache, repo_root=self.root),
                         {"cabs": frozenset(), "unchecked": False})
        self.assertEqual(flow.scene_face_proof(context, None, repo_root=self.root), {"cabs": frozenset(), "unchecked": False})
        # Save mod ZIP: a refusal over a face that could not be checked says so.
        for stale in (self.root / "static" / "packface209", cached, cache / "packs" / "packface209"):
            stale.unlink(missing_ok=True); Path(str(stale) + ".json").unlink(missing_ok=True)
        def refuse(*args, **kwargs):
            raise viewer_mod_package.ModPackageError(viewer_mod_package.FACE_EXCLUSION_REFUSED)
        for pack, message in ((None, flow.STOCK_FACE_UNCHECKED), (face[:-1] + bytes([face[-1] ^ 1]), viewer_mod_package.FACE_EXCLUSION_REFUSED)):
            if pack is not None:
                catalog_face_fixture.write_catalog(self.root, 209, {"face209": ("packface209", pack)})
            # Saving never downloads, even where the face context would allow it.
            with self.subTest(message=message[:30]), patch.object(viewer_mod_package, "package_saved_export", side_effect=refuse), \
                    patch.object(model_faces, "_download_with_deadline", side_effect=AssertionError("Saving never downloads")) as never:
                with self.assertRaises(viewer_mod_package.ModPackageError) as refused:
                    flow.create_package(token, state, output_root=self.root / "exports", repo_root=self.root,
                        cache_root=self.root / "game-cache", display_name="Face scene", character_id=209,
                        include_face_edits=False, face_cache_root=cache,
                        face_context={"repo_root": str(self.root), "cache_dir": str(cache), "allow_download": True},
                        job=Job("face", "viewer_body_mod"))
                self.assertEqual(str(refused.exception), message)
                never.assert_not_called()
        from webtools import i18n
        for language, option in (("ko", "이 코스튬의 얼굴·입 편집 포함"), ("ja", "この衣装の顔・口の編集を含める")):
            translated = i18n.tr(flow.STOCK_FACE_UNCHECKED, language)
            self.assertIn(option, translated)
            self.assertIn(i18n.tr("Load from game assets", language), translated)


if __name__ == "__main__": unittest.main()
