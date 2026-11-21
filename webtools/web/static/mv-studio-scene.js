(function (global) {
  "use strict";

  function vector(value, length) {
    return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  }

  function activeEvent(track, time) {
    return track.events.reduce((current, event) => event.start <= time &&
      time <= event.start + event.duration && (!current || event.start >= current.start) ? event : current, null);
  }

  function localURL(value) {
    return typeof value === "string" && /^\/api\/(?:mv-studio\/media\/[a-f0-9]{32}\.(?:glb|wav|mp3|ogg|m4a)|viewer\/model\/[a-f0-9]{32}\.glb)$/.test(value);
  }

  function create(mount, options) {
    const T = global.THREE;
    if (!T || !T.GLTFLoader || !T.OrbitControls) throw new Error("The 3D preview could not start.");
    const renderer = new T.WebGLRenderer({ antialias: true, alpha: false });
    renderer.outputEncoding = T.sRGBEncoding;
    renderer.setClearColor(0x111522);
    renderer.shadowMap.type = T.PCFSoftShadowMap;
    renderer.domElement.setAttribute("aria-label", "MV stage preview");
    mount.appendChild(renderer.domElement);

    const scene = new T.Scene();
    const editorCamera = new T.PerspectiveCamera(48, 1, 0.02, 1000);
    const liveCamera = new T.PerspectiveCamera(42, 1, 0.02, 1000);
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
    scene.add(stage, actors, effects, grid, ambient, key, rim);
    controls.target.set(0, 1.1, 0);
    editorCamera.position.set(5, 3.8, 8);
    controls.update();

    let disposed = false, visible = true, generation = 0, request = null, project = null;
    let currentTime = 0, useLive = true, hasShot = false, records = [];
    let renderHeight = null, trackSource = null;
    const nativeEvents = new Map(), size = new T.Vector2();
    const position = new T.Vector3(), otherPosition = new T.Vector3();
    const rotation = new T.Quaternion(), otherRotation = new T.Quaternion();

    function draw() {
      if (!disposed && visible && mount.clientWidth && mount.clientHeight) {
        renderer.render(scene, useLive && hasShot ? liveCamera : editorCamera);
      }
    }

    function resize() {
      const width = mount.clientWidth, height = mount.clientHeight;
      if (disposed || !width || !height) return;
      const values = project && project.quality && project.quality.values || {};
      const nativeHeight = values.rendering_resolution;
      const resolution = Number.isFinite(nativeHeight) && nativeHeight > 0
        ? Math.min(nativeHeight / height, 2) : Math.min(global.devicePixelRatio || 1, 2);
      if (renderer.getPixelRatio() !== resolution) renderer.setPixelRatio(resolution);
      renderHeight = nativeHeight;
      renderer.getSize(size);
      if (size.x !== width || size.y !== height) renderer.setSize(width, height, false);
      for (const camera of [editorCamera, liveCamera]) {
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
      }
      draw();
    }

    function release(root) {
      const geometries = new Set(), materials = new Set(), textures = new Set();
      root.traverse((node) => {
        if (node.geometry) geometries.add(node.geometry);
        (Array.isArray(node.material) ? node.material : [node.material]).filter(Boolean).forEach((material) => {
          materials.add(material);
          for (const value of Object.values(material)) if (value && value.isTexture) textures.add(value);
        });
      });
      textures.forEach((value) => value.dispose());
      materials.forEach((value) => value.dispose());
      geometries.forEach((value) => value.dispose());
    }

    function clear() {
      for (const record of records) {
        if (record.materials) record.materials.dispose();
        if (record.mixer) record.mixer.stopAllAction();
        if (record.root.parent) record.root.parent.remove(record.root);
        release(record.root);
      }
      records = [];
      grid.visible = true;
    }

    async function model(url, signal) {
      if (!localURL(url)) throw new Error("The preview asset address is invalid.");
      const response = await fetch(url, { signal });
      if (!response.ok) throw new Error("The preview asset is unavailable. Load it again.");
      const bytes = await response.arrayBuffer();
      if (!bytes.byteLength || bytes.byteLength > 96 * 1024 * 1024) throw new Error("The 3D preview asset is too large.");
      return new Promise((resolve, reject) => new T.GLTFLoader().parse(bytes, "", resolve, reject));
    }

    function actorPose(record, performer) {
      const move = performer.transform || {};
      if (vector(move.position, 3)) record.root.position.fromArray(move.position);
      if (vector(move.rotation, 4)) record.root.quaternion.fromArray(move.rotation).normalize();
      if (vector(move.scale, 3)) record.root.scale.fromArray(move.scale);
    }

    function updateMotion(record) {
      for (const segment of record.segments.concat(record.facialEvents)) {
        const bound = nativeEvents.get(segment.nativeEventId);
        if (!bound) continue;
        const event = bound.event, values = event.values;
        segment.start = event.start;
        segment.duration = event.duration;
        const weight = segment.kind === "gaze" ? values.weightForDirection : values.weight;
        segment.weight = bound.track.muted ? 0 : Number.isFinite(weight) ? Math.min(1, Math.max(0, weight)) : 1;
        if (segment.kind === "gaze" && Number.isInteger(values.target)) segment.target = values.target;
        if (Number.isFinite(values.clipIn)) segment.clipIn = values.clipIn;
        if (Number.isFinite(values.timeScale) && values.timeScale > 0) segment.timeScale = values.timeScale;
        for (const key of ["easeIn", "easeOut", "blendIn", "blendOut"]) {
          if (Number.isFinite(values[key])) segment.timing[key] = values[key];
        }
        for (const side of ["pre", "post"]) {
          for (const field of ["Time", "Mode"]) {
            const edited = values[side + "Extrapolation" + field];
            if (Number.isFinite(edited)) segment.timing[side + field] = edited;
          }
        }
      }
    }

    function gazeContext() {
      const members = {};
      for (const record of records) if (record.group === actors) {
        members[record.position] = [record.root.position.x, record.root.position.y + 1.5, record.root.position.z];
      }
      return { camera: (useLive && hasShot ? liveCamera : editorCamera).position.toArray(), members };
    }

    function frameAll() {
      const bounds = new T.Box3();
      const framed = actors.children.length ? actors : stage;
      bounds.setFromObject(framed);
      if (bounds.isEmpty()) return;
      const center = bounds.getCenter(new T.Vector3());
      const radius = Math.max(1.5, bounds.getSize(new T.Vector3()).length() * 0.5);
      controls.target.copy(center);
      editorCamera.position.copy(center).add(new T.Vector3(0.45, 0.35, 1.25).multiplyScalar(radius * 2));
      controls.update();
    }

    async function load(value) {
      project = value;
      if (request) request.abort();
      request = new AbortController();
      const signal = request.signal, ticket = ++generation;
      clear();
      if (!project || disposed) return;
      const entries = [];
      if (project.stage && project.stage.glb) entries.push({ spec: project.stage, group: stage });
      if (project.stage && project.stage.effectsGlb) entries.push({ spec: { glb: project.stage.effectsGlb }, group: effects });
      for (const asset of project.assets || []) {
        if (["effect", "props", "background"].includes(asset.kind) && asset.previewUrl &&
            (!project.stage || asset.previewUrl !== project.stage.effectsGlb)) {
          entries.push({ spec: { glb: asset.previewUrl }, group: effects });
        }
      }
      for (const performer of (project.performers || []).slice(0, 9)) {
        if (performer.glb) entries.push({ spec: performer, group: actors });
      }
      // Decode one bundle at a time on mobile and keep only the current scene.
      for (const entry of entries) {
        if (ticket !== generation || disposed) return;
        try {
          const gltf = await model(entry.spec.glb, signal);
          if (ticket !== generation || disposed) { release(gltf.scene); return; }
          const record = { root: gltf.scene, id: entry.spec.id, group: entry.group, position: entry.spec.position,
            visibility: [] };
          gltf.scene.traverse((node) => {
            if (!node.isMesh) return;
            node.castShadow = entry.group === actors;
            node.receiveShadow = true;
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
              if (quality) record.visibility.push({ node, quality });
            }
          });
          if (entry.group === actors) {
            actorPose(record, entry.spec);
            if (global.SifasMaterial) record.materials = global.SifasMaterial.apply(gltf.scene, renderer, {
              parser: gltf.parser, enabled: true, rimlight: true, onChange: draw,
              mouthCentroidDepth: renderer.capabilities.isWebGL2 === true
            });
            if (record.materials && record.materials.ready) await record.materials.ready;
            if (ticket !== generation || disposed) {
              if (record.materials) record.materials.dispose();
              release(gltf.scene);
              return;
            }
            if (entry.spec.motion && global.ViewerMotionTimeline) {
              record.segments = (entry.spec.motion.bodySegments || []).map((segment) => ({
                ...segment, timing: { ...segment.timing }
              }));
              record.facialEvents = (entry.spec.motion.facial?.events || []).map((event) => ({
                ...event, timing: { ...event.timing }
              }));
              record.motion = global.ViewerMotionTimeline.create(gltf.scene, gltf.animations,
                entry.spec.rig || {}, { ...entry.spec.motion, bodySegments: record.segments,
                  facial: { ...entry.spec.motion.facial, events: record.facialEvents } },
                { getGazeContext: gazeContext });
            } else if (gltf.animations.length) {
              record.mixer = new T.AnimationMixer(gltf.scene);
              record.mixer.clipAction(gltf.animations[0]).play();
            }
          }
          entry.group.add(record.root);
          records.push(record);
        } catch (error) {
          if (!signal.aborted && !disposed && options && options.onError) options.onError(error.message);
        }
      }
      if (ticket !== generation || disposed) return;
      grid.visible = !stage.children.length;
      frameAll();
      seek(currentTime, project);
    }

    function poseCamera(event, time) {
      const value = event.values || {};
      const frames = Array.isArray(value.keyframes) ? value.keyframes : [];
      const local = Math.max(0, time - event.start);
      let left = frames[0] || value, right = left;
      for (const sample of frames) {
        right = sample;
        if (sample.time > local) break;
        left = sample;
      }
      if (!vector(left.position, 3) || !vector(left.rotation, 4)) return false;
      const fraction = left !== right && right.time > left.time ? Math.max(0, Math.min(1, (local - left.time) / (right.time - left.time))) : 0;
      position.fromArray(left.position);
      if (vector(right.position, 3)) position.lerp(otherPosition.fromArray(right.position), fraction);
      liveCamera.position.set(-position.x, position.y, position.z);
      rotation.fromArray(left.rotation).normalize();
      if (vector(right.rotation, 4)) rotation.slerp(otherRotation.fromArray(right.rotation).normalize(), fraction);
      // The live camera rig already stores a backwards-facing view relative
      // to the camera clip rotation. Mirror X to match the exported meshes.
      liveCamera.quaternion.set(rotation.x, -rotation.y, -rotation.z, rotation.w);
      const fov = Number.isFinite(left.fov) ? left.fov : value.fov;
      if (Number.isFinite(fov)) {
        const next = Number.isFinite(right.fov) ? right.fov : fov;
        liveCamera.fov = Math.min(170, Math.max(1, fov + (next - fov) * fraction));
        liveCamera.updateProjectionMatrix();
      }
      return true;
    }

    function lightValue(event, keys) {
      const values = event.values || {};
      for (const key of keys) if (Object.prototype.hasOwnProperty.call(values, key)) return values[key];
      return null;
    }

    function color(value, fallback) {
      if (vector(value, 3) || vector(value, 4)) return new T.Color(value[0], value[1], value[2]);
      if (value && [value.r, value.g, value.b].every(Number.isFinite)) return new T.Color(value.r, value.g, value.b);
      return new T.Color(fallback);
    }

    function seek(time, value) {
      if (disposed) return;
      project = value || project;
      currentTime = Number.isFinite(time) ? time : 0;
      const tracks = project && project.tracks || [];
      const settings = project && project.quality && project.quality.values || {};
      if (trackSource !== tracks) {
        trackSource = tracks;
        nativeEvents.clear();
        for (const track of tracks) if (["dance", "mouth", "eyes", "gaze", "cheek"].includes(track.kind)) {
          for (const event of track.events) nativeEvents.set(event.id, { track, event });
        }
      }
      hasShot = false;
      ambient.color.setHex(0xe4edff);
      ambient.intensity = 1.2;
      key.color.setHex(0xffffff);
      key.intensity = 2.1;
      rim.color.setHex(0x8bb6ff);
      rim.intensity = 1.0;
      for (const track of tracks) {
        if (track.muted) continue;
        if (track.kind === "camera" && (!track.binding || /MainCamera/i.test(track.binding))) {
          const event = activeEvent(track, currentTime);
          if (event) hasShot = poseCamera(event, currentTime) || hasShot;
        } else if (track.kind === "lighting") {
          const event = activeEvent(track, currentTime);
          if (!event) continue;
          const label = event.values.playableClass;
          if (label === "LiveBaseLightClip") {
            ambient.color.copy(color(lightValue(event, ["ambientColor"]), 0xe4edff));
            rim.color.copy(color(lightValue(event, ["rimlightColor"]), 0x8bb6ff));
            const strength = lightValue(event, ["rimlightIntensity"]);
            if (Number.isFinite(strength)) rim.intensity = Math.max(0, Math.min(10, strength));
          } else if (label === "LiveStageAmbientClip" && settings.stage_ambient !== false) {
            key.color.copy(color(lightValue(event, ["color", "tintColor"]), 0xffffff));
          } else if (label === "LiveRimlightClip" && settings.member_rim_light !== false) {
            rim.color.copy(color(lightValue(event, ["color"]), 0x8bb6ff));
          }
        }
      }
      effects.visible = settings.stage_control !== false;
      if (settings.stage_ambient === false) ambient.intensity = 0.6;
      if (settings.base_light === false) key.intensity = 0.8;
      if (settings.member_rim_light === false) rim.intensity = 0;
      for (const record of records) {
        for (const entry of record.visibility) entry.node.visible = settings[entry.quality] !== false;
        if (record.group !== actors) continue;
        const performer = ((project && project.performers) || []).find((entry) => entry.id === record.id);
        if (performer) actorPose(record, performer);
        if (record.motion) {
          updateMotion(record);
          record.motion.evaluate(currentTime);
          record.motion.applyVisibility(currentTime);
        } else if (record.mixer) record.mixer.setTime(currentTime);
      }
      if (renderHeight !== settings.rendering_resolution) resize();
      else draw();
    }

    const observer = global.ResizeObserver ? new global.ResizeObserver(resize) : null;
    if (observer) observer.observe(mount);
    controls.addEventListener("change", draw);
    resize();
    return {
      load, seek, resize,
      setCamera(mode) { useLive = mode !== "orbit"; draw(); },
      frameAll,
      setVisible(value) { visible = Boolean(value); if (visible) resize(); },
      dispose() {
        disposed = true;
        if (request) request.abort();
        if (observer) observer.disconnect();
        clear();
        release(grid);
        controls.dispose();
        renderer.dispose();
        renderer.domElement.remove();
      }
    };
  }

  global.MVStudioScene = { create };
}(window));
