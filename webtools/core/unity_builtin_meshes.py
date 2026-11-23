"""Unity's built-in meshes referenced from "library/unity default resources".

A MeshFilter that points at one of these meshes has no Mesh object in the
bundle. The geometry below matches the Android and iOS default resources
(Plane 10209: 11x11 vertices over 10 m in XZ, Quad 10210: 1 m in XY facing -Z).
The Plane's 200 triangles are the same as Unity's; only their order differs,
which does not matter for a flat mesh.
"""

DEFAULT_RESOURCES = "library/unity default resources"


def _plane():
    vertices = [(5 - u, 0, 5 - v) for v in range(11) for u in range(11)]
    normals = [(0, 1, 0)] * 121
    uv = [(u / 10, v / 10) for v in range(11) for u in range(11)]
    triangles = []
    for row in range(10):
        for column in range(10):
            base = row * 11 + column
            triangles.extend(((base, base + 11, base + 12), (base, base + 12, base + 1)))
    return vertices, normals, uv, triangles


def _quad():
    vertices = [(-.5, -.5, 0), (.5, .5, 0), (.5, -.5, 0), (-.5, .5, 0)]
    return vertices, [(0, 0, -1)] * 4, [(0, 0), (1, 1), (1, 0), (0, 1)], [(0, 1, 2), (1, 0, 3)]


MESHES = {10209: ("Plane", _plane), 10210: ("Quad", _quad)}


def mesh_id(scene, game_object):
    """Return the built-in Mesh pathID the GameObject's MeshFilter points at, or None."""
    from . import model_viewer as viewer

    tree = scene.tree(game_object)
    for entry in tree.get("m_Component", []):
        mesh_filter = viewer._ref(game_object, entry.get("component"))
        if mesh_filter is None or mesh_filter.type.name != "MeshFilter":
            continue
        pointer = scene.tree(mesh_filter).get("m_Mesh", {})
        file_id, path_id = pointer.get("m_FileID", 0), pointer.get("m_PathID")
        externals = mesh_filter.assets_file.externals
        if (path_id in MESHES and type(file_id) is int and 0 < file_id <= len(externals)
                and externals[file_id - 1].path.replace("\\", "/").lower() == DEFAULT_RESOURCES):
            return path_id
        return None
    return None


def geometry(path_id, world=None):
    """Return (name, positions, normals, uv, [triangles]) like model_viewer._geometry.

    ``world`` is the Unity local-to-world matrix (identity for meshes placed
    under a retained node). Output uses the editor's mirrored X basis, flipped V
    and the matching triangle winding.
    """
    import numpy as np

    from .model_viewer import ModelViewerError

    name, build = MESHES[path_id]
    vertices, normals, uv, triangles = build()
    world = np.eye(4) if world is None else np.asarray(world, dtype=float)
    transform = np.diag([-1., 1., 1., 1.]) @ world
    positions = np.asarray(vertices, dtype=float) @ transform[:3, :3].T + transform[:3, 3]
    try:
        normals = np.asarray(normals, dtype=float) @ np.linalg.inv(transform[:3, :3])
    except np.linalg.LinAlgError as error:
        raise ModelViewerError("The model contains a zero-scale transform.") from error
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    indices = np.asarray(triangles, dtype=np.int64)
    if np.linalg.det(world[:3, :3]) >= 0:
        indices = indices[:, [0, 2, 1]]
    coordinates = np.asarray(uv, dtype=float)
    coordinates[:, 1] = 1 - coordinates[:, 1]
    # Normalize signed zeros so the identity placement stays byte-stable.
    return name, positions + 0., normals + 0., coordinates, [indices]
