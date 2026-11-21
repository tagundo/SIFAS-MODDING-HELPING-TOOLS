(function (global) {
  "use strict";

  const binding = /^\/EntryPoint\/Live\/Cameras\/MainCamera\/Flares\/Flare([1-3])$/;
  const product = (a, b) => Math.fround(a * b);
  const add = (a, b) => Math.fround(a + b);

  function mix(project, track, time, lighting) {
    const color = [0, 0, 0], center = [0, 0];
    let intensity = 0, smoothness = 0, roundness = 0, largest = 0, rounded = 0;
    for (const event of track.events) {
      const value = event.values;
      if (value?.playableClass !== "LiveFlareClip" || ![value.center?.x, value.center?.y, value.intensity,
        value.smoothness, value.roundness].every(Number.isFinite)) continue;
      const weight = Math.fround(lighting.nativeWeight(event, time));
      if (!(weight > 0)) continue;
      const tint = lighting.memberColor(project, value.colorSpecifiedType, value.memberPosition, value.color);
      if (!tint) continue;
      for (let channel = 0; channel < color.length; channel++) color[channel] = add(color[channel], product(tint[channel], weight));
      center[0] = add(center[0], product(value.center.x, weight));
      center[1] = add(center[1], product(value.center.y, weight));
      intensity = add(intensity, product(value.intensity, weight));
      smoothness = add(smoothness, product(value.smoothness, weight));
      roundness = add(roundness, product(value.roundness, weight));
      if (weight > largest) {
        largest = weight;
        rounded = value.rounded === true || value.rounded === 1 ? 1 : 0;
      }
    }
    // FlareComponent.Prepare packs these coefficients for the original Uber pass.
    const settings = [product(intensity, 3), product(smoothness, 5), add(roundness, product(Math.fround(1 - roundness), 6)), rounded];
    return settings[0] !== 0 && settings[1] > 0 && settings[2] > 0 && [...settings, ...color, ...center].every(Number.isFinite)
      ? { color, center, settings } : null;
  }

  function sample(project, time) {
    const lighting = global.MVStudioLighting;
    if (project?.quality?.values?.posteffect !== true || !lighting?.nativeWeight || !lighting?.memberColor) return null;
    const tracks = [null, null, null], duplicates = new Set();
    for (const track of project.tracks || []) {
      if (track.muted || track.nativeClass !== "LiveFlareTrack") continue;
      const match = binding.exec(track.binding || "");
      if (!match || !Array.isArray(track.events)) continue;
      const index = Number(match[1]) - 1;
      if (tracks[index]) duplicates.add(index);
      else tracks[index] = track;
    }
    const values = tracks.map((track, index) => track && !duplicates.has(index) ? mix(project, track, time, lighting) : null);
    return values.some(Boolean) ? values : null;
  }

  function uniforms(T) {
    return {
      mvFlareColor: { value: Array.from({ length: 3 }, () => new T.Vector3()) },
      mvFlareCenter: { value: Array.from({ length: 3 }, () => new T.Vector2()) },
      mvFlareSettings: { value: Array.from({ length: 3 }, () => new T.Vector4(0, 1, 1, 0)) },
      mvFlareAspect: { value: 1 },
    };
  }

  function apply(_T, target, data, width, height) {
    target.mvFlareAspect.value = width > 0 && height > 0 ? width / height : 1;
    for (let index = 0; index < 3; index++) {
      const values = data?.[index], settings = target.mvFlareSettings.value[index];
      if (values) {
        settings.fromArray(values.settings);
        target.mvFlareColor.value[index].fromArray(values.color);
        target.mvFlareCenter.value[index].fromArray(values.center);
      } else settings.set(0, 1, 1, 0);
    }
  }

  const fragment = `
    uniform mediump vec3 mvFlareColor[3];
    uniform mediump vec2 mvFlareCenter[3];
    uniform mediump vec4 mvFlareSettings[3];
    uniform float mvFlareAspect;
    vec3 nativeFlare(vec3 color, vec2 uv) {
      for (int index = 0; index < 3; index++) {
        mediump vec4 settings = mvFlareSettings[index];
        if (settings.x == 0.0) continue;
        vec2 delta = abs(uv - mvFlareCenter[index]);
        delta.x *= mix(1.0, mvFlareAspect, settings.w);
        mediump vec2 shape = pow(delta, vec2(settings.z));
        mediump float falloff = pow(1.0 - min(dot(shape, shape), 1.0), settings.y);
        color += mvFlareColor[index] * (falloff * settings.x);
      }
      return color;
    }
    vec3 nativeFlare(vec2 uv) { return nativeFlare(vec3(0.0), uv); }
  `;

  global.MVStudioFlare = { sample, uniforms, apply, fragment };
})(typeof window !== "undefined" ? window : globalThis);
