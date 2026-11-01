"""Bounded, read-only Unity rest-pose skinning for static model previews.

The result is always in Unity WORLD coordinates. A caller must not apply the
renderer transform again; coordinate-system conversion belongs after this step.
No mesh, bind pose, weight, UV or texture supplied by the caller is modified.
"""

MAX_VERTICES = 250_000
MAX_BONES = 1024
MAX_CHUNK_SIZE = 16_384


class SkinningError(ValueError):
    """Rest geometry cannot be reconstructed safely from the supplied skin."""


def _rows(value, count, widths, np, label, dtype=float):
    """Check dimensions before a potentially copying numeric conversion."""
    try:
        if len(value) != count:
            raise ValueError("row count")
        if isinstance(value, np.ndarray):
            if value.ndim != 2 or value.shape[1] not in widths:
                raise ValueError("column count")
        elif any(len(row) not in widths for row in value):
            raise ValueError("column count")
        result = np.asarray(value, dtype=dtype)
        if result.ndim != 2 or result.shape[0] != count or result.shape[1] not in widths:
            raise ValueError("array shape")
        return result
    except (TypeError, ValueError, OverflowError) as error:
        raise SkinningError(f"The model skin contains invalid {label}.") from error


def _matrix(value, np):
    try:
        if isinstance(value, dict):
            result = np.array([[value[f"e{row}{column}"] for column in range(4)]
                               for row in range(4)], dtype=float)
        elif hasattr(value, "e00"):
            result = np.array([[getattr(value, f"e{row}{column}") for column in range(4)]
                               for row in range(4)], dtype=float)
        else:
            result = _rows(value, 4, (4,), np, "affine matrix")
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError) as error:
        raise SkinningError("A model skin contains an invalid affine matrix.") from error
    if result.shape != (4, 4) or not np.isfinite(result).all() \
            or not np.allclose(result[3], [0, 0, 0, 1], rtol=0, atol=1e-6):
        raise SkinningError("A model skin contains an invalid affine matrix.")
    return result


def _inverse_linear(matrix, np):
    try:
        inverse = np.linalg.inv(matrix[:3, :3])
    except np.linalg.LinAlgError as error:
        raise SkinningError("A model skin contains a zero-scale transform.") from error
    if not np.isfinite(inverse).all():
        raise SkinningError("A model skin contains an invalid normal transform.")
    return inverse


def _normalize(normals, np):
    if normals is None:
        return None
    lengths = np.linalg.norm(normals, axis=1)
    if not np.isfinite(lengths).all():
        raise SkinningError("The model skin produced invalid vertex normals.")
    zero = lengths < 1e-12
    normals[zero] = [0, 1, 0]
    lengths[zero] = 1
    normals /= lengths[:, None]
    return normals


def rest_skin_mesh(positions, normals, bone_indices, bone_weights,
                   bone_world_matrices, bind_poses, renderer_world=None, *,
                   max_vertices=MAX_VERTICES, chunk_size=MAX_CHUNK_SIZE):
    """Return world-space positions/normals without changing any input.

    ``bone_indices`` and ``bone_weights`` are MeshHandler.m_BoneIndices and
    m_BoneWeights (N x at most four). ``bone_world_matrices`` follows the
    renderer's m_Bones order; unresolved entries may be None, but referencing
    one with a positive weight is an error. Bind poses accept either numeric
    4x4 arrays or Unity Matrix4x4 objects/dicts with row-major e00..e33 fields.

    No bind poses, or no renderer bone information (None), uses the ordinary
    renderer transform. Zero-total-weight vertices also use that transform and
    report a warning. Other incomplete/invalid active skin data raises an error
    instead of silently placing disconnected geometry. Tiny weight round-off
    is normalized; a total differing from one by over .001 is invalid.

    Position skinning is sum(w * (boneWorld @ bindPose) * vertex). Normals use
    the corresponding weighted inverse-transpose linear transforms, followed
    by normalization. Work is chunked; no N x bone-count allocation is made.
    ``orientation_sign`` lets the exporter preserve winding after world-space
    skinning. Skeletons mixing reflected and ordinary active binds cannot be
    represented by one static winding and are rejected.
    """
    import numpy as np

    if not isinstance(max_vertices, int) or not 0 < max_vertices <= MAX_VERTICES \
            or not isinstance(chunk_size, int) or not 0 < chunk_size <= MAX_CHUNK_SIZE:
        raise SkinningError("The model skin exceeds the preview allocation limit.")
    try:
        count = len(positions)
    except TypeError as error:
        raise SkinningError("The model skin has no vertex positions.") from error
    if not 0 < count <= max_vertices:
        raise SkinningError("The model skin exceeds the preview vertex limit.")
    points = _rows(positions, count, (3,), np, "vertex positions")
    if not np.isfinite(points).all():
        raise SkinningError("The model skin contains invalid vertex positions.")
    source_normals = None if normals is None else _rows(normals, count, (3,), np, "vertex normals")
    if source_normals is not None and not np.isfinite(source_normals).all():
        raise SkinningError("The model skin contains invalid vertex normals.")
    world = _matrix(np.eye(4) if renderer_world is None else renderer_world, np)
    world_inverse = _inverse_linear(world, np)
    result_positions = np.empty_like(points)
    result_normals = None if source_normals is None else np.empty_like(source_normals)
    warnings = []

    def ordinary(start, end, selection=None):
        selected = slice(start, end) if selection is None else start + np.flatnonzero(selection)
        result_positions[selected] = points[selected] @ world[:3, :3].T + world[:3, 3]
        if result_normals is not None:
            result_normals[selected] = source_normals[selected] @ world_inverse

    pose_count = 0 if bind_poses is None else len(bind_poses)
    if not 0 <= pose_count <= MAX_BONES:
        raise SkinningError("The model skin exceeds the preview bone limit.")
    if not pose_count or bone_world_matrices is None:
        for start in range(0, count, chunk_size):
            ordinary(start, min(count, start + chunk_size))
        if not np.isfinite(result_positions).all():
            raise SkinningError("The model skin produced invalid rest geometry.")
        if pose_count:
            warnings.append("skin_bones_unavailable")
        return {"positions": result_positions, "normals": _normalize(result_normals, np),
                "applied": False, "world_space": True, "warnings": warnings,
                "orientation_sign": -1 if np.linalg.det(world[:3, :3]) < 0 else 1}

    bone_count = len(bone_world_matrices)
    if not 0 < bone_count <= MAX_BONES or not 0 < pose_count <= MAX_BONES:
        raise SkinningError("The model skin exceeds the preview bone limit.")
    if bone_indices is None or bone_weights is None:
        raise SkinningError("The model skin is missing vertex weights.")
    indices = _rows(bone_indices, count, (1, 2, 3, 4), np, "bone indices", dtype=None)
    weights = _rows(bone_weights, count, (1, 2, 3, 4), np, "vertex weights")
    if indices.shape != weights.shape:
        raise SkinningError("Only up to four skin weights per vertex are supported.")
    if indices.dtype.kind not in "iuf" or not np.isfinite(indices).all() \
            or not np.isfinite(weights).all() or (weights < 0).any():
        raise SkinningError("The model skin contains invalid weights or bone indices.")
    active = weights > 0
    if np.any(active & ((indices < 0) | (indices >= min(bone_count, pose_count))
                        | (indices != np.floor(indices)))):
        raise SkinningError("A model skin weight points to a missing bone.")
    # Ignore unused slots, which some exporters populate with a sentinel index.
    safe_indices = np.where(active, indices, 0).astype(np.intp)
    totals = weights.sum(axis=1)
    positive = totals > 0
    if np.any(positive & (np.abs(totals - 1) > .001)):
        raise SkinningError("The model skin weights do not add up to one.")
    if not positive.all():
        warnings.append("skin_zero_weight_vertices")
    used = np.unique(safe_indices[active])
    skin = np.zeros((min(bone_count, pose_count), 4, 4), dtype=float)
    normal_inverse = np.zeros((len(skin), 3, 3), dtype=float)
    signs = set()
    for index in used:
        if bone_world_matrices[index] is None:
            raise SkinningError("A model skin weight points to an unresolved bone.")
        skin[index] = _matrix(bone_world_matrices[index], np) @ _matrix(bind_poses[index], np)
        normal_inverse[index] = _inverse_linear(skin[index], np)
        signs.add(-1 if np.linalg.det(skin[index, :3, :3]) < 0 else 1)
    fallback_sign = -1 if np.linalg.det(world[:3, :3]) < 0 else 1
    if not positive.all():
        signs.add(fallback_sign)
    if len(signs) > 1:
        raise SkinningError("The model skin mixes incompatible reflected transforms.")

    for start in range(0, count, chunk_size):
        end = min(count, start + chunk_size)
        chunk_positive = positive[start:end]
        result_positions[start:end] = 0
        if result_normals is not None:
            result_normals[start:end] = 0
        denominator = np.where(chunk_positive, totals[start:end], 1)
        for slot in range(weights.shape[1]):
            selected = safe_indices[start:end, slot]
            fraction = weights[start:end, slot] / denominator
            matrices = skin[selected]
            transformed = np.einsum("nij,nj->ni", matrices[:, :3, :3], points[start:end])
            transformed += matrices[:, :3, 3]
            result_positions[start:end] += transformed * fraction[:, None]
            if result_normals is not None:
                transformed_normals = np.einsum("ni,nij->nj", source_normals[start:end],
                                                normal_inverse[selected])
                result_normals[start:end] += transformed_normals * fraction[:, None]
        if not chunk_positive.all():
            ordinary(start, end, ~chunk_positive)
    if not np.isfinite(result_positions).all() \
            or (result_normals is not None and not np.isfinite(result_normals).all()):
        raise SkinningError("The model skin produced invalid rest geometry.")
    return {"positions": result_positions, "normals": _normalize(result_normals, np),
            "applied": bool(positive.any()), "world_space": True, "warnings": warnings,
            "orientation_sign": next(iter(signs), fallback_sign)}
