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

  // The camera clip that ends last, when `time` is past its end: an original MV
  // holds that shot's final pose (see frameTracks).
  function endedCameraEvent(track, time) {
    let last = null;
    for (const event of track.events) if (!last || event.start + event.duration > last.start + last.duration) last = event;
    return last && time > last.start + last.duration ? last : null;
  }

  // The director time the music ends at: the audio plays at director time + the
  // soundtrack offset (MVStudio seek), so FinishLiveMv runs at duration - offset.
  function musicEnd(project) {
    const soundtrack = project?.soundtrack;
    if (!Number.isFinite(soundtrack?.duration)) return project?.duration;
    return Math.max(0, soundtrack.duration - (Number.isFinite(soundtrack.offset) ? soundtrack.offset : 0));
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
    // Editor backdrop; a game project uses the native MainCamera clear (see applyProject).
    const editorClear = 0x111522;
    renderer.setClearColor(editorClear);
    renderer.shadowMap.type = T.PCFSoftShadowMap;
    renderer.domElement.setAttribute("aria-label", "MV stage preview");
    mount.appendChild(renderer.domElement);
    const split = global.MVStudioSplit?.create(T, renderer);
    const physicsClock = global.MVStudioPhysics?.createClock();
    let physicsTiming = global.MVStudioPhysics?.normalizeTiming?.() ?? null;
    const post = global.MVStudioPost?.create(T, renderer);
    // LiveMvDarkFilterField and the live-end overlay blur (see mv-studio-screen-fade.js).
    const screenFade = global.MVStudioScreenFade?.create(T, renderer);
    let screenFadeEnabled = options?.screenFade !== false;
    const overlay = global.MVStudioStageOverlay?.create(T, renderer);
    const cameraDepth = global.MVStudioCameraDepth?.create(T, renderer);
    const transparentSort = global.MVStudioTransparentSort?.create(T, renderer);
    // The Live* mixers' input walk over the frame clock (LiveMixerBase`2.ProcessWithoutSeek):
    // MVStudioLighting.nativeWeight leaves out the inputs it skipped.
    const mixers = global.MVStudioMixer?.controller((event, time) => global.MVStudioLighting.clipWeight(event, time)) ?? null;
    global.MVStudioMixer?.activate(mixers);

    const scene = new T.Scene();
    const editorCamera = new T.PerspectiveCamera(48, 1, 0.02, 1000);
    const liveCamera = new T.PerspectiveCamera(42, 1, 0.02, 1000);
    // The game main camera's culling frustum at past frames (particle culling).
    const cullingCamera = new T.PerspectiveCamera(30, 1, 0.1, 1000);
    // Scratch for the shaft anchor sample (shaftAnchorAt).
    const anchorSample = [0, 0, 0];
    let cullingView = null;
    const stageCamera = new T.PerspectiveCamera(48, 1, 0.02, 1000);
    const controls = new T.OrbitControls(editorCamera, renderer.domElement);
    const stage = new T.Group(), actors = new T.Group(), effects = new T.Group(), memberShadows = new T.Group();
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
    scene.add(stage, actors, effects, memberShadows, grid, ambient, key, rim);
    // The scene's fixed roots otherwise dirty the world matrix of every
    // descendant on each render. Dancers and both cameras still animate.
    for (const node of [scene, stage, actors, effects, memberShadows, grid, ambient, key, rim]) {
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
    let stageButterfly = null, stageRain = null, stageLeaves = null, stageMomiji = null, stageConfetti = null, stageGlow = null, stageLens = null;
    let stageSpeedBack = null, stageDisplayLights = null, stageFallingEffects = null, stageBreak = null, stageFinaleFloor = null;
    let stageSparksA = null, stageSparksB = null, stageSparksRoop = null;
    let stageParticleSystems = null, stageControlPrefabs = null;
    let activeSplitGazeCameras = null;
    let loadedProjectToken = null, defaultMemberShadows = false, memberShadowTracks = [], memberShadowPrefabs = null;
    let currentTime = 0, useLive = true, hasShot = false, records = [], queuedDraw = 0, seekDrawPending = false;
    let liveCameraEvent = null;
    let playing = false, lastPlaybackFrame = null, slowFrames = 0, previewScale = 1, adaptivePreview = true;
    let lastShaftFrame = null, resetShafts = true;
    // Client state that changes only on rendered frames (the director's beat
    // origin, the ambient components' last written colors, the cheek floats
    // MemberCheekMixer leaves after a clip): an advancing playback frame
    // continues it; a seek replays the rendered frame times it is given (seek's
    // `history`) or, without them, uses exact values. One frame clock serves all.
    let pendingHistory = null, frameClock = { advancing: false, history: [] }, historyLighting = new Map();
    // The game's Time.time as a function of director time (setGameClock; null: the director's clock).
    // Original particle systems advance on it (MVStudioParticleSystems.gameClock).
    let particleClock = null;
    let renderHeight = null, viewportDirty = false, settings = {}, trackSource = null, renderTracks = [];
    // The player's anti-aliasing option (GameSettingsDM.GetAntiAliasingMode, off unless saved).
    let antiAliasing = options?.antiAliasing === true;
    let nativeMainLens = false, authoredMainFov = liveCamera.fov;
    const cameraOffsets = new Map();
    const nativeEvents = new Map(), performers = new Map(), sortedCameraFrames = new WeakMap(), memberScaleTracks = new Map();
    const memberCullingTracks = new Map();
    // A LiveMemberCullerClip moves the member to the Invisible layer, which both
    // native camera paths exclude; the editor hides the member's root instead.
    function memberCulledAt(position, time) {
      return Boolean(memberCullingTracks.get(position)?.some(event => time >= event.start && time < event.start + event.duration));
    }
    const memberShaftTracks = new Map(), memberAreaTracks = new Map();
    const releasedSkeletons = new WeakSet();
    const size = new T.Vector2();
    const displayOrder = [], displayEye = new T.Vector3(), displayPoint = new T.Vector3();
    const bounds = new T.Box3(), skinMatrix = new T.Matrix4(), boneMatrix = new T.Matrix4();
    const culled = [];
    const position = new T.Vector3(), otherPosition = new T.Vector3();
    const mainCameraPosition = new T.Vector3(), focusPosition = new T.Vector3();
    // MainCamera rig view axis (-transform.forward), read by DOF cameraAutoDistanceMode 2.
    const mainCameraDirection = new T.Vector3(0, 0, -1), focusOffset = new T.Vector3();
    // LiveDepthOfFieldMixer runs in the director's script pass, before this
    // frame's Animator writes the camera and members. Its focus distances read
    // the transforms the previous frame left (Max 3D: every first frame after a
    // cut keeps the old shot's focus). Snapshot those at the start of each
    // continuing playback frame; a seek evaluates the current pose.
    const focusLag = { valid: false, camera: new T.Vector3(), direction: new T.Vector3(), points: new Map(), pool: new Map() };
    // The mixer's transition fields advance once per evaluated frame (dofState);
    // draws and the asset dump re-evaluate the frame from a copy of the state
    // it started with (dofFrameState).
    let dofState = global.MVStudioDofFocus?.createState?.() ?? null, dofFrameState = dofState && { ...dofState };
    // The depth of field the last evaluated frame applied, and the one the
    // frame before it left. A frame on the client's exception path (a missing
    // member or a body part partMap lacks) keeps dofPrevious's settings and
    // resolves its lens at the current camera FOV, as
    // DepthOfFieldComponent.CalculateFocalLength does at render time. With no
    // earlier evaluated frame (after a load, or a seek, which cannot replay the
    // frames before it) the preview draws none; the client's only writer
    // besides the mixer's PostProcess, LiveCoreCameraPostProcess.SetDisabledAll
    // on the director's reset path, only turns the depth of field off.
    let dofApplied = null, dofPrevious = null;
    const dofWarnings = new Set();
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
          drawWorld(preparation.scene, stageCamera, preparation.records, preparation.preview.quality?.mode);
          return;
        }
        // Drags move the free camera only while it is the camera drawn (camera editor).
        controls.enabled = !(useLive && hasShot);
        if (!(useLive && split?.draw(renderView, hasShot ? liveCamera : null))) {
          // The game camera's frustum, only while the free camera draws (never in captures).
          const helper = !useLive && hasShot ? showGameCameraHelper() : null;
          renderView(useLive && hasShot ? liveCamera : editorCamera);
          if (helper) scene.remove(helper);
        }
        if (useLive && settings.stage_overlay_effect !== false) {
          const particles = stageLens?.sortEntries(20);
          if (particles?.length || records.some((record) => record.stageOverlay?.hasVisible())) {
            overlay?.draw(scene, particles?.length ? camera => sortTransparentParticles(camera, particles) : undefined);
          }
        }
        if (useLive && screenFadeEnabled && project?.source?.kind === "game") {
          // FinishLiveMv runs on LiveMusicMachine.OnFinishMusic, at the music end.
          screenFade?.draw(global.MVStudioScreenFade.state(currentTime, musicEnd(project)));
        }
      }
    }

    function renderView(camera) {
      if (camera === liveCamera && post) {
        const source = focusSource();
        const focus = global.MVStudioDofFocus?.sample(project, currentTime, camera.fov, source.distance, source.options);
        const preserveDepth = useLive && settings.stage_overlay_effect !== false &&
          records.some(record => record.stageOverlay?.hasDepthTest());
        if (post.draw(() => renderScene(camera), Boolean(focus), focus, camera, preserveDepth)) return;
      }
      renderScene(camera);
    }

    function prepareSoftDepth(source, camera, sceneRecords, qualityMode) {
      const visibleEffects = sceneRecords.filter(({stageSoftBillboards}) => stageSoftBillboards?.hasVisible());
      if (!visibleEffects.length) return;
      // The live camera requests a separate opaque depth texture in the three full 3D modes.
      const depth = (qualityMode ?? 30) <= 30 ? cameraDepth?.capture(source, camera) : null;
      for (const {stageSoftBillboards} of visibleEffects) stageSoftBillboards.setDepth(depth, camera);
    }

    function drawWorld(source, camera, sceneRecords, qualityMode) {
      prepareSoftDepth(source, camera, sceneRecords, qualityMode);
      if (transparentSort) transparentSort.draw(source, camera, sceneRecords);
      else renderer.render(source, camera);
    }

    // A focus part is an exported node, or a fixed world point (BodyPartManager.face
    // keeps the uninstantiated facial prefab asset).
    function focusPoint(record, part, target, readOnly = false) {
      const point = record?.focusParts?.[part];
      if (!point) return null;
      if (point.isVector3) return target.copy(point);
      return readOnly ? target.setFromMatrixPosition(point.matrixWorld) : point.getWorldPosition(target);
    }

    function captureFocusLag(valid) {
      focusLag.valid = valid;
      focusLag.points.clear();
      if (!valid) return;
      focusLag.camera.copy(mainCameraPosition);
      focusLag.direction.copy(mainCameraDirection);
      for (const record of records) {
        if (record.group !== actors || !record.focusParts) continue;
        for (const part of Object.keys(record.focusParts)) {
          const key = record.position + ":" + part;
          let point = focusLag.pool.get(key);
          if (!point) focusLag.pool.set(key, point = new T.Vector3());
          if (focusPoint(record, part, point)) focusLag.points.set(key, point);
        }
      }
    }

    function focusMembers() {
      return records.filter(record => record.group === actors && Number.isInteger(record.position))
        .map(record => record.position).sort((a, b) => a - b);
    }

    // Every performer slot of the MV, loaded or not (LiveCoreMemberManager.MemberMax 12).
    function focusPerformers() {
      return (project?.performers || []).slice(0, 12).map(performer => performer?.position).filter(Number.isInteger);
    }

    // Distance/angle sources for MVStudioDofFocus.sample: the lagged snapshot
    // while playback continues, else the current pose.
    function focusSource(readOnly = false) {
      const lagged = focusLag.valid;
      const camera = lagged ? focusLag.camera : mainCameraPosition;
      const direction = lagged ? focusLag.direction : mainCameraDirection;
      const point = (slot, part) => lagged ? focusLag.points.get(slot + ":" + part) || null :
        focusPoint(records.find(record => record.group === actors && record.position === slot), part, focusPosition, readOnly);
      const distance = (slot, part) => point(slot, part)?.distanceTo(camera);
      const sampleOptions = {
        members: focusMembers(),
        performers: focusPerformers(),
        angle: (slot, part) => {
          const target = point(slot, part);
          return target ? global.MVStudioDofFocus.vectorAngle(direction, focusOffset.subVectors(target, camera)) : undefined;
        },
        state: dofFrameState && { ...dofFrameState },
        previous: dofPrevious,
        // Each distinct message reaches the console and the studio's warning
        // list once per loaded project.
        warn: readOnly ? undefined : (message) => {
          if (dofWarnings.has(message)) return;
          dofWarnings.add(message);
          global.console?.warn?.(message);
          options?.onWarning?.(message);
        },
      };
      return { distance, options: sampleOptions };
    }

    function advanceFocus() {
      if (!dofState || !global.MVStudioDofFocus) return;
      dofFrameState = { ...dofState };
      dofPrevious = dofApplied;
      const source = focusSource();
      dofApplied = global.MVStudioDofFocus.sample(project, currentTime, liveCamera.fov, source.distance,
        { ...source.options, state: dofState }) ?? null;
    }

    function sortRibbonDisplay(camera) {
      for (const {mesh} of displayOrder) mesh.renderOrder = 2900;
      displayOrder.length = 0;
      if (!stageMomiji && !stageShine) return;
      camera.updateMatrixWorld();
      const transition = stageMomiji?.sortEntries(camera), shine = stageShine?.sortEntries();
      if (!transition?.length && !shine?.length) return;
      displayOrder.push(...(transition || []), ...(stageRibbons?.ribbonSortEntries() || []), ...(shine || []));
      displayEye.setFromMatrixPosition(camera.matrixWorld);
      for (const entry of displayOrder) {
        const depth = camera.isOrthographicCamera ? -displayPoint.copy(entry.center).applyMatrix4(camera.matrixWorldInverse).z :
          displayEye.distanceToSquared(entry.center);
        entry.distance = Math.fround(depth);
      }
      // The ribbon sheets and separate particle renderers share the same
      // Unity queue. Sort their whole bounds before drawing this camera.
      displayOrder.sort((a, b) => b.distance - a.distance || a.order - b.order);
      displayOrder.forEach(({mesh}, rank) => { mesh.renderOrder = 2900 + rank * .01; });
    }

    function sortControlParticles(camera) {
      if (!stageLeaves && !stageConfetti && !stageGlow && !stageLens) return;
      const leaves = stageLeaves?.sortEntries() || [], confetti = stageConfetti?.sortEntries() || [];
      const glow = stageGlow?.sortEntries() || [], lens = stageLens?.sortEntries() || [];
      const rain = stageRain?.sortEntries() || [];
      if (!leaves.length && !confetti.length && !glow.length && !lens.length) {
        for (const {mesh} of rain) mesh.renderOrder = 3010;
        return;
      }
      const entries = [...rain, ...(stageButterfly?.sortEntries() || []), ...leaves, ...confetti, ...glow, ...lens];
      sortTransparentParticles(camera, entries);
    }

    function sortTransparentParticles(camera, entries) {
      camera.updateMatrixWorld();
      displayEye.setFromMatrixPosition(camera.matrixWorld);
      const visible = entries.map(({mesh, center}, order) => {
        mesh.updateWorldMatrix(true, false);
        displayPoint.copy(center).applyMatrix4(mesh.matrixWorld);
        const depth = camera.isOrthographicCamera ? -displayPoint.applyMatrix4(camera.matrixWorldInverse).z :
          displayEye.distanceToSquared(displayPoint);
        return {mesh, order, distance: Math.fround(depth)};
      });
      // These particle renderers share queue 3010, where alpha-over leaves
      // can obscure additive particles depending on the camera.
      visible.sort((a, b) => b.distance - a.distance || a.order - b.order);
      visible.forEach(({mesh}, rank) => { mesh.renderOrder = 3010 + rank * .01; });
    }

    function renderScene(camera) {
      if (!stageBreak?.sort(camera, stageSpeedBack?.displaySortEntries)) stageSpeedBack?.sort(camera);
      stageDisplayLights?.sort(camera);
      stageFallingEffects?.sort(camera, stageTitle?.displaySortEntries);
      sortRibbonDisplay(camera);
      stageButterfly?.sort(camera);
      sortControlParticles(camera);
      for (const record of records) record.stageStationaryBursts?.sort(camera);
      // AxisBillboard follows the camera currently drawing each split layer.
      const billboardCamera = camera === editorCamera ? liveCamera : camera;
      for (const record of records) {
        record.shaft?.billboard(billboardCamera);
        record.axisBillboard?.apply(billboardCamera);
      }
      const projection = camera.projectionMatrix.elements;
      const { width, height } = renderer.domElement;
      if (camera !== liveCamera || renderer.shadowMap.enabled || !width || !height || projection[8] || projection[9] ||
          projection[11] !== -1 || projection[15] !== 0 || !(projection[0] > 0.001 && projection[5] > 0.001) ||
          !records.some((record) => record.skinBounds?.length)) {
        drawWorld(scene, camera, records, project?.quality?.mode);
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
        drawWorld(scene, camera, records, project?.quality?.mode);
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
      // The view's device pixels are the game's screen: the 3D cameras draw at the height the
      // client derives from RenderingResolution, the screen height and the anti-aliasing option
      // (nativeRenderHeight).
      const target = Number.isFinite(nativeHeight) && nativeHeight > 0
        ? nativeRenderHeight(nativeHeight, Math.floor(height * (global.devicePixelRatio || 1)), values.quality_mode, antiAliasing) : null;
      let resolution = target === null ? Math.min(global.devicePixelRatio || 1, 2) : Math.min(target / height, 2);
      // three.js floors height * ratio: keep the exact integer height.
      if (target !== null && resolution < 2 && Math.floor(height * resolution) < target) resolution = Math.min((target + 1e-6) / height, 2);
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
      record.stagePropLight?.dispose();
      record.stageColoring?.dispose();
      record.stageDisplay?.dispose();
      record.stageOverlay?.dispose();
      record.stageSoftBillboards?.dispose();
      record.stageBeam?.dispose();
      record.stageLaserCores?.dispose();
      record.stageStationaryBursts?.dispose();
      record.memberShadow?.dispose();
      if (record.memberShadowPrefabs) {
        // Performers instance these templates under their anchors: drop those
        // meshes (and the scene's reference) before the templates are disposed.
        for (const item of records) item.memberShadow?.releasePrefabs?.(record.memberShadowPrefabs);
        if (memberShadowPrefabs === record.memberShadowPrefabs) memberShadowPrefabs = null;
        record.memberShadowPrefabs.dispose();
      }
      record.lossyScale?.dispose();
      record.physics?.dispose();
      record.constraints?.dispose();
      if (record.mixer) record.mixer.stopAllAction();
      if (record.root.parent) record.root.parent.remove(record.root);
      release(record.root);
    }

    function clear() {
      physicsClock?.reset();
      displayOrder.length = 0;
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
      stageLeaves?.dispose();
      stageLeaves = null;
      stageConfetti?.dispose();
      stageConfetti = null;
      stageGlow?.dispose();
      stageGlow = null;
      stageLens?.dispose();
      stageLens = null;
      stageMomiji?.dispose();
      stageMomiji = null;
      stageRain?.dispose();
      stageRain = null;
      stageButterfly?.dispose();
      stageButterfly = null;
      stageSparksRoop?.dispose();
      stageSparksRoop = null;
      stageParticleSystems?.dispose();
      stageParticleSystems = null;
      stageControlPrefabs?.dispose();
      stageControlPrefabs = null;
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

    // How game_motion_timeline imports a MemberLipSyncClip index 0: the vowel of its paramName.
    const lipSyncVowels = { a: 1, i: 2, u: 3, e: 4, o: 5, n: 6, m: 6 };

    function updateMotion(record) {
      let changed = false, facialChanged = false;
      const assign = (object, key, value) => {
        if (object[key] === value) return;
        object[key] = value;
        changed = true;
      };
      for (const segment of record.motionEvents) {
        const bound = nativeEvents.get(segment.nativeEventId);
        if (!bound) continue;
        const event = bound.event, values = event.values;
        if (segment.kind === "eyes" || segment.kind === "mouth") {
          // Facial clips are bound once per controller. An edited eye or mouth index
          // (the clip's index differs from its native one, kept in project.editor.originals
          // once edited) rebuilds the controller below; the imported index is used otherwise.
          if (!("importIndex" in segment)) {
            const native = project?.editor?.originals?.[event.id]?.values?.index;
            segment.nativeIndex = Number.isInteger(native) ? native : values.index;
            segment.importIndex = segment.index;
          }
          const edited = Number.isInteger(values.index) && values.index !== segment.nativeIndex;
          const index = !edited ? segment.importIndex : segment.kind === "mouth" && values.index === 0
            ? lipSyncVowels[String(values.paramName ?? "").toLowerCase()] ?? 0 : values.index;
          if (segment.index !== index) {
            segment.index = index;
            facialChanged = true;
          }
        }
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
        } else if (segment.kind === "eyes" && Number.isInteger(segment.splitIndex)) {
          // MemberEyeMixer.Process swaps in splitScreenSetting.Index/Weight
          // while the split screen is enabled (see ViewerMotionTimeline).
          const alternate = values.splitScreenSetting;
          const usesAlternate = (alternate?.UseSetting === 1 || alternate?.UseSetting === true) && Number.isFinite(alternate.Weight);
          assign(segment, "splitUse", usesAlternate);
          assign(segment, "splitWeight", usesAlternate && !bound.track.muted ? Math.min(1, Math.max(0, alternate.Weight)) : 0);
        } else if (segment.kind === "cheek") {
          if (Number.isInteger(values.cheekType)) assign(segment, "index", values.cheekType);
          if (Number.isFinite(values.intensity)) assign(segment, "intensity", Math.min(1, Math.max(0, values.intensity)));
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
      if (facialChanged && record.motionSource) {
        // The controller holds interpolants and no mixer: a new one over the loaded pose
        // (as the first was created) replaces it, then takes the current timing.
        const source = record.motionSource;
        if (record.initialPose) restoreActorPose(record.initialPose);
        record.motion = global.ViewerMotionTimeline.create(source.scene, source.animations, source.rig,
          { ...source.motion, bodySegments: record.segments, facial: { ...source.motion.facial, events: record.facialEvents } },
          { indexTiming: true });
        updateMotion(record);
        return;
      }
      if (changed && record.motion.invalidateTiming) record.motion.invalidateTiming();
    }

    // MemberEyeClip.splitScreenSetting {UseSetting, Index, Weight}: the alternate
    // clip index is fixed when the actor's facial inputs are bound.
    function eyeSplitIndex(event) {
      const alternate = event.kind === "eyes" && nativeEvents.get(event.nativeEventId)?.event.values.splitScreenSetting;
      if (alternate && (alternate.UseSetting === 1 || alternate.UseSetting === true) &&
          Number.isInteger(alternate.Index) && alternate.Index >= 0) event.splitIndex = alternate.Index;
      return event;
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
      // LiveCoreMemberManager.MemberMax: an MV has up to 12 performers.
      for (const performer of (value.performers || []).slice(0, 12)) {
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
        identity: entry.identity, visibility: [], rig: entry.spec.rig, role: entry.role };
      if (entry.group === effects) {
        record.memberShadowDefaults = gltf.scene.userData?.mvMemberShadowDefaults;
        record.memberShadowPrefabs = await global.MVStudioMemberShadow?.prefabs?.(T, gltf.scene, gltf.parser);
      }
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
          if (node.isSkinnedMesh && (entry.group === actors ||
              node.userData.mvStageSkin === true || node.parent?.userData.mvStageSkin === true)) node.frustumCulled = false;
          if (entry.group !== effects) return;
          for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
            const name = material.name || "";
            if (/(?:^|_)add(?:_|$)/i.test(name)) {
              material.blending = T.AdditiveBlending;
              material.transparent = true;
              material.depthWrite = false;
            }
            const quality = /(?:^|_)aud(?:_|$)/i.test(name) ? "stage_audience" :
              /(?:^|_)dis(?:_|$)/i.test(name) ? "stage_display" : null;
            const source = node.geometry.userData;
            if (quality && !source?.mvStageDisplay && !source?.mvStageOverlay?.world) {
              record.visibility.push({ node, quality });
            }
          }
        });
        if (entry.group !== actors) {
          record.stageMaterial = await global.MVStudioStageMaterial?.apply(T, record.root, gltf.parser, {
            active, maxTextureSize: renderer.capabilities.maxTextureSize,
          });
          if (!active()) return null;
          record.stagePropLight = await global.MVStudioPropLight?.apply?.(T, record.root, gltf.parser, { active });
          if (!active()) return null;
          record.stageColoring = await global.MVStudioStageColoring?.apply(T, record.root, gltf.parser);
          if (!active()) return null;
          record.stageDisplay = await global.MVStudioStageDisplay?.apply(T, record.root, gltf.parser);
          if (!active()) return null;
          record.stageOverlay = await global.MVStudioStageOverlay?.apply(T, record.root, gltf.parser, {
            active, maxTextureSize: renderer.capabilities.maxTextureSize,
          });
          if (!active()) return null;
          record.stageSoftBillboards = await global.MVStudioSoftBillboards?.apply(T, record.root, gltf.parser, {
            active, maxTextureSize: renderer.capabilities.maxTextureSize,
          });
          if (!active()) return null;
          record.stageBeam = await global.MVStudioStageBeam?.apply(T, record.root, gltf.parser);
          if (!active()) return null;
          record.shaftTemplates = await global.MVStudioShaft?.prepare(T, gltf);
          if (!active()) return null;
          record.areaTemplate = await global.MVStudioSpotlightArea?.prepare(T, gltf);
          if (!active()) return null;
          record.stageMotion = global.MVStudioStageMotion?.apply(T, record.root);
          record.axisBillboard = global.MVStudioAxisBillboard?.create(T, record.root);
          record.lossyScale = global.MVStudioLossyScale?.create(T, record.root);
          record.stageLaserCores = await global.MVStudioStageLaserCores?.apply(T, record.root, gltf.parser, {
            active, maxTextureSize: renderer.capabilities.maxTextureSize,
          });
          if (!active()) return null;
          record.stageStationaryBursts = await global.MVStudioStationaryBursts?.apply(T, record.root, gltf.parser, {
            active, maxTextureSize: renderer.capabilities.maxTextureSize,
          });
          if (!active()) return null;
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
          // focusParts: BodyPartType value -> exported node id, or {world} in Unity space.
          const parts = entry.spec.rig?.focusParts && typeof entry.spec.rig.focusParts === "object" ? entry.spec.rig.focusParts : {};
          const shaftAnchor = entry.spec.rig?.shaftAnchor;
          const boneIds = new Set([...Object.values(parts), shaftAnchor].filter(Number.isInteger));
          const nodes = new Map();
          if (boneIds.size) {
            gltf.scene.traverse(node => {
              const id = node.userData.elichika_node;
              if (boneIds.has(id)) nodes.set(id, nodes.has(id) ? null : node);
            });
            record.shaftAnchor = nodes.get(shaftAnchor);
          }
          record.focusParts = {};
          for (const [part, value] of Object.entries(parts)) {
            const world = value?.world;
            const point = Number.isInteger(value) ? nodes.get(value) :
              Array.isArray(world) && world.length === 3 && world.every(Number.isFinite)
                ? new T.Vector3(-world[0], world[1], world[2]) : null;
            if (point) record.focusParts[part] = point;
          }
          if (global.SifasMaterial) record.materials = global.SifasMaterial.apply(gltf.scene, renderer, {
            parser: gltf.parser, enabled: true, rimlight: true, onChange: requestDraw, liveMember: true,
            mouthCentroidDepth: renderer.capabilities.isWebGL2 === true, nativeMemberDepth: true, releaseParserAfterLoad: true
          });
          if (record.materials && record.materials.ready) await record.materials.ready;
          if (!active()) return null;
          const authoredMotion = entry.spec.motion && global.ViewerMotionTimeline;
          if (authoredMotion || !gltf.animations.length) record.initialPose = captureActorPose(record.root);
          if (authoredMotion) {
            record.segments = (entry.spec.motion.bodySegments || []).map((segment) => ({
              ...segment, timing: { ...segment.timing }
            }));
            record.facialEvents = (entry.spec.motion.facial?.events || []).map((event) => eyeSplitIndex({
              ...event, timing: { ...event.timing }
            }));
            record.motionEvents = record.segments.concat(record.facialEvents);
            record.motionSource = { scene: gltf.scene, animations: gltf.animations, rig: entry.spec.rig || {}, motion: entry.spec.motion };
            record.motion = global.ViewerMotionTimeline.create(gltf.scene, gltf.animations,
              entry.spec.rig || {}, { ...entry.spec.motion, bodySegments: record.segments,
                facial: { ...entry.spec.motion.facial, events: record.facialEvents } },
              { indexTiming: true });
            // LiveCoreMemberHead.InitializeDefault binds MemberCheekBase to the
            // merged face's material; a masked head has no cheek component.
            const cheekMaterial = entry.spec.rig?.memberHead?.cheekMaterial;
            if (typeof cheekMaterial === "string" && cheekMaterial) record.cheekMaterial = cheekMaterial;
            updateMotion(record);
          } else if (gltf.animations.length) {
            record.mixer = new T.AnimationMixer(gltf.scene);
            record.mixer.clipAction(gltf.animations[0]).play();
          }
          record.physics = global.MVStudioPhysics?.create(record.root, entry.spec.rig?.physics,
            entry.spec.motion?.physics ?? project?.motionPhysics);
          record.constraints = global.ViewerConstraints?.create(record.root, entry.spec.rig?.constraints);
          record.memberShadow = await global.MVStudioMemberShadow?.apply(T, record.root, gltf.parser, memberShadows);
          if (!active()) return null;
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
        record.constraints?.restorePose();
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
          record.stageSoftBillboards?.update(0);
          record.stageLaserCores?.update(0, preview, record.stageMotion);
          record.stageStationaryBursts?.update(0, preview, record.stageMotion);
          record.penlight?.update(0, preview);
          record.stageMaterial?.update(0, preview, lighting);
          record.stagePropLight?.setProject(preview);
          record.stagePropLight?.update(0);
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
      dofWarnings.clear();
      dofApplied = dofPrevious = null;
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

      // Optional loading progress for the caller: models done/total, then effects.
      const report = (update) => {
        try { if (active()) preferences?.onProgress?.(update); } catch (_) {}
      };
      report({ done: start, total: entries.length });

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
        report({ done: index + 1, total: entries.length });
      }
      if (!active()) return;
      report({ phase: "effects" });
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
      const butterfly = await global.MVStudioButterfly?.apply(T, scene, value.stageButterfly);
      if (!active()) {
        butterfly?.dispose();
        return;
      }
      stageButterfly = butterfly;
      const rain = await global.MVStudioStageRain?.apply(T, scene, value.stageRain, butterfly?.billboardAtlas);
      if (!active()) {
        rain?.dispose();
        return;
      }
      stageRain = rain;
      const leaves = await global.MVStudioAutumnLeaves?.apply(T, scene, value.stageLeaves, butterfly?.billboardAtlas);
      if (!active()) {
        leaves?.dispose();
        return;
      }
      stageLeaves = leaves;
      const confetti = await global.MVStudioConfetti?.apply(T, scene, value.stageConfetti, butterfly?.billboardAtlas);
      if (!active()) {
        confetti?.dispose();
        return;
      }
      stageConfetti = confetti;
      const glow = await global.MVStudioStageGlow?.apply(T, scene, value.stageGlow);
      if (!active()) {
        glow?.dispose();
        return;
      }
      stageGlow = glow;
      const lens = await global.MVStudioStageLens?.apply(T, scene, value.stageLensFlare);
      if (!active()) {
        lens?.dispose();
        return;
      }
      stageLens = lens;
      const momiji = await global.MVStudioMomiji?.apply(T, scene, value.stageMomiji, butterfly?.billboardAtlas);
      if (!active()) {
        momiji?.dispose();
        return;
      }
      stageMomiji = momiji;
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
      const particleSystems = await global.MVStudioParticleSystems?.apply(T, scene, value.stageParticleSystems);
      if (!active()) {
        particleSystems?.dispose();
        return;
      }
      stageParticleSystems = particleSystems;
      const controlPrefabs = await global.MVStudioControlPrefabs?.apply(T, scene, value.stageControlPrefabs,
        value.stageParticleSystems);
      if (!active()) {
        controlPrefabs?.dispose();
        return;
      }
      stageControlPrefabs = controlPrefabs;
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

    // The shot frameTracks gives the live camera at `time`, posed on a scratch
    // camera with the game's clip planes (near 0.1, far 1000) and the live
    // camera's aspect and lens correction (liveFov); null with no shot.
    function mainCameraAt(time) {
      let shot = null, ended = null;
      const hold = project?.source?.kind === "game";
      for (const track of renderTracks) {
        if (track.kind !== "camera") continue;
        const event = activeCameraEvent(track, time);
        if (event) {
          shot = { event, track, at: time };
          continue;
        }
        const last = hold ? endedCameraEvent(track, time) : null;
        if (last && (!ended || last.start + last.duration > ended.event.start + ended.event.duration)) ended = { event: last, track };
      }
      if (!shot && ended) shot = { event: ended.event, track: ended.track, at: ended.event.start + ended.event.duration };
      if (!shot || !poseCamera(shot.event, shot.at, shot.track, cullingCamera)) return null;
      const native = shot.track.nativeClass === "AnimationTrack" && /(?:^|\/)MainCamera$/i.test(shot.track.binding || "");
      const correction = native ? global.MVStudioSplit?.aspectCorrection(liveCamera.aspect) ?? 1 : 1;
      cullingCamera.fov = Math.min(170, cullingCamera.fov / correction);
      cullingCamera.aspect = liveCamera.aspect;
      cullingCamera.near = 0.1;
      cullingCamera.far = 1000;
      cullingCamera.updateProjectionMatrix();
      applyCameraOffsets(cullingCamera, shot.track.binding, time);
      cullingCamera.updateMatrixWorld(true);
      return cullingCamera;
    }

    // The main camera's world position at `time` (mainCameraAt), or false with no shot.
    function mainCameraPositionAt(time, out) {
      const camera = mainCameraAt(time);
      if (!camera) return false;
      out.setFromMatrixPosition(camera.matrixWorld);
      return true;
    }

    // The world position of a member's Move node (the shaft anchor) at `time`
    // from the dance alone (ViewerMotionTimeline sampleLocal): nothing is posed.
    // Its ancestors keep their current transforms, which the timeline does not
    // animate below the member root.
    function shaftAnchorAt(record, time, out) {
      const node = record.shaftAnchor;
      const local = record.motion?.sampleLocal?.(node, "position", time, anchorSample);
      out.fromArray(local || node.position.toArray(anchorSample));
      if (node.parent) {
        node.parent.updateWorldMatrix(true, false);
        out.applyMatrix4(node.parent.matrixWorld);
      }
      return true;
    }

    // Every camera that draws the particle layers at `time`: the main camera,
    // or while a LiveSplitScreenClip is active the enabled sub cameras plus
    // the main camera when the clip keeps it on (mv-studio-split.js camerasAt).
    function cullingCamerasAt(time) {
      const views = split?.camerasAt?.(time, sampleSplitCamera) ?? null;
      const main = !views || views.main ? mainCameraAt(time) : null;
      return [...(views?.cameras || []), ...(main ? [main] : [])];
    }

    // Recreated when the camera tracks or the aspect change, so the particle
    // visibility pass starts over.
    function particleCullingView() {
      // applyProject rebuilds renderTracks on every seek; its source array changes only with an edit.
      const cameras = renderTracks.filter((track) => track.kind === "camera").map((track) => track.id).join("|");
      if (!cullingView || cullingView.tracks !== trackSource || cullingView.cameras !== cameras ||
          cullingView.aspect !== liveCamera.aspect || cullingView.hold !== (project?.source?.kind === "game") ||
          cullingView.split !== project?.splitScreen || cullingView.splitQuality !== settings?.split_screen) {
        cullingView = { tracks: trackSource, cameras, aspect: liveCamera.aspect, hold: project?.source?.kind === "game",
          split: project?.splitScreen, splitQuality: settings?.split_screen, cameraAt: mainCameraAt, camerasAt: cullingCamerasAt };
        cullingView.key = cullingView;
      }
      return cullingView;
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

    // holdLastShot (original MVs): past the end of every camera clip the game
    // keeps the last shot. Nothing moves the 3D camera after its final key, and at
    // the music end LiveCoreCameraManager.StartBlur (0x2f63180) turns the 3D
    // cameras off one frame later (AnimationBlurIntensity), so the overlay camera
    // keeps blurring that frame. The editor camera is never shown in its place.
    function frameTracks(time, tracks, quality, [ambient, key, rim], onCamera, holdLastShot = false) {
      ambient.color.setHex(0xe4edff);
      ambient.intensity = 1.2;
      key.color.setHex(0xffffff);
      key.intensity = 2.1;
      rim.color.setHex(0x8bb6ff);
      rim.intensity = 1.0;
      let sampledCamera = false, ended = null;
      for (const track of tracks) {
        const event = track.kind === "camera" ? activeCameraEvent(track, time) : activeEvent(track, time);
        if (!event) {
          const last = holdLastShot && onCamera && track.kind === "camera" ? endedCameraEvent(track, time) : null;
          if (last && (!ended || last.start + last.duration > ended.event.start + ended.event.duration)) ended = { event: last, track };
          continue;
        }
        if (track.kind === "camera") {
          sampledCamera = true;
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
      if (!sampledCamera && ended) onCamera(ended.event, ended.event.start + ended.event.duration, ended.track, true);
    }

    function useCameraEvent(event, time, track, held = false) {
      if (!poseCamera(event, time, track)) return;
      hasShot = true;
      liveCameraEvent = { track: track.id ?? null, event: event.id ?? null, start: event.start, duration: event.duration };
      if (held) liveCameraEvent.held = true;
      mainCameraPosition.copy(liveCamera.position);
      mainCameraDirection.set(0, 0, -1).applyQuaternion(liveCamera.quaternion);
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
      // level35 MainCamera/Offset/Camera clears SolidColor (0, 0, 0, 0); the
      // RenderSettings skybox is never drawn and fog is off on every MV stage.
      if (project?.source?.kind === "game") renderer.setClearColor(0x000000, 0);
      else renderer.setClearColor(editorClear, 1);
      const shadowStages = records.filter(record => typeof record.memberShadowDefaults === "boolean");
      // ShadowComponent.Initialize deletes the costume's shadows only for a stage
      // with memberShadowPrefabs; a LiveMemberShadowTrack then only scales them.
      defaultMemberShadows = shadowStages.length === 1 && shadowStages[0].memberShadowDefaults;
      memberShadowPrefabs = shadowStages.length === 1 && !shadowStages[0].memberShadowDefaults
        ? shadowStages[0].memberShadowPrefabs ?? null : null;
      memberShadowTracks = tracks.filter(track => track.nativeClass === "LiveMemberShadowTrack" && !track.muted);
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
          const bound = /^\/EntryPoint\/Live\/Members\/Member([1-9][0-9]*)$/.exec(track.binding || "");
          const slot = track.shaftSlot ?? (bound ? Number(bound[1]) : null);
          if (bound && slot === Number(bound[1])) {
            const events = track.events.filter(event => event.values?.playableClass === "LiveMemberSpotLightShaftClip");
            if (events.length) memberShaftTracks.set(slot, (memberShaftTracks.get(slot) || []).concat(events));
          }
          continue;
        }
        if (!track.muted && track.nativeClass === "LiveMemberSpotLightAreaTrack") {
          const binding = /^\/EntryPoint\/Live\/Members\/Member([1-9][0-9]*)$/.exec(track.binding || "");
          if (binding) {
            const slot = Number(binding[1]);
            const events = track.events.filter(event => event.values?.playableClass === "LiveMemberSpotLightAreaClip");
            if (events.length) memberAreaTracks.set(slot, (memberAreaTracks.get(slot) || []).concat(events));
          }
          continue;
        }
        if (!track.muted && track.nativeClass === "LiveMemberCullerTrack") {
          const slot = /^\/EntryPoint\/Live\/Members\/Member([1-9][0-9]*)$/.exec(track.binding || "");
          if (slot) {
            const position = Number(slot[1]);
            const events = track.events.filter(event => event.values?.playableClass === "LiveMemberCullerClip" && event.duration > 0);
            if (events.length) memberCullingTracks.set(position, (memberCullingTracks.get(position) || []).concat(events));
          }
          continue;
        }
        if (!track.muted && track.nativeClass === "LiveMemberScalingTrack") {
          const bound = /^\/EntryPoint\/Live\/Members\/Member([1-9][0-9]*)\/Model$/.exec(track.binding || "");
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
      stageButterfly?.invalidate();
      stageRain?.invalidate();
      stageLeaves?.invalidate();
      stageConfetti?.invalidate();
      stageGlow?.invalidate();
      stageLens?.invalidate();
      stageMomiji?.invalidate();
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
        // member_rim_light never reaches a member material: the game only mutes
        // the "Member Rim Light" tracks (LiveQualityOperator.
        // ApplyLiveQualityToMemberEffectTrack 0x20f3164), which sample() skips.
        // The base light still writes the rim (LiveBaseLightReciever.
        // ApplyBaseLightColor 0x2f5fac0 -> LiveCoreMemberRimlight.
        // ApplyBaseIntensity 0x2f607fc: intensity = base, ApplyEnable(base > 0))
        // and every AS/Member variant draws it, so the rim term stays on.
        if (record.prop) record.prop.setTracks(tracks);
        record.propLight?.setProject(project);
        record.stagePropLight?.setProject(project);
      }
    }

    // The spring rate the original frame-rate rule gives (MVStudioPhysics.frameRate).
    function physicsRate() {
      return global.MVStudioPhysics?.frameRate?.(settings, physicsTiming) ?? (settings.frame_rate_60fps === true ? 60 : 30);
    }

    function resetPhysics(reason) {
      physicsClock?.reset();
      // A seek cannot replay the frames the game would have applied before it.
      dofState = global.MVStudioDofFocus?.createState?.() ?? null;
      dofApplied = dofPrevious = null;
      resetShafts = true;
      lastShaftFrame = null;
      for (const record of records) {
        record.physics?.reset(reason);
        record.spotlightArea?.reset();
      }
    }

    // `history`: optional ascending director times of the frames the game rendered
    // before `time` (a runtime dump's frame grid); only frame-stepped client state
    // reads them.
    function seek(time, value, deferDraw = false, history = null) {
      if (disposed) return;
      if ((value && value !== project) || (Number.isFinite(time) && Math.abs(time - currentTime) > 1e-9)) resetPhysics("seek");
      project = value || project;
      applyProject();
      pendingHistory = Array.isArray(history) ? history : [];
      try {
        playbackFrame(time, undefined, deferDraw);
      } finally {
        pendingHistory = null;
      }
    }

    function nextFrameClock(time) {
      const advancing = pendingHistory === null && playing && Number.isFinite(time) && time >= currentTime - 1e-9;
      if (advancing) return { advancing, history: [] };
      const history = (pendingHistory || []).filter((value) => Number.isFinite(value) && value < time - 1e-9);
      for (let index = 1; index < history.length; index++) {
        if (history[index] < history[index - 1]) return { advancing: false, history: history.sort((a, b) => a - b) };
      }
      return { advancing: false, history };
    }

    // MVStudioLighting.sample at an earlier rendered frame of the frame clock.
    function lightingAt(time, lighting) {
      if (time === currentTime) return lighting;
      if (!historyLighting.has(time)) historyLighting.set(time, global.MVStudioLighting?.sample(project, time) ?? null);
      return historyLighting.get(time);
    }

    // LiveCoreMemberAmbient's ambient and tint writes (MVStudioLighting.heldColor)
    // for a member or a member prop. With a base light track LiveBaseLightReciever
    // also writes these components (ApplyBase*Color, CheckSame-gated as well); the
    // write order of the two mixers within a frame is not established, so the
    // colors stay exact there (unevidenced choice).
    function heldLiveLighting(record, slot, value, valueAt, lighting) {
      const holds = (record.lightingHolds ||= {})[slot] ||= { ambient: {}, tint: {} };
      value = heldRim(holds, value, valueAt);
      if (!value || lighting?.baseTrack || !global.MVStudioLighting?.heldColor) {
        holds.ambient.color = holds.tint.color = null;
        return value;
      }
      const held = { ...value };
      for (const key of ["ambient", "tint"]) {
        held[key] = value[key] ? global.MVStudioLighting.heldColor(holds[key], (time) => valueAt(time)?.[key] ?? null,
          currentTime, frameClock) : (holds[key].color = null, value[key]);
      }
      return held;
    }

    // LiveRimlightMixer / LivePropRimlightMixer.PostProcess apply colour,
    // sharpness and direction only in a frame an input ran; otherwise they
    // only ApplyIntensity(0) (mv_studio_member_rim_test). The rimlight keeps
    // the colour, power and direction of the last frame a clip wrote (the
    // previous playing frame, or after a seek the last frame of the frame
    // clock's history with an active clip), and LiveCoreMemberRimlight.ResetAll's
    // state (SifasMaterial's live default) before any.
    function heldRim(holds, value, valueAt) {
      const written = (rim) => Array.isArray(rim?.color) && Array.isArray(rim?.direction) && Number.isFinite(rim?.power);
      if (written(value?.rim)) {
        holds.rim = value.rim;
        return value;
      }
      if (!frameClock.advancing) {
        holds.rim = null;
        for (let index = frameClock.history.length - 1; index >= 0 && !holds.rim; index--) {
          const rim = valueAt(frameClock.history[index])?.rim;
          if (written(rim)) holds.rim = rim;
        }
      }
      if (!holds.rim) return value;
      return { ...(value || {}), rim: { color: holds.rim.color, direction: holds.rim.direction, power: holds.rim.power,
        intensity: value?.rim?.intensity ?? 0 } };
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
      // A continuing playback frame follows the frame evaluated before it.
      const continuing = Number.isFinite(frameTimestamp) && Number.isFinite(time) && time > currentTime + 1e-9;
      captureFocusLag(continuing);
      if (Number.isFinite(frameTimestamp) && time < currentTime - 1e-9) resetPhysics("clock-rewind");
      frameClock = nextFrameClock(Number.isFinite(frameTimestamp) || pendingHistory !== null ? time : NaN);
      historyLighting = new Map();
      currentTime = Number.isFinite(time) ? time : 0;
      mixers?.update(project, currentTime, frameClock);
      // Reduce only the temporary playback buffer when the browser has
      // missed several 30 fps frames. Pausing restores the selected quality.
      if (adaptivePreview && playing && Number.isFinite(frameTimestamp) && previewScale > 0.5) {
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
      liveCameraEvent = null;
      frameTracks(currentTime, renderTracks, settings, lights, useCameraEvent, project?.source?.kind === "game");
      post?.evaluate(project, currentTime);
      activeSplitGazeCameras = split?.sample(currentTime, sampleSplitCamera) ?? null;
      const lighting = global.MVStudioLighting?.sample(project, currentTime);
      stageTitle?.update(currentTime, project);
      stageRibbons?.update(currentTime, project);
      stageShine?.update(currentTime, project);
      stageParticles?.update(currentTime, project);
      stageSpotlight?.update(currentTime, project);
      stageButterfly?.update(currentTime, project);
      stageRain?.update(currentTime, project);
      stageLeaves?.update(currentTime, project);
      stageConfetti?.update(currentTime, project);
      stageGlow?.update(currentTime, project);
      stageLens?.update(currentTime, project);
      stageMomiji?.update(currentTime, project);
      stageSpeedBack?.update(currentTime, project);
      stageDisplayLights?.update(currentTime, project);
      stageFallingEffects?.update(currentTime, project);
      stageBreak?.update(currentTime, project);
      stageFinaleFloor?.update(currentTime, project);
      stageSparksA?.update(currentTime, project);
      stageSparksB?.update(currentTime, project);
      stageSparksRoop?.update(currentTime, project);
      stageParticleSystems?.update(currentTime, project, particleCullingView(), particleClock);
      stageControlPrefabs?.update(currentTime, project);
      for (const record of records) record.stageFlash?.update(currentTime, project);
      for (const record of records) record.stageMotion?.update(currentTime, project);
      // LiveCoreLossyScale.LateUpdate follows the animators.
      for (const record of records) record.lossyScale?.apply();
      for (const record of records) record.stageSoftBillboards?.update(currentTime);
      for (const record of records) record.stageLaserCores?.update(currentTime, project, record.stageMotion);
      for (const record of records) record.stageStationaryBursts?.update(currentTime, project, record.stageMotion);
      for (const record of records) record.penlight?.update(currentTime, project, frameClock);
      for (const record of records) {
        record.stageMaterial?.update(currentTime, project, lighting, frameClock);
        record.stagePropLight?.update(currentTime, frameClock, !!lighting?.baseTrack);
      }
      for (const record of records) record.stageColoring?.update(currentTime, project);
      for (const record of records) record.stageDisplay?.update(currentTime, project);
      // LiveCoreMemberManager.Update steps the springs before the director evaluates.
      const physicsStep = playing && visible && records.some((record) => record.physics)
        ? physicsClock?.step(frameTimestamp, physicsRate()) || 0 : 0;
      for (const record of records) record.physics?.frame?.("update", currentTime, physicsStep, settings, record.motion, physicsTiming?.order);
      for (const record of records) {
        if (record.group !== actors) continue;
        // Both native camera paths exclude the member's Invisible layer.
        // Keep sampling its transforms so other actors can still track it.
        const culled = memberCulledAt(record.position, currentTime);
        record.root.visible = record.actorVisible && !culled;
        record.materials?.setLiveLighting?.(heldLiveLighting(record, "member", lighting?.member(record.position),
          (time) => lightingAt(time, lighting)?.member(record.position), lighting));
        record.physics?.restorePose();
        record.constraints?.restorePose();
        record.nodeScaling?.resetHeight();
        const performer = performers.get(record.id);
        if (performer) actorPose(record, performer);
        if (record.motion) {
          record.motion.evaluatePose(currentTime, { split: activeSplitGazeCameras !== null });
          record.motion.applyVisibility(currentTime);
          if (record.cheekMaterial) record.materials?.setCheek?.(record.cheekMaterial, record.motion.cheek?.(currentTime, frameClock));
        } else if (record.mixer) record.mixer.setTime(currentTime);
        record.nodeScaling?.applyHeight(memberScaleTracks.get(record.position), currentTime);
      }
      // Unity's ConstraintManagerUpdate (PreLateUpdate) runs after the Animator
      // and before every LateUpdate script: LiveMemberEyeContact, ShadowComponent
      // and the member manager's AllSafeCorrect. A swing-bone source holds the
      // local rotation this frame's Update job wrote (simulatedPose), unless the
      // timeline animates it. The targets keep the result until the next update
      // hook, whose job reads them as the parents of their swing chains.
      for (const record of records) record.constraints?.apply(record.physics?.simulatedPose?.() || null,
        () => record.motion?.animatedProperties?.(currentTime));
      // Native performers look at the other actor's animated Eye_Root, so
      // prepare every actor at this timestamp before resolving any gaze.
      const targets = gazeContext();
      for (const record of records) if (record.motion) record.motion.evaluateGaze(currentTime, targets, { continuing });
      // The native ShadowComponent runs before the member manager's LateUpdate.
      const advancingShadow = playing && Number.isFinite(frameTimestamp);
      const shadowParameters = global.MVStudioMemberShadow?.sample?.(memberShadowTracks, currentTime) ?? null;
      for (const record of records) record.memberShadow?.update(defaultMemberShadows, advancingShadow, shadowParameters, memberShadowPrefabs);
      for (const record of records) record.physics?.frame?.("late", currentTime, physicsStep, settings, record.motion, physicsTiming?.order);
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
          // A reset rebuilds a hidden shaft from its last drawn frame: the game's
          // frame history when a seek handed one, else the spring clock's grid.
          record.shaft?.frame(settings.member_spot_light_area !== false ? clips : null,
            currentTime, Math.max(0, elapsed), liveCamera, project, resetShafts || elapsed < 0 || elapsed > 0.25,
            { history: frameClock.advancing ? null : frameClock.history, rate: physicsRate(),
              anchorAt: (time, out) => shaftAnchorAt(record, time, out), cameraAt: mainCameraPositionAt });
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
        if (record.propMaterial) {
          // The prop's ambient mixer writes its component every frame, shown or not: the
          // hold steps on every frame and the material takes it while the prop is shown.
          const live = heldLiveLighting(record, "prop", record.propLight?.sample(currentTime),
            (time) => record.propLight?.sample(time), lighting);
          if (record.root.visible) record.propMaterial.setLiveLighting?.(live);
        }
      }
      advanceFocus();
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

    // Runtime value dump of the last evaluated frame (sifas-mv-runtime-dump/1,
    // editor columns, three-rh-mirror-x space). Strictly read-only: it never
    // seeks, resizes, draws or updates a matrix, and copies every value into
    // plain arrays. Call seek(t, undefined, true) first; the deferred seek has
    // already updated the world matrices this reads.
    const defaultGlobals = ["_Beat", "_MusicTime", "_SelfTime", "_ColorsLength", "_RenderTextureResolution", "_Time"];
    const anchorBones = ["Hips", "Head", "LeftHand", "RightHand"];

    function assetDump(request = {}) {
      const D = global.MVStudioAssetDump;
      if (!D) throw new Error("The MV asset dump helpers are not loaded.");
      const clock = global.performance?.now ? () => global.performance.now() : () => Date.now();
      const started = clock();
      const sections = new Set(Array.isArray(request.sections) ? request.sections : ["clock", "cameras"]);
      const limit = (value, fallback) => Number.isInteger(value) && value > 0 ? value : fallback;
      const maxNodes = limit(request.maxNodes, 4000), maxMaterials = limit(request.maxMaterials, 1024);
      const maxBones = limit(request.maxBones, 256);
      const filter = request.filter || {}, keys = request.keys || {};
      const temp = D.temporaries(T), out = {}, errors = [], truncated = [];
      const cache = {};

      function read(section, key, reader) {
        if (!sections.has(section)) return;
        try {
          out[key] = reader();
        } catch (error) {
          out[key] = null;
          errors.push({ at: section, error: String(error?.message || error).slice(0, 160) });
        }
      }

      function viewOf(camera) {
        // An unparented camera's world matrix is its local TRS; compose it into
        // a temporary so a camera that was not drawn yet is still current.
        const world = camera.parent ? camera.matrixWorld : temp.matrix.compose(camera.position, camera.quaternion, camera.scale);
        const current = camera.matrixWorld.elements.every((value, index) => Math.abs(value - world.elements[index]) <= 1e-9);
        return { world: Array.from(world.elements), view: Array.from(temp.inverse.copy(world).invert().elements), current };
      }

      function cameraEvent() {
        if (!liveCameraEvent) return null;
        const track = (project?.tracks || []).find((item) => item.id === liveCameraEvent.track);
        const clipIndex = track ? track.events.findIndex((event) => event.id === liveCameraEvent.event) : -1;
        return { track: liveCameraEvent.track, label: track?.label ?? null, nativeClass: track?.nativeClass ?? null,
          binding: track?.binding ?? null, clipIndex: clipIndex >= 0 ? clipIndex : null,
          start: liveCameraEvent.start, duration: liveCameraEvent.duration, ...(liveCameraEvent.held ? { held: true } : {}) };
      }

      function cameraEntry(camera, base) {
        const matrices = viewOf(camera);
        const world = D.decompose(temp.matrix.fromArray(matrices.world), temp);
        const expectedY = 1 / Math.tan(camera.fov * Math.PI / 360);
        return { ...base, fieldOfView: camera.fov, aspect: camera.aspect, nearClipPlane: camera.near, farClipPlane: camera.far,
          projection: Array.from(camera.projectionMatrix.elements), worldToCamera: matrices.view,
          transform: { position: world.position, rotation: camera.parent ? world.rotation : camera.quaternion.toArray() },
          checks: { matrixWorldCurrent: matrices.current,
            projectionMatchesFov: Math.abs(camera.projectionMatrix.elements[5] - expectedY) <= 1e-6 * Math.max(1, expectedY) } };
      }

      function boneIndex(record) {
        cache.bones ||= new Map();
        if (cache.bones.has(record)) return cache.bones.get(record);
        const paths = new Map(), nodes = new Map();
        for (const bone of Array.isArray(record.rig?.bones) ? record.rig.bones : []) {
          if (Number.isInteger(bone?.node) && typeof bone.path === "string") paths.set(bone.node, bone.path);
        }
        record.root.traverse((node) => {
          const path = paths.get(node.userData?.elichika_node);
          if (path !== undefined && !node.userData.viewerHelper) nodes.set(path, nodes.has(path) ? null : node);
        });
        for (const [path, node] of nodes) if (!node) nodes.delete(path);
        cache.bones.set(record, nodes);
        return nodes;
      }

      function namedBone(record, name) {
        let best = null;
        for (const [path, node] of boneIndex(record)) {
          if (path.split("/").at(-1) === name && (!best || path.length < best[0].length)) best = [path, node];
        }
        return best ? best[1] : null;
      }

      // A renderer the editor builds at runtime for a game GameObject: its path below the record root
      // (the first segment stands for the record root), from the node's own path or its name below a rig bone.
      function runtimeObjectPath(owner, record) {
        const data = owner.userData || {};
        if (typeof data.mvGameObjectPath === "string") return { path: `${D.nodeName(record.root) || "root"}/${data.mvGameObjectPath}`, pathSource: "runtime" };
        if (typeof data.mvGameObjectName !== "string" || record.group !== actors) return null;
        for (const [path, node] of boneIndex(record)) {
          if (node === owner.parent) return { path: `${D.nodeName(record.root) || "root"}/${path}/${data.mvGameObjectName}`, pathSource: "runtime" };
        }
        return null;
      }

      function rendererEntries() {
        if (cache.renderers) return cache.renderers;
        const entries = [], counts = new Map();
        for (const record of records) {
          const scope = D.rendererScope(record, actors);
          for (const [owner, meshes] of D.renderersOf(record.root)) {
            const mesh = D.nodeName(owner), count = (counts.get(scope + "\n" + mesh) || 0) + 1;
            counts.set(scope + "\n" + mesh, count);
            const { path, pathSource } = runtimeObjectPath(owner, record) || D.gameObjectPath(owner, record.root);
            entries.push({ key: D.keyFor("renderer", { scope, mesh, index: count }), scope, mesh, path, pathSource, owner, meshes, record });
          }
        }
        return (cache.renderers = entries);
      }

      // A requested game renderer selects its editor counterparts by key, by
      // GameObject path (the editor path below its prefab root is a suffix of
      // the game path) or by mesh name in the same scope. This is a superset;
      // the comparator makes the actual join.
      // AxisBillboard turns its nodes in renderScene(); a deferred seek never draws, so
      // the transforms hold the rest (or last drawn) rotation. Report what the live
      // camera's draw gives, computed read-only from the rest rotation.
      function billboardOf(entry) {
        if (!cache.billboards) {
          cache.billboards = new Map();
          const world = viewOf(liveCamera).world, eye = new T.Vector3(world[12], world[13], world[14]);
          for (const record of records) {
            for (const [node, rotation] of record.axisBillboard?.preview?.(eye) || []) cache.billboards.set(node, rotation);
            for (const [node, rotation] of record.shaft?.preview?.(eye) || []) cache.billboards.set(node, rotation);
          }
        }
        let node = entry.owner;
        while (node && !cache.billboards.has(node)) node = node.parent;
        return node || null;
      }

      function rendererWorld(entry) {
        const node = billboardOf(entry);
        if (!node) return entry.owner.matrixWorld;
        const turned = new T.Matrix4().multiplyMatrices(node.parent.matrixWorld,
          new T.Matrix4().compose(node.position, cache.billboards.get(node), node.scale));
        return node === entry.owner ? turned : turned.multiply(new T.Matrix4().copy(node.matrixWorld).invert().multiply(entry.owner.matrixWorld));
      }

      function rendererWanted(item, entry) {
        if (item.key === entry.key) return true;
        if (item.scope !== entry.scope) return false;
        const below = entry.path === null ? "" : entry.path.split("/").slice(1).join("/");
        if (below && typeof item.path === "string" && (item.path === below || item.path.endsWith("/" + below))) return true;
        return item.mesh === entry.mesh;
      }

      function selectedRenderers() {
        const wanted = Array.isArray(filter.renderers) ? filter.renderers : null;
        const entries = rendererEntries().filter((entry) => !wanted || wanted.some((item) => rendererWanted(item, entry)));
        if (entries.length > maxNodes) truncated.push("renderers");
        return entries.slice(0, maxNodes);
      }

      // Node visibility without the member culler: the culler hides an actor's
      // root (record.root.visible = actorVisible && !culled), which the game
      // does through the camera culling mask instead; "culled" reports it.
      function nodeVisible(node, record) {
        for (let current = node; current; current = current.parent) {
          const shown = current === record.root && record.group === actors ? Boolean(record.actorVisible) : current.visible;
          if (!shown) return false;
        }
        return true;
      }

      function slots(entry) {
        const result = [];
        for (const mesh of entry.meshes) for (const material of [mesh.material].flat()) result.push({ mesh, material });
        return result;
      }

      const focusReadOnly = focusSource(true);

      read("clock", "clock", () => ({ directorTime: currentTime, rate: physicsRate() }));
      read("directors", "directors", () => [{ key: "director:main", time: currentTime,
        duration: Number.isFinite(project?.duration) ? project.duration : null }]);
      read("cameras", "cameras", () => {
        const main = cameraEntry(liveCamera, { key: D.keyFor("camera", { role: "main" }), role: "main", liveShot: hasShot,
          authoredFov: authoredMainFov, nativeLens: nativeMainLens, event: cameraEvent() });
        if (!hasShot) main.errors = [{ at: "camera", error: "no live camera shot at this time" }];
        const cameras = [main];
        for (const view of split?.inspect?.() || []) {
          const camera = { fov: view.fov, aspect: view.aspect, near: view.near, far: view.far,
            position: new T.Vector3().fromArray(view.position), quaternion: new T.Quaternion().fromArray(view.quaternion),
            scale: new T.Vector3(1, 1, 1), parent: null, matrixWorld: new T.Matrix4(),
            projectionMatrix: new T.Matrix4().fromArray(view.projection) };
          cameras.push({ ...cameraEntry(camera, { key: D.keyFor("camera", { role: "split" + view.slot }), role: "split",
            inView: view.inView, maskBounds: view.maskBounds }), checks: undefined });
        }
        return cameras;
      });
      read("correctors", "correctors", () => {
        const bounds = { min: 0.75, max: 1 };
        const correction = nativeMainLens ? global.MVStudioSplit?.aspectCorrection(liveCamera.aspect) ?? 1 : 1;
        return [{ key: "corrector:camera:main", correction, aspectInput: liveCamera.aspect, bounds, nativeLens: nativeMainLens,
          mode: { modeled: false } }];
      });
      read("cameraWork", "cameraWork", () => [{ key: "cameraWork:/EntryPoint/Live/Cameras/MainCamera", authoredFov: authoredMainFov }]);
      read("globals", "globals", () => {
        const names = Array.isArray(keys.globals) ? keys.globals : defaultGlobals;
        const found = {}, seen = new Set();
        const take = (name, value, from, extra) => {
          if (!(name in found) && Number.isFinite(value)) found[name] = { f: value, from, ...extra };
        };
        scene.traverse((node) => {
          for (const material of node.isMesh ? [node.material].flat() : []) {
            // A hidden material (a penlight shader with no active clip) keeps stale uniforms.
            if (!material?.uniforms || seen.has(material) || material.visible === false) continue;
            seen.add(material);
            const u = material.uniforms, where = "@" + (material.name || node.name || "material");
            if (u.uMode && u.uMusicTime && u.uBeat) {
              take("_MusicTime", u.uMusicTime.value, "uMusicTime" + where);
              // Penlight mode 0 does not read the beat clock.
              if (u.uMode.value !== 0) take("_Beat", u.uBeat.value, "uBeat" + where);
            }
            if (u._MusicTime) take("_MusicTime", u._MusicTime.value, "_MusicTime" + where);
            // LiveColoringTrack clip-local time on one material, not a shader
            // global: the comparator lists it as a note and never scores it.
            if (u.uSelfTime) take("_SelfTime", u.uSelfTime.value, "uSelfTime" + where + " (per material)", { perMaterial: true });
          }
        });
        const buffer = renderer.getDrawingBufferSize(new T.Vector2());
        take("_RenderTextureResolution", 0, "renderer.getDrawingBufferSize", { v: [buffer.x, buffer.y, 0, 0] });
        return Object.fromEntries(names.map((name) => [`global:${name}`, found[name] || null]));
      });
      read("renderSettings", "renderSettings", () => ({ modeled: false }));
      read("lights", "lights", () => ({ modeled: false }));
      // Frame records carry member identity under "members"; the members part carries bones.
      read("memberIdentity", sections.has("members") ? "memberIdentity" : "members", () => (project?.performers || []).map((performer) => ({
        slot: performer.position, memberId: performer.memberId ?? null, costumeId: performer.costumeId ?? null })));
      read("anchors", "anchors", () => {
        const anchors = [];
        for (const record of records) if (record.group === actors) {
          for (const name of anchorBones) {
            const node = namedBone(record, name);
            if (node) anchors.push({ key: D.keyFor("anchor", { slot: record.position, name }), position: D.worldPosition(node, temp) });
          }
        }
        const stageRecord = records.find((record) => record.role === "stage");
        if (stageRecord) anchors.push({ key: "anchor:stageOrigin", position: D.worldPosition(stageRecord.root, temp) });
        return anchors;
      });
      read("renderers", "renderers", () => selectedRenderers().map((entry) => ({
        key: entry.key, scope: entry.scope, mesh: entry.mesh, path: entry.path, pathSource: entry.pathSource,
        class: entry.meshes.some((mesh) => mesh.isSkinnedMesh) ? "SkinnedMeshRenderer" : "MeshRenderer",
        visible: entry.meshes.some((mesh) => nodeVisible(mesh, entry.record)),
        culled: entry.record.group === actors && memberCulledAt(entry.record.position, currentTime),
        materialVisible: slots(entry).every(({ material }) => material?.visible !== false),
        transform: D.decompose(rendererWorld(entry), temp), axisBillboard: billboardOf(entry) !== null,
        materials: slots(entry).map(({ material }, slot) => {
          // The drawn AS/Member variant, as the game reads Material.shaderKeywords per renderer slot.
          const { kind, keywords } = D.materialProperties(material);
          return { slot, name: D.materialName(material), editorName: material?.name ?? null, kind, visible: material?.visible !== false,
            ...(Array.isArray(keywords) ? { keywords } : {}) };
        }),
      })));
      // Uniforms an AnimationTrack curve drives (MVStudioStageMotion material channels): the game applies those
      // through a MaterialPropertyBlock, which its dump does not read, so the comparator never scores them.
      function curveDriven(material) {
        if (!cache.curveTargets) {
          cache.curveTargets = new Set();
          for (const record of records) for (const value of record.stageMotion?.curveTargets?.() || []) cache.curveTargets.add(value);
        }
        return Object.entries(material?.uniforms || {}).filter(([, holder]) =>
          cache.curveTargets.has(holder) || (holder?.value !== null && typeof holder?.value === "object" && cache.curveTargets.has(holder.value)))
          .map(([name]) => name).sort();
      }
      read("materials", "materials", () => {
        const materials = [];
        for (const entry of selectedRenderers()) {
          for (const [slot, { material }] of slots(entry).entries()) {
            if (materials.length >= maxMaterials) { truncated.push("materials"); return materials; }
            const properties = D.materialProperties(material);
            // A hidden material draws nothing; its uniforms are the module's current state unless the
            // module marks them stale (mvHiddenUniforms, e.g. a penlight without clip input).
            const hidden = material?.visible === false;
            materials.push({ key: D.keyFor("material", { renderer: entry.key, slot }), renderer: entry.key, slot,
              name: D.materialName(material), editorName: material?.name ?? null, visible: !hidden,
              ...(hidden ? { hiddenUniforms: material.userData?.mvHiddenUniforms === "stale" ? "stale" : "current" } : {}),
              curveDriven: curveDriven(material), ...properties });
          }
        }
        return materials;
      });
      read("stageNodes", "stageNodes", () => {
        const wanted = Array.isArray(filter.stageNodes) ? new Set(filter.stageNodes) : null;
        const nodes = [];
        for (const record of records) record.root.traverse((node) => {
          const tag = node.userData?.mvStageNode;
          if (typeof tag?.binding !== "string" || !Number.isInteger(tag.path)) return;
          const key = D.keyFor("stageNode", { binding: tag.binding, path: tag.path });
          if (wanted && !wanted.has(key)) return;
          if (nodes.length >= maxNodes) { if (!truncated.includes("stageNodes")) truncated.push("stageNodes"); return; }
          // An AxisBillboard node (or a child of one) reports the live camera's turn, as renderers do,
          // and whether the live camera draws that billboard (axisBillboardDrawn, when known).
          const billboard = billboardOf({ owner: node });
          const drawn = billboard ? billboardDrawn(billboard) : null;
          nodes.push({ key, binding: tag.binding, crc: tag.path, name: D.nodeName(node), activeSelf: node.visible,
            visible: D.effectiveVisible(node), ...D.decompose(rendererWorld({ owner: node }), temp),
            ...(billboard ? { axisBillboard: true } : {}), ...(typeof drawn === "boolean" ? { axisBillboardDrawn: drawn } : {}) });
        });
        return nodes;
      });

      // Whether the live camera draws an AxisBillboard, so that its OnWillRenderObject (0x27bf944) turned it toward
      // that camera in the frame the dump shows: the node is shown, has a renderer, and its AxisBillboard.Start
      // bounds (0x27bf774: the mesh bounds widened to (max(sx, sz), sy, max(sx, sz)) about their center) under the
      // reported turn meet the live camera's frustum (Unity culls a renderer by its world bounds). null (unknown)
      // while a split clip is active, since the sub cameras turn it too and the frame's last draw is not modelled,
      // and for billboards the editor turns by another rule (the member shaft). The camera culling mask is not
      // checked: the 12035 cones are on layer 14, which the main camera's mask 0x0C0BC013 draws (dump4 renderer
      // and camera records); other stages are assumed alike (unevidenced).
      function billboardDrawn(node) {
        cache.billboardDrawn ||= new Map();
        if (cache.billboardDrawn.has(node)) return cache.billboardDrawn.get(node);
        let drawn = null;
        const tagged = records.some((record) => record.axisBillboard?.nodes?.includes(node));
        if (tagged && activeSplitGazeCameras === null) {
          drawn = false;
          // The GameObject's own renderer: the node itself, or the child mesh node the exporter gives it (same name).
          const name = D.nodeName(node);
          const meshes = rendererEntries().filter((entry) => entry.owner === node ||
            (entry.owner.parent === node && D.nodeName(entry.owner) === name)).flatMap((entry) => entry.meshes);
          if (D.effectiveVisible(node) && meshes.length) {
            const box = new T.Box3(), part = new T.Box3(), local = new T.Matrix4(), inverse = new T.Matrix4().copy(node.matrixWorld).invert();
            for (const mesh of meshes) {
              if (!mesh.geometry) continue;
              if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
              part.copy(mesh.geometry.boundingBox);
              if (mesh !== node) part.applyMatrix4(local.multiplyMatrices(inverse, mesh.matrixWorld));
              box.union(part);
            }
            if (!box.isEmpty()) {
              const center = box.getCenter(new T.Vector3()), size = box.getSize(new T.Vector3()), side = Math.max(size.x, size.z);
              box.setFromCenterAndSize(center, size.set(side, size.y, side)).applyMatrix4(rendererWorld({ owner: node }));
              const view = new T.Matrix4().fromArray(viewOf(liveCamera).view);
              drawn = new T.Frustum().setFromProjectionMatrix(new T.Matrix4().multiplyMatrices(liveCamera.projectionMatrix, view))
                .intersectsBox(box);
            }
          }
        }
        cache.billboardDrawn.set(node, drawn);
        return drawn;
      }
      read("members", "members", () => {
        const wanted = Array.isArray(filter.bones) ? new Set(filter.bones) : null;
        const result = [];
        for (const record of records) if (record.group === actors) {
          const bones = [];
          for (const [path, node] of boneIndex(record)) {
            const key = D.keyFor("bone", { slot: record.position, path });
            if (wanted && !wanted.has(key)) continue;
            if (bones.length >= maxBones) { truncated.push("members"); break; }
            bones.push({ key, ...D.decompose(node.matrixWorld, temp),
              localPosition: node.position.toArray(), localRotation: node.quaternion.toArray() });
          }
          const morphs = [];
          for (const entry of rendererEntries()) if (entry.record === record) {
            for (const mesh of entry.meshes) {
              const dictionary = mesh.morphTargetDictionary, influences = mesh.morphTargetInfluences;
              if (!dictionary || !influences) continue;
              const weights = {};
              for (const [name, index] of Object.entries(dictionary)) {
                if (influences[index] && Object.keys(weights).length < 24) weights[name] = influences[index];
              }
              if (Object.keys(weights).length) morphs.push({ rendererKey: entry.key, unit: "influence01", weights });
            }
          }
          result.push({ slot: record.position, bones, morphs, physics: Boolean(record.physics) });
        }
        return result;
      });
      read("springs", "springs", () => {
        const result = [];
        for (const record of records) if (record.group === actors && record.physics) {
          const bones = [];
          for (const [path, node] of boneIndex(record)) {
            if (!/_Dyna$/.test(path) || bones.length >= 64) continue;
            bones.push({ key: D.keyFor("bone", { slot: record.position, path }), localRotation: node.quaternion.toArray(),
              rotation: D.decompose(node.matrixWorld, temp).rotation });
          }
          result.push({ managerKey: `springs:member${record.position}`, bones });
        }
        return result.length ? result : { modeled: false };
      });
      read("post", "post", () => ({
        bloom: global.MVStudioPost?.sample?.(project, currentTime) ?? null,
        dof: global.MVStudioDofFocus?.sample?.(project, currentTime, liveCamera.fov, focusReadOnly.distance, focusReadOnly.options) ?? null,
        flare: global.MVStudioFlare?.sample?.(project, currentTime) ?? null,
        applied: settings.posteffect === true, enablePostEffect: settings.posteffect === true,
      }));
      read("quality", "quality", () => ({ mode: project?.quality?.mode ?? null, values: { ...settings } }));
      read("tracks", "tracks", () => (project?.tracks || []).filter((track) => track.nativeClass && track.binding).map((track) => ({
        key: D.keyFor("track", track), label: track.label ?? null, nativeClass: track.nativeClass, binding: track.binding,
        kind: track.kind ?? null, muted: Boolean(track.muted),
        active: track.events.flatMap((event, clipIndex) => {
          const inside = currentTime >= event.start && currentTime < event.start + event.duration;
          const weight = event.values && global.MVStudioLighting?.nativeWeight ? global.MVStudioLighting.nativeWeight(event, currentTime) : null;
          return inside || weight > 0 ? [{ clipIndex, start: event.start, duration: event.duration, weight }] : [];
        }),
      })));
      read("census", "census", () => {
        const nodes = [];
        const push = (key, kind, extra) => {
          if (nodes.length < maxNodes) nodes.push({ key, kind, ...extra }); else if (!truncated.includes("census")) truncated.push("census");
        };
        for (const entry of rendererEntries()) push(entry.key, "renderer", { scope: entry.scope, mesh: entry.mesh, path: entry.path });
        for (const record of records) record.root.traverse((node) => {
          const tag = node.userData?.mvStageNode;
          if (typeof tag?.binding === "string" && Number.isInteger(tag.path)) push(D.keyFor("stageNode", { binding: tag.binding, path: tag.path }), "stageNode");
        });
        for (const record of records) if (record.group === actors) {
          for (const path of boneIndex(record).keys()) push(D.keyFor("bone", { slot: record.position, path }), "bone");
        }
        return { nodes };
      });
      read("particles", "particles", () => stageParticleSystems?.inspect() ?? { modeled: false });
      for (const name of ["lightingRefs", "fovmodNative", "propertyBlocks"]) read(name, name, () => ({ modeled: false }));

      const nonFinite = [];
      const result = D.finalize(out, nonFinite);
      result.nonFinite = nonFinite;
      result.errors = errors;
      result.truncatedSections = truncated;
      result.cost = { elapsedMs: clock() - started };
      return result;
    }

    // ---- Camera editor (mv-studio-camera-keys.js): the free view and the game camera ----
    // A short CameraHelper of a scratch copy of the game camera, added only around the
    // free camera's render in draw(); the asset dump and inspect() never see it.
    let gameCameraHelper = null, gameHelperEnabled = false;
    const helperCamera = new T.PerspectiveCamera(), alignTarget = new T.Vector3();
    function showGameCameraHelper() {
      if (!gameHelperEnabled || typeof T.CameraHelper !== "function") return null;
      helperCamera.position.copy(liveCamera.position);
      helperCamera.quaternion.copy(liveCamera.quaternion);
      helperCamera.fov = liveCamera.fov;
      helperCamera.aspect = liveCamera.aspect;
      helperCamera.near = .1;
      helperCamera.far = Math.max(.6, Math.min(4, editorCamera.position.distanceTo(liveCamera.position) * .3));
      helperCamera.updateProjectionMatrix();
      helperCamera.updateMatrixWorld(true);
      if (!gameCameraHelper) gameCameraHelper = new T.CameraHelper(helperCamera);
      gameCameraHelper.update();
      scene.add(gameCameraHelper);
      gameCameraHelper.updateMatrixWorld(true);
      return gameCameraHelper;
    }

    // The LiveCameraOffset Y (rig up, metres) the preview adds at `time` to a camera track
    // with `binding` (applyCameraOffsets).
    function cameraOffsetAt(time, binding) {
      const weight = global.ViewerMotionTimeline?.weight, clips = cameraOffsets.get(binding);
      if (!weight || !clips || !Number.isFinite(time)) return 0;
      let offset = 0;
      for (const clip of clips) {
        if (time >= clip.start && time < clip.start + clip.duration) offset += clip.offset * weight(clip, time);
      }
      return offset;
    }

    const observer = global.ResizeObserver ? new global.ResizeObserver(() => resize(false)) : null;
    if (observer) observer.observe(mount);
    controls.addEventListener("change", requestDraw);
    resize();
    return {
      load, prepareStage, cancelStagePreparation, seek, playbackFrame, setPlaying, resize,
      flushSeekDraw() { if (seekDrawPending) draw(); },
      setCamera(mode) { useLive = mode !== "orbit"; controls.enabled = !(useLive && hasShot); draw(); },
      setScreenFade(enabled) { screenFadeEnabled = enabled !== false; requestDraw(); },
      // Fixed-step captures play on slow timestamps: with the adaptive preview off, the slow-frame
      // downscale is undone and not applied again. Playback, the physics clock and the shaft
      // damping clock are left as they are.
      setAdaptivePreview(enabled) {
        adaptivePreview = enabled !== false;
        slowFrames = 0;
        if (!adaptivePreview && previewScale !== 1) {
          previewScale = 1;
          viewportDirty = true;
        }
      },
      // The player's anti-aliasing option (default off): with it, Max and High 3D draw at the
      // screen height (nativeRenderHeight).
      setAntiAliasing(enabled) {
        const value = enabled === true;
        if (value === antiAliasing) return;
        antiAliasing = value;
        viewportDirty = true;
        resize();
      },
      // A game run's clock for the original particle systems: [directorTime, Time.time] of its
      // rendered frames (a runtime dump's frame clock or record clocks), or null for the
      // director's clock. Returns the number of samples used (0: director's clock).
      setGameClock(samples) {
        particleClock = Array.isArray(samples) ? global.MVStudioParticleSystems?.gameClock?.(samples) ?? null : null;
        requestDraw();
        return particleClock ? particleClock.samples : 0;
      },
      // Device frame-rate options and spring order (MVStudioPhysics.normalizeTiming).
      setPhysicsTiming(value) {
        physicsTiming = global.MVStudioPhysics?.normalizeTiming?.({ ...physicsTiming, ...value }) ?? null;
        resetPhysics("physics-timing");
        return physicsTiming && { ...physicsTiming, rate: physicsRate() };
      },
      // The next game frame's LiveCoreMemberManager.Update on its own, for a runtime value
      // dump: the springs step once on the pose the last evaluated frame ended with and
      // nothing else runs, as a reader between the Update scripts and that frame's deferred
      // director evaluation (LiveTimeSynchronizer.SyncMusicPlayingTime sets the time, then
      // DeferredEvaluate) sees the members. Playing frames only; returns the step taken
      // (0: none, e.g. paused or the same-frame order, whose job runs after the timeline).
      // The next seek or playback frame continues as usual.
      stepPhysicsUpdate(frameTimestamp) {
        if (disposed || !playing || !visible || !records.some((record) => record.physics)) return 0;
        const physicsStep = physicsClock?.step(frameTimestamp, physicsRate()) || 0;
        for (const record of records) record.physics?.frame?.("update", currentTime, physicsStep, settings, record.motion, physicsTiming?.order);
        if (scene.autoUpdate) scene.updateMatrixWorld();
        return physicsTiming?.order === "same-frame" ? 0 : physicsStep;
      },
      frameAll,
      // Camera editor: the free (orbit) view in three.js space, its mode, lens and orbit target.
      getViewPose() {
        editorCamera.updateMatrixWorld();
        return { mode: useLive ? "live" : "orbit", position: editorCamera.position.toArray(), quaternion: editorCamera.quaternion.toArray(),
          fov: editorCamera.fov, aspect: editorCamera.aspect, target: controls.target.toArray() };
      },
      // Puts the free camera at the game camera's pose and lens (its orbit target ahead of it).
      alignViewToGame() {
        if (!hasShot) return false;
        const distance = Math.max(.5, editorCamera.position.distanceTo(controls.target));
        editorCamera.position.copy(liveCamera.position);
        editorCamera.quaternion.copy(liveCamera.quaternion);
        if (editorCamera.fov !== liveCamera.fov) { editorCamera.fov = liveCamera.fov; editorCamera.updateProjectionMatrix(); }
        controls.target.copy(alignTarget.set(0, 0, -1).applyQuaternion(liveCamera.quaternion).multiplyScalar(distance).add(liveCamera.position));
        editorCamera.updateMatrixWorld();
        requestDraw();
        return true;
      },
      cameraOffsetAt(time = currentTime, binding) { return cameraOffsetAt(time, binding); },
      // The game camera's lens: its aspect, the vertical FOV shown, the authored FOV and the correction.
      gameCameraLens() {
        return { aspect: liveCamera.aspect, fov: liveCamera.fov, authoredFov: authoredMainFov, nativeLens: nativeMainLens,
          correction: nativeMainLens ? global.MVStudioSplit?.aspectCorrection(liveCamera.aspect) ?? 1 : 1 };
      },
      // listener() after each finished free-camera drag (OrbitControls "end"); returns the remover.
      onViewChange(listener) {
        if (typeof listener !== "function") return () => {};
        const handler = () => listener();
        controls.addEventListener("end", handler);
        return () => controls.removeEventListener("end", handler);
      },
      setGameCameraHelper(enabled) {
        const value = enabled === true;
        if (value === gameHelperEnabled) return;
        gameHelperEnabled = value;
        if (!useLive) requestDraw();
      },
      // Read-only state of the last evaluated frame for frame comparisons.
      inspect() {
        const live = useLive && hasShot, camera = live ? liveCamera : editorCamera;
        camera.updateMatrixWorld();
        const { width, height } = renderer.domElement;
        return {
          time: currentTime, cameraMode: useLive ? "live" : "orbit", liveShot: live,
          cameraEvent: live && liveCameraEvent ? { ...liveCameraEvent } : null,
          splitCameras: activeSplitGazeCameras ? Object.keys(activeSplitGazeCameras).length : 0,
          camera: {
            position: camera.getWorldPosition(new T.Vector3()).toArray(),
            quaternion: camera.getWorldQuaternion(new T.Quaternion()).toArray(),
            fov: camera.fov, aspect: camera.aspect, near: camera.near, far: camera.far,
            projection: Array.from(camera.projectionMatrix.elements),
            authoredFov: live ? authoredMainFov : null, nativeLens: live ? nativeMainLens : null,
            aspectCorrection: live ? (nativeMainLens ? global.MVStudioSplit?.aspectCorrection(camera.aspect) ?? 1 : 1) : null,
          },
          canvas: { width, height, pixelRatio: renderer.getPixelRatio() },
          renderHeight, previewScale, adaptivePreview, playing, antiAliasing, qualityMode: project?.quality?.mode ?? null, quality: { ...settings },
          constraints: records.filter((record) => record.constraints)
            .map((record) => ({ slot: record.position, ...record.constraints.getState() })),
          controlPrefabs: stageControlPrefabs?.inspect() ?? null,
        };
      },
      assetDump,
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
        screenFade?.dispose();
        if (mixers) {
          mixers.reset();
          global.MVStudioMixer?.release(mixers);
        }
        cameraDepth?.dispose();
        release(grid);
        controls.dispose();
        renderer.dispose();
        renderer.domElement.remove();
      }
    };
  }

  // LiveCoreCameraManager.Update3DCameraRenderTextures (GL 3.12.0, 0x2f61b18): the 3D cameras
  // render at RenderingResolution (1080 when it is below 1), never above Screen.height. When
  // needAntiAliasing (field 0x72) is set, the height is raised to Mathf.Max(height, Screen.height).
  // Initialize (0x2f61710) sets needAntiAliasing = antiAliasing && Quality < 21; its only caller
  // (<PostprocessInitializeAsync>d__9) passes GameSettingsDM.GetAntiAliasingMode(), the player's
  // option, which is false unless ASLocalStorage holds AntiAliasingMode. The same flag selects
  // MSAA (MSAAUtility.GetMSAALevel). The render texture width is Screen.width / Screen.height *
  // height, and _RenderTextureResolution is (width, height). Max 3D (1080) on a 1280x720 screen
  // therefore draws 1280x720, Performance 3D (640) 1138x640; on a 1440-line screen Max 3D draws
  // 1080 lines, or 1440 with anti-aliasing on.
  function nativeRenderHeight(renderingResolution, screenHeight, qualityMode, antiAliasing = false) {
    let height = renderingResolution >= 1 ? Math.min(renderingResolution, screenHeight) : 1080;
    if (antiAliasing === true && Number.isFinite(qualityMode) && qualityMode < 21) height = Math.max(height, screenHeight);
    return height;
  }

  global.MVStudioScene = { create, nativeRenderHeight };
}(window));
