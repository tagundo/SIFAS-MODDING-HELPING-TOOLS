/* OS integration only. Model preparation, editing and saving stay in the shared UI. */
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
  var actions = { openFiles: "openFiles", chooseDirectory: "chooseDirectory", reveal: "reveal", setFullscreen: "fullscreen", setLanguage: "setLanguage", setViewerPanelWidth: "setViewerPanelWidth", setViewerFilesWidth: "setViewerFilesWidth" };
  function validPanelWidth(width) { return typeof width === "number" && isFinite(width) && Math.floor(width) === width && (width === 0 || width >= 240 && width <= 640); }
  function validFilesWidth(width) { return typeof width === "number" && isFinite(width) && Math.floor(width) === width && (width === 0 || width >= 160 && width <= 360); }
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
    if (["openModel", "saveModel", "showViewer"].indexOf(action) < 0 || !native || unloading) return false;
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
      language: native && ["en", "ko", "ja"].indexOf(description.language) >= 0 ? description.language : "",
      viewerPanelWidth: native && validPanelWidth(description.viewerPanelWidth) ? description.viewerPanelWidth : 0,
      viewerFilesWidth: native && validFilesWidth(description.viewerFilesWidth) ? description.viewerFilesWidth : 0 };
  }
  global.ElichikaPlatform = Object.freeze({ supports: supports, request: request, receive: receive,
    perform: perform, bind: bind, info: info, chosenPaths: chosenPaths });
  if (native) document.documentElement.classList.add("elichika-desktop", "elichika-macos");

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
