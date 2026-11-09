"""Measure real browser snapshots with independent finite-triangle geometry."""
import argparse
import json
from pathlib import Path
import numpy as np
from physics_collision_oracle import triangle_capsule_clearance, point_capsule_clearance


def measure(snapshot):
    triangles = np.asarray(snapshot['triangles'], float)
    solver = snapshot['solver']; components = {c['id']: c for c in snapshot['components']}
    skirt_bones = [b for b in solver['bones'] if 'skirt' in components.get(b['id'], {}).get('name', '').lower()]
    wanted = {ident for bone in skirt_bones for ident in bone['colliders']}
    capsules = [c for c in solver['capsules'] if c['id'] in wanted]
    summaries, all_gap = [], []
    for capsule in capsules:
        ra, rb = capsule.get('radiusA', capsule.get('ra')), capsule.get('radiusB', capsule.get('rb'))
        gaps = triangle_capsule_clearance(triangles, capsule['a'], capsule['b'], ra, rb)
        order = np.argsort(gaps)[:5]
        summaries.append({'id': capsule['id'], 'name': components.get(capsule['id'], {}).get('name'),
            'minimumGap': float(gaps.min()), 'penetratingTriangles': int((gaps < -.0001).sum()),
            'deepest': [{'triangle': snapshot['triangleIds'][int(i)], 'gap': float(gaps[i]), 'positions': triangles[int(i)].tolist()} for i in order if gaps[i] < -.0001]})
        all_gap.append(gaps)
    tips = []
    by_id = {c['id']: c for c in capsules}
    for bone in skirt_bones:
        gaps = [point_capsule_clearance([bone['tip']], by_id[i]['a'], by_id[i]['b'],
            by_id[i].get('radiusA', by_id[i].get('ra')), by_id[i].get('radiusB', by_id[i].get('rb')), bone['radius'])[0]
            for i in bone['colliders'] if i in by_id]
        tips.append({'id': bone['id'], 'name': components.get(bone['id'], {}).get('name'), 'minimumGap': float(min(gaps)) if gaps else None})
    minimum = np.min(all_gap, axis=0) if all_gap else np.zeros(len(triangles))
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1) / 2
    depth = np.maximum(0, -minimum)
    def region(mask):
        if not np.any(mask):
            return {'triangles': 0, 'minimumGap': None, 'penetratingTriangles': 0, 'surfaceDepthIntegral': 0.}
        return {'triangles': int(mask.sum()), 'minimumGap': float(minimum[mask].min()),
            'penetratingTriangles': int((minimum[mask] < -.0001).sum()), 'surfaceDepthIntegral': float(np.sum(depth[mask] * area[mask]))}
    influences = np.asarray([t.get('swingWeights', [0, 0, 0]) for t in snapshot['triangleIds']])
    fully_mobile = np.min(influences, axis=1) >= .5
    fixed_corner = np.min(influences, axis=1) < 1e-6
    return {'name': snapshot['name'], 'time': snapshot['time'], 'mode': snapshot['mode'],
        'triangles': len(triangles), 'minimumGap': float(minimum.min()), 'penetratingTriangles': int((minimum < -.0001).sum()),
        'fullyMobile': region(fully_mobile), 'fixedCornerAttachments': region(fixed_corner),
        'surfaceDepthIntegral': float(np.sum(depth * area)), 'maxDepth': float(depth.max()), 'capsules': summaries,
        'tips': tips, 'solver': {key: value for key, value in solver.items() if key not in ('bones', 'capsules')}}


def limit_violations(snapshot, baseline):
    import math
    def rotation(quaternion):
        x, y, z, w = quaternion
        return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
            [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
            [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
    out = []; mirror = np.diag([-1, 1, 1])
    for component in snapshot.get('catalog', {}).get('components', []):
        if component['kind'] != 'bone' or 'skirt' not in component['name'].lower():
            continue
        key = str(component['node']); authored = baseline['nodeFrames'].get(key); actual = snapshot['nodeFrames'].get(key)
        if not authored or not actual:
            continue
        relative = mirror @ rotation(authored['quaternion']).T @ rotation(actual['quaternion']) @ mirror
        x = math.asin(max(-1., min(1., -relative[1, 2])))
        euler = np.degrees([x, math.atan2(relative[0, 2], relative[2, 2]), math.atan2(relative[1, 0], relative[1, 1])])
        lo, hi = component['values']['lowRotationLimit'], component['values']['highRotationLimit']
        if any(value < a - .001 or value > b + .001 for value, a, b in zip(euler, lo, hi)):
            out.append({'name': component['name'], 'actualUnityEuler': euler.tolist(), 'low': lo, 'high': hi})
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('capture'); parser.add_argument('--output'); args = parser.parse_args()
    snapshots = json.loads(Path(args.capture).read_text()); reports = [measure(row) for row in snapshots]
    for row, report in zip(snapshots, reports):
        baseline = next((other for other in snapshots if other['time'] == row['time'] and other['mode'] == 'disabled'), row)
        report['rotationLimitViolations'] = limit_violations(row, baseline)
    text = json.dumps(reports, indent=2)
    if args.output:
        Path(args.output).write_text(text)
    else:
        print(text)
