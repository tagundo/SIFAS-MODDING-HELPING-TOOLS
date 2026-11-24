(function (global) {
  "use strict";

  const propBinding = /^\/EntryPoint\/Live\/Members\/ske_[A-Za-z0-9_]+\/Member([1-9][0-9]*)\/Model\/(?:[A-Za-z0-9_]+\/)+chp[0-9]+$/;
  // LivePropBasic on a stage-effect object: the prefab is inserted under MainStage/Effect.
  const stageBinding = /^\/EntryPoint\/Live\/Stages\/MainStage\/Effect(?:\/[^/]+)+$/;

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
    if (typeof binding !== "string" || binding.length > 512) return null;
    if (member === undefined ? !stageBinding.test(binding) :
        !Number.isInteger(member) || Number(propBinding.exec(binding)?.[1]) !== member) return null;
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

  // AS/Rimlight/Opaque (single gles3 pass): main * COLOR0, lerped to the
  // ambient color by its alpha, times the tint, plus the view-space rim term.
  const rimlightVertex = [
    "attribute vec4 _stage_color;",
    "uniform vec4 uTextureST;",
    "uniform vec3 uRimlightDirection;",
    "varying vec2 vTexture;",
    "varying vec4 vColor;",
    "varying vec3 vViewNormal;",
    "varying vec3 vRimDirection;",
    "void main() {",
    "  vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);",
    "  gl_Position = projectionMatrix * viewPosition;",
    "  vTexture = uv * uTextureST.xy + vec2(uTextureST.z, 1.0 - uTextureST.y - uTextureST.w);",
    "  vColor = _stage_color;",
    "  vViewNormal = mat3(modelViewMatrix) * normal;",
    "  vRimDirection = normalize(-viewPosition.xyz - uRimlightDirection);",
    "}"
  ].join("\n");
  const rimlightFragment = [
    "uniform sampler2D uMainTex;",
    "uniform sampler2D uRimlightTex;",
    "uniform mediump vec4 uTintColor;",
    "uniform mediump vec4 uAmbientColor;",
    "uniform mediump vec4 uRimlightColor;",
    "uniform mediump float uRimglightIntensity;",
    "uniform mediump float uRimglightPower;",
    "varying vec2 vTexture;",
    "varying vec4 vColor;",
    "varying vec3 vViewNormal;",
    "varying vec3 vRimDirection;",
    "void main() {",
    "  float facing = 1.0 - clamp(dot(vRimDirection, vViewNormal), 0.0, 1.0);",
    "  mediump float rim = exp2(log2(facing) * uRimglightPower);",
    "  rim *= texture2D(uRimlightTex, vTexture).r * (uRimlightColor.a * uRimglightIntensity);",
    "  mediump vec4 surface = texture2D(uMainTex, vTexture) * vColor;",
    "  surface.rgb = mix(surface.rgb, uAmbientColor.rgb, uAmbientColor.a);",
    "  surface *= uTintColor;",
    "  surface.rgb += rim * uRimlightColor.rgb;",
    "  gl_FragColor = max(surface, vec4(0.0));",
    "}"
  ].join("\n");

  const isRow = (row, length) => Array.isArray(row) && row.length === length && row.every(Number.isFinite);
  const textureIndex = value => value === null || Number.isSafeInteger(value) && value >= 0;

  function validRimlight(fields) {
    return Boolean(fields) && textureIndex(fields.texture) && textureIndex(fields.rimlightTexture) &&
      isRow(fields.uv, 4) && ["tint", "ambient", "rimlightColor", "rimlightDirection"].every(name => isRow(fields[name], 4)) &&
      Number.isFinite(fields.intensity) && Number.isFinite(fields.power) && [0, 1, 2].includes(fields.cull);
  }

  function validLight(light) {
    return typeof light?.binding === "string" && stageBinding.test(light.binding) &&
      typeof light.ambient === "boolean" && typeof light.rim === "boolean" && (light.ambient || light.rim);
  }

  // Stage-effect props whose materials LivePropBasic instanced (mvPropLight).
  async function apply(T, root, parser, options = {}) {
    const {active = () => true} = options;
    const candidates = [];
    root.traverse(node => {
      const data = node.geometry?.userData;
      if (!node.isMesh || node.isSkinnedMesh || Array.isArray(node.material) || !parser ||
          !validRimlight(data?.mvStageRimlight) || !validLight(data?.mvPropLight)) return;
      candidates.push({node, fields: data.mvStageRimlight, light: data.mvPropLight, original: node.material});
    });
    if (!candidates.length) return null;
    const white = new T.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
    white.needsUpdate = true;
    const textures = new Map(), entries = [], lights = new Map();
    function texture(index) {
      if (index === null) return Promise.resolve(white);
      if (!textures.has(index)) textures.set(index, parser.getDependency("texture", index).then(original => {
        const copy = original.clone();
        copy.encoding = T.LinearEncoding;
        copy.needsUpdate = true;
        return copy;
      }));
      return textures.get(index);
    }
    function dispose() {
      for (const {node, original, material} of entries) {
        node.material = original;
        material.dispose();
      }
      entries.length = 0;
      for (const task of textures.values()) task.then(copy => copy.dispose(), () => {});
      white.dispose();
    }
    try {
      for (const {node, fields, light, original} of candidates) {
        const [main, rimTexture] = await Promise.all([texture(fields.texture), texture(fields.rimlightTexture)]);
        if (!active()) break;
        const uniforms = {
          uMainTex: {value: main}, uRimlightTex: {value: rimTexture},
          uTextureST: {value: new T.Vector4().fromArray(fields.uv)},
          uTintColor: {value: new T.Vector4().fromArray(fields.tint)},
          uAmbientColor: {value: new T.Vector4().fromArray(fields.ambient)},
          uRimlightColor: {value: new T.Vector4().fromArray(fields.rimlightColor)},
          // The live camera's own 180-degree turn cancels the X mirror, so
          // the preview view space is Unity's and this vector is used as is.
          uRimlightDirection: {value: new T.Vector3().fromArray(fields.rimlightDirection)},
          uRimglightIntensity: {value: fields.intensity},
          uRimglightPower: {value: fields.power},
        };
        // Unity's CullMode names the discarded side; three's side names the kept one.
        const material = new T.ShaderMaterial({
          name: original?.name || "AS/Rimlight/Opaque", vertexShader: rimlightVertex, fragmentShader: rimlightFragment,
          uniforms, toneMapped: false, side: [T.DoubleSide, T.BackSide, T.FrontSide][fields.cull],
        });
        // A mesh without a COLOR stream reads opaque white.
        material.defaultAttributeValues._stage_color = [1, 1, 1, 1];
        node.material = material;
        if (!lights.has(light.binding)) lights.set(light.binding, create(light.binding));
        entries.push({node, fields, light, original, material, controller: lights.get(light.binding)});
      }
    } catch (error) {
      dispose();
      throw error;
    }
    if (!entries.length) {
      dispose();
      return null;
    }
    return {
      setProject(project) {
        for (const controller of lights.values()) controller?.setProject(project);
      },
      // LivePropAmbientMixer / LivePropRimlightMixer: active clips write the
      // mixed values; otherwise the defaults return and rim intensity is zero.
      // The ambient and tint go through the prop's LiveCoreMemberAmbient
      // (LivePropAmbientMixer.PostProcess 0x20f1480 -> ApplyAmbientColor
      // 0x2f670cc / ApplyTintColor / ApplyDefault*), which keeps its last written
      // color until the new one moves by sqrt(1e-5) (MVStudioLighting.heldColor
      // on the scene's frame clock `frames`). With a base light track (`exact`)
      // LiveBaseLightReciever writes the same components too, and the order of the
      // two writers within a frame is not established, so the colors are not held
      // there (unevidenced choice).
      update(seconds, frames = null, exact = false) {
        const samples = new Map();
        const sampleAt = (controller, time) => {
          let byTime = samples.get(controller);
          if (!byTime) samples.set(controller, byTime = new Map());
          if (!byTime.has(time)) byTime.set(time, controller?.sample(time) ?? null);
          return byTime.get(time);
        };
        const held = !exact && global.MVStudioLighting?.heldColor;
        for (const entry of entries) {
          const {fields, light, material, controller} = entry;
          const sample = sampleAt(controller, seconds), uniforms = material.uniforms;
          if (light.ambient) {
            const ambientAt = (time) => sampleAt(controller, time)?.ambient || fields.ambient;
            const tintAt = (time) => sampleAt(controller, time)?.ambient ? sampleAt(controller, time).tint : fields.tint;
            entry.holds ||= {ambient: {}, tint: {}};
            uniforms.uAmbientColor.value.fromArray(held ? held(entry.holds.ambient, ambientAt, seconds, frames) : ambientAt(seconds));
            uniforms.uTintColor.value.fromArray(held ? held(entry.holds.tint, tintAt, seconds, frames) : tintAt(seconds));
          }
          if (light.rim && sample) {
            const rim = sample.rim, held = heldRim(entry, rim, (time) => sampleAt(controller, time)?.rim, frames);
            uniforms.uRimglightIntensity.value = rim?.intensity ?? 0;
            uniforms.uRimlightColor.value.fromArray(held?.color ?? fields.rimlightColor);
            uniforms.uRimglightPower.value = held?.power ?? fields.power;
            uniforms.uRimlightDirection.value.fromArray(held?.direction ?? fields.rimlightDirection);
          }
        }
      },
      dispose,
    };
  }

  // LivePropRimlightMixer.PostProcess (0x20f21a4) applies colour, sharpness and
  // direction only in a frame an input ran (otherwise only ApplyIntensity(0)),
  // and a muted track writes nothing. The prop's own material instance (a copy
  // of the listed asset, the exported fields) therefore keeps the rim of the
  // last frame a clip ran: the previous playing frame, or after a seek the last
  // written frame of the frame clock's history; its copied values before any.
  function heldRim(entry, rim, rimAt, frames) {
    const written = (value) => Array.isArray(value?.color) && Array.isArray(value?.direction) && Number.isFinite(value?.power);
    if (written(rim)) return entry.rimHold = rim;
    if (!frames?.advancing) {
      entry.rimHold = null;
      const history = Array.isArray(frames?.history) ? frames.history : [];
      for (let index = history.length - 1; index >= 0 && !entry.rimHold; index--) {
        const value = rimAt(history[index]);
        if (written(value)) entry.rimHold = value;
      }
    }
    return entry.rimHold ?? null;
  }

  global.MVStudioPropLight = {create, apply, ambientAt, rimAt};
})(typeof window !== "undefined" ? window : globalThis);
