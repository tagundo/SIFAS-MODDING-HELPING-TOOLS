"""Serialized costume/platform rigs: relative edits, IDs, ZIPs and reloads."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import UnityPy
from webtools.core import model_edits as edits, model_viewer, viewer_archive
from webtools.core import viewer_mod_pair_edits as paired
from webtools.core import viewer_mod_sources as sources
from webtools.jobs import Job
from sifas_mesh_baker import stream_layout, read_attr, ATTR_POS


class PairedBodyEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (Path(__file__).parent / "fixtures/viewer_persistence.unity").read_bytes()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.job = Job("pair-edits", "viewer_mod_package")
        with edits._LOCK:
            edits._SESSIONS.clear()

    def fixture(self, *, other=False, offset=0, platform=13, morphs=False, missing=False, unsupported=False):
        raw = self.raw
        if morphs:
            spec = importlib.util.spec_from_file_location("paired_neutral_fixture", Path(__file__).parent / "generate_viewer_persistence_fixture.py")
            generator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(generator)
            raw = generator.fixture_bytes(morphs=True)
        env = UnityPy.load(raw)
        env.file.target_platform = platform
        env.file._m_target_platform = platform
        def remap(value):
            if isinstance(value, dict):
                if value.get("m_FileID") == 0 and value.get("m_PathID", 0) > 0:
                    value["m_PathID"] += offset
                for child in value.values():
                    remap(child)
            elif isinstance(value, list):
                for child in value:
                    remap(child)
        for obj in list(env.objects):
            tree = obj.read_typetree()
            if obj.type.name == "Texture2D":
                tree["m_Name"] = "ch0209_co0123" if other else "ch9999_co0123"
            if obj.type.name == "GameObject":
                if tree.get("m_Name") == "SyntheticRig":
                    tree["m_Name"] = "UnmaskedWrapper" if other else "BoardWrapper"
                if missing and tree.get("m_Name") == "BreastSize":
                    tree["m_Name"] = "UnknownBodyPart"
            if obj.type.name == "MonoBehaviour":
                if unsupported:
                    tree["m_Script"] = {"m_FileID": 0, "m_PathID": 0}
                if other:
                    tree["scaleValues"][0]["scaledValue"] = {"x": .8, "y": 1.1, "z": .95}
                    tree["scaleValues"].append({"target": {"m_FileID": 0, "m_PathID": 9},
                        "originValue": {"x": 1., "y": 1., "z": 1.},
                        "scaledValue": {"x": 1.15, "y": .95, "z": 1.05}})
                    tree["positionValues"][0]["scaledValue"] = {"x": .2, "y": .8, "z": -.1}
                    tree["rotationValues"][0]["scaledValue"] = {"x": 12., "y": 19., "z": -23.}
                else:
                    tree["rotationValues"][0]["scaledValue"] = {"x": 30., "y": -15., "z": 25.}
            remap(tree)
            obj.save_typetree(tree)
            obj.path_id += offset
        env.file.objects = {obj.path_id: obj for obj in env.objects}
        return env.file.save()

    def write(self, name, raw):
        path = self.root / name
        path.write_bytes(raw)
        return path

    def register(self, path, *, archive=False, variant="primary"):
        if archive:
            variants = {str(path): variant} if variant is not None else {}
            with viewer_archive.expand_inputs([str(path)], self.root / "zip-cache", variants) as expanded:
                preview = model_viewer.prepare(expanded.paths, rigged=True, face_context={"enabled": False, "allow_download": False})
                meta = edits.register_session(preview["id"], expanded.paths, preview["rig"],
                    originals=[str(path)], origins=expanded.origins, archive_members=expanded.archive_members,
                    variants=variants)
        else:
            preview = model_viewer.prepare([str(path)], rigged=True, face_context={"enabled": False, "allow_download": False})
            meta = edits.register_session(preview["id"], [str(path)], preview["rig"])
        return preview["id"], {node["name"]: node for node in meta["nodes"]}

    @staticmethod
    def state(*rows, **extra):
        return {"version": 1, "savedSettingsEnabled": True, "edits": list(rows), **extra}

    def save(self, path, make_state, *, archive=False, variant="primary"):
        token, nodes = self.register(path, archive=archive, variant=variant)
        state = edits.validate_state(token, make_state(nodes))
        context = edits.mod_source_context(token)
        result = edits.export(token, state, self.root / "exports")
        return context, result, state, nodes

    def apply_raw(self, context, result, state, other, variant="primary"):
        selected = result["preview_paths"][0]
        other_role = "unmasked" if variant == "primary" else "primary"
        pair = {"owner": 209, "platform": "android", "explicit_source": True,
                variant: {"path": selected, "sha256": sources._sha(Path(selected).read_bytes())},
                other_role: {"path": str(other), "sha256": sources._sha(other.read_bytes())}}
        return paired.apply_pair_edits(context, result, state, pair=pair, job=self.job)

    @staticmethod
    def key(info, name):
        return next(key for key, value in info["names"].items() if value == name)

    @staticmethod
    def vertices(info):
        mesh = next(obj for obj in info["env"].objects if obj.type.name == "Mesh")
        tree = mesh.read_typetree()
        count, channels, strides, starts, _ = stream_layout(tree)
        raw = np.frombuffer(bytes(tree["m_VertexData"]["m_DataSize"]), dtype=np.uint8)
        return read_attr(raw, ATTR_POS, channels, strides, starts, count)

    def test_node_relative_math_uses_different_ids_wrappers_nonunit_and_noncommuting_baselines(self):
        primary = self.write("board.unity", self.fixture())
        other = self.write("bare.unity", self.fixture(other=True, offset=1000))
        context, result, state, nodes = self.save(primary, lambda n: self.state({
            "node": n["BreastSize"]["node"], "method": "node", "scale": [1.4, .8, 1.1],
            "position": [.2, .9, .3], "rotation": [51., 17., -8.]}))
        before = edits._inspect(other.read_bytes())
        output = self.apply_raw(context, result, state, other)
        target = edits._inspect(Path(output["pair"]["unmasked"]["path"]).read_bytes())
        key = self.key(target, "BreastSize")
        original_source = edits._inspect(primary.read_bytes())
        source_key = self.key(original_source, "BreastSize")
        self.assertNotEqual(source_key[1], key[1])
        self.assertTrue(np.allclose(target["effective"][key]["scale"], [1.4*1.15, .8*.95, 1.1*1.05]))
        self.assertTrue(np.allclose(target["effective"][key]["position"], [-.1, 1.1, .2]))
        expected = edits._euler_matrix([51., 17., -8.]) @ edits._euler_matrix([30., -15., 25.]).T @ edits._euler_matrix([12., 19., -23.])
        self.assertTrue(np.allclose(edits._euler_matrix(target["effective"][key]["rotation"]), expected, atol=1e-5))
        self.assertTrue(np.array_equal(self.vertices(before), self.vertices(target)))
        unrelated = self.key(target, "NeutralRibbon")
        self.assertEqual(before["effective"][unrelated], target["effective"][unrelated])
        leg = self.key(target, "LeftUpLeg")
        self.assertEqual(before["effective"][leg], target["effective"][leg])
        self.assertEqual(other.read_bytes(), self.fixture(other=True, offset=1000))
        self.assertEqual(Path(result["preview_paths"][0]).read_bytes(), Path(output["pair"]["primary"]["path"]).read_bytes())

    def test_mesh_child_compensation_and_morphs_match_standalone_partner_export(self):
        primary = self.write("board.unity", self.fixture(morphs=True))
        other = self.write("bare.unity", self.fixture(other=True, offset=2000, morphs=True))
        def requested(n):
            references = [{"node": row["node"], **copy.deepcopy(row["baseline"])} for row in n.values()]
            return self.state({"node": n["LeftUpLeg"]["node"], "method": "mesh", "scale": [1.69, .99, 1.05],
                "compensate": True, "compensationTargets": [n["BreastSize"]["node"]]}, compensationReference=references)
        context, result, state, _ = self.save(primary, requested)
        token, nodes = self.register(other)
        # Source scale baseline is (1.3,.9,1); the partner has (.8,1.1,.95).
        manual = self.state({"node": nodes["LeftUpLeg"]["node"], "method": "mesh",
            "scale": [1.69/1.2999999523162842*.8, .99/.8999999761581421*1.1, 1.05*.95],
            "compensate": True, "compensationTargets": [nodes["BreastSize"]["node"]]},
            compensationReference=[{"node": row["node"], **copy.deepcopy(row["baseline"])}
                                   for row in nodes.values() if row["name"] in ("Move", "LeftUpLeg", "BreastSize")])
        expected = edits.export(token, manual, self.root / "expected")
        output = self.apply_raw(context, result, state, other)
        actual_raw = Path(output["pair"]["unmasked"]["path"]).read_bytes()
        actual = edits._inspect(actual_raw)
        expected_info = edits._inspect(Path(expected["preview_paths"][0]).read_bytes())
        self.assertTrue(np.allclose(self.vertices(actual), self.vertices(expected_info), atol=2e-6))
        self.assertFalse(np.allclose(self.vertices(actual), self.vertices(edits._inspect(other.read_bytes()))))
        meshes = lambda info: next(obj.read_typetree() for obj in info["env"].objects if obj.type.name == "Mesh")
        self.assertEqual(meshes(actual)["m_Shapes"], meshes(expected_info)["m_Shapes"])
        self.assertNotEqual(meshes(actual)["m_Shapes"], meshes(edits._inspect(other.read_bytes()))["m_Shapes"])
        self.assertEqual(meshes(actual)["m_BindPose"], meshes(edits._inspect(other.read_bytes()))["m_BindPose"])
        # Rebuild the saved bundle and restore its recipe against the preserved
        # original; exporting again must not apply a second mesh bake.
        model_viewer.prepare([output["pair"]["unmasked"]["path"]], rigged=True,
                             face_context={"enabled": False, "allow_download": False})
        recipe = json.loads(Path(output["result"]["paired_recipe_paths"][0]).read_text())
        original = Path(output["result"]["paired_original_paths"][0])
        token, _ = self.register(original)
        restored = edits.restore(token, recipe)
        repeated = edits.export(token, restored, self.root / "restored")
        self.assertEqual(Path(repeated["preview_paths"][0]).read_bytes(), actual_raw)
        again = self.apply_raw(context, result, state, other)
        self.assertEqual(Path(again["pair"]["unmasked"]["path"]).read_bytes(), actual_raw)

    def test_propagates_from_unmasked_to_board(self):
        selected = self.write("bare.unity", self.fixture(other=True, offset=1000))
        counterpart = self.write("board.unity", self.fixture())
        context, result, state, _ = self.save(selected, lambda n: self.state({
            "node": n["BreastSize"]["node"], "method": "node", "scale": [2.3, 1.9, 1.05]}))
        output = self.apply_raw(context, result, state, counterpart, variant="unmasked")
        info = edits._inspect(Path(output["pair"]["primary"]["path"]).read_bytes())
        self.assertTrue(np.allclose(info["effective"][self.key(info, "BreastSize")]["scale"], [2., 2., 1.], atol=1e-6))

    def paired_zip(self, *, four=False):
        values = {"board": self.fixture(), "bare": self.fixture(other=True, offset=1000),
                  "untouched.bin": b"unrelated data"}
        manifest = "chara_id=209\ncostume_file='board'\nrina_unmask_costume_file='bare'\n"
        if four:
            values.update(iphoneboard=self.fixture(offset=2000, platform=9),
                          iphonebare=self.fixture(other=True, offset=3000, platform=9))
            manifest += "costume_file_ios='iphoneboard'\nrina_unmask_costume_file_ios='iphonebare'\n"
        values["modinstall.txt"] = manifest.encode()
        path = self.root / "rina.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in values.items():
                archive.writestr(name, raw)
            archive.comment = b"keep archive comment"
        return path, values

    @staticmethod
    def outline_red(raw, *, values=None):
        env = UnityPy.load(raw)
        obj = next(item for item in env.objects if item.type.name == "Mesh")
        tree = obj.read_typetree()
        count, channels, strides, starts, _ = stream_layout(tree)
        channel = channels[3]
        data = bytearray(tree["m_VertexData"]["m_DataSize"])
        offsets = [starts[channel["stream"]] + index * strides[channel["stream"]] + channel["offset"] for index in range(count)]
        if values is None:
            return [data[offset] for offset in offsets]
        for index, offset in enumerate(offsets):
            data[offset] = values[index % len(values)]
        tree["m_VertexData"]["m_DataSize"] = bytes(data)
        obj.save_typetree(tree)
        return env.file.save()

    def test_outline_only_pair_uses_semantic_mesh_and_each_native_mask(self):
        primary = self.write("board.unity", self.outline_red(self.fixture(), values=[0, 80, 255, 190, 30, 1]))
        other_raw = self.outline_red(self.fixture(other=True, offset=1000), values=[20, 140, 0, 180, 255, 37])
        other = self.write("bare.unity", other_raw)
        token, _ = self.register(primary)
        context = edits.mod_source_context(token)
        identity = context["outlines"]["meshes"][0]["id"]
        state = edits.validate_state(token, self.state(outlines=[{"id": identity, "factor": .5}]))
        result = edits.export(token, state, self.root / "outline-source")
        output = self.apply_raw(context, result, state, other)
        actual_raw = Path(output["pair"]["unmasked"]["path"]).read_bytes()
        self.assertEqual(self.outline_red(actual_raw), [10, 70, 0, 90, 128, 19])
        before, after = edits._inspect(other_raw), edits._inspect(actual_raw)
        for key, obj in before["objects"].items():
            if obj.type.name != "Mesh":
                self.assertEqual(obj.get_raw_data(), after["objects"][key].get_raw_data())
        self.assertEqual(other.read_bytes(), other_raw)
        proof = output["summary"][0]["mapping"]
        self.assertTrue(any("sourceOutline" in row and row["sourceOutline"] != row["targetOutline"] for row in proof))
        recipe = json.loads(Path(output["result"]["paired_recipe_paths"][0]).read_text())
        self.assertEqual(recipe["state"]["outlines"][0]["factor"], .5)

    def test_outline_only_paired_mod_zip_propagates_all_platform_variants(self):
        path, original = self.paired_zip(four=True)
        token, _ = self.register(path, archive=True)
        context = edits.mod_source_context(token)
        identity = context["outlines"]["meshes"][0]["id"]
        state = edits.validate_state(token, self.state(outlines=[{"id": identity, "factor": 0}]))
        result = edits.export(token, state, self.root / "outline-zip")
        output = paired.apply_pair_edits(context, result, state, pair=None, job=self.job)
        self.assertEqual(len(output["summary"]), 3)
        with zipfile.ZipFile(output["result"]["preview_paths"][0]) as archive:
            for name in ("board", "bare", "iphoneboard", "iphonebare"):
                self.assertTrue(all(red == 0 for red in self.outline_red(archive.read(name))))
            self.assertEqual(archive.read("untouched.bin"), original["untouched.bin"])
            self.assertEqual(archive.read("modinstall.txt"), original["modinstall.txt"])

    def test_outline_pair_rejects_missing_and_ambiguous_semantic_mesh(self):
        primary = self.write("board.unity", self.fixture())
        other = self.write("bare.unity", self.fixture(other=True, offset=1000))
        source_token, _ = self.register(primary)
        target_token, _ = self.register(other)
        context, target = edits.mod_source_context(source_token), edits.mod_source_context(target_token)
        identity = context["outlines"]["meshes"][0]["id"]
        state = edits.validate_state(source_token, self.state(outlines=[{"id": identity, "factor": .5}]))
        for entries in ([], target["outlines"]["meshes"] * 2):
            altered = copy.deepcopy(target)
            altered["outlines"]["meshes"] = entries
            with self.subTest(count=len(entries)), self.assertRaisesRegex(ValueError, "unique matching outline"):
                paired._map_state(context, state, 0, edits._inspect(primary.read_bytes()), altered, edits._inspect(other.read_bytes()))

    def test_complete_zip_updates_all_declared_variants_preserves_selected_once_and_unrelated_bytes(self):
        for four in (False, True):
            with self.subTest(four=four):
                path, original = self.paired_zip(four=four)
                source_bytes = path.read_bytes()
                context, result, state, _ = self.save(path, lambda n: self.state({
                    "node": n["BreastSize"]["node"], "method": "node", "scale": [1.4, .8, 1.1]}), archive=True)
                with zipfile.ZipFile(result["preview_paths"][0]) as selected:
                    selected_once = selected.read("board")
                output = paired.apply_pair_edits(context, result, state, pair=None, job=self.job)
                self.assertIsNone(output["pair"])
                self.assertEqual(len(output["summary"]), 3 if four else 1)
                with zipfile.ZipFile(output["result"]["preview_paths"][0]) as archive:
                    self.assertEqual(archive.read("board"), selected_once)
                    self.assertEqual(archive.comment, b"keep archive comment")
                    self.assertEqual(archive.read("untouched.bin"), original["untouched.bin"])
                    self.assertEqual(archive.read("modinstall.txt"), original["modinstall.txt"])
                    for name in ("bare", "iphoneboard", "iphonebare") if four else ("bare",):
                        self.assertNotEqual(archive.read(name), original[name])
                        info = edits._inspect(archive.read(name))
                        scale = info["effective"][self.key(info, "BreastSize")]["scale"]
                        expected = [1.4*1.15, .8*.95, 1.1*1.05] if "bare" in name else [1.4, .8, 1.1]
                        self.assertTrue(np.allclose(scale, expected, atol=1e-6))
                        clips = lambda raw: next(obj.read_typetree() for obj in UnityPy.load(raw).objects if obj.type.name == "AnimationClip")
                        self.assertEqual(clips(archive.read(name)), clips(original[name]))
                self.assertEqual(path.read_bytes(), source_bytes)
                self.assertEqual(output["result"]["preview_variants"], {"0": "primary"})
                self.assertTrue(all(Path(recipe).is_file() for recipe in output["result"]["paired_recipe_paths"]))

    def platform_zip(self, *, owner=6, ios_platform=9, ios_missing=False, ios_unsupported=False):
        # These textures deliberately retain their Rina donor names. A known
        # literal owner binds an explicitly declared transplanted costume;
        # texture prefixes must not silently replace that declaration.
        original = {"android-body": self.fixture(morphs=True),
                    "ios-body": self.fixture(other=True, offset=5000, platform=ios_platform,
                                             morphs=True, missing=ios_missing, unsupported=ios_unsupported),
                    "untouched.bin": b"independent costume data",
                    "modinstall.txt": (f"chara_id={owner!r}\ncostume_file='android-body'\n"
                                       "costume_file_ios='ios-body'\n").encode()}
        path = self.root / "dual-platform.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in original.items():
                archive.writestr(name, raw)
            archive.comment = b"same declared costume; keep both native platforms"
        return path, original

    def test_non_rina_dual_platform_transplant_maps_node_and_mesh_to_own_ios_baseline(self):
        path, original = self.platform_zip()
        original_zip = path.read_bytes()
        self.assertEqual(sources._model_facts(original["ios-body"])["owner"], 209)
        def requested(nodes):
            return self.state(
                {"node": nodes["BreastSize"]["node"], "method": "node", "scale": [1.4, .8, 1.1],
                 "position": [.2, .9, .3], "rotation": [51., 17., -8.]},
                {"node": nodes["LeftUpLeg"]["node"], "method": "mesh", "scale": [1.69, .99, 1.05],
                 "compensate": True, "compensationTargets": [nodes["BreastSize"]["node"]]},
                compensationReference=[{"node": row["node"], **copy.deepcopy(row["baseline"])}
                                       for row in nodes.values()])
        context, result, state, _ = self.save(path, requested, archive=True, variant=None)
        with zipfile.ZipFile(result["preview_paths"][0]) as saved:
            selected_once = saved.read("android-body")
        ios_source = self.write("manual-ios.unity", original["ios-body"])
        token, nodes = self.register(ios_source)
        rotation = edits._matrix_euler(edits._euler_matrix([51., 17., -8.]) @
            edits._euler_matrix([30., -15., 25.]).T @ edits._euler_matrix([12., 19., -23.]))
        manual = self.state(
            {"node": nodes["BreastSize"]["node"], "method": "node", "scale": [1.4*1.15, .8*.95, 1.1*1.05],
             # Public authoring X is opposite Unity's serialized X. The
             # source/target public baselines are -.1/-.2, so -.2+.2-(-.1)=.1.
             "position": [.1, 1.1, .2], "rotation": rotation},
            {"node": nodes["LeftUpLeg"]["node"], "method": "mesh",
             "scale": [1.69/1.2999999523162842*.8, .99/.8999999761581421*1.1, 1.05*.95],
             "compensate": True, "compensationTargets": [nodes["BreastSize"]["node"]]},
            compensationReference=[{"node": row["node"], **copy.deepcopy(row["baseline"])}
                                   for row in nodes.values() if row["name"] in ("Move", "LeftUpLeg", "BreastSize")])
        expected = edits.export(token, manual, self.root / "expected-ios")
        expected_info = edits._inspect(Path(expected["preview_paths"][0]).read_bytes())
        output = paired.apply_pair_edits(context, result, state, pair=None, job=self.job)
        self.assertIsNone(output["pair"])
        self.assertEqual(len(output["summary"]), 1)
        with zipfile.ZipFile(output["result"]["preview_paths"][0]) as saved:
            self.assertEqual(saved.read("android-body"), selected_once)
            ios_raw = saved.read("ios-body")
            self.assertNotEqual(ios_raw, original["ios-body"])
            self.assertEqual(sources._model_facts(ios_raw)["platform"], "ios")
            self.assertEqual(sources._model_facts(saved.read("android-body"))["platform"], "android")
            actual = edits._inspect(ios_raw)
            self.assertNotEqual(self.key(actual, "BreastSize")[1], self.key(edits._inspect(original["android-body"]), "BreastSize")[1])
            self.assertTrue(np.allclose(self.vertices(actual), self.vertices(expected_info), atol=2e-6))
            self.assertFalse(np.allclose(self.vertices(actual), self.vertices(edits._inspect(original["ios-body"]))))
            for kind in ("scale", "position", "rotation"):
                actual_trs = actual["effective"][self.key(actual, "BreastSize")][kind]
                expected_trs = expected_info["effective"][self.key(expected_info, "BreastSize")][kind]
                self.assertTrue(np.allclose(actual_trs, expected_trs, atol=2e-5), kind)
            mesh = lambda info: next(obj.read_typetree() for obj in info["env"].objects if obj.type.name == "Mesh")
            actual_shapes, expected_shapes = copy.deepcopy(mesh(actual)["m_Shapes"]), copy.deepcopy(mesh(expected_info)["m_Shapes"])
            actual_morphs, expected_morphs = actual_shapes.pop("vertices"), expected_shapes.pop("vertices")
            self.assertEqual(actual_shapes, expected_shapes)
            self.assertEqual(len(actual_morphs), len(expected_morphs))
            for actual_morph, expected_morph in zip(actual_morphs, expected_morphs):
                self.assertEqual(actual_morph["index"], expected_morph["index"])
                for kind in ("vertex", "normal", "tangent"):
                    self.assertTrue(np.allclose([actual_morph[kind][axis] for axis in "xyz"],
                                                [expected_morph[kind][axis] for axis in "xyz"], atol=2e-6), kind)
            self.assertNotEqual(mesh(actual)["m_Shapes"], mesh(edits._inspect(original["ios-body"]))["m_Shapes"])
            self.assertEqual(mesh(actual)["m_BindPose"], mesh(edits._inspect(original["ios-body"]))["m_BindPose"])
            for name in ("modinstall.txt", "untouched.bin"):
                self.assertEqual(saved.read(name), original[name])
            self.assertEqual(saved.comment, b"same declared costume; keep both native platforms")
        self.assertEqual(path.read_bytes(), original_zip)
        self.assertEqual(ios_source.read_bytes(), original["ios-body"])
        recipe = json.loads(Path(output["result"]["paired_recipe_paths"][0]).read_text())
        preserved = Path(output["result"]["paired_original_paths"][0])
        token, _ = self.register(preserved)
        restored = edits.restore(token, recipe)
        rebuilt = edits.export(token, restored, self.root / "rebuilt-ios")
        self.assertEqual(Path(rebuilt["preview_paths"][0]).read_bytes(), ios_raw)

    def test_dual_platform_manifest_refuses_unknown_owner_wrong_platform_missing_and_unsupported_rig_atomically(self):
        for flags in ({"owner": True}, {"owner": 9998}, {"ios_platform": 13}, {"ios_platform": 8},
                      {"ios_missing": True}, {"ios_unsupported": True}):
            with self.subTest(flags=flags):
                path, _ = self.platform_zip(**flags)
                source_raw = path.read_bytes()
                context, result, state, _ = self.save(path, lambda nodes: self.state({
                    "node": nodes["BreastSize"]["node"], "method": "node", "scale": [1.4, .8, 1.1]}), archive=True, variant=None)
                saved_before = Path(result["preview_paths"][0]).read_bytes()
                with self.assertRaises(ValueError):
                    paired.apply_pair_edits(context, result, state, pair=None, job=self.job)
                self.assertEqual(path.read_bytes(), source_raw)
                self.assertEqual(Path(result["preview_paths"][0]).read_bytes(), saved_before)
                self.assertEqual(list(Path(result["recipe_path"]).parent.glob("*paired-body-*")), [])

    def test_legacy_ios_only_rina_pair_in_main_fields_preserves_native_platform(self):
        path, original = self.paired_zip()
        original.update(board=self.fixture(platform=9), bare=self.fixture(other=True, offset=1000, platform=9))
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in original.items():
                archive.writestr(name, raw)
        original_zip = path.read_bytes()
        context, result, state, _ = self.save(path, lambda nodes: self.state({
            "node": nodes["BreastSize"]["node"], "method": "node", "scale": [1.4, .8, 1.1]}), archive=True)
        output = paired.apply_pair_edits(context, result, state, pair=None, job=self.job)
        with zipfile.ZipFile(output["result"]["preview_paths"][0]) as saved:
            for member in ("board", "bare"):
                self.assertEqual(sources._model_facts(saved.read(member))["platform"], "ios")
                self.assertNotEqual(saved.read(member), original[member])
        self.assertEqual(path.read_bytes(), original_zip)

    def test_explicit_rina_four_variant_transplant_resolves_before_donor_identity_and_edits_all_members(self):
        path, original = self.paired_zip(four=True)
        members = ("board", "bare", "iphoneboard", "iphonebare")
        for member in members:
            environment = UnityPy.load(original[member])
            for obj in environment.objects:
                if obj.type.name == "Texture2D":
                    tree = obj.read_typetree()
                    tree["m_Name"] = "ch0006_co0123"
                    obj.save_typetree(tree)
            original[member] = environment.file.save()
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in original.items():
                archive.writestr(name, raw)
        original_zip = path.read_bytes()
        context, result, state, _ = self.save(path, lambda nodes: self.state({
            "node": nodes["BreastSize"]["node"], "method": "node", "scale": [1.4, .8, 1.1]}), archive=True)
        self.assertTrue(all(sources._model_facts(original[member])["owner"] == 6 for member in members))
        # The raw/donor-only helper keeps its strict identity checks. The
        # public resolver must first honor the explicit validated ZIP family.
        with self.assertRaisesRegex(ValueError, "same character"):
            sources._complete_rina_zip(original_zip, "board")
        self.assertIsNone(sources.resolve_pair(context, result, repo_root=self.root,
            output_root=self.root / "pair-discovery", job=self.job))
        with zipfile.ZipFile(result["preview_paths"][0]) as saved:
            selected_once = saved.read("board")
        output = paired.apply_pair_edits(context, result, state, pair=None, job=self.job)
        self.assertEqual(len(output["summary"]), 3)
        with zipfile.ZipFile(output["result"]["preview_paths"][0]) as saved:
            self.assertEqual(saved.read("board"), selected_once)
            for member in members:
                actual = saved.read(member)
                self.assertNotEqual(actual, original[member])
                self.assertEqual(sources._model_facts(actual)["platform"], "ios" if member.startswith("iphone") else "android")
                info = edits._inspect(actual)
                expected = [1.4*1.15, .8*.95, 1.1*1.05] if "bare" in member else [1.4, .8, 1.1]
                self.assertTrue(np.allclose(info["effective"][self.key(info, "BreastSize")]["scale"], expected, atol=1e-6))
            self.assertEqual(saved.read("modinstall.txt"), original["modinstall.txt"])
            self.assertEqual(saved.read("untouched.bin"), original["untouched.bin"])
        self.assertEqual(path.read_bytes(), original_zip)

    def test_raw_save_without_declared_owner_or_platform_family_is_an_unchanged_noop(self):
        legacy, original = self.paired_zip()
        original["modinstall.txt"] = b"costume_file='board'\nrina_unmask_costume_file='bare'\n"
        with zipfile.ZipFile(legacy, "w") as archive:
            for name, raw in original.items():
                archive.writestr(name, raw)
        context, result, state, _ = self.save(legacy, lambda nodes: self.state({
            "node": nodes["BreastSize"]["node"], "method": "node", "scale": [1.2, 1., 1.]}), archive=True)
        saved = Path(result["preview_paths"][0]).read_bytes()
        output = paired.apply_pair_edits(context, result, state, pair=None, job=self.job)
        self.assertIs(output["result"], result)
        self.assertEqual(output["summary"], [])
        self.assertEqual(Path(result["preview_paths"][0]).read_bytes(), saved)
        for manifest in (b"chara_id=6\ncostume_file='only'\n", b"this is opaque legacy metadata !",
                         b"chara_id=int('6')\ncostume_file='only'\n",
                         b"chara_id=6\ncostume_file=str('only')\n"):
            ordinary = self.root / "ordinary.zip"
            with zipfile.ZipFile(ordinary, "w") as archive:
                archive.writestr("only", self.raw)
                archive.writestr("modinstall.txt", manifest)
            context, result, state, _ = self.save(ordinary, lambda nodes: self.state({
                "node": nodes["BreastSize"]["node"], "method": "node", "scale": [1.2, 1., 1.]}),
                archive=True, variant=None)
            self.assertIs(paired.apply_pair_edits(context, result, state, pair=None, job=self.job)["result"], result)

    def test_missing_or_unsupported_counterpart_rejects_without_publishing_partial_pair(self):
        primary = self.write("board.unity", self.fixture())
        context, result, state, _ = self.save(primary, lambda n: self.state({
            "node": n["BreastSize"]["node"], "method": "node", "scale": [1.4, 1.1, 1.]}))
        for flags in ({"missing": True}, {"unsupported": True}):
            other = self.write("bare.unity", self.fixture(other=True, offset=1000, **flags))
            with self.assertRaises(ValueError):
                self.apply_raw(context, result, state, other)
            self.assertEqual(list(Path(result["recipe_path"]).parent.glob("paired-body-*")), [])
            self.assertEqual(list(Path(result["recipe_path"]).parent.glob(".paired-body-*")), [])

    def test_nonbaseline_compensation_reference_maps_relative_transforms_and_unmatched_changed_wrapper_rejects(self):
        primary = self.write("board.unity", self.fixture())
        other = self.write("bare.unity", self.fixture(other=True, offset=1000))
        def request(nodes):
            references = [{"node": row["node"], **copy.deepcopy(row["baseline"])} for row in nodes.values()]
            breast = next(row for row in references if row["node"] == nodes["BreastSize"]["node"])
            breast.update(scale=[1.05, .97, 1.02], position=[-.05, .7, .1], rotation=[41., -8., 14.])
            return self.state({"node": nodes["LeftUpLeg"]["node"], "method": "mesh", "scale": [1.5, 1., 1.],
                "compensate": True, "compensationTargets": [nodes["BreastSize"]["node"]]}, compensationReference=references)
        context, result, state, _ = self.save(primary, request)
        output = self.apply_raw(context, result, state, other)
        recipe = json.loads(Path(output["result"]["paired_recipe_paths"][0]).read_text())
        refs = recipe["state"]["compensationReference"]
        self.assertEqual(len(refs), 1)
        row = refs[0]
        self.assertTrue(np.allclose(row["scale"], [1.05*1.15, .97*.95, 1.02*1.05]))
        self.assertTrue(np.allclose(row["position"], [-.15, .9, 0.]))
        expected = edits._euler_matrix([41., -8., 14.]) @ edits._euler_matrix([30., -15., 25.]).T @ edits._euler_matrix([12., 19., -23.])
        self.assertTrue(np.allclose(edits._euler_matrix(row["rotation"]), expected, atol=1e-6))
        modified = copy.deepcopy(state)
        wrapper_node = next(row["node"] for row in context["nodes"] if row["name"] == "BoardWrapper")
        wrapper = next(row for row in modified["compensationReference"] if row["node"] == wrapper_node)
        wrapper["scale"] = [1.1, 1., 1.]
        with self.assertRaisesRegex(ValueError, "unique matching bone"):
            self.apply_raw(context, result, modified, other)

    def test_multi_variant_failure_and_input_race_publish_no_partial_pair(self):
        path, original = self.paired_zip(four=True)
        original["iphoneboard"] = self.fixture(offset=2000, platform=9, unsupported=True)
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in original.items():
                archive.writestr(name, raw)
        context, result, state, _ = self.save(path, lambda n: self.state({
            "node": n["BreastSize"]["node"], "method": "node", "scale": [1.2, 1., 1.]}), archive=True)
        selected_once = Path(result["preview_paths"][0]).read_bytes()
        with self.assertRaises(ValueError):
            paired.apply_pair_edits(context, result, state, pair=None, job=self.job)
        self.assertEqual(Path(result["preview_paths"][0]).read_bytes(), selected_once)
        self.assertEqual(list(Path(result["recipe_path"]).parent.glob("*paired-body-*")), [])
        primary = self.write("board.unity", self.fixture())
        other = self.write("bare.unity", self.fixture(other=True, offset=1000))
        context, result, state, _ = self.save(primary, lambda n: self.state({
            "node": n["BreastSize"]["node"], "method": "node", "scale": [1.2, 1., 1.]}))
        original_edit = paired._edit_partner
        def race(*args, **kwargs):
            value = original_edit(*args, **kwargs)
            other.write_bytes(other.read_bytes() + b"changed")
            return value
        with patch.object(paired, "_edit_partner", side_effect=race):
            with self.assertRaisesRegex(ValueError, "input changed"):
                self.apply_raw(context, result, state, other)
        self.assertEqual(list(Path(result["recipe_path"]).parent.glob("*paired-body-*")), [])

    def test_ambiguous_skeleton_and_zero_relative_scale_fail_closed(self):
        primary = self.write("board.unity", self.fixture())
        raw = self.fixture(other=True, offset=1000)
        environment = UnityPy.load(raw)
        for obj in environment.objects:
            if obj.type.name == "GameObject":
                tree = obj.read_typetree()
                if tree["m_Name"] == "NeutralRibbon":
                    tree["m_Name"] = "Move"
                    obj.save_typetree(tree)
        other = self.write("bare.unity", environment.file.save())
        context, result, state, _ = self.save(primary, lambda n: self.state({
            "node": n["BreastSize"]["node"], "method": "node", "scale": [1.2, 1., 1.]}))
        with self.assertRaisesRegex(ValueError, "duplicate Move"):
            self.apply_raw(context, result, state, other)
        with self.assertRaisesRegex(ValueError, "baseline"):
            paired._relative("scale", [1., 1., 1.], [0., 1., 1.], [1., 1., 1.])

    def test_cancellation_and_non_rina_noop_do_not_create_pair_outputs(self):
        path = self.write("ordinary.unity", self.raw)
        context, result, state, _ = self.save(path, lambda n: self.state({
            "node": n["BreastSize"]["node"], "method": "node", "scale": [1.1, 1., 1.]}))
        self.assertIs(paired.apply_pair_edits(context, result, state, pair=None, job=self.job)["result"], result)
        self.job.cancel_event.set()
        with self.assertRaises(InterruptedError):
            paired.apply_pair_edits(context, result, state, pair=None, job=self.job)


if __name__ == "__main__":
    unittest.main()
