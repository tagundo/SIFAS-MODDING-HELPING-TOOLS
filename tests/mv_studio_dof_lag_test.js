/* MV Studio scene wiring of the native DOF focus parts and update order.
   LiveDepthOfFieldMixer runs in the director's script pass, before the frame's
   Animator writes MainCamera and the members, so a continuing playback frame
   measures the focus distance with the transforms the previous frame left
   (Max 3D 12035: the first game frame after a cut keeps the old shot's focus).
   A seek evaluates the current pose. BodyPartManager.face is a fixed world point. */
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
    const root = new THREE.Group(), head = new THREE.Bone();
    head.name = 'Head'; head.userData.elichika_node = 5; head.position.set(0, 1.5, 0);
    root.add(head);
    onLoad({ scene: root, animations: [] });
  }
};

const window = {
  THREE, requestAnimationFrame() { return 1; }, cancelAnimationFrame() {},
  ResizeObserver: class { observe() {} disconnect() {} },
  console: { warn() {} },
};
const context = vm.createContext({ window, fetch: async () => ({ ok: true, async arrayBuffer() { return new ArrayBuffer(1); } }),
  AbortController, Uint8Array, Uint16Array });
for (const file of ['mv-studio-lighting.js', 'mv-studio-dof-focus.js', 'mv-studio-split.js', 'mv-studio-asset-dump.js', 'mv-studio-scene.js']) {
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/' + file), 'utf8'), context);
}

const camera = '/EntryPoint/Live/Cameras/MainCamera';
const dof = (start, duration, bodyPart) => ({ start, duration, values: { playableClass: 'LiveDepthOfFieldClip', focusDistance: 1,
  aperture: 4, focalLength: 15, kernelSize: 0, useMemberDistance: 1, memberPosition: 1, bodyPart, useCameraFov: 1 } });
const shot = (start, z) => ({ start, duration: 2, values: { position: [0, 1.5, z], rotation: [0, 0, 0, 1], fov: 30 } });
const close = (actual, expected, message) => assert(Math.abs(actual - expected) < 1e-5, `${message}: ${actual} vs ${expected}`);

(async () => {
  const scene = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} }, {
    visible: true, onError(message) { throw new Error(message); } });
  const track = { binding: camera, nativeClass: 'LiveDepthOfFieldTrack', events: [dof(0, 4, 0)] };
  const project = { token: 'dof-lag', quality: { mode: 10, values: { posteffect: true } },
    performers: [{ id: 'solo', position: 1, glb: '/api/mv-studio/media/' + '1'.padStart(32, '0') + '.glb',
      rig: { focusParts: { 0: 5, 2: { world: [3, 0, 4] }, 3: 99 } }, transform: { position: [0, 0, 0] } }],
    tracks: [{ kind: 'camera', binding: camera, events: [shot(0, 4), shot(2, 10)] }, track] };
  await scene.load(project);
  const focus = () => scene.assetDump({ sections: ['post'] }).post.dof.distance;

  scene.seek(1.9, project, true);
  close(focus(), 4 - 0.1, 'a seek measures the current pose');
  scene.setPlaying(true);
  scene.playbackFrame(1.9, 0, true);
  scene.playbackFrame(2.1, 200, true);
  close(focus(), 4 - 0.1, 'the first frame after the cut keeps the previous frame camera');
  scene.playbackFrame(2.3, 400, true);
  close(focus(), 10 - 0.1, 'the next frame measures the new shot');
  scene.seek(2.1, undefined, true);
  close(focus(), 10 - 0.1, 'a seek is not a continuing frame');
  scene.playbackFrame(2.1, 600, true);
  close(focus(), 10 - 0.1, 'a frame at the same director time is not lagged');

  // BodyPartType Face 2: the uninstantiated facial prefab's fixed Unity world point (mirrored X).
  track.events = [dof(0, 4, 2)];
  scene.seek(2.5, project, true);
  close(focus(), Math.hypot(-3 - 0, 0 - 1.5, 4 - 10) - 0.1, 'Face focuses on the facial prefab asset position');
  // An exported part id that is not in the model falls back to focusDistance.
  track.events = [dof(0, 4, 3)];
  scene.seek(2.6, project, true);
  close(focus(), 1, 'a missing part keeps the clip focusDistance');
  scene.dispose();

  // cameraAutoDistanceMode 2: the member nearest the view axis, with the
  // mixer's focusTransitionTime lerp advanced once per evaluated frame, also
  // when playback frames are not drawn.
  const axisScene = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} }, {
    visible: true, onError(message) { throw new Error(message); } });
  const axis = dof(0, 4, 0);
  Object.assign(axis.values, { cameraAutoDistanceMode: 2, focusTransitionTime: 1 });
  const member = (position, x, z) => ({ id: 'm' + position, position, glb: '/api/mv-studio/media/' + String(position).padStart(32, '0') + '.glb',
    rig: { focusParts: { 0: 5 } }, transform: { position: [x, 0, z] } });
  const axisProject = { token: 'dof-axis', quality: { mode: 10, values: { posteffect: true } }, performers: [member(1, 0, 0), member(2, 3, -4)],
    tracks: [{ kind: 'camera', binding: camera, events: [shot(0, 10), { ...shot(2, 10), values: { ...shot(2, 10).values, position: [-3, 1.5, 10] } }] },
      { binding: camera, nativeClass: 'LiveDepthOfFieldTrack', events: [axis] }] };
  await axisScene.load(axisProject);
  const axisFocus = () => axisScene.assetDump({ sections: ['post'] }).post.dof.distance;
  axisScene.seek(1.8, axisProject, true);
  close(axisFocus(), 10 - 0.1, 'the first evaluation settles on member 1');
  axisScene.setPlaying(true);
  const steps = [[1.9, 10], [2.0, 10], [2.1, 10], [2.6, 12], [3.2, 14]];
  steps.forEach(([time, expected], index) => {
    axisScene.playbackFrame(time, index * 100, true);
    close(axisFocus(), expected - 0.1, `mode 2 at ${time}`);
  });
  axisScene.dispose();
  console.log('MV Studio DOF focus wiring: BodyPartType parts, fixed Face point, previous-frame transforms on continuing playback, mode-2 transition per frame.');
})().catch((error) => { console.error(error); process.exitCode = 1; });
