"""Head-mesh grafts on real serialized costumes, with no patched head detection.

The fixture is a saved Unity costume laid out like a game costume: the Hair
SkinnedMeshRenderer sits at Head/Head_All/mesh_hair/Hair, a bone-less Face at
Head_All/mesh_face/Face, and a typed BodyPartManager points headAll and
headMaterial at them. Hair, Face and the manager share one head material, as
they do in game. Its 16x16 nearest-sampled texture is split in quadrants
(texel units, x to the right, y up like UV v):

  x 0-7,  y 8-15  cheek window (uv0 * 2.22 + (0, -1.221) reaches the array)
  x 8-15, y 8-15  Hair, the receiving mesh
  x 0-7,  y 0-7   Face
  x 8-15, y 0-7   free, unless a separate facial bundle covers it
"""
from copy import deepcopy
from pathlib import Path
import re
import tempfile
import unittest

import numpy as np
import UnityPy

import costume_part_transplant as cpt
import graft_game_compat as compat
from graft_game_compat import bake_renderer_for_game
from test_graft_game_compat import fixture, raw_objects
from test_graft_shared_assets import add_component

SIZE = 16
BLUE, RED, GREEN = (0, 0, 255, 255), (255, 0, 0, 255), (0, 255, 0, 255)


def pointer(path_id):
    return {"m_FileID": 0, "m_PathID": path_id}


def quad(x0, y0, x1, y1):
    """Two UV triangles covering texels x0..x1, y0..y1 (inclusive), nothing more."""
    a, b, c, d = (x0 + .25) / SIZE, (y0 + .25) / SIZE, (x1 + .75) / SIZE, (y1 + .75) / SIZE
    return [((a, b), (c, b), (a, d)), ((c, b), (c, d), (a, d))]


HAIR = quad(8, 8, 15, 15)
FACE = quad(0, 0, 7, 7)
FREE = quad(8, 0, 15, 7)


def set_uvs(tree, triangles):
    """Give the n-th triangle (each has its own vertices) the n-th UV triangle, cycling."""
    count, channels, strides, starts, _ = cpt.stream_layout(tree)
    data = bytearray(tree["m_VertexData"]["m_DataSize"])
    uv = cpt.read_attr(np.frombuffer(data, np.uint8), cpt.ATTR_UV0, channels, strides, starts, count)
    for index, face in enumerate(np.concatenate(cpt.submesh_triangles(tree))):
        uv[face, :2] = triangles[index % len(triangles)]
    cpt.write_attr(np.frombuffer(data, np.uint8), uv, cpt.ATTR_UV0, channels, strides, starts, count)
    tree["m_VertexData"]["m_DataSize"] = bytes(data)
    return tree


def split_groups(tree, receiver, donor):
    """Receiver = the first ten triangles, donor = the other ten, each with own UVs."""
    width = 2 if tree.get("m_IndexFormat", 0) == 0 else 4
    half = len(bytes(tree["m_IndexBuffer"])) // width // 2
    first = dict(tree["m_SubMeshes"][0], firstByte=0, indexCount=half)
    tree["m_SubMeshes"] = [first, dict(first, firstByte=half * width)]
    return set_uvs(tree, [receiver[index % len(receiver)] for index in range(10)]
                   + [donor[index % len(donor)] for index in range(10)])


def texture_of(objects, material_id, slot="_MainTex"):
    envs = dict(objects[material_id].read_typetree()["m_SavedProperties"]["m_TexEnvs"])
    return objects[envs[slot]["m_Texture"]["m_PathID"]]


def pixels(texture):
    """RGBA rows with y up (row 0 = UV v 0), so texel (x, y) is image[y, x]."""
    return np.asarray(texture.read().image.convert("RGBA"))[::-1]


def head_costume(*, hair=HAIR, hair_copy=False):
    """Return a reopened game-like costume and the path IDs of its parts."""
    environment, renderer, mesh, material = fixture(BLUE, size=SIZE)
    sf = renderer.assets_file
    objects = {obj.path_id: obj for obj in environment.objects}
    trees = {pid: obj.read_typetree() for pid, obj in objects.items()
             if obj.type.name in ("GameObject", "Transform")}
    names = {trees[pid]["m_Name"]: pid for pid, obj in objects.items() if obj.type.name == "GameObject"}
    head_go = names["Head"]
    head_transform = trees[head_go]["m_Component"][0]["component"]["m_PathID"]
    created, ids = {}, iter(range(5000, 6000))

    def node(name, parent_transform, components=()):
        game, transform = next(ids), next(ids)
        game_tree = deepcopy(trees[head_go])
        game_tree.update(m_Name=name, m_Component=[{"component": pointer(transform)}]
                         + [{"component": pointer(component)} for component in components])
        transform_tree = deepcopy(trees[head_transform])
        transform_tree.update(m_GameObject=pointer(game), m_Children=[], m_Father=pointer(parent_transform),
                              m_LocalPosition={"x": 0., "y": 0., "z": 0.},
                              m_LocalRotation={"x": 0., "y": 0., "z": 0., "w": 1.})
        trees[game], trees[transform] = game_tree, transform_tree
        created[game], created[transform] = objects[head_go], objects[head_transform]
        trees[parent_transform]["m_Children"].append(pointer(transform))
        return game, transform

    head_all, head_all_transform = node("Head_All", head_transform)
    _, hair_holder = node("mesh_hair", head_all_transform)
    _, face_holder = node("mesh_face", head_all_transform)
    # Move the costume's renderer to Head_All/mesh_hair/Hair.
    hair_go = renderer.read_typetree()["m_GameObject"]["m_PathID"]
    hair_transform = trees[hair_go]["m_Component"][0]["component"]["m_PathID"]
    old_parent = trees[hair_transform]["m_Father"]["m_PathID"]
    trees[old_parent]["m_Children"] = [child for child in trees[old_parent]["m_Children"]
                                       if child["m_PathID"] != hair_transform]
    trees[hair_transform]["m_Father"] = pointer(hair_holder)
    trees[hair_holder]["m_Children"].append(pointer(hair_transform))
    trees[hair_go]["m_Name"] = "Hair"
    # A bone-less Face with its own mesh, drawn with the same head material.
    face_mesh, face_renderer = 6000, 6001
    face_go, _ = node("Face", face_holder, (face_renderer,))
    face_tree = renderer.read_typetree()
    face_tree.update(m_GameObject=pointer(face_go), m_Mesh=pointer(face_mesh), m_Bones=[])
    cpt._make_object(sf, mesh, face_mesh, set_uvs(mesh.read_typetree(), FACE))
    cpt._make_object(sf, renderer, face_renderer, face_tree)
    hair_tree = renderer.read_typetree()
    ids_out = {"hair": renderer.path_id, "face": face_renderer, "face_mesh": face_mesh, "mesh": mesh.path_id,
               "material": material.path_id, "manager": 7000, "head_all": head_all}
    if hair_copy:
        # An older graft left Hair with a copied material and its own texture.
        texture = next(obj for obj in objects.values() if obj.type.name == "Texture2D")
        texture_tree = texture.read_typetree()
        texture_tree.update(m_Name="copied", **{"image data": bytes(GREEN) * SIZE * SIZE})
        copy_tree = material.read_typetree()
        copy_tree["m_Name"] = "ch9999_co0001_head"
        dict(copy_tree["m_SavedProperties"]["m_TexEnvs"])["_MainTex"]["m_Texture"] = pointer(6003)
        cpt._make_object(sf, texture, 6003, texture_tree)
        cpt._make_object(sf, material, 6002, copy_tree)
        hair_tree["m_Materials"] = [pointer(6002)]
        ids_out.update(copy=6002, copy_texture=6003)
    renderer.save_typetree(hair_tree)
    mesh.save_typetree(set_uvs(mesh.read_typetree(), hair))
    for pid, tree in trees.items():
        if pid in created:
            cpt._make_object(sf, created[pid], pid, tree)
        else:
            objects[pid].save_typetree(tree)
    add_component(environment, 7000, "BodyPartManager",
                  {"headAll": pointer(head_all), "headMaterial": pointer(material.path_id)},
                  namespace="LLAS.Components.Members")
    return UnityPy.load(environment.file.save(packer="original")), ids_out


def face_bundle(triangles):
    """A separate facial bundle whose eye/mouth renderer samples ``triangles``."""
    environment, _, mesh, _ = fixture(BLUE, size=SIZE)
    mesh.save_typetree(set_uvs(mesh.read_typetree(), triangles))
    return environment.file.save(packer="original")


class RealHeadBakeTests(unittest.TestCase):
    """bake_renderer_for_game with the head found from the costume itself."""

    def bake(self, target, ids, donor_uvs, *, receiver=HAIR, **options):
        objects = {obj.path_id: obj for obj in target.objects}
        renderer = objects[ids["hair"]]
        donor, _, _, donor_material = fixture(RED, size=SIZE)
        tree = split_groups(objects[ids["mesh"]].read_typetree(), receiver, donor_uvs)
        renderer_tree = renderer.read_typetree()
        stats = bake_renderer_for_game(target, renderer, objects[ids["mesh"]], mesh_tree=tree,
            renderer_tree=renderer_tree, additional_sources=[(donor, donor_material.path_id)], **options)
        return stats, renderer_tree

    def test_head_is_found_from_the_costume_and_drawn_with_its_shared_material(self):
        target, ids = head_costume()
        objects = {obj.path_id: obj for obj in target.objects}
        binding = compat.head_material_binding(objects, objects[ids["hair"]])
        self.assertEqual(binding["material"].path_id, ids["material"])
        self.assertEqual({obj.path_id for obj in binding["renderers"]}, {ids["hair"], ids["face"]})
        self.assertTrue(compat.face_combined_renderer(objects, objects[ids["face"]]))
        shared_mesh, shared_material, _ = compat._shared_assets(objects, objects[ids["hair"]],
                                                               objects[ids["mesh"]], objects[ids["material"]])
        self.assertFalse(shared_mesh)
        self.assertTrue(shared_material, "Face and BodyPartManager also use the head material")

    def test_donor_texels_go_into_the_shared_head_material_not_a_copy(self):
        target, ids = head_costume()
        before = raw_objects(target)
        materials = sorted(obj.path_id for obj in target.objects if obj.type.name == "Material")
        stats, renderer_tree = self.bake(target, ids, quad(9, 1, 12, 4), uv_placement="same_position",
                                         face_surfaces=[])
        self.assertTrue(stats["head_material"])
        self.assertFalse(stats["detached_material"])
        self.assertEqual(renderer_tree["m_Materials"], [pointer(ids["material"])])
        saved = UnityPy.load(target.file.save(packer="original"))
        objects = {obj.path_id: obj for obj in saved.objects}
        self.assertEqual(sorted(pid for pid, obj in objects.items() if obj.type.name == "Material"), materials)
        self.assertEqual(objects[ids["face"]].read_typetree()["m_Materials"], [pointer(ids["material"])])
        self.assertEqual(objects[ids["manager"]].read_typetree()["headMaterial"], pointer(ids["material"]))
        self.assertEqual(raw_objects(saved)[ids["face_mesh"]], before[ids["face_mesh"]])
        image = pixels(texture_of(objects, ids["material"]))
        self.assertEqual(image.shape[:2], (SIZE, SIZE))
        expected = np.zeros((SIZE, SIZE), bool)
        expected[1:5, 9:13] = True
        np.testing.assert_array_equal(np.all(image == RED, axis=2), expected)
        self.assertTrue(np.all(image[~expected] == BLUE), "only the donor texels change")

    def test_hair_with_an_older_copied_material_is_written_back_into_the_head_material(self):
        target, ids = head_costume(hair_copy=True)
        copy_before = raw_objects(target)
        stats, renderer_tree = self.bake(target, ids, quad(9, 1, 12, 4), uv_placement="same_position",
                                         face_surfaces=[])
        self.assertEqual(renderer_tree["m_Materials"], [pointer(ids["material"])],
                         "the game draws Hair with headMaterial, so the graft goes there")
        saved = UnityPy.load(target.file.save(packer="original"))
        objects = {obj.path_id: obj for obj in saved.objects}
        self.assertEqual(objects[ids["hair"]].read_typetree()["m_Materials"], [pointer(ids["material"])])
        self.assertTrue(np.any(np.all(pixels(texture_of(objects, ids["material"])) == RED, axis=2)))
        after = raw_objects(saved)
        for name in ("copy", "copy_texture"):
            self.assertEqual(after[ids[name]], copy_before[ids[name]], name)

    def test_face_uvs_on_the_shared_texture_are_never_written(self):
        target, ids = head_costume()
        before = raw_objects(target)
        with self.assertRaises(ValueError) as caught:
            self.bake(target, ids, quad(1, 1, 4, 4), uv_placement="same_position", face_surfaces=[])
        # The original position is taken, but empty UV areas still fit: say so.
        self.assertEqual(str(caught.exception), compat.HEAD_POSITION_IN_USE + " "
                         + compat.HEAD_DETAIL_POSITION.format(slot="_MainTex"))
        self.assertEqual(raw_objects(target), before)
        stats, _ = self.bake(target, ids, quad(1, 1, 4, 4), uv_placement="move_to_empty", face_surfaces=[])
        self.assertEqual(stats["texture_mode"], "relocate_empty_uv")
        image = pixels(texture_of({obj.path_id: obj for obj in UnityPy.load(target.file.save(packer="original")).objects},
                                  ids["material"]))
        red = np.all(image == RED, axis=2)
        self.assertEqual(int(red.sum()), 16)
        self.assertFalse(red[0:8, 0:8].any(), "Face texels keep their colour")
        self.assertFalse(red[8:16, :].any(), "cheek window and Hair keep their colour")


class IslandBakeTests(unittest.TestCase):
    def test_islands_that_only_fit_apart_are_placed_apart_by_the_bake(self):
        """Two 4x4 islands side by side; the only free texels are two far-apart 4x4 holes."""
        target, renderer, mesh, material = fixture(BLUE, size=SIZE)
        donor, _, _, donor_material = fixture(RED, size=SIZE)
        receiver = quad(4, 0, 15, 3) + quad(0, 4, 15, 11) + quad(0, 12, 11, 15)
        islands = quad(4, 4, 7, 7) + quad(8, 4, 11, 7)
        tree = split_groups(mesh.read_typetree(), receiver, islands)
        stats = bake_renderer_for_game(target, renderer, mesh, mesh_tree=tree,
            additional_sources=[(donor, donor_material.path_id)], uv_placement="move_to_empty")
        self.assertEqual(stats["texture_mode"], "relocate_empty_uv", stats["diagnostics"])
        self.assertEqual(stats["placed_groups"], 3, "the receiver plus one group per island")
        saved = UnityPy.load(target.file.save(packer="original"))
        objects = {obj.path_id: obj for obj in saved.objects}
        image = pixels(texture_of(objects, material.path_id))
        self.assertEqual(image.shape[:2], (SIZE, SIZE), "no atlas")
        red = np.all(image == RED, axis=2)
        expected = np.zeros((SIZE, SIZE), bool)
        expected[0:4, 0:4] = expected[12:16, 12:16] = True
        np.testing.assert_array_equal(red, expected)


class FaceBundleTransplantTests(unittest.TestCase):
    """transplant_part reads the separate facial bundle and keeps its texels."""

    def run_part(self, face_triangles, placement):
        target, ids = head_costume()
        donor, donor_renderer, donor_mesh, _ = fixture(RED, size=SIZE)
        donor_mesh.save_typetree(set_uvs(donor_mesh.read_typetree(), quad(9, 1, 12, 4)))
        donor = UnityPy.load(donor.file.save(packer="original"))
        with tempfile.TemporaryDirectory(prefix="head-face-bundle-") as directory:
            root = Path(directory)
            paths = {name: root / f"{name}.unity" for name in ("target", "donor", "face", "output")}
            paths["target"].write_bytes(target.file.save(packer="original"))
            paths["donor"].write_bytes(donor.file.save(packer="original"))
            paths["face"].write_bytes(face_bundle(face_triangles))
            face = paths["face"].read_bytes()
            try:
                cpt.transplant_part(str(paths["donor"]), str(paths["target"]), str(paths["output"]),
                    triangle_indices=[0], new_submesh="atlas", uv_placement=placement,
                    donor_renderer=donor_renderer.path_id, target_renderer=ids["hair"],
                    face_companions=[str(paths["face"])], worldspace=False, fix_nodescaling=False,
                    verbose=False, log_callback=lambda message: None)
                self.assertEqual(paths["face"].read_bytes(), face, "the facial bundle is only read")
                output = UnityPy.load(str(paths["output"]))
                return ids, {obj.path_id: obj for obj in output.objects}
            finally:
                self.assertEqual(paths["face"].read_bytes(), face)

    def test_a_free_area_covered_by_the_facial_bundle_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self.run_part(FREE, "same_position")
        self.assertTrue(str(caught.exception).startswith(compat.HEAD_POSITION_IN_USE), caught.exception)
        with self.assertRaises(ValueError) as caught:
            self.run_part(FREE, "move_to_empty")
        self.assertRegex(str(caught.exception), "^" + re.escape(compat.HEAD_NO_SPACE)
                         + r" Island 1 of 1 \(\d+×\d+ px\) found no free texels in _MainTex\.$")

    def test_free_texels_outside_the_facial_bundle_receive_the_part(self):
        for placement in ("same_position", "move_to_empty"):
            with self.subTest(placement=placement):
                ids, objects = self.run_part(FACE, placement)
                hair = objects[ids["hair"]].read_typetree()
                self.assertEqual(hair["m_Materials"], [pointer(ids["material"])])
                red = np.all(pixels(texture_of(objects, ids["material"])) == RED, axis=2)
                self.assertTrue(red.any())
                self.assertFalse(red[:, 0:8].any() or red[8:16, :].any(), "only the free quadrant changes")


if __name__ == "__main__":
    unittest.main()
