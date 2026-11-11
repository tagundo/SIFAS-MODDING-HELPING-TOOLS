"""Source-bound texture edits through real Unity files, mips and viewer exports."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import secrets
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
import zlib
from types import SimpleNamespace

import UnityPy
from PIL import Image

from webtools.core import decode, model_edits, model_materials, model_viewer
from webtools.core import viewer_mesh_tools, viewer_mod_flow, viewer_texture_tools as textures


FIXTURE = Path(__file__).parent / "fixtures" / "viewer_persistence.unity"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def uri(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def image_from_uri(value):
    with Image.open(io.BytesIO(base64.b64decode(value.split(",", 1)[1]))) as image:
        return image.convert("RGBA")


def authored_texture(raw):
    """Give the existing Texture2D a non-square base and distinct authored mips."""
    env = UnityPy.load(raw)
    images = []
    for level in range(4):
        image = Image.new("RGBA", (max(1, 8 >> level), max(1, 4 >> level)))
        image.putdata([(30 + 45 * level + x * 3, 50 + y * 7, 90 + level,
                        80 + (x * 17 + y * 23 + level * 13) % 150)
                       for y in range(image.height) for x in range(image.width)])
        images.append(image)
    for asset in env.assets:
        asset._m_target_platform = 13
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        tree = obj.read_typetree()
        payload = b"".join(image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
                           for image in images)
        tree.update(m_Name="ch0002_co0001_body", m_Width=8, m_Height=4,
                    m_TextureFormat=4, m_MipCount=4, m_CompleteImageSize=len(payload))
        tree["image data"] = payload
        if "m_MipMap" in tree:
            tree["m_MipMap"] = True
        if "m_StreamData" in tree:
            tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        obj.save_typetree(tree)
    return env.file.save(), images


def unity_objects(raw):
    env = UnityPy.load(raw)
    return env, {(index, obj.path_id): obj for index, asset in enumerate(env.assets)
                 for obj in asset.objects.values()}


class ViewerTextureRoundtripTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.raw, self.images = authored_texture(FIXTURE.read_bytes())
        self.source = self.root / "costume.unity"
        self.source.write_bytes(self.raw)
        self.token, self.metadata = self.open_session([str(self.source)])
        self.catalogue = textures.inspect(self.token)
        self.entry = next(row for row in self.catalogue["textures"]
                          if row["name"] == "ch0002_co0001_body")
        self.identity = self.entry["texture"]

    def open_session(self, paths, **options):
        prepared = model_viewer.prepare(paths, rigged=True,
            face_context={"enabled": False, "allow_download": False})
        token = secrets.token_hex(16)
        metadata = model_edits.register_session(token, paths, prepared["rig"], **options)
        return token, metadata

    def operation(self, image=None, **changes):
        value = {"texture": copy.deepcopy(self.identity), "sourceSha256": digest(self.raw),
                 "png": uri(image or self.images[0]), "kind": "costume"}
        value.update(changes)
        return value

    def state(self, *operations, **changes):
        return {"version": 1, "savedSettingsEnabled": True, "edits": [],
                "textures": list(operations), **changes}

    def edit_image(self):
        image = self.images[0].copy()
        before = image.getpixel((3, 1))
        image.putpixel((3, 1), (209, 31, 182, before[3]))
        return image

    def save(self, state):
        return model_edits.export(self.token, state, self.root / "output")

    def test_catalogue_is_lazy_and_original_pixels_are_loaded_on_demand(self):
        from webtools.core import decode
        with patch.object(decode, "_android_image", side_effect=AssertionError("catalogue decoded pixels")):
            catalog = textures.inspect(self.token)
        self.assertTrue(catalog["textures"])
        self.assertEqual((self.entry["width"], self.entry["height"]), (8, 4))
        self.assertTrue(self.entry["available"], self.entry.get("reason"))
        self.assertNotIn("image", self.entry)
        self.assertEqual(set(self.identity), {"source", "file", "id"})
        data = textures.data(self.token, self.identity)
        self.assertEqual(data["sourceSha256"], digest(self.raw))
        actual = image_from_uri(data["image"])
        self.assertEqual(actual.size, (8, 4))
        self.assertEqual(actual.tobytes(), self.images[0].tobytes())
        self.assertEqual(zlib.decompress(base64.b64decode(data["rgbaZlib"])), self.images[0].tobytes())
        with patch.object(decode, "_android_image", side_effect=AssertionError("cached texture decoded again")):
            self.assertEqual(textures.data(self.token, self.identity)["rgbaZlib"], data["rgbaZlib"])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_rgba_transport_preserves_hidden_and_partially_transparent_colour_bytes(self):
        image = self.images[0].copy()
        image.putpixel((0, 0), (203, 29, 171, 0))
        image.putpixel((1, 0), (79, 157, 231, 1))
        image.putpixel((2, 0), (87, 163, 219, 127))
        env = UnityPy.load(self.raw)
        for obj in env.objects:
            if obj.type.name == "Texture2D":
                tree = obj.read_typetree()
                base = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
                tree["image data"] = base + bytes(tree["image data"])[len(base):]
                obj.save_typetree(tree)
        raw = env.file.save()
        source = self.root / "transparent-original.unity"
        source.write_bytes(raw)
        token, _ = self.open_session([str(source)])
        entry = textures.inspect(token)["textures"][0]
        data = textures.data(token, entry["texture"])
        self.assertEqual(zlib.decompress(base64.b64decode(data["rgbaZlib"])), image.tobytes())
        imported = image.copy()
        imported.putpixel((3, 0), (77, 211, 43, 2))
        loaded = textures.decode(token, entry["texture"], uri(imported))
        self.assertEqual(zlib.decompress(base64.b64decode(loaded["rgbaZlib"])), imported.tobytes())
        self.assertEqual(image_from_uri(loaded["image"]).tobytes(), imported.tobytes())
        self.assertEqual(source.read_bytes(), raw)
        with self.assertRaises(ValueError):
            textures.decode(token, entry["texture"], uri(Image.new("RGBA", (4, 8))))

    def test_texture_only_export_preserves_alpha_unselected_pixels_and_unity_contract(self):
        edited = self.edit_image()
        saved = self.save(self.state(self.operation(edited)))
        raw = Path(saved["preview_paths"][0]).read_bytes()
        _, old = unity_objects(self.raw)
        _, current = unity_objects(raw)
        self.assertEqual(set(current), set(old))
        key = (self.identity["file"], int(self.identity["id"]))
        for ident, before in old.items():
            if ident != key:
                self.assertEqual(current[ident].get_raw_data(), before.get_raw_data(),
                                 (ident, before.type.name))
        before, after = old[key].read_typetree(), current[key].read_typetree()
        self.assertEqual((after["m_Width"], after["m_Height"], after["m_MipCount"]), (8, 4, 4))
        for field in ("m_Name", "m_ColorSpace", "m_TextureSettings", "m_ImageCount", "m_TextureDimension"):
            self.assertEqual(after.get(field), before.get(field), field)
        actual = current[key].read().image.convert("RGBA")
        self.assertEqual(actual.tobytes(), edited.tobytes())
        self.assertEqual(actual.getchannel("A").tobytes(), self.images[0].getchannel("A").tobytes())
        for y in range(4):
            for x in range(8):
                if (x, y) != (3, 1):
                    self.assertEqual(actual.getpixel((x, y)), self.images[0].getpixel((x, y)))
        texture = current[key].read()
        lower = [proxy.read() for proxy in model_materials._original_mips(current[key], texture)]
        for ordinal, level in enumerate(lower, 1):
            pixels = decode._android_image(level, time.monotonic() + 10).convert("RGBA")
            changed = (min(pixels.width - 1, 3 >> ordinal), min(pixels.height - 1, 1 >> ordinal))
            for y in range(pixels.height):
                for x in range(pixels.width):
                    if (x, y) != changed:
                        self.assertEqual(pixels.getpixel((x, y)), self.images[ordinal].getpixel((x, y)))
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(Path(saved["original_paths"][0]).read_bytes(), self.raw)
        self.assertTrue(model_edits.has_changes(saved["recipe"]["state"]))

    def test_every_authored_mip_is_updated_including_one_pixel_tail(self):
        edited = self.images[0].copy()
        edited.putdata([(208, 72, 39, pixel[3]) for pixel in edited.getdata()])
        saved = self.save(self.state(self.operation(edited)))
        _, objects = unity_objects(Path(saved["preview_paths"][0]).read_bytes())
        obj = objects[(self.identity["file"], int(self.identity["id"]))]
        texture = obj.read()
        levels = [texture] + [proxy.read() for proxy in model_materials._original_mips(obj, texture)]
        self.assertEqual([level.m_Width for level in levels], [8, 4, 2, 1])
        self.assertEqual([level.m_Height for level in levels], [4, 2, 1, 1])
        for ordinal, level in enumerate(levels):
            decoded = decode._android_image(level, time.monotonic() + 10).convert("RGBA")
            self.assertEqual(decoded.getchannel("A").tobytes(),
                             self.images[ordinal].getchannel("A").tobytes())
            for pixel in decoded.getdata():
                self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(pixel[:3], (208, 72, 39))), pixel)

    def test_paint_can_explicitly_change_alpha_without_repainting_other_pixels(self):
        image = self.images[0].copy()
        before = image.getpixel((1, 2))
        image.putpixel((1, 2), (*before[:3], 0))
        saved = self.save(self.state(self.operation(image, kind="paint")))
        _, objects = unity_objects(Path(saved["preview_paths"][0]).read_bytes())
        texture = objects[(self.identity["file"], int(self.identity["id"]))].read()
        self.assertEqual(texture.image.convert("RGBA").tobytes(), image.tobytes())

    def test_mixed_colour_and_alpha_paint_preserves_unselected_authored_mip_alpha(self):
        image = self.images[0].copy()
        image.putdata([(201, 23, 180, pixel[3]) for pixel in image.getdata()])
        image.putpixel((1, 2), (201, 23, 180, 0))
        saved = self.save(self.state(self.operation(image, kind="paint")))
        _, objects = unity_objects(Path(saved["preview_paths"][0]).read_bytes())
        obj = objects[(self.identity["file"], int(self.identity["id"]))]
        texture = obj.read()
        self.assertEqual(texture.image.convert("RGBA").tobytes(), image.tobytes())
        for ordinal, proxy in enumerate(model_materials._original_mips(obj, texture), 1):
            level = decode._android_image(proxy.read(), time.monotonic() + 10).convert("RGBA")
            alpha_target = (min(level.width - 1, 1 >> ordinal), min(level.height - 1, 2 >> ordinal))
            for y in range(level.height):
                for x in range(level.width):
                    if (x, y) != alpha_target:
                        self.assertEqual(level.getpixel((x, y))[3], self.images[ordinal].getpixel((x, y))[3])

    def test_portable_recipe_reopens_originals_and_does_not_accumulate_edits(self):
        state = self.state(self.operation(self.edit_image(), kind="skin"))
        first, second = self.save(state), self.save(state)
        self.assertEqual(Path(first["preview_paths"][0]).read_bytes(), Path(second["preview_paths"][0]).read_bytes())
        serialized = json.loads(json.dumps(first["recipe"]))
        other, _ = self.open_session(first["original_paths"])
        restored = model_edits.restore(other, serialized)
        self.assertEqual(restored["textures"], serialized["state"]["textures"])
        again = model_edits.export(other, restored, self.root / "restored")
        self.assertEqual(Path(first["preview_paths"][0]).read_bytes(), Path(again["preview_paths"][0]).read_bytes())

    def test_body_and_mesh_edits_survive_same_source_texture_export(self):
        breast = next(row for row in self.metadata["nodes"] if row["name"] == "BreastSize")
        state = self.state(self.operation(self.edit_image(), kind="paint"), edits=[{
            "node": breast["node"], "method": "node", "scale": [1.21, 1.13, .91]}])
        mesh = viewer_mesh_tools.inspect(self.token)["meshes"][0]["mesh"]
        mesh_state = {"version": 1, "meshes": [{"mesh": mesh, "deleteFaces": [0]}]}
        runtime = self.root / "runtime"
        runtime.mkdir()
        result = viewer_mod_flow.export_current(self.token, state, self.root / "combined",
            mesh_state=mesh_state, repo_root=runtime, cache_root=self.root / "cache")
        output = Path(result["preview_paths"][0]).read_bytes()
        info = model_edits._inspect(output)
        target = next(key for key, name in info["names"].items() if name == "BreastSize")
        for value, wanted in zip(info["effective"][target]["scale"], [1.21, 1.13, .91]):
            self.assertAlmostEqual(value, wanted, places=5)
        _, records = viewer_mesh_tools._mesh_records(output, 0)
        faces, _, _ = viewer_mesh_tools._triangles(records[0][2], 6)
        self.assertEqual(len(faces), 3)
        _, objects = unity_objects(output)
        texture = objects[(self.identity["file"], int(self.identity["id"]))].read()
        self.assertEqual(texture.image.convert("RGBA").tobytes(), self.edit_image().tobytes())
        other, _ = self.open_session(result["original_paths"])
        restored = viewer_mod_flow.restore_current(other, json.loads(json.dumps(result["recipe"])))
        self.assertEqual(restored["state"]["textures"], result["recipe"]["bodyState"]["textures"])
        self.assertEqual(restored["mesh_state"], mesh_state)

    def test_texture_only_mod_zip_and_install_receipt_retain_edited_pixels(self):
        import ast

        runtime = self.root / "runtime"
        runtime.mkdir()
        state = self.state(self.operation(self.edit_image()))
        job = SimpleNamespace(log=lambda _: None, should_stop=lambda: False,
                              progress=lambda *args: None)
        result = viewer_mod_flow.create_package(self.token, state,
            output_root=self.root / "mod-output", repo_root=runtime,
            cache_root=self.root / "cache", display_name="Recoloured costume",
            character_id=2, job=job)
        package = result["mod_package"]
        self.assertTrue(package["installable"])
        with zipfile.ZipFile(package["package_path"]) as archive:
            manifest = {node.targets[0].id: ast.literal_eval(node.value)
                        for node in ast.parse(archive.read("modinstall.txt").decode()).body}
            self.assertEqual(manifest["chara_id"], 2)
            raw = archive.read(manifest["costume_file"])
        _, objects = unity_objects(raw)
        texture = objects[(self.identity["file"], int(self.identity["id"]))].read()
        self.assertEqual(texture.image.convert("RGBA").tobytes(), self.edit_image().tobytes())
        receipt = viewer_mod_flow.validate_install(package["token"])
        self.assertEqual(receipt["state"]["textures"], result["recipe"]["state"]["textures"])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_texture_edit_rewrites_only_its_bound_archive_member(self):
        from webtools.core import viewer_archive

        archive = self.root / "original.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("nested/costume.unity", self.raw)
            output.writestr("notes.txt", "원본 사용자 메모")
            output.writestr("thumbnail.png", b"untouched original thumbnail bytes")
            output.comment = b"original archive comment"
        original = archive.read_bytes()
        with viewer_archive.expand_inputs([str(archive)], self.root / "zip-cache") as expanded:
            prepared = model_viewer.prepare(expanded.paths, rigged=True,
                face_context={"enabled": False, "allow_download": False})
            token = secrets.token_hex(16)
            model_edits.register_session(token, expanded.paths, prepared["rig"],
                originals=[str(archive)], origins=expanded.origins,
                archive_members=expanded.archive_members)
        entry = textures.inspect(token)["textures"][0]
        operation = self.operation(self.edit_image(), texture=entry["texture"])
        result = model_edits.export(token, self.state(operation), self.root / "zip-output")
        with zipfile.ZipFile(archive) as before, zipfile.ZipFile(result["preview_paths"][0]) as after:
            self.assertEqual(after.namelist(), before.namelist())
            self.assertEqual(after.comment, before.comment)
            for name in before.namelist():
                if name == "nested/costume.unity":
                    self.assertNotEqual(after.read(name), before.read(name))
                else:
                    self.assertEqual(after.read(name), before.read(name))
        self.assertEqual(archive.read_bytes(), original)

    def test_verified_face_companion_textures_keep_their_distinct_source_identity(self):
        companion = self.root / "verified-face.unity"
        companion.write_bytes(self.raw)
        token, _ = self.open_session([str(self.source)], companions=[{
            "path": str(companion), "sha256": digest(self.raw), "sourceIndex": 1}])
        catalog = textures.inspect(token)["textures"]
        self.assertEqual({row["texture"]["source"] for row in catalog}, {0, 1})
        face = next(row for row in catalog if row["texture"]["source"] == 1)
        data = textures.data(token, face["texture"])
        self.assertEqual(data["sourceSha256"], digest(self.raw))
        self.assertEqual(image_from_uri(data["image"]).tobytes(), self.images[0].tobytes())
        self.assertEqual(companion.read_bytes(), self.raw)

    def test_paired_texture_scope_reports_selected_source_only_and_preserves_other_uv_layout(self):
        import numpy as np
        from sifas_mesh_baker import read_attr, stream_layout, write_attr
        from webtools.core import viewer_mod_pair_edits

        environment = UnityPy.load(self.raw)
        for obj in environment.objects:
            tree = obj.read_typetree()
            if obj.type.name == "Texture2D":
                images = [Image.new("RGBA", (max(1, 4 >> level), max(1, 8 >> level)),
                                    (11 + level, 189, 61, 255)) for level in range(4)]
                payload = b"".join(image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
                                   for image in images)
                tree.update(m_Width=4, m_Height=8, m_CompleteImageSize=len(payload))
                tree["image data"] = payload
                obj.save_typetree(tree)
            elif obj.type.name == "Mesh":
                count, channels, strides, starts, _ = stream_layout(tree)
                raw = np.frombuffer(bytes(tree["m_VertexData"]["m_DataSize"]), dtype=np.uint8).copy()
                uv = read_attr(raw, 4, channels, strides, starts, count)
                uv[:, 0] = 1 - uv[:, 0]
                uv[:, 1] *= .5
                write_attr(raw, uv, 4, channels, strides, starts, count)
                tree["m_VertexData"]["m_DataSize"] = raw.tobytes()
                obj.save_typetree(tree)
        counterpart = self.root / "different-layout.unity"
        other_raw = environment.file.save()
        counterpart.write_bytes(other_raw)
        state = self.state(self.operation(self.edit_image()))
        selected = self.save(state)
        selected_path = selected["preview_paths"][0]
        selected_raw = Path(selected_path).read_bytes()
        pair = {"owner": 2, "platform": "android", "explicit_source": True,
                "primary": {"path": selected_path, "sha256": digest(selected_raw)},
                "unmasked": {"path": str(counterpart), "sha256": digest(other_raw)}}
        messages = []
        result = viewer_mod_pair_edits.apply_pair_edits(
            model_edits.mod_source_context(self.token), selected, state,
            pair=pair, job=SimpleNamespace(log=messages.append, should_stop=lambda: False))
        self.assertEqual(result["pair"], pair)
        self.assertEqual(result["result"]["preview_paths"], selected["preview_paths"])
        self.assertEqual(result["summary"][0]["status"], "selected_source_only")
        self.assertEqual(result["summary"][0]["kind"], "textures")
        self.assertTrue(messages)
        self.assertIn("textures", state)
        self.assertEqual(counterpart.read_bytes(), other_raw)
        self.assertEqual(Path(selected_path).read_bytes(), selected_raw)
        _, objects = unity_objects(selected_raw)
        edited_texture = objects[(self.identity["file"], int(self.identity["id"]))].read()
        self.assertEqual(edited_texture.image.convert("RGBA").tobytes(), self.edit_image().tobytes())

    def test_invalid_identity_hash_png_dimensions_and_duplicate_operations_publish_nothing(self):
        wrong = self.operation(texture={**self.identity, "source": True})
        missing = self.operation(texture={**self.identity, "id": "9223372036854775807"})
        states = [self.state(wrong), self.state(missing),
            self.state(self.operation(sourceSha256="0" * 64)),
            self.state(self.operation(png="data:image/png;base64,bm90IGEgcG5n")),
            self.state(self.operation(Image.new("RGBA", (4, 8), (1, 2, 3, 4)))),
            self.state(self.operation(kind="unrecognised")),
            self.state(self.operation(), self.operation())]
        for state in states:
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.save(state)
        self.assertEqual(self.source.read_bytes(), self.raw)
        if (self.root / "output").exists():
            self.assertEqual(list((self.root / "output").iterdir()), [])

    def test_original_file_change_is_detected_before_any_export(self):
        self.source.write_bytes(self.raw + b"changed after opening")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.save(self.state(self.operation(self.edit_image())))
        if (self.root / "output").exists():
            self.assertEqual(list((self.root / "output").iterdir()), [])

    def test_single_and_aggregate_png_limits_fail_before_any_output(self):
        # Valid PNG ancillary data counts towards transport budgets too. This
        # tests byte limits using an 8x4 image without huge pixel allocations.
        def padded_png(length):
            raw = base64.b64decode(uri(self.images[0]).split(",", 1)[1])
            chunk = b"vpAg" + bytes(length)
            encoded = raw[:-12] + struct.pack(">I", length) + chunk
            encoded += struct.pack(">I", zlib.crc32(chunk) & 0xffffffff) + raw[-12:]
            return "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")

        too_large = padded_png(8 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, "8 MiB|bounded PNG"):
            self.save(self.state(self.operation(png=too_large)))
        del too_large
        companion = self.root / "other-original.unity"
        companion.write_bytes(self.raw)
        token, _ = self.open_session([str(self.source), str(companion)])
        records = textures.inspect(token)["textures"]
        self.assertEqual(len(records), 2)
        large = padded_png(6 * 1024 * 1024 + 1024)
        operations = [self.operation(texture=row["texture"], png=large) for row in records]
        with self.assertRaisesRegex(ValueError, "12 MiB|too large"):
            model_edits.export(token, self.state(*operations), self.root / "output")
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(companion.read_bytes(), self.raw)
        if (self.root / "output").exists():
            self.assertEqual(list((self.root / "output").iterdir()), [])


class StandaloneTextureImageTests(unittest.TestCase):
    def test_standalone_png_preserves_unpremultiplied_rgba_without_a_model(self):
        image = Image.new("RGBA", (3, 2))
        image.putdata([(203, 29, 171, 0), (79, 157, 231, 1), (87, 163, 219, 127),
                       (17, 213, 81, 255), (7, 11, 19, 3), (233, 131, 67, 191)])
        encoded = uri(image)
        with patch.object(textures, "_session", side_effect=AssertionError("No model may be required")):
            result = textures.decode_image(encoded)
        self.assertEqual((result["width"], result["height"]), image.size)
        self.assertEqual(result["image"], encoded)
        self.assertEqual(zlib.decompress(base64.b64decode(result["rgbaZlib"])), image.tobytes())
        self.assertNotIn("texture", result)
        self.assertNotIn("sourceSha256", result)

    def test_standalone_decoder_refuses_invalid_animated_and_oversize_png_before_pixel_load(self):
        from PIL import PngImagePlugin

        jpeg = io.BytesIO()
        Image.new("RGB", (2, 2)).save(jpeg, "JPEG")
        animated = io.BytesIO()
        Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(animated, "PNG", save_all=True,
            append_images=[Image.new("RGBA", (2, 2), (0, 255, 0, 255))], duration=100, loop=0)
        bad = [None, "", "/tmp/input.png", "data:image/png;base64,not base64",
               "data:image/png;base64," + base64.b64encode(jpeg.getvalue()).decode("ascii"),
               "data:image/png;base64," + base64.b64encode(animated.getvalue()).decode("ascii")]
        for value in bad:
            with self.subTest(value=str(value)[:60]), self.assertRaises(ValueError):
                textures.decode_image(value)

        original = base64.b64decode(uri(Image.new("RGBA", (1, 1))).split(",", 1)[1])
        for width, height in ((8193, 1), (4097, 4097)):
            ihdr = struct.pack(">II", width, height) + original[24:29]
            inflated = original[:16] + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xffffffff) + original[33:]
            encoded = "data:image/png;base64," + base64.b64encode(inflated).decode("ascii")
            with self.subTest(size=(width, height)), \
                    patch.object(PngImagePlugin.PngImageFile, "load", side_effect=AssertionError("Oversize pixels must not be loaded")), \
                    self.assertRaisesRegex(ValueError, "16-megapixel"):
                textures.decode_image(encoded)
        oversized = "data:image/png;base64," + base64.b64encode(bytes(8 * 1024 * 1024 + 1)).decode("ascii")
        with self.assertRaisesRegex(ValueError, "8 MiB|bounded PNG"):
            textures.decode_image(oversized)


if __name__ == "__main__":
    unittest.main()
