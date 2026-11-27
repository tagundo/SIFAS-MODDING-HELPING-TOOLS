"""Game rules applied after a part graft is written (graft_game_rules).

Both were confirmed in the game client with a hat taken off a head mesh and
grafted onto Body: a Body skinned to Head_Hair made the whole member disappear,
and the hat's back-to-back faces flickered while Body drew both sides.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import numpy as np
import UnityPy

import costume_part_transplant as cpt
import graft_game_rules as rules
from test_graft_game_compat import fixture
from test_graft_shared_assets import add_component


def pointer(path_id):
    return {"m_FileID": 0, "m_PathID": path_id}


def floats(tree):
    return dict(tree["m_SavedProperties"]["m_Floats"])


def set_cull(material, value):
    tree = material.read_typetree()
    tree["m_SavedProperties"]["m_Floats"] = [(name, value if name == "_CullMode" else number)
                                            for name, number in tree["m_SavedProperties"]["m_Floats"]]
    if "_CullMode" not in floats(tree):
        tree["m_SavedProperties"]["m_Floats"].append(("_CullMode", value))
    material.save_typetree(tree)


def body_with_face_side_bone():
    """A body renderer outside Head_All that gained Head_Hair for its last triangle."""
    environment, renderer, mesh, material = fixture()
    objects = {obj.path_id: obj for obj in environment.objects}
    trees = {pid: obj.read_typetree() for pid, obj in objects.items() if obj.type.name in ("GameObject", "Transform")}
    names = {trees[pid]["m_Name"]: pid for pid, obj in objects.items() if obj.type.name == "GameObject"}
    head_go = names["Head"]
    head = trees[head_go]["m_Component"][0]["component"]["m_PathID"]
    sf, ids = renderer.assets_file, iter(range(5000, 6000))

    def node(name, parent, position):
        game, transform = next(ids), next(ids)
        game_tree = deepcopy(trees[head_go])
        game_tree.update(m_Name=name, m_Component=[{"component": pointer(transform)}])
        transform_tree = deepcopy(trees[head])
        transform_tree.update(m_GameObject=pointer(game), m_Children=[], m_Father=pointer(parent),
                              m_LocalPosition=dict(zip("xyz", position)),
                              m_LocalRotation={"x": 0., "y": 0.3826834, "z": 0., "w": 0.9238795})
        trees[parent]["m_Children"].append(pointer(transform))
        cpt._make_object(sf, objects[head_go], game, game_tree)
        cpt._make_object(sf, objects[head], transform, transform_tree)
        trees[transform] = transform_tree
        return game, transform

    head_all_go, head_all = node("Head_All", head, (0., .05, 0.))
    _, hair = node("Head_Hair", head_all, (.01, .1, .02))
    objects[head].save_typetree(trees[head])
    add_component(environment, 7000, "BodyPartManager", {"head": pointer(head_go), "headAll": pointer(head_all_go)},
                  namespace="LLAS.Components.Members")
    environment = UnityPy.load(environment.file.save(packer="original"))
    objects = {obj.path_id: obj for obj in environment.objects}
    transforms = {pid: obj.read_typetree() for pid, obj in objects.items() if obj.type.name == "Transform"}
    renderer_tree = objects[renderer.path_id].read_typetree()
    original = len(renderer_tree["m_Bones"])
    tree = objects[mesh.path_id].read_typetree()
    mesh_root = np.eye(4)
    tree["m_BindPose"] = tree["m_BindPose"] + [rules._bindpose_row(np.linalg.inv(rules._rest_world(transforms, hair)) @ mesh_root)]
    if tree.get("m_BoneNameHashes"):
        tree["m_BoneNameHashes"] = tree["m_BoneNameHashes"] + [123]
    count, channels, strides, starts, _ = cpt.stream_layout(tree)
    data = bytearray(tree["m_VertexData"]["m_DataSize"])
    u8 = np.frombuffer(data, np.uint8)
    weights = cpt.read_attr(u8, cpt.ATTR_BLENDWEIGHT, channels, strides, starts, count)
    indices = cpt.read_attr(u8, cpt.ATTR_BLENDINDICES, channels, strides, starts, count)
    last = np.unique(cpt.submesh_triangles(tree)[-1][-1])
    weights[last], indices[last] = [1., 0., 0., 0.][:weights.shape[1]], original
    cpt.write_attr(u8, weights, cpt.ATTR_BLENDWEIGHT, channels, strides, starts, count)
    cpt.write_attr(u8, indices, cpt.ATTR_BLENDINDICES, channels, strides, starts, count)
    tree["m_VertexData"]["m_DataSize"] = bytes(data)
    objects[mesh.path_id].save_typetree(tree)
    renderer_tree["m_Bones"] = renderer_tree["m_Bones"] + [pointer(hair)]
    objects[renderer.path_id].save_typetree(renderer_tree)
    return environment.file.save(packer="original"), renderer.path_id, mesh.path_id, original, hair, head, last


class GraftGameRuleTests(unittest.TestCase):
    def test_body_never_keeps_a_face_side_bone_and_keeps_its_rest_pose(self):
        raw, renderer, mesh, original, hair, head, moved = body_with_face_side_bone()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out.unity"
            path.write_bytes(raw)
            before = UnityPy.load(str(path))
            objects = {obj.path_id: obj for obj in before.objects}
            transforms = {pid: obj.read_typetree() for pid, obj in objects.items() if obj.type.name == "Transform"}
            skin = rules._rest_world(transforms, hair) @ rules._bindpose(objects[mesh].read_typetree()["m_BindPose"][-1])
            self.assertEqual(rules.rebind_head_bones(path, renderer, original, log=lambda *_: None), len(moved))
            self.assertEqual(rules.rebind_head_bones(path, renderer, original, log=lambda *_: None), 0)
            after = {obj.path_id: obj for obj in UnityPy.load(str(path)).objects}
            bones = [row["m_PathID"] for row in after[renderer].read_typetree()["m_Bones"]]
            tree = after[mesh].read_typetree()
            self.assertNotIn(hair, bones)
            self.assertEqual(len(bones), len(tree["m_BindPose"]))
            count, channels, strides, starts, _ = cpt.stream_layout(tree)
            u8 = np.frombuffer(bytes(tree["m_VertexData"]["m_DataSize"]), np.uint8)
            indices = cpt.read_attr(u8, cpt.ATTR_BLENDINDICES, channels, strides, starts, count)
            weights = cpt.read_attr(u8, cpt.ATTR_BLENDWEIGHT, channels, strides, starts, count)
            self.assertTrue(np.all(indices[moved, 0] < len(bones)) and np.allclose(weights[moved].sum(1), 1.))
            target = int(indices[moved[0], 0])
            self.assertEqual(bones[target], head)
            rebound = rules._rest_world(transforms, head) @ rules._bindpose(tree["m_BindPose"][target])
            np.testing.assert_allclose(rebound, skin, atol=1e-5)

    def test_bones_the_costume_already_used_are_left_alone(self):
        raw, renderer, mesh, original, hair, _, _ = body_with_face_side_bone()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out.unity"
            path.write_bytes(raw)
            self.assertEqual(rules.rebind_head_bones(path, renderer, original + 1, log=lambda *_: None), 0)
            self.assertEqual(path.read_bytes(), raw)

    def test_culled_donor_part_gets_its_own_listed_material(self):
        environment, renderer, mesh, material = fixture()
        set_cull(material, 0.)
        add_component(environment, 840, "LiveCoreMemberRimlight", {"materials": [pointer(material.path_id)]},
                      namespace="LLAS.Components.Members")
        raw = environment.file.save(packer="original")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out.unity"
            path.write_bytes(raw)
            before = {obj.path_id: obj for obj in UnityPy.load(str(path)).objects}
            total = int(before[mesh.path_id].read_typetree()["m_SubMeshes"][-1]["indexCount"])
            new = rules.split_culled_part(path, renderer.path_id, 3, 2., log=lambda *_: None)
            after = {obj.path_id: obj for obj in UnityPy.load(str(path)).objects}
            tree = after[mesh.path_id].read_typetree()
            self.assertEqual([s["indexCount"] for s in tree["m_SubMeshes"]][-2:], [total - 3, 3])
            self.assertEqual(bytes(tree["m_IndexBuffer"]), bytes(before[mesh.path_id].read_typetree()["m_IndexBuffer"]))
            self.assertEqual(after[renderer.path_id].read_typetree()["m_Materials"][-1], pointer(new))
            copy, receiving = after[new].read_typetree(), after[material.path_id].read_typetree()
            self.assertEqual((floats(copy)["_CullMode"], floats(receiving)["_CullMode"]), (2., 0.))
            self.assertEqual(copy["m_SavedProperties"]["m_TexEnvs"], receiving["m_SavedProperties"]["m_TexEnvs"])
            self.assertIn(pointer(new), after[840].read_typetree()["materials"])

    def test_two_sided_donor_or_culled_receiver_changes_nothing(self):
        environment, renderer, _, material = fixture()
        for receiving, donor in ((0., 0.), (2., 2.)):
            set_cull(material, receiving)
            raw = environment.file.save(packer="original")
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "out.unity"
                path.write_bytes(raw)
                self.assertIsNone(rules.split_culled_part(path, renderer.path_id, 3, donor, log=lambda *_: None))
                self.assertEqual(path.read_bytes(), raw)


class CulledPartReportTests(unittest.TestCase):
    """The preview and the graft say what rule 2 does: its own culled material,
    or, only when that split cannot be done, that back faces can show."""

    def test_plan_names_the_split_or_why_there_is_none(self):
        from graft_texture_atlas import CULL_MODE_BOTH_SIDES, CULL_MODE_OWN_MATERIAL
        self.assertEqual(rules.plan_culled_part("Body", 0., [("Hat", 2.), ("Hat", 2.)]), (2., [
            CULL_MODE_OWN_MATERIAL.format(donor="Hat", donor_value="2", receiver="Body", copy="Body_culled")]))
        self.assertEqual(rules.plan_culled_part("Body", 0., [("Hat", 2.), ("Ribbon", 0.)]), (None, [
            rules.CULL_MODE_MIXED, CULL_MODE_BOTH_SIDES.format(donor="Hat", donor_value="2", receiver="Body")]))
        for receiver, donor in ((2., 2.), (0., 0.), (1., 1.)):
            self.assertEqual(rules.plan_culled_part("Body", receiver, [("Hat", donor)]), (None, []))
        self.assertEqual(rules.material_cull({"m_SavedProperties": {"m_Floats": []}}), 2.)
        self.assertEqual(rules.material_cull(None), 2.)

    def test_split_logs_its_own_material_or_the_back_face_warning(self):
        environment, renderer, mesh, material = fixture()
        set_cull(material, 0.)
        raw = environment.file.save(packer="original")
        name = material.read_typetree()["m_Name"]
        total = int(mesh.read_typetree()["m_SubMeshes"][-1]["indexCount"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out.unity"
            path.write_bytes(raw)
            lines = []
            self.assertIsNone(rules.split_culled_part(path, renderer.path_id, total, 2., log=lines.append, donor_name="Hat"))
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(lines[-1], f"[warn] Hat (_CullMode 2) is drawn from both sides like {name} (_CullMode 0); "
                                        "its back faces can show.")
            lines.clear()
            self.assertIsNotNone(rules.split_culled_part(path, renderer.path_id, 3, 2., log=lines.append, donor_name="Hat"))
            self.assertEqual(lines, [f"[game] Hat (_CullMode 2) keeps its culling: it becomes its own submesh drawn by "
                                     f"{name}_culled, a copy of {name} (_CullMode 0) with _CullMode 2."])

    def test_preview_and_graft_report_the_same_split(self):
        target, target_renderer, _, target_material = fixture()
        donor, donor_renderer, _, donor_material = fixture((255, 0, 0, 255))
        set_cull(target_material, 0.)
        set_cull(donor_material, 2.)
        receiver = target_material.read_typetree()["m_Name"]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "target.unity").write_bytes(target.file.save(packer="original"))
            (root / "donor.unity").write_bytes(donor.file.save(packer="original"))
            runs = {}
            for dry_run in (True, False):
                lines = runs[dry_run] = []
                cpt.transplant_part(str(root / "donor.unity"), str(root / "target.unity"), str(root / "out.unity"),
                    triangle_indices=[0], new_submesh="atlas", reuse_empty_uv=False,
                    donor_renderer=donor_renderer.path_id, target_renderer=target_renderer.path_id,
                    worldspace=False, fix_nodescaling=False, verbose=False, dry_run=dry_run,
                    log_callback=lines.append)
            out = {obj.path_id: obj for obj in UnityPy.load(str(root / "out.unity")).objects}
        sentence = (f"{donor_material.read_typetree()['m_Name']} (_CullMode 2) keeps its culling: it becomes its own "
                    f"submesh drawn by {receiver}_culled, a copy of {receiver} (_CullMode 0) with _CullMode 2.")
        self.assertIn(f"  culling          : {sentence}", runs[True])
        self.assertIn(f"[game] {sentence}", runs[False])
        for lines in runs.values():
            self.assertFalse([line for line in lines if "back faces can show" in line], lines)
        materials = out[target_renderer.path_id].read_typetree()["m_Materials"]
        self.assertEqual(len(materials), 2)
        self.assertEqual(floats(out[materials[1]["m_PathID"]].read_typetree())["_CullMode"], 2.)


if __name__ == "__main__":
    unittest.main()
