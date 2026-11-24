"""Baked blush through the texture tools: catalogue, cheek source, recipe and export.

The head material, BodyPartManager and cheek arrays are synthetic (built with
real Unity serialization); no game texture data is stored in the repository.
REAL_MV_SAMPLES / REAL_SUIT_BUNDLES enable the checks against original bundles.
"""
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import random
import secrets
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import UnityPy
from PIL import Image
from UnityPy.helpers.TypeTreeNode import TypeTreeNode

import astc_standin
import costume_part_transplant as cpt
from webtools.core import decode, model_edits, model_viewer, texture_blush as tb, viewer_texture_tools as textures
from webtools.core.model_materials import _original_mips
from test_graft_shared_assets import add_component, pointer
from test_texture_blush import blob_layer

FIXTURE = Path(__file__).parent / "fixtures" / "viewer_persistence.unity"
SIZE = 64
LEVELS = SIZE.bit_length()  # 64 .. 1


def uri(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def authored_images(seed=4):
    rng = random.Random(seed)
    images = []
    for level in range(LEVELS):
        side = max(1, SIZE >> level)
        image = Image.new("RGBA", (side, side))
        # Skin-like RGB everywhere and an alpha that is not all 255, so an
        # alpha change could not hide.
        image.putdata([(rng.randrange(200, 256), rng.randrange(150, 230), rng.randrange(140, 220), rng.randrange(1, 256))
                       for _ in range(side * side)])
        images.append(image)
    return images


def smooth_images():
    """Opaque skin-like gradients: what an ASTC face block looks like."""
    images = []
    for level in range(LEVELS):
        side = max(1, SIZE >> level)
        image = Image.new("RGBA", (side, side))
        image.putdata([(236 + 16 * x // side, 186 + 30 * y // side, 172 + 24 * (x + y) // (2 * side), 255)
                       for y in range(side) for x in range(side)])
        images.append(image)
    return images


ASTC_6X6 = 56


def texture_payload(images, astc):
    if astc:
        return b"".join(astc_standin.compress(image.transpose(Image.Transpose.FLIP_TOP_BOTTOM), 6) for image in images)
    return b"".join(image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes() for image in images)


def add_attach_table(env, path_id, datas):
    """A MemberAttachTable with its nested datas, through real Unity serialization."""
    mono = next(obj for obj in env.objects if obj.type.name == "MonoBehaviour")
    script = next(obj for obj in env.objects if obj.type.name == "MonoScript")
    source = [{key: value for key, value in row.items() if key != "m_Children"} for row in mono.serialized_type.node.to_dict_list()]
    names = [row["m_Name"] for row in source]

    def block(name, level, rename=None, kind=None):
        start = next(i for i, row in enumerate(source) if row["m_Name"] == name and row["m_Level"] == 1)
        end = next((i for i in range(start + 1, len(source)) if source[i]["m_Level"] <= 1), len(source))
        rows = copy.deepcopy(source[start:end])
        for row in rows:
            row["m_Level"] += level - 1
        rows[0]["m_Name"] = rename or name
        if kind:
            rows[0]["m_Type"] = kind
        return rows

    def vector(name, level, element, children):
        rows = block("scaleValues", level, name)[:4]  # vector, Array, size, data
        rows[3].update(m_Type=element, m_Name="data")
        return rows + children

    header = source[:names.index("targetName")]
    integer = copy.deepcopy(next(row for row in source if row["m_Name"] == "size"))
    integer.update(m_Level=4, m_Name="attachType", m_MetaFlag=0)
    replace = block("m_Name", 7, "replaceBindName") + block("m_GameObject", 7, "replaceObject", "PPtr<Object>")
    data = block("m_Name", 4, "attachName") + [integer] + vector("replaceObjects", 4, "ReplaceObject", replace)
    rows = header + vector("datas", 1, "MemberAttachData", data)
    for index, row in enumerate(rows):
        row["m_Index"] = index
    serialized = copy.copy(mono.serialized_type)
    serialized.node = TypeTreeNode.from_list(rows)
    serialized.script_type_index = -1
    serialized.script_id = path_id.to_bytes(16, "little")
    serialized.old_type_hash = (path_id + 1).to_bytes(16, "little")
    sf = mono.assets_file
    sf.types.append(serialized)
    script_tree = script.read_typetree()
    script_tree.update(m_Name="MemberAttachTable", m_ClassName="MemberAttachTable",
                       m_Namespace="LLAS.Components.Members", m_AssemblyName="Assembly-CSharp.dll")
    cpt._make_object(sf, script, path_id + 1, script_tree)
    component = copy.copy(mono)
    component.path_id = path_id
    component.type_id = len(sf.types) - 1
    component.serialized_type = serialized
    sf.objects[path_id] = component
    tree = {name: value for name, value in mono.read_typetree().items() if name in ("m_GameObject", "m_Enabled", "m_Name")}
    tree.update(m_Script=pointer(path_id + 1), datas=datas)
    component.save_typetree(tree)
    return component


def recolour_images():
    """The recolour suit's face: the same art with other colours."""
    return [Image.merge("RGBA", (lambda r, g, b, a: (g, b, r, a))(*image.split())) for image in smooth_images()]


ATTACH_ID = 900


def head_fixture(*, head=True, astc=False, attach=False):
    env = UnityPy.load(FIXTURE.read_bytes())
    for asset in env.assets:
        asset._m_target_platform = 13
    images = smooth_images() if astc else authored_images()
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            tree = obj.read_typetree()
            payload = texture_payload(images, astc)
            tree.update(m_Name="ch0001_co0001_head", m_Width=SIZE, m_Height=SIZE, m_TextureFormat=ASTC_6X6 if astc else 4,
                        m_MipCount=LEVELS, m_CompleteImageSize=len(payload))
            tree["image data"] = payload
            if "m_MipMap" in tree:
                tree["m_MipMap"] = True
            obj.save_typetree(tree)
            texture = obj
        elif obj.type.name == "Material":
            tree = obj.read_typetree()
            tree["m_Name"] = "ch0001_co0001_head"
            obj.save_typetree(tree)
            material = obj.path_id
    if attach:
        tree = texture.read_typetree()
        payload = texture_payload(recolour_images(), False)
        tree.update(m_Name="ch0001_co0001_head_c1", m_Width=SIZE, m_Height=SIZE, m_TextureFormat=4, m_MipCount=LEVELS,
                    m_CompleteImageSize=len(payload))
        if "m_MipMap" in tree:
            tree["m_MipMap"] = True
        tree["image data"] = payload
        cpt._make_object(texture.assets_file, texture, ATTACH_ID, tree)
        add_attach_table(env, 840, [{"attachName": "c1", "attachType": 1, "replaceObjects": [
            {"replaceBindName": "ch0001_co0001_head", "replaceObject": pointer(ATTACH_ID)}]}])
    if head:
        add_component(env, 830, "BodyPartManager", {"headMaterial": pointer(material), "attachTable": pointer(840 if attach else 0)},
                      namespace="LLAS.Components.Members")
    return env.file.save(packer="original"), images


def synthetic_payload():
    return blob_layer() + blob_layer(darkest=(255, 210, 207))


def levels_of(raw, name="ch0001_co0001_head"):
    env = UnityPy.load(raw)
    obj = next(o for o in env.objects if o.type.name == "Texture2D" and o.read().m_Name == name)
    texture = obj.read()
    out = [decode._android_image(texture, time.monotonic() + 60).convert("RGBA")]
    out += [decode._android_image(proxy.read(), time.monotonic() + 60).convert("RGBA") for proxy in _original_mips(obj, texture)]
    return texture, out


class BlushSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.payload = synthetic_payload()
        # The synthetic array stands in for the stock one; only its hash differs.
        for patcher in (patch.object(tb, "CHEEK_SHA256", hashlib.sha256(self.payload).hexdigest()),
                        patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root / "library")})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def open(self, raw, name="costume.unity"):
        path = self.root / name
        path.write_bytes(raw)
        prepared = model_viewer.prepare([str(path)], rigged=True, face_context={"enabled": False, "allow_download": False})
        token = secrets.token_hex(16)
        model_edits.register_session(token, [str(path)], prepared["rig"])
        return token, raw

    def cache(self, payload):
        target = textures._cheek_cache_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    def head(self, token):
        catalogue = textures.inspect(token)
        return catalogue, next(row for row in catalogue["textures"] if row["name"] == "ch0001_co0001_head")

    def operation(self, row, image, blush=None, kind=None):
        value = {"texture": copy.deepcopy(row["texture"]), "sourceSha256": row["sourceSha256"], "png": uri(image),
                 "kind": kind or ("blush" if blush else "paint")}
        if blush is not None:
            value["blush"] = blush
        return value

    def export(self, token, *operations):
        state = {"version": 1, "savedSettingsEnabled": True, "edits": [], "textures": list(operations)}
        result = model_edits.export(token, state, self.root / "output")
        return result, Path(result["preview_paths"][0]).read_bytes()

    def test_head_main_texture_is_offered_and_a_missing_array_is_explained(self):
        raw, images = head_fixture()
        token, _ = self.open(raw)
        catalogue, row = self.head(token)
        self.assertEqual(row["blush"], {"role": "head", "material": "ch0001_co0001_head", "matcap": False, "masked": False,
                                        "recolourSuits": False, "platform": "android"})
        self.assertEqual(catalogue["blush"]["cheek"], {"available": False, "source": "", "sourceName": "", "sha256": "",
                                                       "reason": textures.CHEEK_UNAVAILABLE})
        self.assertEqual([level["id"] for level in catalogue["blush"]["levels"]], [name for name, _ in tb.LEVELS])
        with self.assertRaisesRegex(textures.TextureToolError, "cheek_array"):
            textures.cheek(token)
        operation = self.operation(row, images[0], {"layer": 0, "k": 1.65})
        with self.assertRaisesRegex(ValueError, "cheek_array"):
            model_edits.validate_state(token, {"version": 1, "savedSettingsEnabled": True, "edits": [], "textures": [operation]})

    def test_textures_outside_a_head_material_are_not_offered(self):
        raw, images = head_fixture(head=False)
        self.cache(self.payload)
        token, _ = self.open(raw)
        catalogue, row = self.head(token)
        self.assertNotIn("blush", row)
        operation = self.operation(row, images[0], {"layer": 0, "k": 1.0})
        with self.assertRaisesRegex(ValueError, "head material"):
            model_edits.validate_state(token, {"version": 1, "savedSettingsEnabled": True, "edits": [], "textures": [operation]})

    def test_only_a_verified_cached_array_is_used(self):
        raw, _ = head_fixture()
        damaged = bytearray(self.payload)
        damaged[1000] ^= 1
        self.cache(bytes(damaged))
        token, _ = self.open(raw)
        self.assertFalse(self.head(token)[0]["blush"]["cheek"]["available"])
        self.cache(self.payload)
        token, _ = self.open(raw, "second.unity")
        catalogue, _ = self.head(token)
        self.assertEqual(catalogue["blush"]["cheek"]["source"], "cache")
        data = textures.cheek(token)
        self.assertEqual((data["width"], data["height"], data["rowOrder"], data["sha256"]), (256, 512, "unity", tb.CHEEK_SHA256))
        self.assertEqual(__import__("zlib").decompress(base64.b64decode(data["rgbaZlib"])), self.payload)

    def test_export_bakes_every_authored_mip_in_place_and_nothing_else(self):
        raw, images = head_fixture()
        self.cache(self.payload)
        token, _ = self.open(raw)
        _, row = self.head(token)
        for layer in tb.LAYERS:
            result, output = self.export(token, self.operation(row, images[0], {"layer": layer, "k": 1.65}))
            texture, levels = levels_of(output)
            self.assertEqual((texture.m_TextureFormat, texture.m_MipCount), (4, LEVELS))
            cheek = tb.layer_bytes(self.payload, layer)
            counts = []
            for authored, written in zip(images, levels):
                expected, changed, _ = tb.bake_rgba(authored.tobytes(), authored.width, authored.height, cheek, 1.65)
                self.assertEqual(written.tobytes(), expected)
                before, after = authored.tobytes(), written.tobytes()
                self.assertEqual(after[3::4], before[3::4], "alpha is never written")
                self.assertEqual(sum(before[i:i + 4] != after[i:i + 4] for i in range(0, len(before), 4)), changed)
                counts.append(changed)
            self.assertGreater(counts[0], 0)
            self.assertGreater(counts[1], 0, "an authored mip is baked at its own texel centres")
            self.assertEqual(counts[-1], 0)
            summary = result["summary"][0]["textureEdits"][0]
            self.assertEqual(summary["blush"], {"layer": layer, "k": 1.65, "changedTexels": counts, "encoding": "lossless"})
            self.assertEqual((summary["kind"], summary["resultFormat"]), ("blush", "RGBA32"))

    def astc_encoder(self, *, decode_only=False):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.dict(os.environ, {"ASTCENC_BIN": astc_standin.write(folder.name, decode_only=decode_only)})
        patcher.start()
        self.addCleanup(patcher.stop)

    @unittest.skipUnless(astc_standin.available(), "needs astc-encoder-py for the test astcenc")
    def test_astc_bake_reencodes_only_the_blocks_with_changed_texels(self):
        self.astc_encoder()
        raw, _ = head_fixture(astc=True)
        self.cache(self.payload)
        token, _ = self.open(raw)
        _, row = self.head(token)
        self.assertEqual(row["format"], "ASTC_RGBA_6x6")
        texture, before = levels_of(raw)
        original = bytes(texture.get_image_data())
        cheek = tb.layer_bytes(self.payload, 0)
        result, output = self.export(token, self.operation(row, before[0], {"layer": 0, "k": 3.0}))
        written, after = levels_of(output)
        self.assertEqual((written.m_TextureFormat, written.m_MipCount, len(after)), (ASTC_6X6, LEVELS, LEVELS))
        data = bytes(written.get_image_data())
        self.assertEqual(len(data), len(original), "the texture keeps its compressed size")
        summary = result["summary"][0]["textureEdits"][0]
        self.assertEqual((summary["resultFormat"], summary["encodingChanged"], summary["blush"]["encoding"]),
                         ("ASTC_RGBA_6x6", False, "blocks"))
        offset, touched_total = 0, 0
        for level, (authored, level_after) in enumerate(zip(before, after)):
            w, h = authored.size
            columns, rows = -(-w // 6), -(-h // 6)
            baked, changed, _ = tb.bake_rgba(authored.tobytes(), w, h, cheek, 3.0)
            source, result_pixels = authored.tobytes(), level_after.tobytes()
            touched = {(x // 6, (h - 1 - y) // 6) for y in range(h) for x in range(w)
                       if source[(y * w + x) * 4:(y * w + x) * 4 + 3] != baked[(y * w + x) * 4:(y * w + x) * 4 + 3]}
            self.assertEqual(summary["blush"]["changedTexels"][level], changed)
            self.assertEqual(summary["blush"]["reencodedBlocks"][level], len(touched))
            touched_total += len(touched)
            for by in range(rows):
                for bx in range(columns):
                    at = offset + (by * columns + bx) * 16
                    if (bx, by) not in touched:
                        self.assertEqual(data[at:at + 16], original[at:at + 16], (level, bx, by))
            for y in range(h):
                for x in range(w):
                    o = (y * w + x) * 4
                    self.assertEqual(result_pixels[o + 3], source[o + 3], "alpha is never changed")
                    if (x // 6, (h - 1 - y) // 6) not in touched:
                        self.assertEqual(result_pixels[o:o + 4], source[o:o + 4], "texels outside re-encoded blocks keep their value")
                    else:
                        self.assertLessEqual(max(abs(result_pixels[o + c] - baked[o + c]) for c in range(3)), 64)
            offset += columns * rows * 16
        self.assertGreater(touched_total, 0)
        self.assertGreater(summary["blush"]["changedTexels"][0], 0)
        # A darker cheek on average: the re-encoded blocks follow the bake.
        self.assertLess(sum(after[0].tobytes()[1::4]), sum(before[0].tobytes()[1::4]))

    @unittest.skipUnless(astc_standin.available(), "needs astc-encoder-py for the test astcenc")
    def test_exact_pixels_or_a_decoder_only_astcenc_save_lossless_rgba32(self):
        raw, _ = head_fixture(astc=True)
        self.cache(self.payload)
        for decode_only, blush in ((False, {"layer": 1, "k": 2.3, "exact": True}), (True, {"layer": 1, "k": 2.3})):
            with self.subTest(decode_only=decode_only):
                self.astc_encoder(decode_only=decode_only)
                token, _ = self.open(raw, "exact.unity" if not decode_only else "fallback.unity")
                _, row = self.head(token)
                texture, before = levels_of(raw)
                result, output = self.export(token, self.operation(row, before[0], blush))
                written, after = levels_of(output)
                self.assertEqual((written.m_TextureFormat, written.m_MipCount), (4, LEVELS))
                cheek = tb.layer_bytes(self.payload, 1)
                for authored, level in zip(before, after):
                    self.assertEqual(level.tobytes(), tb.bake_rgba(authored.tobytes(), authored.width, authored.height, cheek, 2.3)[0])
                summary = result["summary"][0]["textureEdits"][0]
                self.assertEqual(summary["blush"]["encoding"], "lossless")
                if decode_only:
                    self.assertIn("encoder", summary["blush"]["fallback"])
                    self.assertNotIn("exact", summary["blush"])
                else:
                    self.assertTrue(summary["blush"]["exact"])
                    self.assertEqual(result["recipe"]["state"]["textures"][0]["blush"], {"layer": 1, "k": 2.3, "exact": True})

    def test_recolour_texture_is_offered_and_baked_with_its_head(self):
        raw, _ = head_fixture(attach=True)
        self.cache(self.payload)
        token, _ = self.open(raw)
        catalogue = textures.inspect(token)
        rows = {row["name"]: row for row in catalogue["textures"]}
        self.assertTrue(rows["ch0001_co0001_head"]["blush"]["recolourSuits"])
        self.assertEqual(rows["ch0001_co0001_head_c1"]["blush"], {
            "role": "attach", "material": "ch0001_co0001_head", "attachKey": "c1", "verifiedHead": True, "matcap": False,
            "masked": False, "recolourSuits": False, "platform": "android"})
        recolour = recolour_images()
        _, output = self.export(token, self.operation(rows["ch0001_co0001_head_c1"], recolour[0], {"layer": 0, "k": 1.65}))
        _, levels = levels_of(output, "ch0001_co0001_head_c1")
        self.assertEqual(levels[0].tobytes(), tb.bake_rgba(recolour[0].tobytes(), SIZE, SIZE, tb.layer_bytes(self.payload, 0), 1.65)[0])
        _, head_levels = levels_of(output)
        self.assertEqual(head_levels[0].tobytes(), authored_images()[0].tobytes(), "the costume's own face is untouched")

    def test_an_unreadable_scan_never_removes_the_texture_tools(self):
        raw, _ = head_fixture()
        self.cache(self.payload)
        with patch.object(textures, "_blush_scan", side_effect=RuntimeError("damaged")):
            token, _ = self.open(raw)  # the catalogue is built while the model opens
            catalogue = textures.inspect(token)
        self.assertTrue(catalogue["textures"])
        self.assertFalse(any("blush" in row for row in catalogue["textures"]))

    def test_rebake_replaces_the_previous_bake_and_recipes_keep_original_pixels(self):
        raw, images = head_fixture()
        self.cache(self.payload)
        token, _ = self.open(raw)
        _, row = self.head(token)
        first, _ = self.export(token, self.operation(row, images[0], {"layer": 0, "k": 1.65}))
        recipe = first["recipe"]["state"]["textures"][0]
        self.assertEqual(recipe["blush"], {"layer": 0, "k": 1.65})
        self.assertEqual(recipe["kind"], "blush")
        with Image.open(io.BytesIO(base64.b64decode(recipe["png"].split(",", 1)[1]))) as stored:
            self.assertEqual(stored.convert("RGBA").tobytes(), images[0].tobytes(), "the recipe keeps unbaked pixels")
        rebake = dict(recipe, blush={"layer": 0, "k": 3.0})
        _, output = self.export(token, rebake)
        _, levels = levels_of(output)
        cheek = tb.layer_bytes(self.payload, 0)
        once, _, _ = tb.bake_rgba(images[0].tobytes(), SIZE, SIZE, cheek, 3.0)
        twice, _, _ = tb.bake_rgba(tb.bake_rgba(images[0].tobytes(), SIZE, SIZE, cheek, 1.65)[0], SIZE, SIZE, cheek, 3.0)
        self.assertEqual(levels[0].tobytes(), once)
        self.assertNotEqual(once, twice)

    def test_painted_pixels_and_a_bake_combine_without_regenerating_mips(self):
        raw, images = head_fixture()
        self.cache(self.payload)
        token, _ = self.open(raw)
        _, row = self.head(token)
        painted = images[0].copy()
        painted.putpixel((60, 2), (1, 2, 3, painted.getpixel((60, 2))[3]))   # outside the cheek area
        painted.putpixel((14, 12), (90, 91, 92, painted.getpixel((14, 12))[3]))  # inside it
        _, output = self.export(token, self.operation(row, painted, {"layer": 0, "k": 1.0}, kind="paint"))
        _, levels = levels_of(output)
        cheek = tb.layer_bytes(self.payload, 0)
        self.assertEqual(levels[0].tobytes(), tb.bake_rgba(painted.tobytes(), SIZE, SIZE, cheek, 1.0)[0])
        # Authored mip texels away from both the stroke footprint and the
        # cheek keep their exact authored bytes.
        self.assertEqual(levels[2].getpixel((0, 15)), images[2].getpixel((0, 15)))
        self.assertNotEqual(levels[2].getpixel((15, 0)), images[2].getpixel((15, 0)), "the stroke footprint propagates")

    def test_invalid_blush_operations_publish_nothing(self):
        raw, images = head_fixture()
        self.cache(self.payload)
        token, _ = self.open(raw)
        _, row = self.head(token)
        base = self.operation(row, images[0], {"layer": 0, "k": 1.0})
        for change in ({"blush": {"layer": 2, "k": 1.0}}, {"blush": {"layer": 0, "k": 0}}, {"blush": {"layer": 0, "k": 4.5}},
                       {"blush": {"layer": 0, "k": True}}, {"blush": {"layer": 0, "k": 1.0, "level": "medium"}},
                       {"blush": {"layer": 0, "k": 1.0, "exact": 1}}, {"blush": {"layer": 0, "k": 1.0, "exact": "yes"}},
                       {"blush": {"layer": 0}}, {"blush": None}, {"extra": 1}):
            with self.subTest(change=change):
                operation = dict(base, **change)
                with self.assertRaises(ValueError):
                    model_edits.export(token, {"version": 1, "savedSettingsEnabled": True, "edits": [], "textures": [operation]},
                                       self.root / "rejected")
                self.assertFalse((self.root / "rejected").exists())
        self.assertEqual(textures.checked_blush({"layer": 0, "k": 1.0, "exact": False}), {"layer": 0, "k": 1.0})
        self.assertEqual(textures.checked_blush({"layer": 1, "k": 2.0, "exact": True}), {"layer": 1, "k": 2.0, "exact": True})
        no_blush = {key: value for key, value in base.items() if key != "blush"}
        with self.assertRaises(ValueError):
            model_edits.validate_state(token, {"version": 1, "savedSettingsEnabled": True, "edits": [], "textures": [no_blush]})


class ScanTests(unittest.TestCase):
    """Attach-table and masked-head rules on minimal object graphs."""

    def graph(self):
        files = {}

        class Obj(SimpleNamespace):
            def read_typetree(self):
                return self.tree

        def make(kind, path_id, tree, file="cab-a"):
            assets = files.setdefault(file, SimpleNamespace(name=file, objects={}, externals=[], _m_target_platform=9))
            obj = Obj(type=SimpleNamespace(name=kind), path_id=path_id, tree=tree, assets_file=assets)
            assets.objects[path_id] = obj
            return obj
        p = pointer
        make("MonoScript", 1, {"m_ClassName": "BodyPartManager", "m_Namespace": "LLAS.Components.Members"})
        make("MonoScript", 2, {"m_ClassName": "MemberAttachTable", "m_Namespace": "LLAS.Components.Members"})
        make("Texture2D", 10, {"m_Name": "head"})
        make("Texture2D", 11, {"m_Name": "head_c1"})
        make("Texture2D", 12, {"m_Name": "body_c1"})
        make("Material", 20, {"m_Name": "ch0001_co0001_head", "m_ShaderKeywords": "_RIMLIGHT_ON _MATCAP_ON",
                              "m_SavedProperties": {"m_TexEnvs": [["_MainTex", {"m_Texture": p(10)}]]}})
        make("GameObject", 30, {"m_Name": "Head_All", "m_Component": [{"component": p(31)}]})
        make("Transform", 31, {"m_GameObject": p(30), "m_Children": [p(33)]})
        make("GameObject", 32, {"m_Name": "Head_Face"})
        make("Transform", 33, {"m_GameObject": p(32), "m_Children": [p(35)]})
        make("GameObject", 34, {"m_Name": "mesh_facedots"})
        make("Transform", 35, {"m_GameObject": p(34), "m_Children": []})
        make("MonoBehaviour", 40, {"m_Script": p(1), "headMaterial": p(20), "headAll": p(30), "face": p(0), "head": p(0),
                                   "attachTable": p(41)})
        make("MonoBehaviour", 41, {"m_Script": p(2), "datas": [
            {"attachName": "c1", "attachType": 1, "replaceObjects": [
                {"replaceBindName": "ch0001_co0001_head", "replaceObject": p(11)},
                {"replaceBindName": "ch0001_co0001_body", "replaceObject": p(12)}]},
            {"attachName": "c2", "attachType": 2, "replaceObjects": [{"replaceBindName": "ch0001_co0001_head", "replaceObject": p(12)}]}]})
        objects = [obj for assets in files.values() for obj in assets.objects.values()]
        return [(0, SimpleNamespace(objects=objects), objects, lambda obj: 0)]

    def test_head_texture_recolour_texture_matcap_and_mask_are_identified(self):
        with patch.object(model_viewer, "_as_member_material", return_value=True):
            rules, arrays = textures._blush_scan(self.graph())
        self.assertEqual(arrays, [])
        self.assertEqual(rules[(0, 0, "10")], {"role": "head", "material": "ch0001_co0001_head", "matcap": True, "masked": True,
                                               "recolourSuits": True, "platform": "ios"})
        self.assertEqual(rules[(0, 0, "11")], {"role": "attach", "material": "ch0001_co0001_head", "attachKey": "c1",
                                               "verifiedHead": True, "matcap": True, "masked": True, "recolourSuits": False,
                                               "platform": "ios"})
        self.assertNotIn((0, 0, "12"), rules, "body recolour textures and non-MaterialColor entries are not offered")

    def test_an_unreadable_monobehaviour_only_skips_itself(self):
        import struct

        class Broken(SimpleNamespace):
            def read_typetree(self):
                raise self.error

        groups = self.graph()
        objects = groups[0][2]
        assets = objects[0].assets_file
        for path_id, error in ((50, struct.error("truncated")), (51, EOFError()), (52, RuntimeError("TypeTreeError"))):
            broken = Broken(type=SimpleNamespace(name="MonoBehaviour"), path_id=path_id, error=error, assets_file=assets)
            assets.objects[path_id] = broken
            objects.insert(0, broken)
        with patch.object(model_viewer, "_as_member_material", return_value=True):
            rules, _ = textures._blush_scan(groups)
        self.assertEqual(rules[(0, 0, "10")]["role"], "head")
        self.assertEqual(rules[(0, 0, "11")]["role"], "attach")

    def test_a_non_member_material_is_not_a_head(self):
        with patch.object(model_viewer, "_as_member_material", return_value=False):
            rules, _ = textures._blush_scan(self.graph())
        self.assertEqual(set(rules), {(0, 0, "11")}, "the recolour texture remains bound by its head material name")
        self.assertFalse(rules[(0, 0, "11")]["verifiedHead"])


@unittest.skipUnless(os.environ.get("REAL_MV_SAMPLES"), "set REAL_MV_SAMPLES to a folder with costume bundles")
class RealBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patcher = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root / "library")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.samples = Path(os.environ["REAL_MV_SAMPLES"])

    def open(self, path):
        prepared = model_viewer.prepare([str(path)], rigged=True, face_context={"enabled": False, "allow_download": False})
        token = secrets.token_hex(16)
        model_edits.register_session(token, [str(path)], prepared["rig"])
        return token

    def test_bundle_array_is_verified_cached_and_reused_for_a_head_without_one(self):
        token = self.open(self.samples / "12035-costume.unity")
        catalogue = textures.inspect(token)
        self.assertEqual(catalogue["blush"]["cheek"]["source"], "bundle")
        self.assertTrue(textures._cheek_cache_file().is_file())
        heads = [row for row in catalogue["textures"] if "blush" in row]
        self.assertEqual([row["name"] for row in heads], ["ch0212_co0001_head"])
        # 12029 wears ch9999_co0015, whose head material has no cheek_array.
        token = self.open(self.samples / "12029-costume.unity")
        self.assertEqual(textures.inspect(token)["blush"]["cheek"]["source"], "cache")

    @unittest.skipUnless(astc_standin.available(), "the ASTC head texture needs astc-encoder-py for the test astcenc")
    def test_astc_head_keeps_its_blocks_or_saves_exact_pixels(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"ASTCENC_BIN": astc_standin.write(folder)}):
            path = self.samples / "12035-costume.unity"
            token = self.open(path)
            row = next(row for row in textures.inspect(token)["textures"] if "blush" in row)
            self.assertEqual(row["format"], "ASTC_RGBA_6x6")
            image = textures.data(token, row["texture"])["image"]
            cheek = tb.layer_bytes(textures._read_cached_cheek(), 0)
            original, before = levels_of(path.read_bytes(), row["name"])
            outputs = {}
            for name, blush in (("blocks", {"layer": 0, "k": 1.65}), ("exact", {"layer": 0, "k": 1.65, "exact": True})):
                state = {"version": 1, "savedSettingsEnabled": True, "edits": [], "textures": [
                    {"texture": row["texture"], "sourceSha256": row["sourceSha256"], "png": image, "kind": "blush", "blush": blush}]}
                result = model_edits.export(token, state, self.root / name)
                outputs[name] = (result["summary"][0]["textureEdits"][0],) + levels_of(Path(result["preview_paths"][0]).read_bytes(), row["name"])
        # Exact pixels: the lossless contract, every level equals the rule.
        summary, texture, after = outputs["exact"]
        self.assertEqual((texture.m_TextureFormat, texture.m_MipCount, len(after)), (4, 11, 11))
        counts = []
        for authored, written in zip(before, after):
            expected, changed, _ = tb.bake_rgba(authored.tobytes(), authored.width, authored.height, cheek, 1.65)
            self.assertEqual(written.tobytes(), expected)
            counts.append(changed)
        self.assertGreater(counts[0], 10000)
        self.assertTrue(all(count > 0 for count in counts[:7]) and counts[-1] == 0, counts)
        # Default: ASTC 6x6 kept, only the touched blocks differ, alpha and every other texel unchanged.
        summary, texture, after = outputs["blocks"]
        self.assertEqual((texture.m_TextureFormat, texture.m_MipCount, summary["blush"]["changedTexels"]), (56, 11, counts))
        old, new = bytes(original.get_image_data()), bytes(texture.get_image_data())
        self.assertEqual(len(old), len(new))
        differing = sum(old[i:i + 16] != new[i:i + 16] for i in range(0, len(old), 16))
        self.assertLessEqual(differing, sum(summary["blush"]["reencodedBlocks"]))
        self.assertLess(sum(summary["blush"]["reencodedBlocks"]), 800)
        for authored, written in zip(before, after):
            self.assertEqual(written.tobytes()[3::4], authored.tobytes()[3::4])


@unittest.skipUnless(os.environ.get("REAL_SUIT_BUNDLES"), "set REAL_SUIT_BUNDLES to the suit bundle folder")
class RealAttachTests(unittest.TestCase):
    def test_recolour_suit_head_texture_is_offered_with_its_costume(self):
        folder = Path(os.environ["REAL_SUIT_BUNDLES"])
        paths = [str(folder / "model-727e4c.unity"), str(folder / "dep-member_model-787941.unity")]
        with tempfile.TemporaryDirectory() as library, patch.dict(os.environ, {"SUKUSTA_DIR": library}):
            prepared = model_viewer.prepare(paths, rigged=True, face_context={"enabled": False, "allow_download": False})
            token = secrets.token_hex(16)
            model_edits.register_session(token, paths, prepared["rig"])
            rows = {row["name"]: row.get("blush") for row in textures.inspect(token)["textures"]}
        self.assertEqual(rows["ch0212_co0007_head"]["role"], "head")
        self.assertTrue(rows["ch0212_co0007_head"]["recolourSuits"])
        self.assertEqual(rows["ch0212_co0007_head_c1"]["role"], "attach")
        self.assertTrue(rows["ch0212_co0007_head_c1"]["verifiedHead"])
        self.assertIsNone(rows["ch0212_co0007_body_c1"])


if __name__ == "__main__":
    unittest.main()
