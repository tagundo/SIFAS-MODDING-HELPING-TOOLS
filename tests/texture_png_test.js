"use strict";
const assert = require("assert");
const zlib = require("zlib");
const png = require("../webtools/web/static/texture-png.js");
const cases = [];
function test(name, run) { run(); cases.push(name); }
function crc32(bytes) {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) value = value & 1 ? (value >>> 1) ^ 0xedb88320 : value >>> 1;
  }
  return (value ^ 0xffffffff) >>> 0;
}
function paeth(a, b, c) {
  const p = a + b - c, da = Math.abs(p - a), db = Math.abs(p - b), dc = Math.abs(p - c);
  return da <= db && da <= dc ? a : db <= dc ? b : c;
}
function independentlyDecode(raw) {
  raw = Buffer.from(raw);
  assert.deepStrictEqual(raw.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  let offset = 8, header = null, ended = false;
  const idat = [];
  while (offset < raw.length) {
    assert(offset + 12 <= raw.length);
    const length = raw.readUInt32BE(offset), type = raw.toString("ascii", offset + 4, offset + 8);
    assert(offset + length + 12 <= raw.length);
    const data = raw.subarray(offset + 8, offset + 8 + length);
    assert.strictEqual(raw.readUInt32BE(offset + 8 + length), crc32(raw.subarray(offset + 4, offset + 8 + length)), `Invalid ${type} CRC`);
    if (type === "IHDR") {
      assert.strictEqual(offset, 8); assert.strictEqual(length, 13);
      header = { width: data.readUInt32BE(0), height: data.readUInt32BE(4) };
      assert.deepStrictEqual(Array.from(data.subarray(8)), [8, 6, 0, 0, 0]);
    } else if (type === "IDAT") idat.push(data);
    else if (type === "IEND") { assert.strictEqual(length, 0); ended = true; }
    offset += length + 12;
    if (ended) { assert.strictEqual(offset, raw.length); break; }
  }
  assert(header && ended && idat.length);
  const scanlines = zlib.inflateSync(Buffer.concat(idat)), stride = header.width * 4;
  assert.strictEqual(scanlines.length, (stride + 1) * header.height);
  const data = Buffer.alloc(stride * header.height);
  for (let y = 0; y < header.height; y++) {
    const filter = scanlines[y * (stride + 1)]; assert(filter >= 0 && filter <= 4);
    for (let x = 0; x < stride; x++) {
      const index = y * stride + x, left = x >= 4 ? data[index - 4] : 0;
      const up = y ? data[index - stride] : 0, upperLeft = y && x >= 4 ? data[index - stride - 4] : 0;
      const predictor = [0, left, up, Math.floor((left + up) / 2), paeth(left, up, upperLeft)][filter];
      data[index] = (scanlines[y * (stride + 1) + 1 + x] + predictor) & 255;
    }
  }
  return { ...header, data };
}
const width = 7, height = 3;
const special = [[241, 17, 99, 0], [15, 220, 39, 1], [250, 21, 75, 128], [8, 100, 235, 254], [200, 180, 150, 255]];
const data = Uint8ClampedArray.from(Array.from({ length: width * height }, (_, i) => special[i % special.length]).flat());
const image = { width, height, data };

test("non-square PNG validates every independent chunk CRC and exact straight-alpha pixels", () => {
  const original = Array.from(data), encoded = png.encodeBytes(image), decoded = independentlyDecode(encoded);
  assert.strictEqual(decoded.width, width); assert.strictEqual(decoded.height, height);
  assert.deepStrictEqual(Array.from(decoded.data), original);
  assert.deepStrictEqual(Array.from(data), original, "PNG encoding must not mutate the editor pixels");
});

test("independently compressed backend transport preserves invisible and translucent RGB", () => {
  const compressed = zlib.deflateSync(Buffer.from(data), { level: 9 });
  const decoded = png.decodeRGBA({ width, height, rgbaZlib: compressed.toString("base64") });
  assert.strictEqual(decoded.width, width); assert.strictEqual(decoded.height, height);
  assert(decoded.data instanceof Uint8ClampedArray);
  assert.deepStrictEqual(Array.from(decoded.data), Array.from(data));
});

test("invalid dimensions, pixel lengths, malformed base64 and zlib checksums fail", () => {
  for (const dimensions of [{ width: 0, height: 1 }, { width: 1, height: 0 }, { width: 1.5, height: 1 }, { width: 16777217, height: 1 }]) {
    assert.throws(() => png.encodeBytes({ ...dimensions, data: new Uint8ClampedArray(4) }));
    assert.throws(() => png.decodeRGBA({ ...dimensions, rgbaZlib: "" }));
  }
  assert.throws(() => png.encodeBytes({ width, height, data: data.subarray(4) }));
  for (const value of ["not base64", "AA=", "?", "A".repeat(24 * 1024 * 1024 + 1)]) {
    assert.throws(() => png.decodeRGBA({ width, height, rgbaZlib: value }));
  }
  const compressed = zlib.deflateSync(Buffer.from(data)); compressed[compressed.length - 1] ^= 1;
  assert.throws(() => png.decodeRGBA({ width, height, rgbaZlib: compressed.toString("base64") }), /checksum|zlib/i);
});

test("short and oversized inflated streams cannot be mistaken for declared dimensions", () => {
  assert.throws(() => png.decodeRGBA({ width: 2, height: 1, rgbaZlib: zlib.deflateSync(Buffer.alloc(4)).toString("base64") }));
  assert.throws(() => png.decodeRGBA({ width: 1, height: 1, rgbaZlib: zlib.deflateSync(Buffer.alloc(8)).toString("base64") }));
  // A fixed inflate output can truncate silently. Adler32 also collides after
  // 4*65521 added zero bytes, so the true output length must be bounded/tested
  // independently of its checksum. Both dimensions below fit normal limits.
  assert.throws(() => png.decodeRGBA({ width: 14, height: 1,
    rgbaZlib: zlib.deflateSync(Buffer.alloc(257 * 255 * 4)).toString("base64") }));
});

(async () => {
  const uri = await png.encodeRGBA(image);
  assert(uri.startsWith("data:image/png;base64,"));
  assert.deepStrictEqual(Array.from(independentlyDecode(Buffer.from(uri.split(",")[1], "base64")).data), Array.from(data));
  await assert.rejects(png.encodeRGBA({ width: 1, height: 1, data: new Uint8Array(3) }));
  cases.push("Promise data-URI encoding remains exact and rejects invalid images");
  console.log(JSON.stringify({ status: "PASS", cases: cases.length, names: cases }));
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
