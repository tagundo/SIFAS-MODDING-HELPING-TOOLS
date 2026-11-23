"""Unity Rotation/PositionConstraint components exported with the member rig."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from webtools.core import model_constraints


class _Type:
    def __init__(self, name):
        self.name = name


class _Object:
    def __init__(self, kind, tree):
        self.type = _Type(kind)
        self.tree = tree

    def read_typetree(self):
        if isinstance(self.tree, Exception):
            raise self.tree
        return self.tree


def _pointer(path_id, file_id=0):
    return {"m_FileID": file_id, "m_PathID": path_id}


def _info(constraints, *, inactive=(), extra=None):
    """Hips(10) -> Skirt root(11); SkirtA1(12) and LeftArm(13) under Hips."""
    names = {10: "Hips", 11: "LeftSkirtB_Root_Dyna", 12: "SkirtA1_Dyna", 13: "LeftArm"}
    parents = {(0, 10): None, (0, 11): (0, 10), (0, 12): (0, 10), (0, 13): (0, 10)}
    transforms = {(0, key): {"m_GameObject": _pointer(key + 100)} for key in names}
    objects = {(0, key + 100): _Object("GameObject", {"m_Name": name, "m_IsActive": key not in inactive})
               for key, name in names.items()}
    objects.update({(0, 300 + index): _Object(kind, tree) for index, (kind, tree) in enumerate(constraints)})
    objects.update(extra or {})
    return {"objects": objects, "transforms": transforms, "parents": parents,
            "names": {(0, key): name for key, name in names.items()}}


def _rotation(**overrides):
    tree = {"m_GameObject": _pointer(111), "m_Enabled": 1, "m_Weight": .5,
            "m_RotationAtRest": {"x": 32.5, "y": -40.75, "z": 143.5}, "m_RotationOffset": {"x": -32.5, "y": 13.25, "z": -36.5},
            "m_AffectRotationX": True, "m_AffectRotationY": True, "m_AffectRotationZ": False, "m_IsContraintActive": True,
            "m_Sources": [{"sourceTransform": _pointer(12), "weight": 1.0}]}
    tree.update(overrides)
    return tree


def _position(**overrides):
    tree = {"m_GameObject": _pointer(111), "m_Enabled": 0, "m_Weight": .7,
            "m_TranslationAtRest": {"x": .25, "y": -.125, "z": 0}, "m_TranslationOffset": {"x": -.5, "y": .5, "z": 1},
            "m_AffectTranslationX": 1, "m_AffectTranslationY": 1, "m_AffectTranslationZ": 1, "m_IsContraintActive": False,
            "m_Sources": [{"sourceTransform": _pointer(13), "weight": .5}, {"sourceTransform": _pointer(99, 1), "weight": 1}]}
    tree.update(overrides)
    return tree


BONES = [{"sourceIndex": 0, "transformId": str(key), "node": key + 1000} for key in (10, 11, 12, 13)]


class ConstraintCatalogTests(unittest.TestCase):
    def test_serialized_fields_bind_to_preview_nodes(self):
        timeline = _Object("MonoBehaviour", {"timelineConstraints": [_pointer(300)], "m_Script": _pointer(5, 1)})
        rows = model_constraints.inspect_info(_info([("RotationConstraint", _rotation()), ("PositionConstraint", _position())],
                                                    extra={(0, 400): timeline}), 0, BONES)
        self.assertEqual([row["kind"] for row in rows], ["rotation", "position"])
        rotation, position = rows
        self.assertEqual(rotation, {
            "id": "0:0:300", "kind": "rotation", "sourceIndex": 0, "node": 1011, "name": "LeftSkirtB_Root_Dyna",
            "enabled": True, "activeInHierarchy": True, "constraintActive": True, "weight": .5,
            "atRest": [32.5, -40.75, 143.5], "offset": [-32.5, 13.25, -36.5], "axes": [True, True, False],
            "sources": [{"node": 1012, "weight": 1.0}], "timeline": True})
        self.assertEqual(position["atRest"], [.25, -.125, 0])
        self.assertEqual(position["offset"], [-.5, .5, 1])
        self.assertIs(position["enabled"], False)
        self.assertIs(position["constraintActive"], False)
        self.assertIs(position["timeline"], False)
        # An external or unbound source stays in place as an invalid source.
        self.assertEqual(position["sources"], [{"node": 1013, "weight": .5}, {"node": None, "weight": 1.0}])

    def test_activation_is_the_hierarchy_state(self):
        rows = model_constraints.inspect_info(_info([("RotationConstraint", _rotation())], inactive={10}), 0, BONES)
        self.assertIs(rows[0]["activeInHierarchy"], False)

    def test_unbound_unreadable_and_other_types_are_left_out(self):
        rows = model_constraints.inspect_info(_info([
            ("RotationConstraint", _rotation(m_GameObject=_pointer(111, 2))),
            ("RotationConstraint", _rotation(m_Weight=float("nan"))),
            ("PositionConstraint", _position(m_TranslationOffset={"x": 1})),
            ("PositionConstraint", KeyError("no type tree")),
            ("AimConstraint", _rotation()),
        ]), 0, BONES)
        self.assertEqual(rows, [])
        self.assertEqual(model_constraints.inspect_info(_info([("RotationConstraint", _rotation())]), 1, BONES), [])


_ROOT = os.environ.get("ELICHIKA_ROOT")


@unittest.skipUnless(_ROOT and Path(_ROOT, "llas_asset_extractor.py").is_file(),
                     "Set ELICHIKA_ROOT to an Elichika checkout with the GL Android packs")
class OriginalRigConstraintTests(unittest.TestCase):
    """The verification MVs' first performers on the GL Android packs."""

    def catalog(self, live, asset):
        sys.path.insert(0, _ROOT)
        self.addCleanup(sys.path.remove, _ROOT)
        from webtools.core import model_viewer, mv_studio_game
        performer = mv_studio_game.resolve(Path(_ROOT), region="gl", platform="android", live_id=live, asset_id=asset)["performers"][0]
        raw = mv_studio_game.load_asset(Path(_ROOT), performer["model"], deadline=time.monotonic() + 60)
        if raw is None:
            self.skipTest("The performer pack is not available locally")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "model.unity"
        path.write_bytes(raw)
        preview = model_viewer.prepare([str(path)], rigged=True, face_context={"enabled": False, "allow_download": False})
        return model_constraints.catalogue_preview([path], preview["rig"]["bones"])["constraints"]

    def summary(self, rows):
        for row in rows:
            self.assertTrue(row["enabled"] and row["activeInHierarchy"] and row["constraintActive"], row)
            self.assertEqual(row["axes"], [True, True, True])
            self.assertIsInstance(row["node"], int)
            self.assertTrue(all(isinstance(source["node"], int) for source in row["sources"]), row)
        return sorted((row["name"], row["kind"], round(row["weight"], 6), row["timeline"]) for row in rows)

    def test_12007_skirt_layers_and_hair(self):
        self.assertEqual(self.summary(self.catalog(12007, 1200703)), [
            ("HairC_Root_Dyna", "position", .7, False),
            ("LeftSkirtB_Root_Dyna", "rotation", .5, True), ("LeftSkirtC_Root_Dyna", "rotation", .2, True),
            ("RightSkirtB_Root_Dyna", "rotation", .5, True), ("RightSkirtC_Root_Dyna", "rotation", .2, True)])

    def test_12036_coat_flaps_and_shoulder_parts(self):
        self.assertEqual(self.summary(self.catalog(12036, 1203603)), [
            ("LeftCoatA_Root_Dyna", "position", .7, False), ("LeftShoulderPartsB_Root_Dyna", "rotation", .5, False),
            ("RightCoatA_Root_Dyna", "position", .7, False), ("RightShoulderPartsB_Root_Dyna", "rotation", .5, False)])

    def test_12025_skirt_layers(self):
        self.assertEqual(self.summary(self.catalog(12025, 1202503)), [
            ("LeftSkirtB_Root_Dyna", "rotation", .3, True), ("RightSkirtB_Root_Dyna", "rotation", .3, True)])

    def test_12035_performer_has_none(self):
        self.assertEqual(self.catalog(12035, 1203503), [])


if __name__ == "__main__":
    unittest.main()
