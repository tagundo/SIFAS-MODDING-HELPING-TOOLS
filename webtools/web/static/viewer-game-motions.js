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
    var region, character, category, search, motion, download, status, progress, submit, cancel, options = [];
    var generation = 0, request = null, stream = null, job = "", timer = 0, busy = false;
    function message(value, error) { status.textContent = t(value); status.classList.toggle("viewer-warning", !!error); }
    function stopRequest() { if (request) request.abort(); request = null; }
    function stopStream() { if (stream) stream.close(); stream = null; }
    function cancelJob() { var id = job; job = ""; if (id) fetch("/api/jobs/" + encodeURIComponent(id) + "/cancel", { method: "POST" }).catch(function () {}); }
    function close() { generation += 1; clearTimeout(timer); stopRequest(); stopStream(); cancelJob(); if (dialog.open) dialog.close(); button.focus(); }
    function setBusy(value) {
      busy = value;
      [region, character, category, search, motion, download].forEach(function (node) { node.disabled = value; });
      submit.disabled = value || !motion.value;
      cancel.textContent = t(value ? "Cancel" : "Close");
      dialog.setAttribute("aria-busy", String(value));
    }
    function detail() {
      var selected = options.filter(function (item) { return item.value === motion.value; })[0];
      submit.disabled = busy || !selected;
      if (!selected) return;
      var parts = [];
      if (selected.start_at && selected.end_at) {
        parts.push(new Date(selected.start_at * 1000).toISOString().slice(0, 10) + " – " + new Date(selected.end_at * 1000).toISOString().slice(0, 10));
      }
      if (selected.suit_id) parts.push(t("Costume") + ": " + selected.suit_id);
      if (selected.music) parts.push(t("Linked music") + ": " + selected.music);
      message(parts.join(" · "));
    }
    async function catalog(resetCharacter) {
      stopRequest();
      var current = resetCharacter ? "" : character.value, chosen = motion.value;
      var token = ++generation, controller = new AbortController(); request = controller;
      submit.disabled = true; message("Loading motions…");
      var query = new URLSearchParams({ lang: document.documentElement.lang || "en", region: region.value || "", character: current, category: category.value || "home", search: search.value.trim() });
      try {
        var response = await fetch("/api/viewer/game/motions/catalog?" + query, { signal: controller.signal });
        var data = await response.json();
        if (token !== generation || !dialog.open) return;
        if (!response.ok || data.error) throw new Error(data.error || "Game motions are unavailable.");
        fill(region, data.regions, null, data.region); fill(character, data.characters, "Choose a character", current);
        fill(category, data.categories, null, category.value || "home");
        options = Array.isArray(data.motions) ? data.motions : [];
        fill(motion, options, "Choose a motion", chosen);
        if (!motion.value && options.length) motion.value = options[0].value;
        detail();
        if (!options.length) message(current || category.value === "mv" ? "No motions found." : "Choose a character");
        else if (data.more) message("Showing the first 200 motions. Search to narrow the list.");
      } catch (error) {
        if (error.name !== "AbortError" && token === generation) { fill(motion, [], "Choose a motion"); message(error.message || "Game motions are unavailable.", true); }
      } finally { if (token === generation) request = null; }
    }
    async function run() {
      if (busy || !motion.value) return;
      if (!window.ModelViewer || !window.ModelViewer.getState().loaded) { message("Open a model before loading a motion.", true); return; }
      var token = ++generation;
      clearTimeout(timer); stopRequest(); setBusy(true); message("Preparing game motion…"); progress.hidden = false; progress.removeAttribute("value");
      try {
        var response = await fetch("/api/viewer/game/motions/import?lang=" + encodeURIComponent(document.documentElement.lang || "en"), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ region: region.value, character: character.value, category: category.value, motion: motion.value, download: download.checked })
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
            else if (item.type === "progress" && item.total > 0) { progress.max = item.total; progress.value = item.done; }
            else if (item.type === "done") {
              complete = true; stopStream(); job = "";
              if (item.status === "cancelled") { setBusy(false); progress.hidden = true; message("Cancelled"); return; }
              if (item.status !== "done") throw new Error(item.summary || "The game motion could not be loaded.");
              if (!Array.isArray(item.output_paths) || !item.output_paths.length || item.output_paths.some(function (path) { return typeof path !== "string" || !path; })) throw new Error("The game motion could not be loaded.");
              message("Adding motion to the model…");
              var previousState = window.ModelViewer.getState();
              var previousClips = previousState.rig && previousState.rig.clipNames || [];
              var alreadyLoaded = item.output_paths.every(function (path) { return previousState.loadedPaths.indexOf(path) >= 0; });
              await window.ModelViewer.addMotion(item.output_paths);
              if (token !== generation) return;
              progress.hidden = true; setBusy(false); close();
              var currentState = window.ModelViewer.getState();
              var compatible = alreadyLoaded || currentState.rig && currentState.rig.clipNames.some(function (name) { return previousClips.indexOf(name) < 0; });
              var note = document.getElementById("viewer-game-motion-note");
              note.textContent = t(compatible ? "Motion loaded. Choose a clip in Pose / motion." : "No compatible clips were found in this motion.");
              note.classList.toggle("viewer-warning", !compatible);
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
      category = make("select", { id: "viewer-motion-category" }); fill(category, [{ value: "home", label: "Home and idle motions" }]);
      motion = make("select", { id: "viewer-game-motion-choice" });
      search = make("input", { id: "viewer-motion-search", type: "search", maxlength: "120" });
      download = make("input", { id: "viewer-motion-download", type: "checkbox" }); download.checked = true;
      status = make("p", { role: "status", "aria-live": "polite", id: "viewer-game-motion-status" });
      progress = make("progress", { hidden: "", "aria-label": t("Progress") });
      submit = text("button", "Load motion", { id: "viewer-motion-import", type: "button", disabled: "", className: "viewer-primary" });
      cancel = text("button", "Close", { type: "button" }); cancel.addEventListener("click", close); submit.addEventListener("click", run);
      dialog.append(make("div", { className: "modal-head" }, [text("h2", "Game motions", { id: "viewer-game-motions-title" }), exit]),
        make("div", { className: "viewer-game-assets-fields" }, [label("Game region", region), label("Character", character), label("Motion category", category), label("Search motions", search), label("Motion", motion)]),
        make("label", { className: "viewer-game-assets-download" }, [download, text("span", "Download missing assets")]),
        text("p", "MV files can contain several performers. Select the desired clip after loading.", { className: "viewer-render-note" }),
        status, progress, make("div", { className: "viewer-game-assets-actions" }, [submit, cancel]));
      region.addEventListener("change", function () { catalog(true); });
      character.addEventListener("change", function () { search.value = ""; catalog(false); });
      category.addEventListener("change", function () { search.value = ""; catalog(false); });
      search.addEventListener("input", function () { submit.disabled = true; clearTimeout(timer); timer = setTimeout(function () { catalog(false); }, 250); });
      motion.addEventListener("change", detail);
    }
    button.addEventListener("click", function () { if (!dialog.open) { build(); dialog.showModal(); catalog(false); } });
    dialog.addEventListener("cancel", function (event) { event.preventDefault(); close(); });
    dialog.addEventListener("close", function () { generation += 1; clearTimeout(timer); stopRequest(); stopStream(); cancelJob(); });
    dialog.addEventListener("keydown", function (event) { event.stopPropagation(); if (event.key === "Escape") { event.preventDefault(); close(); } });
    panel.appendChild(make("p", { id: "viewer-game-motion-note", className: "viewer-render-note", role: "status" }));

    var audio = document.createElement("audio"), audioUrl = "", tick = 0, blocked = false;
    var audioEnabled = make("input", { id: "viewer-motion-audio-enabled", type: "checkbox" });
    var audioFile = make("input", { id: "viewer-motion-audio-file", type: "file", accept: "audio/*,.wav,.mp3,.ogg,.m4a,.flac" });
    var audioStatus = make("p", { id: "viewer-motion-audio-status", className: "viewer-render-note", role: "status" });
    var audioBox = make("details", { className: "viewer-save-advanced" }, [text("summary", "Accompanying voice or music"),
      make("label", {}, [audioEnabled, text("span", "Play audio with motion")]), label("Choose accompanying audio", audioFile),
      text("p", "Choose a converted voice or music file. Game ACB/AWB audio must be converted first.", { className: "viewer-render-note" }), audioStatus]);
    panel.appendChild(audioBox);
    function syncAudio() {
      if (!audioUrl || !audioEnabled.checked || document.hidden || !window.ModelViewer) { audio.pause(); return; }
      var state = window.ModelViewer.getMotionState ? window.ModelViewer.getMotionState() : window.ModelViewer.getState(), rig = state.rig;
      if (!state.visible || state.loading || state.contextLost || state.layout && state.layout.minimized || !rig || !rig.selectedClip) { audio.pause(); return; }
      var time = Math.max(0, Number(rig.time) || 0);
      if (Number.isFinite(audio.duration) && time >= audio.duration) { audio.pause(); return; }
      if (Math.abs(audio.currentTime - time) > 0.25) { try { audio.currentTime = time; } catch (_) {} }
      if (rig.playing && audio.paused && !blocked) {
        var promise = audio.play();
        if (promise && promise.catch) promise.catch(function () { blocked = true; audioStatus.textContent = t("Press Play to allow accompanying audio."); });
      } else if (!rig.playing) audio.pause();
    }
    function armAudio() { clearInterval(tick); tick = 0; if (audioUrl && audioEnabled.checked) { syncAudio(); tick = setInterval(syncAudio, 200); } else audio.pause(); }
    audioFile.addEventListener("change", function () {
      audio.pause(); if (audioUrl) URL.revokeObjectURL(audioUrl); audioUrl = ""; audio.removeAttribute("src");
      var file = audioFile.files && audioFile.files[0];
      if (file && file.size > 64 * 1024 * 1024) { audioStatus.textContent = t("Choose an audio file smaller than 64 MB."); armAudio(); return; }
      if (file) { audioUrl = URL.createObjectURL(file); audio.src = audioUrl; audio.preload = "metadata"; audioEnabled.checked = true; blocked = false; audioStatus.textContent = file.name; }
      else audioStatus.textContent = "";
      armAudio();
    });
    audioEnabled.addEventListener("change", function () { blocked = false; armAudio(); });
    audio.addEventListener("error", function () { blocked = true; audioStatus.textContent = t("This audio format could not be played. Choose WAV, MP3 or OGG."); });
    audio.addEventListener("loadedmetadata", syncAudio);
    document.addEventListener("visibilitychange", syncAudio);
    document.addEventListener("click", function (event) { if (event.target.closest && event.target.closest("#viewer-play")) { blocked = false; setTimeout(syncAudio, 0); } });
    window.addEventListener("pagehide", function () { clearInterval(tick); audio.pause(); if (audioUrl) URL.revokeObjectURL(audioUrl); });
    window.ViewerGameMotions = { getAudioState: function () { return { enabled: audioEnabled.checked, loaded: !!audioUrl, paused: audio.paused, time: audio.currentTime, blocked: blocked }; } };
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
}());
