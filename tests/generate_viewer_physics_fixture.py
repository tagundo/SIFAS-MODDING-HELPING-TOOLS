"""Original neutral rig with serialized SwingBone and capsule collider fields."""
import copy
from pathlib import Path


def fixture_bytes(*, manager_membership=False):
    import UnityPy
    from UnityPy.helpers.TypeTreeNode import TypeTreeNode
    source = Path(__file__).parent / "fixtures" / "viewer_persistence.unity"
    env = UnityPy.load(source.read_bytes())
    objects = {obj.path_id: obj for obj in env.objects}
    asset = objects[16].assets_file
    def ptr(ident):
        return {"m_FileID": 0, "m_PathID": ident}
    def vector(name):
        return TypeTreeNode(m_Level=1, m_Type="Vector3f", m_Name=name, m_ByteSize=12, m_Index=0, m_TypeFlags=0,
            m_Version=1, m_MetaFlag=0, m_Children=[TypeTreeNode(m_Level=2, m_Type="float", m_Name=a,
                m_ByteSize=4, m_Version=1, m_MetaFlag=0, m_Index=0, m_TypeFlags=0) for a in "xyz"])
    def scalar(name):
        return TypeTreeNode(m_Level=1, m_Type="float", m_Name=name, m_ByteSize=4, m_Version=1, m_MetaFlag=0, m_Index=0, m_TypeFlags=0)
    def integer(name):
        node = scalar(name); node.m_Type = "int"; return node
    go, transform = copy.copy(objects[8]), copy.copy(objects[9])
    go.path_id, transform.path_id = 200, 201
    gt, tt = objects[8].read_typetree(), objects[9].read_typetree()
    gt.update(m_Name="LeftBreast_Dyna", m_Component=[{"component": ptr(201)}, {"component": ptr(221)}])
    tt.update(m_GameObject=ptr(200), m_Father=ptr(9), m_Children=[ptr(209), ptr(211)],
              m_LocalPosition={"x": 0., "y": .1, "z": 0.}, m_LocalRotation={"x": 0., "y": 0., "z": 0., "w": 1.})
    asset.objects[200], asset.objects[201] = go, transform
    go.save_typetree(gt); transform.save_typetree(tt)
    parent = objects[9].read_typetree(); parent["m_Children"].append(ptr(201)); objects[9].save_typetree(parent)
    for game_id, transform_id, name, position in [(208, 209, "DecoyFirstChild", {"x": 0., "y": .3, "z": 0.}),
                                                  (210, 211, "LeftBreast_End_Dyna", {"x": -.08, "y": 0., "z": 0.})]:
        child_go, child_transform = copy.copy(objects[8]), copy.copy(objects[9])
        child_go.path_id, child_transform.path_id = game_id, transform_id
        child_gt, child_tt = objects[8].read_typetree(), objects[9].read_typetree()
        child_gt.update(m_Name=name, m_Component=[{"component": ptr(transform_id)}])
        child_tt.update(m_GameObject=ptr(game_id), m_Father=ptr(201), m_Children=[], m_LocalPosition=position,
                        m_LocalRotation={"x": 0., "y": 0., "z": 0., "w": 1.})
        asset.objects[game_id], asset.objects[transform_id] = child_go, child_transform
        child_go.save_typetree(child_gt); child_transform.save_typetree(child_tt)
    base_children = objects[16].serialized_type.node.m_Children[:4]
    def pointer(name):
        node = base_children[0].__class__(**base_children[0].to_dict()); node.m_Name = name; return node
    def pointers(name):
        node = TypeTreeNode(**next(n for n in objects[9].serialized_type.node.m_Children if n.m_Name == "m_Children").to_dict())
        node.m_Name = name; return node
    for kind, fields, values, game, script_id, component_id in [
        ("SwingBone", [scalar("stiffnessForce"), scalar("dragForce"), vector("lowRotationLimit"), vector("highRotationLimit"),
                       scalar("radius"), pointer("child"), vector("boneAxis"), vector("externalForce"), pointers("colliders")],
         {"stiffnessForce": .02, "dragForce": .3, "lowRotationLimit": dict.fromkeys("xyz", -30.), "highRotationLimit": dict.fromkeys("xyz", 30.),
          "radius": .02, "child": ptr(211), "boneAxis": {"x": -1., "y": 0., "z": 0.},
          "externalForce": {"x": 0., "y": -.001, "z": 0.}, "colliders": [ptr(224)]}, 200, 220, 221),
        ("SwingCollider", [scalar("radius"), vector("offset"), base_children[0].__class__(**{**base_children[0].to_dict(), "m_Name": "sibling"})],
         {"radius": .04, "offset": {"x": 0., "y": .15, "z": 0.}, "sibling": ptr(223)}, 6, 222, 224),
        ("SwingCollider", [scalar("radius"), vector("offset"), base_children[0].__class__(**{**base_children[0].to_dict(), "m_Name": "sibling"})],
         {"radius": .03, "offset": {"x": 0., "y": .3, "z": 0.}, "sibling": ptr(224)}, 6, 222, 223),
        ("SwingBoneManager", [pointers("bones"), pointers("colliders")],
         {"bones": [ptr(221)], "colliders": [ptr(224), ptr(223)]}, 6, 227, 228),
    ]:
        if kind == "SwingBone" and manager_membership:
            fields = [field for field in fields if field.m_Name != "colliders"] + [integer("colliderBits")]
            values.pop("colliders"); values["colliderBits"] = 1
        script = copy.copy(objects[17]); script.path_id = script_id
        st = objects[17].read_typetree(); st.update(m_Name=kind, m_ClassName=kind)
        asset.objects[script_id] = script; script.save_typetree(st)
        serialized = copy.copy(objects[16].serialized_type)
        serialized.node = TypeTreeNode(**{**objects[16].serialized_type.node.to_dict(), "m_Children": base_children + fields})
        serialized.script_type_index = len(asset.types)
        component = copy.copy(objects[16]); component.path_id = component_id
        component.type_id = len(asset.types); component.serialized_type = serialized; asset.types.append(serialized)
        asset.objects[component_id] = component
        component.save_typetree({"m_GameObject": ptr(game), "m_Enabled": 1, "m_Script": ptr(script_id), "m_Name": kind, **values})
    return env.file.save(packer="original")


if __name__ == "__main__":
    import sys
    destination = Path(sys.argv[1]); destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(fixture_bytes())
