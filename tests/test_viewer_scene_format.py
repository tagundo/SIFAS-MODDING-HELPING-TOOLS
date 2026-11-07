"""Envelope/schema tests. Synthetic bytes are NOT Unity/native evidence."""
import copy
import io
import json
import struct
from pathlib import Path
import tempfile
import unittest
import zipfile

from webtools.core import viewer_scene_format as scene


def native(raw):
    return int(raw.split(b":", 1)[0])


def fixture(platforms=("android",)):
    manifest = {"format": scene.FORMAT, "version": 1, "requires": [scene.CAPABILITY], "character_id": 209,
                "display_name": "리나 scene", "platforms": {}, "canonical_goldens": {}, "authoring": {},
                "thumbnail": None, "dependencies": {}, "navi_sync": {}, "source_suit_id": None, "source_provenance": None}
    files = {}
    for platform in platforms:
        target = scene.PLATFORMS[platform]
        def add(name, body, platform=platform):
            member = platform + "/" + name
            files[member] = body
            return scene.reference(member, body, platform if name.endswith(".unity") else None)
        manifest["platforms"][platform] = {role: add(role + ".unity", f"{target}:{role}".encode()) for role in scene.ROLES}
        manifest["canonical_goldens"][platform] = {role: add("golden_" + role + ".unity", f"{target}:golden:{role}".encode())
                                                 for role in ("mv_board", "mv_unmasked")}
        manifest["authoring"][platform] = {}
        for variant in scene.VARIANTS:
            raw = f"{target}:original:{variant}".encode()
            original = add("original_" + variant + ".unity", raw)
            recipe = {"format": "elichika-viewer-body-edit", "version": 1,
                      "sources": [{"name": variant, "sha256": scene.sha(raw), "container": 0, "member": None}],
                      "originals": [{"name": variant, "sha256": scene.sha(raw)}],
                      "state": {"version": 1, "savedSettingsEnabled": True, "edits": []}, "nodeIdentities": []}
            manifest["authoring"][platform][variant] = {"original": original,
                "recipe": add(variant + ".json", json.dumps(recipe).encode())}
        manifest["dependencies"][platform] = {"facedynamic": None}
        manifest["navi_sync"][platform] = {"BreastSize": [.8, 1.1, 1.2], "HipsSize": [1.25, 1.05, 1.15]}
    return manifest, files


def shared_fixture(platforms=("android",)):
    manifest, files = fixture(platforms)
    manifest.update(version=scene.SHARED_VERSION, requires=[scene.SHARED_CAPABILITY],
                    target_member_id=209, default_variant="primary")
    for family in manifest["platforms"].values():
        del files[family["navi_board"]["member"]]
        family["navi_board"] = copy.deepcopy(family["mv_board"])
    return manifest, files


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return output.getvalue()


def envelope(manifest, files, guard=scene.LEGACY_GUARD, magic=scene.MAGIC):
    return zip_bytes({scene.MANIFEST: json.dumps(manifest).encode(), scene.PAYLOAD: magic + zip_bytes(files),
                      "modinstall.txt": guard})


class SceneFormatTests(unittest.TestCase):
    def test_supplied_native_platform_sets_roundtrip_without_conversion(self):
        for platforms in (("android",), ("ios",), ("android", "ios")):
            with self.subTest(platforms=platforms):
                manifest, files = fixture(platforms)
                data = scene.encode_package(manifest, files, native_validator=native)
                self.assertEqual(scene.read_package(data, native_validator=native), {"manifest": manifest, "files": files})
                self.assertEqual(sum(len(roles) for roles in manifest["platforms"].values()), len(platforms) * 3)

    def test_shared_v2_native_families_use_exactly_two_execution_resources(self):
        for platforms in (("android",), ("ios",), ("android", "ios")):
            with self.subTest(platforms=platforms):
                manifest, files = shared_fixture(platforms)
                encoded = scene.encode_package(manifest, files, native_validator=native)
                self.assertEqual(scene.read_package(encoded, native_validator=native), {"manifest": manifest, "files": files})
                for family in manifest["platforms"].values():
                    self.assertEqual(family["navi_board"], family["mv_board"])
                    self.assertEqual(len({ref["member"] for ref in family.values()}), 2)
        self.assertEqual((scene.VERSION, scene.CAPABILITY), (1, "rina-scene-routing-v1"))

    def test_shared_v2_requires_explicit_target_and_default_variant(self):
        original, files = shared_fixture()
        for key in ("target_member_id", "default_variant"):
            changed = copy.deepcopy(original); del changed[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                scene.validate(changed, files, native_validator=native)
        for target, variant in ((1, "primary"), (6, "unmasked"), (209, "primary")):
            scene.validate({**original, "target_member_id": target, "default_variant": variant}, files, native_validator=native)
        for target, variant in ((True, "primary"), (0, "primary"), (-1, "primary"), (2 ** 31, "primary"),
                                (1.0, "primary"), (209, "unmasked"), (6, None), (6, "board")):
            with self.subTest(target=target, variant=variant), self.assertRaises(ValueError):
                scene.validate({**original, "target_member_id": target, "default_variant": variant}, files, native_validator=native)

    def test_shared_capability_is_versioned_without_weakening_v1(self):
        for producer in (fixture, shared_fixture):
            original, files = producer()
            for version, requires in ((1, [scene.SHARED_CAPABILITY]), (2, [scene.CAPABILITY]),
                                      (3, [scene.SHARED_CAPABILITY]), (True, [scene.SHARED_CAPABILITY])):
                with self.subTest(producer=producer.__name__, version=version, requires=requires), self.assertRaises(ValueError):
                    scene.validate({**original, "version": version, "requires": requires}, files, native_validator=native)

    def test_shared_v2_rejects_distinct_board_and_bare_alias(self):
        manifest, files = shared_fixture()
        changed = copy.deepcopy(manifest)
        new_ref = scene.reference("android/not-shared.unity", b"13:independent-board", "android")
        changed["platforms"]["android"]["navi_board"] = new_ref
        with self.assertRaisesRegex(ValueError, "alias"):
            scene.validate(changed, {**files, new_ref["member"]: b"13:independent-board"}, native_validator=native)
        changed = copy.deepcopy(manifest)
        changed["platforms"]["android"]["mv_unmasked"] = copy.deepcopy(changed["platforms"]["android"]["mv_board"])
        with self.assertRaisesRegex(ValueError, "separate bare"):
            scene.validate(changed, files, native_validator=native)

    def test_shared_bare_cannot_be_duplicate_board_bytes_under_another_name(self):
        manifest, files = shared_fixture()
        reference = manifest["platforms"]["android"]["mv_unmasked"]
        board = files[manifest["platforms"]["android"]["mv_board"]["member"]]
        files[reference["member"]] = board
        manifest["platforms"]["android"]["mv_unmasked"] = scene.reference(reference["member"], board, "android")
        with self.assertRaisesRegex(ValueError, "separate bare"):
            scene.validate(manifest, files, native_validator=native)

    def test_claimed_resource_cache_never_bypasses_a_second_native_family(self):
        for producer in (fixture, shared_fixture):
            manifest, files = producer()
            for key in ("platforms", "canonical_goldens", "authoring", "dependencies", "navi_sync"):
                manifest[key]["ios"] = copy.deepcopy(manifest[key]["android"])
            with self.subTest(producer=producer.__name__), self.assertRaisesRegex(ValueError, "native Android/iOS"):
                scene.validate(manifest, files, native_validator=native)

    def test_shared_sync_limits_are_positive_persisted_float32_endpoints(self):
        manifest, files = shared_fixture()
        low = struct.unpack("<f", struct.pack("<f", .2))[0]
        for value in (low, 1, 2.5):
            changed = copy.deepcopy(manifest); changed["navi_sync"]["android"] = {"BreastSize": [value] * 3}
            scene.validate(changed, files, native_validator=native)
        for value in (.199999, 0, -.8, 2.500001, float("nan"), True):
            changed = copy.deepcopy(manifest); changed["navi_sync"]["android"] = {"BreastSize": [value] * 3}
            with self.subTest(value=value), self.assertRaises(ValueError):
                scene.validate(changed, files, native_validator=native)
        old, old_files = fixture(); old["navi_sync"]["android"] = {"BreastSize": [-.5] * 3}
        scene.validate(old, old_files, native_validator=native)

    def test_old_version_guard_and_magic_are_exact_not_executable_metadata(self):
        manifest, files = fixture()
        for guard in (b"", b"costume_file = 'old.unity'\n", scene.LEGACY_GUARD + b"chara_id = 209\n"):
            with self.subTest(guard=guard), self.assertRaises(ValueError):
                scene.read_package(envelope(manifest, files, guard=guard), native_validator=native)
        for magic in (b"", b"PK\x03\x04", scene.MAGIC.replace(b"\x01", b"\x02")):
            with self.subTest(magic=magic), self.assertRaises(ValueError):
                scene.read_package(envelope(manifest, files, magic=magic), native_validator=native)

    def test_unknown_format_version_capability_or_character_fails_closed(self):
        original, files = fixture()
        for key, value in (("format", "other"), ("version", True), ("version", 2), ("version", 1.0),
                           ("requires", []), ("requires", [scene.CAPABILITY, "other"]), ("character_id", 208), ("character_id", True)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                scene.validate({**original, key: value}, files, native_validator=native)

    def test_missing_extra_roles_or_authoring_never_fall_back_to_navi(self):
        manifest, files = fixture()
        for group, key in (("platforms", "mv_board"), ("canonical_goldens", "mv_unmasked"), ("authoring", "unmasked")):
            changed = copy.deepcopy(manifest)
            del changed[group]["android"][key]
            with self.subTest(group=group), self.assertRaises(ValueError):
                scene.validate(changed, files, native_validator=native)
        changed = copy.deepcopy(manifest)
        changed["platforms"]["android"]["other"] = changed["platforms"]["android"]["mv_board"]
        with self.assertRaises(ValueError):
            scene.validate(changed, files, native_validator=native)

    def test_role_reuse_or_wrong_native_target_is_rejected(self):
        manifest, files = fixture()
        for role in ("mv_board", "mv_unmasked"):
            changed = copy.deepcopy(manifest)
            changed["platforms"]["android"][role] = changed["platforms"]["android"]["navi_board"]
            with self.subTest(role=role), self.assertRaises(ValueError):
                scene.validate(changed, files, native_validator=native)
        for target in (9, 13.0, True):
            changed = copy.deepcopy(manifest)
            changed["platforms"]["android"]["mv_board"]["target_platform"] = target
            with self.subTest(target=target), self.assertRaises(ValueError):
                scene.validate(changed, files, native_validator=native)

    def test_checksums_cover_runtime_goldens_originals_and_recipes(self):
        manifest, files = fixture()
        for member in files:
            changed = {**files, member: files[member] + b"tampered"}
            with self.subTest(member=member), self.assertRaises(ValueError):
                scene.validate(manifest, changed, native_validator=native)

    def test_authoring_recipe_must_bind_raw_original_not_navi_derivative(self):
        manifest, files = fixture()
        reference = manifest["authoring"]["android"]["primary"]["recipe"]
        recipe = json.loads(files[reference["member"]])
        for key in ("sources", "originals"):
            changed = copy.deepcopy(recipe)
            changed[key][0]["sha256"] = manifest["platforms"]["android"]["navi_board"]["sha256"]
            raw = json.dumps(changed).encode()
            changed_manifest = copy.deepcopy(manifest)
            changed_manifest["authoring"]["android"]["primary"]["recipe"] = scene.reference(reference["member"], raw)
            with self.subTest(key=key), self.assertRaises(ValueError):
                scene.validate(changed_manifest, {**files, reference["member"]: raw}, native_validator=native)

    def test_only_supported_scale_sync_is_declared(self):
        manifest, files = fixture()
        for sync in ({"HeadSize": [2, 2, 2]}, {"BreastSize": [1, 0, 1]}, {"HipsSize": [1, True, 1]}, {"HipsSize": [1, float("inf"), 1]}):
            changed = copy.deepcopy(manifest)
            changed["navi_sync"]["android"] = sync
            with self.subTest(sync=sync), self.assertRaises(ValueError):
                scene.validate(changed, files, native_validator=native)

    def test_undeclared_resources_and_unrecognized_metadata_are_rejected(self):
        manifest, files = fixture()
        with self.assertRaises(ValueError):
            scene.validate(manifest, {**files, "hidden.txt": b"danger"}, native_validator=native)
        with self.assertRaises(ValueError):
            scene.validate({**manifest, "unknown": "ignored"}, files, native_validator=native)

    def test_trusted_source_proof_requires_both_id_and_exact_descriptor_fields(self):
        manifest, files = fixture()
        descriptor = {"asset_path": "model", "pack_name": "pack", "head": 0, "size": 2, "key1": 0, "key2": 0}
        manifest["source_suit_id"] = 320913
        manifest["source_provenance"] = {"gl": {"android": {variant: copy.deepcopy(descriptor) for variant in scene.VARIANTS}}}
        scene.validate(manifest, files, native_validator=native)
        for key, value in (("source_suit_id", None), ("source_suit_id", True), ("source_provenance", None)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                scene.validate({**manifest, key: value}, files, native_validator=native)
        bad = copy.deepcopy(manifest)
        bad["source_provenance"]["gl"]["android"]["primary"]["head"] = True
        with self.assertRaises(ValueError):
            scene.validate(bad, files, native_validator=native)

    def test_envelope_has_only_three_owned_members_and_inert_payload(self):
        manifest, files = fixture()
        raw = scene.encode_package(manifest, files, native_validator=native)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(set(archive.namelist()), {scene.MANIFEST, scene.PAYLOAD, "modinstall.txt"})
            self.assertFalse(archive.read(scene.PAYLOAD).startswith(b"PK"))
            self.assertNotIn(b"chara_id", archive.read("modinstall.txt"))

    def test_optional_source_archives_are_inert_bounded_and_checksum_bound(self):
        manifest, files = fixture()
        raw = zip_bytes({"notes.txt": b"Preserve exactly"})
        reference = scene.reference("metadata/source-0.data", raw)
        manifest["source_archives"] = [{"name": "original.zip", "file": reference}]
        files[reference["member"]] = raw
        encoded = scene.encode_package(manifest, files, native_validator=native)
        self.assertEqual(scene.read_package(encoded, native_validator=native)["files"][reference["member"]], raw)
        with self.assertRaises(ValueError):
            scene.validate(manifest, {**files, reference["member"]: raw + b"changed"}, native_validator=native)
        for name in ("../original.zip", "/original.zip", "nested/original.zip"):
            changed = copy.deepcopy(manifest); changed["source_archives"][0]["name"] = name
            with self.subTest(name=name), self.assertRaises(ValueError): scene.validate(changed, files, native_validator=native)
        changed = copy.deepcopy(manifest)
        changed["source_archives"][0]["file"] = scene.reference("metadata/source.zip", raw)
        with self.assertRaises(ValueError):
            scene.validate(changed, {**files, "metadata/source.zip": raw}, native_validator=native)

    def test_dispatch_hint_and_bounded_file_read(self):
        manifest, files = fixture()
        raw = scene.encode_package(manifest, files, native_validator=native)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scene.zip"
            path.write_bytes(raw)
            self.assertTrue(scene.is_scene_package(path))
            self.assertEqual(scene.read_package(path, native_validator=native)["manifest"], manifest)
            link = path.with_name("linked.zip")
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                scene.read_package(link, native_validator=native)
        self.assertFalse(scene.is_scene_package(b"not-a-zip"))

    def test_path_traversal_and_duplicate_members_are_rejected_before_decode(self):
        manifest, files = fixture()
        for name in ("../models.unity", "/models.unity", "a\\b.unity", "a/../b.unity"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                scene.read_package(envelope(manifest, {**files, name: b"13:bad"}), native_validator=native)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(scene.MANIFEST, b"{}")
            archive.writestr(scene.MANIFEST.upper(), b"{}")
        with self.assertRaises(ValueError):
            scene.read_package(output.getvalue(), native_validator=native)

    def test_malformed_scene_marker_never_falls_through_to_legacy(self):
        manifest, files = fixture()
        good = {scene.MANIFEST: json.dumps(manifest).encode(), scene.PAYLOAD: scene.MAGIC + zip_bytes(files),
                "modinstall.txt": scene.LEGACY_GUARD}
        for other in ({"../unsafe.txt": b"legacy execution forbidden"}, {"oversized.data": b"x" * 1024}):
            raw = zip_bytes({**good, **other})
            self.assertTrue(scene.is_scene_package(raw))
            with self.assertRaises(ValueError): scene.read_package(raw, native_validator=native)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, raw in good.items(): archive.writestr(name, raw)
            archive.writestr("MODINSTALL.TXT", b"legacy execution forbidden")
        self.assertTrue(scene.is_scene_package(output.getvalue()))
        with self.assertRaises(ValueError): scene.read_package(output.getvalue(), native_validator=native)


if __name__ == "__main__":
    unittest.main()
