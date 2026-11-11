/* Exact straight-alpha RGBA transport. Canvas is display-only, never an encoder. */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory(require("./vendor/fflate-0.8.2/fflate.min.js"));
  else root.TexturePNG = factory(root.fflate);
})(typeof window !== "undefined" ? window : globalThis, function (zip) {
  "use strict";
  var LIMIT = 16 * 1024 * 1024, table = new Uint32Array(256);
  for (var i = 0; i < 256; i++) { var c = i; for (var j = 0; j < 8; j++) c = c & 1 ? 0xedb88320 ^ c >>> 1 : c >>> 1; table[i] = c; }
  function dimensions(width, height) {
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width * height > LIMIT) throw new Error("The texture dimensions exceed the editor limit.");
    return width * height * 4;
  }
  function crc(bytes) { var value = 0xffffffff; for (var k = 0; k < bytes.length; k++) value = table[(value ^ bytes[k]) & 255] ^ value >>> 8; return (value ^ 0xffffffff) >>> 0; }
  function adler(bytes) { var a = 1, b = 0; for (var start = 0; start < bytes.length; start += 5552) { var end = Math.min(bytes.length, start + 5552); for (var k = start; k < end; k++) { a += bytes[k]; b += a; } a %= 65521; b %= 65521; } return ((b << 16) | a) >>> 0; }
  function be(bytes, offset, value) { new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).setUint32(offset, value, false); }
  function chunk(name, data) {
    var result = new Uint8Array(data.length + 12); be(result, 0, data.length);
    for (var k = 0; k < 4; k++) result[4 + k] = name.charCodeAt(k);
    result.set(data, 8); be(result, result.length - 4, crc(result.subarray(4, result.length - 4))); return result;
  }
  function base64(bytes) {
    if (typeof Buffer !== "undefined") return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString("base64");
    var pieces = []; for (var k = 0; k < bytes.length; k += 16384) pieces.push(String.fromCharCode.apply(null, bytes.subarray(k, k + 16384)));
    return btoa(pieces.join(""));
  }
  function unbase64(text) {
    if (typeof text !== "string" || text.length > Math.ceil((LIMIT * 4 + 65536) / 3) * 4 || text.length % 4 || !/^[A-Za-z0-9+/]*={0,2}$/.test(text)) throw new Error("Invalid texture pixel data.");
    if (typeof Buffer !== "undefined") return new Uint8Array(Buffer.from(text, "base64"));
    var binary = atob(text), bytes = new Uint8Array(binary.length); for (var k = 0; k < binary.length; k++) bytes[k] = binary.charCodeAt(k); return bytes;
  }
  function decodeRGBA(response) {
    if (!zip || !zip.unzlibSync) throw new Error("The lossless texture decoder is unavailable.");
    var size = dimensions(response.width, response.height), compressed = unbase64(response.rgbaZlib);
    if (compressed.length < 6) throw new Error("The texture pixel data is truncated.");
    // An extra byte makes oversized streams observable even when their Adler
    // checksum collides with a truncated prefix. Allocation stays bounded.
    var bytes = zip.unzlibSync(compressed, { out: new Uint8Array(size + 1) });
    var expected = new DataView(compressed.buffer, compressed.byteOffset, compressed.byteLength).getUint32(compressed.length - 4, false);
    if (bytes.length !== size || adler(bytes) !== expected) throw new Error("The texture pixel checksum does not match.");
    return { width: response.width, height: response.height, data: new Uint8ClampedArray(bytes.buffer, bytes.byteOffset, bytes.byteLength) };
  }
  function encodeBytes(image) {
    if (!zip || !zip.zlibSync) throw new Error("The lossless texture encoder is unavailable.");
    var size = dimensions(image.width, image.height);
    if (!image.data || image.data.length !== size) throw new Error("The texture pixel dimensions do not match.");
    var stride = image.width * 4, scanlines = new Uint8Array(size + image.height);
    for (var row = 0; row < image.height; row++) scanlines.set(image.data.subarray(row * stride, (row + 1) * stride), row * (stride + 1) + 1);
    var header = new Uint8Array(13); be(header, 0, image.width); be(header, 4, image.height); header[8] = 8; header[9] = 6;
    var chunks = [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header), chunk("IDAT", zip.zlibSync(scanlines, { level: 3 })), chunk("IEND", new Uint8Array(0))];
    var total = chunks.reduce(function (n, value) { return n + value.length; }, 0), png = new Uint8Array(total), offset = 0;
    chunks.forEach(function (value) { png.set(value, offset); offset += value.length; }); return png;
  }
  return { decodeRGBA: decodeRGBA, encodeBytes: encodeBytes, encodeRGBA: function (image) {
    try { return Promise.resolve("data:image/png;base64," + base64(encodeBytes(image))); } catch (error) { return Promise.reject(error); }
  }, maxPixels: LIMIT };
});
