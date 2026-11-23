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
      update(seconds) {
        const samples = new Map();
        for (const {fields, light, material, controller} of entries) {
          if (!samples.has(controller)) samples.set(controller, controller?.sample(seconds) ?? null);
          const sample = samples.get(controller), uniforms = material.uniforms;
          if (light.ambient) {
            uniforms.uAmbientColor.value.fromArray(sample?.ambient || fields.ambient);
            uniforms.uTintColor.value.fromArray(sample?.ambient ? sample.tint : fields.tint);
          }
          if (light.rim && sample) {
            const rim = sample.rim;
            uniforms.uRimglightIntensity.value = rim?.intensity ?? 0;
            if (rim?.color) uniforms.uRimlightColor.value.fromArray(rim.color);
            if (Number.isFinite(rim?.power)) uniforms.uRimglightPower.value = rim.power;
            if (rim?.direction) uniforms.uRimlightDirection.value.fromArray(rim.direction);
          }
        }
      },
      dispose,
    };
  }

  global.MVStudioPropLight = {create, apply, ambientAt, rimAt};
})(typeof window !== "undefined" ? window : globalThis);
