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
    const entries = source.toes.map((id, side) => ({toe: nodes.get(id), anchor: nodes.get(source.anchors[side]), factor: unset}));
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
      update(compatible, advancing) {
        if (disposed) return;
        for (const entry of entries) {
          const {toe, anchor, mesh} = entry;
          if (!compatible) { mesh.visible = false; continue; }
          toe.getWorldPosition(worldToe);
          const current = Math.min(limit, Math.max(0, f32(height - f32(worldToe.y))));
          const difference = f32(current - entry.factor);
          // LateUpdate writes the position each frame and changes the saved
          // factor only after the original threshold. A scrub samples its pose
          // directly so the result does not depend on the previous edit.
          if (!advancing || f32(difference * difference) > scaleChangeSquared) entry.factor = current;
          mesh.visible = root.visible && entry.factor > 0;
          if (!mesh.visible) continue;
          anchor.parent.updateWorldMatrix(true, false);
          local.compose(origin, anchor.quaternion, scale.set(entry.factor, 1, entry.factor));
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

  global.MVStudioMemberShadow = {apply};
})(typeof window !== "undefined" ? window : globalThis);
