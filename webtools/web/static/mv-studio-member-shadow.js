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
    const texture = atlas.clone();
    texture.encoding = T.LinearEncoding;
    texture.wrapS = texture.wrapT = T.RepeatWrapping;
    texture.magFilter = texture.minFilter = T.LinearFilter;
    texture.generateMipmaps = false;
    texture.needsUpdate = true;
    const material = new T.ShaderMaterial({
      name: "Native member contact shadow", vertexShader, fragmentShader, transparent: true,
      toneMapped: false, side: T.DoubleSide, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.DstColorFactor, blendDst: T.ZeroFactor,
      blendSrcAlpha: T.DstAlphaFactor, blendDstAlpha: T.ZeroFactor,
      uniforms: {uTexture: {value: texture}},
    });
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
    let disposed = false;
    return {
      // parameters: the LiveMemberShadowTrack result (see sample), or null
      // when no track ran: ShadowComponent's constructor scales stay 1, 1.
      update(compatible, advancing, parameters) {
        if (disposed) return;
        const scaleX = parameters ? parameters.scaleX : 1, scaleZ = parameters ? parameters.scaleZ : 1;
        for (const entry of entries) {
          const {toe, anchor, mesh} = entry;
          if (!compatible) { mesh.visible = false; continue; }
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
          mesh.visible = root.visible && entry.factor > 0;
          if (!mesh.visible) continue;
          anchor.parent.updateWorldMatrix(true, false);
          local.compose(origin, anchor.quaternion, scale.set(f32(entry.factor * entry.scaleX), 1, f32(entry.factor * entry.scaleZ)));
          mesh.matrix.multiplyMatrices(anchor.parent.matrixWorld, local);
          // The two native anchors are positioned in world space, while their
          // original local scale and rotation still follow the actor's parent.
          mesh.matrix.setPosition(f32(worldToe.x), floor, f32(worldToe.z));
          mesh.matrixWorldNeedsUpdate = true;
        }
      },
      dispose() {
        if (disposed) return;
        disposed = true;
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

  global.MVStudioMemberShadow = {apply, sample};
})(typeof window !== "undefined" ? window : globalThis);
