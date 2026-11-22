from pathlib import Path
import json
import math
import os
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

from webtools.core import model_animation, model_viewer, mv_studio, mv_studio_props
from webtools.core import mv_studio_stage_particles, mv_studio_timeline


_FIXTURE = os.environ.get("ELICHIKA_AION_PROP_FIXTURE")
_HAND = "Reference/Move/Hips_Position/Hips/Spine/Spine1/Spine2/RightShoulder/RightArm/RightForeArm/RightHand"
_TARGET = "/EntryPoint/Live/Members/ske_so2028/Member1/Model/" + _HAND + "/chp0001"


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
                    self.assertEqual((spec["member"], spec["bone"], spec["limit"]), (1, _HAND, 135))
                    self.assertEqual(spec["binding"], _TARGET)
                    nodes = [bone["node"] for bone in actor["rig"]["bones"]
                             if bone["path"] == _HAND or bone["path"].endswith("/" + _HAND)]
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
        self.assertEqual(document["nodes"][0]["matrix"], [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])

    def _check_angle(self, source):
        self.assertEqual(source["mode"], "cubic")
        self.assertEqual(len(source["keys"]), 128)
        curve = source["mode"], source["keys"]
        self.assertEqual(model_animation._evaluate(curve, 1), 0)
        self.assertAlmostEqual(model_animation._evaluate(curve, 30), 135)


if __name__ == "__main__":
    unittest.main()
