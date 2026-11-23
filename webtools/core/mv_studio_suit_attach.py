"""Suit attach data (m_suit_attach.attach_key) applied like the client's member loader.

A suit with an m_suit_attach row shares its original suit's model bundle and only
names an attach key ("c1" on all 137 GL rows). The model prefab's
BodyPartManager.attachTable (a MemberAttachTable ScriptableObject shipped in a
member_model dependency, ".../characters/attach/<costume>_attach_materialcolor.asset")
maps that key to replacement objects. GL 3.12.0 libil2cpp:

* LiveCoreMember.Initialize (0x2f649d4-0x2f64a54) and CommonCoreMember.Initialize
  (0x27c14f4-0x27c1558): ``if (bodyParts.AttachTable != null)
  ApplyAttachData(bodyParts.AttachTable.GetObject(memberInfo.AttachKeyword))``.
* MemberAttachTable.GetObject (0x27c1d98): the first ``datas`` entry whose
  ``attachName`` compares equal to the key, otherwise null.
* CommonCoreMember.ApplyAttachData (0x27c1edc): only ``attachType == 1``
  (MemberAttachType.MaterialColor). It maps every child renderer's
  ``sharedMaterial.name`` to that material, then for each replace object:

  - ``replaceObject.GetType() == typeof(Texture2D)``: ``Instantiate`` the material
    named ``replaceBindName`` and set its ``mainTexture`` to the replacement (the
    copy also gets ``_RIMLIGHT_ON`` disabled when it has ``_RIMLIGHT`` and
    ``_RimglightIntensity = 0``; the live rim mixer rewrites the intensity every
    frame, so nothing of that survives into a rendered frame);
  - otherwise ``new Material((Material)replaceObject)``;

  and every renderer whose ``sharedMaterial.name`` equals ``replaceBindName``
  draws with the copy.

Every GL costume renderer has one material slot (checked on the sampled attach
models), so replacing by material name here is the same as the client's
``sharedMaterial`` rule. Texture pixels and authored mips are exported unchanged.
"""

import copy

MATERIAL_COLOR = 1  # LLAS.Components.Members.MemberAttachType.MaterialColor


def _script_name(scene, obj):
    from .model_viewer import _ref
    try:
        script = _ref(obj, scene.tree(obj).get("m_Script"))
        return str(script.read().m_ClassName) if script is not None else ""
    except Exception:
        return ""


def _external_id(owner, target):
    """m_FileID that addresses `target`'s serialized file from `owner`'s file."""
    if owner.assets_file is target.assets_file:
        return 0
    wanted = str(getattr(target.assets_file, "name", "")).lower()
    for index, external in enumerate(getattr(owner.assets_file, "externals", ()) or ()):
        path = str(external.path)
        path = path[9:] if path.startswith("archive:/") else path
        if path.rsplit("/")[-1].lower() == wanted:
            return index + 1
    return None


class MemberAttach:
    """Replacement objects selected by one attach key for one member model."""

    def __init__(self, key, table_name, replacements):
        self.key, self.table_name = key, table_name
        self.replacements = replacements  # {bind material name: Texture2D or Material object}

    @classmethod
    def read(cls, scene, key):
        """None when the key is empty or the model has no table / no matching entry."""
        from .model_viewer import _ref
        if not isinstance(key, str) or not key:
            return None
        tables = {}
        for obj in scene.env.objects:
            if obj.type.name != "MonoBehaviour" or _script_name(scene, obj) != "BodyPartManager":
                continue
            table = _ref(obj, scene.tree(obj).get("attachTable"))
            if table is not None:
                tables[(id(table.assets_file), table.path_id)] = table
        if len(tables) != 1:
            if len(tables) > 1:
                scene.warn("member_attach_ambiguous", key)
            return None
        table = next(iter(tables.values()))
        tree = scene.tree(table)
        data = next((entry for entry in tree.get("datas") or () if isinstance(entry, dict)
                     and entry.get("attachName") == key), None)
        if data is None or data.get("attachType") != MATERIAL_COLOR:
            return None
        replacements = {}
        for item in data.get("replaceObjects") or ():
            name = item.get("replaceBindName") if isinstance(item, dict) else None
            target = _ref(table, item.get("replaceObject")) if isinstance(name, str) and name else None
            if target is None or target.type.name not in ("Texture2D", "Material"):
                scene.warn("member_attach_object_unavailable", name or "")
                continue
            # The client replaces a renderer's material once: the copy is no longer
            # named replaceBindName, so a repeated bind name never matches again.
            replacements.setdefault(name, target)
        return cls(key, str(tree.get("m_Name", "")), replacements) if replacements else None

    def material(self, scene, obj, tree):
        """The (material object, typetree) the member draws instead of `obj`."""
        target = self.replacements.get(str(tree.get("m_Name", "")))
        if target is None:
            return obj, tree
        if target.type.name == "Material":
            return target, scene.tree(target)
        file_id = _external_id(obj, target)
        if file_id is None:
            scene.warn("member_attach_object_unavailable", str(tree.get("m_Name", "")))
            return obj, tree
        replaced = copy.deepcopy(tree)
        envs = replaced.setdefault("m_SavedProperties", {}).setdefault("m_TexEnvs", [])
        for entry in envs:
            if isinstance(entry, (list, tuple)) and len(entry) == 2 and entry[0] == "_MainTex":
                entry[1]["m_Texture"] = {"m_FileID": file_id, "m_PathID": target.path_id}
                break
        else:
            envs.append(["_MainTex", {"m_Texture": {"m_FileID": file_id, "m_PathID": target.path_id},
                                      "m_Scale": {"x": 1, "y": 1}, "m_Offset": {"x": 0, "y": 0}}])
        return obj, replaced

    def describe(self):
        return {"key": self.key, "table": self.table_name,
                "materials": sorted(self.replacements),
                "objects": {name: target.type.name for name, target in sorted(self.replacements.items())}}
