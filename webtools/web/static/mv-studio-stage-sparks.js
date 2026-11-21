(function (global) {
  "use strict";

  const atlasAlias = "speedBackCenterStars";
  const tint = [2, 2, 2, 1];
  const profiles = new Map([
    ["A", {widths: new Map([["hibana_01", 1], ["hibana_02", 2], ["smoke", 2]]), usesCueSeed: true,
      simulation: "MVStudioSparksASimulation"}],
    ["B", {widths: new Map([["grow", .5], ["hibana", .5], ["late_kirakira", .5]]), usesCueSeed: false,
      simulation: "MVStudioSparksBSimulation"}],
    ["roop", {widths: new Map(["sparks_R1", "sparks_R2", "sparks_L1", "sparks_L2"].map(name => [name, .5])),
      usesCueSeed: false, maxCues: 1, simulation: "MVStudioSparksRoopSimulation"}],
  ]);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;

  function checked(source, {widths, usesCueSeed, maxCues = 2}) {
    return Array.isArray(source?.textures) && source.textures.length === 1 &&
      Array.isArray(source.cues) && source.cues.length >= 1 && source.cues.length <= maxCues &&
      source.cues.every(cue => id(cue?.trackId) && id(cue.eventId) &&
        (!usesCueSeed || (Number.isInteger(cue.seed) && cue.seed >= 0 && cue.seed <= 0xffffffff))) &&
      new Set(source.cues.map(cue => JSON.stringify([cue.trackId, cue.eventId]))).size === source.cues.length &&
      Array.isArray(source.emitters) && source.emitters.length <= widths.size &&
      (usesCueSeed ? source.emitters.some(row => row?.name === "hibana_01") : source.emitters.length === widths.size) &&
      new Set(source.emitters.map(row => row?.name)).size === source.emitters.length &&
      source.emitters.every(row => widths.has(row?.name) && Number.isInteger(row.capacity) &&
        row.capacity > 0 && row.capacity <= 1000 && row.maxViewportWidth === widths.get(row.name));
  }

  async function apply(T, root, source, atlases, kind) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles;
    const localBillboards = global.MVStudioDisplayLights?.localBillboards;
    const velocityBillboards = global.MVStudioMovingCompanions?.velocityBillboards;
    const profile = profiles.get(kind), simulation = global[profile?.simulation];
    if (!profile || !root?.isObject3D || !title || !particles || !localBillboards || !velocityBillboards ||
        !simulation?.create || !checked(source, profile)) return null;

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
          const sheet = name === "hibana_02", smoke = name === "smoke";
          const shared = !profile.usesCueSeed && seed !== null;
          let stream = shared ? fixed.get(row) : null;
          if (!stream) {
            // Retain the native clip seed override or give an automatic leaf a
            // stable preview seed for independent seeks and replays.
            const initialSeed = profile.usesCueSeed ? cue.seed : (seed ?? particles.autoSeed());
            const engine = smoke ? global.MVStudioSparksASmokeSimulation :
              sheet ? global.MVStudioSparksASecondarySimulation : simulation;
            stream = engine?.create(row, initialSeed);
            if (!stream?.sample) {
              if (sheet || smoke) continue;
              throw new Error("Invalid native spark emitter.");
            }
            if (shared) fixed.set(row, stream);
          }
          const capacity = smoke ? row.capacity : Math.min(row.capacity,
            (row.bursts?.reduce((sum, burst) => sum + burst[1] * (burst[2] ?? 1), 0) ?? 0) +
            Math.ceil(row.duration * (row.rate ?? 0)) + 1);
          const fields = {texture, capacity, maxViewportWidth: row.maxViewportWidth,
            name: `Native stage sparks ${kind}`, tint};
          const [columns, rows] = sheet ? row.atlas.tiles : [1, 1];
          const atlas = sheet ? [1 / columns, 1 / rows, 0, 0] : uv;
          const packet = stretch ? velocityBillboards(T, {...fields, uv, stretch}) :
            localBillboards(T, {...fields, atlas, columns, rotation, additive: true, rolling: true, viewAligned: true,
              minViewportWidth: row.minViewportWidth});
          packet.mesh.name = `Native spark ${kind} ${index + 1} ${name}`;
          packet.mesh.renderOrder = 3010;
          packet.mesh.material.stencilFunc = T.AlwaysStencilFunc;
          packet.mesh.material.stencilRef = 0;
          entries.push({...packet, stream, capacity, viewSize: sheet || smoke || kind === "roop", lastFrame: -1, fps: 0});
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
      if (entry.viewSize) {
        stream.sample(elapsed, fps, (px, py, pz, width, height, roll, r, g, b, a, tile = 0) => {
          if (count >= capacity || Math.max(width, height) <= 0 || a <= 0) return;
          centers.setXYZW(count, px, py, pz, tile);
          sizes.setXY(count, width, height);
          rolls.setX(count, roll);
          colors.setXYZW(count, r, g, b, a);
          count++;
        });
      } else stream.sample(elapsed, fps, (px, py, pz, vx, vy, vz, size, roll, r, g, b, a) => {
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

  global.MVStudioStageSparks = {apply};
})(typeof window !== "undefined" ? window : globalThis);
