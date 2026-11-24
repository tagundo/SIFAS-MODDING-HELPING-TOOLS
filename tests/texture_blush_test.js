/* texture-blush.js equals webtools/core/texture_blush.py byte for byte, and
 * the paint engine's pixel-free undo steps carry the bake. Synthetic arrays only. */
'use strict';
const assert = require('assert'), path = require('path'), { execFileSync } = require('child_process');
const product = path.resolve(__dirname, '..');
const B = require(path.join(product, 'webtools/web/static/texture-blush.js'));
const Engine = require(path.join(product, 'webtools/web/static/texture-paint-engine.js'));
const python = process.env.VIEWER_PYTHON || 'python3';
const cases = [];
function check(name, fn) { fn(); cases.push(name); }

const reference = JSON.parse(execFileSync(python, ['-B', '-c', `
import base64, json, random
from webtools.core import texture_blush as tb
from test_texture_blush import blob_layer, white_layer, put
layers = [blob_layer(), blob_layer(darkest=(255, 210, 207))]
edge = white_layer()
for y in range(256):
    put(edge, 255, y, (255, 128, 128))
layers.append(bytes(edge))
rng = random.Random(9)
rows = []
for width, height, k, layer in ((97, 61, 1.65, 0), (64, 64, 0.5, 1), (128, 32, 3.0, 0), (7, 5, 2.3, 1), (256, 256, 1.05, 0), (1, 1, 1.0, 0), (64, 64, 1.0, 2)):
    image = bytes(rng.randrange(256) for _ in range(width * height * 4))
    out, changed, box = tb.bake_rgba(image, width, height, layers[layer], k)
    rows.append({"width": width, "height": height, "k": k, "layer": layer, "image": base64.b64encode(image).decode(),
                 "out": base64.b64encode(out).decode(), "changed": changed, "box": list(box) if box else None})
print(json.dumps({"layers": [base64.b64encode(value).decode() for value in layers], "rows": rows,
                  "levels": [{"id": name, "k": k} for name, k in tb.LEVELS], "maxK": tb.MAX_K, "defaultLevel": tb.DEFAULT_LEVEL,
                  "defaultLayer": tb.DEFAULT_LAYER, "encodings": list(tb.ENCODINGS), "defaultEncoding": tb.DEFAULT_ENCODING, "scale": tb.UV_SCALE, "offset": tb.UV_OFFSET_V, "sha": tb.CHEEK_SHA256,
                  "samples": [tb.sample(layers[0], cu, cv) for cu, cv in ((0.43, 0.53), (0.7, 0.51), (-1.0, 0.5), (0.5, 1.4))]}))
`], { cwd: product, env: { ...process.env, PYTHONPATH: [product, path.join(product, 'tests')].join(path.delimiter) }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }));
const layers = reference.layers.map(value => new Uint8Array(Buffer.from(value, 'base64')));

check('constants, level table and defaults are the Python ones', () => {
  assert.strictEqual(B.UV_SCALE, reference.scale); assert.strictEqual(B.UV_OFFSET_V, reference.offset);
  assert.deepStrictEqual(B.LEVELS.map(level => ({ id: level.id, k: level.k })), reference.levels);
  assert.strictEqual(B.MAX_K, reference.maxK); assert.strictEqual(B.DEFAULT_LEVEL, reference.defaultLevel); assert.strictEqual(B.DEFAULT_LAYER, reference.defaultLayer);
  assert.strictEqual(B.CHEEK_SHA256, reference.sha);
  assert.deepStrictEqual(B.LEVELS.map(level => level.label), ['Very light', 'Light', 'Medium', 'Strong', 'Very strong']);
});
check('bilinear Clamp samples are bit-identical', () => {
  [[0.43, 0.53], [0.7, 0.51], [-1.0, 0.5], [0.5, 1.4]].forEach((uv, i) => assert.deepStrictEqual(B.sample(layers[0], uv[0], uv[1]), reference.samples[i]));
});
check('bakes are byte-identical to Python for both layers, odd sizes and a non-white Clamp edge', () => {
  reference.rows.forEach(row => {
    const image = new Uint8ClampedArray(Buffer.from(row.image, 'base64')), result = B.bakeRGBA(image, row.width, row.height, layers[row.layer], row.k);
    assert.ok(Buffer.from(result.data).equals(Buffer.from(row.out, 'base64')), JSON.stringify([row.width, row.height, row.k, row.layer]));
    assert.strictEqual(result.changed, row.changed); assert.deepStrictEqual(result.box, row.box);
    for (let i = 3; i < image.length; i += 4) assert.strictEqual(result.data[i], image[i], 'alpha is untouched');
    assert.ok(Buffer.from(image).equals(Buffer.from(row.image, 'base64')), 'the source image is not modified');
  });
});
check('level swatches are the baked texel at the darkest cheek point', () => {
  const row = reference.rows[4], image = { width: row.width, height: row.height, data: new Uint8ClampedArray(Buffer.from(row.image, 'base64')) };
  const swatch = B.swatches(image, layers[0]), point = swatch.point, o = (point.y * image.width + point.x) * 4;
  assert.deepStrictEqual(swatch.base, Array.from(image.data.subarray(o, o + 3)));
  B.LEVELS.forEach((level, i) => {
    const baked = B.bakeRGBA(image.data, image.width, image.height, layers[0], level.k).data;
    assert.deepStrictEqual(swatch.colours[i], Array.from(baked.subarray(o, o + 3)), level.id);
  });
  for (let i = 1; i < swatch.colours.length; i++) assert.ok(swatch.colours[i][1] < swatch.colours[i - 1][1] && swatch.colours[i][2] < swatch.colours[i - 1][2], 'every level is darker than the one below');
});
check('invalid strengths, types and arrays are refused', () => {
  [0, -1, 4.01, NaN, Infinity, '1', true, null].forEach(k => assert.throws(() => B.checkedK(k)));
  [2, -1, '0', 0.5, null].forEach(layer => assert.throws(() => B.checkedLayer(layer)));
  assert.throws(() => B.bakeRGBA(new Uint8ClampedArray(4), 1, 1, layers[0].subarray(4), 1));
  assert.throws(() => B.layerView(new Uint8Array(B.LAYER_BYTES), 0));
  assert.strictEqual(B.levelFor(1.65), 'medium'); assert.strictEqual(B.levelFor(1.7), null); assert.strictEqual(B.levelK('veryStrong'), 3);
});
check('recipe operations: the encoding is canonical, exact by default, and the same rule as Python', () => {
  assert.deepStrictEqual([B.ENCODINGS, B.DEFAULT_ENCODING], [reference.encodings, reference.defaultEncoding]);
  assert.deepStrictEqual(B.checkedOperation({ layer: 1, k: 2 }), { layer: 1, k: 2, encoding: 'exact' }, 'a row without an encoding is exact');
  assert.deepStrictEqual(B.checkedOperation({ layer: 0, k: 1.65, encoding: 'exact' }), { layer: 0, k: 1.65, encoding: 'exact' });
  assert.deepStrictEqual(B.checkedOperation({ layer: 0, k: 1.65, encoding: 'astc-keep' }), { layer: 0, k: 1.65, encoding: 'astc-keep' });
  const invalid = [{ layer: 0 }, { layer: 0, k: 1, level: 'medium' }, { layer: 0, k: 1, exact: true }, { layer: 0, k: 1, encoding: 'fast' }, { layer: 0, k: 1, encoding: true },
    { layer: 0, k: 1, encoding: null }, { layer: 2, k: 1 }, { layer: 0, k: 0 }, null, [], 'x'];
  invalid.forEach(value => assert.throws(() => B.checkedOperation(value), JSON.stringify(value)));
  // Python checked_blush accepts and refuses exactly the same rows, with the same canonical form.
  const fromPython = JSON.parse(execFileSync(python, ['-B', '-c', `
import json, sys
from webtools.core import viewer_texture_tools as t
out = []
for value in json.loads(sys.argv[1]):
    try:
        out.append(t.checked_blush(value))
    except ValueError:
        out.append("refused")
print(json.dumps(out))`, JSON.stringify([{ layer: 1, k: 2 }, { layer: 0, k: 1.65, encoding: 'astc-keep' }].concat(invalid))], { cwd: product, env: { ...process.env, PYTHONPATH: product }, encoding: 'utf8' }));
  assert.deepStrictEqual(fromPython, [{ layer: 1, k: 2, encoding: 'exact' }, { layer: 0, k: 1.65, encoding: 'astc-keep' }].concat(invalid.map(() => 'refused')));
  assert.ok(B.sameOperation({ layer: 0, k: 1 }, { layer: 0, k: 1, encoding: 'exact' })); assert.ok(!B.sameOperation({ layer: 0, k: 1 }, { layer: 0, k: 1, encoding: 'astc-keep' }));
  assert.ok(B.sameOperation(null, null)); assert.ok(!B.sameOperation(null, { layer: 0, k: 1 }));
  assert.deepStrictEqual(B.copyOperation({ layer: 1, k: 3, encoding: 'astc-keep', extra: 1 }), { layer: 1, k: 3, encoding: 'astc-keep' });
  assert.deepStrictEqual(B.copyOperation({ layer: 1, k: 3 }), { layer: 1, k: 3, encoding: 'exact' }); assert.strictEqual(B.copyOperation(null), null);
});
check('engine recordState is a pixel-free undo step and replaceImageData carries its custom state', () => {
  const engine = Engine.create({}), calls = [];
  const image = { width: 2, height: 2, data: new Uint8ClampedArray([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]) };
  engine.setImage(image);
  engine.recordState('Bake blush', redo => calls.push(redo));
  assert.strictEqual(engine.getState().undoCount, 1); assert.strictEqual(engine.getState().revision, 0);
  assert.ok(engine.undo()); assert.deepStrictEqual(calls, [false]); assert.strictEqual(engine.getState().redoCount, 1);
  assert.ok(engine.redo()); assert.deepStrictEqual(calls, [false, true]);
  assert.deepStrictEqual(Array.from(engine.getImage().data), Array.from(image.data), 'no pixel changes');
  const blank = { width: 2, height: 2, data: new Uint8ClampedArray(16) }, restored = [];
  engine.replaceImageData(blank, { label: 'Restore original texture', custom: redo => restored.push(redo) });
  assert.ok(engine.undo()); assert.deepStrictEqual(restored, [false]); assert.deepStrictEqual(Array.from(engine.getImage().data), Array.from(image.data));
  assert.ok(engine.redo()); assert.deepStrictEqual(restored, [false, true]); assert.deepStrictEqual(Array.from(engine.getImage().data), Array.from(blank.data));
  assert.throws(() => engine.recordState('x', null));
  engine.destroy();
});
check('every blush panel string has Korean and Japanese wording', () => {
  const fs = require('fs'), vm = require('vm'), source = fs.readFileSync(path.join(product, 'webtools/web/static/viewer-texture-tools.js'), 'utf8');
  const words = vm.runInNewContext('(' + source.slice(source.indexOf('var WORDS = {') + 'var WORDS = '.length, source.indexOf('};', source.indexOf('var WORDS = {')) + 1) + ')');
  const regions = [['// Baked cheek blush: one panel', '// End of the blush panel strings.'], ['// --- baked cheek blush', 'function blushState()'], ['function applyImported(', 'function finishPickerStack()']];
  const texts = new Set(B.LEVELS.map(level => level.label).concat(B.LAYERS.map(layer => layer.label), B.LAYERS.map(layer => layer.hint)));
  regions.forEach(([from, to]) => {
    const start = source.indexOf(from), end = source.indexOf(to, start); assert.ok(start >= 0 && end > start, from);
    for (const match of source.slice(start, end).matchAll(/"((?:[^"\\]|\\.)*)"/g)) if (/^[A-Z0-9]/.test(match[1]) && /[a-z]/.test(match[1]) && !/^(AbortError)$/.test(match[1])) texts.add(match[1]);
  });
  // Server errors shown in this panel and, through webtools/i18n.py, in the Save status.
  const serverErrors = ['Choose a blush strength between 0 and 4.', 'Choose the Ppo or Akarame blush type.', 'The blush bake takes only a blush type, a strength and a save mode.',
    'Baked blush is available only for a head material\'s main texture or its recolour texture.', 'This model has no head texture that can take a baked blush.'];
  const server = JSON.parse(execFileSync(python, ['-B', '-c', `
import json, sys
from webtools.core import viewer_texture_tools as t
from webtools import i18n
texts = json.loads(sys.argv[1]) + [t.CHEEK_UNAVAILABLE]
print(json.dumps({"reason": t.CHEEK_UNAVAILABLE, "ko": i18n.tr("Baked blush", "ko"), "ja": i18n.tr("Baked blush", "ja"),
                  "errors": {text: [i18n.tr(text, "ko"), i18n.tr(text, "ja")] for text in texts}}))`, JSON.stringify(serverErrors)], { cwd: product, env: { ...process.env, PYTHONPATH: product }, encoding: 'utf8' }));
  texts.add(server.reason); serverErrors.forEach(text => texts.add(text));
  // The Save status (webtools/i18n.py) and this panel use the same wording.
  Object.keys(server.errors).forEach(text => assert.deepStrictEqual(server.errors[text], Array.from(words[text]), text));
  assert.strictEqual(Object.keys(server.errors).length, 6);
  const missing = Array.from(texts).filter(text => !Array.isArray(words[text]) || words[text].length !== 2 || words[text].some(value => !value || value === text));
  assert.deepStrictEqual(missing, [], 'untranslated blush strings');
  assert.ok(texts.size >= 45, 'the scan found the panel strings: ' + texts.size);
  // One word per control: Korean 세기 (never 강도) and Japanese 強さ for the blush strength.
  Array.from(texts).forEach(text => { assert.ok(!/강도/.test(words[text][0]) && !/強度/.test(words[text][1]), text); assert.ok(!/ 볼 픽셀/.test(words[text][0]), text); });
  assert.deepStrictEqual([server.ko, server.ja], ['홍조 굽기', '頬紅の焼き込み']);
  assert.deepStrictEqual(Array.from(words['Bake blush']), ['홍조 굽기', '頬紅の焼き込み']);
  // The two types differ in shape, not strength: their labels name the shape and
  // never carry a strength word (those belong to the five levels only).
  assert.deepStrictEqual(B.LAYERS.map(layer => [layer.label].concat(words[layer.label])), [
    ['Cheeks (Ppo)', '볼 홍조(Ppo)', '頬(Ppo)'], ['Cheeks and nose (Akarame)', '볼·콧등 홍조(Akarame)', '頬・鼻すじ(Akarame)']]);
  assert.deepStrictEqual(B.LAYERS.map(layer => [layer.hint].concat(words[layer.hint])), [
    ['Round cheek patches', '양 볼의 동그란 무늬', '両頬の丸い模様'], ['Band across the nose', '코를 가로지르는 띠', '鼻をまたぐ帯']]);
  B.LAYERS.forEach(layer => [layer.label].concat(words[layer.label]).forEach(text => assert.ok(!/strong|deep|dark|light|진한|진하|짙|연한|약한|濃|薄|強|弱/i.test(text), text)));
  // One Japanese word for blush in the panel (頬紅), never 赤み beside it.
  Array.from(texts).forEach(text => assert.ok(!/赤み/.test(words[text][1]), text));
  // The visible save line carries the size factor of the ASTC texture it describes.
  assert.ok(words['Save: exact pixels (data about {n}× larger)'].every(text => text.includes('{n}')));
  // The Remove button keeps the panel's own wording (the viewer's generic "Remove" is 삭제/削除).
  assert.deepStrictEqual(Array.from(words.Remove), Array.from(words['Remove blush']));
  // The hint about the game's own blush names the level exactly as its button does.
  const hint = words["Light ≈ the game's strongest song blush"];
  assert.ok(hint[0].includes('‘' + words.Light[0] + '’') && hint[1].includes('「' + words.Light[1] + '」'), JSON.stringify(hint));
});
console.log(JSON.stringify({ status: 'PASS', cases: cases.length, names: cases }));
