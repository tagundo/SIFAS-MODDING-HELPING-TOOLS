"""Unity built-in Plane/Quad meshes referenced from the default resources."""
import math
from pathlib import Path
import tempfile
import unittest

from webtools.core import model_viewer as viewer
from webtools.core import unity_builtin_meshes as builtin

from test_model_viewer import attribute, unpack_glb

FIXTURES = Path(__file__).parent / "fixtures"


class BuiltinGeometryTests(unittest.TestCase):
    def setUp(self):
        try:
            import numpy
        except ImportError as error:
            raise unittest.SkipTest("numpy is needed for geometry checks") from error
        self.np = numpy

    def test_plane_matches_default_resource_layout_in_mirrored_basis(self):
        name, positions, normals, uv, (triangles,) = builtin.geometry(10209)
        self.assertEqual((name, positions.shape, triangles.shape), ("Plane", (121, 3), (200, 3)))
        # Unity vertex 0 is (5, 0, 5) with UV (0, 0); vertex 10 is (-5, 0, 5) with UV (1, 0).
        self.np.testing.assert_array_equal(positions[[0, 10, 120]], [[-5, 0, 5], [5, 0, 5], [5, 0, -5]])
        self.np.testing.assert_array_equal(uv[[0, 10, 120]], [[0, 1], [1, 1], [1, 0]])
        self.np.testing.assert_array_equal(normals, [[0, 1, 0]] * 121)
        # Unity's first triangle (0, 11, 12) changes winding with the X mirror.
        self.assertEqual(triangles[0].tolist(), [0, 12, 11])
        for corner in triangles[:4]:
            a, b, c = positions[corner]
            self.assertGreater(self.np.cross(b - a, c - a)[1], 0)

    def test_quad_matches_default_resource_vertices(self):
        from webtools.core.mv_studio_stage_title import _QUAD

        name, positions, normals, uv, (triangles,) = builtin.geometry(10210)
        self.assertEqual(name, "Quad")
        self.np.testing.assert_allclose(positions, _QUAD["positions"], atol=1e-12)
        self.np.testing.assert_array_equal(uv, _QUAD["uv"])
        self.assertEqual(triangles.reshape(-1).tolist(), _QUAD["indices"])
        self.np.testing.assert_array_equal(normals, [[0, 0, -1]] * 4)

    def test_world_transform_is_applied_with_mirror_and_winding(self):
        angle = math.radians(90)
        world = self.np.array([[math.cos(angle), 0, math.sin(angle), 2], [0, 1, 0, 3],
                               [-math.sin(angle), 0, math.cos(angle), 4], [0, 0, 0, 1]])
        world[:3, :3] *= 2
        _, positions, normals, _, (triangles,) = builtin.geometry(10210, world)
        # Unity (-0.5, -0.5, 0) -> world (2, 2, 5) -> mirrored (-2, 2, 5).
        self.np.testing.assert_allclose(positions[0], [-2, 2, 5], atol=1e-12)
        self.np.testing.assert_allclose(normals[0], [1, 0, 0], atol=1e-12)
        self.assertEqual(triangles[0].tolist(), [0, 2, 1])
        world[0, :3] *= -1  # A mirrored renderer keeps Unity's own winding.
        self.assertEqual(builtin.geometry(10210, world)[4][0][0].tolist(), [0, 1, 2])
        with self.assertRaisesRegex(viewer.ModelViewerError, "zero-scale"):
            builtin.geometry(10209, self.np.diag([0., 1., 1., 1.]))


class BuiltinMeshExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import UnityPy
            import numpy
        except ImportError as error:
            raise unittest.SkipTest("UnityPy and numpy are needed for real export checks") from error
        cls.UnityPy, cls.np = UnityPy, numpy

    def fixture(self, directory, path_id, external="Library/unity default resources"):
        """The triangle scene with its MeshFilter pointing at an external built-in mesh."""
        from UnityPy.files.SerializedFile import FileIdentifier

        env = self.UnityPy.load((FIXTURES / "viewer_triangle.unity").read_bytes())
        serialized = next(iter(env.files.values()))
        identifier = object.__new__(FileIdentifier)
        identifier.path, identifier.temp_empty, identifier.guid, identifier.type = external, "", bytes(16), 0
        serialized.externals.append(identifier)
        for obj in env.objects:
            tree = obj.read_typetree()
            if obj.type.name == "MeshFilter":
                tree["m_Mesh"] = {"m_FileID": len(serialized.externals), "m_PathID": path_id}
            elif obj.type.name == "Transform":
                tree["m_LocalPosition"] = dict(x=1., y=2., z=3.)
            else:
                continue
            obj.save_typetree(tree)
        path = Path(directory) / "builtin.unity"
        path.write_bytes(serialized.save())
        return path

    def export(self, path, stage=True):
        context = {"enabled": False, "allow_download": False, "_mv_stage": stage}
        result = viewer.prepare([str(path)], face_context=context)
        return result, *unpack_glb(viewer.get_model(result["id"]))

    def test_stage_preview_draws_default_resource_quad_at_its_renderer_transform(self):
        with tempfile.TemporaryDirectory() as directory:
            result, doc, binary = self.export(self.fixture(directory, 10210))
        self.assertEqual(result["stats"]["vertices"], 4)
        mesh = doc["meshes"][0]
        primitive = mesh["primitives"][0]
        self.assertEqual(mesh["name"], "Quad")
        self.assertEqual(primitive["extras"]["viewerMesh"]["mesh"]["id"], "10210")
        points = self.np.array(attribute(doc, binary, primitive["attributes"]["POSITION"]))
        self.np.testing.assert_allclose(points, [[-.5, 1.5, 3], [-1.5, 2.5, 3], [-1.5, 1.5, 3], [-.5, 2.5, 3]], atol=1e-6)
        self.assertEqual(attribute(doc, binary, primitive["indices"]), [(0,), (2,), (1,), (1,), (3,), (0,)])

    def test_unknown_builtin_ids_other_files_and_non_stage_previews_stay_missing(self):
        for path_id, external, stage in ((10202, "Library/unity default resources", True),
                                         (10210, "Library/unity_builtin_extra", True),
                                         (10210, "Library/unity default resources", False)):
            with self.subTest(path_id=path_id, external=external, stage=stage), \
                    tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(viewer.ModelViewerError, "No visible"):
                    self.export(self.fixture(directory, path_id, external), stage)


if __name__ == "__main__":
    unittest.main()
