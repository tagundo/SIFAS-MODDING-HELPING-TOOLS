/* The actual scene controller with synchronous, small Three.js test assets. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const url = (number) => '/api/mv-studio/media/' + number.toString(16).padStart(32, '0') + '.glb';
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
function harness() {
  const fetched = [], parsed = new Map(), errors = [], building = new Map(), unavailable = new Set();
  let world;
  THREE.WebGLRenderer = class {
    constructor() {
      this.domElement = { setAttribute() {}, remove() {} };
      this.shadowMap = {};
      this.capabilities = { isWebGL2: true };
      this.size = new THREE.Vector2();
    }
    setClearColor() {}
    getSize(value) { value.copy(this.size); }
    setSize(x, y) { this.size.set(x, y); }
    setPixelRatio(value) { this.ratio = value; }
    getPixelRatio() { return this.ratio; }
    render(scene) { world = scene; }
    dispose() {}
  };
  THREE.OrbitControls = class {
    constructor() { this.target = new THREE.Vector3(); }
    update() {}
    addEventListener() {}
    dispose() {}
  };
  THREE.GLTFLoader = class {
    parse(bytes, base, onLoad) {
      const key = new Uint8Array(bytes)[0];
      const scene = new THREE.Group();
      scene.userData.model = key;
      const bone = new THREE.Bone();
      const geometry = new THREE.BoxGeometry();
      const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
      mesh.morphTargetInfluences = [.25];
      bone.add(mesh); scene.add(bone);
      const result = { scene, animations: [], bone, mesh, discarded: 0 };
      geometry.addEventListener('dispose', () => { result.discarded++; });
      if (!parsed.has(key)) parsed.set(key, []);
      parsed.get(key).push(result);
      onLoad(result);
    }
  };
  const window = {
    THREE, requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    SifasMaterial: { apply(scene) {
      const pending = building.get(scene.userData.model);
      if (pending) pending.started.resolve();
      return { ready: pending ? pending.resume.promise : Promise.resolve(), dispose() {} };
    }},
    ViewerMotionTimeline: { create(root) {
      const bone = root.children[0];
      const mesh = bone.children[0];
      return {
        evaluatePose(time) {
          if (time >= 2) { bone.position.x = 4; mesh.morphTargetInfluences[0] = .75; }
        },
        evaluateGaze() {}, eyePosition() {},
        applyVisibility(time) { if (time >= 2) mesh.visible = false; }
      };
    }}
  };
  async function fetch(address, { signal }) {
    assert(!signal.aborted);
    const key = Number.parseInt(path.basename(address), 16);
    fetched.push(key);
    return { ok: !unavailable.has(key), async arrayBuffer() { return Uint8Array.of(key).buffer; } };
  }
  vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-scene.js'), 'utf8'),
    { window, fetch, AbortController });
  const app = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} },
    { onError: message => errors.push(message) });
  const roots = () => world.children.slice(0, 3).map(group => group.children.slice());
  return { app, roots, fetched, parsed, errors, building, unavailable };
}
const original = {
  token: 'project-one', stage: { glb: url(1), effectsGlb: url(2) }, assets: [], tracks: [],
  performers: [
    { id: 'left', position: 1, glb: url(3), rig: { variant: 1 }, motion: {} },
    { id: 'right', position: 2, glb: url(4), rig: { variant: 2 }, motion: {} },
  ],
};
const choice = { reuseOutfit: 'left' };
function swap(project, key) {
  const next = structuredClone(project);
  next.performers[0] = { id: 'left', glb: url(key), transform: { position: [-1, 0, 0] } };
  return next;
}
function checkSameRoots(before, after) {
  assert.equal(after[0][0], before[0][0], 'stage');
  assert.equal(after[2][0], before[2][0], 'effects');
  assert.equal(after[1][1], before[1][1], 'unchanged performer');
}

(async () => {
  const { app, roots, fetched, parsed, errors, building, unavailable } = harness();
  await app.load(original);
  const before = roots();
  app.seek(4, original);
  const right = parsed.get(4)[0];
  assert.equal(right.bone.position.x, 4);
  assert.equal(right.mesh.visible, false);
  const next = swap(original, 5);
  const start = fetched.length;
  const replacement = app.load(next, choice);
  app.seek(0, next);
  await replacement;
  const updated = roots();
  assert.deepEqual(fetched.slice(start), [5]);
  checkSameRoots(before, updated);
  assert.equal(updated[1][0].userData.model, 5);
  assert.equal(parsed.get(3)[0].discarded, 1);
  assert.equal(right.discarded, 0);
  assert.equal(right.bone.position.x, 0, 'retained actor starts from the authored pose after seeking into an inactive gap');
  assert.equal(right.mesh.morphTargetInfluences[0], .25);
  assert.equal(right.mesh.visible, true);

  const stale = { started: deferred(), resume: deferred() };
  building.set(6, stale);
  const waiting = app.load(swap(next, 6), choice);
  await stale.started.promise;
  await app.load(swap(next, 7), choice);
  stale.resume.resolve();
  await waiting;
  const afterRace = roots();
  checkSameRoots(before, afterRace);
  assert.equal(afterRace[1][0].userData.model, 7);
  assert.equal(parsed.get(6)[0].discarded, 1, 'only the stale detached model is disposed');
  assert.deepEqual(errors, []);

  const changedRig = swap(next, 8);
  changedRig.performers[1].rig.variant = 3;
  const changedAt = fetched.length;
  await app.load(changedRig, choice);
  assert.deepEqual(fetched.slice(changedAt), [1, 2, 8, 4], 'changes outside the targeted actor use the original reload');
  assert.notEqual(roots()[1][1], right.scene);
  const differentProject = swap(changedRig, 9);
  differentProject.token = 'different-project';
  const freshAt = fetched.length;
  await app.load(differentProject, choice);
  assert.deepEqual(fetched.slice(freshAt), [1, 2, 9, 4], 'fresh projects reload even with matching assets');

  unavailable.add(10);
  const beforeFailure = roots(), failureAt = fetched.length;
  await app.load(swap(differentProject, 10), choice);
  assert.deepEqual(fetched.slice(failureAt), [10]);
  assert.equal(roots()[0][0], beforeFailure[0][0]);
  assert.equal(roots()[1][0], beforeFailure[1][1], 'the existing incomplete-preview error path retains the unaffected actor');
  assert.equal(parsed.get(9)[0].discarded, 1);
  assert.deepEqual(errors, ['The preview asset is unavailable. Load it again.']);
  app.dispose();
  console.log('PASS: guarded outfit swap, neutral pose, detached cancellation, fallbacks, and failed asset cleanup');
})().catch(error => { console.error(error); process.exitCode = 1; });
