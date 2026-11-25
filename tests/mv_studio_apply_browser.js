/* Apply to game ("게임에 적용"), end to end in the real workbench against a disposable Elichika-like root:
 * stock MV plan -> apply only the edits (managed server stop/restart) -> edit the same clip again ->
 * another change in the game makes a conflict (listed, nothing written) -> apply all -> restore the
 * original MV -> a project that is not a game import points to registration. Korean screenshots go to
 * EVIDENCE_DIR. Needs the Elichika server app (ELICHIKA_DIR, or modtools inside Elichika). */
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
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-apply-browser-'));
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

// A game import without a native timeline (as the registration test uses): not an apply target.
function plainProject() {
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
  return page.locator('#mv-apply-fields').evaluate((box) => {
    const wide = [];
    const limit = box.getBoundingClientRect().right + 1;
    for (const node of box.querySelectorAll('*')) {
      const rect = node.getBoundingClientRect();
      if (rect.width && rect.right > limit) wide.push(`${node.tagName}#${node.id}.${node.className} ${Math.round(rect.right - limit)}px`);
    }
    return { scroll: box.scrollWidth <= box.clientWidth + 1, wide };
  });
}

async function moveFirstClip(page, seconds) {
  await page.locator('.mv-lane[data-tab] .mv-clip').first().click();
  const start = page.locator('[data-mv-field=start]');
  await start.waitFor();
  await start.fill(String(seconds));
  await start.press('Enter');
}

// The panel shows a fresh check: not checking, and the plan covers the latest edit.
async function checked(page, text) {
  await page.waitForFunction(() => !document.querySelector('#mv-panel-apply').textContent.includes('게임의 타임라인 확인 중…'),
    null, { timeout: 60000 });
  if (text) await page.locator('#mv-panel-apply').filter({ hasText: text }).waitFor({ timeout: 60000 });
}

const timelinesNow = (page) => page.evaluate(async () => (await (await fetch('/api/mv-studio/timelines?region=gl')).json()).timelines);

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
      if (request.method() === 'POST' && /\/api\/mv-studio\/(apply-job|apply-plan|restore-job)/.test(request.url())) {
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
    let imported = server.nativeProject;
    await page.route('**/api/mv-studio/game?*', (route) => route.fulfill({ json: imported }));
    const load = async () => {
      await page.locator('#mv-import-game').click();
      await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
      await page.locator('#mv-game-load').click();
      await page.waitForFunction(() => MVStudio.getState().project?.source?.liveId === 21);
    };
    await load();

    // The toolbar shortcut opens the panel; the plan is checked on open (real server, no writes).
    const panel = page.locator('#mv-panel-apply');
    assert.equal(await panel.locator(':scope > summary').textContent(), '게임에 적용');
    const shortcut = page.locator('#mv-apply-open');
    await shortcut.waitFor();
    assert.equal(await shortcut.textContent(), '게임에 적용');
    assert.equal(await page.evaluate(() => document.querySelector('#mv-export-timeline').nextElementSibling.id), 'mv-apply-open');
    await shortcut.click();
    await checked(page, '수정 사항: 불러온 뒤 없음');
    assert.equal(await page.locator('#mv-apply-target').textContent(), '게임 MV: Base song (21) · Star stage');
    assert.equal(await page.locator('#mv-apply-game').textContent(), '게임: 원본 MV · 불러온 것: 원본 MV');
    assert.match(await page.locator('#mv-apply-plan').textContent(), /전체 적용: 게임이 이미 이 프로젝트대로 재생합니다\./);
    assert(await page.locator('#mv-apply-edits').isDisabled(), 'Nothing to apply');
    assert(await page.locator('#mv-apply-all').isDisabled(), 'The game already plays the project');
    assert.equal(await page.locator('#mv-apply-restore').count(), 0);
    assert.deepEqual(log(), []);
    await shot(page, panel, 'apply-stock-ko.png');

    // Apply only the edits: one clip moved; the managed game server stops for the write and restarts.
    await moveFirstClip(page, 0.25);
    await checked(page, '불러온 뒤 수정: 클립 1개 (카메라 0 · 값 0 · 타이밍 1)');
    await page.locator('#mv-apply-edits').waitFor({ state: 'visible' });
    await page.waitForFunction(() => !document.querySelector('#mv-apply-edits').disabled);
    await page.screenshot({ path: path.join(evidence, 'apply-edits-ready-ko.png') });
    let mark = log().length;
    await page.locator('#mv-apply-edits').click();
    await page.locator('#mv-apply-result').filter({ hasText: '게임에 적용했습니다: Base song.' }).waitFor({ timeout: 90000 });
    assert.equal(await page.locator('#mv-apply-result-server').textContent(), '게임 서버를 다시 시작했습니다.');
    assert.match(await page.locator('#mv-apply-result').textContent(), /백업: \S+mv-studio-timeline-2101/);
    assert.deepEqual(log().slice(mark).filter((call) => call === 'stop' || call === 'start'), ['stop', 'start']);
    const job = posted.filter((item) => item.url.endsWith('/apply-job')).pop();
    assert.deepEqual({ ...job.body, project: undefined }, { mode: 'edits', project: undefined, platforms: ['android', 'ios'],
      download: false, expected: { key: 'A2101' }, unbaked: [] });
    let timelines = await timelinesNow(page);
    assert.deepEqual([timelines.length, timelines[0].revision, timelines[0].platforms], [1, 1, { android: 'custom', ios: 'custom' }]);
    await checked(page, '수정 사항: 마지막 적용 이후 없음');
    assert.match(await page.locator('#mv-apply-game').textContent(), /^게임: MV Studio 버전 1 \(\d{4}-\d{2}-\d{2}\) · 불러온 것: 원본 MV$/);
    const applied = await page.evaluate(() => MVStudio.getState().project.source.applied);
    assert.deepEqual(Object.keys(applied.fields), ['cab-1:10:0']);
    await page.locator('#mv-apply-restore').waitFor();
    await shot(page, panel, 'apply-edits-done-ko.png');

    // The same clip edited again: no conflict with this project's own earlier apply.
    await moveFirstClip(page, 0.5);
    await checked(page, '마지막 적용 이후 수정: 클립 1개');
    assert.equal(await page.locator('#mv-apply-conflicts').count(), 0);
    await page.waitForFunction(() => !document.querySelector('#mv-apply-edits').disabled);
    await page.locator('#mv-apply-edits').click();
    await page.locator('#mv-apply-result').filter({ hasText: '게임에 적용했습니다' }).waitFor({ timeout: 90000 });
    await checked(page, '수정 사항: 마지막 적용 이후 없음');
    timelines = await timelinesNow(page);
    assert.equal(timelines[0].revision, 2);

    // Another project changes that clip in the game (Apply all from the stock): this project's next
    // edit of it is a conflict. It is listed, nothing is written, and the server keeps running.
    const other = await page.evaluate(async ({ project, key }) => {
      project.tracks[0].events[0].start = 0.75;
      const response = await fetch('/api/mv-studio/apply-job', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'all', project, platforms: ['android', 'ios'], expected: { key } }) });
      const { job_id: id } = await response.json();
      return new Promise((resolve) => {
        const events = new EventSource('/api/jobs/' + id + '/events');
        events.onmessage = (raw) => { const event = JSON.parse(raw.data); if (event.type === 'done') { events.close(); resolve(event); } };
      });
    }, { project: server.nativeProject, key: timelines[0].timelineKey });
    assert.equal(other.status, 'done', JSON.stringify(other));
    await moveFirstClip(page, 1);
    await checked(page, '게임에서 다르게 바뀐 항목 (1)');
    const conflicts = await page.locator('#mv-apply-conflicts').textContent();
    assert.match(conflicts, /CameraMotion\/Camera1 · cut1 \(0\.00s\) · 시작 시간 \(초\): 불러온 값 0 → 프로젝트 1, 게임 0\.75/);
    assert.match(conflicts, /아무것도 덮어쓰지 않았습니다\./);
    assert.match(await page.locator('#mv-apply-plan').textContent(), /이 프로젝트를 불러온 뒤 게임의 MV가 바뀌었습니다/);
    assert(await page.locator('#mv-apply-edits').isDisabled(), 'A conflict blocks Apply only the edits');
    assert(await page.locator('#mv-apply-all').isEnabled());
    await shot(page, panel, 'apply-conflict-ko.png');

    // Apply all, behind a confirm naming the version it replaces and the backup.
    mark = log().length;
    await page.locator('#mv-apply-all').click();
    const confirm = page.locator('#mv-apply-confirm');
    await confirm.waitFor();
    assert.match(await confirm.textContent(), /'전체 적용'은 게임의 MV Studio 버전 3을 이 프로젝트로 바꿉니다\. 먼저 백업합니다\. 계속할까요\?/);
    await shot(page, panel, 'apply-all-confirm-ko.png');
    await page.locator('#mv-apply-confirm-yes').click();
    await page.locator('#mv-apply-result').filter({ hasText: '게임에 적용했습니다' }).waitFor({ timeout: 90000 });
    assert.deepEqual(log().slice(mark).filter((call) => call === 'stop' || call === 'start'), ['stop', 'start']);
    await checked(page, '전체 적용: 게임이 이미 이 프로젝트대로 재생합니다.');
    assert.equal(await page.locator('#mv-apply-conflicts').count(), 0);
    assert.equal((await timelinesNow(page))[0].revision, 4);

    // Restore the original MV: confirm, backup, server stop/restart; the game plays the stock again.
    mark = log().length;
    await page.locator('#mv-apply-restore').click();
    await confirm.waitFor();
    assert.match(await confirm.textContent(), /원본 MV로 되돌릴까요\? MV Studio 버전 4은 백업에 남습니다\./);
    await page.locator('#mv-apply-confirm-yes').click();
    await page.locator('#mv-apply-result').filter({ hasText: '원본 MV로 되돌렸습니다: Base song.' }).waitFor({ timeout: 90000 });
    assert.match(await page.locator('#mv-apply-result').textContent(), /백업: \S+mv-studio-restore-2101/);
    assert.deepEqual(log().slice(mark).filter((call) => call === 'stop' || call === 'start'), ['stop', 'start']);
    await checked(page, '게임: 원본 MV');
    assert.deepEqual(await timelinesNow(page), []);
    assert.equal(await page.locator('#mv-apply-restore').count(), 0);
    assert.equal(await page.evaluate(() => 'applied' in MVStudio.getState().project.source), false);
    await shot(page, panel, 'apply-restored-ko.png');

    // Layout: no horizontal overflow at a 360 px inspector in Korean.
    await page.setViewportSize({ width: 900, height: 900 });
    await page.addStyleTag({ content: '#mv-inspector { width: 360px !important; min-width: 360px !important; max-width: 360px !important; }' });
    await page.waitForTimeout(200);
    const overflow = await noOverflow(page);
    assert(overflow.scroll && !overflow.wide.length, JSON.stringify(overflow));
    await shot(page, panel, 'apply-narrow-360-ko.png');
    await page.setViewportSize({ width: 1280, height: 900 });

    // A game import without a native timeline is not an apply target: the panel points to registration.
    imported = plainProject();
    await load();
    await page.waitForFunction(() => MVStudio.getState().project?.nativeTimeline === false);
    assert(await shortcut.isHidden(), 'No native timeline: no shortcut');
    if (!(await panel.evaluate((node) => node.open))) await panel.locator(':scope > summary').click();
    await page.locator('#mv-apply-status').filter({ hasText: '게임에 적용하려면 게임에서 MV를 불러오세요.' }).waitFor({ timeout: 60000 });
    await page.locator('#mv-apply-register').click();
    assert(await page.locator('#mv-panel-register').evaluate((node) => node.open), 'The registration panel opens');
    await shot(page, panel, 'apply-not-game-ko.png');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', evidence }));
  } finally {
    if (browser) await browser.close();
    server.child.kill();
    fs.rmSync(server.base, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
