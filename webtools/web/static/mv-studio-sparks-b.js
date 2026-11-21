(function (global) {
  "use strict";

  const atlasAlias = "speedBackCenterStars";
  const tint = [2, 2, 2, 1];
  const names = new Set(["grow", "hibana", "late_kirakira"]);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;

  function checked(source) {
    return Array.isArray(source?.textures) && source.textures.length === 1 &&
      Array.isArray(source.cues) && source.cues.length >= 1 && source.cues.length <= 2 &&
      source.cues.every(cue => id(cue?.trackId) && id(cue.eventId)) &&
      new Set(source.cues.map(cue => JSON.stringify([cue.trackId, cue.eventId]))).size === source.cues.length &&
      Array.isArray(source.emitters) && source.emitters.length === names.size &&
      new Set(source.emitters.map(row => row?.name)).size === names.size &&
      source.emitters.every(row => names.has(row?.name) && Number.isInteger(row.capacity) &&
        row.capacity > 0 && row.capacity <= 1000 && row.maxViewportWidth === .5);
  }

  async function apply(T, root, source, atlases) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles;
    const localBillboards = global.MVStudioDisplayLights?.localBillboards;
    const velocityBillboards = global.MVStudioMovingCompanions?.velocityBillboards;
    const simulation = global.MVStudioSparksBSimulation;
    if (!root?.isObject3D || !title || !particles || !localBillboards || !velocityBillboards || !simulation?.create ||
        !checked(source)) return null;

    const [reference] = source.textures;
    const data = reference === atlasAlias ? atlases?.[atlasAlias] : reference;
    const borrowed = reference === atlasAlias && data?.isTexture;
    let texture;
    try {
      if (borrowed) texture = data;
      else if (title.validMipChain(data) && data[0].width === 512) {
        texture = await title.loadTexture(T, new T.TextureLoader(), data);
      } else return null;
    } catch {
      return null;
    }

    const groups = [], fixed = new Map();
    const rotation = new T.Quaternion();
    let disposed = false, tracks;
    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const {entries} of groups) for (const {mesh} of entries) {
        root.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      if (!borrowed) texture.dispose();
    }
    try {
      source.cues.forEach((cue, index) => {
        const entries = [];
        groups.push({cue, entries, track: null});
        for (const row of source.emitters) {
          const {name, seed, stretch, uv} = row;
          let stream = fixed.get(row);
          if (!stream) {
            // Native auto-seeded leaves receive independent seeds when created.
            // Reuse a preview instance's seed while seeking and replaying it.
            stream = simulation.create(row, seed === null ? particles.autoSeed() : seed);
            if (!stream?.sample) throw new Error("Invalid native spark emitter.");
            if (seed !== null) fixed.set(row, stream);
          }
          const capacity = Math.min(row.capacity, row.bursts.reduce((sum, burst) => sum + burst[1], 0) +
            Math.ceil(row.duration * row.rate) + 1);
          const fields = {texture, capacity, maxViewportWidth: row.maxViewportWidth,
            name: "Native stage sparks B", tint};
          const packet = stretch ? velocityBillboards(T, {...fields, uv, stretch}) :
            localBillboards(T, {...fields, atlas: uv, rotation, additive: true, rolling: true, viewAligned: true});
          packet.mesh.name = `Native spark B ${index + 1} ${name}`;
          packet.mesh.renderOrder = 3010;
          packet.mesh.material.stencilFunc = T.AlwaysStencilFunc;
          packet.mesh.material.stencilRef = 0;
          entries.push({...packet, stream, capacity, lastFrame: -1, fps: 0});
          root.add(packet.mesh);
        }
      });
    } catch {
      dispose();
      return null;
    }

    function updateEmitter(entry, elapsed, fps, offset) {
      const {mesh, stream, centers, sizes, rolls, velocities, colors, capacity} = entry;
      const frame = offset ? particles.nativeFrame(elapsed, fps) : -1;
      if (frame < 0) {
        mesh.visible = false;
        mesh.geometry.instanceCount = 0;
        entry.lastFrame = -1;
        return;
      }
      const [x, y, z] = offset;
      if (mesh.position.x !== x || mesh.position.y !== y || mesh.position.z !== z) {
        mesh.position.set(x, y, z);
        mesh.updateMatrix();
      }
      if (entry.lastFrame === frame && entry.fps === fps) return;
      entry.lastFrame = frame;
      entry.fps = fps;
      let count = 0;
      stream.sample(elapsed, fps, (px, py, pz, vx, vy, vz, size, roll, r, g, b, a) => {
        if (count >= capacity || size <= 0 || a <= 0) return;
        if (velocities) {
          centers.setXYZW(count, px, py, pz, size);
          velocities.setXYZ(count, vx, vy, vz);
        } else {
          centers.setXYZW(count, px, py, pz, 0);
          sizes.setXY(count, size, size);
          rolls.setX(count, roll);
        }
        colors.setXYZW(count, r, g, b, a);
        count++;
      });
      mesh.geometry.instanceCount = count;
      mesh.visible = count > 0;
      if (!count) return;
      const attributes = velocities ? [centers, velocities, colors] : [centers, sizes, rolls, colors];
      for (const attribute of attributes) {
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
          for (const group of groups) {
            const matches = (tracks || []).filter(row => row.id === group.cue.trackId && row.nativeClass === "CustomControlTrack");
            group.track = matches.length === 1 ? matches[0] : null;
          }
        }
        const fps = project?.quality?.values?.frame_rate_60fps === true ? 60 : 30;
        const enabled = project?.quality?.values?.stage_control !== false;
        for (const {cue, track, entries} of groups) {
          const event = enabled && !track?.muted && track?.events.find(row => row.id === cue.eventId);
          const offset = particles.activeOffset(event, time);
          const elapsed = offset ? time - event.start : 0;
          for (const entry of entries) updateEmitter(entry, elapsed, fps, offset);
        }
      },
      dispose,
    };
  }

  global.MVStudioSparksB = {apply};
})(typeof window !== "undefined" ? window : globalThis);
