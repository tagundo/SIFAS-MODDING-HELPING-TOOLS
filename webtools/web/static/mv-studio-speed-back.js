(function (global) {
  "use strict";

  const vertexShader = [
    "attribute float vertexOpacity;",
    "uniform vec4 uTextureST;",
    "varying vec2 vSpeedUV;",
    "varying float vOpacity;",
    "void main() {",
    "  vSpeedUV = uv * uTextureST.xy + uTextureST.zw;",
    "  vOpacity = vertexOpacity;",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
    "}"
  ].join("\n");
  // The native _SATURATE_ON pass adds the fourth power of the sampled RGB.
  // Leave values above one available to the stage's HDR target.
  const fragmentShader = [
    "uniform sampler2D uTexture;",
    "uniform vec3 uVertexColor;",
    "varying vec2 vSpeedUV;",
    "varying float vOpacity;",
    "void main() {",
    "  vec4 texel = texture2D(uTexture, vSpeedUV);",
    "  vec3 squareRGB = texel.rgb * texel.rgb;",
    "  gl_FragColor = vec4(squareRGB * squareRGB + texel.rgb * uVertexColor, texel.a * vOpacity);",
    "}"
  ].join("\n");

  const vector = (value, size) => Array.isArray(value) && value.length === size &&
    value.every(number => Number.isFinite(number) && Math.abs(number) <= 1000);
  const byte = value => Number.isInteger(value) && value >= 0 && value <= 255;
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;

  function checked(data, title, motion) {
    const {trackId, eventId, duration, lifetime, matrix, texture, positions, uv, indices, rgb, alpha, uvCurves} = data;
    return id(trackId) && id(eventId) && Number.isFinite(duration) && duration > 0 && duration <= 60 &&
      Number.isFinite(lifetime) && lifetime >= duration && lifetime <= 60 &&
      vector(matrix, 16) && title.validMipChain(texture) && texture[0].width === 512 &&
      Array.isArray(positions) && positions.length >= 3 && positions.length <= 2000 &&
      positions.every(position => vector(position, 3)) && Array.isArray(uv) &&
      uv.length === positions.length && uv.every(coordinates => vector(coordinates, 2)) &&
      Array.isArray(indices) && indices.length > 0 && indices.length <= 10000 && indices.length % 3 === 0 &&
      indices.every(index => Number.isInteger(index) && index >= 0 && index < positions.length) &&
      Array.isArray(rgb) && rgb.length === 3 && rgb.every(byte) &&
      Array.isArray(alpha) && alpha.length === positions.length && alpha.every(byte) &&
      Array.isArray(uvCurves) && uvCurves.length === 4 &&
      uvCurves.every(curve => title.boundedCurve(curve, motion.validCurve));
  }

  async function apply(T, root, data) {
    const title = global.MVStudioTitle, motion = global.MVStudioStageMotion;
    if (!data || !root?.isObject3D || !title || !motion || !checked(data, title, motion)) return null;
    let texture;
    try {
      texture = await title.loadTexture(T, new T.TextureLoader(), data.texture);
    } catch {
      return null;
    }
    const geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(data.positions.flat(), 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute(data.uv.flat(), 2));
    geometry.setAttribute("vertexOpacity", new T.Uint8BufferAttribute(data.alpha, 1, true));
    geometry.setIndex(data.indices);
    const uv = new T.Vector4();
    const material = new T.ShaderMaterial({
      name: "Native stage speed background", vertexShader, fragmentShader, transparent: true,
      side: T.DoubleSide, toneMapped: false, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneMinusSrcAlphaFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneMinusSrcAlphaFactor,
      stencilWrite: true, stencilFunc: T.EqualStencilFunc, stencilRef: 2,
      stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
      stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: {uTexture: {value: texture}, uTextureST: {value: uv},
        uVertexColor: {value: new T.Vector3().fromArray(data.rgb.map(value => value / 255))}},
    });
    const mesh = new T.Mesh(geometry, material);
    mesh.name = "Native stage speed background";
    mesh.renderOrder = 2900;
    // The CPU mesh particle uses the authored zero Z scale.
    mesh.matrix.fromArray(data.matrix);
    mesh.matrixAutoUpdate = false;
    mesh.visible = false;
    let stars = null, starCenter = null;
    geometry.computeBoundingBox();
    const backgroundCenter = geometry.boundingBox.getCenter(new T.Vector3()).applyMatrix4(mesh.matrix);
    if (vector(data.centerStars?.position, 3)) {
      starCenter = new T.Vector3().fromArray(data.centerStars.position);
      // The fixed pair order holds while center separation is below the
      // difference in the original sort biases.
      if (backgroundCenter.distanceTo(starCenter) < 4) {
        stars = await global.MVStudioCenterStars?.apply(T, root, data.centerStars);
      }
    }
    const companions = stars && data.movingCompanions &&
      global.MVStudioMovingCompanions?.create(T, root, data.movingCompanions, stars.texture);
    const sortEntries = companions ? [
      {mesh, center: backgroundCenter, bias: 5},
      {mesh: stars.mesh, center: starCenter, bias: 1},
      ...companions.batches.map(({mesh, center}) => ({mesh, center, bias: 0})),
    ].map((entry, index) => ({...entry, index, distance: 0})) : null;
    const cameraPosition = new T.Vector3(), viewCenter = new T.Vector3();
    root.add(mesh);
    let tracks, track, disposed = false;
    return {
      invalidate() { tracks = null; },
      sort(camera) {
        if (disposed || !sortEntries || !companions.batches.some(({mesh}) => mesh.visible)) return;
        camera.updateMatrixWorld();
        cameraPosition.setFromMatrixPosition(camera.matrixWorld);
        for (const entry of sortEntries) {
          const distance = camera.isOrthographicCamera
            ? -viewCenter.copy(entry.center).applyMatrix4(camera.matrixWorldInverse).z
            : cameraPosition.distanceTo(entry.center);
          entry.distance = distance + entry.bias;
        }
        // Only these native queue-2900 siblings participate. Their distance
        // order can change for a split camera without affecting other queues.
        sortEntries.sort((a, b) => b.distance - a.distance || a.index - b.index);
        sortEntries.forEach(({mesh}, index) => { mesh.renderOrder = 2900 + index * .01; });
      },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          const matches = (tracks || []).filter(row => row.id === data.trackId && row.nativeClass === "CustomControlTrack");
          track = matches.length === 1 ? matches[0] : null;
        }
        const event = !track?.muted && track?.events.find(row => row.id === data.eventId);
        const active = project?.quality?.values?.stage_display !== false && title.neutralClip(event) &&
          time >= event.start && time < event.start + event.duration;
        const elapsed = active ? time - event.start : null;
        stars?.update(elapsed);
        mesh.visible = active && elapsed < data.lifetime;
        const fps = project?.quality?.values?.frame_rate_60fps === true ? 60 : 30;
        companions?.update(elapsed, fps, mesh.visible);
        if (!mesh.visible) return;
        const local = Math.min(data.duration, elapsed);
        const [sx, sy, ox, oy] = data.uvCurves.map(curve => motion.evaluate(curve, local));
        uv.set(sx, sy, ox, 1 - sy - oy);
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        root.remove(mesh);
        companions?.dispose();
        stars?.dispose();
        geometry.dispose();
        material.dispose();
        texture.dispose();
      },
    };
  }

  global.MVStudioSpeedBack = {apply};
})(typeof window !== "undefined" ? window : globalThis);
