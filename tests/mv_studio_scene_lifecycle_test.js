/* Real Three.js poses and resource ownership with a small instrumented renderer. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const shader = require('../webtools/web/static/sifas-material.js');

const address = (id) => '/api/mv-studio/media/' + id.toString(16).padStart(32, '0') + '.glb';
function latch() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
function fixture() {
  const frames = [], samples = [], models = new Map(), holds = new Map(), queued = new Map();
  let world, renderer, serial = 0;
  THREE.WebGLRenderer = class {
    constructor() {
      renderer = this;
      this.domElement = { setAttribute() {}, remove() {}, width: 1280, height: 720 };
      this.shadowMap = { enabled: false }; this.capabilities = { isWebGL2: true };
      this.size = new THREE.Vector2();
    }
    setClearColor() {}
    getSize(out) { return out.copy(this.size); }
    setSize(width, height) { this.size.set(width, height); }
    getPixelRatio() { return this.pixelRatio; }
    setPixelRatio(value) { this.pixelRatio = value; }
    render(scene, camera) {
      world = scene;
      if (scene.autoUpdate) scene.updateMatrixWorld();
      camera.updateMatrixWorld();
      const visible = [];
      scene.traverseVisible((node) => { if (node.isSkinnedMesh) visible.push(node.name); });
      frames.push(visible);
    }
    dispose() {}
  };
  THREE.OrbitControls = class {
    constructor() { this.target = new THREE.Vector3(); }
    update() {}
    addEventListener() {}
    dispose() {}
  };
  THREE.GLTFLoader = class {
    parse(bytes, _base, onLoad) {
      const id = new Uint8Array(bytes)[0];
      const root = new THREE.Group();
      root.userData.id = id;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute([0,0,0, 1,0,0, 0,1,0], 3));
      geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0,0,0,0, 0,0,0,0, 0,0,0,0], 4));
      geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1,0,0,0, 1,0,0,0, 1,0,0,0], 4));
      geometry.morphTargetsRelative = true;
      geometry.morphAttributes.position = [new THREE.Float32BufferAttribute([0,0,0, 0.25,0,0, 0,0,0], 3)];
      const bone = new THREE.Bone(), rig = new THREE.Skeleton([bone]);
      const mesh = new THREE.SkinnedMesh(geometry, new THREE.ShaderMaterial({ vertexShader: shader.vertexShader }));
      mesh.name = `model-${id}`;
      mesh.bind(rig, new THREE.Matrix4());
      root.add(bone, mesh);
      const info = { mesh, rig, releases: 0, materialsReleased: 0 };
      rig.dispose = () => { info.releases++; };
      models.set(id, info);
      onLoad({ scene: root, animations: [] });
    }
  };
  const window = {
    THREE, requestAnimationFrame(callback) { queued.set(++serial, callback); return serial; },
    cancelAnimationFrame(id) { queued.delete(id); },
    SifasMaterial: { ...shader, apply(root) {
      const id = root.userData.id, info = models.get(id), mesh = info.mesh;
      const outline = new THREE.SkinnedMesh(mesh.geometry, new THREE.ShaderMaterial({
        vertexShader: shader.outlineVertexShader, uniforms: { uOutlineEdited: { value: 0 } }
      }));
      outline.name = `outline-${id}`;
      outline.userData.sifasOutline = true;
      outline.bind(mesh.skeleton, mesh.bindMatrix);
      mesh.add(outline);
      info.outline = outline;
      const hold = holds.get(id);
      if (hold) hold.started.resolve();
      return { ready: hold?.finish.promise || Promise.resolve(), dispose() { info.materialsReleased++; } };
    } },
    ViewerMotionTimeline: { create(root) {
      return { evaluate(time) { samples.push([root.userData.id, time]); }, applyVisibility() {} };
    } }
  };
  async function fetch(url) {
    const id = Number.parseInt(url.split('/').at(-1), 16);
    return { ok: true, async arrayBuffer() { return Uint8Array.of(id).buffer; } };
  }
  vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-scene.js'), 'utf8'),
    { window, fetch, AbortController, Uint8Array, Uint16Array });
  const app = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} },
    { onError(message) { throw new Error(message); } });
  return { app, frames, samples, models, holds, queued, renderer, get world() { return world; } };
}

function project(id) {
  return { token: `project-${id}`, performers: [{ id: 'solo', position: 1, glb: address(id), motion: {}, transform: { position: [0,0,0] } }],
    tracks: [{ kind: 'camera', binding: '/MainCamera', events: [{ start: 0, duration: 10,
      values: { position: [0,0,10], rotation: [0,0,0,1], fov: 45 } }] }] };
}

(async () => {
  const f = fixture(), first = project(1);
  await f.app.load(first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);
  const rendered = f.frames.length, sampled = f.samples.length;
  for (const time of [1, 2, 3]) f.app.seek(time, first, true);
  assert.equal(f.frames.length, rendered);
  assert.deepEqual(f.samples.slice(sampled), [[1,1], [1,2], [1,3]]);
  assert.equal(f.queued.size, 1);
  f.app.flushSeekDraw();
  f.app.flushSeekDraw();
  assert.equal(f.frames.length, rendered + 1);
  assert.equal(f.samples.length, sampled + 3);
  f.app.seek(4, first, true);
  f.app.setVisible(false);
  assert.equal(f.queued.size, 0);
  f.app.flushSeekDraw();
  assert.equal(f.frames.length, rendered + 1);
  f.app.setVisible(true);

  first.performers[0].transform.position = [100,0,0];
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), [], 'an offscreen skinned body and its outline should both be culled');
  const info = f.models.get(1);
  assert.equal(info.mesh.visible, true, 'culling must not change visibility outside the renderer');
  f.renderer.shadowMap.enabled = true;
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);
  f.renderer.shadowMap.enabled = false;
  info.mesh.morphTargetInfluences[0] = 1.1;
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);
  info.mesh.morphTargetInfluences[0] = 0;
  info.outline.material.uniforms.uOutlineEdited.value = 1;
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);
  info.outline.material.uniforms.uOutlineEdited.value = 0;
  info.mesh.geometry.getAttribute('position').needsUpdate = true;
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);

  const hold = { started: latch(), finish: latch() };
  f.holds.set(2, hold);
  const canceled = f.app.load(project(2));
  await hold.started.promise;
  assert.equal(info.releases, 1, 'the old main and outline must release their shared skeleton once');
  await f.app.load(project(3));
  hold.finish.resolve();
  await canceled;
  assert.equal(f.models.get(2).releases, 1, 'a canceled staged skeleton must be released');
  assert.equal(f.models.get(2).materialsReleased, 1);
  assert.equal(f.models.get(3).releases, 0);
  f.app.dispose();
  assert.equal(f.models.get(3).releases, 1);
  assert.equal(f.queued.size, 0);
  console.log('MV Studio render-only scrubbing, conservative culling and skeleton lifecycle passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
