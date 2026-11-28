/* Readable model names in the 3D model tab, through the real server and page.
 *
 * A game import (a cache file named ch0004_suit100041001_primary.unity with the
 * server's .selection receipt) reads as "004 소노다 우미 · <costume>" in the title
 * chip, the Files rows, the Remove buttons, the texture picker, the Mod name and
 * the Mod character list; the code file name stays in the title and on a small
 * details line. Its edited preview copy keeps the code file name on disk and in
 * the download and reads as the same costume. An unbound file keeps its name.
 * The runtime root is a tiny fixture with the game's member/costume dictionary
 * keys (tests/test_model_labels.py build_root). Temporary folders are removed.
 */
'use strict';
const assert = require('assert'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || 'python3';
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-model-labels-'));
const runtime = path.join(scratch, 'runtime'), library = path.join(scratch, 'library');
const env = { ...process.env, PYTHONPATH: [product, path.join(product, 'tests')].join(path.delimiter), SUKUSTA_DIR: library, PYTHONDONTWRITEBYTECODE: '1' };
const fixture = JSON.parse(execFileSync(python, ['-B', '-c', `
import hashlib, json, sys
from pathlib import Path
from test_model_labels import add_asset_catalog, build_root, selection
runtime, library = Path(sys.argv[1]), Path(sys.argv[2])
build_root(runtime)
add_asset_catalog(runtime)
raw = (Path("tests/fixtures/viewer_persistence.unity")).read_bytes()
cache = library / "cache/viewer/game-models"
bound = cache / "gl-100041001-labels" / "ch0004_suit100041001_primary.unity"
bound.parent.mkdir(parents=True)
bound.write_bytes(raw)
receipt = {"model": "gl-100041001-labels/" + bound.name, "sha256": hashlib.sha256(raw).hexdigest(), "selection_record": selection(runtime)}
(cache / (".selection-" + "1" * 32 + ".json")).write_text(json.dumps(receipt))
other = library / "extracted/3d_model/other_costume.unity"
other.parent.mkdir(parents=True)
other.write_bytes(raw)
# The same costume imported from JP: its own bytes and receipt.
jp_raw = Path("tests/fixtures/viewer_triangle.unity").read_bytes()
jp = cache / "jp-100041001-labels" / "ch0004_suit100041001_primary.unity"
jp.parent.mkdir(parents=True)
jp.write_bytes(jp_raw)
receipt = {"model": "jp-100041001-labels/" + jp.name, "sha256": hashlib.sha256(jp_raw).hexdigest(),
           "selection_record": {"region": "jp", "suit_id": 100041001, "variant": "primary", "owner": 4}}
(cache / (".selection-" + "2" * 32 + ".json")).write_text(json.dumps(receipt))
print(json.dumps({"bound": str(bound.resolve()), "other": str(other.resolve()), "jp": str(jp.resolve())}))
`, runtime, library], { cwd: product, env, encoding: 'utf8' }));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const KO = '004 소노다 우미 · 오토노키자카 고교 교복(동복)', JA = '004 園田 海未 · 音ノ木坂学院制服（冬服）';
const CODE = 'ch0004_suit100041001_primary.unity';

async function startServer() {
  const s = net.createServer(); await new Promise(resolve => s.listen(0, '127.0.0.1', resolve)); const port = s.address().port; await new Promise(resolve => s.close(resolve));
  const log = []; const child = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)], { cwd: runtime, env, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.on('data', data => log.push(String(data))); child.stderr.on('data', data => log.push(String(data)));
  const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 300; i++) { if (child.exitCode !== null) throw new Error('Server exited: ' + log.join('')); try { if ((await fetch(url + '/api/tools')).ok) return { url, child, log }; } catch (_) {} await wait(100); }
  child.kill(); throw new Error('Server did not become ready');
}
async function show(page, selector) { const target = page.locator(selector); await target.evaluate(e => { for (let p = e.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; }); await target.scrollIntoViewIfNeeded(); return target; }
// The chip shows the member on a small first line and the costume below it.
async function chip(page) {
  return page.evaluate(() => { const name = document.getElementById('viewer-model-file-name'), member = name.querySelector('.viewer-chip-member'), costume = name.querySelector('.viewer-chip-costume');
    return member && costume ? member.textContent + ' · ' + costume.textContent : name.textContent; });
}
const chipIs = (page, label) => page.waitForFunction(label => { const name = document.getElementById('viewer-model-file-name'), member = name.querySelector('.viewer-chip-member'), costume = name.querySelector('.viewer-chip-costume');
  return (member && costume ? member.textContent + ' · ' + costume.textContent : name.textContent) === label; }, label);
// Choosing a file in the app's picker (window.openPicker) returns this path.
const answerPicker = (page, file) => page.evaluate(file => { window.openPicker = function (type, callback) { callback(file); }; }, file);
async function rows(page) {
  return page.locator('#viewer-file-list > li').evaluateAll(items => items.map(item => ({
    title: item.querySelector('.viewer-file-title').textContent, code: item.querySelector('.viewer-file-code') ? item.querySelector('.viewer-file-code').textContent : null,
    tooltip: item.querySelector('.viewer-file-label').title, remove: item.querySelector('.viewer-remove').getAttribute('aria-label') })));
}

(async () => {
  let server, browser; const cases = [];
  try {
    server = await startServer();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
    await context.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
    const page = await context.newPage(), errors = [], labelRequests = [];
    page.on('pageerror', error => errors.push(String(error.stack || error))); page.setDefaultTimeout(60000);
    page.on('request', request => { if (request.url().endsWith('/api/viewer/model-labels')) labelRequests.push(request.postDataJSON().paths); });
    await page.goto(server.url); await page.waitForFunction(() => typeof openModelViewer === 'function');
    await page.evaluate(file => { document.getElementById('viewer-auto-face').checked = false; return openModelViewer([file]); }, fixture.bound);
    await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading && ModelViewer.getEditingMetadata().available);
    await chipIs(page, KO);
    assert.deepStrictEqual(await page.evaluate(() => [...document.querySelectorAll('#viewer-model-file-name > *')].map(node => [node.className, node.textContent])),
      [['viewer-chip-member', '004 소노다 우미'], ['viewer-chip-costume', '오토노키자카 고교 교복(동복)']]);
    cases.push('title chip: 004 소노다 우미 on a small first line, the costume on its own line');

    // The title chip and the Files rows read as the costume; the code stays in the title and details.
    const summary = await page.locator('#viewer-model-files > summary').getAttribute('title');
    assert(summary.includes(KO) && summary.includes('파일: ' + CODE + ' · GL 의상 ID 100041001'), summary);
    let listed = await rows(page);
    assert.deepStrictEqual(listed.map(row => [row.title, row.code, row.remove]), [[KO, '파일: ' + CODE + ' · GL 의상 ID 100041001', '삭제 ' + KO]]);
    assert(listed[0].tooltip.includes(fixture.bound), listed[0].tooltip);
    assert(!JSON.stringify(listed).includes('primary ·') && !/ · primary\b/.test(JSON.stringify(listed)), 'the default view is never named');
    cases.push('title chip, Files row, details line and Remove label read 004 소노다 우미 · costume; the code stays in the title');

    // The automatic Mod name and the Mod character list.
    assert.equal(await page.locator('#viewer-mod-name').inputValue(), KO);
    const characters = await page.locator('#viewer-mod-character option').evaluateAll(options => options.map(option => option.textContent));
    assert(characters.includes('004 소노다 우미') && characters.includes('101 타카미 치카') && characters.includes('209 텐노지 리나'), characters.join(' | '));
    cases.push('automatic Mod name and Mod character list start with the member number and Korean member name');

    // Another Mod member: that member's number and name, never Umi's; Automatic restores it.
    await (await show(page, '#viewer-mod-character')).selectOption('101');
    await page.waitForFunction(() => document.getElementById('viewer-mod-name').value === '101 타카미 치카 · 오토노키자카 고교 교복(동복)');
    assert(!(await page.locator('#viewer-mod-name').inputValue()).includes('소노다'));
    await page.locator('#viewer-mod-character').selectOption('');
    await page.waitForFunction(label => document.getElementById('viewer-mod-name').value === label, KO);
    cases.push('choosing 101 타카미 치카 renames the automatic Mod name to 101 타카미 치카 · costume; Automatic restores 004');

    // The Rina counterpart field names the chosen file as the costume.
    await answerPicker(page, fixture.bound);
    await page.evaluate(() => document.getElementById('viewer-mod-counterpart-pick').click());
    await page.waitForFunction(label => document.getElementById('viewer-mod-counterpart').value === label, KO);
    assert.equal(await page.locator('#viewer-mod-counterpart').getAttribute('title'), fixture.bound);
    await page.evaluate(() => document.getElementById('viewer-mod-counterpart-clear').click());
    await page.waitForFunction(() => document.getElementById('viewer-mod-counterpart').value === '');
    cases.push('Rina counterpart field reads 004 소노다 우미 · costume with the path as its title');

    // The costume transplant donor field names the donor the same way.
    await page.locator('#viewer-costume-transplant').evaluate(details => { details.open = true; });
    await page.locator('#viewer-costume-transplant [data-transplant-label="Choose donor costume"]').click();
    await page.waitForFunction(label => document.querySelector('#viewer-costume-transplant input[readonly]').value === label, KO);
    assert.equal(await page.locator('#viewer-costume-transplant input[readonly]').getAttribute('title'), fixture.bound);
    await page.locator('#viewer-costume-transplant').evaluate(details => { details.open = false; });
    cases.push('transplant donor field reads 004 소노다 우미 · costume');

    // The mesh picker names each mesh's source costume; its file name is the tooltip.
    await page.locator('#viewer-mesh-modify').evaluate(details => { details.open = true; });
    await page.locator('#viewer-mesh-modify-load').click();
    await page.waitForFunction(() => document.querySelectorAll('#viewer-mesh-modify-select option').length > 1);
    const meshes = await page.locator('#viewer-mesh-modify-select option').evaluateAll(options => options.slice(1).map(option => [option.textContent, option.title]));
    assert(meshes.length && meshes.every(([text, title]) => text.includes(' · ' + '004 소노다 우미 · 오토노키자카 고교 교복(동복)' + ' (') && title.includes(CODE)), JSON.stringify(meshes));
    await page.locator('#viewer-mesh-modify').evaluate(details => { details.open = false; });
    cases.push('mesh picker reads <mesh> · 004 소노다 우미 · costume (vertices); the cache file name is its tooltip');

    // The texture picker names the costume; the file name is its tooltip.
    await page.evaluate(() => { const d = document.getElementById('viewer-texture-tools'); if (!d.open) d.querySelector('summary').click(); });
    await page.waitForFunction(() => document.querySelectorAll('#viewer-texture-select option').length > 1);
    let textures = await page.locator('#viewer-texture-select option').evaluateAll(options => options.slice(1).map(option => [option.textContent, option.title]));
    assert(textures.length && textures.every(([text, title]) => text.endsWith(' · ' + '004 소노다 우미 · 오토노키자카 고교 교복(동복)') && title.includes(CODE)), JSON.stringify(textures));
    cases.push('texture picker names 004 소노다 우미 · costume with the cache file name as its tooltip');

    // Japanese: every name switches without asking the server for labels again.
    const asked = labelRequests.length;
    await page.locator('#lang-select').selectOption('ja');
    await page.waitForFunction(() => document.documentElement.lang === 'ja');
    await chipIs(page, JA);
    await page.waitForFunction(label => document.getElementById('viewer-mod-name').value === label, JA);
    listed = await rows(page);
    assert.deepStrictEqual(listed.map(row => [row.title, row.code]), [[JA, 'ファイル: ' + CODE + ' · GL 衣装ID 100041001']]);
    textures = await page.locator('#viewer-texture-select option').evaluateAll(options => options.slice(1).map(option => option.textContent));
    assert(textures.every(text => text.endsWith(' · ' + JA)), textures.join(' | '));
    assert.equal(labelRequests.length, asked, 'labels hold every language');
    cases.push('ja: chip, rows, Mod name and texture picker switch to 004 園田 海未 · 音ノ木坂学院制服（冬服） with no new label request');

    // Save: the edited preview copy keeps its code name on disk and in the download, and reads as the costume.
    const node = await page.evaluate(() => ModelViewer.getEditingMetadata().nodes.find(n => n.name === 'LeftUpLeg').node);
    await page.evaluate(node => ModelViewer.restoreAuthoringState({ version: 1, savedSettingsEnabled: true, edits: [{ node, method: 'mesh', scale: [1.2, 1.1, 1.0] }] }), node);
    await (await show(page, '#viewer-save')).click();
    await page.waitForFunction(() => { const p = ModelViewer.getState().persistence; return !p.busy && (p.error || p.status === 'done'); });
    const saveError = await page.evaluate(() => ModelViewer.getState().persistence.error); assert(!saveError, saveError);
    // Its derived receipt names the wearer; the link reads as the costume.
    await page.waitForFunction(label => [...document.querySelectorAll('#viewer-save-output-list a')].some(link => link.textContent === label), JA);
    const copy = await page.locator('#viewer-save-output-list a').evaluateAll((links, label) => links.map(link => ({ text: link.textContent, download: link.getAttribute('download'), title: link.title, href: link.href }))
      .find(link => link.text === label), JA);
    assert.equal(copy.download, CODE); assert(copy.title.startsWith(CODE + '\n') && copy.title.includes('/models/' + CODE), copy.title);
    cases.push('the saved edited copy reads 004 園田 海未 · …; its download and tooltip keep ' + CODE);

    // The same costume twice: from GL and JP, the region and costume number tell them apart;
    // the original and its edited copy (same region and number) are numbered.
    const copyPath = decodeURIComponent(new URL(copy.href).searchParams.get('path'));
    await page.evaluate(files => ModelViewer.open(files), [fixture.bound, fixture.jp]);
    await page.waitForFunction(() => !ModelViewer.getState().loading && ModelViewer.getState().loadedPaths.length === 2);
    await page.waitForFunction(() => document.querySelectorAll('#viewer-file-list > li').length === 2 && document.querySelector('#viewer-file-list .viewer-file-code'));
    await page.waitForFunction(() => [...document.querySelectorAll('#viewer-file-list .viewer-file-title')].every(node => / #100041001$/.test(node.textContent)));
    listed = await rows(page);
    assert.deepStrictEqual(listed.map(row => row.title), [JA + ' · GL #100041001', JA + ' · JP #100041001']);
    await page.evaluate(files => ModelViewer.open(files), [fixture.bound, copyPath]);
    await page.waitForFunction(path => !ModelViewer.getState().loading && ModelViewer.getState().loadedPaths.length === 2 && ModelViewer.getState().loadedPaths[1] === path, copyPath);
    await page.waitForFunction(() => [...document.querySelectorAll('#viewer-file-list .viewer-file-title')].every(node => /\(\d\)$/.test(node.textContent)));
    listed = await rows(page);
    assert.deepStrictEqual(listed.map(row => [row.title, row.remove]), [[JA + ' · GL #100041001 (1)', '削除 ' + JA + ' · GL #100041001 (1)'],
      [JA + ' · GL #100041001 (2)', '削除 ' + JA + ' · GL #100041001 (2)']]);
    assert.equal(await chip(page), JA + ' · GL #100041001 (1)');
    cases.push('two files of one costume: GL/JP get · GL #id / · JP #id; the same region and number get (1)/(2)');

    // A file nothing describes keeps its own name, also beside a labelled one.
    await page.evaluate(files => ModelViewer.open(files), [fixture.bound, fixture.other]);
    await page.waitForFunction(path => !ModelViewer.getState().loading && ModelViewer.getState().loadedPaths[1] === path, fixture.other);
    await page.waitForFunction(() => document.querySelectorAll('#viewer-file-list > li').length === 2 && document.querySelector('#viewer-file-list > li:nth-child(2) .viewer-file-title').textContent === 'other_costume.unity');
    listed = await rows(page);
    assert.deepStrictEqual(listed.map(row => [row.title, row.code, row.remove]), [[JA, 'ファイル: ' + CODE + ' · GL 衣装ID 100041001', '削除 ' + JA],
      ['other_costume.unity', null, '削除 other_costume.unity']]);
    cases.push('an unbound file keeps its file name and has no details line');
    assert.deepStrictEqual(errors, []);
  } catch (error) {
    if (server) console.error(server.log.join('').slice(-4000));
    throw error;
  } finally {
    if (browser) await browser.close();
    if (server) server.child.kill();
    fs.rmSync(scratch, { recursive: true, force: true });
  }
  process.stdout.write(JSON.stringify({ status: 'PASS', cases }) + '\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
