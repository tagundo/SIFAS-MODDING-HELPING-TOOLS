(function (global) {
  "use strict";

  const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;
  const matches = (value, target) => vector(value, target.length) && value.every((number, index) => number === target[index]);
  const capacity = {air: 600, floor: 32};

  function checked(source, title) {
    const {geometry, material, texture, uv, emitters, cues} = source;
    return source.schema === 1 && title.validMipChain(texture) && texture[0].width === 256 &&
      matches(uv, [.5, .5, 0, .5]) &&
      Array.isArray(geometry?.positions) && geometry.positions.length === 16 && geometry.positions.every(row => vector(row, 3)) &&
      Array.isArray(geometry.uv) && geometry.uv.length === 16 && geometry.uv.every(row => vector(row, 2)) &&
      Array.isArray(geometry.indices) && geometry.indices.length === 42 &&
      geometry.indices.every(index => Number.isInteger(index) && index >= 0 && index < 16) &&
      material?.queue === 3010 && material.cull === 0 && material.blend === "add" &&
      material.premultiply === false && material.saturate === false && matches(material.tint, [1, 1, 1, 1]) &&
      material.stencil === "always" && material.stencilRef === 2 &&
      Array.isArray(emitters) && emitters.length > 0 && emitters.length <= 2 &&
      emitters.every(row => (row?.role === "air" || row?.role === "floor") &&
        matches(row.position, [0, row.role === "air" ? 15 : Math.fround(.06), 0]) &&
        matches(row.rotation, [0, 0, 0, 1]) && matches(row.scale, [1, 1, 1]) &&
        row.sortMode === 0 && row.maxViewportWidth === .5) &&
      new Set(emitters.map(row => row.role)).size === emitters.length &&
      Array.isArray(cues) && cues.length > 0 && cues.length <= 3 &&
      cues.every(cue => id(cue?.trackId) && id(cue.eventId)) &&
      new Set(cues.map(cue => JSON.stringify([cue.trackId, cue.eventId]))).size === cues.length;
  }

  async function apply(T, root, source, sharedAtlas) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles;
    const meshBatch = global.MVStudioAutumnLeaves?.meshBatch;
    const engines = {air: global.MVStudioConfettiAirSimulation, floor: global.MVStudioConfettiFloorSimulation};
    if (!source || !root?.isObject3D || !title || !particles || !meshBatch || !checked(source, title)) return null;
    const streams = source.emitters.map(row => ({row, stream: engines[row.role]?.create({...row, uv: source.uv})}))
      .filter(({stream}) => stream);
    if (!streams.length) return null;

    const borrowed = title.sharedMipTexture(source.texture, sharedAtlas);
    let texture, tracks, disposed = false;
    const bindings = source.cues.map((cue, index) => ({cue, packets: [], index}));
    const visible = [];
    const position = new T.Vector3(), scale = new T.Vector3(), euler = new T.Euler();
    const orientation = new T.Quaternion(), matrix = new T.Matrix4(), bounds = new T.Box3();
    try {
      texture = borrowed || await title.loadTexture(T, new T.TextureLoader(), source.texture);
    } catch {
      return null;
    }

    function createPackets(binding) {
      for (const {row, stream} of streams) {
        const name = `Native Aion confetti ${row.role} ${binding.index + 1}`;
        const packet = meshBatch(T, source, texture, source, name, source.material, capacity[row.role]);
        root.add(packet.mesh);
        binding.packets.push({...packet, row, stream, center: new T.Vector3(), frame: -1, fps: 0,
          origin: new T.Vector3().fromArray(row.position)});
      }
    }

    function writeFrame(entry, frame, fps) {
      const {mesh, colors, row, stream, origin} = entry;
      const elapsed = frame / fps;
      let count = 0;
      bounds.makeEmpty();

      function particle(x, y, z, sx, sy, sz, rx, ry, rz, r, g, b, a) {
        position.set(x, y, z);
        bounds.expandByPoint(position);
        if (!(sx > 0 && sy > 0 && sz > 0) || !a || count === capacity[row.role]) return;
        orientation.setFromEuler(euler.set(rx, -ry, -rz, "YXZ"));
        mesh.setMatrixAt(count, matrix.compose(position.add(origin), orientation, scale.set(sx, sy, sz)));
        colors.setXYZW(count++, r, g, b, a);
      }

      if (row.role === "air") {
        stream.sample(elapsed, fps, (x, y, z, width, rx, ry, rz, r, g, b, a) =>
          particle(x, y, z, width, width, width, rx, ry, rz, r, g, b, a));
      } else {
        stream.sample(elapsed, fps, particle);
      }
      bounds.getCenter(entry.center).add(origin);
      mesh.visible = count > 0;
      mesh.count = count;
      if (!count) return;
      mesh.instanceMatrix.updateRange.count = count * 16;
      colors.updateRange.count = count * 4;
      mesh.instanceMatrix.needsUpdate = colors.needsUpdate = true;
    }

    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          for (const binding of bindings) {
            const {cue} = binding;
            const matches = tracks?.filter(row => row.id === cue.trackId && row.nativeClass === "CustomControlTrack");
            binding.track = matches?.length === 1 ? matches[0] : null;
            const events = binding.track?.events?.filter(row => row.id === cue.eventId);
            binding.event = events?.length === 1 ? events[0] : null;
          }
        }
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        visible.length = 0;
        for (const binding of bindings) {
          const {track, event, packets} = binding;
          const timing = quality?.stage_control !== false && !track?.muted && particles.activeControlFrame(event, time, fps);
          if (!timing) {
            for (const {mesh} of packets) mesh.visible = false;
            continue;
          }
          if (!packets.length) createPackets(binding);
          const {frame, offset: [x, y, z]} = timing;
          for (const entry of packets) {
            const {mesh} = entry;
            if (mesh.position.x !== x || mesh.position.y !== y || mesh.position.z !== z) {
              mesh.position.set(x, y, z);
              mesh.updateMatrix();
            }
            if (entry.frame !== frame || entry.fps !== fps) {
              writeFrame(entry, frame, fps);
              entry.frame = frame;
              entry.fps = fps;
            }
            mesh.visible = mesh.count > 0;
            if (mesh.visible) visible.push(entry);
          }
        }
      },
      sortEntries() { return visible; },
      dispose() {
        if (disposed) return;
        disposed = true;
        visible.length = 0;
        for (const {packets} of bindings) {
          for (const {mesh} of packets) {
            root.remove(mesh);
            mesh.dispose();
            mesh.geometry.dispose();
            mesh.material.dispose();
          }
        }
        if (!borrowed) texture.dispose();
      },
    };
  }

  global.MVStudioConfetti = {apply};
})(typeof window !== "undefined" ? window : globalThis);
