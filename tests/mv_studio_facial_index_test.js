/* An edited MemberEyeClip / MemberLipSyncClip index previews live: the facial controller is
   rebuilt with the edited index, the imported index comes back on revert, and an unedited
   project (or an edit the preview does not play, such as paramName) never rebuilds it. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');

const address = (id) => '/api/mv-studio/media/' + id.toString(16).padStart(32, '0') + '.glb';

function fixture() {
  const created = [], models = new Map();
  THREE.WebGLRenderer = class {
    constructor() {
      this.domElement = { setAttribute() {}, remove() {}, width: 1280, height: 720 };
      this.shadowMap = { enabled: false }; this.capabilities = { isWebGL2: true };
      this.size = new THREE.Vector2();
    }
    setClearColor() {}
    getSize(out) { return out.copy(this.size); }
    setSize(width, height) { this.size.set(width, height); }
    getPixelRatio() { return 1; }
    setPixelRatio() {}
    getDrawingBufferSize(out) { return out.copy(this.size); }
    render() {}
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
      geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0], 3));
      geometry.morphAttributes.position = [new THREE.Float32BufferAttribute([0, 0, 0, 0.25, 0, 0, 0, 0, 0], 3)];
      const face = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
      face.name = 'face';
      face.updateMorphTargets();
      root.add(face);
      models.set(id, { root, face });
      onLoad({ scene: root, animations: [] });
    }
  };
  const window = {
    THREE, requestAnimationFrame() { return 1; }, cancelAnimationFrame() {},
    ResizeObserver: class { observe() {} disconnect() {} },
  };
  // A controller that records the facial indices it was bound with, and writes the face
  // (as the real one does) so a rebuild must start from the loaded pose again.
  const stub = {
    create(root, animations, rig, motion) {
      const face = root.getObjectByName('face');
      created.push({ root: root.userData.id, morph: face.morphTargetInfluences[0], visible: face.visible,
        facial: motion.facial.events.map((event) => [event.nativeEventId, event.index]), rig, animations });
      return {
        evaluatePose() { face.morphTargetInfluences[0] = 0.7; face.visible = false; },
        evaluateGaze() {}, eyePosition() { return false; }, applyVisibility() {}, invalidateTiming() {},
      };
    },
  };
  const context = vm.createContext({ window, fetch: async (url) => {
    const id = Number.parseInt(url.split('/').at(-1), 16);
    return { ok: true, async arrayBuffer() { return Uint8Array.of(id).buffer; } };
  }, AbortController, Uint8Array, Uint16Array });
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), context);
  const real = window.ViewerMotionTimeline;
  window.ViewerMotionTimeline = { ...real, create: stub.create };
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-scene.js'), 'utf8'), context);
  const app = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} },
    { visible: true, onError(message) { throw new Error(message); } });
  return { app, created, models, window, real };
}

function project({ eye = 4, lip = 13, paramName = 'a', originals = null } = {}) {
  const facial = (kind, id, index) => ({ kind, index, nativeEventId: id, start: 0, duration: 4, clipIn: 0, timeScale: 1,
    weight: 1, label: id, timing: {} });
  const value = {
    token: 'facial', duration: 10,
    performers: [{ id: 'solo', position: 1, glb: address(7), transform: { position: [0, 0, 0] },
      rig: { marker: 'rig' }, motion: { bodySegments: [], facial: { events: [facial('eyes', 'eye:0', 4), facial('mouth', 'lip:0', 13),
        facial('mouth', 'lip:1', 1)] } } }],
    tracks: [
      { id: 'eye', kind: 'eyes', label: 'MemberFacial/Member1/Eye', events: [
        { id: 'eye:0', start: 0, duration: 4, label: 'eye:0', values: { playableClass: 'MemberEyeClip', index: eye, weight: 1 } }] },
      { id: 'lip', kind: 'mouth', label: 'MemberFacial/Member1/Mouth', events: [
        { id: 'lip:0', start: 0, duration: 4, label: 'lip:0', values: { playableClass: 'MemberLipSyncClip', index: lip, paramName, weight: 1 } },
        // Imported as the vowel of its paramName (index 0 + 'a' -> 1).
        { id: 'lip:1', start: 4, duration: 4, label: 'lip:1', values: { playableClass: 'MemberLipSyncClip', index: 0, paramName: 'a', weight: 1 } }] },
    ],
  };
  if (originals) value.editor = { version: 1, originals };
  return value;
}

const indices = (entry) => Object.fromEntries(entry.facial);
const eyeEvent = (value) => value.tracks[0].events[0];
const lipEvent = (value, index = 0) => value.tracks[1].events[index];

(async () => {
  assert.deepEqual([...fixture().real.LIVE_FACIAL_IDS.eyes], [1, 2, 3, 4, 5, ...Array.from({ length: 14 }, (_, i) => 12 + i), 101, 102, 900, 999]);
  assert.deepEqual([...fixture().real.LIVE_FACIAL_IDS.mouth], [...Array.from({ length: 21 }, (_, i) => i), 101, 102, 999]);

  // Unedited: the controller is created once and never again while scrubbing.
  {
    const f = fixture(), value = project();
    await f.app.load(value);
    for (const time of [0, 1, 2.5, 6, 1]) f.app.seek(time, value);
    assert.equal(f.created.length, 1, 'an unedited project binds its facial clips once');
    assert.deepEqual(indices(f.created[0]), { 'eye:0': 4, 'lip:0': 13, 'lip:1': 1 });
    assert.deepEqual(f.created[0].rig, { marker: 'rig' });
    f.app.dispose();
  }

  // Edit, scrub, revert, and edits the preview does not play.
  {
    const f = fixture(), value = project();
    await f.app.load(value);
    f.app.seek(1, value);
    assert.equal(f.created.length, 1);
    const face = f.models.get(7).face;
    assert.equal(face.morphTargetInfluences[0], 0.7, 'the stub controller wrote the face');

    // The editor keeps the original before the first change (history.originals.ensure).
    value.editor = { version: 1, originals: { 'eye:0': JSON.parse(JSON.stringify(eyeEvent(value))) } };
    eyeEvent(value).values.index = 16;
    f.app.seek(1, value);
    assert.equal(f.created.length, 2, 'an edited eye index rebuilds the facial controller');
    assert.deepEqual(indices(f.created[1]), { 'eye:0': 16, 'lip:0': 13, 'lip:1': 1 });
    assert.equal(f.created[1].morph, 0, 'the new controller starts from the loaded face, not the old one\'s writes');
    assert.equal(f.created[1].visible, true);
    for (const time of [0, 2, 3.5, 1]) f.app.seek(time, value);
    assert.equal(f.created.length, 2, 'scrubbing an edited project does not rebuild again');

    eyeEvent(value).values.index = 4;
    f.app.seek(1, value);
    assert.equal(f.created.length, 3, 'reverting rebuilds once more');
    assert.deepEqual(indices(f.created[2]), { 'eye:0': 4, 'lip:0': 13, 'lip:1': 1 });

    lipEvent(value).values.paramName = 'o';
    lipEvent(value).values.weight = 0.5;
    f.app.seek(1, value);
    assert.equal(f.created.length, 3, 'a lip-sync paramName (or weight) edit does not rebuild');

    // Index 0 plays the paramName vowel, as the import maps it.
    lipEvent(value).values.paramName = 'e';
    lipEvent(value).values.index = 0;
    f.app.seek(1, value);
    assert.equal(f.created.length, 4);
    assert.deepEqual(indices(f.created[3]), { 'eye:0': 4, 'lip:0': 4, 'lip:1': 1 });
    lipEvent(value).values.index = 2;
    f.app.seek(1, value);
    assert.deepEqual(indices(f.created.at(-1)), { 'eye:0': 4, 'lip:0': 2, 'lip:1': 1 });
    // An unedited index 0 keeps its imported vowel whatever paramName says.
    lipEvent(value, 1).values.paramName = 'u';
    f.app.seek(5, value);
    assert.equal(f.created.length, 5);
    lipEvent(value).values.index = 13;
    f.app.seek(1, value);
    assert.equal(f.created.length, 6);
    assert.deepEqual(indices(f.created.at(-1)), { 'eye:0': 4, 'lip:0': 13, 'lip:1': 1 });
    f.app.dispose();
  }

  // A saved project with an edited index opens with the edit (the original is in editor.originals).
  {
    const f = fixture();
    const value = project({ eye: 18 });
    value.editor = { version: 1, originals: { 'eye:0': { ...JSON.parse(JSON.stringify(eyeEvent(value))), values: { playableClass: 'MemberEyeClip', index: 4, weight: 1 } } } };
    await f.app.load(value);
    f.app.seek(0, value);
    assert.deepEqual(indices(f.created.at(-1)), { 'eye:0': 18, 'lip:0': 13, 'lip:1': 1 });
    const count = f.created.length;
    f.app.seek(2, value);
    assert.equal(f.created.length, count);
    f.app.dispose();
  }
  console.log('MV Studio live facial index preview passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
