/* Catalog-backed navigation/MV motions and local companion-audio playback. */
(function () {
  "use strict";
  function start() {
    var panel = document.getElementById("viewer-adjustments");
    if (!panel || document.getElementById("viewer-game-motions")) return;
    function t(key) { return typeof window.T === "function" ? window.T(key) : key; }
    function make(tag, props, children) {
      var node = document.createElement(tag);
      Object.keys(props || {}).forEach(function (key) {
        if (key === "text") node.textContent = props[key];
        else if (key === "className") node.className = props[key];
        else node.setAttribute(key, props[key]);
      });
      (children || []).forEach(function (child) { node.appendChild(child); });
      return node;
    }
    function text(tag, key, props) { var node = make(tag, Object.assign({ "data-i18n": key, text: t(key) }, props)); return node; }
    function label(key, control) { return make("label", {}, [text("span", key), control]); }
    function fill(select, options, placeholder, selected) {
      select.replaceChildren();
      if (placeholder) select.appendChild(make("option", { value: "", text: t(placeholder) }));
      (options || []).forEach(function (item) { select.appendChild(make("option", { value: item.value, text: t(item.label) })); });
      if (selected && Array.prototype.some.call(select.options, function (option) { return option.value === selected; })) select.value = selected;
    }
    var button = text("button", "Load game motion", { id: "viewer-game-motions", type: "button" });
    var actions = panel.querySelector(".viewer-motion-import-actions");
    if (!actions) { actions = make("div", { className: "viewer-save-actions viewer-motion-import-actions" }); panel.insertBefore(actions, panel.querySelector(".viewer-motion-row")); }
    actions.appendChild(button);
    var dialog = make("dialog", { id: "viewer-game-motions-dialog", className: "viewer-game-assets-dialog", "aria-labelledby": "viewer-game-motions-title" });
    (document.getElementById("tab-viewer") || document.body).appendChild(dialog);
    var region, character, category, search, motion, performer, songType, linkedAudio, download, status, progress, submit, cancel, previousPage, nextPage, pageInfo, options = [];
    var pageOffset = 0, pageLimit = 200, pageTotal = 0;
    var generation = 0, request = null, stream = null, job = "", timer = 0, busy = false;
    function message(value, error) { status.textContent = t(value); status.classList.toggle("viewer-warning", !!error); }
    function stopRequest() { if (request) request.abort(); request = null; }
    function stopStream() { if (stream) stream.close(); stream = null; }
    function cancelJob() { var id = job; job = ""; if (id) fetch("/api/jobs/" + encodeURIComponent(id) + "/cancel", { method: "POST" }).catch(function () {}); }
    function close() { generation += 1; clearTimeout(timer); stopRequest(); stopStream(); cancelJob(); if (dialog.open) dialog.close(); button.focus(); }
    function setBusy(value) {
      busy = value;
      [region, character, category, search, motion, performer, songType, linkedAudio, download].forEach(function (node) { node.disabled = value; });
      submit.disabled = value || !motion.value;
      cancel.textContent = t(value ? "Cancel" : "Close");
      dialog.setAttribute("aria-busy", String(value));
      previousPage.disabled = value || pageOffset === 0; nextPage.disabled = value || pageOffset + pageLimit >= pageTotal;
    }
    function performers(selected) {
      var keep = performer.value, choices = selected && selected.performers || [];
      fill(performer, choices, null, keep);
      if (!performer.value && choices.length) {
        var preferred = choices.filter(function (entry) { return String(entry.member_id) === character.value; })[0] ||
          choices.filter(function (entry) { return entry.is_center; })[0] || choices[0];
        performer.value = preferred.value;
      }
      performer.parentNode.hidden = category.value !== "mv" || !choices.length;
    }
    function detail() {
      var selected = options.filter(function (item) { return item.value === motion.value; })[0];
      submit.disabled = busy || !selected;
      performers(selected);
      if (!selected) return;
      var parts = [];
      if (selected.start_at && selected.end_at) {
        parts.push(new Date(selected.start_at * 1000).toISOString().slice(0, 10) + " – " + new Date(selected.end_at * 1000).toISOString().slice(0, 10));
      }
      if (selected.suit_id) parts.push(t("Costume") + ": " + selected.suit_id);
      if (selected.music) parts.push(t("Linked music") + ": " + selected.music);
      message(parts.join(" · "));
    }
    async function catalog(resetCharacter, offset) {
      stopRequest();
      var current = resetCharacter ? "" : character.value, chosen = motion.value;
      var token = ++generation, controller = new AbortController(); request = controller;
      submit.disabled = true; message("Loading motions…");
      pageOffset = Number.isInteger(offset) ? offset : 0;
      previousPage.disabled = true; nextPage.disabled = true;
      var query = new URLSearchParams({ lang: document.documentElement.lang || "en", region: region.value || "", character: current, category: category.value || "home", search: search.value.trim(), offset: String(pageOffset), song_type: songType.value || "all" });
      try {
        var response = await fetch("/api/viewer/game/motions/catalog?" + query, { signal: controller.signal });
        var data = await response.json();
        if (token !== generation || !dialog.open) return;
        if (!response.ok || data.error) throw new Error(data.error || "Game motions are unavailable.");
        fill(region, data.regions, null, data.region); fill(character, data.characters, "Choose a character", current);
        fill(category, data.categories, null, category.value || "home");
        songType.parentNode.hidden = category.value !== "mv";
        pageOffset = Number(data.offset) || 0; pageLimit = Number(data.limit) || 200; pageTotal = Number(data.total) || 0;
        previousPage.disabled = pageOffset === 0; nextPage.disabled = !data.more;
        pageInfo.textContent = pageTotal ? (pageOffset + 1) + "–" + Math.min(pageOffset + pageLimit, pageTotal) + " / " + pageTotal : "0 / 0";
        options = Array.isArray(data.motions) ? data.motions : [];
        fill(motion, options, "Choose a motion", chosen);
        if (!motion.value && options.length) motion.value = options[0].value;
        detail();
        if (!options.length) message(current || category.value === "mv" ? "No motions found." : "Choose a character");
        else if (data.more) message("More motions are available on the next page. Search or filter solo songs.");
      } catch (error) {
        if (error.name !== "AbortError" && token === generation) { fill(motion, [], "Choose a motion"); message(error.message || "Game motions are unavailable.", true); }
      } finally { if (token === generation) request = null; }
    }
    async function run() {
      if (busy || !motion.value) return;
      if (!window.ModelViewer || !window.ModelViewer.getState().loaded) { message("Open a model before loading a motion.", true); return; }
      var token = ++generation;
      var importedDescriptor = null;
      var targetState = window.ModelViewer.getState();
      var targetOwners = targetState.faces && targetState.faces.characters || [];
      var targetCharacter = targetOwners.length === 1 ? String(targetOwners[0]) : character.value;
      clearTimeout(timer); stopRequest(); setBusy(true); message("Preparing game motion…"); progress.hidden = false; progress.removeAttribute("value");
      try {
        var response = await fetch("/api/viewer/game/motions/import?lang=" + encodeURIComponent(document.documentElement.lang || "en"), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ region: region.value, character: character.value, category: category.value, motion: motion.value, target_character: targetCharacter, performer: category.value === "mv" ? performer.value : "", audio: linkedAudio.checked, download: download.checked })
        });
        var data = await response.json();
        if (!response.ok || data.error || !/^[a-f0-9]{12}$/.test(data.job_id || "")) throw new Error(data.error || "The game motion could not be loaded.");
        if (token !== generation || !dialog.open) { fetch("/api/jobs/" + data.job_id + "/cancel", { method: "POST" }).catch(function () {}); return; }
        job = data.job_id;
        var events = new EventSource("/api/jobs/" + job + "/events"), complete = false; stream = events;
        events.onmessage = async function (event) {
          if (complete || token !== generation || !dialog.open) return;
          try {
            var item = JSON.parse(event.data);
            if (item.type === "log") message(String(item.line || ""));
            else if (item.type === "motion") importedDescriptor = item.motion;
            else if (item.type === "progress" && item.total > 0) { progress.max = item.total; progress.value = item.done; }
            else if (item.type === "done") {
              complete = true; stopStream(); job = "";
              if (item.status === "cancelled") { setBusy(false); progress.hidden = true; message("Cancelled"); return; }
              if (item.status !== "done") throw new Error(item.summary || "The game motion could not be loaded.");
              if (!Array.isArray(item.output_paths) || !item.output_paths.length || item.output_paths.some(function (path) { return typeof path !== "string" || !path; })) throw new Error("The game motion could not be loaded.");
              if (window.ModelViewer.getState().modelId !== targetState.modelId) throw new Error(t("The model changed while loading this motion. Load the motion again for the current model."));
              message("Adding motion to the model…");
              var previousState = window.ModelViewer.getState();
              var previousClips = previousState.rig && previousState.rig.clipNames || [];
              var alreadyLoaded = item.output_paths.every(function (path) { return previousState.loadedPaths.indexOf(path) >= 0; });
              await window.ModelViewer.addMotion(item.output_paths, { replaceGame: true });
              if (token !== generation) return;
              var composed = null;
              if (importedDescriptor && window.ModelViewer.setMotionTimeline) composed = await window.ModelViewer.setMotionTimeline(importedDescriptor);
              if (token !== generation) return;
              var actualClip = typeof composed === "string" ? composed : composed && composed.clipName;
              if (importedDescriptor && window.ViewerMotionAudio) window.ViewerMotionAudio.load(importedDescriptor.audio,
                { modelId: window.ModelViewer.getState().modelId, clipNames: actualClip ? [actualClip] : [] });
              progress.hidden = true; setBusy(false); close();
              var currentState = window.ModelViewer.getState();
              var compatible = !!actualClip || alreadyLoaded || currentState.rig && currentState.rig.clipNames.some(function (name) { return previousClips.indexOf(name) < 0; });
              var note = document.getElementById("viewer-game-motion-note");
              note.textContent = t(compatible ? "Motion ready. Press Play in Pose / motion." : "No compatible clips were found in this motion.");
              note.classList.toggle("viewer-warning", !compatible);
              if (compatible && importedDescriptor) {
                var warnings = (importedDescriptor.warnings || []).concat(composed && composed.warnings || [], importedDescriptor.audio && importedDescriptor.audio.warnings || []);
                if (warnings.length) note.textContent += " " + warnings.map(t).join(" ");
              }
              panel.open = true;
            }
          } catch (error) { complete = true; stopStream(); cancelJob(); progress.hidden = true; setBusy(false); message(error.message || "The game motion could not be loaded.", true); }
        };
        events.onerror = function () {
          if (!complete && token === generation && events.readyState === EventSource.CLOSED) { complete = true; stopStream(); cancelJob(); setBusy(false); progress.hidden = true; message("The game motion could not be loaded.", true); }
        };
      } catch (error) { if (token === generation) { setBusy(false); progress.hidden = true; message(error.message || "The game motion could not be loaded.", true); } }
    }
    function build() {
      dialog.replaceChildren(); busy = false;
      var exit = text("button", "Close", { type: "button" }); exit.addEventListener("click", close);
      region = make("select", { id: "viewer-motion-region" }); character = make("select", { id: "viewer-motion-character" });
      var selectedRegion = ""; try { selectedRegion = localStorage.getItem("elichika.game-motions.region.v1") || ""; } catch (_) {}
      if (["gl", "jp"].indexOf(selectedRegion) >= 0) fill(region, [{ value: selectedRegion, label: selectedRegion === "jp" ? "Japan (JP)" : "Global (GL)" }], null, selectedRegion);
      category = make("select", { id: "viewer-motion-category" }); fill(category, [{ value: "home", label: "Home and idle motions" }]);
      songType = make("select", { id: "viewer-motion-song-type" }); fill(songType, [{ value: "all", label: "All songs" }, { value: "solo", label: "Solo songs" }, { value: "group", label: "Group songs" }], null, "all");
      performer = make("select", { id: "viewer-motion-performer" });
      motion = make("select", { id: "viewer-game-motion-choice" });
      search = make("input", { id: "viewer-motion-search", type: "search", maxlength: "120" });
      download = make("input", { id: "viewer-motion-download", type: "checkbox" }); download.checked = true;
      linkedAudio = make("input", { id: "viewer-motion-linked-audio", type: "checkbox" }); linkedAudio.checked = true;
      status = make("p", { role: "status", "aria-live": "polite", id: "viewer-game-motion-status" });
      progress = make("progress", { hidden: "", "aria-label": t("Progress") });
      submit = text("button", "Load motion", { id: "viewer-motion-import", type: "button", disabled: "", className: "viewer-primary" });
      cancel = text("button", "Close", { type: "button" }); cancel.addEventListener("click", close); submit.addEventListener("click", run);
      previousPage = text("button", "Previous page", { id: "viewer-motion-page-previous", type: "button", disabled: "" });
      nextPage = text("button", "Next page", { id: "viewer-motion-page-next", type: "button", disabled: "" });
      pageInfo = make("output", { id: "viewer-motion-page-info", "aria-live": "polite" });
      previousPage.addEventListener("click", function () { catalog(false, Math.max(0, pageOffset - pageLimit)); });
      nextPage.addEventListener("click", function () { catalog(false, pageOffset + pageLimit); });
      dialog.append(make("div", { className: "modal-head" }, [text("h2", "Game motions", { id: "viewer-game-motions-title" }), exit]),
        make("div", { className: "viewer-game-assets-fields" }, [label("Game region", region), label("Character", character), label("Motion category", category), label("Song type", songType), label("Search motions", search), label("Motion", motion), label("Original dance performer", performer)]),
        make("div", { className: "viewer-game-assets-actions" }, [previousPage, pageInfo, nextPage]),
        make("label", { className: "viewer-game-assets-download" }, [download, text("span", "Download missing assets")]),
        make("label", { className: "viewer-game-assets-download" }, [linkedAudio, text("span", "Load linked game voice or music")]),
        text("p", "Choose the original dance performer. Body, mouth and eye motion load together.", { className: "viewer-render-note" }),
        status, progress, make("div", { className: "viewer-game-assets-actions" }, [submit, cancel]));
      region.addEventListener("change", function () { try { localStorage.setItem("elichika.game-motions.region.v1", region.value); } catch (_) {} catalog(true); });
      character.addEventListener("change", function () { search.value = ""; catalog(false); });
      category.addEventListener("change", function () { search.value = ""; catalog(false); });
      songType.addEventListener("change", function () { catalog(false); });
      search.addEventListener("input", function () { submit.disabled = true; clearTimeout(timer); timer = setTimeout(function () { catalog(false); }, 250); });
      motion.addEventListener("change", detail);
    }
    button.addEventListener("click", function () { if (!dialog.open) { build(); dialog.showModal(); catalog(false); } });
    dialog.addEventListener("cancel", function (event) { event.preventDefault(); close(); });
    dialog.addEventListener("close", function () { generation += 1; clearTimeout(timer); stopRequest(); stopStream(); cancelJob(); });
    dialog.addEventListener("keydown", function (event) { event.stopPropagation(); if (event.key === "Escape") { event.preventDefault(); close(); } });
    panel.appendChild(make("p", { id: "viewer-game-motion-note", className: "viewer-render-note", role: "status" }));

    window.ViewerGameMotions = { getAudioState: function () {
      return window.ViewerMotionAudio ? window.ViewerMotionAudio.getState() : { enabled: false, loaded: false, paused: true, time: 0 };
    } };

  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
}());
