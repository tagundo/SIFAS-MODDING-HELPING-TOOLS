/* A track mute from the timeline lanes to the game, end to end in the real workbench against the apply
 * test's disposable Elichika-like root: the lane's mute toggle (the editor) changes the project's track
 * mute, and the registration and apply plans count it as an edit that reaches the game (the export's own
 * rule); Apply only the edits writes it, and unmuting is the next edit. Needs the Elichika server app
 * (ELICHIKA_DIR, or modtools inside Elichika). Korean screenshots go to EVIDENCE_DIR. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const repo = path.resolve(__dirname, '..');
const elichika = process.env.ELICHIKA_DIR ||
  (fs.existsSync(path.join(repo, '..', 'mv_studio_live.py')) ? path.resolve(repo, '..') : '');
const ownEvidence = !process.env.EVIDENCE_DIR;
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-track-mute-browser-'));
fs.mkdirSync(evidence, { recursive: true });

async function startServer() {
  const log = fs.openSync(path.join(evidence, 'server.log'), 'w');
  const child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', path.join(__dirname, 'mv_studio_apply_browser_server.py')], {
    cwd: repo, env: { ...process.env, ELICHIKA_DIR: elichika, PYTHONDONTWRITEBYTECODE: '1' }, stdio: ['ignore', 'pipe', log],
  });
  fs.closeSync(log);
  const line = await new Promise((resolve, reject) => {
    const reader = readline.createInterface({ input: child.stdout });
    const timer = setTimeout(() => reject(new Error('The apply test server did not start')), 120000);
    reader.once('line', (text) => { clearTimeout(timer); resolve(text); });
    child.once('exit', (code) => { clearTimeout(timer); reject(new Error('The apply test server exited: ' + code)); });
  });
  return { child, ...JSON.parse(line) };
}

// The apply panel shows a fresh check: not checking, and the plan covers the latest edit.
async function checked(page, text) {
  await page.waitForFunction(() => !document.querySelector('#mv-panel-apply').textContent.includes('게임의 타임라인 확인 중…'),
    null, { timeout: 60000 });
  if (text) await page.locator('#mv-panel-apply').filter({ hasText: text }).waitFor({ timeout: 60000 });
}

async function run() {
  if (!elichika) {
    console.log(JSON.stringify({ status: 'SKIP', reason: 'The Elichika server app is not available (set ELICHIKA_DIR).' }));
    return;
  }
  const server = await startServer();
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ locale: 'ko', viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const posted = [];
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/api\/mv-studio\/(apply-job|apply-plan|registration-plan)/.test(request.url())) {
        posted.push({ url: new URL(request.url()).pathname, body: request.postDataJSON() });
      }
    });
    await page.goto(server.url + '/#mv');
    await page.waitForFunction(() => window.MVStudio && MVStudio.getState().visible);
    await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
      regions: [{ value: 'gl', label: 'Global (GL)' }], platforms: [{ value: 'android', label: 'Android', available: true }],
      songs: [{ id: 21, title: 'Base song', mvOnly: false, variants: [{ id: 2101, label: 'Star stage' }] }], players: [] } }));
    await page.route('**/api/mv-studio/game-stream?*', (route) => route.fulfill({ status: 404 }));
    await page.route('**/api/mv-studio/game?*', (route) => route.fulfill({ json: server.nativeProject }));
    await page.locator('#mv-import-game').click();
    await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
    await page.locator('#mv-game-load').click();
    await page.waitForFunction(() => MVStudio.getState().project?.source?.liveId === 21);

    // The camera track is a leaf outside the quality categories: its toggle is open.
    const track = 'cab-1:10';
    const toggle = page.locator(`.mv-lane-mute[data-track="${track}"]`).first();
    await toggle.waitFor();
    assert.equal(await toggle.getAttribute('aria-disabled'), null);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false');

    await page.locator('#mv-apply-open').click();
    await checked(page, '수정 사항: 불러온 뒤 없음');
    assert(await page.locator('#mv-apply-edits').isDisabled(), 'Nothing to apply before the mute');

    // Mute it in the lane: the project's track mute changes, and the apply plan counts one track
    // (and no clip) as an edit that reaches the game.
    await toggle.click();
    await page.waitForFunction((id) => MVStudio.getState().project.tracks.find((item) => item.id === id).muted === true, track);
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true');
    await checked(page, '음소거를 바꾼 트랙: 1개');
    const applyPlan = await page.locator('#mv-apply-plan').textContent();
    assert.doesNotMatch(applyPlan, /수정 사항: 불러온 뒤 없음/);
    assert.doesNotMatch(applyPlan, /불러온 뒤 수정: 클립/);
    // The edits line and the Apply all line each say what they count.
    assert.equal(applyPlan.split('음소거를 바꾼 트랙: 1개').length - 1, 1, applyPlan);
    assert.match(applyPlan, /전체 적용: 원본 MV와 음소거가 다른 트랙 1개/);
    await page.waitForFunction(() => !document.querySelector('#mv-apply-edits').disabled);
    const plan = posted.filter((item) => item.url.endsWith('/apply-plan')).pop();
    assert.equal(plan.body.project.tracks.find((item) => item.id === track).muted, true);
    await page.locator('#mv-panel-apply').screenshot({ path: path.join(evidence, 'track-mute-apply-plan-ko.png') });

    // The registration plan lists the same mute among what reaches the game.
    const register = page.locator('#mv-panel-register');
    if (!(await register.evaluate((node) => node.open))) await register.locator(':scope > summary').click();
    await page.locator('#mv-register-plan').filter({ hasText: '음소거를 바꾼 트랙: 1개' }).waitFor({ timeout: 60000 });
    assert.doesNotMatch(await page.locator('#mv-register-plan').textContent(), /타임라인 변경 없음/);
    await register.screenshot({ path: path.join(evidence, 'track-mute-register-plan-ko.png') });
    await register.locator(':scope > summary').click();

    // Apply only the edits writes the mute; the next check has nothing left to apply.
    await page.locator('#mv-apply-edits').click();
    await page.locator('#mv-apply-result').filter({ hasText: '게임에 적용했습니다: Base song.' }).waitFor({ timeout: 90000 });
    const job = posted.filter((item) => item.url.endsWith('/apply-job')).pop();
    assert.equal(job.body.mode, 'edits');
    assert.equal(job.body.project.tracks.find((item) => item.id === track).muted, true);
    const timelines = await page.evaluate(async () => (await (await fetch('/api/mv-studio/timelines?region=gl')).json()).timelines);
    assert.deepEqual([timelines.length, timelines[0].revision, timelines[0].platforms], [1, 1, { android: 'custom', ios: 'custom' }]);
    await checked(page, '수정 사항: 마지막 적용 이후 없음');

    // Unmuting is the next edit since that apply.
    await toggle.click();
    await page.waitForFunction((id) => MVStudio.getState().project.tracks.find((item) => item.id === id).muted === false, track);
    await checked(page, '음소거를 바꾼 트랙: 1개');
    await page.waitForFunction(() => !document.querySelector('#mv-apply-edits').disabled);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    server.child.kill();
    fs.rmSync(server.base, { recursive: true, force: true });
    if (ownEvidence) fs.rmSync(evidence, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
