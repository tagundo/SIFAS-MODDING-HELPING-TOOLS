"""Suit attach data (m_suit_attach.attach_key) applied like CommonCoreMember.ApplyAttachData."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import mv_studio_suit_attach as attach


def _object(kind, path_id, file, tree=None, name=None):
    return SimpleNamespace(type=SimpleNamespace(name=kind), path_id=path_id, assets_file=file, tree=tree or {},
                           read=lambda: SimpleNamespace(m_ClassName=name))


class SuitAttachTests(unittest.TestCase):
    """CommonCoreMember.ApplyAttachData with MemberAttachTable.GetObject(attach key)."""

    def setUp(self):
        model_file = SimpleNamespace(name="CAB-model", externals=[SimpleNamespace(path="archive:/CAB-shader/CAB-shader"),
                                                                  SimpleNamespace(path="archive:/CAB-attach/CAB-attach")])
        attach_file = SimpleNamespace(name="CAB-attach", externals=[])
        self.script = _object("MonoScript", 1, model_file, name="BodyPartManager")
        self.body_c1 = _object("Texture2D", 31, attach_file)
        self.head_material = _object("Material", 32, attach_file, {"m_Name": "costume_head_copy"})
        self.table = _object("MonoBehaviour", 30, attach_file, {"m_Name": "costume_attach_materialcolor", "datas": [
            {"attachName": "c2", "attachType": 1, "replaceObjects": []},
            {"attachName": "c1", "attachType": 1, "replaceObjects": [
                {"replaceBindName": "costume_body", "replaceObject": {"m_FileID": 0, "m_PathID": 31}},
                {"replaceBindName": "costume_head", "replaceObject": {"m_FileID": 0, "m_PathID": 32}},
                {"replaceBindName": "costume_body", "replaceObject": {"m_FileID": 0, "m_PathID": 32}}]}]})
        self.parts = _object("MonoBehaviour", 2, model_file, {"m_Script": {"m_PathID": 1},
                                                              "attachTable": {"m_FileID": 2, "m_PathID": 30}})
        self.body = _object("Material", 3, model_file, {"m_Name": "costume_body", "m_SavedProperties": {"m_TexEnvs": [
            ("_RimlightTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 9}}),
            ("_MainTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 8}, "m_Scale": {"x": 1, "y": 1}})]}})
        by_id = {obj.path_id: obj for obj in (self.script, self.body_c1, self.head_material, self.table, self.parts, self.body)}
        self.scene = SimpleNamespace(env=SimpleNamespace(objects=list(by_id.values())), tree=lambda obj: obj.tree,
                                     warnings=[], warn=lambda code, name="": self.scene.warnings.append((code, name)))
        patcher = patch("webtools.core.model_viewer._ref",
                        side_effect=lambda owner, pointer: by_id.get((pointer or {}).get("m_PathID")))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_material_color_entry_replaces_main_texture_or_material(self):
        member = attach.MemberAttach.read(self.scene, "c1")
        self.assertEqual(member.describe()["objects"], {"costume_body": "Texture2D", "costume_head": "Material"})
        obj, tree = member.material(self.scene, self.body, self.body.tree)
        self.assertIs(obj, self.body)
        envs = dict(tree["m_SavedProperties"]["m_TexEnvs"])
        # The model file reaches the attach CAB through its second external (m_FileID 2).
        self.assertEqual(envs["_MainTex"], {"m_Texture": {"m_FileID": 2, "m_PathID": 31}, "m_Scale": {"x": 1, "y": 1}})
        self.assertEqual(envs["_RimlightTex"]["m_Texture"]["m_PathID"], 9)
        self.assertEqual(dict(self.body.tree["m_SavedProperties"]["m_TexEnvs"])["_MainTex"]["m_Texture"]["m_PathID"], 8,
                         "the cached source typetree is not modified")
        head = _object("Material", 4, self.body.assets_file, {"m_Name": "costume_head"})
        self.assertEqual(member.material(self.scene, head, head.tree), (self.head_material, self.head_material.tree))
        other = _object("Material", 5, self.body.assets_file, {"m_Name": "shadow"})
        self.assertEqual(member.material(self.scene, other, other.tree), (other, other.tree))

    def test_no_key_no_entry_or_another_type_changes_nothing(self):
        self.assertIsNone(attach.MemberAttach.read(self.scene, ""))
        self.assertIsNone(attach.MemberAttach.read(self.scene, "c3"))
        self.assertIsNone(attach.MemberAttach.read(self.scene, "c2"), "an entry without objects replaces nothing")
        self.table.tree["datas"][1]["attachType"] = 0
        self.assertIsNone(attach.MemberAttach.read(self.scene, "c1"), "only MemberAttachType.MaterialColor is applied")
        self.parts.tree["attachTable"] = {"m_FileID": 0, "m_PathID": 0}
        self.assertIsNone(attach.MemberAttach.read(self.scene, "c1"))


if __name__ == "__main__":
    unittest.main()
