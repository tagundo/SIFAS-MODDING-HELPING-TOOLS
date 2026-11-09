/* Motion choices depend on exact import receipts and displayed targets. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-rig.js'), 'utf8'), { window });
function setup() {
  const root = new THREE.Group(), hips = new THREE.Bone(), faceRoot = new THREE.Bone(), eye = new THREE.Bone();
  hips.name = 'Hips'; faceRoot.name = 'Head_Face'; eye.name = 'LeftEye1';
  root.add(hips); hips.add(faceRoot); faceRoot.add(eye);
  const skin = new THREE.SkinnedMesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  skin.name = 'body'; skin.userData.elichika_node = 6; root.add(skin); skin.bind(new THREE.Skeleton([hips, faceRoot, eye]));
  const face = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial()); face.name = 'face';
  face.userData.elichika_node = 7; face.morphTargetInfluences = [0]; face.morphTargetDictionary = { A: 0 }; faceRoot.add(face);
  const camera = new THREE.Object3D(), helper = new THREE.Object3D(); camera.name = 'OriginalCamera'; helper.name = 'helper'; helper.userData.viewerHelper = true;
  root.add(camera, helper);
  const clip = (name, node = hips, property = 'position') => new THREE.AnimationClip(name, 1, [new THREE.VectorKeyframeTrack(node.name + '.' + property, [0, 1], [0, 0, 0, 1, 0, 0])]);
  return { root, hips, eye, face, camera, helper, clip };
}
function describe(s, clips, info = {}) { return window.ViewerRig.describeMotionClips(s.root, clips, info); }
function visible(s, clips, info) { return Array.from(describe(s, clips, info).filter(value => value.visible), value => value.name); }
let s = setup();
const bodyA = s.clip('Body A'), bodyB = s.clip('Body B');
const camera = s.clip('Original camera clip', s.camera), helper = s.clip('Helper clip', s.helper), eye = s.clip('Eye pose', s.eye);
const mouth = new THREE.AnimationClip('Mouth pose', 1, [new THREE.NumberKeyframeTrack('face.morphTargetInfluences[0]', [0, 1], [0, 1])]);
const all = [bodyA, bodyB, camera, helper, eye, mouth];
assert.deepStrictEqual(visible(s, all, { expressionCatalog: { rawChannels: [{ node: 7, group: 'mouth' }] } }), ['Body A', 'Body B'], 'A raw multi-clip bundle offers both compatible character motions, with no camera/helper/facial bank choices');
assert.equal(all.length, 6, 'Filtering never removes auxiliary tracks needed for composition');
assert.deepStrictEqual(visible(s, [s.clip('Camera named but genuine body motion')]), ['Camera named but genuine body motion'], 'Names do not substitute for actual target binding');
assert.deepStrictEqual(visible(s, [bodyA, bodyB], { clips: [{ name: bodyA.name, userSelected: false }, { name: bodyB.name, userSelected: true }] }), ['Body B'], 'Unrequested automatically discovered body clips stay internal while explicit user choices remain');
assert.deepStrictEqual(visible(s, [bodyA, bodyB], { clips: [{ name: bodyA.name, sourceRole: 'camera' }, { name: bodyB.name, sourceRole: 'body' }] }), ['Body B'], 'An original Timeline camera binding stays hidden even when its path-zero curves can bind a character root');
const metadata = { clips: [{ name: bodyA.name, sourceHash: 'selected', sourceName: 'same-name' }, { name: bodyB.name, sourceHash: 'user-custom', sourceName: 'same-name' }],
  motionTimelines: [{ bodySegments: [{ sourceHash: 'selected', sourceName: 'same-name' }], facialClips: [], clipSources: [] }] };
assert.deepStrictEqual(visible(s, [bodyA, bodyB], metadata), ['Body B'], 'Only exact timeline-owned source identities are hidden; a previous custom clip with the same source name remains');
assert.equal(describe(s, [bodyA], metadata)[0].reason, 'timeline-source');
metadata.clips[1].sourceHash = 'selected'; metadata.motionTimelines = [];
assert.deepStrictEqual(visible(s, [bodyA, bodyB], metadata), ['Body A'], 'Identical imported source content is not duplicated in the picker');
metadata.clips[1].sourceHash = 'different';
assert.deepStrictEqual(visible(s, [bodyA, bodyB], metadata), ['Body A', 'Body B'], 'Distinct compatible clips are never collapsed by name alone');
assert.deepStrictEqual(visible(s, [s.clip('Missing binding', { name: 'missing' })]), [], 'Unbound tracks never masquerade as compatible model motions');
assert.deepStrictEqual(visible(s, [], { clips: [{ name: 'Eyelid visibility', visibility: [{ node: 7 }] }, { name: 'Body visibility', visibility: [{ node: 6 }] }],
  expressionCatalog: { rawChannels: [{ node: 7, group: 'eyes' }] } }), ['Body visibility'], 'Visibility-only facial helpers remain internal while actual body visibility motion remains available');
console.log('PASS: exact game source filtering, manual body alternatives, facial/camera/helper exclusion, source deduplication');
