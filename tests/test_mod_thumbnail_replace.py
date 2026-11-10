"""Source-bound existing-ZIP updates: original bytes and unrelated payloads."""
import ast
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import UnityPy
from PIL import Image

from webtools.core import mod_thumbnail_replace as updater, viewer_scene_format as fmt
from webtools.tools.common import run_multi
from webtools.tools.thumbnail import run_thumbnail_replace


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Job:
    def __init__(self):
        self.logs, self.outputs = [], []
    def log(self, value):
        self.logs.append(value)
    def progress(self, done, total):
        pass
    def should_stop(self):
        return False
    def add_output(self, value):
        self.outputs.append(value)


class ModThumbnailReplaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "new-copies"
        self.raw = (Path(__file__).parent / "fixtures/viewer_persistence.unity").read_bytes()
        from webtools import filebrowser
        self.jail = patch.object(filebrowser, "is_within_allowed",
            side_effect=lambda path: Path(path).resolve().is_relative_to(self.root))
        self.jail.start()
        self.addCleanup(self.jail.stop)

    def model(self, label):
        env = UnityPy.load(self.raw)
        for obj in env.objects:
            if obj.type.name == "Mesh":
                tree = obj.read_typetree(); tree["m_Name"] = label; obj.save_typetree(tree)
        env.file._m_target_platform = 13
        return env.file.save(packer="original")

    @staticmethod
    def png(color, size=64):
        output = io.BytesIO()
        Image.new("RGBA", (size, size), color).save(output, format="PNG")
        return output.getvalue()

    def legacy(self, name="first.zip", owner=6, *, directory=False, dynamic=False):
        path = self.root / name
        prefix = "nested/" if directory else ""
        manifest = ("\ufeff# 기존 주석·설정 그대로\r\nchara_id = " + str(owner) + "\r\n"
                    "costume_file = 'body.unity'\r\n"
                    "thumbnail_file  = ('old.png') # keep this comment\r\n"
                    "costume_name_ko = '원래 의상'\r\ncustom_settings = {'keep': [1, 'yes']}\r\n")
        if dynamic:
            manifest += "unsupported = __import__('os').system('exit 99')\r\n"
        entries = {prefix + "body.unity": self.model(name), prefix + "old.png": self.png("blue"),
                   prefix + "opaque.bin": b"preserve this exact unrelated payload\x00\xff", prefix + "modinstall.txt": manifest.encode()}
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b"original zip comment"
            if directory:
                archive.writestr(prefix, b"")
            for key, raw in entries.items():
                archive.writestr(key, raw)
        return path

    def receipt(self, path, *, color="red", variant="auto", size=64):
        source = updater.inspect(str(path), variant=variant)
        png = self.png(color, size)
        return {"png": png, "sha256": sha(png), "source_path": str(path), "source_sha256": sha(path.read_bytes()),
                "size": size, "variant": source["variant"], "character_id": source["characterId"],
                "profile_digest": "a" * 64, "cache_key": "b" * 64,
                "quality": {"renderer": "SifasMaterial", "highQuality": True, "animation": False, "supersample": 2}}

    def assert_preserved(self, source, result):
        with zipfile.ZipFile(source) as before, zipfile.ZipFile(result["output_path"]) as after:
            self.assertEqual(before.comment, after.comment)
            self.assertEqual(set(after.namelist()) - set(before.namelist()), {result["thumbnail_member"]})
            for name in before.namelist():
                if name == result["manifest_member"]:
                    old = before.read(name).decode("utf-8-sig")
                    new = after.read(name).decode("utf-8-sig")
                    def neutral(text):
                        node = next(n.value for n in ast.parse(text).body if isinstance(n, ast.Assign)
                                    and n.targets[0].id == "thumbnail_file")
                        raw = text.encode(); offsets = [0]
                        for line in raw.splitlines(keepends=True): offsets.append(offsets[-1] + len(line))
                        start, end = offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset
                        return raw[:start] + b"'UNCHANGED_THUMBNAIL_REFERENCE'" + raw[end:]
                    self.assertEqual(neutral(old), neutral(new))
                    self.assertEqual(before.read(name).startswith(b"\xef\xbb\xbf"), after.read(name).startswith(b"\xef\xbb\xbf"))
                else:
                    self.assertEqual(before.read(name), after.read(name), name)
            self.assertEqual(sha(after.read(result["thumbnail_member"])), result["thumbnail_sha256"])

    def test_single_new_copy_preserves_models_settings_old_png_comment_and_directory(self):
        path = self.legacy(directory=True)
        original = path.read_bytes()
        result = updater.replace(path, self.output, self.receipt(path), size=64)
        self.assert_preserved(path, result)
        self.assertEqual(path.read_bytes(), original)
        self.assertNotEqual(Path(result["output_path"]), path)
        self.assertEqual(sha(Path(result["output_path"]).read_bytes()), result["sha256"])

    def test_other_zip_member_variant_size_and_changed_source_receipts_are_rejected(self):
        first = self.legacy()
        other = self.legacy("second.zip")
        receipt = self.receipt(first)
        for changes in ({"character_id": 201}, {"variant": "unmasked"}, {"size": 256}, {"source_sha256": "0" * 64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                updater.replace(first, self.output, {**receipt, **changes}, size=64)
        with self.assertRaisesRegex(ValueError, "different or changed"):
            updater.replace(other, self.output, receipt, size=64)
        with zipfile.ZipFile(first, "a") as archive:
            archive.writestr("changed.bin", b"source changed after render")
        with self.assertRaisesRegex(ValueError, "different or changed"):
            updater.replace(first, self.output, receipt, size=64)
        self.assertFalse(self.output.exists())

    def test_dynamic_manifest_is_rejected_without_executing_or_publishing(self):
        path = self.legacy(dynamic=True)
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "not executed"):
            updater.inspect(path)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(self.output.exists())

    def test_ordinary_legacy_default_primary_has_no_explicit_archive_variant_choice(self):
        path = self.legacy()
        source = path.read_bytes()
        with updater.render_inputs(path, self.root / "render-cache", sha(source)) as expanded:
            self.assertEqual(len(expanded.paths), 1)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(Path(expanded.paths[0]).read_bytes(), archive.read("body.unity"))
            self.assertEqual(expanded.render_sources, expanded.paths)
        self.assertEqual(path.read_bytes(), source)

    def test_cancel_and_final_archive_limits_leave_no_partial_output(self):
        path = self.legacy()
        source = path.read_bytes()
        receipt = self.receipt(path)
        calls = iter([False, True])
        with self.assertRaisesRegex(ValueError, "cancelled"):
            updater.replace(path, self.output, receipt, size=64, should_stop=lambda: next(calls))
        self.assertEqual(list(self.output.iterdir()), [])
        with patch.object(updater.viewer_archive, "MAX_ENTRIES", 4), self.assertRaisesRegex(ValueError, "entry or unpacked"):
            updater.replace(path, self.output, receipt, size=64)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(path.read_bytes(), source)

    def test_real_single_and_common_multi_adapters_register_each_new_zip_output(self):
        paths = [self.legacy("first.zip", 6), self.legacy("second.zip", 201)]
        originals = {str(path): path.read_bytes() for path in paths}
        receipts = {str(path): self.receipt(path, color=color) for path, color in zip(paths, ["red", "green"])}
        params = {"mode": "multi", "in_paths": "\n".join(map(str, paths)), "out_dir": str(self.output), "thumbnail_size": 64}
        plan = updater.plan_inputs(params)
        self.assertEqual([item["characterId"] for item in plan["items"]], [6, 201])
        job = Job()
        with patch("webtools.core.viewer_thumbnails.updater_provider", return_value=lambda path: receipts[path], create=True):
            text = run_multi(run_thumbnail_replace, job, params)
        self.assertIn("ok=2 fail=0", text)
        self.assertEqual(len(job.outputs), 2)
        reports = [json.loads(line.split(" ", 1)[1]) for line in job.logs if line.startswith("THUMBNAIL_UPDATE ")]
        self.assertEqual(len(reports), 2)
        for path, report in zip(paths, reports):
            self.assert_preserved(path, report)
            self.assertEqual(path.read_bytes(), originals[str(path)])
        one = Job()
        with patch("webtools.core.viewer_thumbnails.updater_provider", return_value=lambda path: receipts[path], create=True):
            run_thumbnail_replace(one, {**params, "mode": "single", "in_path": str(paths[0]), "in_paths": ""})
        self.assertEqual(len(one.outputs), 1)
        self.assertNotIn(one.outputs[0], job.outputs)

    def scene(self):
        files = {}
        def add(name, raw, platform=False):
            files[name] = raw
            return fmt.reference(name, raw, "android" if platform else None)
        board = add("models/current-board.unity", self.model("CURRENT-board"), True)
        bare = add("models/current-bare.unity", self.model("CURRENT-bare"), True)
        manifest = {"format": fmt.FORMAT, "version": 2, "requires": [fmt.SHARED_CAPABILITY],
                    "character_id": 209, "target_member_id": 6, "default_variant": "unmasked", "display_name": "Shared Rina",
                    "platforms": {"android": {"navi_board": board, "mv_board": board, "mv_unmasked": bare}},
                    "canonical_goldens": {"android": {}}, "authoring": {"android": {}},
                    "thumbnail": add("old.png", self.png("blue")), "dependencies": {"android": {"facedynamic": None}},
                    "navi_sync": {"android": {}}, "source_suit_id": None, "source_provenance": None}
        for variant, role in (("primary", "mv_board"), ("unmasked", "mv_unmasked")):
            manifest["canonical_goldens"]["android"][role] = add("goldens/" + variant + ".unity", self.model("GOLDEN-" + variant), True)
            raw = self.model("ORIGINAL-" + variant)
            original = add("originals/" + variant + ".unity", raw, True)
            recipe = {"format": "elichika-viewer-body-edit", "version": 1,
                      "sources": [{"name": variant, "sha256": sha(raw), "container": 0, "member": None}],
                      "originals": [{"name": variant, "sha256": sha(raw)}],
                      "state": {"version": 1, "savedSettingsEnabled": True, "edits": []}, "nodeIdentities": []}
            manifest["authoring"]["android"][variant] = {"original": original,
                "recipe": add("recipes/" + variant + ".json", json.dumps(recipe).encode())}
        path = self.root / "scene.zip"
        path.write_bytes(fmt.encode_package(manifest, files))
        return path, manifest, files

    def test_scene_recipient_reference_hash_and_every_nonthumbnail_resource_are_preserved(self):
        path, manifest, files = self.scene()
        with zipfile.ZipFile(path, "a") as archive:
            archive.comment = b"preserve-my-scene-note"
        original = path.read_bytes()
        result = updater.replace(path, self.output, self.receipt(path), size=64)
        updated = fmt.read_package(result["output_path"])
        expected = copy.deepcopy(manifest); expected["thumbnail"] = fmt.reference("old.png", self.receipt(path)["png"])
        self.assertEqual(updated["manifest"], expected)
        for name, raw in files.items():
            if name != "old.png":
                self.assertEqual(updated["files"][name], raw, name)
        self.assertEqual(result["character_id"], 6)
        with zipfile.ZipFile(result["output_path"]) as archive:
            self.assertEqual(archive.comment, b"preserve-my-scene-note")
        self.assertEqual(path.read_bytes(), original)

    def test_scene_render_uses_current_selected_role_not_canonical_unedited_original(self):
        path, manifest, files = self.scene()
        cache = self.root / "cache"
        with updater.render_inputs(path, cache, sha(path.read_bytes())) as expanded:
            self.assertEqual(len(expanded.paths), 1)
            self.assertEqual(Path(expanded.paths[0]).read_bytes(), files[manifest["platforms"]["android"]["mv_unmasked"]["member"]])
            self.assertNotEqual(Path(expanded.paths[0]).read_bytes(), files[manifest["authoring"]["android"]["unmasked"]["original"]["member"]])
            self.assertEqual(expanded.render_sources, expanded.paths)
            rendered = Path(expanded.paths[0])
        self.assertFalse(rendered.exists())

    def test_scene_execution_graph_dependencies_are_loaded_but_not_selected_as_costume_roots(self):
        path, manifest, files = self.scene()
        dependency = self.model("CURRENT-DEPENDENCY")
        files["execution/dependency.unity"] = dependency
        roots = manifest["platforms"]["android"]
        manifest["execution_model_graph"] = {"android": {"nodes": {
            "board": {"resource": roots["mv_board"], "model_dependencies": ["dependency"], "shared_shader_dependencies": []},
            "bare": {"resource": roots["mv_unmasked"], "model_dependencies": [], "shared_shader_dependencies": []},
            "dependency": {"resource": fmt.reference("execution/dependency.unity", dependency, "android"),
                           "model_dependencies": [], "shared_shader_dependencies": []}},
            "role_bindings": {"navi_board": "board", "mv_board": "board", "mv_unmasked": "bare"}}}
        path.write_bytes(fmt.encode_package(manifest, files))
        source = path.read_bytes()
        with updater.render_inputs(path, self.root / "cache", sha(source), variant="primary") as expanded:
            self.assertEqual(len(expanded.paths), 2)
            self.assertEqual(Path(expanded.paths[0]).read_bytes(), files[roots["mv_board"]["member"]])
            self.assertEqual(Path(expanded.paths[1]).read_bytes(), dependency)
            self.assertEqual(expanded.render_sources, [expanded.paths[0]])
        result = updater.replace(path, self.output, self.receipt(path, variant="primary"), size=64, variant="primary")
        changed = fmt.read_package(result["output_path"])
        self.assertEqual(changed["manifest"]["execution_model_graph"], manifest["execution_model_graph"])
        self.assertEqual(changed["files"]["execution/dependency.unity"], dependency)
        self.assertEqual(path.read_bytes(), source)


if __name__ == "__main__":
    unittest.main()
