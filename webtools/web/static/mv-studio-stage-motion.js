(function (global) {
  "use strict";

  const kinds = { translation: "position", rotation: "quaternion", euler: "quaternion", scale: "scale", visibility: "visible",
    overlayTint: "overlayTint", overlayUV: "overlayUV", overlayColor: "overlayColor", overlayScalar: "overlayScalar",
    overlayAmbient: "overlayAmbient" };
  const materialKinds = new Set(["overlayTint", "overlayUV", "overlayColor", "overlayScalar", "overlayAmbient"]);
  // Unity RotationOrder (0 XYZ ... 4 ZXY, the default) -> three.js Euler order. Unity
  // names the axes in the order they apply (XYZ: q = qZ*qY*qX); three.js names
  // the product left to right, so the string reverses. The X mirror keeps it.
  const eulerOrders = ["ZYX", "YZX", "XZY", "ZXY", "YXZ", "XYZ"];
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

  function sampleTime(clip, local) {
    const seconds = clip.loop && clip.duration > 0 ? modulo(local, clip.duration) : clamp(local, 0, clip.duration);
    const duration = Math.fround(clip.duration);
    // The native AnimationClipPlayable sends a normalized float that the
    // packed curves convert back to local seconds in float32.
    return clip.sampleTimeF32 === true && duration > 0
      ? Math.fround(Math.fround(Math.fround(seconds / duration) * duration) + Math.fround(clip.start))
      : clip.start + seconds;
  }

  function weightedEvent(event, mix) {
    return { ...event, values: { ...event.values, mixIn: mix.mixIn, mixOut: mix.mixOut,
      postExtrapolationTime: mix.postInfinite ? Number.MAX_VALUE : event.values.postExtrapolationTime,
      preExtrapolationTime: mix.preInfinite ? Number.MAX_VALUE : event.values.preExtrapolationTime } };
  }

  function nativeActive(value) {
    // The native Animator's GameObject binding converts a float to bool.
    return Math.abs(Math.fround(value)) > Math.fround(.001);
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

  function materialValue(node, source, scope, requiresMaterial) {
    const { kind, rendererClass, property } = source;
    if (kind === "overlayColor" || kind === "overlayScalar") {
      if (scope !== "world" || (rendererClass !== undefined && rendererClass !== 23)) return;
      const color = kind === "overlayColor";
      const value = global.MVStudioSoftBillboards?.materialChannel?.(node, kind, color ? "_Color" : property);
      if (color ? value?.isVector4 : Number.isFinite(value?.value)) return value;
      // A world MeshRenderer scalar of its own stage material (AS/Blend/Opaque _BlendRate).
      const own = color ? null : global.MVStudioStageMaterial?.materialChannel?.(node, kind, property);
      if (Number.isFinite(own?.value)) return own;
      return;
    }
    if (requiresMaterial) {
      const overlay = global.MVStudioStageOverlay?.materialChannel?.(node, kind, rendererClass, scope);
      if (overlay || scope !== "world" || rendererClass !== undefined) return overlay;
      // A world MeshRenderer without an overlay pass: its own stage material.
      return global.MVStudioStageMaterial?.materialChannel?.(node, kind, property);
    }
    if (rendererClass === undefined) return node.userData.mvStageOverlayChannels?.[kind];
  }

  function apply(T, root) {
    const groups = new Map(), acceptedEvents = new Set();
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
      else if (kind === "overlayScalar") value.value = base;
      else {
        value.copy(base);
        if (!material) node.updateMatrix();
      }
    }

    function bind(project) {
      acceptedEvents.clear();
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
          const materialScope = mix.materialScope === undefined ? "overlay" : mix.materialScope;
          if (materialScope !== "overlay" && materialScope !== "world") continue;
          const particleColors = clip.particleStartColors;
          if (particleColors !== undefined) {
            if (materialScope !== "world" || !Array.isArray(particleColors) || !particleColors.length ||
                !particleColors.every(row => group.nodes.get(row?.path) &&
                  Array.isArray(row.curves) && [3, 4].includes(row.curves.length) && row.curves.every(validCurve) &&
                  global.MVStudioStageLaserCores?.hasEmitter?.(group.nodes.get(row.path))) ||
                new Set(particleColors.map(row => row.path)).size !== particleColors.length) continue;
          }
          const samples = [], targets = [];
          if (materialScope !== "world" && clip.channels.some(row => row?.kind === "overlayColor" || row?.kind === "overlayScalar")) continue;
          const requiresMaterial = clip.requiresOverlayMaterial === true || materialScope === "world";
          for (const source of clip.channels) {
            if (!Object.hasOwn(kinds, source?.kind)) continue;
            const kind = kinds[source.kind], node = group.nodes.get(source.path);
            const material = materialKinds.has(kind), numeric = kind === "visible" || kind === "overlayScalar";
            if (!node || !Array.isArray(source.curves) || !source.curves.every(validCurve) ||
                source.curves.length !== (numeric ? 1 : material || source.kind === "rotation" ? 4 : 3) ||
                (source.kind === "euler" && source.rotationOrder !== undefined && !(Number.isInteger(source.rotationOrder) &&
                  eulerOrders[source.rotationOrder]))) continue;
            const value = material ? materialValue(node, source, materialScope, requiresMaterial) : node[kind];
            if (material && !value) continue;
            targets.push({source, kind, node, material, numeric, value});
          }
          // A missing material target must not leave a partial animation.
          if (requiresMaterial && (targets.length !== clip.channels.length || !targets.some(target => target.material))) continue;
          for (const {source, kind, node, material, numeric, value} of targets) {
            const id = material ? value : `${source.path}:${kind}`;
            if (!group.channels.has(id)) group.channels.set(id, {
              node, kind, value, material, numeric,
              base: kind === "overlayScalar" ? value.value : numeric ? value : value.clone(),
              nativeVisibility: clip.sampleTimeF32 === true &&
                (requiresMaterial || group.animation.quality === "stage_display" && source.visibilityType === "gameObject" ||
                  binding === "/EntryPoint/Live/Stages/MainStage/Effect/fx_par_so2056_05/root"),
              sum: numeric ? 0 : value.clone(), weight: 0, changed: false,
            });
            samples.push({ source, target: group.channels.get(id), values: new Array(source.curves.length) });
          }
          group.events.push({ track, event, clip, mix, samples });
          acceptedEvents.add(event);
        }
      }
    }

    function sample({ source, target, values }, time, weight) {
      for (let i = 0; i < values.length; i++) values[i] = evaluate(source.curves[i], time);
      if (target.numeric) target.sum += values[0] * weight;
      else if (target.kind === "quaternion") {
        if (source.kind === "euler") quaternion.setFromEuler(euler.set(values[0] * radians, -values[1] * radians, -values[2] * radians,
          eulerOrders[source.rotationOrder ?? 4]));
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
          if (channel.numeric) channel.sum = 0;
          else if (channel.kind !== "quaternion") channel.sum.set(0, 0, 0, 0);
        }
        if (enabled) for (const input of group.events) {
          const { track, event, clip, mix, samples } = input;
          if (track.muted) continue;
          const local = clipTime(event, mix, time);
          if (local === null) continue;
          const weight = global.MVStudioLighting.nativeWeight(weightedEvent(event, mix), time);
          if (!(weight > 0)) continue;
          const curveTime = sampleTime(clip, local);
          for (const row of samples) sample(row, curveTime, weight);
        }
        for (const channel of group.channels.values()) {
          if (!channel.weight) {
            if (channel.changed) restore(channel);
            channel.changed = false;
            continue;
          }
          const { node, kind, base, sum, weight, value, material } = channel, remainder = Math.max(0, 1 - weight);
          if (kind === "visible") {
            const active = (sum + Number(base) * remainder) / (weight + remainder);
            node.visible = channel.nativeVisibility ? nativeActive(active) : active > .5;
          } else if (kind === "overlayScalar") value.value = (sum + base * remainder) / (weight + remainder);
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

    // The material values an AnimationTrack curve drives (a MaterialPropertyBlock in the game), read-only.
    function curveTargets() {
      const result = new Set();
      for (const group of groups.values()) for (const channel of group.channels.values()) if (channel.material) result.add(channel.value);
      return result;
    }

    return { update, curveTargets, accepts: event => acceptedEvents.has(event) };
  }

  global.MVStudioStageMotion = { apply, clipTime, evaluate, nativeActive, sampleTime, validCurve, weightedEvent };
})(typeof window !== "undefined" ? window : globalThis);
