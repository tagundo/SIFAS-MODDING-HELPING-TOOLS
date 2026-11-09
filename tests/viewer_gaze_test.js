/* Source-derived GL3.12 gaze targets, original iris poses and playhead ownership. */
'use strict';
const assert = require('assert'), fs = require('fs'), vm = require('vm'), path = require('path');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = {THREE};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), {window});
const close = (a, b, message) => assert(Math.abs(a - b) < 1e-6, `${message}: ${a} != ${b}`);
function setup() {
  const root = new THREE.Group(), face = new THREE.Bone(), left = new THREE.Bone(), right = new THREE.Bone(), lid = new THREE.Bone();
  face.name = 'Head_Face'; left.name = 'LeftEye1'; right.name = 'RightEye1'; lid.name = 'LeftEye_Lid';
  [face, left, right, lid].forEach((node, id) => node.userData.elichika_node = id);
  root.add(face); face.add(left, right, lid);
  const animations = [], clips = [], aliases = [];
  for (const [id, xyz] of [[6, [-1, 0, 0]], [7, [1, 0, 0]], [8, [0, 1, 0]], [9, [0, -1, 0]], [10, [-1, 1, 0]], [11, [1, 1, 0]]]) {
    const clip = new THREE.AnimationClip('pose' + id, 1, [new THREE.VectorKeyframeTrack('LeftEye1.position', [0, 1], [0, 0, 0, ...xyz]),
      new THREE.VectorKeyframeTrack('RightEye1.position', [0, 1], [0, 0, 0, ...xyz]), new THREE.VectorKeyframeTrack('LeftEye_Lid.position', [0, 1], [0, 0, 0, 0, 8, 0])]);
    animations.push(clip); clips.push({name: clip.name, sourceName: 'ch0201_LiveFacial_eye_' + String(id).padStart(3, '0'), sourceHash: 'source' + id, bindingComplete: true});
    aliases.push({kind: 'eyes', index: id, sourceName: clips.at(-1).sourceName, sourceHash: clips.at(-1).sourceHash});
  }
  const metadata = {clips, expressionCatalog: {gaze: {clips: aliases}}};
  const gaze = window.ViewerGaze.create(root, animations, metadata);
  return {root, face, left, right, lid, animations, clips, aliases, metadata, gaze};
}
let s = setup();
assert.deepStrictEqual(Array.from(s.gaze.getState().directions), [6, 7, 8, 9, 10, 11]);
for (const [target, pose] of [[31, 8], [32, 9], [33, 7], [34, 6], [35, 11], [36, 10]]) {
  s.left.position.set(0, 0, 0); s.right.position.set(0, 0, 0); s.lid.position.set(0, 0, 0);
  s.gaze.evaluate([{target, weight: .5}], {});
  const source = s.animations.find(clip => clip.name === 'pose' + pose).tracks[0].values;
  [s.left.position.x, s.left.position.y, s.left.position.z].forEach((v, i) => close(v, source[i + 3] * .5, 'fixed enum selects original direction pose'));
  close(s.lid.position.length(), 0, 'gaze never changes eyelid');
}
s = setup();
let values = s.gaze.targetWeights(21, {camera: [-1, 0, 1]}); close(values[6], 1, 'Unity right is mirrored into Three negativeX');
values = s.gaze.targetWeights(21, {camera: [1, 0, 1]}); close(values[7], 1, 'Unity left');
values = s.gaze.targetWeights(21, {camera: [0, Math.tan(Math.PI / 12), 1]}); close(values[8], .5, '15degrees is half original30degree vertical limit');
values = s.gaze.targetWeights(21, {camera: [-1, Math.sqrt(2) * Math.tan(Math.PI / 6), 1]});
close(values[6], .5, 'diagonal camera horizontal L1 normalized'); close(values[8], .5, 'diagonal camera vertical L1 normalized');
s.face.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2); s.root.updateMatrixWorld(true);
values = s.gaze.targetWeights(21, {camera: [1, 0, 0]}); close(Object.values(values).reduce((a, b) => a + b, 0), 0, 'gaze reference follows the animated face rotation');
s.face.quaternion.identity(); s.root.scale.set(2, .5, 3); s.root.updateMatrixWorld(true);
values = s.gaze.targetWeights(21, {camera: [-1, 0, 1]}); close(values[6], 1, 'direction follows native rotation independent of worldscale');
assert.equal(s.gaze.targetWeights(22, {}), null, 'missing original audience target is not fabricated');
assert(s.gaze.getState().missingTargets.includes(22));
values = s.gaze.targetWeights(22, {audience: [0, 1, 1]}); close(values[8], 1, 'explicit audience position is honored');
values = s.gaze.targetWeights(2, {members: {2: [1, 0, 1]}}); close(values[7], 1, 'explicit other-member position is honored');
values = s.gaze.targetWeights(37, {cameras: {37: [-1, 0, 1]}}); close(values[6], 1, 'original split-screen camera targets remain distinct');
s = setup();
const faceRoot = new THREE.Bone(); faceRoot.name = 'Face_Root';
const angle = Math.PI / 2; s.face.quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),angle);
faceRoot.quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),-angle);s.face.add(faceRoot);s.root.updateMatrixWorld(true);
const anatomical = window.ViewerGaze.create(s.root,s.animations,s.metadata);
values = anatomical.targetWeights(21,{camera:[1,0,1]});close(values[7],1,'Face_Root cancels real SIFAS Head_Face90degree bone axis');
assert(!values[8] && !values[9], 'a horizontal camera never becomes vertical gaze due to bone-axis rotation');
const eyeRoot = new THREE.Bone(); eyeRoot.name = 'Eye_Root'; eyeRoot.position.y = 1; faceRoot.add(eyeRoot);
const eyeOrigin = window.ViewerGaze.create(s.root,s.animations,s.metadata);
values = eyeOrigin.targetWeights(21,{camera:[0,1,1]});close(Object.values(values).reduce((a,b)=>a+b,0),0,'native Eye_Root position wins over lower Face_Root/Head_Face origins');
s = setup();
const hips = new THREE.Bone(); hips.name = 'Hips'; s.root.add(hips);
const body = new THREE.AnimationClip('body', 2, [new THREE.VectorKeyframeTrack('Hips.position', [0, 2], [0, 0, 0, 0, 0, 0])]);
s.animations.push(body); s.metadata.clips.push({name: 'body', sourceHash: 'body', sourceName: 'body'});
const descriptor = {version: 2, category: 'voice', bodySegments: [{sourceHash: 'body', sourceName: 'body', start: 0, duration: 2}],
  facialClips: s.aliases, facial: {events: [{kind: 'gaze', target: 21, start: .5, duration: .5, weight: .5}]}};
let camera = [-1, 0, 1];
const timeline = window.ViewerMotionTimeline.create(s.root, s.animations, s.metadata, descriptor, {getGazeContext: () => ({camera})});
timeline.evaluate(.75); close(s.left.position.x, -.5, 'authored Camera21 gaze drives original iris pose');
assert(timeline.animatedProperties(.75)['1'].position, 'active gaze is declared as an animated physics input');
camera = [1, 0, 1]; s.left.position.set(0, 0, 0); timeline.evaluate(.75); close(s.left.position.x, .5, 'preview camera changes the actual gaze at same paused playhead');
s.left.position.set(0, 0, 0); timeline.evaluate(1.5); close(s.left.position.length(), 0, 'expired original gaze interval retains no stale offset');
assert(!timeline.animatedProperties(1.5)['1'], 'inactive gaze does not claim the source node');
assert.equal(timeline.getGazeState().missingTargets.length, 0);
assert.equal(timeline.followsGazeTarget(), true);
s = setup();
const old = s.animations[0].clone(); old.name = 'other-character-right'; old.tracks[0].values[3] = -20;
s.animations.push(old); s.metadata.clips.push({name: old.name, sourceHash: 'other', sourceName:'ch0001_LiveFacial_eye_006'});
s.metadata.expressionCatalog.gaze.owner = 201; s.metadata.expressionCatalog.gaze.available = true;
const otherBody = new THREE.Bone(); otherBody.name = 'Hips'; s.root.add(otherBody);
const ownBody = new THREE.AnimationClip('body', 1, [new THREE.VectorKeyframeTrack('Hips.position',[0,1],[0,0,0,0,0,0])]);
s.animations.push(ownBody); s.metadata.clips.push({name:'body',sourceHash:'body',sourceName:'body'});
const rebound = window.ViewerMotionTimeline.create(s.root,s.animations,s.metadata,{version:2,targetCharacter:1,category:'voice',
 bodySegments:[{sourceHash:'body',sourceName:'body',start:0,duration:1}],
 facialClips:[{kind:'eyes',index:6,sourceHash:'other',sourceName:'ch0001_LiveFacial_eye_006'}],
 facial:{events:[{kind:'gaze',target:34,start:0,duration:1,weight:1}]}});
rebound.evaluate(.5);close(s.left.position.x,-1,'cross-character library uses this face201 original endpoints, not old absolute iris positions');
assert.equal(rebound.getGazeState().sourceOwner,201);assert.equal(rebound.getGazeState().retargeted,true);
console.log('PASS: original gaze enums45/30-degree axes, source iris poses, moving camera/face, authored weights, target availability and active property ownership');
