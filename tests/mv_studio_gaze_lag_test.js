/* MV Studio passes LiveMemberEyeContact's one-frame gaze lag to the member
   timeline: a continuing playback frame (a later director time with a frame
   timestamp) evaluates the gaze with { continuing: true }; a seek, a paused
   redraw or a clock rewind evaluates it with { continuing: false }. */
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

const log = [];
const window = {
  THREE, requestAnimationFrame() { return 1; }, cancelAnimationFrame() {},
  ResizeObserver: class { observe() {} disconnect() {} },
  ViewerMotionTimeline: { create() {
    return { evaluatePose() {}, evaluateGaze(time, _context, frame) { log.push([time, frame && frame.continuing]); },
      eyePosition() {}, applyVisibility() {}, animatedProperties() { return {}; } };
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
  const project = { token: 'gaze-lag', quality: { mode: 30, values: {} },
    performers: [{ id: 'solo', position: 1, glb: '/api/mv-studio/media/' + '1'.padStart(32, '0') + '.glb', motion: {},
      rig: {}, transform: { position: [0, 0, 0] } }],
    tracks: [{ kind: 'camera', binding: '/MainCamera', events: [{ start: 0, duration: 10,
      values: { position: [0, 0, 10], rotation: [0, 0, 0, 1], fov: 45 } }] }] };
  await scene.load(project);
  log.length = 0;
  scene.seek(1, project, true);
  scene.setPlaying(true);
  scene.playbackFrame(1 + 1 / 30, 0, true);
  scene.playbackFrame(1 + 2 / 30, 1000 / 30, true);
  scene.playbackFrame(1 + 2 / 30, 2000 / 30, true);
  scene.playbackFrame(1, 3000 / 30, true);
  scene.setPlaying(false);
  scene.seek(2, undefined, true);
  assert.deepEqual(log.map(([, continuing]) => continuing), [false, true, true, false, false, false],
    'seek, two continuing frames, a repeated time, a rewind and a paused seek');
  scene.dispose();
  console.log('MV Studio scene gaze lag wiring: continuing playback frames only passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
