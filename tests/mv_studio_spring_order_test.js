/* MV Studio scene wiring of the original spring stepping rule: the frame-rate rule
   picks the clock rate, LiveCoreMemberManager.Update (the "update" hook) runs before
   the timeline evaluates the members and LateUpdate (the "late" hook) after it. */
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
    return { evaluatePose(time) { log.push(['pose', time]); }, evaluateGaze() {}, eyePosition() {}, applyVisibility() {},
      animatedProperties() { return {}; } };
  } },
};
const context = vm.createContext({ window, fetch: async () => ({ ok: true, async arrayBuffer() { return new ArrayBuffer(1); } }),
  AbortController, Uint8Array, Uint16Array });
for (const file of ['mv-studio-physics.js', 'mv-studio-split.js', 'mv-studio-asset-dump.js', 'mv-studio-scene.js']) {
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/' + file), 'utf8'), context);
}
// The real rate rule and clock; the per-member model only records the hook calls.
window.MVStudioPhysics.create = () => ({
  frame(phase, time, delta, _quality, _motion, order) { log.push([phase, time, delta, order]); },
  restorePose() { log.push(['restore']); }, reset() {}, dispose() {},
});

(async () => {
  const scene = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} }, {
    visible: true, onError(message) { throw new Error(message); } });
  const project = { token: 'spring-order', quality: { mode: 30, values: { frame_rate_60fps: false, member_swing_bone_mv: true } },
    performers: [{ id: 'solo', position: 1, glb: '/api/mv-studio/media/' + '1'.padStart(32, '0') + '.glb', motion: {},
      rig: { physics: { available: true } }, transform: { position: [0, 0, 0] } }],
    tracks: [{ kind: 'camera', binding: '/MainCamera', events: [{ start: 0, duration: 10,
      values: { position: [0, 0, 10], rotation: [0, 0, 0, 1], fov: 45 } }] }] };
  await scene.load(project);
  scene.seek(1, project, true);
  scene.setPlaying(true);
  // Display frames at 60 Hz; Normal 3D requests 30 fps, so every other frame runs a job.
  const play = (frames, hz, from = 0) => {
    log.length = 0;
    for (let index = 0; index < frames; index++) scene.playbackFrame(1 + (from + index) / hz, (from + index) * 1000 / hz, true);
    return log.filter(([phase]) => phase === 'update').map(([, , delta]) => delta);
  };
  assert.deepEqual(play(4, 60), [1 / 30, 0, 1 / 30, 0], 'q30 steps at 30 Hz');
  assert.deepEqual(log.slice(0, 4).map(([phase]) => phase), ['update', 'restore', 'pose', 'late'],
    'Update steps before the timeline evaluates; LateUpdate follows it');
  assert.deepEqual(log[0], ['update', 1, 1 / 30, 'game']);
  assert.deepEqual(log[3], ['late', 1, 1 / 30, 'game']);
  assert.equal(scene.assetDump({ sections: ['clock'] }).clock.rate, 30);

  // A 30 fps FOVMOD export ticks at 60 Hz; the reference mode steps every 60 Hz frame.
  assert.equal(scene.setPhysicsTiming({ exportFps: 30 }).rate, 60);
  assert.deepEqual(play(3, 60, 4), [1 / 60, 1 / 60, 1 / 60]);
  assert.equal(scene.assetDump({ sections: ['clock'] }).clock.rate, 60);
  // Refresh-rate mode on a 120 Hz display: set_FPS(0) uses the display rate.
  assert.equal(scene.setPhysicsTiming({ exportFps: null, device: { refreshRateMode: true, displayRate: 120 } }).rate, 120);
  assert.deepEqual(play(2, 120, 20), [1 / 120, 1 / 120]);
  // CoolAssist clears FrameRate60Fps; the earlier editor order stays selectable.
  project.quality.values.frame_rate_60fps = true;
  scene.seek(1, project, true);
  assert.equal(scene.setPhysicsTiming({ device: { coolAssist: true }, order: 'same-frame' }).rate, 30);
  assert.deepEqual(play(2, 60, 40), [1 / 30, 0]);
  assert.deepEqual(log.slice(0, 4).map(([phase, , , order]) => [phase, order]),
    [['update', 'same-frame'], ['restore', undefined], ['pose', undefined], ['late', 'same-frame']]);
  assert.equal(scene.setPhysicsTiming({ device: {}, order: 'game' }).rate, 60, 'Max 3D requests 60 fps');
  assert.throws(() => scene.setPhysicsTiming({ order: 'lagged' }), /game or same-frame/);

  // The runtime dump's read point: the next frame's LiveCoreMemberManager.Update on its own. Only the
  // update hook runs, once, at the time of the last evaluated frame (the pose it ended with); the timeline,
  // restorePose and LateUpdate do not.
  play(2, 60, 60);
  log.length = 0;
  assert.equal(scene.stepPhysicsUpdate(62 * 1000 / 60), 1 / 60);
  assert.deepEqual(log, [['update', 1 + 61 / 60, 1 / 60, 'game']]);
  assert.equal(scene.inspect().time, 1 + 61 / 60, 'the director time does not move');
  // A display frame inside the same game frame has no job, as in playback.
  log.length = 0;
  assert.equal(scene.stepPhysicsUpdate(62 * 1000 / 60 + 1), 0);
  assert.deepEqual(log, [['update', 1 + 61 / 60, 0, 'game']]);
  // The same-frame order runs its job after the timeline, so it has no pre-timeline step.
  scene.setPhysicsTiming({ order: 'same-frame' });
  play(1, 60, 70);
  assert.equal(scene.stepPhysicsUpdate(71 * 1000 / 60), 0);
  scene.setPhysicsTiming({ order: 'game' });
  scene.setPlaying(false);
  log.length = 0;
  assert.equal(scene.stepPhysicsUpdate(80 * 1000 / 60), 0, 'paused: no step');
  assert.deepEqual(log, []);
  scene.setPlaying(true);

  // Paused frames run the hooks without a job, so the held output is shown.
  scene.setPlaying(false);
  log.length = 0;
  scene.seek(2, undefined, true);
  assert.deepEqual(log.filter(([phase]) => phase === 'update' || phase === 'late').map(([phase, , delta]) => [phase, delta]),
    [['update', 0], ['late', 0]]);
  scene.dispose();
  console.log('MV Studio scene spring wiring: frame-rate rule, Update before the timeline, LateUpdate after it passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
