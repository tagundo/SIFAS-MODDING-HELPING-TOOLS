/* Real Three.js poses and resource ownership with a small instrumented renderer. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const THREE = require('../webtools/web/static/vendor/three-r128/three.min.js');
const shader = require('../webtools/web/static/sifas-material.js');

const address = (id) => '/api/mv-studio/media/' + id.toString(16).padStart(32, '0') + '.glb';
function latch() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
function fixture(visible = true) {
  const frames = [], samples = [], models = new Map(), holds = new Map(), queued = new Map();
  const fetched = [], parsing = new Map();
  let world, renderer, onResize, serial = 0;
  THREE.WebGLRenderer = class {
    constructor() {
      renderer = this;
      this.domElement = { setAttribute() {}, remove() {}, width: 1280, height: 720 };
      this.shadowMap = { enabled: false }; this.capabilities = { isWebGL2: true };
      this.size = new THREE.Vector2();
    }
    setClearColor() {}
    getSize(out) { return out.copy(this.size); }
    setSize(width, height) { this.size.set(width, height); }
    getPixelRatio() { return this.pixelRatio; }
    setPixelRatio(value) { this.pixelRatio = value; }
    render(scene, camera) {
      world = scene;
      if (scene.autoUpdate) scene.updateMatrixWorld();
      camera.updateMatrixWorld();
      const visible = [];
      scene.traverseVisible((node) => { if (node.isSkinnedMesh) visible.push(node.name); });
      frames.push(visible);
    }
    dispose() {}
  };
  THREE.OrbitControls = class {
    constructor() { this.target = new THREE.Vector3(); }
    update() {}
    addEventListener() {}
    dispose() {}
  };
  THREE.GLTFLoader = class {
    parse(bytes, _base, onLoad, onError) {
      const id = new Uint8Array(bytes)[0];
      const root = new THREE.Group();
      root.userData.id = id;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute([0,0,0, 1,0,0, 0,1,0], 3));
      geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0,0,0,0, 0,0,0,0, 0,0,0,0], 4));
      geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1,0,0,0, 1,0,0,0, 1,0,0,0], 4));
      geometry.morphTargetsRelative = true;
      geometry.morphAttributes.position = [new THREE.Float32BufferAttribute([0,0,0, 0.25,0,0, 0,0,0], 3)];
      const bone = new THREE.Bone(), rig = new THREE.Skeleton([bone]);
      const mesh = new THREE.SkinnedMesh(geometry, new THREE.ShaderMaterial({ vertexShader: shader.vertexShader }));
      mesh.name = `model-${id}`;
      mesh.bind(rig, new THREE.Matrix4());
      root.add(bone, mesh);
      const info = { mesh, rig, releases: 0, materialsReleased: 0 };
      rig.dispose = () => { info.releases++; };
      models.set(id, info);
      const hold = parsing.get(id);
      if (hold) {
        hold.started.resolve();
        hold.finish.promise.then((error) => {
          if (error) onError(error);
          else onLoad({ scene: root, animations: [] });
        });
      } else onLoad({ scene: root, animations: [] });
    }
  };
  const window = {
    THREE, requestAnimationFrame(callback) { queued.set(++serial, callback); return serial; },
    cancelAnimationFrame(id) { queued.delete(id); },
    ResizeObserver: class {
      constructor(callback) { onResize = callback; }
      observe() {}
      disconnect() {}
    },
    SifasMaterial: { ...shader, apply(root) {
      const id = root.userData.id, info = models.get(id), mesh = info.mesh;
      const outline = new THREE.SkinnedMesh(mesh.geometry, new THREE.ShaderMaterial({
        vertexShader: shader.outlineVertexShader, uniforms: { uOutlineEdited: { value: 0 } }
      }));
      outline.name = `outline-${id}`;
      outline.userData.sifasOutline = true;
      outline.bind(mesh.skeleton, mesh.bindMatrix);
      mesh.add(outline);
      info.outline = outline;
      const hold = holds.get(id);
      if (hold) hold.started.resolve();
      return { ready: hold?.finish.promise || Promise.resolve(), dispose() { info.materialsReleased++; } };
    } },
    ViewerMotionTimeline: { create(root) {
      return { evaluate(time) { samples.push([root.userData.id, time]); }, applyVisibility() {} };
    } }
  };
  async function fetch(url) {
    const id = Number.parseInt(url.split('/').at(-1), 16);
    fetched.push(id);
    return { ok: true, async arrayBuffer() { return Uint8Array.of(id).buffer; } };
  }
  vm.runInNewContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-scene.js'), 'utf8'),
    { window, fetch, AbortController, Uint8Array, Uint16Array });
  const mount = { clientWidth: 1280, clientHeight: 720, appendChild() {} };
  const app = window.MVStudioScene.create(mount,
    { visible, onError(message) { throw new Error(message); } });
  return { app, frames, samples, models, holds, queued, fetched, parsing, renderer, mount, window,
    checkResize: onResize, get world() { return world; } };
}

function project(id) {
  return { token: `project-${id}`, performers: [{ id: 'solo', position: 1, glb: address(id), motion: {}, transform: { position: [0,0,0] } }],
    tracks: [{ kind: 'camera', binding: '/MainCamera', events: [{ start: 0, duration: 10,
      values: { position: [0,0,10], rotation: [0,0,0,1], fov: 45 } }] }] };
}

function checkResizeDraws() {
  const f = fixture();
  f.checkResize();
  f.app.setVisible(true);
  assert.equal(f.frames.length, 1, 'an initial resize notification and repeated visibility do not duplicate the draw');
  f.mount.clientWidth = 800;
  f.checkResize();
  assert.equal(f.frames.length, 2);
  assert.equal(f.renderer.size.x, 800);
  f.window.devicePixelRatio = 2;
  f.checkResize();
  assert.equal(f.frames.length, 3, 'a changed pixel ratio redraws even at the same logical size');
  assert.equal(f.renderer.getPixelRatio(), 2);
  f.app.resize();
  assert.equal(f.frames.length, 4, 'explicit scene resize still requests a draw');
  f.app.setVisible(false);
  f.mount.clientWidth = 640;
  f.window.devicePixelRatio = 1;
  f.checkResize();
  f.app.resize();
  assert.equal(f.frames.length, 4);
  assert.equal(f.renderer.size.x, 800, 'a hidden canvas keeps its allocation until shown');
  assert.equal(f.renderer.getPixelRatio(), 2);
  f.app.setVisible(true);
  assert.equal(f.frames.length, 5);
  assert.equal(f.renderer.size.x, 640);
  assert.equal(f.renderer.getPixelRatio(), 1);
  f.app.dispose();
}

async function checkStagePreparation() {
  const f = fixture(), previous = project(11);
  previous.quality = { values: { rendering_resolution: 360 } };
  await f.app.load(previous);
  const priorWorld = f.world, priorActor = f.models.get(11);
  const preview = {
    stage: { glb: address(21), effectsGlb: address(22) },
    assets: [{ kind: 'props', previewUrl: address(23) }, { kind: 'audio', previewUrl: address(90) }],
    performers: project(91).performers,
    quality: { values: { rendering_resolution: 480, stage_control: false } },
    tracks: [{ kind: 'lighting', events: [{ start: 0, duration: 1,
      values: { playableClass: 'LiveBaseLightClip', ambientColor: [.2,.4,.6] } }] }]
  };
  const effect = { started: latch(), finish: latch() };
  f.parsing.set(22, effect);
  const preparing = f.app.prepareStage(preview);
  await effect.started.promise;
  assert.deepEqual(f.fetched, [11,21,22]);
  assert.deepEqual(f.frames.at(-1), ['model-21'], 'the base is drawn while the optional effects asset is still decoding');
  assert.notEqual(f.world, priorWorld);
  const overviewLight = f.world.children.find(node => node.isHemisphereLight);
  assert.deepEqual(overviewLight.color.toArray(), [.2,.4,.6]);
  assert.equal(f.renderer.getPixelRatio(), 480 / 720);
  assert.equal(priorActor.releases, 0, 'preview must retain the prior canonical scene');
  const firstStage = f.models.get(21);
  const next = { ...project(25), stage: preview.stage,
    assets: [...preview.assets, { kind: 'background', previewUrl: address(24) }], quality: previous.quality };
  const committing = f.app.load(next, { reuseStage: true });
  assert.deepEqual(f.fetched, [11,21,22]);
  effect.finish.resolve();
  assert.equal(await preparing, true);
  await committing;
  assert.deepEqual(f.fetched, [11,21,22,23,24,25], 'an in-flight matching preview and its effects are fetched exactly once');
  assert.equal(priorActor.releases, 1);
  assert.equal(f.models.get(21), firstStage, 'the stage reused the same parsed root');
  assert.equal(firstStage.releases, 0);
  assert.equal(overviewLight.parent, null, 'reusable lights must not hold the retired preview scene');
  assert.deepEqual(f.frames.at(-1), ['model-21','model-25','outline-25','model-22','model-23','model-24']);
  assert.equal(f.world, priorWorld);
  assert.equal(f.renderer.getPixelRatio(), 360 / 720);
  const changedOutfit = structuredClone(next);
  changedOutfit.performers[0].glb = address(26);
  const beforeOutfit = f.fetched.length;
  await f.app.load(changedOutfit, { reuseOutfit: 'solo' });
  assert.deepEqual(f.fetched.slice(beforeOutfit), [26], 'outfit replacement still reuses the adopted stage and effects');
  assert.equal(f.models.get(21), firstStage);

  const transient = { stage: { glb: address(31) }, quality: preview.quality };
  assert.equal(await f.app.prepareStage(transient), true);
  assert.deepEqual(f.frames.at(-1), ['model-31']);
  f.app.cancelStagePreparation();
  assert.equal(f.models.get(31).releases, 1);
  assert.equal(f.world, priorWorld);
  assert.equal(f.renderer.getPixelRatio(), 360 / 720);
  assert.equal(firstStage.releases, 0);

  const late = { started: latch(), finish: latch() };
  f.parsing.set(32, late);
  const canceled = f.app.prepareStage({ stage: { glb: address(32) } });
  await late.started.promise;
  f.app.cancelStagePreparation();
  late.finish.resolve();
  assert.equal(await canceled, false);
  assert.equal(f.models.get(32).releases, 1, 'decoded resources from a canceled stage are released');
  assert.equal(f.world, priorWorld);

  const differentRole = { stage: { glb: address(34) }, assets: [{ kind: 'props', previewUrl: address(35) }] };
  await f.app.prepareStage(differentRole);
  const mismatched = f.models.get(34);
  const afterMismatch = f.fetched.length;
  await f.app.load({ ...differentRole, assets: [{ kind: 'effect', previewUrl: address(35) }] }, { reuseStage: true });
  assert.deepEqual(f.fetched.slice(afterMismatch), [34,35], 'a role mismatch falls back to the complete model load');
  assert.equal(mismatched.releases, 1);

  const failure = { started: latch(), finish: latch() };
  f.parsing.set(42, failure);
  const failed = f.app.prepareStage({ stage: { glb: address(41), effectsGlb: address(42) } });
  const rejected = assert.rejects(failed, /broken preview asset/);
  await failure.started.promise;
  const failedStage = f.models.get(41);
  const afterFailure = f.fetched.length;
  const recovered = f.app.load({ stage: { glb: address(41), effectsGlb: address(42) } }, { reuseStage: true });
  f.parsing.delete(42);
  failure.finish.resolve(new Error('broken preview asset'));
  await rejected;
  await recovered;
  assert.deepEqual(f.fetched.slice(afterFailure), [41,42]);
  assert.equal(failedStage.releases, 1, 'a preview failure releases its earlier finished assets');
  assert.deepEqual(f.frames.at(-1), ['model-41','model-42']);
  f.app.dispose();

  const hidden = fixture(false);
  const hiddenStage = { stage: { glb: address(51) }, assets: [] };
  await hidden.app.prepareStage(hiddenStage);
  await hidden.app.load({ ...hiddenStage, ...project(52) }, { reuseStage: true });
  assert.deepEqual(hidden.fetched, [51,52]);
  assert.deepEqual(hidden.frames, [], 'hidden stage preparation and canonical commit do not draw');
  hidden.app.setVisible(true);
  assert.deepEqual(hidden.frames.at(-1), ['model-51','model-52','outline-52']);
  hidden.app.dispose();
}

(async () => {
  checkResizeDraws();
  const f = fixture(), first = project(1);
  await f.app.load(first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);
  const rendered = f.frames.length, sampled = f.samples.length;
  for (const time of [1, 2, 3]) f.app.seek(time, first, true);
  assert.equal(f.frames.length, rendered);
  assert.deepEqual(f.samples.slice(sampled), [[1,1], [1,2], [1,3]]);
  assert.equal(f.queued.size, 1);
  f.app.flushSeekDraw();
  f.app.flushSeekDraw();
  assert.equal(f.frames.length, rendered + 1);
  assert.equal(f.samples.length, sampled + 3);
  f.app.seek(4, first, true);
  f.app.setVisible(false);
  assert.equal(f.queued.size, 0);
  f.app.flushSeekDraw();
  assert.equal(f.frames.length, rendered + 1);
  f.app.setVisible(true);

  first.performers[0].transform.position = [100,0,0];
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), [], 'an offscreen skinned body and its outline should both be culled');
  const info = f.models.get(1);
  assert.equal(info.mesh.visible, true, 'culling must not change visibility outside the renderer');
  f.renderer.shadowMap.enabled = true;
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);
  f.renderer.shadowMap.enabled = false;
  info.mesh.morphTargetInfluences[0] = 1.1;
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);
  info.mesh.morphTargetInfluences[0] = 0;
  info.outline.material.uniforms.uOutlineEdited.value = 1;
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);
  info.outline.material.uniforms.uOutlineEdited.value = 0;
  info.mesh.geometry.getAttribute('position').needsUpdate = true;
  f.app.seek(5, first);
  assert.deepEqual(f.frames.at(-1), ['model-1', 'outline-1']);

  const hold = { started: latch(), finish: latch() };
  f.holds.set(2, hold);
  const canceled = f.app.load(project(2));
  await hold.started.promise;
  assert.equal(info.releases, 1, 'the old main and outline must release their shared skeleton once');
  await f.app.load(project(3));
  hold.finish.resolve();
  await canceled;
  assert.equal(f.models.get(2).releases, 1, 'a canceled staged skeleton must be released');
  assert.equal(f.models.get(2).materialsReleased, 1);
  assert.equal(f.models.get(3).releases, 0);
  f.app.dispose();
  assert.equal(f.models.get(3).releases, 1);
  assert.equal(f.queued.size, 0);
  await checkStagePreparation();
  console.log('MV Studio viewport, render-only scrubbing, conservative culling, skeleton lifecycle and stage reuse passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
