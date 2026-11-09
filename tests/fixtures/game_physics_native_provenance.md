These fixtures contain synthetic inputs and independently captured outputs from
the original ARM64 physics functions. They contain no game binaries or assets.
Each JSON header records the exact input image SHA-256 values and entrypoints.

`game_physics_native_jobs.json` covers 130 single/group job cases over 252 frames:
in-place hierarchy updates, changing captured poses, history, all four collision
topologies, masks/counts, aggregate member offsets, tapered/zero/subnormal radii,
rotated/scaled matrices, Euler limits and seeded general 3D cases. Both original
job implementations executed with the original IL2CPP and Unity libraries, plus
an unchanged ARM64 Android 26 SDK libm reference. No solver, Quaternion or host
trigonometric callback generated the expected results.

`game_physics_native_safe_correct.json` covers 19 cases over 20 calls, including
left/right/front/center selection, force/partial corrections, unchanged flags,
zero-ratio contact and rotated/scaled parents. Original matrix inversion,
rotation, multiplication, point transforms and Quaternion calculations executed.
Transform values were declared synthetic scene inputs; setters captured outputs.

`game_physics_native_initialize.json` records original initialization and immutable
rest-cache observations. Its scope and runtime boundaries are in its own header.

The numeric VM maps ELF load segments, applies relocations, resolves original
Quaternion/matrix internal calls and links actual ARM64 libm code. Only metadata
and initialized class storage, synthetic Android TLS/stack-canary storage and
explicit Transform/name inputs are supplied as boundaries. Unknown calls stop
execution. This is isolated native-function evidence, not a running Unity scene
or a claim about every device's OS libm or floating-point control state.

The normal JavaScript implementation matched 10,615 of 10,896 job components
exactly in the captured comparison; the largest absolute difference was
0.0000011920928955078125. SafeCorrect matched 151 of 160 components exactly with
maximum difference 0.00000014901161193847656. The regression tolerance is 0.00002
because JavaScript transcendental rounding can differ from Android libm.
Observed native `atan2f` entries/returns identified those scalar differences.
A separate research-only exact-input replay of original Android libm return
values made all 10,896 job components identical; that diagnostic is not the
production math implementation or the native oracle.

Run from the repository root:

```sh
node modtools/tests/viewer_game_physics_native_test.js
node modtools/tests/viewer_game_physics_initialization_test.js
```

Original research scripts and full traces were generated under
`/workspace/scratch/physics-game-faithful/bone/{job,lifecycle}` during development.
Regressions require only the compact JSON fixtures, Node and the bundled Three.js;
they do not require the private source binaries or a native emulator.
