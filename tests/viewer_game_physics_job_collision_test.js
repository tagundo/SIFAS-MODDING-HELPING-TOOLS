/* Isolated branch profiles checked against actual whole-job ARM64 outputs. */
'use strict';
const assert = require('assert');
const fixture = require('./fixtures/game_physics_native_job_collisions.json');
require('../webtools/web/static/viewer-game-physics-collision.js');
const C = globalThis.ViewerGamePhysicsCollision, F = Math.fround;
const V = a => a.map(F), add = (a,b) => a.map((v,i)=>F(v+b[i])), sub = (a,b) => a.map((v,i)=>F(v-b[i]));
function normalize(v) { const n=F(Math.sqrt(F(F(F(v[0]*v[0])+F(v[1]*v[1]))+F(v[2]*v[2]))));return n>F(1e-5)?v.map(x=>F(x/n)):[0,0,0]; }
function f32bits(bits) { const b=Buffer.alloc(4);b.writeUInt32LE(parseInt(bits,16));return b.readFloatLE(); }
let maximumError=0, comparisons=0;
const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
for(const recorded of fixture.cases) {
  const row=JSON.parse(JSON.stringify(recorded)), api=C.forJob({kind:row.profile,epsilon:f32bits(row.mathfEpsilonBits)});
  row.colliderTransforms.forEach(m=>assert.deepStrictEqual(m,identity,'These pure collision fixtures exclude transform-matrix approximations'));
  const bones=row.boneData.map((d,i)=>{
    assert.equal(d.stiffnessForce,0);assert.equal(d.dragForce,1);assert.deepStrictEqual(d.externalForce,[0,0,0]);
    assert.deepStrictEqual(row.before[i].previousTipPosition,row.before[i].currentTipPosition);
    // Native after.Position records its freshly computed root; before.Position
    // records the source buffer root before this job. Neither is a tip result.
    return {tip:V(row.before[i].currentTipPosition),pivot:V(row.after[i].position),storedPivot:V(row.before[i].position),length:F(d.boneLength),radius:F(d.radius)};
  });
  bones.forEach((b,i)=>{const index=row.boneData[i].siblingIndex;b.sibling=index>=0?bones[index]:null;});
  const colliders=row.colliderData.map(d=>({point:V(d.offset),radius:F(d.radius),siblingIndex:d.siblingIndex,siblingRadius:F(d.siblingRadius)}));
  colliders.forEach((c,i)=>{const index=row.colliderData[i].siblingIndex;c.sibling=index>=0?colliders[index]:null;});
  bones.forEach((bone,i)=>{
    // The zero-force job still restores length before testing colliders.
    bone.tip.splice(0,3,...add(bone.pivot,normalize(sub(bone.tip,bone.pivot)).map(v=>F(v*bone.length))));
    const data=row.boneData[i];let tested=0;
    colliders.forEach((collider,j)=>{
      if(tested>=data.colliderCount||!(data.colliderIndexBit&(1<<j)))return;tested++;
      const method=(bone.sibling?'capsule':'sphere')+(collider.sibling?'Capsule':'Sphere');
      api[method](bone,collider,collider.sibling);
    });
    bone.storedPivot=bone.pivot.slice();
  });
  bones.forEach((bone,i)=>bone.tip.forEach((value,axis)=>{
    const expected=row.after[i].currentTipPosition[axis],error=Math.abs(value-expected);maximumError=Math.max(maximumError,error);comparisons++;
    assert(Number.isFinite(value));assert(error<=fixture.comparisonToleranceAbsolute,`${row.name}/${row.profile}/bone${i}/axis${axis}: JS ${value}, original ${expected}, error ${error}`);
  }));
}
for(const kind of ['single','group']) {
  const denormal=C.forJob({kind,epsilon:C.epsilonProfiles.denormal}),flush=C.forJob({kind,epsilon:C.epsilonProfiles.flushToZero});
  assert.equal(denormal.radius(.2,0,.5),F(.2),'A zero sibling radius is excluded by the original positive epsilon guard');
  assert.equal(flush.radius(.2,1e-40,.5),F(.2),'Flush-to-zero probe excludes a subnormal sibling radius');
  assert.notEqual(denormal.radius(.2,1e-40,.5),F(.2),'Denormal-preserving probe includes that source sibling radius');
}
assert.throws(()=>C.forJob({kind:'group',epsilon:0}),/positive/,'Unknown/zero runtime epsilon must not silently stand in for the original probe');
console.log(`GAME_JOB_COLLISION_NATIVE_PASS: ${fixture.cases.length} profiled whole-job cases, ${comparisons} endpoint components, max absolute error ${maximumError}, tolerance ${fixture.comparisonToleranceAbsolute}`);
