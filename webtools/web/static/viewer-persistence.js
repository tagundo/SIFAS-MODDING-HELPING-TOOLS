/* Source-bound body edits. Saving always creates copies and a portable recipe. */
(function (global) {
  "use strict";
  var MAX_RECIPE_BYTES = 1024 * 1024;
  function element(id) { return document.getElementById(id); }
  function basename(path) { return String(path).replace(/\\/g, "/").split("/").pop(); }
  function paths(value) { return Array.isArray(value) ? value.filter(function (path) { return typeof path === "string" && path && path.length < 4096; }) : []; }
  function samePaths(left, right) { return JSON.stringify(left || []) === JSON.stringify(right || []); }
  function create(options) {
    var translate = options.translate, disposed = false, busy = false, installing = false, status = "idle", statusKey = "Open a model to save body edits.", error = "";
    var result = null, resultModelId = "", resultSourcePaths = [], sourceInspection = null, authoringInspection = null, reviewingSaved = false, jobId = "", eventSource = null, requestController = null;
    var outputPaths = [], previewPaths = [], originalPaths = [], recipePath = "", events = [], lastContextId = "", lastAuthoringFingerprint = "";
    var modContext = "", manualModName = false, counterpartPath = "", modCharacters = "", lastPackage = null;
    var suggestedNameKey = "", suggestedName = "";
    var installedFingerprint = "", alreadyAdded = false;
    var progress = element("viewer-save-progress"), cancel = element("viewer-save-cancel");
    function context() { return options.context() || {}; }
    function state() {
      return { available: !!((context().editing || {}).available), busy: busy, installing: installing, alreadyAdded: alreadyAdded, status: status, error: error,
        outputs: outputPaths.slice(), outputPaths: outputPaths.slice(), previewPaths: previewPaths.slice(), originalPaths: originalPaths.slice(),
        recipePath: recipePath, resultModelId: resultModelId, reviewingSaved: reviewingSaved, jobId: jobId,
        modName: element("viewer-mod-name").value, modNameManual: manualModName,
        modPackage: lastPackage ? { packagePath: lastPackage.package_path, characterId: lastPackage.character_id,
          variants: lastPackage.variants || [] } : null };
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
      if (cancel) { cancel.hidden = !busy || installing; cancel.disabled = installing; }
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
      if (lastAuthoringFingerprint && lastAuthoringFingerprint !== fingerprint) lastPackage = null;
      if (lastAuthoringFingerprint && lastAuthoringFingerprint !== fingerprint && !busy && ["done", "restored", "error"].indexOf(status) >= 0) { status = "ready"; error = ""; }
      lastAuthoringFingerprint = fingerprint;
      element("viewer-save").disabled = !authoring || !authored.edits.length || !!(authored.unsupported && authored.unsupported.length);
      element("viewer-save").title = authored.unsupported && authored.unsupported.length ? translate(authored.unsupported[0]) : "";
      refreshModForm(c, rigState, authored, authoring);
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
    function modContextKey(c) { return JSON.stringify([c.modelId || "", (c.editing || {}).token || "", c.loadedPaths || []]); }
    function suggestedModName(c, rigState, authored) {
      var metadata = c.editing || {}, packaging = metadata.modPackaging || {};
      var base = packaging.nameBase || basename((c.loadedPaths || [])[0] || "Costume").replace(/\.[^.]+$/, "");
      var groups = {}, entries = metadata.nodes || [], profile = rigState.thighProfile || {};
      function format(value) { return String(Number(value.toPrecision(4))); }
      function sameVector(left, right) { return left && right && left.length === right.length && left.every(function (value, i) { return Math.abs(value - right[i]) <= 1e-7; }); }
      (authored.edits || []).forEach(function (edit) {
        var target = entries.filter(function (entry) { return entry.node === edit.node; })[0];
        if (!target) return;
        var name = target.name, kind = name === "BreastSize" ? "breast" : name === "HipsSize" ? "hips" : /^(Left|Right)UpLeg$/.test(name) ? "thighs" : name === "Spine" ? "waist" : /skirt/i.test(name) ? "skirt" : name;
        var group = groups[kind] || (groups[kind] = []); group.push({ edit: edit, target: target });
      });
      var details = Object.keys(groups).map(function (kind) {
        var values = groups[kind], label = { breast: "Breast size", hips: "Hip size", thighs: "Thigh thickness", waist: "Waist thickness", skirt: "Skirt" }[kind] || kind;
        if (kind === "thighs" && values.length === 1) label = values[0].target.name === "LeftUpLeg" ? "Left thigh" : "Right thigh";
        var preset = kind === "thighs" && (profile.presets || []).filter(function (entry) { return entry.id === profile.selected; })[0];
        function extraTransforms() {
          var extra = [];
          if (values.some(function (value) { return !!value.edit.position; })) extra.push(translate("Position"));
          if (values.some(function (value) { return !!value.edit.rotation; })) extra.push(translate("Rotation"));
          return extra.length ? " " + extra.join(" ") : "";
        }
        if (preset && values.length === (profile.targets || []).length) return translate(label) + " " + translate(preset.sourceLabel) + "→" + translate(preset.targetLabel) + extraTransforms();
        var breast = kind === "breast" && ((rigState.scaling || {}).controls || []).filter(function (entry) { return entry.id === "breast"; })[0];
        preset = breast && (breast.presets || []).filter(function (entry) {
          return entry.id === (rigState.body || {}).breastPreset && values.every(function (value) { return sameVector(value.edit.scale, entry.scale); });
        })[0];
        if (preset) return translate(label) + " " + translate(preset.label) + extraTransforms();
        var transforms = values.map(function (value) {
          var edit = value.edit, baseline = value.target.baseline || {}, tags = [];
          if (edit.scale && baseline.scale) {
            var ratios = edit.scale.map(function (part, axis) { return baseline.scale[axis] ? part / baseline.scale[axis] : null; });
            var axes = ratios.map(function (part, axis) { return part !== null && Math.abs(part - 1) > 1e-7 ? axis : -1; }).filter(function (axis) { return axis >= 0; });
            if (axes.length) {
              var uniform = axes.length === 3 && axes.every(function (axis) { return Math.abs(ratios[axis] - ratios[0]) < 1e-7; }) ||
                (kind === "thighs" || kind === "waist") && axes.join(",") === "1,2" && Math.abs(ratios[1] - ratios[2]) < 1e-7;
              tags.push(uniform ? format(ratios[axes[0]]) + "×" : axes.map(function (axis) { return "XYZ"[axis] + format(ratios[axis]); }).join("/"));
            } else tags.push(translate("Bake into mesh"));
          }
          if (edit.position) tags.push(translate("Position"));
          if (edit.rotation) tags.push(translate("Rotation"));
          return tags.join(" ");
        });
        return translate(label) + " " + (transforms.every(function (part) { return part === transforms[0]; }) ? transforms[0] : translate("Custom adjustment"));
      });
      return [base].concat(details).join(" · ").slice(0, 120).replace(/[\uD800-\uDBFF]$/, "");
    }
    function refreshModForm(c, rigState, authored, authoring) {
      var key = modContextKey(c), metadata = (c.editing || {}).modPackaging || {};
      if (key !== modContext) {
        modContext = key; manualModName = false; counterpartPath = ""; lastPackage = null; installedFingerprint = "";
        element("viewer-mod-character").value = ""; element("viewer-mod-variant").value = "";
        element("viewer-mod-target").open = !!metadata.requiresCounterpart;
      }
      var name = element("viewer-mod-name");
      if (!manualModName) {
        // Motion time and camera updates do not change the exported edits.
        // Reuse their suggestion instead of regrouping every rig node again.
        var nameKey = JSON.stringify([key, metadata.nameBase, lastAuthoringFingerprint,
          (rigState.thighProfile || {}).selected, (rigState.body || {}).breastPreset, translate("Mod name")]);
        if (nameKey !== suggestedNameKey) { suggestedNameKey = nameKey; suggestedName = suggestedModName(c, rigState, authored); }
        name.value = suggestedName;
      }
      var choices = metadata.characters || [], choicesKey = JSON.stringify([choices, metadata.characterId, translate("Automatic")]);
      var characters = element("viewer-mod-character");
      if (choicesKey !== modCharacters) {
        var selected = characters.value; modCharacters = choicesKey; characters.textContent = "";
        var automatic = document.createElement("option"); automatic.value = ""; automatic.textContent = translate("Automatic");
        var current = choices.filter(function (choice) { return String(choice.value) === String(metadata.characterId); })[0];
        if (current) automatic.textContent += " · " + current.label;
        characters.appendChild(automatic);
        choices.forEach(function (choice) {
          if (!/^[1-9][0-9]{0,3}$/.test(String(choice.value))) return;
          var option = document.createElement("option"); option.value = String(choice.value); option.textContent = choice.label; characters.appendChild(option);
        });
        characters.value = selected;
      }
      var validName = !!name.value.trim() && name.value.trim().length <= 120;
      name.disabled = !authoring; element("viewer-mod-name-auto").disabled = !authoring || !manualModName;
      characters.disabled = !authoring; element("viewer-mod-character-field").hidden = !choices.length;
      element("viewer-mod-variant").disabled = !authoring;
      element("viewer-mod-counterpart").value = counterpartPath ? basename(counterpartPath) : "";
      element("viewer-mod-counterpart").title = counterpartPath;
      element("viewer-mod-counterpart").disabled = !authoring;
      element("viewer-mod-counterpart-pick").disabled = !authoring;
      element("viewer-mod-counterpart-clear").disabled = !authoring || !counterpartPath;
      var owner = characters.value || metadata.characterId;
      element("viewer-mod-rina-fields").hidden = !!owner && Number(owner) !== 209;
      var enabled = authoring && validName && authored.edits.length && !(authored.unsupported || []).length;
      ["viewer-save-mod", "viewer-add-to-game"].forEach(function (id) { element(id).disabled = !enabled; element(id).title = element("viewer-save").title; });
      var body = Object.assign({}, authored); delete body.unsupported;
      alreadyAdded = !!installedFingerprint && installedFingerprint === JSON.stringify([key, JSON.stringify(body), JSON.stringify(modOptions())]);
      if (alreadyAdded) {
        element("viewer-add-to-game").disabled = true;
        if (!(authored.unsupported || []).length) element("viewer-add-to-game").title = translate("Already added to game. Change the edits or mod name to add another copy.");
      }
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
          if (disposed && !installing || settled) return;
          if (timer) { global.clearTimeout(timer); timer = null; }
          var item;
          try { item = JSON.parse(event.data); } catch (_) { fail("The save response is invalid."); return; }
          if (!disposed && item.type === "progress" && progress && Number.isFinite(item.total) && item.total > 0) {
            progress.max = item.total; progress.value = Math.max(0, Math.min(item.total, Number(item.done) || 0));
          }
          if (item.type === "done") {
            settled = true; close();
            if (item.status === "done") resolve(item);
            else reject(new Error(item.summary || (item.status === "cancelled" ? "Saving cancelled." : "The body edits could not be saved.")));
          }
        };
        eventSource.onerror = function () {
          if (settled || disposed && !installing || timer) return;
          if (!disposed) say("Reconnecting to save progress…", "saving");
          timer = global.setTimeout(function () { fail(installing ? "Installation progress was interrupted. Check the server console before adding it again." : "Save progress was interrupted. Your original files are unchanged."); }, 30000);
        };
      });
    }
    function renderOutputs() {
      var list = element("viewer-save-output-list"); list.textContent = ""; list.hidden = !outputPaths.length;
      var modPath = result && result.mod_package && result.mod_package.package_path;
      var displayed = modPath && outputPaths.indexOf(modPath) >= 0 ? [modPath].concat(outputPaths.filter(function (path) { return path !== modPath; })) : outputPaths;
      displayed.forEach(function (path) {
        var item = document.createElement("li"), link = document.createElement("a");
        var label = modPath ? path === modPath ? "Mod ZIP" : path === recipePath ? "Edit recipe" : previewPaths.indexOf(path) >= 0 ? "Edited preview copy" : "" : "";
        link.textContent = (label ? translate(label) + " · " : "") + basename(path);
        link.href = "/api/download?path=" + encodeURIComponent(path); link.setAttribute("download", basename(path));
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
    function captureSave() {
      var c = context(), authored = editingState();
      if (!c.current || !c.editing || !c.editing.available || reviewingSaved) throw new Error("Open the original model before saving body edits.");
      if (authored.unsupported && authored.unsupported.length) throw new Error(authored.unsupported[0]);
      if (!authored.edits.length) throw new Error("Change a body value before saving.");
      var body = JSON.parse(JSON.stringify(authored)); delete body.unsupported;
      return { body: body, modelId: c.modelId, token: c.editing.token, paths: (c.loadedPaths || []).slice(),
        contextKey: modContextKey(c), canonical: canonicalBody(body, c.editing), rawBody: JSON.stringify(body),
        inspection: options.captureInspection ? options.captureInspection() : null };
    }
    function stillCurrent(snapshot) {
      var c = context(), authored = editingState();
      var body = Object.assign({}, authored); delete body.unsupported;
      return c.current && !reviewingSaved && modContextKey(c) === snapshot.contextKey &&
        !(authored.unsupported || []).length && JSON.stringify(body) === snapshot.rawBody &&
        canonicalBody(authored, c.editing) === snapshot.canonical &&
        (!snapshot.modOptions || JSON.stringify(modOptions()) === snapshot.modOptions);
    }
    function modOptions() {
      var character = element("viewer-mod-character").value;
      return { display_name: element("viewer-mod-name").value.trim(), character_id: character ? Number(character) : null,
        counterpart_path: counterpartPath || null, selected_variant: element("viewer-mod-variant").value || null };
    }
    function modChanged() {
      lastPackage = null;
      if (installedFingerprint && !busy) { status = "ready"; error = ""; }
      refresh();
    }
    async function runJob(url, body, signal) {
      jobId = "";
      var response = await jsonRequest(url, body, signal);
      if (typeof response.job_id !== "string" || !/^[a-zA-Z0-9_-]{1,64}$/.test(response.job_id)) throw new Error("The save response is invalid.");
      jobId = response.job_id;
      await awaitJob(jobId, signal);
      var request = await global.fetch("/api/viewer/edit/result/" + encodeURIComponent(jobId), { signal: signal });
      var data = await request.json();
      if (!request.ok || data.error) throw new Error(data.error || "The save result is unavailable.");
      return data;
    }
    function rememberResult(data, snapshot) {
      var savedPaths = paths(data.output_paths), models = paths(data.preview_paths);
      if (!savedPaths.length || !models.length || typeof data.recipe_path !== "string") throw new Error("The save response is invalid.");
      result = data; resultSourcePaths = snapshot.paths; sourceInspection = snapshot.inspection; authoringInspection = snapshot.inspection;
      outputPaths = savedPaths; previewPaths = models; originalPaths = paths(data.original_paths); recipePath = data.recipe_path; resultModelId = snapshot.modelId;
      if (outputPaths.indexOf(recipePath) < 0) outputPaths.push(recipePath);
      renderOutputs();
    }
    async function save() {
      if (busy || disposed) return;
      var snapshot;
      try { snapshot = captureSave(); } catch (failure) { say(failure.message, "error"); return; }
      requestController = new global.AbortController(); var signal = requestController.signal;
      setBusy(true); say("Saving a new costume copy…", "saving");
      try {
        var data = await runJob("/api/viewer/edit/export", { token: snapshot.token, state: snapshot.body }, signal);
        rememberResult(data, snapshot); lastPackage = null;
        say(context().modelId === snapshot.modelId ? "Saved. Open the saved result to verify it." : "Saved the previous model. The current preview was not changed.", "done");
      } catch (failure) {
        if (!disposed) say(failure && failure.name === "AbortError" ? "Saving cancelled." : failure.message || "The body edits could not be saved.", "error");
      } finally { requestController = null; if (!disposed) setBusy(false); }
    }
    async function saveMod(install) {
      if (busy || disposed) return;
      var snapshot, parameters = modOptions(), name = parameters.display_name;
      try {
        snapshot = captureSave();
        if (!name || name.length > 120) throw new Error("Enter a mod name of 1 to 120 characters.");
      } catch (failure) { say(failure.message, "error"); return; }
      snapshot.modOptions = JSON.stringify(parameters);
      var binding = JSON.stringify([snapshot.contextKey, snapshot.rawBody, snapshot.modOptions]);
      if (install && installedFingerprint === binding) { say("Already added to game. Change the edits or mod name to add another copy.", "done"); return; }
      var body = Object.assign({ token: snapshot.token, state: snapshot.body }, parameters);
      requestController = new global.AbortController(); var signal = requestController.signal;
      lastPackage = null; setBusy(true); say("Saving an installer-ready mod ZIP…", "saving");
      try {
        // Each explicit action packages the current authoring snapshot. An older
        // downloaded result can never become the input to a later installation.
        var data = await runJob("/api/viewer/edit/package", body, signal), packaged = data.mod_package;
        if (!packaged || typeof packaged.token !== "string" || !/^[a-zA-Z0-9_-]{16,128}$/.test(packaged.token) ||
            packaged.installable !== true || typeof packaged.package_path !== "string" || paths(data.output_paths).indexOf(packaged.package_path) < 0) throw new Error("The mod package response is invalid.");
        rememberResult(data, snapshot);
        if (stillCurrent(snapshot)) lastPackage = packaged;
        if (!install) {
          say(stillCurrent(snapshot) ? "Mod ZIP saved. You can install it with the mod installer." : "Saved the previous model. The current preview was not changed.", "done");
          return;
        }
        // Model switching remains possible while a background job finishes.
        // Refuse the hand-off if the displayed source or valid edits changed.
        if (!stillCurrent(snapshot)) throw new Error("The model, body edits or mod settings changed. Add the current edits to game again.");
        // Installation is a server-owned database operation. Once submitted,
        // hiding the page or changing the model cannot cancel or retarget it.
        installing = true; setBusy(true); say("Adding the costume to game…", "saving");
        var installed = await runJob("/api/viewer/edit/install", { package_token: packaged.token }, signal);
        if (disposed) return;
        if (installed.installed !== true) throw new Error("The mod could not be added to game.");
        installedFingerprint = binding;
        say(stillCurrent(snapshot) ? "Added to game. Select the new costume in game." : "Added the saved mod to game. The current preview was not changed.", "done");
      } catch (failure) {
        if (!disposed) say(failure && failure.name === "AbortError" ? "Saving cancelled." : failure.message || "The mod could not be saved.", "error");
      } finally { requestController = null; installing = false; if (!disposed) setBusy(false); }
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
    listen("viewer-save-mod", "click", function () { saveMod(false); });
    listen("viewer-add-to-game", "click", function () { saveMod(true); });
    listen("viewer-mod-name", "input", function () { manualModName = true; modChanged(); });
    listen("viewer-mod-name-auto", "click", function () { manualModName = false; modChanged(); });
    ["viewer-mod-character", "viewer-mod-variant"].forEach(function (id) { listen(id, "change", modChanged); });
    listen("viewer-mod-counterpart-pick", "click", function () {
      if (busy || disposed) return;
      var key = modContextKey(context());
      options.pickFile(function (path) {
        if (busy || disposed || modContextKey(context()) !== key) return;
        if (typeof path !== "string" || !path || path.length >= 4096) return;
        counterpartPath = path; modChanged();
      });
    });
    listen("viewer-mod-counterpart-clear", "click", function () { counterpartPath = ""; modChanged(); });
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
      if (installing) return;
      if (jobId) global.fetch("/api/jobs/" + encodeURIComponent(jobId) + "/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(function () {});
      if (requestController) requestController.abort();
    });
    refresh();
    return { refresh: refresh, getState: state, restoreRecipe: restoreRecipe,
      updateLanguage: function () { renderOutputs(); element("viewer-save-status").textContent = translate(statusKey); refresh(); },
      dispose: function () {
        disposed = true;
        if (!installing) { if (requestController) requestController.abort(); if (eventSource) eventSource.close(); }
        events.forEach(function (remove) { remove(); });
      } };
  }
  global.ViewerPersistence = { create: create };
})(window);
