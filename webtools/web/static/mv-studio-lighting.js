(function (global) {
  "use strict";

  const white = [1, 1, 1, 1];
  const memberBinding = /^\/EntryPoint\/Live\/Members\/Member([1-9][0-9]*)$/;
  const baseBinding = "/EntryPoint/Live/Global/LiveBaseLightReciever";

  function rgba(value) {
    const channels = Array.isArray(value) ? value : [value?.r, value?.g, value?.b, value?.a];
    return channels.length === 4 && channels.every(Number.isFinite) ? channels : null;
  }

  function memberColor(project, type, slot, value) {
    const channels = rgba(value);
    if (!channels) return null;
    if (type === 0) return channels;
    if (type !== 1 && type !== 2) return [0, 0, 0, 0];
    const theme = type === 1
      ? project.performers?.find((actor) => actor.position === slot)?.themeColor ?? project.stage?.memberThemeColors?.[slot]
      : project.stage?.originalMemberThemeColors?.[slot];
    const color = rgba(theme);
    return color ? multiply(channels, color) : null;
  }

  function finite(value, fallback) {
    return Number.isFinite(value) ? value : fallback;
  }

  function fade(keys, t, rising) {
    const smooth = t * t * (3 - 2 * t);
    const fallback = rising ? smooth : 1 - smooth;
    return Math.max(0, Math.min(1, global.ViewerMotionTimeline?.curve(keys, t, fallback) ?? fallback));
  }

  function nativeWeight(event, time) {
    const v = event.values;
    let local = time - event.start;
    if (local < 0) {
      if (!v.preExtrapolationMode || local < -finite(v.preExtrapolationTime, 0)) return 0;
      local = 0;
    } else if (local >= event.duration) {
      if (!v.postExtrapolationMode || local >= event.duration + finite(v.postExtrapolationTime, 0)) return 0;
      local = event.duration;
    }
    const incoming = v.blendIn > 0 ? v.blendIn : v.easeIn;
    const outgoing = v.blendOut > 0 ? v.blendOut : v.easeOut;
    const left = incoming > 0 && local < incoming ? fade(v.mixIn, local / incoming, true) : 1;
    const right = outgoing > 0 && local > event.duration - outgoing
      ? fade(v.mixOut, (local - event.duration + outgoing) / outgoing, false) : 1;
    return left * right;
  }

  // UtilColor.CheckSame (0x2960e4c) is true when the squared RGBA distance of two
  // colors is below 1e-5 (the float at 0x56f60fc). The ambient components
  // (LiveCoreMemberAmbient.ApplyAmbientColor 0x2f670cc and ApplyTintColor,
  // LiveCoreStageAmbient.ApplyAmbientColor/ApplyTintColor 0x2f70788/ApplyBlendColor,
  // and their ApplyDefault* writers) compare the new color with the one they last
  // wrote and skip Material.SetColor when CheckSame holds, so a slowly changing
  // color stays at the last written value until it moves by sqrt(1e-5). The
  // material therefore depends on the rendered frames: `frames` is the scene's
  // frame clock ({advancing, history}); an advancing frame continues the held
  // color, otherwise the history (earlier rendered frame times, ascending) is
  // replayed from an unwritten component and an empty history writes the exact
  // color. valueAt(time) returns the component's color at that time or null when
  // it writes nothing (the hold then restarts).
  const HOLD_EPSILON = Math.fround(1e-5);

  function holdStep(hold, color) {
    if (!rgba(color)) {
      hold.color = null;
      return color;
    }
    let distance = 0;
    if (hold.color) for (let channel = 0; channel < 4; channel++) distance += (color[channel] - hold.color[channel]) ** 2;
    if (!hold.color || distance >= HOLD_EPSILON) hold.color = color.slice(0, 4);
    return hold.color;
  }

  function heldColor(hold, valueAt, seconds, frames) {
    if (!frames?.advancing) {
      hold.color = null;
      for (const time of frames?.history || []) holdStep(hold, valueAt(time));
    }
    return holdStep(hold, valueAt(seconds));
  }

  function multiply(a, b) { return a.map((channel, index) => channel * b[index]); }

  function add(target, source, weight) {
    for (let i = 0; i < target.length; i++) target[i] += source[i] * weight;
  }

  function emptyRim() {
    return { color: [0, 0, 0, 0], intensity: 0, sharpness: 0, direction: [0, 0, 0, 0] };
  }

  function addRim(rim, color, intensity, sharpness, direction, weight) {
    if (color) add(rim.color, color, weight);
    rim.intensity += finite(intensity, 0) * weight;
    rim.sharpness += finite(sharpness, 0) * weight;
    add(rim.direction, [finite(direction?.x, 0), finite(direction?.y, 0), finite(direction?.z, 0), 0], weight);
  }

  function mixRim(project, track, seconds) {
    const rim = emptyRim();
    let active = false;
    for (const event of track.events) {
      const value = event.values;
      if (value?.playableClass !== "LiveRimlightClip") continue;
      const weight = nativeWeight(event, seconds);
      if (weight <= 0) continue;
      const color = memberColor(project, value.colorSpecifiedType, value.memberPosition, value.color);
      if (!color) continue;
      addRim(rim, color, value.intensity, value.sharpness, value.direction, weight);
      active = true;
    }
    return active ? rim : null;
  }

  function memberRim(base, local, hasTrack) {
    if (!base && !local) return hasTrack ? { intensity: 0 } : null;
    const direction = (base?.direction || local.direction).map((value, index) =>
      base && local ? value + local.direction[index] : value);
    return {
      color: base && local ? multiply(base.color, local.color) : (base || local).color,
      intensity: (base?.intensity ?? 0) + (local?.intensity ?? 0),
      power: 1 + (base?.sharpness ?? 0) + (local?.sharpness ?? 0),
      direction,
    };
  }

  function mixBase(project, track, seconds) {
    const ambient = [0, 0, 0, 0], tint = [0, 0, 0, 0], rim = emptyRim();
    let active = false;
    for (const event of track.events) {
      const value = event.values;
      if (value?.playableClass !== "LiveBaseLightClip") continue;
      const weight = nativeWeight(event, seconds);
      if (weight <= 0) continue;
      const light = memberColor(project, value.ambientColorType, value.ambientMemberPosition, value.ambientColor);
      const shade = memberColor(project, value.ambientColorType, value.ambientMemberPosition, value.ambientTintColor);
      if (!light || !shade) continue;
      add(ambient, light, weight);
      add(tint, shade, weight);
      addRim(rim, memberColor(project, value.rimlightColorType, value.rimlightMemberPosition, value.rimlightColor),
        value.rimlightIntensity, value.rimlightSharpness, value.rimlightDirection, weight);
      active = true;
    }
    return active ? { ambient, tint, rim } : null;
  }

  function mixMember(project, track, seconds, base) {
    const ambient = [0, 0, 0, 0], inverseTint = [0, 0, 0, 0];
    let active = false;
    for (const event of track.events) {
      const value = event.values;
      if (value?.playableClass !== "LiveMemberAmbientClip") continue;
      const weight = nativeWeight(event, seconds);
      if (weight <= 0) continue;
      const light = memberColor(project, value.colorSpecifiedType, value.memberPosition, value.color);
      const tint = rgba(value.tintColor);
      if (!light || !tint) continue;
      add(ambient, light, weight);
      add(inverseTint, tint.map(channel => 1 - channel), weight);
      active = true;
    }
    if (!active) return { ambient: base?.ambient, tint: null };
    return {
      ambient: base ? multiply(base.ambient, ambient) : ambient,
      tint: multiply(base?.tint || white, inverseTint.map(channel => 1 - channel)),
    };
  }

  function sample(project, seconds) {
    const settings = project?.quality?.values || {};
    const tracks = project?.tracks || [];
    const baseTrack = settings.base_light !== false && tracks.find(track => !track.muted &&
      track.nativeClass === "LiveBaseLightTrack" && track.binding === baseBinding);
    const base = baseTrack ? mixBase(project, baseTrack, seconds) : null;
    const ambient = new Map(), rim = new Map();
    for (const track of tracks) {
      if (track.muted) continue;
      const position = Number(memberBinding.exec(track.binding)?.[1]);
      if (!position) continue;
      if (settings.member_ambient !== false && track.nativeClass === "LiveMemberAmbientTrack") {
        ambient.set(position, mixMember(project, track, seconds, base));
      }
      if (settings.member_rim_light !== false && track.nativeClass === "LiveRimlightTrack") {
        rim.set(position, mixRim(project, track, seconds));
      }
    }
    return {
      // LiveBaseLightReciever also writes the ambient components (through the same
      // CheckSame-gated ApplyBase*Color). Which mixer writes last in a frame is not
      // established, so the holds are not applied while a base light track exists
      // (an unevidenced choice: the colors stay exact).
      baseTrack: !!baseTrack,
      baseAmbient: base?.ambient ?? null, baseTint: base?.tint || white,
      member(position) {
        if (!base && !ambient.has(position) && !rim.has(position)) return null;
        const appearance = ambient.get(position) || base;
        return { ambient: appearance?.ambient, tint: appearance?.tint,
          rim: memberRim(base?.rim, rim.get(position), rim.has(position)) };
      },
    };
  }

  global.MVStudioLighting = { nativeWeight, memberColor, sample, heldColor, HOLD_EPSILON };
})(typeof window !== "undefined" ? window : globalThis);
