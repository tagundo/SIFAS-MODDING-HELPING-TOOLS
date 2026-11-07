"""Pure envelope tests; synthetic platform tags are not Unity/runtime proof."""
import copy
import unittest
from unittest import mock

from webtools.core import viewer_scene_format as scene
from test_viewer_scene_format import fixture, native, shared_fixture


def graph_fixture(platforms=("android",)):
    manifest, files = shared_fixture(platforms)
    graph = {}
    for platform in platforms:
        board, bare = (("Board_A", "Bare_A") if platform == "android" else
                       ("IOSBoard", "IOSBare"))
        nodes = {
            board: {"resource": copy.deepcopy(manifest["platforms"][platform]["mv_board"]),
                    "model_dependencies": [], "shared_shader_dependencies": ["ASMember.shader"]},
            bare: {"resource": copy.deepcopy(manifest["platforms"][platform]["mv_unmasked"]),
                   "model_dependencies": [], "shared_shader_dependencies": ["ASMember.shader"]},
        }
        graph[platform] = {"nodes": nodes, "role_bindings": {
            "navi_board": board, "mv_board": board, "mv_unmasked": bare}}
    manifest["execution_model_graph"] = graph
    return manifest, files


def add_node(manifest, files, platform, node_id, dependencies=(), *, raw=None):
    raw = raw if raw is not None else f"{scene.PLATFORMS[platform]}:dependency:{node_id}".encode()
    member = platform + "/graph/" + node_id + ".unity"
    files[member] = raw
    node = {"resource": scene.reference(member, raw, platform),
            "model_dependencies": list(dependencies), "shared_shader_dependencies": []}
    manifest["execution_model_graph"][platform]["nodes"][node_id] = node
    return node


class ExecutionModelGraphTests(unittest.TestCase):
    def setUp(self):
        # Every test must use the explicit synthetic validator, including decode.
        # Accidentally falling through to the production Unity reader is a failure.
        patch = mock.patch.object(scene, "_native_platform", side_effect=AssertionError("Unity loading is forbidden here"))
        patch.start()
        self.addCleanup(patch.stop)

    def roundtrip(self, manifest, files):
        encoded = scene.encode_package(manifest, files, native_validator=native)
        result = scene.read_package(encoded, native_validator=native)
        self.assertEqual(result, {"manifest": manifest, "files": files})
        return result

    def invalid(self, manifest, files, message=None):
        with self.assertRaisesRegex(ValueError, message or "."):
            scene.encode_package(manifest, files, native_validator=native)

    def test_plain_v2_stays_valid_without_optional_graph(self):
        manifest, files = shared_fixture(("android", "ios"))
        self.assertNotIn("execution_model_graph", manifest)
        self.roundtrip(manifest, files)

    def test_single_native_families_roundtrip_exact_shared_board_roots(self):
        for platform in ("android", "ios"):
            with self.subTest(platform=platform):
                manifest, files = graph_fixture((platform,))
                result = self.roundtrip(manifest, files)
                family = result["manifest"]["execution_model_graph"][platform]
                self.assertEqual(len(family["nodes"]), 2)
                self.assertEqual(family["role_bindings"]["navi_board"], family["role_bindings"]["mv_board"])
                self.assertNotEqual(family["role_bindings"]["mv_board"], family["role_bindings"]["mv_unmasked"])

    def test_two_platforms_keep_distinct_nonroot_ids_topologies_and_authoring(self):
        manifest, files = graph_fixture(("android", "ios"))
        originals = copy.deepcopy({key: manifest[key] for key in ("canonical_goldens", "authoring")})
        android, ios = (manifest["execution_model_graph"][key] for key in ("android", "ios"))
        add_node(manifest, files, "android", "Shared_A")
        add_node(manifest, files, "android", "Face_A", ["Shared_A"])
        android["nodes"]["Board_A"]["model_dependencies"] = ["Shared_A"]
        android["nodes"]["Bare_A"]["model_dependencies"] = ["Face_A", "Shared_A"]
        add_node(manifest, files, "ios", "I_tail")
        add_node(manifest, files, "ios", "I_middle", ["I_tail"])
        add_node(manifest, files, "ios", "I_front", ["I_middle"])
        ios["nodes"]["IOSBoard"]["model_dependencies"] = ["I_front"]
        ios["nodes"]["IOSBare"]["model_dependencies"] = ["I_middle"]
        result = self.roundtrip(manifest, files)
        self.assertEqual({key: result["manifest"][key] for key in originals}, originals)
        self.assertEqual(len(android["nodes"]), 4)
        self.assertEqual(len(ios["nodes"]), 5)
        self.assertTrue(set(android["nodes"]).isdisjoint(ios["nodes"]))

    def test_graph_native_platform_set_must_match_declared_families(self):
        original, files = graph_fixture(("android", "ios"))
        for platforms in ({"android": original["execution_model_graph"]["android"]}, {},
                          {**original["execution_model_graph"], "windows": original["execution_model_graph"]["android"]}):
            changed = copy.deepcopy(original); changed["execution_model_graph"] = platforms
            with self.subTest(platforms=list(platforms)):
                self.invalid(changed, files, "incomplete native platforms")

    def test_v1_cannot_claim_v2_graph_even_with_valid_native_resources(self):
        manifest, files = fixture()
        graph, _ = graph_fixture()
        manifest["execution_model_graph"] = graph["execution_model_graph"]
        self.invalid(manifest, files, "format or capability")

    def test_missing_duplicate_or_nonlist_model_dependencies_are_rejected(self):
        for value in (["Missing"], ["Bare_A", "Bare_A"], "Bare_A", [None], [1]):
            manifest, files = graph_fixture()
            manifest["execution_model_graph"]["android"]["nodes"]["Board_A"]["model_dependencies"] = value
            with self.subTest(dependencies=value):
                self.invalid(manifest, files, "missing or duplicated")

    def test_self_cycle_and_indirect_cycle_are_rejected(self):
        for indirect in (False, True):
            manifest, files = graph_fixture()
            nodes = manifest["execution_model_graph"]["android"]["nodes"]
            if indirect:
                add_node(manifest, files, "android", "Middle", ["Board_A"])
                nodes["Board_A"]["model_dependencies"] = ["Middle"]
            else:
                nodes["Board_A"]["model_dependencies"] = ["Board_A"]
            with self.subTest(indirect=indirect):
                self.invalid(manifest, files, "cyclic")

    def test_valid_but_unreachable_native_resource_is_not_accepted(self):
        manifest, files = graph_fixture()
        add_node(manifest, files, "android", "Orphan")
        self.invalid(manifest, files, "unreachable orphan")

    def test_role_bindings_require_exact_roles_shared_board_and_separate_bare(self):
        mutations = [
            {"mv_board": "Board_A", "mv_unmasked": "Bare_A"},
            {"navi_board": "Board_A", "mv_board": "Board_A", "mv_unmasked": "Bare_A", "unknown": "Board_A"},
            {"navi_board": "Bare_A", "mv_board": "Board_A", "mv_unmasked": "Bare_A"},
            {"navi_board": "Board_A", "mv_board": "Board_A", "mv_unmasked": "Board_A"},
            {"navi_board": "Missing", "mv_board": "Missing", "mv_unmasked": "Bare_A"},
        ]
        for bindings in mutations:
            manifest, files = graph_fixture()
            manifest["execution_model_graph"]["android"]["role_bindings"] = bindings
            with self.subTest(bindings=bindings):
                self.invalid(manifest, files, "role bindings")

    def test_graph_root_reference_must_equal_the_corresponding_scene_role(self):
        manifest, files = graph_fixture()
        replacement = add_node(manifest, files, "android", "Replacement")
        family = manifest["execution_model_graph"]["android"]
        family["nodes"]["Board_A"]["resource"] = replacement["resource"]
        del family["nodes"]["Replacement"]
        self.invalid(manifest, files, "root does not match")

    def test_duplicate_member_and_same_bytes_under_another_member_are_rejected(self):
        for same_member in (True, False):
            manifest, files = graph_fixture()
            nodes = manifest["execution_model_graph"]["android"]["nodes"]
            root_ref = nodes["Board_A"]["resource"]
            duplicate = add_node(manifest, files, "android", "Duplicate", raw=files[root_ref["member"]])
            if same_member:
                del files[duplicate["resource"]["member"]]
                duplicate["resource"] = copy.deepcopy(root_ref)
            nodes["Bare_A"]["model_dependencies"] = ["Duplicate"]
            with self.subTest(same_member=same_member):
                self.invalid(manifest, files, "duplicate physical")

    def test_dependency_reference_checksum_and_native_bytes_are_checked(self):
        for corruption in ("bytes", "digest", "native", "target", "missing"):
            manifest, files = graph_fixture()
            node = add_node(manifest, files, "android", "Part")
            manifest["execution_model_graph"]["android"]["nodes"]["Board_A"]["model_dependencies"] = ["Part"]
            ref = node["resource"]
            if corruption == "bytes":
                files[ref["member"]] += b"changed"
            elif corruption == "digest":
                ref["sha256"] = "0" * 64
            elif corruption == "native":
                files[ref["member"]] = b"9:wrong-native-family"
                node["resource"] = scene.reference(ref["member"], files[ref["member"]], "android")
            elif corruption == "target":
                ref["target_platform"] = True
            else:
                del files[ref["member"]]
            with self.subTest(corruption=corruption):
                self.invalid(manifest, files, "checksum|native Android/iOS|missing")

    def test_copying_android_graph_into_ios_never_reuses_native_validation(self):
        manifest, files = graph_fixture(("android", "ios"))
        manifest["execution_model_graph"]["ios"] = copy.deepcopy(manifest["execution_model_graph"]["android"])
        self.invalid(manifest, files, "native Android/iOS")

    def test_opaque_identifiers_reject_paths_controls_non_ascii_and_excess_length(self):
        for invalid_id in ("", "_start", "9start", "a/b", "a\\b", "a\n", "é", "A" * 65, 1, False):
            manifest, files = graph_fixture()
            family = manifest["execution_model_graph"]["android"]
            family["nodes"][invalid_id] = family["nodes"].pop("Board_A")
            family["role_bindings"].update(navi_board=invalid_id, mv_board=invalid_id)
            with self.subTest(identifier=invalid_id):
                self.invalid(manifest, files, "node identities")

    def test_maximum_graph_is_valid_but_a_thirty_third_node_is_rejected(self):
        manifest, files = graph_fixture()
        nodes = manifest["execution_model_graph"]["android"]["nodes"]
        for index in range(30):
            add_node(manifest, files, "android", "Part" + str(index), ["Part" + str(index + 1)] if index < 29 else [])
        nodes["Board_A"]["model_dependencies"] = ["Part0"]
        nodes["Bare_A"]["model_dependencies"] = ["Part29"]
        self.assertEqual(len(nodes), 32)
        self.roundtrip(manifest, files)
        add_node(manifest, files, "android", "Overflow")
        nodes["Part29"]["model_dependencies"] = ["Overflow"]
        self.invalid(manifest, files, "node identities")

    def test_shared_shader_leaf_keys_are_bounded_data_and_need_no_model_node(self):
        manifest, files = graph_fixture()
        keys = [str(index) + "x" * (512 - len(str(index))) for index in range(32)]
        manifest["execution_model_graph"]["android"]["nodes"]["Board_A"]["shared_shader_dependencies"] = keys
        self.roundtrip(manifest, files)

    def test_shader_keys_reject_duplicates_controls_bad_types_and_overflow(self):
        invalid = [["same", "same"], [""], ["x" * 513], ["shader\0key"], ["shader\nkey"], ["shader\x7fkey"],
                   ["shader\x85key"], list(map(str, range(33))), "shader", [None], [False]]
        for keys in invalid:
            manifest, files = graph_fixture()
            manifest["execution_model_graph"]["android"]["nodes"]["Board_A"]["shared_shader_dependencies"] = keys
            with self.subTest(keys=keys):
                self.invalid(manifest, files, "shader dependency")

    def test_graph_family_node_and_reference_unknown_metadata_is_rejected(self):
        for location in ("family", "node", "reference"):
            manifest, files = graph_fixture()
            family = manifest["execution_model_graph"]["android"]
            target = family if location == "family" else family["nodes"]["Board_A"]
            if location == "reference":
                target = target["resource"]
            target["ignored_metadata"] = "must not be ignored"
            with self.subTest(location=location):
                self.invalid(manifest, files, "invalid")


if __name__ == "__main__":
    unittest.main()
