/* Shared same-origin costume picker: viewer scenes or one native transplant body. */
(function () {
  "use strict";
  function install() {
    var button = document.getElementById("viewer-game-assets"), dialog = document.getElementById("viewer-game-assets-dialog");
    if (!dialog || window.GameAssetPicker) return;
    if (button) button.dataset.gameAssetsBound = "true";
    var generation = 0, request = null, events = null, jobId = null, busy = false, timer = null, choices = [];
    var consumer = null;
    var preferredRegion = "";
    try { preferredRegion = localStorage.getItem("elichika.game-assets.region.v1") || ""; } catch (_) {}
    if (["gl", "jp"].indexOf(preferredRegion) < 0) preferredRegion = "";
    var region, platform, character, search, costume, variant, download, status, log, progress, submit, closeButton, cancel;
    function t(value) { return typeof window.T === "function" ? window.T(value) : value; }
    function language() { return document.documentElement.lang || "en"; }
    function element(tag, attributes, children) {
      var node = document.createElement(tag);
      Object.keys(attributes || {}).forEach(function (key) {
        if (key === "text") node.textContent = attributes[key];
        else if (key === "className") node.className = attributes[key];
        else node.setAttribute(key, attributes[key]);
      });
      (children || []).forEach(function (child) { node.appendChild(child); });
      return node;
    }
    function label(text, control) { return element("label", {}, [element("span", { text: t(text) }), control]); }
    function fill(select, options, placeholder, selected) {
      select.replaceChildren();
      if (placeholder) select.appendChild(element("option", { value: "", text: t(placeholder) }));
      (options || []).forEach(function (option) { select.appendChild(element("option", { value: option.value, text: t(option.label) })); });
      if (selected && Array.prototype.some.call(select.options, function (option) { return option.value === selected; })) select.value = selected;
    }
    function setBusy(value) {
      busy = value;
      [region, platform, character, search, costume, variant, download].forEach(function (node) { if (node) node.disabled = value; });
      submit.disabled = value || !costume.value;
      cancel.textContent = t(value ? "Cancel" : "Close");
      dialog.setAttribute("aria-busy", String(value));
    }
    function setStatus(value, error) { status.textContent = t(value); status.classList.toggle("viewer-warning", !!error); }
    function stopRequest() { if (request) request.abort(); request = null; }
    function finishEvents() { if (events) events.close(); events = null; }
    function cancelJob() {
      var id = jobId; jobId = null;
      if (id) fetch("/api/jobs/" + encodeURIComponent(id) + "/cancel", { method: "POST" }).catch(function () {});
    }
    function current(selection) {
      if (!selection || consumer !== selection || !dialog.open || selection.language !== language()) return false;
      try { return selection.isCurrent() === true; } catch (_) { return false; }
    }
    function restoreFocus(selection) {
      var trigger = selection && selection.trigger;
      if (trigger && trigger.isConnected && !trigger.disabled && trigger.getClientRects().length) trigger.focus();
    }
    function close(options) {
      var previous = consumer; consumer = null;
      generation += 1; clearTimeout(timer); stopRequest(); finishEvents(); cancelJob();
      if (dialog.open) dialog.close();
      if (!options || options.restoreFocus !== false) restoreFocus(previous);
    }
    function invalidate() {
      if (consumer && !current(consumer)) close({ restoreFocus: false });
    }
    function variants() {
      var selected = choices.filter(function (choice) { return choice.value === costume.value; })[0];
      fill(variant, selected && selected.variants || [], null, "primary");
      variant.parentNode.hidden = !selected || (selected.variants || []).length < 2;
      submit.disabled = busy || !selected;
    }
    async function loadCatalog(resetCharacter) {
      stopRequest();
      var token = ++generation, controller = new AbortController(), selection = consumer; request = controller;
      var currentCharacter = resetCharacter ? "" : character.value;
      var currentCostume = costume.value;
      fill(costume, [], "Choose a costume"); submit.disabled = true; setStatus("Loading costumes…");
      var defaultRegion = language().split("-")[0] === "ja" ? "jp" : "gl";
      var params = new URLSearchParams({ lang: language(), region: preferredRegion || defaultRegion, character: currentCharacter, search: search.value.trim() });
      try {
        var response = await fetch("/api/viewer/game/catalog?" + params, { signal: controller.signal });
        var data = await response.json();
        if (token !== generation || consumer !== selection) return;
        if (!current(selection)) { invalidate(); return; }
        if (!response.ok || data.error) throw new Error(data.error || "Game assets are unavailable. Start or prepare the server data first.");
        fill(region, data.regions, null, data.region);
        fill(character, data.characters, "Choose a character", currentCharacter);
        choices = Array.isArray(data.costumes) ? data.costumes : [];
        fill(costume, choices, "Choose a costume", currentCostume);
        if (choices.length && !costume.value) costume.value = choices[0].value;
        variants();
        setStatus(choices.length ? "" : search.value.trim() || currentCharacter ? "No costumes found." : "Choose a character");
      } catch (error) {
        if (error.name !== "AbortError" && token === generation && current(selection)) setStatus(error.message || "Game assets are unavailable. Start or prepare the server data first.", true);
      } finally {
        if (token === generation) request = null;
      }
    }
    function build() {
      dialog.replaceChildren();
      var heading = element("h2", { id: "viewer-game-assets-title", text: t("Game assets") + (consumer.label ? " · " + consumer.label : "") });
      closeButton = element("button", { type: "button", text: "×", "aria-label": t("Close") });
      closeButton.addEventListener("click", close);
      var header = element("div", { className: "modal-head" }, [heading, closeButton]);
      region = element("select", { id: "viewer-game-region" });
      character = element("select", { id: "viewer-game-character" });
      search = element("input", { id: "viewer-game-search", type: "search", maxlength: "120", placeholder: t("Search costumes") });
      costume = element("select", { id: "viewer-game-costume" });
      variant = element("select", { id: "viewer-game-variant" });
      fill(region, preferredRegion ? [{ value: preferredRegion, label: preferredRegion === "jp" ? "Japan (JP)" : "Global (GL)" }] : [{ value: "", label: "Game region" }]);
      fill(character, [], "Choose a character"); fill(costume, [], "Choose a costume");
      var fields = element("div", { className: "viewer-game-assets-fields" }, [label("Game region", region), label("Character", character), label("Search costumes", search), label("Costume", costume), label("Costume variant", variant)]);
      variant.parentNode.hidden = true;
      platform = null;
      if (consumer.purpose === "transplant") {
        platform = element("select", { id: "viewer-game-platform" });
        fill(platform, [{ value: "android", label: "Android" }, { value: "ios", label: "iOS" }], null, consumer.platform);
        fields.insertBefore(label("Bundle platform", platform), character.parentNode);
      }
      download = element("input", { id: "viewer-game-download", type: "checkbox" }); download.checked = true;
      var downloadLabel = element("label", { className: "viewer-game-assets-download" }, [download, element("span", { text: t("Download missing assets") })]);
      status = element("p", { id: "viewer-game-assets-status", role: "status", "aria-live": "polite" });
      log = element("pre", { id: "viewer-game-assets-log", hidden: "", "aria-label": t("Console") });
      progress = element("progress", { id: "viewer-game-assets-progress", hidden: "", "aria-label": t("Progress") });
      submit = element("button", { id: "viewer-game-import", type: "button", className: "viewer-primary", text: t(consumer.purpose === "transplant" ? "Use this model" : "Load model"), disabled: "" });
      cancel = element("button", { type: "button", text: t("Close") });
      submit.addEventListener("click", runImport); cancel.addEventListener("click", close);
      var purposeHint = element("p", { className: "viewer-render-note", text: t("Fills this model field with one body bundle. Your 3D preview stays open as it is.") });
      purposeHint.hidden = consumer.purpose !== "transplant";
      dialog.append(header, fields, downloadLabel,
        element("p", { className: "viewer-render-note", text: t("Uses downloaded game packs first. Missing assets can be downloaded.") }),
        purposeHint,
        status, progress, log, element("div", { className: "viewer-game-assets-actions" }, [submit, cancel]));
      region.addEventListener("change", function () {
        preferredRegion = region.value;
        try { localStorage.setItem("elichika.game-assets.region.v1", preferredRegion); } catch (_) {}
        loadCatalog(true);
      });
      character.addEventListener("change", function () { search.value = ""; loadCatalog(false); });
      search.addEventListener("input", function () {
        clearTimeout(timer); costume.value = ""; submit.disabled = true;
        timer = setTimeout(function () { loadCatalog(false); }, 250);
      });
      search.addEventListener("keydown", function (event) { if (event.key === "Enter") { event.preventDefault(); clearTimeout(timer); loadCatalog(false); } });
      costume.addEventListener("change", variants);
    }
    async function runImport() {
      var selection = consumer;
      if (busy || !costume.value) return;
      if (!current(selection)) { invalidate(); return; }
      var token = ++generation;
      var importedVariant = variant.value || "primary";
      var importedPlatform = platform ? platform.value : null;
      if (selection.purpose === "transplant" && ["android", "ios"].indexOf(importedPlatform) < 0) return;
      var payload = { region: region.value, suit: costume.value, variant: importedVariant, download: download.checked };
      if (selection.purpose === "transplant") { payload.purpose = "transplant"; payload.platform = importedPlatform; }
      clearTimeout(timer); stopRequest(); setBusy(true); setStatus("Preparing game assets…"); log.textContent = ""; log.hidden = false; progress.hidden = false; progress.removeAttribute("value");
      try {
        var response = await fetch("/api/viewer/game/import?lang=" + encodeURIComponent(language()), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        var data = await response.json();
        if (!response.ok || data.error || !/^[a-f0-9]{12}$/.test(data.job_id || "")) throw new Error(data.error || "The game model could not be loaded.");
        if (token !== generation || !current(selection)) {
          fetch("/api/jobs/" + data.job_id + "/cancel", { method: "POST" }).catch(function () {});
          if (consumer === selection) invalidate();
          return;
        }
        jobId = data.job_id;
        var stream = new EventSource("/api/jobs/" + data.job_id + "/events"), completed = false; events = stream;
        stream.onmessage = async function (message) {
          if (completed || token !== generation || consumer !== selection) return;
          if (!current(selection)) { invalidate(); return; }
          try {
            var item = JSON.parse(message.data);
            if (item.type === "log") {
              log.textContent = (log.textContent + String(item.line || "") + "\n").slice(-16000); log.scrollTop = log.scrollHeight;
            } else if (item.type === "progress" && item.total > 0) {
              progress.max = item.total; progress.value = item.done;
            } else if (item.type === "done") {
              completed = true; finishEvents(); jobId = null; progress.hidden = true; setBusy(false);
              if (item.status === "cancelled") { setStatus("Cancelled"); return; }
              if (item.status !== "done") throw new Error(item.summary || "The game model could not be loaded.");
              var paths = item.output_paths;
              if (!Array.isArray(paths) || paths.length !== 1 || typeof paths[0] !== "string" || !paths[0]) throw new Error("The game model could not be loaded.");
              if (selection.purpose === "transplant" && (!/\.unity$/i.test(paths[0]) || paths[0].charAt(0) !== "/" || paths[0].indexOf("\0") >= 0 || paths[0].length > 8192)) throw new Error("The selected game asset is not a body bundle.");
              var result = selection.onSelect(paths[0], { variant: importedVariant, platform: importedPlatform });
              close();
              if (result && typeof result.then === "function") await result;
            }
          } catch (error) {
            completed = true;
            if (token !== generation || consumer !== selection) return;
            finishEvents(); cancelJob(); setBusy(false); progress.hidden = true;
            setStatus(error.message || "The game model could not be loaded.", true);
          }
        };
        stream.onerror = function () {
          if (token === generation && consumer === selection && !current(selection)) { invalidate(); return; }
          if (token === generation && current(selection) && stream.readyState === EventSource.CLOSED && !completed) {
            completed = true; finishEvents(); cancelJob(); progress.hidden = true; setBusy(false); setStatus("The game model could not be loaded.", true);
          }
        };
      } catch (error) {
        if (token === generation && current(selection)) { progress.hidden = true; setBusy(false); setStatus(error.message || "The game model could not be loaded.", true); }
      }
    }
    function open(options) {
      options = options || {};
      var purpose = options.purpose || "viewer";
      if (dialog.open || ["viewer", "transplant"].indexOf(purpose) < 0 || typeof options.onSelect !== "function" || typeof options.isCurrent !== "function") return false;
      try { if (options.isCurrent() !== true) return false; } catch (_) { return false; }
      consumer = { purpose: purpose, trigger: options.trigger, label: String(options.label || ""),
        platform: options.platform === "ios" ? "ios" : "android", language: language(),
        onSelect: options.onSelect, isCurrent: options.isCurrent };
      generation += 1; choices = []; busy = false; build(); dialog.showModal(); loadCatalog(false);
      return true;
    }
    window.GameAssetPicker = Object.freeze({ open: open, close: close, invalidate: invalidate });
    // Existing viewer transplant panels use a callback with scene ZIP variants.
    // Keep that interface on the same guarded picker used by native body forms.
    window.ViewerGameAssets = Object.freeze({ pick: function (callback) {
      var trigger = document.activeElement || button;
      var originalModel = window.ModelViewer && window.ModelViewer.getState().modelId;
      return open({ trigger: trigger, purpose: "viewer", isCurrent: function () {
        return document.getElementById("tab-viewer").classList.contains("active") &&
          (!originalModel || window.ModelViewer && window.ModelViewer.getState().modelId === originalModel);
      }, onSelect: function (path, info) {
        var variants = /\.zip$/i.test(path) ? { 0: info.variant } : null;
        if (typeof callback === "function") return callback([path], variants);
        if (typeof window.openModelViewer === "function") return window.openModelViewer([path], variants);
      } });
    } });

    if (button) button.addEventListener("click", function () {
      open({ trigger: button, purpose: "viewer", isCurrent: function () {
        return document.getElementById("tab-viewer").classList.contains("active");
      }, onSelect: function (path, info) {
        if (typeof window.openModelViewer === "function") return window.openModelViewer([path], /\.zip$/i.test(path) ? { 0: info.variant } : null);
      } });
    });
    dialog.addEventListener("cancel", function (event) { event.preventDefault(); close(); });
    dialog.addEventListener("keydown", function (event) {
      // A modal owns its keys; the viewer underneath must not consume Escape
      // to close a background popover or act on its Save/Open shortcuts.
      event.stopPropagation();
      if (event.key === "Escape") { event.preventDefault(); close(); }
    });
    dialog.addEventListener("close", function () {
      // A queued close event from the previous use must not cancel a newer
      // consumer which has already reopened the same shared dialog.
      if (!dialog.open) close({ restoreFocus: false });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
}());
