(function (global) {
  "use strict";

  const vertexShader = `
    attribute vec4 centerAndSize;
    attribute vec4 particleColor;
    uniform vec4 uAtlas;
    uniform float uMaxWidth;
    varying vec2 vParticleUV;
    varying vec4 vParticleColor;
    #ifdef STRETCHED
    attribute vec3 velocity;
    uniform vec2 uStretch;

    float reciprocalSqrtEstimate(float squared) {
      // The native ARM estimate rounds the reciprocal square root of the
      // midpoint of a mantissa bin. Scale an exponent pair into [1,4).
      float exponentPair = floor(log2(squared) * 0.5);
      float scale = exp2(-exponentPair);
      float normalized = squared * scale * scale;
      float bins = normalized < 2.0 ? 128.0 : 64.0;
      float midpoint = (floor(normalized * bins) + 0.5) / bins;
      return floor(512.0 * inversesqrt(midpoint) + 0.5) * (scale / 512.0);
    }
    #endif

    void main() {
      vec4 head = modelViewMatrix * vec4(centerAndSize.xyz, 1.0);
      float depth = -head.z;
      float width = centerAndSize.w;
      float limit = (2.0 * uMaxWidth) / abs(projectionMatrix[0][0]);
      if (projectionMatrix[3][3] == 1.0) width = min(width, limit);
      else if (depth >= 0.0) width = min(width, limit * depth);
      vec4 point = head;
      #ifdef STRETCHED
      vec3 movement = mat3(modelViewMatrix) * velocity;
      float squared = dot(movement, movement);
      if (squared > 1.0e-30) {
        // Reflection negates the cross product. The head stays anchored and
        // its tail extends along the full 3D velocity, including view depth.
        vec2 across = -cross(head.xyz, movement).xy;
        float sideSquared = dot(across, across);
        if (sideSquared > 1.0e-30) {
          point.xy += across * inversesqrt(sideSquared) * (0.5 * width * position.y);
        }
        if (position.x > 0.0) {
          float sizeLength = centerAndSize.w * uStretch.x;
          float lengthPerSpeed = uStretch.y + sizeLength * reciprocalSqrtEstimate(squared) * 1.0019569397;
          point.xyz -= movement * lengthPerSpeed;
        }
      }
      #else
      vec3 corner = vec3(-position.x, position.y, 0.0) * (0.5 * width);
      point.xyz += mat3(modelViewMatrix) * corner;
      #endif
      gl_Position = projectionMatrix * point;
      vParticleUV = uv * uAtlas.xy + uAtlas.zw;
      vParticleColor = particleColor;
    }
  `;
  const fragmentShader = `
    uniform sampler2D uTexture;
    varying vec2 vParticleUV;
    varying vec4 vParticleColor;
    void main() { gl_FragColor = texture2D(uTexture, vParticleUV) * vParticleColor; }
  `;

  const roles = new Set(["speed", "speed_R", "speed_L", "stars"]);
  const vector = (value, width) => Array.isArray(value) && value.length === width && value.every(Number.isFinite);

  function checked(row) {
    if (!row || !roles.has(row.name) || !vector(row.position, 3) ||
        !Number.isInteger(row.capacity) || row.capacity < 1 || row.capacity > 1024 ||
        !vector(row.uv, 4) || !(row.maxViewportWidth > 0 && row.maxViewportWidth <= 1)) return false;
    const [sx, sy, ox, oy] = row.uv;
    if (!(sx > 0 && sy > 0 && ox >= 0 && oy >= 0 && ox + sx <= 1 && oy + sy <= 1)) return false;
    const {stretch} = row;
    return row.name === "stars" ? stretch == null : !!stretch &&
      Number.isFinite(stretch.lengthScale) && stretch.lengthScale >= 0 && stretch.lengthScale <= 32 &&
      Number.isFinite(stretch.velocityScale) && stretch.velocityScale >= 0 && stretch.velocityScale <= 1;
  }

  function create(T, group, rows, atlas) {
    const simulation = global.MVStudioCompanionSimulation;
    if (!group?.isObject3D || !atlas?.isTexture || !simulation?.create || !Array.isArray(rows) ||
        rows.length < 1 || rows.length > 4 || !rows.every(checked) ||
        new Set(rows.map(row => row.name)).size !== rows.length) return null;
    const sources = rows.map(row => simulation.create(row));
    if (sources.some(source => typeof source?.sample !== "function")) return null;
    const batches = [], rotation = new T.Quaternion();
    let disposed = false;

    function dispose() {
      if (disposed) return;
      disposed = true;
      for (const {mesh} of batches) {
        group.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
    }

    try {
      for (let i = 0; i < rows.length; i++) {
        const row = rows[i], source = sources[i], {capacity, stretch} = row;
        const geometry = new T.InstancedBufferGeometry();
        geometry.setAttribute("position", new T.Float32BufferAttribute([-1, 1, 0, 1, 1, 0, 1, -1, 0, -1, -1, 0], 3));
        geometry.setAttribute("uv", new T.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
        geometry.setIndex([0, 2, 1, 0, 3, 2]);
        const centers = new T.InstancedBufferAttribute(new Float32Array(capacity * 4), 4).setUsage(T.DynamicDrawUsage);
        const colors = new T.InstancedBufferAttribute(new Uint8Array(capacity * 4), 4, true).setUsage(T.DynamicDrawUsage);
        const velocities = stretch ? new T.InstancedBufferAttribute(new Float32Array(capacity * 3), 3)
          .setUsage(T.DynamicDrawUsage) : null;
        geometry.setAttribute("centerAndSize", centers);
        geometry.setAttribute("particleColor", colors);
        if (velocities) geometry.setAttribute("velocity", velocities);
        geometry.instanceCount = 0;
        const material = new T.ShaderMaterial({
          name: "Native stage moving particles", vertexShader, fragmentShader,
          defines: stretch ? {STRETCHED: 1} : {},
          uniforms: {uTexture: {value: atlas}, uAtlas: {value: new T.Vector4().fromArray(row.uv)},
            uMaxWidth: {value: row.maxViewportWidth},
            ...(stretch ? {uStretch: {value: new T.Vector2(stretch.lengthScale, stretch.velocityScale)}} : {})},
          transparent: true, toneMapped: false, side: T.DoubleSide,
          depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
          blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
          blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
          stencilWrite: true, stencilRef: 2, stencilFunc: T.EqualStencilFunc,
          stencilFuncMask: 255, stencilWriteMask: 255, stencilFail: T.KeepStencilOp,
          stencilZFail: T.KeepStencilOp, stencilZPass: T.KeepStencilOp,
        });
        const mesh = new T.Mesh(geometry, material);
        mesh.name = `Native stage moving ${row.name}`;
        mesh.renderOrder = 2900;
        mesh.visible = false;
        mesh.matrixAutoUpdate = false;
        // Expanded shader vertices are outside the static unit quad bounds.
        mesh.frustumCulled = false;
        // Unity uses the procedural simulation envelope for renderer sorting.
        const offset = row.name === "speed" ? 25 : row.name === "stars" ? 10 : 0;
        const center = new T.Vector3(0, 0, offset).applyQuaternion(rotation.fromArray(row.rotation));
        center.set(center.x + row.position[0], center.y + row.position[1], center.z + row.position[2]);
        batches.push({mesh, center, source, centers, colors, velocities, capacity});
        group.add(mesh);
      }
    } catch (error) {
      dispose();
      return null;
    }

    function update(age, fps, visible) {
      if (disposed) return;
      for (const batch of batches) {
        const {mesh, source, centers, colors, velocities, capacity} = batch;
        const geometry = mesh.geometry;
        if (!visible || !Number.isFinite(age) || age < 0 || !Number.isFinite(fps) || fps <= 0) {
          mesh.visible = false;
          geometry.instanceCount = 0;
          continue;
        }
        let count = 0;
        source.sample(age, fps, (px, py, pz, vx, vy, vz, size, r, g, b, a) => {
          if (count >= capacity || size <= 0 || a <= 0) return;
          centers.setXYZW(count, px, py, pz, size);
          // The Color32 buffer is normalized by the vertex fetch itself.
          const offset = count * 4;
          colors.array[offset] = r;
          colors.array[offset + 1] = g;
          colors.array[offset + 2] = b;
          colors.array[offset + 3] = a;
          if (velocities) velocities.setXYZ(count, vx, vy, vz);
          count++;
        });
        geometry.instanceCount = count;
        mesh.visible = count > 0;
        if (!count) continue;
        for (const attribute of velocities ? [centers, colors, velocities] : [centers, colors]) {
          attribute.updateRange.offset = 0;
          attribute.updateRange.count = count * attribute.itemSize;
          attribute.needsUpdate = true;
        }
      }
    }

    return {update, dispose, batches};
  }

  global.MVStudioMovingCompanions = {create};
})(typeof window !== "undefined" ? window : globalThis);
