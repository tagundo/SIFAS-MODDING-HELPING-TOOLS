/* Original numerical fixtures execute IL2CPP + Unity + Android ARM64 libm.
 * No model assets, original binaries, or native arithmetic stubs are shipped.
 */
'use strict';
const assert = require('assert');
const fixture = require('./fixtures/native_unity_quaternion.json');
require('../webtools/web/static/viewer-game-physics-math.js');
const math = globalThis.ViewerGamePhysicsMath;
const methods = {Inverse: 'inverse', FromEulerRad: 'fromEulerRad', ToEulerRad: 'toEulerRad', EulerDegrees: 'euler', GetEulerAnglesDegrees: 'angles'};
const tolerances = {FromToRotation: 0, Inverse: 0, FromEulerRad: 0, ToEulerRad: 2.4e-7, EulerDegrees: 0, GetEulerAnglesDegrees: 8e-6};
const counts = {}, maximumErrors = {};
for (const row of fixture.cases) {
  const originalInput = JSON.stringify(row.input);
  const result = row.method === 'FromToRotation' ? math.fromToRotation(...row.input) : math[methods[row.method]](row.input);
  assert.equal(JSON.stringify(row.input), originalInput, `${row.method}/${row.name} does not mutate the authored pose`);
  assert.equal(result.length, row.nativeOutput.length);
  result.forEach((v, i) => {
    assert(Number.isFinite(v), `${row.method}/${row.name}[${i}] is finite`);
    const error = Math.abs(v - row.nativeOutput[i]);
    maximumErrors[row.method] = Math.max(maximumErrors[row.method] || 0, error);
    assert(error <= tolerances[row.method], `${row.method}/${row.name}[${i}]: JS ${v}, native ${row.nativeOutput[i]}, error ${error}`);
  });
  counts[row.method] = (counts[row.method] || 0) + 1;
}
['FromToRotation', 'Inverse', 'FromEulerRad', 'ToEulerRad'].forEach(method => assert(counts[method] >= 100, `${method} has at least 100 independently recorded native cases`));
assert(counts.EulerDegrees >= 12 && counts.GetEulerAnglesDegrees >= 17, 'Actual managed degree wrappers independently cover their conversion and MakePositive behavior');
// These source-specific behaviors distinguish the original implementation from
// common general-purpose quaternion helpers.
assert.deepStrictEqual(math.inverse([.1, .2, .3, .4]), [-Math.fround(.1), -Math.fround(.2), -Math.fround(.3), Math.fround(.4)], 'Nonunit Inverse is a conjugate; it does not divide by squared length');
assert.deepStrictEqual(math.fromToRotation([1, 0, 0], [-1, 0, 0]), [0, 1, -0, 0], 'Antiparallel X uses the original deterministic +Y axis');
assert.deepStrictEqual(math.fromToRotation([.000001, 0, 0], [0, 1, 0]), [0, 0, 0, 1], 'Tiny vectors follow the original identity fallback');
assert(math.fromToRotation([1, 0, 0], [0, 1, 0])[3] > Math.fround(Math.sqrt(.5)), 'The final original matrix-quaternion normalization is retained');
const tiny = math.angles(math.euler([-.001, -.01, 0]));
assert(tiny[0] < 0 && tiny[1] > 359, 'Original MakePositive deliberately retains tiny negative angles below its wrapping threshold');
assert(Object.isFrozen(math), 'The shared math API cannot be replaced accidentally');
console.log(`GAME_QUATERNION_NATIVE_PASS: ${fixture.cases.length} independent original numeric fixtures; max errors ${JSON.stringify(maximumErrors)}; Android26 reference libm, not live-client parity`);
