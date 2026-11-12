/* Native OS integration and request diagnostics for the shared editing UI. */
(function (global) {
  "use strict";
  var pending = Object.create(null), sequence = 0, bindings = null, queued = [];
  var viewerFullscreen = false, unloading = false;
  var description = global.ElichikaDesktop;
  var handler = global.webkit && global.webkit.messageHandlers && global.webkit.messageHandlers.elichika;
  var topFrame = false;
  try { topFrame = global.top === global.self; } catch (_) { /* Never expose a subframe adapter. */ }
  var native = !!(topFrame && description && description.platform === "macos" && description.version === 1 &&
    handler && typeof handler.postMessage === "function" && global.location.protocol === "http:" &&
    ["127.0.0.1", "localhost"].indexOf(global.location.hostname) >= 0);
  var capabilities = native && Array.isArray(description.capabilities) ? description.capabilities.slice(0, 12) : [];
  var actions = { openFiles: "openFiles", chooseDirectory: "chooseDirectory", reveal: "reveal", setFullscreen: "fullscreen", setLanguage: "setLanguage", setViewerPanelWidth: "setViewerPanelWidth", setViewerFilesWidth: "setViewerFilesWidth", setPanelSettings: "setPanelSettings", setEditorSurface: "editorNavigation", setSection: "setSection" };
  function validPanelWidth(width) { return typeof width === "number" && isFinite(width) && Math.floor(width) === width && (width === 0 || width >= 240 && width <= 16384); }
  function validFilesWidth(width) { return typeof width === "number" && isFinite(width) && Math.floor(width) === width && (width === 0 || width >= 160 && width <= 360); }
  function validPanelSettings(value) {
    return !!value && !Array.isArray(value) && Object.keys(value).sort().join(",") === "hidden,order" &&
      [value.hidden, value.order].every(function (items) {
        return Array.isArray(items) && items.length <= 256 && items.every(function (id, index) {
          return typeof id === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(id) && items.indexOf(id) === index;
        });
      });
  }
  function notify(error) {
    if (unloading) return;
    var message = String(error.message || error);
    global.alert(typeof global.T === "function" ? global.T(message) : message);
  }

  function supports(capability) { return native && !unloading && capabilities.indexOf(capability) >= 0; }
  function validPath(path) { return typeof path === "string" && path[0] === "/" && path.length <= 8192 && path.indexOf("\0") < 0; }
  function chosenPaths(result) {
    if (result && result.cancelled === true) return [];
    if (!result || !Array.isArray(result.paths) || result.paths.length > 128 || !result.paths.every(validPath)) {
      throw new Error("The file selection response is invalid.");
    }
    return result.paths.filter(function (path, index, list) { return list.indexOf(path) === index; });
  }
  function receive(message) {
    if (!message || typeof message.id !== "string" || !Object.prototype.hasOwnProperty.call(pending, message.id)) return false;
    var record = pending[message.id]; delete pending[message.id]; global.clearTimeout(record.timer);
    if (message.error) {
      var text = typeof message.error === "string" ? message.error : message.error.message;
      record.reject(new Error(typeof text === "string" ? text.slice(0, 2048) : "The native request failed."));
    } else record.resolve(message.result);
    return true;
  }
  function request(action, args) {
    if (!Object.prototype.hasOwnProperty.call(actions, action) || !supports(actions[action])) {
      return Promise.reject(new Error("This action is unavailable in this window."));
    }
    if (Object.keys(pending).length >= 8) return Promise.reject(new Error("Finish the current native action first."));
    args = args || {};
    var message = { id: "elichika-" + (++sequence), action: action };
    if (action === "openFiles") {
      message.multiple = args.multiple === true;
      message.extensions = Array.isArray(args.extensions) ? args.extensions.filter(function (value) {
        return typeof value === "string" && /^[a-zA-Z0-9_-]{1,32}$/.test(value);
      }).slice(0, 32) : [];
    }
    if (action === "openFiles" || action === "chooseDirectory") message.title = String(args.title || "").slice(0, 160);
    if (action === "reveal") {
      if (!validPath(args.path)) return Promise.reject(new Error("Choose a saved file to reveal."));
      message.path = args.path;
    }
    if (action === "setFullscreen") message.enabled = args.enabled === true;
    if (action === "setLanguage") {
      if (["en", "ko", "ja"].indexOf(args.language) < 0) return Promise.reject(new Error("Choose a supported language."));
      message.language = args.language;
    }
    if (action === "setViewerPanelWidth") {
      if (!validPanelWidth(args.width)) return Promise.reject(new Error("The panel width is invalid."));
      message.width = args.width;
    }
    if (action === "setViewerFilesWidth") {
      if (!validFilesWidth(args.width)) return Promise.reject(new Error("The panel width is invalid."));
      message.width = args.width;
    }
    if (action === "setEditorSurface") {
      if (["tools", "viewer"].indexOf(args.editorSurface) < 0) return Promise.reject(new Error("Choose a valid editor view."));
      message.editorSurface = args.editorSurface;
    }
    if (action === "setPanelSettings") {
      if (["viewer", "tools", "content"].indexOf(args.panelScope) < 0 || !validPanelSettings(args.panelSettings)) {
        return Promise.reject(new Error("The panel settings are invalid."));
      }
      message.panelScope = args.panelScope;
      message.panelSettings = JSON.parse(JSON.stringify(args.panelSettings));
    }
    if (action === "setSection") {
      if (["tools", "viewer"].indexOf(args.section) < 0 ||
          args.event !== undefined && ["ready", "change"].indexOf(args.event) < 0) {
        return Promise.reject(new Error("Choose an available app section."));
      }
      message.section = args.section;
      message.event = args.event || "change";
    }
    return new Promise(function (resolve, reject) {
      var timer = global.setTimeout(function () {
        delete pending[message.id]; reject(new Error("The native action did not finish. Try again."));
      }, action === "openFiles" || action === "chooseDirectory" ? 300000 : 30000);
      pending[message.id] = { resolve: resolve, reject: reject, timer: timer };
      try { handler.postMessage(message); }
      catch (error) { receive({ id: message.id, error: String(error.message || error) }); }
    });
  }
  function perform(action, args) {
    if (["openModel", "saveModel", "showViewer", "showTools"].indexOf(action) < 0 || !native || unloading) return false;
    if (!bindings) { if (queued.length < 8) queued.push({ action: action, args: args }); return true; }
    if (typeof bindings[action] !== "function") return false;
    try {
      Promise.resolve(bindings[action](args || {})).catch(notify);
      return true;
    } catch (error) { notify(error); return false; }
  }
  function bind(handlers) {
    bindings = handlers;
    var waiting = queued; queued = [];
    waiting.forEach(function (command) { perform(command.action, command.args); });
  }
  function info() {
    return { platform: native ? "macos" : "browser", native: native,
      editorNavigation: supports("editorNavigation"),
      editorSurface: native && ["tools", "viewer"].indexOf(description.editorSurface) >= 0 ? description.editorSurface : "tools",
      language: native && ["en", "ko", "ja"].indexOf(description.language) >= 0 ? description.language : "",
      viewerPanelWidth: native && validPanelWidth(description.viewerPanelWidth) ? description.viewerPanelWidth : 0,
      viewerFilesWidth: native && validFilesWidth(description.viewerFilesWidth) ? description.viewerFilesWidth : 0 };
  }
  var REQUEST_TEXT = {
    "No HTTP response was received": ["HTTP 응답을 받지 못했습니다", "HTTP応答を受信できませんでした"],
    "The response body could not be read": ["응답 데이터를 읽지 못했습니다", "応答データを読み取れませんでした"],
    "The response was not valid JSON": ["서버 응답이 올바른 JSON이 아닙니다", "サーバー応答が正しいJSONではありません"],
    "The request could not be encoded": ["요청 데이터를 만들지 못했습니다", "リクエストデータを作成できませんでした"],
    "The request exceeds the data limit": ["요청 데이터가 허용 크기를 초과했습니다", "リクエストデータが上限を超えています"],
    "The request failed": ["요청이 실패했습니다", "リクエストに失敗しました"],
    "The preview exceeds the data limit": ["미리보기 데이터가 허용 크기를 초과했습니다", "プレビューデータが上限を超えています"]
  };
  function requestText(key) {
    var language = global.document && document.documentElement && document.documentElement.lang || "en";
    var index = language.split("-")[0] === "ko" ? 0 : language.split("-")[0] === "ja" ? 1 : -1;
    return index >= 0 && REQUEST_TEXT[key] ? REQUEST_TEXT[key][index] : key;
  }
  function endpoint(url) {
    try { return new global.URL(url, global.location.href).pathname; }
    catch (_) { return String(url || "").split(/[?#]/)[0].replace(/^https?:\/\/[^/]+/, "").slice(0, 512); }
  }
  function requestError(error, options, details) {
    if (error && (error.name === "AbortError" || error.viewerStale || error.requestContext)) return error;
    options = options || {}; details = details || {};
    var reason = details.reason || error && error.message || String(error || requestText("The request failed"));
    var context = { operation: options.operation || "", stage: options.stage || "", filename: options.filename || "",
      method: details.method || "GET", url: endpoint(details.url), status: details.status || 0, code: details.code || "request_failed" };
    var prefix = [context.operation, context.stage, context.filename].filter(Boolean).join(" · ");
    var location = [context.status ? "HTTP " + context.status : "", context.method + " " + context.url].filter(Boolean).join(" · ");
    var wrapped = new Error((prefix ? prefix + ": " : "") + reason + (location ? " [" + location + "]" : ""));
    wrapped.requestContext = context;
    if (error) wrapped.cause = error;
    return wrapped;
  }
  function cancelled(error, options) { return error && error.name === "AbortError" || options.signal && options.signal.aborted; }
  function responseReason(data, text, response) {
    var value = data && data.error;
    if (value && typeof value === "object") value = value.message || value.detail;
    return typeof value === "string" && value ? value : text && text.trim() ? text.trim().slice(0, 2000) : response.statusText || requestText("The request failed");
  }
  async function requestResponse(url, init, options) {
    try { return await global.fetch(url, init); }
    catch (error) {
      if (cancelled(error, options)) throw error;
      throw requestError(error, options, { method: init.method || "GET", url: url, code: "network_error",
        reason: requestText("No HTTP response was received") + (error && error.message ? " (" + error.message + ")" : "") });
    }
  }
  async function responseText(response, url, method, options) {
    try { return await response.text(); }
    catch (error) {
      if (cancelled(error, options)) throw error;
      throw requestError(error, options, { method: method, url: url, status: response.status, code: "response_read_error",
        reason: requestText("The response body could not be read") + (error && error.message ? " (" + error.message + ")" : "") });
    }
  }
  async function requestJSON(url, payload, options) {
    options = options || {};
    var method = options.method || (payload === undefined ? "GET" : "POST"), init = { method: method, signal: options.signal };
    if (payload !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      try { init.body = JSON.stringify(payload); }
      catch (error) { throw requestError(error, options, { method: method, url: url, code: "request_encoding_error",
        reason: requestText("The request could not be encoded") + ": " + error.message }); }
      if (options.maxRequestBytes > 0) {
        var size = typeof global.TextEncoder === "function" ? new global.TextEncoder().encode(init.body).byteLength : unescape(encodeURIComponent(init.body)).length;
        if (size > options.maxRequestBytes) throw requestError(null, options, { method: method, url: url, code: "request_size",
          reason: requestText("The request exceeds the data limit") + ": " + size + " > " + options.maxRequestBytes + " bytes" });
      }
    }
    var response = await requestResponse(url, init, options), text = await responseText(response, url, method, options), data;
    try { data = JSON.parse(text); }
    catch (error) {
      throw requestError(error, options, { method: method, url: url, status: response.status,
        code: response.ok ? "invalid_json" : "http_error",
        reason: response.ok ? requestText("The response was not valid JSON") + (text.trim() ? ": " + text.trim().slice(0, 500) : "") : responseReason(null, text, response) });
    }
    if (!response.ok || data && data.error) throw requestError(null, options, { method: method, url: url, status: response.status,
      code: data && data.error_code || "http_error", reason: responseReason(data, text, response) });
    return data;
  }
  async function requestBytes(url, options) {
    options = options || {};
    var limit = options.maxBytes > 0 ? options.maxBytes : 64 * 1024 * 1024;
    var response = await requestResponse(url, { signal: options.signal, method: "GET" }, options);
    if (!response.ok) {
      var text = await responseText(response, url, "GET", options), data;
      try { data = JSON.parse(text); } catch (_) {}
      throw requestError(null, options, { method: "GET", url: url, status: response.status, code: data && data.error_code || "http_error",
        reason: responseReason(data, text, response) });
    }
    var length = Number(response.headers.get("Content-Length"));
    if (length > limit) {
      if (response.body && response.body.cancel) response.body.cancel().catch(function () {});
      throw requestError(null, options, { method: "GET", url: url, status: response.status, code: "data_limit",
        reason: requestText("The preview exceeds the data limit") + ": " + length + " > " + limit + " bytes" });
    }
    var bytes;
    try { bytes = await response.arrayBuffer(); }
    catch (error) {
      if (cancelled(error, options)) throw error;
      throw requestError(error, options, { method: "GET", url: url, status: response.status, code: "response_read_error",
        reason: requestText("The response body could not be read") + ": " + error.message });
    }
    if (bytes.byteLength > limit) throw requestError(null, options, { method: "GET", url: url, status: response.status, code: "data_limit",
      reason: requestText("The preview exceeds the data limit") + ": " + bytes.byteLength + " > " + limit + " bytes" });
    return bytes;
  }
  global.ElichikaPlatform = Object.freeze({ supports: supports, request: request, receive: receive,
    perform: perform, bind: bind, info: info, chosenPaths: chosenPaths,
    requestJSON: requestJSON, requestBytes: requestBytes, requestError: requestError });
  if (native) document.documentElement.classList.add("elichika-desktop", "elichika-macos");
  if (supports("editorNavigation")) document.documentElement.classList.add("elichika-native-editor-navigation");

  if (supports("fullscreen") && !global.ElichikaViewerFullscreen) {
    global.ElichikaViewerFullscreen = { postMessage: function (command) {
      if (command !== "enter" && command !== "exit") return;
      var enter = command === "enter";
      viewerFullscreen = enter;
      request("setFullscreen", { enabled: enter }).catch(function () {
        global.dispatchEvent(new CustomEvent("elichika-native-fullscreen", { detail: { active: false, settled: true } }));
        viewerFullscreen = false;
      });
    } };
    global.addEventListener("elichika-native-fullscreen-changed", function (event) {
      var detail = event.detail;
      if (!viewerFullscreen || !detail || typeof detail.active !== "boolean") return;
      global.dispatchEvent(new CustomEvent("elichika-native-fullscreen", { detail: detail }));
      if (!detail.active && detail.settled !== false) viewerFullscreen = false;
    });
  }
  global.addEventListener("pagehide", function () {
    unloading = true;
    Object.keys(pending).forEach(function (id) { receive({ id: id, error: "This window was closed." }); });
    queued = []; bindings = null;
  });
})(window);
