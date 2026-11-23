"""LiveCoreStageEffect.memberShadowPrefabs on a real stage effect (11015's, the only one in
the GL catalog with prefabs). ShadowComponent.Initialize instantiates the prefabs under the
members' shadow anchors, so the effect export must detach the prefab assets from the static
stage and hand them to the members as templates.

Set MV_SHADOW_PREFAB_BUNDLE to the decrypted 11015 stage_effect bundle (asset path ".@(" in
asset_a_en.db) to run it. The prefab textures are ETC/ASTC: the export test also needs
ASTCENC_BIN and ELICHIKA_TEXTURE65_BIN (without them the export fails, which the failure test
covers)."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_BUNDLE = os.environ.get("MV_SHADOW_PREFAB_BUNDLE", "")
_DECODERS = all(os.environ.get(name) for name in ("ASTCENC_BIN", "ELICHIKA_TEXTURE65_BIN"))


def _build(native, warnings=None):
    from webtools.core import model_viewer
    prepared = model_viewer.prepare([_BUNDLE], rigged=False, face_context={
        "enabled": False, "allow_download": False, "_mv_stage": True, "_mv_authored_motion": False,
        "_mv_stage_motion_bindings": (), "_mv_performer": False, "_mv_native_stage_effect": native})
    if warnings is not None:
        warnings.extend(prepared.get("warnings") or ())
    payload = model_viewer.get_model(prepared["id"])
    length = int.from_bytes(payload[12:16], "little")
    return json.loads(payload[20:20 + length])


@unittest.skipUnless(_BUNDLE and Path(_BUNDLE).is_file() and _DECODERS,
                     "Set MV_SHADOW_PREFAB_BUNDLE, ASTCENC_BIN and ELICHIKA_TEXTURE65_BIN")
class StageShadowPrefabTest(unittest.TestCase):
    def build(self, native):
        return _build(native)

    def test_prefabs_are_member_templates_not_stage_meshes(self):
        doc = self.build(True)
        extras = doc["scenes"][0]["extras"]
        self.assertIs(extras["mvMemberShadowDefaults"], False)
        prefabs = extras["mvMemberShadowPrefabs"]
        self.assertEqual(prefabs["schema"], 1)
        rows = [(prefab["scale"], [doc["accessors"][prefab["geometry"][key]]["count"]
                                   for key in ("POSITION", "TEXCOORD_0", "indices")],
                 doc["images"][doc["textures"][prefab["texture"]]["source"]]["name"]) for prefab in prefabs["prefabs"]]
        self.assertEqual(rows, [([2.0, 2.0, 2.0], [12, 12, 30], "dropshadow"),
                                ([2.0, 2.0, 2.0], [4, 4, 6], "dropshadow_02")])
        long = doc["accessors"][prefabs["prefabs"][1]["geometry"]["POSITION"]]
        self.assertAlmostEqual(long["max"][2], 8.7694, places=3)
        names = {node.get("name") for node in doc["nodes"]}
        self.assertFalse(names & {"Shadows_02", "Shadows_03"}, "prefab assets are not stage objects")

    def test_other_previews_are_unchanged(self):
        extras = self.build(False)["scenes"][0].get("extras", {})
        self.assertNotIn("mvMemberShadowPrefabs", extras)


@unittest.skipUnless(_BUNDLE and Path(_BUNDLE).is_file(), "MV_SHADOW_PREFAB_BUNDLE is not set")
class StageShadowPrefabFailureTest(unittest.TestCase):
    def test_unexported_prefabs_warn_instead_of_dropping_the_shadows_silently(self):
        from unittest import mock

        from webtools.core import mv_studio_member_shadow

        warnings = []
        with mock.patch.object(mv_studio_member_shadow, "export_prefabs", return_value=None):
            doc = _build(True, warnings)
        extras = doc["scenes"][0]["extras"]
        # The templates stay detached and the costume shadows off, as the game has them.
        self.assertIs(extras["mvMemberShadowDefaults"], False)
        self.assertNotIn("mvMemberShadowPrefabs", extras)
        self.assertIn("member_shadow_prefabs_unavailable", [item["code"] for item in warnings])


if __name__ == "__main__":
    unittest.main()
