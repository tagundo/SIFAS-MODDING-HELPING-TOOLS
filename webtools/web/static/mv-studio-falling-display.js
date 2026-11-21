(function (global) {
  "use strict";

  const f32 = Math.fround;
  const roles = new Set(["light_big", "light_smole", "light_smole_L", "light_smole_R", "stars"]);
  const white = [255,255,255,255];
  const between = (number, min, max) => Number.isFinite(number) && number >= min && number <= max;
  const vector = (value, size, min, max) => Array.isArray(value) && value.length === size &&
    value.every(number => between(number, min, max));
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;

  function validPalette(palette) {
    return Array.isArray(palette?.rgb) && palette.rgb.length === 2 &&
      palette.rgb.every((row, i) => vector(row, 4, 0, 65535) && row.every(Number.isInteger) &&
        row[0] === [32768, 65535][i] && row.slice(1).every(value => value <= 255)) &&
      Array.isArray(palette.alpha) && palette.alpha.length === 2 &&
      palette.alpha.every((row, i) => vector(row, 2, 0, 65535) && row[0] === i * 65535 && row[1] === 255);
  }

  function checked(source, title, motion, particles) {
    if (!Array.isArray(source?.emitters) || source.emitters.length !== roles.size ||
        new Set(source.emitters.map(row => row?.name)).size !== roles.size ||
        !Array.isArray(source.textures) || source.textures.length !== 2 ||
        !Array.isArray(source.cues) || source.cues.length < 1 || source.cues.length > 2) return false;
    return source.emitters.every(row => {
      const stars = row?.name === "stars";
      return roles.has(row?.name) && vector(row.position, 3, -100, 100) && vector(row.rotation, 4, -1, 1) &&
        Math.abs(Math.hypot(...row.rotation) - 1) < 1e-5 && row.lifetime === (stars ? 5 : 8) &&
        row.maxViewportWidth === 2 && row.sortBias === (row.name.startsWith("light_smole") ? 1 : 0) &&
        row.texture === Number(stars) && particles.validNativeColor({start: white, keys: row.colorKeys});
    }) && source.cues.every(cue => id(cue?.trackId) && id(cue.eventId) && validPalette(cue.starPalette) &&
      between(cue.lightAtlasPeriod, .17, .18) && title.boundedCurve(cue.lightAtlasCurve, motion.validCurve)) &&
      new Set(source.cues.map(cue => JSON.stringify([cue.trackId, cue.eventId]))).size === source.cues.length;
  }

  async function apply(T, root, source, borrowed) {
    const title = global.MVStudioTitle, motion = global.MVStudioStageMotion, particles = global.MVStudioStageParticles;
    const display = global.MVStudioDisplayLights, simulation = global.MVStudioFallingSimulation;
    if (!root?.isObject3D || !title || !motion || !particles || !display?.localBillboards || !simulation ||
        !checked(source, title, motion, particles)) return null;
    const streams = source.emitters.map(row => simulation.create(row));
    if (streams.some(stream => !stream?.sample)) return null;
    const textures = [], owned = [], entries = [], sorted = [];
    let disposed = false, tracks, bindings = [];
    const pivot = new T.Vector3(), eye = new T.Vector3();
    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const {mesh} of entries) {
        root.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      owned.forEach(texture => texture.dispose());
    }

    try {
      for (let index = 0; index < source.textures.length; index++) {
        const reference = source.textures[index], alias = index === 0 ? "displayLights" : "speedBackCenterStars";
        const data = reference === alias ? borrowed?.[alias] : reference;
        if (reference === alias && data?.isTexture) textures.push(data);
        else {
          if (!title.validMipChain(data) || data[0].width !== 512) throw new Error("Invalid native display atlas.");
          const texture = await title.loadTexture(T, new T.TextureLoader(), data);
          owned.push(texture);
          textures.push(texture);
        }
      }
      source.emitters.forEach((row, order) => {
        const stars = row.name === "stars", capacity = stars ? 52 : 9;
        const rotation = new T.Quaternion().fromArray(row.rotation);
        const packet = display.localBillboards(T, {
          texture: textures[row.texture], rotation, capacity, maxViewportWidth: row.maxViewportWidth,
          atlas: stars ? [.25,.25,.75,.25] : [1,.25,0,0], name: "Native falling display particles",
          additive: stars, rolling: true,
        });
        const center = new T.Vector3().set(0, stars ? -2.5748562812805176 : -6, 0).applyQuaternion(rotation)
          .add(pivot.fromArray(row.position));
        packet.mesh.name = `Native stage falling ${row.name}`;
        const record = {start: white, keys: row.colorKeys};
        entries.push({...packet, order, stars, capacity, center, record, stream: streams[order], sortBias: row.sortBias, distance: 0,
          live: [], records: Array.from({length: capacity}, () => ({position: new T.Vector3()}))});
        root.add(packet.mesh);
      });
    } catch {
      dispose();
      return null;
    }

    function updateEmitter(entry, elapsed, fps, cue) {
      const {mesh, stars, record, stream, records, live, capacity} = entry;
      live.length = 0;
      if (cue) stream.sample(elapsed, fps, (px, py, pz, width, height, roll, age, stamp) => {
        if (live.length >= capacity || width <= 0 || height <= 0) return;
        let tile = 0;
        if (stars) {
          const palette = cue.starPalette.rgb;
          const index = stamp <= palette[0][0] ? 0 : 1;
          record.start = [palette[index][1], palette[index][2], palette[index][3], 255];
        } else {
          const period = cue.lightAtlasPeriod;
          const phase = age <= period ? age : f32(age - f32(Math.floor(age / period) * period));
          tile = Math.max(0, Math.min(3, Math.floor(f32(4 * motion.evaluate(cue.lightAtlasCurve, phase)))));
        }
        const color = particles.nativeColorAtTime(record, age);
        if (color[3] <= 0) return;
        const sprite = records[live.length];
        sprite.position.set(px, py, pz);
        sprite.width = width;
        sprite.height = height;
        sprite.roll = roll;
        sprite.tile = tile;
        sprite.color = color;
        sprite.index = live.length;
        live.push(sprite);
      });
      mesh.visible = live.length > 0;
      mesh.geometry.instanceCount = live.length;
    }

    function packet(entry, camera) {
      const {live, centers, sizes, rolls, colors} = entry;
      for (const p of live) {
        p.distance = camera.isOrthographicCamera
          ? f32(-pivot.copy(p.position).applyMatrix4(camera.matrixWorldInverse).z)
          : f32(eye.distanceToSquared(p.position));
      }
      // The distance sorter in the native particle job writes the farthest
      // primitives first. Four renderers use noncommutative alpha blending.
      live.sort((a, b) => b.distance - a.distance || a.index - b.index);
      live.forEach(({position, width, height, roll, tile, color}, slot) => {
        centers.setXYZW(slot, position.x, position.y, position.z, tile);
        sizes.setXY(slot, width, height);
        rolls.setX(slot, roll);
        colors.setXYZW(slot, ...color.map(value => Math.round(value * 255)));
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
          bindings = source.cues.map(cue => {
            const matches = (tracks || []).filter(row => row.id === cue.trackId && row.nativeClass === "CustomControlTrack");
            return {cue, track: matches.length === 1 ? matches[0] : null};
          });
        }
        let cue, start = -Infinity;
        if (project?.quality?.values?.stage_display !== false) {
          for (const binding of bindings) {
            const {track} = binding;
            if (!track || track.muted) continue;
            const event = track.events.find(row => row.id === binding.cue.eventId);
            if (title.neutralClip(event) && time >= event.start && time < event.start + event.duration && event.start >= start) {
              cue = binding.cue;
              start = event.start;
            }
          }
        }
        const fps = project?.quality?.values?.frame_rate_60fps === true ? 60 : 30;
        for (const entry of entries) updateEmitter(entry, time - start, fps, cue);
      },
      sort(camera, titlePeers) {
        if (disposed) return;
        sorted.length = 0;
        for (const entry of entries) if (entry.mesh.visible) sorted.push(entry);
        if (!sorted.length) return;
        camera.updateMatrixWorld();
        eye.setFromMatrixPosition(camera.matrixWorld);
        for (const entry of sorted) packet(entry, camera);
        if (titlePeers) sorted.push(...titlePeers());
        for (const entry of sorted) {
          const distance = camera.isOrthographicCamera
            ? -pivot.copy(entry.center).applyMatrix4(camera.matrixWorldInverse).z
            : eye.distanceTo(entry.center);
          entry.distance = f32(distance + entry.sortBias);
        }
        sorted.sort((a,b) => b.distance - a.distance || a.order - b.order);
        sorted.forEach(({mesh}, rank) => { mesh.renderOrder = 2900 + rank * .01; });
      },
      dispose,
    };
  }

  global.MVStudioFallingDisplay = {apply};
})(typeof window !== "undefined" ? window : globalThis);
