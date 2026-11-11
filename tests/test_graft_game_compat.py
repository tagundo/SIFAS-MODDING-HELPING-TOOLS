"""The saved graft keeps the game's one Body material/submesh contract."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np
import UnityPy

import costume_part_transplant as cpt
from graft_game_compat import bake_renderer_for_game
from test_viewer_transplants import costume_fixture


def fixture(color=None, size=2):
    environment = UnityPy.load(costume_fixture())
    objects = {obj.path_id: obj for obj in environment.objects}
    renderer = next(obj for obj in environment.objects if obj.type.name == 'SkinnedMeshRenderer')
    mesh = objects[renderer.read_typetree()['m_Mesh']['m_PathID']]
    material = objects[renderer.read_typetree()['m_Materials'][0]['m_PathID']]
    texture = next(obj for obj in environment.objects if obj.type.name == 'Texture2D')
    if color is not None:
        width, height = size if isinstance(size, tuple) else (size, size)
        tree = texture.read_typetree()
        tree.update(m_Width=width, m_Height=height, m_TextureFormat=4, m_CompleteImageSize=width * height * 4,
                    m_MipCount=1, **{'image data': bytes(color) * width * height})
        tree['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
        tree['m_TextureSettings']['m_FilterMode'] = 0
        texture.save_typetree(tree)
    tree = mesh.read_typetree()
    count, channels, strides, starts, _ = cpt.stream_layout(tree)
    data = bytearray(tree['m_VertexData']['m_DataSize'])
    uv = np.tile(np.array([[0., 0.], [1., 0.], [0., 1.]], np.float32), (count // 3, 1))
    cpt.write_attr(np.frombuffer(data, np.uint8), uv, cpt.ATTR_UV0, channels, strides, starts, count)
    tree['m_VertexData']['m_DataSize'] = bytes(data)
    mesh.save_typetree(tree)
    environment = UnityPy.load(environment.file.save(packer='original'))
    objects = {obj.path_id: obj for obj in environment.objects}
    renderer, mesh, material = (objects[obj.path_id] for obj in (renderer, mesh, material))
    return environment, renderer, mesh, material


def append_group(mesh_tree):
    tree = deepcopy(mesh_tree)
    data = bytes(tree['m_IndexBuffer'])
    submesh = deepcopy(tree['m_SubMeshes'][0])
    submesh['firstByte'] = len(data)
    tree['m_SubMeshes'].append(submesh)
    tree['m_IndexBuffer'] = data + data
    return tree


def raw_objects(environment):
    return {obj.path_id: obj.data if obj.data is not None else obj.get_raw_data() for obj in environment.objects}


class GraftGameCompatTests(unittest.TestCase):
    def test_distinct_material_textures_bake_without_gutters_and_keep_original_material(self):
        target, renderer, mesh, material = fixture((0, 0, 255, 255))
        donor, _, _, donor_material = fixture((255, 0, 0, 255))
        donor_before = raw_objects(donor)
        old_material = material.read_typetree()
        mesh_tree = append_group(mesh.read_typetree())
        renderer_tree = renderer.read_typetree()
        stats = bake_renderer_for_game(target, renderer, mesh, mesh_tree=mesh_tree,
            renderer_tree=renderer_tree, additional_sources=[(donor, donor_material.path_id)], reuse_empty_uv=False)
        self.assertEqual(stats['submeshes'], 1)
        self.assertEqual(stats['materials'], 1)
        self.assertEqual(stats['texture_mode'], 'atlas')
        self.assertEqual(len(mesh_tree['m_SubMeshes']), 1)
        self.assertEqual(renderer_tree['m_Materials'], [{'m_FileID': 0, 'm_PathID': material.path_id}])
        self.assertEqual(sum(obj.type.name == 'Material' for obj in target.objects), 1)
        reloaded = UnityPy.load(target.file.save(packer='original'))
        reloaded_objects = {obj.path_id: obj for obj in reloaded.objects}
        new_material = reloaded_objects[material.path_id].read_typetree()
        self.assertEqual(new_material['m_Shader'], old_material['m_Shader'])
        for field in old_material:
            if field != 'm_SavedProperties': self.assertEqual(new_material[field], old_material[field])
        for field in ('m_Floats', 'm_Colors'):
            self.assertEqual(new_material['m_SavedProperties'][field], old_material['m_SavedProperties'][field])
        pointer = dict(new_material['m_SavedProperties']['m_TexEnvs'])['_MainTex']['m_Texture']
        texture = reloaded_objects[pointer['m_PathID']]
        image = texture.read().image.convert('RGBA')
        self.assertEqual(image.width * image.height, 8)  # Exactly two 2x2 tiles, no border pixels.
        pixels = [tuple(pixel) for pixel in np.asarray(image).reshape(-1, 4)]
        self.assertEqual(sorted(pixels), sorted([(0, 0, 255, 255)] * 4 + [(255, 0, 0, 255)] * 4))
        self.assertEqual(raw_objects(donor), donor_before)
        saved_renderer = next(obj for obj in reloaded.objects if obj.path_id == renderer.path_id)
        saved_mesh = next(obj for obj in reloaded.objects if obj.path_id == mesh.path_id)
        self.assertEqual(len(saved_renderer.read_typetree()['m_Materials']), 1)
        self.assertEqual(len(saved_mesh.read_typetree()['m_SubMeshes']), 1)

    def test_identical_sources_flatten_without_copying_textures_or_changing_material(self):
        target, renderer, mesh, material = fixture()
        before_material = material.get_raw_data()
        before_ids = set(raw_objects(target))
        tree = append_group(mesh.read_typetree())
        stats = bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree,
            additional_sources=[(target, material.path_id)])
        self.assertTrue(stats['atlas_identity'])
        self.assertEqual(stats['texture_mode'], 'identity')
        self.assertEqual(stats['atlas_textures'], 0)
        self.assertEqual(set(raw_objects(target)), before_ids)
        self.assertEqual(material.get_raw_data(), before_material)
        self.assertEqual(len(tree['m_SubMeshes']), 1)

    def test_donor_rim_map_adds_known_target_texture_property_without_new_material(self):
        target, renderer, mesh, material = fixture((0, 0, 255, 255))
        donor, _, _, donor_material = fixture((255, 0, 0, 255))
        donor_tree = donor_material.read_typetree()
        main = deepcopy(dict(donor_tree['m_SavedProperties']['m_TexEnvs'])['_MainTex'])
        donor_tree['m_SavedProperties']['m_TexEnvs'].append(('_RimlightTex', main))
        donor_material.save_typetree(donor_tree)
        donor = UnityPy.load(donor.file.save(packer='original'))
        donor_before = raw_objects(donor)
        tree = append_group(mesh.read_typetree())
        bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree,
            additional_sources=[(donor, donor_material.path_id)])
        saved = UnityPy.load(target.file.save(packer='original'))
        objects = {obj.path_id: obj for obj in saved.objects}
        texture_properties = dict(objects[material.path_id].read_typetree()['m_SavedProperties']['m_TexEnvs'])
        self.assertEqual(set(texture_properties), {'_MainTex', '_RimlightTex'})
        rim = texture_properties['_RimlightTex']
        self.assertEqual(rim['m_Scale'], {'x': 1., 'y': 1.})
        self.assertEqual(rim['m_Offset'], {'x': 0., 'y': 0.})
        for slot in texture_properties.values():
            self.assertEqual(slot['m_Texture']['m_FileID'], 0)
            self.assertEqual(objects[slot['m_Texture']['m_PathID']].type.name, 'Texture2D')
        self.assertEqual(sum(obj.type.name == 'Material' for obj in saved.objects), 1)
        self.assertEqual(raw_objects(donor), donor_before)

    def test_float16_uv_bounds_and_flattening_use_original_coordinates(self):
        target, renderer, mesh, material = fixture()
        tree = mesh.read_typetree()
        count, channels, strides, starts, _ = cpt.stream_layout(tree)
        raw = np.frombuffer(tree['m_VertexData']['m_DataSize'], np.uint8)
        uv = cpt.read_attr(raw, cpt.ATTR_UV0, channels, strides, starts, count)
        streams = []
        uv_stream = channels[cpt.ATTR_UV0]['stream']
        self.assertEqual(strides[uv_stream], 8)
        for stream in sorted(strides):
            data = uv.astype('<f2').tobytes() if stream == uv_stream else raw[starts[stream]:starts[stream] + count * strides[stream]].tobytes()
            streams.append(data + bytes(-len(data) % 16))
        tree['m_VertexData']['m_DataSize'] = b''.join(streams)
        channels[cpt.ATTR_UV0]['format'] = 1
        tree = append_group(tree)
        stats = bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree,
            additional_sources=[(target, material.path_id)])
        self.assertTrue(stats['atlas_identity'])
        self.assertEqual(tree['m_VertexData']['m_Channels'][cpt.ATTR_UV0]['format'], 1)
        self.assertEqual(len(tree['m_SubMeshes']), 1)

    def test_incompatible_shader_failure_does_not_mutate_objects_or_working_trees(self):
        target, renderer, mesh, material = fixture((0, 0, 255, 255))
        donor, _, _, donor_material = fixture((255, 0, 0, 255))
        shader = next(obj for obj in donor.objects if obj.type.name == 'Shader')
        shader_tree = shader.read_typetree(); shader_tree['m_Name'] = 'Unrelated/Unsupported'
        shader.save_typetree(shader_tree)
        donor = UnityPy.load(donor.file.save(packer='original'))
        before = raw_objects(target)
        tree = append_group(mesh.read_typetree()); untouched = deepcopy(tree)
        with self.assertRaisesRegex(ValueError, 'shader|Shader'):
            bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree,
                additional_sources=[(donor, donor_material.path_id)])
        self.assertEqual(raw_objects(target), before)
        self.assertEqual(tree, untouched)

    def test_game_bone_cap_and_bind_pose_alignment_fail_before_mutation(self):
        target, renderer, mesh, material = fixture()
        for count, message in ((257, 'game limit is 256'), (19, 'bind poses do not match')):
            with self.subTest(count=count):
                before = raw_objects(target)
                tree = append_group(mesh.read_typetree())
                renderer_tree = renderer.read_typetree()
                renderer_tree['m_Bones'] = renderer_tree['m_Bones'][:1] * count
                with self.assertRaisesRegex(ValueError, message):
                    bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree, renderer_tree=renderer_tree,
                        additional_sources=[(target, material.path_id)])
                self.assertEqual(raw_objects(target), before)

    def test_shared_target_material_is_rejected_before_atlas_construction(self):
        target, renderer, mesh, material = fixture()
        cpt._make_object(renderer.assets_file, renderer, 987654321, renderer.read_typetree())
        before = raw_objects(target)
        tree = append_group(mesh.read_typetree())
        with patch('graft_texture_atlas.bake_game_atlas') as bake:
            with self.assertRaisesRegex(ValueError, 'also used by another renderer'):
                bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree,
                    additional_sources=[(target, material.path_id)])
        bake.assert_not_called()
        self.assertEqual(raw_objects(target), before)

    def test_geometry_failure_after_atlas_preflight_is_atomic(self):
        target, renderer, mesh, material = fixture((0, 0, 255, 255))
        donor, _, _, donor_material = fixture((255, 0, 0, 255))
        before = raw_objects(target)
        tree = append_group(mesh.read_typetree()); untouched = deepcopy(tree)
        with self.assertRaisesRegex(ValueError, 'vertex limit'):
            bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree, max_vertices=1,
                additional_sources=[(donor, donor_material.path_id)])
        self.assertEqual(raw_objects(target), before)
        self.assertEqual(tree, untouched)

    def test_unexpected_serializer_failure_rolls_back_new_textures_and_pending_data(self):
        target, renderer, mesh, material = fixture((0, 0, 255, 255))
        donor, _, _, donor_material = fixture((255, 0, 0, 255))
        tree = append_group(mesh.read_typetree()); untouched = deepcopy(tree)
        # Preserve an already prepared caller write if committing the atlas fails.
        mesh.save_typetree(tree)
        before = raw_objects(target)
        original_make = cpt._make_object
        def fail_after_insert(*args):
            original_make(*args)
            raise RuntimeError('serializer failed')
        with patch.object(cpt, '_make_object', side_effect=fail_after_insert):
            with self.assertRaisesRegex(RuntimeError, 'serializer failed'):
                bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree,
                    additional_sources=[(donor, donor_material.path_id)])
        self.assertEqual(raw_objects(target), before)
        self.assertEqual(tree, untouched)

    def test_empty_uv_reuse_patches_unoccupied_faces_without_moving_uvs(self):
        target, renderer, mesh, material = fixture((0, 0, 255, 255), size=16)
        donor, _, _, donor_material = fixture((255, 0, 0, 255), size=16)
        tree = mesh.read_typetree()
        count, channels, strides, starts, _ = cpt.stream_layout(tree)
        data = bytearray(tree['m_VertexData']['m_DataSize'])
        uv = cpt.read_attr(np.frombuffer(data, np.uint8), cpt.ATTR_UV0, channels, strides, starts, count)
        uv[:6] = [[.05, .05], [.25, .05], [.05, .25], [.7, .7], [.95, .7], [.7, .95]]
        cpt.write_attr(np.frombuffer(data, np.uint8), uv, cpt.ATTR_UV0, channels, strides, starts, count)
        tree['m_VertexData']['m_DataSize'] = bytes(data)
        first = deepcopy(tree['m_SubMeshes'][0]); first.update(firstByte=0, indexCount=3)
        second = deepcopy(first); second['firstByte'] = 6
        tree['m_SubMeshes'] = [first, second]
        tree['m_IndexBuffer'] = np.arange(6, dtype='<u2').tobytes()
        messages = []
        stats = bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree,
            additional_sources=[(donor, donor_material.path_id)], log=messages.append)
        self.assertEqual(stats['texture_mode'], 'reuse_empty_uv')
        self.assertTrue(any('reuse empty UV areas' in message for message in messages))
        _, channels, strides, starts, _ = cpt.stream_layout(tree)
        after_uv = cpt.read_attr(np.frombuffer(tree['m_VertexData']['m_DataSize'], np.uint8), cpt.ATTR_UV0, channels, strides, starts, count)
        np.testing.assert_allclose(after_uv, uv)
        self.assertEqual(stats['atlas_dimensions']['_MainTex'], [16, 16])
        saved = UnityPy.load(target.file.save(packer='original'))
        objects = {obj.path_id: obj for obj in saved.objects}
        material_tree = objects[material.path_id].read_typetree()
        pointer = dict(material_tree['m_SavedProperties']['m_TexEnvs'])['_MainTex']['m_Texture']
        pixels = np.asarray(objects[pointer['m_PathID']].read().image.convert('RGBA'))
        self.assertTrue(np.any(np.all(pixels == [255, 0, 0, 255], axis=2)))
        self.assertTrue(np.any(np.all(pixels == [0, 0, 255, 255], axis=2)))
        self.assertEqual(len(tree['m_SubMeshes']), 1)

    def test_empty_uv_conflict_falls_back_to_atlas_with_reason(self):
        target, renderer, mesh, material = fixture((0, 0, 255, 255), size=16)
        donor, _, _, donor_material = fixture((255, 0, 0, 255), size=16)
        tree = append_group(mesh.read_typetree())
        messages = []
        stats = bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree, reuse_empty_uv=True,
            additional_sources=[(donor, donor_material.path_id)], log=messages.append)
        self.assertEqual(stats['texture_mode'], 'atlas')
        self.assertTrue(any('overlap' in message.lower() or 'occupied' in message.lower() or 'conflict' in message.lower() or 'already used' in message.lower()
                            for message in stats['diagnostics']))
        self.assertTrue(any('atlas' in message for message in messages))

    def test_optional_relocation_preserves_native_main_and_rim_pixels_with_rectangular_donor(self):
        target, renderer, mesh, material = fixture((0, 0, 255, 255), size=16)
        donor, _, _, donor_material = fixture((255, 0, 0, 255), size=(8, 4))
        # Both UV-driven maps use the same ratio, so one vertex UV transform
        # preserves each map's original native pixel scale.
        for environment, source_material in ((target, material), (donor, donor_material)):
            material_tree = source_material.read_typetree()
            main = deepcopy(dict(material_tree['m_SavedProperties']['m_TexEnvs'])['_MainTex'])
            material_tree['m_SavedProperties']['m_TexEnvs'].append(('_RimlightTex', main))
            source_material.save_typetree(material_tree)
        target = UnityPy.load(target.file.save(packer='original'))
        donor = UnityPy.load(donor.file.save(packer='original'))
        objects = {obj.path_id: obj for obj in target.objects}
        renderer, mesh, material = (objects[obj.path_id] for obj in (renderer, mesh, material))
        donor_before = raw_objects(donor)
        tree = mesh.read_typetree()
        count, channels, strides, starts, _ = cpt.stream_layout(tree)
        data = bytearray(tree['m_VertexData']['m_DataSize'])
        uv = cpt.read_attr(np.frombuffer(data, np.uint8), cpt.ATTR_UV0, channels, strides, starts, count)
        uv[:6] = [[.1, .1], [.4, .1], [.1, .4], [.1, .1], [.4, .1], [.1, .4]]
        cpt.write_attr(np.frombuffer(data, np.uint8), uv, cpt.ATTR_UV0, channels, strides, starts, count)
        tree['m_VertexData']['m_DataSize'] = bytes(data)
        first = deepcopy(tree['m_SubMeshes'][0]); first.update(firstByte=0, indexCount=3)
        second = deepcopy(first); second['firstByte'] = 6
        tree['m_SubMeshes'] = [first, second]
        tree['m_IndexBuffer'] = np.arange(6, dtype='<u2').tobytes()
        stats = bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree, relocate_empty_uv=True,
            upscale_textures_for_uv_reuse=False,
            additional_sources=[(donor, donor_material.path_id)])
        self.assertEqual(stats['texture_mode'], 'relocate_empty_uv')
        self.assertEqual(stats['atlas_dimensions'], {'_MainTex': [16, 16], '_RimlightTex': [16, 16]})
        saved = UnityPy.load(target.file.save(packer='original'))
        objects = {obj.path_id: obj for obj in saved.objects}
        saved_tree = objects[mesh.path_id].read_typetree()
        count, channels, strides, starts, _ = cpt.stream_layout(saved_tree)
        new_uv = cpt.read_attr(np.frombuffer(saved_tree['m_VertexData']['m_DataSize'], np.uint8), cpt.ATTR_UV0, channels, strides, starts, count)
        np.testing.assert_allclose(new_uv[:3], uv[:3])
        np.testing.assert_allclose(new_uv[4] - new_uv[3], (uv[4] - uv[3]) * [.5, .25], atol=1e-7)
        np.testing.assert_allclose(new_uv[5] - new_uv[3], (uv[5] - uv[3]) * [.5, .25], atol=1e-7)
        material_tree = objects[material.path_id].read_typetree()
        for slot, value in material_tree['m_SavedProperties']['m_TexEnvs']:
            image = objects[value['m_Texture']['m_PathID']].read().image.convert('RGBA')
            pixels = np.asarray(image)
            receiver_uv = uv[:3].mean(axis=0)
            donor_uv = new_uv[3:6].mean(axis=0)
            sample = lambda coord: pixels[15 - int(coord[1] * 16), int(coord[0] * 16)].tolist()
            self.assertEqual(sample(receiver_uv), [0, 0, 255, 255], slot)
            self.assertEqual(sample(donor_uv), [255, 0, 0, 255], slot)
        self.assertEqual(len(saved_tree['m_SubMeshes']), 1)
        self.assertEqual(len(objects[renderer.path_id].read_typetree()['m_Materials']), 1)
        self.assertEqual(raw_objects(donor), donor_before)

    def test_relocation_requires_enabled_primary_reuse_without_mutation(self):
        target, renderer, mesh, _ = fixture()
        before = raw_objects(target)
        with self.assertRaisesRegex(ValueError, 'Enable empty UV reuse'):
            bake_renderer_for_game(target, renderer, mesh, reuse_empty_uv=False, relocate_empty_uv=True)
        self.assertEqual(raw_objects(target), before)


if __name__ == '__main__':
    unittest.main()
