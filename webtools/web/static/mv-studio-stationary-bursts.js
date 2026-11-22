(function (global) {
  "use strict";

  const bindingPrefix = "/EntryPoint/Live/Stages/MainStage/Effect/";
  const queue = 2900;
  const validPath = value => Number.isInteger(value) && value >= 0 && value <= 0xffffffff;
  const within = (value, low, high) => Number.isFinite(value) && value >= low && value <= high;
  const vector = (row, length) => Array.isArray(row) && row.length === length && row.every(Number.isFinite);
  const vertexShader = `
    uniform vec4 uTextureST;
    varying highp vec2 vTexture;
    void main() {
      vTexture = uv * uTextureST.xy + uTextureST.zw;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }`;
  const fragmentShader = `
    uniform mediump sampler2D uTexture;
    uniform mediump vec4 uTint;
    uniform mediump vec4 uParticleColor;
    varying highp vec2 vTexture;
    void main() {
      mediump vec4 texel = texture2D(uTexture, vTexture);
      gl_FragColor = (texel * uTint) * uParticleColor;
    }`;
  const billboardFragmentShader = `
    uniform mediump sampler2D uTexture;
    uniform mediump vec4 uTint;
    varying vec2 vParticleUV;
    varying vec4 vParticleColor;
    void main() {
      mediump vec4 color = texture2D(uTexture, vParticleUV) * uTint;
      mediump vec4 particle = vParticleColor;
      gl_FragColor = color * particle;
    }`;

  function validMesh(shape) {
    return Array.isArray(shape?.positions) && shape.positions.length >= 3 && shape.positions.length <= 512 &&
      shape.positions.every(row => vector(row, 3)) && Array.isArray(shape.uv) &&
      shape.uv.length === shape.positions.length && shape.uv.every(row => vector(row, 2)) &&
      Array.isArray(shape.indices) && shape.indices.length >= 3 && shape.indices.length <= 3072 &&
      shape.indices.length % 3 === 0 &&
      shape.indices.every(i => Number.isInteger(i) && i >= 0 && i < shape.positions.length);
  }

  function createStream(row, simulation) {
    const {material} = row;
    if (!validPath(row.path) || !row.path || !validPath(row.activationPath) ||
        !Number.isSafeInteger(row.texture) || row.texture < 0 ||
        !vector(row.size, 3) || !row.size.every(size => within(size, .001, 100)) ||
        !vector(row.uv, 4) || !row.uv.every(value => within(value, -64, 64)) ||
        !vector(material?.tint, 4) || material.queue !== queue || material.depthTest !== true ||
        material.stencilRef !== 2 || material.alphaBlend !== true || ![0, 2].includes(material.cull)) return null;
    if (row.mode === "mesh" ? !validMesh(row.geometry) : row.mode !== "billboard" || row.geometry !== undefined ||
        !within(row.maxViewportWidth, .001, 8)) return null;
    if (row.flipX !== undefined && (row.flipX !== true || row.mode !== "billboard" || material.cull !== 0)) return null;
    const keys = row.sizeKeys === undefined ? [[0, 1, 0, 0], [1, 1, 0, 0]] : row.sizeKeys;
    if (!Array.isArray(keys) || keys.length < 2 || keys.length > 16 ||
        !keys.every(key => Array.isArray(key) && key.length === 4)) return null;
    const last = keys.at(-1);
    if (last[0] !== 1 && keys.length === 16) return null;
    // This native subset holds its last authored size key. The shared burst
    // solver takes a complete normalized curve and a scalar size multiplier.
    const sizeKeys = last[0] === 1 ? keys : [...keys, [1, last[1], null, 0]];
    return simulation.create({
      kind: "stationaryBurst", duration: row.duration, delay: row.delay,
      burst: {count: 1, time: 0, cycles: 1, period: .01}, maxParticles: 1,
      lifetime: [row.lifetime, row.lifetime], size: [1, 1], startColor: row.startColor,
      sizeKeys, sizeMultiplier: row.sizeMultiplier ?? 1, colorOverLife: row.colorOverLife, tiles: [1, 1],
    }, 0);
  }

  function makeDraw(T, row, texture, billboards) {
    const side = row.material.cull === 2 ? T.FrontSide : T.DoubleSide;
    const name = `Native stationary stage burst ${row.path}`;
    if (row.mode === "billboard") {
      const batch = billboards(T, {texture, rotation: new T.Quaternion(), capacity: 1,
        maxViewportWidth: row.maxViewportWidth, atlas: row.uv, name, side, tint: row.material.tint});
      batch.mesh.name = name;
      batch.mesh.material.fragmentShader = billboardFragmentShader;
      if (row.flipX) {
        const uv = batch.mesh.geometry.getAttribute("uv");
        for (let i = 0; i < uv.count; i++) uv.setX(i, 1 - uv.getX(i));
      }
      batch.centers.setXYZW(0, 0, 0, 0, 0);
      batch.centers.needsUpdate = true;
      return batch;
    }
    const shape = row.geometry, geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(shape.positions.flat(), 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute(shape.uv.flat(), 2));
    geometry.setIndex(shape.indices);
    const material = new T.ShaderMaterial({
      name, vertexShader, fragmentShader, transparent: true, toneMapped: false, side,
      depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false, blending: T.CustomBlending,
      blendSrc: T.SrcAlphaFactor, blendDst: T.OneMinusSrcAlphaFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneMinusSrcAlphaFactor,
      stencilWrite: true, stencilFunc: T.EqualStencilFunc, stencilRef: 2,
      stencilFuncMask: 255, stencilWriteMask: 255,
      stencilFail: T.KeepStencilOp, stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: {uTexture: {value: texture}, uTint: {value: new T.Vector4().fromArray(row.material.tint)},
        uTextureST: {value: new T.Vector4().fromArray(row.uv)}, uParticleColor: {value: new T.Vector4()}},
    });
    const mesh = new T.Mesh(geometry, material);
    mesh.name = name;
    mesh.renderOrder = queue;
    mesh.matrixAutoUpdate = false;
    mesh.frustumCulled = false;
    mesh.visible = false;
    return {mesh};
  }

  async function apply(T, root, parser, options = {}) {
    const source = root?.userData?.mvStageStationaryBursts;
    const {residentChain, residentActivation} = global.MVStudioStageLaserCores || {};
    const simulation = global.MVStudioStageBurstSimulation, billboards = global.MVStudioDisplayLights?.localBillboards;
    const createSampler = global.MVStudioStageMaterial?.createTextureSampler;
    if (!root?.isObject3D || !Array.isArray(source) || !source.length || source.length > 32 ||
        !parser?.getDependency || !residentChain || !residentActivation || !simulation?.create ||
        !createSampler || !billboards) return null;

    const {active = () => true} = options, groups = new Map(), nodes = new Map();
    const sampler = createSampler(T, parser, options), attached = [], visible = [];
    root.traverse(node => {
      sampler.retainOriginalMaterial(node.material);
      const tag = node.userData?.mvStageNode;
      if (typeof tag?.binding !== "string" || !validPath(tag.path)) return;
      if (!nodes.has(tag.binding)) nodes.set(tag.binding, new Map());
      const paths = nodes.get(tag.binding);
      paths.set(tag.path, paths.has(tag.path) ? null : node);
    });
    for (const row of source) {
      if (typeof row?.binding !== "string" || !row.binding.startsWith(bindingPrefix)) continue;
      if (!groups.has(row.binding)) groups.set(row.binding, []);
      groups.get(row.binding).push(row);
    }

    let disposed = false;
    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const {entries} of attached) for (const {draw} of entries) {
        if (!draw) continue;
        const {mesh} = draw;
        root.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      sampler.dispose();
      visible.length = 0;
    }

    // Reserve every base before requesting any additional mip through the
    // shared parser. A base also used in a regular stage material is borrowed.
    const pending = [];
    for (const [binding, rows] of groups) {
      const paths = nodes.get(binding);
      if (!paths?.get(0) || new Set(rows.map(row => row.path)).size !== rows.length) continue;
      const entries = rows.map(row => {
        const stream = createStream(row, simulation), carrier = paths.get(row.path);
        const chain = residentChain(root, carrier, paths.get(0), binding);
        if (!stream || !chain?.some(({path, active}) => path === row.activationPath && !active)) return null;
        return {row, stream, carrier, chain};
      });
      if (entries.some(entry => !entry)) continue;
      for (const {row} of entries) sampler.reserveBase(row.texture);
      pending.push({binding, entries});
    }
    try {
      for (const {binding, entries} of pending) {
        if (!active()) break;
        for (const entry of entries) {
          const {row} = entry;
          const texture = await sampler.sampledNativeTexture(row.texture, row.mainSampler);
          if (!active() || !texture || row.mainSampler &&
              texture.mipmaps.length !== (row.mainSampler.mipmaps?.length ? row.mainSampler.mipmaps.length + 1 : 0)) break;
          entry.texture = texture;
        }
        if (!active()) break;
        if (!entries.every(entry => entry.texture)) continue;
        const schedule = residentActivation(binding, entries.map(({chain}) => chain),
          entries.map(({row}) => row.activationPath));
        if (!schedule) continue;
        attached.push({entries, schedule});
        for (const entry of entries) {
          entry.draw = makeDraw(T, entry.row, entry.texture, billboards);
          root.add(entry.draw.mesh);
        }
      }
    } catch (error) {
      dispose();
      throw error;
    }
    if (!attached.length || !active()) {
      dispose();
      return null;
    }

    const rotation = new T.Quaternion(), matrix = new T.Matrix4(), local = new T.Matrix4();
    const eye = new T.Vector3(), center = new T.Vector3();
    return {
      update(seconds, project, stageMotion) {
        if (disposed) return;
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        const frame = Math.floor(seconds * fps + 1e-9);
        const enabled = quality?.stage_display !== false && Number.isSafeInteger(frame) && frame >= 0 && frame <= 3600 * fps;
        visible.length = 0;
        for (const {entries, schedule} of attached) {
          const playback = enabled ? schedule(project, fps, stageMotion) : null;
          for (const [index, entry] of entries.entries()) {
            const {row, chain, carrier, stream, draw} = entry, {mesh, sizes, colors} = draw;
            mesh.visible = false;
            if (sizes) mesh.geometry.instanceCount = 0;
            const rise = playback?.activeSince(frame, index);
            if (rise == null) continue;
            const elapsed = (frame - rise + 1) / fps;
            stream.sample(elapsed, fps, (_x, _y, _z, size, r, g, b, a) => {
              const scale = carrier.scale;
              if (!(size > 0) || !a || !(scale.x > 0 && scale.y > 0 && scale.z > 0)) return;
              // Local scaling uses the emitter's own dimensions. Ancestor TRS
              // still positions the center and contributes its source rotation.
              matrix.identity();
              rotation.identity();
              for (const {node} of chain) {
                matrix.multiply(local.compose(node.position, node.quaternion, node.scale));
                rotation.multiply(node.quaternion);
              }
              mesh.position.setFromMatrixPosition(matrix);
              const width = Math.fround(size * row.size[0]) * scale.x;
              const height = Math.fround(size * row.size[1]) * scale.y;
              if (sizes) {
                const uniforms = mesh.material.uniforms;
                uniforms.uAxisX.value.set(1, 0, 0).applyQuaternion(rotation);
                uniforms.uAxisY.value.set(0, 1, 0).applyQuaternion(rotation);
                sizes.setXY(0, width, height);
                colors.setXYZW(0, r, g, b, a);
                sizes.updateRange.count = 2;
                colors.updateRange.count = 4;
                sizes.needsUpdate = colors.needsUpdate = true;
                mesh.geometry.instanceCount = 1;
              } else {
                mesh.quaternion.copy(rotation);
                mesh.scale.set(width, height, Math.fround(size * row.size[2]) * scale.z);
                mesh.material.uniforms.uParticleColor.value.set(r / 255, g / 255, b / 255, a / 255);
              }
              mesh.updateMatrix();
              mesh.visible = true;
              mesh.renderOrder = queue;
              visible.push({mesh, order: visible.length, distance: 0});
            });
          }
        }
      },
      sort(camera) {
        if (visible.length < 2) return;
        camera.updateWorldMatrix(true, false);
        eye.setFromMatrixPosition(camera.matrixWorld);
        for (const entry of visible) {
          entry.mesh.updateWorldMatrix(true, false);
          center.setFromMatrixPosition(entry.mesh.matrixWorld);
          entry.distance = Math.fround(camera.isOrthographicCamera ?
            -center.applyMatrix4(camera.matrixWorldInverse).z : eye.distanceToSquared(center));
        }
        visible.sort((a, b) => b.distance - a.distance || a.order - b.order);
        visible.forEach(({mesh}, i) => { mesh.renderOrder = queue + i / visible.length; });
      },
      dispose,
    };
  }

  global.MVStudioStationaryBursts = {apply};
})(typeof window !== "undefined" ? window : globalThis);
