/* Real viewer/rig plus controlled accessory replies for async race and overlay
 * lifecycle checks. The synthetic replies are not an algorithm accuracy test. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const os = require('os');
const net = require('net');
const crypto = require('crypto');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');

const product = path.resolve(__dirname, '..');
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-accessories-library-'));
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-accessories-evidence-'));
fs.mkdirSync(evidence, { recursive: true });
const report = { status: 'RUNNING', scope: 'Actual neutral Unity/HTTP/WebGL and saved results, plus explicitly controlled replies for seven asynchronous/error tests. No original game playback claim.', cases: [] };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
let server, browser, stream;
async function startServer() {
  const reservation = net.createServer(); await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port; await new Promise(resolve => reservation.close(resolve));
  stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  server = spawn(process.env.VIEWER_PYTHON || 'python3', ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stdout.pipe(stream); server.stderr.pipe(stream);
  const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 100; n++) {
    assert.equal(server.exitCode, null, 'Isolated server remains running');
    try { if ((await fetch(url + '/api/tools')).ok) return url; } catch (_) {}
    await wait(100);
  }
  throw new Error('Isolated server did not become ready');
}
async function show(page, id) {
  const target = page.locator('#' + id);
  await target.evaluate(element => { for (let p = element.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; });
  await target.scrollIntoViewIfNeeded(); return target;
}
async function open(page, file) {
  await page.evaluate(file => openModelViewer([file]), file);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
  await page.waitForTimeout(50);
}
const state = page => page.evaluate(() => ModelViewer.getState());
async function bonePosition(page, node) {
  return page.evaluate(node => ModelViewer.getState().rig.bones.find(bone => String(bone.node) === String(node)).position, node);
}
function pythonJSON(code, args = []) {
  const run = spawnSync(process.env.VIEWER_PYTHON || 'python3', ['-c', code, ...args], { cwd: product, encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
  assert.equal(run.status, 0, run.stderr); return JSON.parse(run.stdout);
}
async function points(page) {
  return page.evaluate(() => {
    const points = []; __accessoryScene.updateMatrixWorld(true);
    __accessoryScene.traverseVisible(mesh => {
      if (!mesh.isSkinnedMesh || mesh.userData.viewerHelper) return;
      mesh.skeleton.update();
      for (let index = 0; index < mesh.geometry.attributes.position.count; index++) {
        const point = new THREE.Vector3().fromBufferAttribute(mesh.geometry.attributes.position, index);
        mesh.boneTransform(index, point); point.applyMatrix4(mesh.matrixWorld); points.push(point.toArray());
      }
    }); return points;
  });
}
function samePoints(left, right, label) {
  assert(left.length > 0, label + ' has visible skinned vertices');
  assert.equal(left.length, right.length, label + ' vertex count');
  assert(left.concat(right).every(point => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite)), label + ' has finite XYZ coordinates');
  const maximum = Math.max(...left.flatMap((point, index) => point.map((value, axis) => Math.abs(value - right[index][axis]))));
  assert(maximum < 4e-5, label + ': ' + maximum); return maximum;
}
function near(actual, expected, message) {
  assert(actual.every((value, axis) => Math.abs(value - expected[axis]) < 1e-7), message + ': ' + JSON.stringify({ actual, expected }));
}

(async () => {
  let page;
  try {
    const models = path.join(library, 'extracted/3d_model'); fs.mkdirSync(models, { recursive: true });
    const first = path.join(models, 'first.unity'), second = path.join(models, 'second.unity');
    fs.copyFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'), first);
    fs.copyFileSync(first, second);
    const url = await startServer();
    browser = await chromium.launch({ headless: true,
      executablePath: process.env.CHROMIUM_EXECUTABLE || (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined),
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.setDefaultTimeout(30000);
    const errors = []; page.on('pageerror', error => errors.push(String(error)));
    await page.route('**/static/viewer-quality.js', async route => {
      const response = await route.fetch(), source = await response.text();
      await route.fulfill({ response, body: source + '\n(()=>{const create=ViewerQuality.create;ViewerQuality.create=function(){const c=create.apply(this,arguments),render=c.render;c.render=function(scene,camera){window.__accessoryScene=scene;return render.apply(this,arguments);};return c;};})();' });
    });
    const pending = []; let active = 0, peak = 0;
    await page.route('**/api/viewer/edit/accessories', async route => {
      const body = route.request().postDataJSON(); active++; peak = Math.max(peak, active);
      const value = await new Promise(resolve => pending.push({ body, resolve }));
      try { await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(value) }); }
      finally { active--; }
    });
    await page.goto(url);
    await page.waitForFunction(() => !!window.ModelViewer && typeof openModelViewer === 'function');
    await page.locator('#viewer-auto-face').evaluate(element => { element.checked = false; });
    await open(page, first);
    const metadata = await page.evaluate(() => ModelViewer.getEditingMetadata());
    const target = metadata.nodes.find(node => node.name === 'HipsSize') || metadata.nodes[0];
    assert(target, 'Real writable fixture node exists');
    const original = await bonePosition(page, target.node);
    function success(strength) { return { corrections: [{ node: target.node, delta: [strength / 10, 0, 0] }], summary: { status: 'applied', changed: 1 } }; }
    async function request(number) {
      for (let n = 0; n < 150 && pending.length < number; n++) await wait(20);
      assert.equal(pending.length, number, 'Exactly the expected request is queued'); return pending[number - 1];
    }
    async function ready() { await page.waitForFunction(() => ModelViewer.getState().accessories.status === 'ready'); }

    await (await show(page, 'viewer-accessory-enabled')).check();
    const one = await request(1);
    assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Save waits for matching preview');
    await page.locator('#viewer-accessory-enabled').uncheck();
    one.resolve(success(1)); await wait(150);
    assert.equal((await state(page)).accessories.enabled, false);
    near(await bonePosition(page, target.node), original, 'Late response after Off cannot move a bone');
    report.cases.push('toggle-off ignores late response');

    await page.locator('#viewer-accessory-enabled').check();
    const two = await request(2);
    await (await show(page, 'viewer-accessory-strength')).fill('1.2');
    await page.locator('#viewer-accessory-strength').fill('1.4');
    await wait(450); assert.equal(pending.length, 2, 'Changes wait for the active server request');
    two.resolve(success(1));
    const three = await request(3); assert.equal(three.body.state.accessoryUnclip.strength, 1.4);
    three.resolve(success(1.4)); await ready();
    near(await bonePosition(page, target.node), [original[0] + .14, original[1], original[2]], 'Only latest desired correction applies');
    assert.equal(peak, 1, 'At most one accessory request is in flight');
    let authored = await page.evaluate(() => ModelViewer.getAuthoringState());
    assert.equal(authored.edits.length, 0, 'Derived offset is not a manual position edit');
    assert.deepEqual(authored.accessoryUnclip, { strength: 1.4, overlap: .15, closeGaps: false });
    report.cases.push('latest intent, one in-flight parse, source-only authoring state');

    await page.evaluate(() => { const state = ModelViewer.getAuthoringState(); for (let n = 0; n < 50; n++) ModelViewer.restoreAuthoringState(state); });
    await ready();
    near(await bonePosition(page, target.node), [original[0] + .14, original[1], original[2]], 'Repeated restore installs one cached overlay');
    assert.equal(pending.length, 3, 'Identical recipe state reuses its verified result');
    await (await show(page, 'viewer-edit-evaluation')).selectOption('animation');
    await page.locator('#viewer-edit-evaluation').selectOption('authoring');
    near(await bonePosition(page, target.node), [original[0] + .14, original[1], original[2]], 'Evaluation switches do not accumulate displacement');
    report.cases.push('50 repeated recipes and evaluation switches remain idempotent');

    await (await show(page, 'viewer-accessory-strength')).fill('4');
    await wait(400); assert.equal(pending.length, 3);
    assert.equal(await page.locator('#viewer-save').isDisabled(), true, 'Invalid advanced input blocks saving');
    await page.locator('#viewer-accessory-strength').fill('1.4'); await ready();
    assert.equal(pending.length, 3, 'Valid unchanged correction reuses cache after invalid draft');
    report.cases.push('invalid numeric draft cannot export the previous valid setting');

    await page.locator('#viewer-accessory-strength').fill('2'); const four = await request(4);
    await (await show(page, 'viewer-preview-reset')).click();
    four.resolve(success(2)); await wait(150);
    assert.equal((await state(page)).accessories.enabled, false);
    near(await bonePosition(page, target.node), original, 'Reset clears config and ignores pending response');
    report.cases.push('reset ignores late response');

    await (await show(page, 'viewer-accessory-enabled')).check(); const five = await request(5);
    const previousId = (await state(page)).modelId;
    await open(page, second); assert.notEqual((await state(page)).modelId, previousId);
    five.resolve(success(1)); await wait(150);
    assert.equal((await state(page)).accessories.enabled, false);
    near(await bonePosition(page, target.node), original, 'Late previous-model reply cannot alter the new rig');
    report.cases.push('model/token replacement ignores late response');

    await (await show(page, 'viewer-accessory-enabled')).check(); const six = await request(6);
    six.resolve({ error: 'The accessory skin cannot be analyzed safely: The costume skin is ambiguous; accessory unclipping cannot choose a renderer.' });
    await page.waitForFunction(() => ModelViewer.getState().accessories.status === 'error');
    for (const id of ['viewer-save', 'viewer-save-mod', 'viewer-add-to-game']) assert.equal(await page.locator('#' + id).isDisabled(), true, 'A failed correction cannot be saved or installed');
    await page.evaluate(() => changeLang('ko'));
    const reason = await page.locator('#viewer-accessory-status').innerText();
    assert(reason.includes('본·가중치') && !reason.includes('The costume'), 'The unsupported reason is localized without discarding its detail');
    await (await show(page, 'viewer-accessory-retry')).click(); const seven = await request(7);
    seven.resolve({ corrections: [], summary: { status: 'no_skin', changed: 0 } });
    await page.waitForFunction(() => ModelViewer.getState().accessories.status === 'error');
    assert((await state(page)).accessories.error.includes('cannot be checked safely'), 'No skin is distinct from nothing to correct');
    assert.equal(await page.locator('#viewer-save').isDisabled(), true);
    await page.locator('#viewer-accessory-enabled').uncheck();
    assert.equal((await state(page)).accessories.error, '');
    report.cases.push('failed or unsupported checks block all exports, retry safely, and localize the reason');
    await page.unroute('**/api/viewer/edit/accessories');

    const actual = pythonJSON(`
import sys,json
from pathlib import Path
sys.path.insert(0,'tests')
from test_model_accessory_unclip import make_fixture
root=Path(sys.argv[1]);result={}
for name,options in [('saved',{}),('unit',{'source_scale':(1.,1.,1.)}),('rotated',{'source_scale':(1.,1.,1.),'rotated_parent':True})]:
 p=root/(name+'.unity');p.write_bytes(make_fixture(**options));result[name]=str(p)
print(json.dumps(result))
`, [models]);
    const hashes = Object.fromEntries(Object.values(actual).map(file => [file, crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')]));
    const inspection = file => pythonJSON(`
import sys,json,hashlib,UnityPy,numpy as np
from sifas_mesh_baker import stream_layout,read_attr
from pathlib import Path
env=UnityPy.load(sys.argv[1]);result={'meshes':[],'uvs':[],'textures':[],'anchors':[]}
names={obj.path_id:obj.read_typetree().get('m_Name') for obj in env.objects if obj.type.name=='GameObject'}
for obj in env.objects:
 if obj.type.name=='Transform':
  tree=obj.read_typetree()
  if names.get(tree['m_GameObject']['m_PathID'])=='PartsA_Offset':result['anchors'].append([tree['m_LocalPosition'][axis] for axis in 'xyz'])
 if obj.type.name=='Mesh':
  tree=obj.read_typetree();count,channels,stride,start,_=stream_layout(tree)
  values=read_attr(np.frombuffer(tree['m_VertexData']['m_DataSize'],np.uint8),4,channels,stride,start,count)
  result['meshes'].append(hashlib.sha256(obj.get_raw_data()).hexdigest());result['uvs'].append(None if values is None else hashlib.sha256(values.tobytes()).hexdigest())
 if obj.type.name=='Texture2D':result['textures'].append(hashlib.sha256(obj.get_raw_data()).hexdigest())
print(json.dumps(result))
`, [file]);
    async function actualCase(label, file, kind) {
      await open(page, file);
      const metadata = await page.evaluate(() => ModelViewer.getEditingMetadata());
      const named = name => { const node = metadata.nodes.find(entry => entry.name === name); assert(node, name); return node; };
      const desired = { version: 1, savedSettingsEnabled: true, edits: [], accessoryUnclip: { strength: 1, overlap: .15, closeGaps: false } };
      if (kind !== 'saved') desired.edits.push({ node: named('BreastSize').node, method: kind === 'mesh' ? 'mesh' : 'node', scale: kind === 'node' ? [2, 2, 2] : [1.8, 1.6, 1.3], compensate: false });
      if (kind === 'mixed') desired.edits.push({ node: named('Move').node, method: 'mesh', scale: [1.3, .85, 1.15], compensate: false });
      if (kind === 'compensated') {
        desired.edits.push({ node: named('Spine2').node, method: 'mesh', scale: [1.3, .8, 1.1], compensate: true,
          compensationTargets: [named('BreastSize').node, named('PartsA_Offset').node] });
        desired.compensationReference = metadata.nodes.map(entry => ({ node: entry.node, ...entry.baseline }));
      }
      await page.evaluate(desired => ModelViewer.restoreAuthoringState(desired), desired);
      await ready();
      let live = await state(page); assert(live.accessories.changed > 0, label + ' changes a real ornament');
      if (kind === 'node') near(live.rig.bones.find(bone => String(bone.node) === String(named('PartsA_Offset').node)).position,
        [-.2616666666666667, .03333333333333333, .045], 'Uniform Node2 uses the analytic original-centroid lift once');
      const before = await points(page), authoring = await page.evaluate(() => ModelViewer.getAuthoringState());
      assert.equal(authoring.edits.length, desired.edits.length, label + ' never serializes derived anchor translations');
      const save = await show(page, 'viewer-save'); assert.equal(await save.isDisabled(), false); await save.click();
      await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.status === 'done');
      live = await state(page); assert(!live.persistence.error, live.persistence.error);
      const saved = live.persistence.previewPaths[0], recipe = JSON.parse(fs.readFileSync(live.persistence.recipePath, 'utf8'));
      assert.deepEqual(recipe.state.accessoryUnclip, desired.accessoryUnclip);
      const initial = inspection(file), edited = inspection(saved);
      if (kind === 'node') near(edited.anchors[0], [.2616666666666667, .03333333333333333, .045], 'Saved Unity anchor is the same once-applied lift with handedness restored');
      assert.deepEqual(edited.textures, initial.textures, label + ' keeps texture bytes');
      assert.deepEqual(edited.uvs, initial.uvs, label + ' keeps UV bytes');
      if (kind === 'saved' || kind === 'node') assert.deepEqual(edited.meshes, initial.meshes, label + ' changes no mesh bytes');
      await (await show(page, 'viewer-open-saved')).click();
      await page.waitForFunction(() => ModelViewer.getState().persistence.reviewingSaved && !ModelViewer.getState().loading);
      const savedError = samePoints(await points(page), before, label + ' exported geometry matches preview');
      await (await show(page, 'viewer-reedit-original')).click();
      await ready();
      await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && !ModelViewer.getState().persistence.reviewingSaved);
      const recipeError = samePoints(await points(page), before, label + ' original plus recipe applies correction once');
      for (const file of Object.values(actual)) assert.equal(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), hashes[file], 'Imported original is immutable');
      report.cases.push({ label, savedError, recipeError, actualCorrectedAnchors: live.accessories.changed });
    }
    await actualCase('real saved-profile accessory-only roundtrip', actual.saved, 'saved');
    await actualCase('real Node edit and accessory roundtrip', actual.unit, 'node');
    await actualCase('real Mesh edit and accessory roundtrip', actual.unit, 'mesh');
    await actualCase('real rotated mixed-parent roundtrip', actual.rotated, 'mixed');
    await actualCase('real directly-compensated anchor roundtrip', actual.unit, 'compensated');
    assert.deepEqual(errors, []);
    report.peakControlledInflight = peak; report.controlledRequests = pending.length; report.pageErrors = errors;
    await (await show(page, 'viewer-accessory-card')).screenshot({ path: path.join(evidence, 'accessory-card.png') });
    report.status = 'PASS';
  } catch (error) {
    report.status = 'FAIL'; report.error = error.stack || String(error);
    if (page) {
      try { report.failure = await state(page); await page.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true }); } catch (_) {}
    }
    process.exitCode = 1;
  } finally {
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    if (browser) await browser.close();
    if (server) server.kill('SIGTERM');
    if (stream) stream.end();
    fs.rmSync(library, { recursive: true, force: true });
    console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence, error: report.error }));
  }
})();
