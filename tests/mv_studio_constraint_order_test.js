/* MV Studio scene order of Unity constraints against the swing bones, with the real
   solvers. Unity frame (GL 3.12): LiveCoreMemberManager.Update -> UpdateMultiThread
   (0x2f6a7b8) gathers the bones and their parents with ApplyTransform (0x2f6afb0) and
   schedules the swing job; the director animates; ConstraintManagerUpdate
   (PreLateUpdate) reads the swing bones as the job left them and writes the
   *_Root_Dyna targets; LateUpdate (0x2f6a9a4) only runs AllSafeCorrect. The targets keep
   that value until the next frame's job reads them as the parents of their chains. */
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

// hips(0) -> SkirtA1_Dyna(1, swing bone, constraint source) -> tip(2)
// hips(0) -> LeftSkirtB_Root_Dyna(3, RotationConstraint 0.5 <- 1) -> SkirtB1_Dyna(4, swing) -> tip(5)
// At-rest and offset are zero, so the bind pose is the constraint's fixed point,
// as Unity's Activate stores them on the shipped 12007/12025 skirts.
const rigs = [];
THREE.GLTFLoader = class {
  parse(_bytes, _base, onLoad) {
    const root = new THREE.Group();
    const nodes = Array.from({ length: 6 }, (_, id) => {
      const node = new THREE.Bone(); node.userData.elichika_node = id; return node;
    });
    const [hips, skirtA, tipA, skirtBRoot, skirtB, tipB] = nodes;
    hips.name = 'Hips'; skirtA.name = 'SkirtA1_Dyna'; skirtBRoot.name = 'LeftSkirtB_Root_Dyna'; skirtB.name = 'SkirtB1_Dyna';
    root.add(hips); hips.add(skirtA, skirtBRoot); skirtA.add(tipA); skirtBRoot.add(skirtB); skirtB.add(tipB);
    hips.position.y = 1; skirtA.position.z = .1; skirtBRoot.position.x = -.1;
    tipA.position.x = tipB.position.x = -.3;
    rigs.push({ root, hips, skirtA, skirtBRoot, skirtB });
    onLoad({ scene: root, animations: [] });
  }
};

const hipsAngle = (time) => 50 * Math.sin(time * 9);
const window = {
  THREE, requestAnimationFrame() { return 1; }, cancelAnimationFrame() {},
  ResizeObserver: class { observe() {} disconnect() {} },
  ViewerMotionTimeline: { create(root) {
    const hips = root.getObjectByName('Hips');
    return { evaluatePose(time) { hips.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), hipsAngle(time) * Math.PI / 180); },
      evaluateGaze() {}, eyePosition() {}, applyVisibility() {}, animatedProperties() { return { 0: { quaternion: true } }; } };
  } },
};
const context = vm.createContext({ window, fetch: async () => ({ ok: true, async arrayBuffer() { return new ArrayBuffer(1); } }),
  AbortController, Uint8Array, Uint16Array });
for (const file of ['viewer-game-physics-math.js', 'viewer-game-physics-collision.js', 'viewer-game-physics.js', 'mv-studio-physics.js',
  'viewer-constraints.js', 'mv-studio-split.js', 'mv-studio-asset-dump.js', 'mv-studio-scene.js']) {
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/' + file), 'utf8'), context);
}

// The scene's own hook calls; the target's local rotation as each update hook sees it.
const seenByJob = [];
{
  const create = window.MVStudioPhysics.create;
  window.MVStudioPhysics.create = (root, ...rest) => {
    const model = create(root, ...rest);
    const target = root.getObjectByName('LeftSkirtB_Root_Dyna');
    const frame = model.frame;
    model.frame = (phase, time, delta, ...more) => {
      if (phase === 'update' && delta > 0) seenByJob.push(target.quaternion.toArray());
      return frame(phase, time, delta, ...more);
    };
    return model;
  };
}

const bone = (id, node, childNode) => ({ id, kind: 'bone', node, name: 'Hair_Dyna',
  values: { stiffnessForce: .02, dragForce: .4, lowRotationLimit: [-180, -180, -180], highRotationLimit: [180, 180, 180] },
  simulation: { childNode, parentIndex: -1, childIndex: -1, siblingIndex: -1, boneAxis: [1, 0, 0], externalForce: [0, -.01, 0],
    radius: .02, colliderIds: [], colliderBits: 0 } });
const physics = { available: true, components: [bone('a', 1, 2), bone('b', 4, 5)],
  native: { available: true, runtime: { sources: [{ sourceIndex: 0, known: true, skirtsafeDisable: true }] } },
  managers: [{ id: 'm', sourceIndex: 0, bones: ['a', 'b'], lodBones: [], colliders: [], kneeTransforms: [] }] };
const constraints = { available: true, constraints: [{ id: 'skirt-b', kind: 'rotation', node: 3, name: 'LeftSkirtB_Root_Dyna',
  enabled: true, activeInHierarchy: true, constraintActive: true, weight: .5, atRest: [0, 0, 0], offset: [0, 0, 0],
  axes: [true, true, true], sources: [{ node: 1, weight: 1 }] }] };

const degrees = (q) => 2 * Math.acos(Math.min(1, Math.abs(q[3]))) * 180 / Math.PI;
const half = (q) => new THREE.Quaternion().slerp(new THREE.Quaternion().fromArray(q), .5).toArray();
const close = (a, b, message, tolerance = 1e-6) =>
  assert(a.every((value, index) => Math.abs(value - b[index]) <= tolerance), `${message}: ${a} vs ${b}`);

(async () => {
  const scene = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} }, {
    visible: true, onError(message) { throw new Error(message); } });
  const project = { token: 'constraint-order', quality: { mode: 30, values: { frame_rate_60fps: false, member_swing_bone_mv: true } },
    motionPhysics: { safeSwingBoneKnown: true, safeSwingBone: false },
    performers: [{ id: 'solo', position: 1, glb: '/api/mv-studio/media/' + '1'.padStart(32, '0') + '.glb', motion: {},
      rig: { physics, constraints }, transform: { position: [0, 0, 0] } }],
    tracks: [{ kind: 'camera', binding: '/MainCamera', events: [{ start: 0, duration: 10,
      values: { position: [0, 0, 10], rotation: [0, 0, 0, 1], fov: 45 } }] }] };
  await scene.load(project);
  const rig = rigs.at(-1);
  scene.seek(1, project, true);
  scene.setPlaying(true);
  const frames = (count, from, hz = 30) => {
    for (let index = 0; index < count; index++) scene.playbackFrame(1 + (from + index) / hz, (from + index) * 1000 / hz, true);
  };

  // Default (game) order. The skirt swing bone's local rotation is the job output of
  // this frame (no AllSafeCorrect on this chain), and the constraint reads exactly it.
  assert.equal(scene.setPhysicsTiming({ order: 'game' }).order, 'game');
  const outputs = [];
  for (let index = 0; index < 12; index++) {
    frames(1, index);
    const swing = rig.skirtA.quaternion.toArray(), target = rig.skirtBRoot.quaternion.toArray();
    outputs.push(target);
    close(target, half(swing), `game frame ${index + 1}: target = nlerp(rest, this frame's swing job output, 0.5)`);
  }
  const swung = rig.skirtA.quaternion.toArray(), driven = rig.skirtBRoot.quaternion.toArray();
  assert(degrees(swung) > 5, `the source swings (${degrees(swung)} degrees)`);
  assert(degrees(driven) > 2.5, `the constraint is not a no-op in the default order (${degrees(driven)} degrees)`);
  // ApplyTransform reads each chain's parent before the director: the job under the
  // constrained root saw the previous frame's constraint output, not the rest pose.
  assert.equal(seenByJob.length, 12);
  for (let index = 1; index < 12; index++) close(seenByJob[index], outputs[index - 1], `job ${index + 1} reads frame ${index}'s target`);
  const state = scene.inspect().constraints;
  assert.equal(JSON.stringify(state.map((row) => [row.constraints, row.evaluated, row.unsupported.length])), '[[1,1,0]]');

  // A 60 Hz display of the 30 fps game: the in-between frame has no job, so the source
  // keeps the last job output and the target follows only the newly animated parents.
  frames(1, 11.5);
  close(rig.skirtBRoot.quaternion.toArray(), half(rig.skirtA.quaternion.toArray()), 'in-between frame');

  // The earlier same-frame order runs the job after the timeline, so the solve there
  // reads the previous frame's applied result.
  scene.setPhysicsTiming({ order: 'same-frame' });
  frames(1, 20);
  for (let index = 21; index < 26; index++) {
    const previous = rig.skirtA.quaternion.toArray();
    frames(1, index);
    close(rig.skirtBRoot.quaternion.toArray(), half(previous), `same-frame ${index}: target follows the previous result`);
  }
  assert(degrees(rig.skirtBRoot.quaternion.toArray()) > 1, 'same-frame order still drives the target');

  // A seek discards the simulated pose: the paused target frame shows the bind pose.
  scene.setPlaying(false);
  scene.seek(2, project, true);
  close(rig.skirtBRoot.quaternion.toArray(), [0, 0, 0, 1], 'seek returns the target to its rest', 1e-12);
  scene.dispose();
  console.log('MV Studio constraints: game-order swing job output drives the skirt roots, which the next job reads passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
