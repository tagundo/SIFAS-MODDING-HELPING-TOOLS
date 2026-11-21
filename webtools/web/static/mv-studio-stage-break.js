(function (global) {
  "use strict";

  const f32 = Math.fround;
  const alias = [null, "displayLights", "speedBackCenterStars"];
  const roles = {flash: {count: 1, texture: 2, bias: 2, cap: 4}, Fall: {count: 60, texture: 2, bias: -1, cap: 2},
    light_big: {count: 8, texture: 1, bias: 0, cap: 2}};
  const number = (value, low, high) => Number.isFinite(value) && value >= low && value <= high;
  const vector = (value, n, low, high) => Array.isArray(value) && value.length === n &&
    value.every(item => number(item, low, high));
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;

  function checked(source, title, motion, particles) {
    if (!source || !id(source.trackId) || !id(source.eventId) || !Array.isArray(source.textures) ||
        source.textures.length !== alias.length || !Array.isArray(source.emitters) || source.emitters.length !== 3 ||
        new Set(source.emitters.map(row => row?.name)).size !== 3) return false;
    const mesh = source.mesh;
    if (!mesh || !vector(mesh.position, 3, -100, 100) || !vector(mesh.scale, 3, .01, 20) || mesh.sortBias !== 0 ||
        mesh.lifetime !== f32(.6) || mesh.delay !== 0 || mesh.vertexColors !== null ||
        !Array.isArray(mesh.positions) || mesh.positions.length !== 49 ||
        !mesh.positions.every(row => vector(row, 3, -2, 2)) ||
        !Array.isArray(mesh.uv) || mesh.uv.length !== mesh.positions.length ||
        !mesh.uv.every(row => vector(row, 2, -.00001, 1.00001)) ||
        !Array.isArray(mesh.indices) || mesh.indices.length !== 216 ||
        !mesh.indices.every(index => Number.isInteger(index) && number(index, 0, 48)) ||
        !particles.validNativeColor(mesh.color) || !title.boundedCurve(mesh.atlasCurve, motion.validCurve)) return false;
    return source.emitters.every(row => {
      const spec = row && Object.hasOwn(roles, row.name) && roles[row.name];
      const atlas = row?.atlas;
      return spec && row.count === spec.count && row.texture === spec.texture && row.sortBias === spec.bias &&
        row.maxViewportWidth === spec.cap && vector(row.position, 3, -100, 100) &&
        vector(atlas?.tiles, 2, 1, 4) && atlas.tiles.every(Number.isInteger) &&
        (atlas.row === null || (Number.isInteger(atlas.row) && number(atlas.row, 0, atlas.tiles[1] - 1))) &&
        number(atlas.period, 0, 1) && particles.validNativeColor(row.color) &&
        title.boundedCurve(atlas.frame, motion.validCurve);
    });
  }

  function tileFor(value, tiles) {
    return Math.max(0, Math.min(tiles - 1, Math.floor(f32(value * tiles))));
  }

  function splitTile(atlas, age, start, evaluate) {
    const {tiles: [columns, rows], row, frame, period} = atlas;
    const phase = period > 0 && age > period ? f32(age - f32(Math.floor(age / period) * period)) : age;
    const count = row === null ? columns * rows : columns;
    const value = f32(start + f32(evaluate(frame, phase)));
    // The Sheet module wraps after adding StartFrame, including at exactly 1.
    return tileFor(f32(value - Math.floor(value)), count);
  }

  function breakMesh(T, root, data, texture) {
    const geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(data.positions.flat(), 3));
    geometry.setAttribute("uv", new T.Float32BufferAttribute(data.uv.flat(), 2));
    geometry.setIndex(data.indices);
    const uv = new T.Vector4(), color = new T.Vector4();
    const material = new T.ShaderMaterial({
      name: "Native display fracture mesh", transparent: true, toneMapped: false, side: T.DoubleSide,
      depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneMinusSrcAlphaFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneMinusSrcAlphaFactor,
      stencilWrite: true, stencilRef: 2, stencilFunc: T.EqualStencilFunc, stencilFuncMask: 255, stencilWriteMask: 255,
      stencilFail: T.KeepStencilOp, stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: {uTexture: {value: texture}, uUV: {value: uv}, uColor: {value: color}},
      vertexShader: `
        uniform vec4 uUV;
        varying vec2 vUV;
        void main() {
          vUV = uv * uUV.xy + uUV.zw;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform sampler2D uTexture;
        uniform vec4 uColor;
        varying vec2 vUV;
        void main() { gl_FragColor = texture2D(uTexture, vUV) * uColor; }
      `,
    });
    const mesh = new T.Mesh(geometry, material);
    mesh.name = "Native stage break mesh";
    mesh.position.fromArray(data.position);
    mesh.scale.fromArray(data.scale);
    mesh.renderOrder = 2900;
    mesh.visible = false;
    mesh.updateMatrix();
    mesh.matrixAutoUpdate = false;
    root.add(mesh);
    return {mesh, center: mesh.position, uv, color, index: -4, bias: data.sortBias};
  }

  async function apply(T, root, source, borrowed) {
    const title = global.MVStudioTitle, motion = global.MVStudioStageMotion, particles = global.MVStudioStageParticles;
    const billboards = global.MVStudioDisplayLights?.localBillboards, sim = global.MVStudioBreakSimulation;
    if (!root?.isObject3D || !title || !motion || !particles || !billboards || !sim ||
        !checked(source, title, motion, particles)) return null;
    const streams = source.emitters.map(row => sim.create(row));
    if (streams.some(stream => !stream?.sample) || !sim.meshPhase) return null;
    const textures = [], owned = [], entries = [], ordered = [];
    const eye = new T.Vector3(), scratch = new T.Vector3();
    let breaker, disposed = false, tracks, track;

    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const {mesh} of [...entries, ...(breaker ? [breaker] : [])]) {
        root.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      owned.forEach(texture => texture.dispose());
    }

    try {
      for (let i = 0; i < alias.length; i++) {
        const reference = source.textures[i], key = alias[i];
        const data = key && reference === key ? borrowed?.[key] : reference;
        if (key && reference === key && data?.isTexture) textures.push(data);
        else {
          if (!title.validMipChain(data) || data[0].width !== 512) throw new Error("Invalid native fracture atlas.");
          const texture = await title.loadTexture(T, new T.TextureLoader(), data);
          owned.push(texture);
          textures.push(texture);
        }
      }
      breaker = breakMesh(T, root, source.mesh, textures[0]);
      source.emitters.forEach((row, index) => {
        const viewAligned = row.name === "Fall", [columns, rows] = row.atlas.tiles;
        const packet = billboards(T, {texture: textures[row.texture], rotation: new T.Quaternion(),
          capacity: row.count, maxViewportWidth: row.maxViewportWidth, atlas: [1/columns, 1/rows, 0, (row.atlas.row || 0)/rows],
          name: "Native display break particles", viewAligned, columns, additive: row.name === "flash", rolling: true});
        packet.mesh.name = `Native stage break ${row.name}`;
        const center = new T.Vector3().fromArray(row.position);
        // The native bounds for the light renderer cover its stepped Z sweep.
        if (row.name === "light_big") center.add(scratch.set(0, -.45753002166748047, 8.875));
        entries.push({...packet, row, center, stream: streams[index], index: index - 3, bias: row.sortBias,
          viewAligned, bounds: new T.Box3(), sprites: Array.from({length: row.count}, () => ({position: new T.Vector3()})), live: []});
        root.add(packet.mesh);
      });
    } catch {
      dispose();
      return null;
    }

    function sampleMesh(elapsed, fps) {
      const {mesh, uv, color} = breaker, data = source.mesh;
      const age = elapsed === null ? null : sim.meshPhase(elapsed, fps, data.lifetime, data.delay);
      mesh.visible = age !== null;
      if (age === null) return;
      const cell = tileFor(f32(motion.evaluate(data.atlasCurve, age)), 8);
      uv.set(.5, .25, (cell % 2) / 2, Math.floor(cell / 2) / 4);
      color.fromArray(particles.nativeColorAtTime(data.color, age));
    }

    function sampleEmitter(entry, elapsed, fps) {
      const {mesh, row, stream, bounds, center, viewAligned, sprites, live} = entry;
      bounds.makeEmpty();
      live.length = 0;
      if (elapsed !== null) stream.sample(elapsed, fps, (px, py, pz, width, height, roll, age, offset, slot) => {
        if (viewAligned) bounds.expandByPoint(scratch.set(px, py, pz));
        if (live.length >= row.count || width <= 0 || height <= 0) return;
        const color = particles.nativeColorAtTime(row.color, age);
        if (color[3] <= 0) return;
        const sprite = sprites[live.length];
        sprite.position.set(px, py, pz);
        sprite.width = width;
        sprite.height = height;
        sprite.roll = roll;
        sprite.tile = splitTile(row.atlas, age, offset, motion.evaluate);
        sprite.color = color;
        sprite.slot = slot;
        live.push(sprite);
      });
      if (viewAligned && !bounds.isEmpty()) bounds.getCenter(center);
      mesh.visible = live.length > 0;
      mesh.geometry.instanceCount = live.length;
    }

    function distance(point, camera, squared) {
      if (camera.isOrthographicCamera) return -scratch.copy(point).applyMatrix4(camera.matrixWorldInverse).z;
      return squared ? eye.distanceToSquared(point) : eye.distanceTo(point);
    }

    function upload(entry, camera) {
      const {row, live, centers, sizes, rolls, colors} = entry;
      if (row.count > 1) {
        for (const sprite of live) sprite.distance = f32(distance(sprite.position, camera, true));
        live.sort((a, b) => b.distance - a.distance || a.slot - b.slot);
      }
      live.forEach(({position, width, height, roll, tile, color}, index) => {
        centers.setXYZW(index, position.x, position.y, position.z, tile);
        sizes.setXY(index, width, height);
        rolls.setX(index, roll);
        colors.setXYZW(index, ...color.map(value => Math.round(value * 255)));
      });
      for (const attribute of [centers, sizes, rolls, colors]) {
        attribute.updateRange.count = live.length * attribute.itemSize;
        attribute.needsUpdate = true;
      }
    }

    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          const matches = (tracks || []).filter(row => row.id === source.trackId && row.nativeClass === "CustomControlTrack");
          track = matches.length === 1 ? matches[0] : null;
        }
        const event = !track?.muted && track?.events.find(row => row.id === source.eventId);
        const active = project?.quality?.values?.stage_display !== false && title.neutralClip(event) &&
          time >= event.start && time < event.start + event.duration;
        const elapsed = active ? time - event.start : null;
        const fps = project?.quality?.values?.frame_rate_60fps === true ? 60 : 30;
        sampleMesh(elapsed, fps);
        for (const entry of entries) sampleEmitter(entry, elapsed, fps);
      },
      sort(camera, peers) {
        if (disposed) return false;
        ordered.length = 0;
        if (breaker.mesh.visible) ordered.push(breaker);
        for (const entry of entries) if (entry.mesh.visible) ordered.push(entry);
        if (!ordered.length) return false;
        camera.updateMatrixWorld();
        eye.setFromMatrixPosition(camera.matrixWorld);
        for (const entry of ordered) if (entry.live) upload(entry, camera);
        if (peers) ordered.push(...peers());
        // The .08 fracture and .09 display run together. Sort the entire
        // native queue cohort since alpha-over surfaces sit between add passes.
        for (const entry of ordered) entry.distance = f32(distance(entry.center, camera, false) + entry.bias);
        ordered.sort((a, b) => b.distance - a.distance || a.index - b.index);
        ordered.forEach(({mesh}, index) => { mesh.renderOrder = 2900 + index * .01; });
        return true;
      },
      dispose,
    };
  }

  global.MVStudioStageBreak = {apply};
})(typeof window !== "undefined" ? window : globalThis);
