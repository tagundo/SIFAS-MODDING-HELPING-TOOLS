/* A separate MV editing session in the shared native asset page. */
(function (global) {
  "use strict";

  const route = "/api/mv-studio/";
  const panelKeys = ["assets", "performers", "soundtrack", "tracks", "events", "quality", "registration", "warnings"];
  const panelNames = ["MV assets", "Performers", "Soundtrack", "Tracks", "Selected event", "MV quality settings", "Register in game", "Import notes"];
  const assetKinds = [
    ["stage", "Stage"], ["background", "Background"], ["outfit", "Performer outfit"],
    ["props", "Props"], ["effect", "Effects"], ["audio", "Soundtrack"], ["other", "Other asset"],
  ];
  const kinds = {
    camera: "Camera", dance: "Dance", mouth: "Mouth", eyes: "Eyes", gaze: "Gaze", cheek: "Cheek",
    sound: "Sound", lighting: "Lighting", display: "Display", bloom: "Bloom", dof: "Depth of field",
    effects: "Effects", stage: "Stage", props: "Props", crowd: "Crowd", split: "Split screen", other: "Other",
  };
  const eventLabels = { fov: "Field of view (FOV)", position: "Position", rotation: "Rotation",
    keyframes: "Keyframes", intensity: "Light intensity", m_Intensity: "Light intensity", paramName: "Parameter name",
    timeScale: "Playback speed", clipIn: "Clip offset (s)", preExtrapolationMode: "Before clip", postExtrapolationMode: "After clip" };
  const eventRanges = {
    fov: [.01, 179.99], clipIn: [0, 3600], timeScale: [.000001, 100], easeIn: [0, 3600], easeOut: [0, 3600],
    blendIn: [-1, 3600], blendOut: [-1, 3600], preExtrapolationTime: [0, 3600], postExtrapolationTime: [0, 3600],
    weight: [0, 1], weightForDirection: [0, 1],
  };
  const byId = (id) => document.getElementById(id);
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const text = (value) => String(value == null ? "" : value);
  const finite = Number.isFinite;
  const basename = (path) => text(path).split(/[\\/]/).pop();
  let settings, scene, project, selected, pending, gameImport, catalogRequest, catalogIndex = [], songs = [];
  let visible = false, playing = false, time = 0, frame = 0, lastFrame = 0, pixelsPerSecond = 1;
  let previewLoading = false, playheadNode, seekInput, timeOutput, lastReadout = -Infinity;
  let hidden = [], trackKind = "", assetKind = "stage", performerId = "", resizeObserver, refreshTimelineHeight;
  let registered = null, registrationTitle = "", chartTemplates = [], chartTemplate = "", chartPath = "";
  let registrationTimelines = {}, registrationAudio = {}, latestNativeTimeline = null;
  const timelineLanes = new Map();
  const audio = document.createElement("audio");
  audio.preload = "metadata";

  function t(label) { return settings.translate(label); }

  function make(tag, label, attrs = {}) {
    const element = document.createElement(tag);
    if (label != null) element.textContent = label;
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
    return element;
  }

  function button(label, action, attrs) {
    const control = make("button", label, { type: "button", ...attrs });
    control.addEventListener("click", action);
    return control;
  }

  function replaceOptions(select, options, selectedValue, placeholder) {
    select.replaceChildren();
    if (placeholder) select.append(new Option(placeholder, ""));
    for (const item of options) {
      const value = text(typeof item === "object" ? item.id ?? item.value : item);
      if (!value) continue;
      const option = new Option(t(typeof item === "object" ? item.label || value : value), value);
      option.disabled = typeof item === "object" && item.available === false;
      select.append(option);
    }
    if ([...select.options].some((option) => !option.disabled && option.value === text(selectedValue))) select.value = text(selectedValue);
  }

  function formatTime(seconds) {
    const centiseconds = Math.max(0, Math.round(seconds * 100));
    const minutes = Math.floor(centiseconds / 6000);
    const remainder = centiseconds % 6000;
    return `${minutes}:${String(Math.floor(remainder / 100)).padStart(2, "0")}.${String(remainder % 100).padStart(2, "0")}`;
  }

  function report(label, error = false) {
    const status = byId("mv-status");
    status.textContent = label;
    status.hidden = !label;
    status.classList.toggle("mv-error", error);
  }

  function showError(error) {
    if (error && error.name !== "AbortError") report(t(error.message || "The MV could not be loaded."), true);
  }

  function requestURL(path) {
    const delimiter = path.includes("?") ? "&" : "?";
    return route + path + delimiter + "lang=" + encodeURIComponent(settings.language());
  }

  async function request(path, payload, signal) {
    const url = requestURL(path);
    if (global.ElichikaPlatform && ElichikaPlatform.requestJSON) {
      return ElichikaPlatform.requestJSON(url, payload, { signal, maxRequestBytes: 16 * 1024 * 1024, operation: "3D MV" });
    }
    const response = await fetch(url, payload === undefined ? { signal } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal,
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "The MV request failed.");
    return data;
  }

  async function requestGameStream(payload, signal, onStage) {
    if (typeof global.TextDecoder !== "function" || typeof global.ReadableStream !== "function" ||
        typeof global.ReadableStream.prototype.getReader !== "function" ||
        typeof global.Response !== "function" || !("body" in global.Response.prototype)) return null;
    const response = await global.fetch(requestURL("game-stream"), {
      method: "POST", credentials: "same-origin", signal,
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify(payload),
    });
    if ([404, 405, 501].includes(response.status)) {
      response.body?.cancel?.().catch(() => {});
      return null;
    }
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(data && typeof data.error === "string" && data.error || "The MV request failed.");
    }

    const invalid = () => new Error("The imported MV project is invalid.");
    if (!/^application\/x-ndjson(?:\s*;|$)/i.test(response.headers.get("Content-Type") || "") ||
        !response.body || typeof response.body.getReader !== "function") {
      response.body?.cancel?.().catch(() => {});
      throw invalid();
    }
    const reader = response.body.getReader(), decoder = new global.TextDecoder("utf-8", { fatal: true });
    let buffer = "", received = 0, stageSeen = false, terminal = null, ended = false;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) {
          ended = true;
          buffer += decoder.decode();
          break;
        }
        received += value.byteLength;
        if (received > 64 * 1024 * 1024) throw invalid();
        buffer += decoder.decode(value, { stream: true });
        for (let newline; (newline = buffer.indexOf("\n")) !== -1;) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (!line) continue;
          if (terminal) throw invalid();
          let event;
          try { event = JSON.parse(line); } catch (_) { throw invalid(); }
          if (event?.type === "stage" && !stageSeen) {
            const preview = event.preview;
            if (!preview || !Array.isArray(preview.assets) || !Array.isArray(preview.tracks) ||
                !finite(preview.duration) || preview.duration < 0) throw invalid();
            stageSeen = true;
            onStage(preview);
          } else if (event?.type === "complete") {
            terminal = { project: checkedProject(event.project) };
          } else if (event?.type === "error" && typeof event.error === "string" && event.error) {
            terminal = { error: event.error };
          } else throw invalid();
        }
      }
      if (!terminal || buffer.trim()) throw invalid();
      if (terminal.error) throw new Error(terminal.error);
      return terminal.project;
    } finally {
      if (!ended) reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  function resource(path) {
    if (typeof path !== "string" || !path.startsWith("/api/")) return "";
    const resolved = new URL(path, global.location.origin);
    return resolved.origin === global.location.origin ? resolved.href : "";
  }

  function syncPosition(now) {
    if (playheadNode) playheadNode.style.transform = `translateX(${time * pixelsPerSecond}px)`;
    if (now !== undefined && now - lastReadout < 100) return;
    lastReadout = now ?? performance.now();
    seekInput.value = time;
    const label = formatTime(time) + " / " + formatTime(project ? project.duration : 0);
    if (timeOutput.textContent !== label) timeOutput.textContent = label;
  }

  function audioOffset() {
    const offset = project && project.soundtrack && project.soundtrack.offset;
    return finite(offset) ? offset : 0;
  }

  function seek(seconds, changeAudio = true, deferDraw = false) {
    time = clamp(finite(seconds) ? seconds : 0, 0, project ? project.duration : 0);
    if (changeAudio && audio.hasAttribute("src")) audio.currentTime = Math.max(0, time + audioOffset());
    if (scene && project) scene.seek(time, project, deferDraw);
    syncPosition();
  }

  function updatePlayButton() {
    const control = byId("mv-play");
    control.textContent = t(playing ? "Pause" : "Play");
    control.setAttribute("aria-pressed", String(playing));
    const empty = !project || !project.duration;
    control.disabled = empty || previewLoading || !!gameImport;
    byId("mv-rewind").disabled = empty || !!gameImport;
    seekInput.disabled = empty || !!gameImport;
    seekInput.max = project ? project.duration : 0;
  }

  function pause() {
    const wasPlaying = playing;
    playing = false;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    audio.pause();
    if (wasPlaying) {
      scene?.setPlaying?.(false);
      seek(time, false);
    }
    updatePlayButton();
  }

  function tick(now) {
    if (!visible || !playing || !project) return;
    const position = audio.src && !audio.paused && !audio.ended ? audio.currentTime - audioOffset() : time + (now - lastFrame) / 1000;
    lastFrame = now;
    time = clamp(finite(position) ? position : time, 0, project.duration);
    if (scene) scene.playbackFrame(time, now);
    syncPosition(now);
    if (time >= project.duration) pause();
    else frame = requestAnimationFrame(tick);
  }

  function togglePlayback() {
    if (playing) return pause();
    if (!project || !project.duration || !visible || previewLoading || gameImport) return;
    if (time >= project.duration) seek(0);
    playing = true;
    lastFrame = performance.now();
    scene?.setPlaying?.(true);
    if (audio.src) audio.play().catch(() => {
      if (playing) report(t("Soundtrack playback is unavailable. The timeline is still playing."), true);
    });
    updatePlayButton();
    frame = requestAnimationFrame(tick);
  }

  function availablePanels() {
    return panelKeys.filter((key) => {
      if (key === "registration") return gameSource() !== null;
      if (key === "warnings") return project && project.warnings && project.warnings.length;
      return true;
    });
  }

  function applyPanels() {
    const active = availablePanels();
    for (const key of panelKeys) byId("mv-" + key).hidden = !active.includes(key) || hidden.includes(key);
    const allHidden = active.every((key) => hidden.includes(key));
    byId("mv-inspector").hidden = allHidden;
    byId("mv-workspace").classList.toggle("mv-hide-inspector", allHidden);
    if (visible && scene) scene.resize();
  }

  function renderPanelMenu() {
    const menu = byId("mv-panel-options");
    menu.replaceChildren();
    for (const key of availablePanels()) {
      const check = make("input", null, { type: "checkbox", "data-mv-panel-option": key });
      check.checked = !hidden.includes(key);
      const label = make("label");
      label.append(check, make("span", t(panelNames[panelKeys.indexOf(key)])));
      check.addEventListener("change", () => {
        hidden = hidden.filter((id) => id !== key);
        if (!check.checked) hidden.push(key);
        try { localStorage.setItem("elichika.mv.panels.v1", JSON.stringify(hidden)); } catch (_) {}
        applyPanels();
      });
      menu.append(label);
    }
    applyPanels();
  }

  function field(label, value) {
    const row = make("label", null, { class: "mv-field" });
    row.append(make("span", t(label)), value);
    return row;
  }

  function renderAssets() {
    const box = byId("mv-asset-list");
    box.replaceChildren();
    if (!project) { box.append(make("p", t("No MV is open."))); return; }
    const list = make("ul", null, { class: "mv-asset-list" });
    for (const asset of project.assets || []) {
      const item = make("li", text(asset.label || basename(asset.path) || asset.id), { title: text(asset.path) });
      item.append(make("small", [kinds[asset.kind] || assetKinds.find((entry) => entry[0] === asset.kind)?.[1] || asset.kind, asset.status]
        .filter(Boolean).map(t).join(" · ")));
      list.append(item);
    }
    if (list.childElementCount) box.append(list);
    const choice = make("select", null, { id: "mv-asset-kind" });
    replaceOptions(choice, assetKinds.map(([id, label]) => ({ id, label })), assetKind);
    choice.addEventListener("change", () => { assetKind = choice.value; });
    const add = button(t("Import MV asset"), () => importAsset(assetKind), { id: "mv-add-asset" });
    add.disabled = !!pending;
    box.append(field("Asset type", choice), add);
  }

  function renderPerformers() {
    const box = byId("mv-performer-fields"), performers = project && project.performers || [];
    box.replaceChildren();
    if (!performers.length) { box.append(make("p", t("No performers are loaded."))); return; }
    const control = make("select", null, { id: "mv-performer" });
    replaceOptions(control, performers, performerId);
    performerId = control.value;
    const actor = performers.find((item) => text(item.id) === performerId);
    if (!actor) return;
    control.addEventListener("change", () => { performerId = control.value; renderPerformers(); });
    box.append(field("Performer", control));
    const position = actor.transform && actor.transform.position || [0, 0, 0];
    for (const [axis, label] of ["X", "Y", "Z"].entries()) {
      const value = finite(position[axis]) ? position[axis] : 0;
      box.append(field(label, numberInput(value, { min: -1000, max: 1000, "data-mv-performer-axis": label }, (next) => {
        position[axis] = next;
        actor.transform = { ...actor.transform, position };
        seek(time, false);
      })));
    }
    const change = button(t("Replace outfit"), () => importAsset("outfit", actor.id), { id: "mv-replace-outfit" });
    change.disabled = !!pending;
    box.append(change);
  }

  function renderSoundtrack() {
    const box = byId("mv-soundtrack-fields"), soundtrack = project && project.soundtrack;
    box.replaceChildren();
    if (!project) { box.append(make("p", t("No MV is open."))); return; }
    if (soundtrack && soundtrack.url) box.append(field("Soundtrack offset (s)", numberInput(audioOffset(), {
      min: 0, max: 3600, id: "mv-soundtrack-offset",
    }, (next) => { soundtrack.offset = next; seek(time); })));
    const change = button(t("Import soundtrack"), () => importAsset("audio"), { id: "mv-import-soundtrack" });
    change.disabled = !!pending;
    box.append(change);
  }

  function renderTracks() {
    const box = byId("mv-track-controls");
    box.replaceChildren();
    if (!project || !project.tracks.length) { box.append(make("p", t("No timeline events."))); return; }
    const filter = make("select", null, { id: "mv-track-kind" });
    const present = [...new Set(project.tracks.map((track) => text(track.kind)))];
    replaceOptions(filter, present.map((id) => ({ id, label: kinds[id] || id })), trackKind, t("All tracks"));
    filter.addEventListener("change", () => { trackKind = filter.value; renderTimeline(); });
    box.append(field("Track type", filter));
  }

  function activeEvent() {
    if (!selected || !project) return null;
    const track = project.tracks.find((item) => item.id === selected.track);
    const event = track && track.events.find((item) => item.id === selected.event);
    return event ? { track, event } : null;
  }

  function numberInput(value, options, update) {
    const control = make("input", null, { type: "number", step: "any", ...options });
    control.value = value;
    control.addEventListener("change", () => {
      if (control.value !== "" && finite(control.valueAsNumber)) {
        const min = control.hasAttribute("min") ? Number(control.min) : -Infinity;
        const max = control.hasAttribute("max") ? Number(control.max) : Infinity;
        value = clamp(control.valueAsNumber, min, max);
        update(value);
      }
      control.value = value;
    });
    return control;
  }

  function checkInput(value, attrs, update) {
    const control = make("input", null, { type: "checkbox", ...attrs });
    control.checked = Boolean(value);
    control.addEventListener("change", () => update(control.checked));
    return control;
  }

  function eventField(object, key, path, editable, depth = 0) {
    const value = object[key];
    const title = eventLabels[key] || String(key);
    const data = { "data-mv-field": path };
    const update = (next) => { object[key] = next; seek(time, false); };
    if (key === "time" && path.startsWith("keyframes.")) editable = false;
    if (editable && finite(value)) {
      if (key === "preExtrapolationMode" || key === "postExtrapolationMode") {
        const control = make("select", null, data);
        replaceOptions(control, ["None", "Hold", "Loop", "Ping-pong", "Continue"].map((label, id) => ({ id, label })), value);
        control.addEventListener("change", () => update(Number(control.value)));
        return field(title, control);
      }
      const range = eventRanges[key];
      const bounds = range ? { min: range[0], max: range[1] } : {};
      return field(title, numberInput(value, { ...data, ...bounds }, update));
    }
    if (editable && typeof value === "boolean") return field(title, checkInput(value, data, update));
    if (editable && key === "paramName" && typeof value === "string") {
      const control = make("input", null, { type: "text", maxlength: 120, ...data });
      control.value = value;
      control.addEventListener("change", () => update(control.value));
      return field(title, control);
    }
    if (value && typeof value === "object" && depth < 4 && Object.keys(value).length) {
      const group = make("fieldset");
      group.append(make("legend", t(title)));
      if (Array.isArray(value) && value.length && value[0] && typeof value[0] === "object") {
        const body = make("div"), row = (index) => body.replaceChildren(eventField(value, index - 1, path + "." + (index - 1), editable, depth + 1));
        const cursor = numberInput(1, { min: 1, max: value.length, step: 1, "aria-label": t("Entry number") }, (index) => row(Math.round(index)));
        group.append(field("Entry number", cursor), body);
        row(1);
      } else for (const key of Object.keys(value).slice(0, 48)) group.append(eventField(value, key, path + "." + key, editable, depth + 1));
      return group;
    }
    return field(title, make("output", typeof value === "object" ? JSON.stringify(value).slice(0, 240) : text(value)));
  }

  function renderEvent() {
    const box = byId("mv-event-fields");
    box.replaceChildren();
    const active = activeEvent();
    if (!active) { box.append(make("p", t("Select an event in the timeline."))); return; }
    const { track, event } = active;
    const editable = track.editable !== false && event.editable !== false;
    const start = text(event.start), duration = text(event.duration);
    box.append(make("strong", text(event.label || track.label)));
    if (editable) {
      const startControl = numberInput(event.start, { "data-mv-field": "start", min: 0, max: project.duration - event.duration }, (value) => {
        event.start = value;
        refreshTimelineLane(track);
        seek(value);
        renderEvent();
      });
      const durationControl = numberInput(event.duration, { "data-mv-field": "duration", min: 0, max: project.duration - event.start }, (value) => {
        event.duration = value;
        refreshTimelineLane(track);
        seek(time, false);
        renderEvent();
      });
      box.append(field("Start time (s)", startControl), field("Duration (s)", durationControl));
    } else box.append(field("Start time (s)", make("output", start)), field("Duration (s)", make("output", duration)));
    const values = event.values || {};
    for (const key of Object.keys(values).slice(0, 48)) {
      const writable = editable && (!Array.isArray(event.editableValues) || event.editableValues.includes(key));
      box.append(eventField(values, key, key, writable));
    }
  }

  function renderQuality() {
    const box = byId("mv-quality-fields");
    box.replaceChildren();
    const quality = project && project.quality;
    if (!quality || !quality.options || !quality.options.length) { box.append(make("p", t("No MV quality settings were imported."))); return; }
    const modes = quality.modes || [];
    const select = make("select", null, { id: "mv-quality-mode" });
    replaceOptions(select, modes, quality.mode);
    select.addEventListener("change", () => {
      const mode = modes.find((candidate) => text(candidate.id) === select.value);
      if (!mode) return;
      quality.mode = mode.id;
      quality.values = { ...quality.values, ...copy(mode.values || {}) };
      renderQuality(); seek(time, false);
      if (scene) scene.resize();
    });
    if (modes.length) box.append(field("Quality preset", select));
    const mode = modes.find((candidate) => text(candidate.id) === select.value && candidate.description);
    if (mode) box.append(make("p", t(mode.description)));
    const values = quality.values || (quality.values = {});
    for (const option of quality.options) {
      const key = option.key, value = values[key];
      const data = { "data-mv-quality": key };
      const update = (next) => {
        values[key] = next;
        seek(time, false);
        if (key === "rendering_resolution" && scene) scene.resize();
      };
      if (option.type === "boolean" || option.type === "checkbox") box.append(field(option.label || key, checkInput(value, data, update)));
      else if (option.type === "number" && finite(value)) box.append(field(option.label || key, numberInput(value, data, update)));
      else if (value != null) box.append(field(option.label || key, make("output", text(value))));
    }
  }

  function gameSource() {
    const source = project && project.source;
    return source && source.kind === "game" && Number.isSafeInteger(source.liveId) ? source : null;
  }

  function renderRegistration() {
    const box = byId("mv-registration-fields"), source = gameSource();
    box.replaceChildren();
    if (!source) return;
    const name = make("input", null, { type: "text", maxlength: 120, id: "mv-registration-title" });
    name.value = registrationTitle || project.name;
    name.addEventListener("input", () => { registrationTitle = name.value; });
    const overrides = Object.entries(registrationTimelines).filter(([, path]) => path);
    const register = button(t(registrationAudio.acb ? "Register MV-only copy with selected assets" :
      overrides.length ? "Register MV-only copy with selected timelines" : "Register original as an MV-only copy"), () => {
      const title = name.value.trim();
      if (!title) { name.focus(); return; }
      const payload = { region: source.region, sourceLiveId: source.liveId, title };
      if (Number.isSafeInteger(source.assetId)) payload.assetId = source.assetId;
      if (overrides.length) payload.timelinePaths = Object.fromEntries(overrides);
      if (registrationAudio.acb) payload.audioAcbPath = registrationAudio.acb;
      if (registrationAudio.awb) payload.audioAwbPath = registrationAudio.awb;
      operation("Registering MV…", async (signal) => {
        const receipt = await request("register", payload, signal);
        if (!Number.isSafeInteger(receipt.liveId)) throw new Error("The MV registration response is invalid.");
        registered = { ...receipt, region: source.region };
        chartTemplates = []; chartTemplate = chartPath = "";
        report(t("MV-only copy registered.") + (receipt.restartRequired ? " " + t("Restart the game server to load the updated catalog.") : ""));
      });
    }, { id: "mv-register" });
    register.disabled = !!pending || !!registrationAudio.awb && !registrationAudio.acb;
    const timeline = make("fieldset");
    timeline.append(make("legend", t("Custom timelines (optional)")));
    for (const [platform, title] of [["android", "Choose Android timeline"], ["ios", "Choose iOS timeline"]]) {
      const selectedPath = registrationTimelines[platform];
      if (selectedPath) timeline.append(make("p", `${platform === "ios" ? "iOS" : "Android"} · ${basename(selectedPath)}`, { title: selectedPath }));
      const choose = button(t(title), () => settings.pickFile((path) => {
        if (visible && gameSource() === source) { registrationTimelines[platform] = path; renderRegistration(); }
      }, t(title), ["unity", "bundle", "asset", "bytes"]), { "data-mv-register-timeline": platform });
      choose.disabled = !!pending;
      const row = make("div", null, { class: "mv-controls" });
      row.append(choose);
      if (selectedPath) row.append(button(t("Remove"), () => { delete registrationTimelines[platform]; renderRegistration(); }));
      if (!selectedPath && latestNativeTimeline && latestNativeTimeline.source.liveId === source.liveId &&
          latestNativeTimeline.source.assetId === source.assetId && latestNativeTimeline.source.region === source.region &&
          latestNativeTimeline.platform === platform) {
        row.append(button(t("Use exported timeline"), () => {
          registrationTimelines[platform] = latestNativeTimeline.path; renderRegistration();
        }));
      }
      timeline.append(row);
    }
    const music = make("fieldset");
    music.append(make("legend", t("Custom soundtrack (optional)")), make("p", t("Choose an ACB with one game music cue and its AWB if the cue streams from an external file.")));
    for (const [kind, title] of [["acb", "Choose ACB"], ["awb", "Choose AWB"]]) {
      const selectedPath = registrationAudio[kind];
      if (selectedPath) music.append(make("p", `${kind.toUpperCase()} · ${basename(selectedPath)}`, { title: selectedPath }));
      const choose = button(t(title), () => settings.pickFile((path) => {
        if (visible && gameSource() === source) { registrationAudio[kind] = path; renderRegistration(); }
      }, t(title), [kind]), { "data-mv-register-audio": kind });
      choose.disabled = !!pending;
      const row = make("div", null, { class: "mv-controls" });
      row.append(choose);
      if (selectedPath) row.append(button(t("Remove"), () => { delete registrationAudio[kind]; renderRegistration(); }));
      music.append(row);
    }
    if (registrationAudio.awb && !registrationAudio.acb) music.append(make("p", t("Choose the ACB that uses this AWB.")));
    box.append(field("MV title", name), timeline, music, register);
    if (registered) box.append(make("p", `${registered.title || project.name} · ${t(registered.mvOnly ? "MV only" : "Live show")} (${registered.liveId})`));
    const target = registered || (source.mvOnly || source.registered ? { liveId: source.liveId, region: source.region, mvOnly: source.mvOnly } : null);
    if (!target) return;
    if (!chartTemplates.length) {
      const load = button(t("Load chart templates"), () => operation("Loading chart templates…", async (signal) => {
        const query = new URLSearchParams({ region: target.region, liveId: target.liveId });
        const receipt = await request("chart-templates?" + query, undefined, signal);
        chartTemplates = (receipt.templates || []).filter((item) => Number.isSafeInteger(item.id) && Number.isSafeInteger(item.difficultyType));
        report(chartTemplates.length ? "" : t("No compatible chart templates."));
      }), { id: "mv-chart-templates" });
      load.disabled = !!pending;
      box.append(load);
      return;
    }
    const choices = make("select", null, { id: "mv-chart-template" });
    replaceOptions(choices, chartTemplates, chartTemplate);
    chartTemplate = choices.value;
    choices.addEventListener("change", () => { chartTemplate = choices.value; });
    const pick = button(t("Choose chart file"), () => settings.pickFile((path) => {
      if (!visible) return;
      chartPath = path; renderRegistration();
    }, t("Choose chart file"), ["json"]), { id: "mv-chart-file" });
    pick.disabled = !!pending;
    const attach = button(t("Attach chart"), () => {
      const template = chartTemplates.find((item) => text(item.id) === chartTemplate);
      if (!template || !chartPath) return;
      operation("Attaching chart…", async (signal) => {
        const charts = { [template.difficultyType]: { path: chartPath, template_difficulty_id: template.id } };
        const receipt = await request("charts", { region: target.region, liveId: target.liveId, charts }, signal);
        registered = { ...target, ...receipt };
        chartTemplates = []; chartTemplate = chartPath = "";
        report(t("Chart attached.") + (receipt.restartRequired ? " " + t("Restart the game server to load the updated catalog.") : ""));
      });
    }, { id: "mv-attach-chart" });
    attach.disabled = !!pending || !chartPath;
    box.append(field("Chart template", choices), pick);
    if (chartPath) box.append(make("p", basename(chartPath), { title: chartPath }));
    box.append(attach);
  }

  function chooseEvent(track, event) {
    selected = { track: track.id, event: event.id };
    pause();
    seek(event.start);
    for (const clip of byId("mv-timeline-grid").querySelectorAll(".mv-clip")) {
      clip.setAttribute("aria-pressed", String(clip.dataset.track === text(track.id) && clip.dataset.event === text(event.id)));
    }
    const panel = byId("mv-events");
    if (!panel.hidden) panel.open = true;
    renderEvent();
  }

  function scrub(event, deferDraw = false) {
    if (event.target.closest(".mv-clip")) return;
    const bar = event.currentTarget;
    seek((event.clientX - bar.getBoundingClientRect().left) / pixelsPerSecond, true, deferDraw);
  }

  function flushScrub() {
    scene?.flushSeekDraw();
  }

  function renderTimelineLane(track) {
    const lane = make("div", null, { class: "mv-lane", "data-kind": text(track.kind) });
    lane.addEventListener("click", scrub);
    const rows = [];
    for (const event of track.events.slice().sort((first, second) => first.start - second.start)) {
      const title = text(event.label || track.label || kinds[track.kind]);
      const isSelected = selected && selected.track === track.id && selected.event === event.id;
      const clip = button(title, (click) => { click.stopPropagation(); chooseEvent(track, event); }, {
        class: "mv-clip", title: `${title} · ${formatTime(event.start)}`,
        "data-track": text(track.id), "data-event": text(event.id), "aria-pressed": String(!!isSelected),
      });
      const left = event.start * pixelsPerSecond, width = Math.max(13, event.duration * pixelsPerSecond);
      const free = rows.findIndex((end) => end + 1 < left), row = free < 0 ? rows.length : free;
      rows[row] = left + width;
      clip.style.left = `${left}px`;
      clip.style.width = `${width}px`;
      clip.style.setProperty("--mv-clip-row", row);
      lane.append(clip);
    }
    lane.style.setProperty("--mv-lane-rows", Math.max(rows.length, 1));
    return lane;
  }

  function refreshTimelineLane(track) {
    const previous = timelineLanes.get(track);
    if (!previous) return;
    const lane = renderTimelineLane(track);
    previous.replaceWith(lane);
    timelineLanes.set(track, lane);
  }

  function renderTimeline() {
    const grid = byId("mv-timeline-grid"), scroll = byId("mv-timeline-scroll");
    grid.replaceChildren();
    timelineLanes.clear();
    playheadNode = null;
    if (!project) return;
    const heading = make("p", t("Tracks"), { class: "mv-lane-label" });
    const ruler = make("div", null, { class: "mv-ruler" });
    const scale = byId("mv-zoom").value;
    grid.append(heading, ruler);
    const duration = Math.max(1, project.duration);
    pixelsPerSecond = scale === "fit" ? Math.max(.1, (scroll.clientWidth - heading.offsetWidth) / duration) : Number(scale);
    grid.style.setProperty("--mv-grid-width", `${Math.round(pixelsPerSecond * duration)}px`);
    const interval = [0.5, 1, 2, 5, 10, 15, 30, 60].find((value) => value * pixelsPerSecond >= 56) || 120;
    grid.style.setProperty("--mv-tick-width", `${interval * pixelsPerSecond}px`);
    for (let mark = 0; mark <= project.duration; mark += interval) {
      const item = make("span", formatTime(mark).replace(/\.00$/, ""));
      item.style.left = `${mark * pixelsPerSecond}px`;
      ruler.append(item);
    }
    ruler.addEventListener("pointerdown", (event) => { ruler.setPointerCapture(event.pointerId); scrub(event, true); });
    ruler.addEventListener("pointermove", (event) => { if (ruler.hasPointerCapture(event.pointerId)) scrub(event, true); });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) ruler.addEventListener(type, flushScrub);
    for (const track of project.tracks) {
      if (trackKind && track.kind !== trackKind) continue;
      const label = make("p", text(track.label || kinds[track.kind] || track.kind), { class: "mv-lane-label", title: text(track.binding || track.label) });
      const lane = renderTimelineLane(track);
      timelineLanes.set(track, lane);
      grid.append(label, lane);
    }
    playheadNode = make("div", null, { class: "mv-playhead", "aria-hidden": "true" });
    grid.append(playheadNode);
    syncPosition();
  }

  function renderPreviewStatus() {
    const hint = byId("mv-empty-preview");
    const hasModels = !!(scene && project && (project.stage?.glb || (project.performers || []).some((actor) => actor.glb) ||
      (project.assets || []).some((asset) => ["effect", "props", "background"].includes(asset.kind) && asset.previewUrl)));
    const loading = previewLoading || !!gameImport;
    hint.textContent = t(loading ? "Loading 3D model…" : project ? "This MV has no visual assets available for preview." : "Open an MV to preview its stage and timeline.");
    hint.hidden = !!gameImport?.stageReady || hasModels && !loading;
    byId("mv-preview-controls").hidden = !hasModels || loading;
  }

  function render() {
    byId("mv-project-title").textContent = project && project.name || t("3D MV");
    renderPreviewStatus();
    byId("mv-warning-list").replaceChildren(...(project && project.warnings || []).map((line) => make("li", t(line))));
    byId("mv-save").disabled = !project || !!pending;
    byId("mv-export-timeline").hidden = !(project && project.nativeTimeline);
    byId("mv-export-timeline").disabled = !!pending;
    renderPanelMenu();
    renderAssets();
    renderPerformers();
    renderSoundtrack();
    renderTracks();
    renderEvent();
    renderQuality();
    renderRegistration();
    renderTimeline();
    updatePlayButton();
  }

  function checkedProject(data) {
    const value = data && (data.project || data);
    if (!value || value.version !== 1 || !finite(value.duration) || value.duration < 0 || !Array.isArray(value.tracks) ||
        !value.tracks.every((track) => Array.isArray(track.events) && track.events.every((event) => finite(event.start) && finite(event.duration)))) {
      throw new Error("The imported MV project is invalid.");
    }
    return value;
  }

  function ensureScene() {
    if (!scene && global.MVStudioScene) {
      scene = global.MVStudioScene.create(byId("mv-scene"), { onError: showError, visible: visible && !document.hidden });
      scene.setVisible(visible && !document.hidden);
    }
    return scene;
  }

  async function commit(value, preserveTime = false, reuseOutfit = null, reuseStage = false) {
    const next = checkedProject(value);
    const playhead = preserveTime ? time : 0;
    pause();
    ensureScene();
    const source = resource(next.soundtrack && next.soundtrack.url);
    if (source) {
      if (audio.src !== source) audio.src = source;
    } else if (audio.hasAttribute("src")) {
      audio.removeAttribute("src"); audio.load();
    }
    const previous = selected;
    project = next;
    selected = preserveTime ? previous : null;
    trackKind = preserveTime ? trackKind : "";
    if (!preserveTime) {
      registered = latestNativeTimeline = null; registrationTitle = performerId = ""; registrationTimelines = {}; registrationAudio = {};
      chartTemplates = []; chartTemplate = chartPath = "";
    }
    previewLoading = !!scene;
    try {
      const ready = scene && scene.load(next, { reuseOutfit, reuseStage });
      if (scene) scene.setVisible(visible && !document.hidden);
      render();
      seek(playhead);
      await ready;
    } finally {
      previewLoading = false;
      renderPreviewStatus();
      updatePlayButton();
    }
  }

  async function operation(label, callback) {
    if (pending) return false;
    const controller = new AbortController();
    pending = controller;
    byId("mv-save-result").hidden = true;
    byId("mv-import-game").disabled = byId("mv-open").disabled = byId("mv-save").disabled = byId("mv-export-timeline").disabled = true;
    report(t(label));
    try { await callback(controller.signal); return true; }
    catch (error) { showError(error); return false; }
    finally {
      pending = null;
      byId("mv-import-game").disabled = byId("mv-open").disabled = false;
      byId("mv-save").disabled = !project;
      byId("mv-export-timeline").disabled = false;
      renderAssets();
      renderPerformers();
      renderSoundtrack();
      renderRegistration();
    }
  }

  function open() {
    if (pending) return;
    settings.pickFile((path) => {
      if (!visible) return;
      operation("Opening MV…", async (signal) => {
        await commit(await request("open", { path }, signal));
        report("");
      });
    }, t("Open mod or project"), ["zip", "unity", "bundle", "asset", "bytes", "json", "glb"]);
  }

  function importAsset(kind, replaceActor = null) {
    if (!project || pending) return;
    if (kind === "outfit" && replaceActor == null && (project.performers || []).length >= 9) {
      report(t("This MV already has nine performers. Choose an existing performer to replace their outfit."), true);
      return;
    }
    const activeProject = project;
    settings.pickFile((path) => {
      if (activeProject !== project || !visible) return;
      operation("Importing MV asset…", async (signal) => {
        const response = await request("asset", { path, kind }, signal);
        if (!response.asset || typeof response.asset.id !== "string") throw new Error("The MV asset could not be imported.");
        const next = copy(project);
        next.assets = (next.assets || []).filter((asset) => asset.id !== response.asset.id);
        next.assets.push(response.asset);
        if (response.stage) next.stage = response.stage;
        if (response.performer) {
          if (replaceActor == null) next.performers = (next.performers || []).concat(response.performer);
          else next.performers = next.performers.map((actor) => actor.id === replaceActor
            ? { ...response.performer, id: actor.id, transform: actor.transform || response.performer.transform } : actor);
        }
        if (response.soundtrack) next.soundtrack = response.soundtrack;
        await commit(next, true, kind === "outfit" && response.performer ? replaceActor : null);
        report("");
      });
    }, t(kind === "audio" ? "Import soundtrack" : "Import MV asset"), kind === "audio"
      ? ["m4a", "mp3", "ogg", "wav"] : ["unity", "bundle", "asset", "bytes", "zip", "glb"]);
  }

  function saveResult(endpoint, pendingLabel, doneLabel) {
    if (!project || pending) return;
    const snapshot = copy(project);
    const source = gameSource();
    operation(pendingLabel, async (signal) => {
      const receipt = await request(endpoint, { project: snapshot }, signal);
      const href = resource(receipt.download);
      if (!href) throw new Error("The MV project could not be saved.");
      const result = byId("mv-save-result"), name = basename(receipt.path);
      result.replaceChildren(make("a", name || t("Download MV project"), { href, download: name, title: text(receipt.path) }));
      if (receipt.path && global.ElichikaPlatform && ElichikaPlatform.supports("reveal")) {
        result.append(button(t("Show in Finder"), () => ElichikaPlatform.request("reveal", { path: receipt.path }).catch(showError)));
      }
      if (endpoint === "export-timeline" && source && receipt.path) latestNativeTimeline = { source, platform: source.platform, path: receipt.path };
      result.hidden = false;
      report(t(doneLabel));
    });
  }

  function save() { return saveResult("save", "Saving MV project…", "MV project saved."); }

  function syncVariants() {
    const song = songs.find((item) => text(item.id) === byId("mv-game-song").value);
    const variants = byId("mv-game-variant");
    replaceOptions(variants, song && song.variants || [], variants.value);
    byId("mv-game-download").checked = false;
    byId("mv-game-load").disabled = !song || !variants.value || !!catalogRequest;
  }

  function foldSearch(value) { return text(value).normalize("NFKC").toLocaleLowerCase(settings.language()); }

  function filterCatalog() {
    if (catalogRequest) return;
    const query = foldSearch(byId("mv-game-search").value.trim());
    const select = byId("mv-game-song");
    songs = catalogIndex.filter((entry) => !query || entry.search.includes(query)).map((entry) => entry.song);
    replaceOptions(select, songs.map((song) => ({ id: song.id, label: song.title + (song.mvOnly ? " · " + t("MV only") : "") })), select.value);
    byId("mv-game-status").textContent = songs.length ? "" : t("No matching MVs.");
    syncVariants();
  }

  async function loadCatalog() {
    const dialog = byId("mv-game-picker");
    if (!dialog.open) return;
    if (catalogRequest) catalogRequest.abort();
    const controller = new AbortController();
    catalogRequest = controller;
    const region = byId("mv-game-region"), platform = byId("mv-game-platform"), song = byId("mv-game-song");
    const status = byId("mv-game-status");
    status.textContent = t("Loading MVs…");
    byId("mv-game-load").disabled = true;
    const native = global.ElichikaPlatform && ElichikaPlatform.info().platform === "macos";
    const query = new URLSearchParams({ region: region.value || (settings.language() === "ja" ? "jp" : "gl"),
      platform: platform.value || (native ? "ios" : "android") });
    try {
      const data = await request("catalog?" + query, undefined, controller.signal);
      if (catalogRequest !== controller || !dialog.open) return;
      replaceOptions(region, data.regions || [], data.region || region.value);
      replaceOptions(platform, data.platforms || [], data.platform || platform.value);
      catalogIndex = (Array.isArray(data.songs) ? data.songs : []).map((song) => ({ song,
        search: foldSearch([song.id, song.title, ...(song.variants || []).flatMap((variant) => [variant.id, variant.label])].join("\n")) }));
      catalogRequest = null;
      filterCatalog();
    } catch (error) {
      if (catalogRequest === controller && error.name !== "AbortError") {
        catalogIndex = []; songs = []; song.replaceChildren(); status.textContent = t(error.message);
      }
    } finally {
      if (catalogRequest === controller) { catalogRequest = null; syncVariants(); }
    }
  }

  function showCatalog() {
    if (pending) return;
    const picker = byId("mv-game-picker");
    byId("mv-game-download").checked = false;
    picker.showModal();
    loadCatalog();
  }

  function blockImportEdit(event) {
    if (event.type === "keydown" && event.key === "Tab") return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }

  function lockGameEditing(locked) {
    for (const id of ["mv-inspector", "mv-timeline-scroll"]) {
      const panel = byId(id);
      if ("inert" in panel) panel.inert = locked;
      else {
        if (locked && panel.contains(document.activeElement)) document.activeElement.blur();
        const method = locked ? "addEventListener" : "removeEventListener";
        for (const type of ["click", "pointerdown", "keydown", "beforeinput", "input", "change"]) {
          panel[method](type, blockImportEdit, true);
        }
      }
    }
  }

  function isCurrentGameImport(load) {
    return gameImport === load && !load.controller.signal.aborted;
  }

  function discardStage(load) {
    if (load.stageRequested) scene?.cancelStagePreparation?.();
    load.stageRequested = load.stageReady = false;
  }

  function cancelGameImport() {
    if (!gameImport || gameImport.finishing) return;
    gameImport.controller.abort();
    discardStage(gameImport);
    renderPreviewStatus();
  }

  async function showGameStage(load, preview) {
    if (!isCurrentGameImport(load) || load.finishing || !visible || document.hidden) return;
    try {
      const target = ensureScene();
      if (!target?.prepareStage) return;
      load.stageRequested = true;
      const ready = await target.prepareStage(preview);
      if (isCurrentGameImport(load) && !load.finishing && ready) {
        load.stageReady = true;
        renderPreviewStatus();
      }
    } catch (_) {
      if (isCurrentGameImport(load) && !load.finishing) discardStage(load);
    }
  }

  function importGame() {
    const song = byId("mv-game-song"), variant = byId("mv-game-variant");
    if (!song.value || !variant.value || catalogRequest) return;
    const choice = songs.find((item) => text(item.id) === song.value);
    const version = choice && choice.variants.find((item) => text(item.id ?? item.value) === variant.value);
    if (!choice || !version) return;
    const payload = { region: byId("mv-game-region").value, platform: byId("mv-game-platform").value,
      liveId: choice.id, assetId: version.id ?? version.value, download: byId("mv-game-download").checked };
    byId("mv-game-picker").close();
    operation("Preparing MV from game…", async (signal) => {
      const load = { controller: pending, stageRequested: false, stageReady: false, finishing: false };
      gameImport = load;
      pause();
      lockGameEditing(true);
      renderPreviewStatus();
      let committed = false;
      const requireCurrent = () => {
        if (!isCurrentGameImport(load)) throw new DOMException("The MV import was cancelled.", "AbortError");
      };
      try {
        requireCurrent();
        let imported = await requestGameStream(payload, signal, (preview) => showGameStage(load, preview));
        requireCurrent();
        if (imported === null) imported = checkedProject(await request("game", payload, signal));
        requireCurrent();
        load.finishing = true;
        await commit(imported, false, null, load.stageRequested);
        committed = true;
        report("");
      } catch (error) {
        if (!load.finishing) requireCurrent();
        throw error;
      } finally {
        if (!committed) discardStage(load);
        gameImport = null;
        lockGameEditing(false);
        renderPreviewStatus();
        updatePlayButton();
      }
    });
  }

  function setupTimelineResizer(scroll) {
    const grip = byId("mv-timeline-resizer"), key = "elichika.mv.timelineHeight.v1", minimum = 62;
    const portrait = global.matchMedia("(max-width: 640px) and (orientation: portrait)");
    let preferred = null, drag = null, resizeFrame = 0, nextHeight, maximum = minimum;
    try {
      const saved = Number(localStorage.getItem(key));
      if (finite(saved) && saved >= minimum) preferred = saved;
    } catch (_) {}

    function refresh() {
      maximum = Math.max(minimum, Math.floor(global.innerHeight * (portrait.matches ? .60 : .72)));
      const height = preferred === null ? null : clamp(preferred, minimum, maximum);
      const size = height === null ? "" : `${height}px`;
      if (scroll.style.getPropertyValue("--mv-timeline-height") !== size) {
        if (size) scroll.style.setProperty("--mv-timeline-height", size);
        else scroll.style.removeProperty("--mv-timeline-height");
      }
      grip.setAttribute("aria-valuemax", maximum);
      grip.setAttribute("aria-valuenow", height ?? Math.max(minimum, scroll.clientHeight));
    }

    function saveHeight() {
      try {
        if (preferred === null) localStorage.removeItem(key);
        else localStorage.setItem(key, String(preferred));
      } catch (_) {}
    }

    function applyDrag() {
      resizeFrame = 0;
      preferred = clamp(Math.round(nextHeight), minimum, maximum);
      refresh();
    }

    grip.setAttribute("aria-valuemin", minimum);
    grip.addEventListener("pointerdown", (event) => {
      if (drag || event.button !== 0) return;
      event.preventDefault();
      grip.focus({ preventScroll: true });
      drag = { id: event.pointerId, y: event.clientY, height: scroll.clientHeight, moved: false };
      grip.setPointerCapture(event.pointerId);
      grip.classList.add("mv-dragging");
    });
    grip.addEventListener("pointermove", (event) => {
      if (drag?.id !== event.pointerId) return;
      nextHeight = drag.height + event.clientY - drag.y;
      drag.moved ||= event.clientY !== drag.y;
      if (drag.moved && !resizeFrame) resizeFrame = requestAnimationFrame(applyDrag);
    });
    function finishDrag(event) {
      if (drag?.id !== event.pointerId) return;
      if (resizeFrame) {
        cancelAnimationFrame(resizeFrame);
        applyDrag();
      }
      if (drag.moved) saveHeight();
      drag = null;
      grip.classList.remove("mv-dragging");
    }
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) grip.addEventListener(type, finishDrag);
    grip.addEventListener("keydown", (event) => {
      if (drag) return;
      const step = event.shiftKey ? 48 : 16;
      if (event.key === "Home") preferred = null;
      else if (event.key === "End") preferred = maximum;
      else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        preferred = clamp(scroll.clientHeight + (event.key === "ArrowDown" ? step : -step), minimum, maximum);
      } else return;
      event.preventDefault();
      refresh();
      saveHeight();
    });
    global.addEventListener("resize", refresh);
    refresh();
    return refresh;
  }

  function setVisible(value) {
    if (!settings) return;
    visible = value;
    if (scene) scene.setVisible(visible && !document.hidden);
    if (!visible) {
      pause();
      if (byId("mv-game-picker").open) byId("mv-game-picker").close();
    }
    if (visible) {
      refreshTimelineHeight();
      renderTimeline();
    }
  }

  function mount(options) {
    if (settings) return;
    settings = options;
    seekInput = byId("mv-seek");
    timeOutput = byId("mv-time");
    const timelineScroll = byId("mv-timeline-scroll");
    refreshTimelineHeight = setupTimelineResizer(timelineScroll);
    try { hidden = (JSON.parse(localStorage.getItem("elichika.mv.panels.v1")) || []).filter((key) => panelKeys.includes(key)); } catch (_) {}
    byId("mv-import-game").addEventListener("click", showCatalog);
    byId("mv-game-close").addEventListener("click", () => byId("mv-game-picker").close());
    byId("mv-open").addEventListener("click", open);
    byId("mv-save").addEventListener("click", save);
    byId("mv-export-timeline").addEventListener("click", () => {
      if (project && project.nativeTimeline) saveResult("export-timeline", "Exporting native timeline…", "Native timeline exported.");
    });
    byId("mv-rewind").addEventListener("click", () => { pause(); seek(0); });
    byId("mv-play").addEventListener("click", togglePlayback);
    byId("mv-camera-mode").addEventListener("change", (event) => { if (scene) scene.setCamera(event.target.value); });
    byId("mv-frame-scene").addEventListener("click", () => {
      if (!scene) return;
      byId("mv-camera-mode").value = "orbit";
      scene.setCamera("orbit");
      scene.frameAll();
    });
    seekInput.addEventListener("input", (event) => seek(event.target.valueAsNumber, true, true));
    seekInput.addEventListener("change", flushScrub);
    byId("mv-zoom").addEventListener("change", renderTimeline);
    byId("mv-game-region").addEventListener("change", loadCatalog);
    byId("mv-game-platform").addEventListener("change", loadCatalog);
    byId("mv-game-song").addEventListener("change", syncVariants);
    byId("mv-game-variant").addEventListener("change", () => { byId("mv-game-download").checked = false; });
    byId("mv-game-search").addEventListener("input", filterCatalog);
    byId("mv-game-load").addEventListener("click", importGame);
    byId("mv-game-picker").addEventListener("close", () => {
      if (catalogRequest) catalogRequest.abort();
      catalogRequest = null;
      catalogIndex = [];
    });
    document.addEventListener("visibilitychange", () => {
      if (scene) scene.setVisible(visible && !document.hidden);
      if (document.hidden) pause();
    });
    global.addEventListener("pagehide", (event) => {
      pause();
      if (event.persisted) return;
      cancelGameImport();
      if (pending) pending.abort();
      if (catalogRequest) catalogRequest.abort();
      if (scene) scene.dispose();
    });
    let width = -1;
    resizeObserver = global.ResizeObserver && new ResizeObserver(() => {
      if (!visible) return;
      const next = timelineScroll.clientWidth;
      if (next !== width) { width = next; renderTimeline(); }
      refreshTimelineHeight();
    });
    if (resizeObserver) resizeObserver.observe(timelineScroll);
    render();
  }

  global.MVStudio = Object.freeze({ mount, setVisible, updateLanguage: () => { if (settings) render(); }, open, save,
    getState: () => ({ visible, playing, time, selection: selected && { ...selected }, project: project && copy(project) }) });
})(window);
