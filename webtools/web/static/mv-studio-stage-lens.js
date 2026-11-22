(function (global) {
  "use strict";

  const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  const matches = (value, expected) => vector(value, expected.length) && value.every((n, i) => n === expected[i]);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const seed32 = value => Number.isInteger(value) && value >= -0x80000000 && value <= 0xffffffff;
  function validAtlas(levels, title) {
    const {width, height} = levels?.[0] || {};
    return Array.isArray(levels) && title.validTexture(levels[0]) &&
      levels.length === Math.log2(Math.max(width, height)) + 1 &&
      levels.every((level, index) => level?.width === Math.max(1, width >> index) &&
        level.height === Math.max(1, height >> index) && title.validTexture(level));
  }

  function checked(source, title) {
    const {textures, material, tiles, emitters, cues} = source;
    if (![1, 2].includes(source.schema) || !Array.isArray(textures) || !textures.length || textures.length > 16 ||
        !textures.every(levels => validAtlas(levels, title)) || material?.queue !== 3010 || material.cull !== 0 ||
        material.blend !== "add" || material.stencil !== "always" || material.stencilRef !== 2 ||
        material.premultiply !== false || material.saturate !== false || !matches(material.tint, [1, 1, 1, 1]) ||
        !matches(tiles, [2, 1]) || source.maxViewportWidth !== .5 || source.sortMode !== 0 ||
        !Array.isArray(emitters) || !emitters.length || emitters.length > 16 ||
        !Array.isArray(cues) || !cues.length || cues.length > 64) return false;
    const emittersById = new Map(emitters.map(emitter => [emitter?.id, emitter]));
    return emittersById.size === emitters.length &&
      emitters.every(row => {
        if (!id(row?.id) || !Number.isInteger(row.texture) || !textures[row.texture] ||
            !vector(row.position, 3) || !vector(row.rotation, 4) || Math.abs(Math.hypot(...row.rotation) - 1) >= 1e-5 ||
            !matches(row.scale, [1, 1, 1]) || typeof row.autoSeed !== "boolean" || !seed32(row.seed) ||
            !Number.isFinite(row.rate) || row.rate <= 0) return false;
        if (row.kind === "boxDust") {
          return source.schema === 2 && matches(row.tiles, [1, 1]) && row.maxViewportWidth === 1 &&
            Number.isInteger(row.maxParticles) && row.maxParticles > 0 && row.maxParticles <= 1000;
        }
        return row.kind === undefined && vector(row.sortCenter, 3) && row.rate <= 30 && row.lifetime === 5;
      }) &&
      cues.every(row => id(row?.trackId) && id(row.eventId) && emittersById.has(row.emitterId) &&
        (row.quality === "stage_control" || row.quality === "stage_display")) &&
      new Set(cues.map(row => JSON.stringify([row.trackId, row.eventId]))).size === cues.length;
  }

  async function apply(T, root, source) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles;
    const billboards = global.MVStudioDisplayLights?.localBillboards;
    if (!source || !root?.isObject3D || !title || !particles || !billboards || !checked(source, title)) return null;

    const point = new T.Vector3(), bounds = new T.Box3(), entries = [], visible = [], textures = new Map();
    const emitters = new Map(source.emitters.map(row => [row.id, row]));
    let disposed = false, tracks;
    function dispose() {
      if (disposed) return;
      disposed = true;
      visible.length = 0;
      for (const {mesh} of entries) {
        root.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      for (const texture of textures.values()) texture.dispose();
    }

    try {
      const loader = new T.TextureLoader();
      for (const [index, cue] of source.cues.entries()) {
        const emitter = emitters.get(cue.emitterId);
        const dust = emitter.kind === "boxDust";
        const simulation = dust ? global.MVStudioStageDustSimulation : global.MVStudioStageLensSimulation;
        if (!simulation?.create) continue;
        if (!textures.has(emitter.texture)) {
          const texture = await title.loadTexture(T, loader, source.textures[emitter.texture]);
          textures.set(emitter.texture, texture);
        }
        const texture = textures.get(emitter.texture);
        const basis = new T.Quaternion().fromArray(emitter.rotation);
        const capacity = dust ? emitter.maxParticles : Math.ceil(emitter.rate * emitter.lifetime) + 2;
        const name = `Native stage ${dust ? "dust" : "lens flare"} ${index + 1}`;
        const [columns, rows] = emitter.tiles || source.tiles;
        const batch = billboards(T, {texture, rotation: basis, capacity,
          maxViewportWidth: emitter.maxViewportWidth ?? source.maxViewportWidth,
          atlas: [1 / columns, 1 / rows, 0, 0], columns, name, additive: true, viewAligned: true,
          nativeViewAxes: true, stencilEqual: false});
        batch.mesh.name = name;
        batch.mesh.renderOrder = source.material.queue;
        root.add(batch.mesh);
        const origin = new T.Vector3().fromArray(emitter.position);
        const center = dust ? new T.Vector3() : new T.Vector3().fromArray(emitter.sortCenter);
        entries.push({...batch, cue, emitter, basis, origin, center, simulation, dust, frame: -1, fps: 0});
      }
    } catch {
      dispose();
      return null;
    }

    if (!entries.length) return null;

    function writeBatch(entry, frame, fps) {
      const {mesh, stream, centers, sizes, colors, basis, origin, dust} = entry;
      let count = 0;
      if (dust) bounds.makeEmpty();
      stream.sample(frame / fps, fps, (x, y, z, size, r, g, b, a, tile = 0) => {
        point.set(x, y, z);
        // The dust renderer uses its live bounds, including transparent particles.
        if (dust) bounds.expandByPoint(point);
        if (!(size > 0) || !a || count === centers.count) return;
        point.applyQuaternion(basis).add(origin);
        centers.setXYZW(count, point.x, point.y, point.z, tile);
        sizes.setXY(count, size, size);
        colors.setXYZW(count++, r, g, b, a);
      });
      if (dust) bounds.getCenter(entry.center).applyQuaternion(basis).add(origin);
      mesh.geometry.instanceCount = count;
      if (!count) return;
      for (const attribute of [centers, sizes, colors]) {
        attribute.updateRange.count = count * attribute.itemSize;
        attribute.needsUpdate = true;
      }
    }

    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          for (const entry of entries) {
            const {cue} = entry;
            const matches = tracks?.filter(row => row.id === cue.trackId && row.nativeClass === "CustomControlTrack");
            entry.track = matches?.length === 1 ? matches[0] : null;
            const events = entry.track?.events?.filter(row => row.id === cue.eventId);
            entry.event = events?.length === 1 ? events[0] : null;
          }
        }
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        visible.length = 0;
        for (const entry of entries) {
          const {mesh, event, track, emitter, cue, simulation, dust} = entry;
          const timing = quality?.[cue.quality] !== false && !track?.muted &&
            particles.activeControlFrame(event, time, fps, dust ? 120 : 60);
          mesh.visible = false;
          if (!timing) continue;
          const fields = event.values;
          // Select one preview realization for an auto-seeded cue, so
          // seeking or revisiting it does not change its particle layout.
          let seed = emitter.seed;
          if (fields.overwriteRandomSeed) seed = fields.particleRandomSeed;
          else if (emitter.autoSeed) seed = entry.autoSeed ??= particles.autoSeed();
          if (!seed32(seed)) continue;
          if (entry.seed !== (seed >>> 0)) {
            entry.seed = seed >>> 0;
            entry.stream = simulation.create(emitter, entry.seed);
            entry.frame = -1;
          }
          if (!entry.stream) continue;
          const {frame, offset: [x, y, z]} = timing;
          if (mesh.position.x !== x || mesh.position.y !== y || mesh.position.z !== z) {
            mesh.position.set(x, y, z);
            mesh.updateMatrix();
          }
          if (entry.frame !== frame || entry.fps !== fps) {
            writeBatch(entry, frame, fps);
            entry.frame = frame;
            entry.fps = fps;
          }
          mesh.visible = mesh.geometry.instanceCount > 0;
          if (mesh.visible) visible.push(entry);
        }
      },
      sortEntries() { return visible; },
      dispose,
    };
  }

  global.MVStudioStageLens = {apply};
})(typeof window !== "undefined" ? window : globalThis);
