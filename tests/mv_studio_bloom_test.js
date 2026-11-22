'use strict';
const assert = require('node:assert/strict');
const T = require('../webtools/web/static/vendor/three-r128/three.min.js');

global.window = {};
require('../webtools/web/static/viewer-motion-timeline.js');
require('../webtools/web/static/mv-studio-lighting.js');
require('../webtools/web/static/mv-studio-post.js');

const post = window.MVStudioPost;
const first = { start: 0, duration: 2, values: { playableClass: 'LiveBloomClip', intensity: .25,
  threshold: 1, softKnee: .3, radius: 4, antiFlicker: 0, blendOut: 1 } };
const second = { start: 1, duration: 2, values: { ...first.values, intensity: .75, threshold: .5, radius: 6,
  antiFlicker: 1, blendIn: 1, blendOut: -1 } };
const track = { nativeClass: 'LiveBloomTrack', binding: '/EntryPoint/Live/Cameras/MainCamera', events: [first, second] };
const project = { quality: { values: { posteffect: true } }, tracks: [track] };

const handoff = post.sample(project, 1.5);
assert.equal(handoff.intensity, .5);
assert.equal(handoff.threshold, .75);
assert.equal(handoff.radius, 5);
assert.equal(handoff.antiFlicker, false, 'ties retain the first native input flag');
assert.equal(post.sample(project, 1.75).antiFlicker, true);
assert.equal(post.sample(project, 3), null);
track.muted = true;
assert.equal(post.sample(project, 1.5), null);
track.muted = false;
project.quality.values.posteffect = false;
assert.equal(post.sample(project, 1.5), null);

const setup = post.plan(1280, 720, { threshold: 1, softKnee: .3, radius: 4 });
assert.deepEqual(setup.reduced, [747,420]);
assert.deepEqual(setup.prefilter, [373,210]);
assert.deepEqual(setup.levels, [[186,105],[93,52],[46,26]]);
assert.equal(setup.threshold, 1);
assert(Math.abs(setup.curve[0] - .69999) < 1e-9);
assert(Math.abs(setup.scale - 1.214246) < 1e-6);

window.MVStudioFlare = { sample: () => ({}), uniforms: () => ({}), apply() {} };
const canvasTarget = new T.WebGLRenderTarget(64, 32, { depthBuffer: true, stencilBuffer: true });
let target = canvasTarget, rejectPacked = false;
const draws = [], sources = [];
const gl = { SAMPLES: 1, FRAMEBUFFER: 2, FRAMEBUFFER_COMPLETE: 3,
  getParameter: () => 4, checkFramebufferStatus: () => rejectPacked && target.depthTexture ? 0 : 3 };
const renderer = {
  capabilities: { isWebGL2: true, maxTextureSize: 4096 }, domElement: { width: 64, height: 32 }, autoClear: false,
  getContext: () => gl, getRenderTarget: () => target, setRenderTarget: (value) => { target = value; },
  render(scene) {
    const { material } = scene.children[0];
    draws.push({ material, target, autoClear: this.autoClear });
  },
};

let pipeline = post.create(T, renderer);
pipeline.evaluate({}, 0);
assert.equal(pipeline.draw((source) => sources.push(source)), true);
assert.equal(sources[0].depthTexture, null);
assert.equal(draws.length, 1);
assert.equal(pipeline.draw((source) => sources.push(source), false, null, null, true), true);
assert.equal(sources[1].depthTexture.format, T.DepthStencilFormat);
assert.equal(sources[1].depthTexture.type, T.UnsignedInt248Type);
assert.equal(sources[1].samples, 4);
assert.equal(draws.length, 3);
const [composite, depth] = draws.slice(1);
assert.equal(composite.target, canvasTarget);
assert.equal(composite.material.depthWrite, false);
assert.equal(depth.target, composite.target);
assert.equal(depth.autoClear, false);
assert.equal(depth.material.depthTest, true);
assert.equal(depth.material.depthFunc, T.AlwaysDepth);
assert.equal(depth.material.depthWrite, true);
assert.equal(depth.material.colorWrite, false);
assert.equal(depth.material.stencilWrite, false);
assert.equal(depth.material.glslVersion, T.GLSL3);
assert.equal(depth.material.uniforms.sceneDepth.value, sources[1].depthTexture);
assert.match(depth.material.fragmentShader, /gl_FragDepth\s*=\s*texture\(sceneDepth, vUv\)\.r/);
assert.equal(target, canvasTarget);
assert.equal(renderer.autoClear, false);
pipeline.dispose();

rejectPacked = true;
pipeline = post.create(T, renderer);
pipeline.evaluate({}, 0);
assert.equal(pipeline.draw(() => assert.fail('Incomplete depth target must fall back'), false, null, null, true), false);
assert.equal(pipeline.draw((source) => assert.equal(source.depthTexture, null)), true);
assert.equal(draws.length, 4, 'a recovered color pass has no depth-only draw');
pipeline.dispose();
canvasTarget.dispose();
console.log('MV Studio native Bloom mixer, pyramid and optional composite depth passed');
