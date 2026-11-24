/* LiveMemberEyeContact gaze layer details (GL 3.12.0):
   - the six direction clips play whole in the head graph's gaze mixer
     (LiveCoreMemberHead.InitializeDefault 0x2f67e18: lip-sync, eye and gaze
     mixers into one AnimationLayerMixerPlayable, each at weight 1), so the
     blend shape they bind besides the iris bones (eye_facial_003_006_011)
     follows the same direction weights; indices a clip does not bind stay
     with the eye layer;
   - LateUpdate (0x29985b0) sets the gaze inputs after the head graph has
     evaluated (SetTimeUpdateMode(GameTime) 0x2f65fb0, Play 0x2f660dc), so a
     continuing frame shows the previous frame's weights; a seek uses its own;
   - TimelineClip.get_mixInCurve / get_mixOutCurve (0x35ce834 / 0x35ce970)
     use EaseInOut when the serialized curve has fewer than two keys. */
'use strict';
const assert = require('assert'), fs = require('fs'), vm = require('vm'), path = require('path');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });
const close = (a, b, message) => assert(Math.abs(a - b) < 1e-6, `${message}: ${a} != ${b}`);

const POSES = { 6: [-1, 0, 0], 7: [1, 0, 0], 8: [0, 1, 0], 9: [0, -1, 0], 10: [-1, 1, 0], 11: [1, 1, 0] };
// Eye_Around targets: 0 eye_facial_002, 1 eye_facial_003_006_011, 2 eye_facial_004.
function setup({ bound = true } = {}) {
  const root = new THREE.Group(), eyeRoot = new THREE.Bone(), left = new THREE.Bone();
  eyeRoot.name = 'Eye_Root'; left.name = 'LeftEye1';
  eyeRoot.userData.elichika_node = 0; left.userData.elichika_node = 1;
  const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  face.name = 'Eye_Around'; face.userData.elichika_node = 2; face.morphTargetInfluences = [0, 0, 0];
  root.add(eyeRoot, face); eyeRoot.add(left);
  const animations = [], clips = [], aliases = [];
  const add = (index, pose, morphs, indices) => {
    const clip = new THREE.AnimationClip('eye-' + index, 1 / 60, [
      new THREE.VectorKeyframeTrack('LeftEye1.position', [0, 1 / 60], [...pose, ...pose]),
      // A glTF weights channel repeats every target of the mesh.
      new THREE.NumberKeyframeTrack('Eye_Around.morphTargetInfluences', [0, 1 / 60], [...morphs, ...morphs])]);
    animations.push(clip);
    const entry = { name: clip.name, sourceName: 'ch0212_LiveFacial_eye_' + String(index).padStart(3, '0'),
      sourceHash: 'source' + index, sourceRole: 'facial', bindingComplete: true };
    if (bound) entry.morphTargets = [{ node: 2, indices }];
    clips.push(entry);
    aliases.push({ kind: 'eyes', index, sourceName: entry.sourceName, sourceHash: entry.sourceHash });
  };
  add(2, [0, 0, 0], [1, 0, 0], [0]);
  for (const index of [6, 7, 8, 9, 10, 11]) add(index, POSES[index], [0, 1, 0], [1]);
  return { root, face, left, animations, metadata: { clips }, aliases };
}
function timeline(s, events, options = {}) {
  return window.ViewerMotionTimeline.create(s.root, s.animations, s.metadata,
    { version: 2, category: 'mv', bodySegments: [], facialClips: s.aliases, facial: { duration: 20, events } }, options);
}
const eye2 = { kind: 'eyes', index: 2, start: 0, duration: 20, weight: 1 };

// The gaze clip's own blend shape follows the direction weights; other targets keep the eye layer.
// indexTiming is the MV Studio configuration, which restores the face before each sample.
let s, player;
for (const indexTiming of [false, true]) {
  s = setup();
  player = timeline(s, [eye2, { kind: 'gaze', target: 31, start: 2, duration: 2, weight: .3 }], { indexTiming });
  player.evaluate(1);
  assert.deepStrictEqual(Array.from(s.face.morphTargetInfluences), [1, 0, 0], 'no gaze: only the eye clip');
  player.evaluate(3);
  close(s.face.morphTargetInfluences[1], .3, 'Down (target 31, direction 8) at .3 drives eye_facial_003_006_011');
  close(s.face.morphTargetInfluences[0], 1, 'a target the gaze clips do not bind keeps the eye layer');
  close(s.face.morphTargetInfluences[2], 0, 'an unbound target is not written as the clip rest');
  close(s.left.position.y, .3, 'iris bones follow the same weight');
  player.evaluate(5);
  assert.deepStrictEqual(Array.from(s.face.morphTargetInfluences), [1, 0, 0], 'expired gaze leaves no stale shape');
  close(s.left.position.length(), 0, 'nor a stale iris offset');
}
// Gaze alone (no eye clip binds the shape) restores the rest weight once it ends.
s = setup();
player = timeline(s, [{ kind: 'gaze', target: 31, start: 2, duration: 2, weight: .3 }], { indexTiming: true });
player.evaluate(3); close(s.face.morphTargetInfluences[1], .3, 'gaze alone drives the shape');
player.evaluate(5); close(s.face.morphTargetInfluences[1], 0, 'and the MV restore returns it to rest');

// Exports without the bound-index list keep the earlier iris-only gaze.
s = setup({ bound: false });
player = timeline(s, [eye2, { kind: 'gaze', target: 31, start: 2, duration: 2, weight: .3 }]);
player.evaluate(3);
assert.deepStrictEqual(Array.from(s.face.morphTargetInfluences), [1, 0, 0], 'no morphTargets metadata: morphs untouched');
close(s.left.position.y, .3, 'iris bones still move');

// The expression panel's manual gaze stays iris-only.
s = setup();
const manual = window.ViewerGaze.create(s.root, s.animations, s.metadata, { aliases: s.aliases });
manual.apply({ 8: 1 }, true);
assert.deepStrictEqual(Array.from(s.face.morphTargetInfluences), [0, 0, 0], 'manual gaze writes no blend shape');
assert(manual.operations().every((operation) => ['position', 'quaternion', 'scale'].includes(operation.kind)));

// One-frame lag: a continuing frame applies the weights the previous frame computed.
s = setup();
player = timeline(s, [eye2, { kind: 'gaze', target: 21, start: 0, duration: 20, weight: 1 }]);
const right = { camera: [-1, 0, 1] }, left = { camera: [1, 0, 1] };
player.evaluatePose(6); player.evaluateGaze(6, right, { continuing: false });
close(s.left.position.x, -1, 'a seek applies the weights of its own pose (direction 6)');
close(s.face.morphTargetInfluences[1], 1, 'with its blend shape');
player.evaluatePose(6.1); player.evaluateGaze(6.1, left, { continuing: true });
close(s.left.position.x, -1, 'the next frame still shows the weights the previous LateUpdate set');
player.evaluatePose(6.2); player.evaluateGaze(6.2, left, { continuing: true });
close(s.left.position.x, 1, 'one frame later the new direction (7) arrives');
player.evaluatePose(6.3); player.evaluateGaze(6.3, right, { continuing: false });
close(s.left.position.x, -1, 'a seek never shows a stale lagged weight');
player.evaluatePose(6.4); player.evaluateGaze(6.4, right);
close(s.left.position.x, -1, 'without frame information the gaze is evaluated in the same frame');
const ended = timeline(setup(), [eye2, { kind: 'gaze', target: 21, start: 0, duration: 1, weight: 1 }]);
ended.evaluatePose(.9); ended.evaluateGaze(.9, right, { continuing: false });
ended.evaluatePose(1.1); ended.evaluateGaze(1.1, right, { continuing: true });
assert.equal(ended.getGazeState().weights[6], 1, 'the frame after a gaze clip ends still shows its last weights');
ended.evaluatePose(1.2); ended.evaluateGaze(1.2, right, { continuing: true });
assert.equal(Object.keys(ended.getGazeState().weights).length, 0, 'and the frame after that none');

console.log('PASS: gaze clip blend shape, one-frame gaze lag');
