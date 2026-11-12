"""Bound thumbnail receipts and real PNG/installer-archive preservation.

WebGL rendering is exercised separately in viewer_thumbnail_browser.js. These
checks deliberately exercise rejection of stale sources/options/template data.
"""
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from webtools.core import viewer_thumbnails as thumbs

try:
    from PIL import Image
    import UnityPy
    import unity_costumemod_packer as packer
    from webtools.core import viewer_mod_package
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "UnityPy and Pillow are needed for thumbnail receipts")
class ViewerThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "006-costume.unity"
        self.raw = (Path(__file__).parent / "fixtures/viewer_persistence.unity").read_bytes()
        self.source.write_bytes(self.raw)
        jailed = patch("webtools.filebrowser.is_within_allowed", lambda p: Path(p).resolve().is_relative_to(self.root))
        jailed.start(); self.addCleanup(jailed.stop)
        self.addCleanup(thumbs._PLANS.clear)
        self.params = {"mode": "single", "in_path": str(self.source), "auto_chara_id": False,
            "manual_chara_id": "6", "thumbnail_size": "256", "combine_pairs": True, "thumbnail_mode": "3d"}
        image = Image.new("RGBA", (256, 256), (22, 55, 88, 255)); stream = io.BytesIO(); image.save(stream, format="PNG")
        self.png = stream.getvalue()
        self.render = {"quality": {"enabled": True, "ready": True}, "subjectPixels": 128, "triangles": 4}

    def plan(self, params=None):
        return thumbs.plan({"kind": "packer", "params": params or self.params})

    def upload(self, plan, **override):
        item = plan["items"][0]
        request = {"token": plan["token"], "item_id": item["id"], "cache_key": item["cacheKey"],
            "profile_digest": plan["profileDigest"], "png": "data:image/png;base64," + base64.b64encode(self.png).decode(),
            "render": self.render}
        request.update(override)
        return thumbs.store(request)

    def test_receipt_binds_actual_source_recipient_and_png(self):
        plan = self.plan(); receipt = self.upload(plan)
        provider = thumbs.packer_provider(dict(self.params, thumbnail_plan=plan["token"]))
        self.assertEqual(provider(str(self.source), 256, 6), self.png)
        self.assertEqual(receipt["sha256"], hashlib.sha256(self.png).hexdigest())
        self.assertEqual(receipt["sources"], [{"name": self.source.name, "sha256": hashlib.sha256(self.raw).hexdigest()}])
        self.assertEqual(receipt["characterId"], 6)
        self.assertEqual(receipt["quality"]["renderer"], "SifasMaterial")
        self.assertIs(receipt["quality"]["rimlight"], False)
        with self.assertRaisesRegex(ValueError, "another costume/member"):
            provider(str(self.source), 256, 201)

    def test_rimlight_free_profile_has_a_new_render_cache_binding(self):
        current = self.plan()
        self.assertIs(current["quality"]["rimlight"], False)
        # Earlier thumbnails inherited the material renderer's enabled default.
        previous_quality = {key: value for key, value in thumbs.QUALITY.items() if key != "rimlight"}
        with patch.object(thumbs, "QUALITY", previous_quality):
            previous = self.plan()
        self.assertNotEqual(current["items"][0]["cacheKey"], previous["items"][0]["cacheKey"])

    def test_full_character_profile_invalidates_headless_cached_thumbnails(self):
        current = self.plan()
        self.assertEqual(current["quality"]["subject"], "head-and-upper-body-v1")
        with patch.object(thumbs, "QUALITY", {key: value for key, value in thumbs.QUALITY.items() if key != "subject"}):
            headless = self.plan()
        self.assertNotEqual(current["items"][0]["cacheKey"], headless["items"][0]["cacheKey"])

    def test_whole_character_is_opt_in_and_cannot_reuse_default_crop_receipts(self):
        upper = self.plan(); full_params = dict(self.params, thumbnail_fit_full=True)
        full = self.plan(full_params)
        self.assertEqual(upper["quality"]["subject"], "head-and-upper-body-v1")
        self.assertEqual(full["quality"]["subject"], "full-character-v1")
        self.assertNotEqual(upper["items"][0]["cacheKey"], full["items"][0]["cacheKey"])
        self.upload(full)
        with self.assertRaisesRegex(ValueError, "settings changed"):
            thumbs.packer_provider(dict(self.params, thumbnail_plan=full["token"]))
        self.assertEqual(thumbs.packer_provider(dict(full_params, thumbnail_plan=full["token"]))(str(self.source),256,6), self.png)
        for value in ("true", 1, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "full character"):
                self.plan(dict(self.params, thumbnail_fit_full=value))

    def test_existing_zip_automatically_renders_original_eyes_and_binds_the_face_bytes(self):
        from webtools.core import model_viewer
        from test_model_faces import glb_names
        source = self.root / "incoming.zip"
        source.write_bytes((Path(__file__).parent / "fixtures/viewer_auto_face_costume.zip").read_bytes())
        donor = self.root / "ch0207_facedynamic.unity"
        donor.write_bytes((Path(__file__).parent / "fixtures/viewer_auto_face_donor.unity").read_bytes())
        before = {path: path.read_bytes() for path in (source, donor)}
        options = {"mode": "single", "in_path": str(source), "out_dir": str(self.root / "out"), "thumbnail_size": 256}
        with patch("webtools.filebrowser.allowed_roots", return_value={"library": str(self.root)}), \
                patch("webtools.core.sukusta.default_sukusta_dir", side_effect=lambda suffix="": str(self.root / suffix)):
            plan = thumbs.plan({"kind": "updater", "params": options})
            item = plan["items"][0]
            result = thumbs.model({"token": plan["token"], "item_id": item["id"]})
        self.assertIs(result["faces"]["enabled"], True)
        self.assertEqual(result["faces"]["status"], "added")
        self.assertEqual(result["plannedCacheKey"], item["cacheKey"])
        self.assertNotEqual(result["cacheKey"], item["cacheKey"], "auto-added face bytes participate in the actual render binding")
        expected_faces = [{"name": donor.name, "sha256": hashlib.sha256(before[donor]).hexdigest()}]
        self.assertEqual(result["faceSources"], expected_faces)
        expected_key = {"plan": item["cacheKey"], "faces": [[row["name"], row["sha256"]] for row in expected_faces]}
        encoded_key = json.dumps(expected_key, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(result["cacheKey"], hashlib.sha256(encoded_key).hexdigest())
        self.assertEqual(result["excludedMeshes"], [])
        self.assertEqual(set(glb_names({"id": result["url"].rsplit("/", 1)[1][:-4]})), {"Body", "Face_shell", "Eyes"})
        with thumbs._LOCK:
            stored = thumbs._PLANS[plan["token"]]["items"][0]
            self.assertIn([str(donor), hashlib.sha256(before[donor]).hexdigest()], stored["face_source_hashes"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        receipt = self.upload(plan, cache_key=result["cacheKey"])
        self.assertEqual(receipt["faceSources"], expected_faces)
        donor.write_bytes(before[donor] + b"changed")
        with self.assertRaisesRegex(ValueError, "changed after preparing"):
            self.upload(plan, cache_key=result["cacheKey"])

    def test_source_change_after_render_is_rejected(self):
        plan = self.plan(); self.upload(plan)
        provider = thumbs.packer_provider(dict(self.params, thumbnail_plan=plan["token"]))
        self.source.write_bytes(self.raw + b"changed")
        with self.assertRaisesRegex(ValueError, "changed after preparing"):
            provider(str(self.source), 256, 6)
        with self.assertRaisesRegex(ValueError, "changed after preparing"):
            self.upload(plan)

    def test_repeated_completed_plans_and_accessed_batch_remain_usable(self):
        first = self.plan(); self.upload(first)
        other = []
        for _ in range(15):
            current = self.plan(); self.upload(current); other.append(current)
        # Continue using an old selected-file batch before another plan opens.
        thumbs.packer_provider(dict(self.params, thumbnail_plan=first["token"]))
        for _ in range(20):
            current = self.plan(); self.upload(current)
            provider = thumbs.packer_provider(dict(self.params, thumbnail_plan=first["token"]))
            self.assertEqual(provider(str(self.source), 256, 6), self.png)
        self.assertLessEqual(len(thumbs._PLANS), 16)
        self.assertIn(first["token"], thumbs._PLANS)
        self.assertNotIn(other[0]["token"], thumbs._PLANS)

    def test_recipient_and_options_invalidate_old_thumbnail(self):
        plan = self.plan(); self.upload(plan)
        other = self.plan(dict(self.params, manual_chara_id="201"))
        self.assertNotEqual(plan["items"][0]["cacheKey"], other["items"][0]["cacheKey"])
        with self.assertRaisesRegex(ValueError, "settings changed"):
            thumbs.packer_provider(dict(self.params, manual_chara_id="201", thumbnail_plan=plan["token"]))
        with self.assertRaisesRegex(ValueError, "template changed"):
            self.upload(plan, profile_digest="0" * 64)
        with self.assertRaisesRegex(ValueError, "target member"):
            self.plan(dict(self.params, manual_chara_id="999"))

    def test_rejects_missing_render_bad_png_and_wrong_size(self):
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, "did not render"):
            self.upload(plan, render={"quality": {"enabled": False, "ready": True}, "subjectPixels": 2, "triangles": 4})
        with self.assertRaisesRegex(ValueError, "base64"):
            self.upload(plan, png="data:image/png;base64,???")
        stream = io.BytesIO(); Image.new("RGBA", (128, 128)).save(stream, format="PNG")
        with self.assertRaisesRegex(ValueError, "dimensions"):
            self.upload(plan, png="data:image/png;base64," + base64.b64encode(stream.getvalue()).decode())
        with self.assertRaisesRegex(ValueError, "source or template"):
            self.upload(plan, cache_key="0" * 64)

    def test_selected_file_plan_supports_actual_single_subruns(self):
        second = self.root / "006-second.unity"; second.write_bytes(self.raw)
        params = dict(self.params, mode="multi", in_paths=str(self.source) + "\n" + str(second), in_path="")
        plan = self.plan(params); self.assertEqual(len(plan["items"]), 2)
        for item in plan["items"]:
            thumbs.store({"token": plan["token"], "item_id": item["id"], "cache_key": item["cacheKey"],
                "profile_digest": plan["profileDigest"], "png": "data:image/png;base64," + base64.b64encode(self.png).decode(), "render": self.render})
        for source in (self.source, second):
            sub = dict(params, mode="single", in_path=str(source), thumbnail_plan=plan["token"])
            self.assertEqual(thumbs.packer_provider(sub)(str(source), 256, 6), self.png)
        with self.assertRaisesRegex(ValueError, "settings changed"):
            thumbs.packer_provider(dict(sub, in_paths=str(second)))

    def test_custom_image_bypasses_texture_decode_and_preserves_model(self):
        with patch.object(packer, "extract_body_texture_with_unitypy", side_effect=AssertionError("3D must not decode a texture thumbnail")):
            result = packer.pack_single_bundle(str(self.source), str(self.root), auto_chara_id=False,
                manual_chara_id=6, thumbnail_provider=lambda path, size, member: self.png, log=lambda text: None)
        with zipfile.ZipFile(result) as archive:
            import ast
            manifest = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(archive.read("modinstall.txt").decode()).body}
            self.assertEqual(archive.read(manifest["thumbnail_file"]), self.png)
            self.assertEqual(archive.read(manifest["costume_file"]), self.raw)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_replace_zip_thumbnail_preserves_all_original_assets(self):
        original = packer.pack_single_bundle(str(self.source), str(self.root), auto_chara_id=False,
            manual_chara_id=6, thumbnail_provider=lambda path, size, member: self.png, log=lambda text: None)
        before = Path(original).read_bytes()
        other = io.BytesIO(); Image.new("RGBA", (256, 256), (99, 88, 77, 255)).save(other, format="PNG")
        incoming = self.root / "existing.zip"; incoming.write_bytes(before)
        viewer_mod_package._replace_thumbnail(incoming, other.getvalue(), lambda: False)
        with zipfile.ZipFile(io.BytesIO(before)) as old, zipfile.ZipFile(incoming) as new:
            import ast
            values = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(new.read("modinstall.txt").decode()).body}
            self.assertEqual(new.read(values["thumbnail_file"]), other.getvalue())
            for member in old.namelist():
                if member != "modinstall.txt": self.assertEqual(new.read(member), old.read(member))
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_jail_and_default_texture_path(self):
        self.assertIsNone(thumbs.packer_provider(dict(self.params, thumbnail_mode="texture")))
        with self.assertRaisesRegex(ValueError, "outside"):
            self.plan(dict(self.params, in_path="/etc/hosts"))
