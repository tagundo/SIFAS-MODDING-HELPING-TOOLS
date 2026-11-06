"""Real installer archives from saved Unity exports, without installing mods."""
import ast
import hashlib
import io
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

from webtools.core import viewer_mod_package as packages

try:
    import UnityPy
    from PIL import Image
    import unity_costumemod_packer as packer
    from webtools.core import model_edits, model_viewer
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


def sha(data):
    return hashlib.sha256(data).hexdigest()


def literals(raw):
    return {node.targets[0].id: ast.literal_eval(node.value)
            for node in ast.parse(raw.decode("utf-8")).body}


@unittest.skipUnless(AVAILABLE, "UnityPy and Pillow are needed for real installer package checks")
class ViewerModPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = (Path(__file__).parent / "fixtures/viewer_persistence.unity").read_bytes()
        self.source = self.bundle("source.unity", "ch0006_co0001_body")
        self.output = self.root / "packages"

    def bundle(self, name, texture, platform=13):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        environment = UnityPy.load(self.raw)
        for obj in environment.objects:
            if obj.type.name == "Texture2D":
                tree = obj.read_typetree()
                tree["m_Name"] = texture
                obj.save_typetree(tree)
        file = next(iter(environment.files.values()))
        file._m_target_platform = platform
        path.write_bytes(file.save())
        return path

    def saved(self, *paths):
        return {"preview_paths": [str(path) for path in paths], "originals_preserved": True}

    def package(self, *paths, **options):
        return packages.package_saved_export(self.saved(*paths), self.output,
            display_name=options.pop("display_name", "Edited costume"), **options)

    def pair(self, primary, unmasked, platform="android"):
        return {"primary": {"path": str(primary), "sha256": sha(primary.read_bytes())},
                "unmasked": {"path": str(unmasked), "sha256": sha(unmasked.read_bytes())},
                "owner": 209, "platform": platform}

    def archive(self, name, entries, comment=b""):
        path = self.root / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for key, value in entries.items():
                archive.writestr(key, value)
            archive.comment = comment
        return path

    def test_actual_hybrid_export_becomes_named_installer_zip_without_originals_or_recipe(self):
        original = self.source.read_bytes()
        preview = model_viewer.prepare([str(self.source)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        token = secrets.token_hex(16)
        metadata = model_edits.register_session(token, [str(self.source)], preview["rig"])
        nodes = {node["name"]: node["node"] for node in metadata["nodes"]}
        exported = model_edits.export(token, {"version": 1, "savedSettingsEnabled": True, "edits": [
            {"node": nodes["LeftUpLeg"], "method": "mesh", "scale": [1.6, 1.2, 1.0]},
            {"node": nodes["BreastSize"], "method": "node", "scale": [1.2, 1.1, 1.0]},
        ]}, self.root / "export")
        display = '분수 "edited" \\ costume\n새 이름'
        result = packages.package_saved_export(exported, self.output, display_name=display)
        package = Path(result["package_path"])
        self.assertEqual(result["chara_id"], 6)
        self.assertEqual(result["platform"], "android")
        self.assertEqual(sha(package.read_bytes()), result["sha256"])
        self.assertEqual(package.stat().st_size, result["bytes"])
        with zipfile.ZipFile(package) as archive:
            config = literals(archive.read("modinstall.txt"))
            self.assertEqual({config[key] for key in packages._NAMES}, {display})
            self.assertEqual(archive.read(config["costume_file"]), Path(exported["preview_paths"][0]).read_bytes())
            self.assertNotEqual(archive.read(config["costume_file"]), original)
            self.assertEqual(set(archive.namelist()), {config["costume_file"], config["thumbnail_file"], "modinstall.txt"})
            self.assertTrue(packer.pack_safe_stem(Path(config["costume_file"]).stem) == Path(config["costume_file"]).stem)
            with Image.open(io.BytesIO(archive.read(config["thumbnail_file"]))) as image:
                self.assertTrue(0 < max(image.size) <= 256)
                self.assertEqual(image.format, "PNG")
        self.assertEqual(self.source.read_bytes(), original)
        again = packages.package_saved_export(exported, self.output, display_name=display)
        self.assertNotEqual(result["package_path"], again["package_path"])
        self.assertTrue(package.is_file())

    def test_two_edits_with_identical_thumbnail_have_disjoint_installer_pack_names(self):
        preview = model_viewer.prepare([str(self.source)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        token = secrets.token_hex(16)
        metadata = model_edits.register_session(token, [str(self.source)], preview["rig"])
        node = next(row["node"] for row in metadata["nodes"] if row["name"] == "LeftUpLeg")
        results, payloads, pack_names = [], [], []
        for factor in (1.6, 1.7):
            exported = model_edits.export(token, {"version": 1, "savedSettingsEnabled": True,
                "edits": [{"node": node, "method": "mesh", "scale": [factor, 1.2, 1.0]}]}, self.root / "export")
            result = packages.package_saved_export(exported, self.output, display_name="Same human name")
            with zipfile.ZipFile(result["package_path"]) as archive:
                config = literals(archive.read("modinstall.txt"))
                files = {key: archive.read(config[key]) for key in ("costume_file", "thumbnail_file")}
                self.assertEqual(files["costume_file"], Path(exported["preview_paths"][0]).read_bytes())
                self.assertEqual({config[key] for key in packages._NAMES}, {"Same human name"})
                pack_names.append({f"{zlib.crc32(value):08x}" + Path(config[key]).stem for key, value in files.items()})
                payloads.append(files)
                results.append(result)
        self.assertNotEqual(payloads[0]["costume_file"], payloads[1]["costume_file"])
        self.assertEqual(payloads[0]["thumbnail_file"], payloads[1]["thumbnail_file"])
        self.assertTrue(pack_names[0].isdisjoint(pack_names[1]), "Identical thumbnails must not reuse a legacy installer pack row")

    def test_aliased_asset_expansion_obeys_final_entry_and_unpacked_limits(self):
        manifest = packer.generate_modinstall_txt("Original", "source.unity", "thumb.png", 6)
        manifest += "\ncostume_facedynamic_file='source.unity'\n"
        entries = {"source.unity": self.source.read_bytes(),
                   "thumb.png": packer.make_name_thumbnail_png("Original", 32, 6),
                   "modinstall.txt": manifest.encode()}
        source = self.archive("aliased.zip", entries)
        original = source.read_bytes()
        limits = [("MAX_ENTRIES", len(entries) + 1),
                  ("MAX_UNPACKED_BYTES", sum(map(len, entries.values())) + len(entries["source.unity"]) // 2)]
        for name, limit in limits:
            with self.subTest(limit=name), patch.object(packages.viewer_archive, name, limit):
                with self.assertRaisesRegex(packages.ModPackageError, "packaging limit"):
                    self.package(source)
                self.assertEqual(list(self.output.iterdir()), [])
                self.assertEqual(source.read_bytes(), original)

    def test_existing_rina_dual_zip_changes_only_name_literals_and_keeps_all_variant_bytes(self):
        primary = self.bundle("board.unity", "ch9999_co0001_body")
        unmasked = self.bundle("normal.unity", "ch0209_co0001_body")
        ios = self.bundle("boardios.unity", "ch9999_co0001_body", 9)
        ios_unmasked = self.bundle("normalios.unity", "ch0209_co0001_body", 9)
        manifest = packer.generate_modinstall_txt("Old name", "board.unity", "thumb.png", 209,
            "normal.unity", "boardios.unity", "normalios.unity")
        manifest = "# 기존 주석\n" + manifest + "\ncustom_data = ['keep', 2]\ncostume_facedynamic_file='facial.unity'\n"
        entries = {"board.unity": primary.read_bytes(), "normal.unity": unmasked.read_bytes(),
                   "boardios.unity": ios.read_bytes(), "normalios.unity": ios_unmasked.read_bytes(),
                   "facial.unity": primary.read_bytes(),
                   "thumb.png": packer.make_name_thumbnail_png("Existing", 64, 209),
                   "extra/untouched.bin": b"preserve this accessory exactly", "modinstall.txt": manifest.encode()}
        source = self.archive("rina.zip", entries, comment=b"keep zip comment")
        before = source.read_bytes()
        result = self.package(source, display_name='새 "Rina"\n이름')
        self.assertEqual(result["platform"], "android+ios")
        self.assertEqual(result["mode"], "preserved_installer_zip")
        with zipfile.ZipFile(result["package_path"]) as archive:
            config = literals(archive.read("modinstall.txt"))
            old = literals(entries["modinstall.txt"])
            renames = {old[key]: config[key] for key in packages._ASSET_REFS if old.get(key)}
            self.assertEqual(archive.namelist(), [renames.get(name, name) for name in entries] + [result["source_manifest_member"]])
            self.assertEqual(archive.comment, b"keep zip comment")
            for name, value in entries.items():
                if name != "modinstall.txt":
                    self.assertEqual(archive.read(renames.get(name, name)), value)
            changed = archive.read("modinstall.txt")
            config = literals(changed)
            preserved = archive.read(result["source_manifest_member"])
            self.assertEqual(preserved, entries["modinstall.txt"])
            self.assertEqual(literals(preserved)["custom_data"], ["keep", 2])
            self.assertTrue(preserved.startswith("# 기존 주석\n".encode()))
            self.assertEqual(set(config), set(packages._SUPPORTED_CONFIG))
            self.assertNotIn("custom_data", config)
            self.assertEqual({config[key] for key in packages._NAMES}, {'새 "Rina"\n이름'})
            self.assertEqual(config["chara_id"], old["chara_id"])
            self.assertIsNone(config["id_costume"])
            self.assertIsNone(config["id_trade_product"])
            for key in packages._ASSET_REFS:
                if old.get(key):
                    self.assertRegex(config[key], r"^v[a-f0-9]{16}role[0-9]+\.[a-z]+$")
                    self.assertEqual(result["asset_members"][key], config[key])
        repeated = self.package(source, display_name='새 "Rina"\n이름')
        self.assertTrue(set(result["asset_members"].values()).isdisjoint(repeated["asset_members"].values()))
        self.assertEqual(source.read_bytes(), before)

    def test_generic_single_model_saved_zip_becomes_installer_and_keeps_unrelated_files(self):
        from webtools.core import viewer_archive
        notes = {"notes.txt": b"keep source notes exactly", "thumbnail.png": b"unrelated old thumbnail"}
        source = self.archive("bare-costume.zip", {"models/body.unity": self.source.read_bytes(), **notes},
                              comment=b"original generic comment")
        original = source.read_bytes()
        token = secrets.token_hex(16)
        with viewer_archive.expand_inputs([str(source)], self.root / "expand") as expanded:
            preview = model_viewer.prepare(expanded.paths, rigged=True,
                face_context={"enabled": False, "allow_download": False})
            metadata = model_edits.register_session(token, expanded.paths, preview["rig"],
                originals=[str(source)], origins=expanded.origins, archive_members=expanded.archive_members)
        node = next(node for node in metadata["nodes"] if node["name"] == "LeftUpLeg")
        exported = model_edits.export(token, {"version": 1, "savedSettingsEnabled": True,
            "edits": [{"node": node["node"], "method": "mesh", "scale": [1.6, 1.2, 1.0]}]}, self.root / "export")
        result = packages.package_saved_export(exported, self.output, display_name="Single archive edit")
        self.assertEqual(result["mode"], "packed_single_model_archive")
        self.assertEqual(set(result["preserved_extras"]), {"extras/notes.txt.data", "extras/thumbnail.png"})
        with zipfile.ZipFile(result["package_path"]) as archive, zipfile.ZipFile(exported["preview_paths"][0]) as saved:
            config = literals(archive.read("modinstall.txt"))
            self.assertEqual(config["chara_id"], 6)
            self.assertEqual(archive.read(config["costume_file"]), saved.read("models/body.unity"))
            self.assertNotEqual(archive.read(config["costume_file"]), self.source.read_bytes())
            self.assertEqual(archive.comment, b"original generic comment")
            for name, value in notes.items():
                inert = name + ".data" if name.lower().endswith((".txt", ".zip")) else name
                self.assertEqual(archive.read("extras/" + inert), value)
            with Image.open(io.BytesIO(archive.read(config["thumbnail_file"]))) as image:
                self.assertEqual(image.format, "PNG")
        self.assertEqual(source.read_bytes(), original)

    def test_generic_multiple_models_or_incomplete_rina_are_refused(self):
        multiple = self.archive("multiple.zip", {"first.unity": self.source.read_bytes(),
            "second.unity": self.source.read_bytes(), "notes.txt": b"not a model"})
        with self.assertRaisesRegex(packages.ModPackageError, "exactly one Unity model"):
            self.package(multiple)
        board = self.bundle("board.unity", "ch9999_co0001_body")
        rina = self.archive("incomplete-rina.zip", {"board.unity": board.read_bytes()})
        with self.assertRaisesRegex(packages.ModPackageError, "both the board and no-mask"):
            self.package(rina)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_raw_rina_roles_keep_both_prepared_variants_even_with_same_basename(self):
        primary = self.bundle("primary/costume.unity", "ch9999_co0001_body")
        unmasked = self.bundle("edited/costume.unity", "ch0209_co0001_body")
        pair = self.pair(primary, unmasked)
        result = self.package(unmasked, pair=pair)
        with zipfile.ZipFile(result["package_path"]) as archive:
            config = literals(archive.read("modinstall.txt"))
            self.assertEqual(config["chara_id"], 209)
            self.assertNotEqual(config["costume_file"], config["rina_unmask_costume_file"])
            self.assertEqual(sha(archive.read(config["costume_file"])), pair["primary"]["sha256"])
            self.assertEqual(sha(archive.read(config["rina_unmask_costume_file"])), pair["unmasked"]["sha256"])

    def test_ios_bundle_is_reported_and_named_as_ios(self):
        ios = self.bundle("sourceios.unity", "ch0006_co0001_body", 9)
        result = self.package(ios)
        self.assertEqual(result["platform"], "ios")
        self.assertIn("-ios-", Path(result["package_path"]).name)
        with zipfile.ZipFile(result["package_path"]) as archive:
            config = literals(archive.read("modinstall.txt"))
            self.assertEqual(config["costume_file_ios"], "")
            self.assertEqual(archive.read(config["costume_file"]), ios.read_bytes())

    def test_long_unicode_name_keeps_full_manifest_text_and_fits_filesystem_bytes(self):
        display = "한" * 117 + "é衣🙂"
        self.assertEqual(len(display), 120)
        result = self.package(self.source, display_name=display)
        package = Path(result["package_path"])
        self.assertTrue(package.is_file())
        self.assertLessEqual(len(package.name.encode("utf-8")), 190)
        self.assertEqual(result["display_name"], display)
        with zipfile.ZipFile(package) as archive:
            config = literals(archive.read("modinstall.txt"))
            self.assertEqual({config[key] for key in packages._NAMES}, {display})

    def test_raw_bundle_name_cannot_collide_with_thumbnail_or_manifest(self):
        for name in ("thumbnail.png", "modinstall.txt"):
            source = self.bundle(name, "ch0006_co0001_body")
            result = self.package(source)
            with zipfile.ZipFile(result["package_path"]) as archive:
                self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
                config = literals(archive.read("modinstall.txt"))
                self.assertNotIn(config["costume_file"], ("thumbnail.png", "modinstall.txt"))
                self.assertEqual(archive.read(config["costume_file"]), source.read_bytes())

    def test_missing_changed_unbound_or_wrong_platform_rina_pair_is_refused(self):
        primary = self.bundle("board.unity", "ch9999_co0001_body")
        unmasked = self.bundle("normal.unity", "ch0209_co0001_body")
        pair = self.pair(primary, unmasked)
        with self.assertRaisesRegex(packages.ModPackageError, "both the board and no-mask"):
            self.package(primary)
        changed = self.pair(primary, unmasked)
        changed["unmasked"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(packages.ModPackageError, "changed after selection"):
            self.package(primary, pair=changed)
        with self.assertRaisesRegex(packages.ModPackageError, "not bound"):
            self.package(self.source, pair=pair)
        pair["platform"] = "ios"
        with self.assertRaisesRegex(packages.ModPackageError, "selected platform"):
            self.package(primary, pair=pair)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_unrelated_outputs_unknown_owner_and_unknown_platform_are_refused(self):
        other = self.bundle("other.unity", "ch0007_co0001_body")
        with self.assertRaisesRegex(packages.ModPackageError, "unrelated"):
            self.package(self.source, other)
        for invalid in (0, 9999, True):
            with self.subTest(owner=invalid), self.assertRaisesRegex(packages.ModPackageError, "known costume character"):
                self.package(self.source, chara_id=invalid)
        transplanted = self.package(self.source, chara_id=7)
        self.assertEqual(transplanted["chara_id"], 7)
        Path(transplanted["package_path"]).unlink()
        unknown = self.bundle("unknown.unity", "ch0006_co0001_body", -2)
        with self.assertRaisesRegex(packages.ModPackageError, "platform is unknown"):
            self.package(unknown)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_manifests_are_never_executed_and_ambiguous_archives_are_refused(self):
        marker = self.root / "must-not-exist"
        valid = packer.generate_modinstall_txt("Old", "source.unity", "thumb.png", 6).encode()
        cases = [
            {"modinstall.txt": valid + ("\nopen(%r,'w').write('bad')\n" % str(marker)).encode()},
            {"modinstall.txt": valid, "another/modinstall.txt": valid},
            {"modinstall.txt": valid + b"\nchara_id=7\n"},
        ]
        for index, manifests in enumerate(cases):
            source = self.archive(str(index) + ".zip", {"source.unity": self.source.read_bytes(), "thumb.png": b"existing", **manifests})
            with self.subTest(index=index), self.assertRaises(packages.ModPackageError):
                self.package(source)
            self.assertFalse(marker.exists())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_existing_rina_zip_without_counterpart_is_not_published(self):
        primary = self.bundle("board.unity", "ch9999_co0001_body")
        manifest = packer.generate_modinstall_txt("Old", "board.unity", "", 209).encode()
        source = self.archive("missing.zip", {"board.unity": primary.read_bytes(), "modinstall.txt": manifest})
        with self.assertRaisesRegex(packages.ModPackageError, "both the board and no-mask"):
            self.package(source)

    def test_legacy_text_nested_zip_and_global_overrides_are_preserved_only_as_inert_data(self):
        marker = self.root / "must-not-execute"
        note = ("open(%r,'w').write('unsafe')\n" % str(marker)).encode()
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as archive:
            archive.writestr("nested.txt", note)
        thumbnail = packer.make_name_thumbnail_png("Existing", 32, 6)
        manifest = packer.generate_modinstall_txt("Old", "body.txt", "preview.zip", 6)
        manifest = ("# Keep this source comment\n" + manifest +
            "\ncostume_facedynamic_file='facial.ZIP'\nchara_id_append=7\n" +
            "id_costume=123\nid_trade_product=456\nnested_path_batch='/do-not-override'\n" +
            "temp_directory='/do-not-write'\ncustom_data=['keep',2]\n")
        entries = {"body.txt": self.source.read_bytes(), "facial.ZIP": self.source.read_bytes(),
            "preview.zip": thumbnail, "notes.txt": note, "OTHER.TXT": note,
            "nested\\notes.txt": note, "nested/notes.txt.data": b"existing normalized inert",
            "notes.txt.data": b"already inert companion", "NESTED.ZIP": nested.getvalue(),
            "metadata/source-modinstall.txt.data": b"existing metadata file", "keep.bin": b"keep exact",
            "modinstall.txt": manifest.encode()}
        source = self.archive("legacy.zip", entries, comment=b"preserve comment")
        original = source.read_bytes()
        result = self.package(source, display_name="Safe human name")
        with zipfile.ZipFile(result["package_path"]) as archive:
            self.assertEqual([name for name in archive.namelist() if name.lower().endswith((".txt", ".zip"))], ["modinstall.txt"])
            config = literals(archive.read("modinstall.txt"))
            self.assertEqual(set(config), set(packages._SUPPORTED_CONFIG))
            self.assertEqual(config["chara_id_append"], 7)
            self.assertIsNone(config["id_costume"])
            self.assertIsNone(config["id_trade_product"])
            for key in ("nested_path_batch", "temp_directory", "custom_data"):
                self.assertNotIn(key, config)
            for key in packages._ASSET_REFS:
                if config[key]:
                    self.assertTrue(config[key].endswith(".png" if key == "thumbnail_file" else ".unity"))
            self.assertEqual(archive.read(config["costume_file"]), entries["body.txt"])
            self.assertEqual(archive.read(config["costume_facedynamic_file"]), entries["facial.ZIP"])
            self.assertEqual(archive.read(config["thumbnail_file"]), thumbnail)
            self.assertEqual(archive.read("notes.txt.data.2.data"), note)
            self.assertEqual(archive.read("OTHER.TXT.data"), note)
            self.assertEqual(archive.read("nested/notes.txt.data.2.data"), note)
            self.assertEqual(archive.read("nested/notes.txt.data"), entries["nested/notes.txt.data"])
            self.assertEqual(archive.read("NESTED.ZIP.data"), nested.getvalue())
            self.assertEqual(archive.read("notes.txt.data"), entries["notes.txt.data"])
            self.assertEqual(archive.read("keep.bin"), entries["keep.bin"])
            self.assertEqual(archive.read("metadata/source-modinstall.txt.data"), entries["metadata/source-modinstall.txt.data"])
            self.assertNotEqual(result["source_manifest_member"], "metadata/source-modinstall.txt.data")
            self.assertEqual(archive.read(result["source_manifest_member"]), entries["modinstall.txt"])
            self.assertEqual(archive.comment, b"preserve comment")
            self.assertEqual({config[key] for key in packages._NAMES}, {"Safe human name"})
        self.assertFalse(marker.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_invalid_character_append_cannot_enter_canonical_installer_settings(self):
        manifest = packer.generate_modinstall_txt("Old", "body.unity", "", 6) + "\nchara_id_append=0\n"
        source = self.archive("invalid-append.zip", {"body.unity": self.source.read_bytes(), "modinstall.txt": manifest.encode()})
        with self.assertRaisesRegex(packages.ModPackageError, "known costume character"):
            self.package(source)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_source_change_during_packaging_and_cancellation_leave_no_partial_package(self):
        before = self.source.read_bytes()
        original = packer._extract_body_texture_core
        def change_source(*args, **kwargs):
            self.source.write_bytes(before + b"changed by another process")
            return original(*args, **kwargs)
        with patch.object(packer, "_extract_body_texture_core", side_effect=change_source):
            with self.assertRaisesRegex(packages.ModPackageError, "changed during packaging"):
                self.package(self.source)
        self.assertEqual(list(self.output.iterdir()), [])
        self.source.write_bytes(before)
        calls = 0
        def stopped():
            nonlocal calls
            calls += 1
            return calls >= 3
        with self.assertRaises(InterruptedError):
            self.package(self.source, should_stop=stopped)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.output.iterdir()), [])
        def failed_log(message):
            if message.startswith("Prepared installer Mod ZIP:"):
                raise RuntimeError("The job log closed before publication")
        with self.assertRaisesRegex(RuntimeError, "log closed"):
            self.package(self.source, log=failed_log)
        self.assertEqual(list(self.output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
