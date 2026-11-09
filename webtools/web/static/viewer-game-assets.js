/* Same-origin game costume selection: existing packs -> decrypt -> 3D viewer. */
(function () {
  "use strict";
  function install() {
    var button = document.getElementById("viewer-game-assets"), dialog = document.getElementById("viewer-game-assets-dialog");
    if (!button || !dialog || button.dataset.gameAssetsBound) return;
    button.dataset.gameAssetsBound = "true";
    var generation = 0, request = null, events = null, jobId = null, busy = false, timer = null, choices = [];
    var selectionCallback = null, returnFocus = button;
    var region, character, search, costume, variant, download, status, log, progress, submit, closeButton, cancel;
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
      [region, character, search, costume, variant, download].forEach(function (node) { if (node) node.disabled = value; });
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
    function close() {
      generation += 1; clearTimeout(timer); stopRequest(); finishEvents(); cancelJob();
      if (dialog.open) dialog.close();
      if (returnFocus && returnFocus.focus) returnFocus.focus();
    }
    function variants() {
      var selected = choices.filter(function (choice) { return choice.value === costume.value; })[0];
      fill(variant, selected && selected.variants || [], null, "primary");
      variant.parentNode.hidden = !selected || (selected.variants || []).length < 2;
      submit.disabled = busy || !selected;
    }
    async function loadCatalog(resetCharacter) {
      stopRequest();
      var token = ++generation, controller = new AbortController(); request = controller;
      var currentCharacter = resetCharacter ? "" : character.value;
      var currentCostume = costume.value;
      fill(costume, [], "Choose a costume"); submit.disabled = true; setStatus("Loading costumes…");
      var params = new URLSearchParams({ lang: language(), region: region.value || "", character: currentCharacter, search: search.value.trim() });
      try {
        var response = await fetch("/api/viewer/game/catalog?" + params, { signal: controller.signal });
        var data = await response.json();
        if (token !== generation || !dialog.open) return;
        if (!response.ok || data.error) throw new Error(data.error || "Game assets are unavailable. Start or prepare the server data first.");
        fill(region, data.regions, null, data.region);
        fill(character, data.characters, "Choose a character", currentCharacter);
        choices = Array.isArray(data.costumes) ? data.costumes : [];
        fill(costume, choices, "Choose a costume", currentCostume);
        if (choices.length && !costume.value) costume.value = choices[0].value;
        variants();
        setStatus(choices.length ? "" : search.value.trim() || currentCharacter ? "No costumes found." : "Choose a character");
      } catch (error) {
        if (error.name !== "AbortError" && token === generation) setStatus(error.message || "Game assets are unavailable. Start or prepare the server data first.", true);
      } finally {
        if (token === generation) request = null;
      }
    }
    function build() {
      dialog.replaceChildren();
      var heading = element("h2", { id: "viewer-game-assets-title", text: t("Game assets") });
      closeButton = element("button", { type: "button", text: "×", "aria-label": t("Close") });
      closeButton.addEventListener("click", close);
      var header = element("div", { className: "modal-head" }, [heading, closeButton]);
      region = element("select", { id: "viewer-game-region" });
      character = element("select", { id: "viewer-game-character" });
      search = element("input", { id: "viewer-game-search", type: "search", maxlength: "120", placeholder: t("Search costumes") });
      costume = element("select", { id: "viewer-game-costume" });
      variant = element("select", { id: "viewer-game-variant" });
      fill(region, [{ value: "", label: "Game region" }]);
      fill(character, [], "Choose a character"); fill(costume, [], "Choose a costume");
      var fields = element("div", { className: "viewer-game-assets-fields" }, [label("Game region", region), label("Character", character), label("Search costumes", search), label("Costume", costume), label("Costume variant", variant)]);
      variant.parentNode.hidden = true;
      download = element("input", { id: "viewer-game-download", type: "checkbox" }); download.checked = true;
      var downloadLabel = element("label", { className: "viewer-game-assets-download" }, [download, element("span", { text: t("Download missing assets") })]);
      status = element("p", { id: "viewer-game-assets-status", role: "status", "aria-live": "polite" });
      log = element("pre", { id: "viewer-game-assets-log", hidden: "", "aria-label": t("Console") });
      progress = element("progress", { id: "viewer-game-assets-progress", hidden: "", "aria-label": t("Progress") });
      submit = element("button", { id: "viewer-game-import", type: "button", className: "viewer-primary", text: t("Load model"), disabled: "" });
      cancel = element("button", { type: "button", text: t("Close") });
      submit.addEventListener("click", runImport); cancel.addEventListener("click", close);
      dialog.append(header, fields, downloadLabel,
        element("p", { className: "viewer-render-note", text: t("Uses downloaded game packs first. Missing assets can be downloaded.") }),
        status, progress, log, element("div", { className: "viewer-game-assets-actions" }, [submit, cancel]));
      region.addEventListener("change", function () { loadCatalog(true); });
      character.addEventListener("change", function () { search.value = ""; loadCatalog(false); });
      search.addEventListener("input", function () {
        clearTimeout(timer); costume.value = ""; submit.disabled = true;
        timer = setTimeout(function () { loadCatalog(false); }, 250);
      });
      search.addEventListener("keydown", function (event) { if (event.key === "Enter") { event.preventDefault(); clearTimeout(timer); loadCatalog(false); } });
      costume.addEventListener("change", variants);
    }
    async function runImport() {
      if (busy || !costume.value) return;
      var token = ++generation;
      var importedVariant = variant.value || "primary";
      clearTimeout(timer); stopRequest(); setBusy(true); setStatus("Preparing game assets…"); log.textContent = ""; log.hidden = false; progress.hidden = false; progress.removeAttribute("value");
      try {
        var response = await fetch("/api/viewer/game/import?lang=" + encodeURIComponent(language()), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ region: region.value, suit: costume.value, variant: variant.value || "primary", download: download.checked })
        });
        var data = await response.json();
        if (!response.ok || data.error || !/^[a-f0-9]{12}$/.test(data.job_id || "")) throw new Error(data.error || "The game model could not be loaded.");
        if (token !== generation || !dialog.open) { fetch("/api/jobs/" + data.job_id + "/cancel", { method: "POST" }).catch(function () {}); return; }
        jobId = data.job_id;
        var stream = new EventSource("/api/jobs/" + data.job_id + "/events"), completed = false; events = stream;
        stream.onmessage = async function (message) {
          if (completed || token !== generation || !dialog.open) return;
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
              var callback = selectionCallback;
              selectionCallback = null;
              dialog.close(); if (returnFocus && returnFocus.focus) returnFocus.focus();
              var selectedVariants = /\.zip$/i.test(paths[0]) ? { 0: importedVariant } : null;
              if (callback) await callback(paths, selectedVariants);
              else if (typeof window.openModelViewer === "function") await window.openModelViewer(paths, selectedVariants);
            }
          } catch (error) { completed = true; finishEvents(); cancelJob(); setBusy(false); progress.hidden = true; setStatus(error.message || "The game model could not be loaded.", true); }
        };
        stream.onerror = function () {
          if (token === generation && stream.readyState === EventSource.CLOSED && !completed) {
            completed = true; finishEvents(); cancelJob(); progress.hidden = true; setBusy(false); setStatus("The game model could not be loaded.", true);
          }
        };
      } catch (error) {
        if (token === generation) { progress.hidden = true; setBusy(false); setStatus(error.message || "The game model could not be loaded.", true); }
      }
    }
    function pick(callback) {
      if (dialog.open) return;
      selectionCallback = typeof callback === "function" ? callback : null;
      returnFocus = document.activeElement || button;
      generation += 1; choices = []; busy = false; build(); dialog.showModal(); loadCatalog(false);
    }
    button.addEventListener("click", function () { pick(null); });
    window.ViewerGameAssets = { pick: pick };
    dialog.addEventListener("cancel", function (event) { event.preventDefault(); close(); });
    dialog.addEventListener("keydown", function (event) {
      // A modal owns its keys; the viewer underneath must not consume Escape
      // to close a background popover or act on its Save/Open shortcuts.
      event.stopPropagation();
      if (event.key === "Escape") { event.preventDefault(); close(); }
    });
    dialog.addEventListener("close", function () { generation += 1; clearTimeout(timer); stopRequest(); finishEvents(); cancelJob(); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
}());
