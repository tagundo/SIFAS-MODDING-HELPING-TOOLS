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
      if (overlayRoot) { overlayRoot.parent.remove(overlayRoot); overlayRoot.traverse(function (child) { if (child.geometry) child.geometry.dispose(); if (child.material) child.material.dispose(); }); }
      overlayRoot = null; overlayGeometry = null; overlay = null; pointGeometry = null; points = null; selectedPoints = null; pointSelectionGeometry = null;
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
      if (disposed) return; syncedData = items || syncedData;
      if (!adoptRuntime()) return;
      syncedData.forEach(bind); bindings.forEach(apply); updateVersion++; rebuildOverlay(); beforeRender(); request();
    }
    function world(binding, vertex) {
      var id = binding.mesh.uuid, values = worldVertices[id] || (worldVertices[id] = []);
      return values[vertex] || (values[vertex] = vertexWorld(binding.mesh, vertex));
    }
    function visible(mesh) { for (var node = mesh; node; node = node.parent) if (!node.visible) return false; return true; }
    function beforeRender() {
      if (disposed || !adoptRuntime()) return;
      var context = sourceContext(); if (!context || !context.mesh) { if (overlayRoot) overlayRoot.visible = false; return; }
      var list = boundKeys[identityKey(context.mesh.data.mesh)] || [];
      if (!list.length) { if (overlayRoot) overlayRoot.visible = false; return; }
      if (overlayRoot) overlayRoot.visible = true;
      runtime.model.updateMatrixWorld(true); worldVertices = {}; projectionCache = null;
      if (overlayGeometry) { var pos = overlayGeometry.attributes.position; overlayRefs.forEach(function (entry, i) { var v = world(entry.binding, entry.vertex); pos.setXYZ(i, v.x, v.y, v.z); }); pos.needsUpdate = true; overlay.visible = context.showSelection && overlayRefs.length > 0; }
      if (pointGeometry) { var p = pointGeometry.attributes.position; pointVertices.forEach(function (entry, i) { var v = world(entry.binding, entry.vertex); p.setXYZ(i, v.x, v.y, v.z); }); p.needsUpdate = true; points.visible = context.showVertices && pointVertices.length > 0; }
      if (pointSelectionGeometry) { var chosen = pointSelectionGeometry.attributes.position, first = list[0], n = 0; context.mesh.selected.forEach(function (vertex) { var v = world(first, vertex); chosen.setXYZ(n++, v.x, v.y, v.z); }); chosen.needsUpdate = true; selectedPoints.visible = context.showVertices && context.mesh.selected.size > 0; }
      lastBindingsVersion = updateVersion;
    }
    function activeBindings(context) { return (boundKeys[identityKey(context.mesh.data.mesh)] || []).filter(function (binding) { return visible(binding.mesh) && (context.submesh === undefined || binding.map.submesh === context.submesh); }); }
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
      if (projectionCache) return projectionCache;
      var rect = (runtime.domElement || runtime.renderer.domElement).getBoundingClientRect(), cols = Math.max(1, Math.ceil(rect.width / 32));
      var result = { rect: rect, cols: cols, bindings: {}, surfaces: surfaceBindings() };
      result.surfaces.forEach(function (binding) {
        if (!visible(binding.mesh)) return;
        var entry = { points: {}, bins: {}, binding: binding };
        function point(vertex) { return entry.points[vertex] || (entry.points[vertex] = projectedVertex(binding, vertex, rect)); }
        var indices = binding.geometry.index, indexCount = indices ? indices.count : binding.geometry.attributes.position.count;
        for (var offset = 0; offset < indexCount; offset += 3) {
          var tri = [point(indices ? indices.getX(offset) : offset), point(indices ? indices.getX(offset + 1) : offset + 1), point(indices ? indices.getX(offset + 2) : offset + 2)];
          if (tri.some(function (p) { return p.z < -1 || p.z > 1; })) continue;
          var minX = Math.max(0, Math.floor((Math.min(tri[0].x, tri[1].x, tri[2].x) - rect.left) / 32)), maxX = Math.min(cols - 1, Math.floor((Math.max(tri[0].x, tri[1].x, tri[2].x) - rect.left) / 32));
          var minY = Math.max(0, Math.floor((Math.min(tri[0].y, tri[1].y, tri[2].y) - rect.top) / 32)), maxY = Math.min(Math.ceil(rect.height / 32) - 1, Math.floor((Math.max(tri[0].y, tri[1].y, tri[2].y) - rect.top) / 32));
          for (var x = minX; x <= maxX; x++) for (var y = minY; y <= maxY; y++) { var key = x + y * cols; if (!entry.bins[key]) entry.bins[key] = []; entry.bins[key].push(offset / 3); }
        }
        result.bindings[binding.mesh.uuid] = entry;
      }); projectionCache = result; return result;
    }
    function candidatesAt(context, binding, x, y, radius) {
      var cache = projection(context), entry = cache.bindings[binding.mesh.uuid], set = new Set(); if (!entry) return [];
      for (var gx = Math.max(0, Math.floor((x - radius - cache.rect.left) / 32)); gx <= Math.min(cache.cols - 1, Math.floor((x + radius - cache.rect.left) / 32)); gx++)
        for (var gy = Math.max(0, Math.floor((y - radius - cache.rect.top) / 32)); gy <= Math.min(Math.ceil(cache.rect.height / 32) - 1, Math.floor((y + radius - cache.rect.top) / 32)); gy++)
          (entry.bins[gx + gy * cache.cols] || []).forEach(function (face) { set.add(face); });
      return Array.from(set);
    }
    function raycastAt(event, context, ray) {
      var nearest = null;
      projection(context).surfaces.forEach(function (binding) {
        if (!visible(binding.mesh)) return;
        var hit = raycastMesh(ray, binding.mesh, { vertices: worldVertices[binding.mesh.uuid] || [], faceIndices: candidatesAt(context, binding, event.clientX, event.clientY, 0) });
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
          if (screen.some(function (p) { return p.z < -1 || p.z > 1; })) continue;
          if (!triangleCircle(event.clientX, event.clientY, radius, [screen[0].x, screen[0].y], [screen[1].x, screen[1].y], [screen[2].x, screen[2].y])) continue;
          var cx = screen.reduce(function (sum, p) { return sum + p.x; }, 0) / 3, cy = screen.reduce(function (sum, p) { return sum + p.y; }, 0) / 3;
          var probe = { clientX: cx, clientY: cy }, ray = pointerRay(probe).ray.clone(), nearest = null;
          nearest = raycastAt(probe, context, ray);
          if (!nearest || nearest.binding !== binding || nearest.faceIndex !== offset / 3) continue;
          var face = binding.faceMap[offset / 3]; candidates.push(face);
          ids.forEach(function (v, slot) { if (Math.hypot(screen[slot].x - event.clientX, screen[slot].y - event.clientY) <= radius) vertices.add(v); });
        }
      });
      if (context.modify && !vertices.size && centreHit) { var face = centreHit.face, ids = [face.a, face.b, face.c]; ids.sort(function (a, b) { var pa = projectedVertex(centreHit.binding, a, rect), pb = projectedVertex(centreHit.binding, b, rect); return Math.hypot(pa.x - event.clientX, pa.y - event.clientY) - Math.hypot(pb.x - event.clientX, pb.y - event.clientY); }); vertices.add(ids[0]); }
      if (options.onPaint) options.onPaint(context.modify ? Array.from(vertices) : candidates, !!context.erase, !!context.modify);
    }
    function updateCursor(event) {
      var context = sourceContext(); lastPointer = event;
      if (!brushCursor) return;
      var show = context && context.mesh && context.mode === 'paint' && !event.altKey && !event.ctrlKey && !event.metaKey;
      brushCursor.hidden = !show;
      if (show) { var radius = Math.max(2, Math.min(200, context.radius || 20)); brushCursor.style.width = radius * 2 + 'px'; brushCursor.style.height = radius * 2 + 'px'; brushCursor.style.left = event.clientX - radius + 'px'; brushCursor.style.top = event.clientY - radius + 'px'; }
    }
    function startDrag(event, context, pick) {
      var ray = pointerRay(event).ray, normal = runtime.camera.getWorldDirection(new T.Vector3()), plane = new T.Plane().setFromNormalAndCoplanarPoint(normal, pick.point), anchor = ray.intersectPlane(plane, new T.Vector3());
      if (!anchor) return;
      var sourcePositions = {}, inverse = {}, list = activeBindings(context), binding = pick.binding;
      context.mesh.selected.forEach(function (vertex) {
        sourcePositions[vertex] = (context.mesh.positions[vertex] || context.mesh.data.positions[vertex]).slice();
        var forward = new T.Matrix4().copy(binding.mesh.matrixWorld).multiply(skinMatrix(binding.mesh, vertex)).multiply(binding.positionMatrix);
        var linear = new T.Matrix3().setFromMatrix4(forward); if (Math.abs(linear.determinant()) < 1e-12) return;
        inverse[vertex] = linear.invert();
      });
      stroke.drag = { plane: plane, anchor: anchor, positions: sourcePositions, inverse: inverse };
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
        var pick = context.mode === 'pick' || context.mode === 'drag' ? pickVertex(event, context) : hitSurface(event, context);
        if (!pick) return;
        event.preventDefault(); event.stopImmediatePropagation();
        if (!canvas.hasAttribute('tabindex')) canvas.tabIndex = 0; canvas.focus({ preventScroll: true });
        if (options.onBegin) options.onBegin();
        stroke = { pointerId: event.pointerId, controlsEnabled: runtime.controls ? runtime.controls.enabled : true, previous: { clientX: event.clientX, clientY: event.clientY } };
        if (runtime.controls) runtime.controls.enabled = false; canvas.setPointerCapture(event.pointerId);
        if (context.mode === 'paint') paint(event, context);
        else { if (options.onSelect) options.onSelect(pick.vertex, !!event.shiftKey, context.mode === 'drag'); if (context.mode === 'drag') startDrag(event, sourceContext(), pick); }
        notify(); request();
      }, true);
      listen(canvas, 'pointermove', function (event) {
        updateCursor(event); if (!stroke || stroke.pointerId !== event.pointerId) return;
        event.preventDefault(); event.stopImmediatePropagation(); var context = sourceContext(); if (!context) return;
        if (stroke.drag) {
          var point = pointerRay(event).ray.intersectPlane(stroke.drag.plane, new T.Vector3());
          if (point) { var delta = point.sub(stroke.drag.anchor), values = {}; Object.keys(stroke.drag.inverse).forEach(function (vertex) { var local = delta.clone().applyMatrix3(stroke.drag.inverse[vertex]); values[vertex] = stroke.drag.positions[vertex].map(function (value, axis) { return value + local.getComponent(axis); }); }); if (options.onDrag) options.onDrag(values); }
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
        activeStroke: !!stroke, cursorVisible: !!brushCursor && !brushCursor.hidden,
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
  global.ViewerMeshRuntime = { create: create, vertexLocal: vertexLocal, vertexWorld: vertexWorld, skinMatrix: skinMatrix, raycastMesh: raycastMesh };
})(window);
