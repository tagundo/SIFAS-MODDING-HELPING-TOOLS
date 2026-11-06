/* Dedicated body cards through the real HTTP API, DOM, Unity and WebGL skin.
 * No successful model/export response or vertex deformation is mocked. */
const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');

const product = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-body-library-'));
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-body-evidence-'));
fs.mkdirSync(evidence, { recursive: true });
const report = { status: 'RUNNING', scope: 'Host Chromium and real serialized neutral models; not original game playback', cases: [] };
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const files = ['sifas_body_profiles.py', 'sifas_mesh_baker.py', 'webtools/core/charinfo.py', 'webtools/core/model_scaling.py', 'webtools/core/model_edits.py', 'webtools/web/index.html',
  'webtools/i18n.py', 'webtools/web/static/viewer-rig.js', 'webtools/web/static/viewer-editing.js',
  'webtools/web/static/style.css', 'webtools/web/static/platform.js',
  'webtools/web/static/app.js', 'webtools/web/static/viewer-persistence.js'];
const sourceHashes = () => Object.fromEntries(files.map(name => [name, sha(fs.readFileSync(path.join(product, name)))]));
report.sourcesBefore = sourceHashes();
const wait = value => new Promise(resolve => setTimeout(resolve, value));
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const state = page => page.evaluate(() => ModelViewer.getState());
const authoring = page => page.evaluate(() => ModelViewer.getAuthoringState());

function pythonJSON(file, args) {
  const run = spawnSync(python, [path.join(__dirname, file), ...args], { cwd: product, encoding: 'utf8', maxBuffer: 8*1024*1024 });
  assert.equal(run.status, 0, run.stderr); return JSON.parse(run.stdout);
}
function inspect(file) { return pythonJSON('inspect_viewer_persistence.py', [file, '--member', 'body.unity']); }
async function startServer() {
  const reservation = net.createServer(); await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port; await new Promise(resolve => reservation.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: product, env: { ...process.env, SUKUSTA_DIR: temporary }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:'+port;
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw Error('Real product server exited');
    try { if ((await fetch(url+'/api/tools')).ok) return { child, stream, url }; } catch (_) {}
    await wait(100);
  }
  throw Error('Real product server did not start');
}
async function show(page, id) {
  const locator = page.locator('#'+id);
  await locator.evaluate(element => { for (let p = element.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; });
  await locator.scrollIntoViewIfNeeded(); return locator;
}
async function pageFor(browser, url, locale, width=1280, native=false) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: !native });
  const page = await context.newPage(), errors = [];
  page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(String(error)));
  await page.addInitScript(({ lang, native }) => {
    localStorage.setItem('sifas_lang', lang);
    if (native) {
      // Only the OS protocol is stubbed. Model preparation, command bindings,
      // HTTP export and Unity bytes still use the unmodified product.
      window.ElichikaDesktop = { platform: 'macos', version: 1, language: lang, capabilities: [] };
      window.webkit = { messageHandlers: { elichika: { postMessage(message) {
        setTimeout(() => ElichikaPlatform.receive({ id: message.id, result: {} }), 0);
      } } } };
    }
  }, { lang: locale, native });
  // Observe the real scene passed to the unchanged renderer; never build one.
  await page.route('**/static/viewer-quality.js', async route => {
    const response = await route.fetch(), original = await response.text();
    await route.fulfill({ response, body: original+'\n(()=>{const create=ViewerQuality.create;ViewerQuality.create=function(){const c=create.apply(this,arguments),render=c.render;c.render=function(scene,camera){window.__bodyScene=scene;return render.apply(this,arguments);};return c;};})();' });
  });
  await page.goto(url); await page.waitForFunction(() => !!window.ModelViewer && typeof openModelViewer === 'function');
  await page.locator('.tab[data-tab="viewer"]').click();
  await (await show(page, 'viewer-auto-face')).uncheck();
  return { context, page, errors };
}
async function openModel(page, file) {
  await page.evaluate(file => openModelViewer([file]), file);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && !!window.__bodyScene && ModelViewer.getEditingMetadata().available);
  await frames(page);
}
async function group(page, name) { await (await show(page, 'viewer-editor-'+name+'-tab')).click(); }
async function setHipAxes(page, values) {
  await group(page, 'node');
  assert(Array.isArray(values) && values.length === 3, 'Hip controls use actual XYZ endpoints');
  for (let axis = 0; axis < 3; axis++) {
    if (values[axis] === null) continue;
    const input = await show(page, 'viewer-hips-scale-' + 'xyz'[axis]);
    await input.fill(String(values[axis])); await input.dispatchEvent('input');
  }
  const apply = await show(page, 'viewer-hips-apply');
  assert.equal(await apply.isDisabled(), false); await apply.click(); await frames(page);
  const actual = (await state(page)).rig.bodyControls.hips;
  values.forEach((value, axis) => { if (value !== null) assert(Math.abs(actual.axisValues[axis] - value) < 1e-7); });
  return actual;
}
async function setCard(page, kind, percent) {
  if (kind === 'hips') return setHipAxes(page, percent);
  await group(page, kind === 'hips' ? 'node' : 'mesh');
  await (await show(page, 'viewer-'+kind+'-number')).fill(String(percent));
  await page.locator('#viewer-'+kind+'-number').dispatchEvent('input');
  const apply = await show(page, 'viewer-'+kind+'-apply');
  assert.equal(await apply.isDisabled(), false, kind+' card is available'); await apply.click(); await frames(page);
  const value = (await state(page)).rig.bodyControls[kind];
  assert(Math.abs(value.currentPercent-percent) < 1e-5, kind+' reports the requested percentage'); return value;
}
async function skinPoints(page) {
  await frames(page);
  return page.evaluate(() => {
    const result = []; __bodyScene.updateMatrixWorld(true);
    __bodyScene.traverseVisible(mesh => {
      if (!mesh.isSkinnedMesh || mesh.userData.viewerHelper) return;
      for (let n = 0; n < mesh.geometry.attributes.position.count; n++) {
        const p = new THREE.Vector3().fromBufferAttribute(mesh.geometry.attributes.position, n);
        mesh.boneTransform(n, p); p.applyMatrix4(mesh.matrixWorld); result.push(p.toArray());
      }
    }); return result;
  });
}
async function boneMatrices(page) {
  return page.evaluate(() => {
    const frames = {}, names = new Map(ModelViewer.getEditingMetadata().nodes.map(n => [String(n.node), n.name]));
    __bodyScene.updateMatrixWorld(true); __bodyScene.traverse(object => {
      const name = names.get(String(object.userData.elichika_node)); if (name) frames[name] = object.matrixWorld.toArray();
    }); return frames;
  });
}
function maximumDifference(left, right) {
  assert.equal(left.length, right.length);
  return Math.max(...left.flatMap((value, i) => Array.isArray(value) ? value.map((x, n) => Math.abs(x-right[i][n])) : [Math.abs(value-right[i])]));
}
function comparePoints(left, right, label) { const error = maximumDifference(left, right); assert(error < 3e-5, label+': '+error); return error; }
function assertStateNear(left, right, location='recipe') {
  if (typeof left==='number'&&typeof right==='number') { assert(Math.abs(left-right)<1e-10,location+' preserves a numeric endpoint'); return; }
  if (Array.isArray(left)&&Array.isArray(right)) { assert.equal(left.length,right.length,location+' keeps its entries'); left.forEach((v,i)=>assertStateNear(v,right[i],location+'['+i+']')); return; }
  if (left&&right&&typeof left==='object'&&typeof right==='object') { assert.deepEqual(Object.keys(left).sort(),Object.keys(right).sort()); for(const key of Object.keys(left))assertStateNear(left[key],right[key],location+'.'+key); return; }
  assert.deepEqual(left,right,location);
}
async function save(page) {
  const button = await show(page, 'viewer-save'); assert.equal(await button.isDisabled(), false); await button.click();
  await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ModelViewer.getState().persistence.outputPaths.length > 0);
  const result = (await state(page)).persistence; assert(!result.error, result.error); return result;
}
async function targetGeometry(page, id) {
  const locator = await show(page, id);
  return locator.evaluate(element => {
    const r = element.getBoundingClientRect(), top = document.elementFromPoint(r.left+r.width/2, r.top+r.height/2);
    return { width:r.width, height:r.height, visible:r.width>0&&r.height>0, hit:top===element||element.contains(top), within:r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1 };
  });
}
async function selectAdvanced(page, name) {
  const metadata = await page.evaluate(() => ModelViewer.getEditingMetadata()), node = metadata.nodes.find(n => n.name === name);
  await group(page, node.recommendedMethod === 'mesh' ? 'mesh' : 'node');
  await (await show(page, 'viewer-node-filter')).selectOption('all');
  await (await show(page, 'viewer-node')).selectOption(String(node.node)); return node;
}

function makeSavedHipFixture(source, destination) {
  const code = `
from pathlib import Path
import hashlib,json,sys,UnityPy
from webtools.core import model_edits
raw=Path(sys.argv[1]).read_bytes();info=model_edits._inspect(raw)
hips=[key for key,name in info['names'].items() if name=='HipsSize'];assert len(hips)==1
environment=UnityPy.load(raw)
component=next(obj for obj in environment.objects if obj.type.name=='MonoBehaviour')
tree=component.read_typetree()
tree['scaleValues'].append({'target':{'m_FileID':0,'m_PathID':hips[0][1]},
    'originValue':dict(info['transforms'][hips[0]]['m_LocalScale']),
    'scaledValue':{'x':1.,'y':.95,'z':.95}})
component.save_typetree(tree);raw=environment.file.save();Path(sys.argv[2]).write_bytes(raw)
checked=model_edits._inspect(raw);key=next(key for key,name in checked['names'].items() if name=='HipsSize')
assert checked['effective'][key]['scale']==[1.,.949999988079071,.949999988079071]
print(json.dumps({'path':sys.argv[2],'sha256':hashlib.sha256(raw).hexdigest(),
    'savedHipScale':checked['effective'][key]['scale'],'authoredHipScale':checked['authored'][key]['scale']}))
`;
  const result = spawnSync(python, ['-B', '-c', code, source, destination], { cwd: product, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr); return JSON.parse(result.stdout);
}

async function exerciseNonunitHipNativeGuard(browser, url, fixture) {
  const sample = await pageFor(browser, url, 'ko', 1280, true), { page } = sample;
  const requests = [];
  page.on('request', request => {
    const endpoint = new URL(request.url()).pathname;
    if (['/api/viewer/edit/export', '/api/viewer/edit/package', '/api/viewer/edit/install'].includes(endpoint))
      requests.push({ endpoint, body: request.postDataJSON() });
  });
  try {
    assert.equal(await page.evaluate(() => ElichikaPlatform.info().native), true);
    await openModel(page, fixture.path);
    const metadata = await page.evaluate(() => ModelViewer.getEditingMetadata());
    const hips = metadata.nodes.find(node => node.name === 'HipsSize');
    assert.deepEqual(hips.baseline.scale, fixture.savedHipScale);
    assert.deepEqual(fixture.savedHipScale, [1, .949999988079071, .949999988079071]);
    assert.equal(await page.locator('#viewer-hips-card').evaluate(element => element.open), true,
      'Actual nonunit Y/Z keeps the card open, even at100% of the saved shape');
    await setHipAxes(page, [1.2, null, null]);
    const onlyX = (await state(page)).rig.nodeAdjustments[String(hips.node)];
    assert.deepEqual(onlyX.scale, [1.2, null, null], 'Only the dirtied X becomes a new endpoint');
    const resolved = (await authoring(page)).edits.find(edit => edit.node === hips.node);
    assert.strictEqual(resolved.scale[1], fixture.savedHipScale[1]);
    assert.strictEqual(resolved.scale[2], fixture.savedHipScale[2]);
    assert((await page.locator('#viewer-mod-name').inputValue()).includes('X1.2/Y0.95/Z0.95'));
    await selectAdvanced(page, 'HipsSize');
    await (await show(page, 'viewer-save-method')).selectOption('node');
    await show(page, 'viewer-node-fields');
    for (const [kind, axis, value] of [['position', 'Y', '.1234567'], ['rotation', 'Z', '12.34567']]) {
      const input = page.locator('input[data-viewer-node-kind="'+kind+'"][data-axis="'+axis+'"]');
      await input.fill(value); await input.dispatchEvent('change');
    }
    const other = await selectAdvanced(page, 'LeftUpLeg');
    await (await show(page, 'viewer-save-method')).selectOption('mesh');
    await show(page, 'viewer-node-fields');
    const meshField = page.locator('input[data-viewer-node-kind="scale"][data-axis="Z"]');
    await meshField.fill('1.145'); await meshField.dispatchEvent('change');
    await group(page, 'node');
    await (await show(page, 'viewer-mod-character')).selectOption('6');
    assert.deepEqual(await page.evaluate(() => ['viewer-save', 'viewer-save-mod', 'viewer-add-to-game'].map(id => document.getElementById(id).disabled)),
      [false, false, false], 'All three save routes are available before an invalid Hip draft');
    const beforeInvalid = (await authoring(page)).edits, negatives = [];
    assert.equal(requests.length, 0);
    for (const text of ['0', '', '1e309']) {
      const input = await show(page, 'viewer-hips-scale-y');
      await input.fill(text); await input.dispatchEvent('input');
      await (await show(page, 'viewer-hips-scale-z')).focus(); await frames(page);
      const invalid = await page.evaluate(() => ({ raw: document.getElementById('viewer-hips-scale-y').value,
        dirty: document.getElementById('viewer-hips-scale-y').dataset.viewerHipsDirty,
        invalid: document.getElementById('viewer-hips-scale-y').getAttribute('aria-invalid'),
        disabled: ['viewer-save', 'viewer-save-mod', 'viewer-add-to-game'].map(id => document.getElementById(id).disabled) }));
      assert.equal(invalid.dirty, 'true'); assert.equal(invalid.invalid, 'true'); assert(invalid.disabled.every(Boolean));
      assert((await authoring(page)).unsupported.some(message => /invalid/i.test(message)));
      assert.deepEqual((await authoring(page)).edits, beforeInvalid, 'Invalid drafts preserve the last valid edit');
      assert.strictEqual(await page.evaluate(() => ElichikaPlatform.perform('saveModel')), true);
      await page.keyboard.press('Meta+s'); await wait(200);
      assert.equal(requests.length, 0, 'Production native command/Cmd-S must not export stale values');
      const retained = await page.evaluate(() => ({ raw: document.getElementById('viewer-hips-scale-y').value,
        dirty: document.getElementById('viewer-hips-scale-y').dataset.viewerHipsDirty,
        invalid: document.getElementById('viewer-hips-scale-y').getAttribute('aria-invalid') }));
      assert.deepEqual(retained, { raw: invalid.raw, dirty: 'true', invalid: 'true' });
      negatives.push({ requested: text, actualRaw: invalid.raw, commandsAcknowledged: true, requests: 0 });
    }
    // A different advanced save method disables the simple Hip inputs. That
    // must not turn a retained invalid draft into permission to export stale
    // values, including through the native shortcut's pre-blur guard.
    await selectAdvanced(page, 'HipsSize');
    await (await show(page, 'viewer-save-method')).selectOption('mesh');
    const disabledDraft = await page.evaluate(() => ({
      disabled: document.getElementById('viewer-hips-scale-y').disabled,
      dirty: document.getElementById('viewer-hips-scale-y').dataset.viewerHipsDirty,
      invalid: document.getElementById('viewer-hips-scale-y').getAttribute('aria-invalid'),
      saveDisabled: ['viewer-save', 'viewer-save-mod', 'viewer-add-to-game'].map(id => document.getElementById(id).disabled),
      unsupported: ModelViewer.getAuthoringState().unsupported
    }));
    assert(disabledDraft.disabled); assert.equal(disabledDraft.dirty, 'true'); assert.equal(disabledDraft.invalid, 'true');
    assert(disabledDraft.unsupported.some(message => /invalid/i.test(message)));
    assert(disabledDraft.saveDisabled.every(Boolean), 'Changing method must not bypass the invalid Hip draft');
    assert.strictEqual(await page.evaluate(() => ElichikaPlatform.perform('saveModel')), true);
    await page.keyboard.press('Meta+s'); await wait(200);
    assert.equal(requests.length, 0, 'A disabled but dirty invalid Hip field still blocks the real native command');
    await (await show(page, 'viewer-save-method')).selectOption('node');
    assert((await authoring(page)).unsupported.some(message => /invalid/i.test(message)));
    await setHipAxes(page, [null, .9555000066757202, null]);
    assert.deepEqual((await authoring(page)).unsupported, []);
    const actualName = await page.locator('#viewer-mod-name').inputValue();
    assert(actualName.includes('X1.2/Y0.9555/Z0.95'), 'Hip naming uses actual XYZ endpoints');
    const fractionalStepMismatch = await page.locator('#viewer-hips-scale-y').evaluate(input => input.validity.stepMismatch);
    assert.equal(await page.locator('#viewer-save').isDisabled(), false);
    assert.strictEqual(await page.evaluate(() => ElichikaPlatform.perform('saveModel')), true);
    await page.waitForFunction(() => {
      const p = ModelViewer.getState().persistence;
      return p.jobId && !p.busy && !p.error && p.previewPaths.length === 1 && p.outputs.length >= 2;
    });
    assert.equal(requests.length, 1, 'Correct and Apply is a positive control for the same native command');
    assert.equal(requests[0].endpoint, '/api/viewer/edit/export');
    const saved = (await state(page)).persistence, output = inspect(saved.previewPaths[0]);
    const entries = output.components.flatMap(component => component.entries);
    const endpoint = entries.find(entry => entry.target === 'HipsSize' && entry.kind === 'scale').scaled;
    assert(Math.abs(endpoint[0] - 1.2) < 1e-6); assert(Math.abs(endpoint[1] - .9555000066757202) < 1e-8);
    assert.strictEqual(endpoint[2], fixture.savedHipScale[2], 'Untouched saved Z remains bit-exact in real Unity output');
    const beforeReset = (await authoring(page)).edits;
    await (await show(page, 'viewer-hips-reset')).click(); await frames(page);
    const afterReset = (await authoring(page)).edits;
    const oldHip = beforeReset.find(edit => edit.node === hips.node), resetHip = afterReset.find(edit => edit.node === hips.node);
    assert(resetHip && !resetHip.scale); assert.deepEqual(resetHip.position, oldHip.position); assert.deepEqual(resetHip.rotation, oldHip.rotation);
    assert.equal(resetHip.method, oldHip.method);
    assert.deepEqual(afterReset.find(edit => edit.node === other.node), beforeReset.find(edit => edit.node === other.node));
    assert.equal((await state(page)).rig.editingMethods[String(other.node)], 'mesh');
    assert.deepEqual((await state(page)).rig.bodyControls.hips.axisValues, fixture.savedHipScale);
    assert.equal(sha(fs.readFileSync(fixture.path)), fixture.sha256); assert.deepEqual(sample.errors, []);
    return { label: 'nonunit-saved-hip-native-command-guard', scope: 'Mac protocol stub only; real DOM/HTTP/Unity export',
      fixture, negatives, disabledDraftStillBlocks: disabledDraft, actualName, fractionalStepMismatch, actualSavedEndpoint: endpoint, positiveExportRequests: requests.length,
      untouchedAxesBitExact: true, sourcePreserved: true, resetKeepsHipTRSAndOtherMeshMethod: true };
  } finally { await sample.context.close(); }
}

async function exerciseThighPresets(browser, url, archive, original, hashBefore) {
  const sample = await pageFor(browser, url, 'ko'), { page } = sample;
  try {
    await openModel(page, archive); await group(page, 'mesh');
    const metadata = await page.evaluate(() => ModelViewer.getEditingMetadata());
    const control = (await state(page)).rig.scaling.controls.find(c => c.id === 'thighs');
    assert.equal(control.presets.length, 6, 'All existing explicit source/target transitions are available');
    assert.equal(control.presetSourceRequired, true);
    assert.equal((await state(page)).rig.thighProfile.selected, 'loaded');
    const before = await skinPoints(page), framesBefore = await boneMatrices(page), cases = [];
    const apply = async id => {
      await group(page, 'mesh'); await (await show(page, 'viewer-thighs-preset')).selectOption(id);
      const button = await show(page, 'viewer-thighs-preset-apply'); assert.equal(await button.isDisabled(), false);
      await button.click(); await frames(page);
    };
    for (const profile of control.presets) {
      await apply(profile.id);
      const current = await state(page), authored = await authoring(page), currentFrames = await boneMatrices(page);
      assert.equal(current.rig.thighProfile.selected, profile.id, 'Actual values identify the selected canonical transition');
      assert.equal(current.rig.bodyControls.thighs.currentPercent, null, 'Unequal Y/Z is honestly shown as mixed');
      assert.equal(await page.locator('#viewer-thighs-number').inputValue(), '');
      assert.deepEqual(authored.unsupported, [], 'A mixed preset must remain saveable');
      for (const name of ['LeftUpLeg', 'RightUpLeg']) {
        const node = metadata.nodes.find(n => n.name === name), edit = authored.edits.find(e => e.node === node.node);
        const expected = node.baseline.scale.map((value, axis) => value * profile.scaleDelta[axis]);
        assert(maximumDifference(edit.scale, expected) < 1e-7, 'Canonical unequal factors apply from the original loaded scale');
        assert.equal(current.rig.nodeAdjustments[String(node.node)].scale[0], null, 'Presets do not author X');
        assert.equal(edit.method, 'mesh'); assert.equal(edit.compensate, true); assert(!edit.position && !edit.rotation);
      }
      for (const name of ['LeftLeg', 'LeftFoot', 'RightLeg', 'RightFoot'])
        assert(maximumDifference(currentFrames[name], framesBefore[name]) < 1e-6, 'Full-affine preset compensation preserves '+name);
      const points = await skinPoints(page); assert(maximumDifference(points, before) > .001, 'The transition deforms actual weighted vertices');
      await apply(profile.id); assertStateNear(await authoring(page), authored);
      comparePoints(await skinPoints(page), points, 'Repeated preset Apply does not compound');
      cases.push(profile.id);
    }
    await selectAdvanced(page, 'LeftUpLeg'); await (await show(page, 'bone-compensate-children')).uncheck();
    assert.equal((await state(page)).rig.thighProfile.selected, 'custom', 'Canonical ratios without child compensation are not the complete preset');
    await apply('default:thick');
    const selectedState = await authoring(page);
    await (await show(page, 'viewer-thighs-preset')).selectOption('');
    assert.equal(await page.locator('#viewer-thighs-preset-apply').isDisabled(), true);
    assertStateNear(await authoring(page), selectedState, 'Choosing no transition does not reset edits');
    await setCard(page, 'thighs', 125);
    assert.equal((await state(page)).rig.thighProfile.selected, 'custom', 'Uniform percentage replaces a nonuniform preset');
    const uniform = await authoring(page); await page.locator('#viewer-thighs-preset').selectOption('');
    assertStateNear(await authoring(page), uniform, 'Leaving custom values alone does not reset them');
    const number = await show(page, 'viewer-thighs-number'); await number.fill('0'); await number.dispatchEvent('input');
    assert((await authoring(page)).unsupported.some(text => text.includes('invalid')));
    await apply('default:thick'); assert.deepEqual((await authoring(page)).unsupported, [], 'The replacing preset clears an invalid percentage draft');
    const left = await selectAdvanced(page, 'LeftUpLeg');
    await (await show(page, 'viewer-save-method')).selectOption('node'); await group(page, 'mesh');
    assert.equal(await page.locator('#viewer-thighs-preset').isDisabled(), true, 'Preset must not silently convert an explicit Node edit');
    await selectAdvanced(page, 'LeftUpLeg'); await (await show(page, 'viewer-save-method')).selectOption('mesh');
    await show(page, 'viewer-node');
    await page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]').fill(String(left.baseline.scale[0]*1.1));
    await page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]').dispatchEvent('input');
    assert.equal(await page.locator('#viewer-thighs-preset').isDisabled(), true, 'An advanced length edit must not be silently overwritten');
    await (await show(page, 'viewer-node-reset')).click();
    await selectAdvanced(page, 'LeftUpLeg');
    for (const [kind,axis,value] of [['position','Y','.1234567'],['rotation','Z','12.34567']]) {
      await show(page, 'viewer-node-fields');
      const field = page.locator('input[data-viewer-node-kind="'+kind+'"][data-axis="'+axis+'"]');
      await field.fill(value); await field.dispatchEvent('input');
    }
    const manual = (await authoring(page)).edits.find(e => e.node === left.node);
    await apply('slim:thick');
    const edited = (await authoring(page)).edits.find(e => e.node === left.node);
    assert.deepEqual(edited.position, manual.position); assert.deepEqual(edited.rotation, manual.rotation);
    const expected = await skinPoints(page), firstState = await authoring(page), first = await save(page);
    const output = inspect(first.previewPaths[0]);
    assert.deepEqual(output.transforms, original.transforms, 'Preset saves preserve authored Transform TRS');
    assert.deepEqual(output.archive_entries['notes.txt'], original.archive_entries['notes.txt']);
    await (await show(page, 'viewer-open-saved')).click();
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().persistence.reviewingSaved);
    const reloadError = comparePoints(await skinPoints(page), expected, 'Actual saved preset geometry reloads');
    await (await show(page, 'viewer-reedit-original')).click();
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && !ModelViewer.getState().persistence.busy && !ModelViewer.getState().persistence.reviewingSaved);
    assert.equal((await state(page)).rig.thighProfile.selected, 'slim:thick', 'Recipe re-edit identifies the preset from actual ratios');
    assertStateNear(await authoring(page), firstState); assert.deepEqual((await authoring(page)).unsupported, []);
    const second = await save(page);
    assert.equal(sha(fs.readFileSync(first.previewPaths[0])), sha(fs.readFileSync(second.previewPaths[0])), 'Preset recipe rebuild is byte-identical');
    assert.equal(sha(fs.readFileSync(archive)), hashBefore); assert.deepEqual(sample.errors, []);
    return { label:'exact-tool-thigh-presets', transitions:cases, repeatApplyNoncumulative:true, noneAndCustomPreserveEdits:true,
      percentageAndPresetReplaceEachOther:true, staleInvalidDraftCleared:true, methodAndLengthConflictsBlocked:true,
      positionAndRotationPreserved:true, calfAndFootFramesPreserved:true, sourcePreserved:true, reloadError, recipePresetRestored:true };
  } finally { await sample.context.close(); }
}

(async () => {
  let server, browser;
  try {
    const models = path.join(temporary, 'extracted', '3d_model'); fs.mkdirSync(models, { recursive:true });
    const source = path.join(models, 'neutral-body.unity');
    const originalFixture = pythonJSON('generate_viewer_body_fixture.py', ['--output', source]);
    const archive = path.join(models, 'body-controls.zip');
    const bundle = spawnSync(python, ['-c', 'import sys,zipfile;z=zipfile.ZipFile(sys.argv[2],"w",compression=zipfile.ZIP_DEFLATED);z.write(sys.argv[1],"body.unity");z.writestr("notes.txt",b"Keep this companion exactly.\\n");z.close()', source, archive], { encoding:'utf8' });
    assert.equal(bundle.status, 0, bundle.stderr); const original = inspect(archive);
    const hashBefore = sha(fs.readFileSync(archive)); server = await startServer();
    browser = await chromium.launch({ headless:true, executablePath:process.env.CHROMIUM_EXECUTABLE||undefined,
      args:['--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader'] });
    const opened = await pageFor(browser, server.url, 'ko'), { page } = opened;
    await openModel(page, archive); const baselinePoints = await skinPoints(page), baselineFrames = await boneMatrices(page);
    assert.equal(baselinePoints.length, 57, 'Every body and child group has real weighted vertices');
    const initialCamera = (await state(page)).camera;
    const controls = {};
    for (const kind of ['hips','thighs','waist']) {
      await group(page, kind === 'hips' ? 'node' : 'mesh');
      if (kind === 'hips') {
        const actual = (await state(page)).rig.bodyControls.hips.axisValues;
        actual.forEach((value, axis) => assert(Math.abs(value - [.9, 1.07, .96][axis]) < 1e-6));
      } else assert.equal((await state(page)).rig.bodyControls[kind].currentPercent, 100);
      controls[kind] = await targetGeometry(page, kind === 'hips' ? 'viewer-hips-scale-x' : 'viewer-'+kind+'-number');
      assert(controls[kind].visible&&controls[kind].hit&&controls[kind].within&&controls[kind].height>=44);
    }
    assert((await page.locator('#viewer-hips-card').textContent()).includes('엉덩이 크기'), 'Use buttocks, not pelvis, in Korean');
    assert(!(await page.locator('#viewer-hips-card').textContent()).includes('골반 크기'));
    const hipOriginal = (await page.evaluate(() => ModelViewer.getEditingMetadata())).nodes.find(n => n.name === 'HipsSize');
    await setHipAxes(page, [1.234567, null, null]);
    const oneAxis = (await authoring(page)).edits.find(edit => edit.node === hipOriginal.node);
    assert.deepEqual(oneAxis.scale, [1.234567, hipOriginal.baseline.scale[1], hipOriginal.baseline.scale[2]], 'Untouched non-unit Y/Z preserve exact original precision');
    assert.deepEqual((await state(page)).rig.nodeAdjustments[String(hipOriginal.node)].scale, [1.234567, null, null]);
    await (await show(page, 'viewer-hips-reset')).click();
    assert(!(await authoring(page)).edits.some(edit => edit.node === hipOriginal.node));
    await setCard(page, 'hips', [1.08, 1.284, 1.152]); await setCard(page, 'thighs', 125); await setCard(page, 'waist', 130);
    const firstState = await authoring(page); assert.deepEqual(firstState.unsupported, []); assert.equal(firstState.edits.length, 4);
    for (const kind of ['hips','thighs','waist']) await setCard(page, kind, { hips:[1.08,1.284,1.152], thighs:125, waist:130 }[kind]);
    assert.deepEqual(await authoring(page), firstState, 'Repeated card apply must be noncumulative');
    const metadata = await page.evaluate(() => ModelViewer.getEditingMetadata());
    const editFor = name => firstState.edits.find(e => e.node === metadata.nodes.find(n => n.name === name).node);
    assert.equal(editFor('HipsSize').method, 'node'); assert.equal(editFor('HipsSize').compensate, false);
    for (const name of ['LeftUpLeg','RightUpLeg','Spine']) {
      const edit = editFor(name), target = metadata.nodes.find(n => n.name === name);
      const mask = (await state(page)).rig.nodeAdjustments[String(target.node)];
      assert.equal(edit.method,'mesh'); assert.equal(mask.scale[0],null, name+' does not author length');
      assert.equal(edit.scale[0],target.baseline.scale[0],name+' resolves the untouched original length for export'); assert.equal(edit.compensate,true);
      assert(!edit.position&&!edit.rotation, 'Thickness cards cannot change position or rotation');
    }
    const afterFrames = await boneMatrices(page);
    for (const name of ['Spine2','Head','Head_Hair','LeftArm','LeftForeArm','LeftLeg','LeftFoot','RightLeg','RightFoot'])
      assert(maximumDifference(afterFrames[name], baselineFrames[name])<1e-6, 'Compensation preserves child frame '+name);
    assert(maximumDifference(afterFrames.ButtockTip,baselineFrames.ButtockTip)>.01, 'HipsSize intentionally propagates to its children');
    const expected = await skinPoints(page); assert(maximumDifference(expected,baselinePoints)>.02, 'The cards deform real weighted geometry');
    assert.deepEqual((await state(page)).camera, initialCamera);
    await selectAdvanced(page,'HipsSize'); assert.equal(await page.locator('#bone-compensate-children').isDisabled(),true,'Node compensation is not an available misleading option');
    for (const tool of ['node','mesh']) {
      await group(page,tool);
      const labels = await page.locator('#viewer-node option').allTextContents();
      for (const forbidden of ['HipsSize','BreastSize','LeftUpLeg','RightUpLeg','Spine','LeftHandIndex1','LeftShoulder'])
        assert(!labels.some(label=>label.includes('· '+forbidden)), 'Recommended detail list excludes carded/advanced-only bone '+forbidden);
    }
    const first = await save(page); const output = inspect(first.previewPaths[0]);
    assert.deepEqual(output.transforms,original.transforms,'Every authored position/quaternion/scale is retained');
    assert.deepEqual(output.meshes.map(m=>m.bind_pose_sha256),original.meshes.map(m=>m.bind_pose_sha256));
    assert.deepEqual(output.archive_entries['notes.txt'],original.archive_entries['notes.txt']);
    assert.equal(sha(fs.readFileSync(archive)),hashBefore);
    await (await show(page,'viewer-open-saved')).click();
    await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading&&ModelViewer.getState().persistence.reviewingSaved);
    const reloadError=comparePoints(await skinPoints(page),expected,'Saved hybrid body cards reload');
    await (await show(page,'viewer-reedit-original')).click();
    await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading&&!ModelViewer.getState().persistence.busy&&!ModelViewer.getState().persistence.reviewingSaved&&ModelViewer.getAuthoringState().edits.length===4);
    // Euler -> quaternion -> Euler conversion changes only machine-roundoff
    // in the affine reference; the separate skin comparison checks geometry.
    assertStateNear(await authoring(page),firstState);
    for (const [kind,percent] of Object.entries({hips:[1.08,1.284,1.152],thighs:125,waist:130})) {
      const restoredControl=(await state(page)).rig.bodyControls[kind];
      if (kind === 'hips') percent.forEach((value, axis) => assert(Math.abs(restoredControl.axisValues[axis] - value) < 1e-7));
      else assert(Math.abs(restoredControl.currentPercent-percent)<1e-5);
      assert(restoredControl.available,kind+' remains editable when a recipe explicitly restores its original length');
    }
    const second=await save(page); assert.equal(sha(fs.readFileSync(second.previewPaths[0])),sha(fs.readFileSync(first.previewPaths[0])),'Re-edit/rebuild cannot compound baking');
    // Invalid UI values cannot silently replace an existing valid edit, while
    // spinner steps must not reject valid fractional percentages/source TRS.
    await group(page,'node'); const hipsNumber=await show(page,'viewer-hips-scale-x');
    await hipsNumber.fill('0'); await hipsNumber.dispatchEvent('input');
    assert((await authoring(page)).unsupported.some(text=>text.includes('invalid')));
    assert.equal(await page.locator('#viewer-save').isDisabled(),true);
    await setCard(page,'hips',[1.20125,null,null]); assert.deepEqual((await authoring(page)).unsupported,[]);
    const fractionalStepMismatch=await page.locator('#viewer-hips-scale-x').evaluate(input=>input.validity.stepMismatch);
    await setCard(page,'hips',[1.08,1.284,1.152]);
    // An explicit Node route on a Mesh-recommended target must not be silently
    // reinterpreted by the simple card. Existing compensation has an OFF exit.
    await selectAdvanced(page,'LeftUpLeg'); await (await show(page,'viewer-save-method')).selectOption('node');
    assert.equal((await state(page)).rig.bodyControls.thighs.available,false);
    assert((await state(page)).rig.bodyControls.thighs.reason.includes('method'));
    assert.equal(await page.locator('#bone-compensate-target').isDisabled(),true);
    assert.equal(await page.locator('#bone-compensate-children').isChecked(),true);
    assert.equal(await page.locator('#bone-compensate-children').isDisabled(),false);
    await page.locator('#bone-compensate-children').uncheck();
    assert.equal(await page.locator('#bone-compensate-children').isDisabled(),true);
    await (await show(page,'viewer-save-method')).selectOption('mesh'); await setCard(page,'thighs',125);
    // Reset owns only a card's scale axes, never a manually authored position
    // or Euler endpoint. A changed length axis remains an advanced edit.
    const hipsTarget=await selectAdvanced(page,'HipsSize');
    for(const [kind,axis,value] of [['position','Y','.1234567'],['rotation','Z','12.34567']]) {
      const input=page.locator('input[data-viewer-node-kind="'+kind+'"][data-axis="'+axis+'"]');
      await input.fill(value); await input.dispatchEvent('change');
    }
    const hipsBeforeReset=(await authoring(page)).edits.find(e=>e.node===hipsTarget.node);
    await (await show(page,'viewer-hips-reset')).click();
    const hipsAfterReset=(await authoring(page)).edits.find(e=>e.node===hipsTarget.node);
    assert(!hipsAfterReset.scale); assert.deepEqual(hipsAfterReset.position,hipsBeforeReset.position); assert.deepEqual(hipsAfterReset.rotation,hipsBeforeReset.rotation);
    (await state(page)).rig.bodyControls.hips.axisValues.forEach((value, axis) => assert(Math.abs(value - metadata.nodes.find(n => n.name === 'HipsSize').baseline.scale[axis]) < 1e-7));
    await setCard(page,'hips',[1.08,1.284,1.152]);
    const waistTarget=await selectAdvanced(page,'Spine');
    const lengthInput=page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]');
    await lengthInput.fill('1.18'); await lengthInput.dispatchEvent('change');
    assert.equal((await state(page)).rig.bodyControls.waist.available,false);
    await (await show(page,'viewer-waist-reset')).click();
    assert.deepEqual((await state(page)).rig.nodeAdjustments[String(waistTarget.node)].scale,[1.18,null,null]);
    // A generic advanced edit can legitimately give a card's axes different
    // percentages. Its blank "Different values" summary is not an invalid
    // user draft and must not recreate the disabled-Save regression.
    for(const [name,kind,value] of [['HipsSize','hips','1.31'],['LeftUpLeg','thighs','1.22']]) {
      await selectAdvanced(page,name);
      const axis=page.locator('input[data-viewer-node-kind="scale"][data-axis="Y"]');
      await axis.fill(value); await axis.dispatchEvent('change');
      if (kind === 'hips') assert(Math.abs(Number(await page.locator('#viewer-hips-scale-y').inputValue()) - Number(value)) < 1e-7);
      else {
        assert.equal((await state(page)).rig.bodyControls[kind].currentPercent,null);
        assert.equal(await page.locator('#viewer-'+kind+'-number').inputValue(),'');
      }
      assert.deepEqual((await authoring(page)).unsupported,[],kind+' mixed values remain valid advanced edits');
      assert.equal(await page.locator('#viewer-save').isDisabled(),false);
    }
    await group(page,'node');
    const untouchedHipApply = await authoring(page);
    await (await show(page,'viewer-hips-apply')).click();
    assert.deepEqual(await authoring(page), untouchedHipApply, 'Applying without a dirty axis never rewrites rounded displayed values');
    await setCard(page,'hips',[null,1.21125,null]);
    const mixedNumber=await show(page,'viewer-hips-scale-y');
    await mixedNumber.fill(''); await mixedNumber.dispatchEvent('input');
    assert((await authoring(page)).unsupported.some(text=>text.includes('invalid')),'An explicitly empty user draft is rejected');
    assert.equal(await page.locator('#viewer-save').isDisabled(),true);
    await setCard(page,'hips',[null,1.21125,null]); assert.deepEqual((await authoring(page)).unsupported,[]);
    const smallTarget=await selectAdvanced(page,'HipsSize');
    for(const [axis,index] of [['X',0],['Y',1],['Z',2]]) {
      const input=page.locator('input[data-viewer-node-kind="scale"][data-axis="'+axis+'"]');
      await input.fill(String(smallTarget.baseline.scale[index]*.05)); await input.dispatchEvent('change');
    }
    (await state(page)).rig.bodyControls.hips.axisValues.forEach((value, axis) => assert(Math.abs(value - smallTarget.baseline.scale[axis] * .05) < 1e-7));
    assert.deepEqual((await authoring(page)).unsupported,[],'A valid advanced value outside the simple card range remains saveable');
    assert.equal(await page.locator('#viewer-save').isDisabled(),false);
    assert.deepEqual(opened.errors,[]);
    report.cases.push({label:'real-card-hybrid-zip-roundtrip',controls,sourceSha256:hashBefore,fixtureSha256:originalFixture.sha256,reloadMaximumError:reloadError,sourcePreserved:true,repeatExportByteIdentical:true,childFramesPreserved:true,lengthAxisUnedited:true,
      ownershipAndSafety:{invalidValuesBlocked:true,fractionalAbsoluteHipAxesAccepted:true,fractionalStepMismatch,methodConflictBlocked:true,nodeCompensationOffExit:true,hipsResetKeepsPositionAndRotation:true,waistResetKeepsAdvancedLengthAxis:true,mixedAdvancedValuesRemainSaveable:true,explicitEmptyDraftRejected:true,unchangedAxesNotRecommitted:true,advancedOutsideCardBoundsRemainsSaveable:true}});
    await opened.context.close();
    report.cases.push(await exerciseThighPresets(browser, server.url, archive, original, hashBefore));
    for (const [locale,width] of [['en',1280],['ja',360]]) {
      const sample=await pageFor(browser,server.url,locale,width);await openModel(sample.page,source);
      const visible={};
      for(const kind of ['hips','thighs','waist']) {await group(sample.page,kind==='hips'?'node':'mesh');visible[kind]=await targetGeometry(sample.page,'viewer-'+kind+'-apply');assert(visible[kind].visible&&visible[kind].hit&&visible[kind].within&&visible[kind].height>=44);}
      await group(sample.page,'mesh');
      for(const id of ['viewer-thighs-preset','viewer-thighs-preset-apply']) { visible[id]=await targetGeometry(sample.page,id);assert(visible[id].visible&&visible[id].hit&&visible[id].within&&visible[id].height>=44); }
      assert.equal(await sample.page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
      assert.deepEqual(sample.errors,[]);report.cases.push({label:'translated-card-layout',locale,width,visible});await sample.context.close();
    }
    const savedHipFixture = makeSavedHipFixture(source, path.join(models, 'nonunit-saved-hips.unity'));
    report.cases.push(await exerciseNonunitHipNativeGuard(browser, server.url, savedHipFixture));
    assert.equal(report.cases.length, 5, 'Keep the four existing cases and the saved-Hip native guard regression');
    report.status='PASS';
  } catch(error) {
    report.status='FAIL';report.error=error.stack||String(error);
    if(error.actual!==undefined)report.actual=error.actual;if(error.expected!==undefined)report.expected=error.expected;
    try {const page=browser&&browser.contexts().flatMap(c=>c.pages()).slice(-1)[0];if(page){report.failureState=await state(page);report.failureAuthoring=await authoring(page);await page.screenshot({path:path.join(evidence,'failure.png'),fullPage:true});}}catch(_){}
    throw error;
  } finally {
    report.sourcesAfter=sourceHashes();report.sourcesUnchanged=JSON.stringify(report.sourcesBefore)===JSON.stringify(report.sourcesAfter);
    if(report.status==='PASS'&&!report.sourcesUnchanged)report.status='PASS_EXPLORATORY_SOURCES_CHANGED';
    fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2)+'\n');
    if(browser)await browser.close();if(server){if(server.child.exitCode===null){const done=new Promise(resolve=>server.child.once('exit',resolve));server.child.kill('SIGTERM');await Promise.race([done,wait(1500)]);}server.stream.end();}
    if(!process.env.KEEP_BODY_FIXTURE)fs.rmSync(temporary,{recursive:true,force:true});
  }
  console.log(JSON.stringify({status:report.status,cases:report.cases.length,report:path.join(evidence,'report.json')}));
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
