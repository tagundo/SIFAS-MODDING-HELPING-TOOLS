(function (global) {
  "use strict";

  const f32 = Math.fround;
  const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const equalVector = (a, b) => vector(a, b.length) && a.every((value, index) => value === b[index]);
  const validPose = row => vector(row?.position, 3) && vector(row.rotation, 4) &&
    Math.abs(Math.hypot(...row.rotation) - 1) < 1e-5 && vector(row.scale, 3);
  const roles = new Map([
    ["fan", {texture: "fan", capacity: 10, cull: 1, blend: "alpha"}],
    ["flash", {texture: "flash", capacity: 1, cull: 0, blend: "add"}],
    ["leaf-green", {texture: "leaf", capacity: 75, cull: 0, blend: "alpha", uv: [.25, .25, .75, .25]}],
    ["leaf-red", {texture: "leaf", capacity: 30, cull: 0, blend: "alpha", uv: [.25, .25, .25, .25]}],
  ]);

  function flashColor(row) {
    return {start: row.startColor.map(value => Math.round(value * 255)),
      keys: row.alphaKeys.map(([time, alpha]) => [f32(time / 65535), 255, 255, 255, Math.round(alpha * 255)])};
  }

  function stationaryFlash(row, particles) {
    const palette = flashColor(row);
    const phaseStep = f32(particles.nativeStep * 100);
    let phase = f32(f32(particles.nativeStep * f32(1e-6)) * 100);
    const colors = [null];
    while (phase <= 100) {
      colors.push(particles.nativeColorAtTime(palette, f32(phase * f32(.01))).map(value => Math.round(value * 255)));
      phase = f32(phase + phaseStep);
    }
    return {
      sample(elapsed, fps, emit) {
        const color = colors[particles.nativeFrame(elapsed, fps)];
        if (color) emit(0, 0, 0, row.size, row.size, 0, 0, ...color);
      },
    };
  }

  function validEmitter(row, source, deps) {
    const spec = roles.get(row?.role);
    if (!spec || !validPose(row) || !equalVector(row.scale, [1, 1, 1]) ||
        row.maxViewportWidth !== (row.role === "flash" ? 2 : .5) ||
        row.sortMode !== (row.role === "flash" ? 0 : 1)) return false;
    const {material} = row;
    const brightness = row.role === "flash" ? 1 : f32(1.1898452043533325);
    const levels = source.textures?.[spec.texture];
    const validAtlas = spec.texture === "flash" ? Array.isArray(levels) && levels.length === 7 &&
      levels.every((level, index) => level?.width === (64 >> index) && level.height === level.width &&
        deps.title.validTexture(level)) : deps.title.validMipChain(levels) && levels[0].width === 256;
    if (row.texture !== spec.texture || !validAtlas ||
        material?.queue !== 2900 || material.cull !== spec.cull || material.blend !== spec.blend ||
        material.stencil !== "equal" || material.stencilRef !== 2 || material.saturate !== false ||
        material.premultiply !== false || !equalVector(material.tint, [brightness, brightness, brightness, 1])) return false;
    if (spec.uv) return equalVector(row.uv, spec.uv) && deps.flowers.validFlower(source.geometry);
    if (row.role === "fan") return equalVector(row.tiles, [1, 2]) && equalVector(row.pivot, [0, .5, 0]);
    return row.size === 15 && row.lifetime === 1 && equalVector(row.uv, [1, 1, 0, 0]) &&
      equalVector(row.startColor, [1, f32(.35982987), 0, 1]) &&
      Array.isArray(row.alphaKeys) && row.alphaKeys.length === 4 &&
      row.alphaKeys.every((key, index) => equalVector(key, [[0, 0], [14649, 1], [42887, 1], [65535, 0]][index])) &&
      deps.particles.validNativeColor(flashColor(row));
  }

  function markChanged(attribute, count) {
    attribute.updateRange.count = count * attribute.itemSize;
    attribute.needsUpdate = true;
  }

  async function apply(T, root, source, sharedAtlas) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles;
    const flowers = global.MVStudioAutumnLeaves, display = global.MVStudioDisplayLights;
    const fan = global.MVStudioMomijiFanSimulation, leaves = global.MVStudioMomijiLeavesSimulation;
    if (source?.schema !== 1 || !root?.isObject3D || !title || !particles || !flowers || !display ||
        !id(source.trackId) || !id(source.eventId) || !validPose(source.anchor) ||
        !Array.isArray(source.emitters) || source.emitters.length > roles.size ||
        new Set(source.emitters.map(row => row?.role)).size !== source.emitters.length) return null;

    const owned = [], entries = [], loader = new T.TextureLoader();
    const textures = new Map();
    const position = new T.Vector3(), size = new T.Vector3(), eye = new T.Vector3();
    const world = new T.Vector3(), centerOffset = new T.Vector3();
    const matrix = new T.Matrix4(), rotation = new T.Quaternion(), angles = new T.Euler();
    const anchorPosition = new T.Vector3().fromArray(source.anchor.position);
    const anchorRotation = new T.Quaternion().fromArray(source.anchor.rotation);
    const anchorScale = new T.Vector3().fromArray(source.anchor.scale);
    const bounds = new T.Box3();
    const visible = [];
    let disposed = false, tracks, track, event;
    let ribbons = [];

    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const {mesh} of entries) {
        root.remove(mesh);
        mesh.dispose?.();
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      for (const texture of owned) texture.dispose();
    }

    try {
      for (const row of source.emitters) {
        if (!validEmitter(row, source, {title, particles, flowers})) continue;
        const spec = roles.get(row.role), isLeaf = Boolean(spec.uv);
        const stream = isLeaf ? leaves?.create({...source, ...row}) :
          row.role === "fan" ? fan?.create(row) : stationaryFlash(row, particles);
        if (!stream) continue;

        const levels = source.textures[row.texture];
        if (!textures.has(row.texture)) {
          const borrowed = row.texture === "leaf" && title.sharedMipTexture(levels, sharedAtlas);
          const texture = borrowed || await title.loadTexture(T, loader, levels);
          if (!borrowed) owned.push(texture);
          textures.set(row.texture, texture);
        }
        const texture = textures.get(row.texture), name = `Native Aion display momiji ${row.role}`;
        const origin = new T.Vector3().fromArray(row.position).multiply(anchorScale)
          .applyQuaternion(anchorRotation).add(anchorPosition);
        const basis = new T.Quaternion().fromArray(row.rotation).premultiply(anchorRotation);
        const packet = isLeaf ? flowers.meshBatch(T, source, texture, row, name, row.material, spec.capacity) :
          display.localBillboards(T, {texture, rotation: row.role === "fan" ? new T.Quaternion() : basis,
            capacity: spec.capacity, maxViewportWidth: row.maxViewportWidth, atlas: row.uv || [1, .5, 0, 0],
            columns: 1, name, tint: row.material.tint, additive: row.role === "flash",
            rolling: row.role === "fan", pivot: row.pivot, side: row.role === "fan" ? T.BackSide : T.DoubleSide});
        packet.mesh.name = name;
        root.add(packet.mesh);
        const records = Array.from({length: spec.capacity}, (_, index) => ({
          index, position: new T.Vector3(), size: new T.Vector3(), rotation: new T.Quaternion(), color: [0, 0, 0, 0],
        }));
        entries.push({...packet, row, origin, basis, records, stream, isLeaf, live: [], center: new T.Vector3(),
          frame: -1, fps: 0, order: [...roles.keys()].indexOf(row.role)});
      }
    } catch {
      dispose();
      return null;
    }
    if (!entries.length) return null;

    function updateEntry(entry, frame, fps) {
      const {mesh, live, records, origin, basis, isLeaf, stream} = entry;
      live.length = 0;
      bounds.makeEmpty();
      function record(x, y, z, r, g, b, a) {
        const sample = records[live.length];
        // Native renderer bounds enclose the local particle centers before
        // the emitter transforms the midpoint, including zero-alpha births.
        bounds.expandByPoint(position.set(x, y, z));
        if (!sample || !a) return null;
        sample.position.copy(position).applyQuaternion(basis).add(origin);
        sample.color[0] = r;
        sample.color[1] = g;
        sample.color[2] = b;
        sample.color[3] = a;
        live.push(sample);
        return sample;
      }

      if (isLeaf) {
        stream.sample(frame / fps, fps, (x, y, z, scale, rx, ry, rz, r, g, b, a) => {
          const sample = record(x, y, z, r, g, b, a);
          if (!sample) return;
          sample.size.setScalar(scale);
          // Unity mesh particles apply Z-X-Y rotation before the emitter basis.
          sample.rotation.setFromEuler(angles.set(rx, -ry, -rz, "YXZ")).premultiply(basis);
        });
      } else {
        stream.sample(frame / fps, fps, (x, y, z, width, height, roll, tile, r = 255, g = 255, b = 255, a = 255) => {
          const sample = record(x, y, z, r, g, b, a);
          if (!sample) return;
          sample.size.set(width, height, 1);
          sample.roll = roll;
          sample.tile = tile;
        });
      }
      bounds.getCenter(entry.center).applyQuaternion(basis).add(origin);
      mesh.visible = live.length > 0;
      if (isLeaf) mesh.count = live.length;
      else mesh.geometry.instanceCount = live.length;
    }

    function drawPacket(entry, distance) {
      const {mesh, live, isLeaf, colors, centers, sizes, rolls, row} = entry;
      if (row.sortMode === 1) {
        for (const sample of live) sample.distance = distance(sample.position);
        live.sort((a, b) => b.distance - a.distance || a.index - b.index);
      }
      live.forEach((sample, index) => {
        const {position, size, color} = sample;
        if (isLeaf) mesh.setMatrixAt(index, matrix.compose(position, sample.rotation, size));
        else {
          centers.setXYZW(index, position.x, position.y, position.z, sample.tile);
          sizes.setXY(index, size.x, size.y);
          rolls?.setX(index, sample.roll);
        }
        colors.setXYZW(index, ...color);
      });
      for (const attribute of [isLeaf ? mesh.instanceMatrix : centers, sizes, rolls, colors]) {
        if (attribute) markChanged(attribute, live.length);
      }
    }

    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          const matches = tracks?.filter(row => row.id === source.trackId && row.nativeClass === "CustomControlTrack");
          track = matches?.length === 1 ? matches[0] : null;
          const events = track?.events?.filter(row => row.id === source.eventId);
          event = events?.length === 1 ? events[0] : null;
        }
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        const timing = quality?.stage_display !== false && !track?.muted && particles.activeControlFrame(event, time, fps);
        for (const entry of entries) {
          const {mesh} = entry;
          if (!timing) {
            mesh.visible = false;
            entry.frame = -1;
            continue;
          }
          const [x, y, z] = timing.offset;
          if (mesh.position.x !== x || mesh.position.y !== y || mesh.position.z !== z) {
            mesh.position.set(x, y, z);
            mesh.updateMatrix();
          }
          if (entry.frame === timing.frame && entry.fps === fps) continue;
          entry.frame = timing.frame;
          entry.fps = fps;
          updateEntry(entry, timing.frame, fps);
        }
      },
      sort(camera, ribbonPeers) {
        if (disposed) return;
        visible.length = 0;
        for (const entry of entries) if (entry.mesh.visible) visible.push(entry);
        for (const {mesh} of ribbons) mesh.renderOrder = 2900;
        if (!visible.length) {
          ribbons = [];
          return;
        }
        ribbons = ribbonPeers?.() || [];
        camera.updateMatrixWorld();
        eye.setFromMatrixPosition(camera.matrixWorld);
        for (const entry of visible) {
          centerOffset.copy(entry.mesh.position);
          drawPacket(entry, center => {
            world.copy(center).add(centerOffset);
            return f32(camera.isOrthographicCamera ? -world.applyMatrix4(camera.matrixWorldInverse).z : eye.distanceToSquared(world));
          });
        }
        visible.push(...ribbons);
        for (const entry of visible) {
          world.copy(entry.center);
          if (entry.live) world.add(entry.mesh.position);
          entry.distance = f32(camera.isOrthographicCamera ? -world.applyMatrix4(camera.matrixWorldInverse).z : eye.distanceToSquared(world));
        }
        visible.sort((a, b) => b.distance - a.distance || a.order - b.order);
        visible.forEach(({mesh}, rank) => { mesh.renderOrder = 2900 + rank * .01; });
      },
      dispose,
    };
  }

  global.MVStudioMomiji = {apply};
})(typeof window !== "undefined" ? window : globalThis);
