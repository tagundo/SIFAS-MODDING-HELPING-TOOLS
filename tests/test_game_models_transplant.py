"""Native body consumers keep viewer imports and all game sources unchanged."""
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import unittest
from unittest.mock import patch

import UnityPy
from PIL import Image

from webtools.core import game_models as game
from webtools.jobs import Job
import test_game_models as original
import test_model_accessory_unclip as geometry
import test_viewer_scene_roles as scenes


@unittest.skipUnless(original.extractor, "The application asset extractor is required")
class TransplantGameModelTests(unittest.TestCase):
    def setUp(self):
        self.helper = original.GameModelTests()
        self.helper.setUp(); self.addCleanup(self.helper.doCleanups)
        self.root, self.output = self.helper.root, self.helper.output / "transplant-bodies"
        self.helper.payload = self.bundle("body.assets", self.helper.payload)
        for region, language in (("gl", "ko"), ("jp", "ja")):
            catalog = self.root / "assets/db" / region / ("asset_a_" + language + ".db")
            for name in ("basepack", "maskpack", "barepack", "colourpack"):
                self.store(catalog, name, self.helper.payload)

    def selection(self, *, suit="suit:1", region="gl", variant="primary", platform="android"):
        return game.validate_selection(self.root, {"region": region, "suit": suit, "variant": variant,
            "download": False, "purpose": "transplant", "platform": platform}, "ko")

    def run_import(self, record=None, job=None):
        job = job or Job("transplant", "viewer_game_assets")
        game.run_import(job, repo_root=self.root, output_root=self.output, record=record or self.selection())
        return job.output_paths()

    def store(self, catalog, pack, raw):
        encrypted = bytearray(raw)
        original.extractor.decrypt_section(encrypted, original.extractor.FIXED_KEY0, 7, 11)
        (self.helper.packs / pack).write_bytes(encrypted)
        with sqlite3.connect(catalog) as db:
            db.execute("UPDATE member_model SET size=? WHERE pack_name=?", (len(raw), pack))
            db.execute("UPDATE m_asset_package_mapping SET file_size=? WHERE pack_name=?", (len(raw), pack))

    def ios_catalog(self, *, wrong_platform=False):
        for region, language in (("gl", "ko"), ("jp", "ja")):
            folder = self.root / "assets/db" / region
            destination = folder / ("asset_i_" + language + ".db")
            shutil.copyfile(folder / ("asset_a_" + language + ".db"), destination)
            with sqlite3.connect(destination) as db:
                db.execute("UPDATE member_model SET pack_name=pack_name||'_ios'")
                db.execute("UPDATE m_asset_package_mapping SET pack_name=pack_name||'_ios'")
            env = UnityPy.load(self.helper.payload)
            for asset in env.assets:
                asset.target_platform = 13 if wrong_platform else 9
                asset._m_target_platform = 13 if wrong_platform else 9
            raw = env.file.save()
            for name in ("basepack", "maskpack", "barepack", "colourpack"):
                self.store(destination, name + "_ios", raw)

    def test_default_tool_body_and_original_model_basename_are_preserved(self):
        with sqlite3.connect(self.root / "assets/db/gl/masterdata.db") as db:
            db.execute("UPDATE m_suit SET model_asset_path='models/ch0007_co0123_body' WHERE id IN(1,3)")
        with sqlite3.connect(self.root / "assets/db/gl/asset_a_ko.db") as db:
            db.execute("UPDATE member_model SET asset_path='models/ch0007_co0123_body' WHERE asset_path='body'")
        record = game.validate_selection(self.root, {"region": "gl", "suit": "suit:1", "variant": "primary",
            "download": False, "purpose": "transplant"}, "ko")
        self.assertEqual(record["platform"], "android")
        paths = self.run_import(record)
        self.assertEqual(len(paths), 1)
        self.assertEqual(Path(paths[0]).name, "ch0007_co0123_body.unity")
        self.assertEqual(Path(paths[0]).read_bytes(), self.helper.payload)

    def test_ios_gl_jp_and_rina_unmasked_are_separate_native_cache_selections(self):
        self.ios_catalog()
        choices = [("gl", "android", "primary"), ("gl", "ios", "primary"),
                   ("jp", "ios", "primary"), ("gl", "ios", "unmasked")]
        outputs = []
        for region, platform, variant in choices:
            record = self.selection(suit="suit:2", region=region, platform=platform, variant=variant)
            self.assertEqual(record["model"], "unmasked" if variant == "unmasked" else "masked")
            path = Path(self.run_import(record)[0]); outputs.append(path)
            env = UnityPy.load(path.read_bytes())
            self.assertEqual({int(asset.target_platform) for asset in env.assets}, {9 if platform == "ios" else 13})
            self.assertEqual(self.run_import(record), [str(path)])
        self.assertEqual(len(set(outputs)), len(choices))

    def test_missing_or_mislabeled_ios_never_falls_back_or_converts_android(self):
        with self.assertRaisesRegex(ValueError, "iOS asset catalog"):
            self.selection(platform="ios")
        self.ios_catalog(wrong_platform=True)
        with self.assertRaisesRegex(ValueError, "native platform"):
            self.run_import(self.selection(platform="ios"))

    def test_request_boundary_rejects_untrusted_paths_platforms_and_unknown_intents(self):
        valid = {"region": "gl", "suit": "suit:1", "variant": "primary", "download": False}
        bad = [{"purpose": "body"}, {"purpose": True}, {"platform": "android"},
               {"purpose": "transplant", "platform": "../ios"}, {"purpose": "transplant", "path": "/tmp/body"},
               {"purpose": "transplant", "url": "https://example.invalid/body"}]
        for extra in bad:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                game.validate_selection(self.root, dict(valid, **extra))

    def test_texture_only_asset_is_not_accepted_as_a_costume_body(self):
        raw = (Path(__file__).parent / "fixtures/viewer_textured_triangle.unity").read_bytes()
        self.store(self.root / "assets/db/gl/asset_a_ko.db", "basepack", self.bundle("texture.assets", raw))
        with self.assertRaisesRegex(ValueError, "not a skinned costume body"):
            self.run_import()

    def test_plain_viewer_model_is_rejected_for_the_bundle_only_transplant_consumer(self):
        raw = (Path(__file__).parent / "fixtures/viewer_rig.unity").read_bytes()
        self.store(self.root / "assets/db/gl/asset_a_ko.db", "basepack", raw)
        with self.assertRaisesRegex(ValueError, "original UnityFS"):
            self.run_import()

    def test_unicode_source_and_cache_paths_leave_catalog_packs_and_user_data_unchanged(self):
        packs = self.root / "게임팩_原本"
        self.helper.packs.rename(packs)
        userdata = self.root / "userdata.db"
        userdata.write_bytes(b"synthetic user database sentinel; never opened by importer")
        sources = list((self.root / "assets").rglob("*.db")) + list(packs.iterdir()) + [userdata]
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        job = Job("unicode", "viewer_game_assets")
        with patch.object(original.extractor, "build_pack_roots", return_value=[str(packs)]):
            game.run_import(job, repo_root=self.root, output_root=self.output / "공여_着用", record=self.selection())
        self.assertEqual(len(job.output_paths()), 1)
        self.assertEqual(Path(job.output_paths()[0]).read_bytes(), self.helper.payload)
        for path, digest in before.items(): self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), digest)

    def test_owner_edited_cache_is_preserved_and_warm_cancellation_publishes_nothing(self):
        first = Path(self.run_import()[0]); first.write_bytes(b"user edited copy")
        second = Path(self.run_import()[0])
        self.assertNotEqual(first, second); self.assertEqual(first.read_bytes(), b"user edited copy")
        self.assertEqual(second.read_bytes(), self.helper.payload)
        job = Job("warm-cancel", "viewer_game_assets")
        real = game._tool_body
        def stop(raw, platform):
            real(raw, platform); job.cancel_event.set()
        with patch.object(game, "_tool_body", side_effect=stop):
            self.assertEqual(self.run_import(job=job), [])
        self.assertEqual(second.read_bytes(), self.helper.payload)

    def test_warm_cache_refuses_source_pack_changed_during_validation(self):
        path = Path(self.run_import()[0]); before = path.read_bytes()
        real = game._tool_body
        def change(raw, platform):
            real(raw, platform)
            pack = self.helper.packs / "basepack"; stamp = pack.stat()
            data = bytearray(pack.read_bytes()); data[0] ^= 1; pack.write_bytes(data)
            os.utime(pack, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000))
        job = Job("warm-changed", "viewer_game_assets")
        with patch.object(game, "_tool_body", side_effect=change), self.assertRaisesRegex(ValueError, "source pack changed"):
            self.run_import(job=job)
        self.assertEqual(job.output_paths(), []); self.assertEqual(path.read_bytes(), before)

    def test_late_catalog_mutation_and_cancellation_publish_no_body(self):
        real = game._tool_body
        def mutate(raw, platform):
            real(raw, platform)
            with sqlite3.connect(self.root / "assets/db/gl/asset_a_ko.db") as db:
                db.execute("UPDATE member_model SET key1=key1+1 WHERE asset_path='body'")
        with patch.object(game, "_tool_body", side_effect=mutate), self.assertRaisesRegex(ValueError, "catalog changed"):
            self.run_import()
        self.assertEqual(list(self.output.glob("gl-*")), [])
        with sqlite3.connect(self.root / "assets/db/gl/asset_a_ko.db") as db:
            db.execute("UPDATE member_model SET key1=7 WHERE asset_path='body'")
        job = Job("cancel", "viewer_game_assets")
        def stop(raw, platform):
            real(raw, platform); job.cancel_event.set()
        with patch.object(game, "_tool_body", side_effect=stop):
            self.assertEqual(self.run_import(job=job), [])
        self.assertFalse(list(self.output.glob("*.part")))

    @staticmethod
    def bundle(name, raw):
        info = bytes(16) + struct.pack(">iIIHi", 1, len(raw), len(raw), 0, 1)
        info += struct.pack(">qqI", 0, len(raw), 0) + name.encode() + b"\0"
        prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + b"2019.4.0f1\0"
        return prefix + struct.pack(">QIII", len(prefix) + 20 + len(info) + len(raw), len(info), len(info), 64) + info + raw

    def test_real_selected_colour_texture_is_inside_returned_body_without_uv_resampling(self):
        def texture(raw, name, colour):
            env = UnityPy.load(raw)
            for obj in env.objects:
                if obj.type.name == "Texture2D":
                    image = obj.read(); image.m_Name = name; image.m_TextureFormat = 4
                    image.image = Image.new("RGBA", (2, 2), colour); image.save()
            return env.file.save()
        body = texture(geometry.make_fixture(), "Body", (0, 0, 255, 255))
        variant = texture((Path(__file__).parent / "fixtures/viewer_textured_triangle.unity").read_bytes(),
                          "Body_c1", (255, 0, 0, 255))
        catalog = self.root / "assets/db/gl/asset_a_ko.db"
        self.store(catalog, "basepack", self.bundle("base.assets", body))
        self.store(catalog, "colourpack", self.bundle("colour.assets", variant))
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*") if p.is_file()}
        path = Path(self.run_import(self.selection(suit="suit:3"))[0])
        env = UnityPy.load(path.read_bytes())
        images = [obj.read().image.convert("RGBA") for obj in env.objects if obj.type.name == "Texture2D"]
        self.assertTrue(images)
        self.assertEqual(images[0].size, (2, 2)); self.assertEqual(set(images[0].getdata()), {(255, 0, 0, 255)})
        old_mesh = next(obj.get_raw_data() for obj in UnityPy.load(body).objects if obj.type.name == "Mesh")
        self.assertEqual(next(obj.get_raw_data() for obj in env.objects if obj.type.name == "Mesh"), old_mesh)
        for name, digest in before.items(): self.assertEqual(hashlib.sha256(Path(name).read_bytes()).hexdigest(), digest)

    def test_canonical_scene_returns_exact_selected_body_while_viewer_keeps_original_zip(self):
        helper = scenes.SceneRolesTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        path = helper.source(("android", "ios")); token, nodes, _ = helper.prepare(path)
        result, decoded = helper.package(token, helper.state(nodes))
        archive = Path(result["mod_package"]["package_path"])
        scene = {"archive_path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "target_member_id": 209,
                 "canonical_model_paths": {"gl": {"primary": "models/ch9999_co0123_board", "unmasked": "models/ch0209_co0123_bare"}}}
        with patch.object(game, "_installed_scene", return_value=scene):
            record = self.selection(suit="suit:2", variant="unmasked", platform="ios")
            output = Path(self.run_import(record)[0])
            expected = helper.golden(decoded, "ios", "unmasked")
            self.assertEqual(output.read_bytes(), expected); self.assertEqual(output.suffix, ".unity")
            self.assertEqual(output.name, "ch0209_co0123_bare.unity")
            self.assertEqual(self.run_import(record), [str(output)])
            legacy = self.helper.run_import(self.helper.select("suit:2")).output_paths()
            self.assertEqual(Path(legacy[0]).read_bytes(), archive.read_bytes()); self.assertEqual(Path(legacy[0]).suffix, ".zip")


if __name__ == "__main__":
    unittest.main()
