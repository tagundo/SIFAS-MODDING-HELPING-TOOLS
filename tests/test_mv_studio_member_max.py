"""MVs bind up to 12 performers (LiveCoreMemberManager.MemberMax = LiveConstants.MaxMember = 12).

Lives such as 12034 and 12060 (10 members) and 12074, 12096, 12097, 12121 and
12128 (12 members) bind Member10..Member12 in their timelines.
"""

import unittest

from webtools.core import mv_studio, mv_studio_props, mv_studio_timeline


_HAND = "Reference/Move/RightHand"


class MemberMaxBindingTests(unittest.TestCase):
    def test_member_spot_light_shaft_slots_reach_member_twelve(self):
        for slot in (1, 9, 10, 12):
            track = {"nativeClass": "LiveMemberSpotLightShaftTrack", "binding": f"/EntryPoint/Live/Members/Member{slot}"}
            self.assertEqual(mv_studio_timeline._shaft_slot(track), slot)
        self.assertIsNone(mv_studio_timeline._shaft_slot(
            {"nativeClass": "LiveMemberSpotLightShaftTrack", "binding": "/EntryPoint/Live/Members/Member0"}))

    def test_performer_prop_binding_reaches_member_twelve(self):
        target = f"/EntryPoint/Live/Members/ske_so2028/Member12/Model/{_HAND}/chp0001"
        binding, = mv_studio_props.bindings([
            {"id": "motion", "nativeClass": "AnimationTrack", "binding": target,
             "events": [{"id": "clip", "values": {"animation": "cab:1"}}]},
            {"id": "visibility", "nativeClass": "ActivationTrack", "binding": target},
        ])
        self.assertEqual((binding["member"], binding["bone"]), (12, _HAND))

    def test_saved_project_holds_twelve_performers(self):
        project = {"version": 1, "name": "Twelve", "duration": 1, "tracks": [], "assets": [], "warnings": [],
                   "quality": {}, "source": {}, "performers": [{"position": slot} for slot in range(1, 13)]}
        self.assertTrue(mv_studio._document(project))
        project["performers"].append({"position": 13})
        with self.assertRaisesRegex(ValueError, "too many or invalid performers"):
            mv_studio._document(project)


if __name__ == "__main__":
    unittest.main()
