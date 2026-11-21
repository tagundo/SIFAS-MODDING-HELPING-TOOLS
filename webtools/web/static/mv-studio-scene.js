(function (global) {
  "use strict";

  function vector(value, length) {
    return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  }

  function activeEvent(track, time) {
    return track.events.reduce((current, event) => event.start <= time &&
      time <= event.start + event.duration && (!current || event.start >= current.start) ? event : current, null);
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

  function create(mount, options) {
    const T = global.THREE;
    if (!T || !T.GLTFLoader || !T.OrbitControls) throw new Error("The 3D preview could not start.");
    const renderer = new T.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
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
    // The scene's fixed roots otherwise dirty the world matrix of every
    // descendant on each render. Dancers and both cameras still animate.
    for (const node of [scene, stage, actors, effects, grid, ambient, key, rim]) {
      node.updateMatrix();
      node.matrixAutoUpdate = false;
    }
    controls.target.set(0, 1.1, 0);
    editorCamera.position.set(5, 3.8, 8);
    controls.update();

    let disposed = false, visible = true, generation = 0, request = null, project = null;
    let currentTime = 0, useLive = true, hasShot = false, records = [], queuedDraw = 0;
    let playing = false, lastPlaybackFrame = null, slowFrames = 0, previewScale = 1;
    let renderHeight = null, viewportDirty = false, settings = {}, trackSource = null, renderTracks = [];
    const nativeEvents = new Map(), performers = new Map(), sortedCameraFrames = new WeakMap();
    const size = new T.Vector2();
    const position = new T.Vector3(), otherPosition = new T.Vector3();
    const rotation = new T.Quaternion(), otherRotation = new T.Quaternion();
    const gaze = { camera: [0, 0, 0], members: {} };

    function draw() {
      if (queuedDraw) global.cancelAnimationFrame(queuedDraw);
      queuedDraw = 0;
      if (!disposed && visible && mount.clientWidth && mount.clientHeight) {
        renderer.render(scene, useLive && hasShot ? liveCamera : editorCamera);
      }
    }

    function requestDraw() {
      if (!disposed && !queuedDraw) queuedDraw = global.requestAnimationFrame(draw);
    }

    function resize() {
      const width = mount.clientWidth, height = mount.clientHeight;
      if (disposed || !width || !height) return;
      const values = project && project.quality && project.quality.values || {};
      const nativeHeight = values.rendering_resolution;
      const resolution = Number.isFinite(nativeHeight) && nativeHeight > 0
        ? Math.min(nativeHeight / height, 2) : Math.min(global.devicePixelRatio || 1, 2);
      const previewResolution = resolution * previewScale;
      if (renderer.getPixelRatio() !== previewResolution) renderer.setPixelRatio(previewResolution);
      renderHeight = nativeHeight;
      viewportDirty = false;
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
        if (segment.kind === "gaze" && Number.isInteger(values.target)) assign(segment, "target", values.target);
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
      for (const record of records) if (record.group === actors) {
        const member = gaze.members[record.position] || (gaze.members[record.position] = [0, 0, 0]);
        record.root.position.toArray(member);
        member[1] += 1.5;
      }
      (useLive && hasShot ? liveCamera : editorCamera).position.toArray(gaze.camera);
      return gaze;
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
      gaze.members = {};
      hasShot = false;
      if (!project || disposed) return;
      applyProject();
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
      // Fetch the next GLB while the current one decodes. Only one model is
      // decoded at a time so concurrent texture uploads stay bounded on mobile.
      function fetchEntry(entry) {
        return entry && modelBytes(entry.spec.glb, signal).then((bytes) => ({ bytes }), (error) => ({ error }));
      }
      let pending = fetchEntry(entries[0]);
      for (let index = 0; index < entries.length; index++) {
        const entry = entries[index];
        if (ticket !== generation || disposed) return;
        try {
          const download = await pending;
          if (ticket !== generation || disposed) return;
          pending = fetchEntry(entries[index + 1]);
          if (download.error) throw download.error;
          const gltf = await new Promise((resolve, reject) => new T.GLTFLoader().parse(download.bytes, "", resolve, reject));
          if (ticket !== generation || disposed) { release(gltf.scene); return; }
          const record = { root: gltf.scene, id: entry.spec.id, group: entry.group, position: entry.spec.position,
            visibility: [] };
          gltf.scene.traverse((node) => {
            if (entry.group !== actors && node.matrixAutoUpdate) {
              node.updateMatrix();
              node.matrixAutoUpdate = false;
            }
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
              parser: gltf.parser, enabled: true, rimlight: true, onChange: requestDraw,
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
              record.motionEvents = record.segments.concat(record.facialEvents);
              record.motion = global.ViewerMotionTimeline.create(gltf.scene, gltf.animations,
                entry.spec.rig || {}, { ...entry.spec.motion, bodySegments: record.segments,
                  facial: { ...entry.spec.motion.facial, events: record.facialEvents } },
                { getGazeContext: gazeContext, indexTiming: true });
              updateMotion(record);
            } else if (gltf.animations.length) {
              record.mixer = new T.AnimationMixer(gltf.scene);
              record.mixer.clipAction(gltf.animations[0]).play();
            }
          }
          entry.group.add(record.root);
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
      if (ticket !== generation || disposed) return;
      grid.visible = !stage.children.length;
      frameAll();
      seek(currentTime, project);
    }

    function poseCamera(event, time) {
      const value = event.values || {};
      const local = Math.max(0, time - event.start);
      const frames = value.keyframes;
      if (Array.isArray(frames) && !sortedCameraFrames.has(frames)) {
        sortedCameraFrames.set(frames, frames.every((frame, index) => !index || frame.time >= frames[index - 1].time));
      }
      const [left, right] = cameraSamples(event, local, sortedCameraFrames.get(frames));
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
        const sampled = Math.min(170, Math.max(1, fov + (next - fov) * fraction));
        if (liveCamera.fov !== sampled) {
          liveCamera.fov = sampled;
          liveCamera.updateProjectionMatrix();
        }
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
        (track.kind === "camera" && (!track.binding || /MainCamera/i.test(track.binding)))));
      for (const performer of project && project.performers || []) performers.set(performer.id, performer);
      effects.visible = settings.stage_control !== false;
      for (const record of records) {
        for (const entry of record.visibility) entry.node.visible = settings[entry.quality] !== false;
        if (record.motion) updateMotion(record);
      }
    }

    function seek(time, value) {
      if (disposed) return;
      project = value || project;
      applyProject();
      playbackFrame(time);
    }

    function setPlaying(value) {
      if (playing === value) return;
      playing = value;
      lastPlaybackFrame = null;
      slowFrames = 0;
      if (!playing && previewScale !== 1) {
        previewScale = 1;
        viewportDirty = true;
      }
    }

    function playbackFrame(time, frameTimestamp) {
      if (disposed) return;
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
      ambient.color.setHex(0xe4edff);
      ambient.intensity = 1.2;
      key.color.setHex(0xffffff);
      key.intensity = 2.1;
      rim.color.setHex(0x8bb6ff);
      rim.intensity = 1.0;
      for (const track of renderTracks) {
        const event = activeEvent(track, currentTime);
        if (!event) continue;
        if (track.kind === "camera") {
          hasShot = poseCamera(event, currentTime) || hasShot;
        } else {
          const label = event.values.playableClass;
          if (label === "LiveBaseLightClip") {
            setColor(ambient.color, lightValue(event, ["ambientColor"]), 0xe4edff);
            setColor(rim.color, lightValue(event, ["rimlightColor"]), 0x8bb6ff);
            const strength = lightValue(event, ["rimlightIntensity"]);
            if (Number.isFinite(strength)) rim.intensity = Math.max(0, Math.min(10, strength));
          } else if (label === "LiveStageAmbientClip" && settings.stage_ambient !== false) {
            setColor(key.color, lightValue(event, ["color", "tintColor"]), 0xffffff);
          } else if (label === "LiveRimlightClip" && settings.member_rim_light !== false) {
            setColor(rim.color, lightValue(event, ["color"]), 0x8bb6ff);
          }
        }
      }
      if (settings.stage_ambient === false) ambient.intensity = 0.6;
      if (settings.base_light === false) key.intensity = 0.8;
      if (settings.member_rim_light === false) rim.intensity = 0;
      for (const record of records) {
        if (record.group !== actors) continue;
        const performer = performers.get(record.id);
        if (performer) actorPose(record, performer);
        if (record.motion) {
          record.motion.evaluate(currentTime);
          record.motion.applyVisibility(currentTime);
        } else if (record.mixer) record.mixer.setTime(currentTime);
      }
      if (viewportDirty || renderHeight !== settings.rendering_resolution) resize();
      else draw();
    }

    const observer = global.ResizeObserver ? new global.ResizeObserver(resize) : null;
    if (observer) observer.observe(mount);
    controls.addEventListener("change", requestDraw);
    resize();
    return {
      load, seek, playbackFrame, setPlaying, resize,
      setCamera(mode) { useLive = mode !== "orbit"; draw(); },
      frameAll,
      setVisible(value) { visible = Boolean(value); if (visible) resize(); },
      dispose() {
        disposed = true;
        if (request) request.abort();
        if (observer) observer.disconnect();
        if (queuedDraw) global.cancelAnimationFrame(queuedDraw);
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
