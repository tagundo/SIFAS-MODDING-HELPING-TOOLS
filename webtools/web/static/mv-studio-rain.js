(function (global) {
  "use strict";

  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const finiteVector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  const capacities = new Map([["01", 600], ["02", 300]]);
  const impactRoles = ["wave", "glow"];
  const stretch = {lengthScale: 1, velocityScale: 0};
  const f32 = Math.fround;

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

  function checkedImpact(impact) {
    return impactRoles.every(role => {
      const material = impact?.[role]?.material, wave = role === "wave";
      return material?.queue === 3010 && material.blend === "add" && material.cull === (wave ? 2 : 0) &&
        material.saturate === wave && material.premultiply === false && finiteVector(material.tint, 4) &&
        material.tint.every(channel => channel === 1);
    }) && finiteVector(impact.wave.tiles, 2) && impact.wave.tiles.every(value => value === 4) &&
      finiteVector(impact.glow.uv, 4) && impact.glow.uv.every(value => value === .5);
  }

  async function prepareImpacts(T, source, streams, title) {
    const simulation = global.MVStudioRainFloorSimulation;
    const localBillboards = global.MVStudioDisplayLights?.localBillboards;
    if (!simulation || !localBillboards || !impactRoles.every(role => title.validMipChain(source.impactTextures?.[role]))) return [];
    const candidates = [];
    for (const entry of streams) {
      if (!checkedImpact(entry.cue.impact)) continue;
      const stream = simulation.create(entry.cue.profile, entry.cue.impact);
      if (stream) candidates.push({entry, stream});
    }
    if (!candidates.length) return [];
    const textures = [];
    try {
      const loader = new T.TextureLoader();
      for (const role of impactRoles) textures.push(await title.loadTexture(T, loader, source.impactTextures[role]));
    } catch {
      for (const texture of textures) texture.dispose();
      return [];
    }
    const horizontal = new T.Quaternion(Math.SQRT1_2, 0, 0, Math.SQRT1_2);
    for (const {entry, stream} of candidates) {
      const {profile, impact} = entry.cue, draws = {};
      for (const [index, role] of impactRoles.entries()) {
        const material = impact[role].material, columns = role === "wave" ? 4 : 2;
        const name = `Native Aion rain ${role} ${profile}`;
        // The source rates and lifetimes fit fewer than 128 live
        // particles per role, even through the opening prewarm.
        const draw = localBillboards(T, {texture: textures[index], rotation: horizontal, capacity: 128,
          maxViewportWidth: 2 * Math.SQRT1_2, atlas: [1 / columns, 1 / columns, 0, 0], columns,
          additive: true, rolling: true, tint: material.tint, saturateRGB: material.saturate, name});
        draw.mesh.name = name;
        draw.mesh.renderOrder = material.queue;
        draw.mesh.material.stencilFunc = T.AlwaysStencilFunc;
        draw.mesh.material.side = material.cull === 2 ? T.FrontSide : T.DoubleSide;
        draw.bounds = new T.Box3();
        draw.center = new T.Vector3();
        draws[role] = draw;
      }
      entry.impact = {stream, draws};
    }
    return textures;
  }

  function setVisible(draw, count) {
    draw.mesh.geometry.instanceCount = count;
    draw.mesh.visible = count > 0;
  }

  function upload(attributes, count) {
    if (!count) return;
    for (const attribute of attributes) {
      attribute.updateRange.count = count * attribute.itemSize;
      attribute.needsUpdate = true;
    }
  }

  function updateImpact({stream, draws}, elapsed, fps, point) {
    const counts = {wave: 0, glow: 0};
    for (const role of impactRoles) draws[role].bounds.makeEmpty();
    stream.sample(elapsed, fps, (role, x, y, z, size, roll, r, g, b, a, tile) => {
      const draw = draws[role], index = counts[role];
      draw.bounds.expandByPoint(point.set(x, y, z));
      if (!(size > 0) || !a || index >= draw.centers.count) return;
      draw.centers.setXYZW(index, x, y, z, tile);
      // Unity's horizontal billboard stores the size along its diagonal.
      const edge = size * Math.SQRT1_2;
      draw.sizes.setXY(index, edge, edge);
      draw.rolls.setX(index, roll);
      draw.colors.setXYZW(index, r, g, b, a);
      counts[role]++;
    });
    for (const role of impactRoles) {
      const draw = draws[role], count = counts[role];
      draw.bounds.getCenter(draw.center);
      setVisible(draw, count);
      upload([draw.centers, draw.sizes, draw.rolls, draw.colors], count);
    }
  }

  async function apply(T, root, source, sharedAtlas) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles, simulation = global.MVStudioRainSimulation;
    const velocityBillboards = global.MVStudioMovingCompanions?.velocityBillboards;
    if (!root?.isObject3D || !title || !particles || !simulation || !velocityBillboards || !checked(source, title)) return null;
    const streams = source.cues.map(cue => ({cue, stream: simulation.create({...source, ...cue})})).filter(entry => entry.stream);
    if (!streams.length) return null;
    const borrowed = title.sharedMipTexture(source.texture, sharedAtlas);
    let texture;
    try {
      texture = borrowed || await title.loadTexture(T, new T.TextureLoader(), source.texture);
    } catch {
      return null;
    }

    const impactTextures = await prepareImpacts(T, source, streams, title);
    const entries = streams.map(({cue, stream, impact}) => {
      const capacity = capacities.get(cue.profile), name = `Native Aion rain ${cue.profile}`;
      const draw = velocityBillboards(T, {texture, capacity, stretch, uv: source.uv, maxViewportWidth: source.maxViewportWidth,
        name, tint: source.material.tint, separateLength: true});
      draw.mesh.name = name;
      draw.mesh.renderOrder = source.material.queue;
      draw.mesh.material.stencilFunc = T.AlwaysStencilFunc;
      const meshes = [draw.mesh, ...Object.values(impact?.draws || {}).map(layer => layer.mesh)];
      root.add(...meshes);
      return {cue, stream, impact, meshes, capacity, ...draw, frame: -1, fps: 0, center: new T.Vector3()};
    });
    const renderers = entries.flatMap(entry => [entry, ...Object.values(entry.impact?.draws || {})]);
    const point = new T.Vector3(), bounds = new T.Box3();
    function includeBounds(x, y, z, vx, vy, vz, startSize) {
      bounds.expandByPoint(point.set(x, y, z));
      const speed = Math.sqrt(vx * vx + vy * vy + vz * vz);
      if (speed <= 1e-15) return;
      // Unity includes the stretched tail using the start X size when
      // sorting the renderer, independently of its current draw size.
      const lengthPerSpeed = f32(startSize / speed);
      bounds.expandByPoint(point.set(f32(x - f32(vx * lengthPerSpeed)), f32(y - f32(vy * lengthPerSpeed)),
        f32(z - f32(vz * lengthPerSpeed))));
    }

    let tracks, disposed = false;
    return {
      invalidate() { tracks = null; },
      sortEntries() {
        return disposed ? [] : renderers.filter(draw => draw.mesh.visible);
      },
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
          const {mesh, meshes, track, cue, stream, impact, centers, colors, velocities, lengths, capacity} = entry;
          const event = quality?.stage_control !== false && !track?.muted && track?.events.find(row => row.id === cue.eventId);
          const timing = particles.activeControlFrame(event, time, fps);
          if (!timing) {
            setVisible(entry, 0);
            if (impact) for (const draw of Object.values(impact.draws)) setVisible(draw, 0);
            entry.frame = -1;
            continue;
          }
          const {offset, frame} = timing;
          if (mesh.position.x !== offset[0] || mesh.position.y !== offset[1] || mesh.position.z !== offset[2]) {
            for (const layer of meshes) {
              layer.position.fromArray(offset);
              layer.updateMatrix();
            }
          }
          if (entry.frame === frame && entry.fps === fps) continue;
          entry.frame = frame;
          entry.fps = fps;
          const elapsed = frame / fps;
          let count = 0;
          bounds.makeEmpty();
          stream.sample(elapsed, fps, (x, y, z, vx, vy, vz, width, length, r, g, b, a) => {
            if (!(width > 0) || !(length > 0) || !a || count >= capacity) return;
            centers.setXYZW(count, x, y, z, width);
            velocities.setXYZ(count, vx, vy, vz);
            lengths.setX(count, length);
            colors.setXYZW(count++, r, g, b, a);
          }, includeBounds);
          bounds.getCenter(entry.center);
          setVisible(entry, count);
          upload([centers, colors, velocities, lengths], count);
          if (impact) updateImpact(impact, elapsed, fps, point);
        }
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        for (const {meshes} of entries) for (const mesh of meshes) {
          root.remove(mesh);
          mesh.geometry.dispose();
          mesh.material.dispose();
        }
        for (const atlas of impactTextures) atlas.dispose();
        if (!borrowed) texture.dispose();
      },
    };
  }

  global.MVStudioStageRain = {apply};
})(typeof window !== "undefined" ? window : globalThis);
