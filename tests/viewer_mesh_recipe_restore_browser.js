/* Real source/HTTP/WebGL: atomic whole-mesh recipe restore, Undo and stale jobs. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-restore-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mesh-restore-library-')), models = path.join(library, 'extracted/3d_model');
fs.mkdirSync(models, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const raw = fs.readFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'));
const source = path.join(models, 'original-a.unity'), other = path.join(models, 'original-b.unity');
fs.writeFileSync(source, raw); fs.writeFileSync(other, raw);
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const actualSource = process.env.MESH_RESTORE_GAME_MODEL ? path.join(models, path.basename(process.env.MESH_RESTORE_GAME_MODEL)) : '';
if (actualSource) fs.copyFileSync(process.env.MESH_RESTORE_GAME_MODEL, actualSource);
const actualHash = actualSource ? sha(fs.readFileSync(actualSource)) : '';
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function start() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const log = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log); child.stderr.pipe(log);
  const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { if (child.exitCode !== null) throw Error('Product server exited'); try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) {} await wait(100); }
  child.kill(); throw Error('Product server did not become ready');
}
async function state(page) { return page.evaluate(() => ModelViewer.getState().meshTools); }
function stable(value) { return { edits: value.edits, history: value.history, future: value.future, runtime: value.runtime && value.runtime.bindings }; }
async function open(page, file) {
  await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, file);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
}
async function firstMesh(page) {
  return page.evaluate(async () => { const token = ModelViewer.getEditingMetadata().token;
    const response = await fetch('/api/viewer/mesh/inspect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) });
    if (!response.ok) throw Error(await response.text()); return (await response.json()).meshes.find(row => row.available).mesh;
  });
}
async function restore(page, value) { return page.evaluate(value => window.__meshRecipeTool.restoreEdits(value), value); }
async function main() {
  const report = { status: 'RUNNING', evidence, cases: [] }; let server, browser, context;
  try {
    server = await start(); browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    await context.addInitScript(() => {
      let api;
      Object.defineProperty(window, 'ViewerMeshTools', { configurable: true, get: () => api, set: value => {
        api = value; const create = api.create;
        api.create = function (options) { window.__meshRecipeOptions = options; const tool = create(options); window.__meshRecipeTool = tool; return tool; };
      } });
    });
    const page = await context.newPage(), errors = []; page.on('pageerror', error => errors.push(String(error.stack || error))); page.setDefaultTimeout(30000);
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function'); await open(page, source);
    const mesh = await firstMesh(page), token = await page.evaluate(() => ModelViewer.getEditingMetadata().token);
    const recipe = { version: 1, meshes: [{ mesh, deleteFaces: [1], positions: [{ vertex: 2, position: [.2, .8, -.1] }],
      weights: [{ vertex: 2, influences: [[0, .2], [1, .8]] }] }] };
    // The persistence controller deliberately makes ordinary editing noninteractive
    // during a recipe load. This does not grant a fake source or success response.
    await page.evaluate(() => { window.__originalMeshInteractive = __meshRecipeOptions.isInteractive; __meshRecipeOptions.isInteractive = () => false; });
    const normalized = await restore(page, recipe);
    await page.evaluate(() => { __meshRecipeOptions.isInteractive = __originalMeshInteractive; });
    let s = await state(page); assert.equal(s.history, 1); assert.equal(s.runtime.boundPrimitives, 1);
    assert.deepStrictEqual(normalized, s.edits); assert.equal(s.runtime.bindings[0].triangles, 3);
    const near = (a, b) => assert(Math.abs(a - b) < 1e-6, `${a} != ${b}`);
    near(s.runtime.bindings[0].samplePositions[6], -.2); near(s.runtime.bindings[0].samplePositions[7], .8); near(s.runtime.bindings[0].samplePositions[8], -.1);
    assert(s.runtime.bindings[0].sampleWeights.slice(8, 12).some(value => Math.abs(value - .8) < 1e-6));
    assert.equal(await page.evaluate(() => ModelViewer.getEditingMetadata().token), token);
    await page.evaluate(() => __meshRecipeTool.undo()); s = await state(page); assert.deepStrictEqual(s.edits.meshes, []); assert.equal(s.runtime.bindings[0].triangles, 4);
    await page.evaluate(() => __meshRecipeTool.redo()); s = await state(page); assert.deepStrictEqual(s.edits, normalized); assert.equal(s.history, 1);
    report.cases.push({ name: 'source-bound whole restore while noninteractive, real GPU topology/positions/weights and one Undo/Redo', state: normalized });

    const invalid = [
      { version: 2, meshes: [] }, { version: 1, meshes: [{ ...recipe.meshes[0], extra: true }] },
      { version: 1, meshes: [{ ...recipe.meshes[0], deleteFaces: [4] }] },
      { version: 1, meshes: [{ ...recipe.meshes[0], deleteFaces: [1, 1] }] },
      { version: 1, meshes: [{ ...recipe.meshes[0], positions: [{ vertex: 6, position: [0, 0, 0] }] }] },
      { version: 1, meshes: [{ ...recipe.meshes[0], positions: [{ vertex: 0, position: [null, 0, 0] }] }] },
      { version: 1, meshes: [{ ...recipe.meshes[0], weights: [{ vertex: 0, influences: [[3, 1]] }] }] },
      { version: 1, meshes: [{ ...recipe.meshes[0], weights: [{ vertex: 0, influences: [[0, 0]] }] }] },
      { version: 1, meshes: [recipe.meshes[0], { mesh: { ...mesh, id: '999999999' }, deleteFaces: [0] }] }
    ];
    const beforeInvalid = stable(await state(page)), revision = await page.evaluate(() => __meshRecipeTool.getEditRevision());
    for (const candidate of invalid) {
      const failure = await page.evaluate(async candidate => { try { await __meshRecipeTool.restoreEdits(candidate); return null; } catch (error) { return String(error.message || error); } }, candidate);
      assert(failure, 'Invalid restore must reject'); assert.deepStrictEqual(stable(await state(page)), beforeInvalid);
      assert.equal(await page.evaluate(() => __meshRecipeTool.getEditRevision()), revision);
    }
    report.cases.push({ name: 'malformed, unavailable and late-invalid multi-mesh recipes preserve live state/history atomically', rejected: invalid.length });
    const empty = await restore(page, { version: 1, meshes: [] }); assert.deepStrictEqual(empty.meshes, []);
    s = await state(page); assert.equal(s.runtime.bindings[0].triangles, 4);
    assert.notDeepStrictEqual(s.runtime.bindings[0].samplePositions, beforeInvalid.runtime[0].samplePositions);
    await page.evaluate(() => __meshRecipeTool.undo()); s = await state(page); assert.deepStrictEqual(s.edits, normalized); assert.equal(s.runtime.bindings[0].triangles, 3);
    const replacement = { version: 1, meshes: [{ mesh, deleteFaces: [0, 2], positions: [{ vertex: 2, position: [.3, .7, .1] }], weights: [{ vertex: 2, influences: [[1, .7], [0, .3]] }] }] };
    await restore(page, replacement); s = await state(page); assert.equal(s.runtime.bindings[0].triangles, 2); near(s.runtime.bindings[0].samplePositions[6], -.3);
    assert(s.runtime.bindings[0].sampleWeights.slice(8, 12).some(value => Math.abs(value - .7) < 1e-6));
    await page.evaluate(() => __meshRecipeTool.undo()); assert.deepStrictEqual(stable(await state(page)).runtime, beforeInvalid.runtime);
    report.cases.push({ name: 'empty and repeated restore update actual GPU topology/positions/weights and remain one-step undoable' });
    const beforeCommitFailure = stable(await state(page)), beforeCommitRevision = await page.evaluate(() => __meshRecipeTool.getEditRevision());
    const commitFailure = await page.evaluate(async value => {
      const original = __meshRecipeOptions.onChange;
      __meshRecipeOptions.onChange = function () {
        const current = __meshRecipeTool.getEdits();
        if (current.meshes.length && current.meshes[0].deleteFaces.length === 2) throw Error('Injected presentation callback failure');
        return original.apply(this, arguments);
      };
      try { await __meshRecipeTool.restoreEdits(value); return null; }
      catch (error) { return error.message; }
      finally { __meshRecipeOptions.onChange = original; }
    }, replacement);
    assert.equal(commitFailure, 'Injected presentation callback failure'); assert.deepStrictEqual(stable(await state(page)), beforeCommitFailure);
    assert.equal(await page.evaluate(() => __meshRecipeTool.getEditRevision()), beforeCommitRevision);
    await page.evaluate(() => __meshRecipeTool.redo()); s = await state(page); assert.equal(s.runtime.bindings[0].triangles, 2); near(s.runtime.bindings[0].samplePositions[6], -.3);
    await page.evaluate(() => __meshRecipeTool.undo()); assert.deepStrictEqual(stable(await state(page)), beforeCommitFailure);
    report.cases.push({ name: 'presentation failure during commit rolls back actual GPU geometry, complete edits, revision and Undo/Redo history' });

    // Hold only the real inspect request. Switch source while it is pending,
    // restore a different actual edit in the new source, then release the old job.
    await open(page, source);
    let heldResolve, releaseResolve, held = new Promise(resolve => { heldResolve = resolve; }), release = new Promise(resolve => { releaseResolve = resolve; });
    let intercepted = false;
    await page.route('**/api/viewer/mesh/inspect', async route => { if (!intercepted) { intercepted = true; heldResolve(); await release; } await route.continue(); });
    await page.evaluate(recipe => { window.__staleMeshRestore = null; __meshRecipeTool.restoreEdits(recipe).then(value => { __staleMeshRestore = { value }; }, error => { __staleMeshRestore = { name: error.name, message: error.message }; }); }, recipe);
    await held; await open(page, other);
    const nextToken = await page.evaluate(() => ModelViewer.getEditingMetadata().token); assert.notEqual(nextToken, token);
    const nextMesh = await firstMesh(page), nextRecipe = { version: 1, meshes: [{ mesh: nextMesh, deleteFaces: [2], positions: [{ vertex: 1, position: [.11, .65, .02] }] }] };
    await restore(page, nextRecipe); const nextState = stable(await state(page)); releaseResolve();
    await page.waitForFunction(() => window.__staleMeshRestore); const stale = await page.evaluate(() => window.__staleMeshRestore);
    assert.equal(stale.name, 'AbortError'); assert.deepStrictEqual(stable(await state(page)), nextState); assert.equal((await state(page)).busy, false);
    await page.unroute('**/api/viewer/mesh/inspect');
    report.cases.push({ name: 'obsolete source request cannot replace the new model edits or undo history', oldToken: token, newToken: nextToken, stale });
    if (actualSource) {
      await open(page, actualSource);
      const data = await page.evaluate(async () => {
        const token = ModelViewer.getEditingMetadata().token;
        async function request(endpoint, body) { const r = await fetch('/api/viewer/mesh/' + endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); if (!r.ok) throw Error(await r.text()); return r.json(); }
        const listing = await request('inspect', { token });
        for (const row of listing.meshes.slice().sort((a, b) => b.vertices - a.vertices)) {
          if (!row.available) continue; const data = await request('data', { token, mesh: row.mesh });
          if (data.positionWritable && data.bones.length > 1 && data.triangles.length) return data;
        }
        throw Error('Real costume has no writable skinned mesh');
      });
      const originalBone = data.skin[0][0][0], secondBone = (originalBone + 1) % data.bones.length;
      const proposedWeights = [{ vertex: 0, influences: [[originalBone, .25], [secondBone, .75]] }];
      const actualRecipe = { version: 1, meshes: [{ mesh: data.mesh, deleteFaces: [0], positions: [{ vertex: 0, position: data.positions[0].map(value => value + .01) }], weights: data.skinWritable ? proposedWeights : [] }] };
      await restore(page, actualRecipe); const applied = stable(await state(page));
      assert.equal(applied.runtime.reduce((total, row) => total + row.triangles, 0), data.triangles.length - 1);
      if (data.skinWritable) assert(applied.runtime[0].sampleWeights.slice(0, 4).some(value => Math.abs(value - .75) < 1e-6));
      else {
        const failure = await page.evaluate(async value => { try { await __meshRecipeTool.restoreEdits(value); return null; } catch (error) { return error.message; } },
          { version: 1, meshes: [{ ...actualRecipe.meshes[0], weights: proposedWeights }] });
        assert(failure, 'Unsupported native skin writer rejects instead of pretending to apply'); assert.deepStrictEqual(stable(await state(page)), applied);
      }
      await page.evaluate(() => __meshRecipeTool.undo()); const original = stable(await state(page));
      assert.equal(original.runtime.reduce((total, row) => total + row.triangles, 0), data.triangles.length);
      assert.notDeepStrictEqual(original.runtime[0].samplePositions, applied.runtime[0].samplePositions);
      await page.evaluate(() => __meshRecipeTool.redo()); assert.deepStrictEqual(stable(await state(page)), applied);
      assert.equal(sha(fs.readFileSync(actualSource)), actualHash);
      report.cases.push({ name: 'Real game costume restores topology, positions' + (data.skinWritable ? ' and skin weights' : '') + ' on the GPU with exact one-step Undo/Redo' + (data.skinWritable ? '' : '; unsupported skin channels reject atomically'), source: process.env.MESH_RESTORE_GAME_MODEL, sha256: actualHash, vertices: data.positions.length, triangles: data.triangles.length, boundPrimitives: applied.runtime.length, skinWritable: data.skinWritable });
    }
    await page.screenshot({ path: path.join(evidence, 'restored-live-mesh.png') });
    assert.equal(sha(fs.readFileSync(source)), sha(raw)); assert.equal(sha(fs.readFileSync(other)), sha(raw)); assert.deepStrictEqual(errors, []);
    report.sourceSha256 = sha(raw); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); throw error; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.log.end(); }
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n'); console.log(JSON.stringify(report, null, 2)); }
}
if (require.main === module) main().catch(() => { process.exitCode = 1; });
