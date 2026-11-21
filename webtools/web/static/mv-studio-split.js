(function (global) {
  "use strict";

  const binding = "/EntryPoint/Live/Cameras/SplitScreenEffect";
  const subCamera = new RegExp(`^${binding}/Cameras/SubCamera([1-4])$`);

  function aspectCorrection(aspect) {
    return Math.min(1, Math.max(0.75, aspect / (16 / 9)));
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

    function sample(time, sampleCamera) {
      frame = null;
      if (!enabledInQuality) return null;
      let event = null;
      for (const track of tracks) for (const clip of track.events) {
        if (time >= clip.start && time < clip.start + clip.duration && (!event || clip.start >= event.start) &&
            clip.values?.playableClass === "LiveSplitScreenClip") event = clip;
      }
      if (!event || ![0, 1, false, true].includes(event.values.mainCamera)) return null;
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
            layer.target = new T.WebGLRenderTarget(1, 1, { minFilter: T.LinearFilter, magFilter: T.LinearFilter });
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

    return { setProject, sample, draw, dispose: clearMedia };
  }

  global.MVStudioSplit = { create, aspectCorrection };
}(window));
