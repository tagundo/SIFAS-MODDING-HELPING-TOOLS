/* Hold a real SDK Image response while the actual tool form/source changes. */
'use strict';
const assert = require('assert'), fs = require('fs'), net = require('net'), os = require('os'), path = require('path');
const { spawn } = require('child_process'), { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'thumbnail-form-race-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'thumbnail-form-library-')), input = path.join(library, 'extracted/3d_model');
fs.mkdirSync(input, { recursive: true }); fs.mkdirSync(evidence, { recursive: true });
const sources = ['006before.unity', '006after.unity'].map(name => { const p = path.join(input, name); fs.copyFileSync(path.join(__dirname, 'fixtures/viewer_persistence.unity'), p); return p; });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function start() {
  const s = net.createServer(); await new Promise(r => s.listen(0, '127.0.0.1', r)); const port = s.address().port; await new Promise(r => s.close(r));
  const stream = fs.createWriteStream(path.join(evidence, 'server.log')); const child = spawn(python, ['-m', 'webtools', '--no-browser', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: repo, env: { ...process.env, PYTHONPATH: product + path.delimiter + repo, SUKUSTA_DIR: library }, stdio: ['ignore', 'pipe', 'pipe'] }); child.stdout.pipe(stream); child.stderr.pipe(stream);
  const url = 'http://127.0.0.1:' + port;
  for (let i = 0; i < 150; i++) { try { if ((await fetch(url + '/api/tools')).ok) return { child, stream, url }; } catch (_) {} await sleep(100); }
  throw new Error('Product server did not start');
}
async function fill(page, source, out) { await page.locator('#f_in_path').fill(source); await page.locator('#f_out_dir').fill(out); await page.locator('#f_auto_chara_id').uncheck(); await page.locator('#f_manual_chara_id').fill('6'); await page.locator('#f_thumbnail_mode').selectOption('3d'); }
(async () => { const report = { status: 'RUNNING', evidence, cases: [] }; let server, browser;
  try {
    server = await start(); browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const mode of ['source-change', 'language-rebuild']) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 950 } }); await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
      const page = await context.newPage(); page.setDefaultTimeout(30000); const out = path.join(library, mode); fs.mkdirSync(out);
      let release, held; const gate = new Promise(r => { release = r; }), requestHeld = new Promise(r => { held = r; });
      await page.route('**/static/thumbnail-sdk/pattern.png', async route => { held(); await gate; await route.continue(); });
      await page.goto(server.url); await page.waitForFunction(() => typeof selectTool === 'function' && window.ViewerThumbnails && state.tools.some(tool => tool.id === 'costume_packer'));
      await page.evaluate(() => selectTool('costume_packer')); await fill(page, sources[0], out);
      const submission = page.waitForRequest(r => r.url().endsWith('/api/run/costume_packer') && r.method() === 'POST');
      await page.locator('#tool-form .run-btn').click(); let timer;
      try { await Promise.race([requestHeld, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('SDK image was not held')), 20000); })]); } finally { clearTimeout(timer); }
      if (mode === 'source-change') await page.locator('#f_in_path').fill(sources[1]);
      else { await page.evaluate(() => changeLang('ko')); await fill(page, sources[0], out); }
      release(); const request = await submission, captured = request.postDataJSON(); assert.equal(captured.in_path, sources[0]); assert.equal(captured.mode, 'single');
      await page.waitForFunction(() => document.getElementById('cancel-btn').disabled);
      const log = await page.locator('#log').textContent(); assert(!log.includes('ERROR:') && !log.includes('FAIL '), log);
      assert.equal(await page.locator('#costume-thumbnail-preview').count(), 0, 'old renderer never attaches a preview to the changed form');
      assert(fs.readdirSync(out).some(name => name.endsWith('.zip') && name.includes('before')), 'the captured original job completes without retargeting');
      report.cases.push({ mode, capturedSource: captured.in_path, currentSource: await page.locator('#f_in_path').inputValue(), language: await page.evaluate(() => state.lang), previewAttached: false });
      await context.close();
    }
    report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally { if (browser) await browser.close(); if (server) { server.child.kill(); server.stream.end(); } fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report)); }
})();
