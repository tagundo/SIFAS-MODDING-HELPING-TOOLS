/* Automatic SDK costume thumbnail: isolated high-quality WebGL and PSD layers. */
(function (global) {
  'use strict';
  var active = false, last = null, lastReceipts = [];
  var ROOT = '/static/thumbnail-sdk/';
  var MAX_GLB = 96 * 1024 * 1024;
  function fail(message) { throw new Error(message); }
  function stopped(signal) { if (signal && signal.aborted) { var e = new Error('Thumbnail rendering cancelled.'); e.name = 'AbortError'; throw e; } }
  async function api(action, body, signal) {
    stopped(signal);
    var response = await global.fetch('/api/viewer/thumbnail/' + action, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: signal });
    var result = await response.json();
    if (!response.ok || result.error) fail(result.error || 'The automatic 3D thumbnail could not be prepared.');
    return result;
  }
  function image(url, signal) {
    return new Promise(function (resolve, reject) {
      stopped(signal); var result = new Image(), settled = false;
      function cleanup() { result.onload = result.onerror = null; if (signal) signal.removeEventListener('abort', abort); }
      function abort() {
        if (settled) return; settled = true; cleanup();
        if (typeof result.removeAttribute === 'function') result.removeAttribute('src'); else result.src = '';
        var error = new Error('Thumbnail rendering cancelled.'); error.name = 'AbortError'; reject(error);
      }
      result.onload = function () { if (settled) return; if (signal && signal.aborted) return abort(); settled = true; cleanup(); resolve(result); };
      result.onerror = function () { if (settled) return; settled = true; cleanup(); reject(new Error('The SDK thumbnail template could not be loaded.')); };
      if (signal) { signal.addEventListener('abort', abort, { once: true }); if (signal.aborted) return abort(); }
      result.src = url;
    });
  }
  function canvas(size) { var result = document.createElement('canvas'); result.width = result.height = size; return result; }
  async function compose(profile, member, subject, size, signal) {
    var result = canvas(size), ctx = result.getContext('2d', { willReadFrequently: true });
    if (!ctx || !/^#[a-f0-9]{6}$/i.test(profile.memberColors[String(member)] || '')) fail('The target member has no SDK thumbnail color.');
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.fillStyle = profile.memberColors[String(member)]; ctx.fillRect(0, 0, size, size);
    for (var i = 0; i < profile.layers.length; i++) {
      var layer = profile.layers[i]; stopped(signal);
      if (!/^[a-z-]+\.png$/.test(layer.file) || ['source-over', 'screen'].indexOf(layer.blend) < 0) fail('The SDK thumbnail layer is invalid.');
      ctx.globalCompositeOperation = layer.blend; ctx.globalAlpha = layer.opacity;
      ctx.drawImage(await image(ROOT + layer.file, signal), 0, 0, size, size);
    }
    ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
    // The source PSD's Gradient belongs behind the costume, inside Border In.
    if (subject) ctx.drawImage(subject, 0, 0, size, size);
    ctx.globalCompositeOperation = 'destination-in'; ctx.drawImage(await image(ROOT + profile.innerMask, signal), 0, 0, size, size);
    ctx.globalCompositeOperation = 'source-over'; ctx.drawImage(await image(ROOT + profile.outerBorder, signal), 0, 0, size, size);
    return result;
  }
  function disposeModel(model) {
    var geometries = new Set(), materials = new Set(), textures = new Set(), images = new Set();
    if (!model) return;
    model.traverse(function (node) {
      if (node.geometry) geometries.add(node.geometry);
      (Array.isArray(node.material) ? node.material : [node.material]).forEach(function (material) {
        if (!material) return; materials.add(material);
        Object.keys(material).forEach(function (key) { var value = material[key]; if (value && value.isTexture) textures.add(value); });
      });
    });
    geometries.forEach(function (g) { g.dispose(); });
    textures.forEach(function (t) { if (t.image) images.add(t.image); t.dispose(); });
    materials.forEach(function (m) { m.dispose(); });
    images.forEach(function (i) { if (typeof i.close === 'function') i.close(); });
  }
  function hidden(mesh, exclusions) {
    var mapping = mesh.geometry && mesh.geometry.userData && mesh.geometry.userData.viewerMesh || mesh.userData && mesh.userData.viewerMesh;
    if (mapping && (exclusions || []).some(function (entry) {
      if (entry.renderer !== mapping.renderer || entry.mesh.source !== mapping.mesh.source ||
          entry.mesh.file !== mapping.mesh.file || entry.mesh.id !== mapping.mesh.id) return false;
      if (!entry.rendererIdentity) return true;
      if (!mapping.rendererIdentity) fail('Reload the editor before rendering this thumbnail.');
      return entry.rendererIdentity.source === mapping.rendererIdentity.source &&
        entry.rendererIdentity.file === mapping.rendererIdentity.file && entry.rendererIdentity.id === mapping.rendererIdentity.id;
    })) return true;
    if (mesh.userData && mesh.userData.hidden_default) return true;
    // Names in the GLB are not authority for dropping costume decorations.
    return false;
  }
  function applySavedSettings(root, info) {
    var nodes = {}, groups = {}, operations = [], skipped = 0, conflicts = 0;
    var scaling = info && (info.scaling || info.controls) || {};
    root.traverse(function (object) {
      if (object.userData && object.userData.viewerHelper) return;
      if (object.isSkinnedMesh) object.frustumCulled = false;
      var index = object.userData && object.userData.elichika_node;
      if (index !== undefined) nodes[String(index)] = object;
    });
    (scaling.components || []).forEach(function (component) {
      (component.entries || []).forEach(function (entry) {
        var rotation = entry.kind === 'rotation', values = rotation ? entry.scaledQuaternion : entry.scaled;
        var application = rotation ? 'absolute_local_quaternion' : 'absolute_local_' + entry.kind;
        var valid = info && info.available === true && entry.supported === true &&
          ['scale', 'position', 'rotation'].indexOf(entry.kind) >= 0 && entry.application === application &&
          nodes[String(entry.node)] && Array.isArray(values) && values.length === (rotation ? 4 : 3) &&
          values.every(function (value) { return typeof value === 'number' && isFinite(value); });
        if (valid && rotation) valid = Math.abs(values.reduce(function (sum, value) { return sum + value * value; }, 0) - 1) <= 1e-3;
        if (!valid || entry.kind === 'scale' && values.some(function (value) { return Math.abs(value) < 1e-8; })) { skipped++; return; }
        var key = String(entry.node) + ':' + entry.kind;
        if (!groups[key]) groups[key] = [];
        groups[key].push({ node: String(entry.node), kind: entry.kind, value: values.slice(), name: entry.name || nodes[String(entry.node)].name });
      });
    });
    Object.keys(groups).forEach(function (key) {
      var values = groups[key], first = values[0];
      if (values.some(function (entry) {
        var direct = Math.max.apply(null, entry.value.map(function (value, axis) { return Math.abs(value - first.value[axis]); }));
        var antipodal = first.kind === 'rotation' ? Math.max.apply(null, entry.value.map(function (value, axis) { return Math.abs(value + first.value[axis]); })) : Infinity;
        return Math.min(direct, antipodal) > 1e-6;
      })) { conflicts++; skipped += values.length; return; }
      // Same absolute local endpoints as ViewerRig's default savedOperations.
      // An already exported value is assigned again, never multiplied twice.
      nodes[first.node][first.kind === 'rotation' ? 'quaternion' : first.kind === 'scale' ? 'scale' : 'position'].fromArray(first.value);
      operations.push(first);
    });
    root.updateMatrixWorld(true);
    return { enabled: operations.length > 0, operations: operations, skipped: skipped, conflicts: conflicts,
      metadataWarnings: Array.isArray(scaling.warnings) ? scaling.warnings.slice() : [],
      nodes: Object.keys(groups).map(function (key) { return key.split(':')[0]; }).filter(function (id, index, all) { return all.indexOf(id) === index; }).map(function (id) {
        var object = nodes[id]; return { node: id, name: object.name, position: object.position.toArray(), quaternion: object.quaternion.toArray(), scale: object.scale.toArray() };
      }) };
  }
  function frameCharacter(model, camera, source, fitFull) {
    var T = global.THREE, direction = new T.Vector3().fromArray(source.direction).normalize();
    var right = new T.Vector3().crossVectors(direction, camera.up).normalize();
    var up = new T.Vector3().crossVectors(right, direction).normalize();
    var low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity], vertices = 0;
    model.updateMatrixWorld(true);
    model.traverse(function (mesh) { if (mesh.isSkinnedMesh && mesh.skeleton) mesh.skeleton.update(); });
    var original = new T.Vector3(), point = new T.Vector3(), delta = new T.Vector3();
    var skinIndices = new T.Vector4(), skinWeights = new T.Vector4(), transformed = new T.Vector3(), weighted = new T.Vector3(), boneMatrix = new T.Matrix4();
    model.traverseVisible(function (mesh) {
      if (!mesh.isMesh || mesh.userData && mesh.userData.viewerHelper || !mesh.geometry || !mesh.geometry.attributes.position) return;
      var geometry = mesh.geometry, positions = geometry.attributes.position, morphs = geometry.morphAttributes.position || [];
      var count = geometry.index ? geometry.index.count : positions.count, range = geometry.drawRange || { start: 0, count: Infinity };
      var start = Math.max(0, range.start), end = Math.min(count, start + range.count), seen = new Set();
      for (var at = start; at < end; at++) {
        var i = geometry.index ? geometry.index.getX(at) : at; if (seen.has(i)) continue; seen.add(i);
        original.fromBufferAttribute(positions, i); point.copy(original);
        morphs.forEach(function (morph, index) {
          var influence = mesh.morphTargetInfluences && mesh.morphTargetInfluences[index] || 0;
          if (!influence) return;
          delta.fromBufferAttribute(morph, i); if (!geometry.morphTargetsRelative) delta.sub(original);
          point.addScaledVector(delta, influence);
        });
        if (mesh.isSkinnedMesh) {
          // r128's boneTransform reloads the bind position and discards morph
          // deltas. Apply the shader's skin matrices to the morphed point.
          skinIndices.fromBufferAttribute(geometry.attributes.skinIndex, i);
          skinWeights.fromBufferAttribute(geometry.attributes.skinWeight, i);
          point.applyMatrix4(mesh.bindMatrix); weighted.set(0, 0, 0);
          for (var slot = 0; slot < 4; slot++) {
            var weight = skinWeights.getComponent(slot); if (!weight) continue;
            var bone = skinIndices.getComponent(slot);
            boneMatrix.multiplyMatrices(mesh.skeleton.bones[bone].matrixWorld, mesh.skeleton.boneInverses[bone]);
            weighted.addScaledVector(transformed.copy(point).applyMatrix4(boneMatrix), weight);
          }
          point.copy(weighted).applyMatrix4(mesh.bindMatrixInverse);
        }
        point.applyMatrix4(mesh.matrixWorld);
        var values = [point.dot(right), point.dot(up), point.dot(direction)];
        if (!values.every(isFinite)) fail('The character has invalid thumbnail positions.');
        values.forEach(function (value, axis) { low[axis] = Math.min(low[axis], value); high[axis] = Math.max(high[axis], value); });
        vertices++;
      }
    });
    if (!vertices) fail('No character geometry is available for its thumbnail.');
    var wholeLow = low.slice(), wholeHigh = high.slice();
    // The default is a larger face/upper-costume view. Preserve the complete
    // horizontal extent so hands and outfit details are not cut at the sides.
    // Full-character fitting is a separate opt-in framing policy.
    if (!fitFull) low[1] = Math.max(low[1], high[1] - Math.max(source.top - source.bottom, (high[1] - low[1]) * .65));
    var half = Math.max((source.right - source.left) / 2, (source.top - source.bottom) / 2,
      (high[0] - low[0]) / 2 * 1.12, (high[1] - low[1]) / 2 * 1.12, .001);
    camera.left = camera.bottom = -half; camera.right = camera.top = half;
    camera.position.fromArray(source.position);
    camera.position.addScaledVector(right, (low[0] + high[0]) / 2 - camera.position.dot(right));
    camera.position.addScaledVector(up, (low[1] + high[1]) / 2 - camera.position.dot(up));
    var front = low[2] - camera.position.dot(direction), margin = Math.max(.01, source.near * .1);
    if (front < source.near + margin) camera.position.addScaledVector(direction, front - source.near - margin);
    camera.far = Math.max(source.far, high[2] - camera.position.dot(direction) + margin);
    camera.lookAt(camera.position.clone().add(direction)); camera.updateProjectionMatrix(); camera.updateMatrixWorld(true);
    return { mode: fitFull ? 'full-character' : 'head-and-upper-body', fitFullCharacter: !!fitFull,
      vertices: vertices, minimum: low, maximum: high, wholeMinimum: wholeLow, wholeMaximum: wholeHigh, upperFraction: .65, padding: .12,
      sourceCamera: JSON.parse(JSON.stringify(source)), camera: { position: camera.position.toArray(), direction: direction.toArray(),
        up: camera.up.toArray(), left: camera.left, right: camera.right, top: camera.top, bottom: camera.bottom, near: camera.near, far: camera.far } };
  }
  async function renderSubject(prepared, profile, size, signal) {
    var T = global.THREE, renderer, quality, material, model;
    if (!T || !T.GLTFLoader || !global.ViewerQuality || !global.SifasMaterial) fail('The high-quality 3D thumbnail renderer is unavailable.');
    if (typeof prepared.url !== 'string' || !/^\/api\/viewer\/model\/[a-f0-9_-]+\.glb$/.test(prepared.url)) fail('The thumbnail model response is invalid.');
    try {
      stopped(signal);
      var response = await global.fetch(prepared.url, { signal: signal });
      if (!response.ok || Number(response.headers.get('Content-Length')) > MAX_GLB) fail('The thumbnail model is unavailable or too large.');
      var data = await response.arrayBuffer(); if (data.byteLength > MAX_GLB) fail('The thumbnail model is too large.');
      var gltf = await new Promise(function (resolve, reject) { new T.GLTFLoader().parse(data, '', resolve, reject); });
      model = gltf.scene; stopped(signal);
      var savedNodes = applySavedSettings(model, prepared.rig || {});
      renderer = new T.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true, premultipliedAlpha: false, powerPreference: 'high-performance' });
      renderer.outputEncoding = T.sRGBEncoding; renderer.toneMapping = T.NoToneMapping; renderer.setClearColor(0, 0);
      quality = global.ViewerQuality.create(renderer); quality.setEnabled(true);
      // Supersample only the subject, preserving the PSD's native layer edges.
      var renderSize = Math.min(1024, Math.max(512, size * 2)); quality.resize(renderSize, renderSize);
      var scene = new T.Scene(); scene.background = null; scene.add(model);
      scene.add(new T.HemisphereLight(0xffffff, 0x737b89, .85));
      var key = new T.DirectionalLight(0xffffff, .9); key.position.set(-2, 3, 4); scene.add(key);
      var fill = new T.DirectionalLight(0xffffff, .35); fill.position.set(3, 1, -3); scene.add(fill);
      var visibleMeshes = 0, excludedNames = [], visibleNames = [];
      model.traverse(function (mesh) {
        if (!mesh.isMesh) return;
        if (hidden(mesh, prepared.excludedMeshes)) { mesh.visible = false; excludedNames.push(mesh.name); }
        else {
          visibleMeshes++; visibleNames.push(mesh.name);
          (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach(function (original) {
            var data = original && original.userData && original.userData.sifas;
            if (data && (data.limitations || []).some(function (text) { return /texture unavailable: _MainTex/.test(text); }))
              fail('The costume main texture could not be decoded. The automatic 3D thumbnail was not saved.');
          });
        }
      });
      // Costume thumbnails use a fixed material profile, independent of the
      // live viewer's lighting preference. The raw material API defaults on.
      material = global.SifasMaterial.apply(model, renderer, { parser: gltf.parser, enabled: true, rimlight: false });
      if (material.ready) await material.ready;
      stopped(signal);
      var p = profile.camera, camera = new T.OrthographicCamera(p.left, p.right, p.top, p.bottom, p.near, p.far);
      camera.position.fromArray(p.position); camera.up.fromArray(p.up);
      camera.lookAt(new T.Vector3().fromArray(p.position).add(new T.Vector3().fromArray(p.direction)));
      camera.updateProjectionMatrix(); model.updateMatrixWorld(true);
      var framing = frameCharacter(model, camera, p, prepared.subject === 'full-character-v1');
      quality.render(scene, camera); var info = quality.render(scene, camera);
      var gl = renderer.getContext(); if (gl.isContextLost()) fail('The 3D thumbnail graphics context was lost.');
      if (quality.readGLError() !== gl.NO_ERROR) fail('The high-quality 3D thumbnail could not be rendered.');
      var output = canvas(size), ctx = output.getContext('2d', { willReadFrequently: true });
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high'; ctx.drawImage(renderer.domElement, 0, 0, size, size);
      var pixels = ctx.getImageData(0, 0, size, size).data, subjectPixels = 0;
      var subjectBounds = { left: size, top: size, right: -1, bottom: -1 };
      for (var i = 3; i < pixels.length; i += 4) if (pixels[i] > 8) {
        subjectPixels++; var pixel = (i - 3) / 4, x = pixel % size, y = Math.floor(pixel / size);
        subjectBounds.left = Math.min(subjectBounds.left, x); subjectBounds.right = Math.max(subjectBounds.right, x);
        subjectBounds.top = Math.min(subjectBounds.top, y); subjectBounds.bottom = Math.max(subjectBounds.bottom, y);
      }
      // ViewerQuality returns scene statistics before its final copy triangle.
      var state = quality.getState(), triangles = info.triangles;
      if (!subjectPixels || !triangles || !state.enabled || !state.ready) fail('No costume is visible in the SDK thumbnail camera.');
      return { canvas: output, report: { quality: state, subjectPixels: subjectPixels, subjectBounds: subjectBounds, triangles: triangles,
        material: material.getState ? material.getState() : null, camera: framing.camera, framing: framing,
        pose: 'source-rest', animation: false, sourceStats: prepared.stats, savedNodes: savedNodes, faces: prepared.faces || {}, faceSources: prepared.faceSources || [],
        excludedMeshes: prepared.excludedMeshes || [], excludedNames: excludedNames, visibleNames: visibleNames, visibleMeshes: visibleMeshes,
        lighting: { hemisphere: [0xffffff, 0x737b89, .85], key: { color: 0xffffff, intensity: .9, position: [-2, 3, 4] }, fill: { color: 0xffffff, intensity: .35, position: [3, 1, -3] } } } };
    } finally {
      if (material) material.dispose();
      disposeModel(model);
      if (quality) quality.dispose();
      if (renderer) { renderer.dispose(); renderer.forceContextLoss(); }
    }
  }
  async function renderPlan(plan, options) {
    options = options || {}; var signal = options.signal;
    if (active) fail('Another automatic thumbnail is rendering. Wait for it to finish.');
    active = true; last = null; lastReceipts = [];
    var results = [];
    try {
      var response = await global.fetch(plan.profileUrl, { signal: signal });
      if (!response.ok) fail('The SDK thumbnail profile could not be loaded.');
      var profile = await response.json();
      for (var i = 0; i < plan.items.length; i++) {
        stopped(signal); var item = plan.items[i];
        if (options.onProgress) options.onProgress(i, plan.items.length, item.name);
        var prepared = await api('model', { token: plan.token, item_id: item.id }, signal);
        if (prepared.plannedCacheKey !== item.cacheKey || !/^[a-f0-9]{64}$/.test(prepared.cacheKey) || prepared.profileDigest !== plan.profileDigest) fail('The thumbnail model or template changed.');
        var subject = await renderSubject(prepared, profile, plan.size, signal);
        var combined = await compose(profile, item.characterId, subject.canvas, plan.size, signal), png = combined.toDataURL('image/png');
        var receipt = await api('render', { token: plan.token, item_id: item.id, cache_key: prepared.cacheKey,
          profile_digest: plan.profileDigest, png: png, render: subject.report }, signal);
        results.push({ receipt: receipt, render: subject.report }); lastReceipts.push(receipt);
        last = { token: plan.token, size: plan.size, characterId: item.characterId, receipt: receipt,
          render: subject.report, count: i + 1, total: plan.items.length };
        if (options.onPreview) options.onPreview(png, receipt);
      }
      if (options.onProgress) options.onProgress(plan.items.length, plan.items.length, '');
      return { token: plan.token, receipts: results };
    } finally { active = false; }
  }
  async function preparePacker(params, options) {
    var plan = await api('plan', { kind: 'packer', params: params }, options && options.signal);
    return renderPlan(plan, options);
  }
  async function prepareViewer(snapshot, parameters, options) {
    var request = { kind: 'viewer', token: snapshot.token, state: snapshot.body,
      character_id: parameters.character_id, counterpart_path: parameters.counterpart_path,
      selected_variant: parameters.selected_variant };
    if (typeof parameters.include_face_edits === 'boolean') request.include_face_edits = parameters.include_face_edits;
    request.thumbnail_fit_full = parameters.thumbnail_fit_full === true;
    if (snapshot.meshState && snapshot.meshState.meshes && snapshot.meshState.meshes.length) request.mesh_state = snapshot.meshState;
    var plan = await api('plan', request, options && options.signal);
    return renderPlan(plan, options);
  }
  async function prepareUpdater(params, options) {
    var plan = await api('plan', { kind: 'updater', params: params }, options && options.signal);
    return renderPlan(plan, options);
  }
  global.ViewerThumbnails = { preparePacker: preparePacker, prepareViewer: prepareViewer,
    prepareUpdater: prepareUpdater,
    renderPlan: renderPlan, compose: compose, applySavedSettings: applySavedSettings, frameCharacter: frameCharacter, getState: function () { return { busy: active,
      last: last ? JSON.parse(JSON.stringify(last)) : null, receipts: JSON.parse(JSON.stringify(lastReceipts)) }; } };
}(window));
