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
  const cameras = [];
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
      cameras.push({ position: camera.position.toArray(), rotation: camera.quaternion.toArray(),
        fov: camera.fov, near: camera.near, far: camera.far });
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
      bone.name = 'Move';
      bone.userData.elichika_node = 1;
      if (id === 62) bone.scale.setScalar(1.2);
      const auxiliary = new THREE.Object3D();
      auxiliary.name = 'SavedShape';
      auxiliary.userData.elichika_node = 2;
      const mesh = new THREE.SkinnedMesh(geometry, new THREE.ShaderMaterial({ vertexShader: shader.vertexShader }));
      mesh.name = `model-${id}`;
      mesh.bind(rig, new THREE.Matrix4());
      root.add(bone, mesh, auxiliary);
      const info = { mesh, rig, bone, auxiliary, releases: 0, materialsReleased: 0 };
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
      return { evaluatePose(time) { samples.push([root.userData.id, time]); },
        evaluateGaze() {}, eyePosition() {}, applyVisibility() {} };
    } }
  };
  async function fetch(url) {
    const id = Number.parseInt(url.split('/').at(-1), 16);
    fetched.push(id);
    return { ok: true, async arrayBuffer() { return Uint8Array.of(id).buffer; } };
  }
  const context = vm.createContext({ window, fetch, AbortController, Uint8Array, Uint16Array });
  const motion = window.ViewerMotionTimeline;
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/viewer-motion-timeline.js'), 'utf8'), context);
  window.ViewerMotionTimeline = { ...window.ViewerMotionTimeline, ...motion };
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-split.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-asset-dump.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-scene.js'), 'utf8'), context);
  const mount = { clientWidth: 1280, clientHeight: 720, appendChild() {} };
  const app = window.MVStudioScene.create(mount,
    { visible, onError(message) { throw new Error(message); } });
  return { app, frames, cameras, samples, models, holds, queued, fetched, parsing, renderer, mount, window,
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

async function checkNativeCamera() {
  const f = fixture();
  const track = { kind: 'camera', nativeClass: 'AnimationTrack', binding: '/EntryPoint/Live/Cameras/MainCamera', events: [
    { start: 1, duration: 1, values: { preExtrapolationMode: 1, preExtrapolationTime: .25,
      postExtrapolationMode: 1, postExtrapolationTime: .25, keyframes: [
        { time: 0, position: [0,2,10], rotation: [0,0,0,1], fov: 34 },
        { time: 1, position: [0,3,8], rotation: [0,0,0,1], fov: 23 },
        { time: 1.5, position: [0,4,6], rotation: [0,0,0,1], fov: 20 }
      ] } },
    { start: 2.25, duration: 1, values: { position: [2,2,4], rotation: [0,0,-Math.SQRT1_2,Math.SQRT1_2] } }
  ] };
  const offsets = { kind: 'camera', nativeClass: 'LiveCameraOffsetTrack', binding: track.binding, events: [
    { start: 2.25, duration: 1, values: { playableClass: 'LiveCameraOffsetClip', memberPosition: 1,
      intensity: 2, blendOut: .5 } },
    { start: 2.75, duration: .5, values: { playableClass: 'LiveCameraOffsetClip', memberPosition: 2,
      intensity: 1, blendIn: .5 } }
  ] };
  const cast = [
    { id: 'member-1', position: 1, rig: { scaling: { components: [{ targetName: 'ch0210_co0001_body', heightScale: 1.1 }] } } },
    { id: 'member-2', position: 2, rig: { scaling: { components: [{ targetName: 'ch0212_co0001_body', heightScale: .95 }] } } }
  ];
  const value = { tracks: [track, offsets], performers: cast };
  await f.app.load(value);
  const shot = (time) => { f.app.seek(time, value); return f.cameras.at(-1); };
  assert.equal(shot(.5).near, .02);
  assert.deepEqual(shot(.875).position, [-0,2,10]);
  assert.equal(shot(.875).fov, 34);
  assert.deepEqual(shot(2.125).position, [-0,3,8], 'post-Hold follows the active clip endpoint even when stored samples extend past the edited duration');
  assert.equal(shot(2.125).fov, 23);
  const cut = shot(2.25);
  assert.equal(cut.near, .1);
  assert.equal(cut.far, 1000);
  assert.equal(cut.fov, 30, 'native fallback is independent of the previous shot FOV');
  assert(Math.abs(cut.position[0] - (-2.2)) < 1e-12, 'offset uses the rolled local Y direction and native intensity');
  assert(Math.abs(cut.position[1] - 2) < 1e-12);
  const mixed = shot(2.875), smooth = .25 ** 2 * (3 - 2 * .25), mixedOffset = .2 * (1 - smooth) - .05 * smooth;
  assert(Math.abs(mixed.position[0] - (-2 - mixedOffset)) < 1e-12, 'overlapping native offsets sum their smoothstep input weights');
  offsets.muted = true;
  assert.deepEqual(shot(2.875).position, [-2,2,4]);
  f.mount.clientWidth = 960;
  f.checkResize();
  assert.equal(f.cameras.at(-1).fov, 40, 'a resize applies stock native aspect correction without requiring another seek');
  assert.equal(shot(3.3).near, .02, 'gaps beyond the authored Hold keep the editor view');
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

async function checkSavedNodeScaling() {
  const f = fixture();
  const spec = { available: true, scaling: { components: [{ entries: [
    { node: 1, name: 'Move', kind: 'scale', supported: true, application: 'absolute_local_scale',
      origin: [1, 1, 1], scaled: [1.2, 1.2, 1.2] },
    { node: 1, name: 'Move', kind: 'position', supported: true, application: 'absolute_local_position',
      origin: [0, 0, 0], scaled: [2, 0, 0] },
    { node: 1, name: 'Move', kind: 'rotation', supported: true, application: 'absolute_local_quaternion',
      interpolation: 'unity_euler_lerp', rotationOrder: 'ZXY', unityEulerOrigin: [0, 0, 0], unityEulerScaled: [0, 90, 0],
      scaledQuaternion: [0, -Math.SQRT1_2, 0, Math.SQRT1_2] },
    { node: 2, name: 'SavedShape', kind: 'scale', supported: true, application: 'absolute_local_scale',
      origin: [1, 1, 1], scaled: [1.3, 1.3, 1.3] },
  ] }] } };
  const value = project(61);
  value.performers[0].rig = spec;
  value.performers.push({ ...project(62).performers[0], id: 'another', position: 2, rig: spec });
  const track = { kind: 'dance', nativeClass: 'LiveMemberScalingTrack',
    binding: '/EntryPoint/Live/Members/Member1/Model', events: [
      { id: 'scale', start: 1, duration: 2, values: { playableClass: 'LiveMemberScalingClip', intensity: 1, easeIn: 1 } },
    ] };
  value.tracks.push(track);
  await f.app.load(value);
  const first = f.models.get(61), baked = f.models.get(62);
  const expectMove = (node, scale, position, rotation) => {
    assert(Math.abs(node.scale.x - scale) < 1e-10);
    assert(Math.abs(node.position.x - position) < 1e-10);
    assert(Math.abs(node.quaternion.y - rotation) < 1e-10);
  };
  expectMove(first.bone, 1.2, 2, -Math.SQRT1_2);
  expectMove(baked.bone, 1.2, 2, -Math.SQRT1_2);
  f.app.seek(1.5, value);
  expectMove(first.bone, 1.1, 1, -Math.sin(Math.PI / 8));
  f.app.seek(2.5, value);
  expectMove(first.bone, 1, 0, 0);
  expectMove(baked.bone, 1.2, 2, -Math.SQRT1_2);
  assert.equal(first.auxiliary.scale.x, 1.3, 'the authored override affects Move only');
  f.app.seek(4, value);
  expectMove(first.bone, 1.2, 2, -Math.SQRT1_2);
  f.app.seek(2.5, value);
  track.muted = true;
  f.app.seek(2.5, value);
  expectMove(first.bone, 1.2, 2, -Math.SQRT1_2);
  track.muted = false;
  track.binding = '/EntryPoint/Live/Members/Member1/NotModel';
  f.app.seek(2.5, value);
  expectMove(first.bone, 1.2, 2, -Math.SQRT1_2);
  f.app.dispose();
}

async function checkNativeMemberCulling() {
  const f = fixture(), value = project(55);
  const culling = { nativeClass: 'LiveMemberCullerTrack', binding: '/EntryPoint/Live/Members/Member1', events: [
    { start: 1, duration: 0, values: { playableClass: 'LiveMemberCullerClip' } },
    { start: 2, duration: 1, values: { playableClass: 'LiveMemberCullerClip' } },
  ] };
  value.tracks.push(culling);
  await f.app.load(value);
  f.app.seek(1, value);
  assert.deepEqual(f.frames.at(-1), ['model-55', 'outline-55']);
  f.app.seek(2.5, value);
  assert.deepEqual(f.frames.at(-1), []);
  assert.deepEqual(f.samples.at(-1), [55, 2.5], 'authored culling continues pose sampling');
  assert.equal(f.models.get(55).mesh.visible, true, 'the renderer branch is hidden without changing face/mesh flags');
  f.app.seek(3, value);
  assert.deepEqual(f.frames.at(-1), ['model-55', 'outline-55']);
  culling.muted = true;
  f.app.seek(2.5, value);
  assert.deepEqual(f.frames.at(-1), ['model-55', 'outline-55']);
  f.app.dispose();
}

// LiveCoreMemberManager.MemberMax = 12: lives such as 12074 bind Member10..Member12.
async function checkTwelvePerformers() {
  const f = fixture(), value = project(70);
  value.performers = Array.from({ length: 13 }, (_, index) => ({ ...project(70 + index).performers[0],
    id: `member-${index + 1}`, position: index + 1 }));
  value.tracks.push({ nativeClass: 'LiveMemberCullerTrack', binding: '/EntryPoint/Live/Members/Member12', events: [
    { start: 2, duration: 1, values: { playableClass: 'LiveMemberCullerClip' } },
  ] });
  await f.app.load(value);
  f.app.seek(1, value);
  const shown = new Set(f.frames.at(-1));
  for (let index = 0; index < 12; index++) assert(shown.has(`model-${70 + index}`), `performer ${index + 1} is loaded`);
  assert(!shown.has('model-82'), 'a thirteenth performer is beyond MemberMax');
  f.app.seek(2.5, value);
  const culled = new Set(f.frames.at(-1));
  assert(!culled.has('model-81') && !culled.has('outline-81'), 'Member12 culling hides the twelfth performer');
  assert(culled.has('model-79') && culled.has('model-80'), 'Member12 culling leaves Member10/11 visible');
  f.app.dispose();
}

function stateOf(f) {
  const nodes = [];
  f.world.traverse((node) => {
    const uniforms = {};
    for (const material of node.material ? [node.material].flat() : []) {
      for (const [name, holder] of Object.entries(material.uniforms || {})) {
        const value = holder.value;
        uniforms[name] = value?.toArray ? value.toArray() : value?.isTexture ? value.uuid : value;
      }
    }
    nodes.push([node.uuid, node.position.toArray(), node.quaternion.toArray(), node.scale.toArray(), node.visible,
      Array.from(node.matrixWorld.elements), uniforms]);
  });
  return { inspect: f.app.inspect(), nodes, frames: f.frames.length, queued: f.queued.size,
    size: f.renderer.size.toArray(), ratio: f.renderer.getPixelRatio() };
}

async function checkAssetDump() {
  const f = fixture();
  const track = { id: 'cam', label: 'Camera/MainCamera', kind: 'camera', nativeClass: 'AnimationTrack',
    binding: '/EntryPoint/Live/Cameras/MainCamera', events: [{ id: 'cam:0', start: 0, duration: 10, values: { keyframes: [
      { time: 0, position: [1, 2, 10], rotation: [0, 0, 0, 1], fov: 30 },
      { time: 10, position: [1, 2, 0], rotation: [0, 0, 0, 1], fov: 30 }] } }] };
  const value = project(71);
  value.duration = 12;
  value.tracks = [track];
  value.performers[0].memberId = 212;
  value.performers[0].costumeId = 100212001;
  value.performers[0].rig = { bones: [{ node: 1, path: 'Reference/Move' }] };
  await f.app.load(value);
  f.mount.clientWidth = 720;
  f.checkResize();
  f.app.seek(2, value, true);
  const sections = ['clock', 'directors', 'cameras', 'correctors', 'cameraWork', 'globals', 'renderSettings', 'lights',
    'memberIdentity', 'anchors', 'renderers', 'materials', 'members', 'stageNodes', 'post', 'quality', 'census', 'particles'];
  const before = stateOf(f);
  const dump = (request) => JSON.parse(JSON.stringify(f.app.assetDump(request)));
  const first = dump({ sections });
  const second = dump({ sections });
  const after = stateOf(f);
  assert.deepEqual(after, before, 'assetDump must not change time, cameras, transforms, uniforms, draws or the viewport');
  delete first.cost; delete second.cost;
  assert.deepEqual(second, first, 'assetDump is idempotent');
  assert.deepEqual(first.errors, []);
  assert.deepEqual(first.nonFinite, []);
  assert.deepEqual(first.clock, { directorTime: 2, rate: 30 });
  assert.deepEqual(first.directors, [{ key: 'director:main', time: 2, duration: 12 }]);
  const [main] = first.cameras;
  assert.equal(main.key, 'camera:main');
  assert.equal(main.liveShot, true);
  assert.equal(main.aspect, 1);
  assert(Math.abs(main.fieldOfView - 40) < 1e-6, 'degrees: authored 30 divided by the 0.75 correction at 1:1');
  assert.equal(main.authoredFov, 30);
  assert.equal(main.nativeLens, true);
  assert.deepEqual(main.event, { track: 'cam', label: 'Camera/MainCamera', nativeClass: 'AnimationTrack',
    binding: '/EntryPoint/Live/Cameras/MainCamera', clipIndex: 0, start: 0, duration: 10 });
  assert.deepEqual(main.checks, { matrixWorldCurrent: true, projectionMatchesFov: true });
  // Column-major (three.js .elements, Unity Matrix4x4 memory order): e[11] = -1 for a perspective projection.
  assert.equal(main.projection[11], -1);
  assert.equal(main.projection[15], 0);
  assert(Math.abs(main.projection[5] - 1 / Math.tan(20 * Math.PI / 180)) < 1e-6);
  assert.deepEqual(main.transform.position, [-1, 2, 8], 'editor space mirrors Unity X; the producer never converts');
  const w = main.worldToCamera, p = main.transform.position;
  const eye = [0, 1, 2].map((row) => w[row] * p[0] + w[4 + row] * p[1] + w[8 + row] * p[2] + w[12 + row]);
  assert(eye.every((v) => Math.abs(v) < 1e-9), 'worldToCamera maps the camera position to the eye');
  assert.deepEqual(first.correctors, [{ key: 'corrector:camera:main', correction: 0.75, aspectInput: 1,
    bounds: { min: 0.75, max: 1 }, nativeLens: true, mode: { modeled: false } }]);
  assert.deepEqual(first.cameraWork, [{ key: 'cameraWork:/EntryPoint/Live/Cameras/MainCamera', authoredFov: 30 }]);
  assert.deepEqual(first.renderSettings, { modeled: false });
  assert.deepEqual(first.lights, { modeled: false });
  assert.deepEqual(first.particles, { modeled: false });
  assert.equal(first.globals['global:_Beat'], null, 'quantities the editor does not model are null');
  assert.equal(first.renderers.length, 1);
  assert.equal(first.renderers[0].key, 'renderer:member1:model-71');
  assert.equal(first.renderers[0].visible, true);
  assert.equal(first.renderers[0].culled, false);
  assert.equal(first.renderers[0].path, null, 'a rig-root mesh node carries no GameObject chain');
  assert.equal(first.renderers[0].pathSource, 'flattened');
  assert.deepEqual(first.materials.map((m) => m.key), ['material:renderer:member1:model-71#0']);
  const bones = first.members.find((m) => m.bones)?.bones || [];
  assert.deepEqual(bones.map((bone) => bone.key), ['member:1:Reference/Move']);
  assert.deepEqual(first.census.nodes.map((node) => node.kind).sort(), ['bone', 'renderer']);
  assert.deepEqual(first.census.nodes.find((node) => node.kind === 'renderer'),
    { key: 'renderer:member1:model-71', kind: 'renderer', scope: 'member1', mesh: 'model-71', path: null });
  assert.deepEqual(first.quality, { mode: null, values: {} });
  assert.deepEqual(first.memberIdentity, [{ slot: 1, memberId: 212, costumeId: 100212001 }]);
  assert.deepEqual(dump({ sections: ['memberIdentity'] }).members, first.memberIdentity, 'frame records carry identity as members');
  const narrow = dump({ sections: ['renderers'], filter: { renderers: [{ scope: 'member1', mesh: 'other' }] } });
  assert.deepEqual(narrow.renderers, [], 'renderer filters select by scope and mesh');
  f.app.dispose();
}

// The member culler hides the actor root in the editor; the dump reports it as
// "culled" with node visibility unchanged, and reading it changes nothing.
async function checkAssetDumpCuller() {
  const f = fixture(), value = project(72);
  value.duration = 12;
  value.tracks.push({ nativeClass: 'LiveMemberCullerTrack', binding: '/EntryPoint/Live/Members/Member1', events: [
    { start: 1, duration: 2, values: { playableClass: 'LiveMemberCullerClip' } }] });
  await f.app.load(value);
  const renderer = (time) => {
    f.app.seek(time, value, true);
    const before = stateOf(f);
    const [entry] = JSON.parse(JSON.stringify(f.app.assetDump({ sections: ['renderers'] }))).renderers;
    assert.deepEqual(stateOf(f), before, 'assetDump stays read-only inside a culler clip');
    return entry;
  };
  const inside = renderer(2);
  assert.equal(f.models.get(72).mesh.parent.visible, false, 'the editor culls through the actor root');
  assert.deepEqual([inside.visible, inside.culled], [true, true], 'a culler hide is culled, not a node visibility change');
  const after = renderer(3.5);
  assert.deepEqual([after.visible, after.culled], [true, false]);
  f.app.dispose();
}

function checkAssetDumpHelpers() {
  const helpers = fixture().window.MVStudioAssetDump;
  // Results are built in the vm realm: compare them as plain JSON.
  const D = { gameObjectPath: (...args) => JSON.parse(JSON.stringify(helpers.gameObjectPath(...args))),
    textureIdentity: (...args) => JSON.parse(JSON.stringify(helpers.textureIdentity(...args))) };
  const node = (name, tag) => {
    const value = new THREE.Object3D();
    if (name !== null) value.userData.name = name;
    if (tag) value.userData.mvStageNode = { active: true };
    return value;
  };
  const root = new THREE.Group(), prefab = node('bg0006_01_fx_so2035_ex', true), group = node('ver', true);
  const gameObject = node('ver_color_02', true), wrapper = node(null, false);
  const mesh = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  mesh.userData.name = 'ver_color_01';
  root.add(prefab); prefab.add(wrapper); wrapper.add(group); group.add(gameObject); gameObject.add(mesh);
  assert.deepEqual(D.gameObjectPath(mesh, root), { path: 'bg0006_01_fx_so2035_ex/ver/ver_color_02', pathSource: 'stageNodes' },
    'GameObject names from the tagged chain; the mesh node is named after the Mesh asset; editor wrappers are skipped');
  const flat = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  flat.userData.name = 'bg0006_01_aud_01';
  root.add(flat);
  assert.deepEqual(D.gameObjectPath(flat, root), { path: null, pathSource: 'flattened' });
  const character = node('Character__0', false), skinned = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  skinned.userData.name = 'Body';
  root.add(character); character.add(skinned);
  assert.deepEqual(D.gameObjectPath(skinned, root), { path: null, pathSource: 'flattened' });
  const broken = node('Untagged', false), inner = node('inner', true), leaf = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial());
  root.add(broken); broken.add(inner); inner.add(leaf);
  assert.deepEqual(D.gameObjectPath(leaf, root), { path: null, pathSource: 'flattened' }, 'an untagged glTF node breaks the chain');
  const constant = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
  assert.deepEqual(D.textureIdentity(constant), { name: null, width: 1, height: 1, placeholder: true });
  const real = new THREE.DataTexture(new Uint8Array(16), 2, 2);
  real.name = 'atlas';
  assert.deepEqual(D.textureIdentity(real), { name: 'atlas', width: 2, height: 2 });
}

(async () => {
  checkResizeDraws();
  await checkAssetDump();
  await checkAssetDumpCuller();
  checkAssetDumpHelpers();
  await checkNativeCamera();
  await checkSavedNodeScaling();
  await checkNativeMemberCulling();
  await checkTwelvePerformers();
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
  assert.equal(info.mesh.frustumCulled, false, 'animated faces must bypass static glTF bounds');
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
