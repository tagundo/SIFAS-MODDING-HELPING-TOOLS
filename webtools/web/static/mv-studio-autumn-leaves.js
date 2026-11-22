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
  const defaultCapacity = 200;
  const atlasColumns = new Map([["03", 0], ["04", .5], ["06", .25], ["07", .25]]);
  const transitionColumns = new Map([["green-burst", 0], ["yellow-burst", .5], ["red-in", .25], ["red-burst", .25]]);

  function checkedMaterial(material, blend) {
    return material?.queue === 3010 && material.cull === 0 && material.blend === blend &&
      material.premultiply === false && finiteVector(material.tint, 4) && material.tint.every(value => value === 1);
  }

  function checkedPose(row, column) {
    return finiteVector(row.position, 3) && finiteVector(row.rotation, 4) && finiteVector(row.uv, 4) &&
      row.uv[0] === .25 && row.uv[1] === .25 && row.uv[2] === column && row.uv[3] === .25;
  }

  function checkedCue(cue) {
    if (!id(cue?.trackId) || !id(cue.eventId)) return false;
    if (cue.profile !== "05") return atlasColumns.has(cue.profile) && checkedPose(cue, atlasColumns.get(cue.profile));
    const roles = Array.isArray(cue.emitters) && cue.emitters.map(row => row?.role);
    return roles && roles.length >= 1 && roles.length <= 4 && roles.every(role => transitionColumns.has(role)) &&
      new Set(roles).size === roles.length;
  }

  function validFlower(geometry) {
    return Array.isArray(geometry?.positions) && geometry.positions.length === 22 && geometry.positions.every(row => finiteVector(row, 3)) &&
      Array.isArray(geometry.uv) && geometry.uv.length === 22 && geometry.uv.every(row => finiteVector(row, 2)) &&
      Array.isArray(geometry.indices) && geometry.indices.length === 60 &&
      geometry.indices.every(index => Number.isInteger(index) && index >= 0 && index < 22);
  }

  function checked(source, title) {
    const {geometry, material, cues} = source || {};
    return source?.schema === 1 && title.validMipChain(source.texture) && source.texture[0].width === 256 &&
      validFlower(geometry) && checkedMaterial(material, "alpha") &&
      Array.isArray(cues) && cues.length >= 1 && cues.length <= 10 && cues.every(checkedCue) &&
      new Set(cues.map(cue => JSON.stringify([cue.trackId, cue.eventId]))).size === cues.length &&
      cues.filter(cue => cue.profile === "03").length <= 1 && cues.filter(cue => cue.profile === "04").length <= 1 &&
      cues.filter(cue => cue.profile === "05").length <= 1 &&
      cues.filter(cue => cue.profile === "06").length <= 4 && cues.filter(cue => cue.profile === "07").length <= 3;
  }

  function meshBatch(T, source, texture, pose, name, surface, capacity) {
    const geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(source.geometry.positions.flat(), 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute(source.geometry.uv.flat(), 2));
    geometry.setIndex(source.geometry.indices);
    const colors = new T.InstancedBufferAttribute(new Uint8Array(capacity * 4), 4, true).setUsage(T.DynamicDrawUsage);
    geometry.setAttribute("particleColor", colors);
    const destination = surface.blend === "add" ? T.OneFactor : T.OneMinusSrcAlphaFactor;
    const material = new T.ShaderMaterial({
      vertexShader, fragmentShader, transparent: true, toneMapped: false, side: T.DoubleSide,
      depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: destination,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: destination,
      stencilWrite: true, stencilRef: 2,
      stencilFunc: surface.stencil === "equal" ? T.EqualStencilFunc : T.AlwaysStencilFunc,
      stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
      stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: {uTexture: {value: texture}, uAtlas: {value: new T.Vector4().fromArray(pose.uv)},
        uTint: {value: new T.Vector4().fromArray(surface.tint)}},
    });
    const mesh = new T.InstancedMesh(geometry, material, capacity);
    mesh.name = name;
    mesh.instanceMatrix.setUsage(T.DynamicDrawUsage);
    mesh.renderOrder = surface.queue;
    mesh.frustumCulled = false;
    mesh.matrixAutoUpdate = false;
    mesh.visible = false;
    mesh.count = 0;
    return {mesh, colors};
  }

  async function apply(T, root, source, sharedAtlas) {
    const title = global.MVStudioTitle, simulation = global.MVStudioAutumnLeavesSimulation;
    const floorSimulation = global.MVStudioAutumnFloorSimulation;
    const burstSimulation = global.MVStudioAutumnBurstSimulation;
    const redBurstSimulation = global.MVStudioAutumnRedBurstSimulation;
    const particles = global.MVStudioStageParticles;
    if (!root?.isObject3D || !particles || !title || !checked(source, title)) return null;
    let redCue = 0, floorCue = 0;
    const candidates = source.cues.flatMap(cue => {
      if (cue.profile === "05") {
        return cue.emitters.filter(row => checkedPose(row, transitionColumns.get(row.role)) && checkedMaterial(row.material, "alpha"))
          .map(row => {
            const engine = row.role === "red-in" ? simulation :
              row.role === "red-burst" ? redBurstSimulation : burstSimulation;
            return {cue, pose: row, stream: engine?.create({...source, ...cue, ...row}), anisotropic: false,
              surface: row.material, capacity: row.role === "red-burst" ? 300 : defaultCapacity,
              name: `Native Aion transition leaves ${row.role}`};
          });
      }
      if (cue.profile === "07") {
        const order = ++floorCue;
        if (!floorSimulation || !Array.isArray(cue.emitters) || cue.emitters.length !== 2 ||
            !["alpha", "add"].every(role => checkedMaterial(cue.emitters.find(row => row?.role === role)?.material, role))) return [];
        return cue.emitters.map(emitter => ({cue, pose: cue, stream: floorSimulation.create({...source, ...cue, ...emitter}),
          anisotropic: true, surface: emitter.material, capacity: defaultCapacity,
          name: `Native Aion floor leaves ${emitter.role} ${order}`}));
      }
      // Native PrefabControl has its own clone and clock for every clip,
      // including adjacent clips that reuse the same red-leaf prefab.
      const clip = cue.profile === "06" ? `06 ${++redCue}` : cue.profile;
      return [{cue, pose: cue, stream: simulation?.create({...source, ...cue}), anisotropic: false,
        surface: source.material, capacity: defaultCapacity, name: `Native Aion falling leaves ${clip}`}];
    }).filter(entry => entry.stream);
    if (!candidates.length) return null;
    const borrowed = title.sharedMipTexture(source.texture, sharedAtlas);
    let texture;
    try {
      texture = borrowed || await title.loadTexture(T, new T.TextureLoader(), source.texture);
    } catch {
      return null;
    }
    const entries = candidates.map(({cue, pose, stream, anisotropic, surface, name, capacity}) => {
      const packet = meshBatch(T, source, texture, pose, name, surface, capacity);
      root.add(packet.mesh);
      return {cue, stream, anisotropic, capacity, ...packet, frame: -1, fps: 0,
        emitterRotation: new T.Quaternion().fromArray(pose.rotation), center: new T.Vector3()};
    });
    const center = new T.Vector3(), scale = new T.Vector3(), eye = new T.Vector3();
    const matrix = new T.Matrix4(), spin = new T.Euler(), orientation = new T.Quaternion();
    const bounds = new T.Box3();
    let tracks, disposed = false;

    function update(entry, frame, fps) {
      const {mesh, stream, colors, emitterRotation, anisotropic, capacity} = entry;
      let count = 0;
      bounds.makeEmpty();
      function write(x, y, z, sx, sy, sz, rx, ry, rz, r, g, b, a) {
        center.set(x, y, z);
        bounds.expandByPoint(center);
        if (!(sx > 0 && sy > 0 && sz > 0) || !a || count >= capacity) return;
        // The native Mesh renderer rotates Z, X, then Y before applying the
        // emitter basis. Reflect the native angles along the imported mesh X.
        orientation.setFromEuler(spin.set(rx, -ry, -rz, "YXZ")).premultiply(emitterRotation);
        mesh.setMatrixAt(count, matrix.compose(center, orientation, scale.set(sx, sy, sz)));
        colors.setXYZW(count++, r, g, b, a);
      }
      if (anisotropic) stream.sample(frame / fps, fps, write);
      else stream.sample(frame / fps, fps, (x, y, z, size, rx, ry, rz, r, g, b, a) => {
        write(x, y, z, size, size, size, rx, ry, rz, r, g, b, a);
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

  global.MVStudioAutumnLeaves = {apply, meshBatch, validFlower};
})(typeof window !== "undefined" ? window : globalThis);
