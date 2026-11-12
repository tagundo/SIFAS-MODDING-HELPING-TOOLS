"""Shared graft assets stay isolated through real Unity serialization."""
from copy import copy, deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import UnityPy
from UnityPy.files.ObjectReader import ObjectReader
from UnityPy.helpers.TypeTreeNode import TypeTreeNode

import costume_part_transplant as cpt
import costume_transplant
import lower_body_swap
from graft_game_compat import bake_renderer_for_game, save_isolated_mesh
from test_graft_game_compat import append_group, fixture, raw_objects


def pointer(path_id):
    return {"m_FileID": 0, "m_PathID": path_id}


def reopen(environment):
    return UnityPy.load(environment.file.save(packer="original"))


def objects(environment):
    return {obj.path_id: obj for obj in environment.objects}


def add_component(environment, path_id, class_name, fields, *, namespace="LLAS.Scene.Live.Components"):
    """Add an original typed MonoBehaviour, with only its declared fields.

    Reuse Unity's serialized header and PPtr layouts, then emit an independent
    class-specific typetree. This exercises actual serialization rather than a
    fake object or a patched read_typetree result.
    """
    mono = next(obj for obj in environment.objects if obj.type.name == "MonoBehaviour")
    script = next(obj for obj in environment.objects if obj.type.name == "MonoScript")
    renderer = next(obj for obj in environment.objects if obj.type.name == "SkinnedMeshRenderer")
    sf = mono.assets_file
    rows = []
    for row in mono.serialized_type.node.to_dict_list():
        if row["m_Level"] == 1 and row["m_Name"] == "targetName":
            break
        rows.append({key: value for key, value in row.items() if key != "m_Children"})
    renderer_rows = renderer.serialized_type.node.to_dict_list()
    start = next(i for i, row in enumerate(renderer_rows) if row["m_Name"] == "m_Materials")
    end = next(i for i in range(start + 1, len(renderer_rows)) if renderer_rows[i]["m_Level"] <= 1)
    material_vector = [{key: value for key, value in row.items() if key != "m_Children"}
                       for row in renderer_rows[start:end]]
    for name, value in fields.items():
        if isinstance(value, list):
            field_rows = deepcopy(material_vector)
            field_rows[0]["m_Name"] = name
        else:
            field_rows = deepcopy(material_vector[3:])
            for row in field_rows:
                row["m_Level"] -= 2
            field_rows[0]["m_Name"] = name
        rows.extend(field_rows)
    for index, row in enumerate(rows):
        row["m_Index"] = index
    serialized = copy(mono.serialized_type)
    serialized.node = TypeTreeNode.from_list(rows)
    serialized.script_type_index = -1
    serialized.script_id = path_id.to_bytes(16, "little")
    serialized.old_type_hash = (path_id + 1).to_bytes(16, "little")
    sf.types.append(serialized)
    script_tree = script.read_typetree()
    script_tree.update(m_Name=class_name, m_ClassName=class_name,
                       m_Namespace=namespace, m_AssemblyName="Assembly-CSharp.dll")
    cpt._make_object(sf, script, path_id + 1, script_tree)
    component = copy(mono)
    component.path_id = path_id
    component.type_id = len(sf.types) - 1
    component.serialized_type = serialized
    sf.objects[path_id] = component
    tree = {name: value for name, value in mono.read_typetree().items() if name.startswith("m_")}
    tree.update(m_Script=pointer(path_id + 1), **fields)
    component.save_typetree(tree)
    return component


def shared_fixture(*, shared_renderer=True, controllers=True, head=True, spoof=False):
    environment, renderer, mesh, material = fixture((0, 0, 255, 255))
    by_pid = objects(environment)
    game_object = by_pid[renderer.read_typetree()["m_GameObject"]["m_PathID"]]
    game_tree = game_object.read_typetree()
    game_tree["m_Name"] = "Body"
    game_object.save_typetree(game_tree)
    identities = {"renderer": renderer.path_id, "mesh": mesh.path_id, "material": material.path_id}
    if shared_renderer:
        other_tree = renderer.read_typetree()
        other_tree["m_GameObject"] = pointer(800)
        hair_tree = deepcopy(game_tree)
        hair_tree.update(m_Name="Hair", m_Component=[{"component": pointer(801)}])
        cpt._make_object(renderer.assets_file, game_object, 800, hair_tree)
        cpt._make_object(renderer.assets_file, renderer, 801, other_tree)
        identities["other"] = 801
    if controllers:
        for pid, name in ((810, "LiveCoreMemberAmbient"), (820, "LiveCoreMemberRimlight")):
            add_component(environment, pid, name, {"materials": [pointer(material.path_id)]})
        identities.update(ambient=810, rimlight=820)
    if head:
        add_component(environment, 830, "BodyPartManager", {"headMaterial": pointer(material.path_id)},
                      namespace="LLAS.Components.Members")
        identities["head"] = 830
    if spoof:
        add_component(environment, 840, "LiveCoreMemberRimlight", {"materials": [pointer(material.path_id)]},
                      namespace="Unrelated.Components")
        identities["spoof"] = 840
    return reopen(environment), identities


class GraftSharedAssetsTests(unittest.TestCase):
    def bake(self, environment, identities, donor):
        by_pid = objects(environment)
        renderer = by_pid[identities["renderer"]]
        tree = renderer.read_typetree()
        mesh = by_pid[tree["m_Mesh"]["m_PathID"]]
        mesh_tree = append_group(mesh.read_typetree())
        donor_material = next(obj for obj in donor.objects if obj.type.name == "Material")
        stats = bake_renderer_for_game(environment, renderer, mesh, mesh_tree=mesh_tree,
            renderer_tree=tree, additional_sources=[(donor, donor_material.path_id)], reuse_empty_uv=False)
        return stats, mesh_tree, tree

    def test_shared_mesh_material_face_and_lighting_bindings_survive_repeat_reload(self):
        target, ids = shared_fixture(spoof=True)
        donor, _, _, _ = fixture((255, 0, 0, 255))
        before, donor_before = raw_objects(target), raw_objects(donor)
        stats, mesh_tree, renderer_tree = self.bake(target, ids, donor)
        self.assertTrue(stats["detached_mesh"])
        self.assertTrue(stats["detached_material"])
        self.assertEqual(len(mesh_tree["m_SubMeshes"]), 1)
        self.assertEqual(len(renderer_tree["m_Materials"]), 1)
        mesh_pid = renderer_tree["m_Mesh"]["m_PathID"]
        material_pid = renderer_tree["m_Materials"][0]["m_PathID"]
        self.assertNotEqual(mesh_pid, ids["mesh"])
        self.assertNotEqual(material_pid, ids["material"])
        saved = reopen(target)
        saved_objects, after = objects(saved), raw_objects(saved)
        for identity, data in before.items():
            if identity not in {ids["renderer"], ids["ambient"], ids["rimlight"]}:
                self.assertEqual(after[identity], data, identity)
        self.assertEqual(saved_objects[ids["other"]].read_typetree()["m_Mesh"], pointer(ids["mesh"]))
        self.assertEqual(saved_objects[ids["other"]].read_typetree()["m_Materials"], [pointer(ids["material"])])
        self.assertEqual(saved_objects[ids["head"]].read_typetree()["headMaterial"], pointer(ids["material"]))
        self.assertEqual(saved_objects[ids["spoof"]].read_typetree()["materials"], [pointer(ids["material"])])
        for name in ("ambient", "rimlight"):
            self.assertEqual(saved_objects[ids[name]].read_typetree()["materials"],
                             [pointer(ids["material"]), pointer(material_pid)])
        atlas_pointer = dict(saved_objects[material_pid].read_typetree()["m_SavedProperties"]["m_TexEnvs"])["_MainTex"]["m_Texture"]
        image = saved_objects[atlas_pointer["m_PathID"]].read().image.convert("RGBA")
        self.assertEqual(image.width * image.height, 8)
        self.assertEqual(sorted(map(tuple, np.asarray(image).reshape(-1, 4))),
                         sorted([(0, 0, 255, 255)] * 4 + [(255, 0, 0, 255)] * 4))
        before_repeat = raw_objects(saved)
        counts = {kind: sum(obj.type.name == kind for obj in saved.objects) for kind in ("Mesh", "Material")}
        repeated, _, repeated_renderer = self.bake(saved, ids, donor)
        self.assertFalse(repeated["detached_mesh"])
        self.assertFalse(repeated["detached_material"])
        self.assertEqual(repeated_renderer["m_Mesh"], pointer(mesh_pid))
        self.assertEqual(repeated_renderer["m_Materials"], [pointer(material_pid)])
        final = reopen(saved)
        final_objects, final_raw = objects(final), raw_objects(final)
        for kind, count in counts.items():
            self.assertEqual(sum(obj.type.name == kind for obj in final.objects), count)
        for identity in (ids["mesh"], ids["material"], ids["other"], ids["head"], ids["spoof"], ids["ambient"], ids["rimlight"]):
            self.assertEqual(final_raw[identity], before_repeat[identity], identity)
        self.assertEqual(len(final_objects[mesh_pid].read_typetree()["m_SubMeshes"]), 1)
        self.assertEqual(raw_objects(donor), donor_before)

    def test_lighting_registration_alone_does_not_detach_body_material(self):
        target, ids = shared_fixture(shared_renderer=False, head=False)
        donor, _, _, _ = fixture((255, 0, 0, 255))
        before = raw_objects(target)
        stats, _, renderer_tree = self.bake(target, ids, donor)
        self.assertFalse(stats["detached_mesh"])
        self.assertFalse(stats["detached_material"])
        self.assertEqual(renderer_tree["m_Materials"], [pointer(ids["material"])])
        after = raw_objects(reopen(target))
        for name in ("ambient", "rimlight"):
            self.assertEqual(after[ids[name]], before[ids[name]])

    def test_runtime_face_material_reference_requires_detachment_without_another_renderer(self):
        target, ids = shared_fixture(shared_renderer=False)
        donor, _, _, _ = fixture((255, 0, 0, 255))
        before = raw_objects(target)
        stats, _, renderer_tree = self.bake(target, ids, donor)
        self.assertFalse(stats["detached_mesh"])
        self.assertTrue(stats["detached_material"])
        self.assertEqual(renderer_tree["m_Mesh"], pointer(ids["mesh"]))
        after = raw_objects(reopen(target))
        for name in ("head", "material"):
            self.assertEqual(after[ids[name]], before[ids[name]])

    def test_partial_texture_mesh_or_material_clone_failure_is_atomic(self):
        for kind in ("Texture2D", "Mesh", "Material"):
            with self.subTest(kind=kind):
                target, ids = shared_fixture()
                donor, _, _, donor_material = fixture((255, 0, 0, 255))
                by_pid = objects(target)
                renderer, mesh = by_pid[ids["renderer"]], by_pid[ids["mesh"]]
                mesh_tree = append_group(mesh.read_typetree())
                renderer_tree = renderer.read_typetree()
                before, donor_before = raw_objects(target), raw_objects(donor)
                before_bundle = target.file.save(packer="original")
                pending = {obj.path_id: obj.data for obj in target.objects}
                original_mesh, original_renderer = deepcopy(mesh_tree), deepcopy(renderer_tree)
                make = cpt._make_object
                def fail_after_clone(sf, template, pid, tree):
                    result = make(sf, template, pid, tree)
                    if template.type.name == kind:
                        raise RuntimeError("partial clone failed")
                    return result
                with patch.object(cpt, "_make_object", side_effect=fail_after_clone):
                    with self.assertRaisesRegex(RuntimeError, "partial clone failed"):
                        bake_renderer_for_game(target, renderer, mesh, mesh_tree=mesh_tree,
                            renderer_tree=renderer_tree, additional_sources=[(donor, donor_material.path_id)],
                            reuse_empty_uv=False)
                self.assertEqual(raw_objects(target), before)
                self.assertEqual(target.file.save(packer="original"), before_bundle)
                self.assertEqual({obj.path_id: obj.data for obj in target.objects}, pending)
                self.assertEqual(mesh_tree, original_mesh)
                self.assertEqual(renderer_tree, original_renderer)
                self.assertEqual(raw_objects(donor), donor_before)

    def test_second_lighting_controller_serialization_failure_rolls_back_every_write(self):
        target, ids = shared_fixture()
        donor, _, _, donor_material = fixture((255, 0, 0, 255))
        by_pid = objects(target)
        renderer, mesh = by_pid[ids["renderer"]], by_pid[ids["mesh"]]
        mesh_tree = append_group(mesh.read_typetree())
        renderer_tree = renderer.read_typetree()
        before = raw_objects(target)
        before_bundle = target.file.save(packer="original")
        pending = {obj.path_id: obj.data for obj in target.objects}
        original_mesh, original_renderer = deepcopy(mesh_tree), deepcopy(renderer_tree)
        save = ObjectReader.save_typetree
        saved_controllers = []
        def fail_after_save(obj, tree, *args, **kwargs):
            result = save(obj, tree, *args, **kwargs)
            if obj.path_id in (ids["ambient"], ids["rimlight"]):
                saved_controllers.append(obj.path_id)
                if len(saved_controllers) == 2:
                    raise RuntimeError("controller serialization failed")
            return result
        with patch.object(ObjectReader, "save_typetree", new=fail_after_save):
            with self.assertRaisesRegex(RuntimeError, "controller serialization failed"):
                bake_renderer_for_game(target, renderer, mesh, mesh_tree=mesh_tree,
                    renderer_tree=renderer_tree, additional_sources=[(donor, donor_material.path_id)],
                    reuse_empty_uv=False)
        self.assertEqual(set(saved_controllers), {ids["ambient"], ids["rimlight"]})
        self.assertEqual(raw_objects(target), before)
        self.assertEqual(target.file.save(packer="original"), before_bundle)
        self.assertEqual({obj.path_id: obj.data for obj in target.objects}, pending)
        self.assertEqual(mesh_tree, original_mesh)
        self.assertEqual(renderer_tree, original_renderer)

    def test_isolated_mesh_renderer_serialization_failure_restores_bundle(self):
        target, ids = shared_fixture()
        by_pid = objects(target)
        renderer, mesh = by_pid[ids["renderer"]], by_pid[ids["mesh"]]
        tree = append_group(mesh.read_typetree())
        untouched = deepcopy(tree)
        before = raw_objects(target)
        before_bundle = target.file.save(packer="original")
        save = ObjectReader.save_typetree
        def fail_after_save(obj, values, *args, **kwargs):
            result = save(obj, values, *args, **kwargs)
            if obj is renderer:
                raise RuntimeError("isolation renderer failed")
            return result
        with patch.object(ObjectReader, "save_typetree", new=fail_after_save):
            with self.assertRaisesRegex(RuntimeError, "isolation renderer failed"):
                save_isolated_mesh(target, renderer, mesh, tree)
        self.assertEqual(raw_objects(target), before)
        self.assertEqual(target.file.save(packer="original"), before_bundle)
        self.assertEqual(tree, untouched)

    def test_shared_mesh_with_independent_material_keeps_identity_texture_path(self):
        target, ids = shared_fixture(controllers=False, head=False)
        by_pid = objects(target)
        material = by_pid[ids["material"]]
        cpt._make_object(material.assets_file, material, 850, material.read_typetree())
        other = by_pid[ids["other"]]
        other_tree = other.read_typetree()
        other_tree["m_Materials"] = [pointer(850)]
        other.save_typetree(other_tree)
        target = reopen(target)
        by_pid = objects(target)
        renderer, mesh = by_pid[ids["renderer"]], by_pid[ids["mesh"]]
        mesh_tree = append_group(mesh.read_typetree())
        renderer_tree = renderer.read_typetree()
        before = raw_objects(target)
        stats = bake_renderer_for_game(target, renderer, mesh, mesh_tree=mesh_tree,
            renderer_tree=renderer_tree, additional_sources=[(target, ids["material"])])
        self.assertTrue(stats["atlas_identity"])
        self.assertTrue(stats["detached_mesh"])
        self.assertFalse(stats["detached_material"])
        self.assertEqual(stats["atlas_textures"], 0)
        self.assertEqual(renderer_tree["m_Materials"], [pointer(ids["material"])])
        self.assertNotEqual(renderer_tree["m_Mesh"], pointer(ids["mesh"]))
        final = reopen(target)
        final_raw = raw_objects(final)
        self.assertEqual(sum(obj.type.name == "Material" for obj in final.objects), 2)
        for identity, data in before.items():
            if identity != ids["renderer"]:
                self.assertEqual(final_raw[identity], data, identity)

    def test_part_graft_preserves_shared_original_before_atlas_publication(self):
        target, ids = shared_fixture()
        donor, donor_renderer, _, _ = fixture((255, 0, 0, 255))
        before = raw_objects(target)
        with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="shared-part-test-") as directory:
            root = Path(directory)
            target_path, donor_path, output = (root / name for name in ("target.unity", "donor.unity", "output.unity"))
            target_bytes, donor_bytes = target.file.save(packer="original"), donor.file.save(packer="original")
            target_path.write_bytes(target_bytes)
            donor_path.write_bytes(donor_bytes)
            cpt.transplant_part(str(donor_path), str(target_path), str(output), triangle_indices=[0],
                new_submesh="atlas", reuse_empty_uv=False, donor_renderer=donor_renderer.path_id,
                target_renderer=ids["renderer"], worldspace=False, fix_nodescaling=False,
                verbose=False, log_callback=lambda message: None)
            final = UnityPy.load(str(output))
            self.assertEqual(target_path.read_bytes(), target_bytes)
            self.assertEqual(donor_path.read_bytes(), donor_bytes)
        final_objects, final_raw = objects(final), raw_objects(final)
        for name in ("mesh", "material", "other", "head"):
            self.assertEqual(final_raw[ids[name]], before[ids[name]], name)
        body = final_objects[ids["renderer"]].read_typetree()
        self.assertNotEqual(body["m_Mesh"], pointer(ids["mesh"]))
        self.assertEqual(len(body["m_Materials"]), 1)
        body_mesh = final_objects[body["m_Mesh"]["m_PathID"]].read_typetree()
        self.assertEqual(len(body_mesh["m_SubMeshes"]), 1)
        self.assertEqual(body_mesh["m_SubMeshes"][0]["indexCount"],
                         objects(target)[ids["mesh"]].read_typetree()["m_SubMeshes"][0]["indexCount"] + 3)
        for name in ("ambient", "rimlight"):
            self.assertEqual(final_objects[ids[name]].read_typetree()["materials"],
                             [pointer(ids["material"]), body["m_Materials"][0]])

    def test_lower_graft_preserves_shared_original_before_intermediate_bundle_reload(self):
        target, ids = shared_fixture()
        donor, _, _, _ = fixture((255, 0, 0, 255))
        before = raw_objects(target)
        with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="shared-lower-test-") as directory:
            root = Path(directory)
            target_path, donor_path, output = (root / name for name in ("target.unity", "donor.unity", "output.unity"))
            target_bytes, donor_bytes = target.file.save(packer="original"), donor.file.save(packer="original")
            target_path.write_bytes(target_bytes)
            donor_path.write_bytes(donor_bytes)
            lower_body_swap._graft_materials(str(target_path), str(donor_path), str(output), .5, .96,
                "lower", True, "skin", None, ids["renderer"], False, lambda message: None)
            final = UnityPy.load(str(output))
            self.assertEqual(target_path.read_bytes(), target_bytes)
            self.assertEqual(donor_path.read_bytes(), donor_bytes)
        final_objects, final_raw = objects(final), raw_objects(final)
        for name in ("mesh", "material", "other", "head"):
            self.assertEqual(final_raw[ids[name]], before[ids[name]], name)
        body = final_objects[ids["renderer"]].read_typetree()
        self.assertNotEqual(body["m_Mesh"], pointer(ids["mesh"]))
        self.assertEqual(len(body["m_Materials"]), 1)
        self.assertEqual(len(final_objects[body["m_Mesh"]["m_PathID"]].read_typetree()["m_SubMeshes"]), 1)
        for name in ("ambient", "rimlight"):
            self.assertEqual(final_objects[ids[name]].read_typetree()["materials"],
                             [pointer(ids["material"]), body["m_Materials"][0]])

    def test_default_worldspace_normalizes_selected_body_and_preserves_earlier_shared_hair(self):
        target, ids = shared_fixture()
        by_pid = objects(target)
        renderer, mesh = by_pid[ids["renderer"]], by_pid[ids["mesh"]]
        # Hair sorts before Body after a real bundle reopen and has the same
        # bone count. A most-bones-first postprocessor would select Hair.
        hair = by_pid[ids["other"]]
        cpt._make_object(renderer.assets_file, hair, -1000, hair.read_typetree())
        renderer.assets_file.objects.pop(hair.path_id)
        hair_game = by_pid[800]
        hair_tree = hair_game.read_typetree()
        hair_tree["m_Component"] = [{"component": pointer(-1000)}]
        hair_game.save_typetree(hair_tree)
        ids["other"] = -1000
        # Give both shared consumers an actual nonidentity mesh root, ensuring
        # normalization performs a write instead of silently taking its no-op.
        mesh_tree = mesh.read_typetree()
        translation = np.eye(4)
        translation[0, 3] = .3
        for bind_pose in mesh_tree["m_BindPose"]:
            cpt.mat_to(cpt.mat_from(bind_pose) @ translation, bind_pose)
        mesh.save_typetree(mesh_tree)
        target = reopen(target)
        by_pid = objects(target)
        order = [obj.path_id for obj in target.objects if obj.type.name == "SkinnedMeshRenderer"]
        self.assertLess(order.index(ids["other"]), order.index(ids["renderer"]))
        np.testing.assert_allclose(cpt._mesh_root_world(target, by_pid[ids["renderer"]].read_typetree()),
                                   translation, atol=1e-6)
        before = raw_objects(target)
        donor, donor_renderer, _, _ = fixture((255, 0, 0, 255))
        with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="worldspace-shared-part-") as directory:
            root = Path(directory)
            target_path, donor_path, output = (root / name for name in ("target.unity", "donor.unity", "output.unity"))
            target_bytes, donor_bytes = target.file.save(packer="original"), donor.file.save(packer="original")
            target_path.write_bytes(target_bytes)
            donor_path.write_bytes(donor_bytes)
            cpt.transplant_part(str(donor_path), str(target_path), str(output), triangle_indices=[0],
                new_submesh="atlas", reuse_empty_uv=False, donor_renderer=donor_renderer.path_id,
                target_renderer=ids["renderer"], fix_nodescaling=False,
                verbose=False, log_callback=lambda message: None)
            final = UnityPy.load(str(output))
            self.assertEqual(target_path.read_bytes(), target_bytes)
            self.assertEqual(donor_path.read_bytes(), donor_bytes)
        final_objects, final_raw = objects(final), raw_objects(final)
        for name in ("mesh", "material", "other", "head"):
            self.assertEqual(final_raw[ids[name]], before[ids[name]], name)
        body = final_objects[ids["renderer"]].read_typetree()
        self.assertNotEqual(body["m_Mesh"], pointer(ids["mesh"]))
        self.assertEqual(len(body["m_Materials"]), 1)
        self.assertEqual(len(final_objects[body["m_Mesh"]["m_PathID"]].read_typetree()["m_SubMeshes"]), 1)
        np.testing.assert_allclose(cpt._mesh_root_world(final, body), np.eye(4), atol=1e-6)
        for name in ("ambient", "rimlight"):
            self.assertEqual(final_objects[ids[name]].read_typetree()["materials"],
                             [pointer(ids["material"]), body["m_Materials"][0]])


class LowerBodyRendererSelectionTests(unittest.TestCase):
    def test_gameobject_body_wins_over_orphan_mesh_name_and_earlier_shared_hair_renderer(self):
        target, ids = shared_fixture(controllers=False, head=False)
        by_pid = objects(target)
        mesh = by_pid[ids["mesh"]]
        orphan = mesh.read_typetree()
        orphan["m_Name"] = "Body"
        cpt._make_object(mesh.assets_file, mesh, 790, orphan)
        target = reopen(target)
        by_pid = objects(target)
        self.assertEqual(by_pid[790].read_typetree()["m_Name"], "Body")
        # Serialized object ordering puts Hair before Body, independent of the
        # shared Mesh's misleading name and the unreferenced duplicate.
        hair = by_pid[ids["other"]]
        hair.assets_file.objects = {**{hair.path_id: hair}, **{pid: obj for pid, obj in hair.assets_file.objects.items() if pid != hair.path_id}}
        selected = lower_body_swap.BodyMesh(target, "synthetic.unity")
        self.assertEqual(selected.smr_obj.path_id, ids["renderer"])
        self.assertEqual(selected.mesh_obj.path_id, ids["mesh"])
        for selector in (cpt._body_smr, costume_transplant._body_smr):
            with self.subTest(selector=selector.__module__):
                self.assertEqual(selector(target.objects).path_id, ids["renderer"])
        explicit = lower_body_swap.BodyMesh(target, "synthetic.unity", ids["other"])
        self.assertEqual(explicit.smr_obj.path_id, ids["other"])
        self.assertEqual(explicit.mesh_obj.path_id, ids["mesh"])

    def test_equal_unnamed_candidates_require_an_explicit_renderer(self):
        target, ids = shared_fixture(controllers=False, head=False)
        by_pid = objects(target)
        renderer = by_pid[ids["renderer"]]
        game = by_pid[renderer.read_typetree()["m_GameObject"]["m_PathID"]]
        tree = game.read_typetree()
        tree["m_Name"] = "FirstSurface"
        game.save_typetree(tree)
        target = reopen(target)
        with self.assertRaisesRegex(ValueError, "ambiguous|Choose|choose|several|multiple"):
            lower_body_swap.BodyMesh(target, "synthetic.unity")
        for selector in (cpt._body_smr, costume_transplant._body_smr):
            with self.subTest(selector=selector.__module__):
                with self.assertRaisesRegex(ValueError, "ambiguous|Choose|choose|several|multiple"):
                    selector(target.objects)
        selected = lower_body_swap.BodyMesh(target, "synthetic.unity", ids["renderer"])
        self.assertEqual(selected.smr_obj.path_id, ids["renderer"])

    def test_explicit_part_selection_bypasses_duplicate_body_gameobject_ambiguity(self):
        target, ids = shared_fixture(controllers=False, head=False)
        by_pid = objects(target)
        renderer = by_pid[ids["renderer"]]
        duplicate_pid = 860
        cpt._make_object(renderer.assets_file, renderer, duplicate_pid, renderer.read_typetree())
        game = by_pid[renderer.read_typetree()["m_GameObject"]["m_PathID"]]
        game_tree = game.read_typetree()
        game_tree["m_Component"].append({"component": pointer(duplicate_pid)})
        game.save_typetree(game_tree)
        target = reopen(target)
        for selector in (cpt._body_smr, costume_transplant._body_smr):
            with self.subTest(selector=selector.__module__):
                with self.assertRaisesRegex(ValueError, "Several renderers"):
                    selector(target.objects)
        with self.assertRaisesRegex(ValueError, "Several renderers"):
            lower_body_swap.BodyMesh(target, "ambiguous.unity")
        explicit = lower_body_swap.BodyMesh(target, "ambiguous.unity", ids["renderer"])
        self.assertEqual(explicit.smr_obj.path_id, ids["renderer"])
        before = raw_objects(target)
        with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="explicit-part-test-") as directory:
            root = Path(directory)
            target_path, donor_path, output = (root / name for name in ("target.unity", "donor.unity", "output.unity"))
            source_bytes = target.file.save(packer="original")
            target_path.write_bytes(source_bytes)
            donor_path.write_bytes(source_bytes)
            cpt.transplant_part(str(donor_path), str(target_path), str(output), triangle_indices=[0],
                new_submesh="atlas", reuse_empty_uv=False, donor_renderer=ids["renderer"],
                target_renderer=ids["renderer"], worldspace=False, fix_nodescaling=False,
                verbose=False, log_callback=lambda message: None)
            final = UnityPy.load(str(output))
            self.assertEqual(target_path.read_bytes(), source_bytes)
            self.assertEqual(donor_path.read_bytes(), source_bytes)
        final_objects, final_raw = objects(final), raw_objects(final)
        for identity in (ids["mesh"], ids["material"], ids["other"], duplicate_pid):
            self.assertEqual(final_raw[identity], before[identity], identity)
        body = final_objects[ids["renderer"]].read_typetree()
        self.assertNotEqual(body["m_Mesh"], pointer(ids["mesh"]))
        self.assertEqual(len(body["m_Materials"]), 1)
        self.assertEqual(len(final_objects[body["m_Mesh"]["m_PathID"]].read_typetree()["m_SubMeshes"]), 1)


if __name__ == "__main__":
    unittest.main()
