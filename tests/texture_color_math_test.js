"use strict";
const assert = require("assert");
const math = require("../webtools/web/static/texture-color-math.js");
const cases = [];
function test(name, run) { run(); cases.push(name); }
function near(actual, expected, tolerance = 1e-6) {
  assert(Math.abs(actual - expected) <= tolerance, `${actual} differs from ${expected}`);
}
function hueDistance(a, b) { return Math.abs(((a - b + 540) % 360) - 180); }
function image(colors) { return Uint8ClampedArray.from(colors.flat()); }
function bytes(value) { return Array.from(value); }

test("published OKLab reference vectors and neutral hue", () => {
  const references = [
    [[255, 0, 0], [.6279553606, .2248630611, .1258462985]],
    [[0, 255, 0], [.8664396115, -.2338875742, .1794984799]],
    [[0, 0, 255], [.4520137184, -.0324569842, -.3115281477]],
    [[255, 255, 255], [.9999999935, 0, 0]],
    [[0, 0, 0], [0, 0, 0]]
  ];
  for (const [rgb, expected] of references) {
    math.rgbToOklab(rgb).forEach((v, i) => near(v, expected[i]));
    const back = math.oklchToRgb(math.rgbToOklch(rgb));
    back.forEach((v, i) => assert(Math.abs(v - rgb[i]) <= 1));
  }
  near(math.rgbToOklch([128, 128, 128])[2], 0);
  assert.deepStrictEqual(math.rgbToOklab(255, 0, 0), math.rgbToOklab([255, 0, 0]));
});

test("RGB round trips preserve all tested native byte colours", () => {
  for (let r = 0; r <= 255; r += 17) for (let g = 0; g <= 255; g += 17) for (let b = 0; b <= 255; b += 17) {
    const actual = math.oklchToRgb(math.rgbToOklch([r, g, b]));
    actual.forEach((v, i) => assert(Math.abs(v - [r, g, b][i]) <= 1));
  }
});

test("out-of-gamut colours reduce chroma while retaining L and hue", () => {
  for (const [L, C, H] of [[.65, .5, 40], [.5, 1, 270], [.72, .6, 150], [.35, .7, 5]]) {
    const rgb = math.oklchToRgb([L, C, H]);
    assert(rgb.every(v => v >= 0 && v <= 255 && Number.isInteger(v)));
    const actual = math.rgbToOklch(rgb);
    near(actual[0], L, .003);
    assert(hueDistance(actual[2], H) < 1, `${H} shifted to ${actual[2]}`);
    assert(actual[1] < C);
  }
  assert.deepStrictEqual(math.oklchToRgb(0, 1, 20), [0, 0, 0]);
  assert.deepStrictEqual(math.oklchToRgb(1, 1, 20), [255, 255, 255]);
});

test("identity, wrapped hue, zero strength and empty masks are byte-exact", () => {
  const input = image([[255, 5, 41, 13], [10, 33, 231, 0], [17, 91, 74, 255]]), original = bytes(input);
  for (const options of [{}, { hue: 720 }, { lightness: .2, hue: 40, strength: 0 }]) {
    const actual = math.adjustRGBA(input, 3, 1, null, options);
    assert.deepStrictEqual(bytes(actual), original);
    assert.notStrictEqual(actual, input);
  }
  assert.deepStrictEqual(bytes(math.adjustRGBA(input, 3, 1, new Uint8Array(3), { lightness: 1 })), original);
  assert.deepStrictEqual(bytes(input), original);
});

test("mask coverage and input alpha are preserved without editing hidden texels", () => {
  const input = image([[240, 40, 20, 255], [30, 210, 70, 37], [250, 40, 80, 0]]), snapshot = bytes(input);
  const full = math.adjustRGBA(input, 3, 1, null, { hue: 100 });
  const actual = math.adjustRGBA(input, 3, 1, Uint8Array.from([0, 128, 255]), { hue: 100 });
  assert.deepStrictEqual(bytes(actual.slice(0, 4)), snapshot.slice(0, 4));
  assert.deepStrictEqual(bytes(actual.slice(8, 12)), snapshot.slice(8, 12));
  for (let c = 0; c < 3; c++) near(actual[4 + c], input[4 + c] + (full[4 + c] - input[4 + c]) * 128 / 255, 1);
  for (let p = 0; p < 3; p++) assert.strictEqual(actual[p * 4 + 3], input[p * 4 + 3]);
  assert.deepStrictEqual(bytes(input), snapshot);
});

test("target-colour mode recolours neutral cloth while preserving its lightness detail", () => {
  const input = image([[80, 80, 80, 255], [180, 180, 180, 255]]);
  const actual = math.adjustRGBA(input, 2, 1, null, { mode: "colorize", color: "#e63366" });
  for (let p = 0; p < 2; p++) {
    near(math.rgbToOklch(actual.slice(p * 4, p * 4 + 3))[0], math.rgbToOklch(input.slice(p * 4, p * 4 + 3))[0], .003);
    assert(actual[p * 4] > actual[p * 4 + 1]);
  }
  assert(actual[4] > actual[0], "The original lightness difference must remain visible");
  const flat = math.adjustRGBA(input, 2, 1, null, { mode: "colorize", color: "#e63366", preserveLightness: false });
  assert.deepStrictEqual(bytes(flat.slice(0, 4)), bytes(flat.slice(4, 8)));
});

test("skin defaults use the existing calibrated map only inside confirmed skin", () => {
  const input = image([[220, 191, 157, 255], [230, 195, 160, 127], [220, 191, 157, 255]]);
  const actual = math.skinRGBA(input, 3, 1, Uint8Array.from([255, 128, 0]), { source: "default", target: "bright" });
  const a = [.83398, 1.07079, 1.09697], b = [40.2073, -8.3518, -9.9921];
  for (let p = 0; p < 2; p++) for (let c = 0; c < 3; c++) {
    const mapped = Math.max(0, Math.min(255, input[p * 4 + c] * a[c] + b[c]));
    near(actual[p * 4 + c], input[p * 4 + c] + (mapped - input[p * 4 + c]) * [1, 128 / 255][p], 1);
  }
  assert.deepStrictEqual(bytes(actual.slice(8)), bytes(input.slice(8)), "Peach costume pixels outside the mask must stay exact");
  assert.strictEqual(actual[3], 255); assert.strictEqual(actual[7], 127);
  assert.deepStrictEqual(bytes(math.skinRGBA(input, 3, 1, Uint8Array.from([255, 0, 0]), { source: "default", target: "default" })), bytes(input));
});

test("skin auto detection uses selected visible skin, never the surrounding costume", () => {
  const bright = math.referenceSkinMean.bright.map(Math.round);
  const medium = math.referenceSkinMean.medium_tone.map(Math.round);
  const colors = Array.from({ length: 20 }, () => [...bright, 255]);
  colors.push([...medium, 255], [...bright, 0]);
  const input = image(colors), mask = new Uint8Array(colors.length); mask[20] = mask[21] = 255;
  assert.strictEqual(math.detectToneFromMask(input, colors.length, 1, mask), "medium_tone");
  const analysis = math.analyzeToneFromMask(input, colors.length, 1, mask);
  assert.strictEqual(analysis.weight, 1); assert(analysis.confidence > 0);
  assert.deepStrictEqual(analysis.meanRGB, medium);
  const actual = math.skinRGBA(input, colors.length, 1, mask, { source: "auto", target: "bright" });
  assert.deepStrictEqual(bytes(actual.slice(0, 80)), bytes(input.slice(0, 80)));
});

test("skin selection is mandatory and invalid data cannot produce silent edits", () => {
  const input = image([[220, 190, 157, 255]]);
  for (const mask of [null, undefined, Uint8Array.from([0])]) assert.throws(() => math.skinRGBA(input, 1, 1, mask, { source: "default", target: "bright" }), /Select and confirm/);
  assert.throws(() => math.skinRGBA(input, 1, 1, Uint8Array.from([255]), { source: "unknown", target: "bright" }));
  assert.throws(() => math.adjustRGBA(input, 1, 1, null, { hue: NaN }));
  assert.throws(() => math.adjustRGBA(input, 1, 1, null, { mode: "colorize", color: "invalid" }));
  assert.throws(() => math.adjustRGBA(input, 2, 1, null, {}));
  assert.throws(() => math.rgbToOklab([255, 0, undefined]));
});

test("skin fine OKLCH changes remain gated and retain all alpha bytes", () => {
  const input = image([[220, 190, 157, 230], [220, 190, 157, 255]]);
  const actual = math.skinRGBA(input, 2, 1, Uint8Array.from([255, 0]), { source: "default", target: "bright", fine: { lightness: -.03, chroma: .8, hue: -8 } });
  assert.notDeepStrictEqual(bytes(actual.slice(0, 3)), bytes(input.slice(0, 3)));
  assert.strictEqual(actual[3], input[3]);
  assert.deepStrictEqual(bytes(actual.slice(4)), bytes(input.slice(4)));
  assert(math.approximateTones.includes("slight"));
});

test("colour region growing respects connectivity, alpha and gate coverage", () => {
  const red = [220, 30, 40, 255], blue = [30, 40, 220, 255];
  const input = image([red, blue, red, red, blue, red]);
  assert.deepStrictEqual(bytes(math.growMask(input, 3, 2, [[0, 0]], { tolerance: .001 })), [255, 0, 0, 255, 0, 0]);
  assert.deepStrictEqual(bytes(math.growMask(input, 3, 2, [{ x: 0, y: 0 }], { tolerance: .001, connected: false })), [255, 0, 255, 255, 0, 255]);
  const gate = Uint8Array.from([128, 255, 255, 0, 0, 255]);
  assert.deepStrictEqual(bytes(math.growMask(input, 3, 2, [0], { tolerance: 1, gate })), [128, 255, 255, 0, 0, 255]);
  const invisible = image([[220, 30, 40, 0], red]);
  assert.deepStrictEqual(bytes(math.growMask(invisible, 2, 1, [0], {})), [0, 0]);
});

test("negative colour seeds protect adjacent costume colours without gradient creep", () => {
  const input = image([[220, 191, 157, 255], [222, 193, 160, 255], [235, 185, 150, 255], [236, 186, 150, 255]]);
  const broad = math.growMask(input, 4, 1, [0], { tolerance: .2 });
  assert.deepStrictEqual(bytes(broad), [255, 255, 255, 255]);
  const protectedMask = math.growMask(input, 4, 1, [0], { tolerance: .2, excludeSeeds: [3] });
  assert.deepStrictEqual(bytes(protectedMask), [255, 255, 0, 0]);
});

test("optional eight-neighbour region selection does not alter the default topology", () => {
  const input = image([[220, 0, 0, 255], [0, 0, 220, 255], [0, 0, 220, 255], [220, 0, 0, 255]]);
  assert.deepStrictEqual(bytes(math.growMask(input, 2, 2, [0], { tolerance: .001 })), [255, 0, 0, 0]);
  assert.deepStrictEqual(bytes(math.growMask(input, 2, 2, [0], { tolerance: .001, connectivity: 8 })), [255, 0, 0, 255]);
});

test("mask feathering is inward-only and never leaks into clothing or beyond gate", () => {
  const original = new Uint8Array(49); for (let y = 1; y < 6; y++) for (let x = 1; x < 6; x++) original[y * 7 + x] = 255;
  const gate = new Uint8Array(49).fill(255); gate[3 * 7 + 3] = 0;
  const actual = math.featherMask(original, 7, 7, 2, gate);
  for (let p = 0; p < 49; p++) {
    if (!original[p] || !gate[p]) assert.strictEqual(actual[p], 0);
    assert(actual[p] <= original[p] && actual[p] <= gate[p]);
  }
  assert(actual[8] > 0 && actual[8] < 255);
  assert.deepStrictEqual(bytes(math.featherMask(original, 7, 7, 0)), bytes(original));
});

console.log(JSON.stringify({ status: "PASS", cases: cases.length, names: cases }));
