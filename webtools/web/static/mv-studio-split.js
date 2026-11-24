(function (global) {
  "use strict";

  const binding = "/EntryPoint/Live/Cameras/SplitScreenEffect";
  const subCamera = new RegExp(`^${binding}/Cameras/SubCamera([1-4])$`);

  // FOVMOD clamps CameraAspectCorrector.Correction to [min, max]; the stock
  // client range is [0.75, 1]. Other bounds are only used by the value dump.
  function aspectCorrection(aspect, bounds) {
    const min = Number.isFinite(bounds?.min) ? bounds.min : 0.75, max = Number.isFinite(bounds?.max) ? bounds.max : 1;
    return Math.min(max, Math.max(min, aspect / (16 / 9)));
  }

  function enabled(value) { return value === true || value === 1; }

  function samePointer(a, b) {
    return a && b && a.m_FileID === b.m_FileID && a.m_PathID === b.m_PathID;
  }

  function validMask(data) {
    if (!data) return false;
    const { positions, uv, indices, bounds } = data;
    if (![positions, uv, indices, bounds].every(Array.isArray)) return false;
    const count = positions.length / 3;
    return Number.isInteger(count) && count >= 3 && count <= 256 && uv.length === count * 2 &&
      indices.length >= 3 && indices.length % 3 === 0 && indices.length <= 768 &&
      positions.every((value) => Number.isFinite(value) && Math.abs(value) <= 64) &&
      uv.every((value) => Number.isFinite(value) && Math.abs(value) <= 64) &&
      indices.every((value) => Number.isInteger(value) && value >= 0 && value < count) &&
      bounds.length === 2 && bounds.every((value) => Number.isFinite(value) && value > 0 && value <= 64);
  }

  function makeGeometry(T, mask) {
    const positions = mask.positions.slice(), triangleIndices = mask.indices.slice();
    // The overlay camera points along Unity +Z. Preserve screen X and Y and
    // reverse distance and winding for Three's -Z camera and front faces.
    for (let index = 2; index < positions.length; index += 3) positions[index] *= -1;
    for (let index = 0; index < triangleIndices.length; index += 3) {
      [triangleIndices[index + 1], triangleIndices[index + 2]] = [triangleIndices[index + 2], triangleIndices[index + 1]];
    }
    const geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute(mask.uv, 2));
    geometry.setIndex(triangleIndices);
    return geometry;
  }

  function create(T, renderer) {
    const overlay = new T.Scene();
    const projection = new T.OrthographicCamera(-1, 1, 1, -1, 0.01, 100);
    projection.position.z = 10;
    const clearColor = new T.Color();
    const maskCache = new Map(), layers = new Array(4);
    let data = null, enabledInQuality = false, tracks = [], viewTracks = [], frame = null;

    function layerFor(slot) {
      if (!layers[slot]) {
        const camera = new T.PerspectiveCamera(30, 1, 0.1, 1000);
        layers[slot] = { slot, camera, target: null, mesh: null };
      }
      return layers[slot];
    }

    function clearMedia() {
      frame = null;
      for (const layer of layers) if (layer?.mesh) {
        overlay.remove(layer.mesh);
        layer.mesh.material.dispose();
        layer.target.dispose();
        layer.target = layer.mesh = null;
      }
      for (const item of maskCache.values()) item.geometry.dispose();
      maskCache.clear();
    }

    function setProject(project) {
      const nextData = project?.splitScreen || null;
      if (data !== nextData) clearMedia();
      data = nextData;
      frame = null;
      enabledInQuality = project?.quality?.values?.split_screen !== false;
      tracks = [];
      viewTracks = [[], [], [], []];
      for (const track of project?.tracks || []) {
        if (track.muted) continue;
        if (track.nativeClass === "LiveSplitScreenTrack" && track.binding === binding) tracks.push(track);
        if (track.nativeClass !== "AnimationTrack") continue;
        const slot = subCamera.exec(track.binding)?.[1];
        if (slot) viewTracks[Number(slot) - 1].push(track);
      }
    }

    function findMask(event, slot) {
      const descriptor = data?.events?.[event.id]?.[slot];
      if (!descriptor || typeof descriptor.key !== "string" || !samePointer(descriptor.pointer, event.values[`mask${slot + 1}`])) return null;
      if (maskCache.has(descriptor.key)) return maskCache.get(descriptor.key);
      const mask = data?.masks?.[descriptor.key];
      if (maskCache.size >= 128 || !validMask(mask)) return null;
      const item = { bounds: mask.bounds, geometry: makeGeometry(T, mask) };
      maskCache.set(descriptor.key, item);
      return item;
    }

    // The LiveSplitScreenClip that drives the frame at `time`, or null.
    function activeEvent(time) {
      if (!enabledInQuality) return null;
      let event = null;
      for (const track of tracks) for (const clip of track.events) {
        if (time >= clip.start && time < clip.start + clip.duration && (!event || clip.start >= event.start) &&
            clip.values?.playableClass === "LiveSplitScreenClip") event = clip;
      }
      return event && [0, 1, false, true].includes(event.values.mainCamera) ? event : null;
    }

    function sample(time, sampleCamera) {
      frame = null;
      const event = activeEvent(time);
      if (!event) return null;
      const gaze = {}, views = [];
      let complete = true;
      for (let slot = 0; slot < 4; slot++) {
        const [track] = viewTracks[slot];
        const layer = layerFor(slot);
        const ready = viewTracks[slot].length === 1 && sampleCamera(layer.camera, track, time);
        if (ready) gaze[37 + slot] = layer.camera.position.toArray();
        if (!enabled(event.values[`subCamera${slot + 1}`])) continue;
        const mask = findMask(event, slot);
        if (!ready || !mask) complete = false;
        else views.push({ layer, mask });
      }
      if (complete) frame = { main: enabled(event.values.mainCamera), views };
      return gaze;
    }

    function draw(renderView, mainCamera) {
      if (!frame || (frame.main && !mainCamera)) return false;
      const { width, height } = renderer.domElement;
      if (!width || !height || !renderer.capabilities.maxTextureSize) return false;
      const correction = aspectCorrection(width / height);
      // Unity allocates each subview from its original mesh bounds, including
      // the overscan. Keep that camera aspect even if the preview has to use
      // smaller render targets to fit the mobile drawing buffer budget.
      const unit = Math.min(1080, height) * correction / 0.75;
      const sizes = frame.views.map(({ mask }) => mask.bounds.map((length) => Math.max(1, Math.round(length * unit))));
      const area = sizes.reduce((sum, size) => sum + size[0] * size[1], 0);
      const largest = Math.max(1, ...sizes.flat());
      const scale = Math.min(1, Math.sqrt(Math.min(width * height * 2, 8_000_000) / Math.max(1, area)),
        renderer.capabilities.maxTextureSize / largest);
      const originalTarget = renderer.getRenderTarget(), originalAutoClear = renderer.autoClear;
      const originalAlpha = renderer.getClearAlpha();
      renderer.getClearColor(clearColor);
      try {
        for (const layer of layers) if (layer?.mesh) layer.mesh.visible = false;
        renderer.autoClear = true;
        for (let index = 0; index < frame.views.length; index++) {
          const { layer, mask } = frame.views[index], [rawWidth, rawHeight] = sizes[index];
          if (!layer.target) {
            layer.target = new T.WebGLRenderTarget(1, 1, { minFilter: T.LinearFilter, magFilter: T.LinearFilter, stencilBuffer: true });
            layer.mesh = new T.Mesh(mask.geometry, new T.MeshBasicMaterial({ map: layer.target.texture, toneMapped: false }));
            layer.mesh.frustumCulled = false;
            layer.mesh.renderOrder = layer.slot;
            overlay.add(layer.mesh);
          }
          layer.target.setSize(Math.max(1, Math.floor(rawWidth * scale)), Math.max(1, Math.floor(rawHeight * scale)));
          const aspect = rawWidth / rawHeight;
          if (layer.camera.aspect !== aspect) {
            layer.camera.aspect = aspect;
            layer.camera.updateProjectionMatrix();
          }
          layer.mesh.geometry = mask.geometry;
          layer.mesh.scale.set(correction / (0.75 * width / height), correction / 0.75, 1);
          layer.mesh.visible = true;
          renderer.setRenderTarget(layer.target);
          renderView(layer.camera);
        }
        renderer.setRenderTarget(originalTarget);
        if (frame.main) renderView(mainCamera);
        else {
          renderer.setClearColor(0x000000, 1);
          renderer.clear();
          renderer.setClearColor(clearColor, originalAlpha);
        }
        if (frame.views.length) {
          renderer.autoClear = false;
          renderer.clearDepth();
          renderer.render(overlay, projection);
        }
      } finally {
        renderer.autoClear = originalAutoClear;
        renderer.setRenderTarget(originalTarget);
        renderer.setClearColor(clearColor, originalAlpha);
      }
      return true;
    }

    // The cameras that draw the frame at `time`, for Unity's renderer
    // visibility (a renderer is visible when any camera that draws its layer
    // sees it). Every SubCamera of the client's split prefab
    // (Resources Live/SplitScreen/SplitScreenEffect, LiveCoreCameraManager
    // .SplitScreenPrefabPath) culls the MainCamera's layers 0x0C0BC013 with
    // near .1 and far 1000. Returns null without an active split clip (the
    // main camera alone), or when a view this module cannot draw is enabled
    // (the preview then draws the main view); else whether the main camera
    // draws and the enabled sub cameras, posed on scratch cameras with their
    // mask aspect. Leaves the live frame and layer cameras untouched.
    const scratch = [];
    function camerasAt(time, sampleCamera) {
      const event = activeEvent(time);
      if (!event) return null;
      const cameras = [];
      for (let slot = 0; slot < 4; slot++) {
        if (!enabled(event.values[`subCamera${slot + 1}`])) continue;
        const [track] = viewTracks[slot], mask = findMask(event, slot);
        const camera = scratch[slot] || (scratch[slot] = new T.PerspectiveCamera(30, 1, 0.1, 1000));
        if (viewTracks[slot].length !== 1 || !mask || !sampleCamera(camera, track, time)) return null;
        camera.aspect = mask.bounds[0] / mask.bounds[1];
        camera.near = 0.1;
        camera.far = 1000;
        camera.updateProjectionMatrix();
        camera.updateMatrixWorld(true);
        cameras.push(camera);
      }
      return { main: enabled(event.values.mainCamera), cameras };
    }

    // Read-only view of the sub cameras of the last sample (runtime value dump).
    // A sub camera's aspect is set when its layer is drawn.
    function inspect() {
      return layers.filter(Boolean).map((layer) => {
        const view = frame?.views.find((item) => item.layer === layer) || null;
        const { camera } = layer;
        return { slot: layer.slot + 1, enabledInQuality, inView: Boolean(view), main: frame ? frame.main : null,
          fov: camera.fov, aspect: camera.aspect, near: camera.near, far: camera.far,
          position: camera.position.toArray(), quaternion: camera.quaternion.toArray(),
          projection: Array.from(camera.projectionMatrix.elements),
          maskBounds: view ? view.mask.bounds.slice() : null };
      });
    }

    return { setProject, sample, camerasAt, draw, inspect, dispose: clearMedia };
  }

  global.MVStudioSplit = { create, aspectCorrection };
}(window));
