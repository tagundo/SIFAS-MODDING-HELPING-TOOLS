/* Before/after check of the spring stepping rule on a real MV import.

   node tests/mv_spring_order_check.js --manifest M.json --out DIR [--times 14.85,57.6]
        [--configs same-frame,game,game@60] [--server-root DIR] [--library DIR] [--url URL]
        [--chromium PATH] [--software true] [--margin 32] [--margin-fraction 0.15] [--assert true] [--envelope 4] [--noise 0.15]

   Every time is rendered once per config through the editor's own import, with the
   spring rate of the manifest's reference (mv_frame_capture.physicsReference). A config
   is ORDER[@GRID]: the spring order ("game" or "same-frame") and optionally a playback
   grid in Hz that differs from the spring rate (e.g. game@60 plays 60 Hz frames while
   the springs keep stepping at the reference rate). The first config is the baseline.
   For each later config the check reports, against the baseline:
   - per _Dyna bone world-rotation angle (deg) from assetDump, grouped by region;
   - changed pixels (any channel differs by more than 8) and how many lie outside the
     members' projected bone box, widened on each side by --margin px plus
     --margin-fraction of the box's larger side (meshes reach past their last bone:
     hat feathers, coat tails, cords). The box is a proxy for the member mask.
   With --assert true: no changed pixel outside the member box, every config whose
   grid differs from the baseline grid stays within --noise deg, and every order change
   stays within --envelope deg. DIR gets the PNGs, result.json and summary.json.
*/
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const capture = require('./mv_frame_capture');

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 2) {
    if (!argv[index].startsWith('--') || argv[index + 1] === undefined) throw new Error(`Bad argument ${argv[index]}`);
    options[argv[index].slice(2)] = argv[index + 1];
  }
  if (!options.manifest || !options.out) throw new Error('Usage: --manifest FILE --out DIR [--times a,b] [--configs same-frame,game]');
  return options;
}

function parseConfig(text) {
  const [order, grid] = text.split('@');
  assert(['game', 'same-frame'].includes(order), `config ${text}: order is game or same-frame`);
  assert(grid === undefined || Number(grid) > 0, `config ${text}: grid is a rate in Hz`);
  return { name: text, order, grid: grid === undefined ? null : Number(grid) };
}

function region(key) {
  const name = key.split('/').at(-1).toLowerCase();
  if (name.includes('skirt')) return 'skirt';
  if (/bust|breast/.test(name)) return 'bust';
  if (/hair|bang|tail|pony|side|back/.test(name)) return 'hair';
  if (/ear|pierce/.test(name)) return 'earring';
  return 'other';
}

// Angle between two rotations. World rotations decomposed from a scaled bone (the
// bust bones carry node scaling) are not unit quaternions, so normalize first.
function angle(a, b) {
  const norm = Math.hypot(...a) * Math.hypot(...b);
  const dot = Math.abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]) / norm;
  return 2 * Math.acos(Math.min(1, dot)) * 180 / Math.PI;
}

function percentile(values, q) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1) + 0.5))] : null;
}

// Dyna world rotations, all member bone positions and the camera of the frame just drawn.
async function frameState(page) {
  return page.evaluate(() => {
    const scene = mvFrameProbe.scene;
    const dump = scene.assetDump({ sections: ['members'], maxBones: 4000 });
    const members = (dump.members || []).map((member) => ({ slot: member.slot, physics: member.physics,
      positions: member.bones.map((bone) => bone.position),
      dyna: member.bones.filter((bone) => /_Dyna$/.test(bone.key)).map(({ key, rotation, position }) => ({ key, rotation, position })) }));
    const state = scene.inspect();
    return { members, camera: state.camera, canvas: state.canvas, errors: dump.errors || [] };
  });
}

// Pixel difference of two PNGs and the members' projected bone box, in the page.
async function compareImages(page, a, b, members, camera, margin, fraction) {
  return page.evaluate(async ({ a, b, positions, camera, margin, fraction }) => {
    const decode = async (data) => {
      const bitmap = await createImageBitmap(await (await fetch('data:image/png;base64,' + data)).blob());
      const canvas = new OffscreenCanvas(bitmap.width, bitmap.height), context = canvas.getContext('2d');
      context.drawImage(bitmap, 0, 0);
      return context.getImageData(0, 0, bitmap.width, bitmap.height);
    };
    const [left, right] = await Promise.all([decode(a), decode(b)]);
    const width = left.width, height = left.height;
    const T = window.THREE, view = new T.Matrix4().compose(new T.Vector3().fromArray(camera.position),
      new T.Quaternion().fromArray(camera.quaternion), new T.Vector3(1, 1, 1)).invert();
    const projection = new T.Matrix4().fromArray(camera.projection);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const position of positions) {
      const point = new T.Vector3().fromArray(position).applyMatrix4(view);
      if (point.z >= 0) continue;
      point.applyMatrix4(projection);
      const x = (point.x + 1) / 2 * width, y = (1 - point.y) / 2 * height;
      x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
    }
    const pad = margin + fraction * Math.max(x1 - x0, y1 - y0);
    const box = Number.isFinite(x0) ? [x0 - pad, y0 - pad, x1 + pad, y1 + pad] : null;
    let changed = 0, exact = 0, outside = 0, outsideExact = 0, maxDiff = 0;
    for (let index = 0; index < left.data.length; index += 4) {
      const diff = Math.max(Math.abs(left.data[index] - right.data[index]), Math.abs(left.data[index + 1] - right.data[index + 1]),
        Math.abs(left.data[index + 2] - right.data[index + 2]));
      if (!diff) continue;
      const pixel = index / 4, x = pixel % width, y = Math.floor(pixel / width);
      const out = !box || x < box[0] || x > box[2] || y < box[1] || y > box[3];
      exact++; if (out) outsideExact++;
      if (diff > 8) { changed++; if (out) outside++; }
      maxDiff = Math.max(maxDiff, diff);
    }
    return { width, height, changed, changedShare: changed / (width * height), exact, outside, outsideExact, maxDiff,
      memberBox: box && box.map((value) => Math.round(value)) };
  }, { a, b, positions: members.flatMap((member) => member.positions), camera, margin, fraction });
}

function boneDelta(base, other) {
  const rows = [];
  for (const [index, member] of base.members.entries()) {
    const match = new Map((other.members[index]?.dyna || []).map((bone) => [bone.key, bone]));
    for (const bone of member.dyna) {
      const peer = match.get(bone.key);
      if (!peer) continue;
      const shift = Math.hypot(...bone.position.map((value, axis) => value - peer.position[axis])) * 100;
      rows.push({ key: bone.key, region: region(bone.key), angle: angle(bone.rotation, peer.rotation), shiftCm: shift });
    }
  }
  const regions = {};
  for (const row of rows) (regions[row.region] ||= []).push(row);
  const summary = {};
  for (const [name, list] of Object.entries(regions)) {
    const worst = list.reduce((best, row) => row.angle > best.angle ? row : best);
    summary[name] = { n: list.length, median: percentile(list.map((row) => row.angle), .5), p90: percentile(list.map((row) => row.angle), .9),
      max: worst.angle, worst: worst.key.split('/').at(-1), maxShiftCm: Math.max(...list.map((row) => row.shiftCm)) };
  }
  const top = [...rows].sort((a, b) => b.angle - a.angle).slice(0, 12)
    .map(({ key, angle, shiftCm }) => ({ bone: key.split('/').at(-1), angle, shiftCm }));
  return { bones: rows.length, max: rows.reduce((max, row) => Math.max(max, row.angle), 0), regions: summary, top };
}

async function run() {
  const options = parseArgs(process.argv.slice(2));
  const manifest = capture.readManifest(options.manifest);
  const out = path.resolve(options.out);
  fs.mkdirSync(out, { recursive: true });
  const configs = (options.configs || 'same-frame,game').split(',').map(parseConfig);
  const margin = Number(options.margin ?? 32), fraction = Number(options['margin-fraction'] ?? 0.15);
  const serverRoot = path.resolve(options['server-root'] || path.join(__dirname, '..', '..'));
  const { chromium } = require('playwright');
  let server = null, browser = null;
  const result = { manifest: options.manifest, configs, frames: [] };
  try {
    const url = options.url || (server = await capture.bootEditor(serverRoot, options.library, path.join(out, 'editor-server.log'))).url;
    browser = await chromium.launch({ executablePath: options.chromium || process.env.CHROMIUM_EXECUTABLE || undefined, headless: true,
      args: capture.browserArgs(options.software !== 'false') });
    const page = await browser.newPage({ viewport: { width: 2600, height: 1600 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(capture.attachSceneProbe);
    await page.goto(url + '/#mv');
    await capture.importOriginal(page, manifest.source, manifest.download === true);
    const quality = await capture.applyQuality(page, manifest.quality);
    const height = quality.values.rendering_resolution, width = Math.round(height * (manifest.aspect ?? 16 / 9) / 2) * 2;
    await capture.pinViewport(page, width, height);
    await page.evaluate(() => {
      const select = document.querySelector('#mv-camera-mode');
      select.value = 'live';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const reference = capture.physicsReference(manifest, quality.values);
    result.reference = { source: reference.source, rate: reference.rate, exportFps: reference.exportFps, warmupSteps: reference.warmupSteps };
    // The manifest's frames plus its auto mid-shot frames, as mv_frame_capture.js renders them.
    const tracks = await page.evaluate(() => MVStudio.getState().project.tracks
      .filter((track) => track.kind === 'camera').map(({ kind, muted, events }) => ({ kind, muted,
        events: events.map(({ start, duration }) => ({ start, duration })) })));
    const planned = manifest.autoFrames ? capture.midShotTimes(tracks, manifest.autoFrames) : [];
    const times = options.times ? options.times.split(',').map(Number) :
      [...new Set([...manifest.frames.map((frame) => frame.time), ...planned])].sort((a, b) => a - b);
    for (const time of times) {
      const row = { time, runs: [] };
      for (const config of configs) {
        const grid = config.grid ?? reference.rate;
        await capture.applyPhysicsReference(page, { ...reference, order: config.order, timing: { ...reference.timing, order: config.order } });
        const { png, steps, warmupSteps } = await capture.renderFrame(page, time, manifest.physics.preroll, grid,
          Math.round(reference.warmupSteps * grid / reference.rate));
        const image = `f${time.toFixed(4).replace('.', '_')}-${config.name.replace('@', '-g')}.png`;
        const data = png.slice(png.indexOf(',') + 1);
        fs.writeFileSync(path.join(out, image), Buffer.from(data, 'base64'));
        row.runs.push({ config: config.name, order: config.order, grid, rate: reference.rate, steps, warmupSteps, image, data,
          state: await frameState(page) });
      }
      const [base, ...others] = row.runs;
      for (const other of others) {
        other.versus = { baseline: base.config, bones: boneDelta(base.state, other.state),
          pixels: await compareImages(page, base.data, other.data, base.state.members, base.state.camera, margin, fraction) };
        console.log(JSON.stringify({ time, config: other.config, maxDeg: +other.versus.bones.max.toFixed(3),
          changedPct: +(other.versus.pixels.changedShare * 100).toFixed(3), outside: other.versus.pixels.outside,
          outsideExact: other.versus.pixels.outsideExact }));
      }
      for (const run of row.runs) { delete run.data; run.dynaBones = run.state.members.reduce((sum, member) => sum + member.dyna.length, 0);
        run.camera = run.state.camera; run.dumpErrors = run.state.errors;
        run.dyna = run.state.members.map((member) => Object.fromEntries(member.dyna.map((bone) => [bone.key.split('/').at(-1), bone.rotation])));
        delete run.state; }
      result.frames.push(row);
    }
    result.pageErrors = errors;
  } finally {
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 1));
    if (browser) await browser.close();
    if (server) server.child.kill();
  }
  const summary = {};
  for (const config of configs.slice(1)) {
    const runs = result.frames.map((frame) => ({ time: frame.time, ...frame.runs.find((run) => run.config === config.name)?.versus }));
    summary[config.name] = {
      maxDeg: Math.max(...runs.map((run) => run.bones?.max ?? 0)),
      maxChangedPct: Math.max(...runs.map((run) => (run.pixels?.changedShare ?? 0) * 100)),
      outsidePixels: runs.reduce((sum, run) => sum + (run.pixels?.outside ?? 0), 0),
      outsideExactPixels: runs.reduce((sum, run) => sum + (run.pixels?.outsideExact ?? 0), 0),
      frames: runs.map((run) => ({ time: run.time, maxDeg: run.bones?.max, regions: run.bones?.regions,
        changedPct: (run.pixels?.changedShare ?? 0) * 100, outside: run.pixels?.outside, outsideExact: run.pixels?.outsideExact,
        memberBox: run.pixels?.memberBox })),
    };
  }
  fs.writeFileSync(path.join(out, 'summary.json'), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify(Object.fromEntries(Object.entries(summary).map(([name, value]) =>
    [name, { maxDeg: value.maxDeg, maxChangedPct: value.maxChangedPct, outsidePixels: value.outsidePixels }]))));
  if (options.assert === 'true') {
    const noise = Number(options.noise ?? 0.15), envelope = Number(options.envelope ?? 4);
    const baseline = configs[0];
    for (const config of configs.slice(1)) {
      const value = summary[config.name];
      assert.equal(value.outsidePixels, 0, `${config.name}: pixels changed outside the members`);
      if (config.order === baseline.order) assert(value.maxDeg <= noise, `${config.name}: grid-only change ${value.maxDeg} deg > ${noise}`);
      else assert(value.maxDeg <= envelope, `${config.name}: order change ${value.maxDeg} deg > ${envelope}`);
    }
    assert.equal(result.pageErrors.length, 0, 'page errors');
  }
}

if (require.main === module) run().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
module.exports = { parseConfig, region, angle, boneDelta };
