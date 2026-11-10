/* Independently authored neutral GPU scene. Does not replace SifasMaterial.apply.
 * The caller must use the actual packaged product SifasMaterial controller.
 * Names deliberately do not identify a mouth; the verified semantic role does.
 */
(function (global) {
  'use strict';
  function createNeutralSifasScene(T, fixture, options) {
    options = options || {};
    var scene = new T.Scene(), root = new T.Group(), geometry = new T.BufferGeometry();
    var camera = new T.Camera(); camera.projectionMatrix.identity();
    camera.matrixAutoUpdate = false; camera.matrix.identity(); camera.updateMatrixWorld(true);
    camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
    var texture = new T.DataTexture(new Uint8Array(fixture.texture.rgba), 2, 1, T.RGBAFormat);
    texture.minFilter = texture.magFilter = T.NearestFilter;
    texture.wrapS = texture.wrapT = T.ClampToEdgeWrapping;
    texture.generateMipmaps = false; texture.encoding = T.LinearEncoding; texture.needsUpdate = true;
    var original = new T.MeshBasicMaterial({ map: texture });
    original.name = 'Neutral shared source material';
    original.userData.sifas = { version: 1, shader: 'AS/Member', pipeline: 'gamma',
      colors: {}, floats: { _CullMode: 2, _OutlineStencilComp: 8 }, features: {},
      textures: { _MainTex: { index: 0, filterMode: 0 } } };
    var mesh = new T.Mesh(geometry, original); mesh.name = 'NeutralMouthPatch'; mesh.frustumCulled = false;
    if (options.role !== null) mesh.userData.viewerFacialRole = options.role || 'mouth';
    root.add(mesh); scene.add(root);
    function setOrder(order) {
      var position = [], normal = [], uv = [], color = [];
      (order || [0, 1]).forEach(function (index) {
        var triangle = fixture.clipTriangles[index];
        (options.reverseWinding ? triangle.vertices.slice().reverse() : triangle.vertices).forEach(function (point) {
          position.push.apply(position, point); normal.push(0, 0, 1);
          uv.push.apply(uv, triangle.uv); color.push(0, 1, 1, 1);
        });
      });
      geometry.setAttribute('position', new T.Float32BufferAttribute(position, 3));
      geometry.setAttribute('normal', new T.Float32BufferAttribute(normal, 3));
      geometry.setAttribute('uv', new T.Float32BufferAttribute(uv, 2));
      geometry.setAttribute('_sifas_color', new T.Float32BufferAttribute(color, 4));
    }
    setOrder([0, 1]);
    var occluders = [];
    function addOccluder(kind) {
      var z = kind === 'front' ? -0.4 : 0.95;
      var g = new T.BufferGeometry();
      g.setAttribute('position', new T.Float32BufferAttribute(
        fixture.clipTriangles[0].vertices.flatMap(function (p) { return [p[0], p[1], z]; }), 3));
      var m = new T.MeshBasicMaterial({ color: 0x0000ff, depthTest: true, depthWrite: true, side: T.FrontSide });
      var o = new T.Mesh(g, m); o.name = 'Neutral opaque ' + kind + ' occluder'; o.frustumCulled = false;
      // This is an independent opaque reference plane, not a facial material.
      scene.add(o); occluders.push(o); return o;
    }
    function removeOccluders() {
      occluders.forEach(function (o) { scene.remove(o); o.geometry.dispose(); o.material.dispose(); }); occluders = [];
    }
    return { scene: scene, root: root, mesh: mesh, camera: camera, geometry: geometry,
      texture: texture, originalMaterial: original, setOrder: setOrder,
      addOccluder: addOccluder, removeOccluders: removeOccluders,
      dispose: function () { removeOccluders(); geometry.dispose(); original.dispose(); texture.dispose(); } };
  }
  global.createNeutralSifasScene = createNeutralSifasScene;
}(typeof window !== 'undefined' ? window : globalThis));
