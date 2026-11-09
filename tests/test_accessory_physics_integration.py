"""Real serialized accessory corrections retain simultaneous physics recipes."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np
import UnityPy

from generate_viewer_physics_fixture import fixture_bytes
from test_model_accessory_unclip import make_fixture
from webtools.core import model_edits as edits, model_viewer, viewer_physics
from webtools.core import viewer_mod_pair_edits as paired, viewer_scene_roles as roles


def combined_fixture():
    env, physics = UnityPy.load(make_fixture()), UnityPy.load(fixture_bytes())
    target = {obj.path_id: obj for obj in env.objects}
    source = {obj.path_id: obj for obj in physics.objects}
    asset = target[16].assets_file
    game = next(obj for obj in env.objects if obj.type.name == "GameObject" and obj.peek_name() == "LeftBreast")
    script = copy.copy(source[220])
    script.assets_file, script.path_id = asset, 40000
    script.type_id, script.serialized_type = target[17].type_id, target[17].serialized_type
    asset.objects[script.path_id] = script
    script.save_typetree(source[220].read_typetree())
    serialized = copy.copy(source[221].serialized_type)
    serialized.script_type_index = len(asset.types)
    component = copy.copy(source[221])
    component.assets_file, component.path_id = asset, 40001
    component.type_id, component.serialized_type = len(asset.types), serialized
    asset.types.append(serialized)
    asset.objects[component.path_id] = component
    tree = source[221].read_typetree()
    tree.update(m_GameObject={"m_FileID": 0, "m_PathID": game.path_id},
                m_Script={"m_FileID": 0, "m_PathID": script.path_id})
    component.save_typetree(tree)
    game_tree = game.read_typetree()
    game_tree["m_Component"].append({"component": {"m_FileID": 0, "m_PathID": component.path_id}})
    game.save_typetree(game_tree)
    return env.file.save(packer="original")


class AccessoryPhysicsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = combined_fixture()
        self.source = self.root / "combined.unity"
        self.source.write_bytes(self.raw)
        prepared = model_viewer.prepare([str(self.source)], rigged=True,
                                        face_context={"enabled": False, "allow_download": False})
        self.token = prepared["id"]
        self.catalog = edits.register_session(self.token, [str(self.source)], prepared["rig"])
        self.addCleanup(edits._SESSIONS.pop, self.token, None)
        self.bone = self.catalog["physics"]["components"][0]

    def test_accessory_and_physics_save_together_and_map_to_counterpart(self):
        state = edits.validate_state(self.token, {"version": 1, "edits": [], "accessoryUnclip": {},
            "physics": [{"id": self.bone["id"], "values": {"dragForce": .6}}]})
        self.assertTrue(edits.has_changes(state))
        preview = edits.accessory_preview(self.token, state)
        self.assertEqual(preview["summary"]["status"], "applied")
        self.assertEqual(len(preview["corrections"]), 1)
        output = edits.export(self.token, state, self.root / "out")
        saved = edits._inspect(Path(output["preview_paths"][0]).read_bytes())
        original = edits._inspect(self.raw)
        anchor = next(key for key, name in saved["names"].items() if name == "PartsA_Offset")
        delta = preview["corrections"][0]["delta"]
        self.assertTrue(np.allclose(np.asarray(saved["authored"][anchor]["position"]) - original["authored"][anchor]["position"],
                                    [-delta[0], delta[1], delta[2]], atol=1e-5))
        physics = viewer_physics.inspect_info(saved, 0, [])
        self.assertAlmostEqual(physics[0]["values"]["dragForce"], .6, places=6)
        context = edits.mod_source_context(self.token)
        mapped, proof = paired._map_state(context, state, 0, original, context, original)
        self.assertEqual(mapped["physics"], state["physics"])
        self.assertEqual(mapped["accessoryUnclip"], state["accessoryUnclip"])
        self.assertTrue(any("sourcePhysics" in row for row in proof))
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_scene_recipe_filters_and_reanchors_physics_source_with_accessory_option(self):
        local_id = self.bone["id"].split(":", 1)[1]
        recipe = {"sources": [{"sha256": "other-source"}, {"sha256": hashlib.sha256(self.raw).hexdigest()}],
                  "nodeIdentities": [], "state": {"version": 1, "savedSettingsEnabled": True,
                      "edits": [], "unsupported": [], "compensationReference": [], "accessoryUnclip": {},
                      "physics": [{"id": "0:" + local_id, "values": {"dragForce": .2}},
                                  {"id": "1:" + local_id, "values": {"dragForce": .7}}]}}
        normalized = roles._normalize_recipe(recipe, self.raw, self.source.name)
        self.assertEqual(normalized["state"]["physics"], [{"id": "0:" + local_id, "values": {"dragForce": .7}}])
        restored = edits.restore(self.token, normalized)
        output = edits.export(self.token, restored, self.root / "scene-restored")
        saved = edits._inspect(Path(output["preview_paths"][0]).read_bytes())
        self.assertAlmostEqual(viewer_physics.inspect_info(saved, 0, [])[0]["values"]["dragForce"], .7, places=6)
        self.assertEqual(len(edits.accessory_preview(self.token, restored)["corrections"]), 1)

    def test_manual_vertices_and_physics_keep_the_original_bound_accessory_preview(self):
        from webtools.core import viewer_mesh_tools as mesh
        state = {"version": 1, "edits": [], "accessoryUnclip": {},
                 "physics": [{"id": self.bone["id"], "values": {"dragForce": .8}}]}
        preview = edits.accessory_preview(self.token, state)
        identity = mesh.inspect(self.token)["meshes"][0]["mesh"]
        data = mesh.data(self.token, identity)
        moved = [[x, y + 1, z] for x, y, z in data["positions"]]
        changes = {"version": 1, "meshes": [{"mesh": identity, "positions": [
            {"vertex": index, "position": position} for index, position in enumerate(moved)]}]}
        output = mesh.export(self.token, changes, self.root / "manual-mesh", body_state=state)
        saved_raw = Path(output["preview_paths"][0]).read_bytes()
        saved, original = edits._inspect(saved_raw), edits._inspect(self.raw)
        anchor = next(key for key, name in saved["names"].items() if name == "PartsA_Offset")
        delta = preview["corrections"][0]["delta"]
        self.assertTrue(np.allclose(np.asarray(saved["authored"][anchor]["position"]) - original["authored"][anchor]["position"],
                                    [-delta[0], delta[1], delta[2]], atol=1e-5))
        _, records = mesh._mesh_records(saved_raw, 0)
        actual_positions, _, _, _ = mesh._arrays(records[0][1], records[0][2])
        self.assertTrue(np.allclose(actual_positions, moved, atol=1e-5))
        self.assertAlmostEqual(viewer_physics.inspect_info(saved, 0, [])[0]["values"]["dragForce"], .8, places=6)


if __name__ == "__main__":
    unittest.main()
