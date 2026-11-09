/* Original GL 3.12.0 SwingBone collision arithmetic, transcribed from ARM64.
 * Stateless float32 math; Transform/animation scheduling belongs to the caller.
 * Native fixture comparisons use declared synthetic Unity/runtime boundaries,
 * and do not establish bit-exact behavior of a running Unity client.
 *
 * Bone: {tip:[x,y,z], pivot:[x,y,z], length, radius, sibling:Bone|null}
 * Collider: {point:[x,y,z], radius, sibling:Collider|null}
 * Calls mutate existing tip arrays and return whether the native contact branch
 * ran. Radii are serialized world-unit values: no transform scale is applied.
 */
(function (global) {
  'use strict';
  var F = Math.fround;
  function vector(a) { return [F(a[0]), F(a[1]), F(a[2])]; }
  function add(a, b) { return [F(a[0] + b[0]), F(a[1] + b[1]), F(a[2] + b[2])]; }
  function subtract(a, b) { return [F(a[0] - b[0]), F(a[1] - b[1]), F(a[2] - b[2])]; }
  function multiply(a, scalar) { scalar = F(scalar); return [F(a[0] * scalar), F(a[1] * scalar), F(a[2] * scalar)]; }
  function dot(a, b) { return F(F(F(a[0] * b[0]) + F(a[1] * b[1])) + F(a[2] * b[2])); }
  function distance(a, b) { var d = subtract(a, b); return F(Math.sqrt(dot(d, d))); }
  function normalized(a) {
    var magnitude = F(Math.sqrt(dot(a, a)));
    return magnitude > F(1e-5) ? [F(a[0] / magnitude), F(a[1] / magnitude), F(a[2] / magnitude)] : [0, 0, 0];
  }
  function clamp01(t) { return F(Math.min(1, Math.max(0, F(t)))); }
  function radius(value, siblingValue, ratio) {
    value = F(value); ratio = F(ratio === undefined ? 0 : ratio);
    if (ratio <= 0 || siblingValue === null || siblingValue === undefined || value === F(siblingValue)) return value;
    return F(value + F(F(F(siblingValue) - value) * clamp01(ratio)));
  }
  function boneRadius(bone, ratio) { return radius(bone.radius, bone.sibling ? bone.sibling.radius : null, ratio); }
  function colliderRadius(collider, ratio) { return radius(collider.radius, collider.sibling ? collider.sibling.radius : null, ratio); }
  function projectLength(tip, bone) {
    var pivot = vector(bone.pivot);
    return add(pivot, multiply(normalized(subtract(tip, pivot)), bone.length));
  }
  function write(bone, tip) { bone.tip[0] = tip[0]; bone.tip[1] = tip[1]; bone.tip[2] = tip[2]; }
  function movePair(bone, displacement) {
    write(bone, projectLength(add(vector(bone.tip), displacement), bone));
    var sibling = bone.sibling;
    write(sibling, projectLength(add(vector(sibling.tip), displacement), sibling));
  }
  // RVA 0x2c984d4: first push the endpoint to the collider sphere, then
  // restore its own bone length. This is the original order, even when the
  // second projection leaves a residual overlap.
  function sphereSphere(bone, collider) {
    var tip = vector(bone.tip), center = vector(collider.point);
    var sum = F(F(bone.radius) + F(collider.radius));
    // ARM64 FCMP/B.HI also skips unordered NaN distances.
    if (!(distance(tip, center) <= sum)) return false;
    write(bone, projectLength(add(center, multiply(normalized(subtract(tip, center)), sum)), bone));
    return true;
  }
  // RVA 0x2c987a4: choose the orthogonal projection onto the capsule axis;
  // interpolate its authored endpoint radii at that ratio. The original
  // calculation does not minimize distance over varying-radius spheres.
  function sphereCapsule(bone, colliderA, colliderB) {
    var tip = vector(bone.tip), a = vector(colliderA.point), b = vector(colliderB.point);
    var ap = subtract(tip, a), ab = subtract(b, a);
    var t = clamp01(F(dot(normalized(ab), ap) / distance(a, b)));
    var closest = subtract(add(tip, multiply(ab, t)), ap);
    var sum = F(F(bone.radius) + colliderRadius(colliderA, t));
    if (!(distance(tip, closest) <= sum)) return false;
    write(bone, projectLength(add(closest, multiply(normalized(subtract(tip, closest)), sum)), bone));
    return true;
  }
  // RVA 0x2c98b80: a SwingBone capsule connects this endpoint to its
  // SwingBone sibling endpoint, rather than this bone's pivot.
  function capsuleSphere(bone, collider) {
    var tip = vector(bone.tip), siblingTip = vector(bone.sibling.tip), center = vector(collider.point);
    var ac = subtract(center, tip), ab = subtract(siblingTip, tip);
    var t = clamp01(F(dot(normalized(ab), ac) / distance(tip, siblingTip)));
    var closest = subtract(add(center, multiply(ab, t)), ac);
    var separation = distance(center, closest), sum = F(boneRadius(bone, t) + F(collider.radius));
    if (!(separation <= sum)) return false;
    movePair(bone, multiply(normalized(subtract(closest, center)), F(sum - separation)));
    return true;
  }
  // RVA 0x2c990fc: preserve the source's one-pass closest-axis calculation,
  // including its exchanged radius arguments and parallel-axis NaN behavior.
  function capsuleCapsule(bone, colliderA, colliderB) {
    var tip = vector(bone.tip), siblingTip = vector(bone.sibling.tip);
    var a = vector(colliderA.point), b = vector(colliderB.point);
    var u = subtract(siblingTip, tip), v = subtract(b, a), w = subtract(tip, a);
    var uv = dot(u, v), uu = dot(u, u), vv = dot(v, v), vw = dot(v, w), uw = dot(u, w);
    var t = clamp01(F(F(F(uv * vw) - F(vv * uw)) / F(F(uu * vv) - F(uv * uv))));
    var onBone = add(tip, multiply(u, t));
    var s = clamp01(F(dot(v, subtract(onBone, a)) / vv));
    var onCollider = add(a, multiply(v, s)), separation = distance(onCollider, onBone);
    var sum = F(boneRadius(bone, s) + colliderRadius(colliderA, t));
    if (!(separation <= sum)) return false;
    movePair(bone, multiply(normalized(subtract(onBone, onCollider)), F(sum - separation)));
    return true;
  }
  // Native job bodies share the axis geometry above but have distinct radius
  // guards, Group's squared-distance contact tests and a stored-pivot quirk.
  // Keep these profiles explicit rather than changing the verified Mono API.
  function forJob(profile) {
    if (!profile || (profile.kind !== 'single' && profile.kind !== 'group')) throw new Error('Choose an original single or group job collision profile.');
    var epsilon = F(profile.epsilon), squared = profile.kind === 'group';
    if (!(epsilon > 0) || !Number.isFinite(epsilon)) throw new Error('Provide the positive float32 Mathf.Epsilon runtime probe value.');
    function jobRadius(value, siblingValue, ratio) {
      value = F(value); siblingValue = F(siblingValue); ratio = F(ratio);
      if (value === siblingValue || epsilon >= ratio || epsilon > siblingValue) return value;
      return F(value + F(F(siblingValue - value) * clamp01(ratio)));
    }
    function dataRadius(collider, ratio) {
      var value = F(collider.radius), sibling = collider.sibling;
      var index = collider.siblingIndex === undefined ? (sibling ? 0 : -1) : collider.siblingIndex;
      var siblingValue = F(collider.siblingRadius === undefined ? (sibling ? sibling.radius : 0) : collider.siblingRadius);
      ratio = F(ratio);
      if (ratio === 0 || index < 0 || value === siblingValue) return value;
      return F(value + F(F(siblingValue - value) * clamp01(ratio)));
    }
    function ownRadius(bone, ratio) { return jobRadius(bone.radius, bone.sibling ? bone.sibling.radius : -1, ratio); }
    function measure(a, b) { var d = subtract(a, b); return squared ? dot(d, d) : F(Math.sqrt(dot(d, d))); }
    function contact(separation, sum) { return separation <= (squared ? F(sum * sum) : sum); }
    function depth(separation, sum) { return F(sum - (squared ? F(Math.sqrt(separation)) : separation)); }
    function moveJobPair(bone, displacement, capsuleSphereContact) {
      var pushed = add(vector(bone.tip), displacement), pivot = vector(bone.pivot);
      var destination = capsuleSphereContact && bone.storedPivot ? vector(bone.storedPivot) : pivot;
      write(bone, add(multiply(normalized(subtract(pushed, pivot)), bone.length), destination));
      var sibling = bone.sibling, stored = vector(sibling.storedPivot || sibling.pivot);
      pushed = add(vector(sibling.tip), displacement);
      write(sibling, add(multiply(normalized(subtract(pushed, stored)), sibling.length), stored));
    }
    function jobSphereSphere(bone, collider) {
      var tip = vector(bone.tip), center = vector(collider.point), sum = F(F(bone.radius) + F(collider.radius));
      if (!contact(measure(tip, center), sum)) return false;
      write(bone, projectLength(add(center, multiply(normalized(subtract(tip, center)), sum)), bone));
      return true;
    }
    function jobSphereCapsule(bone, colliderA, colliderB) {
      var tip = vector(bone.tip), a = vector(colliderA.point), b = vector(colliderB.point);
      var ap = subtract(tip, a), ab = subtract(b, a);
      var t = clamp01(F(dot(normalized(ab), ap) / F(Math.sqrt(dot(ab, ab)))));
      var closest = subtract(add(tip, multiply(ab, t)), ap), sum = F(F(bone.radius) + dataRadius(colliderA, t));
      if (!contact(measure(tip, closest), sum)) return false;
      write(bone, projectLength(add(closest, multiply(normalized(subtract(tip, closest)), sum)), bone));
      return true;
    }
    function jobCapsuleSphere(bone, collider) {
      var tip = vector(bone.tip), siblingTip = vector(bone.sibling.tip), center = vector(collider.point);
      var ac = subtract(center, tip), ab = subtract(siblingTip, tip);
      var t = clamp01(F(dot(normalized(ab), ac) / F(Math.sqrt(dot(ab, ab)))));
      var closest = subtract(add(center, multiply(ab, t)), ac);
      var separation = measure(center, closest), sum = F(ownRadius(bone, t) + F(collider.radius));
      if (!contact(separation, sum)) return false;
      moveJobPair(bone, multiply(normalized(subtract(closest, center)), depth(separation, sum)), true);
      return true;
    }
    function jobCapsuleCapsule(bone, colliderA, colliderB) {
      var tip = vector(bone.tip), siblingTip = vector(bone.sibling.tip);
      var a = vector(colliderA.point), b = vector(colliderB.point);
      var u = subtract(siblingTip, tip), v = subtract(b, a), w = subtract(tip, a);
      var uv = dot(u, v), uu = dot(u, u), vv = dot(v, v), vw = dot(v, w), uw = dot(u, w);
      var t = clamp01(F(F(F(uv * vw) - F(vv * uw)) / F(F(uu * vv) - F(uv * uv))));
      var onBone = add(tip, multiply(u, t)), s = clamp01(F(dot(v, subtract(onBone, a)) / vv));
      var onCollider = add(a, multiply(v, s));
      var separation = measure(onCollider, onBone), sum = F(ownRadius(bone, s) + dataRadius(colliderA, t));
      if (!contact(separation, sum)) return false;
      moveJobPair(bone, multiply(normalized(subtract(onBone, onCollider)), depth(separation, sum)), false);
      return true;
    }
    return { kind: profile.kind, epsilon: epsilon, radius: jobRadius, colliderRadius: dataRadius,
      sphereSphere: jobSphereSphere, sphereCapsule: jobSphereCapsule,
      capsuleSphere: jobCapsuleSphere, capsuleCapsule: jobCapsuleCapsule };
  }
  global.ViewerGamePhysicsCollision = {
    radius: radius, sphereSphere: sphereSphere, sphereCapsule: sphereCapsule,
    capsuleSphere: capsuleSphere, capsuleCapsule: capsuleCapsule, forJob: forJob,
    epsilonProfiles: { denormal: F(1.401298464324817e-45), flushToZero: F(1.1754943508222875e-38) }
  };
}(typeof window !== 'undefined' ? window : globalThis));
