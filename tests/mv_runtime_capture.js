/* Evaluate MV Studio at every director time recorded in a game runtime value dump.

   node tests/mv_runtime_capture.js --dump GAME.json.gz|job.log --manifest M.json --out DIR
        [--library DIR] [--server-root DIR] [--url URL] [--phases -1,0,1] [--preroll 3]
        [--software true] [--chromium PATH] [--keys FILE] [--batch 100] [--physics-order game|same-frame]
        [--physics-grid clock|rule] [--suits dump|POSITION:SUIT,...]

   The game dump (schema sifas-mv-runtime-dump/1, side "game") is read as a gzip
   or plain JSON document, or extracted from a GitHub job log (@@RTDUMP blobs;
   the 'rtdump-probe' blob is not a dump document and is only recorded).
   The editor imports the original MV through its own catalog and game stream,
   applies the quality the game actually ran (header.quality.values, mapped
   name by name; the manifest quality is only the fallback when the game
   recorded none) and marks the dump invalid:quality when a difference
   remains. It then pins the game's viewport and switches to the
   live camera. With --suits the members wear explicit suits instead of the
   member mapping's: "dump" pins the suit each game slot wore (frame
   members[].suitId), or list POSITION:SUIT pairs; the import fails unless the
   editor dresses every pinned slot so. Every game record is then evaluated at
   t = clock.directorTime + phase * clock.deltaTime for each phase: a plain
   deferred seek for pure parts, a fixed-step physics preroll ending exactly at
   t for members and springs. The preroll grid is the frame rate the game
   achieved (frames per director second, capped by the requested rate), since
   the game steps its springs once per rendered frame (--physics-grid rule
   uses the requested rate instead, for A/B checks). The read-only
   MVStudioScene.assetDump() supplies
   the values; DIR/editor-dump.json.gz is written in the same schema with
   side "editor". Values stay in editor space: tests/mv_runtime_compare.py
   owns every conversion. Pixels are never read back or resampled.
*/
'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const capture = require('./mv_frame_capture');
const SPRINGS = globalThis.MVStudioPhysics;

const SCHEMA = 'sifas-mv-runtime-dump/1';
const MODTOOLS = path.resolve(__dirname, '..');
const FRAME_SECTIONS = ['clock', 'directors', 'cameras', 'correctors', 'cameraWork', 'globals', 'renderSettings', 'lights',
  'memberIdentity', 'anchors'];
const PHYSICS_PARTS = new Set(['members', 'springs']);
const KNOWN_PARTS = new Set(['census', 'quality', 'fovmodNative', 'renderers', 'materials', 'lightingRefs', 'members',
  'springs', 'stageNodes', 'particles', 'post', 'propertyBlocks', 'tracks']);
const TIMESTAMP = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z /;

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index++) {
    const key = argv[index];
    if (!key.startsWith('--')) throw new Error(`Unexpected argument ${key}`);
    const value = argv[index + 1];
    if (value === undefined || (value.startsWith('--') && !/^--?\d/.test(value))) throw new Error(`${key} needs a value`);
    options[key.slice(2)] = value;
    index++;
  }
  if (!options.dump || !options.manifest || !options.out) {
    throw new Error('Usage: --dump GAME.json.gz|job.log --manifest FILE --out DIR [--url URL | --server-root DIR --library DIR]');
  }
  return options;
}

function parsePhases(text) {
  const phases = String(text ?? '-1,0,1').split(',').map((value) => Number(value.trim()));
  assert(phases.length && phases.every((value) => Number.isInteger(value) && Math.abs(value) <= 3), '--phases lists integers in [-3, 3]');
  return [...new Set(phases)].sort((a, b) => a - b);
}

// ------------------------------------------------------------------ dump input

function gunzipMaybe(bytes) {
  return bytes[0] === 0x1f && bytes[1] === 0x8b ? zlib.gunzipSync(bytes) : bytes;
}

// The @@RTDUMP transport (schema section 8): strip the GitHub timestamp prefix,
// join the chunks between BEGIN and END, and verify bytes and sha256 from INDEX.
function extractFromLog(text) {
  const index = new Map(), chunks = new Map(), done = new Set();
  let open = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(TIMESTAMP, '');
    if (!line.startsWith('@@')) continue;
    if (line.startsWith('@@RTDUMP-INDEX ')) {
      const entry = JSON.parse(line.slice('@@RTDUMP-INDEX '.length));
      index.set(entry.name, entry);
    } else if (line.startsWith('@@RTDUMP-BEGIN ')) {
      open = line.slice('@@RTDUMP-BEGIN '.length).trim();
      chunks.set(open, []);
    } else if (line.startsWith('@@RTDUMP-END ')) {
      const name = line.slice('@@RTDUMP-END '.length).trim();
      if (name !== open) throw new Error(`RTDUMP blob ${name} ends while ${open} is open`);
      done.add(name);
      open = null;
    } else if (open && !line.startsWith('@@RTDUMP-') && !line.startsWith('@@RTPROBE') && !line.startsWith('@@SHOT')) {
      chunks.get(open).push(line.slice(2).trim());
    }
  }
  const docs = [], auxiliary = {};
  for (const name of done) {
    const bytes = Buffer.from(chunks.get(name).join(''), 'base64');
    const entry = index.get(name);
    if (entry) {
      if (Number.isInteger(entry.bytes) && entry.bytes !== bytes.length) throw new Error(`RTDUMP ${name}: ${bytes.length} bytes, index says ${entry.bytes}`);
      const sha = crypto.createHash('sha256').update(bytes).digest('hex');
      if (entry.sha256 && entry.sha256 !== sha) throw new Error(`RTDUMP ${name}: sha256 mismatch`);
    }
    const value = JSON.parse(gunzipMaybe(bytes).toString('utf8'));
    if (isDumpDocument(name, value)) docs.push(value); else auxiliary[name] = value;
  }
  if (!docs.length) throw new Error('The job log has no complete @@RTDUMP dump blob');
  Object.defineProperty(docs, 'auxiliary', { value: auxiliary });
  return docs;
}

// rtdump-core and rtdump-full are dump documents; 'rtdump-probe' (the class
// and field inventory of the game probe) and any other blob are not merged.
function isDumpDocument(name, value) {
  return name !== 'rtdump-probe' && value !== null && typeof value === 'object' && typeof value.side === 'string' &&
    Array.isArray(value.records);
}

function mergeDumps(docs) {
  const [first] = docs;
  const records = new Map();
  for (const doc of docs) {
    if (doc.schema !== first.schema || doc.side !== first.side) throw new Error('Dump parts disagree on schema or side');
    for (const record of doc.records || []) if (!records.has(record.id)) records.set(record.id, record);
  }
  const trailers = docs.map((doc) => doc.trailer).filter(Boolean);
  const trailer = trailers.find((item) => item.stopReason) || trailers[0] || null;
  const truncation = trailers.map((item) => item.truncation).find(Boolean) || trailer?.truncation || null;
  return { schema: first.schema, side: first.side, header: first.header,
    records: [...records.values()].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0) || String(a.id).localeCompare(String(b.id))),
    trailer: trailer ? { ...trailer, truncation } : null };
}

function readDump(file) {
  const raw = gunzipMaybe(fs.readFileSync(file));
  const text = raw.toString('utf8');
  let docs;
  if (/^\s*\{/.test(text)) {
    try { docs = [JSON.parse(text)]; } catch (_) { docs = null; }
  }
  docs ||= extractFromLog(text);
  const doc = mergeDumps(docs);
  if (doc.schema !== SCHEMA) throw new Error(`Unknown dump schema ${doc.schema}; this runner reads ${SCHEMA}`);
  if (!doc.header || !Array.isArray(doc.records)) throw new Error('The dump has no header or records');
  return { doc, sha256: crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), auxiliary: docs.auxiliary || {} };
}

// ------------------------------------------------------------- member suits

// The suit each slot wore in the game (frame members[] {slot, memberId, suitId}).
function gameSuits(doc) {
  const suits = new Map(), changed = new Set();
  for (const record of doc.records) {
    if (record.kind !== 'frame') continue;
    for (const member of Array.isArray(record.members) ? record.members : []) {
      if (!Number.isInteger(member?.slot) || !Number.isInteger(member?.suitId)) continue;
      const seen = suits.get(member.slot);
      if (seen && (seen.suitId !== member.suitId || seen.memberId !== (member.memberId ?? null))) changed.add(member.slot);
      else if (!seen) suits.set(member.slot, { suitId: member.suitId, memberId: member.memberId ?? null });
    }
  }
  if (changed.size) throw new Error(`The game dump changes the member or suit of slot ${[...changed].join(', ')} during the performance`);
  return suits;
}

// --suits: "dump" or POSITION:SUIT[,POSITION:SUIT...] -> { source, costumes: { "<position>": suitId } }, or null.
function suitPlan(text, doc) {
  if (text === undefined) return null;
  if (text === 'dump') {
    const suits = gameSuits(doc);
    if (!suits.size) throw new Error('--suits dump: the game dump records no member suits (frame members[].suitId)');
    return { source: 'dump', costumes: Object.fromEntries([...suits].sort((a, b) => a[0] - b[0]).map(([slot, item]) => [String(slot), item.suitId])),
      members: Object.fromEntries([...suits].map(([slot, item]) => [String(slot), item.memberId])) };
  }
  const costumes = {};
  for (const item of String(text).split(',')) {
    const match = /^\s*(\d+)\s*:\s*(\d+)\s*$/.exec(item);
    const position = match && String(Number(match[1]));
    if (!match || !(Number(position) >= 1 && Number(position) <= 64) || position in costumes || !(Number(match[2]) > 0)) {
      throw new Error('--suits is "dump" or POSITION:SUIT[,POSITION:SUIT...] with positions 1-64');
    }
    costumes[position] = Number(match[2]);
  }
  return { source: 'option', costumes, members: {} };
}

// The editor's game import request carries the pinned costumes (server option `costumes`).
async function pinCostumes(page, plan) {
  const pattern = /\/api\/mv-studio\/game(?:-stream)?(?:\?|$)/;
  const handler = async (route) => {
    const request = route.request();
    if (request.method() !== 'POST') return route.continue();
    const body = JSON.parse(request.postData() || '{}');
    return route.continue({ postData: JSON.stringify({ ...body, costumes: plan.costumes }) });
  };
  await page.route(pattern, handler);
  return () => page.unroute(pattern, handler);
}

// Every pinned slot must be dressed as requested (and by the member the game had there).
function checkCostumes(plan, performers) {
  const byPosition = new Map((performers || []).map((item) => [String(item.position), item]));
  const problems = [];
  for (const [position, suit] of Object.entries(plan.costumes)) {
    const performer = byPosition.get(position);
    if (!performer) problems.push(`position ${position} has no performer`);
    else if (performer.costumeId !== suit) problems.push(`position ${position} wears ${performer.costumeId}, not ${suit}`);
    else if (performer.loaded === false) {
      problems.push(`position ${position} has no model for suit ${suit} (its asset pack is not local; set "download": true in the manifest)`);
    }
    else if (plan.members[position] != null && performer.memberId !== plan.members[position]) {
      problems.push(`position ${position} is member ${performer.memberId}, the game had ${plan.members[position]}`);
    }
  }
  if (problems.length) throw new Error(`The editor did not dress the pinned suits: ${problems.join('; ')}`);
  return [...byPosition.values()].map(({ position, memberId, costumeId, loaded }) => ({ position, memberId: memberId ?? null,
    costumeId: costumeId ?? null, ...(loaded === undefined ? {} : { loaded }) }));
}

// ------------------------------------------------------------- evaluation plan

function stageNodeKey(node) {
  if (typeof node.key === 'string' && node.key.startsWith('stageNode:')) return node.key;
  const crc = Number.isInteger(node.crc) ? node.crc : zlib.crc32(Buffer.from(String(node.relPath ?? '').replace(/\\/g, '/'), 'utf8')) >>> 0;
  return `stageNode:${node.binding}#${crc}`;
}

// What assetDump needs to select the editor counterparts of a game renderer:
// key, scope, GameObject path and mesh name (schema 1.5 renderer join).
// A renderer outside /EntryPoint belongs to the additively loaded stage scene (e.g. /Model/ground
// of bg0006_01_s1): its editor counterpart is in scope "stage" (mv_runtime_compare.Conventions.game_scope).
function rendererSelector(renderer) {
  const outside = renderer.scope === 'other' && typeof renderer.path === 'string' && renderer.path.startsWith('/') &&
    !renderer.path.startsWith('/EntryPoint/') && renderer.path.split('/').length >= 3;
  return { key: renderer.key, scope: outside ? 'stage' : renderer.scope, mesh: renderer.mesh ?? null,
    path: outside ? renderer.path.split('/').slice(2).join('/') : renderer.path ?? null };
}

function rendererIndex(records) {
  const index = new Map();
  for (const record of records) for (const renderer of Array.isArray(record.renderers) ? record.renderers : []) {
    if (typeof renderer.key === 'string') index.set(renderer.key, rendererSelector(renderer));
  }
  return index;
}

// The editor dumps exactly the counterparts of what the game record holds, so
// a chunk of 24 renderers does not repeat the whole stage at every phase.
function filterFor(record, renderers) {
  const part = record.part;
  if (part === 'renderers' && Array.isArray(record.renderers) && record.renderers.length) {
    return { renderers: record.renderers.map(rendererSelector) };
  }
  if (part === 'materials' && Array.isArray(record.materials) && record.materials.length) {
    const wanted = new Map();
    for (const material of record.materials) for (const use of Array.isArray(material.usedBy) ? material.usedBy : []) {
      const key = String(use).replace(/#\d+$/, '');
      const renderer = renderers.get(key);
      if (!renderer) return null;
      wanted.set(key, renderer);
    }
    return wanted.size ? { renderers: [...wanted.values()] } : null;
  }
  if (part === 'stageNodes' && Array.isArray(record.stageNodes) && record.stageNodes.length) {
    return { stageNodes: record.stageNodes.map(stageNodeKey) };
  }
  if (part === 'members' && Array.isArray(record.members)) {
    const bones = record.members.flatMap((member) => (member.bones || []).map((bone) => bone.key)).filter(Boolean);
    return bones.length ? { bones } : null;
  }
  return null;
}

function planRequests(doc, phases) {
  const renderers = rendererIndex(doc.records);
  const requests = [];
  for (const record of doc.records) {
    const time = record.clock?.directorTime;
    if (!Number.isFinite(time)) continue;
    const deltaTime = Number.isFinite(record.clock?.deltaTime) && record.clock.deltaTime > 0 ? record.clock.deltaTime : 1 / 30;
    const part = record.kind === 'full' ? record.part : null;
    const sections = record.kind === 'frame' ? FRAME_SECTIONS : ['clock', part];
    for (const phase of phases) {
      const t = time + phase * deltaTime;
      if (t < 0) continue;
      requests.push({ id: `${record.id}@${phase}`, source: record, phase, t, deltaTime, sections,
        physics: PHYSICS_PARTS.has(part), unknownPart: part !== null && !KNOWN_PARTS.has(part), filter: filterFor(record, renderers) });
    }
  }
  return requests.sort((a, b) => a.t - b.t || a.id.localeCompare(b.id));
}

// The real-time game steps its springs once per rendered frame, so a runtime dump
// is reproduced at the frame rate the game achieved: frames per director second
// between the first and last records taken while the director advanced
// (clock.frameCount and clock.directorTime), capped by the rate the game
// requested (MVStudioPhysics.gameFrameRate). When the frame counter does not
// agree with the recorded deltaTime (within 25%; e.g. a synthetic document whose
// frameCount is a record counter) the mean deltaTime gives the rate instead.
// Without a usable clock the requested rate is used.
function gameClockRate(doc, qualityValues, device) {
  const target = SPRINGS.gameFrameRate(qualityValues, device);
  const clocks = (doc.records || []).map((record) => record.clock)
    .filter((clock) => Number.isFinite(clock?.frameCount) && Number.isFinite(clock?.directorTime));
  const end = clocks.reduce((max, clock) => Math.max(max, clock.directorTime), -Infinity);
  const advancing = clocks.filter((clock) => clock.directorTime > 0 && clock.directorTime < end)
    .sort((a, b) => a.frameCount - b.frameCount);
  const first = advancing[0], last = advancing.at(-1);
  const frames = last && last.frameCount - first.frameCount, seconds = last && last.directorTime - first.directorTime;
  if (!(frames > 0 && seconds > 0)) return { source: 'game-rule', rate: target, target, achieved: null, frames: 0, seconds: 0, meanDeltaTime: null };
  const deltas = advancing.map((clock) => clock.deltaTime).filter((value) => Number.isFinite(value) && value > 0);
  const meanDeltaTime = deltas.length ? deltas.reduce((sum, value) => sum + value, 0) / deltas.length : null;
  let achieved = frames / seconds, source = 'game-clock';
  if (meanDeltaTime && Math.abs(achieved * meanDeltaTime - 1) > 0.25) { achieved = 1 / meanDeltaTime; source = 'game-deltaTime'; }
  return { source, rate: Math.min(achieved, target), target, achieved, frames, seconds, meanDeltaTime };
}

// ------------------------------------------------------------- browser side

async function evaluatePure(page, batch, keys) {
  return page.evaluate(({ batch, keys }) => {
    const scene = mvFrameProbe.scene;
    const now = () => performance.now();
    return batch.map((request) => {
      const start = now();
      scene.seek(request.t, undefined, true);
      const seeked = now();
      const values = scene.assetDump({ sections: request.sections, filter: request.filter || undefined, keys: keys || undefined });
      return { id: request.id, values, seekMs: seeked - start, dumpMs: now() - seeked };
    });
  }, { batch: batch.map(({ id, t, sections, filter }) => ({ id, t, sections, filter })), keys });
}

// Same fixed-step grid as mv_frame_capture.js renderFrame(), ending exactly at
// t, but the last step is deferred too: nothing is drawn or read back.
async function evaluatePhysics(page, request, preroll, rate, keys) {
  return page.evaluate(({ request, preroll, rate, keys }) => {
    const scene = mvFrameProbe.scene;
    const begin = performance.now(), time = request.t;
    const available = Math.floor(time * rate + 1e-6);
    const steps = preroll === 'full' ? available : Math.min(available, Math.floor(preroll * rate + 1e-6));
    const start = time - steps / rate;
    if (Math.abs(scene.inspect().time - start) <= 1e-9) scene.seek(start + 1 / rate, undefined, true);
    scene.seek(start, undefined, true);
    scene.setPlaying(true);
    try {
      for (let step = 0; step < steps; step++) scene.playbackFrame(start + step / rate, step * 1000 / rate, true);
      scene.playbackFrame(time, steps * 1000 / rate, true);
      const seeked = performance.now();
      const values = scene.assetDump({ sections: request.sections, filter: request.filter || undefined, keys: keys || undefined });
      return { id: request.id, values, seekMs: seeked - begin, dumpMs: performance.now() - seeked, steps, prerollStart: start };
    } finally {
      scene.setPlaying(false);
    }
  }, { request: { id: request.id, t: request.t, sections: request.sections, filter: request.filter }, preroll, rate, keys });
}

// --------------------------------------------------------------- editor dump

// LiveQualitySettingVO backing-field names -> editor quality keys. This table
// and the fallback rule are exactly mv_runtime_compare.Conventions.QUALITY and
// Conventions.quality_key (test_mv_runtime_compare checks that they agree).
const QUALITY_NAMES = Object.freeze({
  PostEffect: 'posteffect', FrameRate60Fps: 'frame_rate_60fps', MemberSwingBone: 'member_swing_bone_mv',
  Quality: 'quality_mode', RenderingResolution: 'rendering_resolution', BaseLight: 'base_light',
  StageAmbient: 'stage_ambient', StageAnimation: 'stage_animation', StageColoring: 'stage_coloring',
  StageControl: 'stage_control', StageOverlayEffect: 'stage_overlay_effect', StageFlashLight: 'stage_flash_light',
  StageDisplay: 'stage_display', StageEmissive: 'stage_emissive', StageAudience: 'stage_audience',
  StageCubemap: 'stage_cubemap', MemberAmbient: 'member_ambient', MemberRimLight: 'member_rim_light',
  MemberSpotLightShaft: 'member_spot_light_shaft', MemberSpotLightArea: 'member_spot_light_area',
  PropAmbient: 'prop_ambient', PropRimLight: 'prop_rim_light', SplitScreen: 'split_screen',
});
// The preset's row id identifies the catalog row, not a scene setting; it is never compared.
const QUALITY_IGNORED = new Set(['set_id']);
function snakeCase(name) {
  if (Object.prototype.hasOwnProperty.call(QUALITY_NAMES, name)) return QUALITY_NAMES[name];
  return name.replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2').replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
}

function qualityValue(raw) {
  return raw && typeof raw === 'object' && 'v' in raw ? raw.v : raw;
}

// A C# bool may arrive as 0/1 from a raw field read.
function sameQuality(gameValue, editorValue) {
  if (typeof editorValue === 'boolean' && (gameValue === 0 || gameValue === 1)) return editorValue === Boolean(gameValue);
  return gameValue === editorValue;
}

function qualityDifferences(gameQuality, editorValues) {
  const values = gameQuality?.values;
  if (!values || typeof values !== 'object') return { compared: 0, differences: [], gameOnly: [] };
  const differences = [], gameOnly = [];
  let compared = 0;
  for (const [name, raw] of Object.entries(values)) {
    const key = snakeCase(name), value = qualityValue(raw);
    if (QUALITY_IGNORED.has(key)) continue;
    if (!(key in editorValues)) { gameOnly.push(name); continue; }
    compared++;
    if (!sameQuality(value, editorValues[key])) differences.push({ game: name, editor: key, gameValue: value, editorValue: editorValues[key] });
  }
  return { compared, differences, gameOnly };
}

// Contract 5: the quality request built from the game header. The mode comes
// from Quality (-> quality_mode); every other value with an editor control
// becomes an override applied after the mode's preset. Values with no editor
// control are listed as gameOnly (they cannot be applied).
function qualityPlan(gameQuality, catalog, fallback) {
  const values = gameQuality?.values && typeof gameQuality.values === 'object' ? gameQuality.values : null;
  if (!values || !Object.keys(values).length) {
    return { source: 'manifest', request: { mode: fallback.mode, overrides: { ...(fallback.overrides || {}) } }, gameOnly: [],
      reason: 'the game dump records no quality values' };
  }
  const options = new Map((catalog.options || []).map((option) => [option.key, option]));
  const overrides = {}, gameOnly = [];
  let mode = null;
  for (const [name, raw] of Object.entries(values)) {
    const key = snakeCase(name), value = qualityValue(raw);
    if (key === 'quality_mode') { mode = value; continue; }
    if (QUALITY_IGNORED.has(key)) continue;
    const option = options.get(key);
    if (!option) { gameOnly.push(name); continue; }
    if (option.type === 'number' && Number.isFinite(value)) overrides[key] = value;
    else if (option.type !== 'number' && (typeof value === 'boolean' || value === 0 || value === 1)) overrides[key] = Boolean(value);
    else gameOnly.push(name);
  }
  const plan = { source: 'game', request: { mode: Number.isSafeInteger(mode) ? mode : fallback.mode, overrides }, gameOnly };
  if (!Number.isSafeInteger(mode)) plan.reason = 'the game dump records no Quality mode; the manifest mode is the base preset';
  return plan;
}

async function qualityCatalog(page) {
  return page.evaluate(() => {
    const quality = MVStudio.getState().project?.quality || {};
    return { modes: (quality.modes || []).map((mode) => mode.id), options: (quality.options || []).map(({ key, type }) => ({ key, type })) };
  });
}

// Applies the game's quality; on failure falls back to the manifest quality.
// The result carries status "matched" or "invalid:quality" with its reasons.
async function applyGameQuality(page, gameQuality, manifestQuality) {
  const catalog = await qualityCatalog(page);
  const plan = qualityPlan(gameQuality, catalog, manifestQuality);
  const reasons = plan.reason && plan.source === 'manifest' ? [plan.reason] : [];
  let applied;
  try {
    applied = await capture.applyQuality(page, plan.request);
  } catch (error) {
    reasons.push(`the game quality could not be applied: ${error.message}`);
    applied = await capture.applyQuality(page, manifestQuality);
  }
  const differences = qualityDifferences(gameQuality, applied.values);
  if (differences.differences.length) reasons.push(`${differences.differences.length} game quality value(s) differ after applying`);
  return { mode: applied.mode, values: applied.values, source: plan.source, request: plan.request, gameOnly: plan.gameOnly,
    status: reasons.length ? 'invalid:quality' : 'matched', reasons, gameDifferences: differences };
}

function viewportFor(doc) {
  const screen = doc.header.screen || {};
  let width = Number.isInteger(screen.width) && screen.width > 0 ? screen.width : 1280;
  let height = Number.isInteger(screen.height) && screen.height > 0 ? screen.height : 720;
  const notes = [];
  const camera = doc.records.filter((record) => record.kind === 'frame')
    .flatMap((record) => record.cameras || []).find((item) => item?.key === 'camera:main');
  const target = camera?.targetTexture;
  // RenderingResolution scales the screen to its height and Unity rounds the width
  // (1280x720 at 640 -> 1138x640, aspect 1.778125): no width at the screen height
  // reproduces that aspect, so pin the camera's own pixel size when it gives the aspect.
  const pixel = [camera?.pixelWidth, camera?.pixelHeight];
  const pixelAspect = pixel.every((value) => Number.isInteger(value) && value > 0) ? pixel[0] / pixel[1] : null;
  if (target && Number.isInteger(target.width) && Number.isInteger(target.height) &&
      Math.abs(target.width / target.height - width / height) > 1e-4) {
    notes.push(`main camera renders to ${target.width}x${target.height}; pinned to that aspect instead of the screen`);
    width = Math.round(height * target.width / target.height);
  } else if (pixelAspect !== null && (!Number.isFinite(camera?.aspect) || Math.abs(pixelAspect - camera.aspect) <= 1e-5 * camera.aspect) &&
      (pixel[0] !== width || pixel[1] !== height)) {
    notes.push(`main camera draws ${pixel[0]}x${pixel[1]} (aspect ${pixelAspect}) on the ${width}x${height} screen; pinned to the camera pixel size`);
    [width, height] = pixel;
  } else if (Number.isFinite(camera?.aspect) && Math.abs(camera.aspect - width / height) > 1e-4) {
    notes.push(`main camera aspect ${camera.aspect} differs from the screen ${width}x${height}; pinned to the camera aspect`);
    width = Math.round(height * camera.aspect);
  }
  return { width, height, gameAspect: Number.isFinite(camera?.aspect) ? camera.aspect : null, notes };
}

function stats(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const at = (q) => sorted[Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1) + 0.5))];
  return { n: sorted.length, p50: at(0.5), p95: at(0.95), max: sorted.at(-1), total: sorted.reduce((sum, value) => sum + value, 0) };
}

function editorRecord(request, result, rate) {
  const source = request.source, values = { ...result.values };
  const record = { id: request.id, kind: source.kind, sourceRecord: source.id, phase: request.phase };
  if (source.kind === 'full') Object.assign(record, { pass: source.pass ?? null, part: source.part, chunk: source.chunk ?? 0 });
  record.clock = { directorTime: request.t, sourceDirectorTime: source.clock.directorTime, phase: request.phase,
    phaseSeconds: request.phase * request.deltaTime, deltaTime: request.deltaTime, rate: values.clock?.rate ?? rate };
  if (request.physics) record.clock.physicsRate = rate;
  if (Math.abs((values.clock?.directorTime ?? NaN) - request.t) > 1e-9) {
    (values.errors ||= []).push({ at: 'clock', error: `editor time ${values.clock?.directorTime} != requested ${request.t}` });
  }
  delete values.clock;
  record.cost = { elapsedMs: result.seekMs + result.dumpMs, seekMs: result.seekMs, dumpMs: result.dumpMs,
    assetDumpMs: values.cost?.elapsedMs ?? null, ...(result.steps !== undefined ? { prerollSteps: result.steps, prerollStart: result.prerollStart } : {}) };
  delete values.cost;
  record.nonFinite = values.nonFinite || [];
  delete values.nonFinite;
  if (request.unknownPart) (values.errors ||= []).push({ at: source.part, error: 'part not modeled by this editor runner' });
  if (!values.errors?.length) delete values.errors;
  if (!values.truncatedSections?.length) delete values.truncatedSections;
  return Object.assign(record, values);
}

// Pins the game viewport, selects the live camera and applies the size to it.
async function prepareLiveView(page, viewport) {
  await capture.pinViewport(page, viewport.width, viewport.height);
  const pinned = await page.evaluate(() => {
    const select = document.querySelector('#mv-camera-mode');
    select.value = 'live';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    const scene = mvFrameProbe.scene;
    if (typeof scene.assetDump !== 'function') throw new Error('This editor build has no MVStudioScene.assetDump()');
    // Without resize(false) the live camera keeps the old aspect.
    scene.resize(false);
    const state = scene.inspect();
    return { aspect: state.camera.aspect, canvas: state.canvas, cameraMode: state.cameraMode };
  });
  assert(Math.abs(pinned.aspect - viewport.width / viewport.height) < 1e-9, `editor aspect ${pinned.aspect} after pinning ${viewport.width}x${viewport.height}`);
  if (viewport.gameAspect !== null) {
    assert(Math.abs(pinned.aspect - viewport.gameAspect) <= 1e-5 * viewport.gameAspect,
      `editor aspect ${pinned.aspect} differs from the game main camera aspect ${viewport.gameAspect}`);
  }
  return pinned;
}

// Evaluates every game record at every phase; pure records in batches.
async function capturePage(page, game, { phases, preroll, rate, batchSize = 100, keys = null }) {
  const requests = planRequests(game, phases);
  const results = new Map();
  const pureStart = Date.now();
  const pure = requests.filter((request) => !request.physics), physics = requests.filter((request) => request.physics);
  for (let index = 0; index < pure.length; index += batchSize) {
    for (const result of await evaluatePure(page, pure.slice(index, index + batchSize), keys)) results.set(result.id, result);
  }
  const pureSeconds = (Date.now() - pureStart) / 1000;
  const physicsStart = Date.now();
  for (const request of physics) results.set(request.id, await evaluatePhysics(page, request, preroll, rate, keys));
  const physicsSeconds = (Date.now() - physicsStart) / 1000;
  const records = requests.map((request) => editorRecord(request, results.get(request.id), rate));
  const costs = (select) => records.filter(select).map((record) => record.cost.elapsedMs);
  const timing = { pureSeconds, physicsSeconds, captureSeconds: pureSeconds + physicsSeconds,
    frameMs: stats(costs((record) => record.kind === 'frame')), fullMs: stats(costs((record) => record.kind === 'full')),
    physicsMs: stats(costs((record) => record.cost.prerollSteps !== undefined)) };
  return { records, timing };
}

function editorDocument({ game, gameFile, sha256, auxiliary = {}, records, timing, conventions, manifest, viewport, quality, phases, preroll, rate,
  physics = null, batchSize, keysFile, producer, errors, began, performers = null }) {
  const elapsedSeconds = (Date.now() - began) / 1000;
  return {
    schema: SCHEMA, side: 'editor',
    header: {
      createdAt: new Date().toISOString(), producer, conventions, source: { ...manifest.source },
      screen: { width: viewport.width, height: viewport.height, notes: viewport.notes },
      fovmod: { aspectBounds: { min: 0.75, max: 1 }, source: 'MVStudioSplit.aspectCorrection' },
      quality: { mode: quality.mode, values: quality.values, source: quality.source ?? 'manifest', request: quality.request ?? null,
        status: quality.status ?? 'invalid:quality', reasons: quality.reasons ?? ['quality was not taken from the game dump'],
        gameOnly: quality.gameOnly ?? [], gameDifferences: qualityDifferences(game.header.quality, quality.values) },
      ...(performers ? { performers } : {}),
      limits: { phases, physicsPrerollSeconds: preroll, rate, batch: batchSize },
      physics,
      keys: keysFile ? { file: path.basename(keysFile), sha256: crypto.createHash('sha256').update(fs.readFileSync(keysFile)).digest('hex') } : null,
      gameDump: { sha256, file: gameFile ? path.basename(gameFile) : null, schema: game.schema, records: game.records.length,
        producer: game.header.producer?.name ?? null, budgets: game.header.budgets ?? null, auxiliaryBlobs: Object.keys(auxiliary).sort() },
    },
    records,
    trailer: { records: { frame: records.filter((record) => record.kind === 'frame').length,
      full: records.filter((record) => record.kind === 'full').length }, pageErrors: errors, elapsedSeconds, timing },
  };
}

async function run() {
  const options = parseArgs(process.argv.slice(2));
  const began = Date.now();
  const phases = parsePhases(options.phases);
  const preroll = options.preroll === 'full' ? 'full' : Number(options.preroll ?? 3);
  assert(preroll === 'full' || (Number.isFinite(preroll) && preroll >= 0), '--preroll is seconds or "full"');
  const order = options['physics-order'] ?? 'game';
  assert(SPRINGS.ORDERS.includes(order), '--physics-order is game or same-frame');
  const gridMode = options['physics-grid'] ?? 'clock';
  assert(['clock', 'rule'].includes(gridMode), '--physics-grid is clock or rule');
  const batchSize = Number(options.batch ?? 100);
  assert(Number.isInteger(batchSize) && batchSize > 0, '--batch is a positive integer');
  const manifest = capture.readManifest(options.manifest);
  const { doc: game, sha256, auxiliary } = readDump(path.resolve(options.dump));
  assert.equal(game.side, 'game', 'The --dump document must be a game dump (side "game")');
  const keysFile = options.keys ? path.resolve(options.keys) : null;
  const keys = keysFile ? JSON.parse(fs.readFileSync(keysFile, 'utf8')) : null;
  const requestKeys = keys && Array.isArray(keys.shaderGlobalCandidates) ? { globals: keys.shaderGlobalCandidates } : null;
  const out = path.resolve(options.out);
  fs.mkdirSync(out, { recursive: true });
  const serverRoot = path.resolve(options['server-root'] || path.join(MODTOOLS, '..'));
  const viewport = viewportFor(game);
  const suits = suitPlan(options.suits, game);
  let server = null, browser = null;
  try {
    const { chromium } = require('playwright');
    const url = options.url || (server = await capture.bootEditor(serverRoot, options.library, path.join(out, 'editor-server.log'))).url;
    browser = await chromium.launch({ executablePath: options.chromium || process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: capture.browserArgs(options.software === 'true') });
    const page = await browser.newPage({ viewport: { width: Math.max(2600, viewport.width + 64), height: Math.max(1600, viewport.height + 64) },
      deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(capture.attachSceneProbe);
    await page.goto(url + '/#mv');
    const importStart = Date.now();
    const unpin = suits ? await pinCostumes(page, suits) : null;
    try {
      await capture.importOriginal(page, manifest.source, manifest.download === true);
    } finally {
      if (unpin) await unpin();
    }
    const importSeconds = (Date.now() - importStart) / 1000;
    const dressed = await page.evaluate(() => (MVStudio.getState().project?.performers || [])
      .map(({ position, memberId, costumeId, glb }) => ({ position, memberId, costumeId, loaded: typeof glb === 'string' && glb.length > 0 })));
    const performers = suits ? { source: suits.source, pinned: suits.costumes, dressed: checkCostumes(suits, dressed) }
      : { source: 'mapping', pinned: null, dressed };
    const quality = await applyGameQuality(page, game.header.quality, manifest.quality);
    const clock = gameClockRate(game, quality.values, manifest.device);
    await capture.applyPhysicsReference(page, { rate: clock.target, order,
      timing: { order, exportFps: null, device: manifest.device || {} } });
    const rate = gridMode === 'rule' ? clock.target : clock.rate;
    const physics = { ...clock, rate, reference: gridMode === 'rule' ? 'game-rule' : clock.source, order };
    const pinned = await prepareLiveView(page, viewport);
    const project = await page.evaluate(() => {
      const value = MVStudio.getState().project;
      return { name: value.name, source: value.source, duration: value.duration, warnings: value.warnings || [] };
    });
    const { records, timing } = await capturePage(page, game, { phases, preroll, rate, batchSize, keys: requestKeys });
    timing.importSeconds = importSeconds;
    const webgl = await capture.rendererInfo(page);
    const producer = { name: 'mv_runtime_capture.js', modtools: { commit: capture.gitHead(MODTOOLS), dirty: capture.gitDirty(MODTOOLS) },
      server: { root: serverRoot, commit: options.url ? null : capture.gitHead(serverRoot) }, url: options.url || null,
      browser: browser.version(), webgl };
    const conventions = await page.evaluate(() => ({ ...MVStudioAssetDump.CONVENTIONS }));
    const editor = editorDocument({ game, gameFile: options.dump, sha256, auxiliary, records, timing, conventions, manifest, viewport, quality,
      phases, preroll, rate, physics, batchSize, keysFile, producer, errors, began, performers });
    const body = zlib.gzipSync(Buffer.from(JSON.stringify(editor)), { level: 9 });
    fs.writeFileSync(path.join(out, 'editor-dump.json.gz'), body);
    const environment = { schema: 1, kind: 'elichika-mv-runtime-capture', createdAt: editor.header.createdAt, manifest, project,
      physicsRate: rate, physics,
      gameDump: editor.header.gameDump, render: { ...viewport, pinned }, quality: editor.header.quality, performers,
      environment: { ...producer, platform: process.platform }, timing, elapsedSeconds: editor.trailer.elapsedSeconds, pageErrors: errors,
      output: { file: 'editor-dump.json.gz', bytes: body.length, records: records.length } };
    fs.writeFileSync(path.join(out, 'capture.json'), JSON.stringify(environment, null, 2) + '\n');
    console.log(JSON.stringify({ out, records: records.length, gameRecords: game.records.length, phases,
      importSeconds, captureSeconds: timing.captureSeconds, elapsedSeconds: editor.trailer.elapsedSeconds, frameMsP50: timing.frameMs?.p50 ?? null,
      bytes: body.length, quality: { status: quality.status, source: quality.source, mode: quality.mode, reasons: quality.reasons },
      qualityDifferences: editor.header.quality.gameDifferences.differences.length, pageErrors: errors.length,
      webgl: webgl.renderer }));
  } finally {
    if (browser) await browser.close();
    if (server) server.child.kill();
  }
}

if (require.main === module) run().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
module.exports = { readDump, extractFromLog, mergeDumps, isDumpDocument, planRequests, filterFor, stageNodeKey, editorRecord, rendererSelector,
  gameSuits, suitPlan, pinCostumes, checkCostumes,
  qualityDifferences, qualityPlan, applyGameQuality, snakeCase, QUALITY_NAMES, viewportFor, parsePhases, evaluatePure, evaluatePhysics,
  prepareLiveView, capturePage, editorDocument, gameClockRate, FRAME_SECTIONS, SCHEMA };
