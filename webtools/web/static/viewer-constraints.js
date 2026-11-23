/* Unity 2018.4.23f1 RotationConstraint / PositionConstraint, as evaluated by
 * the GL 3.12 player's ConstraintManager (libunity.so, job 0x71b2d4; position
 * case 0x71b47c, rotation case 0x71b658, packing 0x71a0a0 / 0x71a384).
 *
 * - A constraint is evaluated when its Behaviour is enabled, its GameObject is
 *   active in the hierarchy, constraintActive is set and it has sources.
 * - Source weights are divided by their sum. When there is no valid source or
 *   the sum is 0, the target's local value is the at-rest value.
 * - Position: weighted world source position, InverseTransformPoint into the
 *   target's parent, + offset (parent space), lerp from at-rest by weight.
 * - Rotation: source world rotations folded by sign-aligned nlerp (the first
 *   source taken whole), into the parent's space, * Euler(offset), then nlerp
 *   from Euler(at-rest) by weight.
 * - Masked axes keep the current local value (rotation per Euler ZXY axis).
 * - Weight is clamped to [0, 1]. Euler angles are Unity degrees, ZXY order.
 * All math is in Unity space; the glTF scene mirrors X. ConstraintManagerUpdate
 * runs in PreLateUpdate, after the Animator and before every LateUpdate script.
 * The swing bones are not simulated in LateUpdate: LiveCoreMemberManager.Update
 * runs their job (UpdateMultiThread 0x2f6a7b8) and LateUpdate (0x2f6a9a4) only
 * applies AllSafeCorrect, so a swing-bone source holds the local rotation this
 * frame's Update job wrote, unless the Animator owns that property.
 * Not modeled: dependency ordering between constraints (none in the shipped
 * rigs share nodes) and Unity's sign handling for negative-scale ancestors
 * (such a chain is reported and skipped). */
(function (global) {
  'use strict';
  var REST_EPSILON = 1e-30, SOURCE_EPSILON = 1e-6, SCALE_EPSILON = 1e-9;

  function quatMul(a, b) {
    return [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
      a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
      a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
      a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]];
  }
  function conjugate(a) { return [-a[0], -a[1], -a[2], a[3]]; }
  function dot4(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]; }
  function rotate(q, v) { var p = quatMul(quatMul(q, [v[0], v[1], v[2], 0]), conjugate(q)); return [p[0], p[1], p[2]]; }
  function normalize(q) { var n = Math.sqrt(dot4(q, q)); return [q[0] / n, q[1] / n, q[2] / n, q[3] / n]; }
  function nlerp(from, to, t) {
    var sign = dot4(from, to) < 0 ? -1 : 1;
    return normalize([0, 1, 2, 3].map(function (i) { return from[i] + (to[i] * sign - from[i]) * t; }));
  }
  function axisAngle(index, degrees) {
    var half = degrees * Math.PI / 360, q = [0, 0, 0, Math.cos(half)];
    q[index] = Math.sin(half);
    return q;
  }
  // Quaternion.Euler: z degrees about Z, then x about X, then y about Y.
  function euler(angles) { return quatMul(quatMul(axisAngle(1, angles[1]), axisAngle(0, angles[0])), axisAngle(2, angles[2])); }
  // Inverse of euler() for the per-axis selection, in degrees.
  function toEuler(q) {
    var x = q[0], y = q[1], z = q[2], w = q[3];
    var m00 = 1 - 2 * (y * y + z * z), m02 = 2 * (x * z + w * y), m10 = 2 * (x * y + w * z), m11 = 1 - 2 * (x * x + z * z);
    var m12 = 2 * (y * z - w * x), m20 = 2 * (x * z - w * y), m22 = 1 - 2 * (x * x + y * y);
    var sx = Math.max(-1, Math.min(1, -m12)), degrees = 180 / Math.PI;
    if (Math.abs(sx) < 1 - 1e-6) return [Math.asin(sx) * degrees, Math.atan2(m02, m22) * degrees, Math.atan2(m10, m11) * degrees];
    return [Math.asin(sx) * degrees, Math.atan2(-m20, m00) * degrees, 0];
  }
  function clamp01(value) { return Math.max(0, Math.min(1, value)); }

  function chain(node) { var nodes = []; while (node) { nodes.push(node); node = node.parent; } return nodes.reverse(); }
  // Unity TransformHierarchy composition: position = parent position +
  // parent rotation * (parent scale * local position).
  function world(node, local) {
    var position = [0, 0, 0], rotation = [0, 0, 0, 1], scale = [1, 1, 1];
    chain(node).forEach(function (item) {
      var row = local(item), offset = rotate(rotation, [scale[0] * row.p[0], scale[1] * row.p[1], scale[2] * row.p[2]]);
      position = [position[0] + offset[0], position[1] + offset[1], position[2] + offset[2]];
      rotation = quatMul(rotation, row.r);
      scale = [scale[0] * row.s[0], scale[1] * row.s[1], scale[2] * row.s[2]];
    });
    return { position: position, rotation: rotation };
  }
  // TransformHierarchy InverseTransformPoint / InverseTransformRotation into
  // `parent`'s space, applied from the root down as the native recursion does.
  function inversePoint(parent, point, local) {
    var p = point.slice();
    chain(parent).forEach(function (item) {
      var row = local(item), d = rotate(conjugate(row.r), [p[0] - row.p[0], p[1] - row.p[1], p[2] - row.p[2]]);
      p = d.map(function (value, i) { return Math.abs(row.s[i]) < SCALE_EPSILON ? 0 : value / row.s[i]; });
    });
    return p;
  }
  function inverseRotation(parent, rotation, local) {
    var q = rotation;
    chain(parent).forEach(function (item) { q = quatMul(conjugate(local(item).r), q); });
    return q;
  }

  // One constraint in Unity space. `sources` holds [{ position, rotation, weight }]
  // for valid source transforms; `current` is the target's local { p, r }.
  function solve(constraint, sources, current, parent, local) {
    var total = sources.reduce(function (sum, row) { return sum + row.weight; }, 0);
    var rest = constraint.atRest, weight = clamp01(constraint.weight), axes = constraint.axes;
    if (constraint.kind === 'position') {
      if (!sources.length || total === 0) return { position: rest.slice() };
      var sum = [0, 0, 0];
      sources.forEach(function (row) { for (var i = 0; i < 3; i++) sum[i] += row.position[i] * (row.weight / total); });
      var target = parent ? inversePoint(parent, sum, local) : sum;
      return { position: [0, 1, 2].map(function (i) {
        var value = rest[i] + (target[i] + constraint.offset[i] - rest[i]) * weight;
        return axes[i] ? value : current.p[i];
      }) };
    }
    if (!sources.length || total === 0) return { rotation: euler(rest) };
    var accumulated = [0, 0, 0, 1], first = true;
    sources.forEach(function (row) {
      var share = row.weight / total;
      if (share < SOURCE_EPSILON) return;
      accumulated = nlerp(accumulated, row.rotation, first ? 1 : share);
      first = false;
    });
    accumulated = dot4(accumulated, accumulated) > REST_EPSILON ? normalize(accumulated) : [0, 0, 0, 1];
    var constrained = quatMul(parent ? inverseRotation(parent, accumulated, local) : accumulated, euler(constraint.offset));
    var blended = nlerp(euler(rest), constrained, weight);
    if (axes[0] && axes[1] && axes[2]) return { rotation: blended };
    var chosen = toEuler(blended), kept = toEuler(current.r);
    return { rotation: normalize(euler([0, 1, 2].map(function (i) { return axes[i] ? chosen[i] : kept[i]; }))) };
  }

  function evaluable(row) {
    return row && (row.kind === 'position' || row.kind === 'rotation') && row.enabled !== false &&
      row.activeInHierarchy !== false && row.constraintActive === true && Array.isArray(row.sources) && row.sources.length > 0;
  }
  function vector(value) { return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite); }

  function create(root, catalog) {
    if (!catalog || !Array.isArray(catalog.constraints)) return null;
    var nodes = new Map();
    root.traverse(function (node) {
      var id = node.userData && node.userData.elichika_node;
      if (!(node.userData && node.userData.viewerHelper) && Number.isInteger(id)) nodes.set(id, nodes.has(id) ? null : node);
    });
    var entries = [], skipped = [];
    catalog.constraints.forEach(function (row) {
      if (!evaluable(row)) return;
      var target = nodes.get(row.node);
      if (!target || !vector(row.atRest) || !vector(row.offset) || !Number.isFinite(row.weight) ||
          !Array.isArray(row.axes) || row.axes.length !== 3) { skipped.push(row.id + ':unbound'); return; }
      // A missing source transform is dropped from the job, as in the player.
      var sources = row.sources.map(function (source) {
        var object = Number.isInteger(source.node) ? nodes.get(source.node) : null;
        return object && Number.isFinite(source.weight) ? { object: object, weight: source.weight } : null;
      }).filter(Boolean);
      entries.push({ row: row, target: target, sources: sources,
        rest: { position: target.position.clone(), quaternion: target.quaternion.clone() } });
    });
    if (!entries.length) return null;
    var applied = false, evaluated = 0, unsupported = [];

    function restorePose() {
      if (!applied) return;
      entries.forEach(function (entry) {
        entry.target.position.copy(entry.rest.position);
        entry.target.quaternion.copy(entry.rest.quaternion);
        if (entry.target.matrixAutoUpdate === false) entry.target.updateMatrix();
      });
      applied = false;
    }

    // simulated: Map(node id -> { position, quaternion }) of the swing-bone
    // local pose the transforms hold at ConstraintManagerUpdate (the caller's
    // physics simulatedPose()); animated(): properties the Animator owns now.
    function apply(simulated, animated) {
      var owned = null;
      function animatedNow() { if (!owned) owned = (animated && animated()) || {}; return owned; }
      function local(node) {
        var id = node.userData && node.userData.elichika_node, position = node.position, quaternion = node.quaternion;
        var row = simulated && Number.isInteger(id) ? simulated.get(id) : null;
        if (row) {
          var claim = animatedNow()[String(id)] || {};
          if (row.quaternion && !claim.quaternion) quaternion = row.quaternion;
          if (row.position && !claim.position) position = row.position;
        }
        return { p: [-position.x, position.y, position.z], r: [quaternion.x, -quaternion.y, -quaternion.z, quaternion.w],
          s: [node.scale.x, node.scale.y, node.scale.z] };
      }
      function negative(node) { return chain(node).some(function (item) { return item.scale.x < 0 || item.scale.y < 0 || item.scale.z < 0; }); }
      var results = [];
      evaluated = 0; unsupported = [];
      entries.forEach(function (entry) {
        if (negative(entry.target) || entry.sources.some(function (source) { return negative(source.object); })) {
          unsupported.push(entry.row.id + ':negative-scale');
          return;
        }
        var sources = entry.sources.map(function (source) {
          var pose = world(source.object, local);
          return { position: pose.position, rotation: pose.rotation, weight: source.weight };
        });
        var current = local(entry.target);
        results.push({ entry: entry, value: solve(entry.row, sources, current, entry.target.parent, local) });
      });
      // One job reads every input before the manager writes the results back.
      results.forEach(function (result) {
        var target = result.entry.target, value = result.value;
        if (value.position) target.position.set(-value.position[0], value.position[1], value.position[2]);
        if (value.rotation) {
          var q = normalize(value.rotation);
          target.quaternion.set(q[0], -q[1], -q[2], q[3]);
        }
        if (target.matrixAutoUpdate === false) target.updateMatrix();
        evaluated++;
      });
      if (results.length) { applied = true; root.updateMatrixWorld(true); }
    }

    function getState() {
      return { constraints: entries.length, evaluated: evaluated, skipped: skipped.slice(), unsupported: unsupported.slice(),
        targets: entries.map(function (entry) { return { id: entry.row.id, kind: entry.row.kind, node: entry.row.node, name: entry.row.name }; }) };
    }
    function dispose() { restorePose(); entries = []; }
    return { apply: apply, restorePose: restorePose, getState: getState, dispose: dispose };
  }

  global.ViewerConstraints = { create: create,
    reference: { solve: solve, euler: euler, toEuler: toEuler, quatMul: quatMul, rotate: rotate, nlerp: nlerp, world: world,
      inversePoint: inversePoint, inverseRotation: inverseRotation } };
}(typeof window !== 'undefined' ? window : globalThis));
