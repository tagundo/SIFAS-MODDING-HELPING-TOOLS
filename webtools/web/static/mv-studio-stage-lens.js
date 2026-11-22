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

  const emitterLayer = row => row.kind === "stationaryBurst" ? row.layer : 1;

  function cueEmitterIds(cue, schema) {
    if (cue?.emitterIds !== undefined) {
      const {emitterIds} = cue;
      return schema === 4 && cue.emitterId === undefined && Array.isArray(emitterIds) && emitterIds.length >= 2 &&
        emitterIds.length <= 8 && emitterIds.every(id) && new Set(emitterIds).size === emitterIds.length
        ? emitterIds : null;
    }
    return id(cue?.emitterId) ? [cue.emitterId] : null;
  }

  function checked(source, title) {
    const {textures, material, tiles, emitters, cues} = source;
    if (![1, 2, 3, 4].includes(source.schema) || !Array.isArray(textures) || !textures.length || textures.length > 16 ||
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
            (row.kind !== "stationaryBurst" && (!Number.isFinite(row.rate) || row.rate <= 0))) return false;
        if (row.kind === "boxDust") {
          const plain = matches(row.tiles, [1, 1]) && row.maxViewportWidth === 1;
          const animated = source.schema >= 3 && matches(row.tiles, [2, 2]) && [1, 2].includes(row.maxViewportWidth);
          return source.schema >= 2 && (plain || animated) &&
            Number.isInteger(row.maxParticles) && row.maxParticles > 0 && row.maxParticles <= 1000;
        }
        if (row.kind === "stationaryBurst") {
          return source.schema === 4 && ((row.layer === 1 && row.blend === "add") ||
            (row.layer === 20 && row.blend === "alpha")) && vector(row.sortCenter, 3) &&
            (matches(row.tiles, [1, 1]) || matches(row.tiles, [4, 4])) &&
            Number.isFinite(row.maxViewportWidth) && row.maxViewportWidth > 0 && row.maxViewportWidth <= 8 &&
            Number.isInteger(row.maxParticles) && row.maxParticles > 0 && row.maxParticles <= 1000;
        }
        return row.kind === undefined && vector(row.sortCenter, 3) && row.rate <= 30 && row.lifetime === 5;
      }) &&
      cues.every(row => {
        if (!id(row?.trackId) || !id(row.eventId) || !["stage_control", "stage_display"].includes(row.quality)) return false;
        const ids = cueEmitterIds(row, source.schema);
        if (!ids?.every(key => emittersById.has(key))) return false;
        const layer = emitterLayer(emittersById.get(ids[0]));
        return ids.every(key => emitterLayer(emittersById.get(key)) === layer);
      }) &&
      new Set(cues.map(row => JSON.stringify([row.trackId, row.eventId]))).size === cues.length &&
      cues.reduce((count, row) => count + cueEmitterIds(row, source.schema).length, 0) <= 64;
  }

  async function apply(T, root, source) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles;
    const billboards = global.MVStudioDisplayLights?.localBillboards;
    if (!source || !root?.isObject3D || !title || !particles || !billboards || !checked(source, title)) return null;

    const point = new T.Vector3(), bounds = new T.Box3(), groups = [], textures = new Map();
    const world = [], overlay = [];
    const emitters = new Map(source.emitters.map(row => [row.id, row]));
    let disposed = false, tracks;
    function dispose() {
      if (disposed) return;
      disposed = true;
      world.length = overlay.length = 0;
      for (const group of groups) {
        for (const {mesh} of group.entries) {
          root.remove(mesh);
          mesh.geometry.dispose();
          mesh.material.dispose();
        }
      }
      for (const texture of textures.values()) texture.dispose();
    }

    try {
      const loader = new T.TextureLoader();
      for (const [index, cue] of source.cues.entries()) {
        const members = cueEmitterIds(cue, source.schema).map(key => {
          const emitter = emitters.get(key);
          const dust = emitter.kind === "boxDust", burst = emitter.kind === "stationaryBurst";
          const simulation = dust ? global.MVStudioStageDustSimulation : burst ?
            global.MVStudioStageBurstSimulation : global.MVStudioStageLensSimulation;
          return {emitter, simulation, dust, burst};
        });
        if (members.some(({simulation}) => !simulation?.create)) continue;
        const layer = emitterLayer(members[0].emitter);
        const group = {cue, layer, entries: [], maxDuration: members.every(({dust}) => dust) ? 120 : 60};
        groups.push(group);
        for (const [memberIndex, {emitter, simulation, dust, burst}] of members.entries()) {
          if (!textures.has(emitter.texture)) {
            const texture = await title.loadTexture(T, loader, source.textures[emitter.texture]);
            textures.set(emitter.texture, texture);
          }
          const texture = textures.get(emitter.texture);
          const basis = new T.Quaternion().fromArray(emitter.rotation);
          const capacity = dust || burst ? emitter.maxParticles : Math.ceil(emitter.rate * emitter.lifetime) + 2;
          const category = dust ? "dust" : burst ? "burst" : "lens flare";
          const suffix = members.length > 1 ? `.${memberIndex + 1}` : "";
          const name = `Native stage ${category} ${index + 1}${suffix}`;
          const [columns, rows] = emitter.tiles || source.tiles;
          const batch = billboards(T, {texture, rotation: basis, capacity,
            maxViewportWidth: emitter.maxViewportWidth ?? source.maxViewportWidth,
            atlas: [1 / columns, 1 / rows, 0, 0], columns, name,
            additive: !burst || emitter.blend === "add", viewAligned: true, nativeViewAxes: true, stencilEqual: false});
          batch.mesh.name = name;
          batch.mesh.renderOrder = source.material.queue;
          if (layer === 20) batch.mesh.layers.set(layer);
          root.add(batch.mesh);
          const origin = new T.Vector3().fromArray(emitter.position);
          const center = dust ? new T.Vector3() : new T.Vector3().fromArray(emitter.sortCenter);
          group.entries.push({...batch, emitter, basis, origin, center, simulation, dust, frame: -1, fps: 0});
        }
      }
    } catch {
      dispose();
      return null;
    }

    if (!groups.length) return null;

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

    function prepareStream(entry, fields) {
      const {emitter, simulation} = entry;
      // An overwrite uses the same seed for every native child. An
      // auto-seeded child keeps its own preview seed through seeks.
      let seed = emitter.seed;
      if (fields.overwriteRandomSeed) seed = fields.particleRandomSeed;
      else if (emitter.autoSeed) seed = entry.autoSeed ??= particles.autoSeed();
      if (!seed32(seed)) return false;
      if (entry.seed !== (seed >>> 0)) {
        entry.seed = seed >>> 0;
        entry.stream = simulation.create(emitter, entry.seed);
        entry.frame = -1;
      }
      return Boolean(entry.stream);
    }

    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          for (const group of groups) {
            const {cue} = group;
            const matches = tracks?.filter(row => row.id === cue.trackId && row.nativeClass === "CustomControlTrack");
            group.track = matches?.length === 1 ? matches[0] : null;
            const events = group.track?.events?.filter(row => row.id === cue.eventId);
            group.event = events?.length === 1 ? events[0] : null;
          }
        }
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        world.length = overlay.length = 0;
        for (const {entries, event, track, cue, layer, maxDuration} of groups) {
          for (const {mesh} of entries) mesh.visible = false;
          const timing = quality?.[cue.quality] !== false && (layer !== 20 || quality?.stage_overlay_effect !== false) &&
            !track?.muted && particles.activeControlFrame(event, time, fps, maxDuration);
          if (!timing || !entries.every(entry => prepareStream(entry, event.values))) continue;
          const {frame, offset: [x, y, z]} = timing;
          for (const entry of entries) {
            const {mesh} = entry;
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
            if (mesh.visible) (layer === 20 ? overlay : world).push(entry);
          }
        }
      },
      sortEntries(layer = 1) { return layer === 20 ? overlay : world; },
      dispose,
    };
  }

  global.MVStudioStageLens = {apply};
})(typeof window !== "undefined" ? window : globalThis);
