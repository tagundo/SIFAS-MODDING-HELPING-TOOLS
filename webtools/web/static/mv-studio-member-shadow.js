(function (global) {
  "use strict";

  const f32 = Math.fround;
  const floor = f32(.01), height = f32(.15), limit = f32(.20), scaleChangeSquared = f32(.000025);
  const unset = -3.4028234663852886e38;
  const index = value => Number.isSafeInteger(value) && value >= 0;
  const pair = values => Array.isArray(values) && values.length === 2 && values.every(index);
  const vertexShader = `
    varying vec2 vTexture;
    void main() {
      vTexture = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `;
  const fragmentShader = `
    uniform sampler2D uTexture;
    varying vec2 vTexture;
    void main() { gl_FragColor = texture2D(uTexture, vTexture); }
  `;

  // AS/General/Transparent with _BlendSrc DstColor, _BlendDst Zero, ZWrite off,
  // Cull off, renderQueue 2800: the shadow texture multiplies the frame.
  function shadowMaterial(T, atlas, name) {
    const texture = atlas.clone();
    texture.encoding = T.LinearEncoding;
    texture.wrapS = texture.wrapT = T.RepeatWrapping;
    texture.magFilter = texture.minFilter = T.LinearFilter;
    texture.generateMipmaps = false;
    texture.needsUpdate = true;
    const material = new T.ShaderMaterial({
      name, vertexShader, fragmentShader, transparent: true,
      toneMapped: false, side: T.DoubleSide, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.DstColorFactor, blendDst: T.ZeroFactor,
      blendSrcAlpha: T.DstAlphaFactor, blendDstAlpha: T.ZeroFactor,
      uniforms: {uTexture: {value: texture}},
    });
    return {texture, material};
  }

  // LiveCoreStageEffect.memberShadowPrefabs exported by the stage effect GLB
  // (mv_studio_member_shadow.export_prefabs): shared templates every member's
  // ShadowComponent instantiates under both shadow anchors.
  async function prefabs(T, root, parser) {
    const source = root?.userData?.mvMemberShadowPrefabs;
    if (source?.schema !== 1 || !Array.isArray(source.prefabs) || !source.prefabs.length || source.prefabs.length > 16) return null;
    const templates = [];
    const dispose = () => {
      for (const template of templates) {
        template.geometry.dispose();
        template.material.dispose();
        template.texture.dispose();
      }
      templates.length = 0;
    };
    try {
      for (const prefab of source.prefabs) {
        const geometry = prefab?.geometry;
        if (!index(geometry?.POSITION) || !index(geometry?.TEXCOORD_0) || !index(geometry?.indices) || !index(prefab.texture) ||
            !Array.isArray(prefab.scale) || prefab.scale.length !== 3 || !prefab.scale.every(value => Number.isFinite(value) && value > 0)) {
          throw new Error("invalid shadow prefab");
        }
        const [positions, uv, faces, atlas] = await Promise.all([
          parser.getDependency("accessor", geometry.POSITION), parser.getDependency("accessor", geometry.TEXCOORD_0),
          parser.getDependency("accessor", geometry.indices), parser.getDependency("texture", prefab.texture),
        ]);
        if (positions?.itemSize !== 3 || !(positions.count > 0) || positions.count > 64 || uv?.itemSize !== 2 ||
            uv.count !== positions.count || faces?.itemSize !== 1 || !(faces.count > 0) || faces.count % 3 || !atlas?.isTexture) {
          throw new Error("invalid shadow prefab");
        }
        const meshGeometry = new T.BufferGeometry();
        meshGeometry.setAttribute("position", positions);
        meshGeometry.setAttribute("uv", uv);
        meshGeometry.setIndex(faces);
        const {texture, material} = shadowMaterial(T, atlas, "Native stage member shadow");
        templates.push({geometry: meshGeometry, material, texture,
          scale: new T.Matrix4().makeScale(prefab.scale[0], prefab.scale[1], prefab.scale[2])});
      }
    } catch {
      dispose();
      return null;
    }
    return {templates, dispose};
  }

  async function apply(T, root, parser, sceneRoot) {
    const source = root?.userData?.mvMemberShadow;
    const geometry = source?.geometry;
    if (source?.schema !== 1 || !pair(source.toes) || !pair(source.anchors) ||
        !index(geometry?.POSITION) || !index(geometry?.TEXCOORD_0) || !index(geometry?.indices) ||
        !index(source.texture)) return null;
    const ids = new Set([...source.toes, ...source.anchors]);
    if (ids.size !== 4) return null;
    const nodes = new Map();
    root.traverse(node => {
      const id = node.userData.elichika_node;
      if (ids.has(id)) nodes.set(id, nodes.has(id) ? null : node);
    });
    const entries = source.toes.map((id, side) => ({toe: nodes.get(id), anchor: nodes.get(source.anchors[side]), factor: unset,
      scaleX: 1, scaleZ: 1}));
    if (entries.some(({toe, anchor}) => !toe || !anchor?.parent)) return null;
    let positions, uv, faces, atlas;
    try {
      [positions, uv, faces, atlas] = await Promise.all([
        parser.getDependency("accessor", geometry.POSITION), parser.getDependency("accessor", geometry.TEXCOORD_0),
        parser.getDependency("accessor", geometry.indices), parser.getDependency("texture", source.texture),
      ]);
    } catch { return null; }
    if (positions?.itemSize !== 3 || positions.count !== 12 || uv?.itemSize !== 2 || uv.count !== 12 ||
        faces?.itemSize !== 1 || faces.count !== 30 || !atlas?.isTexture ||
        atlas.image?.width !== 128 || atlas.image?.height !== 128) return null;

    const meshGeometry = new T.BufferGeometry();
    meshGeometry.setAttribute("position", positions);
    meshGeometry.setAttribute("uv", uv);
    meshGeometry.setIndex(faces);
    const {texture, material} = shadowMaterial(T, atlas, "Native member contact shadow");
    for (const [side, entry] of entries.entries()) {
      entry.mesh = new T.Mesh(meshGeometry, material);
      entry.mesh.name = `Native member contact shadow ${side ? "R" : "L"}`;
      entry.mesh.renderOrder = 2800;
      entry.mesh.visible = false;
      entry.mesh.matrixAutoUpdate = false;
      sceneRoot.add(entry.mesh);
    }
    const worldToe = new T.Vector3(), scale = new T.Vector3(), origin = new T.Vector3();
    const local = new T.Matrix4();
    let disposed = false, instanced = null;
    function instances(prefabSet) {
      if (instanced && instanced.set === prefabSet) return instanced.meshes;
      if (instanced) for (const meshes of instanced.meshes) for (const mesh of meshes) sceneRoot.remove(mesh);
      instanced = null;
      if (!prefabSet?.templates?.length) return null;
      // Initialize: Instantiate(prefabs[i], shadowL) and (prefabs[i], shadowR).
      const meshes = entries.map((entry, side) => prefabSet.templates.map((template, slot) => {
        const mesh = new T.Mesh(template.geometry, template.material);
        mesh.name = `Native stage member shadow ${slot} ${side ? "R" : "L"}`;
        mesh.renderOrder = 2800;
        mesh.visible = false;
        mesh.matrixAutoUpdate = false;
        sceneRoot.add(mesh);
        return mesh;
      }));
      instanced = {set: prefabSet, meshes};
      return meshes;
    }
    return {
      // parameters: the LiveMemberShadowTrack result (see sample), or null
      // when no track ran: ShadowComponent's constructor scales stay 1, 1.
      // prefabSet: the stage's shadow prefabs (see prefabs); they replace the
      // costume's shadows, and ApplyShadowIndex keeps only parameters.index
      // (0 from Initialize without a track) active.
      update(compatible, advancing, parameters, prefabSet) {
        if (disposed) return;
        const scaleX = parameters ? parameters.scaleX : 1, scaleZ = parameters ? parameters.scaleZ : 1;
        const stageMeshes = instances(prefabSet), activeIndex = parameters ? parameters.index : 0;
        for (const [side, entry] of entries.entries()) {
          const {toe, anchor, mesh} = entry;
          const sideMeshes = stageMeshes?.[side];
          if (sideMeshes) mesh.visible = false;
          if (!compatible && !sideMeshes) { mesh.visible = false; continue; }
          toe.getWorldPosition(worldToe);
          const current = Math.min(limit, Math.max(0, f32(height - f32(worldToe.y))));
          const difference = f32(current - entry.factor);
          // LateUpdate writes the position each frame and changes the saved
          // factor only after the original threshold. A scrub samples its pose
          // directly so the result does not depend on the previous edit.
          // UpdateScale writes localScale (factor * shadowScaleX, 1, factor *
          // shadowScaleZ) only then, so a new track scale waits for it too.
          if (!advancing || f32(difference * difference) > scaleChangeSquared) {
            entry.factor = current;
            entry.scaleX = scaleX;
            entry.scaleZ = scaleZ;
          }
          const shown = root.visible && entry.factor > 0;
          if (sideMeshes) sideMeshes.forEach((instance, slot) => { instance.visible = shown && slot === activeIndex; });
          else mesh.visible = shown;
          if (!shown) continue;
          anchor.parent.updateWorldMatrix(true, false);
          local.compose(origin, anchor.quaternion, scale.set(f32(entry.factor * entry.scaleX), 1, f32(entry.factor * entry.scaleZ)));
          mesh.matrix.multiplyMatrices(anchor.parent.matrixWorld, local);
          // The two native anchors are positioned in world space, while their
          // original local scale and rotation still follow the actor's parent.
          mesh.matrix.setPosition(f32(worldToe.x), floor, f32(worldToe.z));
          mesh.matrixWorldNeedsUpdate = true;
          const instance = sideMeshes?.[activeIndex];
          if (instance) {
            instance.matrix.multiplyMatrices(mesh.matrix, prefabSet.templates[activeIndex].scale);
            instance.matrixWorldNeedsUpdate = true;
          }
        }
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        instances(null);
        for (const {mesh} of entries) sceneRoot.remove(mesh);
        meshGeometry.dispose();
        material.dispose();
        texture.dispose();
      },
    };
  }

  // LiveMemberShadowMixer (GL 3.12.0, 0x20eb2c4/0x20eb2d0/0x20eb3f0), bound to
  // LiveCoreMemberManager. PreProcess zeroes maxWeight, shadowIndex and both
  // scales. Process runs for each input whose weight w is not 0, in input order:
  // when maxWeight < w it takes clip.shadowIndex and w, and it always adds
  // clip.shadowScaleX/Z * w (no normalization). PostProcess calls
  // ApplyShadowParameters(index, scaleX, scaleZ) when an input ran, else
  // (0, 1, 1); it reaches every member's ShadowComponent, so the last
  // unmuted track wins. Without the stage's memberShadowPrefabs the index has no
  // object to switch (ApplyShadowIndex stops on the missing array) and the
  // costume's default shadows keep drawing with the scales.
  function timing(values) {
    return {easeIn: values.easeIn, easeOut: values.easeOut, blendIn: values.blendIn, blendOut: values.blendOut,
      mixIn: values.mixIn?.length ? values.mixIn : [{time: 0, value: 0}, {time: 1, value: 1}],
      mixOut: values.mixOut?.length ? values.mixOut : [{time: 0, value: 1}, {time: 1, value: 0}],
      preMode: values.preExtrapolationMode, postMode: values.postExtrapolationMode,
      preTime: values.preExtrapolationTime, postTime: values.postExtrapolationTime};
  }

  function sample(tracks, time, weightOf = global.ViewerMotionTimeline?.weight) {
    if (typeof weightOf !== "function") return null;
    let result = null;
    for (const track of tracks || []) {
      if (track.muted || track.nativeClass !== "LiveMemberShadowTrack" || !Array.isArray(track.events)) continue;
      let maxWeight = 0, shadowIndex = 0, scaleX = 0, scaleZ = 0, processed = false;
      for (const event of track.events) {
        const values = event.values || {};
        if (values.playableClass !== "LiveMemberShadowClip" || !Number.isInteger(values.shadowIndex) ||
            !Number.isFinite(values.shadowScaleX) || !Number.isFinite(values.shadowScaleZ)) continue;
        const weight = f32(weightOf({start: event.start, duration: event.duration, timing: timing(values)}, time));
        if (!(weight !== 0)) continue;
        processed = true;
        if (maxWeight < weight) {
          shadowIndex = values.shadowIndex;
          maxWeight = weight;
        }
        scaleX = f32(scaleX + f32(f32(values.shadowScaleX) * weight));
        scaleZ = f32(scaleZ + f32(f32(values.shadowScaleZ) * weight));
      }
      result = processed ? {index: shadowIndex, scaleX, scaleZ} : {index: 0, scaleX: 1, scaleZ: 1};
    }
    return result;
  }

  global.MVStudioMemberShadow = {apply, prefabs, sample};
})(typeof window !== "undefined" ? window : globalThis);
