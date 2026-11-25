/* The MV import progress card on the actual MV editor page, fed by a slowed fake
   game stream: plan/progress records in split chunks, percent never going back,
   member count, game data bytes and elapsed time, the strip over the stage, the
   cancel button (which aborts the request), Korean/Japanese/English labels, and an
   older server that sends no progress records. SCREENSHOT_DIR keeps screenshots. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

function attachProbe(language) {
  try { localStorage.setItem('sifas_lang', language); } catch (_) {}
  const probe = window.mvStreamProbe = { urls: [], prepared: [], loaded: [], aborted: 0 };
  const fetchActual = window.fetch;
  window.fetch = (url, options) => {
    if (!String(url).startsWith('/api/mv-studio/game-stream?')) return fetchActual(url, options);
    probe.urls.push(String(url));
    probe.signal = options.signal;
    let stream;
    // Like a real fetch, an abort errors the response body.
    options.signal.addEventListener('abort', () => {
      probe.aborted++;
      try { stream.error(new DOMException('The operation was aborted.', 'AbortError')); } catch (_) {}
    });
    const body = new ReadableStream({ start(writer) { probe.writer = stream = writer; } });
    return Promise.resolve(new Response(body, { headers: { 'Content-Type': 'application/x-ndjson; charset=utf-8' } }));
  };
  const create = document.createElement.bind(document);
  Object.defineProperty(window, 'MVStudioScene', {
    get() {
      return { create(mount) {
        const canvas = create('canvas');
        canvas.style.background = 'linear-gradient(#26304a, #0d1020)';
        mount.append(canvas);
        return {
          setVisible() {},
          prepareStage(value) { probe.prepared.push(value); return new Promise(resolve => { probe.stageReady = resolve; }); },
          cancelStagePreparation() {},
          load(value, choices) {
            probe.loaded.push(value.name);
            probe.loadChoices = choices;
            return new Promise(resolve => { probe.finishLoad = resolve; });
          },
          seek() {}, setPlaying() {}, resize() {}, flushSeekDraw() {}, dispose() {}
        };
      } };
    },
    set() {}
  });
}

async function boot(library) {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const child = spawn(process.env.VIEWER_PYTHON || 'python3', ['-B', '-m', 'webtools', '--no-browser', '--port', String(port)],
    { cwd: path.resolve(__dirname, '..'), env: { ...process.env, SUKUSTA_DIR: library }, stdio: 'ignore' });
  const url = 'http://127.0.0.1:' + port;
  for (let tries = 0; tries < 100; tries++) {
    try { if ((await fetch(url + '/api/tools')).ok) return { child, url }; } catch (_) {}
    if (child.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 75));
  }
  child.kill();
  throw new Error('Isolated MV editor did not start');
}

const MB = 1024 * 1024;
const plan = { type: 'plan', v: 1, members: 2, bytes: Math.round(7.8 * MB), t: 0.2, read: 0, steps: [
  { id: 'resolve', w: 3, label: 'Reading game data…' }, { id: 'timeline', w: 20, label: 'Reading the live timeline…' },
  { id: 'stage', w: 12, label: 'Converting the stage…' }, { id: 'effect', w: 16, label: 'Converting stage effects…' },
  { id: 'member', index: 1, of: 2, w: 35, label: 'Converting member {index}/{count}: {name}' },
  { id: 'member', index: 2, of: 2, w: 35, label: 'Converting member {index}/{count}: {name}' },
  { id: 'audio', w: 5, label: 'Decoding the soundtrack…' }, { id: 'finish', w: 2, label: 'Finishing the MV project…' }] };
const progress = (step, state, extra = {}) => ({ type: 'progress', step, ...(state ? { state } : {}), ...extra });
const model = (key) => '/api/mv-studio/media/' + key.repeat(32) + '.glb';
const stage = { type: 'stage', preview: { stage: { glb: model('b'), label: 'Stage' }, assets: [], tracks: [], quality: {}, duration: 16 } };
const project = { version: 1, name: 'Progress fixture', token: 'a'.repeat(32), duration: 16, stage: { glb: model('b') },
  soundtrack: null, source: { kind: 'game', region: 'gl', platform: 'android', liveId: 12, assetId: 34 },
  tracks: [], assets: [], performers: [], warnings: [], quality: {} };

const EXPECT = {
  ko: { member: '멤버 변환 중 1/2: 上原歩夢', timeline: '라이브 타임라인을 분석하는 중…', members: '멤버 1/2 완료', data: '게임 데이터 3.0/7.8 MB',
        stageReady: '무대가 준비되었습니다. 멤버를 불러오는 중입니다.', cancel: '불러오기 취소', cancelled: 'MV 불러오기를 취소했습니다.',
        textures: '텍스처 12개', dance: '댄스 모션을 만드는 중… 40%', models: '3D 모델을 불러오는 중 0/1…', preparing: '게임에서 MV 준비 중…',
        ready: '재생 준비 완료' },
  ja: { member: 'メンバーを変換中 1/2: 上原歩夢', timeline: 'ライブタイムラインを解析中…', members: 'メンバー 1/2 完了', data: 'ゲームデータ 3.0/7.8 MB',
        stageReady: 'ステージの準備ができました。メンバーを読み込み中です。', cancel: '読み込みをキャンセル', cancelled: 'MVの読み込みをキャンセルしました。',
        textures: 'テクスチャ 12枚', dance: 'ダンスモーションを生成中… 40%', models: '3Dモデルを読み込み中 0/1…', preparing: 'ゲームデータからMVを準備中…',
        ready: '再生の準備ができました' },
  en: { member: 'Converting member 1/2: 上原歩夢', timeline: 'Reading the live timeline…', members: 'Members done 1/2', data: 'Game data 3.0/7.8 MB',
        stageReady: 'Stage is ready. Members are still loading.', cancel: 'Cancel import', cancelled: 'MV import cancelled.',
        textures: 'Textures 12', dance: 'Building dance motion… 40%', models: 'Loading 3D models 0/1…', preparing: 'Preparing MV from game…',
        ready: 'Ready to play' },
};

async function send(page, event, finish = false) {
  // Split each record into uneven chunks, like a slow connection would.
  await page.evaluate(({ event, finish }) => {
    const bytes = new TextEncoder().encode(JSON.stringify(event) + '\n');
    const writer = mvStreamProbe.writer;
    for (let start = 0; start < bytes.length; start += 7 + (start % 5)) writer.enqueue(bytes.subarray(start, start + 7 + (start % 5)));
    if (finish) writer.close();
  }, { event, finish });
  await page.waitForTimeout(30);
}

async function card(page) {
  return page.evaluate(() => {
    const element = document.querySelector('#mv-import-progress');
    const bar = document.querySelector('#mv-import-bar');
    return { hidden: element.hidden, strip: element.classList.contains('mv-import-strip'),
      step: document.querySelector('#mv-import-step').textContent, percent: document.querySelector('#mv-import-percent').textContent,
      detail: document.querySelector('#mv-import-detail').textContent, value: bar.hasAttribute('value') ? bar.value : null,
      valuetext: bar.getAttribute('aria-valuetext'), cancel: document.querySelector('#mv-import-cancel').textContent,
      cancelDisabled: document.querySelector('#mv-import-cancel').disabled, status: document.querySelector('#mv-status').textContent,
      hint: document.querySelector('#mv-empty-preview').hidden };
  });
}

async function run() {
  const library = fs.mkdtempSync(path.join(os.tmpdir(), 'elichika-mv-progress-browser-'));
  const shots = process.env.SCREENSHOT_DIR;
  const server = await boot(library);
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'] });
    for (const language of ['ko', 'ja', 'en']) {
      const expect = EXPECT[language];
      const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(attachProbe, language);
      await page.route('**/api/mv-studio/catalog?*', route => route.fulfill({ json: {
        region: 'gl', platform: 'android', regions: [{ id: 'gl', label: 'GL' }], platforms: [{ id: 'android', label: 'Android' }],
        songs: [{ id: 12, title: 'Fixture song', variants: [{ id: 34, label: 'MV' }] }] } }));
      await page.goto(server.url + '/#mv');
      await page.waitForFunction(() => window.MVStudio && MVStudio.getState().visible);
      const begin = async () => {
        await page.evaluate(() => { mvStreamProbe.writer = null; });
        await page.locator('#mv-import-game').click();
        await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
        await page.locator('#mv-game-load').click();
        await page.waitForFunction(() => !!mvStreamProbe.writer);
      };
      const settled = () => page.waitForFunction(() => !document.querySelector('#mv-import-game').disabled);

      // 1. A full import with progress records.
      await begin();
      assert.match(await page.evaluate(() => mvStreamProbe.urls.at(-1)), /^\/api\/mv-studio\/game-stream\?lang=\w+&progress=1$/);
      let view = await card(page);
      assert.equal(view.hidden, false);
      assert.equal(view.value, null, 'indeterminate before the plan');
      assert.equal(view.hint, true, 'the card replaces the plain loading hint');
      const percents = [];
      const look = async () => { const value = await card(page); percents.push(Number.parseInt(value.percent, 10) || 0); return value; };
      await send(page, plan);
      await send(page, progress('resolve', 'done', { read: 0 }));
      await send(page, progress('timeline', 'start', { read: Math.round(0.3 * MB) }));
      view = await look();
      assert.equal(view.step, expect.timeline);
      assert.equal(view.status, expect.timeline, '#mv-status follows the step');
      await send(page, progress('timeline', 'done'));
      await send(page, progress('stage', 'start'));
      await send(page, progress('stage', 'done'));
      await send(page, progress('effect', 'start'));
      await send(page, progress(null, null, { step: 'effect', phase: 'textures', done: 20 }));
      await send(page, progress('effect', 'cached'));
      await send(page, progress('member', 'start', { index: 1, of: 2, name: '上原歩夢', read: Math.round(3.0 * MB) }));
      await send(page, progress(null, null, { step: 'member', index: 1, of: 2, phase: 'textures', done: 12 }));
      view = await look();
      assert.equal(view.step, expect.member);
      assert(view.detail.includes(expect.textures), view.detail);
      assert(view.detail.includes(expect.data), view.detail);
      assert.match(view.detail, /0:0\d$/);
      if (shots && language === 'ko') await page.screenshot({ path: path.join(shots, 'mv-import-progress-ko-card.png') });
      await send(page, stage);
      await page.waitForFunction(() => mvStreamProbe.prepared.length === 1);
      await page.evaluate(() => mvStreamProbe.stageReady(true));
      await page.waitForFunction(() => document.querySelector('#mv-import-progress').classList.contains('mv-import-strip'));
      await send(page, progress(null, null, { step: 'member', index: 1, of: 2, phase: 'animation', done: 40, total: 100 }));
      view = await look();
      assert(view.detail.includes(expect.dance), view.detail);
      assert(view.valuetext.startsWith(view.percent + ' · '), view.valuetext);
      if (shots && language === 'ko') await page.screenshot({ path: path.join(shots, 'mv-import-progress-ko-strip.png') });
      await send(page, progress('member', 'done', { index: 1, of: 2 }));
      view = await look();
      assert(view.detail.includes(expect.members), view.detail);
      await send(page, progress('member', 'start', { index: 2, of: 2, name: 'Kasumi' }));
      await send(page, progress('member', 'done', { index: 2, of: 2 }));
      await send(page, progress('audio', 'start'));
      await send(page, progress('audio', 'done'));
      await send(page, progress('finish', 'start'));
      await send(page, progress('finish', 'done'));
      view = await look();
      assert.equal(view.percent, '90%');
      await send(page, { type: 'complete', project }, true);
      await page.waitForFunction(() => mvStreamProbe.loaded.length === 1);
      // The page's own model loading is the last tenth of the bar.
      await page.evaluate(() => mvStreamProbe.loadChoices.onProgress({ done: 0, total: 1 }));
      view = await look();
      assert.equal(view.step, expect.models);
      assert.equal(view.cancelDisabled, true, 'nothing to cancel once the project has arrived');
      await page.evaluate(() => { mvStreamProbe.loadChoices.onProgress({ done: 1, total: 1 }); mvStreamProbe.loadChoices.onProgress({ phase: 'effects' }); });
      await look();
      // Every state the card passes through until it goes.
      await page.evaluate(() => {
        const card = document.querySelector('#mv-import-progress');
        window.mvCardSeen = [];
        new MutationObserver(() => mvCardSeen.push(card.hidden ? 'hidden' : document.querySelector('#mv-import-percent').textContent
          + '|' + document.querySelector('#mv-import-step').textContent))
          .observe(card, { subtree: true, childList: true, characterData: true, attributes: true });
      });
      await page.evaluate(() => mvStreamProbe.finishLoad());
      await settled();
      await page.waitForFunction(() => document.querySelector('#mv-import-progress').hidden);
      const seen = await page.evaluate(() => mvCardSeen);
      assert(seen.includes('100%|' + expect.ready), seen.join(' / '));
      percents.push(100);
      view = await card(page);
      assert.equal(view.hidden, true);
      assert.equal(await page.evaluate(() => MVStudio.getState().project.name), 'Progress fixture');
      for (let index = 1; index < percents.length; index++) assert(percents[index] >= percents[index - 1], percents.join(','));
      assert.equal(percents.at(-1), 100, percents.join(','));

      // 2. Cancel aborts the request; the server stops at its next report (tests/test_mv_studio_progress.py).
      await begin();
      await send(page, plan);
      await send(page, progress('member', 'start', { index: 1, of: 2, name: '上原歩夢' }));
      view = await card(page);
      assert.equal(view.cancel, expect.cancel);
      if (shots && language === 'ko') await page.screenshot({ path: path.join(shots, 'mv-import-progress-ko-member.png') });
      await page.locator('#mv-import-cancel').click();
      await settled();
      assert.equal(await page.evaluate(() => mvStreamProbe.aborted), 1);
      view = await card(page);
      assert.equal(view.hidden, true);
      assert.equal(view.status, expect.cancelled);
      assert.equal(await page.evaluate(() => MVStudio.getState().project.name), 'Progress fixture', 'the open project stays');

      // 3. An older server: no plan or progress records, only stage and complete.
      await begin();
      view = await card(page);
      assert.equal(view.step, expect.preparing);
      assert.equal(view.value, null);
      await send(page, stage);
      await page.waitForFunction(() => mvStreamProbe.prepared.length === 2);
      await page.evaluate(() => mvStreamProbe.stageReady(true));
      await page.waitForFunction(() => document.querySelector('#mv-import-progress').classList.contains('mv-import-strip'));
      view = await card(page);
      assert.equal(view.step, expect.stageReady);
      assert.equal(view.value, null, 'still indeterminate');
      assert.equal(view.percent, '');
      await send(page, { type: 'complete', project: { ...project, name: 'Legacy server' } }, true);
      await page.waitForFunction(() => mvStreamProbe.loaded.length === 2);
      await page.evaluate(() => mvStreamProbe.loadChoices.onProgress({ done: 1, total: 2 }));
      view = await card(page);
      assert.equal(view.value, 35, 'the page part is determinate');
      await page.evaluate(() => mvStreamProbe.finishLoad());
      await settled();
      assert.equal(await page.evaluate(() => MVStudio.getState().project.name), 'Legacy server');
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('PASS: MV import progress card (ko/ja/en), monotonic percent, strip over the stage, cancel and older servers');
  } finally {
    if (browser) await browser.close();
    server.child.kill();
    fs.rmSync(library, { recursive: true, force: true });
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
