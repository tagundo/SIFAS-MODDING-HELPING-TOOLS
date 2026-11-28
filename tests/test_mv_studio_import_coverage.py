"""Every original timeline track class is classified; gaps are reported, never dropped."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webtools.core import mv_studio_import_coverage as coverage

# Native track classes of the 14 verification timelines (7 songs x iOS/Android).
_VERIFICATION_CLASSES = {
    "ActivationTrack", "AnimationTrack", "CustomControlTrack", "GroupTrack", "LiveBloomTrack", "LiveColoringTrack",
    "LiveDepthOfFieldTrack", "LiveDisplayTrack", "LiveFlareTrack", "LiveFlashLightTrack", "LiveMemberAmbientTrack",
    "LiveMemberScalingTrack", "LiveMemberSpotLightAreaTrack", "LiveMemberSpotLightShaftTrack", "LivePenlightTrack",
    "LivePropAmbientTrack", "LivePropRimlightTrack", "LiveRimlightTrack", "LiveStageAmbientTrack",
    "LiveStageEmissiveTrack", "LiveStageSingleAmbientTrack", "MemberCheekTrack", "MemberEyeTrack", "MemberGazeTrack",
    "MemberLipSyncTrack",
}
# Track classes the client defines that no verification timeline carries.
_CLIENT_ONLY = {"LiveMemberIKTrack", "LiveMemberShadowTrack", "LiveDisplayCameraTrack", "LiveCameraCutMarkerTrack",
                "LivePropColoringTrack"}


def _track(identity, native, *, clips=1, binding=None, label=None, **fields):
    track = {"id": identity, "nativeClass": native, "kind": fields.pop("kind", "other"), "label": label or identity,
             "events": [{"id": f"{identity}:{index}", "start": 0., "duration": 1., "values": {}} for index in range(clips)],
             **fields}
    if binding:
        track["binding"] = binding
    return track


_HAND = "Reference/Move/Hips_Position/Hips/Spine/Spine1/Spine2/RightShoulder/RightArm/RightForeArm/RightHand"


def _prop_target(member=1, prop="chp0001"):
    return f"/EntryPoint/Live/Members/ske_so2028/Member{member}/Model/{_HAND}/{prop}"


def _prop_tracks(member=1, prop="chp0001", name="prop"):
    """A performer prop binding: an AnimationTrack and an ActivationTrack on the same exact target."""
    motion = _track(f"{name}-motion", "AnimationTrack", clips=2, binding=_prop_target(member, prop))
    for index, event in enumerate(motion["events"]):
        event["values"] = {"animation": f"cab-prop:{index + 1}"}
    return [motion, _track(f"{name}-on", "ActivationTrack", binding=_prop_target(member, prop))]


def _prop_asset(member=1, name="prop", **fields):
    attachment = {"kind": "fan", "member": member, "bone": _HAND, "track": f"{name}-motion",
                  "activation": [f"{name}-on"], "curves": {f"{name}-motion:0": {"mode": "constant", "keys": 90.}}}
    return {"id": "9", "kind": "props", "label": "Performer prop", "status": "loaded",
            "previewUrl": "/api/mv-studio/media/prop.glb", "attachment": attachment, **fields}


def _rows(report, native):
    return {(row["status"], row["note"]): (row["tracks"], row["clips"]) for row in report["tracks"]
            if row["nativeClass"] == native}


class ImportCoverageTests(unittest.TestCase):
    def project(self, *tracks, **fields):
        return {"tracks": list(tracks), "warnings": [], "performers": [{"position": 1, "glb": "/m.glb"}], **fields}

    def test_known_track_classes_are_explicitly_classified(self):
        for native in _VERIFICATION_CLASSES | _CLIENT_ONLY:
            with self.subTest(native=native):
                self.assertIn(native, coverage.CLASSES)
        self.assertEqual(coverage.CLASSES["LiveCameraCutMarkerTrack"][0], coverage.NO_EFFECT)
        self.assertEqual(coverage.CLASSES["LiveMemberIKTrack"][0], coverage.NOT_RENDERED)

    def test_animation_tracks_follow_their_binding(self):
        stage = "/EntryPoint/Live/Stages/MainStage/Effect/fx/root"
        project = self.project(
            _track("dance", "AnimationTrack", kind="dance", binding="/EntryPoint/Live/Members/Member1/Model"),
            _track("camera", "AnimationTrack", kind="camera", binding="/EntryPoint/Live/Cameras/MainCamera", clips=3),
            _track("sub", "AnimationTrack", kind="camera",
                   binding="/EntryPoint/Live/Cameras/SplitScreenEffect/Cameras/SubCamera2"),
            _track("motion", "AnimationTrack", kind="effects", binding=stage),
            _track("rejected", "AnimationTrack", kind="effects", binding=stage + "2", clips=2),
            stageMotion={"bindings": [stage], "mix": {"motion:0": {}}},
        )
        rows = _rows(coverage.report(project), "AnimationTrack")
        self.assertEqual(rows[coverage.RENDERED, "Main camera."], (1, 3))
        self.assertEqual(rows[coverage.RENDERED, "Performer dance from the timeline's choreography pack."], (1, 1))
        self.assertEqual(rows[coverage.RENDERED, "Stage-node animation."], (1, 1))
        self.assertEqual(rows[coverage.NOT_RENDERED, "No preview module animates this binding."], (1, 2))
        self.assertEqual(rows[coverage.NOT_RENDERED, "Split-screen sub camera without a split-screen layout."], (1, 1))
        project["splitScreen"] = {"masks": []}
        self.assertIn((coverage.RENDERED, "Split-screen sub camera."), _rows(coverage.report(project), "AnimationTrack"))

    def test_activation_tracks_count_only_when_a_preview_switches_them(self):
        project = self.project(_track("on", "ActivationTrack", clips=2), _track("off", "ActivationTrack"),
                               stageMotion={"bindings": [], "activations": {"on": ["on:0", "on:1"]}})
        rows = _rows(coverage.report(project), "ActivationTrack")
        self.assertEqual(rows[coverage.RENDERED, "Stage-node visibility."], (1, 2))
        self.assertEqual(rows[coverage.NOT_RENDERED, "No preview module switches this binding."], (1, 1))

    def test_stage_node_clips_count_per_clip_the_stage_motion_reader_accepts(self):
        stage = "/EntryPoint/Live/Stages/MainStage/Effect/fx/root"
        # The activation track alone puts the binding into stageMotion.bindings.
        project = self.project(
            _track("motion", "AnimationTrack", kind="effects", binding=stage, clips=3),
            _track("on", "ActivationTrack", binding=stage, clips=3),
            stageMotion={"bindings": [stage], "mix": {"motion:1": {}, "on:0": {}, "on:2": {}},
                         "activations": {"on": ["on:0", "on:2"]}})
        report = coverage.report(project)
        self.assertEqual(_rows(report, "AnimationTrack"), {
            (coverage.RENDERED, "Stage-node animation."): (1, 1),
            (coverage.NOT_RENDERED, "Clips the stage-motion reader rejects."): (1, 2)})
        self.assertEqual(_rows(report, "ActivationTrack"), {
            (coverage.RENDERED, "Stage-node visibility."): (1, 2),
            (coverage.NOT_RENDERED, "Clips the stage-motion reader rejects."): (1, 1)})
        project["stageMotion"]["mix"] = {"on:0": {}, "on:2": {}}
        self.assertEqual(_rows(coverage.report(project), "AnimationTrack"), {
            (coverage.NOT_RENDERED, "Clips the stage-motion reader rejects."): (1, 3)})

    def test_a_stage_binding_with_two_tracks_of_a_class_is_not_driven(self):
        stage = "/EntryPoint/Live/Stages/MainStage/Effect/fx/root"
        project = self.project(
            _track("motion", "AnimationTrack", kind="effects", binding=stage),
            _track("muted", "AnimationTrack", kind="effects", binding=stage, muted=True),
            _track("on", "ActivationTrack", binding=stage), _track("on-2", "ActivationTrack", binding=stage),
            _track("ignored", "ActivationTrack", binding=stage),
            stageMotion={"bindings": [stage], "mix": {"motion:0": {}, "on:0": {}, "on-2:0": {}},
                         "activations": {"on": ["on:0"], "on-2": ["on-2:0"]}})
        report = coverage.report(project)
        self.assertEqual(_rows(report, "AnimationTrack"), {
            (coverage.NOT_RENDERED, "More than one AnimationTrack on this stage binding; none is animated."): (1, 1),
            (coverage.MUTED, "Muted in the original timeline."): (1, 1)})
        self.assertEqual(_rows(report, "ActivationTrack"), {
            (coverage.NOT_RENDERED, "More than one accepted ActivationTrack on this stage binding; none is switched."):
                (2, 2),
            (coverage.NOT_RENDERED, "No preview module switches this binding."): (1, 1)})

    def test_performer_prop_tracks_count_only_through_an_attached_prop(self):
        project = self.project(*_prop_tracks(), assets=[_prop_asset()])
        report = coverage.report(project)
        self.assertEqual(_rows(report, "AnimationTrack"), {
            (coverage.RENDERED, "Performer prop animation."): (1, 1),
            (coverage.NOT_RENDERED, "Prop clips without a playable native opening curve."): (1, 1)})
        self.assertEqual(_rows(report, "ActivationTrack"), {(coverage.RENDERED, "Performer prop visibility."): (1, 1)})
        # The scene creates the prop only from a previewed props asset with an attachment.
        for asset in (_prop_asset(previewUrl=None), _prop_asset(kind="effect"), {**_prop_asset(), "attachment": None}):
            with self.subTest(asset=asset):
                rows = _rows(coverage.report(dict(project, assets=[asset])), "AnimationTrack")
                self.assertEqual(rows, {(coverage.NOT_RENDERED, coverage.PROP_NOT_ATTACHED): (1, 2)})

    def test_attached_prop_needs_a_performer_at_its_member_slot(self):
        project = self.project(*_prop_tracks(member=2), assets=[_prop_asset(member=2)])
        report = coverage.report(project)
        self.assertEqual({row["nativeClass"]: (row["status"], row["note"], row["slots"]) for row in report["tracks"]}, {
            "AnimationTrack": (coverage.NOT_RENDERED, "No performer is loaded at its member slot.", [2]),
            "ActivationTrack": (coverage.NOT_RENDERED, "No performer is loaded at its member slot.", [2])})

    def test_unattached_prop_tracks_are_reported_with_the_import_reason(self):
        tracks = (*_prop_tracks(), *_prop_tracks(member=2, prop="chp0002", name="other"))
        project = self.project(*tracks, performers=[{"position": 1, "glb": "/1.glb"}, {"position": 2, "glb": "/2.glb"}])
        for gap in (coverage.PROP_SEVERAL, coverage.PROP_NO_BUNDLE, coverage.PROP_UNAVAILABLE,
                    coverage.PROP_PREVIEW_FAILED, None):
            with self.subTest(gap=gap):
                case = deepcopy(project)
                coverage.apply(case, gap)
                note = gap or coverage.PROP_NOT_ATTACHED
                self.assertEqual({(row["nativeClass"], row["status"], row["note"]): (row["tracks"], row["clips"])
                                  for row in case["importCoverage"]["tracks"]},
                                 {("AnimationTrack", coverage.NOT_RENDERED, note): (2, 4),
                                  ("ActivationTrack", coverage.NOT_RENDERED, note): (2, 2)})
                self.assertEqual(case["warnings"], [
                    f"Original timeline tracks MV Studio does not reproduce: ActivationTrack x2 (2 clips: "
                    f"{note.rstrip('.')}); AnimationTrack x2 (4 clips: {note.rstrip('.')})."])

    def test_custom_control_cues_count_per_clip_by_their_stage_descriptor(self):
        project = self.project(_track("control", "CustomControlTrack", clips=3),
                               stageGlow={"cues": [{"trackId": "control", "eventId": "control:1"}]})
        report = coverage.report(project)
        rows = _rows(report, "CustomControlTrack")
        self.assertEqual(rows[coverage.RENDERED, "Effect cues drawn by a stage effect reader."], (1, 1))
        self.assertEqual(rows[coverage.NOT_RENDERED, "Effect cues no stage effect reader draws."], (1, 2))
        self.assertEqual(coverage.warnings(report), [
            "Original timeline tracks MV Studio does not reproduce: CustomControlTrack x1 "
            "(2 clips: Effect cues no stage effect reader draws)."])

    def test_member_tracks_without_a_loaded_performer_are_reported_by_slot(self):
        project = self.project(
            _track("lips-1", "MemberLipSyncTrack", label="MemberFacial/Member1/Mouth", clips=4),
            _track("lips-10", "MemberLipSyncTrack", label="MemberFacial/Member10/Mouth", clips=5),
            _track("lips-11", "MemberLipSyncTrack", label="MemberFacial/Member11/Mouth", clips=6),
        )
        report = coverage.report(project)
        rows = {row["status"]: row for row in report["tracks"]}
        self.assertEqual((rows[coverage.RENDERED]["tracks"], rows[coverage.RENDERED]["clips"]), (1, 4))
        self.assertEqual(rows[coverage.NOT_RENDERED]["slots"], [10, 11])
        self.assertEqual(coverage.warnings(report), [
            "Original timeline tracks MV Studio does not reproduce: MemberLipSyncTrack x2 "
            "(11 clips: No performer is loaded at its member slot (Member10, Member11))."])

    def test_muted_structure_metadata_and_no_effect_tracks_raise_no_warning(self):
        project = self.project(_track("group", "GroupTrack", clips=0), _track("muted", "LiveMemberIKTrack", muted=True),
                               _track("cut", "LiveCameraCutMarkerTrack", clips=4), _track("audio", "AudioTrack"))
        report = coverage.report(project)
        self.assertEqual(report["gaps"], [])
        self.assertEqual({row["status"] for row in report["tracks"]},
                         {coverage.STRUCTURE, coverage.MUTED, coverage.NO_EFFECT, coverage.METADATA})

    def test_unknown_and_unsupported_classes_are_named(self):
        project = self.project(_track("ik", "LiveMemberIKTrack", clips=3), _track("shadow", "LiveMemberShadowTrack"),
                               _track("new", "LiveSomethingNewTrack", clips=2))
        # No class is partial today; keep the partial wording covered.
        partial = (coverage.PARTIAL, "Only turns the stage's default member shadows off; "
                                     "shadowIndex and scale clips are not applied.")
        with patch.dict(coverage.CLASSES, {"LiveMemberShadowTrack": partial}):
            coverage.apply(project)
        self.assertEqual(project["warnings"], [
            "Original timeline tracks MV Studio does not reproduce: LiveMemberIKTrack x1 "
            "(3 clips: Arm IK (TimelineAssetBindingInfo.ikInfo) is not implemented).",
            "Original timeline tracks MV Studio reproduces only in part: LiveMemberShadowTrack x1 "
            "(1 clip: Only turns the stage's default member shadows off; shadowIndex and scale clips are not applied).",
            "Original timeline track classes MV Studio does not know: LiveSomethingNewTrack x1 "
            "(2 clips: MV Studio does not know this track class).",
        ])
        self.assertEqual([row["nativeClass"] for row in project["importCoverage"]["gaps"]],
                         ["LiveMemberIKTrack", "LiveMemberShadowTrack", "LiveSomethingNewTrack"])

    def test_unexported_member_shadow_prefabs_are_not_reported_as_rendered(self):
        project = self.project(_track("shadow", "LiveMemberShadowTrack", clips=2))
        self.assertEqual(coverage.report(project)["gaps"], [])
        rows = coverage.report(project, shadow_gap=coverage.SHADOW_PREFABS_UNAVAILABLE)["tracks"]
        self.assertEqual([(row["status"], row["clips"], row["note"]) for row in rows],
                         [(coverage.NOT_RENDERED, 2, coverage.SHADOW_PREFABS_UNAVAILABLE)])

    def test_a_project_without_tracks_reports_nothing(self):
        project = self.project()
        self.assertEqual(coverage.apply(project), {"tracks": [], "gaps": []})
        self.assertEqual(project["warnings"], [])


class LoadGamePropCoverageTests(unittest.TestCase):
    """load_game credits performer prop tracks only when it attached the prop."""

    def setUp(self):
        from webtools.core import mv_studio, mv_studio_actor_cache, mv_studio_game, mv_studio_props, mv_studio_quality

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tracks = list(_prop_tracks())
        asset = lambda name: {"table": "live_timeline", "asset": name, "available": True}
        self.selection = {
            "name": "Fixture", "region": "gl", "platform": "ios", "liveId": 1, "assetId": 2,
            "timeline": asset("timeline"), "stage": {"model": asset("stage"), "props": asset("props")},
            "performers": [{"position": 1, "memberId": 208, "model": asset("actor-208")}],
        }
        self.attachment = _prop_asset()["attachment"]
        self.preview = patch.object(mv_studio_props, "preview", return_value=(b"glTF", self.attachment)).start()
        self.addCleanup(patch.stopall)
        patch.object(mv_studio_game, "resolve", side_effect=lambda *a, **k: deepcopy(self.selection)).start()
        self.missing = set()
        patch.object(mv_studio_game, "load_asset", side_effect=lambda root, descriptor, **_: (
            None if descriptor["asset"] in self.missing else descriptor["asset"].encode())).start()
        patch.object(mv_studio_quality, "read_quality", return_value={"values": {}}).start()
        patch.object(mv_studio_actor_cache, "open_cache", return_value=None).start()
        patch.object(mv_studio, "_root", return_value=self.root).start()
        patch.object(mv_studio, "_timeline", side_effect=lambda path: (path.read_bytes(), {
            "duration": 10.0, "tracks": deepcopy(self.tracks), "warnings": []})).start()
        patch.object(mv_studio, "_preview", return_value=("/api/mv-studio/media/" + "a" * 32 + ".glb", {})).start()
        patch.object(mv_studio, "_media", return_value="/api/mv-studio/media/" + "b" * 32 + ".glb").start()
        patch.object(mv_studio, "_motion", return_value=([], {"bodySegments": []})).start()
        patch.object(mv_studio, "_register", side_effect=lambda project, native: project).start()
        self.mv_studio = mv_studio

    def import_rows(self):
        project = self.mv_studio.load_game(self.root, region="gl", platform="ios", live_id=1, asset_id=2, language="en")
        return {(row["nativeClass"], row["status"], row["note"]): row["clips"] for row in project["importCoverage"]["tracks"]}

    def test_attached_prop_plays_its_tracks(self):
        self.assertEqual(self.import_rows(), {
            ("AnimationTrack", coverage.RENDERED, "Performer prop animation."): 1,
            ("AnimationTrack", coverage.NOT_RENDERED, "Prop clips without a playable native opening curve."): 1,
            ("ActivationTrack", coverage.RENDERED, "Performer prop visibility."): 1})
        self.preview.assert_called_once()

    def test_each_member_merges_its_own_prop_skeleton(self):
        # LiveCoreMember.Initialize merges <ske_*>/Member<N> into member N, whatever
        # prop the preview can draw; another slot's skeleton never reaches it.
        from webtools.core import mv_studio_props
        nodes = {1: [{"path": "Reference", "position": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}],
                 2: [{"path": "Other", "position": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}]}
        read = []
        skeleton = patch.object(mv_studio_props, "skeleton",
                                side_effect=lambda path, deadline: read.append(path.read_bytes()) or nodes).start()
        calls = []

        def preview(path, **options):
            calls.append(options)
            return "/api/mv-studio/media/" + "a" * 32 + ".glb", {}

        patch.object(self.mv_studio, "_preview", side_effect=preview).start()
        self.mv_studio.load_game(self.root, region="gl", platform="ios", live_id=1, asset_id=2, language="en")
        skeleton.assert_called_once()
        self.assertEqual(read, [b"props"])
        actor, = [options for options in calls if options.get("performer")]
        self.assertEqual(actor["prop_skeleton"], nodes[1])
        # Without a prop bundle nothing is merged.
        del self.selection["stage"]["props"]
        calls.clear()
        self.mv_studio.load_game(self.root, region="gl", platform="ios", live_id=1, asset_id=2, language="en")
        actor, = [options for options in calls if options.get("performer")]
        self.assertEqual(actor["prop_skeleton"], ())

    def test_stage_effect_shadow_prefab_failure_is_reported(self):
        # The stage effect preview warns that its member-shadow prefabs were not exported.
        self.selection["stage"]["effect"] = {"table": "stage_effect", "asset": "effect", "available": True}
        self.tracks.append(_track("shadow", "LiveMemberShadowTrack", binding="/EntryPoint/Live/Members"))
        message = "The stage's member shadow prefabs could not be exported, so the performers draw no shadows in this preview."

        def preview(path, *, warnings=None, native_stage_effect=False, **_):
            if native_stage_effect and warnings is not None:
                warnings.append({"code": "member_shadow_prefabs_unavailable", "name": "", "message": message})
            return "/api/mv-studio/media/" + "a" * 32 + ".glb", {}

        patch.object(self.mv_studio, "_preview", side_effect=preview).start()
        project = self.mv_studio.load_game(self.root, region="gl", platform="ios", live_id=1, asset_id=2, language="en")
        rows = {(row["nativeClass"], row["status"], row["note"]) for row in project["importCoverage"]["tracks"]}
        self.assertIn(("LiveMemberShadowTrack", coverage.NOT_RENDERED, coverage.SHADOW_PREFABS_UNAVAILABLE), rows)
        self.assertIn(f"Stage effects: {message}", project["warnings"])

    def test_stage_effect_display_variant_warning_reaches_coverage(self):
        # The stage effect preview warns that one display variant cannot be drawn; load_game
        # passes it to the coverage report, which marks the clips selecting it not rendered.
        self.selection["stage"]["effect"] = {"table": "stage_effect", "asset": "effect", "available": True}
        target = "/EntryPoint/Live/Stages/MainStage/Effect/dis_01/main"
        track = _track("display", "LiveDisplayTrack", binding=target, clips=3)
        for event, material in zip(track["events"], (0, 1, 5)):
            event["values"] = {"materialIndex": material}
        self.tracks.append(track)
        reason = "_WaveTex could not be decoded"

        def preview(path, *, warnings=None, native_stage_effect=False, **_):
            if native_stage_effect and warnings is not None:
                warnings.append({"code": coverage.DISPLAY_VARIANTS_UNSUPPORTED, "name": target, "message": "Some variants.",
                                 "target": target, "variants": 2, "unsupported": [[1, reason]]})
            return "/api/mv-studio/media/" + "a" * 32 + ".glb", {}

        patch.object(self.mv_studio, "_preview", side_effect=preview).start()
        project = self.mv_studio.load_game(self.root, region="gl", platform="ios", live_id=1, asset_id=2, language="en")
        rows = {(row["nativeClass"], row["status"], row["note"]): row["clips"] for row in project["importCoverage"]["tracks"]
                if row["nativeClass"] == "LiveDisplayTrack"}
        self.assertEqual(rows, {
            ("LiveDisplayTrack", coverage.RENDERED, "Stage display screens."): 1,
            ("LiveDisplayTrack", coverage.NOT_RENDERED, coverage._DISPLAY_VARIANT.format(reason)): 2})

    def test_each_case_without_an_attached_prop_names_its_reason(self):
        def expect(note):
            self.assertEqual(self.import_rows(), {("AnimationTrack", coverage.NOT_RENDERED, note): 2,
                                                  ("ActivationTrack", coverage.NOT_RENDERED, note): 1})

        self.preview.side_effect = ValueError("The selected hand prop has no native fan renderer.")
        expect(coverage.PROP_PREVIEW_FAILED)
        self.preview.reset_mock(side_effect=True)
        self.tracks += _prop_tracks(prop="chp0002", name="other")
        self.assertEqual(self.import_rows(), {("AnimationTrack", coverage.NOT_RENDERED, coverage.PROP_SEVERAL): 4,
                                              ("ActivationTrack", coverage.NOT_RENDERED, coverage.PROP_SEVERAL): 2})
        self.preview.assert_not_called()
        self.tracks = list(_prop_tracks())
        self.missing.add("props")
        expect(coverage.PROP_UNAVAILABLE)
        self.missing.clear()
        del self.selection["stage"]["props"]
        expect(coverage.PROP_NO_BUNDLE)


if __name__ == "__main__":
    unittest.main()
