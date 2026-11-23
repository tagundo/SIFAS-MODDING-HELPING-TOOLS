"""Every original timeline track class is classified; gaps are reported, never dropped."""
import unittest

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
            stageMotion={"bindings": [stage]},
        )
        rows = _rows(coverage.report(project), "AnimationTrack")
        self.assertEqual(rows[coverage.RENDERED, "Main camera."], (1, 3))
        self.assertEqual(rows[coverage.RENDERED, "Performer dance from the timeline's choreography pack."], (1, 1))
        self.assertEqual(rows[coverage.RENDERED, "Stage-node or prop animation."], (1, 1))
        self.assertEqual(rows[coverage.NOT_RENDERED, "No preview module animates this binding."], (1, 2))
        self.assertEqual(rows[coverage.NOT_RENDERED, "Split-screen sub camera without a split-screen layout."], (1, 1))
        project["splitScreen"] = {"masks": []}
        self.assertIn((coverage.RENDERED, "Split-screen sub camera."), _rows(coverage.report(project), "AnimationTrack"))

    def test_activation_tracks_count_only_when_a_preview_switches_them(self):
        project = self.project(_track("on", "ActivationTrack", clips=2), _track("off", "ActivationTrack"),
                               stageMotion={"bindings": [], "activations": {"on": ["on:0", "on:1"]}})
        rows = _rows(coverage.report(project), "ActivationTrack")
        self.assertEqual(rows[coverage.RENDERED, "Stage-node or prop visibility."], (1, 2))
        self.assertEqual(rows[coverage.NOT_RENDERED, "No preview module switches this binding."], (1, 1))

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

    def test_a_project_without_tracks_reports_nothing(self):
        project = self.project()
        self.assertEqual(coverage.apply(project), {"tracks": [], "gaps": []})
        self.assertEqual(project["warnings"], [])


if __name__ == "__main__":
    unittest.main()
