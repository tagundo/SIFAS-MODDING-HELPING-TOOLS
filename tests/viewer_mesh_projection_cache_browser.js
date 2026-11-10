/* Trusted mesh strokes against an exhaustive deformed-triangle oracle. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const sources = process.env.ELICHIKA_VIEWER_STATIC_DIR || path.join(root, 'webtools/web/static');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mesh-projection-cache-'));
fs.mkdirSync(evidence, { recursive: true });
const report = { status: 'RUNNING', cases: [], scope: 'Actual product runtime, trusted pointer events and exhaustive unindexed world-space oracle. Generated skin/morph geometry; no game asset or native performance claim.' };
let browser;
(async () => { try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1000, height: 800 } }), errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await page.setContent('<body style="margin:0"><div id="stage"></div></body>');
  for (const name of ['vendor/three-r128/three.min.js', 'viewer-mesh-runtime.js', 'viewer-mesh-tools.js']) await page.addScriptTag({ path: path.join(sources, name) });
  await page.evaluate(() => {
    const T = THREE, renderer = new T.WebGLRenderer({ antialias: true }); renderer.setSize(800, 600); document.getElementById('stage').append(renderer.domElement);
    const camera = new T.PerspectiveCamera(45, 800 / 600, .1, 30); camera.position.z = 4; camera.updateMatrixWorld(true);
    const scene = new T.Scene(); let model, mesh, bone, data, state, context;
    function fresh() {
      model = new T.Group(); const geometry = new T.PlaneGeometry(3, 2.2, 40, 30), count = geometry.attributes.position.count;
      const skinIndex = new Uint16Array(count * 4), skinWeight = new Float32Array(count * 4), morph = new Float32Array(count * 3);
      for (let i = 0; i < count; i++) { skinIndex.set([0, 1, 0, 0], i * 4); skinWeight.set([.35, .65, 0, 0], i * 4); morph[i * 3 + 2] = Math.sin(i / 7) * .12; }
      geometry.setAttribute('skinIndex', new T.Uint16BufferAttribute(skinIndex, 4)); geometry.setAttribute('skinWeight', new T.Float32BufferAttribute(skinWeight, 4));
      geometry.morphAttributes.position = [new T.Float32BufferAttribute(morph, 3)]; geometry.morphTargetsRelative = true;
      const identity = { source: 0, file: 0, id: 'body' };
      geometry.userData.viewerMesh = { version: 1, writable: true, vertexOrder: 'identity', boneOrder: 'identity', mesh: identity, positionMatrix: new T.Matrix4().toArray(), vertexCount: count, faceCount: geometry.index.count / 3, firstFace: 0, submesh: 0 };
      mesh = new T.SkinnedMesh(geometry, new T.MeshBasicMaterial({ color: 0xeeeeee, side: T.DoubleSide, skinning: true, morphTargets: true }));
      const a = new T.Bone(); bone = new T.Bone(); a.add(bone); mesh.add(a); mesh.bind(new T.Skeleton([a, bone])); mesh.morphTargetInfluences[0] = .2;
      model.add(mesh); scene.add(model); data = { mesh: identity, positions: Array.from({ length: count }, (_, i) => [geometry.attributes.position.getX(i), geometry.attributes.position.getY(i), geometry.attributes.position.getZ(i)]) };
      state = { data, deleted: new Set(), marked: new Set(), selected: new Set(), positions: {}, weights: {}, geometryRevision: 0 };
      context = { mesh: state, modify: false, mode: 'paint', submesh: 0, radius: 24, erase: false, showSelection: true, showVertices: false, interactive: true };
      Object.assign(window.test || {}, { model, mesh, bone, state, context });
    }
    fresh(); const runtime = { model, scene, camera, renderer, domElement: renderer.domElement, controls: { enabled: true }, requestRender() {} };
    const controller = ViewerMeshRuntime.create({ getRuntime: () => runtime, getContext: () => context,
      onPaint(indices, erase, modify) { const set = modify ? state.selected : state.marked; indices.forEach(i => erase ? set.delete(i) : set.add(i)); controller.sync([state]); },
      onSelect(index) { state.selected = new Set([index]); controller.sync([state]); }, onEnd() { controller.sync([state]); } });
    controller.sync([state]);
    const blocker = new T.Mesh(new T.PlaneGeometry(.6, 1), new T.MeshBasicMaterial({ color: 0x222222, side: T.DoubleSide })); blocker.position.z = .3; blocker.visible = false; model.add(blocker);
    window.test = { T, scene, renderer, camera, runtime, controller, model, mesh, bone, state, context, blocker, original: mesh.geometry.clone(), fresh,
      initialPosition: Array.from(mesh.geometry.attributes.position.array), initialSkin: Array.from(mesh.geometry.attributes.skinWeight.array) };
    function allSurfaces() {
      const list = []; model.updateMatrixWorld(true); camera.updateMatrixWorld(true);
      model.traverse(m => { if (!m.isMesh || m.userData.viewerHelper) return; for (let p=m;p;p=p.parent) if (!p.visible) return; const mats=Array.isArray(m.material)?m.material:[m.material]; if (mats.every(v=>!v||v.visible===false||v.opacity===0)) return; list.push(m); }); return list;
    }
    window.oracle = function(point) {
      const surfaces = allSurfaces(), rect = renderer.domElement.getBoundingClientRect(), raycaster = new T.Raycaster();
      function nearest(x,y) { raycaster.setFromCamera(new T.Vector2((x-rect.left)/rect.width*2-1,1-(y-rect.top)/rect.height*2),camera); return surfaces.map(m=>ViewerMeshRuntime.raycastMesh(raycaster.ray,m)).filter(Boolean).sort((a,b)=>a.distanceSquared-b.distanceSquared)[0]; }
      const center = nearest(point.x,point.y); if (!center || center.object !== mesh) return [];
      const index=mesh.geometry.index, selected=[]; const mapping=[];for(let i=0;i<test.original.index.count/3;i++)if(!state.deleted.has(i))mapping.push(i);
      function project(v) { const p=ViewerMeshRuntime.vertexWorld(mesh,v),q=p.clone().project(camera);return {x:rect.left+(q.x+1)*rect.width/2,y:rect.top+(1-q.y)*rect.height/2,z:q.z}; }
      for(let offset=0;offset<index.count;offset+=3){const ids=[index.getX(offset),index.getX(offset+1),index.getX(offset+2)], p=ids.map(project);if(p.some(v=>v.z< -1||v.z>1))continue;if(!ViewerMeshTools.circleIntersectsTriangle(point.x,point.y,context.radius,[p[0].x,p[0].y],[p[1].x,p[1].y],[p[2].x,p[2].y]))continue;const hit=nearest(p.reduce((s,v)=>s+v.x,0)/3,p.reduce((s,v)=>s+v.y,0)/3);if(hit&&hit.object===mesh&&hit.faceIndex===offset/3)selected.push(mapping[offset/3]);}
      return selected.sort((a,b)=>a-b);
    };
    window.prepare = function() { state.marked.clear(); controller.sync([state]); model.updateMatrixWorld(true); camera.updateMatrixWorld(true); renderer.render(scene,camera); return controller.getState().performance; };
    window.summary = function() { return { selected:Array.from(state.marked).sort((a,b)=>a-b),performance:controller.getState().performance,runtime:controller.getState() }; };
  });
  async function stroke(name, mutate, expectedChange, point = { x: 400, y: 300 }) {
    if (mutate) await page.evaluate(mutate);
    const before = await page.evaluate(() => prepare()), expected = await page.evaluate(p => oracle(p), point);
    await page.mouse.click(point.x, point.y); const after = await page.evaluate(() => summary());
    assert.deepEqual(after.selected, expected, name + ': exact exhaustive source faces');
    const delta = Object.fromEntries(Object.keys(before).map(k => [k, after.performance[k] - before[k]]));
    if (expectedChange === 'warm') { assert.equal(delta.projectionBuilds, 0); assert.equal(delta.worldVertices, 0); assert.equal(delta.geometryApplications, 0); }
    if (expectedChange === 'view') { assert.equal(delta.worldVertices, 0); assert.equal(delta.projectionBuilds, 1); }
    if (expectedChange === 'pose') { assert(delta.worldVertices > 0, name + ': deformed vertices recomputed'); assert.equal(delta.projectionBuilds, 1); }
    report.cases.push({ name, selected: expected.length, delta }); return after;
  }
  await stroke('First skinned and morphed paint agrees with exhaustive oracle');
  await stroke('Unchanged-pose selection sync keeps exact projection and world caches', null, 'warm');
  await page.evaluate(() => { test.context.showSelection=false;test.controller.beforeRender();const visible=[];test.scene.traverse(o=>{if(o.renderOrder===900)visible.push(o.visible)});if(visible.length!==1||visible[0])throw Error('cached overlay did not hide');test.context.showSelection=true;test.controller.beforeRender(); });
  report.cases.push({name:'Selection visibility updates without discarding exact pose cache'});
  await stroke('Camera orbit invalidates projection only', () => { test.camera.position.x=.3;test.camera.lookAt(0,0,0); }, 'view');
  await stroke('Zoom invalidates projection only', () => { test.camera.fov=48;test.camera.updateProjectionMatrix(); }, 'view');
  await stroke('Pan invalidates projection only', () => { test.camera.position.y=.2;test.camera.lookAt(.1,.1,0); }, 'view');
  await stroke('Viewport resize invalidates projection only', () => { test.renderer.setSize(760,560);test.camera.aspect=760/560;test.camera.updateProjectionMatrix(); }, 'view', {x:380,y:280});
  await stroke('Current bone transforms invalidate deformed surface caches', () => { test.bone.rotation.y=.25; }, null, {x:380,y:280});
  await stroke('Current morph weight invalidates deformed surface caches', () => { test.mesh.morphTargetInfluences[0]=.75; }, null, {x:380,y:280});
  await stroke('Mesh scale and rotation invalidate deformed surface caches', () => { test.mesh.rotation.z=.08;test.mesh.scale.x=1.08; }, null, {x:380,y:280});
  await stroke('Position edits apply geometry once and invalidate picks', () => { test.state.positions[635]=[.1,.15,.35];test.state.geometryRevision++; }, null, {x:380,y:280});
  await stroke('Skin-weight edits invalidate deformed picks', () => { test.state.weights[635]=[[1,1]];test.state.geometryRevision++; }, null, {x:380,y:280});
  await stroke('Deleting source faces updates topology and face identities', () => { for(let i=1000;i<1100;i++)test.state.deleted.add(i);test.state.geometryRevision++; }, null, {x:380,y:280});
  await stroke('Undo restoring geometry and weights keeps source identities', () => { test.state.deleted.clear();test.state.positions={};test.state.weights={};test.state.geometryRevision++; }, null, {x:380,y:280});
  await stroke('Occluding unmapped mesh participates in exact visible picking', () => { test.blocker.visible=true; }, null, {x:380,y:280});
  await stroke('Moving occluder invalidates visibility', () => { test.blocker.position.x=2; }, null, {x:380,y:280});
  await stroke('Transparent occluder leaves source geometry selectable', () => { test.blocker.position.x=0;test.blocker.material.opacity=0; }, null, {x:380,y:280});
  await stroke('Replacing a morph attribute invalidates even with same version/count', () => { test.mesh.geometry.morphAttributes.position[0]=test.mesh.geometry.morphAttributes.position[0].clone(); }, null, {x:380,y:280});
  await stroke('Bone inverse changes invalidate the exact skin transform', () => { test.mesh.skeleton.boneInverses[1].elements[12]=.04; }, null, {x:380,y:280});
  await stroke('Bind matrix changes invalidate the exact skin transform', () => { test.mesh.bindMatrix.elements[13]=.02; }, null, {x:380,y:280});
  await stroke('Standalone unversioned mesh-state mutations remain supported', () => { delete test.state.geometryRevision;test.state.positions[635]=[.15,.1,.2]; }, null, {x:380,y:280});
  await stroke('Standalone unchanged edits reuse the projection cache', null, 'warm', {x:380,y:280});
  for (let frame=0;frame<6;frame++) {
    await page.evaluate(frame => { test.bone.rotation.z = .03 * (frame + 1); test.mesh.morphTargetInfluences[0] = .1 + frame * .12; }, frame);
    await stroke('Consecutive moving bone and morph pose frame ' + frame, null, 'pose', {x:380,y:280});
  }
  await page.evaluate(() => { const old=test.mesh,original=old.geometry.userData.viewerMesh;test.controller.reset();if(!original||old.geometry.userData.viewerMesh.mesh.id!=='body')throw Error('original mapping lost');if(JSON.stringify(Array.from(old.geometry.attributes.position.array))!==JSON.stringify(test.initialPosition)||JSON.stringify(Array.from(old.geometry.attributes.skinWeight.array))!==JSON.stringify(test.initialSkin))throw Error('source geometry or weight bytes were changed');test.scene.remove(test.model);test.fresh();Object.assign(test.runtime,{model:test.model});test.controller.sync([test.state]); });
  await stroke('Model reload discards the old model cache and binds the new source', null, null, {x:380,y:280});
  const stable = await page.evaluate(() => { test.controller.reset();test.controller.dispose();return {bindings:test.controller.getState().boundPrimitives}; });
  assert.equal(stable.bindings,0); assert.deepEqual(errors,[]); report.cases.push({name:'Reset and disposal release all live source bindings'});
  report.status='PASS'; await page.screenshot({path:path.join(evidence,'cache-regression.png')});
} catch (error) { report.status='FAIL';report.error=String(error.stack||error);process.exitCode=1; }
finally { if(browser)await browser.close();fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,cases:report.cases.length,evidence,error:report.error})); }
})();
