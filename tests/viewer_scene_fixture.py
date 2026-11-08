"""Original neutral weighted UnityFS rigs; no game assets are included."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import struct

import UnityPy
from UnityPy.enums import ClassIDType
from UnityPy.helpers.Tpk import get_typetree_node
from UnityPy.helpers.TypeTreeNode import TypeTreeNode


def _defaults(node):
    if node.m_Type == "string": return ""
    if node.m_Type == "TypelessData": return b""
    if node.m_Children and node.m_Children[0].m_Type == "Array": return []
    if node.m_Type == "bool": return False
    if node.m_Type in ("float", "double"): return 0.0
    if node.m_Children: return {child.m_Name: _defaults(child) for child in node.m_Children}
    return 0


def _copy_typetree(node):
    # Native Boost nodes cannot be pickled/deepcopied. from_list creates new
    # nodes, but each dictionary must omit the original cached child list.
    return TypeTreeNode.from_list([{key: value for key, value in row.items() if key != "m_Children"}
                                   for row in node.to_dict_list()])


def bundle_fixture(platform=13, variant="primary", *, unit_breast=False):
    here = Path(__file__).parent
    spec = importlib.util.spec_from_file_location("scene_body_generator", here / "generate_viewer_body_fixture.py")
    generator = importlib.util.module_from_spec(spec); spec.loader.exec_module(generator)
    generator.BONES += (("BreastSize", "Spine2", (.1, .2, .02), (0, 0, 0),
                         (.61, .91, .85) if variant == "primary" and not unit_breast else (1, 1, 1)),)
    env = UnityPy.load(generator.fixture_bytes())
    asset = env.file
    asset.target_platform = platform; asset._m_target_platform = platform
    names, streams = {}, b""
    for obj in list(env.objects):
        tree = obj.read_typetree()
        if obj.type.name == "GameObject": names[obj.path_id] = tree["m_Name"]
        if obj.type.name == "Texture2D":
            tree["m_Name"] = "ch9999_co0001_body" if variant == "primary" else "ch0209_co0001_body"
            obj.save_typetree(tree)
    transforms = {}
    for obj in list(env.objects):
        tree = obj.read_typetree()
        if obj.type.name == "Transform": transforms[names[tree["m_GameObject"]["m_PathID"]]] = obj
    component = next(obj for obj in env.objects if obj.type.name == "MonoBehaviour")
    tree = component.read_typetree()
    tree["scaleValues"] = [{"target": {"m_FileID": 0, "m_PathID": transforms[name].path_id},
                            "originValue": transforms[name].read_typetree()["m_LocalScale"],
                            "scaledValue": transforms[name].read_typetree()["m_LocalScale"]}
                           for name in ("BreastSize", "HipsSize")]
    component.save_typetree(tree)
    node = _copy_typetree(get_typetree_node(142, asset.version))
    for index, part in enumerate(node.traverse()):
        for field in ("m_TypeFlags", "m_MetaFlag", "m_RefTypeHash"):
            if getattr(part, field, None) is None: setattr(part, field, 0)
        if part.m_Index is None: part.m_Index = index
    serialized = copy.copy(asset.types[0]); serialized.class_id = 142; serialized.node = node
    serialized.script_type_index = -1; serialized.script_id = None; serialized.old_type_hash = bytes(16)
    asset.types.append(serialized)
    reader = copy.copy(next(iter(asset.objects.values())))
    reader.path_id = 9999; reader.type_id = len(asset.types) - 1; reader.serialized_type = serialized
    reader.class_id = 142; reader.type = ClassIDType.AssetBundle
    tree = _defaults(node)
    tree.update(m_Name="neutral_" + str(platform) + variant, m_AssetBundleName="neutral_" + str(platform) + variant,
                m_Dependencies=[], m_PreloadTable=[{"m_FileID": 0, "m_PathID": 2}],
                m_Container=[("assets/fixtures/character.prefab", {"preloadIndex": 0, "preloadSize": 1,
                              "asset": {"m_FileID": 0, "m_PathID": 2}})])
    reader.save_typetree(tree); asset.objects[reader.path_id] = reader
    cab = "CAB-" + hashlib.sha256((str(platform) + variant).encode()).hexdigest()[:32]
    entries = [(cab, asset.save()), (cab + ".resS", b"original-neutral-stream-bytes")]
    payload = b"".join(raw for _, raw in entries)
    info = bytes(16) + struct.pack(">iIIHi", 1, len(payload), len(payload), 0, len(entries))
    offset = 0
    for name, raw in entries:
        info += struct.pack(">qqI", offset, len(raw), 0) + name.encode() + b"\0"; offset += len(raw)
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + asset.unity_version.encode() + b"\0"
    return prefix + struct.pack(">QIII", len(prefix) + 20 + len(info) + len(payload), len(info), len(info), 64) + info + payload
