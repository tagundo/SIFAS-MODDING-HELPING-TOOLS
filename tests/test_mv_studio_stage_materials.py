"""Exercise native stage shader inputs and ownership metadata."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from webtools.core import decode, mv_studio_stage_materials as stage


class StageCubemapTests(unittest.TestCase):
    @staticmethod
    def cube(format_id, block_sizes):
        face_bytes = sum(block_sizes)
        payload = b"".join(bytes([1 + 4 * face + mip]) * length
                           for face in range(6) for mip, length in enumerate(block_sizes))
        return SimpleNamespace(m_Width=8, m_Height=8, m_ImageCount=6, m_MipCount=4,
                               m_TextureFormat=format_id, m_TextureDimension=2, m_ColorSpace=1,
                               m_LightmapFormat=0, m_CompleteImageSize=face_bytes,
                               m_StreamData=SimpleNamespace(size=0), get_image_data=Mock(return_value=payload),
                               m_TextureSettings=SimpleNamespace(m_FilterMode=2, m_MipBias=0, m_Aniso=0,
                                                                 m_WrapU=1, m_WrapV=1, m_WrapW=1))

    def test_exact_face_and_mip_order_and_pvrtc_small_levels(self):
        for format_id, name, sizes, extents in ((34, "etc1", [32, 8, 8, 8], [8, 4, 2, 1]),
                                                  (32, "pvrtc4", [32, 32, 32, 32], [8, 8, 8, 8])):
            with self.subTest(format=name):
                recorded = []

                def decode_block(format_name, payload, width, height, deadline):
                    self.assertEqual(format_name, name)
                    level = len(recorded) % 4
                    self.assertEqual(len(payload), sizes[level])
                    self.assertEqual((width, height), (extents[level], extents[level]))
                    self.assertEqual(deadline, 123)
                    recorded.append(payload[0])
                    return Image.new("RGBA", (width, height), (payload[0], 0, 0, 255))

                with patch.object(decode, "_stage_block_image", side_effect=decode_block):
                    raw, width, pixels = stage._cube_pixels(self.cube(format_id, sizes), 1024, 123)
                self.assertEqual((width, pixels), (8, 6 * (64 + 16 + 4 + 1)))
                self.assertEqual(recorded, list(range(1, 25)))
                expected = bytearray()
                for index, value in enumerate(recorded):
                    side = 8 >> (index % 4)
                    expected.extend(bytes([value, 0, 0, 255]) * side ** 2)
                self.assertEqual(raw, expected)

    def test_rejects_invalid_budget_and_incomplete_native_data_before_decode(self):
        raw_cube = self.cube(34, [32, 8, 8, 8])
        with patch.object(decode, "_stage_block_image") as decoder:
            self.assertIsNone(stage._cube_pixels(raw_cube, 400, 123))
            raw_cube.get_image_data.assert_not_called()
            raw_cube.get_image_data.return_value = raw_cube.get_image_data.return_value[:-1]
            self.assertIsNone(stage._cube_pixels(raw_cube, 1024, 123))
            decoder.assert_not_called()



class StageEmissiveOwnershipTests(unittest.TestCase):
    def test_model_binding_uses_only_the_unique_root_receiver(self):
        stage_file, materials_file = object(), object()

        def node(kind, identifier, serialized=stage_file):
            return SimpleNamespace(type=SimpleNamespace(name=kind), path_id=identifier, assets_file=serialized)

        def ref(identifier, file_id=0):
            return {"m_FileID": file_id, "m_PathID": identifier}

        root, child = node("GameObject", 1), node("GameObject", 2)
        model, receiver, child_receiver = (node("MonoBehaviour", value) for value in (10, 11, 12))
        extra_root_receiver = node("MonoBehaviour", 13)
        model_script, receiver_script = (node("MonoScript", value, materials_file) for value in (20, 21))
        material, child_material = (node("Material", value, materials_file) for value in (30, 31))
        objects = {stage._key(obj): obj for obj in (root, child, model, receiver, child_receiver, extra_root_receiver,
                                                    model_script, receiver_script, material, child_material)}
        root_data = {"m_Component": [{"component": ref(10)}, {"component": ref(11)}]}
        model_data = {"m_GameObject": ref(1), "m_Script": ref(20, 1), "emissives": [ref(11), ref(12)]}
        receiver_data = {"m_GameObject": ref(1), "m_Script": ref(21, 1), "materials": [ref(30, 1)]}
        child_data = {**receiver_data, "m_GameObject": ref(2), "materials": [ref(31, 1)]}
        script_fields = ("m_ClassName", "m_Namespace", "m_AssemblyName")
        trees = {stage._key(obj): data for obj, data in (
            (root, root_data), (model, model_data), (receiver, receiver_data), (child_receiver, child_data),
            (extra_root_receiver, receiver_data), (model_script, dict(zip(script_fields, stage._MODEL_SCRIPT))),
            (receiver_script, dict(zip(script_fields, stage._EMISSIVE_SCRIPT))),
        )}
        scene = SimpleNamespace(tree=lambda obj: trees[stage._key(obj)])

        def resolve(owner, pointer):
            if pointer is None:
                return None
            target = owner.assets_file if pointer["m_FileID"] == 0 else materials_file
            return objects.get((id(target), pointer["m_PathID"]))

        with patch.object(stage, "_ref", side_effect=resolve), patch.object(stage, "_object_path", return_value=("Model",)):
            self.assertEqual(stage.emissive_materials(scene, model, model_data), {stage._key(material)})
            self.assertFalse(stage.emissive_materials(scene, model, {**model_data, "emissives": [ref(12)]}))
            root_data["m_Component"].append({"component": ref(13)})
            self.assertFalse(stage.emissive_materials(scene, model, model_data))
