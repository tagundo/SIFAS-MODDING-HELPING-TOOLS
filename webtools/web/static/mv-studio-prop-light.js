(function (global) {
  "use strict";

  const propBinding = /^\/EntryPoint\/Live\/Members\/ske_[A-Za-z0-9_]+\/Member([1-9])\/Model\/(?:[A-Za-z0-9_]+\/)+chp[0-9]+$/;

  function uniqueTrack(tracks, nativeClass) {
    const matches = tracks.filter(track => track.nativeClass === nativeClass);
    return matches.length === 1 ? matches[0] : null;
  }

  function* inputs(project, track, clipClass, seconds) {
    const {nativeWeight, memberColor} = global.MVStudioLighting;
    for (const event of track.events) {
      const value = event?.values;
      if (value?.playableClass !== clipClass || !Number.isFinite(event.start) ||
          !Number.isFinite(event.duration) || event.duration <= 0) continue;
      const weight = nativeWeight(event, seconds);
      if (!(weight > 0)) continue;
      const color = memberColor(project, value.colorSpecifiedType, value.memberPosition, value.color);
      if (color) yield {value, color, weight};
    }
  }

  function ambientAt(project, track, seconds) {
    const ambient = [0, 0, 0, 0], inverseTint = [0, 0, 0, 0];
    let active = false;
    for (const {value, color, weight} of inputs(project, track, "LivePropAmbientClip", seconds)) {
      const tint = [value.tintColor?.r, value.tintColor?.g, value.tintColor?.b, value.tintColor?.a];
      if (!tint.every(Number.isFinite)) continue;
      active = true;
      for (let channel = 0; channel < 4; channel++) {
        ambient[channel] += color[channel] * weight;
        inverseTint[channel] += (1 - tint[channel]) * weight;
      }
    }
    return active ? {ambient, tint: inverseTint.map(channel => 1 - channel)} : null;
  }

  function rimAt(project, track, seconds) {
    const color = [0, 0, 0, 0], direction = [0, 0, 0, 0];
    let intensity = 0, sharpness = 0, active = false;
    for (const {value, color: source, weight} of inputs(project, track, "LivePropRimlightClip", seconds)) {
      const axis = [value.direction?.x, value.direction?.y, value.direction?.z];
      if (![value.intensity, value.sharpness, ...axis].every(Number.isFinite)) continue;
      active = true;
      intensity += value.intensity * weight;
      sharpness += value.sharpness * weight;
      for (let channel = 0; channel < 4; channel++) color[channel] += source[channel] * weight;
      for (let index = 0; index < 3; index++) direction[index] += axis[index] * weight;
    }
    // Native direction is already in the view coordinates used by the prop shader.
    return active ? {color, intensity, power: 1 + sharpness, direction} : {intensity: 0};
  }

  function create(binding, member) {
    if (typeof binding !== "string" || binding.length > 512 || !Number.isInteger(member) ||
        Number(propBinding.exec(binding)?.[1]) !== member) return null;
    let project, ambientTrack, rimTrack;
    return {
      setProject(value) {
        project = value;
        const tracks = (project?.tracks || []).filter(track => track?.binding === binding && Array.isArray(track.events));
        ambientTrack = uniqueTrack(tracks, "LivePropAmbientTrack");
        rimTrack = uniqueTrack(tracks, "LivePropRimlightTrack");
      },
      sample(seconds) {
        if (!project || !Number.isFinite(seconds) || !global.MVStudioLighting) return null;
        const settings = project.quality?.values;
        const ambient = settings?.prop_ambient !== false && ambientTrack && !ambientTrack.muted &&
          ambientTrack.binding === binding && ambientAt(project, ambientTrack, seconds);
        const rim = settings?.prop_rim_light !== false && rimTrack && !rimTrack.muted && rimTrack.binding === binding
          ? rimAt(project, rimTrack, seconds) : {intensity: 0};
        // Track mute and gaps restore the native component's zero rim intensity.
        return {...ambient, rim};
      },
    };
  }

  global.MVStudioPropLight = {create};
})(typeof window !== "undefined" ? window : globalThis);
