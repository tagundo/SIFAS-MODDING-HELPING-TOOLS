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
// Independent projection of a complete character: the original SDK torso crop
// cuts the hair, but the thumbnail must include every visible, posed vertex.
const profile = JSON.parse(fs.readFileSync(path.join(__dirname, '../webtools/web/static/thumbnail-sdk/profile.json'))).camera;
const unchangedProfile = JSON.stringify(profile), root = new THREE.Group();
function part(name, min, max) {
  const g = new THREE.BoxGeometry(max[0]-min[0], max[1]-min[1], max[2]-min[2]);
  g.translate((min[0]+max[0])/2,(min[1]+max[1])/2,(min[2]+max[2])/2);
  const mesh = new THREE.Mesh(g, new THREE.MeshBasicMaterial()); mesh.name=name;root.add(mesh);return mesh;
}
part('costume',[-.25,0,-.15],[.25,1.5,.15]); part('Face',[-.16,1.4,-.08],[.16,1.75,.2]);
part('Hair',[-.22,1.65,-.2],[.22,1.95,.1]); part('long costume bow',[-.8,.8,0],[-.2,1.1,.1]);
const hiddenPart=part('hidden alternative',[-10,-10,-10],[10,10,10]);hiddenPart.visible=false;
const sparse=new THREE.BufferGeometry();sparse.setAttribute('position',new THREE.Float32BufferAttribute([0,1,0,.1,1,0,0,1.1,0,100,100,100],3));sparse.setIndex([0,1,2]);root.add(new THREE.Mesh(sparse,new THREE.MeshBasicMaterial()));
const skinGeometry=new THREE.BufferGeometry();skinGeometry.setAttribute('position',new THREE.Float32BufferAttribute([0,2,0,.1,2,0,0,2.1,0],3));
skinGeometry.setAttribute('skinIndex',new THREE.Uint16BufferAttribute([0,0,0,0,0,0,0,0,0,0,0,0],4));
skinGeometry.setAttribute('skinWeight',new THREE.Float32BufferAttribute([1,0,0,0,1,0,0,0,1,0,0,0],4));
skinGeometry.morphAttributes.position=[new THREE.Float32BufferAttribute([0,1,0,0,1,0,0,1,0],3)];skinGeometry.morphTargetsRelative=true;
const posed=new THREE.SkinnedMesh(skinGeometry,new THREE.MeshBasicMaterial()),posedBone=new THREE.Bone();
posed.add(posedBone);posed.bind(new THREE.Skeleton([posedBone]));posedBone.scale.y=2;posed.updateMorphTargets();posed.morphTargetInfluences[0]=1;root.add(posed);
const camera = new THREE.OrthographicCamera(profile.left,profile.right,profile.top,profile.bottom,profile.near,profile.far);
camera.position.fromArray(profile.position);camera.up.fromArray(profile.up);
root.updateMatrixWorld(true);
const originalSource = JSON.stringify(root.toJSON()), framing=window.ViewerThumbnails.frameCharacter(root,camera,profile,true);
assert.equal(framing.mode,'full-character');assert.equal(framing.vertices,102,'visible indexed vertices only, without removed/hidden outliers');
assert.deepStrictEqual(JSON.stringify(profile),unchangedProfile);assert.equal(JSON.stringify(root.toJSON()),originalSource);
root.traverseVisible(mesh=>{if(!mesh.isMesh)return;const index=mesh.geometry.index,positions=mesh.geometry.attributes.position;
  for(let at=0;at<(index?index.count:positions.count);at++){const point=new THREE.Vector3().fromBufferAttribute(positions,index?index.getX(at):at).applyMatrix4(mesh.matrixWorld).project(camera);
    assert(Math.abs(point.x)<.9&&Math.abs(point.y)<.9&&Math.abs(point.z)<1,'complete face/hair/costume lies within padded camera');}});
assert(camera.top-camera.bottom>profile.top-profile.bottom,'complete character expands the original torso framing');
const knownPosedTop=new THREE.Vector3(0,6.2,0).project(camera);
assert(Math.abs(knownPosedTop.x)<.9&&Math.abs(knownPosedTop.y)<.9,'morph delta is applied before the actual saved bone scale');
assert(Math.abs(framing.maximum[1]-6.2*profile.up[1])<1e-5,'posed, not bind-pose geometry determines the top');
root.remove(posed);
const normalCamera = new THREE.OrthographicCamera(profile.left,profile.right,profile.top,profile.bottom,profile.near,profile.far);normalCamera.up.fromArray(profile.up);
const normalFull=window.ViewerThumbnails.frameCharacter(root,normalCamera,profile,true);
const upperCamera = new THREE.OrthographicCamera(profile.left,profile.right,profile.top,profile.bottom,profile.near,profile.far);upperCamera.up.fromArray(profile.up);
const upper=window.ViewerThumbnails.frameCharacter(root,upperCamera,profile);
assert.equal(upper.mode,'head-and-upper-body');assert.equal(upper.fitFullCharacter,false);assert.equal(normalFull.fitFullCharacter,true);
assert(upperCamera.top<normalCamera.top,'default face/upper-costume crop is larger than the opt-in whole figure');
const hairTop=new THREE.Vector3(0,1.95,0).project(upperCamera),feet=new THREE.Vector3(0,0,0).project(upperCamera);
assert(Math.abs(hairTop.y)<.9&&feet.y < -1,'default includes the head while intentionally cropping lower legs');
assert(upper.minimum[1]>upper.wholeMinimum[1]&&upper.maximum[1]===upper.wholeMaximum[1]);
assert.equal(window.ViewerRig,undefined,'framing stays isolated from the main viewer');
console.log(JSON.stringify({ status: 'PASS', checks: ['absolute-scale-position-quaternion', 'antipodal-equivalence', 'idempotent-exported-endpoints', 'conflict-and-unsupported-preserved', 'no-height-guess', 'no-live-viewer-mutation', 'full-character-face-hair-accessory-projection', 'hidden-and-unused-vertices-excluded', 'framing-preserves-source-and-sdk-profile', 'saved-skin-and-morph-framing', 'default-head-upper-crop-and-opt-in-full-character'] }));
