"""Serialized main/LOD graph and unweighted-tip regression for costume grafts."""
import copy
import json
import random
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import UnityPy
import costume_transplant as full
import costume_part_transplant as part
from generate_viewer_physics_fixture import fixture_bytes
from webtools.core import model_edits, viewer_physics
from test_viewer_transplants import costume_fixture


def as_bundle(raw):
    """Wrap the neutral standalone SerializedFile in a genuine UnityFS."""
    version = UnityPy.load(raw).file.unity_version
    entry = b"CAB-neutral-physics\0"
    info = bytes(16) + struct.pack(">iIIHi", 1, len(raw), len(raw), 0, 1)
    info += struct.pack(">qqI", 0, len(raw), 0) + entry
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + version.encode() + b"\0"
    return prefix + struct.pack(">QIII", len(prefix) + 20 + len(info) + len(raw), len(info), len(info), 64) + info + raw


def donor_chain():
    env = UnityPy.load(fixture_bytes(native=True))
    objects = {obj.path_id: obj for obj in env.objects}
    asset = objects[221].assets_file
    def ptr(n): return {"m_FileID": 0, "m_PathID": n}
    for ident, name in ((200, "TailA1_Dyna"), (210, "TailA_End")):
        tree = objects[ident].read_typetree(); tree["m_Name"] = name
        objects[ident].save_typetree(tree)
    for source, ident in ((200, 250), (201, 251), (221, 252)):
        obj = copy.copy(objects[source]); obj.path_id = ident
        asset.objects[ident] = obj
        tree = objects[source].read_typetree()
        if ident == 250:
            tree.update(m_Name="TailA2_Dyna", m_Component=[{"component": ptr(251)}, {"component": ptr(252)}])
        elif ident == 251:
            tree.update(m_GameObject=ptr(250), m_Father=ptr(201), m_Children=[ptr(211)],
                        m_LocalPosition={"x": -.04, "y": 0., "z": 0.})
        else:
            tree.update(m_GameObject=ptr(250), child=ptr(211), sibling=ptr(0), parentIndex=0, childIndex=-1,
                        siblingIndex=-1, enableLod=True)
        obj.save_typetree(tree)
    tree = objects[201].read_typetree(); tree["m_Children"] = [ptr(209), ptr(251)]
    objects[201].save_typetree(tree)
    tree = objects[211].read_typetree(); tree["m_Father"] = ptr(251)
    tree["m_LocalPosition"] = {"x": -.04, "y": 0., "z": 0.}
    objects[211].save_typetree(tree)
    tree = objects[221].read_typetree()
    tree.update(child=ptr(251), sibling=ptr(252), childIndex=1, siblingIndex=1, parentIndex=-1, enableLod=True)
    objects[221].save_typetree(tree)
    tree = objects[228].read_typetree(); tree.update(bones=[], lodBones=[ptr(221), ptr(252)])
    objects[228].save_typetree(tree)
    return env.file.save(packer="original")


def shared_skirt_and_tail():
    """A shared native skirt plus two weighted donor-only SwingBone links."""
    def ptr(n): return {"m_FileID": 0, "m_PathID": n}
    target = UnityPy.load(fixture_bytes(native=True))
    target_index = {obj.path_id: obj for obj in target.objects}
    for pid, name in ((200, "SkirtA1_Dyna"), (210, "SkirtA_End")):
        tree = target_index[pid].read_typetree()
        tree["m_Name"] = name
        target_index[pid].save_typetree(tree)
    donor = UnityPy.load(donor_chain())
    donor_index = {obj.path_id: obj for obj in donor.objects}
    asset = donor_index[221].assets_file
    for source_pid, new_pid in ((200, 270), (201, 271), (221, 272), (210, 280), (211, 281)):
        template = donor_index[source_pid]
        tree = template.read_typetree()
        if new_pid == 270:
            tree.update(m_Name="SkirtA1_Dyna", m_Component=[{"component": ptr(271)}, {"component": ptr(272)}])
        elif new_pid == 271:
            tree.update(m_GameObject=ptr(270), m_Father=ptr(9), m_Children=[ptr(281)])
        elif new_pid == 272:
            tree.update(m_GameObject=ptr(270), child=ptr(281), sibling=ptr(0),
                        parentIndex=-1, childIndex=-1, siblingIndex=-1,
                        enableLod=False, stiffnessForce=.73)
        elif new_pid == 280:
            tree.update(m_Name="SkirtA_End", m_Component=[{"component": ptr(281)}])
        else:
            tree.update(m_GameObject=ptr(280), m_Father=ptr(271), m_Children=[])
        full._make_object(asset, template, new_pid, tree)
    tree = donor_index[9].read_typetree()
    tree["m_Children"].append(ptr(271))
    donor_index[9].save_typetree(tree)
    tree = donor_index[228].read_typetree()
    tree["bones"] = [ptr(272)]
    donor_index[228].save_typetree(tree)
    # Full transplant discovers missing physics from the donor skin's bone
    # list. Weight both tail links and the shared skirt in actual mesh data.
    renderer = donor_index[12].read_typetree()
    renderer["m_Bones"].extend([ptr(271), ptr(201), ptr(251)])
    donor_index[12].save_typetree(renderer)
    mesh = donor_index[1].read_typetree()
    root_local = donor_index[201].read_typetree()
    second_local = donor_index[251].read_typetree()
    def local_translation(tree):
        matrix = np.eye(4)
        matrix[:3, 3] = [tree["m_LocalPosition"][axis] for axis in "xyz"]
        return matrix
    first_pose = np.linalg.inv(local_translation(root_local)) @ part.mat_from(mesh["m_BindPose"][2])
    second_pose = np.linalg.inv(local_translation(second_local)) @ first_pose
    mesh["m_BindPose"].extend([part._mat_dict(first_pose), part._mat_dict(first_pose), part._mat_dict(second_pose)])
    count, channels, strides, starts, _ = part.stream_layout(mesh)
    data = bytearray(mesh["m_VertexData"]["m_DataSize"])
    weights = np.tile([1., 0., 0., 0.], (count, 1))
    bone_ids = np.zeros((count, 4), dtype=int)
    bone_ids[:3, 0], bone_ids[3:, 0] = 4, 5
    weights[0], bone_ids[0] = [.5, .5, 0., 0.], [3, 4, 0, 0]
    part.write_attr(np.frombuffer(data, np.uint8), weights, part.ATTR_BLENDWEIGHT, channels, strides, starts, count)
    part.write_attr(np.frombuffer(data, np.uint8), bone_ids, part.ATTR_BLENDINDICES, channels, strides, starts, count)
    mesh["m_VertexData"]["m_DataSize"] = bytes(data)
    donor_index[1].save_typetree(mesh)
    return as_bundle(target.file.save(packer="original")), as_bundle(donor.file.save(packer="original"))


class TransplantPhysicsGraphTests(unittest.TestCase):
    def test_shared_native_physics_sync_keeps_pending_injected_chain_bytes_and_siblings(self):
        target_raw, donor_raw = shared_skirt_and_tail()
        donor, target = UnityPy.load(donor_raw), UnityPy.load(target_raw)
        native_objects, target_index = part._index(target)
        native_ids = set(target_index)
        names, children = full.inject_appendage_bones(donor, target, ["TailA1_Dyna"],
            part._name2transform(target_index), restore_collision=False)
        part.wire_child_adds(target_index, children)
        injected = {obj.path_id: obj.data for obj in target.objects
                    if obj.path_id not in native_ids and obj.type.name == "MonoBehaviour"}
        self.assertEqual(len(injected), 2)
        self.assertTrue(all(data is not None for data in injected.values()))
        count = full.sync_costume_swing_physics(donor, target, ["SkirtA1_Dyna", "TailA1_Dyna", "TailA2_Dyna"],
            restore_collision=False, target_objects=native_objects)
        self.assertEqual(count, 1)
        pending = {obj.path_id: obj.data for obj in target.objects}
        for pid, data in injected.items():
            self.assertEqual(pending[pid], data, pid)
        saved = UnityPy.load(target.file.save(packer="original"))
        _, saved_index = part._index(saved)
        for pid, data in injected.items():
            self.assertEqual(saved_index[pid].get_raw_data(), data, pid)
        native = saved_index[221].read_typetree()
        self.assertAlmostEqual(native["stiffnessForce"], .73, places=6)
        self.assertEqual(native["m_GameObject"]["m_PathID"], 200)
        self.assertEqual(native["child"]["m_PathID"], 211)
        self.assertEqual(native["sibling"]["m_PathID"], 0)
        with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="native-swing-sync-") as temporary:
            root = Path(temporary)
            donor_path, target_path, output = (root / name for name in ("donor.unity", "target.unity", "output.unity"))
            donor_path.write_bytes(donor_raw)
            target_path.write_bytes(target_raw)
            output.write_bytes(saved.file.save(packer="original"))
            full.repair_transplant_physics(str(output), str(donor_path), str(target_path), names,
                restore_collision=False, verbose=False)
            self.assertTrue(full.validate(str(output), verbose=False))
            repaired = UnityPy.load(str(output))
            repaired_objects, repaired_index = part._index(repaired)
            scripts = part._scriptname_map(repaired_objects)
            swings = {part._go_name(repaired_index, obj.read_typetree()["m_GameObject"]["m_PathID"]): obj
                      for obj in repaired_objects if obj.type.name == "MonoBehaviour"
                      and scripts.get(obj.read_typetree()["m_Script"]["m_PathID"]) == "SwingBone"}
            first, second = swings["TailA1_Dyna"], swings["TailA2_Dyna"]
            self.assertEqual(first.read_typetree()["sibling"]["m_PathID"], second.path_id)
            self.assertEqual(repaired_index[first.read_typetree()["sibling"]["m_PathID"]].type.name, "MonoBehaviour")
            self.assertEqual(donor_path.read_bytes(), donor_raw)
            self.assertEqual(target_path.read_bytes(), target_raw)

    def test_full_transplant_syncs_native_skirt_without_overwriting_weighted_new_tail(self):
        target_raw, donor_raw = shared_skirt_and_tail()
        sync = full.sync_costume_swing_physics
        calls = []
        def capture(donor, target, names, *args, **kwargs):
            snapshot = kwargs.get("target_objects")
            self.assertIsNotNone(snapshot, "Full transplant must keep its pre-injection native snapshot")
            native_ids = {obj.path_id for obj in snapshot}
            injected = {obj.path_id: obj.data for obj in target.objects
                        if obj.path_id not in native_ids and obj.type.name == "MonoBehaviour"}
            self.assertEqual(len(injected), 2)
            result = sync(donor, target, names, *args, **kwargs)
            self.assertEqual(result, 1)
            current = {obj.path_id: obj.data for obj in target.objects}
            for pid, data in injected.items():
                self.assertEqual(current[pid], data, pid)
            calls.append(set(injected))
            return result
        with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="full-native-swing-sync-") as temporary:
            root = Path(temporary)
            donor_path, target_path, output = (root / name for name in ("donor.unity", "target.unity", "output.unity"))
            donor_path.write_bytes(donor_raw)
            target_path.write_bytes(target_raw)
            with patch.object(full, "sync_costume_swing_physics", side_effect=capture):
                full.transplant(str(donor_path), str(target_path), str(output), verbose=False,
                    preserve_physics=True, restore_collision=False)
            self.assertEqual(len(calls), 1)
            self.assertTrue(full.validate(str(output), verbose=False))
            self.assertTrue(part.validate(str(output), verbose=False))
            saved = UnityPy.load(str(output))
            saved_objects, index = part._index(saved)
            scripts = part._scriptname_map(saved_objects)
            swings = {part._go_name(index, obj.read_typetree()["m_GameObject"]["m_PathID"]): obj
                      for obj in saved_objects if obj.type.name == "MonoBehaviour"
                      and scripts.get(obj.read_typetree()["m_Script"]["m_PathID"]) == "SwingBone"}
            self.assertTrue({"SkirtA1_Dyna", "TailA1_Dyna", "TailA2_Dyna"} <= set(swings))
            self.assertAlmostEqual(swings["SkirtA1_Dyna"].read_typetree()["stiffnessForce"], .73, places=6)
            first, second = swings["TailA1_Dyna"], swings["TailA2_Dyna"]
            self.assertEqual({first.path_id, second.path_id}, calls[0])
            self.assertEqual(first.read_typetree()["sibling"]["m_PathID"], second.path_id)
            donor_index = part._index(UnityPy.load(donor_raw))[1]
            for field in ("childIndex", "siblingIndex"):
                self.assertEqual(first.read_typetree()[field], donor_index[221].read_typetree()[field])
            self.assertEqual(second.read_typetree()["parentIndex"], donor_index[252].read_typetree()["parentIndex"])
            manager = full._find_swingbone_manager(saved_objects, scripts).read_typetree()
            self.assertEqual([row["m_PathID"] for row in manager["bones"]], [swings["SkirtA1_Dyna"].path_id])
            self.assertEqual([row["m_PathID"] for row in manager["lodBones"]], [first.path_id, second.path_id])
            renderer = part._body_smr(saved_objects).read_typetree()
            mesh = index[renderer["m_Mesh"]["m_PathID"]].read_typetree()
            self.assertEqual(len(renderer["m_Bones"]), 6)
            self.assertEqual(len(mesh["m_BindPose"]), 6)
            count, channels, strides, starts, _ = part.stream_layout(mesh)
            weights, bone_ids = part.get_skin(np.frombuffer(bytes(mesh["m_VertexData"]["m_DataSize"]), np.uint8),
                mesh, channels, strides, starts, count)
            weighted = set(bone_ids[weights > 0])
            self.assertTrue({3, 4, 5} <= weighted)
            self.assertEqual(donor_path.read_bytes(), donor_raw)
            self.assertEqual(target_path.read_bytes(), target_raw)

    def test_shared_donor_keeps_saved_physics_and_provenance_without_reopening_source(self):
        target_raw, donor_raw = as_bundle(fixture_bytes(native=True)), as_bundle(donor_chain())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            donor_path, target_path = root / 'donor.unity', root / 'target.unity'
            donor_path.write_bytes(donor_raw); target_path.write_bytes(target_raw)
            donor, target = UnityPy.load(donor_raw), UnityPy.load(target_raw)
            _, index = part._index(target)
            names, children = full.inject_appendage_bones(donor, target, ['TailA1_Dyna'],
                part._name2transform(index), restore_collision=False)
            part.wire_child_adds(index, children)
            initial = target.file.save(packer='original')
            source_objects = {obj.path_id: obj.get_raw_data() for obj in donor.objects}
            real_load = UnityPy.load
            results = []
            for cached in (False, True):
                out = root / ('cached.unity' if cached else 'fresh.unity')
                out.write_bytes(initial)
                source_reads = []
                def load(value, *args, **kwargs):
                    if value == str(donor_path):
                        source_reads.append(value)
                        self.assertFalse(cached, 'A shared donor must not be opened again')
                    return real_load(value, *args, **kwargs)
                options = {'donor_environment': donor} if cached else {}
                provenance = {}
                with patch.object(UnityPy, 'load', side_effect=load):
                    full.repair_costume_swing_chain(str(out), str(donor_path), names, verbose=False, **options)
                    full.adopt_donor_body_colliders(str(out), str(donor_path), verbose=False, **options)
                    full.scale_costume_swing_lengths(str(out), str(donor_path), names, verbose=False, **options)
                    part.scale_costume_swing_lengths(str(out), str(donor_path), names, verbose=False, **options)
                    full.repair_transplant_physics(str(out), str(donor_path), str(target_path), names,
                        restore_collision=False, verbose=False, provenance=provenance, **options)
                self.assertEqual(len(source_reads), 0 if cached else 5)
                self.assertTrue(full.validate(str(out), verbose=False))
                results.append((out.read_bytes(), provenance))
            self.assertEqual(results[0], results[1])
            self.assertEqual({obj.path_id: obj.get_raw_data() for obj in donor.objects}, source_objects)
            self.assertEqual(donor_path.read_bytes(), donor_raw)
            self.assertEqual(target_path.read_bytes(), target_raw)

    def test_full_and_part_reuse_only_the_immutable_donor_and_keep_exact_output(self):
        raw = costume_fixture()
        for operation in ('full', 'part'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                donor, target = root / 'donor.unity', root / 'wearer.unity'
                donor.write_bytes(raw); target.write_bytes(raw)
                results = []
                for fresh in (True, False):
                    source_reads = []
                    real_load = UnityPy.load
                    def load(value, *args, **kwargs):
                        if value == str(donor): source_reads.append(value)
                        return real_load(value, *args, **kwargs)
                    def fallback(function):
                        def call(*args, **kwargs):
                            if fresh: kwargs['donor_environment'] = None
                            return function(*args, **kwargs)
                        return call
                    output, provenance = root / 'output.unity', {}
                    # Seed only this isolated test so injected object IDs permit
                    # an exact saved-file comparison; production IDs stay random.
                    rng = random.getstate()
                    try:
                        random.seed(47)
                        with patch.object(UnityPy, 'load', side_effect=load), \
                             patch.object(full, 'repair_costume_swing_chain', fallback(full.repair_costume_swing_chain)), \
                             patch.object(full, 'adopt_donor_body_colliders', fallback(full.adopt_donor_body_colliders)), \
                             patch.object(full, 'scale_costume_swing_lengths', fallback(full.scale_costume_swing_lengths)), \
                             patch.object(part, 'scale_costume_swing_lengths', fallback(part.scale_costume_swing_lengths)), \
                             patch.object(full, 'repair_transplant_physics', fallback(full.repair_transplant_physics)):
                            if operation == 'full':
                                full.transplant(str(donor), str(target), str(output), verbose=False,
                                    preserve_physics=True, physics_provenance=provenance)
                            else:
                                part.transplant_part(str(donor), str(target), str(output),
                                    part_root='BreastSize', verbose=False, physics_provenance=provenance)
                    finally:
                        random.setstate(rng)
                    self.assertTrue(full.validate(str(output), verbose=False))
                    results.append((output.read_bytes(), provenance, len(source_reads)))
                self.assertEqual(results[0][:2], results[1][:2])
                self.assertGreater(results[0][2], results[1][2])
                self.assertEqual(results[1][2], 1)
                self.assertEqual(donor.read_bytes(), raw)
                self.assertEqual(target.read_bytes(), raw)

    def test_full_and_part_keep_unweighted_tips_typed_siblings_and_lod_indices(self):
        target_raw, donor_raw = as_bundle(fixture_bytes(native=True)), as_bundle(donor_chain())
        for operation in ("full", "part"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                donor_path, target_path, out_path = (root / name for name in ("donor.unity", "target.unity", "out.unity"))
                donor_path.write_bytes(donor_raw); target_path.write_bytes(target_raw)
                donor, target = UnityPy.load(donor_raw), UnityPy.load(target_raw)
                _, index = part._index(target)
                names = part._name2transform(index)
                if operation == "full":
                    new, children = full.inject_appendage_bones(donor, target, ["TailA1_Dyna"], names,
                                                                 restore_collision=False)
                else:
                    new, children = part.inject_bone_chain(donor, target, ["TailA1_Dyna"], names,
                                                           restore_collision=False)
                self.assertTrue({"TailA1_Dyna", "TailA2_Dyna", "TailA_End"} <= set(new))
                part.wire_child_adds(index, children)
                out_path.write_bytes(target.file.save(packer="original"))
                origins = {}
                full.repair_transplant_physics(str(out_path), str(donor_path), str(target_path), new,
                                               restore_collision=False, verbose=False, provenance=origins)
                saved = UnityPy.load(str(out_path))
                objects, index = part._index(saved)
                scripts = part._scriptname_map(objects)
                manager = full._find_swingbone_manager(objects, scripts).read_typetree()
                self.assertEqual(len(manager["bones"]), 1)
                self.assertEqual(len(manager["lodBones"]), 2)
                by_name = {part._go_name(index, obj.read_typetree()["m_GameObject"]["m_PathID"]): obj
                           for obj in objects if obj.type.name == "MonoBehaviour"
                           and scripts.get(obj.read_typetree()["m_Script"]["m_PathID"]) == "SwingBone"}
                first, second = (by_name[name] for name in ("TailA1_Dyna", "TailA2_Dyna"))
                original_components = {row['componentId']: row for row in origins['components']}
                for component, original in ((first, '221'), (second, '252')):
                    self.assertEqual(original_components[str(component.path_id)], {
                        'componentId': str(component.path_id), 'serializedFile': 0,
                        'source': 'donor', 'sourceComponentId': original, 'sourceSerializedFile': 0})
                a, b = first.read_typetree(), second.read_typetree()
                self.assertEqual(index[a["child"]["m_PathID"]].type.name, "Transform")
                self.assertEqual(index[a["sibling"]["m_PathID"]].type.name, "MonoBehaviour")
                self.assertEqual(a["sibling"]["m_PathID"], second.path_id)
                self.assertEqual(a["childIndex"], 2)
                self.assertEqual(a["siblingIndex"], 2)
                self.assertEqual(b["parentIndex"], 1)
                endpoint = index[b["child"]["m_PathID"]]
                self.assertEqual(part._go_name(index, endpoint.read_typetree()["m_GameObject"]["m_PathID"]), "TailA_End")
                info = model_edits._inspect(out_path.read_bytes())
                bones = [{"sourceIndex": 0, "serializedFile": key[0], "transformId": str(key[1]), "node": node}
                         for node, key in enumerate(info["transforms"])]
                catalog = viewer_physics.make_catalog(viewer_physics.inspect_info(info, 0, bones),
                                                      viewer_physics.native_managers(info, 0, bones))
                self.assertTrue(catalog["native"]["available"], catalog["native"])
                records = {row["componentId"]: row for row in catalog["components"]}
                first_record, second_record = records[str(first.path_id)], records[str(second.path_id)]
                manager_record = catalog["managers"][0]
                self.assertEqual(first_record["simulation"]["manager"], manager_record["id"])
                self.assertEqual(second_record["simulation"]["manager"], manager_record["id"])
                self.assertEqual(first_record["simulation"]["order"], 1)
                self.assertEqual(second_record["simulation"]["order"], 2)
                self.assertEqual(first_record["simulation"]["child"], second_record["id"])
                self.assertEqual(second_record["simulation"]["parent"], first_record["id"])
                self.assertEqual(target_path.read_bytes(), target_raw)
                self.assertEqual(donor_path.read_bytes(), donor_raw)
                # Re-saving/re-opening must retain typed references; an in-memory
                # catalogue-only fix would fail this assertion.
                out_path.write_bytes(saved.file.save(packer="original"))
                self.assertTrue(full.validate(str(out_path), verbose=False))
                # A zero tip or a Transform used as a SwingBone sibling used
                # to pass the publication validator despite disabling physics.
                broken = UnityPy.load(str(out_path))
                _, broken_index = part._index(broken)
                data = broken_index[first.path_id].read_typetree()
                data["sibling"] = data["child"].copy()
                broken_index[first.path_id].save_typetree(data)
                out_path.write_bytes(broken.file.save(packer="original"))
                self.assertFalse(full.validate(str(out_path), verbose=False))
                self.assertFalse(part.validate(str(out_path), verbose=False))
