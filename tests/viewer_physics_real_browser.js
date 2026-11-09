/* Enhanced clipping-correction regression on real costumes and original clips.
 * PHYSICS_MODE=game observes the native mode without imposing enhanced surface
 * clearance or timestep invariance. Native numerical parity has separate tests.
 * The scene observer never changes mesh, animation, physics or API responses. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), os = require('os'), net = require('net');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const crypto = require('crypto');
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'physics-real-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'physics-real-library-')), sources = path.join(library, 'extracted/3d_model');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(sources, { recursive: true });
const bodyFile = process.env.PHYSICS_MODEL || '/workspace/scratch/game-motion-real/ayumu-body.unity';
const animationFile = process.env.PHYSICS_MOTION || '/workspace/scratch/game-motion-real/import-cache/motion-c77f23d6-khpvs7mr/animation-1.unity';
const physicsMode = process.env.PHYSICS_MODE || 'enhanced';
assert(['enhanced', 'game'].includes(physicsMode), 'PHYSICS_MODE must be enhanced or game');
const physicsProfile = process.env.PHYSICS_PROFILE || (physicsMode === 'game' ? 'live' : null);
if (physicsProfile) assert(['auto', 'live', 'navi'].includes(physicsProfile), 'PHYSICS_PROFILE must be auto, live or navi');
const body = path.join(sources, 'body.unity'), animation = path.join(sources, 'animation.unity'); fs.copyFileSync(bodyFile, body); fs.copyFileSync(animationFile, animation);
const originalBodyHash = sha(fs.readFileSync(body)), originalMotionHash = sha(fs.readFileSync(animation));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] }); child.stdout.pipe(log); child.stderr.pipe(log);
  const url = 'http://127.0.0.1:' + port; for (let i = 0; i < 200; i++) { if (child.exitCode !== null) throw Error('Product exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) {} await wait(100); } throw Error('Product startup timed out');
}
async function snapshot(page, time, mode) {
  return page.evaluate(({ time, mode, physicsMode }) => {
    const state = ModelViewer.getState().rig.physics, catalog = ModelViewer.getEditingMetadata().physics;
    const skirtNodes = new Set(catalog.components.filter(c => c.kind === 'bone' && /skirt/i.test(c.name)).map(c => String(c.node)));
    const triangles = [], triangleIds = [], seenGeometry = new Set(), meshFrames = [], nodeFrames = {};
    window.__physicsReadOnlyScene.traverse(node => { if (node.userData && node.userData.elichika_node !== undefined) nodeFrames[String(node.userData.elichika_node)] = { name: node.userData.originalName || node.name, world: node.matrixWorld.toArray(), parentWorld: node.parent ? node.parent.matrixWorld.toArray() : null, parent: node.parent && node.parent.userData.elichika_node, position: node.position.toArray(), quaternion: node.quaternion.toArray(), scale: node.scale.toArray() }; });
    function skirtBone(bone) { for (let node = bone; node; node = node.parent) if (skirtNodes.has(String(node.userData && node.userData.elichika_node))) return true; return false; }
    window.__physicsReadOnlyScene.updateMatrixWorld(true);
    window.__physicsReadOnlyScene.traverse(mesh => {
      if (!mesh.isSkinnedMesh || mesh.userData.viewerHelper || !mesh.geometry || seenGeometry.has(mesh.uuid)) return;
      seenGeometry.add(mesh.uuid); const geometry = mesh.geometry, skin = geometry.attributes.skinIndex, weights = geometry.attributes.skinWeight, index = geometry.index;
      if (!skin || !weights || !index) return;
      const influences = mesh.skeleton.bones.map(skirtBone), values = [], mask = [];
      for (let v = 0; v < geometry.attributes.position.count; v++) {
        let sum = 0; for (const axis of ['X', 'Y', 'Z', 'W']) if (influences[skin['get' + axis](v)]) sum += weights['get' + axis](v);
        mask[v] = sum; values[v] = null;
      }
      function vertex(id) { return values[id] || (values[id] = ViewerMeshRuntime.vertexWorld(mesh, id).toArray()); }
      const mapping = geometry.userData.viewerMesh || mesh.userData.viewerMesh || {}, frame = { identity: mapping.mesh || mesh.name, bind: mesh.bindMatrix.toArray(), bindInverse: mesh.bindMatrixInverse.toArray(), world: mesh.matrixWorld.toArray(), bones: mesh.skeleton.bones.map((bone, index) => ({ node: bone.userData.elichika_node, world: bone.matrixWorld.toArray(), inverse: mesh.skeleton.boneInverses[index].toArray() })), vertices: {} };
      for (let face = 0; face < index.count / 3; face++) {
        const ids = [index.getX(face * 3), index.getX(face * 3 + 1), index.getX(face * 3 + 2)];
        if (!ids.some(id => mask[id] >= .5)) continue;
        triangles.push(ids.map(vertex)); triangleIds.push({ mesh: mapping.mesh || mesh.name, submesh: mapping.submesh || 0, face: (mapping.firstFace || 0) + face, vertices: ids, swingWeights: ids.map(id => mask[id]) }); ids.forEach(id => { if (!frame.vertices[id]) frame.vertices[id] = { local: ViewerMeshRuntime.vertexLocal(mesh, id).toArray(), indices: ['X','Y','Z','W'].map(axis => skin['get' + axis](id)), weights: ['X','Y','Z','W'].map(axis => weights['get' + axis](id)) }; });
      }
      if (Object.keys(frame.vertices).length) meshFrames.push(frame);
    });
    return { nodeFrames, meshFrames, catalog, name: 'original-model', time, mode, physicsMode, previewSettings: { mode: state.mode, frameRate: state.frameRate, profile: state.profile, qualityMode: state.qualityMode, runtime: state.runtime }, components: catalog.components.map(c => ({ id: c.id, name: c.name, kind: c.kind })), solver: state.solver, triangles, triangleIds };
  }, { time, mode, physicsMode });
}
async function main() {
  let server, browser; const snapshots = [], report = { status: 'RUNNING', evidence, source: bodyFile, motion: animationFile, physicsMode,
    validationScope: physicsMode === 'enhanced' ? 'Enhanced surface-clearance regression; not native-fidelity proof' : 'Original-mode browser observation; native numerical parity is checked by separate ARM64 fixtures' };
  try {
    server = await start(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } }); page.setDefaultTimeout(120000); const errors = []; page.on('pageerror', e => errors.push(String(e)));
    await page.route('**/static/viewer-quality.js', async route => {
      const response = await route.fetch(), source = await response.text();
      await route.fulfill({ response, body: source + '\n(()=>{const original=ViewerQuality.create;ViewerQuality.create=function(){const controller=original.apply(this,arguments),render=controller.render;controller.render=function(scene,camera){window.__physicsReadOnlyScene=scene;return render.apply(this,arguments)};return controller};})();' });
    });
    await page.route('**/static/viewer-physics.js', async route => {
      const response = await route.fetch(), original = await response.text();
      await route.fulfill({ response, body: original + '\n(()=>{const create=ViewerPhysics.create;window.__physicsFrameSamples=[];ViewerPhysics.create=function(){const controller=create.apply(this,arguments),apply=controller.apply;let previous;controller.apply=function(delta){const start=performance.now(),interval=previous===undefined?null:start-previous;previous=start;try{return apply.apply(this,arguments)}finally{const elapsed=performance.now()-start;if(window.__physicsPerfEnabled&&delta>0){const timing=controller.getTimingState();window.__physicsFrameSamples.push(Object.assign({ms:elapsed,delta,intervalMs:interval,showColliders:!!document.getElementById("viewer-physics-show-colliders").checked},timing))}}};return controller};})();' });
    });
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(paths => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer(paths); }, [body, animation]);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().rig.physics.solver);
    await page.locator('#viewer-adjustments').evaluate(e => { e.open = true; }); await page.locator('.viewer-physics-region').evaluateAll(es => es.forEach(e => { e.open = true; }));
    await page.locator('#viewer-physics-mode').selectOption(physicsMode);
    assert.equal(await page.evaluate(() => ModelViewer.getState().rig.physics.mode), physicsMode, 'The requested physics engine is explicitly selected');
    if (physicsProfile) await page.locator('#viewer-physics-profile').selectOption(physicsProfile);
    for (const [key, id] of [['PHYSICS_SKIRT_CORRECTION', 'viewer-physics-skirt-correction'], ['PHYSICS_MOTION_CORRECTION', 'viewer-physics-motion-correction']]) if (process.env[key]) {
      assert(['auto', 'enabled', 'disabled'].includes(process.env[key]), key + ' must be auto, enabled or disabled');
      await page.locator('#' + id).selectOption(process.env[key]);
    }
    report.previewSettings = await page.evaluate(() => { const p=ModelViewer.getState().rig.physics; return {mode:p.mode,frameRate:p.frameRate,profile:p.profile,qualityMode:p.qualityMode,skirtCorrection:p.skirtCorrection,motionCorrection:p.motionCorrection,runtime:p.runtime}; });
    const motion = await page.locator('#viewer-motion option').evaluateAll(options => options.filter(o => o.value).find(o => /so2002|dance|2002/i.test(o.textContent + o.value))?.value || options.filter(o => o.value)[0].value);
    await page.locator('#viewer-motion').selectOption(motion);
    const times = JSON.parse(process.env.PHYSICS_TIMES || '[0,54.25,65.5,82.75]');
    const modes = JSON.parse(process.env.PHYSICS_MODES || '["disabled","bones","collision"]');
    for (const time of times) {
      for (const mode of modes) {
        await page.locator('#viewer-physics-colliders').setChecked(mode === 'collision'); await page.locator('#viewer-physics-bones').setChecked(mode !== 'disabled');
        await page.locator('#viewer-time').fill(String(time)); await page.locator('#viewer-time').dispatchEvent('input');
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        snapshots.push(await snapshot(page, time, mode));
        if (time === times[times.length - 1] && (mode === 'disabled' || mode === 'collision')) { if (mode === 'disabled') await page.locator('#viewer-fit').click(); await page.locator('#viewer-stage').screenshot({ path: path.join(evidence, 'pose-' + String(time).replace('.', '_') + '-' + mode + '.png') }); }
      }
    }
    if (process.env.PHYSICS_PERF !== '0') {
      const samples = [];
      await page.locator('#viewer-physics-show-colliders').setChecked(process.env.PHYSICS_PERF_DEBUG === '1');
      for (const startTime of [54, 65.25, 82.5]) {
        await page.locator('#viewer-physics-bones').check(); await page.locator('#viewer-physics-colliders').check();
        await page.locator('#viewer-time').fill(String(startTime)); await page.locator('#viewer-time').dispatchEvent('input');
        await page.evaluate(() => { window.__physicsFrameSamples = []; window.__physicsPerfEnabled = true; });
        await page.locator('#viewer-play').click();
        await page.waitForFunction(() => window.__physicsFrameSamples.length >= 40, null, { timeout: 120000 });
        await page.locator('#viewer-play').click();
        const segment = await page.evaluate(() => { window.__physicsPerfEnabled = false; return { samples: window.__physicsFrameSamples.slice(), time: ModelViewer.getState().rig.time }; });
        samples.push(...segment.samples);
        snapshots.push(await snapshot(page, segment.time, 'collision'));
        await page.locator('#viewer-physics-bones').uncheck(); await page.locator('#viewer-physics-colliders').uncheck();
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        snapshots.push(await snapshot(page, segment.time, 'disabled'));
      }
      const stats = values => { const sorted = values.slice().sort((a, b) => a-b); return { median: sorted[Math.floor(sorted.length * .5)], p95: sorted[Math.floor(sorted.length * .95)], max: sorted[sorted.length - 1] }; };
      const durations = stats(samples.map(row => row.ms)), groups = {};
      samples.forEach(row => { (groups[row.substeps] || (groups[row.substeps] = [])).push(row.ms); });
      fs.writeFileSync(path.join(evidence, 'frame-timings.json'), JSON.stringify(samples, null, 2));
      report.performance = { scope: 'Physics controller CPU apply time in actual playing browser frames; excludes GPU render', frames: samples.length,
        medianMs: durations.median, p95Ms: durations.p95, maxMs: durations.max,
        deltaSeconds: stats(samples.map(row => row.delta)), intervalMs: stats(samples.map(row => row.intervalMs).filter(Number.isFinite)),
        substeps: Object.fromEntries(Object.entries(groups).map(([steps, values]) => [steps, { frames: values.length, ...stats(values) }])),
        showColliders: process.env.PHYSICS_PERF_DEBUG === '1', samples: 'frame-timings.json',
        renderer: 'Chromium software WebGL (SwiftShader), shared cloud CPU', windows: [54, 65.25, 82.5] };
      if (physicsMode === 'game') {
        report.performance.nativeAcceptedFrames = samples.filter(row => row.nativeSteps > 0).length;
        assert(report.performance.nativeAcceptedFrames > 0, 'Actual playback advances the original native-equation engine');
      }
    }
    await page.locator('#viewer-physics-show-colliders').check(); await page.screenshot({ path: path.join(evidence, 'original-model-colliders.png') });
    assert.deepStrictEqual(errors, [], 'Actual physics has no browser exceptions');
    fs.writeFileSync(path.join(evidence, 'snapshots.json'), JSON.stringify(snapshots));
    if (physicsMode === 'enhanced') {
      execFileSync(python, [path.join(__dirname, 'measure_physics_capture.py'), path.join(evidence, 'snapshots.json'), '--output', path.join(evidence, 'measurements.json')], { cwd: product });
      const measurements = JSON.parse(fs.readFileSync(path.join(evidence, 'measurements.json'))); report.measurements = measurements.map(({ capsules, tips, ...summary }) => summary);
      const baseline = measurements.filter(row => row.mode === 'disabled'), corrected = measurements.filter(row => row.mode === 'collision');
      assert(baseline.some(row => row.fullyMobile.penetratingTriangles > 0), 'The original motion must exercise actual free skirt/leg intersections');
      corrected.forEach(row => { assert.equal(row.fullyMobile.penetratingTriangles, 0, 'Enhanced correction clears free skirt triangles at ' + row.time); assert(row.fullyMobile.minimumGap >= -.0001, 'Enhanced finite-triangle clearance at ' + row.time); assert.deepStrictEqual(row.rotationLimitViolations, [], 'Enhanced correction stays within authored Unity Euler limits'); });
    } else {
      report.nativeObservations = snapshots.map(row => ({time:row.time,mode:row.mode,triangles:row.triangles.length,settings:row.previewSettings,solver:row.solver}));
      snapshots.filter(row => row.mode === 'collision').forEach(row => {
        assert(row.solver.available && row.solver.initialized, 'The original engine is available and initialized at ' + row.time);
        assert.deepStrictEqual(row.solver.unsupported, [], 'All required original runtime inputs are supplied');
        assert(row.triangles.length > 0 && row.triangles.flat(2).every(Number.isFinite), 'Actual animated/skinned skirt geometry remains finite');
      });
      report.nativePlaybackResponses = snapshots.filter(row => row.mode === 'collision' && row.solver.totalNativeSteps > 0).map(row => {
        const baseline=snapshots.find(other=>other.time===row.time&&other.mode==='disabled');
        assert(baseline, 'Native playback has a disabled-physics comparison at the identical animation time');
        const changes=row.catalog.components.filter(c=>c.kind==='bone').map(c=>{
          const a=row.nodeFrames[String(c.node)]?.quaternion,b=baseline.nodeFrames[String(c.node)]?.quaternion;
          if(!a||!b)return null;
          const dot=Math.min(1,Math.abs(a.reduce((sum,value,i)=>sum+value*b[i],0))/Math.sqrt(a.reduce((sum,v)=>sum+v*v,0)*b.reduce((sum,v)=>sum+v*v,0)));
          return {name:c.name,angleDegrees:2*Math.acos(dot)*180/Math.PI};
        }).filter(change=>change&&change.angleDegrees>1e-4);
        assert(changes.length>0, 'Native playback changes the actual loaded model bone rotations');
        return {time:row.time,totalNativeSteps:row.solver.totalNativeSteps,changedBones:changes.length,largestAngleDegrees:Math.max(...changes.map(change=>change.angleDegrees))};
      });
      if(process.env.PHYSICS_PERF!=='0') assert(report.nativePlaybackResponses.length>=3, 'All three actual playback windows visibly apply the original engine');
    }
    assert.equal(sha(fs.readFileSync(body)), originalBodyHash); assert.equal(sha(fs.readFileSync(animation)), originalMotionHash);
    assert.equal(sha(fs.readFileSync(bodyFile)), originalBodyHash); assert.equal(sha(fs.readFileSync(animationFile)), originalMotionHash);
    report.sourceHashes = {body:{before:originalBodyHash,after:sha(fs.readFileSync(bodyFile))},motion:{before:originalMotionHash,after:sha(fs.readFileSync(animationFile))}};
    report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (browser) await browser.close(); if (server) { server.child.kill(); server.log.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, physicsMode: report.physicsMode, evidence: report.evidence, source: report.source, poses: (report.measurements || report.nativeObservations || []).filter(row => row.mode === 'collision').length, worstMobileGap: report.measurements && Math.min(...report.measurements.filter(row => row.mode === 'collision').map(row => row.fullyMobile.minimumGap)), performance: report.performance, error: report.error }, null, 2)); }
}
main().catch(() => { process.exitCode = 1; });
