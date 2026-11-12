/* Execute the real shared request helpers against declared fetch boundaries. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), path = require('path'), vm = require('vm');
const script = path.resolve(__dirname, '../webtools/web/static/platform.js'), source = fs.readFileSync(script, 'utf8');
const sha = value => crypto.createHash('sha256').update(value).digest('hex'), sourceSha256 = sha(source);
const detail = { operation: 'Lower body replacement', stage: 'Donor inspection', filename: 'donor.unity' };
const url = '/api/viewer/transplant/inspect?private=never-print#private-fragment';
const plain = value => JSON.parse(JSON.stringify(value));
function harness({ language = 'en', textEncoder = true, urlConstructor = true } = {}) {
  const calls = [], events = new Map(), classes = new Set();
  let responder = () => { throw Error('Unexpected fetch'); };
  const document = { documentElement: { lang: language, classList: { add: (...names) => names.forEach(name => classes.add(name)) } } };
  const window = { document, location: { protocol: 'http:', hostname: '127.0.0.1', href: 'http://127.0.0.1:43123/' },
    URL: urlConstructor ? URL : undefined, TextEncoder: textEncoder ? TextEncoder : undefined, setTimeout, clearTimeout,
    addEventListener: (name, listener) => events.set(name, listener),
    fetch: async (requestUrl, init) => { calls.push({ url: requestUrl, init }); return responder(requestUrl, init); } };
  window.self = window; window.top = window;
  vm.runInNewContext(source, { window, document }, { filename: script });
  return { api: window.ElichikaPlatform, calls, events, document, respond: callback => { responder = callback; } };
}
function jsonResponse(value, status = 200, headers = {}) { return new Response(JSON.stringify(value), { status, headers }); }
async function rejected(promise) { try { await promise; } catch (error) { return error; } assert.fail('Expected request to reject'); }
function context(error, { code, status = 0, method = 'POST', endpoint = '/api/viewer/transplant/inspect', reason } = {}) {
  assert.deepStrictEqual(plain(error.requestContext), { ...detail, method, url: endpoint, status, code });
  for (const value of [detail.operation, detail.stage, detail.filename, method + ' ' + endpoint, reason].filter(Boolean)) assert(error.message.includes(value), error.message);
  if (status) assert(error.message.includes('HTTP ' + status), error.message);
  assert(!error.message.includes('never-print') && !error.message.includes('private-fragment'), 'diagnostics omit request query and fragment');
}
async function main() {
  const checks = [];
  async function check(name, run) { await run(); checks.push(name); }
  await check('real frozen platform exports load in a minimal browser context', async () => {
    const h = harness(); assert(Object.isFrozen(h.api));
    for (const name of ['requestJSON', 'requestBytes', 'requestError']) { assert.equal(typeof h.api[name], 'function'); assert.equal(Object.getOwnPropertyDescriptor(h.api, name).writable, false); }
    assert.equal(h.api.info().platform, 'browser'); assert(h.events.has('pagehide')); assert.equal(h.calls.length, 0);
  });
  await check('JSON success preserves response data and GET/POST/explicit method contracts', async () => {
    const h = harness(); h.respond(() => jsonResponse({ mesh: 123 }));
    assert.deepStrictEqual(plain(await h.api.requestJSON(url, undefined, detail)), { mesh: 123 });
    assert.equal(h.calls[0].init.method, 'GET'); assert.equal(h.calls[0].init.body, undefined);
    for (const payload of [null, false, ['a', 2]]) {
      h.respond(() => jsonResponse(payload)); const value = await h.api.requestJSON(url, payload, detail);
      assert.deepStrictEqual(plain(value), payload); assert.equal(h.calls.at(-1).init.method, 'POST'); assert.equal(h.calls.at(-1).init.body, JSON.stringify(payload));
      assert.equal(h.calls.at(-1).init.headers['Content-Type'], 'application/json');
    }
    await h.api.requestJSON(url, { donor: 'donor.unity' }, { ...detail, method: 'PUT' }); assert.equal(h.calls.at(-1).init.method, 'PUT');
  });
  await check('network Load failed keeps cause, no-response explanation and complete request context', async () => {
    const h = harness(), failure = new TypeError('Load failed'); h.respond(() => { throw failure; });
    const error = await rejected(h.api.requestJSON(url, {}, detail)); context(error, { code: 'network_error', reason: 'No HTTP response was received (Load failed)' });
    assert.strictEqual(error.cause, failure); assert.strictEqual(h.calls[0].url, url, 'redaction does not change the actual request');
  });
  await check('JSON HTTP error retains server error code, nested backend reason and HTTP status', async () => {
    const h = harness(); h.respond(() => jsonResponse({ error: { message: 'Missing donor mesh 123.' }, error_code: 'missing_mesh' }, 422));
    context(await rejected(h.api.requestJSON(url, {}, detail)), { code: 'missing_mesh', status: 422, reason: 'Missing donor mesh 123.' });
  });
  await check('successful HTTP response carrying a backend error still rejects with its reason', async () => {
    const h = harness(); h.respond(() => jsonResponse({ error: { detail: 'The saved source fingerprint changed.' } }));
    context(await rejected(h.api.requestJSON(url, {}, detail)), { code: 'http_error', status: 200, reason: 'The saved source fingerprint changed.' });
  });
  await check('non-JSON HTTP errors retain readable body instead of a JSON parse failure', async () => {
    const h = harness(); h.respond(() => new Response('Failed to read donor.unity: device I/O error.', { status: 503 }));
    context(await rejected(h.api.requestJSON(url, {}, detail)), { code: 'http_error', status: 503, reason: 'Failed to read donor.unity: device I/O error.' });
  });
  await check('empty HTTP error body falls back to the actual HTTP status text', async () => {
    const h = harness(); h.respond(() => new Response('', { status: 502, statusText: 'Bad Gateway' }));
    context(await rejected(h.api.requestJSON(url, {}, detail)), { code: 'http_error', status: 502, reason: 'Bad Gateway' });
  });
  await check('malformed successful JSON has a distinct code, status, body excerpt and parser cause', async () => {
    const h = harness(); h.respond(() => new Response('<html>Proxy returned a login page.</html>', { status: 200 }));
    const error = await rejected(h.api.requestJSON(url, {}, detail)); context(error, { code: 'invalid_json', status: 200, reason: 'Proxy returned a login page.' });
    assert.equal(error.cause.name, 'SyntaxError'); assert(error.message.includes('The response was not valid JSON'));
  });
  await check('JSON response read failure keeps original cause and received status', async () => {
    const h = harness(), failure = new TypeError('Response stream terminated.'); h.respond(() => ({ status: 206, ok: true, text: async () => { throw failure; } }));
    const error = await rejected(h.api.requestJSON(url, {}, detail)); context(error, { code: 'response_read_error', status: 206, reason: 'Response stream terminated.' }); assert.strictEqual(error.cause, failure);
  });
  await check('byte success returns original bytes at the exact size boundary', async () => {
    const h = harness(), payload = new Uint8Array([71, 76, 66, 0]); h.respond(() => new Response(payload, { headers: { 'Content-Length': '4' } }));
    assert.deepStrictEqual(Array.from(new Uint8Array(await h.api.requestBytes(url, { ...detail, maxBytes: 4 }))), Array.from(payload)); assert.equal(h.calls[0].init.method, 'GET');
  });
  await check('byte HTTP 404 retains JSON backend reason and code before reading binary data', async () => {
    const h = harness(); h.respond(() => jsonResponse({ error: 'The GLB preview cache entry expired.', error_code: 'preview_missing' }, 404));
    context(await rejected(h.api.requestBytes(url, detail)), { code: 'preview_missing', status: 404, method: 'GET', reason: 'The GLB preview cache entry expired.' });
  });
  await check('byte HTTP error also preserves non-JSON backend text', async () => {
    const h = harness(); h.respond(() => new Response('The preview file could not be opened.', { status: 500 }));
    context(await rejected(h.api.requestBytes(url, detail)), { code: 'http_error', status: 500, method: 'GET', reason: 'The preview file could not be opened.' });
  });
  await check('oversize Content-Length rejects before materializing bytes and cancels the stream', async () => {
    const h = harness(); let read = 0, cancel = 0;
    h.respond(() => ({ status: 200, ok: true, headers: new Headers({ 'Content-Length': '5' }), body: { cancel: async () => { cancel++; } }, arrayBuffer: async () => { read++; return new ArrayBuffer(5); } }));
    context(await rejected(h.api.requestBytes(url, { ...detail, maxBytes: 4 })), { code: 'data_limit', status: 200, method: 'GET', reason: '5 > 4 bytes' }); assert.equal(read, 0); assert.equal(cancel, 1);
  });
  await check('stream cancellation rejection does not replace the meaningful byte-limit failure', async () => {
    const h = harness(); h.respond(() => ({ status: 200, ok: true, headers: new Headers({ 'Content-Length': '9' }), body: { cancel: async () => { throw Error('Cancel already closed stream.'); } } }));
    const error = await rejected(h.api.requestBytes(url, { ...detail, maxBytes: 4 })); context(error, { code: 'data_limit', status: 200, method: 'GET', reason: '9 > 4 bytes' }); assert(!error.message.includes('Cancel already'));
  });
  await check('byte default limit remains bounded without allocating a large payload', async () => {
    const h = harness(); h.respond(() => ({ status: 200, ok: true, headers: new Headers({ 'Content-Length': String(64 * 1024 * 1024 + 1) }) }));
    context(await rejected(h.api.requestBytes(url, detail)), { code: 'data_limit', status: 200, method: 'GET', reason: '67108865 > 67108864 bytes' });
  });
  await check('absent or misleading small Content-Length cannot bypass actual byte-size limit', async () => {
    for (const headers of [{}, { 'Content-Length': '1' }]) {
      const h = harness(); h.respond(() => new Response(new Uint8Array(5), { headers }));
      context(await rejected(h.api.requestBytes(url, { ...detail, maxBytes: 4 })), { code: 'data_limit', status: 200, method: 'GET', reason: '5 > 4 bytes' });
    }
  });
  await check('byte body read failure retains original cause and GET/status context', async () => {
    const h = harness(), failure = new TypeError('GLB response body was interrupted.'); h.respond(() => ({ status: 200, ok: true, headers: new Headers(), arrayBuffer: async () => { throw failure; } }));
    const error = await rejected(h.api.requestBytes(url, detail)); context(error, { code: 'response_read_error', status: 200, method: 'GET', reason: 'GLB response body was interrupted.' }); assert.strictEqual(error.cause, failure);
  });
  await check('AbortError is rethrown as the same object at fetch and both body-reading boundaries', async () => {
    for (const boundary of ['json-fetch', 'bytes-fetch', 'json-body', 'bytes-body']) {
      const h = harness(), failure = new DOMException('The user changed models.', 'AbortError');
      h.respond(() => {
        if (boundary.endsWith('fetch')) throw failure;
        return { status: 200, ok: true, headers: new Headers(), text: async () => { throw failure; }, arrayBuffer: async () => { throw failure; } };
      });
      assert.strictEqual(await rejected(boundary.startsWith('json') ? h.api.requestJSON(url, {}, detail) : h.api.requestBytes(url, detail)), failure, boundary);
    }
  });
  await check('aborted signal preserves an ordinary network/body error object without wrapping', async () => {
    for (const boundary of ['json-fetch', 'bytes-fetch', 'json-body', 'bytes-body']) {
      const h = harness(), controller = new AbortController(), failure = new TypeError('Load failed after abort.'); controller.abort();
      h.respond(() => {
        if (boundary.endsWith('fetch')) throw failure;
        return { status: 200, ok: true, headers: new Headers(), text: async () => { throw failure; }, arrayBuffer: async () => { throw failure; } };
      });
      const options = { ...detail, signal: controller.signal };
      assert.strictEqual(await rejected(boundary.startsWith('json') ? h.api.requestJSON(url, {}, options) : h.api.requestBytes(url, options)), failure, boundary);
      assert.strictEqual(h.calls[0].init.signal, controller.signal);
    }
  });
  await check('viewerStale and existing requestContext errors preserve identity and avoid duplicate context', async () => {
    const h = harness(), stale = new Error('The viewer changed.'); stale.viewerStale = true;
    assert.strictEqual(h.api.requestError(stale, detail, { url }), stale); h.respond(() => { throw stale; }); assert.strictEqual(await rejected(h.api.requestJSON(url, {}, detail)), stale);
    const wrapped = h.api.requestError(new Error('Load failed'), detail, { url, method: 'POST' });
    assert.strictEqual(h.api.requestError(wrapped, detail, { url, method: 'POST' }), wrapped); h.respond(() => { throw wrapped; }); assert.strictEqual(await rejected(h.api.requestBytes(url, detail)), wrapped);
  });
  await check('circular and BigInt payloads fail encoding before fetch and retain encoder cause', async () => {
    const circular = {}; circular.self = circular;
    for (const payload of [circular, { vertex: 1n }]) {
      const h = harness(), error = await rejected(h.api.requestJSON(url, payload, detail)); context(error, { code: 'request_encoding_error', reason: 'The request could not be encoded' }); assert.equal(error.cause.name, 'TypeError'); assert.equal(h.calls.length, 0);
    }
  });
  await check('UTF-8 request preflight rejects one-byte excess before fetch and accepts exact byte limit', async () => {
    const payload = { label: '가😀' }, body = JSON.stringify(payload), bytes = Buffer.byteLength(body, 'utf8'); assert(bytes > body.length);
    for (const textEncoder of [true, false]) {
      const h = harness({ textEncoder }); h.respond(() => jsonResponse({ ok: true }));
      context(await rejected(h.api.requestJSON(url, payload, { ...detail, maxRequestBytes: bytes - 1 })), { code: 'request_size', reason: bytes + ' > ' + (bytes - 1) + ' bytes' }); assert.equal(h.calls.length, 0);
      assert.deepStrictEqual(plain(await h.api.requestJSON(url, payload, { ...detail, maxRequestBytes: bytes })), { ok: true }); assert.equal(h.calls.length, 1); assert.equal(h.calls[0].init.body, body);
    }
  });
  await check('request diagnostics redact URL origin, user info, query and fragment in both URL parsing paths', async () => {
    for (const urlConstructor of [true, false]) {
      const h = harness({ urlConstructor }), address = 'https://private-user:private-password@example.invalid/api/viewer/prepare?token=never-print#private-fragment';
      h.respond(() => { throw new TypeError('Load failed'); }); const error = await rejected(h.api.requestJSON(address, {}, detail));
      context(error, { code: 'network_error', endpoint: '/api/viewer/prepare' });
      for (const secret of ['private-user', 'private-password', 'example.invalid', 'token=']) assert(!error.message.includes(secret) && !JSON.stringify(error.requestContext).includes(secret));
      assert.strictEqual(h.calls[0].url, address);
    }
  });
  await check('EN, KO and JA localize fixed diagnostic prose while preserving reasons, files and HTTP status', async () => {
    for (const [language, words] of [
      ['en', ['No HTTP response was received', 'The response was not valid JSON', 'The request could not be encoded', 'The request exceeds the data limit', 'The preview exceeds the data limit']],
      ['ko-KR', ['HTTP 응답을 받지 못했습니다', '서버 응답이 올바른 JSON이 아닙니다', '요청 데이터를 만들지 못했습니다', '요청 데이터가 허용 크기를 초과했습니다', '미리보기 데이터가 허용 크기를 초과했습니다']],
      ['ja-JP', ['HTTP応答を受信できませんでした', 'サーバー応答が正しいJSONではありません', 'リクエストデータを作成できませんでした', 'リクエストデータが上限を超えています', 'プレビューデータが上限を超えています']]
    ]) {
      const h = harness({ language }); h.respond(() => { throw new TypeError('Load failed'); }); let error = await rejected(h.api.requestJSON(url, {}, detail)); context(error, { code: 'network_error', reason: words[0] }); assert(error.message.includes('Load failed'));
      h.respond(() => new Response('Invalid preview metadata.', { status: 200 })); error = await rejected(h.api.requestJSON(url, {}, detail)); context(error, { code: 'invalid_json', status: 200, reason: words[1] }); assert(error.message.includes('Invalid preview metadata.'));
      const cycle = {}; cycle.self = cycle; error = await rejected(h.api.requestJSON(url, cycle, detail)); context(error, { code: 'request_encoding_error', reason: words[2] });
      error = await rejected(h.api.requestJSON(url, { label: '가😀' }, { ...detail, maxRequestBytes: 1 })); context(error, { code: 'request_size', reason: words[3] });
      h.respond(() => new Response(new Uint8Array(2))); error = await rejected(h.api.requestBytes(url, { ...detail, maxBytes: 1 })); context(error, { code: 'data_limit', status: 200, method: 'GET', reason: words[4] });
    }
  });
  assert.equal(sha(fs.readFileSync(script)), sourceSha256, 'production helper source remains unchanged during tests');
  const report = { status: 'PASS', script, sourceSha256, checks: checks.length, cases: checks };
  if (process.env.EVIDENCE_DIR) { fs.mkdirSync(process.env.EVIDENCE_DIR, { recursive: true }); fs.writeFileSync(path.join(process.env.EVIDENCE_DIR, 'report.json'), JSON.stringify(report, null, 2) + '\n'); }
  console.log(JSON.stringify(report, null, 2));
}
main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
