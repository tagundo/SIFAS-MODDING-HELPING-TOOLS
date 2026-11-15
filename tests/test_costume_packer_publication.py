"""Archive publication stays bound to the selected plan through every read."""
import ast
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import unity_costumemod_packer as packer
from test_costume_packer_selection import rina_fixture


class CostumePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / "out"
        self.output.mkdir()
        environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root / "library")})
        environment.start(); self.addCleanup(environment.stop)

    def source(self, name, platform=9, masked=False):
        path = self.root / name
        path.write_bytes(rina_fixture(platform, masked))
        return str(path)

    def pair(self):
        return self.source("primary.unity", masked=True), self.source("unmasked.unity")

    def binding(self, paths):
        return {path: {"owner": 209, "region": "gl", "suit_id": 1,
            "variant": "primary" if "unmasked" not in Path(path).name else "unmasked",
            "platform": packer.detect_bundle_platform(path),
            "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()} for path in paths}

    def write(self, paths, *, thumbnail=None, bindings=None, messages=None):
        return packer.run_pack_jobs(paths, str(self.output), source_bindings=bindings,
            log=(messages.append if messages is not None else lambda text: None),
            thumbnail_provider=thumbnail or (lambda *args: b"unchanged thumbnail"))

    def assert_no_pending(self):
        self.assertEqual(list(self.output.glob(".costume-pack-*")), [])

    def test_callback_swapped_bound_companion_fails_and_preserves_prior_valid_installer(self):
        primary, helper = self.pair()
        bindings = self.binding([primary, helper])
        self.assertEqual(self.write([primary, helper], bindings=bindings), (1, 0))
        output = next(self.output.glob("*.zip"))
        previous = output.read_bytes()
        messages = []
        def mutate(*args):
            Path(helper).write_bytes(rina_fixture(13, False, "0002"))
            return b"thumbnail"
        self.assertEqual(self.write([primary, helper], thumbnail=mutate, bindings=bindings, messages=messages), (0, 1))
        self.assertEqual(output.read_bytes(), previous)
        self.assertTrue(zipfile.is_zipfile(output))
        diagnostic = "\n".join(messages)
        self.assertIn(Path(helper).name, diagnostic)
        self.assertIn("expected SHA256 " + bindings[helper]["sha256"], diagnostic)
        self.assertIn("current SHA256 " + hashlib.sha256(Path(helper).read_bytes()).hexdigest(), diagnostic)
        self.assert_no_pending()

    def test_callback_swapped_main_is_also_rejected(self):
        primary, helper = self.pair()
        def mutate(*args):
            Path(primary).write_bytes(rina_fixture(13, True, "0002"))
            return b"thumbnail"
        self.assertEqual(self.write([primary, helper], thumbnail=mutate), (0, 1))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_combined_installer_verifies_all_four_selected_members(self):
        paths = [self.source("rinaapk.unity", 13, True), self.source("unmaskedapk.unity", 13),
                 self.source("rinaios.unity", 9, True), self.source("unmaskedios.unity", 9)]
        self.assertEqual(self.write(paths), (1, 0))
        output = next(self.output.glob("*.zip")); previous = output.read_bytes()
        with zipfile.ZipFile(output) as archive:
            fields = {node.targets[0].id: ast.literal_eval(node.value)
                      for node in ast.parse(archive.read("modinstall.txt").decode()).body}
            for key, path in zip(("costume_file", "rina_unmask_costume_file",
                                  "costume_file_ios", "rina_unmask_costume_file_ios"), paths):
                self.assertEqual(archive.read(fields[key]), Path(path).read_bytes())
        def mutate(*args):
            Path(paths[-1]).write_bytes(rina_fixture(13, False, "0002"))
            return b"thumbnail"
        self.assertEqual(self.write(paths, thumbnail=mutate), (0, 1))
        self.assertEqual(output.read_bytes(), previous)
        self.assert_no_pending()

    def test_mid_read_mutation_is_detected_before_atomic_publish(self):
        path = self.root / "streamed.unity"
        path.write_bytes(b"A" * (packer.ZIP_COPY_CHUNK_BYTES * 3))
        original = hashlib.sha256(path.read_bytes()).hexdigest()
        output = self.output / "streamed.zip"
        output.write_bytes(b"prior output")
        real_open = open
        changed = []
        class ChangingReader:
            def __init__(self, handle):
                self.handle = handle
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.handle.close()
            def read(self, size):
                value = self.handle.read(size)
                if value and not changed:
                    changed.append(True)
                    with real_open(path, "r+b") as edited:
                        edited.seek(packer.ZIP_COPY_CHUNK_BYTES)
                        edited.write(b"B" * packer.ZIP_COPY_CHUNK_BYTES)
                return value
        def controlled_open(filename, mode="r", *args, **kwargs):
            handle = real_open(filename, mode, *args, **kwargs)
            return ChangingReader(handle) if os.fspath(filename) == str(path) and mode == "rb" else handle
        with patch.object(packer, "open", side_effect=controlled_open, create=True), \
             self.assertRaisesRegex(ValueError, "changed after planning"):
            packer.create_zip_package(str(output), str(path), b"thumbnail", "thumb.png", "chara_id = 1",
                expected_hashes={str(path): original})
        self.assertTrue(changed)
        self.assertEqual(output.read_bytes(), b"prior output")
        self.assert_no_pending()

    def test_public_writer_without_hash_argument_remains_compatible_and_crc_failure_preserves_output(self):
        path = self.root / "selected.unity"; path.write_bytes(b"selected original bytes")
        output = self.output / "public.zip"
        self.assertTrue(packer.create_zip_package(str(output), str(path), b"thumbnail", "thumb.png", "chara_id = 1"))
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.read(path.name), path.read_bytes())
        previous = output.read_bytes()
        with patch.object(packer.zipfile.ZipFile, "testzip", return_value=path.name), \
             self.assertRaisesRegex(ValueError, "CRC"):
            packer.create_zip_package(str(output), str(path), b"thumbnail", "thumb.png", "chara_id = 1")
        self.assertEqual(output.read_bytes(), previous)
        self.assert_no_pending()

    def test_missing_planned_companion_hash_cannot_be_silently_trusted(self):
        primary, helper = self.pair()
        with self.assertRaisesRegex(ValueError, "no SHA256"):
            packer.create_zip_package(str(self.output / "missing.zip"), primary, b"thumbnail", "thumb.png",
                "chara_id = 209", helper, expected_hashes={primary: hashlib.sha256(Path(primary).read_bytes()).hexdigest()})
        self.assertEqual(list(self.output.iterdir()), [])

    def test_desktop_gui_writer_passes_exact_planned_hashes(self):
        primary, helper = self.pair()
        expected = {}
        _, _, companions, platforms = packer.prepare_pack_jobs([primary, helper],
            log=lambda text: None, expected_hashes=expected)
        gui = object.__new__(packer.UnityAssetBundleModPackerAutoCharaID)
        value = lambda item: SimpleNamespace(get=lambda: item)
        gui.auto_chara_id = value(True); gui.chara_id = value(0); gui.thumbnail_size = value(256)
        gui.append_platform_suffix = value(True); gui.output_to_bundle_location = value(False)
        gui.output_dir = value(str(self.output)); gui.rina_unmasked_by_path = companions
        gui.expected_source_hashes = expected
        gui.log = lambda text: None
        gui.update_current_progress = gui.update_current_status = lambda *args: None
        def mutate(*args):
            Path(helper).write_bytes(rina_fixture(13, False, "0002"))
            return b"thumbnail"
        with patch.object(packer, "extract_body_texture_with_unitypy", return_value=("ch9999_co0001_body", None)), \
             patch.object(packer, "make_name_thumbnail_png", side_effect=mutate), \
             self.assertRaisesRegex(ValueError, "changed after planning"):
            gui.process_single_file(primary, platform=platforms[primary])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_thumbnail_plan_rejects_a_companion_changed_during_member_detection(self):
        from webtools.core import viewer_thumbnails as thumbs
        primary, helper = self.pair()
        original_names = packer._bundle_texture_names
        def mutate(path):
            names = original_names(path)
            if path == primary:
                Path(helper).write_bytes(rina_fixture(13, False, "0002"))
            return names
        params = {"mode": "multi", "in_paths": primary + "\n" + helper, "auto_chara_id": True,
                  "manual_chara_id": 0, "thumbnail_size": 256, "combine_pairs": True, "thumbnail_mode": "3d"}
        with patch("webtools.filebrowser.is_within_allowed", return_value=True), \
             patch.object(packer, "_bundle_texture_names", side_effect=mutate), \
             self.assertRaisesRegex(ValueError, "changed after preparing"):
            thumbs.plan({"kind": "packer", "params": params})


if __name__ == "__main__":
    unittest.main()

