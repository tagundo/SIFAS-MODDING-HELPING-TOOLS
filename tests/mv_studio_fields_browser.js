/* MV Studio inspector value controls in the real workbench (Korean UI):
   - every control kind (HDR colour swatch, ×intensity, exact channels, slider, vector,
     enum, observed enum, facial index, 0/1 checkbox, text) is one undo step, with real
     pointer presses and a keyboard-opened picker, and undo/redo restore the project;
   - an observed field offers only the values its track already uses; read-only values
     and the collapsed native data carry no data-mv-field; Korean labels and the
     "Not shown in the preview" badge;
   - opening every clip's inspector changes nothing: the project stays deep-equal to its
     input with no project.editor;
   - with the original 1203503 timeline (ELICHIKA_STUDIO_TIMELINE_DIR, optional): a
     project saved with the editableValues lists from before this change opens, shows
     its inspectors and exports the original bytes; an observed textureIndex edit
     exports and parses back; an unobserved index forced past the offered options is
     refused with the server's guard message in Korean; after undo the export is the
     original bytes again.
   Screenshots go to EVIDENCE_DIR. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.VIEWER_PYTHON || 'python3';
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'mv-fields-library-'));
const modded = path.join(library, 'modded');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mv-fields-browser-'));
fs.mkdirSync(modded, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
const samples = process.env.ELICHIKA_STUDIO_TIMELINE_DIR || '/unavailable-studio-samples';
const timeline12035 = path.join(samples, 'a-1203503-live_timeline.unity');

async function startServer() {
  const socket = net.createServer();
  await new Promise((resolve) => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  const processLog = fs.openSync(path.join(evidence, 'server.log'), 'w');
  const processHandle = spawn(python, ['-B', '-m', 'webtools', '--no-browser', '--port', String(port)], {
    cwd: root, env: { ...process.env, SUKUSTA_DIR: library }, stdio: ['ignore', processLog, processLog],
  });
  fs.closeSync(processLog);
  const url = 'http://127.0.0.1:' + port;
  for (let count = 0; count < 100; count++) {
    try { if ((await fetch(url + '/api/tools')).ok) return { processHandle, url }; } catch (_) {}
    if (processHandle.exitCode !== null) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  processHandle.kill();
  throw new Error('Isolated workbench did not start');
}

const colour = (r, g, b, a = 1) => ({ r, g, b, a });
function event(id, label, start, values, editableValues) {
  return { id, label, start, duration: 2, values: { clipIn: 0, timeScale: 1, easeIn: 0, easeOut: 0, blendIn: -1, blendOut: -1,
    preExtrapolationMode: 0, postExtrapolationMode: 0, preExtrapolationTime: 0, postExtrapolationTime: 0, asset: 'cab:' + id, ...values },
  editableValues: ['clipIn', 'timeScale', 'easeIn', 'easeOut', 'blendIn', 'blendOut', 'preExtrapolationMode', 'postExtrapolationMode',
    'preExtrapolationTime', 'postExtrapolationTime', ...editableValues] };
}

// A game project with one clip of each control kind (values shaped as the parser gives them).
function syntheticProject() {
  const members = '/EntryPoint/Live/Members/Member1';
  return { version: 1, name: '필드 MV', duration: 20, nativeTimeline: false, assets: [], warnings: [], quality: {},
    source: { kind: 'game', region: 'gl', platform: 'android', liveId: 98, assetId: 1 },
    performers: [{ id: 'member-1', label: '우에하라 아유무', position: 1, transform: { position: [0, 0, 0] } }],
    tracks: [
      { id: 'rim', kind: 'lighting', nativeClass: 'LiveRimlightTrack', label: 'MemberEffect/Expert/Rimlight/Member1', binding: members, events: [
        event('rim:0', 'Rim', 0, { playableClass: 'LiveRimlightClip', colorSpecifiedType: 0, color: colour(2, 1, .5, .25), memberPosition: 1,
          intensity: 1, sharpness: 8, direction: { x: -24, y: 12, z: 0 }, mixIn: [{ time: 0, value: 0 }, { time: 1, value: 1 }] },
        ['color', 'colorSpecifiedType', 'direction', 'intensity', 'sharpness'])] },
      { id: 'coloring', kind: 'stage', nativeClass: 'LiveColoringTrack', label: 'StageEffect/Expert/Coloring/LED_panel_01', events: [
        event('coloring:0', 'LED A', 0, { playableClass: 'LiveColoringClip', shift: 3, tintColor: colour(0, 0, 0, 0), speed: .5, textureIndex: 0 },
          ['shift', 'speed', 'textureIndex', 'tintColor']),
        event('coloring:1', 'LED B', 4, { playableClass: 'LiveColoringClip', shift: 0, tintColor: colour(1, 1, 1, 1), speed: 0, textureIndex: 2 },
          ['shift', 'speed', 'textureIndex', 'tintColor'])] },
      { id: 'coloring-b', kind: 'stage', nativeClass: 'LiveColoringTrack', label: 'StageEffect/Expert/Coloring/LED_panel_02', events: [
        event('coloring-b:0', 'LED C', 0, { playableClass: 'LiveColoringClip', shift: 0, tintColor: colour(0, 0, 0, 0), speed: 0, textureIndex: 5 },
          ['shift', 'speed', 'textureIndex', 'tintColor'])] },
      { id: 'bloom', kind: 'bloom', nativeClass: 'LiveBloomTrack', label: 'StageEffect/Expert/Post/Bloom', binding: '/EntryPoint/Live/Cameras/MainCamera', events: [
        event('bloom:0', 'Bloom', 0, { playableClass: 'LiveBloomClip', intensity: .3, threshold: 1, softKnee: .3, radius: 4, antiFlicker: 0 },
          ['antiFlicker', 'intensity', 'radius', 'softKnee', 'threshold'])] },
      { id: 'eye', kind: 'eyes', nativeClass: 'MemberEyeTrack', label: 'MemberFacial/Expert/Member1/Eye', binding: members, events: [
        event('eye:0', 'Eye', 0, { playableClass: 'MemberEyeClip', index: 1, weight: 1, splitScreenSetting: { UseSetting: 0, Index: 1, Weight: 1 } },
          ['index', 'weight'])] },
      { id: 'lip', kind: 'mouth', nativeClass: 'MemberLipSyncTrack', label: 'MemberFacial/Expert/Member1/LipSync', binding: members, events: [
        event('lip:0', 'A', 0, { playableClass: 'MemberLipSyncClip', paramName: 'a', index: 13, weight: .693 }, ['index', 'paramName', 'weight'])] },
      { id: 'fx', kind: 'effects', nativeClass: 'CustomControlTrack', label: 'StageEffect/Expert/Control/fx', events: [
        event('fx:0', 'fx_par_01', 0, { playableClass: 'CustomControlClip', prefabGameObject: { m_FileID: 0, m_PathID: '223836546502069450' },
          particleRandomSeed: 7548, overwriteRandomSeed: 0, weight: 1, offset: { x: 0, y: 0, z: 0 } }, ['offset', 'weight'])] },
    ] };
}

const state = (page) => page.evaluate(() => MVStudio.getState());
// The inspector scrolled to one value row, captured as the side panel shows it.
async function shotInspector(page, selector, file) {
  await page.locator(selector).first().evaluate((element) => {
    const inspector = document.getElementById('mv-inspector');
    inspector.scrollTop += element.getBoundingClientRect().top - inspector.getBoundingClientRect().top - 8;
  });
  await page.locator('#mv-inspector').screenshot({ path: path.join(evidence, file) });
}
const undoCount = async (page) => (await state(page)).history.undo;
const value = async (page, id, key) => (await state(page)).project.tracks.flatMap((track) => track.events).find((item) => item.id === id).values[key];
const select = (page, id) => page.evaluate((target) => document.querySelector(`.mv-clip[data-event="${target}"]`).click(), id);
const field = (page, name) => page.locator(`#mv-event-fields [data-mv-field="${name}"]`);

async function expectStep(page, before, label = 'one undo step') {
  const after = await state(page);
  assert.equal(after.history.undo, before + 1, label);
  assert.equal(after.history.undoLabel, 'Edit value', label);
  return after.history.undo;
}

async function openSynthetic(browser, url) {
  const page = await browser.newPage({ locale: 'ko', viewport: { width: 1366, height: 1100 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const project = syntheticProject();
  await page.route('**/api/mv-studio/catalog?*', (route) => route.fulfill({ json: { region: 'gl', platform: 'android',
    regions: [{ id: 'gl', label: 'GL' }], platforms: [{ id: 'android', label: 'Android' }],
    songs: [{ id: 98, title: '필드 MV', variants: [{ id: 1, label: 'MV' }] }] } }));
  await page.route('**/api/mv-studio/game-stream?*', (route) => route.fulfill({ status: 404 }));
  await page.route('**/api/mv-studio/game?*', (route) => route.fulfill({ json: project }));
  await page.goto(url + '/?lang=ko#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  await page.evaluate(() => { localStorage.setItem('language', 'ko'); });
  await page.locator('#mv-import-game').click();
  await page.locator('#mv-game-song option').first().waitFor({ state: 'attached' });
  await page.waitForFunction(() => !document.querySelector('#mv-game-load').disabled);
  await page.locator('#mv-game-load').click();
  await page.locator('.mv-clip[data-event="rim:0"]').waitFor();
  return { page, errors, project };
}

async function synthetic(browser, url) {
  const { page, errors, project } = await openSynthetic(browser, url);
  await page.locator('#mv-events').evaluate((panel) => { panel.open = true; });

  // Opening every inspector edits nothing.
  for (const track of project.tracks) for (const item of track.events) await select(page, item.id);
  let current = await state(page);
  assert.deepEqual(current.project.tracks, project.tracks, 'opening the inspectors leaves every clip as it was');
  assert.equal('editor' in current.project, false, 'no project.editor before an edit');
  assert.equal(current.history.undo, 0);

  // Rim light: colour swatch, intensity, exact channels, colour source, vector; read-only member.
  await select(page, 'rim:0');
  assert.equal(await page.locator('#mv-event-fields [data-mv-value=color] .mv-value-label').first().textContent(), '색');
  assert.equal(await field(page, 'color').getAttribute('type'), 'color');
  assert.equal(await field(page, 'color').inputValue(), '#ff8040');
  assert.equal(await field(page, 'color.intensity').inputValue(), '2');
  assert.deepEqual(await page.locator('#mv-event-fields [data-mv-field=colorSpecifiedType] option').allTextContents(),
    ['직접 지정한 색', '멤버 색', '원래 멤버 색']);
  const member = page.locator('#mv-event-fields [data-mv-value=memberPosition]');
  assert.equal(await member.locator('output').textContent(), '멤버 1 · 우에하라 아유무');
  assert.equal(await member.locator('[data-mv-field]').count(), 0, 'read-only values carry no data-mv-field');
  assert.deepEqual(await page.locator('#mv-event-fields [data-mv-value=direction] .mv-axis > span').allTextContents(), ['X', 'Y', 'Z']);
  assert.equal(await page.locator('#mv-event-fields [data-mv-value=direction] .mv-value-label').textContent(), '방향 (°)');
  const native = page.locator('#mv-native-fields');
  assert.equal(await native.evaluate((element) => element.open), false, 'native data starts collapsed');
  assert.equal(await native.locator('summary').textContent(), '원본 데이터 (읽기 전용)');
  assert.deepEqual(await native.locator('[data-mv-native]').evaluateAll((items) => items.map((item) => item.dataset.mvNative)),
    ['asset', 'playableClass', 'mixIn']);
  assert.equal(await native.locator('[data-mv-field]').count(), 0);
  assert.equal(await page.locator('#mv-event-fields [data-mv-field=asset]').count(), 0, 'identity keys leave the value list');

  // Colour picker opened with the mouse: press, click, several picker inputs, change.
  let before = await undoCount(page);
  await field(page, 'color').click();
  await field(page, 'color').evaluate((swatch) => {
    for (const hex of ['#00ff00', '#20ff40', '#4080ff']) {
      swatch.value = hex;
      swatch.dispatchEvent(new Event('input', { bubbles: true }));
    }
    swatch.dispatchEvent(new Event('change', { bubbles: true }));
  });
  before = await expectStep(page, before, 'a mouse-opened picker session is one step');
  assert.deepEqual(await value(page, 'rim:0', 'color'), { r: round(0x40 / 255 * 2), g: round(0x80 / 255 * 2), b: 2, a: .25 },
    'the pick keeps ×2 and the alpha');
  assert.equal(await field(page, 'color.intensity').inputValue(), '2');
  await page.locator('#mv-event-fields .mv-color-channels summary').first().click();
  await shotInspector(page, '#mv-event-fields [data-mv-value=colorSpecifiedType]', 'fields-rimlight-ko.png');

  // A picker opened from the keyboard (Enter → click, no pointerdown) is one step too.
  await field(page, 'color').focus();
  await page.keyboard.press('Enter');
  await field(page, 'color').evaluate((swatch) => {
    for (const hex of ['#ff0000', '#ff2000']) {
      swatch.value = hex;
      swatch.dispatchEvent(new Event('input', { bubbles: true }));
    }
    swatch.dispatchEvent(new Event('change', { bubbles: true }));
  });
  before = await expectStep(page, before, 'a keyboard-opened picker session is one step');
  assert.deepEqual(await value(page, 'rim:0', 'color'), { r: 2, g: round(0x20 / 255 * 2), b: 0, a: .25 });

  // ×intensity and an exact channel: one step each.
  await field(page, 'color.intensity').fill('4');
  await field(page, 'color.intensity').press('Enter');
  await field(page, 'color.intensity').evaluate((box) => box.blur());
  before = await expectStep(page, before, 'the intensity box is one step');
  assert.deepEqual(await value(page, 'rim:0', 'color'), { r: 4, g: round(round(0x20 / 255 * 2) / 2 * 4), b: 0, a: .25 });
  await field(page, 'color.a').fill('0.5');
  await field(page, 'color.a').evaluate((box) => box.blur());
  before = await expectStep(page, before, 'an exact channel is one step');
  assert.equal((await value(page, 'rim:0', 'color')).a, .5);

  // Enum and vector.
  await field(page, 'colorSpecifiedType').selectOption('1');
  before = await expectStep(page, before, 'a select is one step');
  assert.equal(await value(page, 'rim:0', 'colorSpecifiedType'), 1);
  await field(page, 'direction.y').fill('-6.5');
  await field(page, 'direction.y').evaluate((box) => box.blur());
  before = await expectStep(page, before, 'a vector box is one step');
  assert.deepEqual(await value(page, 'rim:0', 'direction'), { x: -24, y: -6.5, z: 0 });

  // Undo by keyboard restores the colour source; redo brings it back.
  await field(page, 'color').focus();
  await page.keyboard.press('Control+z');
  assert.deepEqual(await value(page, 'rim:0', 'direction'), { x: -24, y: 12, z: 0 });
  await page.keyboard.press('Control+Shift+z');
  assert.deepEqual(await value(page, 'rim:0', 'direction'), { x: -24, y: -6.5, z: 0 });
  assert.equal(await undoCount(page), before);

  // Bloom: a real slider drag is one step; a click on the track is one more; the box too.
  await select(page, 'bloom:0');
  assert.equal(await page.locator('#mv-event-fields [data-mv-value=softKnee] .mv-value-label').textContent(), '소프트 니');
  const range = page.locator('#mv-event-fields [data-mv-range=softKnee]');
  const box = await range.boundingBox();
  await page.mouse.move(box.x + box.width * .3, box.y + box.height / 2);
  await page.mouse.down();
  for (const fraction of [.4, .5, .6, .7, .75]) await page.mouse.move(box.x + box.width * fraction, box.y + box.height / 2, { steps: 2 });
  await page.mouse.up();
  before = await expectStep(page, before, 'a slider drag is one step');
  const dragged = await value(page, 'bloom:0', 'softKnee');
  assert(dragged > .6 && dragged < .9, `dragged to ${dragged}`);
  assert.equal(Number(await field(page, 'softKnee').inputValue()), dragged, 'the number box follows the slider');
  await page.mouse.click(box.x + box.width * .2, box.y + box.height / 2);
  before = await expectStep(page, before, 'a click on the slider is one step');
  assert(await value(page, 'bloom:0', 'softKnee') < .3);
  await shotInspector(page, '#mv-event-fields [data-mv-value=intensity]', 'fields-bloom-ko.png');
  await range.focus();
  await page.keyboard.press('ArrowRight');
  before = await expectStep(page, before, 'a slider key press is one step');
  await field(page, 'softKnee').fill('0.45');
  await field(page, 'softKnee').evaluate((item) => item.blur());
  before = await expectStep(page, before, 'the slider number box is one step');
  assert.equal(await value(page, 'bloom:0', 'softKnee'), .45);
  assert.equal(await range.inputValue(), '0.45');
  // 0/1 checkbox keeps an int.
  await field(page, 'antiFlicker').check();
  before = await expectStep(page, before, 'a checkbox is one step');
  assert.equal(await value(page, 'bloom:0', 'antiFlicker'), 1);

  // Coloring: textureIndex offers only this track's values {0, 2}; a read-only value has no field.
  await select(page, 'coloring:0');
  assert.deepEqual(await page.locator('#mv-event-fields [data-mv-field=textureIndex] option').evaluateAll((options) =>
    options.map((option) => [option.value, option.textContent])), [['0', '조명 텍스처 0'], ['2', '조명 텍스처 2']]);
  await field(page, 'textureIndex').selectOption('2');
  before = await expectStep(page, before, 'an observed select is one step');
  assert.equal(await value(page, 'coloring:0', 'textureIndex'), 2);
  await field(page, 'shift').fill('7.6');
  await field(page, 'shift').evaluate((item) => item.blur());
  before = await expectStep(page, before, 'an integer box is one step');
  assert.equal(await value(page, 'coloring:0', 'shift'), 8, 'integer fields write whole numbers');

  // Eye index from the live ids; lip-sync parameter name with its badge.
  await select(page, 'eye:0');
  assert.equal(await page.locator('#mv-event-fields [data-mv-field=index] option').count(), 23);
  await field(page, 'index').selectOption('16');
  before = await expectStep(page, before, 'a facial index select is one step');
  assert.equal(await value(page, 'eye:0', 'index'), 16);
  await select(page, 'lip:0');
  assert.equal(await page.locator('#mv-event-fields [data-mv-value=paramName] .mv-field-badge').textContent(), '미리보기에 표시되지 않음');
  await field(page, 'paramName').fill('o');
  await field(page, 'paramName').press('Enter');
  await field(page, 'paramName').evaluate((item) => item.blur());
  before = await expectStep(page, before, 'a text field is one step');
  assert.equal(await value(page, 'lip:0', 'paramName'), 'o');
  await select(page, 'fx:0');
  assert.equal(await page.locator('#mv-event-fields [data-mv-value=offset] .mv-field-badge').count(), 1);
  await page.locator('#mv-native-fields summary').click();
  await shotInspector(page, '#mv-event-fields [data-mv-value=weight]', 'fields-native-data-ko.png');

  // Undo everything with the button: the project is the input again; redo all returns.
  const edited = (await state(page)).project.tracks;
  while ((await undoCount(page)) > 0) await page.locator('#mv-undo').click();
  current = await state(page);
  assert.deepEqual(current.project.tracks, project.tracks, 'undoing every step restores the input');
  while ((await state(page)).history.redo > 0) await page.locator('#mv-redo').click();
  assert.deepEqual((await state(page)).project.tracks, edited, 'redo restores every edit');
  await select(page, 'eye:0');
  await shotInspector(page, '#mv-event-fields [data-mv-value=index]', 'fields-eye-ko.png');
  await select(page, 'coloring:0');
  await shotInspector(page, '#mv-event-fields [data-mv-value=shift]', 'fields-coloring-ko.png');
  await page.screenshot({ path: path.join(evidence, 'fields-workbench-ko.png') });
  assert.deepEqual(errors, []);
  await page.close();
}

function round(number) { return Math.round(number * 1e6) / 1e6; }

// The original 1203503 timeline saved as a project from before this change.
function savedProject() {
  const code = String.raw`
import json, sys, shutil
from pathlib import Path
sys.path.insert(0, 'tests')
from webtools.core import mv_studio, mv_studio_timeline as studio
import test_mv_studio_editable_values as fields
raw = Path(sys.argv[1]).read_bytes()
parsed = studio.parse_timeline(raw, 'a-1203503-live_timeline.unity')
project = mv_studio._blank('Fields 1203503')
project['duration'] = parsed['duration']
project['tracks'] = fields.old_lists(parsed['tracks'])
saved = mv_studio.save(mv_studio._register(project, raw))
target = Path(sys.argv[2]) / 'fields-1203503.zip'
shutil.copyfile(saved['path'], target)
def find(native, label=None, wanted=None):
    for track in parsed['tracks']:
        for event in track['events']:
            if event['values'].get('playableClass') == native and (label is None or track['label'].endswith(label)) and (
                    wanted is None or all(event['values'].get(key) == value for key, value in wanted.items())):
                return event['id']
print(json.dumps({'zip': str(target), 'coloring': find('LiveColoringClip', '/LED_panel_01', {'textureIndex': 0}),
                  'rim': find('LiveRimlightClip'), 'eye': find('MemberEyeClip'), 'dof': find('LiveDepthOfFieldClip'),
                  'prop': find('LivePropAmbientClip'), 'scaling': find('LiveMemberScalingClip'),
                  'old': sum(not studio.needs_editable_values_sync(track) for track in project['tracks'])}))
`;
  const run = spawnSync(python, ['-c', code, timeline12035, modded], { cwd: root, env: { ...process.env, SUKUSTA_DIR: library }, encoding: 'utf8' });
  if (run.status !== 0) throw new Error(run.stderr);
  return JSON.parse(run.stdout.trim().split('\n').at(-1));
}

function parsedValue(file, id, key) {
  const code = String.raw`
import json, sys
from pathlib import Path
from webtools.core import mv_studio_timeline as studio
parsed = studio.parse_timeline(Path(sys.argv[1]).read_bytes(), 'export')
print(json.dumps(next(event['values'][sys.argv[3]] for track in parsed['tracks'] for event in track['events'] if event['id'] == sys.argv[2])))
`;
  const run = spawnSync(python, ['-c', code, file, id, key], { cwd: root, encoding: 'utf8' });
  if (run.status !== 0) throw new Error(run.stderr);
  return JSON.parse(run.stdout.trim());
}

async function exportTimeline(page, previous) {
  await page.locator('#mv-export-timeline').click();
  await page.waitForFunction((last) => {
    const link = document.querySelector('#mv-save-result a');
    return link && link.title.endsWith('.unity') && link.title !== last && !document.querySelector('#mv-export-timeline').disabled;
  }, previous, { timeout: 120000 });
  return page.locator('#mv-save-result a').getAttribute('title');
}

async function original12035(browser, url) {
  const raw = fs.readFileSync(timeline12035);
  const saved = savedProject();
  assert(saved.coloring && saved.rim && saved.eye && saved.dof && saved.prop && saved.scaling, JSON.stringify(saved));
  const page = await browser.newPage({ locale: 'ko', viewport: { width: 1366, height: 1100 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(url + '/?lang=ko#mv');
  await page.waitForFunction(() => MVStudio.getState().visible);
  await page.locator('#mv-open').click();
  await page.waitForFunction((expected) => document.getElementById('picker-crumb').textContent === expected, modded);
  await page.locator('#picker-entries li').filter({ hasText: 'fields-1203503.zip' }).click();
  await page.waitForFunction(() => MVStudio.getState().project?.tracks?.length > 60, null, { timeout: 120000 });
  await page.locator(`.mv-clip[data-event="${saved.coloring}"]`).waitFor({ state: 'attached' });
  const opened = (await state(page)).project;
  assert.equal('editor' in opened, false);
  const listed = opened.tracks.flatMap((track) => track.events).find((item) => item.id === saved.coloring).editableValues;
  assert(listed.includes('textureIndex'), 'the saved project took the current editableValues when it opened');
  await page.locator('#mv-events').evaluate((panel) => { panel.open = true; });
  for (const id of [saved.rim, saved.eye, saved.dof, saved.prop, saved.scaling, saved.coloring]) await select(page, id);
  assert.deepEqual((await state(page)).project, opened, 'inspecting the original clips changes nothing');

  const unedited = await exportTimeline(page, null);
  assert.equal(Buffer.compare(fs.readFileSync(unedited), raw), 0, 'an unedited original exports byte-identically');

  // Only the values LED_panel_01 already uses are offered.
  assert.deepEqual(await page.locator('#mv-event-fields [data-mv-field=textureIndex] option').evaluateAll((options) =>
    options.map((option) => option.value)), ['0', '5']);
  await field(page, 'textureIndex').selectOption('5');
  assert.equal((await state(page)).history.undo, 1);
  await shotInspector(page, '#mv-event-fields [data-mv-value=shift]', 'fields-12035-coloring-ko.png');
  const edited = await exportTimeline(page, unedited);
  assert.notEqual(Buffer.compare(fs.readFileSync(edited), raw), 0);
  assert.equal(parsedValue(edited, saved.coloring, 'textureIndex'), 5, 'the observed index exports and parses back');

  // An index the track does not use, forced past the offered options: the export is
  // refused and the guard message arrives in the page's language.
  await field(page, 'textureIndex').evaluate((select) => {
    select.add(new Option('3', '3'));
    select.value = '3';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  assert.equal((await state(page)).history.undo, 2);
  await page.locator('#mv-export-timeline').click();
  await page.waitForFunction(() => {
    const status = document.querySelector('#mv-status');
    return status && !status.hidden && status.classList.contains('mv-error') && !document.querySelector('#mv-export-timeline').disabled;
  }, null, { timeout: 120000 });
  const refusal = await page.locator('#mv-status').textContent();
  assert(refusal.includes("이 MV에서 이미 쓰는 'textureIndex' 값 중에서 고르세요."), refusal);
  assert.equal(await page.locator('#mv-save-result a').getAttribute('title'), edited, 'a refused export writes no file');
  await page.locator('#mv-undo').click();
  await page.locator('#mv-undo').click();
  const undone = await exportTimeline(page, edited);
  assert.equal(Buffer.compare(fs.readFileSync(undone), raw), 0, 'after undo the export is the original bytes again');
  assert.deepEqual(errors, []);
  await page.close();
  return { unedited, edited, undone };
}

(async () => {
  const { processHandle, url } = await startServer();
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const result = { status: 'PASS', evidence };
  try {
    await synthetic(browser, url);
    if (fs.existsSync(timeline12035)) result.original12035 = await original12035(browser, url);
    else result.original12035 = 'skipped: ELICHIKA_STUDIO_TIMELINE_DIR has no a-1203503-live_timeline.unity';
  } finally {
    await browser.close();
    processHandle.kill();
    fs.rmSync(library, { recursive: true, force: true });
  }
  console.log(JSON.stringify(result));
})().catch((error) => { console.error(error); process.exitCode = 1; });
