"""Rina pairing uses immutable provenance, real Unity metadata and exact catalogs."""
import copy
import hashlib
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import UnityPy
import llas_asset_extractor as extractor
from webtools.core import game_models as game
from webtools.core import viewer_mod_sources as sources
from webtools.jobs import Job


class ViewerModSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.cache = self.root / "cache"
        self.packs = self.root / "packs"
        self.packs.mkdir()
        self.primary = self.bundle("ch9999_co0123")
        self.unmasked = self.bundle("ch0209_co0123")
        self.other = self.bundle("ch0101_co0123")
        self.ios = self.bundle("ch0209_co0123", platform=9)
        self.record = None
        self.job = Job("pair", "viewer_mod_zip")
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root / "library")}).start()
        patch.object(extractor, "detect_game_candidates", return_value=[]).start()
        patch.object(extractor, "build_pack_roots", return_value=[str(self.packs)]).start()
        patch.object(extractor, "build_pack_index", side_effect=lambda root: {p.name: str(p) for p in Path(root).iterdir() if p.is_file()}).start()
        with sources._LOCK:
            sources._REGISTRY.clear()
        for region in ("gl", "jp"):
            directory = self.root / "assets/db" / region
            directory.mkdir(parents=True)
            with sqlite3.connect(directory / "masterdata.db") as db:
                db.executescript("CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,name TEXT,model_asset_path TEXT); CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,model_asset_path TEXT); CREATE TABLE m_suit_attach(suit_master_id INTEGER,original_suit_master_id INTEGER,attach_key TEXT);")
                db.execute("INSERT INTO m_suit VALUES(12,209,'Rina','board')")
                db.execute("INSERT INTO m_suit_view VALUES(12,2,'unmasked')")
            with sqlite3.connect(directory / "asset_a_en.db") as db:
                db.executescript("CREATE TABLE member_model(asset_path TEXT,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER); CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER);")
                for model, raw in (("board", self.primary), ("unmasked", self.unmasked)):
                    pack = region + model
                    encrypted = bytearray(raw)
                    extractor.decrypt_section(encrypted, extractor.FIXED_KEY0, 7, 11)
                    (self.packs / pack).write_bytes(encrypted)
                    db.execute("INSERT INTO member_model VALUES(?,?,0,?,7,11)", (model, pack, len(raw)))
                    db.execute("INSERT INTO m_asset_package_mapping VALUES('suit:12',?,?,NULL,0)", (pack, len(raw)))

    @staticmethod
    def bundle(texture, platform=13):
        raw = (Path(__file__).parent / "fixtures/viewer_textured_triangle.unity").read_bytes()
        environment = UnityPy.load(raw)
        environment.file.target_platform = platform
        environment.file._m_target_platform = platform
        for obj in environment.objects:
            if obj.type.name == "Texture2D":
                tree = obj.read_typetree()
                tree["m_Name"] = texture
                obj.save_typetree(tree)
        return environment.file.save()

    def write(self, name, raw):
        path = self.root / name
        path.write_bytes(raw)
        return path

    @staticmethod
    def context(path, raw, *, member=None, model_raw=None):
        return {"containers": [{"path": str(path), "name": path.name, "raw": raw,
                                "sha256": sources._sha(raw)}],
                "sources": [{"name": path.name, "container": 0, "member": member,
                             "sha256": sources._sha(raw if model_raw is None else model_raw)}],
                "variants": {}, "nodes": []}

    def imported(self, variant="primary", region="gl"):
        record = game.validate_selection(self.root, {"region": region, "suit": "suit:12", "variant": variant, "download": False})
        job = Job("import", "viewer_game_assets")
        game.run_import(job, repo_root=self.root, output_root=self.cache, record=record)
        path = Path(job.output_paths()[0])
        receipt = sources.register_game_import(path, record)
        return path, record, receipt

    def resolve(self, context, edited, **options):
        return sources.resolve_pair(context, {"preview_paths": [str(edited)]},
                                    repo_root=self.root, output_root=self.cache,
                                    job=self.job, **options)

    def zip_context(self, *, ios=False, missing=False, unmask=None, manifest_extra=""):
        values = {"board": self.primary, "bare": self.unmasked if unmask is None else unmask}
        manifest = "chara_id=209\ncostume_file='board'\nrina_unmask_costume_file='bare'\n" + manifest_extra
        if missing:
            del values["bare"]
        if ios:
            values.update(iphoneboard=self.bundle("ch9999_co0123", 9), iphonebare=self.ios)
            manifest += "costume_file_ios='iphoneboard'\nrina_unmask_costume_file_ios='iphonebare'\n"
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, raw in values.items():
                archive.writestr(name, raw)
            archive.writestr("modinstall.txt", manifest)
        raw = output.getvalue()
        path = self.write("paired.zip", raw)
        return self.context(path, raw, member="board", model_raw=self.primary)

    def test_official_pair_both_directions_and_regions_preserve_originals(self):
        for region in ("gl", "jp"):
            for variant in ("primary", "unmasked"):
                with self.subTest(region=region, variant=variant):
                    path, record, _ = self.imported(variant, region)
                    original = path.read_bytes()
                    edited = self.write("edited.unity", original)
                    result = self.resolve(self.context(path, original), edited)
                    self.assertFalse(result["explicit_source"])
                    self.assertEqual(result[variant]["path"], str(edited))
                    other = "unmasked" if variant == "primary" else "primary"
                    self.assertEqual(Path(result[other]["path"]).read_bytes(), self.unmasked if other == "unmasked" else self.primary)
                    self.assertIn(region, Path(result[other]["path"]).parent.name)
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(self.job.output_paths(), [])

    def test_persisted_receipt_reopens_after_registry_restart_without_name_guess(self):
        path, record, _ = self.imported()
        renamed = self.write("jp-suit999999-unmasked.unity", path.read_bytes())
        receipt = sources.register_game_import(renamed, record)
        with sources._LOCK:
            sources._REGISTRY.clear()
        context = self.context(renamed, renamed.read_bytes())
        result = self.resolve(context, self.write("edit.unity", self.primary), receipts=[receipt])
        self.assertEqual(Path(result["unmasked"]["path"]).read_bytes(), self.unmasked)

    def test_catalog_change_rejects_registered_receipt(self):
        path, _, _ = self.imported()
        with sqlite3.connect(self.root / "assets/db/gl/asset_a_en.db") as db:
            db.execute("UPDATE member_model SET key1=19 WHERE asset_path='board'")
        with self.assertRaisesRegex(ValueError, "catalog changed"):
            self.resolve(self.context(path, path.read_bytes()), path)

    def test_expected_import_hash_rejects_changed_file_without_registry_pollution(self):
        path, record, receipt = self.imported()
        original = copy.deepcopy(sources._REGISTRY[str(path)])
        path.write_bytes(self.unmasked)
        with self.assertRaisesRegex(ValueError, "changed before"):
            sources.register_game_import(path, record, expected_sha256=receipt["sha256"])
        self.assertEqual(sources._REGISTRY[str(path)], original)
        fresh = self.write("unregistered.unity", self.unmasked)
        with self.assertRaisesRegex(ValueError, "changed before"):
            sources.register_game_import(fresh, record, expected_sha256=receipt["sha256"])
        self.assertNotIn(str(fresh), sources._REGISTRY)

    def test_expected_import_hash_accepts_verified_bytes_and_invalid_hash_is_rejected(self):
        path, record, receipt = self.imported()
        self.assertEqual(sources.register_game_import(path, record,
            expected_sha256=receipt["sha256"]), receipt)
        with self.assertRaisesRegex(ValueError, "changed before"):
            sources.register_game_import(path, record, expected_sha256="not-a-sha256")

    def test_missing_or_wrong_hash_receipt_never_guesses_suit_from_filename(self):
        path = self.write("ch0209_suit12_primary.unity", self.primary)
        context = self.context(path, self.primary)
        with self.assertRaisesRegex(ValueError, "explicitly choose"):
            self.resolve(context, path)
        _, record, _ = self.imported()
        with sources._LOCK:
            sources._REGISTRY.clear()
        receipt = {"path": str(path), "sha256": "0" * 64, "record": record}
        with self.assertRaisesRegex(ValueError, "explicitly choose"):
            self.resolve(context, path, receipts=[receipt])

    def test_conflicting_same_hash_receipts_are_rejected(self):
        path, record, receipt = self.imported()
        changed = copy.deepcopy(receipt)
        changed["record"]["region"] = "jp"
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            sources.game_context(self.context(path, path.read_bytes()), self.root, receipts=[receipt, changed])

    def test_explicit_pair_requires_roles_and_accepts_both_selected_variants(self):
        for variant in ("primary", "unmasked"):
            raw = self.primary if variant == "primary" else self.unmasked
            other = self.unmasked if variant == "primary" else self.primary
            path = self.write("chosen.unity", raw)
            edited = self.write("edited.unity", raw)
            counterpart = self.write("arbitrary-name.unity", other)
            result = self.resolve(self.context(path, raw), edited,
                                  selection={"counterpart_path": str(counterpart), "selected_variant": variant})
            self.assertTrue(result["explicit_source"])
            self.assertEqual(result[variant]["path"], str(edited))
        with self.assertRaisesRegex(ValueError, "declare"):
            self.resolve(self.context(path, raw), edited, selection={"counterpart_path": str(counterpart)})

    def test_explicit_pair_rejects_other_character_platform_and_symlink(self):
        path = self.write("selected.unity", self.primary)
        edited = self.write("edited.unity", self.primary)
        for raw in (self.other, self.ios):
            counterpart = self.write("counterpart.unity", raw)
            with self.assertRaisesRegex(ValueError, "same platform"):
                self.resolve(self.context(path, self.primary), edited,
                             selection={"counterpart_path": str(counterpart), "selected_variant": "primary"})
        counterpart.write_bytes(self.unmasked)
        link = self.root / "linked.unity"
        link.symlink_to(counterpart)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.resolve(self.context(path, self.primary), edited,
                         selection={"counterpart_path": str(link), "selected_variant": "primary"})

    def test_complete_rina_zip_already_contains_both_platform_pairs_without_executing_manifest(self):
        marker = self.root / "manifest-executed"
        context = self.zip_context(ios=True, manifest_extra=f"open({str(marker)!r},'w').write('bad')\n")
        with patch.object(game, "run_import", side_effect=AssertionError("must not fetch")):
            self.assertIsNone(self.resolve(context, Path(context["containers"][0]["path"])))
        self.assertFalse(marker.exists())

    def test_incomplete_or_cross_platform_archive_cannot_silently_package_partial_rina(self):
        for options in ({"missing": True}, {"unmask": self.ios}, {"unmask": self.other},
                        {"unmask": self.primary},
                        {"manifest_extra": "rina_unmask_costume_file='board'\n"}):
            with self.subTest(options=list(options)):
                context = self.zip_context(**options)
                with patch.object(game, "run_import", side_effect=AssertionError("must not guess")):
                    with self.assertRaises(ValueError):
                        self.resolve(context, Path(context["containers"][0]["path"]))

    def test_explicit_copy_cannot_fake_a_missing_partner(self):
        path = self.write("selected.unity", self.primary)
        copied = self.write("claimed-partner.unity", self.primary)
        with self.assertRaisesRegex(ValueError, "copy of the selected"):
            self.resolve(self.context(path, self.primary), path,
                         selection={"counterpart_path": str(copied), "selected_variant": "primary"})

    def test_counterpart_import_never_reuses_changed_source_or_wrong_attach_key(self):
        path, record, _ = self.imported()
        edited = self.write("edited.unity", self.primary)
        actual_import = game.run_import
        def changed(*args, **kwargs):
            result = actual_import(*args, **kwargs)
            edited.write_bytes(self.unmasked)
            return result
        with patch.object(game, "run_import", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed while"):
                self.resolve(self.context(path, path.read_bytes()), edited)
        counterpart = copy.deepcopy(record)
        counterpart.update(variant="unmasked", attach_key="c2")
        actual_validate = game.validate_selection
        def mismatch(root, params, *args, **kwargs):
            return counterpart if params["variant"] == "unmasked" else actual_validate(root, params, *args, **kwargs)
        with patch.object(game, "validate_selection", side_effect=mismatch):
            with self.assertRaisesRegex(ValueError, "matching"):
                self.resolve(self.context(path, path.read_bytes()), edited)

    def test_snapshot_hash_and_export_container_identity_are_required(self):
        path, _, _ = self.imported()
        context = self.context(path, path.read_bytes())
        invalid = copy.deepcopy(context)
        invalid["containers"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source identity"):
            self.resolve(invalid, path)
        with self.assertRaisesRegex(ValueError, "original container"):
            sources.resolve_pair(context, {"preview_paths": []}, repo_root=self.root,
                                 output_root=self.cache, job=self.job)

    def test_non_rina_does_not_import_or_guess_a_partner(self):
        path = self.write("209rinamasked.unity", self.other)
        with patch.object(game, "run_import", side_effect=AssertionError("must not fetch")):
            self.assertIsNone(self.resolve(self.context(path, self.other), path))


if __name__ == "__main__":
    unittest.main()
