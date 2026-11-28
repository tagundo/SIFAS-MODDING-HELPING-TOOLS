/* MV Studio hands the member timeline's cheek its frame clock: MemberCheekMixer
   keeps the floats of the last frame a clip was processed in, so an advancing
   playback frame continues from the previous frame ({ advancing: true }), a
   seek gives the rendered frame times it was handed (seek's history: a runtime
   dump's frame grid, only those before the seek time) and a plain seek, a
   paused redraw or a rewind none. The state goes to the head material's
   setCheek. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');

THREE.WebGLRenderer = class {
  constructor() {
    this.domElement = { setAttribute() {}, remove() {}, width: 1280, height: 720 };
    this.shadowMap = { enabled: false }; this.capabilities = { isWebGL2: true }; this.size = new THREE.Vector2();
  }
  setClearColor() {}
  getSize(out) { return out.copy(this.size); }
  setSize(width, height) { this.size.set(width, height); }
  getPixelRatio() { return 1; }
  setPixelRatio() {}
  render() {}
  dispose() {}
};
THREE.OrbitControls = class {
  constructor() { this.target = new THREE.Vector3(); }
  update() {} addEventListener() {} dispose() {}
};
THREE.GLTFLoader = class {
  parse(_bytes, _base, onLoad) {
    const root = new THREE.Group(), bone = new THREE.Bone();
    bone.name = 'Move'; bone.userData.elichika_node = 1;
    root.add(bone);
    onLoad({ scene: root, animations: [] });
  }
};

const clocks = [], applied = [];
const window = {
  THREE, requestAnimationFrame() { return 1; }, cancelAnimationFrame() {},
  ResizeObserver: class { observe() {} disconnect() {} },
  SifasMaterial: { apply() { return { setCheek(name, state) { applied.push([name, state]); }, dispose() {} }; } },
  ViewerMotionTimeline: { create() {
    return { evaluatePose() {}, evaluateGaze() {}, eyePosition() {}, applyVisibility() {}, animatedProperties() { return {}; },
      cheek(time, clock) { clocks.push([time, clock && { advancing: clock.advancing, history: JSON.parse(JSON.stringify(clock.history)) }]); return { index: 0, intensity: time, enabled: true }; } };
  } },
};
const context = vm.createContext({ window, fetch: async () => ({ ok: true, async arrayBuffer() { return new ArrayBuffer(1); } }),
  AbortController, Uint8Array, Uint16Array });
for (const file of ['mv-studio-physics.js', 'mv-studio-split.js', 'mv-studio-asset-dump.js', 'mv-studio-scene.js']) {
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/' + file), 'utf8'), context);
}

(async () => {
  const scene = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} }, {
    visible: true, onError(message) { throw new Error(message); } });
  const project = { token: 'cheek-clock', quality: { mode: 30, values: {} },
    performers: [{ id: 'solo', position: 1, glb: '/api/mv-studio/media/' + '1'.padStart(32, '0') + '.glb', motion: {},
      rig: { memberHead: { cheekMaterial: 'ch0212_co0002_head' } }, transform: { position: [0, 0, 0] } }],
    tracks: [{ kind: 'camera', binding: '/MainCamera', events: [{ start: 0, duration: 10,
      values: { position: [0, 0, 10], rotation: [0, 0, 0, 1], fov: 45 } }] }] };
  await scene.load(project);
  clocks.length = 0; applied.length = 0;
  scene.seek(1, project, true);
  scene.setPlaying(true);
  scene.playbackFrame(1 + 1 / 30, 0, true);
  scene.playbackFrame(1 + 1 / 30, 1000 / 30, true);
  scene.playbackFrame(1, 2000 / 30, true);
  scene.seek(3, undefined, true, [0.5, 2, 2.9, 3, 4]);
  scene.playbackFrame(3.1, 3000 / 30, true);
  scene.setPlaying(false);
  scene.seek(2.5, undefined, true, [2.4, 0.5, 2.6]);
  scene.playbackFrame(2.5);
  assert.deepEqual(clocks.map(([time, clock]) => [time, clock.advancing, clock.history]), [
    [1, false, []],
    [1 + 1 / 30, true, []],
    [1 + 1 / 30, true, []],
    [1, false, []],
    [3, false, [0.5, 2, 2.9]],
    [3.1, true, []],
    [2.5, false, [0.5, 2.4]],
    [2.5, false, []],
  ], 'seek, advancing frames, a repeated time, a rewind, a seek with frames before t only, a paused seek (sorted), a redraw');
  assert(applied.every(([name, state]) => name === 'ch0212_co0002_head' && state.enabled === true), 'the state goes to the head material');
  assert.equal(applied.length, clocks.length);
  scene.dispose();
  console.log('MV Studio scene cheek frame clock wiring passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
