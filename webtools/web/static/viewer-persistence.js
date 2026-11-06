/* Source-bound body edits. Saving always creates copies and a portable recipe. */
(function (global) {
  "use strict";
  var MAX_RECIPE_BYTES = 1024 * 1024;
  function element(id) { return document.getElementById(id); }
  function basename(path) { return String(path).replace(/\\/g, "/").split("/").pop(); }
  function paths(value) { return Array.isArray(value) ? value.filter(function (path) { return typeof path === "string" && path && path.length < 4096; }) : []; }
  function samePaths(left, right) { return JSON.stringify(left || []) === JSON.stringify(right || []); }
  function create(options) {
    var translate = options.translate, disposed = false, busy = false, status = "idle", statusKey = "Open a model to save body edits.", error = "";
    var result = null, resultModelId = "", resultSourcePaths = [], sourceInspection = null, authoringInspection = null, reviewingSaved = false, jobId = "", eventSource = null, requestController = null;
    var outputPaths = [], previewPaths = [], originalPaths = [], recipePath = "", events = [], lastContextId = "", lastAuthoringFingerprint = "";
    var progress = element("viewer-save-progress"), cancel = element("viewer-save-cancel");
    function context() { return options.context() || {}; }
    function state() {
      return { available: !!((context().editing || {}).available), busy: busy, status: status, error: error,
        outputs: outputPaths.slice(), outputPaths: outputPaths.slice(), previewPaths: previewPaths.slice(), originalPaths: originalPaths.slice(),
        recipePath: recipePath, resultModelId: resultModelId, reviewingSaved: reviewingSaved, jobId: jobId };
    }
    function listen(id, name, fn) {
      var target = element(id); if (!target) return;
      target.addEventListener(name, fn); events.push(function () { target.removeEventListener(name, fn); });
    }
    function say(key, next, detail) {
      statusKey = key; status = next || status; error = next === "error" ? detail || key : "";
      var target = element("viewer-save-status");
      target.textContent = translate(key) + (detail && detail !== key ? " " + translate(detail) : "");
      target.classList.toggle("viewer-save-error", !!error); refresh();
    }
    function setBusy(value) {
      busy = !!value;
      if (progress) { progress.hidden = !busy; progress.removeAttribute("value"); }
      if (cancel) cancel.hidden = !busy;
      if (options.busyChanged) options.busyChanged(busy);
      refresh();
    }
    function editingState() {
      var c = context();
      return c.rig && c.rig.getAuthoringState ? c.rig.getAuthoringState() : { version: 1, edits: [], unsupported: [] };
    }
    function refresh() {
      if (disposed) return;
      var c = context(), metadata = c.editing || {}, rigState = c.rig && c.rig.getState ? c.rig.getState() : {};
      if (lastContextId !== c.modelId) {
        lastContextId = c.modelId || "";
        reviewingSaved = !!(previewPaths.length && samePaths(c.loadedPaths, previewPaths));
      }
      if (c.rig && c.rig.setAuthoringEnabled) c.rig.setAuthoringEnabled(!reviewingSaved);
      element("viewer-save-status").classList.toggle("viewer-save-error", !!error);
      var ready = !!(c.current && metadata.available && metadata.token && c.rig), authoring = ready && !busy && !reviewingSaved;
      var authored = editingState(), fingerprint = JSON.stringify(authored);
      if (lastAuthoringFingerprint && lastAuthoringFingerprint !== fingerprint && !busy && ["done", "restored", "error"].indexOf(status) >= 0) { status = "ready"; error = ""; }
      lastAuthoringFingerprint = fingerprint;
      element("viewer-save").disabled = !authoring || !authored.edits.length || !!(authored.unsupported && authored.unsupported.length);
      element("viewer-save").title = authored.unsupported && authored.unsupported.length ? translate(authored.unsupported[0]) : "";
      element("viewer-recipe-open").disabled = !authoring;
      element("viewer-open-saved").hidden = !previewPaths.length;
      element("viewer-open-saved").disabled = busy || !c.current;
      element("viewer-reedit-original").hidden = !originalPaths.length || !result || !result.recipe;
      element("viewer-reedit-original").disabled = busy;
      var method = element("viewer-save-method"), selected = String(rigState.selectedNode || "");
      var target = (metadata.nodes || []).filter(function (node) { return String(node.node) === selected; })[0];
      method.disabled = !authoring || !target;
      method.value = rigState.editingMethods && rigState.editingMethods[selected] || "auto";
      Array.prototype.forEach.call(method.options, function (option) {
        option.disabled = option.value !== "auto" && (!target || (target.methods || ["node", "mesh"]).indexOf(option.value) < 0);
      });
      element("viewer-save-selected").textContent = target ? translate("Selected bone") + ": " + target.name : translate("Choose a bone in Individual bones to set its save method.");
      var recommendation = target && (target.recommendedMethod || target.recommended_method);
      element("viewer-save-method-status").textContent = target ? translate("Scale recommendation") + ": " + translate(recommendation === "mesh" ? "Bake into mesh" : recommendation === "choose" ? "Choose a save method" : "Node scaling") + (target.reason ? " · " + translate(target.reason) : "") + (method.value === "mesh" ? " · " + translate("The current scale will be saved into the mesh, including existing node scaling.") : "") : "";
      var counts = { node: 0, mesh: 0 };
      authored.edits.forEach(function (edit) {
        var entry = (metadata.nodes || []).filter(function (target) { return target.node === edit.node; })[0];
        var resolved = edit.method === "auto" ? edit.compensate ? "mesh" : entry && entry.recommendedMethod : edit.method;
        if (counts[resolved] !== undefined) counts[resolved] += 1;
      });
      ["node", "mesh"].forEach(function (tool) { var count = element("viewer-editor-" + tool + "-count"); if (count) count.textContent = String(counts[tool]); });
      var group = rigState.editorGroup || "node";
      if (target && method.value !== "auto" && method.value !== group) element("viewer-save-method-status").textContent += " · " + translate("This bone keeps its existing save method when switching tools.");
      var hasMesh = authored.edits.some(function (edit) {
        var entry = (metadata.nodes || []).filter(function (target) { return target.node === edit.node; })[0];
        return edit.method === "mesh" || edit.method === "auto" && (edit.compensate || entry && entry.recommendedMethod === "mesh");
      });
      var resultNote = element("viewer-save-result-note");
      if (resultNote) { resultNote.hidden = !hasMesh || reviewingSaved; resultNote.textContent = translate("Baked results can differ while moving. Open the saved result to check the exported model."); }
      var evaluation = rigState.evaluation || {};
      var selector = element("viewer-edit-evaluation"); selector.disabled = !c.current || !c.rig || busy; selector.value = evaluation.mode || "authoring";
      var evaluationText = translate(evaluation.mode === "animation" ? "Checks loaded motion tracks against node edits. Open the saved result to inspect mesh changes." : "Editing values are shown after motion. They may differ from game playback.");
      if (evaluation.mode === "animation") evaluationText += evaluation.hasMotion ? " " + translate("Loaded motion scale targets") + ": " + (evaluation.scaleTargets || []).length + "." : " " + translate("No motion is selected.");
      if (rigState.restoredCompensationReference) evaluationText += " " + translate("The recipe's saved child-compensation baseline is retained.");
      element("viewer-edit-evaluation-status").textContent = evaluationText;
      if (!busy && !error && ["idle", "ready", "reviewing"].indexOf(status) >= 0) {
        var key = reviewingSaved ? "Reviewing the saved copy. Re-edit from original to continue." : !ready ? (c.current ? "Body saving is unavailable for this model." : "Open a model to save body edits.") : authored.unsupported && authored.unsupported.length ? authored.unsupported[0] : "Body changes";
        statusKey = key; status = reviewingSaved ? "reviewing" : ready ? "ready" : "idle";
        element("viewer-save-status").textContent = translate(key) + (key === "Body changes" ? ": " + authored.edits.length : "");
      }
      element("viewer-save-status").classList.toggle("viewer-save-error", !!error);
    }
    async function jsonRequest(url, body, signal) {
      var response = await global.fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: signal });
      var data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || "The body edits could not be saved.");
      return data;
    }
    function awaitJob(id, signal) {
      return new Promise(function (resolve, reject) {
        var settled = false, timer = null;
        function close() { if (timer) global.clearTimeout(timer); if (eventSource) eventSource.close(); eventSource = null; signal.removeEventListener("abort", aborted); }
        function fail(message) { if (settled) return; settled = true; close(); reject(new Error(message)); }
        function aborted() { fail("Saving cancelled."); }
        signal.addEventListener("abort", aborted);
        if (!global.EventSource) { fail("Save progress is unavailable. Reopen this page and try again."); return; }
        eventSource = new global.EventSource("/api/jobs/" + encodeURIComponent(id) + "/events");
        eventSource.onmessage = function (event) {
          if (disposed || settled) return;
          if (timer) { global.clearTimeout(timer); timer = null; }
          var item;
          try { item = JSON.parse(event.data); } catch (_) { fail("The save response is invalid."); return; }
          if (item.type === "progress" && progress && Number.isFinite(item.total) && item.total > 0) {
            progress.max = item.total; progress.value = Math.max(0, Math.min(item.total, Number(item.done) || 0));
          }
          if (item.type === "done") {
            settled = true; close();
            if (item.status === "done") resolve(item);
            else reject(new Error(item.summary || (item.status === "cancelled" ? "Saving cancelled." : "The body edits could not be saved.")));
          }
        };
        eventSource.onerror = function () {
          if (settled || disposed || timer) return;
          say("Reconnecting to save progress…", "saving");
          timer = global.setTimeout(function () { fail("Save progress was interrupted. Your original files are unchanged."); }, 30000);
        };
      });
    }
    function renderOutputs() {
      var list = element("viewer-save-output-list"); list.textContent = ""; list.hidden = !outputPaths.length;
      outputPaths.forEach(function (path) {
        var item = document.createElement("li"), link = document.createElement("a");
        link.textContent = basename(path); link.href = "/api/download?path=" + encodeURIComponent(path); link.setAttribute("download", basename(path));
        item.appendChild(link);
        if (global.ElichikaPlatform && global.ElichikaPlatform.supports("reveal")) {
          var reveal = document.createElement("button");
          reveal.type = "button"; reveal.className = "viewer-reveal"; reveal.textContent = translate("Show in Finder");
          reveal.addEventListener("click", function () {
            global.ElichikaPlatform.request("reveal", { path: path }).catch(function (error) {
              if (global.ElichikaPlatform.supports("reveal")) global.alert(translate(String(error.message || error)));
            });
          });
          item.appendChild(reveal);
        }
        list.appendChild(item);
      });
    }
    function canonicalBody(input, metadata) {
      function numeric(value) { return typeof value === "number" ? Number(value.toPrecision(10)) : value; }
      function vector(values) { return values.map(numeric); }
      var canonical = { version: input.version, savedSettingsEnabled: input.savedSettingsEnabled,
        edits: (input.edits || []).map(function (edit) {
          var target = ((metadata || {}).nodes || []).filter(function (entry) { return entry.node === edit.node; })[0];
          var method = edit.method === "auto" ? edit.compensate ? "mesh" : target && target.recommendedMethod || "auto" : edit.method;
          var value = { node: edit.node, method: method, compensate: !!edit.compensate };
          ["scale", "position", "rotation"].forEach(function (kind) { if (edit[kind]) value[kind] = vector(edit[kind]); });
          if (edit.compensate) value.compensationTargets = (edit.compensationTargets || []).slice().sort(function (a, b) { return a - b; });
          return value;
        }).sort(function (a, b) { return a.node - b.node; }) };
      if (canonical.edits.some(function (edit) { return edit.compensate; })) canonical.compensationReference = (input.compensationReference || []).map(function (entry) {
        return { node: entry.node, scale: vector(entry.scale), position: vector(entry.position), rotation: vector(entry.rotation) };
      }).sort(function (a, b) { return a.node - b.node; });
      return JSON.stringify(canonical);
    }
    async function save() {
      if (busy || disposed) return;
      var c = context(), authored = editingState();
      if (!c.current || !c.editing || !c.editing.available || reviewingSaved) { say("Open the original model before saving body edits.", "error"); return; }
      if (authored.unsupported && authored.unsupported.length) { say(authored.unsupported[0], "error"); return; }
      if (!authored.edits.length) { say("Change a body value before saving.", "error"); return; }
      var body = JSON.parse(JSON.stringify(authored)); delete body.unsupported;
      var modelId = c.modelId, token = c.editing.token, sourcePaths = (c.loadedPaths || []).slice();
      var inspection = options.captureInspection ? options.captureInspection() : null;
      requestController = new global.AbortController(); var signal = requestController.signal;
      setBusy(true); say("Saving a new costume copy…", "saving");
      try {
        var response = await jsonRequest("/api/viewer/edit/export", { token: token, state: body }, signal);
        if (typeof response.job_id !== "string" || !/^[a-zA-Z0-9_-]{1,64}$/.test(response.job_id)) throw new Error("The save response is invalid.");
        jobId = response.job_id;
        await awaitJob(jobId, signal);
        var request = await global.fetch("/api/viewer/edit/result/" + encodeURIComponent(jobId), { signal: signal });
        var data = await request.json();
        if (!request.ok || data.error) throw new Error(data.error || "The save result is unavailable.");
        var savedPaths = paths(data.output_paths), models = paths(data.preview_paths);
        if (!savedPaths.length || !models.length || typeof data.recipe_path !== "string") throw new Error("The save response is invalid.");
        result = data; resultSourcePaths = sourcePaths; sourceInspection = inspection; authoringInspection = inspection; outputPaths = savedPaths; previewPaths = models; originalPaths = paths(data.original_paths); recipePath = data.recipe_path; resultModelId = modelId;
        if (outputPaths.indexOf(recipePath) < 0) outputPaths.push(recipePath);
        renderOutputs();
        say(context().modelId === modelId ? "Saved. Open the saved result to verify it." : "Saved the previous model. The current preview was not changed.", "done");
      } catch (failure) {
        if (!disposed) say(failure && failure.name === "AbortError" ? "Saving cancelled." : failure.message || "The body edits could not be saved.", "error");
      } finally { requestController = null; if (!disposed) setBusy(false); }
    }
    async function readRecipe(path) {
      if (typeof path !== "string" || !/\.json$/i.test(path)) throw new Error("Choose a saved body edit recipe JSON file.");
      var response = await global.fetch("/api/download?path=" + encodeURIComponent(path));
      if (!response.ok) throw new Error("The edit recipe could not be opened.");
      var length = Number(response.headers.get("Content-Length"));
      if (!Number.isFinite(length) || length <= 0 || length > MAX_RECIPE_BYTES) throw new Error("The edit recipe is too large or empty.");
      var raw = await response.arrayBuffer();
      if (raw.byteLength > MAX_RECIPE_BYTES) throw new Error("The edit recipe is too large or empty.");
      try { return JSON.parse(new global.TextDecoder("utf-8", { fatal: true }).decode(raw)); }
      catch (_) { throw new Error("The body edit recipe is invalid."); }
    }
    async function restoreRecipe(recipe) {
      var c = context();
      if (!c.current || !c.editing || !c.editing.token || reviewingSaved) throw new Error("Open the original model before loading its recipe.");
      var modelId = c.modelId, response = await jsonRequest("/api/viewer/edit/restore", { token: c.editing.token, recipe: recipe });
      if (!context().current || context().modelId !== modelId) throw new Error("The model changed while its recipe was loading. Try again.");
      if (!response.state) throw new Error("The body edit recipe is invalid.");
      c.rig.restoreAuthoringState(response.state); say("Edit recipe restored from the original model.", "restored");
    }
    function pickRecipe() {
      if (busy || disposed || reviewingSaved) return;
      options.pickFile(async function (path) {
        if (busy || disposed) return;
        setBusy(true); say("Loading edit recipe…", "saving");
        try { await restoreRecipe(await readRecipe(path)); }
        catch (failure) { if (!disposed) say(failure.message, "error"); }
        finally { if (!disposed) setBusy(false); }
      });
    }
    async function openSaved() {
      if (busy || !previewPaths.length) return;
      var c = context(), current = editingState();
      var ownOriginal = samePaths(c.loadedPaths, resultSourcePaths) || samePaths(c.loadedPaths, originalPaths);
      if (!reviewingSaved && current.edits.length && (!ownOriginal || !result || !result.recipe ||
          canonicalBody(current, c.editing) !== canonicalBody(result.recipe.state || {}, c.editing))) {
        say("Save current body changes before opening the saved result.", "error"); return;
      }
      authoringInspection = ownOriginal && options.captureInspection ? options.captureInspection() : sourceInspection;
      setBusy(true);
      try {
        await options.openFiles(previewPaths.slice(), result && result.preview_variants);
        reviewingSaved = samePaths(context().loadedPaths, previewPaths);
        if (!reviewingSaved) throw new Error("The saved model could not be opened.");
        if (context().rig) context().rig.setEvaluationMode("animation");
        say("Reviewing the saved copy. Re-edit from original to continue.", "reviewing");
      } catch (failure) { say(failure.message, "error"); }
      finally { setBusy(false); }
    }
    async function reeditOriginal() {
      if (busy || !result || !result.recipe || !originalPaths.length) return;
      var recipe = result.recipe, originals = originalPaths.slice();
      setBusy(true); say("Opening the original model and edit recipe…", "saving");
      try {
        await options.openFiles(originals, result.original_variants, authoringInspection || sourceInspection);
        reviewingSaved = false;
        if (!samePaths(context().loadedPaths, originals)) throw new Error("The original model could not be opened.");
        await restoreRecipe(recipe);
      } catch (failure) { say(failure.message, "error"); }
      finally { setBusy(false); }
    }
    // Invalid number inputs intentionally do not update the last valid edit.
    // Observe their bubbled events as well, so Save cannot export stale values.
    ["viewer-adjustments", "viewer-body-adjustments"].forEach(function (id) {
      listen(id, "input", function (event) {
        // A select emits input before change. Refreshing its value here would
        // overwrite the new save-method choice before its change handler runs.
        if (event.target && event.target.matches("#viewer-node-fields input[type='number'], #viewer-skirt-number")) refresh();
      });
      listen(id, "change", refresh);
    });
    listen("viewer-save", "click", save);
    listen("viewer-recipe-open", "click", pickRecipe);
    listen("viewer-open-saved", "click", openSaved);
    listen("viewer-reedit-original", "click", reeditOriginal);
    listen("viewer-save-method", "change", function () {
      var c = context(), selected = c.rig && c.rig.getState().selectedNode;
      if (selected) c.rig.setEditingMethod(selected, this.value);
      refresh();
    });
    listen("viewer-edit-evaluation", "change", function () { var c = context(); if (c.rig) c.rig.setEvaluationMode(this.value); refresh(); });
    listen("viewer-save-cancel", "click", function () {
      if (jobId) global.fetch("/api/jobs/" + encodeURIComponent(jobId) + "/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(function () {});
      if (requestController) requestController.abort();
    });
    refresh();
    return { refresh: refresh, getState: state, restoreRecipe: restoreRecipe,
      updateLanguage: function () { renderOutputs(); element("viewer-save-status").textContent = translate(statusKey); refresh(); },
      dispose: function () {
        disposed = true; if (requestController) requestController.abort(); if (eventSource) eventSource.close();
        events.forEach(function (remove) { remove(); });
      } };
  }
  global.ViewerPersistence = { create: create };
})(window);
