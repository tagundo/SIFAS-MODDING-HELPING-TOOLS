"""Independent pixel, authored-LOD and saved-Unity tests for optional UV-map resizing."""
from copy import deepcopy
import unittest
from unittest.mock import Mock

import numpy as np
from PIL import Image
import UnityPy

import costume_part_transplant as cpt
from graft_game_compat import bake_renderer_for_game
from graft_uv_reuse import prepare_uv_reuse
from test_graft_game_compat import fixture, raw_objects
from test_graft_texture_atlas import image, levels, source, texture_asset
from test_graft_uv_reuse import mesh, RECEIVER, DONOR, linear_sample


def signature(sources):
    """Capture original material, typed texture payloads and every object tree."""
    return [(deepcopy(value.tree), {pid: (deepcopy(obj.tree),
                bytes(obj.read().get_image_data()) if obj.type.name == 'Texture2D' else None)
                for pid, obj in value.objects.items()}) for value in sources]


def chain(size, red):
    return [image((size >> level, size >> level), (red + level, 17, 91, 255))
            for level in range(size.bit_length())]


def native_fixture(main_size, rim_size, main_color, rim_color):
    """Use independent Main/Rim objects so changing one cannot mask alias bugs."""
    environment, renderer, mesh_object, material = fixture(main_color, size=main_size)
    template = next(obj for obj in environment.objects if obj.type.name == 'Texture2D')
    tree = template.read_typetree()
    tree.update(m_Name='independent-rim', m_Width=rim_size, m_Height=rim_size,
                m_TextureFormat=4, m_MipCount=1, m_CompleteImageSize=rim_size * rim_size * 4,
                **{'image data': bytes(rim_color) * rim_size * rim_size})
    tree['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
    rim_id = max(obj.path_id for obj in environment.objects) + 1
    cpt._make_object(material.assets_file, template, rim_id, tree)
    material_tree = material.read_typetree()
    slot = deepcopy(dict(material_tree['m_SavedProperties']['m_TexEnvs'])['_MainTex'])
    slot['m_Texture'] = {'m_FileID': 0, 'm_PathID': rim_id}
    material_tree['m_SavedProperties']['m_TexEnvs'].append(('_RimlightTex', slot))
    material.save_typetree(material_tree)
    environment = UnityPy.load(environment.file.save(packer='original'))
    objects = {obj.path_id: obj for obj in environment.objects}
    return environment, objects[renderer.path_id], objects[mesh_object.path_id], objects[material.path_id]


def two_native_groups(mesh_object, receiver=RECEIVER, donor=DONOR):
    tree = mesh_object.read_typetree()
    count, channels, strides, starts, _ = cpt.stream_layout(tree)
    raw = bytearray(tree['m_VertexData']['m_DataSize'])
    uv = cpt.read_attr(np.frombuffer(raw, np.uint8), cpt.ATTR_UV0, channels, strides, starts, count)
    uv[:6] = np.asarray([*receiver, *donor], dtype=np.float32)
    cpt.write_attr(np.frombuffer(raw, np.uint8), uv, cpt.ATTR_UV0, channels, strides, starts, count)
    tree['m_VertexData']['m_DataSize'] = bytes(raw)
    first = deepcopy(tree['m_SubMeshes'][0]); first.update(firstByte=0, indexCount=3)
    second = deepcopy(first); second['firstByte'] = 6
    tree['m_SubMeshes'] = [first, second]
    tree['m_IndexBuffer'] = np.arange(6, dtype='<u2').tobytes()
    return tree, uv


class TextureUpscalePixelTests(unittest.TestCase):
    def test_default_same_position_copies_nearest_expanded_rgba_without_touching_originals(self):
        target_rim = np.full((16, 16, 4), [9, 19, 29, 39], dtype=np.uint8)
        donor_rim = np.arange(8 * 8 * 4, dtype=np.uint8).reshape(8, 8, 4)
        target = source('receiver', [image((32, 32), 'red')], rim=[Image.fromarray(target_rim)])
        donor = source('donor', [image((32, 32), 'blue')], rim=[Image.fromarray(donor_rim)])
        geometry = mesh([RECEIVER, DONOR])
        originals = signature([target, donor]), deepcopy(geometry)
        result = prepare_uv_reuse([target, donor], geometry, 1)
        self.assertIsNotNone(result)
        self.assertEqual((result.textures['_MainTex'].width, result.textures['_MainTex'].height), (32, 32))
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (16, 16))
        self.assertTrue(all(value.scale == (1., 1.) and value.offset == (0., 0.) for value in result.transforms))
        expected = np.repeat(np.repeat(donor_rim, 2, axis=0), 2, axis=1)
        pixels = levels(result.textures['_RimlightTex'])[0]
        changed = np.any(pixels != target_rim, axis=2)
        self.assertTrue(changed.any())
        np.testing.assert_array_equal(pixels[changed], expected[changed])
        np.testing.assert_array_equal(pixels[5, 10], expected[5, 10])
        np.testing.assert_array_equal(pixels[14, 1], target_rim[14, 1])
        self.assertEqual((signature([target, donor]), geometry), originals)
        self.assertEqual(result.textures['_RimlightTex'].tree['m_TextureSettings'], target.objects[3].tree['m_TextureSettings'])
        self.assertEqual(result.textures['_RimlightTex'].tree['m_ColorSpace'], target.objects[3].tree['m_ColorSpace'])
        self.assertEqual(result.textures['_RimlightTex'].tree['m_MipCount'], 1)
        self.assertEqual(len(result.textures['_RimlightTex'].tree['image data']), 16 * 16 * 4)

    def test_explicit_off_retains_strict_resolution_failure_and_unchanged_inputs(self):
        target = source('receiver', [image((32, 32), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((8, 8), 'black')])
        originals = signature([target, donor])
        reasons = []
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1,
                                 upscale_textures_for_uv_reuse=False, diagnostics=reasons)
        self.assertIsNone(result)
        self.assertTrue(any('dimensions' in value.lower() for value in reasons))
        self.assertEqual(signature([target, donor]), originals)

    def test_same_main_with_smaller_receiver_rim_enlarges_receiver_instead_of_shrinking_donor(self):
        target_rim = np.arange(8 * 8 * 4, dtype=np.uint8).reshape(8, 8, 4)
        target = source('receiver', [image((32, 32), 'red')], rim=[Image.fromarray(target_rim)])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((16, 16), (201, 13, 82, 255))])
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1)
        self.assertIsNotNone(result)
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (16, 16))
        pixels = levels(result.textures['_RimlightTex'])[0]
        expected_receiver = np.repeat(np.repeat(target_rim, 2, axis=0), 2, axis=1)
        np.testing.assert_array_equal(pixels[14, 1], expected_receiver[14, 1])
        np.testing.assert_array_equal(pixels[5, 10], [201, 13, 82, 255])
        self.assertEqual(result.textures['_MainTex'].width, 32)

    def test_equal_rim_sizes_different_main_sizes_enlarge_only_the_smaller_main(self):
        donor_main = np.arange(32 * 32 * 4, dtype=np.uint8).reshape(32, 32, 4)
        target = source('receiver', [image((64, 64), 'red')], rim=[image((16, 16), (9, 39, 69, 255))])
        donor = source('donor', [Image.fromarray(donor_main)], rim=[image((16, 16), (201, 13, 82, 255))])
        geometry = mesh([RECEIVER, DONOR])
        originals = signature([target, donor]), deepcopy(geometry)
        result = prepare_uv_reuse([target, donor], geometry, 1)
        self.assertIsNotNone(result)
        self.assertEqual((result.textures['_MainTex'].width, result.textures['_MainTex'].height), (64, 64))
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (16, 16))
        self.assertTrue(all(value.scale == (1., 1.) and value.offset == (0., 0.) for value in result.transforms))
        expected = np.repeat(np.repeat(donor_main, 2, axis=0), 2, axis=1)
        np.testing.assert_array_equal(levels(result.textures['_MainTex'])[0][23, 40], expected[23, 40])
        np.testing.assert_array_equal(levels(result.textures['_RimlightTex'])[0][5, 10], [201, 13, 82, 255])
        self.assertEqual((signature([target, donor]), geometry), originals)

    def test_main_and_rim_are_upscaled_independently_then_occupied_uvs_can_relocate(self):
        target = source('receiver', [image((64, 64), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((4, 4), (200, 80, 40, 255))])
        self.assertIsNone(prepare_uv_reuse([target, donor], mesh([RECEIVER, RECEIVER]), 1))
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, RECEIVER]), 1, relocate_empty_uv=True)
        self.assertIsNotNone(result)
        self.assertEqual((result.textures['_MainTex'].width, result.textures['_MainTex'].height), (64, 64))
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (16, 16))
        self.assertEqual(result.transforms[1].scale, (1., 1.))
        self.assertNotEqual(result.transforms[1].offset, (0., 0.))
        pixels = levels(result.textures['_RimlightTex'])[0]
        moved = result.transforms[1].remap_uv([[.1, .1]])[0]
        np.testing.assert_array_equal(pixels[15 - int(moved[1] * 16), int(moved[0] * 16)], [200, 80, 40, 255])

    def test_rectangular_maps_without_mips_expand_each_axis_without_padding(self):
        target = source('receiver', [image((64, 32), 'red')], rim=[image((16, 8), 'white')])
        donor_main = np.arange(64 * 32 * 4, dtype=np.uint8).reshape(64, 32, 4)
        donor_rim = np.arange(16 * 8 * 4, dtype=np.uint8).reshape(16, 8, 4)
        donor = source('donor', [Image.fromarray(donor_main)], rim=[Image.fromarray(donor_rim)])
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1)
        self.assertIsNotNone(result)
        self.assertEqual((result.textures['_MainTex'].width, result.textures['_MainTex'].height), (64, 64))
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (16, 16))
        np.testing.assert_array_equal(levels(result.textures['_MainTex'])[0][23, 40], np.repeat(donor_main, 2, axis=1)[23, 40])
        np.testing.assert_array_equal(levels(result.textures['_RimlightTex'])[0][5, 10], np.repeat(donor_rim, 2, axis=1)[5, 10])
        self.assertEqual(len(result.textures['_MainTex'].tree['image data']), 64 * 64 * 4)

    def test_authored_mip_chain_is_shifted_after_twofold_upscale(self):
        receiver_rim = chain(16, 20)
        donor_rim = chain(8, 120)
        target = source('receiver', chain(32, 1), rim=receiver_rim)
        donor = source('donor', chain(32, 60), rim=donor_rim)
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1)
        self.assertIsNotNone(result)
        output = levels(result.textures['_RimlightTex'])
        self.assertEqual(len(output), 5)
        for level, pixels in enumerate(output):
            source_level = max(0, level - 1)
            colors = {tuple(value) for value in pixels.reshape(-1, 4)}
            self.assertIn((120 + source_level, 17, 91, 255), colors)
            self.assertTrue(colors <= {(20 + level, 17, 91, 255), (120 + source_level, 17, 91, 255)})
        self.assertIn((120, 17, 91, 255), {tuple(value) for value in output[1].reshape(-1, 4)})
        np.testing.assert_array_equal(output[-1][0, 0], [123, 17, 91, 255])

    def test_main_authored_mips_are_shifted_independently_of_unchanged_rim_mips(self):
        target = source('receiver', chain(64, 20), rim=chain(16, 60))
        donor = source('donor', chain(32, 120), rim=chain(16, 160))
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1)
        self.assertIsNotNone(result)
        main = levels(result.textures['_MainTex'])
        rim = levels(result.textures['_RimlightTex'])
        self.assertEqual(len(main), 7)
        self.assertEqual(len(rim), 5)
        for level, pixels in enumerate(main):
            source_level = max(0, level - 1)
            colors = {tuple(value) for value in pixels.reshape(-1, 4)}
            self.assertIn((120 + source_level, 17, 91, 255), colors)
            self.assertTrue(colors <= {(20 + level, 17, 91, 255), (120 + source_level, 17, 91, 255)})
        for level, pixels in enumerate(rim):
            colors = {tuple(value) for value in pixels.reshape(-1, 4)}
            self.assertIn((160 + level, 17, 91, 255), colors)
            self.assertTrue(colors <= {(60 + level, 17, 91, 255), (160 + level, 17, 91, 255)})

    def test_identical_normalized_maps_still_return_the_enlarged_receiver_texture(self):
        target = source('receiver', [image((32, 32), 'red')], rim=[image((8, 8), 'white')])
        donor = source('donor', [image((32, 32), 'red')], rim=[image((16, 16), 'white')])
        original = signature([target, donor])
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1)
        self.assertIsNotNone(result)
        self.assertFalse(result.identity)
        self.assertEqual(set(result.textures), {'_RimlightTex'})
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (16, 16))
        np.testing.assert_array_equal(levels(result.textures['_RimlightTex'])[0], np.full((16, 16, 4), 255, dtype=np.uint8))
        self.assertEqual(signature([target, donor]), original)

    def test_upscale_does_not_override_occupied_uvs(self):
        target = source('receiver', [image((32, 32), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((8, 8), 'black')])
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], mesh([DONOR, DONOR]), 1, diagnostics=reasons))
        self.assertTrue(any('already used' in value for value in reasons))

    def test_upscale_does_not_relax_sampler_color_space_or_normal_driven_matcap_checks(self):
        for mismatch in ('sampler', 'color_space', 'normal_matcap'):
            with self.subTest(mismatch=mismatch):
                target = source('receiver', [image((32, 32), 'red')], rim=[image((16, 16), 'white')])
                donor = source('donor', [image((32, 32), 'blue')], rim=[image((8, 8), 'black')])
                if mismatch == 'sampler':
                    donor.objects[3] = texture_asset(3, [image((8, 8), 'black')], filter_mode=0)
                elif mismatch == 'color_space':
                    donor.objects[3] = texture_asset(3, [image((8, 8), 'black')], color_space=0)
                else:
                    for value, color in ((target, 'white'), (donor, 'black')):
                        value.tree['m_ShaderKeywords'] = '_MATCAP_ON'
                        value.objects[4] = texture_asset(4, [image((4, 4), color)])
                        value.objects[5] = texture_asset(5, [image((16, 16), 'white')])
                        value.tree['m_SavedProperties']['m_TexEnvs'].extend([
                            ('_MatcapTex', {'m_Texture': {'m_FileID': 0, 'm_PathID': 4}}),
                            ('_MatcapMaskTex', {'m_Texture': {'m_FileID': 0, 'm_PathID': 5}})])
                self.assertIsNone(prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1))

    def test_uv_driven_matcap_mask_is_upscaled_but_normal_matcap_is_left_original(self):
        target = source('receiver', [image((32, 32), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((8, 8), 'black')])
        for value, size, mask_color in ((target, 16, (11, 21, 31, 255)), (donor, 8, (110, 120, 130, 255))):
            value.tree['m_ShaderKeywords'] = '_MATCAP_ON'
            value.objects[4] = texture_asset(4, [image((4, 4), 'white')])
            value.objects[5] = texture_asset(5, [image((size, size), mask_color)])
            value.tree['m_SavedProperties']['m_TexEnvs'].extend([
                ('_MatcapTex', {'m_Texture': {'m_FileID': 0, 'm_PathID': 4}}),
                ('_MatcapMaskTex', {'m_Texture': {'m_FileID': 0, 'm_PathID': 5}})])
        originals = signature([target, donor])
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1)
        self.assertIsNotNone(result)
        self.assertNotIn('_MatcapTex', result.textures)
        self.assertEqual((result.textures['_MatcapMaskTex'].width, result.textures['_MatcapMaskTex'].height), (16, 16))
        np.testing.assert_array_equal(levels(result.textures['_MatcapMaskTex'])[0][5, 10], [110, 120, 130, 255])
        np.testing.assert_array_equal(levels(result.textures['_MatcapMaskTex'])[0][14, 1], [11, 21, 31, 255])
        self.assertEqual(signature([target, donor]), originals)

    def test_low_memory_budget_and_partial_authored_mips_decline_before_decode(self):
        for invalid in ('budget', 'partial_mips'):
            with self.subTest(invalid=invalid):
                target = source('receiver', [image((32, 32), 'red')], rim=chain(16, 20))
                donor_rim = chain(8, 120)
                if invalid == 'partial_mips':
                    donor_rim = donor_rim[:2]
                donor = source('donor', [image((32, 32), 'blue')], rim=donor_rim)
                decoder = Mock(side_effect=AssertionError('unsupported normalization must fail before image decoding'))
                reasons = []
                options = {'max_total_bytes': 1000} if invalid == 'budget' else {}
                result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1,
                                         image_decoder=decoder, diagnostics=reasons, **options)
                self.assertIsNone(result)
                self.assertTrue(reasons)
                decoder.assert_not_called()

    def test_normalized_pixel_budget_and_nonuniform_authored_mips_decline_before_decode(self):
        for invalid in ('pixels', 'nonuniform_mips'):
            with self.subTest(invalid=invalid):
                mip_count = 1 if invalid == 'pixels' else 7
                target = source('receiver', [image((max(1, 64 >> level), max(1, 32 >> level)), 'red') for level in range(mip_count)])
                donor = source('donor', [image((max(1, 32 >> level), max(1, 64 >> level)), 'blue') for level in range(mip_count)])
                decoder = Mock(side_effect=AssertionError('unsupported normalization must fail before image decoding'))
                reasons = []
                options = {'max_pixels': 2048} if invalid == 'pixels' else {}
                result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1,
                                         image_decoder=decoder, diagnostics=reasons, **options)
                self.assertIsNone(result)
                self.assertTrue(reasons)
                decoder.assert_not_called()


class TextureUpscaleUnitySaveTests(unittest.TestCase):
    def test_normalized_identical_textures_commit_larger_receiver_rim_after_save(self):
        target, renderer, mesh_object, material = native_fixture(32, 8, (10, 20, 30, 255), (7, 27, 47, 255))
        donor, _, _, donor_material = native_fixture(32, 16, (10, 20, 30, 255), (7, 27, 47, 255))
        tree, _ = two_native_groups(mesh_object)
        original_slots = dict(material.read_typetree()['m_SavedProperties']['m_TexEnvs'])
        stats = bake_renderer_for_game(target, renderer, mesh_object, mesh_tree=tree,
                                       additional_sources=[(donor, donor_material.path_id)])
        self.assertEqual(stats['texture_mode'], 'reuse_empty_uv')
        self.assertFalse(stats['atlas_identity'])
        saved = UnityPy.load(target.file.save(packer='original'))
        objects = {obj.path_id: obj for obj in saved.objects}
        slots = dict(objects[material.path_id].read_typetree()['m_SavedProperties']['m_TexEnvs'])
        self.assertEqual(slots['_MainTex']['m_Texture'], original_slots['_MainTex']['m_Texture'])
        rim = objects[slots['_RimlightTex']['m_Texture']['m_PathID']].read().image.convert('RGBA')
        self.assertEqual(rim.size, (16, 16))
        np.testing.assert_array_equal(np.asarray(rim), np.full((16, 16, 4), [7, 27, 47, 255], dtype=np.uint8))
        self.assertEqual(sum(obj.type.name == 'Material' for obj in saved.objects), 1)
        self.assertEqual(len(objects[mesh_object.path_id].read_typetree()['m_SubMeshes']), 1)

    def test_default_and_disabled_paths_save_one_original_material_and_submesh(self):
        for enabled, expected_mode in ((True, 'reuse_empty_uv'), (False, 'atlas')):
            with self.subTest(enabled=enabled):
                target, renderer, mesh_object, material = native_fixture(32, 16, (10, 20, 30, 255), (7, 27, 47, 255))
                donor, _, _, donor_material = native_fixture(32, 8, (180, 150, 120, 255), (190, 13, 83, 255))
                donor_before = raw_objects(donor)
                old_texture_bytes = {obj.path_id: obj.get_raw_data() for obj in target.objects if obj.type.name == 'Texture2D'}
                material_before = material.read_typetree()
                tree, uv = two_native_groups(mesh_object)
                options = {} if enabled else {'upscale_textures_for_uv_reuse': False}
                stats = bake_renderer_for_game(target, renderer, mesh_object, mesh_tree=tree,
                    additional_sources=[(donor, donor_material.path_id)], **options)
                self.assertEqual(stats['texture_mode'], expected_mode)
                saved = UnityPy.load(target.file.save(packer='original'))
                objects = {obj.path_id: obj for obj in saved.objects}
                saved_material = objects[material.path_id].read_typetree()
                self.assertEqual(sum(obj.type.name == 'Material' for obj in saved.objects), 1)
                self.assertEqual(saved_material['m_Shader'], material_before['m_Shader'])
                self.assertEqual(saved_material['m_SavedProperties']['m_Floats'], material_before['m_SavedProperties']['m_Floats'])
                self.assertEqual(saved_material['m_SavedProperties']['m_Colors'], material_before['m_SavedProperties']['m_Colors'])
                self.assertEqual(len(objects[renderer.path_id].read_typetree()['m_Materials']), 1)
                saved_mesh = objects[mesh_object.path_id].read_typetree()
                self.assertEqual(len(saved_mesh['m_SubMeshes']), 1)
                self.assertEqual(raw_objects(donor), donor_before)
                for pid, original in old_texture_bytes.items():
                    self.assertEqual(objects[pid].get_raw_data(), original)
                if enabled:
                    self.assertEqual(stats['atlas_dimensions'], {'_MainTex': [32, 32], '_RimlightTex': [16, 16]})
                    count, channels, strides, starts, _ = cpt.stream_layout(saved_mesh)
                    saved_uv = cpt.read_attr(np.frombuffer(saved_mesh['m_VertexData']['m_DataSize'], np.uint8),
                                             cpt.ATTR_UV0, channels, strides, starts, count)
                    np.testing.assert_allclose(saved_uv, uv)
                    slots = dict(saved_material['m_SavedProperties']['m_TexEnvs'])
                    rim = objects[slots['_RimlightTex']['m_Texture']['m_PathID']].read().image.convert('RGBA')
                    self.assertEqual(rim.size, (16, 16))
                    pixels = np.asarray(rim)
                    np.testing.assert_array_equal(pixels[5, 10], [190, 13, 83, 255])
                    np.testing.assert_array_equal(pixels[14, 1], [7, 27, 47, 255])

    def test_geometry_rejection_after_rim_preparation_does_not_mutate_unity_objects(self):
        target, renderer, mesh_object, _ = native_fixture(32, 16, (10, 20, 30, 255), (7, 27, 47, 255))
        donor, _, _, donor_material = native_fixture(32, 8, (180, 150, 120, 255), (190, 13, 83, 255))
        tree, _ = two_native_groups(mesh_object)
        original_tree, target_before, donor_before = deepcopy(tree), raw_objects(target), raw_objects(donor)
        with self.assertRaisesRegex(ValueError, 'vertex limit'):
            bake_renderer_for_game(target, renderer, mesh_object, mesh_tree=tree, max_vertices=1,
                                   additional_sources=[(donor, donor_material.path_id)])
        self.assertEqual(tree, original_tree)
        self.assertEqual(raw_objects(target), target_before)
        self.assertEqual(raw_objects(donor), donor_before)


class ExplicitUVPlacementPixelTests(unittest.TestCase):
    def test_same_position_normalizes_main_slots_without_enlarging_equal_rim_slots(self):
        target = source('receiver', [image((64, 64), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((16, 16), 'black')])
        geometry = mesh([RECEIVER, DONOR])
        original = signature([target, donor]), deepcopy(geometry)
        result = prepare_uv_reuse([target, donor], geometry, 1, uv_placement='same_position',
                                 upscale_textures_for_uv_reuse=False)
        self.assertIsNotNone(result)
        self.assertEqual((result.textures['_MainTex'].width, result.textures['_MainTex'].height), (64, 64))
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (16, 16))
        self.assertTrue(all(value.scale == (1., 1.) and value.offset == (0., 0.) for value in result.transforms))
        np.testing.assert_array_equal(levels(result.textures['_MainTex'])[0][23, 40], [0, 0, 255, 255])
        self.assertEqual((signature([target, donor]), geometry), original)

    def test_same_position_never_moves_occupied_uvs_even_when_legacy_relocation_is_on(self):
        target = source('receiver', [image((64, 64), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((16, 16), 'black')])
        geometry = mesh([RECEIVER, RECEIVER])
        reasons = []
        self.assertIsNone(prepare_uv_reuse([target, donor], geometry, 1, uv_placement='same_position',
                                         relocate_empty_uv=True, diagnostics=reasons))
        self.assertTrue(any('already used' in value for value in reasons))

    def test_move_preserves_main_native_scale_and_equalizes_relative_rim_density(self):
        donor_main = np.arange(32 * 32 * 4, dtype=np.uint8).reshape(32, 32, 4)
        donor_rim = np.arange(16 * 16 * 4, dtype=np.uint8).reshape(16, 16, 4)
        target = source('receiver', [image((64, 64), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [Image.fromarray(donor_main)], rim=[Image.fromarray(donor_rim)])
        geometry = mesh([RECEIVER, RECEIVER])
        original = signature([target, donor]), deepcopy(geometry)
        result = prepare_uv_reuse([target, donor], geometry, 1, uv_placement='move_to_empty')
        self.assertIsNotNone(result)
        self.assertEqual((result.textures['_MainTex'].width, result.textures['_MainTex'].height), (64, 64))
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (32, 32))
        self.assertEqual(result.transforms[0].scale, (1., 1.))
        self.assertEqual(result.transforms[0].offset, (0., 0.))
        self.assertEqual(result.transforms[1].scale, (.5, .5))
        for uv in ((.1, .1), (.15, .1), (.1, .15)):
            moved = result.transforms[1].remap_uv([uv])[0]
            np.testing.assert_allclose(linear_sample(levels(result.textures['_MainTex'])[0], moved),
                                       linear_sample(donor_main, uv), atol=1e-10)
            np.testing.assert_allclose(linear_sample(levels(result.textures['_RimlightTex'])[0], moved),
                                       linear_sample(donor_rim, uv), atol=1e-10)
        self.assertEqual((signature([target, donor]), geometry), original)

    def test_move_of_rectangular_and_square_main_maps_keeps_both_native_axes(self):
        target = source('receiver', [image((32, 16), 'red')], rim=[image((16, 8), 'white')])
        main = np.arange(16 * 16 * 4, dtype=np.uint8).reshape(16, 16, 4)
        rim = np.arange(8 * 8 * 4, dtype=np.uint8).reshape(8, 8, 4)
        donor = source('donor', [Image.fromarray(main)], rim=[Image.fromarray(rim)])
        triangle = ((.1, .1), (.5, .1), (.1, .5))
        geometry = mesh([triangle, triangle])
        original = signature([target, donor]), deepcopy(geometry)
        result = prepare_uv_reuse([target, donor], geometry, 1, uv_placement='move_to_empty')
        self.assertIsNotNone(result)
        self.assertEqual(result.transforms[1].scale, (.5, 1.))
        self.assertEqual((result.textures['_MainTex'].width, result.textures['_MainTex'].height), (32, 16))
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (16, 8))
        for slot, original_image in (('_MainTex', main), ('_RimlightTex', rim)):
            output = levels(result.textures[slot])[0]
            for uv in ((.2, .2), (.15, .25), (.3, .15)):
                moved = result.transforms[1].remap_uv([uv])[0]
                np.testing.assert_allclose(linear_sample(output, moved), linear_sample(original_image, uv), atol=1e-10)
        self.assertEqual((signature([target, donor]), geometry), original)

    def test_move_strategy_places_directly_instead_of_returning_available_original_uvs(self):
        target = source('receiver', [image((32, 32), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((16, 16), 'black')])
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1, uv_placement='move_to_empty')
        self.assertIsNotNone(result)
        self.assertEqual(result.transforms[1].scale, (1., 1.))
        self.assertNotEqual(result.transforms[1].offset, (0., 0.))

    def test_move_keeps_native_main_mips_and_shifted_receiver_auxiliary_mips_independent(self):
        target = source('receiver', chain(64, 20), rim=chain(16, 60))
        donor = source('donor', chain(32, 120), rim=chain(16, 160))
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, RECEIVER]), 1, uv_placement='move_to_empty')
        self.assertIsNotNone(result)
        self.assertEqual(result.transforms[1].scale, (.5, .5))
        main = levels(result.textures['_MainTex'])
        rim = levels(result.textures['_RimlightTex'])
        self.assertEqual(len(main), 7)
        self.assertEqual(len(rim), 6)
        for level, pixels in enumerate(main):
            colors = {tuple(value) for value in pixels.reshape(-1, 4)}
            donor_color = (120 + min(level, 5), 17, 91, 255)
            self.assertIn(donor_color, colors)
            self.assertTrue(colors <= {(20 + level, 17, 91, 255), donor_color})
        for level, pixels in enumerate(rim):
            colors = {tuple(value) for value in pixels.reshape(-1, 4)}
            donor_color = (160 + min(level, 4), 17, 91, 255)
            receiver_color = (60 + max(0, level - 1), 17, 91, 255)
            self.assertIn(donor_color, colors)
            self.assertTrue(colors <= {receiver_color, donor_color})

    def test_move_can_enlarge_only_the_donor_auxiliary_map(self):
        target = source('receiver', [image((64, 64), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((4, 4), 'black')])
        result = prepare_uv_reuse([target, donor], mesh([RECEIVER, RECEIVER]), 1,
                                 uv_placement='move_to_empty')
        self.assertIsNotNone(result)
        self.assertEqual((result.textures['_MainTex'].width, result.textures['_MainTex'].height), (64, 64))
        self.assertEqual((result.textures['_RimlightTex'].width, result.textures['_RimlightTex'].height), (16, 16))
        self.assertEqual(result.transforms[1].scale, (.5, .5))
        output = levels(result.textures['_RimlightTex'])[0]
        moved = result.transforms[1].remap_uv([[.1, .1]])[0]
        np.testing.assert_array_equal(output[15 - int(moved[1] * 16), int(moved[0] * 16)], [0, 0, 0, 255])

    def test_atlas_strategy_does_not_decode_or_mutate_sources(self):
        target = source('receiver', [image((64, 64), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((16, 16), 'black')])
        geometry = mesh([RECEIVER, DONOR])
        original = signature([target, donor]), deepcopy(geometry)
        decoder = Mock(side_effect=AssertionError('atlas strategy must bypass UV reuse'))
        self.assertIsNone(prepare_uv_reuse([target, donor], geometry, 1, uv_placement='atlas', image_decoder=decoder))
        decoder.assert_not_called()
        self.assertEqual((signature([target, donor]), geometry), original)

    def test_placement_enum_rejects_unsupported_values_before_decoding(self):
        target = source('receiver', [image((32, 32), 'red')], rim=[image((16, 16), 'white')])
        donor = source('donor', [image((32, 32), 'blue')], rim=[image((8, 8), 'black')])
        geometry = mesh([RECEIVER, DONOR])
        original = signature([target, donor]), deepcopy(geometry)
        for invalid in ('', 'SAME_POSITION', 'same position', 'relocate', 0, 1, False, True, [], {}):
            with self.subTest(invalid=invalid):
                decoder = Mock(side_effect=AssertionError('invalid strategy must fail before image decoding'))
                with self.assertRaisesRegex(ValueError, 'UV|placement|strategy'):
                    prepare_uv_reuse([target, donor], geometry, 1, uv_placement=invalid, image_decoder=decoder)
                decoder.assert_not_called()
                self.assertEqual((signature([target, donor]), geometry), original)


class ExplicitUVPlacementUnitySaveTests(unittest.TestCase):
    def test_same_move_and_atlas_saved_bundles_keep_original_single_material_contract(self):
        for strategy, expected_mode, main_size, rim_size, donor_scale in (
                ('same_position', 'reuse_empty_uv', (64, 64), (16, 16), (1., 1.)),
                ('move_to_empty', 'relocate_empty_uv', (64, 64), (32, 32), (.5, .5)),
                ('atlas', 'atlas', None, None, None)):
            with self.subTest(strategy=strategy):
                target, renderer, mesh_object, material = native_fixture(64, 16, (10, 20, 30, 255), (7, 27, 47, 255))
                donor, _, _, donor_material = native_fixture(32, 16, (180, 150, 120, 255), (190, 13, 83, 255))
                donor_before = raw_objects(donor)
                old_texture_bytes = {obj.path_id: obj.get_raw_data() for obj in target.objects if obj.type.name == 'Texture2D'}
                material_before = material.read_typetree()
                tree, uv = two_native_groups(mesh_object, donor=RECEIVER if strategy == 'move_to_empty' else DONOR)
                stats = bake_renderer_for_game(target, renderer, mesh_object, mesh_tree=tree,
                    additional_sources=[(donor, donor_material.path_id)], uv_placement=strategy)
                self.assertEqual(stats['texture_mode'], expected_mode)
                saved = UnityPy.load(target.file.save(packer='original'))
                objects = {obj.path_id: obj for obj in saved.objects}
                saved_material = objects[material.path_id].read_typetree()
                self.assertEqual(sum(obj.type.name == 'Material' for obj in saved.objects), 1)
                self.assertEqual(saved_material['m_Shader'], material_before['m_Shader'])
                self.assertEqual(saved_material['m_SavedProperties']['m_Floats'], material_before['m_SavedProperties']['m_Floats'])
                self.assertEqual(saved_material['m_SavedProperties']['m_Colors'], material_before['m_SavedProperties']['m_Colors'])
                self.assertEqual(len(objects[renderer.path_id].read_typetree()['m_Materials']), 1)
                saved_mesh = objects[mesh_object.path_id].read_typetree()
                self.assertEqual(len(saved_mesh['m_SubMeshes']), 1)
                self.assertEqual(raw_objects(donor), donor_before)
                for pid, original in old_texture_bytes.items():
                    self.assertEqual(objects[pid].get_raw_data(), original)
                if main_size is not None:
                    count, channels, strides, starts, _ = cpt.stream_layout(saved_mesh)
                    saved_uv = cpt.read_attr(np.frombuffer(saved_mesh['m_VertexData']['m_DataSize'], np.uint8),
                                             cpt.ATTR_UV0, channels, strides, starts, count)
                    np.testing.assert_allclose(saved_uv[:3], uv[:3])
                    np.testing.assert_allclose(saved_uv[4] - saved_uv[3], (uv[4] - uv[3]) * donor_scale, atol=1e-7)
                    np.testing.assert_allclose(saved_uv[5] - saved_uv[3], (uv[5] - uv[3]) * donor_scale, atol=1e-7)
                    slots = dict(saved_material['m_SavedProperties']['m_TexEnvs'])
                    for slot, size, donor_color, target_color in (
                            ('_MainTex', main_size, [180, 150, 120, 255], [10, 20, 30, 255]),
                            ('_RimlightTex', rim_size, [190, 13, 83, 255], [7, 27, 47, 255])):
                        texture = objects[slots[slot]['m_Texture']['m_PathID']].read().image.convert('RGBA')
                        self.assertEqual(texture.size, size)
                        pixels = np.asarray(texture)
                        sample = lambda coord: pixels[size[1] - 1 - int(coord[1] * size[1]), int(coord[0] * size[0])]
                        np.testing.assert_array_equal(sample(saved_uv[:3].mean(axis=0)), target_color)
                        np.testing.assert_array_equal(sample(saved_uv[3:6].mean(axis=0)), donor_color)

    def test_strategy_failures_report_atlas_fallback_without_extra_materials(self):
        for strategy in ('same_position', 'move_to_empty'):
            with self.subTest(strategy=strategy):
                target, renderer, mesh_object, material = native_fixture(32, 16, (10, 20, 30, 255), (7, 27, 47, 255))
                donor, _, _, donor_material = native_fixture(32, 8, (180, 150, 120, 255), (190, 13, 83, 255))
                tree = mesh_object.read_typetree()
                count, channels, strides, starts, _ = cpt.stream_layout(tree)
                raw = bytearray(tree['m_VertexData']['m_DataSize'])
                uv = cpt.read_attr(np.frombuffer(raw, np.uint8), cpt.ATTR_UV0, channels, strides, starts, count)
                uv[:9] = np.asarray([(0, 0), (1, 0), (0, 1), (1, 0), (1, 1), (0, 1), *RECEIVER], dtype=np.float32)
                cpt.write_attr(np.frombuffer(raw, np.uint8), uv, cpt.ATTR_UV0, channels, strides, starts, count)
                tree['m_VertexData']['m_DataSize'] = bytes(raw)
                first = deepcopy(tree['m_SubMeshes'][0]); first.update(firstByte=0, indexCount=6)
                second = deepcopy(first); second.update(firstByte=12, indexCount=3)
                tree['m_SubMeshes'] = [first, second]
                tree['m_IndexBuffer'] = np.arange(9, dtype='<u2').tobytes()
                stats = bake_renderer_for_game(target, renderer, mesh_object, mesh_tree=tree,
                    additional_sources=[(donor, donor_material.path_id)], uv_placement=strategy)
                self.assertEqual(stats['texture_mode'], 'atlas')
                self.assertTrue(stats['diagnostics'])
                reason = 'already used' if strategy == 'same_position' else 'no common free'
                self.assertTrue(any(reason in value for value in stats['diagnostics']), stats['diagnostics'])
                saved = UnityPy.load(target.file.save(packer='original'))
                objects = {obj.path_id: obj for obj in saved.objects}
                self.assertEqual(sum(obj.type.name == 'Material' for obj in saved.objects), 1)
                self.assertEqual(len(objects[renderer.path_id].read_typetree()['m_Materials']), 1)
                self.assertEqual(len(objects[mesh_object.path_id].read_typetree()['m_SubMeshes']), 1)

    def test_invalid_strategy_is_rejected_without_mutating_unity_objects(self):
        target, renderer, mesh_object, _ = native_fixture(32, 16, (10, 20, 30, 255), (7, 27, 47, 255))
        donor, _, _, donor_material = native_fixture(32, 8, (180, 150, 120, 255), (190, 13, 83, 255))
        tree, _ = two_native_groups(mesh_object)
        original_tree, target_before, donor_before = deepcopy(tree), raw_objects(target), raw_objects(donor)
        for invalid in ('', 'same position', 1, True, [], {}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'UV|placement|strategy'):
                bake_renderer_for_game(target, renderer, mesh_object, mesh_tree=tree,
                    additional_sources=[(donor, donor_material.path_id)], uv_placement=invalid)
            self.assertEqual(tree, original_tree)
            self.assertEqual(raw_objects(target), target_before)
            self.assertEqual(raw_objects(donor), donor_before)


if __name__ == '__main__':
    unittest.main()
