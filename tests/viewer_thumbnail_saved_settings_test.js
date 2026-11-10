/* Pure independent thumbnail shape: the main viewer's verified absolute endpoints. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const window = { THREE };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../webtools/web/static/viewer-thumbnails.js'), 'utf8'), { window });
const apply = window.ViewerThumbnails.applySavedSettings;
function model() { const root = new THREE.Group(), bone = new THREE.Bone(); bone.name = 'BreastSize'; bone.userData.elichika_node = 3; root.add(bone); return { root, bone }; }
function entry(kind, value, overrides) { return Object.assign({ node: 3, name: 'BreastSize', supported: true, kind,
  application: kind === 'rotation' ? 'absolute_local_quaternion' : 'absolute_local_' + kind,
  [kind === 'rotation' ? 'scaledQuaternion' : 'scaled']: value }, overrides); }
function info(entries) { return { available: true, scaling: { heightScale: 1.234, warnings: [], components: [{ heightScale: 1.234, entries }] } }; }
function equal(a, b) { assert.deepStrictEqual(JSON.parse(JSON.stringify(a)), JSON.parse(JSON.stringify(b))); }
let s = model(); const quaternion = new THREE.Quaternion().setFromEuler(new THREE.Euler(.1, .2, .3, 'ZXY')).toArray();
const metadata = info([entry('scale', [1.04, 1.02, 1.04]), entry('position', [.0074, -.0074, .0011662079]), entry('rotation', quaternion), entry('rotation', quaternion.map(v => -v))]);
const original = JSON.stringify(metadata), first = apply(s.root, metadata);
equal(s.bone.scale.toArray(), [1.04, 1.02, 1.04]); equal(s.bone.position.toArray(), [.0074, -.0074, .0011662079]); equal(s.bone.quaternion.toArray(), quaternion);
assert.equal(first.operations.length, 3); assert.equal(first.conflicts, 0); assert.equal(first.skipped, 0); assert.equal(JSON.stringify(metadata), original);
const once = { position: s.bone.position.toArray(), quaternion: s.bone.quaternion.toArray(), scale: s.bone.scale.toArray() };
apply(s.root, metadata); equal({ position: s.bone.position.toArray(), quaternion: s.bone.quaternion.toArray(), scale: s.bone.scale.toArray() }, once);
// Exported values are already absolute. Never multiply scale a second time.
s.bone.scale.set(1.04, 1.02, 1.04); apply(s.root, metadata); equal(s.bone.scale.toArray(), [1.04, 1.02, 1.04]);
s = model(); s.bone.scale.set(9, 8, 7); const rejected = apply(s.root, info([entry('scale', [2, 2, 2]), entry('scale', [3, 2, 2]), entry('position', [1, 2, 3], { supported: false }),
  entry('rotation', [0, 0, 0, 2]), entry('scale', [0, 1, 1], { node: 7 }), entry('position', [1, 2, 3], { node: 99 })]));
assert.equal(rejected.operations.length, 0); assert.equal(rejected.conflicts, 1); assert(rejected.skipped >= 4); equal(s.bone.scale.toArray(), [9, 8, 7]); equal(s.bone.position.toArray(), [0, 0, 0]);
const inactive = info([entry('scale', [2, 2, 2])]); inactive.available = false; assert.equal(apply(s.root, inactive).operations.length, 0);
assert.equal(apply(s.root, info([])).operations.length, 0); equal(s.bone.scale.toArray(), [9, 8, 7]);
assert.equal(window.ViewerRig, undefined, 'No live viewer, DOM, animation or physics controller is mounted');
console.log(JSON.stringify({ status: 'PASS', checks: ['absolute-scale-position-quaternion', 'antipodal-equivalence', 'idempotent-exported-endpoints', 'conflict-and-unsupported-preserved', 'no-height-guess', 'no-live-viewer-mutation'] }));
