(function (global) {
  "use strict";

  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const finiteVector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  const capacities = new Map([["01", 600], ["02", 300]]);
  const stretch = {lengthScale: 1, velocityScale: 0};
  const tick = time => Math.trunc(time / 1e-12 + .5);

  function checked(source, title) {
    const material = source?.material;
    return source?.schema === 1 && title.validMipChain(source.texture) && source.texture[0].width === 256 &&
      Array.isArray(source.cues) && source.cues.length >= 1 && source.cues.length <= 2 &&
      source.cues.every(row => capacities.has(row?.profile) && id(row.trackId) && id(row.eventId) &&
        finiteVector(row.position, 3) && finiteVector(row.rotation, 4)) &&
      new Set(source.cues.map(row => row.profile)).size === source.cues.length &&
      finiteVector(source.uv, 4) && source.uv[0] === .25 && source.uv[1] === .25 && source.uv[2] === .5 && source.uv[3] === 0 &&
      source.maxViewportWidth === .5 && material?.queue === 3010 && material.blend === "add" && material.cull === 0 &&
      material.premultiply === false && finiteVector(material.tint, 4) && material.tint.every(channel => channel === 1);
  }

  async function apply(T, root, source, sharedAtlas) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles, simulation = global.MVStudioRainSimulation;
    const velocityBillboards = global.MVStudioMovingCompanions?.velocityBillboards;
    if (!root?.isObject3D || !title || !particles || !simulation || !velocityBillboards || !checked(source, title)) return null;
    const streams = source.cues.map(cue => ({cue, stream: simulation.create({...source, ...cue})})).filter(entry => entry.stream);
    if (!streams.length) return null;
    const borrowed = sharedAtlas?.texture?.isTexture && source.texture.length === sharedAtlas.levels?.length &&
      source.texture.every((level, index) => {
        const shared = sharedAtlas.levels[index];
        return level.png === shared?.png && level.width === shared.width && level.height === shared.height;
      });
    let texture;
    try {
      texture = borrowed ? sharedAtlas.texture : await title.loadTexture(T, new T.TextureLoader(), source.texture);
    } catch {
      return null;
    }

    const entries = streams.map(({cue, stream}) => {
      const capacity = capacities.get(cue.profile), name = `Native Aion rain ${cue.profile}`;
      const draw = velocityBillboards(T, {texture, capacity, stretch, uv: source.uv, maxViewportWidth: source.maxViewportWidth,
        name, tint: source.material.tint, separateLength: true});
      draw.mesh.name = name;
      draw.mesh.renderOrder = source.material.queue;
      draw.mesh.material.stencilFunc = T.AlwaysStencilFunc;
      root.add(draw.mesh);
      return {cue, stream, capacity, ...draw, frame: -1, fps: 0};
    });

    let tracks, disposed = false;
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
        const displayFrame = Math.floor(time * fps + 1e-9), timeline = tick(time);
        for (const entry of entries) {
          const {mesh, track, cue, stream, centers, colors, velocities, lengths, capacity} = entry;
          const event = quality?.stage_control !== false && !track?.muted && track?.events.find(row => row.id === cue.eventId);
          const start = event && tick(event.start);
          const offset = event && timeline >= start && timeline < tick(event.start + event.duration) &&
            particles.activeOffset(event, Math.max(time, event.start));
          if (!offset) {
            mesh.geometry.instanceCount = 0;
            mesh.visible = false;
            entry.frame = -1;
            continue;
          }
          if (mesh.position.x !== offset[0] || mesh.position.y !== offset[1] || mesh.position.z !== offset[2]) {
            mesh.position.fromArray(offset);
            mesh.updateMatrix();
          }
          const first = Math.ceil(event.start * fps);
          const activated = tick((first - 1) / fps) === start ? first - 1 : first;
          // The first active display update advances past the wake state.
          const frame = Math.max(0, displayFrame - activated + 1);
          if (entry.frame === frame && entry.fps === fps) continue;
          entry.frame = frame;
          entry.fps = fps;
          let count = 0;
          stream.sample(frame / fps, fps, (x, y, z, vx, vy, vz, width, length, r, g, b, a) => {
            if (!(width > 0) || !(length > 0) || !a || count >= capacity) return;
            centers.setXYZW(count, x, y, z, width);
            velocities.setXYZ(count, vx, vy, vz);
            lengths.setX(count, length);
            colors.setXYZW(count++, r, g, b, a);
          });
          mesh.geometry.instanceCount = count;
          mesh.visible = count > 0;
          if (!count) continue;
          for (const attribute of [centers, colors, velocities, lengths]) {
            attribute.updateRange.count = count * attribute.itemSize;
            attribute.needsUpdate = true;
          }
        }
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        for (const {mesh} of entries) {
          root.remove(mesh);
          mesh.geometry.dispose();
          mesh.material.dispose();
        }
        if (!borrowed) texture.dispose();
      },
    };
  }

  global.MVStudioStageRain = {apply};
})(typeof window !== "undefined" ? window : globalThis);
