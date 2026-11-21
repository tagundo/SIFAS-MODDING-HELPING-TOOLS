(function (global) {
  "use strict";

  // AS/Penlight expands a camera-facing quad at the native pivot of each light.
  // The three source attributes retain the Unity pivot, corner, and random seed.
  const vertexShader = `
    attribute vec3 _penlight_center;
    attribute vec3 _penlight_corner;
    attribute vec4 _penlight_color;
    uniform mat4 uLocalToPreview;
    uniform float uMode, uBeat, uMusicTime, uBeatLength, uBeatOffset;
    uniform float uRandomBrightness, uRandomSwing, uFog, uPaletteSize;
    uniform vec4 uRandomUp, uPalette[12];
    uniform vec3 uRandomDelay;
    uniform vec4 uBasicYZ, uGrowthYZ;
    uniform vec3 uGrowthShape, uBasicX;
    uniform vec2 uSimpleXZ;
    uniform float uBasicPower;
    varying vec2 vPenlightUv;
    varying vec4 vPenlightColor;

    const float PI = 3.141592653589793;

    float oscillation(float seed, float time) {
      vec3 phase = seed * vec3(87034.0, 174068.0, 348136.0) + time;
      return dot(sin(phase), vec3(1.0, 0.5, 0.25));
    }

    vec3 tiltYZ(vec3 up, float angle) {
      float c = cos(angle), s = sin(angle);
      return vec3(up.x, c * up.y - s * up.z, s * up.y + c * up.z);
    }

    vec3 tiltXY(vec3 up, float angle) {
      float c = cos(angle), s = sin(angle);
      return vec3(c * up.x + s * up.y, c * up.y - s * up.x, up.z);
    }

    void main() {
      vec4 seed = _penlight_color;
      float time = uMusicTime * uRandomUp.w;
      vec3 up = normalize(vec3(oscillation(seed.y, time) * uRandomUp.x, 1.0,
                               oscillation(seed.z, time) * uRandomUp.z));
      vec3 center = _penlight_center;
      vec3 phase = (uBeat - uBeatOffset) / uBeatLength + (seed.z - 0.5) * uRandomDelay;
      float swing = 1.0 + (seed.y - 1.0) * uRandomSwing;

      if (uMode == 1.0) {
        float wave = abs(2.0 * fract(phase.z - 0.5) - 1.0);
        float distance = swing * (uBasicYZ.w - (fract(phase.z) < 0.5 ? pow(wave, uBasicPower) : wave));
        center.y += swing * abs(sin(PI * phase.y)) * uBasicYZ.x;
        center.z += distance * uBasicYZ.y;
        up = tiltYZ(up, distance * uBasicYZ.z);
      } else if (uMode == 2.0) {
        float cycle = fract(phase.z);
        float front = cycle > uGrowthShape.z
          ? (cycle - uGrowthShape.z) / (1.0 - uGrowthShape.z)
          : pow(sin((1.0 - cycle / uGrowthShape.z) * PI * 0.5), uGrowthShape.y);
        float distance = swing * (uGrowthYZ.w - front);
        center.y += swing * pow((sin(2.0 * PI * (phase.y - 0.25)) + 1.0) * 0.5, uGrowthShape.x) * uGrowthYZ.x;
        center.z += distance * uGrowthYZ.y;
        up = tiltYZ(up, distance * uGrowthYZ.z);
      } else if (uMode == 3.0) {
        float distance = swing * cos(PI * phase.x);
        center.x += distance * uBasicX.y;
        center.y += sin(2.0 * PI * phase.x) * uBasicX.z;
        up = tiltXY(up, distance * uBasicX.x);
      } else if (uMode == 4.0) {
        up = tiltXY(up, swing * cos(PI * phase.x) * uSimpleXZ.x);
        up = tiltYZ(up, swing * cos(PI * phase.z) * uSimpleXZ.y);
      }

      vec3 worldCenter = (uLocalToPreview * vec4(center, 1.0)).xyz;
      vec3 worldUp = (uLocalToPreview * vec4(up, 0.0)).xyz;
      // Preview world mirrors Unity X. A cross product reverses under this
      // reflection, so preserve the source billboard's handedness explicitly.
      vec3 right = -normalize(cross(cameraPosition - worldCenter, worldUp));
      vec3 forward = -normalize(cross(worldUp, right));
      vec3 corner = _penlight_corner;
      vec3 world = worldCenter + right * corner.x + worldUp * corner.y + forward * corner.z;
      vec4 view = viewMatrix * vec4(world, 1.0);
      gl_Position = projectionMatrix * view;
      float distance = -view.z;
      float fog = uFog > 0.0 ? -0.1 * uFog * distance : uFog / max(distance, 0.00001);
      float slot = floor(fract(seed.x * 256.0 / uPaletteSize) * uPaletteSize);
      vec4 color = uPalette[0];
      for (int i = 0; i < 12; ++i) if (slot == float(i)) color = uPalette[i];
      color.a *= clamp(1.0 + fog, 0.0, 1.0) * (1.0 + (seed.w - 1.0) * uRandomBrightness);
      vPenlightColor = color;
      vPenlightUv = uv;
    }
  `;
  const fragmentShader = `
    uniform sampler2D uTexture;
    uniform vec4 uTint;
    varying vec2 vPenlightUv;
    varying vec4 vPenlightColor;
    void main() {
      gl_FragColor = texture2D(uTexture, vPenlightUv) * vPenlightColor * uTint;
    }
  `;

  function finite(value, fallback) {
    return Number.isFinite(value) ? value : fallback;
  }

  function tuple(value, names, defaults) {
    return names.map((name, index) => finite(Array.isArray(value) ? value[index] : value?.[name], defaults[index]));
  }

  function color(value) {
    if (!value) return null;
    const values = tuple(value, ["r", "g", "b", "a"], [NaN, NaN, NaN, NaN]);
    return values.every(Number.isFinite) ? values : null;
  }

  function beatAt(seconds, sync) {
    if (!Number.isFinite(sync?.bpm) || sync.bpm <= 0 ||
        !Number.isFinite(sync.startSample) || !Number.isFinite(sync.baseRate) || sync.baseRate <= 0) return null;
    return Math.max(0, seconds - sync.startSample / sync.baseRate) * sync.bpm / 60;
  }

  function paletteFor(values, project) {
    if (!Array.isArray(values.memberColors) || !values.memberColors.length || values.memberColors.length > 12) return null;
    const result = [];
    for (const entry of values.memberColors) {
      const tint = color(entry?.color);
      if (!tint) return null;
      const resolved = global.MVStudioLighting.memberColor(project, entry.colorSpecifiedType, entry.memberPosition, tint);
      if (!resolved) return null;
      result.push(resolved);
    }
    return result;
  }

  const continuous = {
    fogIntensity: 0, randomBrightness: 0, randomSwingIntensity: 0,
    basicYZMoveY: 0, basicYZMoveZ: 0, basicYZRotateZ: 0, basicYZSwingBackZ: 0, basicYZSwingPowerZ: 0,
    growthYZMoveY: 0, growthYZMoveZ: 0, growthYZRotateZ: 0, growthYZSwingBackZ: 0,
    growthYZSwingPowerZ: 0, growthYZSwingBottomZ: 0,
    basicXRotateX: 0, basicXMoveX: 0, basicXMoveY: 0, simpleXZRotateX: 0, simpleXZRotateZ: 0,
  };
  const vectorFields = {
    position: ["x", "y", "z"], tintColor: ["r", "g", "b", "a"],
    randomDelay: ["x", "y", "z"], randomUp: ["x", "y", "z", "w"],
  };

  function mixInputs(inputs, project) {
    if (inputs.length === 1 && inputs[0].weight === 1) {
      const { fields } = inputs[0];
      return { fields, palette: paletteFor(fields, project) };
    }
    let strongest = inputs[0];
    const mixed = { ...continuous }, palette = [];
    for (const [key, names] of Object.entries(vectorFields)) mixed[key] = names.map(() => 0);
    for (const input of inputs) {
      const { fields, weight } = input;
      if (weight > strongest.weight) strongest = input;
      const colors = paletteFor(fields, project);
      if (!colors) return { fields: null, palette: null };
      for (const key of Object.keys(continuous)) mixed[key] += finite(fields[key], 0) * weight;
      for (const [key, names] of Object.entries(vectorFields)) {
        const channels = tuple(fields[key], names, mixed[key].map(() => 0));
        for (let i = 0; i < channels.length; i++) mixed[key][i] += channels[i] * weight;
      }
      for (let i = 0; i < colors.length; i++) {
        const slot = palette[i] ||= [0, 0, 0, 0];
        for (let j = 0; j < slot.length; j++) slot[j] += colors[i][j] * weight;
      }
    }
    const { swingMode, beatLength, beatOffset } = strongest.fields;
    return { fields: { ...mixed, swingMode, beatLength, beatOffset }, palette };
  }

  function material(T, original, meta) {
    const value = (initial) => ({ value: initial });
    const uniforms = {
      uTexture: value(original.map), uLocalToPreview: value(new T.Matrix4()),
      uMode: value(0), uBeat: value(0), uMusicTime: value(0), uBeatLength: value(1), uBeatOffset: value(0),
      uRandomUp: value(new T.Vector4()), uRandomDelay: value(new T.Vector3()), uRandomBrightness: value(0),
      uRandomSwing: value(0), uFog: value(0), uTint: value(new T.Vector4()), uPaletteSize: value(1),
      uPalette: value(Array.from({ length: 12 }, () => new T.Vector4())),
      uBasicYZ: value(new T.Vector4()), uBasicPower: value(1), uGrowthYZ: value(new T.Vector4()),
      uGrowthShape: value(new T.Vector3()), uBasicX: value(new T.Vector3()), uSimpleXZ: value(new T.Vector2()),
    };
    const mode = meta.material?.floats?._CullMode;
    return new T.ShaderMaterial({
      name: original.name, vertexShader, fragmentShader, uniforms, transparent: true, toneMapped: false,
      depthTest: true, depthWrite: false, depthFunc: T.LessEqualDepth,
      side: mode === 2 ? T.FrontSide : mode === 1 ? T.BackSide : T.DoubleSide,
      blending: T.CustomBlending, blendEquation: T.AddEquation, blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
    });
  }

  function apply(T, root) {
    const members = [];
    root.traverse((node) => {
      const meta = node.geometry?.userData?.mvPenlight;
      if (!node.isMesh || !meta?.bindingSuffix || !node.material?.map ||
          !Array.isArray(meta.localToPreview) || meta.localToPreview.length !== 16 || !meta.localToPreview.every(Number.isFinite) ||
          !["_penlight_center", "_penlight_color", "_penlight_corner"].every((name) => node.geometry.getAttribute(name))) return;
      members.push({
        node, meta, original: node.material, shader: material(T, node.material, meta),
        registration: null, inputs: null,
        base: new T.Matrix4().fromArray(meta.localToPreview),
        frustumCulled: node.frustumCulled,
      });
    });
    if (!members.length) return null;

    function update(seconds, project) {
      for (const member of members) {
        const { node, original, shader, meta, base, frustumCulled } = member;
        if (member.registration !== project) {
          const matching = (project?.tracks || []).filter((track) => track.kind === "crowd" &&
            typeof track.binding === "string" && track.binding.endsWith("/" + meta.bindingSuffix));
          member.track = matching.length === 1 ? matching[0] : null;
          member.registration = project;
          member.inputs = null;
        }
        const track = member.track && !member.track.muted ? member.track : null;
        if (!track) {
          node.material = original;
          node.frustumCulled = frustumCulled;
          continue;
        }
        const inputs = [];
        for (const event of track.events) {
          if (event.values?.playableClass !== "LivePenlightClip") continue;
          const weight = global.MVStudioLighting.nativeWeight(event, seconds);
          if (weight > 0) inputs.push({ fields: event.values, weight });
        }
        const constantInput = inputs.length === 1 && inputs[0].weight === 1 ? inputs[0].fields : null;
        if (!inputs.length) {
          node.material = shader;
          shader.visible = false;
          continue;
        }
        const beat = beatAt(seconds, project?.stage?.beatSync);
        if (!constantInput || member.inputs !== constantInput) {
          const { fields, palette } = mixInputs(inputs, project);
          const mode = fields?.swingMode;
          if (!palette || !Number.isInteger(mode) || mode < 0 || mode > 4) {
            node.material = original;
            node.frustumCulled = frustumCulled;
            member.inputs = null;
            continue;
          }
          const u = shader.uniforms, saved = meta.material?.floats || {};
          u.uPaletteSize.value = palette.length;
          for (let index = 0; index < palette.length; index++) u.uPalette.value[index].fromArray(palette[index]);
          u.uMode.value = mode;
          u.uBeatLength.value = fields.beatLength > 0 && Number.isFinite(fields.beatLength) ? fields.beatLength : 1;
          u.uBeatOffset.value = finite(fields.beatOffset, 0);
          u.uTint.value.fromArray(color(fields.tintColor) || color(meta.material?.vectors?._TintColor) || [1, 1, 1, 1]);
          u.uFog.value = finite(fields.fogIntensity, finite(saved._FogIntensity, 0.5));
          u.uRandomBrightness.value = finite(fields.randomBrightness, finite(saved._RandomBrightness, 0.2));
          u.uRandomSwing.value = finite(fields.randomSwingIntensity, finite(saved._RandomSwingIntensity, 0.5));
          u.uRandomUp.value.fromArray(tuple(fields.randomUp, ["x", "y", "z", "w"], [0.1, 0, 0.1, 5]));
          u.uRandomDelay.value.fromArray(tuple(fields.randomDelay, ["x", "y", "z"], [0.1, 0.1, 0.1]));
          u.uBasicYZ.value.set(finite(fields.basicYZMoveY, 0.5), finite(fields.basicYZMoveZ, 0.17),
            finite(fields.basicYZRotateZ, 0.7), finite(fields.basicYZSwingBackZ, 0.6));
          u.uBasicPower.value = finite(fields.basicYZSwingPowerZ, 4);
          u.uGrowthYZ.value.set(finite(fields.growthYZMoveY, 0.8), finite(fields.growthYZMoveZ, 0.5),
            finite(fields.growthYZRotateZ, 0.8), finite(fields.growthYZSwingBackZ, 0.25));
          // Native LivePenlightMixer multiplies its reset output for power Y.
          u.uGrowthShape.value.set(0, finite(fields.growthYZSwingPowerZ, 0.8), finite(fields.growthYZSwingBottomZ, 0.8));
          u.uBasicX.value.set(finite(fields.basicXRotateX, 0.5), finite(fields.basicXMoveX, 0.2),
            finite(fields.basicXMoveY, 0.2));
          u.uSimpleXZ.value.set(finite(fields.simpleXZRotateX, 0.5), finite(fields.simpleXZRotateZ, 0.5));
          const position = tuple(fields.position, ["x", "y", "z"], [NaN, NaN, NaN]);
          const transform = u.uLocalToPreview.value.copy(base).elements;
          // LivePenlightMixer applies an absolute Unity world position.
          if (position.every(Number.isFinite)) {
            transform[12] = -position[0];
            transform[13] = position[1];
            transform[14] = position[2];
          }
          member.inputs = constantInput;
        }
        const clockAvailable = shader.uniforms.uMode.value === 0 || beat !== null;
        node.material = clockAvailable ? shader : original;
        node.frustumCulled = clockAvailable ? false : frustumCulled;
        shader.visible = true;
        shader.uniforms.uMusicTime.value = seconds;
        shader.uniforms.uBeat.value = beat ?? 0;
      }
    }

    return {
      update,
      invalidate() { for (const member of members) member.registration = null; },
      dispose() {
        for (const { node, original, shader, frustumCulled } of members) {
          node.material = original;
          node.frustumCulled = frustumCulled;
          shader.dispose();
        }
      },
    };
  }

  global.MVStudioPenlight = { apply };
})(typeof window !== "undefined" ? window : globalThis);
