(function (global) {
  "use strict";

  const kinds = { translation: "position", rotation: "quaternion", euler: "quaternion", scale: "scale", visibility: "visible",
    overlayTint: "overlayTint", overlayUV: "overlayUV" };
  const clamp = (x, low, high) => Math.min(high, Math.max(low, x));
  const number = (value, fallback) => Number.isFinite(value) ? value : fallback;
  const modulo = (x, divisor) => ((x % divisor) + divisor) % divisor;

  function clipTime(event, mix, time) {
    const { start, duration, values } = event;
    if (!Number.isFinite(start) || !(duration > 0) || !Number.isFinite(duration)) return null;
    let local = time - start;
    const pre = local < 0;
    const post = time >= start + duration;
    if (pre || post) {
      const mode = pre ? values.preExtrapolationMode : values.postExtrapolationMode;
      const limit = pre
        ? mix.preInfinite ? Infinity : values.preExtrapolationTime
        : mix.postInfinite ? Infinity : values.postExtrapolationTime;
      if (!mode || !(limit > 0) || (pre ? -local > limit : local - duration >= limit)) return null;
      if (mode === 1) local = pre ? 0 : duration;
      else if (mode === 2) local = pre ? duration - ((-local) % duration) : local % duration;
      else if (mode === 3) {
        const phase = modulo(local, 2 * duration);
        local = duration - Math.abs(phase - duration);
      } else if (mode !== 4) return null;
    }
    return local * number(values.timeScale, 1) + number(values.clipIn, 0);
  }

  function evaluate(curve, time) {
    const [mode, keys] = curve;
    if (mode === "constant") return keys;
    let left = 0, right = keys.length;
    while (left + 1 < right) {
      const middle = (left + right) >> 1;
      if (keys[middle][0] <= time) left = middle;
      else right = middle;
    }
    const [start, value] = keys[left], next = keys[left + 1];
    if (mode === "cubic") {
      if (Math.abs(start) > 1e20) return value[3];
      const delta = Math.max(0, time - start);
      return ((value[0] * delta + value[1]) * delta + value[2]) * delta + value[3];
    }
    if (next && next[0] > start) return value + (next[1] - value) * clamp((time - start) / (next[0] - start), 0, 1);
    return value;
  }

  function validCurve(curve) {
    if (!Array.isArray(curve)) return false;
    const [mode, keys] = curve;
    if (mode === "constant") return Number.isFinite(keys);
    return (mode === "linear" || mode === "cubic") && Array.isArray(keys) && keys.length > 0 &&
      keys.every((pair) => Array.isArray(pair) && Number.isFinite(pair[0]) &&
        (mode === "linear" ? Number.isFinite(pair[1]) :
          Array.isArray(pair[1]) && pair[1].length === 4 && pair[1].every(Number.isFinite)));
  }

  function activationTarget(track, group, stageMotion) {
    if (track.nativeClass !== "ActivationTrack" || !Object.hasOwn(stageMotion?.activations || {}, track.id)) return null;
    const original = group.nodes.get(0), ids = stageMotion.activations[track.id];
    if (!original || !Array.isArray(ids)) return null;
    const allowed = new Set(ids);
    return { node: original, base: original.userData.mvStageNode.active, track,
      events: track.events.filter((event) => allowed.has(event.id)) };
  }

  function apply(T, root) {
    const groups = new Map();
    root.traverse((node) => {
      const data = node.userData.mvStageNode;
      if (typeof data?.active !== "boolean") return;
      node.visible = data.active;
      if (typeof data.binding !== "string" || !Number.isInteger(data.path)) return;
      if (!groups.has(data.binding)) groups.set(data.binding, { nodes: new Map(), channels: new Map(), events: [] });
      const group = groups.get(data.binding);
      group.nodes.set(data.path, group.nodes.has(data.path) ? null : node);
    });
    if (!groups.size) return null;

    const euler = new T.Euler(0, 0, 0, "YXZ"), quaternion = new T.Quaternion();
    const radians = Math.PI / 180;
    let stageMotion, sourceTracks;
    function restore(channel) {
      const { node, kind, base, value, material } = channel;
      if (kind === "visible") node.visible = base;
      else {
        value.copy(base);
        if (!material) node.updateMatrix();
      }
    }

    function bind(project) {
      for (const [binding, group] of groups) {
        for (const channel of group.channels.values()) if (channel.changed) restore(channel);
        group.channels.clear();
        group.events.length = 0;
        if (group.activation) group.activation.node.visible = group.activation.base;
        if (group.animation?.node) group.animation.node.visible = group.animation.node.userData.mvStageNode.active;
        group.animation = null;
        const tracks = (project?.tracks || []).filter((track) => track.binding === binding);
        const activations = tracks.map((track) => activationTarget(track, group, stageMotion)).filter(Boolean);
        group.activation = activations.length === 1 ? activations[0] : null;
        const animations = tracks.filter((track) => track.nativeClass === "AnimationTrack");
        if (animations.length !== 1) continue;
        const track = animations[0];
        group.animation = { node: group.nodes.get(0), quality: stageMotion?.quality?.[track.id] };
        for (const event of track.events || []) {
          if (!event.values || !Object.hasOwn(stageMotion?.mix || {}, event.id)) continue;
          const clip = stageMotion.clips?.[event.values.animation], mix = stageMotion.mix[event.id];
          if (!clip || !mix || !Array.isArray(clip.channels) || !Number.isFinite(clip.start) ||
              !Number.isFinite(clip.duration) || clip.duration < 0) continue;
          const samples = [];
          for (const source of clip.channels) {
            if (!Object.hasOwn(kinds, source.kind)) continue;
            const kind = kinds[source.kind], node = group.nodes.get(source.path);
            const material = kind === "overlayTint" || kind === "overlayUV";
            const value = material ? node?.userData.mvStageOverlayChannels?.[kind] : node?.[kind];
            if (!node || !Array.isArray(source.curves) || !source.curves.every(validCurve) ||
                (material && !value) ||
                source.curves.length !== (kind === "visible" ? 1 : material || source.kind === "rotation" ? 4 : 3)) continue;
            const id = `${source.path}:${kind}`;
            if (!group.channels.has(id)) group.channels.set(id, {
              node, kind, value, material, base: kind === "visible" ? value : value.clone(),
              sum: kind === "visible" ? 0 : value.clone(), weight: 0, changed: false,
            });
            samples.push({ source, target: group.channels.get(id), values: new Array(source.curves.length) });
          }
          group.events.push({ track, event, clip, mix, samples });
        }
      }
    }

    function sample({ source, target, values }, time, weight) {
      for (let i = 0; i < values.length; i++) values[i] = evaluate(source.curves[i], time);
      if (target.kind === "visible") target.sum += values[0] * weight;
      else if (target.kind === "quaternion") {
        if (source.kind === "euler") quaternion.setFromEuler(euler.set(values[0] * radians, -values[1] * radians, -values[2] * radians));
        else {
          quaternion.set(values[0], -values[1], -values[2], values[3]);
          if (!(quaternion.lengthSq() > 0)) return;
          quaternion.normalize();
        }
        if (target.weight > 0) target.sum.slerp(quaternion, weight / (target.weight + weight));
        else target.sum.copy(quaternion);
      } else {
        target.sum.x += values[0] * weight * (source.kind === "translation" ? -1 : 1);
        target.sum.y += values[1] * weight;
        target.sum.z += values[2] * weight;
        if (target.material) target.sum.w += values[3] * weight;
      }
      target.weight += weight;
    }

    function update(time, project) {
      if (project?.stageMotion !== stageMotion || project?.tracks !== sourceTracks) {
        stageMotion = project?.stageMotion;
        sourceTracks = project?.tracks;
        bind(project);
      }
      const quality = project?.quality?.values || {};
      for (const group of groups.values()) {
        const enabled = quality[group.animation?.quality] !== false;
        if (group.animation?.node) group.animation.node.visible = enabled && group.animation.node.userData.mvStageNode.active;
        for (const channel of group.channels.values()) {
          channel.weight = 0;
          if (channel.kind === "visible") channel.sum = 0;
          else if (channel.kind !== "quaternion") channel.sum.set(0, 0, 0, 0);
        }
        if (enabled) for (const input of group.events) {
          const { track, event, clip, mix, samples } = input;
          if (track.muted) continue;
          const local = clipTime(event, mix, time);
          if (local === null) continue;
          const timing = { ...event.values, mixIn: mix.mixIn, mixOut: mix.mixOut,
            postExtrapolationTime: mix.postInfinite ? Number.MAX_VALUE : event.values.postExtrapolationTime,
            preExtrapolationTime: mix.preInfinite ? Number.MAX_VALUE : event.values.preExtrapolationTime };
          const weight = global.MVStudioLighting.nativeWeight({ ...event, values: timing }, time);
          if (!(weight > 0)) continue;
          const seconds = clip.loop && clip.duration > 0 ? modulo(local, clip.duration) : clamp(local, 0, clip.duration);
          for (const row of samples) sample(row, clip.start + seconds, weight);
        }
        for (const channel of group.channels.values()) {
          if (!channel.weight) {
            if (channel.changed) restore(channel);
            channel.changed = false;
            continue;
          }
          const { node, kind, base, sum, weight, value, material } = channel, remainder = Math.max(0, 1 - weight);
          if (kind === "visible") node.visible = (sum + Number(base) * remainder) / (weight + remainder) > .5;
          else {
            if (kind === "quaternion") value.copy(base).slerp(sum, weight / (weight + remainder));
            else value.copy(sum).addScaledVector(base, remainder).multiplyScalar(1 / (weight + remainder));
            if (!material) node.updateMatrix();
          }
          channel.changed = true;
        }
        const activation = group.activation;
        if (activation) {
          const { node, base, track, events } = activation;
          node.visible = track.muted ? base :
            events.some((event) => time >= event.start && time < event.start + event.duration);
        }
      }
    }

    return { update };
  }

  global.MVStudioStageMotion = { apply, clipTime };
})(typeof window !== "undefined" ? window : globalThis);
