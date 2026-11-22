(function (global) {
  "use strict";

  const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  const matches = (value, expected) => vector(value, expected.length) && value.every((n, i) => n === expected[i]);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const seed32 = value => Number.isInteger(value) && value >= -0x80000000 && value <= 0xffffffff;
  const capacity = 64;

  function checked(source, title) {
    const {texture, material, position, rotation, scale, uv, cues} = source;
    return source.schema === 1 && Array.isArray(texture) && texture.length === 9 &&
      texture.every((level, index) => level?.width === (256 >> index) &&
        level.height === Math.max(1, 128 >> index) && title.validTexture(level)) &&
      material?.queue === 3010 && material.cull === 0 && material.blend === "add" &&
      material.stencil === "always" && material.stencilRef === 2 &&
      material.premultiply === false && material.saturate === false && matches(material.tint, [1, 1, 1, 1]) &&
      matches(uv, [.25, 1, .5, 0]) && source.maxViewportWidth === 8 && source.sortMode === 3 &&
      vector(position, 3) && vector(rotation, 4) && Math.abs(Math.hypot(...rotation) - 1) < 1e-5 &&
      matches(scale, [1, 1, 1]) && source.seed === 2559958440 &&
      Array.isArray(cues) && cues.length >= 1 && cues.length <= 2 &&
      cues.every(row => id(row?.trackId) && id(row.eventId)) &&
      new Set(cues.map(row => JSON.stringify([row.trackId, row.eventId]))).size === cues.length;
  }

  async function apply(T, root, source) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles;
    const simulation = global.MVStudioStageGlowSimulation, billboards = global.MVStudioDisplayLights?.localBillboards;
    if (!source || !root?.isObject3D || !title || !particles || !simulation || !billboards || !checked(source, title)) return null;
    const origin = new T.Vector3().fromArray(source.position);
    const basis = new T.Quaternion().fromArray(source.rotation);
    const point = new T.Vector3(), bounds = new T.Box3(), visible = [];
    const entries = [];
    let texture, disposed = false, tracks;

    function dispose() {
      if (disposed) return;
      disposed = true;
      visible.length = 0;
      for (const {mesh} of entries) {
        root.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      texture?.dispose();
    }

    try {
      texture = await title.loadTexture(T, new T.TextureLoader(), source.texture);
      for (const [index, cue] of source.cues.entries()) {
        const name = `Native Aion stage glow ${index + 1}`;
        const batch = billboards(T, {texture, rotation: basis, capacity, maxViewportWidth: source.maxViewportWidth,
          atlas: source.uv, name, additive: true, rolling: true, viewAligned: true,
          nativeViewAxes: true, stencilEqual: false});
        batch.mesh.name = name;
        batch.mesh.renderOrder = source.material.queue;
        root.add(batch.mesh);
        entries.push({...batch, cue, center: new T.Vector3(), frame: -1, fps: 0});
      }
    } catch {
      dispose();
      return null;
    }

    function writeBatch(entry, frame, fps) {
      const {mesh, stream, centers, sizes, colors, rolls} = entry;
      let count = 0;
      bounds.makeEmpty();
      stream.sample(frame / fps, fps, (x, y, z, width, height, roll, r, g, b, a) => {
        bounds.expandByPoint(point.set(x, y, z));
        if (!(width > 0 && height > 0) || !a || count === capacity) return;
        point.applyQuaternion(basis).add(origin);
        centers.setXYZW(count, point.x, point.y, point.z, 0);
        sizes.setXY(count, width, height);
        rolls.setX(count, roll);
        colors.setXYZW(count++, r, g, b, a);
      });
      bounds.getCenter(entry.center).applyQuaternion(basis).add(origin);
      mesh.geometry.instanceCount = count;
      if (!count) return;
      for (const attribute of [centers, sizes, colors, rolls]) {
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
            const tracksForCue = tracks?.filter(row => row.id === cue.trackId && row.nativeClass === "CustomControlTrack");
            entry.track = tracksForCue?.length === 1 ? tracksForCue[0] : null;
            const events = entry.track?.events?.filter(row => row.id === cue.eventId);
            entry.event = events?.length === 1 ? events[0] : null;
          }
        }
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        visible.length = 0;
        for (const entry of entries) {
          const {mesh, event, track} = entry;
          const timing = quality?.stage_control !== false && !track?.muted && particles.activeControlFrame(event, time, fps);
          mesh.visible = false;
          if (!timing) continue;
          const fields = event.values;
          // A CustomControl override sets the seed even on a fixed-seed
          // emitter. Other clips retain the particle system's authored seed.
          const seed = fields.overwriteRandomSeed ? fields.particleRandomSeed : source.seed;
          if (!seed32(seed)) continue;
          if (entry.seed !== (seed >>> 0)) {
            entry.seed = seed >>> 0;
            entry.stream = simulation.create(source, entry.seed);
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

  global.MVStudioStageGlow = {apply};
})(typeof window !== "undefined" ? window : globalThis);
