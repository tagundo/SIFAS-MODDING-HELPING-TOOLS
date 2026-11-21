(function (global) {
  "use strict";

  function vector(value, length) {
    return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  }

  const offsetMixIn = [{ time: 0, value: 0 }, { time: 1, value: 1 }];
  const offsetMixOut = [{ time: 0, value: 1 }, { time: 1, value: 0 }];

  function heightScale(performer) {
    const components = performer?.rig?.scaling?.components;
    if (!Array.isArray(components)) return 1;
    const body = components.filter((component) => /(?:^|_)body$/i.test(component?.targetName));
    const scale = body[0]?.heightScale;
    return body.length === 1 && Number.isFinite(scale) && scale > 0 ? scale : 1;
  }

  function savedNodeScaling(T, root, rig) {
    const components = rig?.scaling?.components;
    if (rig?.available !== true || !Array.isArray(components) || !components.length) return null;
    const nodes = new Map(), operations = new Map(), conflicts = new Set();
    root.traverse((node) => {
      const index = node.userData?.elichika_node;
      if (!Number.isInteger(index) || node.userData.viewerHelper) return;
      nodes.set(index, nodes.has(index) ? null : node);
    });
    for (const component of components) for (const entry of Array.isArray(component?.entries) ? component.entries : []) {
      if (!entry || !["scale", "position", "rotation"].includes(entry.kind)) continue;
      const node = nodes.get(entry.node), rotation = entry.kind === "rotation";
      const property = rotation ? "quaternion" : entry.kind;
      const values = rotation ? entry.scaledQuaternion : entry.scaled;
      if (!node || entry.supported !== true || entry.application !== `absolute_local_${property}` || !vector(values, rotation ? 4 : 3) ||
          (rotation && Math.abs(values.reduce((sum, value) => sum + value * value, 0) - 1) > 1e-3) ||
          (property === "scale" && values.some((value) => Math.abs(value) < 1e-8))) continue;
      const key = `${entry.node}:${property}`;
      const previous = operations.get(key);
      if (previous) {
        const sign = rotation && previous.values.reduce((sum, value, axis) => sum + value * values[axis], 0) < 0 ? -1 : 1;
        if (values.some((value, axis) => Math.abs(previous.values[axis] - value * sign) > 1e-6)) conflicts.add(key);
        continue;
      }
      operations.set(key, { node, property, values, entry });
    }
    const moves = [], euler = new T.Euler(0, 0, 0, "YXZ"), scratch = new T.Vector3();
    for (const [key, { node, property, values, entry }] of operations) {
      if (conflicts.has(key)) continue;
      // The saved settings are absolute local endpoints, including models whose
      // authored transforms already match the endpoints.
      node[property].fromArray(values);
      if (entry.name !== "Move" || (node.userData.originalName || node.name) !== "Move") continue;
      const rotation = property === "quaternion";
      const from = rotation ? entry.unityEulerOrigin : entry.origin;
      const to = rotation ? entry.unityEulerScaled : entry.scaled;
      if (!vector(from, 3) || !vector(to, 3) || (rotation && (entry.interpolation !== "unity_euler_lerp" || entry.rotationOrder !== "ZXY")) ||
          (property === "scale" && from.some((value, axis) => Math.abs(value) < 1e-8 || value * to[axis] < 0))) continue;
      moves.push({ node, property, values, from: new T.Vector3().fromArray(from), to: new T.Vector3().fromArray(to) });
    }
    if (!moves.length) return null;
    let applied = false;
    return {
      resetHeight() {
        if (!applied) return;
        for (const { node, property, values } of moves) node[property].fromArray(values);
        applied = false;
      },
      applyHeight(clips, time) {
        if (!clips?.length) return;
        let amount = 1;
        for (const clip of clips) {
          const influence = global.ViewerMotionTimeline.weight(clip, time);
          if (influence > 0) amount = Math.min(1, Math.max(0, 1 - clip.intensity * influence));
        }
        // The game's override affects only the saved Move properties. The
        // mixer restores the fully scaled endpoint outside its active clips.
        for (const { node, property, values, from, to } of moves) {
          if (amount === 1) node[property].fromArray(values);
          else if (property === "quaternion") {
            scratch.lerpVectors(from, to, amount);
            node.quaternion.setFromEuler(euler.set(scratch.x * Math.PI / 180, -scratch.y * Math.PI / 180, -scratch.z * Math.PI / 180));
          } else node[property].lerpVectors(from, to, amount);
        }
        applied = true;
      }
    };
  }

  function activeEvent(track, time) {
    return track.events.reduce((current, event) => event.start <= time &&
      time <= event.start + event.duration && (!current || event.start >= current.start) ? event : current, null);
  }

  function activeCameraEvent(track, time) {
    const active = activeEvent(track, time);
    if (active) return active;
    let previous = null, next = null;
    // Stock Timeline often gives one authored frame to post-extrapolation
    // Hold between camera clips. Preserve the shot until the real cut.
    for (const event of track.events) {
      const values = event.values || {};
      const end = event.start + event.duration;
      if (time > end && values.postExtrapolationMode === 1 && time <= end + values.postExtrapolationTime &&
          (!previous || event.start > previous.start)) previous = event;
      if (time < event.start && values.preExtrapolationMode === 1 && time >= event.start - values.preExtrapolationTime &&
          (!next || event.start < next.start)) next = event;
    }
    return previous || next;
  }

  // Camera frames from the native importer are ordered. Continue to accept
  // projects authored by older tools that saved frames in a different order.
  function cameraSamples(event, time, ordered) {
    const value = event.values || {};
    const frames = value.keyframes;
    if (!Array.isArray(frames) || !frames.length) return [value, value];
    if (!ordered) {
      let left = frames[0], right = left;
      for (const sample of frames) {
        right = sample;
        if (sample.time > time) break;
        left = sample;
      }
      return [left, right];
    }
    let lower = 0, upper = frames.length;
    while (lower < upper) {
      const mid = (lower + upper) >>> 1;
      if (frames[mid].time <= time) lower = mid + 1;
      else upper = mid;
    }
    return [frames[Math.max(0, lower - 1)], frames[Math.min(lower, frames.length - 1)]];
  }

  function localURL(value) {
    return typeof value === "string" && /^\/api\/(?:mv-studio\/media\/[a-f0-9]{32}\.(?:glb|wav|mp3|ogg|m4a)|viewer\/model\/[a-f0-9]{32}\.glb)$/.test(value);
  }

  function vertexShaders(source) {
    return new Set([source, "centroid varying vec2 vSifasMouthClipZW;\n" +
      source.replace(/\n}$/, "\n  vSifasMouthClipZW = gl_Position.zw;\n}")]);
  }

  function materials(mesh) {
    return [mesh.material].flat();
  }

  function matchesOutline(mesh, outline) {
    return outline.isSkinnedMesh && outline.userData.sifasOutline && !outline.children.length &&
      outline.skeleton === mesh.skeleton && outline.geometry === mesh.geometry &&
      outline.bindMode === mesh.bindMode && outline.bindMatrix.equals(mesh.bindMatrix) &&
      !outline.position.lengthSq() && !outline.quaternion.x && !outline.quaternion.y &&
      !outline.quaternion.z && Math.abs(outline.quaternion.w) === 1 &&
      outline.scale.x === 1 && outline.scale.y === 1 && outline.scale.z === 1;
  }

  function boundsAttributeVersion(attribute) {
    return attribute.data ? attribute.data.version : attribute.version;
  }

  function finiteAffine(matrix) {
    const values = matrix.elements;
    return values[3] === 0 && values[7] === 0 && values[11] === 0 && values[15] === 1 &&
      values.every((value) => Number.isFinite(value) && Math.abs(value) <= 1024);
  }

  function skinBounds(T, root) {
    const shader = global.SifasMaterial;
    if (!shader || typeof shader.vertexShader !== "string" || typeof shader.outlineVertexShader !== "string") return [];
    const mainShaders = vertexShaders(shader.vertexShader), outlineShaders = vertexShaders(shader.outlineVertexShader);
    const entries = [], position = new T.Vector3(), joints = new T.Vector4(), weights = new T.Vector4();
    // Imported rigs can contain many mesh/morph combinations. Keep the work
    // per actor bounded and continue to draw meshes outside the supported set.
    let budget = 300000;
    root.traverse((mesh) => {
      if (!mesh.isSkinnedMesh || !mesh.skeleton || mesh.userData.sifasOutline || !mesh.children.length ||
          !mesh.children.every((outline) => matchesOutline(mesh, outline)) ||
          !["attached", "detached"].includes(mesh.bindMode) || !finiteAffine(mesh.bindMatrix)) return;
      const { skeleton, geometry } = mesh;
      const count = skeleton.bones.length;
      if (!count || count > 256 || skeleton.boneInverses.length !== count) return;
      const main = materials(mesh), outlines = mesh.children.flatMap(materials);
      if (!main.every((material) => mainShaders.has(material?.vertexShader)) ||
          !outlines.every((material) => outlineShaders.has(material?.vertexShader) && material.uniforms?.uOutlineEdited)) return;
      const { position: positions, skinIndex, skinWeight, _sifas_color: mask, _sifas_outline_width: editedWidth } = geometry.attributes;
      const morphs = geometry.morphAttributes.position || [];
      if (!positions || !skinIndex || !skinWeight || editedWidth || skinIndex.itemSize !== 4 || skinWeight.itemSize !== 4 ||
          skinIndex.count !== positions.count || skinWeight.count !== positions.count ||
          (morphs.length && !geometry.morphTargetsRelative) || morphs.some((morph) => morph.count !== positions.count)) return;
      const attributes = [positions, skinIndex, skinWeight, ...morphs];
      if (attributes.some((attribute) => attribute.normalized)) return;
      const samples = positions.count * (morphs.length + 1);
      if (samples > budget) return;
      budget -= samples;
      if (mask) {
        if (mask.count !== positions.count) return;
        const array = mask.array;
        if (mask.normalized) {
          if (!(array instanceof Uint8Array || array instanceof Uint16Array)) return;
        } else {
          for (let index = 0; index < mask.count; index++) {
            const width = mask.getX(index);
            if (!Number.isFinite(width) || width < 0 || width > 1) return;
          }
        }
        attributes.push(mask);
      }
      const boxes = Array.from({ length: count }, () => new T.Box3());
      const min = new T.Vector3(), max = new T.Vector3(), extent = new T.Vector3();
      const bind = mesh.bindMatrix.elements;
      let weightError = 0;
      for (let index = 0; index < positions.count; index++) {
        joints.fromBufferAttribute(skinIndex, index);
        weights.fromBufferAttribute(skinWeight, index);
        const error = Math.abs(1 - weights.x - weights.y - weights.z - weights.w);
        if (!Number.isFinite(error) || error > 1e-5 || Math.min(weights.x, weights.y, weights.z, weights.w) < 0) return;
        weightError = Math.max(error, weightError);
        position.fromBufferAttribute(positions, index).applyMatrix4(mesh.bindMatrix);
        let dx = 0, dy = 0, dz = 0;
        for (const morph of morphs) {
          dx += Math.abs(morph.getX(index)); dy += Math.abs(morph.getY(index)); dz += Math.abs(morph.getZ(index));
        }
        extent.set(
          Math.abs(bind[0])*dx + Math.abs(bind[4])*dy + Math.abs(bind[8])*dz,
          Math.abs(bind[1])*dx + Math.abs(bind[5])*dy + Math.abs(bind[9])*dz,
          Math.abs(bind[2])*dx + Math.abs(bind[6])*dy + Math.abs(bind[10])*dz
        );
        min.copy(position).sub(extent); max.copy(position).add(extent);
        if (Math.max(Math.abs(min.x), Math.abs(min.y), Math.abs(min.z), Math.abs(max.x), Math.abs(max.y), Math.abs(max.z)) > 1024 ||
            !Number.isFinite(min.lengthSq() + max.lengthSq())) return;
        for (let component = 0; component < 4; component++) if (weights.getComponent(component) > 0) {
          const box = boxes[joints.getComponent(component)];
          if (!box) return;
          box.expandByPoint(min).expandByPoint(max);
        }
      }
      const bones = boxes.flatMap((box, index) => box.isEmpty() ? [] : [{ index,
        center: box.getCenter(new T.Vector3()), extent: box.getSize(new T.Vector3()).multiplyScalar(0.5) }]);
      entries.push({ mesh, skeleton, geometry, morphs: morphs.slice(), main, outlines, mask, weightError, bones,
        positions, skinIndex, skinWeight, bindMatrix: mesh.bindMatrix.clone(),
        mainShaders: main.map((material) => material.vertexShader),
        outlineShaders: outlines.map((material) => material.vertexShader),
        versions: attributes.map((attribute) => [attribute, boundsAttributeVersion(attribute)]) });
    });
    return entries;
  }

  function outsideCamera(entry, camera, width, height, bounds, model, transform) {
    const { mesh, skeleton, geometry, morphs } = entry;
    const attributes = geometry.attributes;
    const activeMorphs = geometry.morphAttributes.position || [];
    if (!mesh.visible || mesh.geometry !== geometry || mesh.skeleton !== skeleton ||
        !mesh.bindMatrix.equals(entry.bindMatrix) || attributes.position !== entry.positions ||
        attributes.skinIndex !== entry.skinIndex || attributes.skinWeight !== entry.skinWeight ||
        attributes._sifas_color !== entry.mask || attributes._sifas_outline_width ||
        activeMorphs.length !== morphs.length || (morphs.length && !geometry.morphTargetsRelative) ||
        morphs.some((morph, index) => morph !== activeMorphs[index]) ||
        entry.versions.some(([attribute, version]) => boundsAttributeVersion(attribute) !== version) ||
        mesh.morphTargetInfluences?.some((weight) => !Number.isFinite(weight) || Math.abs(weight) > 1) ||
        !mesh.children.length || !mesh.children.every((outline) => matchesOutline(mesh, outline)) ||
        !finiteAffine(mesh.bindMatrixInverse)) return false;
    const shaders = materials(mesh), outlines = mesh.children.flatMap(materials);
    if (shaders.length !== entry.main.length || shaders.some((material, index) =>
        material !== entry.main[index] || material.vertexShader !== entry.mainShaders[index]) ||
        outlines.length !== entry.outlines.length || outlines.some((material, index) =>
          material !== entry.outlines[index] || material.vertexShader !== entry.outlineShaders[index] ||
          material.uniforms.uOutlineEdited.value !== 0)) return false;
    model.multiplyMatrices(camera.matrixWorldInverse, mesh.matrixWorld);
    const translation = Math.max(Math.abs(model.elements[12]), Math.abs(model.elements[13]), Math.abs(model.elements[14]));
    model.multiply(mesh.bindMatrixInverse);
    if (!finiteAffine(model)) return false;
    bounds.makeEmpty();
    for (const bone of entry.bones) {
      const world = skeleton.bones[bone.index]?.matrixWorld, inverse = skeleton.boneInverses[bone.index];
      if (!world || !inverse || !finiteAffine(world) || !finiteAffine(inverse)) return false;
      transform.multiplyMatrices(model, world).multiply(inverse);
      if (!finiteAffine(transform)) return false;
      const a = transform.elements, c = bone.center, r = bone.extent;
      const x = a[0]*c.x + a[4]*c.y + a[8]*c.z + a[12];
      const y = a[1]*c.x + a[5]*c.y + a[9]*c.z + a[13];
      const z = a[2]*c.x + a[6]*c.y + a[10]*c.z + a[14];
      const dx = Math.abs(a[0])*r.x + Math.abs(a[4])*r.y + Math.abs(a[8])*r.z;
      const dy = Math.abs(a[1])*r.x + Math.abs(a[5])*r.y + Math.abs(a[9])*r.z;
      const dz = Math.abs(a[2])*r.x + Math.abs(a[6])*r.y + Math.abs(a[10])*r.z;
      bounds.min.set(Math.min(bounds.min.x, x-dx), Math.min(bounds.min.y, y-dy), Math.min(bounds.min.z, z-dz));
      bounds.max.set(Math.max(bounds.max.x, x+dx), Math.max(bounds.max.y, y+dy), Math.max(bounds.max.z, z+dz));
    }
    if (bounds.isEmpty()) return false;
    const { min, max } = bounds;
    const magnitude = Math.max(Math.abs(min.x), Math.abs(min.y), Math.abs(min.z), Math.abs(max.x), Math.abs(max.y), Math.abs(max.z));
    bounds.expandByScalar(0.02 + magnitude*0.0001 + (magnitude + translation)*entry.weightError);
    if (min.z > 0) return true;
    const depth = -min.z, projection = camera.projectionMatrix.elements;
    const fx = projection[0], fy = projection[5];
    // The outline shader expands its input in clip XY by at most this width.
    // Keep a further two drawing-buffer pixels around the conservatively skinned box.
    const z = depth / (fy * 0.267949194);
    const factor = Math.max(z * 1.11111116, z * 0.555555582 + 0.5);
    const margin = 4 * depth / Math.min(width, height);
    const xLimit = depth + margin + fx * factor * 0.001, yLimit = depth + margin + fy * factor * 0.001;
    return fx*max.x < -xLimit || fx*min.x > xLimit || fy*max.y < -yLimit || fy*min.y > yLimit;
  }

  function create(mount, options) {
    const T = global.THREE;
    if (!T || !T.GLTFLoader || !T.OrbitControls) throw new Error("The 3D preview could not start.");
    const renderer = new T.WebGLRenderer({ antialias: true, alpha: false, stencil: true, powerPreference: "high-performance" });
    renderer.outputEncoding = T.sRGBEncoding;
    renderer.setClearColor(0x111522);
    renderer.shadowMap.type = T.PCFSoftShadowMap;
    renderer.domElement.setAttribute("aria-label", "MV stage preview");
    mount.appendChild(renderer.domElement);
    const split = global.MVStudioSplit?.create(T, renderer);
    const physicsClock = global.MVStudioPhysics?.createClock();
    const post = global.MVStudioPost?.create(T, renderer);
    const overlay = global.MVStudioStageOverlay?.create(T, renderer);

    const scene = new T.Scene();
    const editorCamera = new T.PerspectiveCamera(48, 1, 0.02, 1000);
    const liveCamera = new T.PerspectiveCamera(42, 1, 0.02, 1000);
    const stageCamera = new T.PerspectiveCamera(48, 1, 0.02, 1000);
    const controls = new T.OrbitControls(editorCamera, renderer.domElement);
    const stage = new T.Group(), actors = new T.Group(), effects = new T.Group();
    const grid = new T.GridHelper(30, 30, 0x53728c, 0x27354c);
    const ambient = new T.HemisphereLight(0xe4edff, 0x54546e, 1.2);
    const key = new T.DirectionalLight(0xffffff, 2.1);
    key.position.set(-3, 7, 4);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    const rim = new T.DirectionalLight(0x8bb6ff, 1.0);
    rim.position.set(4, 4, -3);
    const lights = [ambient, key, rim];
    const stageLights = lights.map((light) => light.clone());
    stageLights[1].castShadow = false;
    scene.add(stage, actors, effects, grid, ambient, key, rim);
    // The scene's fixed roots otherwise dirty the world matrix of every
    // descendant on each render. Dancers and both cameras still animate.
    for (const node of [scene, stage, actors, effects, grid, ambient, key, rim]) {
      node.updateMatrix();
      node.matrixAutoUpdate = false;
    }
    controls.target.set(0, 1.1, 0);
    editorCamera.position.set(5, 3.8, 8);
    stageCamera.position.copy(editorCamera.position);
    stageCamera.lookAt(controls.target);
    controls.update();

    let disposed = false, visible = options?.visible !== false, generation = 0, request = null, project = null;
    let preparation = null;
    let stageTitle = null, stageRibbons = null, stageShine = null, stageParticles = null, stageSpotlight = null;
    let stageSpeedBack = null, stageDisplayLights = null, stageFallingEffects = null, stageBreak = null, stageFinaleFloor = null;
    let stageSparksA = null, stageSparksB = null, stageSparksRoop = null;
    let activeSplitGazeCameras = null;
    let loadedProjectToken = null;
    let currentTime = 0, useLive = true, hasShot = false, records = [], queuedDraw = 0, seekDrawPending = false;
    let playing = false, lastPlaybackFrame = null, slowFrames = 0, previewScale = 1;
    let lastShaftFrame = null, resetShafts = true;
    let renderHeight = null, viewportDirty = false, settings = {}, trackSource = null, renderTracks = [];
    let nativeMainLens = false, authoredMainFov = liveCamera.fov;
    const cameraOffsets = new Map();
    const nativeEvents = new Map(), performers = new Map(), sortedCameraFrames = new WeakMap(), memberScaleTracks = new Map();
    const memberCullingTracks = new Map();
    const memberShaftTracks = new Map(), memberAreaTracks = new Map();
    const releasedSkeletons = new WeakSet();
    const size = new T.Vector2();
    const bounds = new T.Box3(), skinMatrix = new T.Matrix4(), boneMatrix = new T.Matrix4();
    const culled = [];
    const position = new T.Vector3(), otherPosition = new T.Vector3();
    const mainCameraPosition = new T.Vector3(), focusPosition = new T.Vector3();
    const rotation = new T.Quaternion(), otherRotation = new T.Quaternion();
    const gaze = { camera: [0, 0, 0], members: {} }, gazeEyePosition = new T.Vector3();

    function cancelDraw() {
      if (queuedDraw) global.cancelAnimationFrame(queuedDraw);
      queuedDraw = 0;
      seekDrawPending = false;
    }

    function draw() {
      cancelDraw();
      if (!disposed && visible && mount.clientWidth && mount.clientHeight) {
        if (preparation?.shown) {
          renderer.render(preparation.scene, stageCamera);
          return;
        }
        if (!(useLive && split?.draw(renderView, hasShot ? liveCamera : null))) {
          renderView(useLive && hasShot ? liveCamera : editorCamera);
        }
        if (useLive && settings.stage_overlay_effect !== false && records.some((record) => record.stageOverlay?.hasVisible())) {
          overlay?.draw(scene);
        }
      }
    }

    function renderView(camera) {
      if (camera === liveCamera && post) {
        const focus = global.MVStudioDofFocus?.sample(project, currentTime, camera.fov, focusDistance);
        if (post.draw(() => renderScene(camera), Boolean(focus), focus, camera)) return;
      }
      renderScene(camera);
    }

    function focusDistance(slot, part) {
      const point = records.find(record => record.group === actors && record.position === slot)?.focusParts?.[part];
      return point?.getWorldPosition(focusPosition).distanceTo(mainCameraPosition);
    }

    function renderScene(camera) {
      if (!stageBreak?.sort(camera, stageSpeedBack?.displaySortEntries)) stageSpeedBack?.sort(camera);
      stageDisplayLights?.sort(camera);
      stageFallingEffects?.sort(camera, stageTitle?.displaySortEntries);
      // AxisBillboard follows the camera currently drawing each split layer.
      for (const record of records) record.shaft?.billboard(camera === editorCamera ? liveCamera : camera);
      const projection = camera.projectionMatrix.elements;
      const { width, height } = renderer.domElement;
      if (camera !== liveCamera || renderer.shadowMap.enabled || !width || !height || projection[8] || projection[9] ||
          projection[11] !== -1 || projection[15] !== 0 || !(projection[0] > 0.001 && projection[5] > 0.001) ||
          !records.some((record) => record.skinBounds?.length)) {
        renderer.render(scene, camera);
        return;
      }
      const autoUpdate = scene.autoUpdate;
      if (autoUpdate) scene.updateMatrixWorld();
      camera.updateMatrixWorld();
      scene.autoUpdate = false;
      try {
        for (const record of records) for (const entry of record.skinBounds || []) {
          if (outsideCamera(entry, camera, width, height, bounds, skinMatrix, boneMatrix)) {
            entry.mesh.visible = false;
            culled.push(entry.mesh);
          }
        }
        renderer.render(scene, camera);
      } finally {
        culled.forEach((mesh) => { mesh.visible = true; });
        culled.length = 0;
        scene.autoUpdate = autoUpdate;
      }
    }

    function liveFov() {
      const correction = nativeMainLens ? global.MVStudioSplit?.aspectCorrection(liveCamera.aspect) ?? 1 : 1;
      return Math.min(170, authoredMainFov / correction);
    }

    function requestDraw() {
      if (!disposed && visible && !queuedDraw) queuedDraw = global.requestAnimationFrame(draw);
    }

    function resize(forceDraw = true) {
      const width = mount.clientWidth, height = mount.clientHeight;
      if (disposed || !visible || !width || !height) return;
      const displayed = preparation?.shown ? preparation.preview : project;
      const values = displayed?.quality?.values || {};
      const nativeHeight = values.rendering_resolution;
      const resolution = Number.isFinite(nativeHeight) && nativeHeight > 0
        ? Math.min(nativeHeight / height, 2) : Math.min(global.devicePixelRatio || 1, 2);
      const previewResolution = resolution * (preparation?.shown ? 1 : previewScale);
      const changedRatio = renderer.getPixelRatio() !== previewResolution;
      renderer.getSize(size);
      const changedSize = size.x !== width || size.y !== height;
      renderHeight = nativeHeight;
      viewportDirty = false;
      if (!forceDraw && !changedRatio && !changedSize) return;
      if (changedRatio) renderer.setPixelRatio(previewResolution);
      if (changedSize) renderer.setSize(width, height, false);
      const aspect = width / height;
      for (const camera of [editorCamera, liveCamera, stageCamera]) {
        if (camera.aspect !== aspect) {
          camera.aspect = aspect;
          if (camera === liveCamera) camera.fov = liveFov();
          camera.updateProjectionMatrix();
        }
      }
      draw();
    }

    function release(root) {
      const geometries = new Set(), materials = new Set(), textures = new Set(), skeletons = new Set();
      root.traverse((node) => {
        if (node.geometry) geometries.add(node.geometry);
        if (node.isSkinnedMesh && node.skeleton) skeletons.add(node.skeleton);
        (Array.isArray(node.material) ? node.material : [node.material]).filter(Boolean).forEach((material) => {
          materials.add(material);
          for (const value of Object.values(material)) if (value && value.isTexture) textures.add(value);
        });
      });
      textures.forEach((value) => value.dispose());
      materials.forEach((value) => value.dispose());
      geometries.forEach((value) => value.dispose());
      if (skeletons.size) {
        scene.traverse((node) => {
          if (node.isSkinnedMesh && node.skeleton) skeletons.delete(node.skeleton);
        });
        // Main and outline meshes normally share one bone texture.
        for (const skeleton of skeletons) if (!releasedSkeletons.has(skeleton)) {
          releasedSkeletons.add(skeleton);
          skeleton.dispose();
        }
      }
    }

    function releaseRecord(record) {
      if (record.group === actors) {
        for (const item of records) if (item.prop) item.prop.detach(record);
      }
      if (record.prop) record.prop.detach();
      record.propMaterial?.dispose();
      record.shaft?.dispose();
      record.shaftTemplates?.dispose();
      record.spotlightArea?.dispose();
      record.areaTemplate?.dispose();
      if (record.materials) record.materials.dispose();
      record.penlight?.dispose();
      record.stageFlash?.dispose();
      record.stageMaterial?.dispose();
      record.stageColoring?.dispose();
      record.stageDisplay?.dispose();
      record.stageOverlay?.dispose();
      record.physics?.dispose();
      if (record.mixer) record.mixer.stopAllAction();
      if (record.root.parent) record.root.parent.remove(record.root);
      release(record.root);
    }

    function clear() {
      physicsClock?.reset();
      stageTitle?.dispose();
      stageTitle = null;
      stageRibbons?.dispose();
      stageRibbons = null;
      stageShine?.dispose();
      stageShine = null;
      stageParticles?.dispose();
      stageParticles = null;
      stageSpotlight?.dispose();
      stageSpotlight = null;
      stageSparksRoop?.dispose();
      stageSparksRoop = null;
      stageSparksA?.dispose();
      stageSparksA = null;
      stageSparksB?.dispose();
      stageSparksB = null;
      stageFinaleFloor?.dispose();
      stageFinaleFloor = null;
      stageBreak?.dispose();
      stageBreak = null;
      stageFallingEffects?.dispose();
      stageFallingEffects = null;
      stageSpeedBack?.dispose();
      stageSpeedBack = null;
      stageDisplayLights?.dispose();
      stageDisplayLights = null;
      lastShaftFrame = null;
      resetShafts = true;
      // Actors borrow stage geometries. Detach the instances before clearing the stage.
      for (const record of records) if (record.group === actors) releaseRecord(record);
      for (const record of records) if (record.group !== actors) releaseRecord(record);
      records = [];
      loadedProjectToken = null;
      grid.visible = true;
    }

    function captureActorPose(root) {
      const pose = [];
      root.traverse((node) => pose.push({
        node, position: node.position.toArray(), rotation: node.quaternion.toArray(),
        scale: node.scale.toArray(), visible: node.visible, morphs: node.morphTargetInfluences?.slice()
      }));
      return pose;
    }

    function restoreActorPose(pose) {
      for (const saved of pose) {
        const { node } = saved;
        node.position.fromArray(saved.position);
        node.quaternion.fromArray(saved.rotation);
        node.scale.fromArray(saved.scale);
        node.visible = saved.visible;
        if (saved.morphs) {
          for (let index = 0; index < saved.morphs.length; index++) {
            node.morphTargetInfluences[index] = saved.morphs[index];
          }
        }
      }
    }

    async function modelBytes(url, signal) {
      if (!localURL(url)) throw new Error("The preview asset address is invalid.");
      const response = await fetch(url, { signal });
      if (!response.ok) throw new Error("The preview asset is unavailable. Load it again.");
      const bytes = await response.arrayBuffer();
      if (!bytes.byteLength || bytes.byteLength > 96 * 1024 * 1024) throw new Error("The 3D preview asset is too large.");
      return bytes;
    }

    function actorPose(record, performer) {
      const move = performer.transform || {};
      if (vector(move.position, 3)) record.root.position.fromArray(move.position);
      if (vector(move.rotation, 4)) record.root.quaternion.fromArray(move.rotation).normalize();
      if (vector(move.scale, 3)) record.root.scale.fromArray(move.scale);
    }

    function updateMotion(record) {
      let changed = false;
      const assign = (object, key, value) => {
        if (object[key] === value) return;
        object[key] = value;
        changed = true;
      };
      for (const segment of record.motionEvents) {
        const bound = nativeEvents.get(segment.nativeEventId);
        if (!bound) continue;
        const event = bound.event, values = event.values;
        assign(segment, "start", event.start);
        assign(segment, "duration", event.duration);
        const weight = segment.kind === "gaze" ? values.weightForDirection : values.weight;
        assign(segment, "weight", bound.track.muted ? 0 : Number.isFinite(weight) ? Math.min(1, Math.max(0, weight)) : 1);
        if (segment.kind === "gaze") {
          if (Number.isInteger(values.target)) assign(segment, "target", values.target);
          const alternate = values.splitScreenSetting;
          const usesAlternate = (alternate?.UseSetting === 1 || alternate?.UseSetting === true) &&
            Number.isInteger(alternate.Target) && Number.isFinite(alternate.WeightForDirection);
          assign(segment, "splitTarget", usesAlternate ? alternate.Target : null);
          assign(segment, "splitWeight", usesAlternate && !bound.track.muted ? Math.min(1, Math.max(0, alternate.WeightForDirection)) : 0);
        }
        if (Number.isFinite(values.clipIn)) assign(segment, "clipIn", values.clipIn);
        if (Number.isFinite(values.timeScale) && values.timeScale > 0) assign(segment, "timeScale", values.timeScale);
        for (const key of ["easeIn", "easeOut", "blendIn", "blendOut"]) {
          if (Number.isFinite(values[key])) assign(segment.timing, key, values[key]);
        }
        for (const side of ["pre", "post"]) {
          for (const field of ["Time", "Mode"]) {
            const edited = values[side + "Extrapolation" + field];
            if (Number.isFinite(edited)) assign(segment.timing, side + field, edited);
          }
        }
      }
      if (changed && record.motion.invalidateTiming) record.motion.invalidateTiming();
    }

    function gazeContext() {
      gaze.audience = records.find((record) => record.group === stage)?.audience;
      gaze.cameras = activeSplitGazeCameras;
      gaze.split = activeSplitGazeCameras !== null;
      for (const record of records) if (record.group === actors) {
        if (record.motion?.eyePosition(gazeEyePosition)) {
          const member = gaze.members[record.position] || (gaze.members[record.position] = [0, 0, 0]);
          gazeEyePosition.toArray(member);
        } else delete gaze.members[record.position];
      }
      // Game gaze binds to the authored MainCamera even while editing in orbit view.
      const camera = project?.source?.kind === "game"
        ? (hasShot ? liveCamera : null)
        : (useLive && hasShot ? liveCamera : editorCamera);
      gaze.camera = camera ? camera.position.toArray(gaze.camera || []) : null;
      return gaze;
    }

    function frameGroup(group, camera, target) {
      const bounds = new T.Box3();
      bounds.setFromObject(group);
      if (bounds.isEmpty()) return false;
      const center = bounds.getCenter(new T.Vector3());
      const radius = Math.max(1.5, bounds.getSize(new T.Vector3()).length() * 0.5);
      camera.position.copy(center).add(new T.Vector3(0.45, 0.35, 1.25).multiplyScalar(radius * 2));
      if (target) target.copy(center);
      else camera.lookAt(center);
      return true;
    }

    function frameAll() {
      if (frameGroup(actors.children.length ? actors : stage, editorCamera, controls.target)) controls.update();
    }

    function sceneEntries(value, stageOnly = false) {
      const entries = [], attachments = [];
      if (value.stage && value.stage.glb) entries.push({ spec: { ...value.stage }, group: stage, role: "stage" });
      if (value.stage && value.stage.effectsGlb) {
        entries.push({ spec: { glb: value.stage.effectsGlb }, group: effects, role: "stage-effects" });
      }
      for (const asset of value.assets || []) {
        if (asset.kind === "props" && asset.attachment) {
          if (!stageOnly && asset.previewUrl) attachments.push({
            spec: { glb: asset.previewUrl, attachment: asset.attachment }, group: effects, role: "performer-prop"
          });
          continue;
        }
        if (["effect", "props", "background"].includes(asset.kind) && asset.previewUrl &&
            (!value.stage || asset.previewUrl !== value.stage.effectsGlb)) {
          entries.push({ spec: { glb: asset.previewUrl }, group: effects, role: asset.kind });
        }
      }
      if (stageOnly) return entries;
      for (const performer of (value.performers || []).slice(0, 9)) {
        if (performer.glb) entries.push({ spec: performer, group: actors });
      }
      entries.push(...attachments);
      return entries;
    }

    function entryIdentity(entry) {
      const { spec } = entry;
      if (spec.attachment) return JSON.stringify([spec.glb, spec.attachment]);
      if (entry.group !== actors) return spec.glb;
      return JSON.stringify([spec.id, spec.position, spec.glb, spec.transform, spec.rig, spec.motion]);
    }

    function outfitReplacement(value, entries, actorId) {
      if (typeof actorId !== "string" || !actorId || typeof value?.token !== "string" ||
          value.token !== loadedProjectToken || entries.length !== records.length) return -1;
      let replacement = -1;
      for (let index = 0; index < entries.length; index++) {
        const entry = entries[index], record = records[index];
        if (entry.group !== record.group) return -1;
        if (entry.group === actors && entry.spec.id === actorId) {
          if (replacement !== -1 || record.id !== actorId) return -1;
          replacement = index;
        } else if (entry.identity !== record.identity || (entry.group === actors && !record.initialPose)) {
          return -1;
        }
      }
      return replacement;
    }

    async function buildRecord(entry, bytes, active) {
      const gltf = await new Promise((resolve, reject) => new T.GLTFLoader().parse(bytes, "", resolve, reject));
      const record = { root: gltf.scene, id: entry.spec.id, group: entry.group, position: entry.spec.position,
        identity: entry.identity, visibility: [], rig: entry.spec.rig };
      const audience = gltf.scene.userData?.mvAudiencePoint;
      if (entry.group === stage && vector(audience, 3)) record.audience = audience;
      let ready = false;
      try {
        if (!active()) return null;
        if (entry.spec.attachment) {
          record.prop = global.MVStudioProps?.create(gltf.scene, entry.spec.attachment);
          if (!record.prop) throw new Error("The animated prop preview could not be opened.");
          record.propMember = entry.spec.attachment.member;
        }
        gltf.scene.traverse((node) => {
          if (entry.group !== actors && node.matrixAutoUpdate) {
            node.updateMatrix();
            node.matrixAutoUpdate = false;
          }
          if (!node.isMesh) return;
          node.castShadow = entry.group === actors;
          node.receiveShadow = true;
          // Three's static geometry bounds do not cover a skinned dance pose.
          // The renderer uses updated bone bounds for supported actor meshes.
          if (entry.group === actors && node.isSkinnedMesh) node.frustumCulled = false;
          if (entry.group !== effects) return;
          for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
            const name = material.name || "";
            if (/(?:^|_)add(?:_|$)/i.test(name)) {
              material.blending = T.AdditiveBlending;
              material.transparent = true;
              material.depthWrite = false;
            }
            const quality = /(?:^|_)aud(?:_|$)/i.test(name) ? "stage_audience" :
              /(?:^|_)led(?:_|$)/i.test(name) ? "stage_emissive" :
              /(?:^|_)dis(?:_|$)/i.test(name) ? "stage_display" : null;
            if (quality && !node.geometry.userData?.mvStageDisplay) record.visibility.push({ node, quality });
          }
        });
        if (entry.group !== actors) {
          record.stageMaterial = await global.MVStudioStageMaterial?.apply(T, record.root, gltf.parser);
          if (!active()) return null;
          record.stageColoring = await global.MVStudioStageColoring?.apply(T, record.root, gltf.parser);
          if (!active()) return null;
          record.stageDisplay = await global.MVStudioStageDisplay?.apply(T, record.root, gltf.parser);
          if (!active()) return null;
          record.stageOverlay = await global.MVStudioStageOverlay?.apply(T, record.root, gltf.parser);
          if (!active()) return null;
          record.shaftTemplates = await global.MVStudioShaft?.prepare(T, gltf);
          if (!active()) return null;
          record.areaTemplate = await global.MVStudioSpotlightArea?.prepare(T, gltf);
          if (!active()) return null;
          record.stageMotion = global.MVStudioStageMotion?.apply(T, record.root);
          record.penlight = global.MVStudioPenlight?.apply(T, record.root);
          record.stageFlash = await global.MVStudioStageFlash?.apply(T, record.root, gltf.parser);
          if (!active()) return null;
        }
        if (record.prop && entry.spec.attachment.binding && global.SifasMaterial) {
          record.propLight = global.MVStudioPropLight?.create(entry.spec.attachment.binding, record.propMember);
          record.propMaterial = global.SifasMaterial.apply(gltf.scene, renderer, {
            memberProp: true, parser: gltf.parser, enabled: true, rimlight: true,
            onChange: requestDraw, releaseParserAfterLoad: true
          });
          await record.propMaterial?.ready;
          if (!active()) return null;
        }
        if (entry.group === actors) {
          record.actorVisible = record.root.visible;
          actorPose(record, entry.spec);
          record.nodeScaling = savedNodeScaling(T, gltf.scene, entry.spec.rig);
          const parts = entry.spec.rig?.focusParts;
          const shaftAnchor = entry.spec.rig?.shaftAnchor;
          const boneIds = new Set([parts?.head, parts?.hips, shaftAnchor].filter(Number.isInteger));
          if (boneIds.size) {
            const nodes = new Map();
            gltf.scene.traverse(node => {
              const id = node.userData.elichika_node;
              if (boneIds.has(id)) nodes.set(id, nodes.has(id) ? null : node);
            });
            record.focusParts = { 0: nodes.get(parts?.head), 3: nodes.get(parts?.hips) };
            record.shaftAnchor = nodes.get(shaftAnchor);
          }
          if (global.SifasMaterial) record.materials = global.SifasMaterial.apply(gltf.scene, renderer, {
            parser: gltf.parser, enabled: true, rimlight: true, onChange: requestDraw,
            mouthCentroidDepth: renderer.capabilities.isWebGL2 === true, releaseParserAfterLoad: true
          });
          if (record.materials && record.materials.ready) await record.materials.ready;
          if (!active()) return null;
          const authoredMotion = entry.spec.motion && global.ViewerMotionTimeline;
          if (authoredMotion || !gltf.animations.length) record.initialPose = captureActorPose(record.root);
          if (authoredMotion) {
            record.segments = (entry.spec.motion.bodySegments || []).map((segment) => ({
              ...segment, timing: { ...segment.timing }
            }));
            record.facialEvents = (entry.spec.motion.facial?.events || []).map((event) => ({
              ...event, timing: { ...event.timing }
            }));
            record.motionEvents = record.segments.concat(record.facialEvents);
            record.motion = global.ViewerMotionTimeline.create(gltf.scene, gltf.animations,
              entry.spec.rig || {}, { ...entry.spec.motion, bodySegments: record.segments,
                facial: { ...entry.spec.motion.facial, events: record.facialEvents } },
              { indexTiming: true });
            updateMotion(record);
          } else if (gltf.animations.length) {
            record.mixer = new T.AnimationMixer(gltf.scene);
            record.mixer.clipAction(gltf.animations[0]).play();
          }
          record.physics = global.MVStudioPhysics?.create(record.root, entry.spec.rig?.physics,
            entry.spec.motion?.physics ?? project?.motionPhysics);
        }
        if (entry.group === actors && record.materials) record.skinBounds = skinBounds(T, record.root);
        ready = true;
        return record;
      } finally {
        if (!ready) releaseRecord(record);
      }
    }

    async function swapOutfit(entry, index, signal, active) {
      let replacement = null;
      try {
        const bytes = await modelBytes(entry.spec.glb, signal);
        if (!active()) return;
        replacement = await buildRecord(entry, bytes, active);
      } catch (error) {
        if (!signal.aborted && !disposed && options && options.onError) options.onError(error.message);
      }
      if (!active()) {
        if (replacement) releaseRecord(replacement);
        return;
      }
      releaseRecord(records[index]);
      if (replacement) records[index] = replacement;
      else records.splice(index, 1);
      // A fresh scene starts from the loaded pose in intervals with no keys.
      // Restore that pose before seeking so earlier playback leaves no state.
      resetPhysics("costume-change");
      for (const child of actors.children.slice()) actors.remove(child);
      for (const record of records) {
        if (record.group !== actors) continue;
        record.physics?.restorePose();
        if (record.initialPose) restoreActorPose(record.initialPose);
        actors.add(record.root);
      }
      gaze.members = {};
      frameAll();
      seek(currentTime, project);
    }

    function cancelStagePreparation(redraw = true) {
      const pending = preparation;
      if (!pending) return;
      preparation = null;
      pending.controller.abort();
      for (const record of pending.records) releaseRecord(record);
      pending.scene.remove(...stageLights);
      if (pending.shown) {
        viewportDirty = true;
        if (redraw) resize();
      }
    }

    // This transient scene shares the renderer, while the current project
    // keeps its resources, playhead, and camera until a final project arrives.
    // Report false on supersession and throw a current asset failure.
    async function prepareStage(preview) {
      if (disposed) return false;
      cancelStagePreparation();
      const entries = preview ? sceneEntries(preview, true) : [];
      if (entries[0]?.group !== stage) return false;
      for (const entry of entries) entry.identity = entryIdentity(entry);
      const overviewEffects = new T.Group();
      const quality = preview.quality?.values || {};
      overviewEffects.visible = preview.source?.kind === "game" || quality.stage_control !== false;
      const pending = { preview, entries, scene: new T.Scene(), records: [], controller: new AbortController(), shown: false };
      pending.scene.add(overviewEffects, ...stageLights);
      frameTracks(0, (preview.tracks || []).filter((track) => track.kind === "lighting" && !track.muted), quality, stageLights);
      const lighting = global.MVStudioLighting?.sample(preview, 0);
      preparation = pending;
      const active = () => !disposed && preparation === pending;
      pending.ready = (async () => {
        const { signal } = pending.controller;
        for (const entry of entries) {
          const bytes = await modelBytes(entry.spec.glb, signal);
          if (!active()) return false;
          const record = await buildRecord(entry, bytes, active);
          if (!active()) {
            if (record) releaseRecord(record);
            return false;
          }
          for (const item of record.visibility) item.node.visible = quality[item.quality] !== false;
          record.stageFlash?.update(0, preview);
          record.stageMotion?.update(0, preview);
          record.penlight?.update(0, preview);
          record.stageMaterial?.update(0, preview, lighting);
          record.stageColoring?.update(0, preview);
          record.stageDisplay?.update(0, preview);
          pending.records.push(record);
          if (entry.group === stage) {
            pending.scene.add(record.root);
            frameGroup(record.root, stageCamera);
            pending.shown = true;
            resize();
          } else {
            overviewEffects.add(record.root);
            draw();
          }
        }
        return true;
      })();
      try {
        return await pending.ready;
      } catch (error) {
        if (!active()) return false;
        cancelStagePreparation();
        throw error;
      }
    }

    function reusableStage(entries, wanted) {
      if (!wanted || !preparation || preparation.entries.length > entries.length) return null;
      // URLs identify immutable GLB contents. Check their ordered scene roles
      // as well, since stage, stage effects, and props have separate inputs.
      return preparation.entries.every((entry, index) => entry.role === entries[index].role &&
        entry.identity === entries[index].identity) ? preparation : null;
    }

    async function load(value, preferences) {
      if (disposed) return;
      cancelDraw();
      const entries = value ? sceneEntries(value) : [];
      for (const entry of entries) entry.identity = entryIdentity(entry);
      const replacement = outfitReplacement(value, entries, preferences?.reuseOutfit);
      const pendingStage = reusableStage(entries, replacement < 0 && preferences?.reuseStage);
      if (!pendingStage) cancelStagePreparation(false);
      project = value;
      if (request) request.abort();
      request = new AbortController();
      const signal = request.signal, ticket = ++generation;
      const active = () => ticket === generation && !disposed;
      if (replacement < 0) clear();
      gaze.members = {};
      hasShot = false;
      if (!project) {
        split?.setProject(null);
        return;
      }
      applyProject();
      if (replacement >= 0) return swapOutfit(entries[replacement], replacement, signal, active);

      let start = 0;
      if (pendingStage) {
        // Join an exact stage preparation already in flight. Keep the same
        // GLB requests and parsed roots even if completion raced the stage.
        const ready = await pendingStage.ready.catch(() => false);
        if (!active()) return;
        if (ready && preparation === pendingStage) {
          preparation = null;
          viewportDirty = true;
          pendingStage.scene.remove(...stageLights);
          for (const record of pendingStage.records) {
            record.group.add(record.root);
            records.push(record);
          }
          start = records.length;
          grid.visible = false;
          frameAll();
          applyProject();
          playbackFrame(currentTime);
        }
      }

      // Fetch the next GLB while the current one decodes. Only one model is
      // decoded at a time so concurrent texture uploads stay bounded on mobile.
      function fetchEntry(entry) {
        return entry && modelBytes(entry.spec.glb, signal).then((bytes) => ({ bytes }), (error) => ({ error }));
      }
      let pending = fetchEntry(entries[start]);
      for (let index = start; index < entries.length; index++) {
        const entry = entries[index];
        if (!active()) return;
        try {
          const download = await pending;
          if (!active()) return;
          pending = fetchEntry(entries[index + 1]);
          if (download.error) throw download.error;
          const record = await buildRecord(entry, download.bytes, active);
          if (!active()) {
            if (record) releaseRecord(record);
            return;
          }
          if (!record.prop) entry.group.add(record.root);
          records.push(record);
          if (entry.group === stage) {
            grid.visible = false;
            frameAll();
            playbackFrame(currentTime);
          }
        } catch (error) {
          if (!signal.aborted && !disposed && options && options.onError) options.onError(error.message);
        }
      }
      if (!active()) return;
      const title = await global.MVStudioTitle?.apply(T, scene, value.stageTitle);
      if (!active()) {
        title?.dispose();
        return;
      }
      stageTitle = title;
      const ribbons = await global.MVStudioTitle?.apply(T, scene, value.stageRibbons, {ribbons: true});
      if (!active()) {
        ribbons?.dispose();
        return;
      }
      stageRibbons = ribbons;
      const shine = await global.MVStudioRibbonShine?.apply(T, scene, value.stageRibbons?.shine);
      if (!active()) {
        shine?.dispose();
        return;
      }
      stageShine = shine;
      const particles = await global.MVStudioStageParticles?.apply(T, scene, value.stageParticles);
      if (!active()) {
        particles?.dispose();
        return;
      }
      stageParticles = particles;
      stageSpotlight = global.MVStudioStageSpotlight?.apply(T, scene, value.stageSpotlight);
      const speedBack = await global.MVStudioSpeedBack?.apply(T, scene, value.stageSpeedBack);
      if (!active()) {
        speedBack?.dispose();
        return;
      }
      stageSpeedBack = speedBack;
      const displayLights = await global.MVStudioDisplayLights?.apply(T, scene, value.stageDisplayLights);
      if (!active()) {
        displayLights?.dispose();
        return;
      }
      stageDisplayLights = displayLights;
      const displayAtlases = {
        displayLights: displayLights?.texture || value.stageDisplayLights?.texture,
        speedBackCenterStars: speedBack?.centerTexture || value.stageSpeedBack?.centerStars?.texture,
      };
      const fallingEffects = await global.MVStudioFallingDisplay?.apply(T, scene, value.stageFallingEffects, displayAtlases);
      if (!active()) {
        fallingEffects?.dispose();
        return;
      }
      stageFallingEffects = fallingEffects;
      const fracture = await global.MVStudioStageBreak?.apply(T, scene, value.stageBreak, displayAtlases);
      if (!active()) {
        fracture?.dispose();
        return;
      }
      stageBreak = fracture;
      const finaleFloor = await global.MVStudioFinaleFloor?.apply(T, scene, value.stageFinaleFloor, displayAtlases);
      if (!active()) {
        finaleFloor?.dispose();
        return;
      }
      stageFinaleFloor = finaleFloor;
      const sparksB = await global.MVStudioStageSparks?.apply(T, scene, value.stageSparksB, displayAtlases, "B");
      if (!active()) {
        sparksB?.dispose();
        return;
      }
      stageSparksB = sparksB;
      const sparksA = await global.MVStudioStageSparks?.apply(T, scene, value.stageSparksA, displayAtlases, "A");
      if (!active()) {
        sparksA?.dispose();
        return;
      }
      stageSparksA = sparksA;
      const sparksRoop = await global.MVStudioStageSparks?.apply(T, scene, value.stageSparksRoop, displayAtlases, "roop");
      if (!active()) {
        sparksRoop?.dispose();
        return;
      }
      stageSparksRoop = sparksRoop;
      loadedProjectToken = typeof value.token === "string" ? value.token : null;
      grid.visible = !stage.children.length;
      frameAll();
      seek(currentTime, project);
    }

    function poseCamera(event, time, track, camera = liveCamera) {
      const value = event.values || {};
      const local = Math.min(event.duration, Math.max(0, time - event.start));
      const frames = value.keyframes;
      if (Array.isArray(frames) && !sortedCameraFrames.has(frames)) {
        sortedCameraFrames.set(frames, frames.every((frame, index) => !index || frame.time >= frames[index - 1].time));
      }
      const [left, right] = cameraSamples(event, local, sortedCameraFrames.get(frames));
      if (!vector(left.position, 3) || !vector(left.rotation, 4)) return false;
      const fraction = left !== right && right.time > left.time ? Math.max(0, Math.min(1, (local - left.time) / (right.time - left.time))) : 0;
      position.fromArray(left.position);
      if (vector(right.position, 3)) position.lerp(otherPosition.fromArray(right.position), fraction);
      camera.position.set(-position.x, position.y, position.z);
      rotation.fromArray(left.rotation).normalize();
      if (vector(right.rotation, 4)) rotation.slerp(otherRotation.fromArray(right.rotation).normalize(), fraction);
      // The native camera child faces -Z through its 180-degree Y turn.
      // Three already looks down -Z. Mirror X to match the exported meshes.
      camera.quaternion.set(rotation.x, -rotation.y, -rotation.z, rotation.w);
      const native = track.nativeClass === "AnimationTrack" && /(?:^|\/)MainCamera$/i.test(track.binding || "");
      const near = native || camera !== liveCamera ? 0.1 : 0.02;
      let fov = Number.isFinite(left.fov) ? left.fov : value.fov;
      if (!Number.isFinite(fov) && (native || camera !== liveCamera)) fov = 30;
      let sampled = camera === liveCamera ? authoredMainFov : camera.fov;
      if (Number.isFinite(fov)) {
        const next = Number.isFinite(right.fov) ? right.fov : fov;
        sampled = Math.min(170, Math.max(1, fov + (next - fov) * fraction));
      }
      if (camera === liveCamera) {
        nativeMainLens = native;
        authoredMainFov = sampled;
        sampled = liveFov();
      }
      if (camera.fov !== sampled || camera.near !== near) {
        camera.fov = sampled;
        camera.near = near;
        camera.updateProjectionMatrix();
      }
      return true;
    }

    function lightValue(event, keys) {
      const values = event.values || {};
      for (const key of keys) if (Object.prototype.hasOwnProperty.call(values, key)) return values[key];
      return null;
    }

    function setColor(target, value, fallback) {
      if (vector(value, 3) || vector(value, 4)) target.setRGB(value[0], value[1], value[2]);
      else if (value && Number.isFinite(value.r) && Number.isFinite(value.g) && Number.isFinite(value.b)) target.setRGB(value.r, value.g, value.b);
      else target.setHex(fallback);
    }

    function frameTracks(time, tracks, quality, [ambient, key, rim], onCamera) {
      ambient.color.setHex(0xe4edff);
      ambient.intensity = 1.2;
      key.color.setHex(0xffffff);
      key.intensity = 2.1;
      rim.color.setHex(0x8bb6ff);
      rim.intensity = 1.0;
      for (const track of tracks) {
        const event = track.kind === "camera" ? activeCameraEvent(track, time) : activeEvent(track, time);
        if (!event) continue;
        if (track.kind === "camera") {
          onCamera?.(event, time, track);
        } else {
          const label = event.values.playableClass;
          if (label === "LiveBaseLightClip") {
            setColor(ambient.color, lightValue(event, ["ambientColor"]), 0xe4edff);
            setColor(rim.color, lightValue(event, ["rimlightColor"]), 0x8bb6ff);
            const strength = lightValue(event, ["rimlightIntensity"]);
            if (Number.isFinite(strength)) rim.intensity = Math.max(0, Math.min(10, strength));
          } else if (label === "LiveStageAmbientClip" && quality.stage_ambient !== false) {
            setColor(key.color, lightValue(event, ["color", "tintColor"]), 0xffffff);
          } else if (label === "LiveRimlightClip" && quality.member_rim_light !== false) {
            setColor(rim.color, lightValue(event, ["color"]), 0x8bb6ff);
          }
        }
      }
      if (quality.stage_ambient === false) ambient.intensity = 0.6;
      if (quality.base_light === false) key.intensity = 0.8;
      if (quality.member_rim_light === false) rim.intensity = 0;
    }

    function useCameraEvent(event, time, track) {
      if (!poseCamera(event, time, track)) return;
      hasShot = true;
      mainCameraPosition.copy(liveCamera.position);
      applyCameraOffsets(liveCamera, track.binding, time);
    }

    function sampleSplitCamera(camera, track, time) {
      const event = activeCameraEvent(track, time);
      if (!event || !poseCamera(event, time, track, camera)) return false;
      applyCameraOffsets(camera, track.binding, time);
      return true;
    }

    function applyCameraOffsets(camera, binding, time) {
      const weight = global.ViewerMotionTimeline?.weight, clips = cameraOffsets.get(binding);
      if (!weight || !clips) return;
      let offset = 0;
      for (const clip of clips) {
        if (time >= clip.start && time < clip.start + clip.duration) offset += clip.offset * weight(clip, time);
      }
      // LiveCameraOffset writes the animated rig's child local Y, so pitched
      // and rolled shots must rotate this correction with the rig.
      if (offset) camera.position.add(otherPosition.set(0, offset, 0).applyQuaternion(camera.quaternion));
    }

    function applyProject() {
      const tracks = project && project.tracks || [];
      settings = project && project.quality && project.quality.values || {};
      if (trackSource !== tracks) {
        trackSource = tracks;
        nativeEvents.clear();
        for (const track of tracks) if (["dance", "mouth", "eyes", "gaze", "cheek"].includes(track.kind)) {
          for (const event of track.events) nativeEvents.set(event.id, { track, event });
        }
      }
      performers.clear();
      renderTracks = tracks.filter((track) => !track.muted && (track.kind === "lighting" ||
        (track.kind === "camera" && track.nativeClass !== "LiveCameraOffsetTrack" &&
          (!track.binding || /MainCamera/i.test(track.binding)))));
      const cast = project && project.performers || [];
      for (const performer of cast) performers.set(performer.id, performer);
      const heights = new Map(cast.map((performer) => [performer.position, heightScale(performer)]));
      memberScaleTracks.clear();
      memberCullingTracks.clear();
      memberShaftTracks.clear();
      memberAreaTracks.clear();
      cameraOffsets.clear();
      for (const track of tracks) {
        if (!track.muted && track.nativeClass === "LiveMemberSpotLightShaftTrack") {
          const bound = /^\/EntryPoint\/Live\/Members\/Member([1-9])$/.exec(track.binding || "");
          const slot = track.shaftSlot ?? (bound ? Number(bound[1]) : null);
          if (bound && slot === Number(bound[1])) {
            const events = track.events.filter(event => event.values?.playableClass === "LiveMemberSpotLightShaftClip");
            if (events.length) memberShaftTracks.set(slot, (memberShaftTracks.get(slot) || []).concat(events));
          }
          continue;
        }
        if (!track.muted && track.nativeClass === "LiveMemberSpotLightAreaTrack") {
          const binding = /^\/EntryPoint\/Live\/Members\/Member([1-9])$/.exec(track.binding || "");
          if (binding) {
            const slot = Number(binding[1]);
            const events = track.events.filter(event => event.values?.playableClass === "LiveMemberSpotLightAreaClip");
            if (events.length) memberAreaTracks.set(slot, (memberAreaTracks.get(slot) || []).concat(events));
          }
          continue;
        }
        if (!track.muted && track.nativeClass === "LiveMemberCullerTrack") {
          const slot = /^\/EntryPoint\/Live\/Members\/Member([1-9])$/.exec(track.binding || "");
          if (slot) {
            const position = Number(slot[1]);
            const events = track.events.filter(event => event.values?.playableClass === "LiveMemberCullerClip" && event.duration > 0);
            if (events.length) memberCullingTracks.set(position, (memberCullingTracks.get(position) || []).concat(events));
          }
          continue;
        }
        if (!track.muted && track.nativeClass === "LiveMemberScalingTrack") {
          const bound = /^\/EntryPoint\/Live\/Members\/Member([1-9])\/Model$/.exec(track.binding || "");
          if (!bound) continue;
          const slot = Number(bound[1]);
          const clips = memberScaleTracks.get(slot) || [];
          for (const event of track.events) {
            const values = event.values || {};
            if (values.playableClass !== "LiveMemberScalingClip" || !Number.isFinite(values.intensity)) continue;
            clips.push({ start: event.start, duration: event.duration, intensity: values.intensity,
              timing: { ...values, mixIn: values.mixIn?.length ? values.mixIn : offsetMixIn,
                mixOut: values.mixOut?.length ? values.mixOut : offsetMixOut } });
          }
          if (clips.length) memberScaleTracks.set(slot, clips);
          continue;
        }
        if (track.muted || track.kind !== "camera" || track.nativeClass !== "LiveCameraOffsetTrack" || !track.binding) continue;
        const clips = cameraOffsets.get(track.binding) || [];
        for (const event of track.events) {
          const values = event.values || {};
          if (values.playableClass !== "LiveCameraOffsetClip" || !Number.isFinite(values.intensity)) continue;
          const offset = ((heights.get(values.memberPosition) ?? 1) - 1) * values.intensity;
          if (!offset) continue;
          clips.push({ start: event.start, duration: event.duration, offset,
            timing: { ...values, mixIn: offsetMixIn, mixOut: offsetMixOut } });
        }
        if (clips.length) cameraOffsets.set(track.binding, clips);
      }
      split?.setProject(project);
      effects.visible = project?.source?.kind === "game" || settings.stage_control !== false;
      stageTitle?.invalidate();
      stageRibbons?.invalidate();
      stageShine?.invalidate();
      stageSpotlight?.invalidate();
      stageSpeedBack?.invalidate();
      stageDisplayLights?.invalidate();
      stageFallingEffects?.invalidate();
      stageBreak?.invalidate();
      stageFinaleFloor?.invalidate();
      stageSparksA?.invalidate();
      stageSparksB?.invalidate();
      stageSparksRoop?.invalidate();
      for (const record of records) {
        for (const entry of record.visibility) entry.node.visible = settings[entry.quality] !== false;
        record.penlight?.invalidate();
        record.stageFlash?.invalidate();
        record.stageColoring?.invalidate();
        record.stageDisplay?.invalidate();
        if (record.motion) updateMotion(record);
        record.materials?.setRimlight?.(settings.member_rim_light !== false);
        if (record.prop) record.prop.setTracks(tracks);
        record.propLight?.setProject(project);
      }
    }

    function resetPhysics(reason) {
      physicsClock?.reset();
      resetShafts = true;
      lastShaftFrame = null;
      for (const record of records) {
        record.physics?.reset(reason);
        record.spotlightArea?.reset();
      }
    }

    function seek(time, value, deferDraw = false) {
      if (disposed) return;
      if ((value && value !== project) || (Number.isFinite(time) && Math.abs(time - currentTime) > 1e-9)) resetPhysics("seek");
      project = value || project;
      applyProject();
      playbackFrame(time, undefined, deferDraw);
    }

    function setPlaying(value) {
      if (playing === value) return;
      playing = value;
      physicsClock?.reset();
      lastShaftFrame = null;
      lastPlaybackFrame = null;
      slowFrames = 0;
      if (!playing && previewScale !== 1) {
        previewScale = 1;
        viewportDirty = true;
      }
    }

    function playbackFrame(time, frameTimestamp, deferDraw = false) {
      if (disposed) return;
      if (Number.isFinite(frameTimestamp) && time < currentTime - 1e-9) resetPhysics("clock-rewind");
      currentTime = Number.isFinite(time) ? time : 0;
      // Reduce only the temporary playback buffer when the browser has
      // missed several 30 fps frames. Pausing restores the selected quality.
      if (playing && Number.isFinite(frameTimestamp) && previewScale > 0.5) {
        if (lastPlaybackFrame !== null && frameTimestamp - lastPlaybackFrame > 40) slowFrames++;
        else slowFrames = 0;
        lastPlaybackFrame = frameTimestamp;
        if (slowFrames === 4) {
          slowFrames = 0;
          previewScale = Math.max(0.5, previewScale * 0.75);
          viewportDirty = true;
        }
      }
      hasShot = false;
      frameTracks(currentTime, renderTracks, settings, lights, useCameraEvent);
      post?.evaluate(project, currentTime);
      activeSplitGazeCameras = split?.sample(currentTime, sampleSplitCamera) ?? null;
      const lighting = global.MVStudioLighting?.sample(project, currentTime);
      stageTitle?.update(currentTime, project);
      stageRibbons?.update(currentTime, project);
      stageShine?.update(currentTime, project);
      stageParticles?.update(currentTime, project);
      stageSpotlight?.update(currentTime, project);
      stageSpeedBack?.update(currentTime, project);
      stageDisplayLights?.update(currentTime, project);
      stageFallingEffects?.update(currentTime, project);
      stageBreak?.update(currentTime, project);
      stageFinaleFloor?.update(currentTime, project);
      stageSparksA?.update(currentTime, project);
      stageSparksB?.update(currentTime, project);
      stageSparksRoop?.update(currentTime, project);
      for (const record of records) record.stageFlash?.update(currentTime, project);
      for (const record of records) record.stageMotion?.update(currentTime, project);
      for (const record of records) record.penlight?.update(currentTime, project);
      for (const record of records) record.stageMaterial?.update(currentTime, project, lighting);
      for (const record of records) record.stageColoring?.update(currentTime, project);
      for (const record of records) record.stageDisplay?.update(currentTime, project);
      for (const record of records) {
        if (record.group !== actors) continue;
        // Both native camera paths exclude the member's Invisible layer.
        // Keep sampling its transforms so other actors can still track it.
        const culled = memberCullingTracks.get(record.position)?.some(event =>
          currentTime >= event.start && currentTime < event.start + event.duration);
        record.root.visible = record.actorVisible && !culled;
        record.materials?.setLiveLighting?.(lighting?.member(record.position));
        record.physics?.restorePose();
        record.nodeScaling?.resetHeight();
        const performer = performers.get(record.id);
        if (performer) actorPose(record, performer);
        if (record.motion) {
          record.motion.evaluatePose(currentTime);
          record.motion.applyVisibility(currentTime);
        } else if (record.mixer) record.mixer.setTime(currentTime);
        record.nodeScaling?.applyHeight(memberScaleTracks.get(record.position), currentTime);
      }
      // Native performers look at the other actor's animated Eye_Root, so
      // prepare every actor at this timestamp before resolving any gaze.
      const targets = gazeContext();
      for (const record of records) if (record.motion) record.motion.evaluateGaze(currentTime, targets);
      const physicsStep = playing && visible && records.some((record) => record.physics)
        ? physicsClock?.step(frameTimestamp, settings.frame_rate_60fps === true ? 60 : 30) || 0 : 0;
      for (const record of records) record.physics?.apply(currentTime, physicsStep, settings, record.motion);
      // Unity gates both native member spot light tracks on the Area quality value.
      const shaftTemplates = records.find(record => record.shaftTemplates)?.shaftTemplates;
      if (shaftTemplates) {
        const timestamp = playing && Number.isFinite(frameTimestamp) ? frameTimestamp : null;
        const elapsed = timestamp === null || lastShaftFrame === null ? 0 : (timestamp - lastShaftFrame) / 1000;
        for (const record of records) {
          if (!record.shaftAnchor) continue;
          const clips = memberShaftTracks.get(record.position);
          if (!record.shaft && clips) {
            record.shaft = global.MVStudioShaft?.create(T, shaftTemplates, record.root, record.shaftAnchor);
          }
          record.shaft?.frame(settings.member_spot_light_area !== false ? clips : null,
            currentTime, Math.max(0, elapsed), liveCamera, project, resetShafts || elapsed < 0 || elapsed > 0.25);
        }
        lastShaftFrame = timestamp;
        resetShafts = false;
      }
      const areaTemplate = records.find(record => record.areaTemplate)?.areaTemplate;
      if (areaTemplate) for (const record of records) {
        if (!record.shaftAnchor) continue;
        const clips = settings.member_spot_light_area !== false ? memberAreaTracks.get(record.position) : null;
        if (!record.spotlightArea && clips) {
          record.spotlightArea = global.MVStudioSpotlightArea?.create(T, areaTemplate, record.shaftAnchor);
        }
        record.spotlightArea?.frame(clips, currentTime, project);
      }
      for (const record of records) if (record.prop) {
        record.prop.bind(records.find((actor) => actor.group === actors && actor.position === record.propMember) || null);
        record.prop.evaluate(currentTime);
        if (record.root.visible) record.propMaterial?.setLiveLighting?.(record.propLight?.sample(currentTime));
      }
      if (viewportDirty || renderHeight !== settings.rendering_resolution) resize();
      else if (deferDraw && visible) {
        // Motion sampling is still synchronous. Preserve the world matrices
        // the next facial/gaze evaluation would have seen after a render.
        if (scene.autoUpdate) scene.updateMatrixWorld();
        const camera = useLive && hasShot ? liveCamera : editorCamera;
        if (camera.parent === null) camera.updateMatrixWorld();
        seekDrawPending = true;
        requestDraw();
      } else draw();
    }

    const observer = global.ResizeObserver ? new global.ResizeObserver(() => resize(false)) : null;
    if (observer) observer.observe(mount);
    controls.addEventListener("change", requestDraw);
    resize();
    return {
      load, prepareStage, cancelStagePreparation, seek, playbackFrame, setPlaying, resize,
      flushSeekDraw() { if (seekDrawPending) draw(); },
      setCamera(mode) { useLive = mode !== "orbit"; draw(); },
      frameAll,
      setVisible(value) {
        const changed = visible !== Boolean(value);
        visible = Boolean(value);
        if (visible) resize(changed);
        else cancelDraw();
      },
      dispose() {
        disposed = true;
        if (request) request.abort();
        cancelStagePreparation(false);
        if (observer) observer.disconnect();
        cancelDraw();
        clear();
        split?.dispose();
        post?.dispose();
        release(grid);
        controls.dispose();
        renderer.dispose();
        renderer.domElement.remove();
      }
    };
  }

  global.MVStudioScene = { create };
}(window));
