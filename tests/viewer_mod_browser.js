/* Mod ZIP actions through real HTTP, Unity export and installer archives.
 * The stale-source case delays delivery of a genuine package response; no
 * successful preparation/export/package/install response is fabricated.
 * Set VIEWER_MOD_RUNTIME_ROOT to an isolated prepared installer fixture and
 * VIEWER_MOD_EXPECT_INSTALL=1 to include a real successful game installation.
 * VIEWER_MOD_FACTOR_OFFSET permits a fresh shape on a reused test fixture. */
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
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mod-evidence-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-mod-library-'));
const inputs = path.join(library, 'extracted/3d_model');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(inputs, { recursive: true });
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const frontendFiles = ['webtools/web/index.html', 'webtools/web/static/viewer-persistence.js', 'webtools/web/static/model-viewer.js', 'webtools/web/static/viewer-rig.js', 'webtools/web/static/style.css', 'webtools/i18n.py'];
const frontendHashes = () => Object.fromEntries(frontendFiles.map(name => [name, sha(fs.readFileSync(path.join(product, name)))]));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
function py(code, args = []) {
  const result = spawnSync(python, ['-c', code, ...args], { cwd: product, encoding: 'utf8', maxBuffer: 8*1024*1024 });
  assert.equal(result.status, 0, result.stderr); return JSON.parse(result.stdout);
}
function fixtures() {
  return py(`import json,sys,zipfile\nfrom pathlib import Path\nimport UnityPy\nimport unity_costumemod_packer as p\nroot=Path(sys.argv[1]); source=Path(sys.argv[2]).read_bytes()\nfor filename,texture in [('board.unity','ch9999_co0001_body'),('unmasked.unity','ch0209_co0001_body')]:\n env=UnityPy.load(source)\n for obj in env.objects:\n  if obj.type.name=='Texture2D':\n   tree=obj.read_typetree();tree['m_Name']=texture;obj.save_typetree(tree)\n (root/filename).write_bytes(next(iter(env.files.values())).save())\nwith zipfile.ZipFile(root/'rina.zip','w',compression=zipfile.ZIP_DEFLATED) as z:\n z.write(root/'board.unity','board.unity');z.write(root/'unmasked.unity','unmasked.unity')\n z.writestr('thumbnail.png',p.make_name_thumbnail_png('Neutral costume',64,209))\n z.writestr('modinstall.txt',p.generate_modinstall_txt('Neutral costume','board.unity','thumbnail.png',209,'unmasked.unity'))\n z.writestr('notes.txt',b'Keep this companion exactly.');z.comment=b'Original neutral fixture'\nprint(json.dumps({'archive':str(root/'rina.zip'),'board':str(root/'board.unity'),'unmasked':str(root/'unmasked.unity')}))`, [inputs, path.join(product, 'tests/fixtures/viewer_persistence.unity')]);
}
function inspectPackage(file) {
  return py(`import ast,hashlib,json,sys,zipfile\nfrom webtools.core import model_edits\nwith zipfile.ZipFile(sys.argv[1]) as z:\n config={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(z.read('modinstall.txt').decode('utf-8')).body if isinstance(n,ast.Assign)}\n models={}\n for role,key in [('primary','costume_file'),('unmasked','rina_unmask_costume_file')]:\n  raw=z.read(config[key]);info=model_edits._inspect(raw)\n  models[role]={'sha256':hashlib.sha256(raw).hexdigest(),'scales':{name:info['effective'][node]['scale'] for node,name in info['names'].items() if name in ['BreastSize','LeftUpLeg']}}\n print(json.dumps({'config':config,'models':models,'members':z.namelist(),'notes':z.read('notes.txt' if 'notes.txt' in z.namelist() else 'notes.txt.data').decode(),'comment':z.comment.decode()}))`, [file]);
}
async function startServer() {
  const socket = net.createServer(); await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log'));
  const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: process.env.VIEWER_MOD_RUNTIME_ROOT || product,
    env: { ...process.env, SUKUSTA_DIR: library, PYTHONPATH: [product, path.dirname(product), process.env.PYTHONPATH || ''].join(path.delimiter) },
    stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(stream); child.stderr.pipe(stream); const url = 'http://127.0.0.1:' + port;
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw new Error('Product server exited: ' + child.exitCode);
    try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) { /* startup */ }
    await wait(100);
  }
  child.kill(); throw new Error('Product server was not ready');
}
async function show(page, selector) {
  const target = typeof selector === 'string' ? page.locator(selector) : selector; await target.evaluate(element => { for (let p = element.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; });
  await target.scrollIntoViewIfNeeded(); return target;
}
async function open(page, source, variant = 'primary') {
  await page.evaluate(({ source, variant }) => {
    document.getElementById('viewer-auto-face').checked = false;
    openModelViewer([source]);
  }, { source, variant });
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
  if (variant !== 'primary') {
    await (await show(page, '#viewer-variant-0')).selectOption(variant);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getState().loadedArchiveVariants[0] === 'unmasked');
  }
}
async function breast(page, factor) {
  await (await show(page, '#viewer-editor-node-tab')).click();
  await (await show(page, '#viewer-node-filter')).selectOption('all');
  const node = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(n => n.name === 'BreastSize'));
  await page.locator('#viewer-node').selectOption(String(node.node)); await page.locator('#viewer-save-method').selectOption('node');
  for (let axis = 0; axis < 3; axis++) {
    const field = page.locator('input[data-viewer-node-kind="scale"][data-axis="' + 'XYZ'[axis] + '"]');
    await field.fill(String(node.baseline.scale[axis] * factor)); await field.dispatchEvent('change');
  }
  return node;
}
async function finished(page, timeout = 30000) {
  await page.waitForFunction(() => !ModelViewer.getState().persistence.busy && ['done', 'error'].includes(ModelViewer.getState().persistence.status), null, { timeout });
  return page.evaluate(() => ModelViewer.getState().persistence);
}
async function downloads(page, modPath, locale) {
  const items = await page.locator('#viewer-save-output-list a').evaluateAll(links => links.map(link => ({
    path: new URL(link.href).searchParams.get('path'), label: link.textContent, download: link.getAttribute('download') })));
  assert.equal(items[0].path, modPath, 'The actual installer Mod ZIP is the primary download');
  assert(items[0].label.startsWith((locale === 'ko' ? '모드 ZIP' : 'MOD ZIP') + ' · '));
  const saved = await page.evaluate(() => ModelViewer.getState().persistence);
  assert.deepStrictEqual(items.map(item => item.path).sort(), saved.outputPaths.slice().sort(), 'Every output path remains available');
  assert(items.some(item => item.path === saved.recipePath && item.label.startsWith(locale === 'ko' ? '편집 기록 · ' : '編集レシピ · ')));
  assert(items.some(item => saved.previewPaths.includes(item.path) && item.label.startsWith(locale === 'ko' ? '편집한 미리보기 사본 · ' : '編集したプレビュー用コピー · ')));
  return items;
}
(async () => {
  let browser, server;
  const report = { status: 'RUNNING', scope: 'Actual host Chromium/HTTP/Unity/mod ZIP; positive installation only with explicit isolated runtime fixture',
    library, runtimeRoot: process.env.VIEWER_MOD_RUNTIME_ROOT || product, frontendBefore: frontendHashes(), cases: [] };
  try {
    const fixture = fixtures(), sourceHash = sha(fs.readFileSync(fixture.archive)); server = await startServer();
    const bodyPath = path.join(inputs, 'body-controls.unity');
    const generated = spawnSync(python, [path.join(product, 'tests/generate_viewer_body_fixture.py'), '--output', bodyPath], { cwd: product, encoding: 'utf8' });
    assert.equal(generated.status, 0, generated.stderr);
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    {
      const context = await browser.newContext({ viewport: { width: 448, height: 998 }, hasTouch: true });
      await context.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
      const page = await context.newPage(); await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
      await open(page, bodyPath); await (await show(page, '#viewer-editor-node-tab')).click();
      await (await show(page, '#viewer-hips-scale-x')).fill('1.17'); await page.locator('#viewer-hips-apply').click();
      assert((await page.locator('#viewer-mod-name').inputValue()).includes('X1.17/Y1.07/Z0.96'));
      await (await show(page, '#viewer-mod-name')).fill('Keep my name');
      await (await show(page, '#viewer-editor-mesh-tab')).click(); await (await show(page, '#viewer-thighs-preset')).selectOption('slim:thick');
      await page.locator('#viewer-thighs-preset-apply').click(); assert.equal(await page.locator('#viewer-mod-name').inputValue(), 'Keep my name');
      await (await show(page, '#viewer-mod-name-auto')).click();
      const automatic = await page.locator('#viewer-mod-name').inputValue(); assert(automatic.includes('X1.17/Y1.07/Z0.96') && automatic.includes('가느다란 체형→굵은 체형'), automatic);
      await page.locator('#viewer-mod-name').fill(''); assert(await page.locator('#viewer-save-mod').isDisabled()); assert(await page.locator('#viewer-add-to-game').isDisabled());
      assert.equal(await page.locator('#viewer-save').isDisabled(), false, 'An empty mod name does not disable raw model export');
      await page.locator('#viewer-mod-name-auto').click(); const hits = {};
      for (const id of ['viewer-mod-name', 'viewer-mod-name-auto', 'viewer-save-mod', 'viewer-add-to-game']) {
        const target = await show(page, '#' + id); hits[id] = await target.evaluate(element => { const r = element.getBoundingClientRect(), h = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return { width: r.width, height: r.height, hit: h === element || element.contains(h) }; });
        assert(hits[id].height >= 44 && hits[id].hit, id + ' remains a real visible touch target');
      }
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({ path: path.join(evidence, 'phone-automatic-name.png') });
      report.cases.push({ name: 'automatic-name-and-form', automatic, hits, horizontalOverflow: false }); await context.close();
    }
    for (const profile of [ { name: 'phone-ko-primary', width: 448, height: 998, locale: 'ko', variant: 'primary', touch: true },
      { name: 'mac-ja-unmasked', width: 1360, height: 900, locale: 'ja', variant: 'unmasked', mac: true } ]) {
      const context = await browser.newContext({ viewport: { width: profile.width, height: profile.height }, hasTouch: !!profile.touch });
      await context.addInitScript(p => { localStorage.setItem('sifas_lang', p.locale); if (p.mac) {
        window.ElichikaDesktop = { platform: 'macos', version: 1, language: p.locale, capabilities: [] };
        window.webkit = { messageHandlers: { elichika: { postMessage() {} } } };
      } }, profile);
      const page = await context.newPage(), errors = [], packages = [], installs = [], raw = [], cancellations = [];
      page.setDefaultTimeout(30000); page.on('pageerror', error => errors.push(String(error)));
      page.on('request', request => {
        if (request.method() !== 'POST') return;
        const route = new URL(request.url()).pathname;
        if (route === '/api/viewer/edit/package') packages.push(JSON.parse(request.postData()));
        if (route === '/api/viewer/edit/install') installs.push(JSON.parse(request.postData()));
        if (route === '/api/viewer/edit/export') raw.push(JSON.parse(request.postData()));
        if (/^\/api\/jobs\/[^/]+\/cancel$/.test(route)) cancellations.push(route);
      });
      await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
      await open(page, fixture.archive, profile.variant); const initial = await page.evaluate(() => ModelViewer.getState());
      await page.locator('#viewer-save-panel > summary').click();
      const guidance = await page.locator('[data-i18n="Add to game saves your current body edits as a mod and installs it. Rina\'s board and unmasked models receive the same body edits."]').innerText();
      assert(guidance.includes(profile.locale === 'ko' ? '리나' : '璃奈'), 'The two-variant editing explanation is translated: ' + JSON.stringify({ guidance, language: await page.evaluate(() => document.documentElement.lang), expected: profile.locale }));
      await breast(page, 1.17); await show(page, '#viewer-save-mod');
      const suggested = await page.locator('#viewer-mod-name').inputValue(); assert(suggested.includes('Neutral costume') && suggested.includes('1.17×'), suggested);
      await page.locator('#viewer-mod-name').fill('Manual costume'); await breast(page, 1.18);
      assert.equal(await page.locator('#viewer-mod-name').inputValue(), 'Manual costume');
      await (await show(page, '#viewer-mod-name-auto')).click(); assert((await page.locator('#viewer-mod-name').inputValue()).includes('1.18×'));
      await page.locator('#viewer-mod-name').fill('Named ' + profile.variant);
      const field = page.locator('input[data-viewer-node-kind="scale"][data-axis="X"]');
      await (await show(page, field)).fill('0');
      for (const id of ['viewer-save', 'viewer-save-mod', 'viewer-add-to-game']) assert(await page.locator('#' + id).isDisabled(), 'Invalid body draft blocks ' + id);
      if (profile.mac) { await field.focus(); await page.keyboard.press('Meta+s'); await frames(page); assert.equal(raw.length, 0); assert.equal(await field.inputValue(), '0'); }
      await breast(page, 1.18); await (await show(page, '#viewer-save-mod')).click(); const saved = await finished(page);
      assert.equal(saved.status, 'done', saved.error); assert.equal(packages.length, 1); assert.equal(installs.length, 0); assert.equal(raw.length, 0);
      const inspected = inspectPackage(saved.modPackage.packagePath);
      const savedDownloads = await downloads(page, saved.modPackage.packagePath, profile.locale);
      assert.deepStrictEqual(await page.evaluate(() => ModelViewer.getState().camera), initial.camera, 'Packaging leaves the current camera unchanged');
      assert.equal(inspected.config.costume_name_en, 'Named ' + profile.variant); assert.equal(inspected.config.chara_id, 209);
      assert.equal(inspected.notes, 'Keep this companion exactly.');
      assert.equal(inspected.comment, 'Original neutral fixture', 'The source ZIP comment is preserved exactly');
      assert.deepStrictEqual(inspected.members.filter(name => /\.txt$/i.test(name)), ['modinstall.txt'], 'Only the canonical installer manifest can be active text');
      assert(!inspected.members.some(name => /\.zip$/i.test(name)), 'Preserved nested archive data cannot trigger another installer package');
      for (const role of ['primary', 'unmasked']) {
        assert(Math.abs(inspected.models[role].scales.BreastSize[0] - 1.18) < 1e-6, 'Both Rina variants receive the body edit');
        assert.notEqual(inspected.models[role].sha256, sha(fs.readFileSync(fixture[role === 'primary' ? 'board' : 'unmasked'])));
      }
      const oldPackagePath = saved.modPackage.packagePath;
      const factorOffset = Number(process.env.VIEWER_MOD_FACTOR_OFFSET || 0);
      assert(Number.isFinite(factorOffset) && Math.abs(factorOffset) <= 1);
      const addFactor = Number(((profile.variant === 'primary' ? 1.19 : 1.21) + factorOffset).toFixed(6));
      let releaseInstall, installReceived;
      const installGate = new Promise(resolve => { releaseInstall = resolve; });
      const installStarted = new Promise(resolve => { installReceived = resolve; });
      await page.route('**/api/viewer/edit/install', async route => { const response = await route.fetch(); installReceived(); await installGate; await route.fulfill({ response }); });
      await breast(page, addFactor);
      await downloads(page, oldPackagePath, profile.locale); // Current edits do not relabel an older completed file.
      await (await show(page, '#viewer-add-to-game')).click(); await installStarted;
      assert(await page.locator('#viewer-save-cancel').isHidden()); assert(await page.locator('#viewer-save-cancel').isDisabled());
      await page.locator('#viewer-save-cancel').dispatchEvent('click');
      assert.equal(cancellations.length, 0, 'A submitted install is tracked to completion instead of falsely reporting cancellation');
      releaseInstall(); const added = await finished(page, 120000); await page.unroute('**/api/viewer/edit/install');
      assert.equal(packages.length, 2, 'Direct Add packages the current edit instead of reusing the old ZIP');
      assert.equal(installs.length, 1); assert.deepStrictEqual(Object.keys(installs[0]), ['package_token']);
      assert.notEqual(added.modPackage.packagePath, oldPackagePath);
      assert(packages[1].state.edits.some(edit => edit.scale && Math.abs(edit.scale[0] - addFactor) < 1e-8));
      if (process.env.VIEWER_MOD_EXPECT_INSTALL === '1') assert.equal(added.status, 'done', added.error);
      else { assert.equal(added.status, 'error'); assert(added.error.includes('Prepare the Elichika server data'), added.error); }
      let installedEvidence = null;
      if (added.status === 'done') {
        assert(await page.locator('#viewer-add-to-game').isDisabled(), 'The exact successfully added edit cannot be accidentally added twice');
        assert.equal(await page.locator('#viewer-save-mod').isDisabled(), false, 'The same mod remains available for download');
        await page.locator('#viewer-add-to-game').dispatchEvent('click');
        assert.equal(packages.length, 2, 'The same success fingerprint cannot create another package/install');
        const response = await fetch(server.url + '/api/viewer/edit/result/' + encodeURIComponent(added.jobId)), receipt = await response.json();
        assert(response.ok && receipt.installed === true);
        const installedBytes = fs.readFileSync(receipt.installed_package_path);
        assert.equal(sha(installedBytes), receipt.mod_package.sha256, 'The actual installer input matches its bound saved package');
        const installedModels = inspectPackage(receipt.installed_package_path);
        assert.equal(installedModels.config.costume_name_en, 'Named ' + profile.variant);
        for (const role of ['primary', 'unmasked']) assert(Math.abs(installedModels.models[role].scales.BreastSize[0] - addFactor) < 1e-6, 'Both actually installed Rina variants use the fresh edit');
        installedEvidence = { packagePath: receipt.installed_package_path, sha256: sha(installedBytes), bytes: installedBytes.length,
          models: installedModels.models, displayName: receipt.mod_package.display_name };
      }
      await (await show(page, '#viewer-mod-name')).fill('Another ' + profile.variant);
      assert.equal(await page.locator('#viewer-add-to-game').isDisabled(), false, 'A different mod name enables an intentional new copy');
      // Delay only the delivery of a successful, real background-job response.
      let release, received; const gate = new Promise(resolve => { release = resolve; });
      const started = new Promise(resolve => { received = resolve; });
      await page.route('**/api/viewer/edit/package', async route => { const response = await route.fetch(); received(); await gate; await route.fulfill({ response }); });
      await (await show(page, '#viewer-add-to-game')).click(); await started;
      await open(page, fixture.board); release(); const stale = await finished(page);
      assert.equal(stale.status, 'error'); assert(stale.error.includes('model, body edits or mod settings changed'), stale.error);
      assert.equal(installs.length, 1, 'A package that finishes after a model switch is never installed');
      const previousResult = await (await fetch(server.url + '/api/viewer/edit/result/' + encodeURIComponent(stale.jobId))).json();
      const staleDownloads = await downloads(page, previousResult.mod_package.package_path, profile.locale);
      assert.equal(await page.locator('#viewer-mod-name').inputValue(), 'board', 'A new source resets manual name to its own suggestion');
      assert.deepStrictEqual(errors, []); assert.equal(sha(fs.readFileSync(fixture.archive)), sourceHash);
      await page.screenshot({ path: path.join(evidence, profile.name + '.png') });
      report.cases.push({ profile, suggested, package: inspected, savedDownloads, staleDownloads, rawExports: raw.length, packageRequests: packages.length,
        installRequests: installs.length, addFactor, installSucceeded: added.status === 'done', installedEvidence, staleGuard: true,
        originalCamera: initial.camera, sourceUnchanged: true });
      await context.close();
    }
    report.frontendAfter = frontendHashes(); assert.deepStrictEqual(report.frontendAfter, report.frontendBefore, 'The tested shared UI source stayed unchanged');
    report.status = 'PASS'; fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence }));
  } finally {
    if (browser) await browser.close();
    if (server) { server.child.kill(); server.child.stdout.unpipe(server.stream); server.child.stderr.unpipe(server.stream); server.stream.end(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
