"""Actual neutral Unity bundles exercise the production scene pipeline."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from webtools.core import model_edits as edits, model_viewer, viewer_archive
from webtools.core import viewer_mod_flow as flow, viewer_scene_format as fmt, viewer_scene_roles as roles
from webtools.jobs import Job
from viewer_scene_fixture import bundle_fixture


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

    def prepare(self, path):
        with viewer_archive.expand_inputs([str(path)], self.root / "cache") as expanded:
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
                    self.assertEqual(set(decoded["manifest"]["platforms"][platform]), set(fmt.ROLES))
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
