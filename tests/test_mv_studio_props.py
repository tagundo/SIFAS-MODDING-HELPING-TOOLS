from pathlib import Path
import json
import math
import os
import struct
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import model_animation, model_viewer, mv_studio, mv_studio_props
from webtools.core import mv_studio_stage_particles, mv_studio_timeline


_FIXTURE = os.environ.get("ELICHIKA_AION_PROP_FIXTURE")
# A folder holding the 12028 originals (props.bundle = ske_so2028, choreo00.bundle
# = ch0208_so2028, member_model_00 and member_companions_00-02 bundles,
# timeline.bundle) and the GL client runtime dump (mv-runtime-dump.json.gz).
_AION_DATA = os.environ.get("ELICHIKA_AION_PROP_DATA")
_HAND = "Reference/Move/Hips_Position/Hips/Spine/Spine1/Spine2/RightShoulder/RightArm/RightForeArm/RightHand"
_TARGET = "/EntryPoint/Live/Members/ske_so2028/Member1/Model/" + _HAND + "/chp0001"
_DECOR = _HAND + "/chp0001/Attach_01/Attach_02/Attach_03/Decor"


def _identity(path):
    return {"path": path, "position": [0., 0., 0.], "rotation": [0., 0., 0., 1.], "scale": [1., 1., 1.]}


def _rig(paths):
    """A RigBuilder holding primary bones at these paths (path "" is the prefab root)."""
    import numpy as np
    from webtools.core.model_rig import RigBuilder
    rig = RigBuilder.__new__(RigBuilder)
    rig.deadline, rig.node_bindings, rig.worlds = float("inf"), {}, {}
    rig.glb = SimpleNamespace(doc={"nodes": [{"name": "Character"}]})
    rig.bones = []
    for path in paths:
        node = len(rig.glb.doc["nodes"])
        rig.glb.doc["nodes"].append({"name": path.rsplit("/", 1)[-1] or "Model"})
        rig.bones.append({"node": node, "path": path, "sourceIndex": 0, "transformId": str(node)})
        rig.worlds[node] = np.eye(4)
        rig._binding(path, node)
    return rig


class MemberPropSkeletonMergeTests(unittest.TestCase):
    """UnityObjectUtility.MergeHierarchy: name matches recurse, the rest keep their local TRS."""

    def test_unmatched_nodes_move_below_their_matched_parent_with_authored_locals(self):
        from zlib import crc32
        hand = "Reference/RightHand"
        rig = _rig(["", "Reference", hand, hand + "/RightHandIndex1"])
        nodes = [_identity("Reference"), _identity(hand), _identity(hand + "/RightHandIndex1"),
                 _identity(hand + "/chp0001"),
                 {"path": hand + "/chp0001/Attach_01", "position": [.25, 0., 0.], "rotation": [0., .6, 0., .8],
                  "scale": [1., 2., 1.]},
                 _identity(hand + "/chp0001/Attach_01/Decor"), _identity("Member1_chp0007")]
        merged = rig.merge_prop_skeleton(nodes)
        self.assertEqual([rig.glb.doc["nodes"][node]["extras"]["originalName"] for node in merged],
                         ["chp0001", "Attach_01", "Decor", "Member1_chp0007"])
        bones = {bone["path"]: bone for bone in rig.bones}
        # Matched names reuse the member's own bones; nothing is duplicated.
        self.assertEqual(sum(bone["path"] == hand for bone in rig.bones), 1)
        self.assertEqual(bones[hand + "/chp0001"]["parent"], bones[hand]["node"])
        self.assertEqual(bones[hand + "/chp0001/Attach_01"]["parent"], bones[hand + "/chp0001"]["node"])
        self.assertEqual(bones["Member1_chp0007"]["parent"], bones[""]["node"])
        self.assertTrue(all(bones[path]["propSkeleton"] for path in (hand + "/chp0001", "Member1_chp0007")))
        # SetParent(parent, false) keeps the authored local (mirrored into glTF space).
        attach = rig.glb.doc["nodes"][bones[hand + "/chp0001/Attach_01"]["node"]]
        self.assertEqual(attach["translation"], [-.25, 0., 0.])
        self.assertEqual(attach["rotation"], [0., -.6, -0., .8])
        self.assertEqual(attach["scale"], [1., 2., 1.])
        self.assertIn(bones[hand + "/chp0001/Attach_01"]["node"],
                      rig.glb.doc["nodes"][bones[hand + "/chp0001"]["node"]]["children"])
        # The member's dance clips bind the merged nodes by the usual path hash.
        for path in (hand + "/chp0001", hand + "/chp0001/Attach_01", hand + "/chp0001/Attach_01/Decor"):
            self.assertEqual(model_animation._nodes(rig.node_bindings, crc32(path.encode())), [bones[path]["node"]])

    def test_a_missing_bone_reparents_the_skeleton_branch_at_its_deepest_match(self):
        rig = _rig(["", "Reference", "Reference/RightArm"])
        nodes = [_identity("Reference"), _identity("Reference/RightArm"), _identity("Reference/RightArm/RightHand"),
                 _identity("Reference/RightArm/RightHand/chp0001")]
        merged = rig.merge_prop_skeleton(nodes)
        bones = {bone["path"]: bone for bone in rig.bones}
        self.assertEqual(len(merged), 2)
        self.assertEqual(bones["Reference/RightArm/RightHand"]["parent"], bones["Reference/RightArm"]["node"])
        self.assertEqual(bones["Reference/RightArm/RightHand/chp0001"]["parent"], bones["Reference/RightArm/RightHand"]["node"])

    def test_an_ambiguous_member_path_skips_only_its_branch(self):
        rig = _rig(["", "Reference", "Reference/LeftHand", "Reference/RightHand", "Reference/RightHand"])
        nodes = [_identity("Reference"), _identity("Reference/RightHand"), _identity("Reference/RightHand/chp0001"),
                 _identity("Reference/LeftHand"), _identity("Reference/LeftHand/chp0002")]
        for bone in rig.bones[-1:]:
            bone["sourceIndex"] = 0
        merged = rig.merge_prop_skeleton(nodes)
        self.assertEqual([rig.glb.doc["nodes"][node]["extras"]["originalName"] for node in merged], ["chp0002"])

    def test_the_merge_is_all_or_nothing(self):
        from webtools.core import model_rig
        rig = _rig(["", "Reference"])
        before = len(rig.glb.doc["nodes"])
        broken = [_identity("Reference"), _identity("Reference/chp0001"),
                  {**_identity("Reference/chp0001/Attach_01"), "rotation": [0., 0., 0., 0.]}]
        with self.assertRaises(ValueError):
            rig.merge_prop_skeleton(broken)
        self.assertEqual(len(rig.glb.doc["nodes"]), before)
        with patch.object(model_rig, "MAX_NODES", before + 1):
            with self.assertRaisesRegex(model_rig.RigError, "node limit"):
                rig.merge_prop_skeleton([_identity("Reference"), _identity("Reference/chp0001"),
                                         _identity("Reference/chp0001/Decor")])
        self.assertEqual(len(rig.glb.doc["nodes"]), before)

    def test_each_member_builds_and_caches_its_own_merged_skeleton(self):
        from webtools.core import mv_studio_actor_cache
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, face = root / "model", root / "face"
            model.write_bytes(b"model")
            face.write_bytes(b"face")
            cache = mv_studio_actor_cache.ActorCache(root, ("gl", "android"), lambda name: (root / name, "glb"))
            shared = cache.inputs(b"timeline", [])
            plain = cache.key(shared, 1, 208, model, [face], [])
            self.assertEqual(cache.key(shared, 1, 208, model, [face], [], props=()), plain)
            merged = cache.key(shared, 1, 208, model, [face], [], props=[_identity("Reference/chp0001")])
            self.assertNotIn(merged, (None, plain))
            moved = cache.key(shared, 1, 208, model, [face], [], props=[
                {**_identity("Reference/chp0001"), "position": [0., .1, 0.]}])
            self.assertNotIn(moved, (None, plain, merged))


class MVStudioPropBindingsTests(unittest.TestCase):
    def test_matches_exact_animation_and_activation_target(self):
        tracks = [
            {"id": "motion", "nativeClass": "AnimationTrack", "binding": _TARGET,
             "events": [{"id": "clip", "values": {"animation": "cab:123"}}]},
            {"id": "different", "nativeClass": "ActivationTrack", "binding": _TARGET + "2"},
        ]
        self.assertEqual(mv_studio_props.bindings(tracks), [])
        tracks.append({"id": "visibility", "nativeClass": "ActivationTrack", "binding": _TARGET})
        binding, = mv_studio_props.bindings(tracks)
        self.assertEqual((binding["member"], binding["bone"]), (1, _HAND))
        self.assertEqual(binding["activation"], ["visibility"])
        self.assertEqual(binding["clips"], {"clip": "cab:123"})

    @unittest.skipUnless(_FIXTURE, "Set ELICHIKA_AION_PROP_FIXTURE to the native Aion catalog fixture.")
    def test_complete_original_assets_in_both_platforms(self):
        fixture = Path(_FIXTURE)
        with tempfile.TemporaryDirectory() as media, patch.object(mv_studio, "_root", return_value=Path(media)):
            for platform, key in (("android", "a"), ("ios", "i")):
                with self.subTest(platform=platform):
                    stages = []
                    project = mv_studio.load_game(
                        fixture / "runtime", region="gl", platform=platform, live_id=12028,
                        asset_id=1202803, language="en", on_stage=stages.append,
                    )
                    self.assertEqual(len(stages), 1)
                    self.assertTrue(stages[0]["stage"]["glb"])
                    self.assertFalse(any(row.get("attachment") for row in stages[0]["assets"]))
                    effects = project["stageParticles"]
                    tracks = {track["id"]: track for track in project["tracks"]}
                    self.assertEqual(len(effects["cues"]), 8)
                    self.assertEqual(effects["schema"], mv_studio_stage_particles.SCHEMA)
                    self.assertEqual(sorted(len(levels) for levels in effects["textures"]), [9, 9, 10, 10])
                    waves, umbrellas = [], []
                    for cue in effects["cues"]:
                        track = tracks[cue["trackId"]]
                        clip, = [event for event in track["events"] if event["id"] == cue["eventId"]]
                        template = effects["templates"][cue["template"]]
                        if track["label"].endswith("/par_15_foot_wave"):
                            waves.append(round(clip["start"], 6))
                            ripples = [emitter for emitter in template if emitter["material"]["premultiply"]]
                            self.assertEqual([round(emitter["birth"], 8) for emitter in ripples], [0, .05, .1])
                            glow, = [emitter for emitter in template if not emitter["material"]["premultiply"]]
                            self.assertEqual(glow["material"]["cull"], 0)
                            self.assertEqual(glow["size"], 1.5)
                            self.assertEqual(len(glow["geometry"]["positions"]), 4)
                            self.assertEqual(tuple(glow["rollRange"]), (-1.570796251296997, 1.570796251296997))
                        elif track["label"].endswith("/flo_01-03_umbrella"):
                            umbrellas.append(round(clip["start"], 6))
                            emitter, = [item for item in template if not item.get("orbitY")]
                            self.assertEqual(emitter["birth"], 0)
                            self.assertEqual(emitter["material"]["cull"], 2)
                            self.assertEqual(emitter["geometry"]["uv"], [[0, 0], [1, 0], [1, 1], [0, 1]])
                            self.assertAlmostEqual(math.hypot(*emitter["geometry"]["positions"][0]), .5)
                            ring = [item for item in template if item.get("orbitY")]
                            self.assertEqual(len(ring), 6 if round(clip["start"], 6) == 75.016667 else 8)
                            self.assertTrue(all(item["birth"] == 0 and item["lifetime"] == 90 for item in ring))
                            for item in ring:
                                self.assertAlmostEqual(item["orbitY"], .075)
                                x, _, z = item["position"]
                                self.assertAlmostEqual(math.hypot(x, z), 3.8, places=6)
                        else:
                            self.fail(track["label"])
                    self.assertEqual(waves, [42.85, 46, 49.333333, 50.933333])
                    self.assertEqual(umbrellas, [58.933333, 62.183333, 75.016667, 78.016667])
                    ribbons = project["stageRibbons"]
                    self.assertEqual(len(ribbons["geometry"]["positions"]), 9)
                    self.assertEqual(len(ribbons["geometry"]["indices"]), 24)
                    self.assertEqual([len(levels) for levels in ribbons["textures"]], [10, 10])
                    ribbon_times = []
                    for cue in ribbons["cues"]:
                        track = tracks[cue["trackId"]]
                        clip, = [event for event in track["events"] if event["id"] == cue["eventId"]]
                        ribbon_times.append((round(clip["start"], 6), round(clip["duration"], 6)))
                        self.assertEqual([mesh["name"] for mesh in cue["meshes"]], [f"obi_0{i}" for i in range(4)])
                        self.assertEqual({mesh["material"]["cull"] for mesh in cue["meshes"]}, {2})
                        self.assertEqual({channel["kind"] for channel in cue["animation"]["channels"]},
                                         {"translation", "overlayUV", "overlayTint", "visibility"})
                    self.assertEqual(ribbon_times, [(10.35, 48.933333), (59.283333, 38.6)])
                    shine = ribbons["shine"]
                    self.assertEqual([level["width"] for level in shine["texture"]],
                                     [256 >> index for index in range(9)])
                    self.assertEqual([item["eventId"] for item in shine["cues"]],
                                     [item["eventId"] for item in ribbons["cues"]])
                    self.assertEqual([item["lifetime"] for item in shine["cues"]], [[10, 13], [10, 10]])
                    self.assertTrue(all(item["rate"] == 10 and item["cycle"] == 5 for item in shine["cues"]))
                    spotlight = project["stageSpotlight"]
                    spot_track = tracks[spotlight["trackId"]]
                    spot, = [event for event in spot_track["events"] if event["id"] == spotlight["eventId"]]
                    self.assertEqual(spot_track["label"], "StageEffect/Expert/Control/par_12_spot")
                    self.assertAlmostEqual(spot["start"], 75.0166666667)
                    self.assertAlmostEqual(spot["duration"], 3)
                    self.assertAlmostEqual(spotlight["duration"], 1.8)
                    shapes = {mesh["name"]: (len(mesh["positions"]), len(mesh["indices"]))
                              for mesh in spotlight["meshes"]}
                    self.assertEqual(shapes, {"Glow_03": (84, 390), "Glow_02": (81, 420)})
                    for mesh in spotlight["meshes"]:
                        self.assertEqual(len(mesh["alpha"]), len(mesh["positions"]))
                        self.assertEqual(len(mesh["matrix"]), 16)
                        self.assertEqual(len(mesh["tintCurves"]), 4)
                    butterfly = project["stageButterfly"]
                    butterfly_track = tracks[butterfly["trackId"]]
                    cue, = butterfly_track["events"]
                    self.assertEqual(butterfly_track["label"], "StageEffect/Expert/Control/par_13_butterfly")
                    self.assertEqual(cue["id"], butterfly["eventId"])
                    self.assertAlmostEqual(cue["start"], 1781 / 60)
                    self.assertAlmostEqual(cue["start"] + cue["duration"], 2571 / 60)
                    self.assertEqual(len(butterfly["geometry"]["positions"]), 6)
                    self.assertEqual(len(butterfly["geometry"]["indices"]), 12)
                    self.assertEqual(len(butterfly["animation"]["curves"]), 3)
                    self.assertEqual([level["width"] for level in butterfly["texture"]], [512 >> i for i in range(10)])
                    self.assertEqual(butterfly["particle"]["size"], 6)
                    self.assertEqual(butterfly["material"]["tint"], [2, 2, 2, 1])
                    finale = butterfly["finale"]
                    finale_track = tracks[finale["trackId"]]
                    finale_cue, = finale_track["events"]
                    self.assertEqual(finale_track["label"], "StageEffect/Expert/Control/par_14_butterfly")
                    self.assertEqual(finale_cue["id"], finale["eventId"])
                    self.assertAlmostEqual(finale_cue["start"], 5341 / 60)
                    self.assertAlmostEqual(finale_cue["duration"], 531 / 60)
                    self.assertEqual(finale["geometry"], butterfly["geometry"])
                    self.assertEqual([level["width"] for level in finale["texture"]], [512 >> i for i in range(10)])
                    self.assertNotEqual(finale["texture"][0], butterfly["texture"][0])
                    self.assertEqual(finale["particle"]["size"], 9)
                    self.assertAlmostEqual(finale["particle"]["lifetime"], 5.55, places=6)
                    self.assertEqual(len(finale["animation"]["tintCurves"]), 4)
                    opening_glow, finale_glow = butterfly["glow"], finale["glow"]
                    self.assertEqual((opening_glow["profile"], finale_glow["profile"]), ("opening", "finale"))
                    self.assertEqual((opening_glow["activation"], finale_glow["activation"]), (0, 5.083333492279053))
                    self.assertEqual((opening_glow["maxViewportWidth"], finale_glow["maxViewportWidth"]), (.5, 1))
                    self.assertEqual(opening_glow["uv"], finale_glow["uv"])
                    self.assertEqual(opening_glow["uv"], [.5, .5, .5, .5])
                    self.assertEqual([mip["width"] for mip in butterfly["glowTexture"]], [256 >> i for i in range(9)])
                    butterfly_shine = butterfly["shine"]
                    self.assertEqual(butterfly_shine["profile"], "opening")
                    self.assertEqual(butterfly_shine["uv"], [.25, .25, .75, 0])
                    self.assertEqual(butterfly_shine["maxViewportWidth"], .5)
                    self.assertEqual([len(keys) for keys in butterfly_shine["sizeKeys"]], [15, 20])
                    self.assertEqual(len(butterfly_shine["startRGB"]), 6)
                    self.assertEqual([len(keys) for keys in butterfly_shine["alphaKeys"]], [8, 8])
                    self.assertNotIn("texture", butterfly_shine)
                    self.assertNotIn("shine", finale)
                    butterfly_dust = finale["dust"]
                    self.assertEqual(butterfly_dust["profile"], "finale")
                    self.assertAlmostEqual(butterfly_dust["activation"], 5 + 25 / 60, places=6)
                    self.assertEqual(butterfly_dust["position"], [0, 0, 0])
                    self.assertEqual(butterfly_dust["uv"], [.25, .25, 0, 0])
                    self.assertEqual([len(keys) for keys in butterfly_dust["sizeKeys"]], [10, 12])
                    self.assertEqual([len(keys["min"]) for keys in butterfly_dust["velocity"]], [4, 2, 2])
                    self.assertEqual([row["role"] for row in butterfly_dust["emitters"]], ["add", "alpha"])
                    self.assertEqual({row["material"]["blend"] for row in butterfly_dust["emitters"]}, {"add", "alpha"})
                    self.assertNotIn("texture", butterfly_dust)
                    rain = project["stageRain"]
                    self.assertEqual([cue["profile"] for cue in rain["cues"]], ["01", "02"])
                    self.assertEqual(rain["texture"], butterfly["glowTexture"])
                    self.assertEqual(rain["uv"], [.25, .25, .5, 0])
                    self.assertEqual([round(cue["position"][1], 5) for cue in rain["cues"]], [15.01, 8.54])
                    self.assertEqual([len(keys) for keys in rain["sizeKeys"]], [3, 3])
                    self.assertEqual(len(rain["startRGB"]), 3)
                    self.assertEqual({name: len(keys) for name, keys in rain["colorKeys"].items()}, {"rgb": 2, "alpha": 4})
                    for index, cue in enumerate(rain["cues"]):
                        self.assertEqual(tracks[cue["trackId"]]["label"], "StageEffect/Expert/Control/par_01-02_rain")
                        self.assertEqual(tracks[cue["trackId"]]["events"][index]["id"], cue["eventId"])
                    floor_textures = rain["impactTextures"]
                    self.assertEqual(set(floor_textures), {"wave", "glow"})
                    self.assertEqual([[level["width"] for level in chain] for chain in floor_textures.values()],
                                     [[256 >> i for i in range(9)]] * 2)
                    self.assertNotEqual(floor_textures["wave"], floor_textures["glow"])
                    for index, cue in enumerate(rain["cues"]):
                        wave, glow = (cue["impact"][name] for name in ("wave", "glow"))
                        self.assertAlmostEqual(wave["position"][1], .02)
                        self.assertEqual(wave["position"][2], index)
                        self.assertEqual(wave["startColor"]["mode"], (1, 4)[index])
                        self.assertEqual(wave["material"]["cull"], 2)
                        self.assertTrue(wave["material"]["saturate"])
                        self.assertEqual(glow["material"]["cull"], 0)
                        self.assertFalse(glow["material"]["saturate"])
                        self.assertEqual(glow["uv"], [.5] * 4)
                    leaves = project["stageLeaves"]
                    self.assertEqual(leaves["texture"], rain["texture"])
                    self.assertEqual(leaves["material"]["blend"], "alpha")
                    self.assertEqual({key: len(values) for key, values in leaves["geometry"].items()},
                                     {"positions": 22, "uv": 22, "indices": 60})
                    self.assertEqual(leaves["alphaKeys"], [[0, 0], [6554, 1], [58982, 1], [65535, 0]])
                    self.assertEqual([(cue["profile"], cue["rate"], cue["uv"]) for cue in leaves["cues"][:2]],
                                     [("03", 12, [.25, .25, 0, .25]), ("04", 10, [.25, .25, .5, .25])])
                    for cue in leaves["cues"][:2]:
                        self.assertEqual(tracks[cue["trackId"]]["events"][0]["id"], cue["eventId"])
                    red_leaves = [cue for cue in leaves["cues"] if cue["profile"] == "06"]
                    self.assertEqual([(cue["profile"], cue["rate"], cue["uv"]) for cue in red_leaves],
                                     [("06", 20, [.25, .25, .25, .25])] * 4)
                    self.assertEqual([cue["seed"] for cue in red_leaves], [670425550, 8958, 670425550, 2336])
                    self.assertEqual([cue["overwriteRandomSeed"] for cue in red_leaves], [False, True, False, True])
                    red_events = tracks[red_leaves[0]["trackId"]]["events"]
                    self.assertEqual([cue["eventId"] for cue in red_leaves], [event["id"] for event in red_events])
                    floor_leaves = [cue for cue in leaves["cues"] if cue["profile"] == "07"]
                    self.assertEqual(len(floor_leaves), 3)
                    floor_events = tracks[floor_leaves[0]["trackId"]]["events"]
                    self.assertEqual([cue["eventId"] for cue in floor_leaves], [event["id"] for event in floor_events])
                    for cue in floor_leaves:
                        self.assertEqual(cue["uv"], [.25] * 4)
                        self.assertAlmostEqual(cue["position"][1], .06)
                        self.assertEqual([(emitter["role"], emitter["seed"], emitter["rate"], emitter["material"]["blend"])
                                          for emitter in cue["emitters"]],
                                         [("alpha", 3279275062, 7, "alpha"), ("add", 363848346, 3, "add")])
                    transition, = [cue for cue in leaves["cues"] if cue["profile"] == "05"]
                    transition_track = tracks[transition["trackId"]]
                    self.assertEqual(transition_track["label"], "StageEffect/Expert/Control/par_05_momij_burst")
                    self.assertEqual(transition_track["events"][0]["id"], transition["eventId"])
                    self.assertEqual([(row["role"], row["seed"], row["uv"][2]) for row in transition["emitters"]],
                                     [("green-burst", 3279275062, 0), ("yellow-burst", 3364901415, .5),
                                      ("red-burst", 1586243424, .25),
                                      ("red-in", 1722352272, .25)])
                    self.assertTrue(all(row["material"] == leaves["material"] for row in transition["emitters"]))
                    momiji = project["stageMomiji"]
                    momiji_track = tracks[momiji["trackId"]]
                    self.assertEqual(momiji_track["label"], "StageEffect/Expert/Display/dis_par_03_momiji")
                    self.assertEqual(momiji_track["events"][0]["id"], momiji["eventId"])
                    self.assertEqual([row["role"] for row in momiji["emitters"]], ["fan", "flash", "leaf-green", "leaf-red"])
                    self.assertEqual(momiji["geometry"], leaves["geometry"])
                    self.assertEqual(momiji["textures"]["leaf"], leaves["texture"])
                    self.assertEqual({name: len(mips) for name, mips in momiji["textures"].items()},
                                     {"fan": 9, "flash": 7, "leaf": 9})
                    self.assertEqual([(row["material"]["cull"], row["material"]["blend"]) for row in momiji["emitters"]],
                                     [(1, "alpha"), (0, "add"), (0, "alpha"), (0, "alpha")])
                    self.assertTrue(all(row["material"]["queue"] == 2900 and row["material"]["stencilRef"] == 2
                                        for row in momiji["emitters"]))
                    confetti = project["stageConfetti"]
                    confetti_track = tracks[confetti["cues"][0]["trackId"]]
                    self.assertEqual(confetti_track["label"], "StageEffect/Expert/Control/par_08_confetti")
                    self.assertEqual([cue["eventId"] for cue in confetti["cues"]],
                                     [event["id"] for event in confetti_track["events"]])
                    self.assertEqual(confetti["texture"], leaves["texture"])
                    self.assertEqual(confetti["uv"], [.5, .5, 0, .5])
                    self.assertEqual({key: len(values) for key, values in confetti["geometry"].items()},
                                     {"positions": 16, "uv": 16, "indices": 42})
                    self.assertEqual([(row["role"], row["seed"], row["rate"]) for row in confetti["emitters"]],
                                     [("air", 1425677110, 70), ("floor", 3279275062, 3)])
                    self.assertEqual((confetti["material"]["queue"], confetti["material"]["blend"],
                                      confetti["material"]["stencil"]), (3010, "add", "always"))
                    stage_glow = project["stageGlow"]
                    glow_track = tracks[stage_glow["cues"][0]["trackId"]]
                    self.assertEqual(glow_track["label"], "StageEffect/Expert/Control/par_09_glow")
                    self.assertEqual([cue["eventId"] for cue in stage_glow["cues"]],
                                     [event["id"] for event in glow_track["events"]])
                    self.assertEqual([(cue["seed"], cue["overwriteRandomSeed"]) for cue in stage_glow["cues"]],
                                     [(6433, True), (2559958440, False)])
                    self.assertEqual(stage_glow["position"], [-2.7699999809265137, 2.4800000190734863, .5])
                    self.assertEqual(stage_glow["uv"], [.25, 1, .5, 0])
                    self.assertEqual([(row["width"], row["height"]) for row in stage_glow["texture"]],
                                     [(256 >> i, max(1, 128 >> i)) for i in range(9)])
                    self.assertEqual((stage_glow["material"]["queue"], stage_glow["material"]["blend"],
                                      stage_glow["material"]["stencil"]), (3010, "add", "always"))
                    lens = project["stageLensFlare"]
                    lens_track = tracks[lens["cues"][0]["trackId"]]
                    self.assertEqual(lens_track["label"], "StageEffect/Expert/Control/par_10-11_lensflare")
                    self.assertEqual([cue["eventId"] for cue in lens["cues"]],
                                     [event["id"] for event in lens_track["events"]])
                    emitters = {row["id"]: row for row in lens["emitters"]}
                    self.assertTrue(all(cue["emitterId"].split(":")[0] == cue["trackId"].split(":")[0]
                                        for cue in lens["cues"]))
                    self.assertEqual([emitters[cue["emitterId"]]["rate"] for cue in lens["cues"]], [10, 15, 15])
                    self.assertEqual({cue["quality"] for cue in lens["cues"]}, {"stage_control"})
                    self.assertEqual([(row["autoSeed"], row["seed"], row["rate"]) for row in lens["emitters"]],
                                     [(True, 0, 10), (False, 0, 15)])
                    self.assertEqual(len(lens["textures"]), 1)
                    self.assertEqual([(row["width"], row["height"]) for row in lens["textures"][0]],
                                     [(128 >> i, max(1, 64 >> i)) for i in range(8)])
                    for emitter in lens["emitters"]:
                        self.assertGreater(emitter["sortCenter"][1], emitter["position"][1])
                    self.assertEqual((lens["material"]["queue"], lens["material"]["blend"],
                                      lens["material"]["stencil"], lens["tiles"]), (3010, "add", "always", [2, 1]))
                    stage_glb, _ = mv_studio.media(stages[0]["stage"]["glb"].rsplit("/", 1)[-1])
                    stage_bytes = stage_glb.read_bytes()
                    stage_length = int.from_bytes(stage_bytes[12:16], "little")
                    stage_doc = json.loads(stage_bytes[20:20+stage_length])
                    stage_ambient = [primitive["extras"]["mvStageMaterial"]
                                     for mesh in stage_doc["meshes"] for primitive in mesh["primitives"]
                                     if "singleAmbientBinding" in primitive.get("extras", {}).get("mvStageMaterial", {})]
                    self.assertEqual({data["singleAmbientBinding"].rsplit("/", 1)[-1] for data in stage_ambient},
                                     {f"Ambient{i}" for i in range(1, 9)})
                    cutouts = [data for data in stage_ambient if "alphaCutoff" in data]
                    self.assertEqual([data["alphaCutoff"] for data in cutouts], [.5, .5, .5])
                    far, = [data for data in cutouts if "emissive" in data]
                    image = stage_doc["textures"][far["emissive"]["texture"]]["source"]
                    self.assertEqual(stage_doc["images"][image]["name"], "bg0025_01_farAalp_emi")
                    effect, = [item for item in stages[0]["assets"] if item["kind"] == "effect"]
                    effect_glb, _ = mv_studio.media(effect["previewUrl"].rsplit("/", 1)[-1])
                    effect_bytes = effect_glb.read_bytes()
                    effect_length = int.from_bytes(effect_bytes[12:16], "little")
                    effect_doc = json.loads(effect_bytes[20:20+effect_length])
                    self.assertEqual(len(effect_doc["meshes"]), 151)
                    self.assertIs(effect_doc["scenes"][0]["extras"]["mvMemberShadowDefaults"], True)
                    self.assertGreater(len(effect_doc["meshes"]), model_viewer.MAX_MESHES)
                    overlays = {mesh["name"]: (primitive["extras"]["mvStageOverlay"]["cull"],
                                               effect_doc["accessors"][primitive["indices"]]["count"])
                                for mesh in effect_doc["meshes"] for primitive in mesh["primitives"]
                                if "mvStageOverlay" in primitive.get("extras", {})}
                    self.assertEqual(overlays, {"Glow_02": (0, 420), "Plane_02": (1, 24)})
                    overlay_track, = (track for track in tracks.values()
                                      if track.get("binding", "").endswith("/fx_ove_so2028_01/Effect_root"))
                    overlay_motion = project["stageMotion"]
                    self.assertEqual(overlay_motion["quality"][overlay_track["id"]], "stage_overlay_effect")
                    overlay_event, = overlay_track["events"]
                    overlay_clip = overlay_motion["clips"][overlay_event["values"]["animation"]]
                    self.assertTrue(overlay_clip["sampleTimeF32"])
                    self.assertEqual({(channel["path"], channel["kind"]) for channel in overlay_clip["channels"]
                                      if channel["kind"].startswith("overlay")},
                                     {(2350170846, "overlayTint"), (3121091544, "overlayTint"),
                                      (3121091544, "overlayUV")})
                    effect_ambient = [primitive["extras"]["mvStageMaterial"]["singleAmbientBinding"]
                                      for mesh in effect_doc["meshes"] for primitive in mesh["primitives"]
                                      if "singleAmbientBinding" in primitive.get("extras", {}).get("mvStageMaterial", {})]
                    self.assertEqual(effect_ambient, ["/EntryPoint/Live/Stages/MainStage/Effect"] * 76)
                    penlights = {primitive["extras"]["mvPenlight"]["bindingSuffix"]
                                 for mesh in effect_doc["meshes"] for primitive in mesh["primitives"]
                                 if "mvPenlight" in primitive.get("extras", {})}
                    self.assertEqual(penlights, {f"aud_root/aud_0{i}" for i in range(1, 7)})
                    self.assertIn("tex_aud_gen_01", [image["name"] for image in effect_doc["images"]])
                    flashlight, = [primitive for mesh in effect_doc["meshes"] for primitive in mesh["primitives"]
                                   if "mvStageFlash" in primitive.get("extras", {})]
                    flash, = [track for track in project["tracks"] if track["nativeClass"] == "LiveFlashLightTrack"]
                    fields = flashlight["extras"]["mvStageFlash"]
                    uv = effect_doc["accessors"][flashlight["attributes"]["_STAGE_FLASH_UV"]]
                    self.assertEqual((fields["binding"], fields["atlasST"], uv["count"]),
                                     (flash["binding"], [4, 2, 0, 0], 96))
                    names = [effect_doc["images"][effect_doc["textures"][fields[key]]["source"]]["name"]
                             for key in ("texture", "atlas")]
                    self.assertEqual(names, ["tex_grs_fla_gen_01", "tex_msk_fla_01_gen_01"])
                    prop, = [item for item in project["assets"] if item.get("attachment")]
                    actor, = project["performers"]
                    self.assertEqual((actor["memberId"], actor["position"]), (208, 1))
                    self.assertTrue(actor["motion"])
                    actor_glb, _ = mv_studio.media(actor["glb"].rsplit("/", 1)[-1])
                    actor_bytes = actor_glb.read_bytes()
                    actor_length = int.from_bytes(actor_bytes[12:16], "little")
                    actor_doc = json.loads(actor_bytes[20:20 + actor_length])
                    shadow = actor_doc["scenes"][0]["extras"]["mvMemberShadow"]
                    self.assertEqual(shadow["schema"], 1)
                    by_node = {row["extras"]["elichika_node"]: row["extras"]["originalName"]
                               for row in actor_doc["nodes"] if "originalName" in row.get("extras", {})}
                    self.assertEqual([by_node[node] for node in shadow["toes"]], ["LeftToeBase", "RightToeBase"])
                    self.assertEqual([by_node[node] for node in shadow["anchors"]], ["ShadowToeL", "ShadowToeR"])
                    self.assertEqual({key: actor_doc["accessors"][index]["count"]
                                      for key, index in shadow["geometry"].items()},
                                     {"POSITION": 12, "TEXCOORD_0": 12, "indices": 30})
                    texture = actor_doc["textures"][shadow["texture"]]["source"]
                    self.assertEqual(actor_doc["images"][texture]["name"], "dropshadow")
                    spec = prop["attachment"]
                    self.assertEqual((spec["member"], spec["bone"], spec["limit"]), (1, _DECOR, 135))
                    self.assertEqual(spec["binding"], _TARGET)
                    nodes = [bone["node"] for bone in actor["rig"]["bones"]
                             if bone["path"] == _DECOR or bone["path"].endswith("/" + _DECOR)]
                    self.assertEqual(len(nodes), 1)
                    raw, _ = mv_studio.media(prop["previewUrl"].rsplit("/", 1)[-1])
                    self._check_glb(raw.read_bytes())
                    curve, = spec["curves"].values()
                    self._check_angle(curve)
                    visibility, = [track for track in project["tracks"] if track["id"] in spec["activation"]]
                    interval, = visibility["events"]
                    self.assertEqual(interval["start"], 0)
                    self.assertAlmostEqual(interval["duration"], 97.8666666667)
                    for variant in (1202801, 1202802):
                        source = fixture / f"{key}-timeline-{variant}.unity"
                        native = source.read_bytes()
                        bindings, = mv_studio_props.bindings(mv_studio_timeline.parse_timeline(native, source.name)["tracks"])
                        glb, variant_spec = mv_studio_props.preview(
                            fixture / f"{key}-prop.unity", native, source.name, bindings, time.monotonic()+20,
                        )
                        self._check_glb(glb)
                        variant_curve, = variant_spec["curves"].values()
                        self._check_angle(variant_curve)

    def _check_glb(self, raw):
        length = int.from_bytes(raw[12:16], "little")
        document = json.loads(raw[20:20+length])
        primitive, = document["meshes"][0]["primitives"]
        attributes = primitive["attributes"]
        self.assertEqual(document["accessors"][attributes["_MV_FAN_UV"]]["count"], 288)
        colors = document["accessors"][attributes["_SIFAS_COLOR"]]
        self.assertEqual((colors["count"], colors["type"], colors["componentType"]), (288, "VEC4", 5126))
        color_data = document["bufferViews"][colors["bufferView"]]
        offset = 28 + length + color_data["byteOffset"]
        entries = list(struct.iter_unpack("<4f", raw[offset:offset + color_data["byteLength"]]))
        self.assertEqual(entries.count((1, 1, 1, 1)), 208)
        self.assertEqual(entries.count((0, 0, 1, 1)), 80)
        material = document["materials"][primitive["material"]]
        self.assertIn("KHR_materials_unlit", material["extensions"])
        native = material["extras"]["sifas"]
        self.assertEqual((native["version"], native["shader"], native["pipeline"]), (1, "AS/MemberProp", "gamma"))
        self.assertTrue(native["features"]["rimlight"])
        for field, name, size in (("_MainTex", "chp0001", 1024), ("_RimlightTex", "chp0001_rim", 256)):
            texture = native["textures"][field]
            widths = [size >> level for level in range(size.bit_length())]
            self.assertEqual(texture["mipWidths"], widths)
            self.assertEqual(texture["mipHeights"], widths)
            self.assertEqual(texture["filterMode"], 1)
            self.assertEqual(texture["mipmaps"][0], texture["index"])
            images = [document["images"][document["textures"][index]["source"]]["name"]
                      for index in texture["mipmaps"]]
            self.assertEqual(images, [name, *[f"{name}_mip_{i}" for i in range(1, len(widths))]])
        # The renderer's own merged node places it: no extra local transform.
        self.assertNotIn("matrix", document["nodes"][0])
        self.assertEqual(document["nodes"][0]["extras"], {"mvGameObjectPath": _DECOR})

    def _check_angle(self, source):
        self.assertEqual(source["mode"], "cubic")
        self.assertEqual(len(source["keys"]), 128)
        curve = source["mode"], source["keys"]
        self.assertEqual(model_animation._evaluate(curve, 1), 0)
        self.assertAlmostEqual(model_animation._evaluate(curve, 30), 135)


def _quaternion_multiply(a, b):
    x1, y1, z1, w1 = a
    x2, y2, z2, w2 = b
    return [w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2]


def _rotate(q, v):
    x, y, z, _ = _quaternion_multiply(_quaternion_multiply(q, [*v, 0.]), [-q[0], -q[1], -q[2], q[3]])
    return [x, y, z]


@unittest.skipUnless(_AION_DATA, "Set ELICHIKA_AION_PROP_DATA to the 12028 originals and GL runtime dump folder.")
class AionFanAgainstTheGameTests(unittest.TestCase):
    """The 12028 fan against the GL client (CI runtime dump of 1202803)."""

    @classmethod
    def setUpClass(cls):
        import gzip
        cls.data = Path(_AION_DATA)
        cls.dump = json.load(gzip.open(cls.data / "mv-runtime-dump.json.gz"))
        cls.records = cls.dump["records"]

    def test_member_merges_the_fan_skeleton_and_its_dance_clip_moves_the_fan(self):
        nodes = mv_studio_props.skeleton(self.data / "props.bundle", time.monotonic() + 60)
        self.assertEqual(set(nodes), {1})
        chain = [_HAND + "/chp0001" + suffix for suffix in ("", "/Attach_01", "/Attach_01/Attach_02",
                                                             "/Attach_01/Attach_02/Attach_03")] + [_DECOR]
        by_path = {node["path"]: node for node in nodes[1]}
        self.assertLessEqual(set(chain), set(by_path))
        for path in chain:
            self.assertEqual((by_path[path]["position"], by_path[path]["rotation"], by_path[path]["scale"]),
                             ([0, 0, 0], [0, 0, 0, 1], [1, 1, 1]))
        # The game merged chp0001 below Member1's own RightHand with its local identity.
        passes = [record for record in self.records if record.get("part") == "members"]
        self.assertEqual(len(passes), 5)
        for record in passes:
            bone, = [bone for bone in record["members"][0]["bones"] if bone["key"].endswith("/chp0001")]
            self.assertEqual(bone["path"], "/EntryPoint/Live/Members/Member1/Model/" + _HAND + "/chp0001")
            self.assertEqual((bone["localPosition"], bone["localRotation"]), ([0, 0, 0], [0, 0, 0, 1]))
        with tempfile.TemporaryDirectory() as directory:
            files = []
            for name in ("member_model_00", "member_companions_00", "member_companions_01", "member_companions_02",
                         "choreo00"):
                target = Path(directory) / (name + ".unity")
                target.write_bytes((self.data / (name + ".bundle")).read_bytes())
                files.append(str(target))
            prepared = model_viewer.prepare(files[:-1], rigged=True, motion_paths=files[-1:], face_context={
                "enabled": False, "allow_download": False, "_mv_stage": False, "_mv_authored_motion": True,
                "_mv_performer": True, "_mv_prop_skeleton": nodes[1]})
            raw = model_viewer.get_model(prepared["id"])
        rig = prepared["rig"]
        bones = {bone["path"]: bone for bone in rig["bones"]}
        self.assertEqual(bones[chain[0]]["parent"], bones[_HAND]["node"])
        self.assertTrue(all(bones[path].get("propSkeleton") for path in chain))
        dance, = [clip for clip in rig["clips"] if clip["sourceName"] == "ch0208_so2028"]
        self.assertEqual(dance["unboundTracks"], 0)
        length = int.from_bytes(raw[12:16], "little")
        document, binary = json.loads(raw[20:20 + length]), raw[28 + length:]

        def values(index):
            accessor = document["accessors"][index]
            view = document["bufferViews"][accessor["bufferView"]]
            width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[accessor["type"]]
            offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            flat = struct.unpack_from(f"<{accessor['count'] * width}f", binary, offset)
            return [flat[i:i + width] for i in range(0, len(flat), width)]

        animation = document["animations"][dance["index"]]
        channels = {}
        for channel in animation["channels"]:
            sampler = animation["samplers"][channel["sampler"]]
            channels[(channel["target"]["node"], channel["target"]["path"])] = (
                [row[0] for row in values(sampler["input"])], values(sampler["output"]))
        animated = {(path.rsplit("/", 1)[-1], kind) for path in chain for kind in ("translation", "rotation", "scale")
                    if (bones[path]["node"], kind) in channels}
        self.assertEqual(animated, {("Attach_01", "translation"), ("Attach_01", "rotation"), ("Attach_02", "translation"),
                                    ("Attach_02", "rotation"), ("Attach_02", "scale")})

        def sample(node, kind, seconds, rest):
            if (node, kind) not in channels:
                return list(rest)
            times, rows = channels[(node, kind)]
            index = max(0, min(len(times) - 2, next((i for i, t in enumerate(times) if t > seconds), len(times)) - 1))
            fraction = min(1, max(0, (seconds - times[index]) / (times[index + 1] - times[index])))
            first, second = list(rows[index]), list(rows[index + 1])
            if kind == "rotation" and sum(a * b for a, b in zip(first, second)) < 0:
                second = [-value for value in second]
            mixed = [a + (b - a) * fraction for a, b in zip(first, second)]
            if kind == "rotation":
                norm = math.sqrt(sum(value * value for value in mixed))
                mixed = [value / norm for value in mixed]
            return mixed

        def decor_offset(seconds):
            """The Decor origin below the hand (metres), composed from the exported dance channels."""
            position, rotation, scale = [0., 0., 0.], [0., 0., 0., 1.], [1., 1., 1.]
            for path in chain:
                node = bones[path]["node"]
                rest = document["nodes"][node]
                local = sample(node, "translation", seconds, rest.get("translation", (0, 0, 0)))
                position = [a + b for a, b in zip(position, _rotate(rotation, [s * v for s, v in zip(scale, local)]))]
                rotation = _quaternion_multiply(rotation, sample(node, "rotation", seconds, rest.get("rotation", (0, 0, 0, 1))))
                scale = [a * b for a, b in zip(scale, sample(node, "scale", seconds, rest.get("scale", (1, 1, 1))))]
            return math.sqrt(sum(value * value for value in position))

        # The game frames record the RightHand origin (anchors) but not its
        # rotation, so compare the rotation-free distance hand -> Decor where an
        # anchor brackets the Decor record on both sides within 0.4 s.
        anchors = sorted((record["clock"]["directorTime"], anchor["position"]) for record in self.records
                         for anchor in record.get("anchors") or () if anchor["key"] == "anchor:member1:RightHand")
        checked = []
        for record in self.records:
            for renderer in record.get("renderers", ()) if record.get("part") == "renderers" else ():
                if renderer["path"] != "/EntryPoint/Live/Members/Member1/Model/" + _DECOR:
                    continue
                seconds = record["clock"]["directorTime"]
                before = [row for row in anchors if seconds - .4 <= row[0] <= seconds]
                after = [row for row in anchors if seconds <= row[0] <= seconds + .4]
                if not before or not after:
                    continue
                game = [math.dist(renderer["transform"]["position"], row[1]) for row in (before[-1], after[0])]
                offset = decor_offset(seconds)
                self.assertGreater(offset, .03)
                self.assertGreaterEqual(offset, min(game) - .003, seconds)
                self.assertLessEqual(offset, max(game) + .003, seconds)
                checked.append(seconds)
        self.assertEqual(checked, [5.55, 27.885])

    def test_overlay_flares_sample_at_the_native_float_time_by_the_common_rule(self):
        # Every overlay-scope clip, fx_ove_so2028_01/Effect_root's MeshRenderer
        # clip included, samples at the normalized float time; world clips keep
        # their own sampling.
        native = (self.data / "timeline.bundle").read_bytes()
        parsed = mv_studio_timeline.parse_timeline(native, "timeline.bundle", preview_stage_motion=True)
        motion = parsed["stageMotion"]
        scopes = {}
        for track in parsed["tracks"]:
            setting = motion["quality"].get(track["id"])
            for event in track["events"]:
                if setting and event["id"] in motion["mix"]:
                    scopes.setdefault(event["values"]["animation"], set()).add(setting)
        overlay = [identity for identity, settings in scopes.items() if "stage_overlay_effect" in settings]
        self.assertEqual(len(overlay), 1)
        for identity, clip in motion["clips"].items():
            self.assertEqual(clip.get("sampleTimeF32", False), identity in overlay, identity)
        self.assertNotIn("requiresOverlayMaterial", motion["clips"][overlay[0]])

    def test_fan_opening_matches_the_game_material(self):
        native = (self.data / "timeline.bundle").read_bytes()
        tracks = mv_studio_timeline.parse_timeline(native, "timeline.bundle")["tracks"]
        binding, = mv_studio_props.bindings(tracks)
        _, spec = mv_studio_props.preview(self.data / "props.bundle", native, "timeline.bundle", binding,
                                          time.monotonic() + 60)
        self.assertEqual(spec["bone"], _DECOR)
        motion, = [track for track in tracks if track["id"] == spec["track"]]
        recorded = []
        for record in self.records:
            for material in record.get("materials", ()) if record.get("part") == "materials" else ():
                if material.get("name") != "mat_chp0001":
                    continue
                seconds = record["clock"]["directorTime"]
                properties = material["properties"]
                self.assertEqual((properties["_UV2Limit"]["v"], properties["_UV2Axis"]["v"][:3]), (spec["limit"], [0, 1, 0]))
                # MVStudioProps.evaluate: the active clip's source time, clamped into the clip.
                event, = [event for event in motion["events"]
                          if event["start"] <= seconds < event["start"] + event["duration"]]
                curve = spec["curves"][event["id"]]
                timing = event["values"]
                source = curve["first"] + (timing.get("clipIn") or 0) + (seconds - event["start"]) * timing.get("timeScale", 1)
                angle = model_animation._evaluate((curve["mode"], curve["keys"]), min(curve["last"], max(curve["first"], source)))
                recorded.append((seconds, properties["_UV2Angle"]["v"], round(max(angle, 0), 3)))
        self.assertEqual([row[1] for row in recorded], [0, 135, 135, 135, 135])
        for seconds, game, editor in recorded:
            self.assertAlmostEqual(editor, game, places=2, msg=seconds)


if __name__ == "__main__":
    unittest.main()
