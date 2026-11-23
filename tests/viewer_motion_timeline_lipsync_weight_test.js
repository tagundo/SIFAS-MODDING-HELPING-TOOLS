/* MemberFace.memberFaceData.lipSync.weight scales the vowel mouth inputs.
   LiveMemberLipSync.Initialize: WeightRate = weight for A, I, U, E, O, N (1..6)
   and 1 for other indices; ProcessFrameDefault: SetInputWeight(clip, w * rate).
   The 12035 CI runtime dump shows mouth_facial_001 = 90 for a full vowel A with
   ch0212's weight 0.9. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });
const timeline = window.ViewerMotionTimeline;

function player(memberHead) {
  const root = new THREE.Group();
  const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  face.name = 'face'; face.userData.elichika_node = 2; face.morphTargetInfluences = [0, 0, 0];
  face.morphTargetDictionary = { A: 0, Smile: 1, Eye: 2 }; root.add(face);
  const animations = [
    new THREE.AnimationClip('mouth-1', 1 / 60, [new THREE.NumberKeyframeTrack('face.morphTargetInfluences[0]', [0], [1])]),
    new THREE.AnimationClip('mouth-7', 1 / 60, [new THREE.NumberKeyframeTrack('face.morphTargetInfluences[1]', [0], [1])]),
    new THREE.AnimationClip('eye-1', 1 / 60, [new THREE.NumberKeyframeTrack('face.morphTargetInfluences[2]', [0], [1])]),
  ];
  const clips = [
    { name: 'mouth-1', sourceHash: 'a', sourceName: 'ch0212_LiveFacial_mouth_001' },
    { name: 'mouth-7', sourceHash: 'b', sourceName: 'ch0212_LiveFacial_mouth_007' },
    { name: 'eye-1', sourceHash: 'c', sourceName: 'ch0212_LiveFacial_eye_001' },
  ];
  const events = [
    { kind: 'mouth', index: 1, start: 0, duration: 2, weight: 1, timing: { easeOut: 1 } },
    { kind: 'mouth', index: 7, start: 3, duration: 1, weight: 1 },
    { kind: 'eyes', index: 1, start: 0, duration: 4, weight: 1 },
  ];
  const rig = { clips, ...(memberHead ? { memberHead } : {}) };
  const result = timeline.create(root, animations, rig, { version: 2, category: 'mv', bodySegments: [],
    facial: { duration: 4, events } }, { indexTiming: true });
  return { result, face };
}

const near = (actual, expected, message) => assert(Math.abs(actual - expected) < 1e-6, `${message}: ${actual} != ${expected}`);
const weighted = player({ faceDots: false, lipSyncWeight: 0.8999999761581421 });
weighted.result.evaluate(.5);
near(weighted.face.morphTargetInfluences[0], Math.fround(.9), 'vowel A at full input weight reaches 0.9');
near(weighted.face.morphTargetInfluences[2], 1, 'eye inputs keep rate 1');
weighted.result.evaluate(1.5);
near(weighted.face.morphTargetInfluences[0], Math.fround(Math.fround(.5) * Math.fround(.9)), 'the eased weight is scaled, not squared');
weighted.result.evaluate(3.5);
near(weighted.face.morphTargetInfluences[1], 1, 'index 7 (Smile) is not a lip-sync vowel');

const plain = player(null);
plain.result.evaluate(.5);
near(plain.face.morphTargetInfluences[0], 1, 'without a face weight the rate is 1');
console.log('PASS: per-face lip-sync weight scales vowel inputs 1..6 only');
