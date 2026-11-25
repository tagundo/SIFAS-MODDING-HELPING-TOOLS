/* MVStudioScene draws the world with the stage renderers' native opaque order: MVStudioOpaqueSort
   sets the renderer's opaque comparator for that one render and clears it afterwards, also when the
   render throws. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');

const statics = path.join(__dirname, '../webtools/web/static');
const programs = new Map();
// three.js r128 painterSortStable.
function painter(a, b) {
  return a.groupOrder !== b.groupOrder ? a.groupOrder - b.groupOrder :
    a.renderOrder !== b.renderOrder ? a.renderOrder - b.renderOrder :
    a.program !== b.program ? a.program.id - b.program.id :
    a.material.id !== b.material.id ? a.material.id - b.material.id :
    a.z !== b.z ? a.z - b.z : a.id - b.id;
}

function run(withTransparentSort) {
  const frames = [];
  let throwNext = false, instance = null;
  THREE.WebGLRenderer = class {
    constructor() {
      instance = this;
      this.domElement = { setAttribute() {}, remove() {} };
      this.shadowMap = {};
      this.capabilities = { isWebGL2: true };
      this.size = new THREE.Vector2();
      this.properties = { get: material => ({ program: programs.get(material) }) };
      this.comparator = null;
    }
    setClearColor() {}
    getSize(value) { value.copy(this.size); }
    setSize(x, y) { this.size.set(x, y); }
    setPixelRatio(value) { this.ratio = value; }
    getPixelRatio() { return this.ratio; }
    setOpaqueSort(sort) { this.comparator = sort; }
    // WebGLRenderer.projectObject and the opaque list sort, for the meshes with a known program.
    render(source, camera) {
      source.updateMatrixWorld();
      camera.updateMatrixWorld();
      const viewProjection = new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
      const items = [];
      source.traverseVisible((object) => {
        if (!object.isMesh || !programs.has(object.material)) return;
        items.push({ object, id: object.id, groupOrder: 0, renderOrder: object.renderOrder, material: object.material,
          program: programs.get(object.material),
          z: new THREE.Vector3().setFromMatrixPosition(object.matrixWorld).applyMatrix4(viewProjection).z });
      });
      items.sort(this.comparator || painter);
      frames.push({ native: Boolean(this.comparator), order: items.map(({ object }) => object.name) });
      if (throwNext) {
        throwNext = false;
        throw new Error('context lost');
      }
    }
    dispose() {}
  };
  THREE.OrbitControls = class {
    constructor() { this.target = new THREE.Vector3(); }
    update() {}
    addEventListener() {}
    dispose() {}
  };
  THREE.GLTFLoader = class { parse(_bytes, _base, onLoad) { onLoad({ scene: new THREE.Group(), animations: [] }); } };
  const window = { THREE, requestAnimationFrame: () => 1, cancelAnimationFrame() {} };
  const context = { window, fetch: async () => ({ ok: false }), AbortController };
  vm.runInNewContext(fs.readFileSync(path.join(statics, 'mv-studio-opaque-sort.js'), 'utf8'), context);
  if (withTransparentSort) {
    window.MVStudioTransparentSort = { create: (_T, renderer) => ({ draw: (source, camera) => renderer.render(source, camera) }) };
  }
  // Two coplanar stage surfaces whose bounds centres sit at the drawing
  // camera and 1000 to its side. Three.js would draw "far" first (its program
  // was linked first); the native order draws "near" first.
  const material = (id) => {
    const value = new THREE.MeshBasicMaterial();
    programs.set(value, { id });
    return value;
  };
  const near = new THREE.Mesh(new THREE.PlaneGeometry(), material(2)), far = new THREE.Mesh(new THREE.PlaneGeometry(), material(1));
  near.name = 'near';
  far.name = 'far';
  near.frustumCulled = far.frustumCulled = false;
  const entries = [
    { node: near, material: near.material, center: new THREE.Vector3(), queue: 2000 },
    { node: far, material: far.material, center: new THREE.Vector3(), queue: 2000 },
  ];
  const calls = [];
  const sorting = window.MVStudioOpaqueSort;
  window.MVStudioOpaqueSort = { create(T, renderer) {
    const sorter = sorting.create(T, renderer);
    return {
      begin(source, camera, records) {
        calls.push('begin');
        assert.ok(Array.isArray(records), 'the scene records offer the stage materials');
        if (!near.parent) source.add(near, far);
        const eye = camera.getWorldPosition(new T.Vector3());
        entries[0].center.copy(eye);
        entries[1].center.copy(eye).add(new T.Vector3(1000, 0, 0));
        return sorter.begin(source, camera, [...records, { stageMaterial: { opaqueSortEntries: () => entries } }]);
      },
      end() {
        calls.push('end');
        sorter.end();
      },
    };
  } };
  vm.runInNewContext(fs.readFileSync(path.join(statics, 'mv-studio-scene.js'), 'utf8'), context);
  const app = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} }, {});
  const game = { source: { kind: 'game', region: 'gl', platform: 'android', liveId: 10120, assetId: 1012003 },
    stage: {}, assets: [], tracks: [], performers: [] };

  app.seek(1, game);
  assert.ok(frames.length > 0, 'the seek draws the world');
  assert.deepEqual(frames.at(-1), { native: true, order: ['near', 'far'] },
    'the native comparator orders the render: the nearer bounds draw first');
  assert.deepEqual(calls.slice(-2), ['begin', 'end'], 'end closes the render begin opened');
  assert.equal(instance.comparator, null, 'the comparator applies to that render only');
  // A render that throws still ends the native order.
  calls.length = frames.length = 0;
  throwNext = true;
  try {
    app.seek(2, game);
  } catch (error) {
    assert.match(error.message, /context lost/);
  }
  assert.deepEqual(frames.map(({ native }) => native), [true]);
  assert.deepEqual(calls, ['begin', 'end']);
  assert.equal(instance.comparator, null);
  app.dispose?.();
}

// Without MVStudioTransparentSort the scene renders directly; with it, its draw renders.
for (const withTransparentSort of [false, true]) run(withTransparentSort);
console.log('MV Studio scene: the opaque stage order brackets each world render.');
