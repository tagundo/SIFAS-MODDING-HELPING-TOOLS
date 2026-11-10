/* Original SIFAS GL3.12 SwingBone runtime. Proven native entrypoints and fixtures
 * are listed in tests/fixtures/game_physics_native_jobs.json. No mesh repair is
 * applied by this engine. Transform sampling is owned by its Three adapter. */
(function (global) {
  'use strict';
  var F = Math.fround;
  function v(a) { return [F(a[0]), F(a[1]), F(a[2])]; }
  function q(a) { return [F(a[0]), F(a[1]), F(a[2]), F(a[3])]; }
  function add(a, b) { return [F(a[0] + b[0]), F(a[1] + b[1]), F(a[2] + b[2])]; }
  function sub(a, b) { return [F(a[0] - b[0]), F(a[1] - b[1]), F(a[2] - b[2])]; }
  function mul(a, b) { b = F(b); return [F(a[0] * b), F(a[1] * b), F(a[2] * b)]; }
  function dot(a, b) { return F(F(F(a[0] * b[0]) + F(a[1] * b[1])) + F(a[2] * b[2])); }
  function length(a) { return F(Math.sqrt(dot(a, a))); }
  function normalize(a) { var n = length(a); return n > F(1e-5) ? [F(a[0] / n), F(a[1] / n), F(a[2] / n)] : [0, 0, 0]; }
  function copy(out, value) { for (var i = 0; i < value.length; i++) out[i] = F(value[i]); return out; }
  function unequal(a, b) { var d = sub(a, b); return !(dot(d, d) < F(9.99999944e-11)); }
  // ARM64 0x40eb6f8, including the actual add/sub grouping.
  function quatMul(a, b) {
    a = q(a); b = q(b);
    return [F(F(F(a[1] * b[2]) + F(F(a[3] * b[0]) + F(a[0] * b[3]))) - F(a[2] * b[1])),
      F(F(F(a[2] * b[0]) + F(F(a[3] * b[1]) + F(a[1] * b[3]))) - F(a[0] * b[2])),
      F(F(F(a[0] * b[1]) + F(F(a[3] * b[2]) + F(a[2] * b[3]))) - F(a[1] * b[0])),
      F(F(F(F(a[3] * b[3]) - F(a[0] * b[0])) - F(a[1] * b[1])) - F(a[2] * b[2]))];
  }
  // ARM64 0x40eb76c: point.x/point.y/point.z are not evaluated in the same
  // associative order in all three output channels.
  function quatRotate(a, p) {
    a = q(a); p = v(p);
    var x = F(a[0] + a[0]), y = F(a[1] + a[1]), z = F(a[2] + a[2]);
    var xx = F(a[0] * x), yy = F(a[1] * y), zz = F(a[2] * z), xy = F(a[0] * y), xz = F(a[0] * z), yz = F(a[1] * z);
    var wx = F(a[3] * x), wy = F(a[3] * y), wz = F(a[3] * z);
    return [F(F(p[2] * F(xz + wy)) + F(F(p[1] * F(xy - wz)) + F(p[0] * F(1 - F(yy + zz))))),
      F(F(p[2] * F(yz - wx)) + F(F(p[0] * F(xy + wz)) + F(p[1] * F(1 - F(xx + zz))))),
      F(F(F(p[0] * F(xz - wy)) + F(p[1] * F(yz + wx))) + F(p[2] * F(1 - F(xx + yy))))];
  }
  function point(m, a) { return [0, 1, 2].map(function (i) { return F(F(F(F(m[i] * a[0]) + F(m[i + 4] * a[1])) + F(m[i + 8] * a[2])) + m[i + 12]); }); }
  function repeat(value, n) { value = F(value); n = F(n); var r = F(value - F(F(Math.floor(F(value / n))) * n)), upper = r > n ? n : r; return r < 0 ? 0 : upper; }
  function deltaAngle(a, b) { var d = repeat(F(F(b) - F(a)), 360); return d > 180 ? F(d + -360) : d; }
  function constraint(angles, base, low, high) { var out = v(angles); for (var i = 0; i < 3; i++) { var d = deltaAngle(base[i], angles[i]); if (d < F(low[i])) out[i] = F(F(base[i]) + F(low[i])); if (d > F(high[i])) out[i] = F(F(base[i]) + F(high[i])); } return out; }
  function stepJob(data, buffers, colliderData, colliderMatrices, options) {
    options = options || {}; var math = options.math || global.ViewerGamePhysicsMath, collision = global.ViewerGamePhysicsCollision;
    if (!math || !collision || !collision.forJob) throw new Error('The original game physics math is unavailable.');
    data = data.map(function (d) { var row = Object.assign({}, d); ['localPosition', 'boneAxis', 'externalForce', 'lowRotationLimit', 'highRotationLimit'].forEach(function (key) { row[key] = v(d[key]); }); row.baseLocalRotation = q(d.baseLocalRotation); ['boneLength', 'radius', 'stiffnessForce', 'dragForce'].forEach(function (key) { row[key] = F(d[key]); }); return row; });
    colliderData = colliderData.map(function (d) { return Object.assign({}, d, { offset: v(d.offset), radius: F(d.radius), siblingRadius: F(d.siblingRadius) }); });
    colliderMatrices = colliderMatrices.map(function (m) { return m.map(F); });
    var group = options.kind === 'group', contacts = 0, jobCollision = collision.forJob({ kind: group ? 'group' : 'single', epsilon: options.epsilon === undefined ? F(1.401298464324817e-45) : F(options.epsilon) });
    var boneStates = data.map(function (d, index) { return { tip: buffers[index].currentTipPosition, pivot: buffers[index].position, length: F(d.boneLength), radius: F(d.radius), sibling: null }; });
    function colliderAt(index, offset) {
      var d = colliderData[index]; if (!d) throw new Error('The original collider index is out of range.');
      var object = { point: point(colliderMatrices[index], d.offset), radius: F(d.radius), sibling: null };
      if (d.siblingIndex >= 0) { var sibling = colliderData[offset + d.siblingIndex]; object.sibling = { point: point(colliderMatrices[offset + d.siblingIndex], sibling.offset), radius: F(d.siblingRadius), sibling: null }; }
      return object;
    }
    data.forEach(function (d, index) {
      var b = buffers[index], boneOffset = group ? d.boneIndex : 0, colliderOffset = group ? d.colliderIndex : 0;
      var parent = d.parentIndex >= 0 ? buffers[boneOffset + d.parentIndex] : null;
      var pivot = parent ? add(parent.position, quatRotate(parent.rotation, d.localPosition)) : v(b.position);
      var reference = quatMul(parent ? parent.rotation : b.parentRotation, d.baseLocalRotation), oldPrevious = v(b.previousTipPosition), oldCurrent = v(b.currentTipPosition);
      copy(b.previousTipPosition, oldCurrent);
      var force = add(add(mul(quatRotate(reference, d.boneAxis), d.stiffnessForce), mul(sub(oldPrevious, oldCurrent), d.dragForce)), d.externalForce);
      var tip = add(pivot, mul(normalize(sub(add(sub(mul(oldCurrent, 2), oldPrevious), force), pivot)), d.boneLength));
      var bone = { tip: tip, pivot: pivot, storedPivot: v(b.position), length: F(d.boneLength), radius: F(d.radius), sibling: d.siblingIndex >= 0 ? boneStates[boneOffset + d.siblingIndex] : null };
      if (options.colliders !== false) {
        var count = group ? d.colliderDataCount : colliderData.length, processed = 0, mask = 1;
        for (var j = 0; j < count && processed < d.colliderCount; j++, mask = (mask << 1) >>> 0) {
          if (!(d.colliderIndexBit & mask)) continue;
          processed++; var col = colliderAt(colliderOffset + j, colliderOffset), hit;
          if (bone.sibling) hit = col.sibling ? jobCollision.capsuleCapsule(bone, col, col.sibling) : jobCollision.capsuleSphere(bone, col);
          else hit = col.sibling ? jobCollision.sphereCapsule(bone, col, col.sibling) : jobCollision.sphereSphere(bone, col);
          if (hit) contacts++;
        }
      }
      var rotation = quatMul(math.fromToRotation(quatRotate(reference, d.boneAxis), sub(tip, pivot)), reference);
      copy(b.rotation, rotation); copy(b.position, pivot); copy(b.currentTipPosition, tip); copy(b.localRotation, d.baseLocalRotation);
      // Native constraints use this frame's captured parentRotation, even if
      // ParentIndex's buffer rotation changed earlier in this same loop.
      var relative = quatMul(math.inverse(b.parentRotation), rotation), angles = math.angles(relative);
      var constrained = constraint(angles, math.angles(d.baseLocalRotation), d.lowRotationLimit, d.highRotationLimit);
      if (unequal(angles, constrained)) {
        copy(b.localRotation, math.euler(constrained)); copy(b.rotation, quatMul(b.parentRotation, b.localRotation));
        var distance = length(sub(pivot, tip));
        copy(b.currentTipPosition, add(pivot, group ? quatRotate(b.rotation, mul(d.boneAxis, distance)) : mul(quatRotate(b.rotation, d.boneAxis), distance)));
      }
    });
    return { contacts: contacts, nativeSteps: 1 };
  }
  // Scene adapter follows below. Pure buffers are also exported for independent
  // comparisons with original ARM64 execution, without WebGL or a DOM.
  function classify(name) {
    if (name.indexOf('Skirt') < 0 || name.indexOf('2_Dyna') >= 0) return 0;
    if (name.indexOf('SkirtA1_Dyna') === 0) return 7;
    if (name.indexOf('SkirtE1_Dyna') === 0) return 3;
    if (['LeftSkirtB1_Dyna', 'LeftSkirtC1_Dyna', 'LeftSkirtD1_Dyna'].some(function (prefix) { return name.indexOf(prefix) === 0; })) return 1;
    if (['RightSkirtB1_Dyna', 'RightSkirtC1_Dyna', 'RightSkirtD1_Dyna'].some(function (prefix) { return name.indexOf(prefix) === 0; })) return 2;
    return 0;
  }
  function matrixMul(a, b) {
    var out = new Array(16);
    for (var col = 0; col < 4; col++) for (var row = 0; row < 4; row++) out[col * 4 + row] = F(F(F(F(a[row] * b[col * 4]) + F(a[row + 4] * b[col * 4 + 1])) + F(a[row + 8] * b[col * 4 + 2])) + F(a[row + 12] * b[col * 4 + 3]));
    return out;
  }
  function rotationMatrix(rotation) { var x = quatRotate(rotation, [1, 0, 0]), y = quatRotate(rotation, [0, 1, 0]), z = quatRotate(rotation, [0, 0, 1]); return [x[0], x[1], x[2], 0, y[0], y[1], y[2], 0, z[0], z[1], z[2], 0, 0, 0, 0, 1]; }
  function inverseMatrix(m, THREE) { return new THREE.Matrix4().fromArray(m).invert().elements.map(F); }
  function safeCorrect(state, kneeL, kneeR, force, math, THREE) {
    if (!state.hasTrans || !state.skirtData || !state.skirtSafeEnable) return false;
    var amount = 1;
    if (state.skirtData & 1) amount = Math.min(1, dot(state.parentForward, kneeL));
    if (state.skirtData & 2) amount = Math.min(amount, dot(state.parentForward, kneeR));
    var low = F(state.skirtLimitDotMin), high = F(state.skirtLimitDotMax), ratio = low !== high ? Math.min(1, Math.max(0, F(F(amount - low) / F(high - low)))) : 0;
    state.skirtRotRatio = F(1 - ratio);
    var matrix = matrixMul(state.parentMatrix, rotationMatrix(math.euler([0, F(state.skirtRotDegMax * state.skirtRotRatio), 0])));
    var child = point(inverseMatrix(matrix, THREE), state.childPosition), offset = force ? state.kneeSpaceOffsetForce : state.skirtData & 4 ? state.kneeSpaceOffsetFront : state.kneeSpaceOffsetOther;
    var cutoff = F(F(offset) * state.skirtRotRatio);
    if (!(child[2] < cutoff)) return false;
    child[0] = F(-state.length); child[2] = cutoff;
    var target = point(matrix, mul(normalize(child), state.length));
    state.rotation = quatMul(math.fromToRotation(quatRotate(state.rotation, state.boneAxis), sub(target, state.pivot)), state.rotation);
    state.childPosition = target; state.safeCorrectAdjust = true; return true;
  }
  function catalogReadiness(catalog) {
    var native = catalog && catalog.native, managers = catalog && catalog.managers || [];
    var reasons = native && Array.isArray(native.missing) ? native.missing.slice() : native && native.available === true ? [] : ['native-catalog'];
    if (!native || native.available !== true && !reasons.length) reasons.push('native-catalog');
    var missing = [], skirt = [];
    reasons.forEach(function (reason) {
      // Only this explicitly identified serialized field is optional for the
      // native core. Every other constructor/graph diagnostic remains fatal.
      var manager = managers.filter(function (row) { return typeof row.id === 'string' && reason === row.id + ':kneeTransforms'; })[0];
      var target = manager ? skirt : missing, value = manager ? 'source-knee-transforms:' + manager.sourceIndex : reason;
      if (target.indexOf(value) < 0) target.push(value);
    });
    return { coreAvailable: !missing.length, missing: missing, skirtCorrectionMissing: skirt };
  }
  function create(root, catalog, current, options) {
    options = options || {}; var THREE = global.THREE, math = global.ViewerGamePhysicsMath, nodes = {}, records = {}, managers = [], baseCache = {}, buffers = [], data = [], colliders = [], matrices = [], entries = [], captured = null, context = {}, output = {}, initialized = false, pending = true, pendingBase = true, disposed = false, signature = '', restSignature = '', startupCorrection = false, profile = 'navi', missing = [], skirtCorrectionMissing = [], configuredCorrectionMissing = [];
    var stats = { mode: 'game', profile: profile, nativeSteps: 0, totalNativeSteps: 0, resets: 0, initializationGeneration: 0, dynamicGeneration: 0, contacts: 0, safeCorrections: 0, delta: 0, substeps: 0, frameMs: 0 };
    function helper(o) { while (o) { if (o.userData && o.userData.viewerHelper) return true; o = o.parent; } return false; }
    root.traverse(function (o) { if (!helper(o) && o.userData && o.userData.elichika_node !== undefined) nodes[String(o.userData.elichika_node)] = o; });
    (catalog.components || []).forEach(function (r) { records[r.id] = r; });
    function mirrored(a) { return [-a[0], a[1], a[2]]; }
    function unityPosition(o) { return v(mirrored(o.getWorldPosition(new THREE.Vector3()).toArray())); }
    function unityRotation(o) { var chain = [], result = [0, 0, 0, 1]; while (o) { chain.push(o); o = o.parent; } for (var i = chain.length - 1; i >= 0; i--) result = quatMul(result, unityLocalRotation(chain[i])); return result; }
    function unityLocalRotation(o) { return q([o.quaternion.x, -o.quaternion.y, -o.quaternion.z, o.quaternion.w]); }
    function unityMatrix(o) { return o.matrixWorld.elements.map(function (value, index) { return F(value * ((index % 4 === 0) !== (index < 4) ? -1 : 1)); }); }
    function snapshot() { var pose = {}; Object.keys(nodes).forEach(function (id) { var o = nodes[id]; pose[id] = { position: o.position.toArray(), quaternion: o.quaternion.toArray(), scale: o.scale.toArray(), matrix: o.matrix.toArray(), matrixAutoUpdate: o.matrixAutoUpdate }; }); return pose; }
    function restore(pose) { if (!pose) return; Object.keys(pose).forEach(function (id) { var o = nodes[id], row = pose[id]; if (!o || !row) return; o.position.fromArray(row.position); o.quaternion.fromArray(row.quaternion); o.scale.fromArray(row.scale); if (row.matrixAutoUpdate !== undefined) o.matrixAutoUpdate = row.matrixAutoUpdate; if (row.matrix) o.matrix.fromArray(row.matrix); else o.updateMatrix(); }); root.updateMatrixWorld(true); }
    function setWorldRotation(o, rotation) {
      var local = o.parent ? quatMul(math.inverse(unityRotation(o.parent)), rotation) : rotation;
      o.quaternion.set(local[0], -local[1], -local[2], local[3]); if (o.matrixAutoUpdate === false) o.updateMatrix(); o.updateMatrixWorld(true);
    }
    function setWorldPosition(o, position) { var p = new THREE.Vector3().fromArray(mirrored(position)); if (o.parent) o.parent.worldToLocal(p); o.position.copy(p); if (o.matrixAutoUpdate === false) o.updateMatrix(); o.updateMatrixWorld(true); }
    function depth(o) { var d = 0; while (o.parent) { d++; o = o.parent; } return d; }
    function currentValues(record) { return current ? current(record) : record.values; }
    function resetSimulation(reason) { pending = true; stats.resets++; stats.resetReason = reason || 'reset'; if (/author|model|load|initialization/.test(reason || '')) pendingBase = true; }
    function obtainRest() { return options.initializationPose || (typeof options.getInitializationPose === 'function' ? options.getInitializationPose() : null); }
    function buildBase() {
      var rest = obtainRest();
      if (!rest || !Object.keys(rest).length) { missing.push('original-rest-pose'); return false; }
      var restKey = JSON.stringify(rest);
      if (restKey === restSignature && Object.keys(baseCache).length) { pendingBase = false; return true; }
      var before = snapshot(), next = {};
      try {
        restore(rest);
        (catalog.components || []).forEach(function (record) {
          if (record.kind !== 'bone') return;
          var o = nodes[String(record.node)], sim = record.simulation || {}, child = nodes[String(sim.childNode)];
          if (!o || !child) throw new Error('An original SwingBone child transform is missing.');
          var pivot = unityPosition(o), tip = unityPosition(child), local = unityLocalRotation(o);
          next[record.id] = { baseLocalRotation: local, initialAngles: math.angles(local), localPosition: v(mirrored(o.position.toArray())), boneLength: length(sub(pivot, tip)), skirtData: classify(record.name || ''), child: child, safeCorrectAdjust: false, childPoseActive: false, skirtRotRatio: 0 };
        });
      } finally { restore(before); }
      baseCache = next; restSignature = restKey; stats.initializationGeneration++; pendingBase = false; return true;
    }
    function resolveKnees(manager) {
      var ids = manager.kneeTransforms && manager.kneeTransforms.length ? manager.kneeTransforms : manager.resolvedKneeTransforms;
      if (Array.isArray(ids)) return [nodes[String(ids[0])] || null, nodes[String(ids[1])] || null];
      return [null, null];
    }
    function configure(settings) {
      profile = settings.profile || 'navi'; var sourceFlags = settings.skirtsafeDisableBySource || {}, componentFlags = settings.skirtsafeDisableByComponent || {};
      var readiness = catalogReadiness(catalog); missing = readiness.missing.slice(); configuredCorrectionMissing = readiness.skirtCorrectionMissing.slice();
      if (!THREE || !math || !global.ViewerGamePhysicsCollision || !global.ViewerGamePhysicsCollision.forJob) missing.push('native-math-module');
      if (profile !== 'navi' && profile !== 'live') missing.push('runtime-profile');
      managers = (catalog.managers || []).map(function (record) {
        var ids = (record.bones || []).concat(settings.enableLod === false ? [] : record.lodBones || []);
        var disable = profile === 'navi' ? true : sourceFlags[String(record.sourceIndex)];
        if (profile === 'live' && typeof disable !== 'boolean' && ids.some(function (id) { return typeof componentFlags[id] !== 'boolean'; })) configuredCorrectionMissing.push('source-skirt-runtime:' + record.sourceIndex);
        var knees = resolveKnees(record);
        if (profile === 'live' && (!knees[0] || !knees[1])) configuredCorrectionMissing.push('source-knee-transforms:' + record.sourceIndex);
        return { record: record, boneIds: ids, colliderIds: record.colliders || [], knees: knees, skirtsafeDisable: typeof disable === 'boolean' ? disable : null };
      });
      if (!managers.length) missing.push('native-manager');
      refreshCorrectionMissing(settings);
      return missing.length === 0;
    }
    function refreshCorrectionMissing(settings) {
      skirtCorrectionMissing = configuredCorrectionMissing.filter(function (reason, index, rows) { return rows.indexOf(reason) === index; });
      if (profile === 'live' && typeof settings.safeSwingBone !== 'boolean' && typeof context.safeSwingBone !== 'boolean') skirtCorrectionMissing.push('motion-skirt-runtime');
    }
    function initialize(settings) {
      if (!configure(settings)) return false;
      if (pendingBase || !Object.keys(baseCache).length) if (!buildBase()) return false;
      buffers = []; data = []; entries = []; colliders = []; matrices = []; output = {};
      restore(captured);
      managers.forEach(function (manager) {
        manager.boneOffset = data.length; manager.colliderOffset = colliders.length; manager.count = manager.boneIds.length;
        manager.colliderIds.forEach(function (id) {
          var record = records[id], value = currentValues(record), index = manager.colliderIds.indexOf(record.sibling), simIndex = record.siblingIndex;
          if (typeof simIndex === 'number') index = simIndex;
          var sibling = index >= 0 ? records[manager.colliderIds[index]] : null;
          colliders.push({ radius: F(value.radius), offset: v(value.offset), siblingIndex: index, siblingRadius: sibling ? F(currentValues(sibling).radius) : 0, managerOffset: manager.colliderOffset, record: record });
        });
        manager.boneIds.forEach(function (id, ordinal) {
          var record = records[id], base = baseCache[id], sim = record.simulation || {}, value = currentValues(record), o = nodes[String(record.node)], tip = unityPosition(base.child), pivot = unityPosition(o), parent = o.parent;
          base.safeCorrectAdjust = false; base.childPoseActive = false;
          var parentIndex = typeof sim.parentIndex === 'number' ? sim.parentIndex : -1, siblingIndex = typeof sim.siblingIndex === 'number' ? sim.siblingIndex : -1;
          if (parentIndex >= manager.count) parentIndex = -1; if (siblingIndex >= manager.count) siblingIndex = -1;
          var row = { localPosition: base.localPosition.slice(), baseLocalRotation: base.baseLocalRotation.slice(), parentIndex: parentIndex, childIndex: sim.childIndex === undefined ? -1 : sim.childIndex, siblingIndex: siblingIndex, colliderCount: Array.isArray(sim.colliderIds) ? sim.colliderIds.length : 0, boneLength: base.boneLength, boneAxis: v(sim.boneAxis), radius: F(sim.radius), stiffnessForce: F(value.stiffnessForce), dragForce: F(value.dragForce), externalForce: v(sim.externalForce), lowRotationLimit: v(value.lowRotationLimit), highRotationLimit: v(value.highRotationLimit), colliderIndexBit: sim.colliderBits >>> 0, boneIndex: manager.boneOffset, colliderIndex: manager.colliderOffset, colliderDataCount: manager.colliderIds.length };
          data.push(row); buffers.push({ parentPosition: parent ? unityPosition(parent) : [0, 0, 0], parentRotation: parent ? unityRotation(parent) : [0, 0, 0, 1], position: pivot, rotation: unityRotation(o), localRotation: unityLocalRotation(o), previousTipPosition: tip.slice(), currentTipPosition: tip.slice() });
          entries.push({ record: record, object: o, child: base.child, base: base, manager: manager, index: manager.boneOffset + ordinal, depth: depth(o) });
        });
      });
      colliders.forEach(function (d) { matrices.push(unityMatrix(nodes[String(d.record.node)])); });
      initialized = true; pending = false; stats.dynamicGeneration++; stats.resetReason = stats.resetReason || 'initialize'; return true;
    }
    function captureAnimationPose(nextContext) { if (disposed) return; root.updateMatrixWorld(true); captured = snapshot(); context = Object.assign({}, nextContext || {}); }
    function reapplyOutput(unanimatedOnly) { Object.keys(output).forEach(function (id) { var o = nodes[id], row = output[id], owned = unanimatedOnly && context.animatedProperties && context.animatedProperties[id] || {}; if (!o) return; if (row.quaternion && !owned.quaternion) o.quaternion.fromArray(row.quaternion); if (row.position && !owned.position) o.position.fromArray(row.position); if (o.matrixAutoUpdate === false) o.updateMatrix(); }); root.updateMatrixWorld(true); }
    function refreshInputs() {
      reapplyOutput(true);
      entries.forEach(function (entry, index) { var o = entry.object, b = buffers[index]; copy(b.position, unityPosition(o)); copy(b.rotation, unityRotation(o)); copy(b.localRotation, unityLocalRotation(o)); if (o.parent) { copy(b.parentPosition, unityPosition(o.parent)); copy(b.parentRotation, unityRotation(o.parent)); } });
      colliders.forEach(function (d, i) { matrices[i] = unityMatrix(nodes[String(d.record.node)]); });
    }
    function applyRotations() { entries.slice().sort(function (a, b) { return a.depth - b.depth; }).forEach(function (entry) { setWorldRotation(entry.object, buffers[entry.index].rotation); }); }
    function saveOutput() { output = {}; entries.forEach(function (entry) { var nodeId = String(entry.record.node); output[nodeId] = Object.assign(output[nodeId] || {}, { quaternion: entry.object.quaternion.toArray() }); if (entry.base.childPoseActive) { var childId = String((entry.record.simulation || {}).childNode); output[childId] = Object.assign(output[childId] || {}, { position: entry.child.position.toArray() }); } }); }
    function correctSkirts(settings, force) {
      var enabled = typeof settings.safeSwingBone === 'boolean' ? settings.safeSwingBone : context.safeSwingBone;
      if (!force && enabled !== true) return;
      managers.forEach(function (manager) {
        var componentFlags = settings.skirtsafeDisableByComponent || {};
        if (manager.skirtsafeDisable && !force && manager.boneIds.every(function (id) { return componentFlags[id] !== false; })) return;
        if (!manager.knees[0] || !manager.knees[1]) return;
        var left = quatRotate(unityRotation(manager.knees[0]), [1, 0, 0]), right = quatRotate(unityRotation(manager.knees[1]), [1, 0, 0]);
        entries.forEach(function (entry) {
          if (entry.manager !== manager) return;
          var disabled = typeof componentFlags[entry.record.id] === 'boolean' ? componentFlags[entry.record.id] : manager.skirtsafeDisable;
          // An unknown caller flag is not an invented false. Keep verified
          // mixed-source chains active and skip only unverified correction.
          if (!force && disabled !== false) return;
          var sim = entry.record.simulation || {}, base = entry.base, o = entry.object;
          var state = Object.assign({}, sim, { hasTrans: true, skirtData: base.skirtData, skirtSafeEnable: sim.skirtSafeEnable, parentForward: o.parent ? quatRotate(unityRotation(o.parent), [0, 0, 1]) : [0, 0, 1], parentMatrix: o.parent ? unityMatrix(o.parent) : [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], pivot: unityPosition(o), childPosition: unityPosition(entry.child), rotation: unityRotation(o), boneAxis: data[entry.index].boneAxis, length: base.boneLength, safeCorrectAdjust: base.safeCorrectAdjust });
          if (safeCorrect(state, left, right, force, math, THREE)) { setWorldRotation(o, state.rotation); setWorldPosition(entry.child, state.childPosition); base.childPoseActive = true; stats.safeCorrections++; }
          base.safeCorrectAdjust = state.safeCorrectAdjust; base.skirtRotRatio = state.skirtRotRatio;
        });
        entries.forEach(function (entry) { if (entry.manager !== manager || (!force && !entry.base.safeCorrectAdjust)) return; var tip = unityPosition(entry.child); copy(buffers[entry.index].currentTipPosition, tip); copy(buffers[entry.index].previousTipPosition, tip); entry.base.safeCorrectAdjust = false; });
      });
    }
    function now() { return typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now(); }
    function apply(delta, settings) {
      if (disposed) return; var start = now(); settings = settings || {}; stats.nativeSteps = 0; stats.substeps = 0; stats.contacts = 0; stats.safeCorrections = 0; stats.delta = Number(delta) || 0; profile = settings.profile || 'navi'; stats.profile = profile;
      if (!settings.bones) return;
      if (!captured) captureAnimationPose({});
      // Native Update/group jobs do not depend on the song's LateUpdate
      // correction switch. Unknown caller metadata disables only that optional
      // non-forced correction; it must not freeze hair, ribbons or colliders.
      var nextSignature = JSON.stringify([profile, settings.enableLod !== false, settings.skirtsafeDisableBySource || {}, settings.skirtsafeDisableByComponent || {}]);
      if (nextSignature !== signature) { pending = true; initialized = false; startupCorrection = profile === 'live'; signature = nextSignature; }
      if (pending && !initialize(settings)) return;
      refreshCorrectionMissing(settings);
      if (!(delta > 0)) { reapplyOutput(); stats.frameMs = now() - start; return; }
      refreshInputs();
      if (profile === 'live') { var result = stepJob(data, buffers, colliders, matrices, { kind: 'group', math: math, colliders: settings.colliders !== false }); stats.contacts += result.contacts; }
      else managers.forEach(function (manager) {
        var start = manager.boneOffset, end = start + manager.count;
        var result = stepJob(data.slice(start, end), buffers.slice(start, end), colliders.slice(manager.colliderOffset, manager.colliderOffset + manager.colliderIds.length), matrices.slice(manager.colliderOffset, manager.colliderOffset + manager.colliderIds.length), { kind: 'single', math: math, colliders: settings.colliders !== false }); stats.contacts += result.contacts;
      });
      applyRotations();
      if (profile === 'live') { correctSkirts(settings, startupCorrection || !!settings.forceCorrect); startupCorrection = false; }
      saveOutput(); root.updateMatrixWorld(true); root.traverse(function (o) { if (o.isSkinnedMesh && !helper(o)) o.skeleton.update(); });
      stats.nativeSteps = 1; stats.substeps = 1; stats.totalNativeSteps++; stats.frameMs = now() - start;
    }
    function state() {
      var boneRows = initialized ? entries.map(function (entry) { var b = buffers[entry.index], d = data[entry.index]; return { id: entry.record.id, node: entry.record.node, childNode: (entry.record.simulation || {}).childNode, origin: mirrored(b.position), tip: mirrored(b.currentTipPosition), radius: d.radius, colliders: (entry.record.simulation || {}).colliders || [] }; }) : [];
      var capsuleRows = initialized ? colliders.map(function (d, index) { var a = point(matrices[index], d.offset), base = d.managerOffset || 0, sibling = d.siblingIndex >= 0 ? colliders[base + d.siblingIndex] : null, b = sibling ? point(matrices[base + d.siblingIndex], sibling.offset) : a; return { id: d.record.id, a: mirrored(a), b: mirrored(b), ra: d.radius, rb: sibling ? d.siblingRadius : d.radius }; }) : [];
      return Object.assign({}, stats, { available: missing.length === 0 && catalogReadiness(catalog).coreAvailable, nativeCatalogAvailable: !!(catalog.native && catalog.native.available), initialized: initialized, initializationMissing: missing.slice(), unsupported: missing.slice(), skirtCorrectionMissing: skirtCorrectionMissing.slice(), mode: 'game', profile: profile, dynamicBones: entries.length, components: (catalog.components || []).length, bones: boneRows, capsules: capsuleRows, runtimeProfile: { job: profile === 'live' ? 'SwingBoneGroupJob' : 'SwingBoneJob', callerFlags: true } });
    }
    return { captureAnimationPose: captureAnimationPose, resetSimulation: resetSimulation, setInitializationPose: function (pose) { options.initializationPose = pose; pendingBase = true; resetSimulation('initialization-pose'); }, apply: apply, getState: state, getTimingState: function () { return Object.assign({}, stats); }, dispose: function () { disposed = true; output = {}; captured = null; buffers = []; data = []; entries = []; } };
  }
  global.ViewerGamePhysics = { create: create, catalogReadiness: catalogReadiness, profiles: { navi: { job: 'single', enableJob: true, enableLod: true, skirtsafeDisable: true }, live: { job: 'group', flagsFromCaller: true } }, reference: { stepJob: stepJob, constraint: constraint, quatMul: quatMul, quatRotate: quatRotate, point: point, classify: classify, safeCorrect: safeCorrect } };
}(typeof window !== 'undefined' ? window : globalThis));
