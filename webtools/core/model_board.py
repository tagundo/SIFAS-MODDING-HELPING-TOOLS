"""Native SIFAS board placement in a private preview transform view."""

# CommonCoreMemberHead.ExistsMask assigns UtilVector.Forword3 * .001f to
# these two local positions. Keeping the float32 value also keeps the glTF
# bone and rigid facial inverse bind on the same basis.
BOARD_POSITION = (0., 0., 0.0010000000474974513)


def board_positions(scene):
    """Return runtime overrides without changing source trees or source files.

    Ownership is read from the same source as the active native board mesh.
    A costume filename, another selected source or the app selection cannot
    identify a board. Transform names deliberately retain Unity's case-sensitive
    Find semantics rather than accepting vaguely similar mask names.
    """
    from .model_viewer import _key, _ref, _source_path
    from .model_faces import _mesh, source_owner

    roots, owners = {}, {}
    for renderer, tree, game_object in scene.renderers:
        if not tree.get("m_Enabled", True) or not scene.active(game_object):
            continue
        mesh = _mesh(scene, renderer, tree, game_object)
        if mesh is None or mesh.type.name != "Mesh":
            continue
        source = _source_path(renderer)
        if not source or _source_path(game_object) != source or _source_path(mesh) != source:
            continue
        transform = scene.transforms.get(_key(game_object))
        seen = set()
        while transform is not None and _source_path(transform) == source:
            key = _key(transform)
            if key in seen or len(seen) >= 256:
                break  # Scene.active/world retain the ordinary invalid-tree error.
            seen.add(key)
            current = scene.tree(transform)
            game = _ref(transform, current.get("m_GameObject"))
            parent = _ref(transform, current.get("m_Father"))
            if game is not None and _source_path(game) == source and scene.name(game) == "mesh_facedots" and parent is not None \
                    and _source_path(parent) == source:
                head = _ref(parent, scene.tree(parent).get("m_GameObject"))
                if head is not None and _source_path(head) == source and scene.name(head) == "Head_Face":
                    if source not in owners:
                        owners[source] = source_owner(scene, source)
                    if owners[source] == {209}:
                        roots[key] = (transform, parent, source)
                    break
            transform = parent

    positions = {key: BOARD_POSITION for key in roots}
    if not roots:
        return positions
    # Resolve the overlay by the exact same head identity. A same-named leaf
    # under another head/source is never initialized on its behalf.
    heads = {_key(head): source for _, head, source in roots.values()}
    for transform in scene.transforms.values():
        source = _source_path(transform)
        tree = scene.tree(transform)
        game = _ref(transform, tree.get("m_GameObject"))
        if game is None or _source_path(game) != source or scene.name(game) != "Mask_DisplayOverlayparts":
            continue
        mask = _ref(transform, tree.get("m_Father"))
        if mask is None or _source_path(mask) != source:
            continue
        mask_tree = scene.tree(mask)
        mask_game = _ref(mask, mask_tree.get("m_GameObject"))
        head = _ref(mask, mask_tree.get("m_Father"))
        if mask_game is not None and _source_path(mask_game) == source and scene.name(mask_game) == "mesh_mask" and head is not None \
                and heads.get(_key(head)) == source:
            positions[_key(transform)] = BOARD_POSITION
    return positions
