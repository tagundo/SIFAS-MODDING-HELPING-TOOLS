(function (global) {
  "use strict";

  const radians = Math.PI / 180;
  const active = (event, time) => event.start <= time && time < event.start + event.duration;

  function sample(curve, time) {
    if (curve.mode === "constant") return curve.keys;
    let left = 0, right = curve.keys.length;
    while (left < right) {
      const middle = Math.floor((left + right) / 2);
      if (curve.keys[middle][0] > time) right = middle;
      else left = middle + 1;
    }
    const index = Math.max(0, left - 1), [start, value] = curve.keys[index];
    const delta = Math.max(0, time - start);
    if (curve.mode === "cubic") {
      return Math.abs(start) > 1e20 ? value[3] : ((value[0] * delta + value[1]) * delta + value[2]) * delta + value[3];
    }
    const next = curve.keys[index + 1];
    return next && next[0] > start ? value + (next[1] - value) * Math.min(1, delta / (next[0] - start)) : value;
  }

  function findHand(actor, path) {
    const bones = (actor.rig?.bones || []).filter((bone) => bone.path === path ||
      (typeof bone.path === "string" && bone.path.endsWith("/" + path)));
    if (bones.length !== 1) return null;
    let hand = null;
    actor.root.traverse((node) => {
      if (node.userData.elichika_node === bones[0].node) hand = node;
    });
    return hand;
  }

  function deformation(root, limit) {
    const geometries = new Set(), updates = [];
    root.traverse((node) => {
      if (!node.isMesh) return;
      const geometry = node.geometry, positions = geometry.attributes.position;
      const uv = geometry.attributes._mv_fan_uv;
      if (!positions || !uv || positions.count !== uv.count || uv.itemSize !== 2) return;
      // Fan blades can move beyond the folded mesh's original bounds.
      node.frustumCulled = false;
      if (geometries.has(geometry)) return;
      geometries.add(geometry);
      const original = new Float32Array(positions.count * 3), limits = new Float32Array(positions.count);
      for (let index = 0; index < positions.count; index++) {
        original[index * 3] = positions.getX(index);
        original[index * 3 + 1] = positions.getY(index);
        original[index * 3 + 2] = positions.getZ(index);
        limits[index] = limit - Math.abs(uv.getX(index)) * 512;
      }
      updates.push({ positions, original, limits });
    });
    let previous;
    return updates.length ? (angle) => {
      angle = Math.fround(Math.max(angle, 0));
      if (angle === previous) return;
      previous = angle;
      for (const { positions, original, limits } of updates) {
        for (let index = 0; index < positions.count; index++) {
          const theta = Math.min(limits[index], angle) * radians;
          const sine = Math.sin(theta), cosine = Math.cos(theta), offset = index * 3;
          const x = original[offset], z = original[offset + 2];
          // The exported geometry mirrors Unity's X coordinate.
          positions.setXYZ(index, cosine * x - sine * z, original[offset + 1], sine * x + cosine * z);
        }
        positions.needsUpdate = true;
      }
    } : null;
  }

  function create(root, spec) {
    if (spec?.kind !== "fan" || !Number.isFinite(spec.limit) || !Number.isFinite(spec.defaultAngle) ||
        typeof spec.bone !== "string" || !Array.isArray(spec.activation) || !spec.curves) return null;
    const deform = deformation(root, spec.limit);
    if (!deform) return null;
    let owner = null, motion = null, activation = [];
    root.visible = false;
    function detach(actor = owner) {
      if (!owner || actor !== owner) return;
      if (root.parent) root.parent.remove(root);
      owner = null;
      root.visible = false;
    }
    return {
      bind(actor) {
        if (owner === actor) return;
        detach();
        const hand = actor && findHand(actor, spec.bone);
        if (!hand) return;
        owner = actor;
        hand.add(root);
      },
      detach,
      setTracks(tracks) {
        motion = tracks.find((track) => track.id === spec.track && !track.muted) || null;
        activation = tracks.filter((track) => spec.activation.includes(track.id) && !track.muted);
      },
      evaluate(time) {
        root.visible = !!owner && (activation.length
          ? activation.some((track) => track.events.some((event) => active(event, time))) : !!spec.defaultVisible);
        if (!root.visible) return;
        const event = motion?.events.find((candidate) => active(candidate, time) && spec.curves[candidate.id]);
        if (!event) {
          deform(spec.defaultAngle);
          return;
        }
        const curve = spec.curves[event.id], timing = event.values || {};
        if (curve.mode !== "constant" && (!Array.isArray(curve.keys) || !curve.keys.length)) {
          deform(spec.defaultAngle);
          return;
        }
        const sourceTime = curve.first + (timing.clipIn || 0) + (time - event.start) * (timing.timeScale ?? 1);
        const angle = sample(curve, Math.max(curve.first, Math.min(curve.last, sourceTime)));
        deform(Number.isFinite(angle) ? angle : spec.defaultAngle);
      }
    };
  }

  global.MVStudioProps = { create };
})(window);
