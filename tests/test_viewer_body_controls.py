"""Body-card contracts against independently weighted serialized neutral data."""
import copy
import hashlib
from pathlib import Path
import secrets
import tempfile
import unittest

try:
    import numpy as np
    from generate_viewer_body_fixture import BONES, fixture_bytes, local_matrix
    from webtools.core import model_edits as edits, model_scaling, model_viewer
    from sifas_mesh_baker import stream_layout, read_attr, ATTR_POS
    import sifas_mesh_baker as mesh_tool
    from sifas_body_profiles import (THIGH_STATES, THIGH_TRANSITIONS,
                                     thigh_factor, thigh_profile_metadata)
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "UnityPy and numpy are needed for body-card output checks")
class ViewerBodyControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = fixture_bytes()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root / "neutral-body.unity"
        self.source.write_bytes(self.raw)
        self.prepared = model_viewer.prepare([str(self.source)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        self.token = secrets.token_hex(16)
        self.metadata = edits.register_session(self.token, [str(self.source)], self.prepared["rig"])
        self.nodes = {node["name"]: node for node in self.metadata["nodes"]}
        self.controls = {c["id"]: c for c in self.prepared["rig"]["scaling"]["controls"]}
        self.original = edits._inspect(self.raw)

    def tearDown(self):
        with edits._LOCK:
            edits._SESSIONS.clear()

    def key(self, name, info=None):
        return next(key for key, value in (info or self.original)["names"].items() if value == name)

    def positions(self, info):
        mesh = next(obj for obj in info["env"].objects if obj.type.name == "Mesh").read_typetree()
        count, channels, stride, start, _ = stream_layout(mesh)
        raw = np.frombuffer(mesh["m_VertexData"]["m_DataSize"], np.uint8)
        return mesh, read_attr(raw, ATTR_POS, channels, stride, start, count).astype(float)

    def worlds(self, info):
        result = {}
        def visit(key):
            if key in result: return result[key]
            tr = info["transforms"][key]; q = np.array([tr["m_LocalRotation"][a] for a in "xyzw"])
            q /= np.linalg.norm(q)
            local = local_matrix([tr["m_LocalPosition"][a] for a in "xyz"], q,
                                 [tr["m_LocalScale"][a] for a in "xyz"])
            parent = info["parents"][key]
            result[key] = visit(parent) @ local if parent is not None else local
            return result[key]
        for key in info["transforms"]: visit(key)
        return result

    def operation(self, name, percent, *, children=(), method="mesh"):
        base = self.nodes[name]["baseline"]["scale"]
        scale = [base[0], base[1]*percent/100, base[2]*percent/100]
        if method == "node": scale = [value*percent/100 for value in base]
        result = {"node": self.nodes[name]["node"], "method": method, "scale": scale}
        if children:
            result.update(compensate=True, compensationTargets=[self.nodes[c]["node"] for c in children])
        return result

    def state(self, *operations):
        return {"version": 1, "savedSettingsEnabled": True, "edits": list(operations)}

    def test_metadata_exposes_only_safe_targets_and_length_axis_contract(self):
        hips, thighs, waist = (self.controls[k] for k in ("hips", "thighs", "waist"))
        self.assertTrue(all(c["available"] for c in (hips, thighs, waist)))
        self.assertEqual((hips["method"], hips["editedAxes"], hips["compensate"]), ("node", [0, 1, 2], False))
        self.assertEqual([n["name"] for n in thighs["nodes"]], ["LeftUpLeg", "RightUpLeg"])
        for control in (thighs, waist):
            self.assertEqual((control["method"], control["lengthAxis"], control["editedAxes"]), ("mesh", 0, [1, 2]))
            self.assertTrue(control["compensate"])
        self.assertEqual(waist["compensationMode"], "spine2")
        self.assertEqual(waist["nodes"][0]["compensationTargets"], [self.nodes["Spine2"]["node"]])
        for duplicate, missing, control in ((True, False, "hips"), (False, True, "waist")):
            path = self.root / (control+"-unavailable.unity")
            path.write_bytes(fixture_bytes(duplicate_hips=duplicate, missing_spine2=missing))
            prepared = model_viewer.prepare([str(path)], rigged=True, face_context={"enabled": False, "allow_download": False})
            selected = next(c for c in prepared["rig"]["scaling"]["controls"] if c["id"] == control)
            self.assertFalse(selected["available"], "Ambiguous/missing compensation boundaries must not be guessed")
            self.assertTrue(selected.get("unavailableReason"))

    def test_thigh_presets_share_the_existing_tool_without_guessing_source_type(self):
        from webtools.core import charinfo
        control = self.controls["thighs"]
        self.assertIs(mesh_tool.THIGH_STATES, THIGH_STATES)
        self.assertIs(charinfo.THIGH_STATES, THIGH_STATES)
        self.assertIs(mesh_tool.thigh_factor, thigh_factor)
        self.assertEqual([(p["sourceState"], p["targetState"]) for p in control["presets"]], THIGH_TRANSITIONS)
        self.assertTrue(control["presetSourceRequired"])
        self.assertEqual(control["presetPercentagePolicy"], "replace_same_axes")
        self.assertEqual(control["presetApplication"], "relative_to_original_static_scale")
        self.assertNotIn("detectedSourceState", control, "A named bone cannot establish a costume's original body type")
        for profile in control["presets"]:
            old_targets = mesh_tool.thigh_targets(profile["sourceState"], profile["targetState"])
            self.assertEqual([t.bone for t in old_targets], ["LeftUpLeg", "RightUpLeg"])
            self.assertTrue(all(t.compensate for t in old_targets))
            self.assertEqual(profile["scaleDelta"], list(old_targets[0].scale))
            self.assertEqual(profile["scaleDelta"][0], 1)
            self.assertNotEqual(profile["scaleDelta"][1], profile["scaleDelta"][2],
                                "The existing body-type conversions are not uniform thickness percentages")
        control["presets"][0]["scaleDelta"][1] = 999
        self.assertEqual(thigh_profile_metadata()["presets"][0]["scaleDelta"],
                         list(thigh_factor(*THIGH_TRANSITIONS[0])), "Metadata must not mutate the shared reference data")

    def test_every_tool_thigh_profile_saves_exact_shape_and_preserves_calves(self):
        before_mesh, before = self.positions(self.original)
        worlds = self.worlds(self.original); names = [row[0] for row in BONES]
        for src, dst in THIGH_TRANSITIONS:
            with self.subTest(source=src, target=dst):
                factor = np.asarray(mesh_tool.thigh_factor(src, dst))
                operations = []
                for name, child in (("LeftUpLeg", "LeftLeg"), ("RightUpLeg", "RightLeg")):
                    base = np.asarray(self.nodes[name]["baseline"]["scale"])
                    operations.append({"node": self.nodes[name]["node"], "method": "mesh",
                        "scale": (base*factor).tolist(), "compensate": True,
                        "compensationTargets": [self.nodes[child]["node"]]})
                state = self.state(*operations)
                result = edits.export(self.token, state, self.root / (src+"-"+dst))
                checked = edits._inspect(Path(result["preview_paths"][0]).read_bytes())
                after_mesh, after = self.positions(checked)
                self.assertEqual(before_mesh["m_BindPose"], after_mesh["m_BindPose"])
                for index, name in enumerate(names):
                    points = before[index*3:index*3+3]; actual = after[index*3:index*3+3]
                    if name not in ("LeftUpLeg", "RightUpLeg"):
                        np.testing.assert_allclose(actual, points, atol=3e-6, rtol=0,
                            err_msg=f"{src}->{dst} must preserve child/calf/foot geometry: {name}")
                        continue
                    world = worlds[self.key(name)]
                    local = np.c_[points, np.ones(3)] @ np.linalg.inv(world).T
                    expected_local = local.copy(); expected_local[:, :3] *= factor
                    expected = (expected_local @ world.T)[:, :3]
                    np.testing.assert_allclose(actual, expected, atol=3e-6, rtol=0,
                        err_msg=f"{src}->{dst} must match the tool's unequal Y/Z factors on {name}")
                    self.assertGreater(np.max(np.abs(actual-points)), .001)
                    reloaded_local = np.c_[actual, np.ones(3)] @ np.linalg.inv(world).T
                    np.testing.assert_allclose(reloaded_local[:, 0], local[:, 0], atol=3e-6, rtol=0,
                        err_msg="Preset conversion must not change local bone length")
                for name in names:
                    self.assertEqual(self.original["transforms"][self.key(name)], checked["transforms"][self.key(name, checked)])
                restored = edits.restore(self.token, result["recipe"])
                rebuilt = edits.export(self.token, restored, self.root / (src+"-"+dst+"-rebuilt"))
                np.testing.assert_array_equal(self.positions(edits._inspect(Path(rebuilt["preview_paths"][0]).read_bytes()))[1], after,
                    "Recipe rebuild must not multiply a preset onto its previous baked output")
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_virtual_character_parent_cannot_join_independent_thigh_armatures(self):
        # A virtual Character node joins exported models, but it is not a
        # source Transform establishing one left/right body hierarchy.
        names = {1: "LeftArmature", 2: "LeftUpLeg", 3: "LeftLeg",
                 4: "RightArmature", 5: "RightUpLeg", 6: "RightLeg"}
        authored = {node: {"node": node, "name": name, "baseScale": [1., 1., 1.]}
                    for node, name in names.items()}
        sources = {node: "same-original-file" for node in names}
        parents = {0: [], 1: [0], 2: [1], 3: [2], 4: [0], 5: [4], 6: [5]}
        original = copy.deepcopy((authored, parents, sources))
        def thighs():
            return next(c for c in model_scaling._body_card_controls(authored, parents, sources)
                        if c["id"] == "thighs")
        rejected = thighs()
        self.assertFalse(rejected["available"])
        self.assertEqual(rejected["unavailableReason"], "ambiguous_body_control_hierarchy")
        self.assertEqual((authored, parents, sources), original, "Metadata checks never change the source graph")
        parents[4] = [1]
        accepted = thighs()
        self.assertTrue(accepted["available"], "An actual shared source Transform root establishes one body hierarchy")
        self.assertEqual([n["compensationTargets"] for n in accepted["nodes"]], [[3], [6]])

    def test_real_hybrid_output_changes_thickness_preserves_length_and_child_geometry(self):
        operations = [self.operation("HipsSize", 115, method="node"),
                      self.operation("Spine", 120, children=("Spine2",)),
                      self.operation("LeftUpLeg", 125, children=("LeftLeg",)),
                      self.operation("RightUpLeg", 125, children=("RightLeg",))]
        state = self.state(*operations)
        first = edits.export(self.token, state, self.root / "first")
        second = edits.export(self.token, state, self.root / "second")
        first_raw = Path(first["preview_paths"][0]).read_bytes()
        self.assertEqual(first_raw, Path(second["preview_paths"][0]).read_bytes(), "Repeat exports must not compound scale")
        checked = edits._inspect(first_raw)
        before_mesh, before = self.positions(self.original); after_mesh, after = self.positions(checked)
        self.assertEqual(before_mesh["m_BindPose"], after_mesh["m_BindPose"])
        # The expected deformation is derived directly in each original bone's
        # rest frame, not by invoking the product's compensation implementation.
        worlds = self.worlds(self.original); names = [row[0] for row in BONES]
        changed_groups = {"Spine": ("Spine", 1.2), "Spine1": ("Spine", 1.2),
                          "LeftUpLeg": ("LeftUpLeg", 1.25), "RightUpLeg": ("RightUpLeg", 1.25)}
        for name in names:
            index = names.index(name); points = before[index*3:index*3+3]; actual = after[index*3:index*3+3]
            if name in changed_groups:
                parent, factor = changed_groups[name]; world = worlds[self.key(parent)]
                local = np.c_[points, np.ones(3)] @ np.linalg.inv(world).T
                local[:, 1:3] *= factor
                expected = (local @ world.T)[:, :3]
                self.assertGreater(np.max(np.abs(actual-points)), .005, name+" has genuinely affected vertices")
                np.testing.assert_allclose(actual, expected, atol=3e-6, rtol=0)
                roundtrip = np.c_[actual, np.ones(3)] @ np.linalg.inv(world).T
                original_local = np.c_[points, np.ones(3)] @ np.linalg.inv(world).T
                np.testing.assert_allclose(roundtrip[:, 0], original_local[:, 0], atol=3e-6, rtol=0,
                                           err_msg=name+" preserves the bone-local length axis")
            else:
                np.testing.assert_allclose(actual, points, atol=3e-6, rtol=0,
                    err_msg=name+" child/upper-body geometry must be preserved")
        for name in names:
            old, new = self.key(name), self.key(name, checked)
            self.assertEqual(self.original["transforms"][old], checked["transforms"][new],
                             "Authored scale/position/quaternion must stay intact: "+name)
        hips_key = self.key("HipsSize", checked)
        np.testing.assert_allclose(checked["effective"][hips_key]["scale"], operations[0]["scale"], atol=1e-7)
        self.assertEqual(self.source.read_bytes(), self.raw)
        restored = edits.restore(self.token, first["recipe"])
        rebuilt = edits.export(self.token, restored, self.root / "rebuilt")
        np.testing.assert_array_equal(self.positions(edits._inspect(Path(rebuilt["preview_paths"][0]).read_bytes()))[1], after)

    def test_node_child_compensation_is_still_rejected_and_publishes_nothing(self):
        operation = self.operation("HipsSize", 115, children=("ButtockTip",), method="node")
        with self.assertRaisesRegex(edits.ModelEditError, "mesh"):
            edits.export(self.token, self.state(operation), self.root / "unsafe")
        self.assertFalse((self.root / "unsafe").exists())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), hashlib.sha256(self.raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
