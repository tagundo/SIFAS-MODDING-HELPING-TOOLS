(function (global) {
  "use strict";

  const sameColor = Math.fround(1e-5);
  const vector = (value, size) => Array.isArray(value) && value.length === size && value.every(Number.isFinite);
  const accessor = value => Number.isInteger(value) && value >= 0;
  const vertexShader = [
    "uniform vec4 uTextureST;",
    "varying vec2 vArea;",
    "void main() {",
    "  vArea = uv * uTextureST.xy + uTextureST.zw;",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
    "}"
  ].join("\n");
  const fragmentShader = [
    "uniform sampler2D uTexture;",
    "uniform vec4 uTint;",
    "varying vec2 vArea;",
    "void main() { gl_FragColor = texture2D(uTexture, vArea) * uTint; }"
  ].join("\n");

  async function prepare(T, gltf) {
    const descriptor = gltf.scene.userData.mvSpotlightArea;
    if (!descriptor || !gltf.parser || descriptor.queue !== 3000 || !vector(descriptor.uv, 4) ||
        !vector(descriptor.translation, 3) || !vector(descriptor.rotation, 4) || !vector(descriptor.scale, 3)) return null;
    const fields = descriptor.geometry;
    const images = descriptor.textures;
    if (!fields || ![fields.position, fields.uv, fields.index].every(accessor) ||
        !Array.isArray(images) || !images.length || images.length > 10 || !images.every(accessor)) return null;
    const parser = gltf.parser;
    let position, uv, index, maps;
    try {
      [position, uv, index, maps] = await Promise.all([
        ...[fields.position, fields.uv, fields.index].map(value => parser.getDependency("accessor", value)),
        Promise.all(images.map(value => parser.getDependency("texture", value)))
      ]);
    } catch {
      return null;
    }
    if (position?.itemSize !== 3 || position.count !== 4 || uv?.itemSize !== 2 || uv.count !== 4 ||
        index?.itemSize !== 1 || index.count !== 6 || !maps.every(map => map?.isTexture && map.image)) return null;
    const { width, height } = maps[0].image;
    if (!(width > 0 && width <= 512 && height > 0 && height <= 512 &&
        T.MathUtils.isPowerOfTwo(width) && T.MathUtils.isPowerOfTwo(height))) return null;
    if (maps.length > 1 && (maps.length !== Math.log2(Math.max(width, height)) + 1 ||
        maps.some(({ image }, level) => image.width !== Math.max(1, width >> level) ||
          image.height !== Math.max(1, height >> level)))) return null;
    const geometry = new T.BufferGeometry();
    geometry.setAttribute("position", position);
    geometry.setAttribute("uv", uv);
    geometry.setIndex(index);
    const texture = maps[0].clone();
    texture.encoding = T.LinearEncoding;
    texture.wrapS = T.RepeatWrapping;
    texture.wrapT = T.RepeatWrapping;
    texture.magFilter = T.LinearFilter;
    texture.minFilter = maps.length > 1 ? T.LinearMipmapNearestFilter : T.LinearFilter;
    texture.mipmaps = maps.length > 1 ? maps.map(map => map.image) : [];
    texture.generateMipmaps = false;
    texture.needsUpdate = true;
    return { geometry, texture, descriptor, dispose() { geometry.dispose(); texture.dispose(); } };
  }

  function create(T, template, move) {
    const lighting = global.MVStudioLighting;
    if (!template || !move?.isObject3D || !lighting) return null;
    const { descriptor, geometry, texture } = template;
    const [sx, sy, x, y] = descriptor.uv;
    const tint = new T.Vector4(0, 0, 0, 0);
    const material = new T.ShaderMaterial({
      vertexShader, fragmentShader, transparent: true, depthTest: true, depthFunc: T.LessEqualDepth,
      depthWrite: false, toneMapped: false, side: T.DoubleSide, blending: T.CustomBlending,
      blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor, blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
      uniforms: { uTexture: { value: texture }, uTextureST: { value: new T.Vector4(sx, sy, x, 1 - sy - y) },
        uTint: { value: tint } }
    });
    material.name = "Native member spotlight area";
    const mesh = new T.Mesh(geometry, material);
    mesh.name = "Native member spotlight area";
    // The prefab instance's GameObject below the performer's Move node, for the runtime value dump.
    if (typeof descriptor.name === "string" && descriptor.name) mesh.userData.mvGameObjectName = descriptor.name;
    mesh.position.fromArray(descriptor.translation);
    mesh.quaternion.fromArray(descriptor.rotation);
    mesh.scale.fromArray(descriptor.scale);
    mesh.renderOrder = descriptor.queue;
    mesh.visible = false;
    move.add(mesh);

    let cached = false;
    const color = new T.Vector4(), difference = new T.Vector4();
    function reset() {
      cached = false;
      mesh.visible = false;
    }
    return {
      frame(events, time, project) {
        if (!events?.length) {
          reset();
          return;
        }
        color.set(0, 0, 0, 0);
        for (const event of events) {
          const value = event.values;
          if (value?.playableClass !== "LiveMemberSpotLightAreaClip") continue;
          const weight = lighting.nativeWeight(event, time);
          if (!(weight > 0)) continue;
          const source = lighting.memberColor(project, value.colorSpecifiedType, value.memberPosition, value.color);
          if (!source) continue;
          color.x += source[0] * weight;
          color.y += source[1] * weight;
          color.z += source[2] * weight;
          color.w += source[3] * weight;
        }
        if (cached && difference.copy(color).sub(tint).lengthSq() < sameColor) return;
        tint.copy(color);
        cached = true;
        // Mathf.Approximately(alpha, 0) matches zero at the authored weights.
        mesh.visible = Math.fround(color.w) !== 0;
      },
      reset,
      dispose() {
        move.remove(mesh);
        material.dispose();
      }
    };
  }

  global.MVStudioSpotlightArea = { prepare, create };
})(typeof window !== "undefined" ? window : globalThis);
