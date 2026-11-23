/* The live camera clear of original MV projects (level35 MainCamera/Offset/Camera). */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');

const clears = [];
THREE.WebGLRenderer = class {
  constructor() {
    this.domElement = { setAttribute() {}, remove() {} };
    this.shadowMap = {};
    this.capabilities = { isWebGL2: true };
    this.size = new THREE.Vector2();
  }
  setClearColor(color, alpha = 1) { clears.push([new THREE.Color(color).getHex(), alpha]); }
  getSize(value) { value.copy(this.size); }
  setSize(x, y) { this.size.set(x, y); }
  setPixelRatio(value) { this.ratio = value; }
  getPixelRatio() { return this.ratio; }
  render() {}
  dispose() {}
};
THREE.OrbitControls = class {
  constructor() { this.target = new THREE.Vector3(); }
  update() {}
  addEventListener() {}
  dispose() {}
};
THREE.GLTFLoader = class { parse(_bytes, _base, onLoad) { onLoad({ scene: new THREE.Group(), animations: [] }); } };
const window = { THREE, requestAnimationFrame: () => 1, cancelAnimationFrame() {} };
vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-scene.js'), 'utf8'),
  { window, fetch: async () => ({ ok: false }), AbortController });
const app = window.MVStudioScene.create({ clientWidth: 1280, clientHeight: 720, appendChild() {} }, {});

assert.deepEqual(clears.at(-1), [0x111522, 1], 'the editor backdrop before a project');
const game = { source: { kind: 'game', region: 'gl', platform: 'android', liveId: 12035, assetId: 1203503 },
  stage: {}, assets: [], tracks: [], performers: [] };
app.seek(1, game);
// The 12035 CI runtime dump records camera:main clearFlags SolidColor, backgroundColor (0, 0, 0, 0).
assert.deepEqual(clears.at(-1), [0x000000, 0], 'an original MV clears like the native main camera');
app.seek(1, { ...game, source: { kind: 'local' } });
assert.deepEqual(clears.at(-1), [0x111522, 1], 'edited projects keep the editor backdrop');
console.log('MV Studio clear color: native SolidColor (0, 0, 0, 0) for original MVs.');
