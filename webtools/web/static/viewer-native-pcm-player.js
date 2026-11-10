/* A bounded native Mac PCM transport. The clock is the actual AudioContext processing clock. */
(function (global) {
  "use strict";
  var INPUT_LIMIT = 32 * 1024 * 1024, PCM_LIMIT = 64 * 1024 * 1024, QUEUE_LIMIT = 32;
  var context = null, contextFailure = "", queue = [], busy = null, players = [], retained = 0, reserved = 0, closed = false, resumePending = null;
  var urlPattern = /^\/api\/viewer\/game\/motions\/audio\/[a-f0-9]{32}\.wav$/;
  function abortError() { var error = new Error("Audio request was superseded."); error.name = "AbortError"; return error; }
  function nativeMac() {
    try { var info = global.ElichikaPlatform && global.ElichikaPlatform.info(); return !!(info && info.native === true && info.platform === "macos"); } catch (_) { return false; }
  }
  // HTML preserves pitch for authored non-unit rates; retain that media path.
  function eligible(descriptor) { return nativeMac() && !!(descriptor && Array.isArray(descriptor.tracks) && descriptor.tracks.length === 1 && descriptor.tracks[0].playbackRate === 1 && urlPattern.test(descriptor.tracks[0].url)); }
  function getContext() {
    if (closed) throw abortError();
    if (context) return context;
    var Constructor = global.AudioContext || global.webkitAudioContext;
    if (!Constructor) throw new Error("AudioContext unavailable");
    if (contextFailure) throw new Error(contextFailure);
    try { context = new Constructor(); return context; } catch (error) { contextFailure = error.message || "AudioContext unavailable"; throw error; }
  }
  function resume() {
    var ctx;
    try { ctx = getContext(); } catch (error) { return Promise.reject(error); }
    if (ctx.state === "running") return Promise.resolve();
    if (resumePending) return resumePending;
    var operation;
    try { operation = ctx.resume(); } catch (error) { return Promise.reject(error); }
    resumePending = new Promise(function (resolve, reject) {
      var settled = false, timeout = setTimeout(function () { finish(new Error("Audio context resume timed out")); }, 1500);
      function finish(error) { if (settled) return; settled = true; clearTimeout(timeout); if (error) reject(error); else if (ctx.state !== "running") reject(new Error("Audio context is not running")); else resolve(); }
      Promise.resolve(operation).then(function () { finish(); }, finish);
    });
    var result = resumePending;
    result.then(function () { if (resumePending === result) resumePending = null; }, function () { if (resumePending === result) resumePending = null; });
    return result;
  }
  function emit(player, type) {
    if (player.dead) return;
    (player.listeners[type] || []).slice().forEach(function (handler) { handler.call(player.facade, { type: type, target: player.facade }); });
  }
  function gain(player) { if (player.gain) player.gain.gain.value = player.muted ? 0 : player.volume; }
  function position(player) {
    if (player.html) return player.html.currentTime;
    var value = player.position;
    if (player.source && !player.paused) value += Math.max(0, context.currentTime - player.epoch) * player.rate;
    return player.buffer ? Math.min(player.buffer.duration, value) : value;
  }
  function stopSource(player) {
    var source = player.source; player.source = null; player.generation++;
    if (source) { source.onended = null; try { source.stop(); } catch (_) {} try { source.disconnect(); } catch (_) {} }
  }
  function releaseBuffer(player) {
    if (player.buffer) { retained -= player.bytes; player.buffer = null; player.bytes = 0; }
  }
  function dropJob(player) {
    if (player.job) {
      player.job.stale = true;
      if (player.job.controller) player.job.controller.abort();
      queue = queue.filter(function (job) { return job !== player.job; });
      player.job = null;
    }
  }
  function fallback(player, reason) {
    if (player.dead || player.html) return;
    player.position = position(player); stopSource(player); releaseBuffer(player); dropJob(player);
    player.playToken++; player.paused = true; player.ready = 0; player.loading = "html-media"; player.fallbackReason = String(reason && reason.message || reason || "Native PCM unavailable");
    if (player.gain) { try { player.gain.disconnect(); } catch (_) {} player.gain = null; }
    try {
      var html = player.options.createHTML(); player.html = html;
      html.preload = "auto"; html.volume = player.volume; html.muted = player.muted; html.playbackRate = player.rate;
      ["loadedmetadata", "error", "ended", "playing", "pause", "seeking", "seeked"].forEach(function (type) {
        var handler = function () {
          if (player.dead || player.html !== html) return;
          if (type === "loadedmetadata") { html.playbackRate = player.rate; html.volume = player.volume; html.muted = player.muted; try { html.currentTime = Math.min(player.position, Number.isFinite(html.duration) ? html.duration : player.position); } catch (_) {} }
          emit(player, type);
        };
        html.addEventListener(type, handler); player.htmlListeners.push([type, handler]);
      });
      html.src = player.data.url;
      if (typeof html.load === "function") html.load();
      html.playbackRate = player.rate; html.volume = player.volume; html.muted = player.muted;
    } catch (error) { player.error = error; emit(player, "error"); }
  }
  function validatePCM(bytes, sampleRate) {
    if (bytes.byteLength < 44) throw new Error("Incomplete PCM WAV");
    var view = new DataView(bytes), length = bytes.byteLength;
    function word(offset) { return String.fromCharCode(view.getUint8(offset), view.getUint8(offset + 1), view.getUint8(offset + 2), view.getUint8(offset + 3)); }
    if (word(0) !== "RIFF" || word(8) !== "WAVE" || view.getUint32(4, true) + 8 !== length) throw new Error("Unsupported PCM WAV");
    var format = null, dataBytes = -1;
    for (var offset = 12; offset + 8 <= length;) {
      var type = word(offset), size = view.getUint32(offset + 4, true), start = offset + 8;
      if (size > length - start) throw new Error("Truncated PCM WAV");
      if (type === "fmt ") {
        if (size < 16 || format) throw new Error("Invalid PCM format");
        format = { encoding: view.getUint16(start, true), channels: view.getUint16(start + 2, true), rate: view.getUint32(start + 4, true), byteRate: view.getUint32(start + 8, true), align: view.getUint16(start + 12, true), bits: view.getUint16(start + 14, true) };
      }
      if (type === "data") { if (dataBytes >= 0) throw new Error("Ambiguous PCM data"); dataBytes = size; }
      offset = start + size + (size % 2);
    }
    if (!format || format.encoding !== 1 || format.channels < 1 || format.channels > 8 || format.rate < 8000 || format.rate > 192000 || [8, 16, 24, 32].indexOf(format.bits) < 0 || format.align !== format.channels * format.bits / 8 || format.byteRate !== format.rate * format.align || dataBytes <= 0 || dataBytes % format.align) throw new Error("Unsupported PCM geometry");
    return Math.ceil(dataBytes / format.align * sampleRate / format.rate) * format.channels * 4;
  }
  async function readInput(response, signal) {
    if (!response.ok) throw new Error("PCM fetch failed");
    var declared = Number(response.headers && response.headers.get("content-length"));
    if (declared > INPUT_LIMIT) throw new Error("PCM input exceeds limit");
    if (!response.body || !response.body.getReader) {
      var bytes = await response.arrayBuffer();
      if (signal.aborted) throw abortError();
      if (bytes.byteLength > INPUT_LIMIT) throw new Error("PCM input exceeds limit");
      return bytes;
    }
    var reader = response.body.getReader(), chunks = [], length = 0;
    try {
      while (true) {
        var part = await reader.read();
        if (signal.aborted) throw abortError();
        if (part.done) break;
        length += part.value.byteLength;
        if (length > INPUT_LIMIT) throw new Error("PCM input exceeds limit");
        chunks.push(part.value);
      }
    } catch (error) { try { await reader.cancel(); } catch (_) {} throw error; }
    finally { try { if (typeof reader.releaseLock === "function") reader.releaseLock(); } catch (_) {} }
    var result = new Uint8Array(length), cursor = 0;
    chunks.forEach(function (chunk) { result.set(chunk, cursor); cursor += chunk.byteLength; });
    return result.buffer;
  }
  function pump() {
    if (busy || closed) return;
    var job;
    while (queue.length && !job) { var next = queue.shift(); if (!next.stale && !next.player.dead) job = next; }
    if (!job) return;
    busy = job;
    (async function () {
      var player = job.player, reservation = 0;
      try {
        player.loading = "fetch"; var ctx = getContext();
        job.controller = new AbortController();
        var response = await global.fetch(player.data.url, { credentials: "same-origin", signal: job.controller.signal });
        var bytes = await readInput(response, job.controller.signal);
        if (job.stale || player.dead) throw abortError();
        var estimate = validatePCM(bytes, ctx.sampleRate);
        if (estimate > PCM_LIMIT - retained - reserved) throw new Error("Decoded PCM budget exceeded");
        reservation = estimate; reserved += reservation; player.loading = "decode";
        // The shared lock and reservation survive cancellation of this promise.
        var buffer = await ctx.decodeAudioData(bytes);
        if (job.stale || player.dead || closed) throw abortError();
        var actual = buffer.length * buffer.numberOfChannels * 4;
        if (!Number.isFinite(actual) || actual <= 0 || actual > PCM_LIMIT - retained - (reserved - reservation)) throw new Error("Decoded PCM budget exceeded");
        reserved -= reservation; reservation = 0;
        player.buffer = buffer; player.bytes = actual; retained += actual; player.ready = 4; player.loading = "ready";
        player.position = Math.min(buffer.duration, player.position); player.job = null;
        emit(player, "loadedmetadata");
      } catch (error) {
        if (!job.stale && !player.dead && !closed) fallback(player, error);
      } finally {
        reserved -= reservation;
        if (player.job === job) player.job = null;
        busy = null; pump();
      }
    }());
  }
  function sourceStart(player, target) {
    if (!player.buffer || player.dead || context.state !== "running") throw abortError();
    stopSource(player); player.position = Math.max(0, Math.min(player.buffer.duration, target)); player.ended = false;
    if (player.position >= player.buffer.duration) { player.paused = true; player.ended = true; return; }
    if (!player.gain) { player.gain = context.createGain(); player.gain.connect(context.destination); gain(player); }
    var source = context.createBufferSource(), generation = player.generation;
    source.buffer = player.buffer; source.playbackRate.value = player.rate; source.connect(player.gain);
    player.source = source; player.epoch = context.currentTime; player.paused = false;
    source.onended = function () {
      if (player.dead || player.source !== source || player.generation !== generation) return;
      player.position = player.buffer.duration; player.source = null; player.paused = true; player.ended = true;
      try { source.disconnect(); } catch (_) {} emit(player, "ended");
    };
    try { source.start(0, player.position); player.starts++; } catch (error) { stopSource(player); player.paused = true; throw error; }
    emit(player, "playing");
  }
  function create(data, options) {
    if (!nativeMac() || !data || !urlPattern.test(data.url)) throw new Error("Native PCM input is not eligible");
    var player = { data: data, options: options, listeners: {}, htmlListeners: [], html: null, buffer: null, bytes: 0, gain: null, source: null, job: null, position: 0, epoch: 0, rate: 1, volume: 1, muted: false, ready: 0, paused: true, ended: false, dead: false, playToken: 0, generation: 0, starts: 0, loading: "queued", fallbackReason: "", error: null };
    var facade = player.facade = {
      addEventListener: function (type, handler) { (player.listeners[type] || (player.listeners[type] = [])).push(handler); },
      removeEventListener: function (type, handler) { player.listeners[type] = (player.listeners[type] || []).filter(function (item) { return item !== handler; }); },
      play: async function () {
        if (player.dead) throw abortError();
        if (player.source && !player.paused && context.state === "running") return;
        var token = ++player.playToken;
        if (!player.html) {
          try { await resume(); }
          catch (error) { if (player.dead || token !== player.playToken) throw abortError(); fallback(player, error); throw abortError(); }
        }
        if (player.dead || token !== player.playToken || player.html && player.html.readyState < 2) throw abortError();
        var target = player.options.preStart ? player.options.preStart() : position(player);
        if (!Number.isFinite(target) || target < 0) throw abortError();
        if (player.html) {
          if (player.html.readyState >= 1) player.html.currentTime = Math.min(target, Number.isFinite(player.html.duration) ? player.html.duration : target);
          player.position = target;
          var html = player.html;
          await html.play();
          if (player.dead || token !== player.playToken || player.html !== html) { html.pause(); throw abortError(); }
          return;
        }
        if (player.ready < 2) throw abortError();
        try { sourceStart(player, target); }
        catch (error) { fallback(player, error); throw abortError(); }
      },
      pause: function () {
        if (player.dead) return;
        player.playToken++;
        if (player.html) { player.html.pause(); return; }
        var changed = !player.paused; player.position = position(player); stopSource(player); player.paused = true;
        if (changed) emit(player, "pause");
      },
      dispose: function () {
        if (player.dead) return;
        facade.pause(); player.dead = true; dropJob(player); releaseBuffer(player);
        if (player.gain) { try { player.gain.disconnect(); } catch (_) {} player.gain = null; }
        if (player.html) {
          player.htmlListeners.forEach(function (item) { player.html.removeEventListener(item[0], item[1]); });
          player.html.removeAttribute("src"); player.html.load(); player.html.remove(); player.html = null;
        }
        player.listeners = {}; players = players.filter(function (item) { return item !== player; });
      },
      getState: function () { return { backend: player.html ? "html-media" : "web-audio-pcm", contextState: context ? context.state : "unavailable", loading: player.loading, fallbackReason: player.fallbackReason || null, decodedBytes: player.bytes, sourceGeneration: player.generation, sourceStarts: player.starts, sourceEpoch: player.source ? player.epoch : null, sourceActive: !!player.source, contextTime: context ? context.currentTime : null, sourceRate: player.source ? player.source.playbackRate.value : null, gain: player.gain ? player.gain.gain.value : null, bufferDuration: player.buffer ? player.buffer.duration : null, bufferSampleRate: player.buffer ? player.buffer.sampleRate : null, bufferChannels: player.buffer ? player.buffer.numberOfChannels : null, retainedDecodedBytes: retained, reservedDecodedBytes: reserved }; }
    };
    Object.defineProperties(facade, {
      currentTime: { get: function () { return position(player); }, set: function (value) {
        if (!Number.isFinite(value) || value < 0 || player.dead) return;
        if (player.html) { player.position = value; player.html.currentTime = value; return; }
        player.playToken++; var playing = !player.paused; player.position = Math.min(player.buffer ? player.buffer.duration : Infinity, value);
        player.ended = false;
        if (playing && context.state === "running") { try { sourceStart(player, player.position); } catch (error) { fallback(player, error); } }
        else { stopSource(player); if (playing) player.paused = true; }
      } },
      duration: { get: function () { return player.html ? player.html.duration : player.buffer ? player.buffer.duration : NaN; } },
      readyState: { get: function () { return player.html ? player.html.readyState : player.ready; } },
      paused: { get: function () { return player.html ? player.html.paused : player.paused; } },
      ended: { get: function () { return player.html ? player.html.ended : player.ended; } },
      seeking: { get: function () { return player.html ? player.html.seeking : false; } },
      playbackRate: { get: function () { return player.html ? player.html.playbackRate : player.rate; }, set: function (value) {
        if (!Number.isFinite(value) || value < .05 || value > 8) return;
        if (player.html) { player.rate = value; player.html.playbackRate = value; return; }
        player.position = position(player); player.epoch = context ? context.currentTime : 0; player.rate = value;
        if (player.source) player.source.playbackRate.value = value;
      } },
      volume: { get: function () { return player.volume; }, set: function (value) { if (Number.isFinite(value) && value >= 0 && value <= 1 && value !== player.volume) { player.volume = value; gain(player); if (player.html) player.html.volume = value; } } },
      muted: { get: function () { return player.muted; }, set: function (value) { value = !!value; if (value === player.muted) return; player.muted = value; gain(player); if (player.html) player.html.muted = player.muted; } }
    });
    players.push(player);
    if (queue.length + (busy ? 1 : 0) >= QUEUE_LIMIT) fallback(player, "PCM queue exceeds limit");
    else { var job = { player: player, stale: false, controller: null }; player.job = job; queue.push(job); pump(); }
    return facade;
  }
  function dispose() {
    if (closed) return; closed = true; players.slice().forEach(function (player) { player.facade.dispose(); }); queue = [];
    if (context) { try { var result = context.close(); if (result && result.catch) result.catch(function () {}); } catch (_) {} }
  }
  global.ViewerNativePCM = Object.freeze({ eligible: eligible, create: create, resumeGesture: resume,
    getState: function () { return { contextState: context ? context.state : "unavailable", retainedDecodedBytes: retained, reservedDecodedBytes: reserved, queued: queue.length, decoding: !!busy, players: players.length }; }, dispose: dispose });
  global.addEventListener("pagehide", dispose);
}(window));
