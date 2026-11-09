"""Original neutral rig with serialized SwingBone and capsule collider fields."""
import copy
from pathlib import Path


def fixture_bytes():
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
    go, transform = copy.copy(objects[8]), copy.copy(objects[9])
    go.path_id, transform.path_id = 200, 201
    gt, tt = objects[8].read_typetree(), objects[9].read_typetree()
    gt.update(m_Name="LeftBreast_Dyna", m_Component=[{"component": ptr(201)}, {"component": ptr(221)}])
    tt.update(m_GameObject=ptr(200), m_Father=ptr(9), m_Children=[],
              m_LocalPosition={"x": 0., "y": .1, "z": 0.}, m_LocalRotation={"x": 0., "y": 0., "z": 0., "w": 1.})
    asset.objects[200], asset.objects[201] = go, transform
    go.save_typetree(gt); transform.save_typetree(tt)
    parent = objects[9].read_typetree(); parent["m_Children"].append(ptr(201)); objects[9].save_typetree(parent)
    base_children = objects[16].serialized_type.node.m_Children[:4]
    for kind, fields, values, game, script_id, component_id in [
        ("SwingBone", [scalar("stiffnessForce"), scalar("dragForce"), vector("lowRotationLimit"), vector("highRotationLimit")],
         {"stiffnessForce": .02, "dragForce": .3, "lowRotationLimit": dict.fromkeys("xyz", -30.), "highRotationLimit": dict.fromkeys("xyz", 30.)}, 200, 220, 221),
        ("SwingCollider", [scalar("radius"), vector("offset"), base_children[0].__class__(**{**base_children[0].to_dict(), "m_Name": "sibling"})],
         {"radius": .04, "offset": {"x": 0., "y": .15, "z": 0.}, "sibling": ptr(223)}, 6, 222, 224),
        ("SwingCollider", [scalar("radius"), vector("offset"), base_children[0].__class__(**{**base_children[0].to_dict(), "m_Name": "sibling"})],
         {"radius": .03, "offset": {"x": 0., "y": .3, "z": 0.}, "sibling": ptr(224)}, 6, 222, 223),
    ]:
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
