(function (global) {
  "use strict";

  const vertexShader = `
    attribute vec4 particleColor;
    uniform vec4 uAtlas;
    varying vec2 vTexture;
    varying vec4 vColor;
    void main() {
      gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(position, 1.0);
      vTexture = uv * uAtlas.xy + uAtlas.zw;
      vColor = particleColor;
    }
  `;
  const fragmentShader = `
    uniform sampler2D uTexture;
    uniform vec4 uTint;
    varying vec2 vTexture;
    varying vec4 vColor;
    void main() { gl_FragColor = texture2D(uTexture, vTexture) * vColor * uTint; }
  `;

  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const finiteVector = (value, count) => Array.isArray(value) && value.length === count && value.every(Number.isFinite);
  const capacity = 200;
  const atlasColumns = new Map([["03", 0], ["04", .5], ["06", .25]]);

  function checked(source, title) {
    const {geometry, material, cues} = source || {};
    return source?.schema === 1 && title.validMipChain(source.texture) && source.texture[0].width === 256 &&
      Array.isArray(geometry?.positions) && geometry.positions.length === 22 && geometry.positions.every(row => finiteVector(row, 3)) &&
      Array.isArray(geometry.uv) && geometry.uv.length === 22 && geometry.uv.every(row => finiteVector(row, 2)) &&
      Array.isArray(geometry.indices) && geometry.indices.length === 60 &&
      geometry.indices.every(index => Number.isInteger(index) && index >= 0 && index < 22) &&
      material?.queue === 3010 && material.cull === 0 && material.blend === "alpha" && material.premultiply === false &&
      finiteVector(material.tint, 4) && material.tint.every(value => value === 1) &&
      Array.isArray(cues) && cues.length >= 1 && cues.length <= 6 && cues.every(cue => id(cue?.trackId) &&
        id(cue.eventId) && atlasColumns.has(cue.profile) &&
        finiteVector(cue.position, 3) && finiteVector(cue.rotation, 4) && finiteVector(cue.uv, 4) &&
        cue.uv[0] === .25 && cue.uv[1] === .25 && cue.uv[2] === atlasColumns.get(cue.profile) && cue.uv[3] === .25) &&
      new Set(cues.map(cue => JSON.stringify([cue.trackId, cue.eventId]))).size === cues.length &&
      cues.filter(cue => cue.profile === "03").length <= 1 && cues.filter(cue => cue.profile === "04").length <= 1 &&
      cues.filter(cue => cue.profile === "06").length <= 4;
  }

  function make(T, source, texture, cue, name) {
    const geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(source.geometry.positions.flat(), 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute(source.geometry.uv.flat(), 2));
    geometry.setIndex(source.geometry.indices);
    const colors = new T.InstancedBufferAttribute(new Uint8Array(capacity * 4), 4, true).setUsage(T.DynamicDrawUsage);
    geometry.setAttribute("particleColor", colors);
    const material = new T.ShaderMaterial({
      vertexShader, fragmentShader, transparent: true, toneMapped: false, side: T.DoubleSide,
      depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneMinusSrcAlphaFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneMinusSrcAlphaFactor,
      stencilWrite: true, stencilRef: 2, stencilFunc: T.AlwaysStencilFunc,
      stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
      stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: {uTexture: {value: texture}, uAtlas: {value: new T.Vector4().fromArray(cue.uv)},
        uTint: {value: new T.Vector4().fromArray(source.material.tint)}},
    });
    const mesh = new T.InstancedMesh(geometry, material, capacity);
    mesh.name = name;
    mesh.instanceMatrix.setUsage(T.DynamicDrawUsage);
    mesh.renderOrder = source.material.queue;
    mesh.frustumCulled = false;
    mesh.matrixAutoUpdate = false;
    mesh.visible = false;
    mesh.count = 0;
    return {mesh, colors};
  }

  async function apply(T, root, source, sharedAtlas) {
    const title = global.MVStudioTitle, simulation = global.MVStudioAutumnLeavesSimulation;
    const particles = global.MVStudioStageParticles;
    if (!root?.isObject3D || !particles || !title || !simulation || !checked(source, title)) return null;
    const candidates = source.cues.map(cue => ({cue, stream: simulation.create({...source, ...cue})})).filter(entry => entry.stream);
    if (!candidates.length) return null;
    const borrowed = title.sharedMipTexture(source.texture, sharedAtlas);
    let texture;
    try {
      texture = borrowed || await title.loadTexture(T, new T.TextureLoader(), source.texture);
    } catch {
      return null;
    }
    let redCue = 0;
    const entries = candidates.map(({cue, stream}) => {
      // Native PrefabControl has its own clone and clock for every clip,
      // including adjacent clips that reuse the same red-leaf prefab.
      const clip = cue.profile === "06" ? `06 ${++redCue}` : cue.profile;
      const packet = make(T, source, texture, cue, `Native Aion falling leaves ${clip}`);
      root.add(packet.mesh);
      return {cue, stream, ...packet, frame: -1, fps: 0,
        emitterRotation: new T.Quaternion().fromArray(cue.rotation), center: new T.Vector3()};
    });
    const center = new T.Vector3(), scale = new T.Vector3(), eye = new T.Vector3();
    const matrix = new T.Matrix4(), spin = new T.Euler(), orientation = new T.Quaternion();
    const bounds = new T.Box3();
    let tracks, disposed = false;

    function update(entry, frame, fps) {
      const {mesh, stream, colors, emitterRotation} = entry;
      let count = 0;
      bounds.makeEmpty();
      stream.sample(frame / fps, fps, (x, y, z, size, rx, ry, rz, r, g, b, a) => {
        center.set(x, y, z);
        bounds.expandByPoint(center);
        if (!(size > 0) || !a || count >= capacity) return;
        // The native Mesh renderer rotates Z, X, then Y before applying the
        // emitter basis. Reflect the native angles along the imported mesh X.
        orientation.setFromEuler(spin.set(rx, -ry, -rz, "YXZ")).premultiply(emitterRotation);
        mesh.setMatrixAt(count, matrix.compose(center, orientation, scale.setScalar(size)));
        colors.setXYZW(count++, r, g, b, a);
      });
      bounds.getCenter(entry.center);
      mesh.visible = count > 0;
      mesh.count = count;
      if (!count) return;
      mesh.instanceMatrix.updateRange.count = count * 16;
      colors.updateRange.count = count * 4;
      mesh.instanceMatrix.needsUpdate = colors.needsUpdate = true;
    }

    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          for (const entry of entries) {
            entry.track = tracks?.find(track => track.id === entry.cue.trackId && track.nativeClass === "CustomControlTrack");
          }
        }
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        for (const entry of entries) {
          const {mesh, cue, track} = entry;
          const event = quality?.stage_control !== false && !track?.muted && track?.events.find(row => row.id === cue.eventId);
          const timing = particles.activeControlFrame(event, time, fps);
          if (!timing) {
            mesh.count = 0;
            mesh.visible = false;
            entry.frame = -1;
            continue;
          }
          const {offset, frame} = timing;
          if (mesh.position.x !== offset[0] || mesh.position.y !== offset[1] || mesh.position.z !== offset[2]) {
            mesh.position.fromArray(offset);
            mesh.updateMatrix();
          }
          if (entry.frame === frame && entry.fps === fps) continue;
          entry.frame = frame;
          entry.fps = fps;
          update(entry, frame, fps);
        }
      },
      sort(camera, rain = [], butterfly = []) {
        if (disposed) return;
        const leaves = entries.filter(entry => entry.mesh.visible);
        if (!leaves.length) {
          for (const {mesh} of rain) mesh.renderOrder = source.material.queue;
          return;
        }
        if (leaves.length === 1 && !rain.length && !butterfly.length) {
          leaves[0].mesh.renderOrder = source.material.queue;
          return;
        }
        camera.updateMatrixWorld();
        eye.setFromMatrixPosition(camera.matrixWorld);
        // The leaves use alpha-over. Preserve the native camera order
        // against other transparent renderers in this part of the song.
        const visible = [...rain, ...butterfly, ...leaves].map((entry, order) => {
          entry.mesh.updateWorldMatrix(true, false);
          center.copy(entry.center).applyMatrix4(entry.mesh.matrixWorld);
          const distance = camera.isOrthographicCamera ? Math.fround(-center.applyMatrix4(camera.matrixWorldInverse).z) :
            Math.fround(eye.distanceToSquared(center));
          return {mesh: entry.mesh, order, distance};
        });
        visible.sort((a, b) => b.distance - a.distance || a.order - b.order);
        visible.forEach(({mesh}, index) => { mesh.renderOrder = source.material.queue + .01 * index; });
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        for (const {mesh} of entries) {
          root.remove(mesh);
          mesh.dispose();
          mesh.geometry.dispose();
          mesh.material.dispose();
        }
        if (!borrowed) texture.dispose();
      },
    };
  }

  global.MVStudioAutumnLeaves = {apply};
})(typeof window !== "undefined" ? window : globalThis);
