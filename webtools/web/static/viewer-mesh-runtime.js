/* Exact source-bound mesh editing on the live Three.js model. */
(function (global) {
  'use strict';
  function vertexLocal(mesh, index, target) {
    var T = global.THREE, geometry = mesh.geometry, base = geometry.attributes.position;
    target = target || new T.Vector3(); target.fromBufferAttribute(base, index);
    var morphs = geometry.morphAttributes.position || [], influences = mesh.morphTargetInfluences || [];
    var value = new T.Vector3(), original = target.clone();
    morphs.forEach(function (attribute, i) {
      var weight = influences[i] || 0; if (!weight) return;
      value.fromBufferAttribute(attribute, index); if (!geometry.morphTargetsRelative) value.sub(original);
      target.addScaledVector(value, weight);
    });
    return target;
  }
  function skinMatrix(mesh, index, target) {
    var T = global.THREE; target = target || new T.Matrix4(); target.identity();
    var skin = mesh.geometry.attributes.skinIndex, weights = mesh.geometry.attributes.skinWeight;
    if (!mesh.isSkinnedMesh || !mesh.skeleton || !skin || !weights) return target;
    var sum = new T.Matrix4(), bone = new T.Matrix4(); sum.elements.fill(0);
    ['X', 'Y', 'Z', 'W'].forEach(function (axis) {
      var w = weights['get' + axis](index), i = skin['get' + axis](index); if (!w) return;
      if (!mesh.skeleton.bones[i] || !mesh.skeleton.boneInverses[i]) return;
      bone.multiplyMatrices(mesh.skeleton.bones[i].matrixWorld, mesh.skeleton.boneInverses[i]);
      for (var n = 0; n < 16; n++) sum.elements[n] += bone.elements[n] * w;
    });
    return target.copy(mesh.bindMatrixInverse).multiply(sum).multiply(mesh.bindMatrix);
  }
  function vertexWorld(mesh, index, target) {
    var T = global.THREE; target = vertexLocal(mesh, index, target || new T.Vector3());
    // r128 boneTransform reloads the un-morphed base vertex. Apply skinning
    // explicitly so morph + skin picking agrees with the rendered shader.
    if (mesh.isSkinnedMesh) target.applyMatrix4(skinMatrix(mesh, index));
    return target.applyMatrix4(mesh.matrixWorld);
  }
  function worldSnapshot(mesh, indices) {
    // Read one immutable pose for a batch. Bone world/inverse products and
    // temporary matrices are shared, while weighted additions and bind-matrix
    // multiplication retain vertexWorld's original arithmetic order.
    var T = global.THREE, geometry = mesh.geometry, base = geometry.attributes.position, result = new Array(base.count);
    var morphs = geometry.morphAttributes.position || [], influences = mesh.morphTargetInfluences || [];
    var morph = new T.Vector3(), original = new T.Vector3(), blend = new T.Matrix4(), transform = new T.Matrix4();
    var skin = geometry.attributes.skinIndex, weights = geometry.attributes.skinWeight, matrices = [], weightValues = [0, 0, 0, 0], boneValues = [0, 0, 0, 0];
    var canSkin = !!(mesh.isSkinnedMesh && mesh.skeleton && skin && weights);
    if (canSkin) mesh.skeleton.bones.forEach(function (bone, index) {
      var inverse = mesh.skeleton.boneInverses[index];
      if (bone && inverse) matrices[index] = new T.Matrix4().multiplyMatrices(bone.matrixWorld, inverse);
    });
    var count = indices ? indices.length : base.count;
    for (var slot = 0; slot < count; slot++) {
      var index = indices ? indices[slot] : slot;
      if (!Number.isInteger(index) || index < 0 || index >= base.count) throw new Error('The source vertex index is invalid.');
      var point = new T.Vector3().fromBufferAttribute(base, index); original.copy(point);
      for (var target = 0; target < morphs.length; target++) {
        var influence = influences[target] || 0; if (!influence) continue;
        morph.fromBufferAttribute(morphs[target], index); if (!geometry.morphTargetsRelative) morph.sub(original);
        point.addScaledVector(morph, influence);
      }
      if (canSkin) {
        blend.elements.fill(0);
        weightValues[0] = weights.getX(index); weightValues[1] = weights.getY(index); weightValues[2] = weights.getZ(index); weightValues[3] = weights.getW(index);
        boneValues[0] = skin.getX(index); boneValues[1] = skin.getY(index); boneValues[2] = skin.getZ(index); boneValues[3] = skin.getW(index);
        for (var axis = 0; axis < 4; axis++) {
          var weight = weightValues[axis], matrix = matrices[boneValues[axis]];
          if (!weight || !matrix) continue;
          for (var element = 0; element < 16; element++) blend.elements[element] += matrix.elements[element] * weight;
        }
        transform.copy(mesh.bindMatrixInverse).multiply(blend).multiply(mesh.bindMatrix);
        point.applyMatrix4(transform);
      } else if (mesh.isSkinnedMesh) point.applyMatrix4(transform.identity());
      result[index] = point.applyMatrix4(mesh.matrixWorld);
    }
    return result;
  }
  function identityKey(value) { return JSON.stringify(value); }
  function mapping(mesh) { return mesh && (mesh.geometry && mesh.geometry.userData && mesh.geometry.userData.viewerMesh || mesh.userData && mesh.userData.viewerMesh); }
  function validMapping(mesh) {
    var map = mapping(mesh), geometry = mesh.geometry;
    return map && map.version === 1 && map.writable === true && map.vertexOrder === 'identity' &&
      map.mesh && Array.isArray(map.positionMatrix) && map.positionMatrix.length === 16 &&
      geometry && geometry.attributes.position && geometry.attributes.position.count === map.vertexCount &&
      geometry.index && geometry.index.count / 3 === map.faceCount;
  }
  function raycastMesh(ray, mesh, options) {
    var T = global.THREE, geometry = mesh.geometry, index = geometry.index, positions = geometry.attributes.position;
    options = options || {}; var vertices = options.vertices || new Array(positions.count), nearest = null;
    function point(i) { return vertices[i] || (vertices[i] = vertexWorld(mesh, i)); }
    var count = index ? index.count : positions.count, hit = new T.Vector3(), list = options.faceIndices || null;
    for (var ordinal = 0; ordinal < (list ? list.length : count / 3); ordinal++) {
      var faceIndex = list ? list[ordinal] : ordinal, offset = faceIndex * 3; if (options.faceFilter && !options.faceFilter(faceIndex)) continue;
      var a = index ? index.getX(offset) : offset, b = index ? index.getX(offset + 1) : offset + 1, c = index ? index.getX(offset + 2) : offset + 2;
      if (!ray.intersectTriangle(point(a), point(b), point(c), false, hit)) continue;
      if (options.hitFilter && !options.hitFilter(hit, faceIndex, mesh)) continue;
      var distance = ray.origin.distanceToSquared(hit);
      if (!nearest || distance < nearest.distanceSquared) nearest = { object: mesh, point: hit.clone(), faceIndex: faceIndex,
        face: { a: a, b: b, c: c }, distanceSquared: distance,
        barycoord: T.Triangle.getBarycoord(hit, point(a), point(b), point(c), new T.Vector3()) };
    }
    if (nearest) nearest.distance = Math.sqrt(nearest.distanceSquared);
    return nearest;
  }
  function create(options) {
    var T = global.THREE; if (!T || !options.getRuntime) return null;
    var runtime = null, model = null, bindings = [], boundKeys = {}, overlayRoot = null, overlayGeometry = null, overlay = null;
    var pointGeometry = null, points = null, pointVertices = [], pointSelectionGeometry = null, selectedPoints = null;
    var stroke = null, disposed = false, sceneListeners = [], brushCursor = null, lastPointer = null;
    var overlayRefs = [], projected = [], projectionCache = null, worldVertices = {}, updateVersion = 0, lastBindingsVersion = -1, syncedData = [];
    var poseSignature = '', projectionValidated = false, currentSurfaces = [], helperSelectionKey = '', attributeIds = new WeakMap(), attributeGeneration = 0;
    var gizmoRoot = null, gizmoAxes = [], gizmoState = { visible: false, handles: [] }, gizmoSignature = '';
    var performanceState = { worldInvalidations: 0, worldVertices: 0, projectionBuilds: 0, projectionHits: 0, geometryApplications: 0, overlayUpdates: 0 };
    var raycaster = new T.Raycaster(), scratch = new T.Vector3(), v4 = new T.Vector4();
    function sourceContext() { return options.getContext ? options.getContext() : null; }
    function request() { var r = options.getRuntime(); if (r && r.requestRender) r.requestRender(); }
    function notify() { if (options.onRuntimeChange) options.onRuntimeChange(); }
    function helper(object) { object.userData.viewerHelper = true; object.frustumCulled = false; return object; }
    function ensureOverlay(r) {
      if (overlayRoot || !r.scene) return;
      overlayRoot = helper(new T.Group()); overlayRoot.name = 'Mesh editor selection';
      overlayGeometry = new T.BufferGeometry(); overlayGeometry.setAttribute('position', new T.Float32BufferAttribute([], 3));
      overlay = helper(new T.Mesh(overlayGeometry, new T.MeshBasicMaterial({ color: 0xff4370, transparent: true, opacity: .55,
        depthTest: true, depthWrite: false, side: T.DoubleSide, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 })));
      overlay.renderOrder = 900; overlayRoot.add(overlay);
      pointGeometry = new T.BufferGeometry(); pointGeometry.setAttribute('position', new T.Float32BufferAttribute([], 3));
      points = helper(new T.Points(pointGeometry, new T.PointsMaterial({ color: 0x53d7ff, size: 5, sizeAttenuation: false, depthTest: true, depthWrite: false })));
      points.renderOrder = 901; overlayRoot.add(points);
      pointSelectionGeometry = new T.BufferGeometry(); pointSelectionGeometry.setAttribute('position', new T.Float32BufferAttribute([], 3));
      selectedPoints = helper(new T.Points(pointSelectionGeometry, new T.PointsMaterial({ color: 0xffdf48, size: 10, sizeAttenuation: false, depthTest: false, depthWrite: false })));
      selectedPoints.renderOrder = 902; overlayRoot.add(selectedPoints); r.scene.add(overlayRoot);
    }
    function releaseBindings() {
      bindings.forEach(function (binding) { if (binding.mesh.geometry === binding.geometry) binding.mesh.geometry = binding.original; binding.geometry.dispose(); });
      bindings = []; boundKeys = {}; worldVertices = {}; projected = []; overlayRefs = []; pointVertices = [];
      poseSignature = ''; projectionCache = null; projectionValidated = false; currentSurfaces = []; helperSelectionKey = '';
      if (overlayRoot) { overlayRoot.parent.remove(overlayRoot); overlayRoot.traverse(function (child) { if (child.geometry) child.geometry.dispose(); if (child.material) { if (child.material.map) child.material.map.dispose(); child.material.dispose(); } }); }
      overlayRoot = null; overlayGeometry = null; overlay = null; pointGeometry = null; points = null; selectedPoints = null; pointSelectionGeometry = null;
      gizmoRoot = null; gizmoAxes = []; gizmoState = { visible: false, handles: [] }; gizmoSignature = '';
      updateVersion++; lastBindingsVersion = -1;
    }
    function unlisten() { sceneListeners.forEach(function (remove) { remove(); }); sceneListeners = []; if (brushCursor) brushCursor.remove(); brushCursor = null; }
    function listen(element, event, fn, capture) { element.addEventListener(event, fn, capture || false); sceneListeners.push(function () { element.removeEventListener(event, fn, capture || false); }); }
    function reset() {
      endStroke(true); unlisten(); releaseBindings(); model = null; runtime = null; syncedData = [];
    }
    function adoptRuntime() {
      var next = options.getRuntime(); if (!next || !next.model || !next.renderer || !next.camera) return false;
      if (model !== next.model || !runtime || runtime.renderer !== next.renderer) { reset(); runtime = next; model = next.model; attachPointer(); }
      runtime = next; ensureOverlay(next); return true;
    }
    function bind(m) {
      if (!adoptRuntime()) return;
      var id = identityKey(m.data.mesh); if (boundKeys[id]) return;
      var found = [];
      model.traverse(function (mesh) {
        var map = mapping(mesh); if (!mesh.isMesh || mesh.userData.viewerHelper || !map || identityKey(map.mesh) !== id || !validMapping(mesh)) return;
        var original = mesh.geometry, geometry = original.clone(); mesh.geometry = geometry;
        var binding = { mesh: mesh, map: map, original: original, geometry: geometry, data: m,
          positionMatrix: new T.Matrix4().fromArray(map.positionMatrix), baseIndex: Array.from(geometry.index.array),
          basePosition: geometry.attributes.position.array.slice(), baseNormal: geometry.attributes.normal && geometry.attributes.normal.array.slice(),
          baseWeight: geometry.attributes.skinWeight && geometry.attributes.skinWeight.array.slice(),
          baseSkinIndex: geometry.attributes.skinIndex && geometry.attributes.skinIndex.array.slice(), faceMap: [] };
        bindings.push(binding); found.push(binding);
      });
      boundKeys[id] = found; updateVersion++;
    }
    function apply(binding) {
      var m = binding.data, geometry = binding.geometry, position = geometry.attributes.position;
      // Selection and UV navigation do not change the source geometry. Keep
      // attribute versions and the index object stable for exact pick caching.
      // The JSON fallback retains the standalone runtime's mutation contract.
      var revision = typeof m.geometryRevision === 'number' ? m.geometryRevision : JSON.stringify([Array.from(m.deleted), m.positions, m.weights]);
      if (binding.appliedRevision === revision) return;
      position.array.set(binding.basePosition);
      Object.keys(m.positions).forEach(function (id) { scratch.fromArray(m.positions[id]).applyMatrix4(binding.positionMatrix); position.setXYZ(+id, scratch.x, scratch.y, scratch.z); });
      position.needsUpdate = true;
      var weights = geometry.attributes.skinWeight, indices = geometry.attributes.skinIndex;
      if (weights && indices && binding.map.boneOrder === 'identity') {
        weights.array.set(binding.baseWeight); indices.array.set(binding.baseSkinIndex);
        Object.keys(m.weights).forEach(function (id) { var value = m.weights[id], w = [0, 0, 0, 0], i = [0, 0, 0, 0]; value.forEach(function (pair, slot) { i[slot] = pair[0]; w[slot] = pair[1]; }); weights.setXYZW(+id, w[0], w[1], w[2], w[3]); indices.setXYZW(+id, i[0], i[1], i[2], i[3]); });
        weights.needsUpdate = true; indices.needsUpdate = true;
      }
      var index = [], faceMap = [];
      for (var i = 0; i < binding.baseIndex.length; i += 3) {
        var sourceFace = binding.map.firstFace + i / 3;
        if (m.deleted.has(sourceFace)) continue;
        index.push(binding.baseIndex[i], binding.baseIndex[i + 1], binding.baseIndex[i + 2]); faceMap.push(sourceFace);
      }
      geometry.setIndex(index); binding.faceMap = faceMap;
      if (Object.keys(m.positions).length) geometry.computeVertexNormals();
      else if (binding.baseNormal && geometry.attributes.normal) { geometry.attributes.normal.array.set(binding.baseNormal); geometry.attributes.normal.needsUpdate = true; }
      geometry.boundingBox = null; geometry.boundingSphere = null;
      binding.appliedRevision = revision; performanceState.geometryApplications++;
    }
    function rebuildOverlay() {
      overlayRefs = []; pointVertices = [];
      var context = sourceContext(); if (!context || !context.mesh) return;
      var active = context.mesh, id = identityKey(active.data.mesh), list = boundKeys[id] || [];
      list.forEach(function (binding) {
        if (!context.showSelection || !active.marked) return;
        active.marked.forEach(function (face) {
          if (face < binding.map.firstFace || face >= binding.map.firstFace + binding.map.faceCount || active.deleted.has(face)) return;
          var offset = (face - binding.map.firstFace) * 3;
          for (var slot = 0; slot < 3; slot++) overlayRefs.push({ binding: binding, vertex: binding.baseIndex[offset + slot] });
        });
      });
      if (context.showVertices && list.length) {
        var seen = new Set();
        list.forEach(function (binding) {
          if (context.submesh !== undefined && binding.map.submesh !== context.submesh) return;
          binding.baseIndex.forEach(function (vertex) { if (!seen.has(vertex)) { pointVertices.push({ binding: binding, vertex: vertex }); seen.add(vertex); } });
        });
      }
      if (overlayGeometry) overlayGeometry.setAttribute('position', new T.Float32BufferAttribute(new Float32Array(overlayRefs.length * 3), 3));
      if (pointGeometry) pointGeometry.setAttribute('position', new T.Float32BufferAttribute(new Float32Array(pointVertices.length * 3), 3));
      var selectedCount = active.selected ? active.selected.size : 0;
      if (pointSelectionGeometry) pointSelectionGeometry.setAttribute('position', new T.Float32BufferAttribute(new Float32Array(selectedCount * 3), 3));
    }
    function sync(items) {
      if (disposed) return; var nextData = items || syncedData;
      if (!adoptRuntime()) return;
      syncedData = nextData;
      syncedData.forEach(bind); bindings.forEach(apply); updateVersion++; rebuildOverlay(); beforeRender(); request();
    }
    function world(binding, vertex) {
      var id = binding.mesh.uuid, values = worldVertices[id] || (worldVertices[id] = []);
      if (!values[vertex]) { values[vertex] = vertexWorld(binding.mesh, vertex); performanceState.worldVertices++; }
      return values[vertex];
    }
    function visible(mesh) { for (var node = mesh; node; node = node.parent) if (!node.visible) return false; return true; }
    function attributeKey(attribute) {
      if (!attribute) return '-';
      if (!attributeIds.has(attribute)) attributeIds.set(attribute, ++attributeGeneration);
      var data = attribute.data, array = attribute.array || data && data.array;
      if (array && !attributeIds.has(array)) attributeIds.set(array, ++attributeGeneration);
      return [attributeIds.get(attribute), attribute.version, data && data.version, attribute.count,
        attribute.itemSize, attribute.offset, data && data.stride, array && attributeIds.get(array)].join(':');
    }
    function surfacePoseSignature(surfaces) {
      var key = [];
      surfaces.forEach(function (binding) {
        var mesh = binding.mesh, geometry = mesh.geometry, attributes = geometry.attributes;
        key.push(mesh.uuid, geometry.uuid, mesh.matrixWorld.elements.join(','));
        [geometry.index, attributes.position, attributes.skinIndex, attributes.skinWeight].forEach(function (attribute) { key.push(attributeKey(attribute)); });
        key.push((mesh.morphTargetInfluences || []).join(','), geometry.morphTargetsRelative);
        (geometry.morphAttributes.position || []).forEach(function (attribute) { key.push(attributeKey(attribute)); });
        if (mesh.isSkinnedMesh && mesh.skeleton) {
          key.push(mesh.bindMatrix.elements.join(','), mesh.bindMatrixInverse.elements.join(','));
          mesh.skeleton.bones.forEach(function (bone, index) {
            var inverse = mesh.skeleton.boneInverses[index];
            key.push(bone && bone.matrixWorld ? bone.matrixWorld.elements.join(',') : '-', inverse ? inverse.elements.join(',') : '-');
          });
        }
      });
      return key.join('|');
    }
    function beforeRender() {
      if (disposed || !adoptRuntime()) return;
      var context = sourceContext(); if (!context || !context.mesh) { if (overlayRoot) overlayRoot.visible = false; return; }
      var list = boundKeys[identityKey(context.mesh.data.mesh)] || [];
      if (!list.length) { if (overlayRoot) overlayRoot.visible = false; return; }
      if (overlayRoot) overlayRoot.visible = true;
      runtime.model.updateMatrixWorld(true); runtime.camera.updateMatrixWorld(true); currentSurfaces = surfaceBindings();
      var signature = surfacePoseSignature(currentSurfaces), changedPose = signature !== poseSignature;
      if (changedPose) { poseSignature = signature; worldVertices = {}; projectionCache = null; performanceState.worldInvalidations++; }
      projectionValidated = false;
      var selectionKey = context.showVertices ? Array.from(context.mesh.selected).join(',') : '';
      if (overlay) overlay.visible = context.showSelection && overlayRefs.length > 0;
      if (points) points.visible = context.showVertices && pointVertices.length > 0;
      if (selectedPoints) selectedPoints.visible = context.showVertices && context.mesh.selected.size > 0;
      updateGizmo(context, list);
      // Both pose and selection must be unchanged before reusing helper buffers.
      if (!changedPose && lastBindingsVersion === updateVersion && helperSelectionKey === selectionKey) return;
      if (overlayGeometry) { var pos = overlayGeometry.attributes.position; overlayRefs.forEach(function (entry, i) { var v = world(entry.binding, entry.vertex); pos.setXYZ(i, v.x, v.y, v.z); }); pos.needsUpdate = true; overlay.visible = context.showSelection && overlayRefs.length > 0; }
      if (pointGeometry) { var p = pointGeometry.attributes.position; pointVertices.forEach(function (entry, i) { var v = world(entry.binding, entry.vertex); p.setXYZ(i, v.x, v.y, v.z); }); p.needsUpdate = true; points.visible = context.showVertices && pointVertices.length > 0; }
      if (pointSelectionGeometry) { var chosen = pointSelectionGeometry.attributes.position, first = list[0], n = 0; context.mesh.selected.forEach(function (vertex) { var v = world(first, vertex); chosen.setXYZ(n++, v.x, v.y, v.z); }); chosen.needsUpdate = true; selectedPoints.visible = context.showVertices && context.mesh.selected.size > 0; }
      lastBindingsVersion = updateVersion;
      helperSelectionKey = selectionKey;
      performanceState.overlayUpdates++;
    }
    function activeBindings(context) { return (boundKeys[identityKey(context.mesh.data.mesh)] || []).filter(function (binding) { return visible(binding.mesh) && (context.submesh === undefined || binding.map.submesh === context.submesh); }); }
    function sourceLinear(binding, vertex) {
      return new T.Matrix3().setFromMatrix4(new T.Matrix4().copy(binding.mesh.matrixWorld).multiply(skinMatrix(binding.mesh, vertex)).multiply(binding.positionMatrix));
    }
    function selectedFrame(context, binding) {
      var centre = new T.Vector3(), vectors = [new T.Vector3(), new T.Vector3(), new T.Vector3()], count = 0;
      context.mesh.selected.forEach(function (vertex) {
        if (!Number.isInteger(vertex) || vertex < 0 || vertex >= binding.geometry.attributes.position.count) return;
        centre.add(world(binding, vertex)); count++;
        var linear = sourceLinear(binding, vertex);
        vectors.forEach(function (sum, axis) { var basis = new T.Vector3(); basis.setComponent(axis, 1); sum.add(basis.applyMatrix3(linear)); });
      });
      if (!count) return null;
      centre.divideScalar(count); vectors.forEach(function (v) { v.divideScalar(count); });
      return { centre: centre, vectors: vectors, count: count, binding: binding };
    }
    function screenPoint(point, rect) {
      var p = point.clone().project(runtime.camera);
      return { x: rect.left + (p.x + 1) * rect.width / 2, y: rect.top + (1 - p.y) * rect.height / 2, z: p.z };
    }
    function ensureGizmo() {
      if (gizmoRoot || !overlayRoot) return;
      gizmoRoot = helper(new T.Group()); gizmoRoot.name = 'Selected vertex move axes'; overlayRoot.add(gizmoRoot);
      ['x', 'y', 'z'].forEach(function (axis, index) {
        var color = [0xff5268, 0x5bd37f, 0x58a5ff][index], arrow = new T.ArrowHelper(new T.Vector3(1, 0, 0), new T.Vector3(), 1, color, .2, .1), label = null;
        arrow.traverse(function (child) { helper(child); child.renderOrder = 903; if (child.material) { child.material.depthTest = false; child.material.depthWrite = false; } });
        gizmoRoot.add(arrow);
        try {
          var canvas = document.createElement('canvas'); canvas.width = canvas.height = 48;
          var ctx = canvas.getContext('2d');
          if (ctx) {
            ctx.font = 'bold 32px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineWidth = 5; ctx.strokeStyle = '#17212f'; ctx.strokeText(axis.toUpperCase(), 24, 25); ctx.fillStyle = '#' + color.toString(16).padStart(6, '0'); ctx.fillText(axis.toUpperCase(), 24, 25);
            label = helper(new T.Sprite(new T.SpriteMaterial({ map: new T.CanvasTexture(canvas), transparent: true, depthTest: false, depthWrite: false })));
            label.renderOrder = 904; gizmoRoot.add(label);
          }
        } catch (_) { /* Geometry handles remain usable without canvas text. */ }
        gizmoAxes.push({ axis: axis, index: index, arrow: arrow, label: label });
      });
    }
    function hideGizmo() {
      if (gizmoRoot) gizmoRoot.visible = false;
      gizmoState = { visible: false, handles: [] }; gizmoSignature = '';
    }
    function updateGizmo(context, list) {
      if (!context.modify || context.mode !== 'drag' || context.interactive === false || !context.mesh.data.positionWritable || !context.mesh.selected.size || !list.length) { hideGizmo(); return; }
      var canvas = runtime.domElement || runtime.renderer.domElement, rect = canvas.getBoundingClientRect();
      var signature = [poseSignature, updateVersion, Array.from(context.mesh.selected).join(','), context.submesh, context.mode,
        runtime.camera.matrixWorld.elements.join(','), runtime.camera.projectionMatrix.elements.join(','), rect.left, rect.top, rect.width, rect.height, nearClipEnabled() ? 1 : 0].join(':');
      if (signature === gizmoSignature) return;
      gizmoSignature = signature;
      var active = activeBindings(context), frame = active.length && selectedFrame(context, active[0]); if (!frame || !rect.height) { hideGizmo(); return; }
      var depth = -frame.centre.clone().applyMatrix4(runtime.camera.matrixWorldInverse).z;
      if (depth <= 0 || global.ViewerNearClip && !global.ViewerNearClip.visiblePoint(runtime.camera, frame.centre)) { hideGizmo(); return; }
      var origin = screenPoint(frame.centre, rect);
      if (origin.z < -1 || origin.z > 1) { hideGizmo(); return; }
      ensureGizmo(); if (!gizmoRoot) return;
      var worldPixel = 2 * (runtime.camera.isOrthographicCamera ? 1 : depth) / Math.max(1e-12, rect.height * Math.abs(runtime.camera.projectionMatrix.elements[5]));
      gizmoRoot.visible = true;
      var handles = [];
      gizmoAxes.forEach(function (axis) {
        var direction = frame.vectors[axis.index].clone(), magnitude = direction.length(), length = worldPixel * 66;
        if (magnitude < 1e-10) { axis.arrow.visible = false; if (axis.label) axis.label.visible = false; return; }
        direction.divideScalar(magnitude);
        var end = screenPoint(frame.centre.clone().addScaledVector(direction, length), rect), pixels = Math.hypot(end.x - origin.x, end.y - origin.y);
        // An axis pointing straight through the camera has no unambiguous
        // screen handle. The explicit axis selector still supports depth drag.
        if (pixels < 12) { axis.arrow.visible = false; if (axis.label) axis.label.visible = false; return; }
        length *= Math.max(.5, Math.min(4, 66 / pixels));
        axis.arrow.visible = true; axis.arrow.position.copy(frame.centre); axis.arrow.setDirection(direction); axis.arrow.setLength(length, Math.min(length * .3, worldPixel * 12), worldPixel * 7);
        end = screenPoint(frame.centre.clone().addScaledVector(direction, length), rect);
        if (!Number.isFinite(end.x) || !Number.isFinite(end.y) || end.z < -1 || end.z > 1) { axis.arrow.visible = false; if (axis.label) axis.label.visible = false; return; }
        var start = screenPoint(frame.centre.clone().addScaledVector(direction, length * .25), rect), hit = screenPoint(frame.centre.clone().addScaledVector(direction, length * .76), rect);
        if (axis.label) { axis.label.visible = true; axis.label.position.copy(frame.centre).addScaledVector(direction, length + worldPixel * 10); axis.label.scale.setScalar(worldPixel * 20); }
        handles.push({ axis: axis.axis, x: hit.x, y: hit.y, start: { x: start.x, y: start.y }, end: { x: end.x, y: end.y }, world: frame.centre.clone().addScaledVector(direction, length * .76).toArray() });
      });
      gizmoState = { visible: handles.length > 0, centre: { x: origin.x, y: origin.y, world: frame.centre.toArray() }, handles: handles, frame: frame };
      gizmoRoot.visible = gizmoState.visible;
    }
    function pickGizmo(event, context) {
      if (context.mode !== 'drag' || !context.modify) return null;
      beforeRender(); if (!gizmoState.visible) return null;
      var nearest = null, radius = event.pointerType === 'touch' ? 15 : 9;
      gizmoState.handles.forEach(function (handle) {
        var dx = handle.end.x - handle.start.x, dy = handle.end.y - handle.start.y, length = dx * dx + dy * dy;
        var amount = length ? Math.max(0, Math.min(1, ((event.clientX - handle.start.x) * dx + (event.clientY - handle.start.y) * dy) / length)) : 0;
        var distance = Math.hypot(event.clientX - handle.start.x - dx * amount, event.clientY - handle.start.y - dy * amount);
        if (distance <= radius && (!nearest || distance < nearest.distance)) nearest = { gizmo: true, axis: handle.axis, binding: gizmoState.frame.binding, point: gizmoState.frame.centre.clone(), distance: distance };
      }); return nearest;
    }
    function pointerRay(event) {
      var canvas = runtime.domElement || runtime.renderer.domElement, rect = canvas.getBoundingClientRect();
      raycaster.setFromCamera(new T.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2), runtime.camera); return { ray: raycaster.ray, rect: rect };
    }
    function surfaceBindings() {
      var result = [], owned = {}; bindings.forEach(function (binding) { owned[binding.mesh.uuid] = binding; });
      if (!model) return result;
      model.traverse(function (mesh) {
        if (!mesh.isMesh || mesh.userData.viewerHelper || !visible(mesh) || !mesh.geometry || !mesh.geometry.attributes.position) return;
        var materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        if (materials.length && materials.every(function (material) { return !material || material.visible === false || material.opacity === 0; })) return;
        result.push(owned[mesh.uuid] || { mesh: mesh, geometry: mesh.geometry, data: null, map: mapping(mesh), faceMap: [] });
      }); return result;
    }
    function projection(context) {
      if (projectionCache && projectionValidated) { performanceState.projectionHits++; return projectionCache; }
      runtime.camera.updateMatrixWorld(true);
      var rect = (runtime.domElement || runtime.renderer.domElement).getBoundingClientRect(), cols = Math.max(1, Math.ceil(rect.width / 32));
      var viewKey = runtime.camera.matrixWorld.elements.join(',') + ':' + runtime.camera.projectionMatrix.elements.join(',') + ':' + [rect.left, rect.top, rect.width, rect.height, nearClipEnabled() ? 1 : 0].join(',');
      projectionValidated = true;
      if (projectionCache && projectionCache.viewKey === viewKey) { performanceState.projectionHits++; return projectionCache; }
      var result = { rect: rect, cols: cols, bindings: {}, surfaces: currentSurfaces, viewKey: viewKey };
      performanceState.projectionBuilds++;
      result.surfaces.forEach(function (binding) {
        if (!visible(binding.mesh)) return;
        var entry = { points: {}, bins: {}, wide: [], binding: binding };
        function point(vertex) { return entry.points[vertex] || (entry.points[vertex] = projectedVertex(binding, vertex, rect)); }
        var indices = binding.geometry.index, indexCount = indices ? indices.count : binding.geometry.attributes.position.count;
        for (var offset = 0; offset < indexCount; offset += 3) {
          var tri = [point(indices ? indices.getX(offset) : offset), point(indices ? indices.getX(offset + 1) : offset + 1), point(indices ? indices.getX(offset + 2) : offset + 2)];
          if (tri.some(function (p) { return p.z < -1 || p.z > 1; })) {
            if (!nearClipEnabled()) continue;
            var depths = tri.map(function (p) { return viewDepth(p.world); });
            if (depths.every(function (depth) { return depth < runtime.camera.near; }) || depths.every(function (depth) { return depth > runtime.camera.far; })) continue;
            // A triangle crossing the near plane can cover visible interior
            // pixels even with a clipped corner. Its exact filtered ray hit,
            // rather than an unstable projected bounding box, decides picks.
            entry.wide.push(offset / 3); continue;
          }
          var minX = Math.max(0, Math.floor((Math.min(tri[0].x, tri[1].x, tri[2].x) - rect.left) / 32)), maxX = Math.min(cols - 1, Math.floor((Math.max(tri[0].x, tri[1].x, tri[2].x) - rect.left) / 32));
          var minY = Math.max(0, Math.floor((Math.min(tri[0].y, tri[1].y, tri[2].y) - rect.top) / 32)), maxY = Math.min(Math.ceil(rect.height / 32) - 1, Math.floor((Math.max(tri[0].y, tri[1].y, tri[2].y) - rect.top) / 32));
          for (var x = minX; x <= maxX; x++) for (var y = minY; y <= maxY; y++) { var key = x + y * cols; if (!entry.bins[key]) entry.bins[key] = []; entry.bins[key].push(offset / 3); }
        }
        result.bindings[binding.mesh.uuid] = entry;
      }); projectionCache = result; return result;
    }
    function candidatesAt(context, binding, x, y, radius) {
      var cache = projection(context), entry = cache.bindings[binding.mesh.uuid], set = new Set(); if (!entry) return [];
      (entry.wide || []).forEach(function (face) { set.add(face); });
      for (var gx = Math.max(0, Math.floor((x - radius - cache.rect.left) / 32)); gx <= Math.min(cache.cols - 1, Math.floor((x + radius - cache.rect.left) / 32)); gx++)
        for (var gy = Math.max(0, Math.floor((y - radius - cache.rect.top) / 32)); gy <= Math.min(Math.ceil(cache.rect.height / 32) - 1, Math.floor((y + radius - cache.rect.top) / 32)); gy++)
          (entry.bins[gx + gy * cache.cols] || []).forEach(function (face) { set.add(face); });
      return Array.from(set);
    }
    function raycastAt(event, context, ray) {
      var nearest = null, hitFilter = global.ViewerNearClip && global.ViewerNearClip.filterForCamera(runtime.camera);
      projection(context).surfaces.forEach(function (binding) {
        if (!visible(binding.mesh)) return;
        var hit = raycastMesh(ray, binding.mesh, { vertices: worldVertices[binding.mesh.uuid] || [], faceIndices: candidatesAt(context, binding, event.clientX, event.clientY, 0), hitFilter: hitFilter });
        if (hit && (!nearest || hit.distanceSquared < nearest.distanceSquared - 1e-10 || Math.abs(hit.distanceSquared - nearest.distanceSquared) <= 1e-10 && binding.data === context.mesh && binding.map && binding.map.submesh === context.submesh)) { nearest = hit; nearest.binding = binding; nearest.sourceFace = binding.faceMap[hit.faceIndex]; }
      }); return nearest;
    }
    function hitSurface(event, context, prepared) {
      if (!prepared) beforeRender(); var pointer = pointerRay(event), nearest = raycastAt(event, context, pointer.ray);
      if (nearest && (nearest.binding.data !== context.mesh || context.submesh !== undefined && nearest.binding.map.submesh !== context.submesh)) return null;
      return nearest;

    }
    function projectedVertex(binding, vertex, rect) {
      var p = world(binding, vertex), q = p.clone().project(runtime.camera);
      return { x: rect.left + (q.x + 1) * rect.width / 2, y: rect.top + (1 - q.y) * rect.height / 2, z: q.z, world: p };
    }
    function nearClipEnabled() { return !!(global.ViewerNearClip && runtime.camera.userData && runtime.camera.userData.viewerNearClipEnabled); }
    function viewDepth(point) { var e = runtime.camera.matrixWorldInverse.elements; return -(point.x * e[2] + point.y * e[6] + point.z * e[10] + e[14]); }
    function clippedScreenPolygon(screen, rect) {
      var polygon = screen.map(function (p) { return p.world; });
      [{ depth: runtime.camera.near, minimum: true }, { depth: runtime.camera.far, minimum: false }].forEach(function (plane) {
        var output = []; if (!polygon.length) return;
        polygon.forEach(function (current, index) {
          var previous = polygon[(index + polygon.length - 1) % polygon.length], a = viewDepth(previous), b = viewDepth(current);
          var insideA = plane.minimum ? a >= plane.depth : a <= plane.depth, insideB = plane.minimum ? b >= plane.depth : b <= plane.depth;
          if (insideA !== insideB) output.push(previous.clone().lerp(current, (plane.depth - a) / (b - a)));
          if (insideB) output.push(current);
        }); polygon = output;
      });
      return polygon.map(function (point) { var p = screenPoint(point, rect); p.world = point; return p; });
    }
    function pickVertex(event, context) {
      beforeRender(); var pointer = pointerRay(event), rect = pointer.rect, nearest = null, seen = new Set(), radius = 12;
      activeBindings(context).forEach(function (binding) {
        binding.baseIndex.forEach(function (vertex) {
          if (seen.has(vertex)) return; seen.add(vertex);
          var p = projectedVertex(binding, vertex, rect); if (p.z < -1 || p.z > 1) return;
          var distance = Math.hypot(p.x - event.clientX, p.y - event.clientY); if (distance > radius || nearest && distance > nearest.distance) return;
          // Surface occlusion uses the exact deformed triangles, avoiding rest
          // bounding spheres and the r128 morph + skin raycast issue.
          var ndc = new T.Vector2((p.x - rect.left) / rect.width * 2 - 1, 1 - (p.y - rect.top) / rect.height * 2); raycaster.setFromCamera(ndc, runtime.camera);
          var blocked = false;
          var hit = raycastAt({ clientX: p.x, clientY: p.y }, context, raycaster.ray); if (hit && hit.point.distanceTo(p.world) > 1e-5 && hit.distance + 1e-5 < raycaster.ray.origin.distanceTo(p.world)) blocked = true;
          if (!blocked) nearest = { vertex: vertex, binding: binding, distance: distance, point: p.world.clone() };
        });
      }); return nearest;
    }
    function paint(event, context) {
      var centreHit = hitSurface(event, context); if (!centreHit) return;
      var pointer = pointerRay(event), rect = pointer.rect, radius = Math.max(2, Math.min(200, context.radius || 20)), candidates = [], vertices = new Set();
      var triangleCircle = global.ViewerMeshTools && global.ViewerMeshTools.circleIntersectsTriangle;
      activeBindings(context).forEach(function (binding) {
        var faceCandidates = candidatesAt(context, binding, event.clientX, event.clientY, radius);
        for (var ci = 0; ci < faceCandidates.length; ci++) { var offset = faceCandidates[ci] * 3;
          var ids = [binding.geometry.index.getX(offset), binding.geometry.index.getX(offset + 1), binding.geometry.index.getX(offset + 2)];
          var screen = ids.map(function (v) { return projectedVertex(binding, v, rect); });
          var polygon = screen;
          if (screen.some(function (p) { return p.z < -1 || p.z > 1; })) { if (!nearClipEnabled()) continue; polygon = clippedScreenPolygon(screen, rect); }
          if (polygon.length < 3 || !polygon.slice(2).some(function (p, index) { return triangleCircle(event.clientX, event.clientY, radius, [polygon[0].x, polygon[0].y], [polygon[index + 1].x, polygon[index + 1].y], [p.x, p.y]); })) continue;
          var cx = polygon.reduce(function (sum, p) { return sum + p.x; }, 0) / polygon.length, cy = polygon.reduce(function (sum, p) { return sum + p.y; }, 0) / polygon.length;
          var probe = { clientX: cx, clientY: cy }, ray = pointerRay(probe).ray.clone(), nearest = null;
          nearest = raycastAt(probe, context, ray);
          if (!nearest || nearest.binding !== binding || nearest.faceIndex !== offset / 3) continue;
          var face = binding.faceMap[offset / 3]; candidates.push(face);
          ids.forEach(function (v, slot) { if (screen[slot].z >= -1 && screen[slot].z <= 1 && Math.hypot(screen[slot].x - event.clientX, screen[slot].y - event.clientY) <= radius) vertices.add(v); });
        }
      });
      if (context.modify && !vertices.size && centreHit) { var face = centreHit.face, ids = [face.a, face.b, face.c].filter(function (vertex) { var p = projectedVertex(centreHit.binding, vertex, rect); return !nearClipEnabled() || p.z >= -1 && p.z <= 1; }); ids.sort(function (a, b) { var pa = projectedVertex(centreHit.binding, a, rect), pb = projectedVertex(centreHit.binding, b, rect); return Math.hypot(pa.x - event.clientX, pa.y - event.clientY) - Math.hypot(pb.x - event.clientX, pb.y - event.clientY); }); if (ids.length) vertices.add(ids[0]); }
      if (options.onPaint) options.onPaint(context.modify ? Array.from(vertices) : candidates, !!context.erase, !!context.modify);
    }
    function updateCursor(event) {
      var context = sourceContext(); lastPointer = event;
      if (!brushCursor) return;
      var show = context && context.mesh && context.interactive !== false && context.mode === 'paint' && !event.altKey && !event.ctrlKey && !event.metaKey;
      brushCursor.hidden = !show;
      if (show) { var radius = Math.max(2, Math.min(200, context.radius || 20)); brushCursor.style.width = radius * 2 + 'px'; brushCursor.style.height = radius * 2 + 'px'; brushCursor.style.left = event.clientX - radius + 'px'; brushCursor.style.top = event.clientY - radius + 'px'; }
    }
    function startDrag(event, context, pick) {
      var axis = pick.axis || context.dragAxis;
      if (['x', 'y', 'z'].indexOf(axis) >= 0) {
        var frame = selectedFrame(context, pick.binding), axisIndex = ['x', 'y', 'z'].indexOf(axis); if (!frame) return;
        var vector = frame.vectors[axisIndex], magnitude = vector.length(); if (magnitude < 1e-12) return;
        var source = {}; context.mesh.selected.forEach(function (vertex) { source[vertex] = (context.mesh.positions[vertex] || context.mesh.data.positions[vertex]).slice(); });
        var origin = pointerRay(event), depth = Math.max(runtime.camera.near, viewDepth(frame.centre)), worldPixel = 2 * (runtime.camera.isOrthographicCamera ? 1 : depth) / Math.max(1e-12, origin.rect.height * Math.abs(runtime.camera.projectionMatrix.elements[5]));
        var from = screenPoint(frame.centre, origin.rect), to = screenPoint(frame.centre.clone().addScaledVector(vector, worldPixel * 60 / magnitude), origin.rect);
        var screenX = to.x - from.x, screenY = to.y - from.y, screenLength = Math.hypot(screenX, screenY);
        var drag = { axis: axisIndex, origin: frame.centre.clone(), vector: vector.clone(), positions: source, startX: event.clientX, startY: event.clientY,
          screenDirection: screenLength >= 8 ? [screenX / screenLength, screenY / screenLength] : [0, -1],
          pixelsPerUnit: screenLength >= 8 ? screenLength * magnitude / (worldPixel * 60) : magnitude / worldPixel };
        drag.anchor = axisRayAmount(origin.ray, drag); stroke.drag = drag; return;
      }
      var ray = pointerRay(event).ray, normal = runtime.camera.getWorldDirection(new T.Vector3()), plane = new T.Plane().setFromNormalAndCoplanarPoint(normal, pick.point), anchor = ray.intersectPlane(plane, new T.Vector3());
      if (!anchor) return;
      var sourcePositions = {}, inverse = {}, list = activeBindings(context), binding = pick.binding;
      context.mesh.selected.forEach(function (vertex) {
        sourcePositions[vertex] = (context.mesh.positions[vertex] || context.mesh.data.positions[vertex]).slice();
        var linear = sourceLinear(binding, vertex); if (Math.abs(linear.determinant()) < 1e-12) return;
        inverse[vertex] = linear.invert();
      });
      stroke.drag = { plane: plane, anchor: anchor, positions: sourcePositions, inverse: inverse };
    }
    function axisRayAmount(ray, drag) {
      var a = drag.vector.lengthSq(), b = drag.vector.dot(ray.direction), relative = drag.origin.clone().sub(ray.origin), denominator = a - b * b;
      if (denominator < a * 1e-5) return null;
      return (b * ray.direction.dot(relative) - drag.vector.dot(relative)) / denominator;
    }
    function endStroke(cancel) {
      if (!stroke) return;
      var previous = stroke; stroke = null;
      if (runtime && runtime.controls) runtime.controls.enabled = previous.controlsEnabled;
      if (options.onEnd) options.onEnd(!!cancel); notify(); request();
    }
    function attachPointer() {
      var canvas = runtime.domElement || runtime.renderer.domElement;
      brushCursor = document.createElement('div'); brushCursor.id = 'viewer-mesh-brush-cursor'; brushCursor.hidden = true; brushCursor.setAttribute('aria-hidden', 'true');
      brushCursor.style.cssText = 'position:fixed;z-index:12000;pointer-events:none;border:2px solid #ffdb52;box-shadow:0 0 0 1px #17202b;border-radius:50%;box-sizing:border-box;'; document.body.appendChild(brushCursor);
      listen(canvas, 'pointerdown', function (event) {
        var context = sourceContext(); if (!context || !context.mesh || context.mode === 'orbit' || context.interactive === false || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey) return;
        if (!activeBindings(context).length) return;
        var pick = context.mode === 'drag' && pickGizmo(event, context) || (context.mode === 'pick' || context.mode === 'drag' ? pickVertex(event, context) : hitSurface(event, context));
        if (!pick) return;
        event.preventDefault(); event.stopImmediatePropagation();
        if (!canvas.hasAttribute('tabindex')) canvas.tabIndex = 0; canvas.focus({ preventScroll: true });
        if (options.onBegin) options.onBegin();
        stroke = { pointerId: event.pointerId, controlsEnabled: runtime.controls ? runtime.controls.enabled : true, previous: { clientX: event.clientX, clientY: event.clientY } };
        if (runtime.controls) runtime.controls.enabled = false; canvas.setPointerCapture(event.pointerId);
        if (context.mode === 'paint') paint(event, context);
        else if (context.mode === 'connected') { if (options.onConnected) options.onConnected(pick.sourceFace, !!context.erase, !!event.shiftKey); }
        else { if (!pick.gizmo && options.onSelect) options.onSelect(pick.vertex, !!event.shiftKey, context.mode === 'drag'); if (context.mode === 'drag') startDrag(event, sourceContext(), pick); }
        notify(); request();
      }, true);
      listen(canvas, 'pointermove', function (event) {
        updateCursor(event); if (!stroke || stroke.pointerId !== event.pointerId) return;
        event.preventDefault(); event.stopImmediatePropagation(); var context = sourceContext(); if (!context || context.interactive === false || context.mode === 'orbit') { endStroke(true); return; }
        if (stroke.drag) {
          var values = {}, drag = stroke.drag;
          if (drag.axis !== undefined) {
            var amount = axisRayAmount(pointerRay(event).ray, drag), delta = amount !== null && drag.anchor !== null ? amount - drag.anchor :
              ((event.clientX - drag.startX) * drag.screenDirection[0] + (event.clientY - drag.startY) * drag.screenDirection[1]) / drag.pixelsPerUnit;
            if (Number.isFinite(delta) && (drag.moved || Math.abs(delta) > 1e-12)) { drag.moved = true; Object.keys(drag.positions).forEach(function (vertex) { var position = drag.positions[vertex].slice(); position[drag.axis] += delta; values[vertex] = position; }); }
          } else {
            var point = pointerRay(event).ray.intersectPlane(drag.plane, new T.Vector3());
            if (point) { var deltaWorld = point.sub(drag.anchor); Object.keys(drag.inverse).forEach(function (vertex) { var local = deltaWorld.clone().applyMatrix3(drag.inverse[vertex]); values[vertex] = drag.positions[vertex].map(function (value, axis) { return value + local.getComponent(axis); }); }); }
          }
          if (Object.keys(values).length && options.onDrag) options.onDrag(values);
        } else if (context.mode === 'paint') {
          var previous = stroke.previous, distance = Math.hypot(event.clientX - previous.clientX, event.clientY - previous.clientY), steps = Math.min(24, Math.max(1, Math.ceil(distance / Math.max(2, context.radius / 2))));
          for (var i = 1; i <= steps; i++) paint({ clientX: previous.clientX + (event.clientX - previous.clientX) * i / steps, clientY: previous.clientY + (event.clientY - previous.clientY) * i / steps }, context);
        }
        if (stroke) stroke.previous = { clientX: event.clientX, clientY: event.clientY }; request();
      }, true);
      ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (eventName) { listen(canvas, eventName, function (event) { if (!stroke || stroke.pointerId !== event.pointerId) return; event.preventDefault(); event.stopImmediatePropagation(); endStroke(eventName !== 'pointerup'); }, true); });
      listen(canvas, 'pointerleave', function () { if (brushCursor && !stroke) brushCursor.hidden = true; });
      listen(canvas, 'contextmenu', function (event) { var context = sourceContext(); if (context && context.mode !== 'orbit') event.preventDefault(); });
    }
    function inspect() {
      var context = sourceContext(); return { boundPrimitives: bindings.length, mode: context && context.mode || 'orbit',
        highlightedFaces: overlayRefs.length / 3, vertexDots: pointVertices.length, selectedVertices: context && context.mesh ? context.mesh.selected.size : 0,
        activeStroke: !!stroke, cursorVisible: !!brushCursor && !brushCursor.hidden, performance: Object.assign({}, performanceState),
        gizmo: { visible: gizmoState.visible, centre: gizmoState.centre, handles: gizmoState.handles.map(function (handle) { return { axis: handle.axis, x: handle.x, y: handle.y, start: handle.start, end: handle.end, world: handle.world }; }) },
        bindings: bindings.map(function (b) { return { mesh: b.map.mesh, submesh: b.map.submesh, triangles: b.faceMap.length,
          vertexCount: b.geometry.attributes.position.count, selectedFaces: b.data.marked ? Array.from(b.data.marked) : [],
          samplePositions: Array.from(b.geometry.attributes.position.array.slice(0, 24)), sampleWeights: b.geometry.attributes.skinWeight ? Array.from(b.geometry.attributes.skinWeight.array.slice(0, 24)) : [] }; }) };
    }
    function screenVertex(mesh, vertex) {
      var list = boundKeys[identityKey(mesh)] || []; if (!adoptRuntime() || !list.length) return null;
      beforeRender(); var rect = (runtime.domElement || runtime.renderer.domElement).getBoundingClientRect();
      var p = projectedVertex(list[0], vertex, rect); return { x: p.x, y: p.y, depth: p.z, world: p.world.toArray() };
    }
    return { sync: sync, beforeRender: beforeRender, reset: reset, getState: inspect, projectVertex: screenVertex,
      dispose: function () { disposed = true; reset(); } };
  }
  global.ViewerMeshRuntime = { create: create, vertexLocal: vertexLocal, vertexWorld: vertexWorld, worldSnapshot: worldSnapshot, skinMatrix: skinMatrix, raycastMesh: raycastMesh };
})(window);
