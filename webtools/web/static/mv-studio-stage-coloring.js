(function (global) {
  "use strict";

  // AS/Coloring/Transparent's GLES3 programs: _AUTO_PLAY_ON scrolls the palette by -_Time.y * _Speed
  // instead of -_SelfTime * _Speed (uSelfTime carries the clock), _VERTEX_COLOR_ON multiplies COLOR0
  // in, and _SATURATE_ON adds (main.rgb^2)^2 to the colour, alpha unchanged.
  const vertexShader = [
    "attribute vec2 _stage_color_index;",
    "#ifdef VERTEX_COLOR",
    "attribute vec4 _stage_color;",
    "varying vec4 vColor;",
    "#endif",
    "uniform vec4 uMainST;",
    "uniform vec2 uIndexST;",
    "uniform float uShift;",
    "uniform float uSpeed;",
    "uniform float uSelfTime;",
    "varying vec2 vMain;",
    "varying vec2 vPalette;",
    "void main() {",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
    "  vMain = uv * uMainST.xy + uMainST.zw;",
    "  float index = floor((_stage_color_index.x * uIndexST.x + uIndexST.y) * 256.0);",
    "  vPalette = vec2((index * (255.0 / 256.0) + uShift + 0.5) / 256.0, -uSpeed * uSelfTime);",
    "  #ifdef VERTEX_COLOR",
    "  vColor = _stage_color;",
    "  #endif",
    "}"
  ].join("\n");

  const fragmentShader = [
    "uniform sampler2D uMain;",
    "uniform sampler2D uPalette;",
    "uniform vec4 uTint;",
    "varying vec2 vMain;",
    "varying vec2 vPalette;",
    "#ifdef VERTEX_COLOR",
    "varying vec4 vColor;",
    "#endif",
    "void main() {",
    "  vec4 base = texture2D(uMain, vMain);",
    "  gl_FragColor = base * texture2D(uPalette, vPalette) * uTint;",
    "  #ifdef VERTEX_COLOR",
    "  gl_FragColor *= vColor;",
    "  #endif",
    "  #ifdef SATURATE",
    "  vec3 square = base.rgb * base.rgb;",
    "  gl_FragColor.rgb += square * square;",
    "  #endif",
    "}"
  ].join("\n");

  function rgba(value) {
    const four = Array.isArray(value) ? value : [value?.r, value?.g, value?.b, value?.a];
    return four.length === 4 && four.every(Number.isFinite) ? four : null;
  }

  function sample(track, time) {
    const tint = [0, 0, 0, 0];
    let primary = null, weight = 0, selfTime = 0;
    for (const event of track.events) {
      const fields = event.values;
      if (fields?.playableClass !== "LiveColoringClip") continue;
      const color = rgba(fields.tintColor);
      if (!color || !Number.isFinite(fields.shift) || !Number.isFinite(fields.speed)) continue;
      const contribution = global.MVStudioLighting?.nativeWeight(event, time) ?? 0;
      if (contribution <= 0) continue;
      for (let axis = 0; axis < 4; axis++) tint[axis] += contribution * color[axis];
      if (contribution > weight) {
        weight = contribution;
        primary = fields;
        selfTime = (fields.clipIn || 0) + (time - event.start) * (fields.timeScale ?? 1);
      }
    }
    // LiveColoringMixer: PreProcess resets textureIndex to 0 and Process keeps
    // the strictly heaviest input's LiveColoringClip.textureIndex.
    const textureIndex = primary ? primary.textureIndex ?? 0 : 0;
    return { tint, shift: primary?.shift || 0, speed: primary?.speed || 0, selfTime, textureIndex };
  }

  // LiveCoreStageColoring.ApplyTextureIndex: nothing without light shaft
  // textures or when the index is current; otherwise _MainTex becomes
  // lightShaftTextures[index]. currentTextureIndex starts at int.MinValue, so
  // index 0 replaces the material texture on the first mixer frame. An index
  // outside the list throws in the client before currentTextureIndex changes.
  function applyTextureIndex(state, shafts, index) {
    if (!shafts?.length || state.currentIndex === index) return false;
    if (!Number.isInteger(index) || index < 0 || index >= shafts.length) return false;
    state.currentIndex = index;
    return true;
  }

  // While StageColoring is off, LiveQualityOperator.ApplyLiveQualityToStageEffectTrack
  // mutes the StageEffect/<difficulty>/<category> group whose name, without
  // spaces and lower-cased (NormalizeTrackName), is "coloring". Its
  // ApplyMuteToChildTracks (0x20f348c) is not recursive: it set_muted's only
  // the group's direct child tracks. A sub-GroupTrack there is muted itself,
  // but this Timeline compiles every output track by its own m_Muted only
  // (TrackAsset.compilable = !muted && !isEmpty; GroupTrack is never compiled),
  // so a LiveColoringTrack nested in it keeps its mixer (12023's
  // Coloring/LightShaft, Led_p and Led_l). A muted non-Animation track keeps
  // its binding active (RemainsInMuted) but runs no mixer, so the material
  // keeps its own values.
  function qualityMuted(track, values) {
    if (values?.stage_coloring !== false) return false;
    const parts = typeof track?.label === "string" ? track.label.split("/") : [];
    return parts.length === 4 && parts[0] === "StageEffect" && parts[2].replace(/ /g, "").toLowerCase() === "coloring";
  }

  function customize(source, result, colors) {
    result.set(source);
    for (let offset = 0; offset < source.length; offset += 4) {
      if (source[offset + 3] >= .51 * 255) continue;
      const position = Math.min(11, Math.max(0, Math.floor(source[offset] / 10) - 1)) + 1;
      const color = rgba(colors[position]);
      if (!color) continue;
      const mix = source[offset + 1] / 255, gray = source[offset + 2];
      for (let channel = 0; channel < 4; channel++) {
        const initial = channel === 3 ? 255 : gray;
        result[offset + channel] = Math.round(Math.min(255, Math.max(0, initial + (color[channel] * 255 - initial) * mix)));
      }
    }
  }

  async function apply(T, root, parser) {
    const paletteTextures = new Map(), mainTextures = new Map(), groups = new Map(), meshes = [];
    root.traverse((node) => {
      const fields = node.geometry?.userData?.mvStageColoring;
      if (node.isMesh && !Array.isArray(node.material) && fields && node.geometry.attributes._stage_color_index) {
        meshes.push({ node, fields, original: node.material, renderOrder: node.renderOrder });
      }
    });
    if (!meshes.length) return null;
    function palette(info) {
      if (!paletteTextures.has(info.bytes)) {
        paletteTextures.set(info.bytes, parser.getDependency("bufferView", info.bytes).then((buffer) => {
          const source = new Uint8Array(buffer), [width, height] = info.size;
          if (source.length !== width * height * 4) throw new Error("The original stage palette is incomplete.");
          const target = source.slice();
          const texture = new T.DataTexture(target, width, height, T.RGBAFormat, T.UnsignedByteType);
          texture.wrapS = texture.wrapT = T.RepeatWrapping;
          texture.minFilter = texture.magFilter = T.LinearFilter;
          texture.needsUpdate = true;
          return { source, target, texture };
        }));
      }
      return paletteTextures.get(info.bytes);
    }
    function main(index) {
      if (!mainTextures.has(index)) {
        mainTextures.set(index, parser.getDependency("texture", index).then((original) => {
          const texture = original.clone();
          texture.encoding = T.LinearEncoding;
          texture.needsUpdate = true;
          return texture;
        }));
      }
      return mainTextures.get(index);
    }
    try {
      for (const { fields } of meshes) {
        if (groups.has(fields.target)) continue;
        const shaftIndices = Array.isArray(fields.shaftTextures) ? fields.shaftTextures : [];
        const [base, colors, ...shafts] = await Promise.all([main(fields.main), palette(fields.palette),
          ...shaftIndices.map(main)]);
        const [sx, sy, ox, oy] = fields.mainUV;
        const uniforms = {
          uMain: { value: base }, uPalette: { value: colors.texture },
          uMainST: { value: new T.Vector4(sx, sy, ox, 1 - sy - oy) },
          uIndexST: { value: new T.Vector2(fields.indexScale, fields.indexOffset) },
          uTint: { value: new T.Vector4().fromArray(fields.tint) },
          uShift: { value: fields.shift }, uSpeed: { value: fields.speed }, uSelfTime: { value: 0 }
        };
        const defines = {};
        if (fields.vertexColor === true) defines.VERTEX_COLOR = 1;
        if (fields.saturate === true) defines.SATURATE = 1;
        const material = new T.ShaderMaterial({
          uniforms, vertexShader, fragmentShader, defines, depthWrite: false, transparent: true, toneMapped: false,
          side: [T.DoubleSide, T.BackSide, T.FrontSide][fields.cull], blending: T.CustomBlending,
          blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
          blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor
        });
        material.name = "AS/Coloring/Transparent";
        // Unity feeds opaque white to COLOR when the mesh has no colour stream.
        material.defaultAttributeValues._stage_color = [1, 1, 1, 1];
        groups.set(fields.target, { fields, material, uniforms, track: null, palette: colors, base, shafts,
          currentIndex: null });
      }
      for (const { node, fields } of meshes) {
        node.material = groups.get(fields.target).material;
        node.renderOrder = fields.queue;
      }
    } catch (error) {
      for (const { material } of groups.values()) material.dispose();
      for (const task of mainTextures.values()) task.then((texture) => texture.dispose(), () => {});
      for (const task of paletteTextures.values()) task.then(({ texture }) => texture.dispose(), () => {});
      throw error;
    }
    let lastProject, lastColors, gameClock = null;
    // Unity draws queue-3000 renderers back to front by the distance from the camera to the
    // renderer's bounds center; MVStudioTransparentSort orders these meshes with the other
    // native transparent stage meshes. sortCenter is the mesh's m_LocalAABB center in the node's
    // frame: local under a retained stage node, baked with the vertices for a world-space mesh.
    const sortEntries = meshes.filter(({ fields }) => Array.isArray(fields.sortCenter) && fields.sortCenter.length === 3 &&
      fields.sortCenter.every(Number.isFinite)).map(({ node, fields }) => ({
      node, anchor: node, center: new T.Vector3().fromArray(fields.sortCenter), queue: fields.queue,
    }));
    return {
      sortEntries() { return sortEntries; },
      invalidate() { lastProject = null; },
      // The scene's game clock (director seconds -> the game's Time.time), or null for the director time.
      useClock(clock) { gameClock = typeof clock === "function" ? clock : null; },
      // `clock` (optional, the scene's game clock): director seconds -> the game's Time.time, which
      // the _AUTO_PLAY_ON programs read as _Time.y; the director time stands in without one.
      update(seconds, project, clock = gameClock) {
        if (project !== lastProject) {
          const tracks = new Map();
          const colors = { ...project?.stage?.memberThemeColors };
          for (const actor of project?.performers || []) if (actor.themeColor) colors[actor.position] = actor.themeColor;
          const identity = JSON.stringify(colors);
          if (lastColors !== identity) {
            const prepared = new Set();
            for (const { palette } of groups.values()) if (!prepared.has(palette)) {
              customize(palette.source, palette.target, colors);
              palette.texture.needsUpdate = true;
              prepared.add(palette);
            }
            lastColors = identity;
          }
          for (const track of project?.tracks || []) {
            if (track.nativeClass !== "LiveColoringTrack" || track.muted || !groups.has(track.binding)) continue;
            tracks.set(track.binding, tracks.has(track.binding) ? null : track);
          }
          for (const [target, group] of groups) group.track = tracks.get(target);
          lastProject = project;
        }
        for (const group of groups.values()) {
          const { fields, material, uniforms } = group;
          const track = group.track && !qualityMuted(group.track, project?.quality?.values) ? group.track : null;
          const value = track ? sample(track, seconds) : { ...fields, selfTime: 0 };
          if (!track) {
            // Without a bound mixer the client never calls ApplyTextureIndex.
            group.currentIndex = null;
            uniforms.uMain.value = group.base;
          } else if (applyTextureIndex(group, group.shafts, value.textureIndex)) {
            uniforms.uMain.value = group.shafts[group.currentIndex];
          }
          uniforms.uTint.value.fromArray(value.tint);
          uniforms.uShift.value = value.shift;
          uniforms.uSpeed.value = value.speed;
          uniforms.uSelfTime.value = fields.autoPlay === true
            ? (typeof clock === "function" ? clock(seconds) : seconds) : value.selfTime;
          material.visible = value.tint[3] !== 0;
        }
      },
      dispose() {
        for (const { node, original, renderOrder } of meshes) {
          node.material = original;
          node.renderOrder = renderOrder;
        }
        for (const { material } of groups.values()) material.dispose();
        for (const task of mainTextures.values()) task.then((texture) => texture.dispose());
        for (const task of paletteTextures.values()) task.then(({ texture }) => texture.dispose());
      }
    };
  }

  global.MVStudioStageColoring = { apply, sample, customize, applyTextureIndex, qualityMuted };
})(window);
