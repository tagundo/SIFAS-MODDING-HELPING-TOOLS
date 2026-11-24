/* MV-only song registration, end to end in the real workbench against a disposable Elichika-like root:
 * plan -> register (jacket crop, managed server stop/restart) -> songs list -> update (no change) -> remove.
 * Needs the Elichika server app (ELICHIKA_DIR, or modtools inside Elichika). Korean screenshots go to EVIDENCE_DIR. */
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
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-register-browser-'));
fs.mkdirSync(evidence, { recursive: true });

async function startServer() {
  const log = fs.openSync(path.join(evidence, 'server.log'), 'w');
  const child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', path.join(__dirname, 'mv_studio_register_browser_server.py')], {
    cwd: repo, env: { ...process.env, ELICHIKA_DIR: elichika, PYTHONDONTWRITEBYTECODE: '1' }, stdio: ['ignore', 'pipe', log],
  });
  fs.closeSync(log);
  const line = await new Promise((resolve, reject) => {
    const reader = readline.createInterface({ input: child.stdout });
    const timer = setTimeout(() => reject(new Error('The registration test server did not start')), 30000);
    reader.once('line', (text) => { clearTimeout(timer); resolve(text); });
    child.once('exit', (code) => { clearTimeout(timer); reject(new Error('The registration test server exited: ' + code)); });
  });
  return { child, ...JSON.parse(line) };
}

async function chooseFile(page, folder, file) {
  await page.waitForFunction(expected => document.getElementById('picker-crumb').textContent === expected, folder);
  await page.locator('#picker-entries li').filter({ hasText: file }).click();
}

function gameProject() {
  // A game import of base MV 21 without a native timeline (the synthetic root has no Unity packs):
  // the registration keeps the base timeline and exercises title, credit, jacket and the store.
  return { version: 1, name: 'MV Studio sample', duration: 12, stage: null, performers: [], soundtrack: null, assets: [],
    tracks: [], warnings: [], quality: { modes: [], options: [], mode: null, values: {} }, nativeTimeline: false,
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 21, assetId: 2101, mvOnly: false, registered: false } };
}

// The panel lives in the scrolling inspector: a tall viewport shows it whole for the screenshot.
async function shot(page, panel, name) {
  const size = page.viewportSize();
  await page.setViewportSize({ width: size.width, height: 2400 });
  await page.waitForTimeout(150);
  await panel.screenshot({ path: path.join(evidence, name) });
  await page.setViewportSize(size);
}

async function noOverflow(page) {
  return page.locator('#mv-register-fields').evaluate((box) => {
    const wide = [];
    const limit = box.getBoundingClientRect().right + 1;
    for (const node of box.querySelectorAll('*')) {
      const rect = node.getBoundingClientRect();
      if (rect.width && rect.right > limit) wide.push(`${node.tagName}#${node.id}.${node.className} ${Math.round(rect.right - limit)}px`);
    }
    return { scroll: box.scrollWidth <= box.clientWidth + 1, wide };
  });
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
      if (request.method() === 'POST' && /\/api\/mv-studio\/(register-job|registration-plan|songs\/)/.test(request.url())) {
        posted.push({ url: new URL(request.url()).pathname, body: request.postDataJSON() });
      }
    });
    await page.goto(server.url + '/#mv');
    await page.waitForFunction(() => window.MVStudio && MVStudio.getState().visible);
    await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
      regions: [{ value: 'gl', label: 'Global (GL)' }], platforms: [{ value: 'android', label: 'Android', available: true }],
      songs: [{ id: 21, title: 'Base song', mvOnly: false, variants: [{ id: 2101, label: 'Star stage' }] }], players: [] } }));
    await page.route('**/api/mv-studio/game-stream?*', (route) => route.fulfill({ status: 404 }));
    await page.route('**/api/mv-studio/game?*', (route) => route.fulfill({ json: gameProject() }));
    await page.locator('#mv-import-game').click();
    await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
    await page.locator('#mv-game-load').click();
    await page.waitForFunction(() => MVStudio.getState().project?.source?.liveId === 21);

    // The panel is listed for the project and plans on open (real server, no writes).
    const panel = page.locator('#mv-panel-register');
    assert.equal(await panel.locator(':scope > summary').textContent(), 'MV 전용 곡으로 등록');
    await panel.locator(':scope > summary').click();
    await page.locator('#mv-register-base').filter({ hasText: 'Base song' }).waitFor();
    assert.equal(await page.locator('#mv-register-base').textContent(), 'Base song · Star stage (21)');
    assert.equal(await page.locator('#mv-register-title').inputValue(), 'MV Studio sample');
    assert(await page.locator('input[name=mv-register-audio][value=base]').isChecked());
    assert(await page.locator('input[name=mv-register-audio][value=project]').isDisabled());
    assert.match(await page.locator('#mv-register-plan').textContent(), /기본 MV의 타임라인이 그대로 재생됩니다/);
    assert.equal(await page.locator('#mv-register-submit').textContent(), 'MV 전용 곡으로 등록');
    await page.locator('#mv-register-title').fill('내 MV');
    await page.locator('#mv-register-credit').fill('작곡: 테스트');

    // A non-square jacket gets a square crop box; the server cuts exact pixels.
    await page.locator('#mv-register-jacket-choose').click();
    await chooseFile(page, path.join(server.library, 'modded'), 'jacket-wide.png');
    await page.locator('#mv-register-crop').waitFor();
    assert.equal(await page.locator('#mv-register-jacket-name').textContent(), 'jacket-wide.png · 600×400');
    const box = page.locator('.mv-register-crop-box');
    await box.focus();
    for (let index = 0; index < 3; index++) await box.press('Shift+ArrowLeft');
    assert.equal(await box.getAttribute('aria-valuetext'), '70, 0 · 400px');
    await page.locator('#mv-register-title').click();
    await page.screenshot({ path: path.join(evidence, 'register-panel-ko.png') });
    await shot(page, panel, 'register-panel-detail-ko.png');

    // Register: the job reports its stages, then the song; the managed server was stopped and restarted.
    await page.locator('#mv-register-submit').click();
    await page.locator('#mv-register-result').filter({ hasText: '등록했습니다' }).waitFor({ timeout: 60000 });
    const result = await page.locator('#mv-register-result').textContent();
    assert.match(result, /'내 MV'\(93000\)를 등록했습니다\./);
    assert.match(result, /게임 서버를 다시 시작했습니다\./);
    assert.match(result, /게임: 라이브 → 곡 목록 → 내 MV → MV 버튼/);
    const job = posted.find((item) => item.url.endsWith('/register-job'));
    assert.deepEqual({ ...job.body, project: undefined }, { mode: 'new', project: undefined, title: '내 MV', credit: '작곡: 테스트',
      jacket: { kind: 'file', path: path.join(server.library, 'modded', 'jacket-wide.png'), crop: { x: 70, y: 0, size: 400 } },
      audio: { kind: 'base' }, platforms: [], download: false, unbaked: [] });
    assert.deepEqual(await page.evaluate(() => MVStudio.getState().project.registration), { region: 'gl', liveId: 93000 });
    const songs = await page.evaluate(async () => (await (await fetch('/api/mv-studio/songs?region=gl')).json()).songs);
    assert.equal(songs.length, 1);
    assert.equal(songs[0].jacket, 'custom');
    assert.equal(songs[0].credit, '작곡: 테스트');
    assert.equal(songs[0].visible, true);
    await page.screenshot({ path: path.join(evidence, 'register-done-ko.png') });

    // The songs list shows the song with open/delete.
    await page.locator('#mv-register-songs summary').click();
    const row = page.locator('[data-mv-song="93000"]');
    await row.waitFor();
    assert.match(await row.textContent(), /내 MV/);
    assert.deepEqual(await row.locator('[data-mv-song-action]').evaluateAll((items) => items.map((item) => item.textContent)), ['열기', '삭제']);
    assert.equal(await page.locator('#mv-register-songs summary').textContent(), '등록한 MV 전용 곡 (1)');
    await shot(page, panel, 'register-songs-ko.png');

    // Update with nothing changed: the registered jacket stays and nothing is written.
    await page.locator('#mv-register-submit').filter({ hasText: '업데이트' }).waitFor();
    assert.equal(await page.locator('#mv-register-target').inputValue(), '93000');
    assert.equal(await page.locator('#mv-register-jacket-keep').getAttribute('aria-pressed'), 'true');
    assert(await page.locator('input[name=mv-register-audio][value=keep]').isChecked());
    const log = () => fs.readFileSync(server.controllerLog, 'utf8').trim().split('\n');
    const before = log().length;
    await page.locator('#mv-register-submit').click();
    await page.locator('#mv-register-result').filter({ hasText: '바뀐 내용이 없습니다.' }).waitFor({ timeout: 30000 });
    assert(!log().slice(before).includes('stop'), 'A no-op update does not stop the game server');
    await page.screenshot({ path: path.join(evidence, 'register-update-noop-ko.png') });

    // Layout: no horizontal overflow at a 360 px inspector in Korean.
    await page.setViewportSize({ width: 900, height: 900 });
    await page.addStyleTag({ content: '#mv-inspector { width: 360px !important; min-width: 360px !important; max-width: 360px !important; }' });
    await page.waitForTimeout(200);
    const overflow = await noOverflow(page);
    assert(overflow.scroll && !overflow.wide.length, JSON.stringify(overflow));
    await shot(page, panel, 'register-narrow-360-ko.png');
    await page.setViewportSize({ width: 1280, height: 900 });

    // Delete: review, dialog, remove job (stops and restarts the managed server), empty list.
    await row.locator('[data-mv-song-action=remove]').click();
    const dialog = page.locator('#mv-register-remove-dialog');
    await dialog.waitFor();
    assert.match(await dialog.textContent(), /'내 MV'를 삭제할까요\?/);
    assert.match(await dialog.textContent(), /곡, 재킷, 음원, 타임라인 파일과 모든 플레이어의 이 곡 MV 덱·플레이 기록·플레이리스트 항목을 지웁니다/);
    await shot(page, panel, 'register-remove-dialog-ko.png');
    const review = posted.find((item) => item.url.endsWith('/songs/remove-plan'));
    assert.deepEqual(review.body, { region: 'gl', liveId: 93000 });
    const removedAt = log().length;
    await dialog.locator('[data-mv-remove=confirm]').click();
    await page.locator('#mv-register-songs').filter({ hasText: '이 지역에 등록한 MV 전용 곡이 없습니다.' }).waitFor({ timeout: 60000 });
    const removal = posted.find((item) => item.url.endsWith('/songs/remove-job'));
    assert.equal(removal.body.liveId, 93000);
    assert.match(removal.body.reviewToken, /^[0-9a-f]{64}$/);
    assert.deepEqual(log().slice(removedAt).filter((call) => call === 'stop' || call === 'start'), ['stop', 'start']);
    assert.deepEqual(await page.evaluate(async () => (await (await fetch('/api/mv-studio/songs?region=gl')).json()).songs), []);
    await shot(page, panel, 'register-removed-ko.png');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    server.child.kill();
    fs.rmSync(server.base, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
