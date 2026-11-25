/* Exact Unity streamed curves end to end: model_animation.py writes a streamed
 * rotation + translation clip as glTF CUBICSPLINE, the vendored r128
 * GLTFLoader reads it, and the MV timeline, a plain AnimationMixer and the
 * gaze poses must reproduce libunity's per-component cubic
 * t*(t*(t*c0 + c1) + c2) + c3 (normalized for rotations) at off-key times. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm');
const { spawnSync } = require('child_process');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const ROOT = path.join(__dirname, '..');
const context = { THREE, TextDecoder, console, self: globalThis, navigator: { userAgent: 'node' } };
vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'webtools/web/static/vendor/three-r128/GLTFLoader.js'), 'utf8'), context);
const window = { THREE };
vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'webtools/web/static/viewer-motion-timeline.js'), 'utf8'), { window });

const script = `
import base64, json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/tests")
import test_model_animation as T
from webtools.core import model_animation as animation
rotation = {0: [(0, .10, 0, .3), (.3, .19, .2, -.1), (.7, .12, .4, .4), (1, .3, 0, 0)],
            1: [(0, -.2, 0, .5), (.45, .05, .1, .1), (1, .1, 0, 0)],
            2: [(0, .05, 0, 0), (.2, .02, -.3, -.3), (.55, -.1, 0, .6), (.8, .04, .2, .2), (1, 0, 0, 0)],
            3: [(0, .97, 0, -.1), (1, .94, .05, 0)]}
position = {4: [(0, 0, 0, 1), (.25, .3, 1.5, 1.5), (1, .9, 0, 0)], 5: [(0, 1.2, 0, 0), (.6, 1.0, -.8, -.8), (1, 1.1, 0, 0)],
            6: [(0, -.4, 0, 0), (1, .4, 0, 0)]}
eye = {0: [(0, 0, 0, 0), (1, .2, 0, 0)], 1: [(0, 0, 0, 0), (1, .1, 0, 0)], 2: [(0, 0, 0, 0), (1, 0, 0, 0)], 3: [(0, 1, 0, 0), (1, 1.3, 0, 0)]}
body = T.AnimationTests.hermite_frames({**rotation, **position})
gaze = T.AnimationTests.hermite_frames(eye)
trees = [T.clip([T.binding(1, 2), T.binding(1, 1)], stream={"curveCount": 7, "data": T.words(body)}, duration=1., name="Original dance"),
         T.clip([T.binding(2, 2)], stream={"curveCount": 4, "data": T.words(gaze)}, duration=1., name="ch0201_LiveFacial_eye_006")]
glb = T.builder(3)
glb.doc["nodes"] = [{"name": "Root", "children": [1, 2]}, {"name": "Hips"}, {"name": "LeftEye1"}]
glb.doc["scenes"][0]["nodes"] = [0]
result = animation.append_animations(T.scene(trees), glb, {1: 1, 2: 2})
assert result["warnings"] == [], result["warnings"]
frames = lambda rows: [[stamp if stamp > -1e38 else -3.4e38, [[index, list(c)] for index, c in keys]] for stamp, keys in rows if stamp != float("inf")]
print(json.dumps({"glb": base64.b64encode(glb.finish()).decode(), "body": frames(body), "gaze": frames(gaze),
                  "interpolation": [s["interpolation"] for a in glb.doc["animations"] for s in a["samplers"]]}))
`;
const run = spawnSync(process.env.VIEWER_PYTHON || 'python3', ['-c', script, ROOT], { encoding: 'utf8', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
assert.strictEqual(run.status, 0, run.stderr);
const fixture = JSON.parse(run.stdout);
assert.deepStrictEqual(fixture.interpolation, ['CUBICSPLINE', 'CUBICSPLINE', 'CUBICSPLINE']);

// libunity GL 3.12.0: the seek (0x591304) keeps each curve's last key at or before the time and
// SampleClip (0x591078) evaluates t*(t*(t*c0 + c1) + c2) + c3 with float32 fmul/fadd.
function unity(frames, curve, time) {
  let owner = null;
  for (const [stamp, keys] of frames) if (stamp <= time) for (const [index, c] of keys) if (index === curve) owner = [stamp, c];
  const [stamp, c] = owner, f = Math.fround, t = stamp < -1e20 ? 0 : f(f(time) - f(stamp));
  return f(f(t * f(f(t * f(f(t * c[0]) + c[1])) + c[2])) + c[3]);
}
function unityRotation(frames, time, first = 0) {
  const raw = [0, 1, 2, 3].map((i) => unity(frames, first + i, time)), q = new THREE.Quaternion(raw[0], -raw[1], -raw[2], raw[3]);
  return { raw, q: q.normalize() };
}
function angle(a, b) { return 2 * Math.acos(Math.min(1, Math.abs(a.dot(b)))) * 180 / Math.PI; }
const failures = [];
function check(name, fn) {
  return Promise.resolve().then(fn).then(() => console.log('PASS: ' + name),
    (error) => { failures.push(name); console.error('FAIL: ' + name + ': ' + (error.stack || error)); });
}
function load() {
  const bytes = Buffer.from(fixture.glb, 'base64');
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  return new Promise((resolve, reject) => new context.THREE.GLTFLoader().parse(buffer, '', resolve, reject));
}
const times = Array.from({ length: 97 }, (_, index) => (index + .37) / 97);

(async () => {
  await check('the loader marks CUBICSPLINE tracks and the timeline sizes their samples as one value', async () => {
    const gltf = await load(), track = gltf.animations[0].tracks[0];
    assert.strictEqual(track.ValueTypeName, 'quaternion');
    assert(track.createInterpolant.isInterpolantFactoryMethodGLTFCubicSpline);
    assert.strictEqual(track.getValueSize(), 12);
    assert.strictEqual(window.ViewerMotionTimeline.trackValueSize(track), 4);
    assert.strictEqual(window.ViewerMotionTimeline.trackValueSize(new THREE.VectorKeyframeTrack('a.position', [0], [1, 2, 3])), 3);
  });
  await check('MV timeline poses the dance at off-key times as the client evaluates it', async () => {
    const gltf = await load(), hips = gltf.scene.getObjectByName('Hips');
    const metadata = { clips: [{ name: 'Original dance', sourceHash: 'dance', sourceName: 'Original dance', bindingComplete: true }] };
    const descriptor = { version: 2, category: 'mv', bodySegments: [{ sourceHash: 'dance', sourceName: 'Original dance', start: 0, duration: 1, clipIn: 0, timeScale: 1 }],
      facial: { duration: 1, events: [] }, facialClips: [] };
    const player = window.ViewerMotionTimeline.create(gltf.scene, gltf.animations, metadata, descriptor, { indexTiming: true });
    assert.strictEqual(player.compatibleSegments, 1, 'the cubic body tracks bind (their base is one sample wide)');
    let worst = 0, position = 0;
    for (const time of times) {
      player.evaluate(time);
      worst = Math.max(worst, angle(hips.quaternion, unityRotation(fixture.body, time).q));
      const expected = [-unity(fixture.body, 4, time), unity(fixture.body, 5, time), unity(fixture.body, 6, time)];
      position = Math.max(position, ...expected.map((value, axis) => Math.abs(value - hips.position.getComponent(axis))));
      assert(Math.abs(hips.quaternion.length() - 1) < 1e-6);
    }
    assert(worst < 2e-4, `rotation ${worst} deg`);
    assert(position < 2e-6, `position ${position}`);
  });
  await check('AnimationMixer and a replayed interpolant read normalized rotations, the raw cubic is not unit length', async () => {
    const gltf = await load(), hips = gltf.scene.getObjectByName('Hips');
    window.ViewerMotionTimeline.prepareAnimations(gltf.animations);
    window.ViewerMotionTimeline.prepareAnimations(gltf.animations); // idempotent
    const mixer = new THREE.AnimationMixer(gltf.scene);
    mixer.clipAction(gltf.animations[0]).play();
    const interpolant = gltf.animations[0].tracks[0].createInterpolant();
    let rawOff = 0;
    for (const time of times) {
      mixer.setTime(time);
      const expected = unityRotation(fixture.body, time);
      rawOff = Math.max(rawOff, Math.abs(Math.hypot(...expected.raw) - 1));
      assert(Math.abs(hips.quaternion.length() - 1) < 1e-6, `mixer |q| ${hips.quaternion.length()} at ${time}`);
      assert(angle(hips.quaternion, expected.q) < 2e-4);
      const value = interpolant.evaluate(time);
      assert(Math.abs(Math.hypot(value[0], value[1], value[2], value[3]) - 1) < 1e-6);
    }
    assert(rawOff > 1e-3, 'the fixture exercises a non-unit raw cubic');
    // The clamped end key (afterEnd_) is normalized too.
    const end = interpolant.evaluate(5);
    assert(Math.abs(Math.hypot(end[0], end[1], end[2], end[3]) - 1) < 1e-6);
  });
  await check('gaze poses blend the normalized end key of a cubic eye clip', async () => {
    const gltf = await load(), eye = gltf.scene.getObjectByName('LeftEye1');
    eye.isBone = true;
    const metadata = { clips: [{ name: 'ch0201_LiveFacial_eye_006', sourceName: 'ch0201_LiveFacial_eye_006', sourceHash: 'eye6', bindingComplete: true }] };
    const gaze = window.ViewerGaze.create(gltf.scene, gltf.animations, metadata);
    assert.deepStrictEqual(Array.from(gaze.getState().directions), [6]);
    eye.quaternion.set(0, 0, 0, 1);
    gaze.apply({ 6: .5 });
    const pose = unityRotation(fixture.gaze, 1).q;
    assert(Math.abs(Math.hypot(...unityRotation(fixture.gaze, 1).raw) - 1) > .1, 'the end key is not unit length');
    const expected = new THREE.Quaternion().slerp(pose, .5);
    assert(angle(eye.quaternion, expected) < 1e-4, `gaze ${angle(eye.quaternion, expected)} deg`);
  });
  if (failures.length) { console.error(failures.length + ' failed'); process.exit(1); }
  console.log('all cubic timeline checks passed');
})();
