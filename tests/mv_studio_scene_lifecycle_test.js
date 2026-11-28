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
function fixture(visible = true, options = {}) {
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
    getDrawingBufferSize(out) { return out.set(Math.floor(this.size.x * (this.pixelRatio ?? 1)), Math.floor(this.size.y * (this.pixelRatio ?? 1))); }
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
      Object.assign(root.userData, options.userData?.[id]);
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
      options.build?.(root, id);
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
      return { ready: hold?.finish.promise || Promise.resolve(), dispose() { info.materialsReleased++; },
        setRimlight(value) { (info.rimlight ||= []).push(value); },
        setLiveLighting(value) { info.liveLighting = value; } };
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
  if (options.lighting) {
    vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-lighting.js'), 'utf8'), context);
  }
  if (options.mixer) {
    vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-mixer.js'), 'utf8'), context);
  }
  if (options.axisBillboard) {
    vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-axis-billboard.js'), 'utf8'), context);
  }
  const fades = [], shadows = [];
  if (options.memberShadow) {
    // Stage-effect prefab sets and per-performer controllers, as MVStudioMemberShadow.
    window.MVStudioMemberShadow = {
      async prefabs(T, root) {
        if (!root.userData.shadowSet) return null;
        const set = { id: root.userData.id, disposed: false, dispose() { set.disposed = true; shadows.push(['dispose', set.id]); } };
        return set;
      },
      async apply() {
        let instanced = null;
        return { update(compatible, advancing, parameters, set) {
          if (set?.disposed) shadows.push(['drawn-disposed', set.id]);
          instanced = set;
        }, releasePrefabs(set) {
          if (instanced === set) { shadows.push(['release', set.id]); instanced = null; }
        }, dispose() {} };
      },
      sample: () => null,
    };
  }
  if (options.stageDisplay) window.MVStudioStageDisplay = options.stageDisplay;
  if (options.screenFade) {
    window.MVStudioScreenFade = { create: () => ({ draw(state) { fades.push(state); }, dispose() {} }),
      state: (time, end) => ({ time, end }) };
  }
  vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio-scene.js'), 'utf8'), context);
  const mount = { clientWidth: 1280, clientHeight: 720, appendChild() {} };
  const app = window.MVStudioScene.create(mount,
    { visible, onError(message) { throw new Error(message); }, onWarning: options.onWarning });
  return { app, frames, cameras, samples, models, holds, queued, fetched, parsing, renderer, mount, window, fades, shadows,
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

// LiveCoreCameraManager.Update3DCameraRenderTextures: RenderingResolution capped at the screen
// height (1080 when unset), raised to the screen height only when needAntiAliasing is set
// (the player's anti-aliasing option, default off, and a quality mode below 21).
async function checkNativeRenderHeight() {
  const f = fixture();
  const height = f.window.MVStudioScene.nativeRenderHeight;
  assert.equal(height(1080, 720, 10), 720, 'Max 3D on a 1280x720 screen draws 720 lines (game camera pixelRect)');
  assert.equal(height(640, 720, 40), 640, 'Performance 3D keeps its 640 lines (game 1138x640)');
  assert.equal(height(1080, 1440, 10), 1080, 'Max 3D draws RenderingResolution lines with anti-aliasing off (the default)');
  assert.equal(height(1080, 1440, 10, false), 1080);
  assert.equal(height(1080, 1440, 10, true), 1440, 'with anti-aliasing on, Max/High 3D never draw below the screen height');
  assert.equal(height(1080, 1440, 20, true), 1440);
  assert.equal(height(720, 1440, 30, true), 720, 'Normal 3D is not raised by anti-aliasing');
  assert.equal(height(640, 720, 40, true), 640, 'Performance 3D is not raised by anti-aliasing');
  assert.equal(height(1080, 720, 10, true), 720);
  assert.equal(height(0, 720, 40), 1080, 'an unset resolution draws 1080 lines');
  assert.equal(height(0, 1440, 10), 1080);
  assert.equal(height(0, 1440, 10, true), 1440);
  assert.equal(height(1080, 1440, 10, 1), 1080, 'only a boolean true turns anti-aliasing on');
  const value = project(73);
  value.quality = { mode: 10, values: { quality_mode: 10, rendering_resolution: 1080 } };
  await f.app.load(value);
  f.app.resize();
  assert.equal(f.app.inspect().antiAliasing, false, 'anti-aliasing is off by default');
  assert.equal(f.renderer.getPixelRatio(), 1, 'a 720-line view at Max 3D is not supersampled');
  f.window.devicePixelRatio = 2;
  f.app.resize();
  assert.equal(f.renderer.getPixelRatio(), 1.5, 'a 1440-device-line view draws 1080 lines with anti-aliasing off');
  f.app.setAntiAliasing(true);
  assert.equal(f.app.inspect().antiAliasing, true);
  assert.equal(f.renderer.getPixelRatio(), 2, 'with anti-aliasing on, a 1440-device-line view draws at its device pixels');
  f.app.setAntiAliasing(false);
  assert.equal(f.renderer.getPixelRatio(), 1.5, 'turning anti-aliasing off resizes back to 1080 lines');
  f.window.devicePixelRatio = 1;
  value.quality = { mode: 40, values: { quality_mode: 40, rendering_resolution: 640 } };
  f.app.seek(0, value);
  f.app.resize();
  assert.equal(Math.floor(720 * f.renderer.getPixelRatio()), 640, 'Performance 3D draws its exact 640 lines');
  f.app.setAntiAliasing(true);
  assert.equal(Math.floor(720 * f.renderer.getPixelRatio()), 640, 'Performance 3D keeps 640 lines with anti-aliasing on');
  f.app.dispose();
}

// The playback's slow-frame preview downscale, and the capture switch that turns it off without
// touching playback.
async function checkAdaptivePreview() {
  const f = fixture();
  const value = project(74);
  value.quality = { mode: 10, values: { quality_mode: 10, rendering_resolution: 1080 } };
  await f.app.load(value);
  f.app.resize();
  assert.equal(f.renderer.getPixelRatio(), 1);
  f.app.setPlaying(true);
  for (let step = 0; step <= 4; step++) f.app.playbackFrame(1 + step * .2, step * 205, true);
  assert.equal(f.app.inspect().previewScale, .75, 'four slow frames scale the playback buffer down');
  f.app.playbackFrame(2.2, 5 * 205, true);
  assert.equal(f.renderer.getPixelRatio(), .75);
  f.app.setAdaptivePreview(false);
  let state = f.app.inspect();
  assert.deepEqual([state.previewScale, state.adaptivePreview, state.playing], [1, false, true], 'playback keeps running');
  for (let step = 6; step <= 12; step++) f.app.playbackFrame(1 + step * .2, step * 205, true);
  assert.equal(f.app.inspect().previewScale, 1, 'slow frames no longer scale the buffer down');
  assert.equal(f.renderer.getPixelRatio(), 1, 'the next frame resizes back to the selected resolution');
  f.app.setAdaptivePreview(true);
  for (let step = 13; step <= 17; step++) f.app.playbackFrame(1 + step * .2, step * 205, true);
  assert.equal(f.app.inspect().previewScale, .75, 'the adaptive preview comes back');
  f.app.setPlaying(false);
  assert.equal(f.app.inspect().previewScale, 1);
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

// A stage effect's member-shadow prefab set is released with its record: the
// performers that stay drop their instances first and never draw the disposed set.
async function checkShadowPrefabRelease() {
  const userData = { 91: { mvMemberShadowDefaults: false, shadowSet: true }, 92: { mvMemberShadowDefaults: false, shadowSet: true } };
  const f = fixture(true, { memberShadow: true, userData });
  const value = project(90);
  value.assets = [{ kind: 'effect', previewUrl: address(91) }];
  await f.app.load(value);
  f.app.seek(1, value);
  const next = { ...project(90), assets: [{ kind: 'effect', previewUrl: address(92) }] };
  await f.app.load(next);
  f.app.seek(1, next);
  f.app.seek(2, next);
  const log = f.shadows.map((row) => row.join(':'));
  assert(log.includes('release:91') && log.indexOf('release:91') < log.indexOf('dispose:91'),
    `the performer drops the old instances before the templates go: ${log}`);
  assert(!log.some((row) => row.startsWith('drawn-disposed')), `a disposed set is never drawn: ${log}`);
  f.app.dispose();
}

// Original MV end: past the last camera clip the live camera holds that shot's
// final pose (StartBlur keeps the last 3D frame), and the end effect starts when
// the music ends, at soundtrack duration - offset in director time.
async function checkOriginalEndHold() {
  const f = fixture(true, { screenFade: true });
  const track = { kind: 'camera', nativeClass: 'AnimationTrack', binding: '/EntryPoint/Live/Cameras/MainCamera', events: [
    { id: 'c:0', start: 0, duration: 1, values: { keyframes: [
      { time: 0, position: [0,2,10], rotation: [0,0,0,1], fov: 34 }, { time: 1, position: [0,3,8], rotation: [0,0,0,1], fov: 23 }] } },
    { id: 'c:1', start: 2, duration: 1, values: { keyframes: [
      { time: 0, position: [1,2,4], rotation: [0,0,0,1], fov: 30 }, { time: 1, position: [2,2,4], rotation: [0,0,0,1], fov: 28 }] } }
  ] };
  const value = { source: { kind: 'game' }, duration: 6, soundtrack: { duration: 5, offset: .5 }, tracks: [track], performers: [] };
  await f.app.load(value);
  const shot = (time) => { f.app.seek(time, value); return f.cameras.at(-1); };
  assert.equal(shot(1.5).near, .02, 'a gap between clips is not the end: the editor view stays');
  const held = shot(4);
  assert.deepEqual([held.position, held.fov, held.near], [[-2,2,4], 28, .1], 'the last shot holds its final pose');
  assert.deepEqual(JSON.parse(JSON.stringify(f.app.inspect().cameraEvent)),
    { track: null, event: 'c:1', start: 2, duration: 1, held: true });
  assert.equal(f.app.inspect().liveShot, true);
  assert.deepEqual({ ...f.fades.at(-1) }, { time: 4, end: 4.5 }, 'the music ends at duration - offset');
  value.soundtrack.offset = undefined;
  shot(4);
  assert.deepEqual({ ...f.fades.at(-1) }, { time: 4, end: 5 });
  value.source = { kind: 'user' };
  assert.equal(shot(4).near, .02, 'only an original MV holds the last shot');
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

// member_rim_light only mutes the Member Rim Light tracks
// (LiveQualityOperator.ApplyLiveQualityToMemberEffectTrack); the member
// material keeps its rim term and the base light still lights it.
async function checkMemberRimQuality() {
  const f = fixture(true, { lighting: true }), value = project(56);
  value.quality = { values: { member_rim_light: false, base_light: true } };
  value.tracks.push({ nativeClass: 'LiveBaseLightTrack', binding: '/EntryPoint/Live/Global/LiveBaseLightReciever', events: [
    { start: 0, duration: 10, values: { playableClass: 'LiveBaseLightClip', ambientColorType: 0, ambientMemberPosition: 1,
      ambientColor: [1, 1, 1, 1], ambientTintColor: [1, 1, 1, 1], rimlightColorType: 0, rimlightColor: [1, 1, 1, 1],
      rimlightIntensity: .4, rimlightSharpness: 2, rimlightDirection: { x: 0, y: 1, z: 0 } } }] },
  { nativeClass: 'LiveRimlightTrack', binding: '/EntryPoint/Live/Members/Member1', events: [
    { start: 0, duration: 10, values: { playableClass: 'LiveRimlightClip', colorSpecifiedType: 0, color: [1, 1, 1, 1],
      intensity: .3, sharpness: 1, direction: { x: 0, y: 0, z: 0 } } }] });
  await f.app.load(value);
  f.app.seek(1, value);
  const info = f.models.get(56);
  assert.deepEqual(info.rimlight || [], [], 'the quality never switches the member rim term off');
  assert.equal(info.liveLighting.rim.intensity, .4, 'only the base light rim reaches the material');
  value.quality.values.member_rim_light = true;
  f.app.seek(1, value);
  assert(Math.abs(info.liveLighting.rim.intensity - .7) < 1e-9, 'with the quality on the rim track adds to the base');
  assert.deepEqual(info.rimlight || [], []);
  f.app.dispose();
}

// LiveRimlightMixer.PostProcess applies colour, sharpness and direction only in a frame a clip ran,
// otherwise only ApplyIntensity(0): between clips the rim keeps the last written values (intensity 0),
// from the previous playing frame or, after a seek, from the frame history; before any write, and on a
// plain seek, SifasMaterial's live default (LiveCoreMemberRimlight.ResetAll) stays.
async function checkMemberRimHold() {
  const f = fixture(true, { lighting: true }), value = project(59);
  value.quality = { values: { member_rim_light: true, base_light: true } };
  const clip = (start, sharpness, x) => ({ start, duration: 1, values: { playableClass: 'LiveRimlightClip', colorSpecifiedType: 0,
    color: [.5, .25, 1, 1], intensity: .6, sharpness, direction: { x, y: 1, z: 0 } } });
  value.tracks.push({ nativeClass: 'LiveRimlightTrack', binding: '/EntryPoint/Live/Members/Member1', events: [clip(0, 4, 2), clip(2, 9, -3)] });
  await f.app.load(value);
  const info = f.models.get(59);
  // The scene runs in the fixture's own realm: compare plain copies.
  const rim = () => JSON.parse(JSON.stringify(info.liveLighting?.rim ?? null));
  f.app.seek(.5, value, true);
  assert.deepEqual(rim(), { color: [.5, .25, 1, 1], intensity: .6, power: 5, direction: [2, 1, 0, 0] }, 'a clip writes everything');
  f.app.seek(1.5, value, true);
  assert.deepEqual(rim(), { intensity: 0 }, 'a plain seek between clips has no earlier frame to hold');
  f.app.seek(1.5, value, true, [.3, .9, 1.2]);
  assert.deepEqual(rim(), { color: [.5, .25, 1, 1], direction: [2, 1, 0, 0], power: 5, intensity: 0 },
    'after a seek with the frame history the last frame a clip ran holds colour, power and direction');
  f.app.seek(1.6, value, true, [1.1, 1.2]);
  assert.deepEqual(rim(), { intensity: 0 }, 'a history without a written frame holds nothing');
  f.app.seek(2.5, value, true);
  f.app.setPlaying(true);
  f.app.playbackFrame(3.2, 100, true);
  assert.deepEqual(rim(), { color: [.5, .25, 1, 1], direction: [-3, 1, 0, 0], power: 10, intensity: 0 }, 'a playing frame holds the previous one');
  f.app.playbackFrame(3.4, 200, true);
  assert.deepEqual(rim().direction, [-3, 1, 0, 0], 'and keeps holding it');
  f.app.setPlaying(false);
  f.app.dispose();
}

// The scene runs the Live* mixers' input walk (LiveMixerBase`2.ProcessWithoutSeek) on its frame
// clock: a seek replays the history it is handed, playback frames continue it, and a seek without
// history processes every input (ProcessWithSeek). MVStudioLighting.nativeWeight reads the walk.
async function checkMixerWalk() {
  const f = fixture(true, { lighting: true, mixer: true }), value = project(59);
  const clip = (start, duration, values = {}) => ({ start, duration, values: { playableClass: 'LiveColoringClip', ...values } });
  const late = clip(47.233, .7, { blendIn: .15 });
  value.tracks.push({ nativeClass: 'LiveColoringTrack', label: 'StageEffect/Expert/Coloring/LED_panel_03', binding: '/x',
    events: [clip(42.6, 2.533), clip(46.467, .566, { blendOut: .25 }), clip(46.783, .384, { blendIn: .25 }),
      clip(47.167, .216, { blendOut: .15 }), late] });
  const history = [];
  for (let time = 47.138; time > 42; time -= .19) history.unshift(Math.round(time * 1e4) / 1e4);
  await f.app.load(value);
  const { MVStudioLighting: lighting } = f.window;
  f.app.seek(47.328, value, true);
  assert(lighting.nativeWeight(late, 47.328) > .6, 'a seek without history processes every input');
  f.app.seek(47.328, value, true, history);
  assert.equal(lighting.nativeWeight(late, 47.328), 0, 'the game frames leave the 47.233 s clip out at 47.328 s');
  f.app.setPlaying(true);
  f.app.playbackFrame(47.518, 100, true);
  assert(lighting.nativeWeight(late, 47.518) > .9, 'the next playback frame takes it');
  f.app.setPlaying(false);
  f.app.dispose();
  assert(lighting.nativeWeight(late, 47.328) > .6, 'a disposed scene leaves no walk behind');
}

// A member prop's ambient mixer writes its LiveCoreMemberAmbient every frame, shown or not: the
// CheckSame hold steps on hidden frames too, and the material takes the held color while shown.
async function checkMemberPropHold() {
  const f = fixture(true, { lighting: true }), value = project(57);
  value.assets = [{ kind: 'props', previewUrl: address(58), attachment: { member: 1, binding: '/EntryPoint/Live/Props/Prop1' } }];
  const shown = [];
  f.window.MVStudioProps = { create(root) {
    return { bind() {}, setTracks() {}, detach() {}, evaluate(time) { root.visible = !(time > 2.05 && time < 2.85); } };
  } };
  // alpha(t) = .2 + .01 t: 0.001 per 0.1 s frame, below the sqrt(1e-5) write threshold until four frames add up.
  f.window.MVStudioPropLight = { create() {
    return { setProject() {}, sample: (time) => ({ ambient: [0, 0, 0, .2 + .01 * time], tint: [1, 1, 1, 1] }) };
  } };
  await f.app.load(value);
  f.app.seek(1, value, true);
  f.app.setPlaying(true);
  const info = f.models.get(58);
  for (let step = 1; step <= 19; step++) {
    const time = 1 + step / 10;
    f.app.playbackFrame(time, step * 100, true);
    shown.push([Math.round(time * 10) / 10, Math.round(info.liveLighting.ambient[3] * 1e6) / 1e6]);
  }
  // Written at 1.4, 1.8, 2.2 (hidden) and 2.6 (hidden); 2.9 is within the threshold of the 2.6 write.
  assert.deepEqual(shown.find(([time]) => time === 2.9), [2.9, .226]);
  assert.deepEqual(shown.find(([time]) => time === 2), [2, .218], 'the last color the material took before it was hidden');
  assert.deepEqual(shown.find(([time]) => time === 2.5), [2.5, .218], 'a hidden prop keeps its material as it was');
  f.app.setPlaying(false);
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
  assert.deepEqual(first.globals['global:_RenderTextureResolution'],
    { f: 0, from: 'renderer.getDrawingBufferSize', v: [720, 720, 0, 0] }, 'the render-target size in pixels');
  assert.equal(first.renderers.length, 1);
  assert.equal(first.renderers[0].key, 'renderer:member1:model-71');
  assert.equal(first.renderers[0].visible, true);
  assert.equal(first.renderers[0].culled, false);
  assert.equal(first.renderers[0].path, null, 'a rig-root mesh node carries no GameObject chain');
  assert.equal(first.renderers[0].pathSource, 'flattened');
  assert.deepEqual(first.materials.map((m) => m.key), ['material:renderer:member1:model-71#0']);
  assert.deepEqual([first.renderers[0].materialVisible, first.materials[0].visible, first.materials[0].hiddenUniforms],
    [true, true, undefined]);
  // A hidden material draws nothing: its uniforms are current unless its module marks them stale.
  const shown = f.models.get(71).mesh.material;
  shown.visible = false;
  let hidden = dump({ sections: ['renderers', 'materials'] });
  assert.deepEqual([hidden.renderers[0].visible, hidden.renderers[0].materialVisible], [true, false]);
  assert.deepEqual([hidden.materials[0].visible, hidden.materials[0].hiddenUniforms], [false, 'current']);
  shown.userData.mvHiddenUniforms = 'stale';
  hidden = dump({ sections: ['materials'] });
  assert.equal(hidden.materials[0].hiddenUniforms, 'stale');
  shown.visible = true;
  delete shown.userData.mvHiddenUniforms;
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

// AxisBillboard turns its nodes only when the scene draws; a deferred seek's stage
// node dump reports the turn the live camera's draw gives (as renderers do).
async function checkAssetDumpStageBillboard() {
  const binding = '/EntryPoint/Live/Stages/MainStage/Effect/lit_01/litB_All';
  let cone = null;
  const f = fixture(true, { axisBillboard: true, build(root, id) {
    if (id !== 82) return;
    const zrot = new THREE.Object3D();
    zrot.userData.mvStageNode = { binding, path: 11 };
    zrot.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), 2.03);
    zrot.position.set(-14.4, 10.2, -2.8);
    cone = new THREE.Object3D();
    cone.userData.mvStageNode = { binding, path: 12 };
    cone.userData.mvAxisBillboard = 1;
    zrot.add(cone);
    root.add(zrot);
  } });
  const value = project(81);
  value.duration = 12;
  value.stage = { glb: address(82) };
  value.tracks = [{ id: 'cam', label: 'Camera/MainCamera', kind: 'camera', nativeClass: 'AnimationTrack',
    binding: '/EntryPoint/Live/Cameras/MainCamera', events: [{ id: 'cam:0', start: 0, duration: 10, values: { keyframes: [
      { time: 0, position: [1, 2, 10], rotation: [0, 0, 0, 1], fov: 30 },
      { time: 10, position: [5, 3, 0], rotation: [0, 0, 0, 1], fov: 30 }] } }] }];
  await f.app.load(value);
  const node = () => JSON.parse(JSON.stringify(f.app.assetDump({ sections: ['stageNodes'] }))).stageNodes
    .find((entry) => entry.crc === 12);
  f.app.seek(4, value, true);
  const deferred = node();
  f.app.seek(4, value);
  const drawn = node();
  deferred.rotation.forEach((component, index) => assert(Math.abs(component - drawn.rotation[index]) < 1e-6,
    `deferred stage node rotation ${deferred.rotation} matches the drawn turn ${drawn.rotation}`));
  assert(Math.abs(Math.abs(new THREE.Quaternion(...drawn.rotation).dot(cone.parent.quaternion)) - 1) > 1e-3,
    'the billboard turned the cone away from its parent');
  f.app.seek(8, value, true);
  const later = node();
  f.app.seek(8, value);
  later.rotation.forEach((component, index) => assert(Math.abs(component - node().rotation[index]) < 1e-6,
    'a later deferred seek follows the moved live camera'));
  f.app.dispose();
}

// A stage node dump says whether the live camera draws each AxisBillboard
// (axisBillboardDrawn): shown, with a renderer, and its AxisBillboard.Start
// bounds (x/z widened to max(sx, sz)) under the reported turn in the frustum.
async function checkAssetDumpStageBillboardDrawn() {
  const binding = '/EntryPoint/Live/Stages/MainStage/Effect/lit_01/litB_All';
  const holders = {}, cones = {};
  const f = fixture(true, { axisBillboard: true, build(root, id) {
    if (id !== 82) return;
    const add = (name, path, size, mesh = true) => {
      const holder = new THREE.Object3D();
      holder.userData.mvStageNode = { binding, path };
      const cone = mesh ? new THREE.Mesh(new THREE.BoxGeometry(...size), new THREE.MeshBasicMaterial()) : new THREE.Object3D();
      cone.userData.mvStageNode = { binding, path: path + 1 };
      cone.userData.mvAxisBillboard = 1;
      holder.add(cone);
      root.add(holder);
      (holders[name] ||= []).push(holder);   // every parse of the stage model
      (cones[name] ||= []).push(cone);
    };
    add('front', 20, [0.4, 2, 0.4]);
    add('behind', 30, [0.4, 2, 0.4]);
    add('hidden', 40, [0.4, 2, 0.4]);
    add('bare', 50, null, false);
    add('edge', 60, [6, 2, 0.01]);
    // Deep rather than wide (sz > sx): only max(sx, sz) widens x past the 1 cm the cone has.
    add('deep', 90, [0.01, 2, 6]);
    // A 12035 cone: the AxisBillboard node is a group whose renderer is a child mesh node of the same name.
    add('group', 70, null, false);
    const part = new THREE.Mesh(new THREE.BoxGeometry(.4, 2, .4), new THREE.MeshBasicMaterial());
    part.name = 'cone_1';
    part.userData.name = cones.group.at(-1).userData.name = 'cone';
    cones.group.at(-1).add(part);
    // A differently named child is another GameObject's renderer, not the billboard's.
    add('other', 80, null, false);
    const other = new THREE.Mesh(new THREE.BoxGeometry(.4, 2, .4), new THREE.MeshBasicMaterial());
    other.userData.name = 'lens';
    cones.other.at(-1).userData.name = 'cone';
    cones.other.at(-1).add(other);
    const child = new THREE.Object3D();
    child.userData.mvStageNode = { binding, path: 22 };
    cones.front.at(-1).add(child);
  } });
  const value = project(81);
  value.duration = 12;
  value.stage = { glb: address(82) };
  value.tracks = [{ id: 'cam', label: 'Camera/MainCamera', kind: 'camera', nativeClass: 'AnimationTrack',
    binding: '/EntryPoint/Live/Cameras/MainCamera', events: [{ id: 'cam:0', start: 0, duration: 10, values: { keyframes: [
      { time: 0, position: [1, 2, 10], rotation: [0, 0, 0, 1], fov: 30 },
      { time: 10, position: [5, 3, 0], rotation: [0, 0, 0, 1], fov: 30 }] } }] }];
  await f.app.load(value);
  f.app.seek(4, value, true);
  const camera = f.app.assetDump({ sections: ['cameras'] }).cameras.find((entry) => entry.key === 'camera:main');
  const toWorld = new THREE.Matrix4().fromArray(camera.worldToCamera).invert();
  // Camera space looks down -z; the frustum's half width at depth 10 is 10 tan(fov/2) aspect.
  const halfWidth = 10 * Math.tan(camera.fieldOfView * Math.PI / 360) * camera.aspect;
  const at = (name, x, z) => holders[name].forEach((holder) => holder.position.copy(new THREE.Vector3(x, 0, z).applyMatrix4(toWorld)));
  at('front', 0, -10);
  at('behind', 0, 10);
  at('hidden', 0, -10);
  at('bare', 0, -10);
  at('group', 0, -10);
  at('other', 0, -10);
  // A 6 m wide, flat cone turned toward the camera from twice the half width: its own bounds stay outside the
  // right plane, the widened (6 x 2 x 6) bounds reach into the view.
  at('edge', 2 * halfWidth, -10);
  // A 6 m deep, 1 cm wide cone at the same place: its own bounds (and x/z widened to sx) stay outside, the
  // widened (6 x 2 x 6) bounds reach into the view.
  at('deep', 2 * halfWidth, -10);
  cones.hidden.forEach((cone) => { cone.visible = false; });
  for (const holder of Object.values(holders).flat()) {
    holder.updateMatrix();   // the stage keeps matrixAutoUpdate off on its nodes
    holder.parent.updateMatrixWorld(true);
  }
  const nodes = new Map(JSON.parse(JSON.stringify(f.app.assetDump({ sections: ['stageNodes'] }))).stageNodes
    .map((entry) => [entry.crc, entry]));
  const drawn = (crc) => nodes.get(crc)?.axisBillboardDrawn;
  assert.equal(drawn(21), true, 'a cone in front of the live camera is drawn');
  assert.equal(drawn(22), true, 'a node below a drawn billboard reports its billboard');
  assert.equal(drawn(31), false, 'a cone behind the camera is not drawn');
  assert.equal(drawn(41), undefined, 'a hidden cone is not turned (MVStudioAxisBillboard skips it), so it reports nothing');
  assert.equal(drawn(51), false, 'a billboard without a renderer is never drawn');
  assert.equal(drawn(61), true, 'AxisBillboard.Start widens x/z to max(sx, sz)');
  assert.equal(drawn(91), true, 'AxisBillboard.Start widens x/z to max(sx, sz) when sz is the larger side');
  assert.equal(drawn(71), true, 'the renderer on a child mesh node of the same name');
  assert.equal(drawn(81), false, "another GameObject's renderer below the billboard");
  assert.equal(nodes.get(20).axisBillboard, undefined, 'the parent is not a billboard');
  assert.equal(drawn(20), undefined);
  f.app.dispose();
}

// The particle culling view (Automatic / Pause culling) counts every camera that
// draws the frame: inside a LiveSplitScreenClip the enabled sub cameras, plus the
// main camera when the clip keeps it on. Its key follows the split data and the
// split_screen quality, so the visibility pass restarts when either changes.
async function checkParticleCullingSplitCameras() {
  const updates = [];
  const f = fixture(true);
  f.window.MVStudioParticleSystems = { async apply() {
    return { update(time, _project, view) { updates.push({ time, view }); }, dispose() {} };
  } };
  const effect = '/EntryPoint/Live/Cameras/SplitScreenEffect';
  const pointer = { m_FileID: 0, m_PathID: '-42' };
  const mask = { positions: [1,-1,.01, -1,-1,.01, -1,1,.01, 1,1,.01], indices: [0,1,2,0,2,3], uv: [1,0,0,0,0,1,1,1], bounds: [2,1] };
  const clip = { id: 'split:0', start: 4, duration: 2, values: { playableClass: 'LiveSplitScreenClip', mainCamera: 0, subCamera1: 1,
    mask1: pointer } };
  const value = project(81);
  value.duration = 12;
  value.stage = { glb: address(82) };
  value.quality = { values: { split_screen: true } };
  value.splitScreen = { masks: { mask }, events: { 'split:0': [{ key: 'mask', pointer }, null, null, null] } };
  value.tracks = [{ id: 'cam', label: 'Camera/MainCamera', kind: 'camera', nativeClass: 'AnimationTrack',
    binding: '/EntryPoint/Live/Cameras/MainCamera', events: [{ id: 'cam:0', start: 0, duration: 10, values: { keyframes: [
      { time: 0, position: [1, 2, 10], rotation: [0, 0, 0, 1], fov: 30 }] } }] },
  { id: 'split', kind: 'other', nativeClass: 'LiveSplitScreenTrack', binding: effect, events: [clip] },
  { id: 'sub1', label: 'SubCamera1', kind: 'camera', nativeClass: 'AnimationTrack', binding: `${effect}/Cameras/SubCamera1`,
    events: [{ id: 'sub1:0', start: 0, duration: 10, values: { keyframes: [{ time: 0, position: [7, 1, -3], rotation: [0, 0, 0, 1], fov: 40 }] } }] }];
  await f.app.load(value);
  const viewAt = (time, next = value) => {
    f.app.seek(time, next, true);
    const { view } = updates.at(-1);
    assert.equal(updates.at(-1).time, time);
    return view;
  };
  const outside = viewAt(2);
  const main = outside.camerasAt(2);
  assert.equal(main.length, 1, 'outside the split clip only the main camera draws');
  const inside = viewAt(5);
  assert.equal(inside.key, outside.key, 'the same project keeps the visibility pass');
  const subs = inside.camerasAt(5);
  assert.equal(subs.length, 1, 'mainCamera 0: only the sub camera draws');
  assert.notEqual(subs[0], main[0]);
  assert.equal(subs[0].aspect, 2, 'the sub camera takes its mask aspect');
  assert.deepEqual([subs[0].near, subs[0].far], [.1, 1000]);
  clip.values.mainCamera = 1;
  assert.equal(inside.camerasAt(5).length, 2, 'mainCamera 1: the sub camera and the main camera');
  clip.values.mainCamera = 0;
  // New split data or the split_screen quality restart the pass (a new key).
  const moved = viewAt(5, { ...value, splitScreen: { ...value.splitScreen } });
  assert.notEqual(moved.key, inside.key, 'new split data gives a new key');
  const off = viewAt(5, { ...value, splitScreen: moved.split, quality: { values: { split_screen: false } } });
  assert.notEqual(off.key, moved.key, 'the split_screen quality gives a new key');
  assert.equal(off.camerasAt(5).length, 1, 'split screen off: the main camera only');
  assert.notEqual(off.camerasAt(5)[0], subs[0]);
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
    textureIdentity: (...args) => JSON.parse(JSON.stringify(helpers.textureIdentity(...args))),
    materialProperties: (...args) => JSON.parse(JSON.stringify(helpers.materialProperties(...args))) };
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
  assert.deepEqual(D.textureIdentity(constant), { name: null, width: 1, height: 1, mips: 1, placeholder: true });
  const real = new THREE.DataTexture(new Uint8Array(16), 2, 2);
  real.name = 'atlas';
  assert.deepEqual(D.textureIdentity(real), { name: 'atlas', width: 2, height: 2, mips: 1 });
  real.mipmaps = [{ width: 2, height: 2 }, { width: 1, height: 1 }];
  real.userData = { sifasArrayLayer: 1 };
  assert.deepEqual(D.textureIdentity(real), { name: 'atlas', width: 2, height: 2, mips: 2, arrayLayer: 1 },
    'authored mip levels and the array slice are part of the identity');
  // An image texture with no uploaded levels gets its chain from the GPU.
  const gpu = new THREE.Texture({ width: 128, height: 64 });
  gpu.name = 'rim';
  assert.deepEqual(D.textureIdentity(gpu), { name: 'rim', width: 128, height: 64, mips: 8, mipsGenerated: true },
    'a GPU-generated chain is reported as generated, not as authored mips');
  gpu.minFilter = THREE.LinearFilter;
  assert.deepEqual(D.textureIdentity(gpu), { name: 'rim', width: 128, height: 64, mips: 1 }, 'a non-mip filter samples one level');
  gpu.minFilter = THREE.LinearMipmapLinearFilter;
  gpu.mipmaps = [{ width: 128, height: 64 }, { width: 64, height: 32 }, { width: 32, height: 16 }];
  assert.deepEqual(D.textureIdentity(gpu), { name: 'rim', width: 128, height: 64, mips: 3 }, 'uploaded levels are authored');
  // AS/Member: effective keywords (authored, with variant keywords as drawn),
  // the rim evaluation and the outline stencil comparison.
  const member = new THREE.ShaderMaterial({ uniforms: { uRimglightIntensity: { value: .5 }, uOutlineScale: { value: 1 } },
    defines: { SIFAS_RIMLIGHT: 1, SIFAS_CHEEK: 1 } });
  member.userData.sifas = { keywords: ['_RIMLIGHT_ON', '_MATCAP_ON'] };
  member.userData.sifasRuntime = { outlineStencilComp: 3 };
  const read = D.materialProperties(member);
  assert.deepEqual([read.kind, read.keywords, read.rimlightEvaluated], ['member', ['_CHEEK_ON', '_RIMLIGHT_ON'], true],
    'the drawn variant replaces the authored _MATCAP_ON; the legacy _RIMLIGHT_ON stays as authored');
  assert.deepEqual(read.properties._OutlineStencilComp, { t: 'float', v: 3, from: 'outline stencilFunc' });
  assert.deepEqual(read.properties._RimglightIntensity, { t: 'float', v: .5, from: 'uRimglightIntensity' });
}

// After a load the programs and textures of every material are prepared (renderer.compile and
// initTexture), hidden ones included. That is only an optimisation: when it fails the load still
// completes and draws, and the preview lists a warning.
async function checkWarmScene() {
  const warnings = [], compiled = [], uploaded = [];
  const texture = new THREE.Texture({ width: 4, height: 4, complete: true });
  texture.needsUpdate = true;
  const build = (root) => {
    const hidden = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ map: texture }));
    hidden.visible = false;
    root.add(hidden);
  };
  const f = fixture(true, { build, onWarning: (message) => warnings.push(message) });
  f.renderer.compile = (scene, camera) => compiled.push([scene.isScene, camera.isCamera]);
  f.renderer.initTexture = (value) => uploaded.push(value);
  await f.app.load(project(76));
  assert.deepEqual(compiled, [[true, true]], 'one compile of the scene after the load');
  assert.deepEqual(uploaded, [texture], 'the texture of a hidden material is uploaded');
  assert.deepEqual(warnings, []);
  f.app.dispose();

  const failing = fixture(true, { onWarning: (message) => warnings.push(message) });
  let attempts = 0;
  failing.renderer.compile = () => { attempts++; throw new Error('program link failed'); };
  await failing.app.load(project(77));
  assert.equal(attempts, 1);
  assert.deepEqual(warnings, ['The 3D preview could not prepare its materials before playback. They are prepared when first shown.']);
  const drawn = failing.frames.length;
  failing.app.seek(1, project(77));
  assert.equal(failing.frames.length, drawn + 1, 'the loaded scene still draws');
  assert.deepEqual(failing.frames.at(-1), ['model-77', 'outline-77']);
  failing.app.dispose();

  // A stage display creates every variant's program at load; the ones its screen does not show
  // yet join this compile on hidden stand-ins of the screen (same geometry), removed afterwards.
  const screens = [], seen = [], updates = [];
  const later = [new THREE.ShaderMaterial(), new THREE.ShaderMaterial()];
  const stageDisplay = { async apply(T, root) {
    const node = root.children.find((child) => child.isMesh);
    const shown = node.material;
    screens.push(node);
    return { programs: () => [shown, ...later].map((material) => ({ node, material })),
      update(...values) { updates.push(values); }, invalidate() {}, dispose() {} };
  } };
  const display = fixture(true, { stageDisplay });
  display.renderer.compile = (scene) => scene.traverse((node) => {
    if (node.material) seen.push([node.material, node.visible, node.geometry === screens[0].geometry]);
  });
  await display.app.load({ ...project(78), stage: { glb: address(79) } });
  assert.equal(screens.length, 1);
  assert.deepEqual(seen.filter(([material]) => later.includes(material)),
    later.map((material) => [material, false, true]), 'each later program on a hidden stand-in of its screen');
  assert.equal(seen.filter(([material]) => material === screens[0].material).length, 1, 'the shown one only on the screen');
  assert.equal(screens[0].children.filter((child) => later.includes(child.material)).length, 0, 'stand-ins removed');
  // The wave screens read _Time.y: the display gets the scene's game clock with the director time.
  display.window.MVStudioParticleSystems = { gameClock: (samples) => Object.assign((time) => time + .42, { samples: samples.length }) };
  assert.equal(display.app.setGameClock([[0, .42]]), 1);
  display.app.seek(2, { ...project(78), stage: { glb: address(79) } });
  const [time, , clock] = updates.at(-1);
  assert.equal(time, 2);
  assert.equal(clock?.(2), 2.42, 'the game clock reaches the stage display');
  display.app.dispose();
}

(async () => {
  checkResizeDraws();
  await checkWarmScene();
  await checkNativeRenderHeight();
  await checkAdaptivePreview();
  await checkAssetDump();
  await checkAssetDumpStageBillboard();
  await checkAssetDumpStageBillboardDrawn();
  await checkParticleCullingSplitCameras();
  await checkAssetDumpCuller();
  checkAssetDumpHelpers();
  await checkNativeCamera();
  await checkSavedNodeScaling();
  await checkNativeMemberCulling();
  await checkMemberRimQuality();
  await checkMemberRimHold();
  await checkMemberPropHold();
  await checkMixerWalk();
  await checkOriginalEndHold();
  await checkShadowPrefabRelease();
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
