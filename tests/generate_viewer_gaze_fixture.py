"""Neutral source physics ribbon plus original-format synthetic iris-pose clips.

No game assets. Existing persistence/physics fixtures and their pixel contracts
are unchanged. Eye joints are real skin joints with zero weights in this ribbon;
native QA must assert their transforms, not claim visible pupil pixel motion.
"""
import copy


def fixture_bytes():
    import UnityPy
    from generate_viewer_physics_fixture import fixture_bytes as physics_fixture
    env = UnityPy.load(physics_fixture(native=True))
    objects = {obj.path_id: obj for obj in env.objects}
    asset = objects[1].assets_file
    ptr = lambda ident: {"m_FileID": 0, "m_PathID": ident}
    definitions = [(500, 501, "Head_Face", 3, [503, 507], (0., 1., 0.)),
                   (502, 503, "LeftEye1", 501, [505], (.03, 0., .02)),
                   (504, 505, "LeftEye2", 503, [], (0., 0., 0.)),
                   (506, 507, "RightEye1", 501, [509], (-.03, 0., .02)),
                   (508, 509, "RightEye2", 507, [], (0., 0., 0.))]
    for game_id, transform_id, name, parent, children, position in definitions:
        game, transform = copy.copy(objects[8]), copy.copy(objects[9])
        game.path_id, transform.path_id = game_id, transform_id
        gt, tt = copy.deepcopy(objects[8].read_typetree()), copy.deepcopy(objects[9].read_typetree())
        gt.update(m_Name=name, m_Component=[{"component": ptr(transform_id)}], m_IsActive=True)
        tt.update(m_GameObject=ptr(game_id), m_Father=ptr(parent), m_Children=[ptr(child) for child in children],
                  m_LocalPosition=dict(zip("xyz", position)), m_LocalScale=dict.fromkeys("xyz", 1.),
                  m_LocalRotation={"x": 0., "y": 0., "z": 0., "w": 1.})
        asset.objects[game_id], asset.objects[transform_id] = game, transform
        game.save_typetree(gt); transform.save_typetree(tt)
    root = objects[3].read_typetree(); root["m_Children"].append(ptr(501)); objects[3].save_typetree(root)
    renderer, mesh = objects[12].read_typetree(), objects[1].read_typetree()
    for _, transform_id, _, _, _, position in definitions:
        renderer["m_Bones"].append(ptr(transform_id))
        inverse = copy.deepcopy(mesh["m_BindPose"][0])
        world = position if transform_id == 501 else ((.03 if transform_id in (503, 505) else -.03), 1., .02)
        inverse.update(e03=-world[0], e13=-world[1], e23=-world[2]); mesh["m_BindPose"].append(inverse)
    objects[12].save_typetree(renderer); objects[1].save_typetree(mesh)
    original = objects[15].read_typetree()
    for direction, delta in ((6, (.015, 0.)), (7, (-.015, 0.)), (8, (0., .012)), (9, (0., -.012)),
                             (10, (.012, .01)), (11, (-.012, .01))):
        animation = copy.copy(objects[15]); animation.path_id = 600 + direction
        tree = copy.deepcopy(original); tree["m_Name"] = "ch0001_LiveFacial_eye_%03d" % direction
        tree.update(m_RotationCurves=[], m_CompressedRotationCurves=[], m_EulerCurves=[], m_ScaleCurves=[],
                    m_FloatCurves=[], m_PPtrCurves=[], m_Events=[], m_PositionCurves=[])
        for side, offset in (("Left", .03), ("Right", -.03)):
            for index in (1, 2):
                curve = copy.deepcopy(original["m_ScaleCurves"][0])
                curve["path"] = "Head_Face/%sEye1" % side + ("/%sEye2" % side if index == 2 else "")
                value = (offset + delta[0], delta[1], .02) if index == 1 else (0., 0., 0.)
                for key in curve["curve"]["m_Curve"]:
                    key["value"] = dict(zip("xyz", value))
                    for slope in ("inSlope", "outSlope"):
                        key[slope] = dict.fromkeys("xyz", 0.)
                tree["m_PositionCurves"].append(curve)
        asset.objects[animation.path_id] = animation; animation.save_typetree(tree)
    return env.file.save(packer="original")


if __name__ == "__main__":
    import sys
    from pathlib import Path
    destination = Path(sys.argv[1]); destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(fixture_bytes())
