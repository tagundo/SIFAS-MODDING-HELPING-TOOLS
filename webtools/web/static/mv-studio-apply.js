/* MV Studio plugin: "게임에 적용" — apply the open project's timeline to the game's MV.
 *
 * The server (webtools/core/mv_studio_apply.py) plans and runs the jobs; this page only:
 *  - asks for the plan (no writes) when the panel opens and after edits (debounced 1 s);
 *  - prepares the project like the registration panel (MVStudioRegister.prepare: every plugin's
 *    beforeExport and prepareNativeExport) and checks again with exactly the posted project;
 *  - offers "Apply only the edits" (the changes since loading, or since this project's last
 *    apply, written onto what the game plays now; conflicts are listed, never overwritten),
 *    "Apply all" (the whole project replaces the game's timeline) and, for a stock MV with an
 *    applied timeline, "Restore the original MV";
 *  - keeps the job's record of what the project and each platform's game timeline agree on
 *    (source.applied, per platform), so editing the same clip again after an apply is not a
 *    conflict, and a platform left out with consent still gets the edits later;
 *  - adds a compact toolbar shortcut after "Export native timeline".
 * A project that is not a game import points to the registration panel ("MV 전용 곡으로 등록").
 */
(function (global) {
  "use strict";

  const route = "/api/mv-studio/";
  const KEY = "apply";
  const PLATFORMS = ["android", "ios"];
  const text = (value) => String(value == null ? "" : value);
  let ctx = null, box = null, shortcut = null;
  let state = fresh();

  // revision counts project changes; planned is the revision the shown plan was made from.
  // consent lists the platforms the user agreed to leave as they are for the next submit.
  function fresh() {
    return { plan: null, planning: null, timer: 0, planError: "", revision: 0, planned: -1, download: false,
      consent: [], confirm: null, job: null, result: null, failed: null, conflicts: null, error: "" };
  }

  // ---- helpers ----------------------------------------------------------------------------
  function t(label) { return ctx.t(label); }
  function format(label, values) { return ctx.format(label, values); }
  function clean(attrs) {
    const result = {};
    for (const [key, value] of Object.entries(attrs || {})) if (value !== undefined && value !== null) result[key] = value;
    return result;
  }
  function make(tag, label, attrs) { return ctx.make(tag, label, clean(attrs)); }
  function button(label, action, attrs) { return ctx.button(t(label), action, clean(attrs)); }
  function url(path) {
    const language = typeof ctx.language === "function" ? ctx.language() : "en";
    return route + path + (path.includes("?") ? "&" : "?") + "lang=" + encodeURIComponent(language);
  }
  async function call(path, payload, signal) {
    const response = await fetch(url(path), { method: "POST", credentials: "same-origin", signal,
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    let data = null;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok || !data || data.error) throw new Error(data && data.error || "The MV request failed.");
    return data;
  }
  function message(item) { return item && item.values ? format(item.message, item.values) : t(item && item.message || ""); }
  function platformName(platform) { return platform === "ios" ? "iOS" : "Android"; }
  function open() { const panel = box && box.closest("details"); return !!(panel && panel.open); }
  function stale() { return state.planned !== state.revision; }
  function date(seconds) {
    if (!Number.isFinite(seconds)) return "";
    const value = new Date(seconds * 1000);
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  }
  function prepare() {
    if (global.MVStudioRegister && typeof global.MVStudioRegister.prepare === "function") return global.MVStudioRegister.prepare(plugin);
    return Promise.resolve({ project: JSON.parse(JSON.stringify(ctx.project())), unbaked: [] });
  }
  // The registration panel: first registrations of MV-only songs happen there.
  function openRegister() {
    const panel = document.getElementById("mv-panel-register");
    if (!panel) return;
    panel.open = true;
    panel.scrollIntoView({ block: "nearest" });
    const summary = panel.querySelector(":scope > summary");
    if (summary) summary.focus();
  }

  // ---- plan ---------------------------------------------------------------------------------
  function schedulePlan(delay = 1000) {
    if (!ctx.project() || !open()) return;
    clearTimeout(state.timer);
    state.timer = setTimeout(runPlan, delay);
  }

  async function runPlan() {
    if (!ctx.project()) return;
    if (state.planning) state.planning.abort();
    clearTimeout(state.timer);
    const controller = new AbortController(), current = state, revision = state.revision;
    state.planning = controller;
    draw();
    try {
      let prepared;
      try { prepared = await prepare(); }
      catch (error) { prepared = null; current.planError = text(error && error.message); }
      if (!prepared) return;
      const plan = await call("apply-plan", { project: prepared.project, unbaked: prepared.unbaked }, controller.signal);
      if (current !== state) return;
      usePlan(plan, revision);
    } catch (error) {
      if (error.name !== "AbortError" && current === state) state.planError = text(error.message);
    } finally {
      if (current.planning === controller) current.planning = null;
      if (current === state) draw();
    }
  }

  function usePlan(plan, revision) {
    state.plan = plan;
    state.planned = revision;
    state.planError = "";
    // Conflicts shown after a refused job belong to the game as it was then.
    if (state.conflicts && !(plan.edits && plan.edits.conflicts && plan.edits.conflicts.length)) state.conflicts = null;
  }

  // ---- jobs -----------------------------------------------------------------------------------
  function catalogued(plan) { return PLATFORMS.filter((platform) => plan.platforms && plan.platforms[platform]); }

  // The job's platforms: every catalogued one, minus those whose needed download was not allowed
  // (they keep what they play now, with the user's consent).
  function platformsFor(plan, mode) {
    const needed = (mode === "all" ? plan.all && plan.all.download : plan.edits && plan.edits.download) || [];
    const skipped = state.download ? [] : needed.filter((platform) => catalogued(plan).includes(platform));
    return { send: catalogued(plan).filter((platform) => !skipped.includes(platform)), skipped };
  }

  function consentMessage(skipped) {
    return skipped.length > 1 ? "Android and iOS keep the MV they play now. Continue?" :
      skipped[0] === "ios" ? "iOS keeps the MV it plays now. Continue?" : "Android keeps the MV it plays now. Continue?";
  }

  function blocked(plan, mode) {
    if (!plan || plan.blocked.length || state.planError) return true;
    if (mode === "restore") return !(plan.restore && plan.restore.available);
    const part = mode === "all" ? plan.all : plan.edits;
    if (!part || part.blocked.length) return true;
    if (mode === "all") return !!part.unchanged || (part.missing || []).length === catalogued(plan).length;
    // A platform whose served timeline needs a download is merged by the job once the download is allowed.
    return !((part.apply || []).length || (part.download || []).length && part.counts && part.counts.clips);
  }

  function confirmText(plan, mode) {
    const game = plan.game || {};
    if (mode === "restore") return format("Restore the original MV? The MV Studio version {revision} stays in a backup.", { revision: game.revision });
    if (game.state === "custom") return format("Apply all replaces the game's MV Studio version {revision} with this project. A backup is made first. Continue?", { revision: game.revision });
    return "Apply all writes this whole project over the game's original MV. A backup is made first. Continue?";
  }

  function submit(mode, confirmed = false) {
    const plan = state.plan;
    if (state.job || state.planning || stale() || blocked(plan, mode)) { draw(); return; }
    if (mode !== "edits" && !confirmed) {
      state.confirm = { mode, message: confirmText(plan, mode) };
      draw();
      focus("mv-apply-confirm");
      return;
    }
    if (mode !== "restore") {
      const { skipped } = platformsFor(plan, mode);
      if (skipped.length && !skipped.every((platform) => state.consent.includes(platform))) {
        state.confirm = { mode, platforms: skipped, message: consentMessage(skipped), consent: true };
        draw();
        focus("mv-apply-confirm");
        return;
      }
    }
    state.confirm = null;
    start(mode);
  }

  async function start(mode) {
    const plan = state.plan, controller = new AbortController(), current = state, revision = state.revision;
    state.job = { controller, stage: "Preparing the project", index: 0, total: 1, id: null, mode };
    state.error = "";
    state.result = state.failed = null;
    draw();
    try {
      let receipt;
      if (mode === "restore") {
        receipt = await call("restore-job", { region: plan.target.region, assetId: plan.target.assetId,
          expected: { key: plan.expected.key } }, controller.signal);
      } else {
        const prepared = await prepare();
        if (prepared.unbaked.length) throw new Error("Some editor changes are not baked into the timeline yet. Wait for them to finish, then register again.");
        // Check again with exactly the posted project: an edit since the shown plan must not change what is applied.
        const checked = await call("apply-plan", { project: prepared.project, unbaked: [] }, controller.signal);
        if (current !== state) return;
        usePlan(checked, revision);
        const { send, skipped } = platformsFor(checked, mode);
        if (blocked(checked, mode) || checked.expected.key !== plan.expected.key) { state.job = null; draw(); return; }
        if (skipped.length && !skipped.every((platform) => state.consent.includes(platform))) {
          state.job = null;
          state.confirm = { mode, platforms: skipped, message: consentMessage(skipped), consent: true };
          draw();
          return;
        }
        receipt = await call("apply-job", { mode, project: prepared.project, platforms: send, download: !!state.download,
          expected: { key: checked.expected.key }, unbaked: [] }, controller.signal);
        current.consent = [];
      }
      follow(receipt.job_id, current);
    } catch (error) {
      if (current !== state) return;
      state.job = null;
      if (error.name !== "AbortError") state.error = text(error.message);
      draw();
    }
  }

  function follow(id, current) {
    if (!global.EventSource) { current.job = null; current.error = "MV registration progress is unavailable. Reopen this page."; draw(); return; }
    current.job.id = id;
    const events = new global.EventSource("/api/jobs/" + encodeURIComponent(id) + "/events");
    let finished = false;
    events.onmessage = (raw) => {
      let event;
      try { event = JSON.parse(raw.data); } catch (_) { return; }
      if (event.type === "mv-stage" && current.job) {
        current.job.stage = event.label; current.job.index = event.index; current.job.total = event.total;
        current.job.key = event.stage;
      } else if (event.type === "mv-failed") {
        current.failed = { message: text(event.message), restart: event.restart };
      } else if (event.type === "mv-conflicts") {
        current.conflicts = event.conflicts || [];
      } else if (event.type === "mv-timeline") {
        current.result = event;
        // What the project and the game now agree on: the next "edits only" starts from it.
        const project = ctx.project();
        if (current === state && project && project.source && typeof project.source === "object" && "applied" in event) {
          if (event.applied) project.source.applied = event.applied;
          else delete project.source.applied;
        }
      } else if (event.type === "done") {
        finished = true;
        events.close();
        current.job = null;
        if (current.failed) current.error = current.failed.message;
        else if (event.status === "error") current.error = text(event.summary);
        else if (event.status === "cancelled") current.error = "Applying to the game was cancelled.";
        if (current === state) runPlan();
      }
      if (current === state) draw();
    };
    events.onerror = () => {
      if (finished || events.readyState !== global.EventSource.CLOSED) return;
      current.job = null;
      current.error = "MV registration progress was interrupted. Check the songs list.";
      if (current === state) draw();
    };
  }

  function cancelJob() {
    const job = state.job;
    if (!job) return;
    if (job.id) fetch("/api/jobs/" + encodeURIComponent(job.id) + "/cancel", { method: "POST", credentials: "same-origin" }).catch(() => {});
    else job.controller.abort();
  }

  // ---- rendering ----------------------------------------------------------------------------
  function focus(id) { setTimeout(() => { const node = box && box.querySelector("#" + id); if (node) node.focus(); }); }

  function draw() {
    syncShortcut();
    if (!box || !ctx) return;
    const active = document.activeElement && box.contains(document.activeElement) ? document.activeElement : null;
    const restore = active && active.id ? active.id : null;
    box.replaceChildren(...content());
    if (restore) { const node = box.querySelector("#" + restore); if (node) node.focus(); }
  }

  function content() {
    const project = ctx.project();
    if (!project) return [make("p", t("No MV is open."))];
    const plan = state.plan, nodes = [];
    if (!plan) {
      nodes.push(make("p", t(state.planError || (state.planning ? "Checking the game's timeline…" : "Open this panel to check the game's timeline.")),
        { class: state.planError ? "mv-register-error" : "mv-field-note", id: "mv-apply-status" }));
      return nodes;
    }
    if (!plan.target) {
      // Not a game import with a native timeline (a mod, a saved scratch project): register it instead.
      nodes.push(make("p", message(plan.blocked[0] || { message: "Load the MV from the game to apply it." }), { class: "mv-field-note", id: "mv-apply-status" }));
      if (document.getElementById("mv-panel-register")) {
        nodes.push(button("Register as a new MV-only song…", openRegister, { id: "mv-apply-register" }));
      }
      return nodes;
    }
    nodes.push(summary(plan), checks(plan));
    const conflicts = state.conflicts || plan.edits && plan.edits.conflicts || [];
    if (conflicts.length) nodes.push(conflictBox(conflicts));
    nodes.push(actions(plan));
    if (state.confirm) nodes.push(confirmBox());
    if (state.job) nodes.push(progressBox());
    if (state.error) nodes.push(make("p", t(state.error), { class: "mv-register-error", role: "alert", id: "mv-apply-error" }));
    const server = state.failed && state.error === state.failed.message && serverNote(state.failed.restart);
    if (server) nodes.push(make("p", t(server), { class: "mv-field-note", id: "mv-apply-error-server" }));
    if (state.result) nodes.push(resultBox(state.result));
    return nodes;
  }

  function summary(plan) {
    const wrap = make("div", null, { class: "mv-apply-summary", id: "mv-apply-summary" });
    const target = plan.target, game = plan.game || {}, source = plan.source || {};
    wrap.append(make("p", format(target.kind === "song" ? "MV-only song: {title} ({id})" : "Game MV: {title} ({id})",
      { title: target.title || target.liveId, id: target.liveId }) + (target.stage ? " · " + target.stage : ""), { id: "mv-apply-target" }));
    const inGame = game.state === "custom" ? format("In the game: MV Studio version {revision} ({date})", { revision: game.revision, date: date(game.updatedAt) })
      : t("In the game: the original MV");
    const loaded = source.state === "song" ? t("Loaded from: the registered song") : source.state === "custom" ?
      (source.revision ? format("Loaded from: MV Studio version {revision}", { revision: source.revision }) : t("Loaded from: an MV Studio version"))
      : t("Loaded from: the original MV");
    wrap.append(make("p", inGame + " · " + loaded, { class: "mv-field-note", id: "mv-apply-game" }));
    const lives = target.lives || { count: 0, shown: [] };
    if (target.kind === "stock" && lives.count > 1) {
      wrap.append(make("p", format("This MV also plays in the 3D live of {count} songs: {titles}", { count: lives.count,
        titles: lives.shown.map((item) => item.title).join(", ") + (lives.count > lives.shown.length ? "…" : "") }), { class: "mv-field-note" }));
    } else if (target.kind === "stock") {
      wrap.append(make("p", t("The song's 3D live plays this MV too."), { class: "mv-field-note" }));
    }
    return wrap;
  }

  function checks(plan) {
    const list = make("ul", null, { id: "mv-apply-plan", class: "mv-register-plan" });
    const item = (kind, label, extra) => {
      const row = make("li", null, { class: "mv-register-" + kind, "data-mv-plan": kind });
      row.append(make("span", kind === "ok" ? "✓" : kind === "blocked" ? "✕" : "⚠", { "aria-hidden": "true", class: "mv-register-icon" }), make("span", label));
      if (extra) row.append(extra);
      list.append(row);
      return row;
    };
    const edits = plan.edits, all = plan.all;
    if (plan.source && plan.source.changedSince) {
      item("warn", t("The game's MV changed after this project was loaded. Apply only the edits keeps those changes; Apply all replaces them."));
    }
    if (edits) {
      const counts = edits.counts || {};
      if (!counts.clips) item("ok", t(edits.since === "apply" ? "Edits: none since the last apply" : "Edits: none since loading"));
      else {
        item("ok", format(edits.since === "apply" ? "Edits since the last apply: {clips} clips (camera {camera} · values {values} · timing {timing})" :
          "Edits since loading: {clips} clips (camera {camera} · values {values} · timing {timing})",
        { clips: counts.clips, camera: counts.cameraShots || 0, values: counts.values || 0, timing: counts.timing || 0 }));
        // A platform left out of an earlier apply (with consent) still waits for edits the other one has.
        const pending = edits.pending || {};
        const waiting = catalogued(plan).filter((platform) => pending[platform]);
        if (waiting.length && waiting.length < catalogued(plan).length) {
          item("warn", format("These edits are not in {platform} yet.", { platform: waiting.map(platformName).join(" · ") }));
        }
      }
    }
    if (all) {
      if (all.unchanged) item("ok", t("Apply all: the game already plays this project."));
      else if (all.counts && !all.counts.clips) item("ok", t("Apply all: the game plays the original MV again."));
      else if (all.counts) item("ok", format("Apply all: {clips} clips differ from the original MV", { clips: all.counts.clips }));
    }
    const downloads = [...new Set([...(edits && edits.download || []), ...(all && all.download || [])])];
    if (downloads.length) {
      const bytes = downloads.reduce((sum, platform) => {
        const entry = plan.platforms[platform] || {};
        return sum + Math.max((entry.stock && entry.stock.bytes) || 0, (entry.served && entry.served.bytes) || 0);
      }, 0);
      const check = make("input", null, { type: "checkbox", id: "mv-apply-download" });
      check.checked = !!state.download;
      check.addEventListener("change", () => { state.download = check.checked; draw(); });
      const label = make("label", null, { class: "mv-register-download" });
      label.append(check, make("span", format("Download (about {size} MB)", { size: Math.max(0.1, Math.round(bytes / 104857.6) / 10) })));
      item("warn", format("No {platform} original", { platform: downloads.map(platformName).join(" · ") }), label);
    }
    for (const note of plan.notInGame || []) {
      item("warn", t("Not in the game:") + " " + t(note.message) + (note.labels && note.labels.length ? " " + note.labels.join(", ") : ""));
    }
    for (const warning of plan.warnings || []) item("warn", message(warning));
    for (const reason of plan.blocked || []) item("blocked", message(reason) + (reason.labels && reason.labels.length ? " " + reason.labels.join(", ") : ""));
    for (const reason of edits && edits.blocked || []) {
      if (reason.message === "There are no edits since this project was loaded.") continue;
      if (reason.message === "Some edits were also changed differently in the game since this project was loaded. Use Apply all, or load the MV from the game again.") continue;
      item("blocked", message(reason));
    }
    if (state.planError) item("blocked", t(state.planError));
    const wrap = make("div", null, { id: "mv-apply-check" });
    wrap.append(list);
    if (state.planning) wrap.append(make("p", t("Checking the game's timeline…"), { class: "mv-field-note" }));
    return wrap;
  }

  // The inspector's own labels for clip timing and names; playable values keep their native names.
  const CLIP_FIELDS = { start: "Start time (s)", duration: "Duration (s)", label: "Clip name" };

  // One row per field; a conflict on both platforms is listed once.
  function conflictBox(conflicts) {
    const wrap = make("div", null, { class: "mv-register-confirm mv-apply-conflicts", id: "mv-apply-conflicts", role: "alert" });
    const rows = new Map();
    for (const item of conflicts) {
      // The same field on both platforms is one row when both compared against the same value.
      const key = [item.eventId, item.field, item.basis, item.loaded, item.game].join("\u0000");
      if (!rows.has(key)) rows.set(key, { ...item, platforms: [] });
      rows.get(key).platforms.push(item.platform);
    }
    wrap.append(make("p", format("Changed differently in the game ({count})", { count: rows.size }), { class: "mv-register-confirm-title" }));
    const list = make("ul", null, { class: "mv-apply-conflict-list" });
    for (const row of rows.values()) {
      const where = `${row.track} · ${row.clip} (${Number(row.start).toFixed(2)}s) · ${CLIP_FIELDS[row.field] ? t(CLIP_FIELDS[row.field]) : row.field}`;
      // "loaded" is the value the project agreed on with the game: as loaded, or as this project last applied it.
      const label = row.basis === "applied" ? "{where}: last applied {loaded} → project {project}, game {game}" :
        "{where}: loaded {loaded} → project {project}, game {game}";
      list.append(make("li", format(label, { where, loaded: row.loaded, project: row.project, game: row.game }) +
        (row.platforms.length === 1 ? " · " + platformName(row.platforms[0]) : "")));
    }
    wrap.append(list, make("p", t("Nothing was overwritten. Use Apply all to replace the game's version with this project, or load the MV from the game again."), { class: "mv-field-note" }));
    return wrap;
  }

  function actions(plan) {
    const row = make("div", null, { class: "mv-controls mv-register-actions", id: "mv-apply-actions" });
    const busy = !!state.job || !!state.planning || stale();
    const edits = button("Apply only the edits", () => submit("edits"), { id: "mv-apply-edits", class: "primary" });
    const all = button("Apply all", () => submit("all"), { id: "mv-apply-all" });
    edits.disabled = busy || blocked(plan, "edits");
    all.disabled = busy || blocked(plan, "all");
    row.append(edits, all);
    if (plan.restore && plan.restore.available) {
      const restore = button("Restore the original MV", () => submit("restore"), { id: "mv-apply-restore" });
      restore.disabled = busy || blocked(plan, "restore");
      row.append(restore);
    }
    const wrap = make("div", null, { class: "mv-apply-actions-wrap" });
    wrap.append(row, make("p", t(plan.managedRestart ? "The game server stops for a moment while the game catalog is written." :
      "Restart the game server after applying."), { class: "mv-field-note" }));
    return wrap;
  }

  function confirmBox() {
    const confirm = state.confirm;
    const dialog = make("div", null, { class: "mv-register-confirm", role: "alertdialog", id: "mv-apply-confirm", tabindex: "-1",
      "aria-label": t(confirm.message) });
    const row = make("div", null, { class: "mv-controls" });
    row.append(button("Continue", () => {
      const { mode, platforms } = state.confirm;
      state.confirm = null;
      if (platforms) state.consent = platforms;
      submit(mode, true);
    }, { id: "mv-apply-confirm-yes" }), button("Cancel", () => { state.confirm = null; draw(); }, { id: "mv-apply-confirm-no" }));
    dialog.append(make("p", t(confirm.message)), row);
    return dialog;
  }

  function serverNote(restart) {
    return { done: "The game server was restarted.", pending: "The game server restarts when this job finishes.",
      manual: "Restart the game server to apply it.", stopped: "The game server was stopped. Start it again." }[restart] || "";
  }

  // Once the job stops the game server it writes the catalog and restarts the server: no cancel.
  const COMMITTING = ["stop", "write", "restore", "restart"];

  function progressBox() {
    const job = state.job, wrap = make("div", null, { class: "mv-register-progress", id: "mv-apply-job" });
    const bar = make("progress", null, { id: "mv-apply-progress", max: String(Math.max(1, job.total)) });
    bar.value = Math.min(job.total, job.index);
    const row = make("div", null, { class: "mv-controls" });
    const cancel = button("Cancel", cancelJob, { id: "mv-apply-cancel" });
    cancel.disabled = COMMITTING.includes(job.key);
    row.append(make("span", t(job.stage) + "…", { id: "mv-apply-stage", "aria-live": "polite" }), cancel);
    wrap.append(bar, row);
    return wrap;
  }

  function resultBox(result) {
    const wrap = make("div", null, { class: "mv-register-result", id: "mv-apply-result", role: "status" });
    const title = result.target && (result.target.title || result.target.liveId);
    if (!result.changed) wrap.append(make("p", t("No changes to apply.")));
    else wrap.append(make("p", "✔ " + format(result.mode === "restore" ? "Restored the original MV: {title}." : "Applied to the game: {title}.", { title })));
    const server = serverNote(result.restart);
    if (server) wrap.append(make("p", t(server), { id: "mv-apply-result-server" }));
    for (const warning of result.warnings || []) wrap.append(make("p", t(warning), { class: "mv-field-note" }));
    if (result.backup) wrap.append(make("p", format("Backup: {path}", { path: result.backup }), { class: "mv-field-note mv-register-path" }));
    return wrap;
  }

  // ---- toolbar shortcut -----------------------------------------------------------------------
  function syncShortcut() {
    if (!shortcut) return;
    const project = ctx && ctx.project();
    shortcut.hidden = !(project && project.nativeTimeline);
    shortcut.disabled = !!state.job;
  }

  function mountShortcut() {
    const anchor = document.getElementById("mv-export-timeline");
    if (!anchor || document.getElementById("mv-apply-open")) return;
    shortcut = document.createElement("button");
    shortcut.type = "button";
    shortcut.id = "mv-apply-open";
    shortcut.hidden = true;
    shortcut.dataset.i18n = "Apply to game";
    shortcut.textContent = t("Apply to game");
    shortcut.addEventListener("click", () => {
      const panel = document.getElementById("mv-panel-" + KEY);
      if (!panel) return;
      panel.hidden = false;
      panel.open = true;
      panel.scrollIntoView({ block: "nearest" });
    });
    anchor.after(shortcut);
  }

  const STYLE = `
#mv-panel-apply .mv-apply-summary { display: grid; gap: 2px; }
#mv-panel-apply .mv-apply-summary p { margin: 0; overflow-wrap: anywhere; }
#mv-panel-apply .mv-apply-conflict-list { margin: 0; padding-inline-start: 1.2em; display: grid; gap: 2px; overflow-wrap: anywhere; }
#mv-panel-apply .mv-apply-actions-wrap { display: grid; gap: 4px; }
#mv-panel-apply .mv-apply-actions-wrap p { margin: 0; }
`;

  const plugin = {
    id: "mv-studio-apply",
    order: 85,
    attach(context) {
      ctx = context;
      if (!document.getElementById("mv-apply-style")) {
        const style = document.createElement("style");
        style.id = "mv-apply-style";
        style.textContent = STYLE;
        document.head.append(style);
      }
      mountShortcut();
    },
    panels: [{
      key: KEY,
      name: "Apply to game",
      open: false,
      available: (context) => !!context.project(),
      render(element) {
        if (box !== element) {
          box = element;
          const panel = element.closest("details");
          if (panel) panel.addEventListener("toggle", () => {
            if (panel.open && (!state.plan || stale()) && !state.planning) runPlan();
          });
        }
        if (shortcut) shortcut.textContent = t("Apply to game");
        draw();
      },
    }],
    projectChanged(context, { reason }) {
      if (reason === "load") {
        if (state.planning) state.planning.abort();
        clearTimeout(state.timer);
        state = fresh();
        draw();
        if (open()) runPlan();
        return;
      }
      state.revision++;
      draw();
      schedulePlan(reason === "history" ? 1000 : 0);
    },
  };

  // Every UI string of this module (English sources of webtools/i18n.py).
  const STRINGS = Object.freeze([
    "Apply to game", "Apply only the edits", "Apply all", "Restore the original MV", "No MV is open.",
    "Checking the game's timeline…", "Open this panel to check the game's timeline.", "Load the MV from the game to apply it.",
    "Register as a new MV-only song…", "MV-only song: {title} ({id})", "Game MV: {title} ({id})",
    "In the game: MV Studio version {revision} ({date})", "In the game: the original MV", "Loaded from: the registered song",
    "Loaded from: MV Studio version {revision}", "Loaded from: an MV Studio version", "Loaded from: the original MV",
    "This MV also plays in the 3D live of {count} songs: {titles}", "The song's 3D live plays this MV too.",
    "The game's MV changed after this project was loaded. Apply only the edits keeps those changes; Apply all replaces them.",
    "Edits: none since the last apply", "Edits: none since loading",
    "Edits since the last apply: {clips} clips (camera {camera} · values {values} · timing {timing})",
    "Edits since loading: {clips} clips (camera {camera} · values {values} · timing {timing})",
    "These edits are not in {platform} yet.", "Apply all: the game already plays this project.", "Apply all: the game plays the original MV again.",
    "Apply all: {clips} clips differ from the original MV", "Download (about {size} MB)", "No {platform} original",
    "Not in the game:", "Changed differently in the game ({count})", "{where}: loaded {loaded} → project {project}, game {game}",
    "{where}: last applied {loaded} → project {project}, game {game}",
    "Nothing was overwritten. Use Apply all to replace the game's version with this project, or load the MV from the game again.",
    "The game server stops for a moment while the game catalog is written.", "Restart the game server after applying.",
    "Restore the original MV? The MV Studio version {revision} stays in a backup.",
    "Apply all replaces the game's MV Studio version {revision} with this project. A backup is made first. Continue?",
    "Apply all writes this whole project over the game's original MV. A backup is made first. Continue?",
    "Android and iOS keep the MV they play now. Continue?", "iOS keeps the MV it plays now. Continue?",
    "Android keeps the MV it plays now. Continue?", "Continue", "Cancel", "Preparing the project",
    "The game server was restarted.", "The game server restarts when this job finishes.", "Restart the game server to apply it.",
    "The game server was stopped. Start it again.", "No changes to apply.", "Restored the original MV: {title}.",
    "Applied to the game: {title}.", "Backup: {path}", "Applying to the game was cancelled.",
    "MV registration progress is unavailable. Reopen this page.", "MV registration progress was interrupted. Check the songs list.",
    "Some editor changes are not baked into the timeline yet. Wait for them to finish, then register again.",
    "Start time (s)", "Duration (s)", "Clip name",
  ]);

  global.MVStudioApply = Object.freeze({ STRINGS, platformsFor: (plan, mode) => platformsFor(plan, mode) });
  (global.MVStudioPlugins = global.MVStudioPlugins || []).push(plugin);
})(window);
