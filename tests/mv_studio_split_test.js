/* The native camera router and Three overlay keep the original mask geometry. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');

const window = {};
vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-split.js'), 'utf8'), { window });
const binding = '/EntryPoint/Live/Cameras/SplitScreenEffect';
const pointer = { m_FileID: 0, m_PathID: '-42' };
const mask = { positions: [1,-1,.01, -1,-1,.01, -1,1,.01, 1,1,.01],
  indices: [0,1,2,0,2,3], uv: [1,0,0,0,0,1,1,1], bounds: [2,2] };
const asset = { masks: { mask }, events: { first: [{ key: 'mask', pointer }, null, null, null] } };
const first = { id: 'first', start: 4, duration: 2, values: { playableClass: 'LiveSplitScreenClip',
  mainCamera: 0, subCamera1: 1, mask1: pointer } };
const tracks = [{ binding, nativeClass: 'LiveSplitScreenTrack', events: [first] },
  { binding: `${binding}/Cameras/SubCamera1`, nativeClass: 'AnimationTrack', events: [] }];
const project = { quality: { values: { split_screen: true } }, tracks, splitScreen: asset };

const defaultColor = new THREE.Color(0x111522), clearColor = defaultColor.clone();
let target = null, alpha = .5, overlays, draws = [];
const renderer = {
  domElement: { width: 640, height: 360 }, capabilities: { maxTextureSize: 4096 }, autoClear: true,
  getRenderTarget() { return target; }, setRenderTarget(value) { target = value; },
  getClearColor(output) { return output.copy(clearColor); }, getClearAlpha() { return alpha; },
  setClearColor(value, opacity) { clearColor.set(value); alpha = opacity; },
  clear() { assert.equal(target, null); draws.push('clear'); },
  clearDepth() { assert.equal(target, null); draws.push('depth'); },
  render(scene, camera) {
    assert.equal(camera.isOrthographicCamera, true);
    assert.equal(target, null);
    assert.equal(renderer.autoClear, false);
    overlays = scene.children.filter((mesh) => mesh.visible);
    draws.push('overlay');
  }
};
const compositor = window.MVStudioSplit.create(THREE, renderer);
const sample = (camera, _track, time) => { camera.position.set(time, 3, 4); return true; };
const view = (camera) => {
  assert.equal(camera.near, .1);
  assert.equal(camera.aspect, 1);
  assert(target && target.width === target.height);
  draws.push('sub');
};

compositor.setProject(project);
assert.equal(compositor.sample(3.99, sample), null);
assert.equal(compositor.draw(view, null), false);
assert.deepEqual(Array.from(compositor.sample(4, sample)[37]), [4,3,4]);
assert.equal(compositor.draw(view, null), true);
assert.deepEqual(draws, ['sub','clear','depth','overlay']);
assert.equal(target, null);
assert.equal(renderer.autoClear, true);
assert.equal(clearColor.getHex(), defaultColor.getHex());
assert.equal(alpha, .5);

const panel = overlays[0], geometry = panel.geometry;
assert.deepEqual(Array.from(geometry.index.array), [0,2,1,0,3,2]);
assert.equal(geometry.attributes.uv.getX(0), 1);
assert(geometry.attributes.position.getZ(0) < 0);
assert(Math.abs(panel.scale.x - .75) < 1e-12);
assert(Math.abs(panel.scale.y - 4/3) < 1e-12);
assert.equal(compositor.sample(6, sample), null);
assert.equal(compositor.draw(view, null), false);

project.quality.values.split_screen = false;
compositor.setProject(project);
assert.equal(compositor.sample(4, sample), null);
assert.equal(compositor.draw(view, null), false);
project.quality.values.split_screen = true;
first.values.mask1 = { ...pointer, m_PathID: '43' };
compositor.setProject(project);
assert.deepEqual(Array.from(compositor.sample(4, sample)[37]), [4,3,4]);
assert.equal(compositor.draw(view, null), false, 'a missing exact mask falls back without rendering an unmasked subview');
first.values.mask1 = pointer;
compositor.sample(4, sample);
assert.throws(() => compositor.draw(() => { throw Error('view failed'); }, null), /view failed/);
assert.equal(target, null);
assert.equal(renderer.autoClear, true);

let released = 0;
geometry.addEventListener('dispose', () => { released++; });
panel.material.addEventListener('dispose', () => { released++; });
compositor.setProject({ tracks: [] });
compositor.dispose();
assert.equal(released, 2);
console.log('MV Studio native split masks, routing, quality toggle, fallback and ownership passed');
