/* Actual HTTP/WebGL/SDK composition and immutable costume ZIP output. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process'); const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-thumbnail-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-thumbnail-library-')), input = path.join(library, 'extracted/3d_model'), output = path.join(library, 'suit');
fs.mkdirSync(input, { recursive: true }); fs.mkdirSync(output, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const source = path.join(input, '006thumbnail.unity'); fs.copyFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'), source);
const sha = data => crypto.createHash('sha256').update(data).digest('hex'), original = sha(fs.readFileSync(source)), sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function start() { const s = net.createServer(); await new Promise(r => s.listen(0, '127.0.0.1', r)); const port = s.address().port; await new Promise(r => s.close(r));
  const log = fs.createWriteStream(path.join(evidence, 'server.log')); const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: repo, env: { ...process.env, PYTHONPATH: product + path.delimiter + repo, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] }); child.stdout.pipe(log); child.stderr.pipe(log);
  const url = 'http://127.0.0.1:' + port; for (let i = 0; i < 150; i++) { try { if ((await fetch(url + '/api/tools')).ok) return { child, log, url }; } catch (_) {} await sleep(100); } throw new Error('Server did not start'); }
async function show(page, selector) { const loc = page.locator(selector); await loc.evaluate(e => { for (let p = e.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; }); await loc.scrollIntoViewIfNeeded(); return loc; }
function inspectZip(filename, pngOut) { return JSON.parse(execFileSync(python, ['-c', `import ast,hashlib,io,json,sys,zipfile;from PIL import Image;z=zipfile.ZipFile(sys.argv[1]);m=next(n for n in z.namelist() if n.rsplit('/',1)[-1]=='modinstall.txt');d={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(z.read(m).decode()).body};b=z.read(d['thumbnail_file']);open(sys.argv[2],'wb').write(b);im=Image.open(io.BytesIO(b)).convert('RGBA');print(json.dumps({'sha256':hashlib.sha256(b).hexdigest(),'size':im.size,'member':d['chara_id'],'thumbnail':d['thumbnail_file'],'alpha':im.getpixel((0,0))[3],'modelSha':hashlib.sha256(z.read(d['costume_file'])).hexdigest(),'iosSha':hashlib.sha256(z.read(d['costume_file_ios'])).hexdigest() if d.get('costume_file_ios') else None,'backgroundPixel':im.getpixel((im.width//8,im.height//8))}))`, filename, pngOut], { cwd: product, encoding: 'utf8' })); }
async function untouched(page) { return page.evaluate(() => { const s = ModelViewer.getState(); return { paths: s.loadedPaths, motions: s.motionLibraryPaths, camera: s.camera, authoring: ModelViewer.getAuthoringState(),
  pose: s.rig && { clip: s.rig.selectedClip, time: s.rig.time, playing: s.rig.playing, body: s.rig.body, physics: s.rig.physics }, meshNames: s.meshNames, source: s.sourceTriangles,
  rimlight: s.materials && s.materials.rimlightEnabled, rimlightPreference: localStorage.getItem('elichika.viewer.rimlight.v1') }; }); }
function noRimlight(state, fitFull = false) {
  assert.strictEqual(state.last.render.material.rimlightEnabled, false, 'thumbnail shader disables rimlight');
  assert(state.receipts.every(receipt => receipt.quality.rimlight === false), 'every receipt binds the rimlight-free material profile');
  assert(state.receipts.every(receipt => receipt.quality.subject === (fitFull?'full-character-v1':'head-and-upper-body-v1')), 'framing choice participates in every thumbnail binding');
  const render=state.last.render,b=render.subjectBounds;
  assert.equal(render.framing.mode,fitFull?'full-character':'head-and-upper-body');
  assert.equal(render.framing.fitFullCharacter,fitFull);
  assert(b.left>0&&b.top>0&&b.right<state.last.size-1&&b.bottom<state.last.size&&(!fitFull||b.bottom<state.last.size-1),'head and sides retain image padding; full mode also includes the feet');
}
function savedMatchesMain(render, rig, exactOperations) {
  const actual = render.savedNodes;
  assert(actual && actual.operations.length, 'thumbnail applies verified saved settings');
  if (exactOperations) {
    const key = op => op.node + ':' + op.kind;
    const clean = ops => ops.map(op => ({ node: String(op.node), kind: op.kind, value: op.value })).sort((a, b) => key(a).localeCompare(key(b)));
    assert.deepStrictEqual(clean(actual.operations), clean(rig.savedNodes.operations));
  }
  for (const op of actual.operations) {
    const node = actual.nodes.find(n => n.node === op.node), live = rig.bones.find(n => String(n.node) === op.node);
    assert(node && live, 'actual saved endpoint has a main-viewer source node');
    const field = op.kind === 'rotation' ? 'quaternion' : op.kind === 'scale' ? 'scale' : 'position';
    node[field].forEach((v, i) => assert(Math.abs(v - live[field][i]) < 1e-6, 'main and thumbnail ' + op.node + '.' + field));
  }
}
async function submitTool(page, toolId = 'costume_packer') {
  let answer = null, failure = null;
  page.waitForResponse(r => r.url().endsWith('/api/run/'+toolId), { timeout: 60000 }).then(r => r.json()).then(r => { answer = r; }, e => { failure = e; });
  await page.locator('#tool-form .run-btn').click();
  for (let i = 0; i < 1200; i++) {
    if (answer) { assert(answer.job_id, JSON.stringify(answer)); return answer; }
    if ((await page.locator('#console-title').textContent()).includes('error')) throw new Error(await page.locator('#log').textContent());
    if (failure) throw failure;
    await sleep(50);
  }
  throw new Error('No tool submission: ' + await page.locator('#log').textContent());
}
async function main() { const report = { status: 'RUNNING', evidence, cases: [] }; let server, browser, context;
  try {
    server = await start(); browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1050 } }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const page = await context.newPage(), errors = []; page.on('pageerror', e => errors.push(String(e.stack || e))); page.setDefaultTimeout(90000);
    await page.goto(server.url); await page.waitForFunction(() => typeof selectTool === 'function' && window.ViewerThumbnails);
    await page.evaluate(() => selectTool('costume_packer'));
    await page.locator('#f_in_path').fill(source); await page.locator('#f_out_dir').fill(output); await page.locator('#f_auto_chara_id').uncheck(); await page.locator('#f_manual_chara_id').fill('6');
    await page.locator('#f_thumbnail_mode').selectOption('3d');
    const job = await submitTool(page);
    await page.waitForFunction(() => /done|error/.test(document.getElementById('console-title').textContent));
    assert((await page.locator('#console-title').textContent()).includes('done'), await page.locator('#log').textContent());
    const toolState = await page.evaluate(() => ViewerThumbnails.getState()); assert.equal(toolState.last.characterId, 6); assert(toolState.last.render.subjectPixels > 0 && toolState.last.render.quality.enabled && toolState.last.render.quality.ready); noRimlight(toolState);
    const zip = fs.readdirSync(output).find(n => n.endsWith('.zip')); assert(zip);
    const packaged = inspectZip(path.join(output, zip), path.join(evidence, 'tool-thumbnail.png')); assert.equal(packaged.sha256, toolState.last.receipt.sha256); assert.equal(packaged.modelSha, original); assert.deepStrictEqual(packaged.size, [256, 256]);
    assert.equal(packaged.member, 6); assert.equal(sha(fs.readFileSync(source)), original); assert.equal((await page.evaluate(() => ModelViewer.getState())).loaded, false, 'hidden render never loads the main viewer');
    report.cases.push({ name: 'real Tools option→automatic high-quality render→installer ZIP', state: toolState, packaged });
    assert.equal(await page.locator('#f_thumbnail_fit_full').isChecked(),false,'whole-character framing starts off');
    const fullPackerOutput=path.join(output,'full-packer');fs.mkdirSync(fullPackerOutput);
    await page.locator('#f_out_dir').fill(fullPackerOutput);await page.locator('#f_thumbnail_fit_full').check();await submitTool(page);
    await page.waitForFunction(()=>/done|error/.test(document.getElementById('console-title').textContent));assert((await page.locator('#console-title').textContent()).includes('done'),await page.locator('#log').textContent());
    const fullPacker=await page.evaluate(()=>ViewerThumbnails.getState());noRimlight(fullPacker,true);assert.notEqual(fullPacker.last.receipt.cacheKey,toolState.last.receipt.cacheKey);
    const fullPacked=inspectZip(path.join(fullPackerOutput,fs.readdirSync(fullPackerOutput).find(n=>n.endsWith('.zip'))),path.join(evidence,'tool-full-thumbnail.png'));
    assert.equal(fullPacked.sha256,fullPacker.last.receipt.sha256);assert.equal(fullPacked.modelSha,original);
    report.cases.push({name:'actual Packer whole-character checkbox opt-in and separate source-bound installer PNG',state:fullPacker,packaged:fullPacked});
    await page.locator('#f_thumbnail_fit_full').uncheck();await page.locator('#f_out_dir').fill(output);
    const existing = path.join(output, zip), secondExisting = path.join(output, 'second-existing.zip'); fs.copyFileSync(existing, secondExisting);
    for (const mode of ['single', 'multi']) {
      const update = await page.evaluate(async ({ mode, paths, output }) => {
        await ViewerThumbnails.prepareUpdater({ mode, in_path: paths[0], in_paths: paths.join('\n'), out_dir: output, thumbnail_size: '256', variant: 'auto' });
        return ViewerThumbnails.getState();
      }, { mode, paths: [existing, secondExisting], output: path.join(output, 'updated') });
      noRimlight(update); assert.equal(update.receipts.length, mode === 'single' ? 1 : 2);
      report.cases.push({ name: 'existing Mod thumbnail ' + mode + ' uses the shared rimlight-free high-quality renderer', state: update });
    }
    assert.equal(sha(fs.readFileSync(existing)), sha(fs.readFileSync(secondExisting)), 'thumbnail replacement preparation preserves original ZIP bytes');
    fs.unlinkSync(secondExisting);
    const alternate = await page.evaluate(async source => { const params = { mode: 'single', in_path: source, out_dir: '', auto_chara_id: false, manual_chara_id: '201', thumbnail_size: '256', combine_pairs: true, thumbnail_mode: '3d' };
      const result = await ViewerThumbnails.preparePacker(params); return { result, state: ViewerThumbnails.getState() }; }, source);
    assert.notEqual(alternate.state.last.receipt.sha256, toolState.last.receipt.sha256); assert.notEqual(alternate.state.last.receipt.cacheKey, toolState.last.receipt.cacheKey); assert.equal(alternate.state.last.characterId, 201);
    report.cases.push({ name: 'recipient member changes template/cache without touching source', state: alternate.state });
    const batch = path.join(input, 'batch'), batchOutput = path.join(output, 'batch'), selectedOutput = path.join(output, 'selected'); fs.mkdirSync(batch, { recursive: true }); fs.mkdirSync(batchOutput); fs.mkdirSync(selectedOutput);
    execFileSync(python, ['-c', `import sys;from pathlib import Path;import UnityPy
sys.path.insert(0,'tests');from test_model_viewer import unity_bundle
raw=Path(sys.argv[1]).read_bytes();root=Path(sys.argv[2])
for name,platform in [('006set_apk.unity',13),('006set_ios.unity',9),('006other_apk.unity',13)]:
 e=UnityPy.load(raw);e.file._m_target_platform=platform;(root/name).write_bytes(unity_bundle([('CAB-thumbnail',e.file.save())]))`, source, batch], { cwd: product });
    const batchHashes = Object.fromEntries(fs.readdirSync(batch).map(n => [n, sha(fs.readFileSync(path.join(batch, n)))]));
    await page.getByRole('button', { name: 'Batch folder', exact: true }).click(); await page.locator('#f_in_dir').fill(batch); await page.locator('#f_out_dir').fill(batchOutput);
    await page.locator('#f_auto_chara_id').uncheck(); await page.locator('#f_manual_chara_id').fill('6'); await page.locator('#f_thumbnail_mode').selectOption('3d'); await page.locator('#f_combine_pairs').check();
    await submitTool(page);
    await page.waitForFunction(() => /done|error/.test(document.getElementById('console-title').textContent)); assert((await page.locator('#console-title').textContent()).includes('done'), await page.locator('#log').textContent());
    const batchState = await page.evaluate(() => ViewerThumbnails.getState()), batchZips = fs.readdirSync(batchOutput).filter(n => n.endsWith('.zip')); assert.equal(batchState.receipts.length, 2, 'Android+iOS pair renders its primary only'); assert.equal(batchZips.length, 2); noRimlight(batchState);
    const batchPackages = batchZips.map((name, i) => inspectZip(path.join(batchOutput, name), path.join(evidence, 'batch-' + i + '.png')));
    for (const pack of batchPackages) { assert(batchState.receipts.some(r => r.sha256 === pack.sha256 && r.characterId === pack.member && r.sources.some(s => s.sha256 === pack.modelSha))); if (pack.iosSha) assert(batchState.receipts.some(r => r.sha256 === pack.sha256 && r.sources.some(s => s.sha256 === pack.iosSha))); }
    assert(batchPackages.some(p => p.iosSha === batchHashes['006set_ios.unity'])); report.cases.push({ name: 'batch Android+iOS grouping uses one primary render per ZIP and binds all source files', state: batchState, packages: batchPackages });
    await page.getByRole('button', { name: 'Selected files', exact: true }).click(); const selected = [path.join(batch, '006set_apk.unity'), path.join(batch, '006other_apk.unity')];
    await page.locator('#tool-form [data-name="in_paths"]').evaluate((e, paths) => { e.value = paths.join('\n'); e.dispatchEvent(new Event('change', { bubbles: true })); }, selected);
    await page.locator('#f_out_dir').fill(selectedOutput); await page.locator('#f_auto_chara_id').uncheck(); await page.locator('#f_manual_chara_id').fill('6'); await page.locator('#f_thumbnail_mode').selectOption('3d');
    await submitTool(page);
    await page.waitForFunction(() => /done|error/.test(document.getElementById('console-title').textContent)); assert((await page.locator('#console-title').textContent()).includes('done'), await page.locator('#log').textContent());
    const multiState = await page.evaluate(() => ViewerThumbnails.getState()), multiZips = fs.readdirSync(selectedOutput).filter(n => n.endsWith('.zip')); assert.equal(multiState.receipts.length, 2); assert.equal(multiZips.length, 2);
    multiZips.forEach((name, i) => { const zip = inspectZip(path.join(selectedOutput, name), path.join(evidence, 'selected-' + i + '.png')); assert(multiState.receipts.some(r => r.sha256 === zip.sha256 && r.sources.some(s => s.sha256 === zip.modelSha))); });
    assert.deepStrictEqual(Object.fromEntries(fs.readdirSync(batch).map(n => [n, sha(fs.readFileSync(path.join(batch, n)))])), batchHashes); report.cases.push({ name: 'Selected files shares source-bound render receipts with actual single subruns', state: multiState });
    const fullUpdaterOutput=path.join(output,'full-updater');fs.mkdirSync(fullUpdaterOutput);const existingHash=sha(fs.readFileSync(existing));
    await page.evaluate(()=>selectTool('costume_thumbnail_replace'));await page.locator('#f_in_path').fill(existing);await page.locator('#f_out_dir').fill(fullUpdaterOutput);
    assert.equal(await page.locator('#f_thumbnail_fit_full').isChecked(),false,'updater whole-character framing also starts off');
    await page.locator('#f_thumbnail_fit_full').check();await submitTool(page,'costume_thumbnail_replace');
    await page.waitForFunction(()=>/done|error/.test(document.getElementById('console-title').textContent));assert((await page.locator('#console-title').textContent()).includes('done'),await page.locator('#log').textContent());
    const fullUpdater=await page.evaluate(()=>ViewerThumbnails.getState());noRimlight(fullUpdater,true);
    const fullUpdated=inspectZip(path.join(fullUpdaterOutput,fs.readdirSync(fullUpdaterOutput).find(n=>n.endsWith('.zip'))),path.join(evidence,'updater-full-thumbnail.png'));
    assert.equal(fullUpdated.sha256,fullUpdater.last.receipt.sha256);assert.equal(fullUpdated.modelSha,original);assert.equal(sha(fs.readFileSync(existing)),existingHash);
    report.cases.push({name:'actual existing-Mod updater whole-character checkbox creates new full-framed copy',state:fullUpdater,packaged:fullUpdated});
    await page.evaluate(source => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([source]); }, source);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
    await (await show(page, '#viewer-rimlight')).check();
    assert.strictEqual((await page.evaluate(() => ModelViewer.getState())).materials.rimlightEnabled, true, 'live viewer uses the selected lighting preference');
    savedMatchesMain(toolState.last.render, (await page.evaluate(() => ModelViewer.getState())).rig, true);
    await page.evaluate(() => { const m = ModelViewer.getEditingMetadata(), node = m.nodes.find(n => n.name === 'BreastSize') || m.nodes.find(n => n.methods.includes('node')); const s = ModelViewer.getAuthoringState(); s.edits = [{ node: node.node, method: 'node', scale: node.baseline.scale.map((v, i) => i === 0 ? v * 1.1 : v) }]; ModelViewer.restoreAuthoringState(s); });
    const fitApi = await page.evaluate(async () => {
      const state = ModelViewer.getAuthoringState(); delete state.unsupported;
      const request = { kind: 'viewer', token: ModelViewer.getEditingMetadata().token, state, character_id: 6, counterpart_path: '', selected_variant: 'apk', include_face_edits: false }, results = [];
      for (const fit of [false, true, 'true', 1, null]) {
        const response = await fetch('/api/viewer/thumbnail/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({}, request, { thumbnail_fit_full: fit })) });
        results.push({ fit, status: response.status, data: await response.json() });
      }
      const response = await fetch('/api/viewer/thumbnail/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({}, request, { thumbnail_fit_full: false, unexpected: true })) });
      results.push({ unknown: true, status: response.status, data: await response.json() }); return results;
    });
    assert.equal(fitApi[0].status,200,JSON.stringify(fitApi[0]));assert.equal(fitApi[1].status,200,JSON.stringify(fitApi[1]));
    assert.equal(fitApi[0].data.quality.subject,'head-and-upper-body-v1');assert.equal(fitApi[1].data.quality.subject,'full-character-v1');
    assert.notEqual(fitApi[0].data.items[0].cacheKey,fitApi[1].data.items[0].cacheKey);
    for(const result of fitApi.slice(2,5)){assert.equal(result.status,400);assert.match(result.data.error,/full character/);}
    assert.equal(fitApi[5].status,400);assert.equal(fitApi[5].data.error,'Unsupported editing request.');
    report.cases.push({name:'actual viewer framing API accepts only true/false and rejects unknown request fields',results:fitApi});
    await (await show(page, '#viewer-mod-character')).selectOption('6'); await (await show(page, '#viewer-mod-thumbnail-mode')).selectOption('3d');
    const before = await untouched(page); await (await show(page, '#viewer-save-mod')).click();
    await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && ['done', 'error'].includes(p.status); });
    const p = (await page.evaluate(() => ModelViewer.getState())).persistence; assert.equal(p.status, 'done', p.error);
    const live = await page.evaluate(() => ViewerThumbnails.getState()), after = await untouched(page); assert.deepStrictEqual(after, before, 'automatic thumbnail never changes camera, pose, body, physics, visibility, motion library or live rimlight preference'); noRimlight(live);
    savedMatchesMain(live.last.render, (await page.evaluate(() => ModelViewer.getState())).rig, false);
    assert(p.modPackage.thumbnail && p.modPackage.thumbnail.sha256 === live.last.receipt.sha256); assert.equal(p.modPackage.thumbnail.characterId, 6);
    const saved = inspectZip(p.modPackage.packagePath, path.join(evidence, 'viewer-thumbnail.png')); assert.equal(saved.sha256, live.last.receipt.sha256); assert.equal(saved.thumbnail, p.modPackage.thumbnail.member); assert.notEqual(saved.modelSha, original, 'actual exported edits are represented by the thumbnail model');
    await page.screenshot({ path: path.join(evidence, 'viewer-option-and-preview.png') }); report.cases.push({ name: 'actual edited viewer→3D thumbnail→saved ModZIP, isolated inspection state', thumbnail: live, saved, package: p.modPackage });
    assert.equal(await page.locator('#viewer-mod-thumbnail-fit-full').isChecked(),false,'viewer whole-character framing starts off');
    await (await show(page,'#viewer-mod-thumbnail-fit-full')).check();const beforeFullViewer=await untouched(page);
    await (await show(page,'#viewer-save-mod')).click();await page.waitForFunction(()=>{const p=ModelViewer.getState().persistence;return !p.busy&&['done','error'].includes(p.status);});
    const fullViewerPersistence=await page.evaluate(()=>ModelViewer.getState().persistence);assert.equal(fullViewerPersistence.status,'done',fullViewerPersistence.error);
    const fullViewer=await page.evaluate(()=>ViewerThumbnails.getState());noRimlight(fullViewer,true);assert.notEqual(fullViewer.last.receipt.cacheKey,live.last.receipt.cacheKey);
    assert.deepStrictEqual(await untouched(page),beforeFullViewer);assert.equal(fullViewerPersistence.modPackage.thumbnail.sha256,fullViewer.last.receipt.sha256);
    await (await show(page,'#viewer-mod-thumbnail-fit-full')).uncheck();
    report.cases.push({name:'actual viewer whole-character checkbox saves full-framed installer while keeping live scene and face-export option independent',state:fullViewer,package:fullViewerPersistence.modPackage});
    if (fs.existsSync('/workspace/scratch/game-motion-real/ayumu-body.unity')) {
      const body = path.join(input, 'ayumu-body.unity'), face = path.join(input, 'ayumu-face.unity'); fs.copyFileSync('/workspace/scratch/game-motion-real/ayumu-body.unity', body); fs.copyFileSync('/workspace/scratch/game-motion-real/ayumu-face.unity', face);
      const hashes = [body, face].map(p => sha(fs.readFileSync(p)));
      const actual = await page.evaluate(async body => { let png; const result = await ViewerThumbnails.preparePacker({ mode: 'single', in_path: body, auto_chara_id: false, manual_chara_id: '201', thumbnail_size: '256', combine_pairs: true }, { onPreview: image => { png = image; } }); return { result, state: ViewerThumbnails.getState(), png }; }, body);
      fs.writeFileSync(path.join(evidence, 'ayumu-costume.png'), Buffer.from(actual.png.split(',')[1], 'base64')); delete actual.png;
      assert(actual.state.last.render.triangles > 1000 && actual.state.last.render.subjectPixels > 1000 && actual.state.last.render.material.recognizedMaterials > 0); noRimlight(actual.state);
      assert(actual.state.last.render.visibleNames.includes('Hair') && actual.state.last.render.visibleNames.includes('Face') && actual.state.last.render.visibleMeshes >= 3, 'original hair and face are rendered with the costume');
      assert(!actual.state.last.render.excludedNames.includes('Hair')&&!actual.state.last.render.excludedNames.includes('Face'),'head roles are never removed from the full-character thumbnail');
      assert.deepStrictEqual([body, face].map(p => sha(fs.readFileSync(p))), hashes); report.cases.push({ name: 'original Ayumu costume, native SDK framing and SIFAS material', actual });
      const fullActual=await page.evaluate(async body=>{let png;await ViewerThumbnails.preparePacker({mode:'single',in_path:body,auto_chara_id:false,manual_chara_id:'201',thumbnail_size:'256',combine_pairs:true,thumbnail_fit_full:true},{onPreview:image=>{png=image;}});return{state:ViewerThumbnails.getState(),png};},body);
      noRimlight(fullActual.state,true);assert(fullActual.state.last.render.camera.top>actual.state.last.render.camera.top,'head-and-upper-costume default is closer than the full-body option');
      assert.notEqual(fullActual.state.last.receipt.cacheKey,actual.state.last.receipt.cacheKey);assert.notEqual(fullActual.state.last.receipt.sha256,actual.state.last.receipt.sha256);
      fs.writeFileSync(path.join(evidence,'ayumu-full-character-option.png'),Buffer.from(fullActual.png.split(',')[1],'base64'));delete fullActual.png;
      report.cases.push({name:'original character head-and-upper default versus opt-in full figure retain head textures and distinct image/cache',fullActual});
      await page.evaluate(paths => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer(paths); }, [body, face]);
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
      const ordinary = await page.evaluate(() => ({ authoring: ModelViewer.getAuthoringState(), rig: ModelViewer.getState().rig }));
      assert.deepStrictEqual(ordinary.authoring.unsupported, [], 'unused Face helper transforms do not block ordinary body saving');
      savedMatchesMain(actual.state.last.render, ordinary.rig, true);
      const bodyNode = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(n => n.name === 'BreastSize'));
      const liveBody = ordinary.rig.bones.find(n => Number(n.node) === bodyNode.node);
      await (await show(page, '#viewer-node-filter')).selectOption('all');
      await (await show(page, '#viewer-node-search')).fill(''); await (await show(page, '#viewer-node')).selectOption(String(bodyNode.node));
      await (await show(page, '#viewer-save-method')).selectOption('node');
      const scaleX = page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]');
      await scaleX.fill(String(liveBody.scale[0] * 1.01)); await scaleX.dispatchEvent('change');
      await (await show(page, '#viewer-save')).click();
      await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && ['done', 'error'].includes(p.status); });
      const rawSaved = await page.evaluate(() => ModelViewer.getState().persistence); assert.equal(rawSaved.status, 'done', rawSaved.error);
      assert.equal(rawSaved.previewPaths.length, 2, 'actual Body and Face copies are saved through the unmodified body-save guard');
      const realBefore = await untouched(page);
      const facial = await page.evaluate(async () => { const metadata = ModelViewer.getEditingMetadata();
        const state = ModelViewer.getAuthoringState(); delete state.unsupported;
        const snapshot = { token: metadata.token, body: state }; let png;
        await ViewerThumbnails.prepareViewer(snapshot, { character_id: 201, counterpart_path: null, selected_variant: null }, { onPreview: image => { png = image; } }); return { ...ViewerThumbnails.getState(), png, liveAuthoring: ModelViewer.getAuthoringState() }; });
      fs.writeFileSync(path.join(evidence, 'ayumu-body-face-complete.png'), Buffer.from(facial.png.split(',')[1], 'base64')); delete facial.png;
      assert(facial.last.render.visibleNames.includes('Mouth')&&facial.last.render.visibleNames.includes('Hair')&&facial.last.render.visibleNames.includes('Face'),'explicit original face, mouth and hair remain rendered');
      assert(facial.last.render.visibleMeshes >= 8 && facial.last.render.excludedNames.length === 0 && facial.last.render.triangles > 1000 && facial.last.render.subjectPixels > 1000, 'complete character and costume survive the actual render');
      noRimlight(facial);
      savedMatchesMain(facial.last.render, (await page.evaluate(() => ModelViewer.getState())).rig, false);
      assert.deepStrictEqual(await untouched(page), realBefore); assert.deepStrictEqual([body, face].map(p => sha(fs.readFileSync(p))), hashes);
      report.cases.push({ name: 'original Body+Face real UI body save, verified saved-shape complete-character render and untouched live scene', facial, rawSaved });
    }
    const abortContext = await browser.newContext({ viewport: { width: 900, height: 700 } }); const abortPage = await abortContext.newPage(); let releaseImage, imageHeld;
    const held = new Promise(resolve => { imageHeld = resolve; }), imageGate = new Promise(resolve => { releaseImage = resolve; });
    await abortPage.route('**/static/thumbnail-sdk/pattern.png', async route => { imageHeld(); await imageGate; try { await route.abort(); } catch (_) {} });
    await abortPage.goto(server.url); await abortPage.waitForFunction(() => window.ViewerThumbnails);
    await abortPage.evaluate(source => { window.__thumbnailAbort = new AbortController(); window.__thumbnailAbortResult = null;
      ViewerThumbnails.preparePacker({ mode: 'single', in_path: source, auto_chara_id: false, manual_chara_id: '6', thumbnail_size: '256' }, { signal: window.__thumbnailAbort.signal }).then(() => { window.__thumbnailAbortResult = 'UNEXPECTED_SUCCESS'; }, e => { window.__thumbnailAbortResult = e.name; }); }, source);
    let holdTimer; try { await Promise.race([held, new Promise((_, reject) => { holdTimer = setTimeout(() => reject(new Error('Template image request was not held')), 30000); })]); } finally { clearTimeout(holdTimer); } const abortAt = Date.now(); await abortPage.evaluate(() => window.__thumbnailAbort.abort());
    await abortPage.waitForFunction(() => window.__thumbnailAbortResult === 'AbortError' && ViewerThumbnails.getState().busy === false, null, { timeout: 5000 });
    const abortElapsed = Date.now() - abortAt; assert(abortElapsed < 4000, 'held Image load cancels promptly'); releaseImage(); await abortContext.close(); report.cases.push({ name: 'cancel while the actual template Image response is held releases renderer busy state', elapsedMs: abortElapsed });
    assert.equal(sha(fs.readFileSync(source)), original); assert.deepStrictEqual(errors, []); report.status = 'PASS';
  } catch (e) { report.status = 'FAIL'; report.error = String(e.stack || e); throw e; }
  finally { if (context) await context.close(); if (browser) await browser.close(); if (server) { server.child.kill(); server.log.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, evidence, error: report.error })); }
}
main().catch(() => { process.exitCode = 1; });
