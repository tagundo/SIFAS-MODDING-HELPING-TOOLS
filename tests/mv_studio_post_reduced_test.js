'use strict';
// PostProcessingBehaviour.OnPostRender (GL 3.12.0, 0x2cd19dc-0x2cd1a20) blits the camera image into
// PostProcessingContext's 420-pixel-high reduced image once when DOF or bloom is active, and both
// DepthOfFieldComponent.Prepare (get_ReducedImage 0x2ccebd8, Blit 0x2ccec58) and BloomComponent.Prepare
// filter that reduced image. CreateRenderTextures (0x2ccf0c0) sizes the DOF pyramid from it.
const assert = require('node:assert/strict');
const T = require('../webtools/web/static/vendor/three-r128/three.min.js');

global.window = {};
require('../webtools/web/static/viewer-motion-timeline.js');
require('../webtools/web/static/mv-studio-lighting.js');
require('../webtools/web/static/mv-studio-dof.js');
require('../webtools/web/static/mv-studio-post.js');
const realDof = window.MVStudioDof;

// CreateReducedImage (0x2cd22d0): Math.Round(width / height * 420f, AwayFromZero) x 420.
assert.deepEqual(window.MVStudioPost.reducedSize(1280, 720), [747, 420]);
assert.deepEqual(window.MVStudioPost.reducedSize(720, 1280), [236, 420]);
assert.deepEqual(window.MVStudioPost.reducedSize(1920, 1080), [747, 420]);

// The DOF pyramid halves the reduced image; the CoC limit still uses the camera height.
const camera = { near: 0.1, far: 1000 };
const lens = { distance: 7, focalLength: 0.02, aperture: 6, kernelSize: 0 };
let layout = realDof.plan(1280, 720, lens, camera, [747, 420]);
assert.deepEqual(layout.sizes, [[373, 210], [186, 105]]);
assert.equal(layout.params[2], 6 / 720, 'CalculateMaxCoCRadius reads the camera image height');
layout = realDof.plan(1280, 720, { ...lens, kernelSize: 2 }, camera, [747, 420]);
assert.deepEqual(layout.sizes, [[373, 210], [186, 105], [93, 52], [46, 26]]);
assert.equal(layout.params[2], 14 / 720);

const prepared = [];
window.MVStudioDof = {
  ...realDof,
  create: () => ({
    prepare(source, lens, view, image) {
      prepared.push({ source, image, after: draws.length });
      return { image: null, depth: source.depthTexture, params: [1, 1, 1], zParams: [1, 1] };
    },
    dispose() {},
  }),
};
window.MVStudioFlare = { sample: () => null, uniforms: () => ({}), apply() {} };

const canvasTarget = new T.WebGLRenderTarget(16, 16);
let target = canvasTarget;
const draws = [];
const gl = { SAMPLES: 1, FRAMEBUFFER: 2, FRAMEBUFFER_COMPLETE: 3, getParameter: () => 0, checkFramebufferStatus: () => 3 };
const renderer = {
  capabilities: { isWebGL2: true, maxTextureSize: 4096 }, domElement: { width: 1280, height: 720 }, autoClear: false,
  getContext: () => gl, getRenderTarget: () => target, setRenderTarget: (value) => { target = value; },
  render(scene) {
    const { material } = scene.children[0];
    draws.push({ material, target, input: material.uniforms.image?.value ?? null });
  },
};
const reduceShader = /gl_FragColor = texture2D\(image, vUv\);/;
const prefilterShader = /linearColor\(sampleColor\)/;

const post = window.MVStudioPost;
let pipeline = post.create(T, renderer);
pipeline.evaluate({}, 0);
let scene = null;
assert.equal(pipeline.draw((source) => { scene = source; }, true, lens, camera), true);
const reduce = draws.filter(({ material }) => reduceShader.test(material.fragmentShader));
assert.equal(reduce.length, 1, 'DOF alone still builds the reduced image');
assert.equal(reduce[0].input, scene.texture, 'the reduced image is a copy of the camera image');
assert.deepEqual([reduce[0].target.width, reduce[0].target.height], [747, 420]);
assert.equal(prepared.length, 1);
assert.equal(prepared[0].source, scene, 'the camera image keeps the depth and the CoC height');
assert.equal(prepared[0].image, reduce[0].target, 'DOF filters the reduced image, not the camera image');
assert.equal(prepared[0].after, draws.indexOf(reduce[0]) + 1, 'the reduced image is drawn before DOF reads it');
pipeline.dispose();

// Bloom and DOF share one reduced image, drawn once before either reads it.
const bloom = { start: 0, duration: 4, values: { playableClass: 'LiveBloomClip', intensity: .46, threshold: .8, softKnee: .3,
  radius: 4, antiFlicker: 0, blendIn: -1, blendOut: -1 } };
const project = { quality: { values: { posteffect: true } },
  tracks: [{ nativeClass: 'LiveBloomTrack', binding: '/EntryPoint/Live/Cameras/MainCamera', events: [bloom] }] };
draws.length = 0;
prepared.length = 0;
pipeline = post.create(T, renderer);
pipeline.evaluate(project, 1);
assert.equal(pipeline.draw((source) => { scene = source; }, true, lens, camera), true);
const reduced = draws.filter(({ material }) => reduceShader.test(material.fragmentShader));
const prefilter = draws.filter(({ material }) => prefilterShader.test(material.fragmentShader));
assert.equal(reduced.length, 1, 'one reduced image per frame');
assert.equal(prefilter.length, 1);
assert.equal(prefilter[0].input, reduced[0].target.texture, 'bloom prefilters the reduced image');
assert.equal(prepared[0].image, reduced[0].target, 'DOF reads the same reduced image');
assert(prepared[0].after <= draws.indexOf(prefilter[0]), 'DOF prepares before bloom, as OnPostRender orders them');
pipeline.dispose();
canvasTarget.dispose();
console.log('MV Studio post: DOF and bloom read one 420-pixel reduced image; DOF pyramid sized from it');
