(function (global) {
  "use strict";

  const vertexShader = [
    "attribute float vertexOpacity;",
    "varying float vOpacity;",
    "void main() {",
    "  vOpacity = vertexOpacity;",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
    "}"
  ].join("\n");
  const fragmentShader = [
    "uniform vec4 uTint;",
    "varying float vOpacity;",
    "void main() { gl_FragColor = vec4(uTint.rgb, uTint.a * vOpacity); }"
  ].join("\n");

  const vector = (value, size) => Array.isArray(value) && value.length === size &&
    value.every(number => Number.isFinite(number) && Math.abs(number) <= 1000);
  const byte = value => Number.isInteger(value) && value >= 0 && value <= 255;
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;

  function validMesh(mesh, validCurve, boundedCurve) {
    const {name, positions, indices, alpha, tintCurves, matrix} = mesh || {};
    return id(name) && Array.isArray(positions) && positions.length >= 3 && positions.length <= 128 &&
      positions.every(position => vector(position, 3)) && Array.isArray(alpha) &&
      alpha.length === positions.length && alpha.every(byte) &&
      Array.isArray(indices) && indices.length > 0 && indices.length <= 768 && indices.length % 3 === 0 &&
      indices.every(index => Number.isInteger(index) && index >= 0 && index < positions.length) &&
      vector(matrix, 16) && Array.isArray(tintCurves) && tintCurves.length === 4 &&
      tintCurves.every(curve => boundedCurve(curve, validCurve));
  }

  function apply(T, root, descriptor) {
    const title = global.MVStudioTitle, curves = global.MVStudioStageMotion;
    if (!root?.isObject3D || !descriptor || !title?.neutralClip || !curves?.evaluate ||
        !id(descriptor.trackId) || !id(descriptor.eventId) || !Number.isFinite(descriptor.duration) ||
        descriptor.duration <= 0 || descriptor.duration > 15 ||
        !Array.isArray(descriptor.meshes) || descriptor.meshes.length !== 2 ||
        !descriptor.meshes.every(mesh => validMesh(mesh, curves.validCurve, title.boundedCurve))) return null;
    const group = new T.Group();
    group.name = "Native stage spotlight";
    group.visible = false;
    const records = descriptor.meshes.map(source => {
      const geometry = new T.BufferGeometry();
      geometry.setAttribute("position", new T.Float32BufferAttribute(source.positions.flat(), 3));
      geometry.setAttribute("vertexOpacity", new T.Uint8BufferAttribute(source.alpha, 1, true));
      geometry.setIndex(source.indices);
      const tint = new T.Vector4();
      const material = new T.ShaderMaterial({
        name: "Native stage spotlight", vertexShader, fragmentShader, transparent: true,
        toneMapped: false, side: T.DoubleSide, depthTest: true, depthFunc: T.LessEqualDepth, depthWrite: false,
        blending: T.CustomBlending, blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor,
        blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
        uniforms: {uTint: {value: tint}},
      });
      const mesh = new T.Mesh(geometry, material);
      mesh.name = source.name;
      mesh.renderOrder = 3010;
      // In the source skin, every vertex follows one joint with unit weight
      // and an identity inverse bind. Its original fixed pose is the matrix.
      mesh.matrix.fromArray(source.matrix);
      mesh.matrixAutoUpdate = false;
      group.add(mesh);
      return {mesh, tint, curves: source.tintCurves};
    });
    root.add(group);
    let tracks, track, disposed = false;
    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          const matches = (tracks || []).filter(row => row.id === descriptor.trackId &&
            row.nativeClass === "CustomControlTrack");
          track = matches.length === 1 ? matches[0] : null;
        }
        const event = !track?.muted && track?.events.find(row => row.id === descriptor.eventId);
        group.visible = Boolean(project?.quality?.values?.stage_control !== false && title.neutralClip(event) &&
          time >= event.start && time < event.start + event.duration);
        if (!group.visible) return;
        // This one-state controller holds its last frame before the cue ends.
        const elapsed = Math.min(descriptor.duration, time - event.start);
        for (const record of records) record.tint.set(...record.curves.map(curve => curves.evaluate(curve, elapsed)));
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        root.remove(group);
        for (const {mesh} of records) {
          mesh.material.dispose();
          mesh.geometry.dispose();
        }
      },
    };
  }

  global.MVStudioStageSpotlight = {apply};
})(typeof window !== "undefined" ? window : globalThis);
