/* Scene lifecycle tests for the original-game engine, separate from its ARM64
 * numerical fixtures. Source Update is one step, without delta-time scaling. */
'use strict';
const assert = require('assert');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
global.window = {THREE};
require('../webtools/web/static/viewer-game-physics-math.js');
require('../webtools/web/static/viewer-game-physics-collision.js');
require('../webtools/web/static/viewer-game-physics.js');
const API = window.ViewerGamePhysics;
function setup(skirt = false) {
  const root = new THREE.Group(), parent = new THREE.Bone(), bone = new THREE.Bone(), child = new THREE.Bone();
  const left = new THREE.Bone(), right = new THREE.Bone();
  [parent,bone,child,left,right].forEach((o,i)=>{o.userData.elichika_node=i;});
  root.add(parent,left,right);parent.add(bone);bone.add(child);child.position.set(-1,0,skirt ? -.1 : 0);
  const record = {id:'b',node:1,name:skirt?'SkirtA1_Dyna':'Tail1_Dyna',kind:'bone',sourceIndex:0,
    values:{stiffnessForce:.02,dragForce:.6,lowRotationLimit:[-180,-180,-180],highRotationLimit:[180,180,180]},
    simulation:{childNode:2,parentIndex:-1,siblingIndex:-1,childIndex:-1,radius:.02,boneAxis:[1,0,0],externalForce:[0,.03,0],colliderIds:[],colliderBits:0,
      skirtSafeEnable:true,skirtLimitDotMin:-1,skirtLimitDotMax:1,skirtRotDegMax:0,kneeSpaceOffsetFront:.1,kneeSpaceOffsetOther:.1,kneeSpaceOffsetForce:.2}};
  const catalog={native:{available:true,missing:[]},components:[record],managers:[{id:'m',sourceIndex:0,node:0,bones:['b'],lodBones:[],colliders:[],kneeTransforms:[3,4]}]};
  const pose=()=>{const out={};root.traverse(o=>{if(o.userData.elichika_node!==undefined)out[o.userData.elichika_node]={position:o.position.toArray(),quaternion:o.quaternion.toArray(),scale:o.scale.toArray()};});return out;};
  root.updateMatrixWorld(true);const rest=pose(), engine=API.create(root,catalog,r=>r.values,{getInitializationPose:()=>rest});
  const navi={bones:true,colliders:true,profile:'navi',enableLod:true};
  const live={...navi,profile:'live',skirtsafeDisableBySource:{0:false},safeSwingBone:false};
  function capture() {root.updateMatrixWorld(true);engine.captureAnimationPose({clipId:'fixture',time:0});}
  return {root,parent,bone,child,left,right,record,catalog,rest,engine,navi,live,capture};
}
{
  const s=setup();s.capture();s.engine.apply(0,s.navi);
  assert(s.engine.getState().initialized);assert.equal(s.engine.getState().totalNativeSteps,0);
  s.engine.apply(.1,s.navi);const first=s.engine.getState();
  assert.equal(first.nativeSteps,1);assert.equal(first.totalNativeSteps,1);
  assert(first.bones[0].tip[1]>0,'original external force moves the tip');
  const rotation=s.bone.quaternion.toArray(),history=JSON.stringify(first.bones);
  s.bone.quaternion.identity();s.capture();s.engine.apply(0,s.navi);
  assert.deepStrictEqual(s.bone.quaternion.toArray(),rotation,'paused rendering reapplies cached physical pose');
  assert.equal(JSON.stringify(s.engine.getState().bones),history,'zero delta preserves tip history');
  assert.equal(s.engine.getState().totalNativeSteps,1);
  s.capture();s.engine.apply(1/120,s.navi);assert.equal(s.engine.getState().totalNativeSteps,2,'accepted positive delta is exactly one game Update');
  s.engine.resetSimulation('seek');s.capture();s.engine.apply(0,s.navi);
  assert.equal(s.engine.getState().initializationGeneration,1,'seek retains original base caches');
  assert.equal(s.engine.getState().dynamicGeneration,2,'seek resets only dynamic history');
}
{
  const s=setup(true);s.record.simulation.externalForce=[0,0,0];s.capture();s.engine.apply(0,s.live);
  assert.equal(s.engine.getState().safeCorrections,0,'zero delta does not run startup LateUpdate');
  s.engine.apply(1/30,s.live);assert.equal(s.engine.getState().safeCorrections,1,'original MV load performs forced correction even when global mode is false');
  assert(s.child.getWorldPosition(new THREE.Vector3()).z>0,'native forced correction moved the explicit child in world coordinates');
  const position=s.child.position.toArray();s.child.position.fromArray(s.rest[2].position);s.capture();s.engine.apply(0,s.live);
  assert.deepStrictEqual(s.child.position.toArray(),position,'child correction remains after SafeCorrectAdjust is cleared by packed-tip sync');
  s.engine.resetSimulation('seek');s.capture();s.engine.apply(1/30,s.live);
  assert.equal(s.engine.getState().safeCorrections,0,'editor seeks do not invent another game-load correction');
}
{
  const s=setup();s.capture();s.engine.apply(0,{...s.live,skirtsafeDisableBySource:{}});
  assert(s.engine.getState().unsupported.includes('source-skirt-runtime:0'));
  s.engine.apply(0,{...s.live,safeSwingBone:undefined});
  assert(s.engine.getState().unsupported.includes('motion-skirt-runtime'),'unknown global MV setting requires source data or explicit override');
  s.catalog.managers[0].kneeTransforms=[];s.engine.resetSimulation('source-change');s.engine.apply(0,s.live);
  assert(s.engine.getState().unsupported.includes('source-knee-transforms:0'),'original AllSafeCorrect dereferences both knees; a missing graph is not silently simulated');
}
{
  // A derived costume can contain exact caller flags from more than one
  // original source. A complete component map must behave identically to the
  // source-wide flag when they are equal, without fabricating a suit identity.
  for(const flag of [false,true]) {
    const original=setup(true),derived=setup(true);
    original.capture();derived.capture();
    const a={...original.live,skirtsafeDisableBySource:{0:flag},safeSwingBone:true};
    const b={...derived.live,skirtsafeDisableBySource:{},skirtsafeDisableByComponent:{b:flag},safeSwingBone:true};
    for(const delta of [0,1/30,1/30]) { original.engine.apply(delta,a);derived.engine.apply(delta,b); }
    assert.deepStrictEqual(derived.engine.getState().unsupported,[]);
    assert.deepStrictEqual(derived.engine.getState().bones,original.engine.getState().bones);
    assert.deepStrictEqual(derived.bone.quaternion.toArray(),original.bone.quaternion.toArray());
    assert.deepStrictEqual(derived.child.position.toArray(),original.child.position.toArray());
  }
  const unknown=setup();unknown.capture();unknown.engine.apply(1/30,
    {...unknown.live,skirtsafeDisableBySource:{},skirtsafeDisableByComponent:{another:false}});
  assert(unknown.engine.getState().unsupported.includes('source-skirt-runtime:0'));
  assert.equal(unknown.engine.getState().totalNativeSteps,0,'an unrelated derived component cannot authorize a manager');
}
{
  const s=setup(true),other=new THREE.Bone(),tip=new THREE.Bone();
  other.userData.elichika_node=5;tip.userData.elichika_node=6;other.position.x=.3;tip.position.set(-1,0,-.1);
  s.parent.add(other);other.add(tip);s.record.simulation.externalForce=[0,0,0];
  const record={...s.record,id:'mixed',node:5,name:'SkirtE1_Dyna',simulation:{...s.record.simulation,childNode:6}};
  s.catalog.components.push(record);s.catalog.managers[0].bones.push(record.id);s.root.updateMatrixWorld(true);
  const rest={};s.root.traverse(o=>{if(o.userData.elichika_node!==undefined)rest[o.userData.elichika_node]={position:o.position.toArray(),quaternion:o.quaternion.toArray(),scale:o.scale.toArray()}});
  s.engine.dispose();const engine=API.create(s.root,s.catalog,r=>r.values,{getInitializationPose:()=>rest});
  const live={...s.live,skirtsafeDisableBySource:{},skirtsafeDisableByComponent:{b:false,mixed:true},safeSwingBone:true};
  engine.captureAnimationPose({});engine.apply(1/30,live);
  assert.equal(engine.getState().safeCorrections,2,'the original forced load correction still affects both source chains');
  s.root.traverse(o=>{const p=rest[o.userData.elichika_node];if(p){o.position.fromArray(p.position);o.quaternion.fromArray(p.quaternion);o.scale.fromArray(p.scale)}});
  s.root.updateMatrixWorld(true);engine.resetSimulation('seek');engine.captureAnimationPose({});engine.apply(1/30,live);
  assert.equal(engine.getState().safeCorrections,1,'a mixed manager retains each component original costume caller flag');
  assert.deepStrictEqual(engine.getState().unsupported,[]);
}
{
  const s=setup();s.capture();s.engine.apply(1/30,s.live);
  const before=s.engine.getState().totalNativeSteps, generation=s.engine.getState().dynamicGeneration;
  s.engine.captureAnimationPose({});s.engine.apply(1/30,{...s.live,safeSwingBone:undefined});
  assert.equal(s.engine.getState().totalNativeSteps,before,'losing trusted MV global flags blocks further native updates');
  assert(s.engine.getState().unsupported.includes('motion-skirt-runtime'));
  s.engine.apply(1/30,s.live);
  assert.equal(s.engine.getState().totalNativeSteps,before+1);
  assert.equal(s.engine.getState().dynamicGeneration,generation,'known global mode can resume without rebasing native history');
  assert(!s.engine.getState().unsupported.includes('motion-skirt-runtime'));
}
{
  const s=setup();s.parent.matrixAutoUpdate=false;
  s.parent.matrix.set(1,.3,0,.2,0,1,0,.4,0,0,1,.1,0,0,0,1);
  s.root.updateMatrixWorld(true);const matrix=s.parent.matrix.toArray();s.capture();s.engine.apply(0,s.navi);
  assert.deepStrictEqual(s.parent.matrix.toArray(),matrix,'temporary source-rest sampling preserves exact current affine matrix');
  assert.equal(s.parent.matrixAutoUpdate,false);
}
{
  // Negative scale changes the geometry matrix, not Unity Transform.rotation.
  const a=setup(),b=setup();b.parent.scale.set(1,-2,3);
  a.capture();b.capture();a.engine.apply(1/30,a.navi);b.engine.apply(1/30,b.navi);
  const qa=a.bone.quaternion.toArray(),qb=b.bone.quaternion.toArray();
  qa.forEach((value,i)=>assert(Math.abs(value-qb[i])<2e-6,'world-rotation sampling must not decompose reflection into rotation'));
}
{
  const s=setup(true);s.record.simulation.externalForce=[0,0,0];s.capture();s.engine.apply(1/30,s.live);
  const animated=[-.8,.1,-.25];s.child.position.fromArray(animated);s.root.updateMatrixWorld(true);
  s.engine.captureAnimationPose({animatedProperties:{2:{position:true}}});s.engine.apply(1/30,s.live);
  assert.deepStrictEqual(s.child.position.toArray(),animated,'current animation-owned child position is not replaced by prior physical output');
}
console.log('GAME_PHYSICS_ADAPTER_PASS: pause/history, one-step clock, rest/seek lifecycle, MV forced child sync, strict flags, affine preservation, scale-independent rotation');
