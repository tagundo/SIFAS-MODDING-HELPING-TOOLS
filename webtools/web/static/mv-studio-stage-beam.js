(function (global) {
  "use strict";

  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_par_so2056_05/root";
  const vertexShader = `
    #include <common>
    #include <skinning_pars_vertex>
    varying vec2 vTexture;
    void main() {
      vTexture = uv;
      #include <begin_vertex>
      #include <skinbase_vertex>
      #include <skinning_vertex>
      #include <project_vertex>
    }
  `;
  const fragmentShader = `
    uniform sampler2D uTexture;
    uniform vec4 uTint;
    varying vec2 vTexture;
    void main() { gl_FragColor = texture2D(uTexture, vTexture) * uTint; }
  `;

  function checked(fields, owner) {
    const stageNode = owner?.userData?.mvStageNode;
    return fields?.binding === binding + "/joint_all/LaserBeam" && stageNode?.binding === binding &&
      stageNode.path === 587684620 && !owner.userData.mvStageOverlayChannels &&
      fields.shader === "AS/General/Transparent" && fields.renderOrder === 3010 && fields.vertexColor === false &&
      Array.isArray(fields.uv) && fields.uv.length === 4 && fields.uv.every((value, index) => value === (index < 2 ? 1 : 0)) &&
      Array.isArray(fields.tint) && fields.tint.length === 4 && fields.tint.every(value =>
        Number.isFinite(value) && value >= 0 && value <= 8) &&
      Array.isArray(fields.mips) && fields.mips.length === 9 && [fields.texture, ...fields.mips].every(index =>
        Number.isSafeInteger(index) && index >= 0);
  }

  async function apply(T, root, parser) {
    const matches = [];
    root.traverse(node => {
      const fields = node.geometry?.userData?.mvStageBeam;
      if (node.isSkinnedMesh && !Array.isArray(node.material) && checked(fields, node.parent)) matches.push({node, fields});
    });
    if (matches.length !== 1) return null;
    const [{node, fields}] = matches;
    const owner = node.parent, original = node.material, order = node.renderOrder, culling = node.frustumCulled;
    const maps = await Promise.all([fields.texture, ...fields.mips].map(index => parser.getDependency("texture", index)));
    if (!maps.every((map, level) => map?.isTexture && map.image?.width === (512 >> level) &&
        map.image?.height === (512 >> level))) throw new Error("The original stage beam texture is incomplete.");

    const texture = maps[0].clone();
    texture.encoding = T.LinearEncoding;
    texture.wrapS = texture.wrapT = T.RepeatWrapping;
    texture.magFilter = T.LinearFilter;
    texture.minFilter = T.LinearMipmapNearestFilter;
    texture.anisotropy = 1;
    texture.generateMipmaps = false;
    texture.mipmaps = maps.map(map => map.image);
    texture.needsUpdate = true;
    const tint = new T.Vector4().fromArray(fields.tint);
    const material = new T.ShaderMaterial({
      name: "Native stage beam", vertexShader, fragmentShader, skinning: true, transparent: true,
      toneMapped: false, side: T.DoubleSide, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
      blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
      blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
      stencilWrite: true, stencilFunc: T.AlwaysStencilFunc, stencilRef: 0,
      stencilFail: T.KeepStencilOp, stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
      uniforms: {uTexture: {value: texture}, uTint: {value: tint}},
    });
    node.material = material;
    node.renderOrder = fields.renderOrder;
    node.frustumCulled = false; // Bounds change with the animated skin.
    owner.userData.mvStageOverlayChannels = {overlayTint: tint};
    let disposed = false;
    return {
      dispose() {
        if (disposed) return;
        disposed = true;
        delete owner.userData.mvStageOverlayChannels;
        node.material = original;
        node.renderOrder = order;
        node.frustumCulled = culling;
        material.dispose();
        texture.dispose();
      },
    };
  }

  global.MVStudioStageBeam = {apply};
})(typeof window !== "undefined" ? window : globalThis);
