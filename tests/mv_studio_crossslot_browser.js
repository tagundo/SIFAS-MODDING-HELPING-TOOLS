/* "게임에 적용" to another MV slot, in the real workbench against a disposable Elichika-like root with a
 * cross-slot store stand-in (tests/mv_studio_crossslot_browser_server.py): the slot choice (loaded MV /
 * another 3D asset id), "무대도 함께 바꾸기" on by default, the lives that change, the stage-bound track
 * warning without the stage, the whole-timeline apply, the ask when a platform's timeline is not at hand
 * (convert / this platform only / cancel), restore of that slot, and an MV timeline pack export.
 * Korean screenshots go to EVIDENCE_DIR. Needs the Elichika server app (ELICHIKA_DIR). */
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
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-crossslot-browser-'));
fs.mkdirSync(evidence, { recursive: true });

async function startServer() {
  const log = fs.openSync(path.join(evidence, 'server.log'), 'w');
  const child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', path.join(__dirname, 'mv_studio_crossslot_browser_server.py')], {
    cwd: repo, env: { ...process.env, ELICHIKA_DIR: elichika, PYTHONDONTWRITEBYTECODE: '1' }, stdio: ['ignore', 'pipe', log],
  });
  fs.closeSync(log);
  const line = await new Promise((resolve, reject) => {
    const reader = readline.createInterface({ input: child.stdout });
    const timer = setTimeout(() => reject(new Error('The cross-slot test server did not start')), 120000);
    reader.once('line', (text) => { clearTimeout(timer); resolve(text); });
    child.once('exit', (code) => { clearTimeout(timer); reject(new Error('The cross-slot test server exited: ' + code)); });
  });
  return { child, ...JSON.parse(line) };
}

async function shot(page, panel, name) {
  const size = page.viewportSize();
  await page.setViewportSize({ width: size.width, height: 2400 });
  await page.waitForTimeout(150);
  await panel.screenshot({ path: path.join(evidence, name) });
  await page.setViewportSize(size);
}

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
      if (request.method() === 'POST' && /\/api\/mv-studio\/(apply-job|apply-plan|restore-job|pack-export)/.test(request.url())) {
        posted.push({ url: new URL(request.url()).pathname, body: request.postDataJSON() });
      }
    });
    const log = () => fs.existsSync(server.controllerLog) ?
      fs.readFileSync(server.controllerLog, 'utf8').trim().split('\n').filter(Boolean) : [];
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
    const panel = page.locator('#mv-panel-apply');
    await page.locator('#mv-apply-open').click();
    await checked(page, '수정 사항: 불러온 뒤 없음');

    // The slot choice: the loaded MV by default, labelled like the game MV picker.
    const slot = page.locator('#mv-apply-slot');
    assert.equal(await slot.inputValue(), 'loaded');
    assert.match(await slot.locator('option').first().textContent(), /^지금 불러온 MV \(MV 1번 · Star stage · scene101 · 3D 2101\)$/);
    assert.equal(await slot.locator('option').last().textContent(), '다른 3D 에셋 ID…');
    assert.equal(await page.locator('#mv-apply-stage').count(), 0, 'No stage choice for the loaded slot');

    // Another 3D asset id: the whole timeline, the stage on by default, the lives that change.
    await slot.selectOption('other');
    await page.locator('#mv-apply-asset').fill('2201');
    await page.locator('#mv-apply-asset').press('Tab');
    await checked(page, '3D 2201에 적용');
    assert(await page.locator('#mv-apply-stage').isChecked(), '무대도 함께 바꾸기 is on by default');
    assert.equal(await page.locator('#mv-apply-stage').locator('xpath=..').textContent(), '무대도 함께 바꾸기');
    assert.match(await page.locator('#mv-apply-target').textContent(), /^적용 대상: 3D 2201/);
    assert.match(await page.locator('#mv-apply-lives').textContent(), /^3D 2201을\(를\) 쓰는 라이브 \(1\): .*\(22\)\. 리듬 게임의 3D 라이브도 함께 바뀝니다\.$/);
    assert.match(await page.locator('#mv-apply-whole').textContent(), /타임라인 전체가 들어갑니다/);
    assert.match(await page.locator('#mv-apply-plan').textContent(), /원래 MV의 무대가 타임라인과 함께 들어가므로/);
    assert.deepEqual(await page.locator('#mv-apply-regions option').allTextContents(), ['이 지역만 (GL)', 'GL과 JP 모두']);
    assert.equal(await page.locator('#mv-apply-edits').count(), 0, 'Only the whole timeline goes into another slot');
    const crossPlan = posted.filter((item) => item.url.endsWith('/apply-plan')).pop();
    assert.deepEqual(crossPlan.body.target, { assetId: 2201, stage: true, regions: ['gl'] });
    await shot(page, panel, 'crossslot-ko.png');

    // Without the stage: the stage-bound tracks are named as a risk.
    await page.locator('#mv-apply-stage').uncheck();
    await checked(page, '무대 트랙 2개');
    assert.equal(await page.locator('[data-mv-plan=warn]').filter({ hasText: '무대 트랙 2개' }).count(), 1);
    await shot(page, panel, 'crossslot-nostage-ko.png');
    await page.locator('#mv-apply-stage').check();
    await checked(page, '원래 MV의 무대가 타임라인과 함께 들어가므로');

    // Apply: confirm, then the job writes the slot (the managed server stops and restarts).
    let mark = log().length;
    await page.waitForFunction(() => !document.querySelector('#mv-apply-all').disabled);
    await page.locator('#mv-apply-all').click();
    assert.equal(await page.locator('#mv-apply-confirm p').textContent(),
      '이 프로젝트의 타임라인 전체와 무대를 3D 2201에 넣을까요? 먼저 백업을 만듭니다.');
    await page.locator('#mv-apply-confirm-yes').click();
    await page.locator('#mv-apply-result').filter({ hasText: '3D 2201' }).waitFor({ timeout: 90000 });
    assert.deepEqual(log().slice(mark).filter((call) => call === 'stop' || call === 'start'), ['stop', 'start']);
    let job = posted.filter((item) => item.url.endsWith('/apply-job')).pop();
    assert.deepEqual({ ...job.body, project: undefined }, { mode: 'all', project: undefined, platforms: ['android', 'ios'],
      download: false, expected: { key: 'A2201', keys: { gl: 'A2201' } }, unbaked: [],
      target: { assetId: 2201, stage: true, regions: ['gl'] } });
    assert.equal(await page.evaluate(() => 'applied' in MVStudio.getState().project.source), false,
      "Another slot does not change the project's record of its own slot");
    await page.locator('#mv-apply-restore').filter({ hasText: '3D 2201 원래대로 되돌리기' }).waitFor({ timeout: 60000 });

    // A platform whose timeline is not at hand: ask (convert / this platform only / cancel).
    await page.route('**/api/mv-studio/apply-plan?*', async (route) => {
      const response = await route.fetch();
      const json = await response.json();
      if (json.cross) {
        json.all.download = ['ios'];
        json.platforms.ios = { payload: { status: 'download', bytes: 2097152 } };
      }
      await route.fulfill({ response, json });
    });
    await page.locator('#mv-apply-stage').uncheck();
    await page.locator('#mv-apply-stage').check();
    await checked(page, 'iOS 타임라인이 아직 없습니다: 적용할 때 Android에서 변환합니다.');
    await page.waitForFunction(() => !document.querySelector('#mv-apply-all').disabled);
    await page.locator('#mv-apply-all').click();
    await page.locator('#mv-apply-confirm-yes').click();
    await page.locator('#mv-apply-convert').waitFor();
    assert.equal(await page.locator('#mv-apply-confirm p').textContent(),
      '이 슬롯에 넣을 iOS 타임라인이 없습니다. 3D 2101의 iOS 원본(약 2 MB 다운로드)으로 Android에서 변환할 수 있습니다. ' +
      '제외하면 iOS은(는) 3D 2101의 원본 타임라인을 재생합니다. 무대는 두 플랫폼 모두 바뀝니다.');
    assert.deepEqual(await page.locator('#mv-apply-confirm button').allTextContents(), ['Android에서 변환', 'Android에만 적용', '취소']);
    await shot(page, panel, 'crossslot-ask-ko.png');
    mark = posted.length;
    await page.locator('#mv-apply-confirm-yes').click();
    await page.waitForFunction(() => document.querySelector('#mv-apply-result') && !document.querySelector('#mv-apply-job'), null,
      { timeout: 90000 });
    job = posted.slice(mark).filter((item) => item.url.endsWith('/apply-job')).pop();
    assert.deepEqual([job.body.platforms, job.body.download], [['android'], false]);
    await page.unroute('**/api/mv-studio/apply-plan?*');

    // Restore that slot (timeline and stage).
    await page.locator('#mv-apply-stage').uncheck();
    await checked(page, '3D 2201 원래대로 되돌리기');
    await page.waitForFunction(() => document.querySelector('#mv-apply-restore') && !document.querySelector('#mv-apply-restore').disabled);
    await page.locator('#mv-apply-restore').click();
    assert.equal(await page.locator('#mv-apply-confirm p').textContent(),
      '3D 2201을(를) 원래 MV로 되돌릴까요? 타임라인과 무대가 게임 원래의 것으로 돌아갑니다.');
    await page.locator('#mv-apply-confirm-yes').click();
    await page.waitForFunction(() => !document.querySelector('#mv-apply-job') &&
      [...document.querySelectorAll('#mv-apply-result')].length, null, { timeout: 90000 });
    const restore = posted.filter((item) => item.url.endsWith('/restore-job')).pop();
    assert.deepEqual(restore.body, { assetId: 2201, regions: { gl: { key: 'X1' } } });

    // MV timeline pack export.
    await page.locator('#mv-apply-pack > summary').click();
    assert.equal(await page.locator('#mv-apply-pack > summary').textContent(), 'MV 타임라인 팩');
    assert.deepEqual(await page.locator('#mv-apply-pack > .mv-controls button').allTextContents(),
      ['MV 타임라인 팩 내보내기…', 'MV 타임라인 팩 열기…']);
    await page.locator('#mv-pack-export').click();
    await page.locator('#mv-pack-name').fill('강당에 넣을 특별 스테이지');
    assert.equal(await page.locator('#mv-pack-target').textContent(), '적용 슬롯: 3D 2201, 무대 제외.');
    await page.locator('#mv-pack-export-go').click();
    await page.locator('#mv-pack-result a').waitFor({ timeout: 60000 });
    assert.match(await page.locator('#mv-pack-result a').textContent(), /\.sifasmv$/);
    const pack = posted.filter((item) => item.url.endsWith('/pack-export')).pop();
    assert.deepEqual({ ...pack.body, project: undefined }, { project: undefined, name: '강당에 넣을 특별 스테이지', note: '',
      target: { assetId: 2201, stage: false }, platforms: ['android', 'ios'], download: false });
    await shot(page, panel, 'crossslot-pack-ko.png');

    // Back to the loaded slot: the usual two modes again.
    await slot.selectOption('loaded');
    await checked(page, '수정 사항: 불러온 뒤 없음');
    await page.locator('#mv-apply-edits').waitFor();
    assert.equal(await page.locator('#mv-apply-stage').count(), 0);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    server.child.kill();
    fs.rmSync(server.base, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
