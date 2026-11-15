"""Selected costume companions: real neutral Unity bytes, no game assets."""
import ast
import copy
from functools import lru_cache
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import UnityPy
from PIL import Image
from UnityPy.helpers.TypeTreeNode import TypeTreeNode

import generate_viewer_body_fixture as body_fixture
from test_model_faces import bundle
import unity_costumemod_packer as packer
from webtools.server import Handler, MANAGER
from webtools.tools import costume


@lru_cache(maxsize=24)
def rina_fixture(platform=9, masked=False, code="0001", owner=None):
    """Original neutral skin plus four static board parts when masked."""
    env = UnityPy.load(body_fixture.fixture_bytes())
    asset = env.file
    asset.target_platform = platform
    asset._m_target_platform = platform
    for obj in list(env.objects):
        tree = obj.read_typetree()
        if obj.type.name == "Texture2D":
            tree["m_Name"] = f"ch{owner or ('9999' if masked else '0209')}_co{code}_body"
            obj.save_typetree(tree)
    if masked:
        donor = UnityPy.load(str(Path(__file__).parent / "fixtures/viewer_auto_face_donor.unity"))
        template = next(obj for obj in donor.objects if obj.type.name == "MeshRenderer")
        serialized = copy.copy(template.serialized_type)
        serialized.node = TypeTreeNode.from_list([
            {key: value for key, value in row.items() if key != "m_Children"}
            for row in template._get_typetree_node().to_dict_list()])
        for index, part in enumerate(serialized.node.traverse()):
            for field in ("m_TypeFlags", "m_MetaFlag", "m_RefTypeHash"):
                if getattr(part, field, None) is None:
                    setattr(part, field, 0)
            if part.m_Index is None:
                part.m_Index = index
        asset.types.append(serialized)
        go_template, tr_template = asset.objects[4], asset.objects[5]
        head = next(obj for obj in env.objects
                    if obj.type.name == "GameObject" and obj.read_typetree()["m_Name"] == "Head")
        head_tr = asset.objects[head.read_typetree()["m_Component"][0]["component"]["m_PathID"]]
        for index in range(4):
            gid, tid, rid = 1000 + index * 3, 1001 + index * 3, 1002 + index * 3
            go, tr, renderer = copy.copy(go_template), copy.copy(tr_template), copy.copy(template)
            go.path_id, tr.path_id, renderer.path_id = gid, tid, rid
            renderer.assets_file = asset
            renderer.serialized_type = serialized
            renderer.type_id = len(asset.types) - 1
            asset.objects.update({gid: go, tid: tr, rid: renderer})
            tree = go_template.read_typetree()
            tree.update(m_Name="NeutralBoard" + str(index),
                m_Component=[{"component": {"m_FileID": 0, "m_PathID": tid}},
                             {"component": {"m_FileID": 0, "m_PathID": rid}}])
            go.save_typetree(tree)
            tree = tr_template.read_typetree()
            tree.update(m_GameObject={"m_FileID": 0, "m_PathID": gid},
                m_Father={"m_FileID": 0, "m_PathID": head_tr.path_id}, m_Children=[])
            tr.save_typetree(tree)
            tree = template.read_typetree()
            tree["m_GameObject"] = {"m_FileID": 0, "m_PathID": gid}
            renderer.save_typetree(tree)
            tree = head_tr.read_typetree()
            tree["m_Children"].append({"m_FileID": 0, "m_PathID": tid})
            head_tr.save_typetree(tree)
    return bundle([("neutral.assets", asset.save())])


class CostumeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.out = self.root / "out"
        self.out.mkdir()
        environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root / "library")})
        environment.start(); self.addCleanup(environment.stop)

    def source(self, name, *, platform=9, masked=False, code="0001", owner=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rina_fixture(platform, masked, code, owner))
        return str(path)

    def plan(self, paths, **kw):
        return packer.prepare_pack_jobs(paths, log=lambda text: None, **kw)

    def pair(self, names=("209rinacolorfulmaskedios", "209rinacolorfulunmaskedios")):
        return [self.source(names[0], masked=True), self.source(names[1])]

    def test_real_neutral_board_and_unmasked_content_is_identified(self):
        primary, helper = self.pair()
        self.assertEqual(packer._rina_content_scan(primary), ("co0001", True))
        self.assertEqual(packer._rina_content_scan(helper), ("co0001", False))
        self.assertEqual(packer.detect_bundle_platform(primary), "ios")

    def test_old_new_and_renamed_filenames_keep_one_job(self):
        for names in (("209rinacolorfulmaskedios", "209rinacolorfulunmaskedios"),
                      ("209rinamaskedcolorful.unity", "209rinaunmaskedcolorful.unity"),
                      ("ch0209_suit123_primary.unity", "renamed-companion.unity")):
            with self.subTest(names=names):
                primary, helper = self.pair(names)
                jobs, names_map, paths, platforms = self.plan([helper, primary])
                self.assertEqual(jobs, [("single", primary)])
                self.assertEqual(paths, {primary: helper})
                self.assertEqual(names_map, {})
                self.assertEqual(platforms[helper], "ios")

    def test_duplicate_selected_path_is_not_an_ambiguous_second_helper(self):
        primary, helper = self.pair()
        self.assertEqual(len(self.plan([primary, helper, helper])[0]), 1)

    def test_wrong_costume_or_native_platform_never_pairs(self):
        primary = self.source("primary.unity", masked=True)
        for helper in (self.source("wrong-suit.unity", code="0002"),
                       self.source("wrong-platform.unity", platform=13)):
            with self.subTest(helper=helper), self.assertRaisesRegex(ValueError, "missing unmasked"):
                self.plan([primary, helper])

    def test_combined_platform_pair_requires_same_costume_beyond_filename(self):
        paths = [self.source("rinaapk.unity", platform=13, masked=True, code="0001"),
                 self.source("unmaskedapk.unity", platform=13, code="0001"),
                 self.source("rinaios.unity", platform=9, masked=True, code="0002"),
                 self.source("unmaskedios.unity", platform=9, code="0002")]
        with self.assertRaisesRegex(ValueError, "same Rina costume"):
            self.plan(paths)
        self.assertEqual(len(self.plan(paths, combine_pairs=False)[0]), 2)

    def test_ambiguous_or_orphaned_helpers_are_explicit_errors(self):
        primary, helper = self.pair()
        duplicate = self.source("another-unmasked.unity")
        with self.assertRaisesRegex(ValueError, "ambiguous unmasked"):
            self.plan([primary, helper, duplicate])
        with self.assertRaisesRegex(ValueError, "Missing matching masked"):
            self.plan([helper])

    def test_no_target_and_mixed_platform_headers_fail_before_packaging(self):
        unknown = self.source("renamed-ios.unity", platform=-2, owner="0101")
        with self.assertRaisesRegex(ValueError, "NoTarget"):
            self.plan([unknown])
        left = UnityPy.load(rina_fixture(9, False)).assets[0]
        right = UnityPy.load(rina_fixture(13, False)).assets[0]
        mixed = self.root / "mixed-ios.unity"
        mixed.write_bytes(bundle([("ios.assets", left.save()), ("android.assets", right.save())]))
        self.assertIsNone(packer.detect_bundle_platform(str(mixed)))
        with self.assertRaisesRegex(ValueError, "platform is unknown"):
            self.plan([str(mixed)])

    def test_filename_does_not_claim_unrelated_bundle_as_helper(self):
        unrelated = self.source("209rinaunmasked-fake.unity", owner="0101")
        self.assertEqual(self.plan([unrelated])[0], [("single", unrelated)])

    def test_multiple_costume_codes_need_provenance_not_last_texture_wins(self):
        helper = self.source("ambiguous.unity", code="0001_ch0209_co0002")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.plan([helper])
        primary = self.source("ambiguous-board.unity", masked=True, code="0001_ch9999_co0002")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.plan([primary])

    def test_receipt_sha_is_rechecked_and_receipt_family_must_match(self):
        primary, helper = self.pair()
        def bound(path, variant, suit):
            return {"sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                    "owner": 209, "region": "gl", "suit_id": suit,
                    "variant": variant, "platform": "ios"}
        bindings = {primary: bound(primary, "primary", 1), helper: bound(helper, "unmasked", 2)}
        with self.assertRaisesRegex(ValueError, "missing unmasked"):
            self.plan([primary, helper], source_bindings=bindings)
        bindings[helper]["suit_id"] = 1
        bindings[helper]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "changed after"):
            self.plan([primary, helper], source_bindings=bindings)

    def test_selected_pair_builds_one_installer_with_unchanged_companion_bytes(self):
        primary, helper = self.pair(("renamed-primary.unity", "renamed-unmasked.unity"))
        before = {path: Path(path).read_bytes() for path in (primary, helper)}
        image = io.BytesIO(); Image.new("RGB", (8, 8), "white").save(image, format="PNG")
        success, fail = packer.run_pack_jobs([primary, helper], str(self.out),
            log=lambda text: None, thumbnail_provider=lambda *args: image.getvalue())
        self.assertEqual((success, fail), (1, 0))
        outputs = list(self.out.glob("*.zip")); self.assertEqual(len(outputs), 1)
        with zipfile.ZipFile(outputs[0]) as archive:
            fields = {node.targets[0].id: ast.literal_eval(node.value)
                      for node in ast.parse(archive.read("modinstall.txt").decode()).body}
            self.assertEqual(fields["chara_id"], 209)
            self.assertEqual(archive.read(fields["costume_file"]), before[primary])
            self.assertEqual(archive.read(fields["rina_unmask_costume_file"]), before[helper])
        self.assertEqual(before, {path: Path(path).read_bytes() for path in before})

    def test_conflicting_manual_character_does_not_drop_companion(self):
        primary, helper = self.pair()
        result = packer.run_pack_jobs([primary, helper], str(self.out), auto_chara_id=False,
            manual_chara_id=101, log=lambda text: None, thumbnail_provider=lambda *args: b"thumbnail")
        self.assertEqual(result, (0, 1))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_same_basename_variants_have_distinct_installer_members(self):
        primary, helper = self.pair(("masked/shared.unity", "unmasked/shared.unity"))
        result = packer.run_pack_jobs([primary, helper], str(self.out),
            log=lambda text: None, thumbnail_provider=lambda *args: b"thumbnail")
        self.assertEqual(result, (1, 0))
        with zipfile.ZipFile(next(self.out.glob("*.zip"))) as archive:
            fields = {node.targets[0].id: ast.literal_eval(node.value)
                      for node in ast.parse(archive.read("modinstall.txt").decode()).body}
            self.assertNotEqual(fields["costume_file"], fields["rina_unmask_costume_file"])
            self.assertEqual(archive.read(fields["costume_file"]), Path(primary).read_bytes())
            self.assertEqual(archive.read(fields["rina_unmask_costume_file"]), Path(helper).read_bytes())

    def test_selected_jobs_cannot_silently_overwrite_each_other(self):
        paths = [self.source("first/primary.unity", masked=True, code="0001"),
                 self.source("first/unmasked.unity", code="0001"),
                 self.source("second/primary.unity", masked=True, code="0002"),
                 self.source("second/unmasked.unity", code="0002")]
        with self.assertRaisesRegex(ValueError, "same installer filename"):
            packer.run_pack_jobs(paths, str(self.out), log=lambda text: None)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_web_adapter_keeps_selected_paths_in_one_shared_plan(self):
        primary, helper = self.pair()
        class Job:
            log = staticmethod(lambda text: None)
            progress = staticmethod(lambda *args: None)
        from webtools.core import viewer_thumbnails
        with patch("webtools.tools.texture.ensure_astc_cli"), \
             patch.object(viewer_thumbnails, "packer_provider", return_value=lambda *args: b"thumbnail"):
            result = costume.run_costume_packer(Job(), {"mode": "multi", "in_paths": primary + "\n" + helper,
                "out_dir": str(self.out), "auto_chara_id": True, "thumbnail_mode": "texture"})
        self.assertEqual(result, "packed: success=1 fail=0")
        self.assertEqual(len(list(self.out.glob("*.zip"))), 1)

    def test_server_dispatch_groups_costume_multi_and_preserves_other_tools(self):
        handler = object.__new__(Handler)
        params = {"mode": "multi", "in_paths": "a\nb"}
        handler._read_json_body = lambda: params
        handler._validate_run_paths = lambda *args: None
        handler._send_json = lambda value, **kw: value
        calls = []
        class Job:
            id = "test"
        run = lambda job, values: calls.append(values)
        with patch("webtools.server.registry.get_tool", return_value={
                "run": run, "group_selected_inputs": True}), \
             patch.object(MANAGER, "create", return_value=Job()), \
             patch.object(MANAGER, "run_async", side_effect=lambda job, work: work(job)), \
             patch("webtools.tools.common.run_multi", side_effect=AssertionError("Companions cannot be split")):
            self.assertEqual(handler._api_run("costume_packer"), {"job_id": "test"})
        self.assertEqual(calls, [params])
        with patch("webtools.server.registry.get_tool", return_value={"run": run}), \
             patch.object(MANAGER, "create", return_value=Job()), \
             patch.object(MANAGER, "run_async", side_effect=lambda job, work: work(job)), \
             patch("webtools.tools.common.run_multi", return_value=None) as other:
            handler._api_run("unrelated")
            other.assert_called_once_with(run, unittest.mock.ANY, params)


if __name__ == "__main__":
    unittest.main()

