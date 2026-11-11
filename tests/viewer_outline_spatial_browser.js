/* Exact brush visibility, pose/topology cache invalidation and bounded ray work. */
'use strict';
const assert = require('assert'), fs = require('fs'), os = require('os'), path = require('path');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-outline-spatial-'));
fs.mkdirSync(evidence, { recursive: true });
async function main() {
  let browser;
  const report = { status: 'RUNNING', evidence, cases: [], scope: 'Real trusted pointer events and product brush; exhaustive world-space ray oracle independently checks screen-index pruning. CPU times are observations, not fixed performance thresholds.' };
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ viewport: { width: 1200, height: 900 } }), errors = [];
    page.on('pageerror', error => errors.push(String(error.stack || error)));
    await page.setContent('<html lang="en"><body style="margin:0"><div id="stage" style="position:fixed;left:0;top:0;width:800px;height:600px"></div><div id="viewer-control-panel" style="position:fixed;left:810px;top:0;width:380px;height:880px;overflow:auto"><details id="viewer-body-adjustments"></details></div></body></html>');
    for (const file of ['vendor/three-r128/three.min.js', 'viewer-mesh-runtime.js', 'viewer-outlines.js']) await page.addScriptTag({ path: path.join(product, 'webtools/web/static', file) });
    await page.evaluate(() => {
      const T = THREE, renderer = new T.WebGLRenderer({ antialias: false }); renderer.setSize(800, 600); document.getElementById('stage').append(renderer.domElement);
      const scene = new T.Scene(), camera = new T.PerspectiveCamera(45, 800 / 600, .1, 20); camera.position.z = 4; camera.updateMatrixWorld(true);
      const model = new T.Group(), geometry = new T.PlaneGeometry(3, 2.2, 100, 70), count = geometry.attributes.position.count;
      const mesh = new T.Mesh(geometry, new T.MeshBasicMaterial({ color: 0xdddddd, side: T.DoubleSide }));
      geometry.userData = { viewerMesh: { version: 1, vertexOrder: 'identity', mesh: { source: 0, file: 0, id: '1' }, vertexCount: count } };
      const back = new T.Mesh(geometry.clone(), new T.MeshBasicMaterial({ color: 0x555555, side: T.DoubleSide })); back.position.z = -.2;
      back.geometry.userData = { viewerMesh: { version: 1, vertexOrder: 'identity', mesh: { source: 0, file: 0, id: '2' }, vertexCount: count } };
      model.add(mesh, back); scene.add(model);
      let edits = [], revision = 0;
      const catalogue = { meshes: [{ id: '0:0:1', name: 'front', vertexCount: count }, { id: '0:0:2', name: 'behind', vertexCount: count }] };
      const rig = { getOutlineEdits: () => JSON.parse(JSON.stringify(edits)), getOutlineRevision: () => revision,
        setOutlineEdits: next => { edits = ViewerOutlines.checked(next, catalogue); revision++; } };
      const runtime = { model, scene, camera, renderer, domElement: renderer.domElement };
      const controller = ViewerOutlines.create({ getRuntime: () => runtime, context: () => ({ rig, editing: { available: true, outlines: catalogue }, current: true,
        materials: { setOutlineEdits() {}, getState: () => ({ enabled: true }) } }), onChange() {} });
      window.test = { T, model, mesh, back, scene, camera, renderer, rig, controller, runtime, catalogue, baseIndex: geometry.index.array.slice() };
      document.getElementById('viewer-outline-card').open = true; document.getElementById('viewer-outline-detail').open = true;
      document.getElementById('viewer-outline-scene-mode').value = 'paint'; document.getElementById('viewer-outline-brush-radius').value = 24;
      controller.refresh(); model.updateMatrixWorld(true); renderer.render(scene, camera);
      // The reference deliberately examines every triangle for each ray. It
      // has no dependency on the brush's projected triangle cells or cache.
      window.exhaustive = function (x, y) {
        const { T, model, camera, renderer } = test, rect = renderer.domElement.getBoundingClientRect(), list = [];
        model.updateMatrixWorld(true); camera.updateMatrixWorld(true);
        model.traverse(mesh => { if (!mesh.isMesh || mesh.userData.viewerHelper) return; for (let current = mesh; current; current = current.parent) if (!current.visible) return; list.push(mesh); });
        const raycaster = new T.Raycaster();
        function nearest() { return list.map(mesh => ViewerMeshRuntime.raycastMesh(raycaster.ray, mesh)).filter(Boolean).sort((a, b) => a.distanceSquared - b.distanceSquared)[0]; }
        raycaster.setFromCamera(new T.Vector2((x - rect.left) / rect.width * 2 - 1, 1 - (y - rect.top) / rect.height * 2), camera);
        const hit = nearest(); if (!hit) return [];
        const map = hit.object.geometry.userData.viewerMesh, identity = [map.mesh.source, map.mesh.file, map.mesh.id].join(':');
        const index = hit.object.geometry.index, used = new Set(index ? index.array : Array.from({ length: hit.object.geometry.attributes.position.count }, (_, i) => i));
        const vertices = [], radius = Number(document.getElementById('viewer-outline-brush-radius').value); let nearestVertex = null, distance = Infinity;
        for (const vertex of used) {
          const world = ViewerMeshRuntime.vertexWorld(hit.object, vertex), p = world.clone().project(camera), px = rect.left + (p.x + 1) / 2 * rect.width, py = rect.top + (1 - p.y) / 2 * rect.height, d = Math.hypot(px - x, py - y);
          if ([hit.face.a, hit.face.b, hit.face.c].includes(vertex) && d < distance) { distance = d; nearestVertex = vertex; }
          if (p.z < -1 || p.z > 1 || d > radius) continue;
          raycaster.setFromCamera(new T.Vector2(p.x, p.y), camera); const blocker = nearest();
          if (blocker && blocker.distance + 1e-5 < raycaster.ray.origin.distanceTo(world) && blocker.point.distanceTo(world) > 1e-4) continue;
          vertices.push(vertex);
        }
        if (!vertices.length && nearestVertex !== null) vertices.push(nearestVertex);
        return vertices.length ? [{ id: identity, factor: 1, vertices: vertices.sort((a, b) => a - b).map(vertex => ({ vertex, value: .5 })) }] : [];
      };
      window.snapshotProof = function () {
        let compared = 0, maxError = 0; test.model.updateMatrixWorld(true);
        test.model.traverse(mesh => {
          if (!mesh.isMesh || mesh.userData.viewerHelper) return;
          const snapshot = ViewerMeshRuntime.worldSnapshot(mesh);
          for (let vertex = 0; vertex < snapshot.length; vertex++) {
            const original = ViewerMeshRuntime.vertexWorld(mesh, vertex);
            maxError = Math.max(maxError, original.distanceTo(snapshot[vertex])); compared++;
          }
          const subset = [snapshot.length - 1, 0, Math.floor(snapshot.length / 2)], partial = ViewerMeshRuntime.worldSnapshot(mesh, subset);
          for (const vertex of subset) if (!partial[vertex].equals(snapshot[vertex])) throw new Error('Subset snapshots must preserve original source indices');
        });
        if (maxError !== 0) throw new Error('Batch skin/morph world positions must be exactly identical: ' + maxError);
        return { compared, maxError };
      };
    });
    async function stroke(name, mutate, point = [400, 300]) {
      if (mutate) await page.evaluate(mutate);
      const snapshotProof = await page.evaluate(() => window.snapshotProof());
      const expected = await page.evaluate(point => { test.rig.setOutlineEdits([]); test.controller.refresh(); return exhaustive(point[0], point[1]); }, point);
      const before = await page.evaluate(() => test.controller.getState().performance);
      const start = Date.now(); await page.mouse.move(point[0], point[1]); await page.mouse.down(); await page.mouse.up();
      const observed = await page.evaluate(() => test.controller.getState());
      assert.deepStrictEqual(observed.edits, expected, name + ' must match exhaustive source-vertex visibility exactly');
      const work = Object.fromEntries(Object.keys(before).filter(key => key !== 'lastPaintMs').map(key => [key, observed.performance[key] - before[key]]));
      report.cases.push({ name, snapshotProof, expectedVertices: expected.reduce((sum, row) => sum + row.vertices.length, 0), observedMeshes: observed.edits.map(row => row.id), work, handlerMs: observed.performance.lastPaintMs, elapsedMs: Date.now() - start });
      return observed;
    }
    const first = await stroke('Two overlapping source meshes keep the hidden layer untouched');
    const warm = await stroke('Repeated brush positions reuse exact world vertices and triangle cells');
    assert.equal(report.cases[1].work.cacheBuilds, 0); assert.equal(report.cases[1].work.worldVertices, 0);
    const fullTriangleWork = report.cases[1].work.rayQueries * 14000;
    assert(report.cases[1].work.triangleTests < fullTriangleWork / 8, 'Spatial pruning must reduce exact triangle work while selecting the same vertices');
    await stroke('Moving the front mesh invalidates the pose cache and exposes the rear mesh', () => { test.mesh.position.x = 3; });
    assert.deepStrictEqual(report.cases.at(-1).observedMeshes, ['0:0:2']);
    await stroke('Replacing the index buffer removes faces from the next pick', () => { test.mesh.position.x = 0; test.mesh.geometry.setIndex([]); });
    assert.deepStrictEqual(report.cases.at(-1).observedMeshes, ['0:0:2']);
    await stroke('Camera changes use the current projection', () => { test.camera.position.set(.3, .2, 4); test.camera.lookAt(0, 0, 0); });
    await stroke('Skinned and morphed geometry uses current world positions', () => {
      const { T, model, back } = test, geometry = back.geometry.clone(), count = geometry.attributes.position.count;
      geometry.setAttribute('skinIndex', new T.Uint16BufferAttribute(new Uint16Array(count * 4), 4));
      const indices = new Uint16Array(count * 4), weights = new Float32Array(count * 4); for (let i = 0; i < count; i++) { indices.set([0, 1, 2, 3], i * 4); weights.set([.1, .2, .3, .4], i * 4); }
      geometry.setAttribute('skinIndex', new T.Uint16BufferAttribute(indices, 4));
      geometry.setAttribute('skinWeight', new T.Float32BufferAttribute(weights, 4));
      const morph = new Float32Array(count * 3); for (let i = 0; i < count; i++) morph[i * 3 + 2] = .12 * Math.sin(i / 10);
      geometry.morphAttributes.position = [new T.Float32BufferAttribute(morph, 3)]; geometry.morphTargetsRelative = true;
      const skin = new T.SkinnedMesh(geometry, new T.MeshBasicMaterial({ color: 0x999999, side: T.DoubleSide, skinning: true, morphTargets: true }));
      skin.position.copy(back.position); skin.rotation.x = .04; skin.scale.set(1.01, .98, 1.03);
      const bones = Array.from({ length: 4 }, (_, index) => { const bone = new T.Bone(); bone.position.set(index * .01, index * -.02, index * .005); skin.add(bone); return bone; });
      skin.bind(new T.Skeleton(bones)); skin.morphTargetInfluences[0] = .5; const bone = bones[0];
      model.remove(back); model.add(skin); test.skin = skin; test.bone = bone;
    });
    await stroke('Bone rotation and morph-weight changes invalidate cached picks', () => { test.bone.rotation.z = .12; test.skin.morphTargetInfluences[0] = .9; });
    await stroke('Brush-edge vertices retain occlusion from off-screen triangles', () => {
      const { T, model, mesh, back, camera } = test; model.clear(); mesh.position.set(0, 0, 0); mesh.geometry.setIndex(new T.BufferAttribute(test.baseIndex.slice(), 1));
      model.add(mesh, back); camera.position.set(0, 0, 1.2); camera.lookAt(0, 0, 0);
      const blocker = new T.Mesh(new T.PlaneGeometry(.02, .4), new T.MeshBasicMaterial({ side: T.DoubleSide })); blocker.position.set(-.6325, 0, .1);
      blocker.geometry.userData = { viewerMesh: { version: 1, vertexOrder: 'identity', mesh: { source: 0, file: 0, id: 'offscreen' } } }; model.add(blocker);
    }, [4, 300]);
    await page.evaluate(() => { test.controller.undo(); test.controller.redo(); });
    assert.deepStrictEqual(errors, []); report.pruningRatio = fullTriangleWork / report.cases[1].work.triangleTests; report.status = 'PASS';
    await page.screenshot({ path: path.join(evidence, 'spatial-brush.png') });
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally { if (browser) await browser.close(); fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence, error: report.error })); }
}
if (require.main === module) main();
