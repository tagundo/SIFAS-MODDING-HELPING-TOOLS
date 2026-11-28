/* Source-bound model edits. Saving always creates copies and a portable recipe. */
(function (global) {
  "use strict";
  var MAX_RECIPE_BYTES = 64 * 1024 * 1024;
  function element(id) { return document.getElementById(id); }
  function basename(path) { return String(path).replace(/\\/g, "/").split("/").pop(); }
  function dirname(path) { var parts = String(path).replace(/\\/g, "/").split("/"); parts.pop(); return parts.join("/") || "/"; }
  function paths(value) { return Array.isArray(value) ? value.filter(function (path) { return typeof path === "string" && path && path.length < 4096; }) : []; }
  function samePaths(left, right) { return JSON.stringify(left || []) === JSON.stringify(right || []); }
  function editCount(state, held) { return (state.edits || []).length + (state.physics || []).length + (state.outlines || []).length + (state.textures || []).length + (state.accessoryUnclip ? 1 : 0) + (held ? held.length : 0); }
  // The rows of a held summary ({count, meshes, rows}) the server reports.
  function heldRows(value) { return value && Array.isArray(value.rows) ? value.rows : []; }
  function create(options) {
    var translate = options.translate, disposed = false, busy = false, installing = false, status = "idle", statusKey = "Open a model to save model edits.", error = "";
    var result = null, resultModelId = "", resultSourcePaths = [], sourceInspection = null, authoringInspection = null, reviewingSaved = false, jobId = "", eventSource = null, requestController = null;
    var outputPaths = [], previewPaths = [], originalPaths = [], recipePath = "", events = [], lastContextId = "", lastAuthoringFingerprint = "";
    var modContext = "", manualModName = false, counterpartPath = "", modCharacters = "", lastPackage = null;
    var suggestedNameKey = "", suggestedName = "", suggestedParts = null, savedNaming = null, savedNamingSerial = 0, carriedModName = null;
    var installedFingerprint = "", alreadyAdded = false, installedComparisonKey = "", installedComparisonValue = "";
    var resultBodyState = null, resultMeshState = null;
    // English sentences shown after the save status (the baked-blush save mode); translated on display.
    var statusNotes = [];
    // Face outline rows a Rina board view holds (reported by the server on
    // open and on each recipe restore), for the editing token they belong to.
    var heldReport = null;
    var meshContext = null, meshRevision = null, meshOwner = null, meshSnapshot = null;
    var progress = element("viewer-save-progress"), cancel = element("viewer-save-cancel");
    function context() { return options.context() || {}; }
    // The member and costume a file is (from the viewer's labels), else its name.
    function fileLabel(path) { return options.labelFor ? options.labelFor(path) : basename(path); }
    function thumbnailMode() { var select = element("viewer-mod-thumbnail-mode"); return select && select.value === "3d" ? "3d" : "texture"; }
    function thumbnailFitFull() { var choice = element("viewer-mod-thumbnail-fit-full"); return !!(choice && choice.checked); }
    function clearThumbnail() {
      var preview = element("viewer-mod-thumbnail-preview"), label = element("viewer-mod-thumbnail-status");
      if (preview) { preview.hidden = true; preview.removeAttribute("src"); preview.removeAttribute("data-sha256"); }
      if (label) label.textContent = "";
    }
    function state() {
      return { available: !!((context().editing || {}).available), busy: busy, installing: installing, alreadyAdded: alreadyAdded, status: status, error: error,
        outputs: outputPaths.slice(), outputPaths: outputPaths.slice(), previewPaths: previewPaths.slice(), originalPaths: originalPaths.slice(),
        recipePath: recipePath, resultModelId: resultModelId, reviewingSaved: reviewingSaved, jobId: jobId, notes: statusNotes.slice(),
        modName: element("viewer-mod-name").value, modNameManual: manualModName, thumbnailMode: thumbnailMode(), thumbnailFitFull: thumbnailFitFull(),
        modPackage: lastPackage ? { packagePath: lastPackage.package_path, characterId: lastPackage.character_id,
          variants: lastPackage.variants || [], thumbnail: lastPackage.thumbnail || null } : null };
    }
    function listen(id, name, fn) {
      var target = element(id); if (!target) return;
      target.addEventListener(name, fn); events.push(function () { target.removeEventListener(name, fn); });
    }
    // A multi-line name field grows to show the whole suggested name (up to its
    // CSS max-height). Only when the text or the width changed, and only while
    // shown: a hidden field keeps its rows-based height.
    var fittedName = "";
    function fitModName(field) {
      if (!field || field.tagName !== "TEXTAREA") return;
      var width = field.clientWidth, key = width + "\n" + field.value;
      if (!width || key === fittedName) return;
      fittedName = key; field.style.height = "auto";
      var style = global.getComputedStyle ? global.getComputedStyle(field) : null, border = style ? (parseFloat(style.borderTopWidth) || 0) + (parseFloat(style.borderBottomWidth) || 0) : 2;
      if (field.scrollHeight) field.style.height = Math.ceil(field.scrollHeight + border) + "px";
    }
    // Sentences are joined with a space, except after a full-width stop (ja).
    function joinSentences(parts) { return parts.reduce(function (text, part) { return !part ? text : !text ? part : text + (/[。！？]$/.test(text) ? "" : " ") + part; }, ""); }
    // A server refusal that names one part is a fixed sentence ending in
    // ": {name}" (viewer_mod_pair_edits.NAMED_REFUSALS): translate the
    // sentence and keep the name. Exact sentences translate as before.
    // The Elichika installer's own summary (adminui installers): name its usual causes.
    var INSTALLER_EXIT = /^costume installer failed for .+ \(exit ([^()]*)\)$/;
    function translateMessage(text) {
      text = String(text || "");
      var exact = translate(text);
      if (exact !== text) return exact;
      var exit = INSTALLER_EXIT.exec(text);
      if (exit) return noteText({ text: "The costume installer stopped with exit code {code}. Usual causes are missing Elichika settings (config.json) or a Mod ZIP the installer could not find in its costume folder; the server console shows the installer's message.", values: { code: exit[1] } });
      for (var at = text.indexOf(": "); at >= 0; at = text.indexOf(": ", at + 1)) {
        var key = text.slice(0, at) + ": {name}", sentence = translate(key);
        if (sentence !== key) return sentence.split("{name}").join(text.slice(at + 2));
      }
      return text;
    }
    // Part names inside a sentence, with this language's list separator.
    function nameList(values) { return values.map(String).join(translate(", ")); }
    // A note is an English sentence, or {text, values} for a sentence with values
    // (a list value is a list of part names).
    function noteText(note) {
      if (note && typeof note === "object") return translate(String(note.text || "")).replace(/\{(\w+)\}/g, function (whole, name) {
        if (!note.values || !Object.prototype.hasOwnProperty.call(note.values, name)) return whole;
        return Array.isArray(note.values[name]) ? nameList(note.values[name]) : String(note.values[name]);
      });
      return translateMessage(note);
    }
    // The English text of a note, for the error state.
    function noteSource(note) {
      if (!note || typeof note !== "object") return String(note || "");
      return String(note.text || "").replace(/\{(\w+)\}/g, function (whole, name) {
        var value = note.values && Object.prototype.hasOwnProperty.call(note.values, name) ? note.values[name] : undefined;
        return value === undefined ? whole : Array.isArray(value) ? value.join(", ") : String(value);
      });
    }
    // Server notes ({text, values}) of a save result, e.g. parts kept on this variant.
    function resultNotes(data) {
      return (data && Array.isArray(data.notes) ? data.notes : []).filter(function (note) { return note && typeof note === "object" && typeof note.text === "string"; });
    }
    // A refusal the job sent as {text, values} is shown from that, else from its English sentence.
    function failureNote(failure, fallback) { return failure && failure.note || failure && failure.message || fallback; }
    function statusText(key, detail) { return joinSentences([noteText(key), detail && detail !== key ? noteText(detail) : ""].concat(statusNotes.map(noteText))); }
    function held() {
      var editing = context().editing || {};
      if (heldReport && heldReport.token === editing.token) return heldReport.value;
      return editing.heldFaceOutlines || null;
    }
    function renderHeldNote() {
      var note = element("viewer-save-held-note"), value = held(), count = heldRows(value).length;
      if (!note) return;
      note.hidden = !count;
      note.textContent = !count ? "" : translate(count === 1 ? "1 face outline edit made in the Normal face view is kept ({meshes})." :
        "{count} face outline edits made in the Normal face view are kept ({meshes}).").replace("{count}", String(count))
        .replace("{meshes}", nameList((value && value.meshes) || []));
    }
    // The save summary of each baked blush: the encoding it was saved with and,
    // when keeping ASTC was requested but not possible, why (server sentences).
    function textureSaveNotes(data) {
      var notes = [];
      (data && Array.isArray(data.texture_edits) ? data.texture_edits : []).forEach(function (row) {
        var blush = row && row.blush; if (!blush) return;
        [blush.fallback, blush.note].forEach(function (text) { if (typeof text === "string" && text && notes.indexOf(text) < 0) notes.push(text); });
      });
      return notes;
    }
    // ``key`` is an English sentence or a {text, values} note.
    function say(key, next, detail, notes) {
      statusKey = key; status = next || status; error = next === "error" ? noteSource(detail || key) : ""; statusNotes = notes || [];
      var target = element("viewer-save-status");
      target.textContent = statusText(key, detail);
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
      var body = c.rig && c.rig.getAuthoringState ? c.rig.getAuthoringState() : { version: 1, edits: [], unsupported: [] };
      var textures = c.textureTools && c.textureTools.getEdits ? c.textureTools.getEdits() : [];
      if (textures.length) body.textures = textures;
      return body;
    }
    function editingMeshState() {
      var c = context(), tool = c.meshTools;
      if (!tool || !tool.getEdits) return null;
      var revision = tool.getEditRevision ? tool.getEditRevision() : null;
      if (meshContext !== c.modelId || meshOwner !== tool || revision === null || meshRevision !== revision) {
        meshContext = c.modelId; meshOwner = tool; meshRevision = revision; meshSnapshot = tool.getEdits();
      }
      return meshSnapshot && meshSnapshot.meshes && meshSnapshot.meshes.length ? meshSnapshot : null;
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
      var mesh = editingMeshState(), unresolvedMesh = c.pendingMeshSelection || c.pendingMeshEdits && !mesh;
      var unresolvedTexture = !!(c.textureTools && c.textureTools.hasPending && c.textureTools.hasPending());
      var ready = !!(c.current && metadata.available && metadata.token && c.rig), authoring = ready && !busy && !reviewingSaved && !unresolvedMesh && !unresolvedTexture;
      var authored = editingState(), lightweight = Object.assign({}, authored), heldFace = heldRows(held());
      // Pixel payloads are immutable cached strings. A revision is enough for
      // frequent UI updates; serialize PNGs only for a concrete save operation.
      if (lightweight.textures) lightweight.textures = lightweight.textures.map(function (row) { return { texture: row.texture, kind: row.kind, sourceSha256: row.sourceSha256, blush: row.blush || null, operations: row.operations || null }; });
      // Held face rows are saved too: a restore that changes them is an edit.
      var fingerprint = JSON.stringify([lightweight, mesh, c.textureTools && c.textureTools.getRevision ? c.textureTools.getRevision() : 0, heldFace]);
      renderHeldNote();
      var accessories = c.accessories || {}, accessoryBlocked = !!authored.accessoryUnclip && (accessories.pending || accessories.error);
      if (lastAuthoringFingerprint && lastAuthoringFingerprint !== fingerprint) { lastPackage = null; clearThumbnail(); }
      if (lastAuthoringFingerprint && lastAuthoringFingerprint !== fingerprint && !busy && ["done", "restored", "error"].indexOf(status) >= 0) { status = "ready"; error = ""; }
      lastAuthoringFingerprint = fingerprint;
      element("viewer-save").disabled = !authoring || (!editCount(authored, heldFace) && !mesh && !(c.transplantEdits || []).length && !metadata.allowEmptySceneReset && !(metadata.modPackaging || {}).derivedOwner) || accessoryBlocked || !!(authored.unsupported && authored.unsupported.length);
      element("viewer-save").title = authored.unsupported && authored.unsupported.length ? translate(authored.unsupported[0]) : accessoryBlocked ? accessories.errorText || translate(accessories.error || "Wait for the accessory check before saving.") : "";
      refreshModForm(c, rigState, authored, ready && !busy && !unresolvedMesh && !unresolvedTexture);
      element("viewer-recipe-open").disabled = !authoring;
      element("viewer-open-saved").hidden = !previewPaths.length;
      element("viewer-open-saved").disabled = busy || !c.current || !!unresolvedMesh;
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
        var key = reviewingSaved ? "Reviewing the saved copy. Re-edit from original to continue." : unresolvedTexture ? "Apply or cancel the texture preview before saving." : unresolvedMesh ? "Apply selected face deletions before saving." : !ready ? (c.current ? "Model saving is unavailable for this model." : "Open a model to save model edits.") : authored.unsupported && authored.unsupported.length ? authored.unsupported[0] : accessoryBlocked ? accessories.errorText || accessories.error || "Wait for the accessory check before saving." : "Model changes";
        statusKey = key; status = reviewingSaved ? "reviewing" : ready ? "ready" : "idle"; statusNotes = [];
        element("viewer-save-status").textContent = translate(key) + (key === "Model changes" ? ": " + (editCount(authored, heldFace) + (mesh ? mesh.meshes.length : 0) + (c.transplantEdits || []).length) + (authored.accessoryUnclip ? " · " + translate("Accessory Un-clip") : "") : "");
      }
      element("viewer-save-status").classList.toggle("viewer-save-error", !!error);
    }
    function modContextKey(c) { return JSON.stringify([c.modelId || "", (c.editing || {}).token || "", c.loadedPaths || []]); }
    // The most automatic name labels sent with a save (viewer_mod_flow.NAME_PART_LIMIT).
    var NAME_PART_LIMIT = 64;
    // The texture operations applied now, each once across all textures, in
    // the name's order. The texture tools know several per texture and follow
    // Undo/Redo; a texture row alone names its saved operations (an older row
    // its one kind) and its baked blush.
    var TEXTURE_OPERATIONS = [["costume", "Costume colour"], ["skin", "Skin tone"], ["blush", "Baked blush"], ["paint", "Texture painting"]];
    function textureOperations(c, authored) {
      var tools = c.textureTools, rows = tools && tools.getAppliedOperations ? tools.getAppliedOperations() : (authored.textures || []).map(function (row) {
        return { operations: (row.kind !== "blush" && Array.isArray(row.operations) ? row.operations : [row.kind === "blush" ? "" : row.kind]).concat([row.blush ? "blush" : ""]) };
      }), found = {};
      rows.forEach(function (row) { (row.operations || []).forEach(function (kind) { found[kind] = true; }); });
      return TEXTURE_OPERATIONS.filter(function (pair) { return found[pair[0]]; }).map(function (pair) { return pair[0]; });
    }
    // What the automatic name is built from: the current edits or, while the
    // saved copy is reviewed (its own source has no edits), those it was saved with.
    function namingInputs(c, rigState, authored) {
      if (reviewingSaved && savedNaming) return savedNaming;
      // The texture rows themselves (their PNGs) are not kept: textures names them.
      return { c: { editing: c.editing, loadedPaths: (c.loadedPaths || []).slice(), transplantEdits: (c.transplantEdits || []).slice() }, rigState: rigState,
        authored: { edits: authored.edits || [], outlines: authored.outlines, physics: authored.physics, accessoryUnclip: authored.accessoryUnclip },
        textures: textureOperations(c, authored), mesh: editingMeshState(), heldOutlines: heldRows(held()).length > 0 };
    }
    // The page language ("en", "ko" or "ja") picks the costume name base.
    function pageLanguage() { var code = options.language ? options.language() : (document.documentElement.lang || "en"); code = String(code || "en").split("-")[0]; return ["en", "ko", "ja"].indexOf(code) >= 0 ? code : "en"; }
    // An edit label is a list of tokens: literal text (numbers, ×, →) or
    // {k: English source} that each language translates. The server builds
    // the same name per game language from these parts (viewer_mod_flow
    // compose_mod_name) when the name is still this automatic suggestion.
    function K(key) { return { k: String(key) }; }
    function renderPart(part, tr) { return part.map(function (token) { return typeof token === "string" ? token : tr(token.k); }).join(""); }
    function composeModName(base, parts, tr) {
      // A Mod name has at most 120 characters: whole labels only, never one cut
      // short or a dangling separator. A label the base (an installed Mod's own
      // name) already carries is not repeated.
      var present = base.split(" · ").slice(1), seen = [], name = base.slice(0, 120).replace(/[\uD800-\uDBFF]$/, "");
      for (var index = 0; index < parts.length; index++) {
        var text = renderPart(parts[index], tr);
        if (!text || present.indexOf(text) >= 0 || seen.indexOf(text) >= 0) continue;
        seen.push(text);
        if ((name + " · " + text).length > 120) break;
        name += " · " + text;
      }
      return name;
    }
    // The Mod member the costume is for: the chosen one, else the automatic one.
    function chosenMember(packaging) {
      var value = element("viewer-mod-character").value;
      return value || (packaging.characterId !== null && packaging.characterId !== undefined ? String(packaging.characterId) : "");
    }
    function suggestedModBase(naming, member) {
      var c = naming.c, packaging = (c.editing || {}).modPackaging || {}, bases = packaging.nameBases || {}, code = pageLanguage();
      var texts = packaging.nameTexts;
      // Another chosen member: that member's number and name before the same
      // costume, never the number of the member it was opened as. The server
      // builds the same (viewer_mod_flow.name_bases) for the installed names.
      if (member && member !== String(packaging.nameOwner) && texts && typeof texts === "object") {
        var choice = (packaging.characters || []).filter(function (row) { return String(row.value) === member; })[0];
        var label = choice && choice.labels && typeof choice.labels[code] === "string" ? choice.labels[code] : "";
        var text = typeof texts[code] === "string" ? texts[code] : "";
        if (label) return text ? label + " · " + text : label;
      }
      return typeof bases[code] === "string" && bases[code] ? bases[code] :
        packaging.nameBase || basename((c.loadedPaths || [])[0] || "Costume").replace(/\.[^.]+$/, "");
    }
    function suggestedModParts(naming) {
      var c = naming.c, rigState = naming.rigState, authored = naming.authored, textures = naming.textures;
      var metadata = c.editing || {}, packaging = metadata.modPackaging || {};
      var groups = {}, entries = metadata.nodes || [], profile = rigState.thighProfile || {};
      function format(value) { return String(Number(value.toPrecision(4))); }
      function sameVector(left, right) { return left && right && left.length === right.length && left.every(function (value, i) { return Math.abs(value - right[i]) <= 1e-7; }); }
      function joined(parts, separator) { var out = []; parts.forEach(function (part, index) { if (index) out.push(separator); out = out.concat(part); }); return out; }
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
          if (values.some(function (value) { return !!value.edit.position; })) extra.push([K("Position")]);
          if (values.some(function (value) { return !!value.edit.rotation; })) extra.push([K("Rotation")]);
          return extra.length ? [" "].concat(joined(extra, " ")) : [];
        }
        if (preset && values.length === (profile.targets || []).length) return [K(label), " ", K(preset.sourceLabel), "→", K(preset.targetLabel)].concat(extraTransforms());
        var breast = kind === "breast" && ((rigState.scaling || {}).controls || []).filter(function (entry) { return entry.id === "breast"; })[0];
        preset = breast && (breast.presets || []).filter(function (entry) {
          return entry.id === (rigState.body || {}).breastPreset && values.every(function (value) { return sameVector(value.edit.scale, entry.scale); });
        })[0];
        if (preset) return [K(label), " ", K(preset.label)].concat(extraTransforms());
        var transforms = values.map(function (value) {
          var edit = value.edit, baseline = value.target.baseline || {}, tags = [];
          if (edit.scale && baseline.scale) {
            if (kind === "hips") {
              // The dedicated hip fields author actual XYZ endpoints. Keep
              // their name hint in those same values for non-unit originals.
              tags.push([edit.scale.map(function (part, axis) { return "XYZ"[axis] + format(part); }).join("/")]);
            } else {
            var ratios = edit.scale.map(function (part, axis) { return baseline.scale[axis] ? part / baseline.scale[axis] : null; });
            var axes = ratios.map(function (part, axis) { return part !== null && Math.abs(part - 1) > 1e-7 ? axis : -1; }).filter(function (axis) { return axis >= 0; });
            if (axes.length) {
              var uniform = axes.length === 3 && axes.every(function (axis) { return Math.abs(ratios[axis] - ratios[0]) < 1e-7; }) ||
                (kind === "thighs" || kind === "waist") && axes.join(",") === "1,2" && Math.abs(ratios[1] - ratios[2]) < 1e-7;
              tags.push([uniform ? format(ratios[axes[0]]) + "×" : axes.map(function (axis) { return "XYZ"[axis] + format(ratios[axis]); }).join("/")]);
            } else tags.push([K("Bake into mesh")]);
            }
          }
          if (edit.position) tags.push([K("Position")]);
          if (edit.rotation) tags.push([K("Rotation")]);
          return joined(tags, " ");
        });
        var first = JSON.stringify(transforms[0]);
        return [K(label), " "].concat(transforms.every(function (part) { return JSON.stringify(part) === first; }) ? transforms[0] : [K("Custom adjustment")]);
      });
      var kinds = [], mesh = naming.mesh, derived = packaging.derivedOwner || {};
      function addKind(key) { if (!kinds.some(function (part) { return part[0].k === key; })) kinds.push([K(key)]); }
      (derived.operations || []).forEach(function (operation) {
        var title = { costume: "Costume transplant", part: "Costume part transplant", lower: "Lower body replacement", mesh: "Mesh editing" }[operation];
        if (title) addKind(title);
      });
      (c.transplantEdits || []).forEach(function (title) { addKind(title); });
      if (mesh) {
        if (mesh.meshes.some(function (row) { return row.deleteFaces && row.deleteFaces.length; })) kinds.push([K("Mesh deletion")]);
        if (mesh.meshes.some(function (row) { return row.positions && row.positions.length; })) kinds.push([K("Vertex positions")]);
        if (mesh.meshes.some(function (row) { return row.weights && row.weights.length; })) kinds.push([K("Skin weights")]);
      }
      TEXTURE_OPERATIONS.forEach(function (pair) { if (textures.indexOf(pair[0]) >= 0) kinds.push([K(pair[1])]); });
      // Held face outline rows (a Rina board view) are saved as outline edits.
      if (authored.outlines && authored.outlines.length || naming.heldOutlines) kinds.push([K("Outlines")]);
      if (authored.physics && authored.physics.length) kinds.push([K("Physics")]);
      if (authored.accessoryUnclip) kinds.push([K("Accessory Un-clip")]);
      return kinds.concat(details);
    }
    function suggestedModName(naming, member) {
      suggestedParts = suggestedModParts(naming);
      return composeModName(suggestedModBase(naming, member), suggestedParts, translate);
    }
    function refreshModForm(c, rigState, authored, authoring) {
      var key = modContextKey(c), metadata = (c.editing || {}).modPackaging || {};
      if (key !== modContext) {
        modContext = key; manualModName = false; counterpartPath = ""; lastPackage = null; installedFingerprint = ""; clearThumbnail();
        element("viewer-mod-character").value = ""; element("viewer-mod-variant").value = "";
        // A costume ZIP that includes its own face keeps it by default.
        if (element("viewer-mod-include-face")) element("viewer-mod-include-face").checked = !!metadata.faceIncluded;
        element("viewer-mod-target").open = !!metadata.requiresCounterpart;
        // A typed name stays with the same edits when their saved copy or
        // their original is opened from this panel.
        if (carriedModName && samePaths(c.loadedPaths, carriedModName.paths)) { manualModName = true; element("viewer-mod-name").value = carriedModName.name; carriedModName = null; }
      }
      var name = element("viewer-mod-name");
      if (!manualModName) {
        // Motion time and camera updates do not change the exported edits.
        // Reuse their suggestion instead of regrouping every rig node again.
        var naming = namingInputs(c, rigState, authored), member = chosenMember(metadata);
        var nameKey = JSON.stringify([key, pageLanguage(), member, naming === savedNaming ? ["saved", savedNamingSerial] : [metadata.nameBase, metadata.nameBases, metadata.nameTexts, metadata.nameOwner, lastAuthoringFingerprint, naming.textures,
          (rigState.thighProfile || {}).selected, (rigState.body || {}).breastPreset], translate("Mod name")]);
        if (nameKey !== suggestedNameKey) { suggestedNameKey = nameKey; suggestedName = suggestedModName(naming, member); }
        name.value = suggestedName;
      }
      // The whole name, also where the field is narrower than it.
      if (name.title !== name.value) name.title = name.value;
      fitModName(name);
      // Members read "004 소노다 우미" in the page language (labels from the server).
      var choices = metadata.characters || [], choicesKey = JSON.stringify([choices, metadata.characterId, translate("Automatic"), pageLanguage()]);
      function choiceLabel(choice) { return choice.labels && typeof choice.labels[pageLanguage()] === "string" && choice.labels[pageLanguage()] || choice.label; }
      var characters = element("viewer-mod-character");
      if (choicesKey !== modCharacters) {
        var selected = characters.value; modCharacters = choicesKey; characters.textContent = "";
        var automatic = document.createElement("option"); automatic.value = ""; automatic.textContent = translate("Automatic");
        var current = choices.filter(function (choice) { return String(choice.value) === String(metadata.characterId); })[0];
        if (current) automatic.textContent += " · " + choiceLabel(current);
        characters.appendChild(automatic);
        choices.forEach(function (choice) {
          if (!/^[1-9][0-9]{0,3}$/.test(String(choice.value))) return;
          var option = document.createElement("option"); option.value = String(choice.value); option.textContent = choiceLabel(choice); characters.appendChild(option);
        });
        characters.value = selected;
      }
      var validName = !!name.value.trim() && name.value.trim().length <= 120;
      name.disabled = !authoring; element("viewer-mod-name-auto").disabled = !authoring || !manualModName;
      if (element("viewer-mod-thumbnail-mode")) element("viewer-mod-thumbnail-mode").disabled = !authoring;
      var fullThumbnail = element("viewer-mod-thumbnail-fit-full");
      if (fullThumbnail) { fullThumbnail.disabled = !authoring || thumbnailMode() !== "3d"; if (fullThumbnail.parentElement) fullThumbnail.parentElement.hidden = thumbnailMode() !== "3d"; }
      var faceOption = element("viewer-mod-include-face"), faceHelp = element("viewer-mod-face-help");
      if (faceOption) { faceOption.disabled = !authoring || !metadata.hasFaceCompanions; if (!metadata.hasFaceCompanions) faceOption.checked = false; }
      if (faceHelp) faceHelp.textContent = translate(!metadata.hasFaceCompanions ? "Open the original face with this costume to include face and mouth edits." : faceOption && !faceOption.checked ? "Face and mouth edits will not be applied in game. This costume uses the game's original face." : metadata.faceIncluded ? "This costume ZIP includes its own face, so it is included by default. Only this costume uses it; other costumes and the character's shared face stay unchanged." : "Only this costume uses the included face. Other costumes and the character's shared face stay unchanged.");
      characters.disabled = !authoring; element("viewer-mod-character-field").hidden = !choices.length;
      element("viewer-mod-variant").disabled = !authoring;
      element("viewer-mod-counterpart").value = counterpartPath ? fileLabel(counterpartPath) : "";
      element("viewer-mod-counterpart").title = counterpartPath;
      element("viewer-mod-counterpart").disabled = !authoring;
      element("viewer-mod-counterpart-pick").disabled = !authoring;
      element("viewer-mod-counterpart-clear").disabled = !authoring || !counterpartPath;
      var owner = characters.value || metadata.characterId;
      element("viewer-mod-rina-fields").hidden = !!owner && Number(owner) !== 209;
      var accessories = c.accessories || {};
      var enabled = authoring && validName && !(authored.unsupported || []).length && !(authored.accessoryUnclip && (accessories.pending || accessories.error));
      ["viewer-save-mod", "viewer-add-to-game"].forEach(function (id) { element(id).disabled = !enabled; element(id).title = element("viewer-save").title; });
      var body = Object.assign({}, authored); delete body.unsupported;
      var comparisonKey = JSON.stringify([key, lastAuthoringFingerprint, modOptions()]);
      if (comparisonKey !== installedComparisonKey || installedComparisonValue !== installedFingerprint) {
        alreadyAdded = !!installedFingerprint && installedFingerprint === JSON.stringify([key, JSON.stringify(body), JSON.stringify(modOptions()), JSON.stringify(editingMeshState()), JSON.stringify(heldRows(held()))]);
        installedComparisonKey = comparisonKey; installedComparisonValue = installedFingerprint;
      }
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
        var settled = false, timer = null, message = null;
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
          // A refusal sentence with its values, sent just before the job fails.
          if (item.type === "message" && typeof item.text === "string") message = { text: item.text, values: item.values && typeof item.values === "object" ? item.values : {} };
          if (item.type === "done") {
            settled = true; close();
            if (item.status === "done") resolve(item);
            else {
              var failure = new Error(item.summary || (item.status === "cancelled" ? "Saving cancelled." : "The body edits could not be saved."));
              if (message && item.status === "error") failure.note = message;
              reject(failure);
            }
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
        // An edited copy keeps its code file name on disk and in the download;
        // its link reads as the costume it is.
        var shown = previewPaths.indexOf(path) >= 0 ? fileLabel(path) : basename(path);
        link.textContent = (label ? translate(label) + " · " : "") + shown;
        link.title = shown !== basename(path) ? basename(path) + "\n" + path : path;
        link.href = "/api/download?path=" + encodeURIComponent(path); link.setAttribute("download", basename(path));
        item.appendChild(link);
        if (path === modPath) {
          // Phones have no Finder button: name the folder that holds the ZIP.
          var folder = document.createElement("div");
          folder.className = "viewer-save-folder";
          folder.textContent = translate("Saved in folder") + ": " + dirname(path);
          item.appendChild(folder);
        }
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
      if (input.physics && input.physics.length) canonical.physics = input.physics;
      if (input.outlines && input.outlines.length) canonical.outlines = input.outlines.map(function (value) {
        var row = { id: value.id, factor: numeric(value.factor) };
        if (value.absolute !== undefined) row.absolute = value.absolute;
        if (value.vertices && value.vertices.length) row.vertices = value.vertices.map(function (vertex) { return { vertex: vertex.vertex, value: numeric(vertex.value) }; }).sort(function (a, b) { return a.vertex - b.vertex; });
        return row;
      }).sort(function (a, b) { return a.id.localeCompare(b.id); });
      if (input.accessoryUnclip) canonical.accessoryUnclip = { strength: numeric(input.accessoryUnclip.strength), overlap: numeric(input.accessoryUnclip.overlap), closeGaps: input.accessoryUnclip.closeGaps };
      if (input.textures && input.textures.length) canonical.textures = input.textures.map(function (row) {
        var value = { texture: { source: row.texture.source, file: row.texture.file, id: row.texture.id },
          sourceSha256: row.sourceSha256, png: row.png, kind: row.kind };
        if (row.blush) value.blush = { layer: row.blush.layer, k: row.blush.k, encoding: row.blush.encoding === undefined ? "exact" : row.blush.encoding };
        if (row.operations) value.operations = row.operations.slice();
        return value;
      }).sort(function (a, b) {
        var order = a.texture.source - b.texture.source || a.texture.file - b.texture.file;
        if (order) return order;
        var left = BigInt(a.texture.id), right = BigInt(b.texture.id);
        return left < right ? -1 : left > right ? 1 : 0;
      });
      return JSON.stringify(canonical);
    }
    function captureSave(forPackage) {
      var c = context(), authored = editingState(), mesh = editingMeshState();
      if (!c.current || !c.editing || !c.editing.available || reviewingSaved && !forPackage) throw new Error("Open the original model before saving model edits.");
      if (c.pendingMeshSelection || c.pendingMeshEdits && !mesh) throw new Error("Apply selected face deletions before saving.");
      if (c.textureTools && c.textureTools.hasPending && c.textureTools.hasPending()) throw new Error("Apply or cancel the texture preview before saving.");
      if (authored.unsupported && authored.unsupported.length) throw new Error(authored.unsupported[0]);
      if (authored.accessoryUnclip && c.accessories && (c.accessories.pending || c.accessories.error)) throw new Error(c.accessories.error || "Wait for the accessory check before saving.");
      var heldFace = heldRows(held());
      if (!forPackage && !editCount(authored, heldFace) && !mesh && !(c.transplantEdits || []).length && !(c.editing.modPackaging || {}).derivedOwner && !c.editing.allowEmptySceneReset) throw new Error("Change a model value before saving.");
      var body = JSON.parse(JSON.stringify(authored)); delete body.unsupported;
      return { body: body, meshState: mesh ? JSON.parse(JSON.stringify(mesh)) : null, rawMesh: JSON.stringify(mesh), rawHeld: JSON.stringify(heldFace), reviewingSaved: reviewingSaved, modelId: c.modelId, token: c.editing.token, paths: (c.loadedPaths || []).slice(),
        contextKey: modContextKey(c), canonical: canonicalBody(body, c.editing), rawBody: JSON.stringify(body),
        naming: namingInputs(c, c.rig && c.rig.getState ? c.rig.getState() : {}, authored),
        inspection: options.captureInspection ? options.captureInspection() : null };
    }
    function stillCurrent(snapshot) {
      var c = context(), authored = editingState();
      var body = Object.assign({}, authored); delete body.unsupported;
      return c.current && reviewingSaved === snapshot.reviewingSaved && modContextKey(c) === snapshot.contextKey &&
        !(authored.unsupported || []).length && JSON.stringify(body) === snapshot.rawBody &&
        JSON.stringify(editingMeshState()) === snapshot.rawMesh &&
        JSON.stringify(heldRows(held())) === snapshot.rawHeld &&
        canonicalBody(authored, c.editing) === snapshot.canonical &&
        (!snapshot.modOptions || JSON.stringify(modOptions()) === snapshot.modOptions);
    }
    function modOptions() {
      var character = element("viewer-mod-character").value;
      var suggested = ((context().editing || {}).modPackaging || {}).characterId;
      return { display_name: element("viewer-mod-name").value.trim(), character_id: character ? Number(character) : suggested ? Number(suggested) : null,
        counterpart_path: counterpartPath || null, selected_variant: element("viewer-mod-variant").value || null,
        thumbnail_mode: thumbnailMode(), thumbnail_fit_full: thumbnailFitFull(), include_face_edits: !!(element("viewer-mod-include-face") && element("viewer-mod-include-face").checked) };
    }
    function modChanged() {
      lastPackage = null; clearThumbnail();
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
      savedNaming = snapshot.naming || null; savedNamingSerial++;
      resultBodyState = JSON.parse(JSON.stringify(snapshot.body)); resultMeshState = snapshot.meshState ? JSON.parse(JSON.stringify(snapshot.meshState)) : null;
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
        var request = { token: snapshot.token, state: snapshot.body };
        if (snapshot.meshState) request.mesh_state = snapshot.meshState;
        var data = await runJob("/api/viewer/edit/export", request, signal);
        rememberResult(data, snapshot); lastPackage = null;
        say(context().modelId === snapshot.modelId ? "Saved. Open the saved result to verify it." : "Saved the previous model. The current preview was not changed.", "done", "", textureSaveNotes(data).concat(resultNotes(data)));
      } catch (failure) {
        if (!disposed) say(failure && failure.name === "AbortError" ? "Saving cancelled." : failureNote(failure, "The body edits could not be saved."), "error");
      } finally { requestController = null; if (!disposed) setBusy(false); }
    }
    async function saveMod(install) {
      if (busy || disposed) return;
      var snapshot, parameters = modOptions(), name = parameters.display_name;
      try {
        snapshot = captureSave(true);
        if (!name || name.length > 120) throw new Error("Enter a mod name of 1 to 120 characters.");
      } catch (failure) { say(failure.message, "error"); return; }
      snapshot.modOptions = JSON.stringify(parameters);
      var binding = JSON.stringify([snapshot.contextKey, snapshot.rawBody, snapshot.modOptions, snapshot.rawMesh, snapshot.rawHeld]);
      if (install && installedFingerprint === binding) { say("Already added to game. Change the edits or mod name to add another copy.", "done"); return; }
      var body = Object.assign({ token: snapshot.token, state: snapshot.body }, parameters);
      if (snapshot.meshState) body.mesh_state = snapshot.meshState;
      // An untouched automatic name is installed in each game language; the
      // server rebuilds it from these labels and checks it equals this name.
      // A 120-character name holds fewer labels than this; the rest are never
      // sent (viewer_mod_flow.NAME_PART_LIMIT), so many edited bones cannot
      // turn the labels into a refused save.
      if (!manualModName && suggestedParts && name === suggestedName.trim()) body.name_parts = JSON.parse(JSON.stringify(suggestedParts.slice(0, NAME_PART_LIMIT)));
      delete body.thumbnail_mode;
      delete body.thumbnail_fit_full;
      requestController = new global.AbortController(); var signal = requestController.signal;
      lastPackage = null; setBusy(true); say("Saving an installer-ready mod ZIP…", "saving");
      try {
        if (parameters.thumbnail_mode === "3d") {
          if (!global.ViewerThumbnails) throw new Error("The automatic 3D thumbnail renderer is unavailable.");
          say("Rendering costume thumbnail…", "saving");
          var rendered = await global.ViewerThumbnails.prepareViewer(snapshot, parameters, { signal: signal,
            onPreview: function (png, receipt) {
              if (disposed || !stillCurrent(snapshot)) return;
              var preview = element("viewer-mod-thumbnail-preview"), label = element("viewer-mod-thumbnail-status");
              if (preview) { preview.src = png; preview.hidden = false; preview.dataset.sha256 = receipt.sha256; }
              if (label) label.textContent = translate("Automatic 3D thumbnail ready.");
            } });
          body.thumbnail_token = rendered.token;
          say("Saving an installer-ready mod ZIP…", "saving");
        }
        // Each explicit action packages the current authoring snapshot. An older
        // downloaded result can never become the input to a later installation.
        var data = await runJob("/api/viewer/edit/package?lang=" + encodeURIComponent(pageLanguage()), body, signal), packaged = data.mod_package;
        if (!packaged || typeof packaged.token !== "string" || !/^[a-zA-Z0-9_-]{16,128}$/.test(packaged.token) ||
            packaged.installable !== true || typeof packaged.package_path !== "string" || paths(data.output_paths).indexOf(packaged.package_path) < 0) throw new Error("The mod package response is invalid.");
        rememberResult(data, snapshot);
        if (stillCurrent(snapshot)) lastPackage = packaged;
        if (!install) {
          say(stillCurrent(snapshot) ? "Mod ZIP saved. You can install it with the mod installer." : "Saved the previous model. The current preview was not changed.", "done", "", textureSaveNotes(data).concat(resultNotes(data)));
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
        // The server moves an added ZIP from mods/saved to mods/added.
        var moved = installed.mod_package && installed.mod_package.package_path, before = packaged.package_path;
        if (typeof moved === "string" && moved && moved.length < 4096 && moved !== before) {
          packaged.package_path = moved;
          if (result === data) {
            outputPaths = outputPaths.map(function (path) { return path === before ? moved : path; });
            if (!disposed) renderOutputs();
          }
        }
        say(stillCurrent(snapshot) ? "Added to game. Select the new costume in game." : "Added the saved mod to game. The current preview was not changed.", "done", "", resultNotes(data));
      } catch (failure) {
        if (!disposed) say(failure && failure.name === "AbortError" ? "Saving cancelled." : failureNote(failure, "The mod could not be saved."), "error");
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
      catch (_) { throw new Error("The model edit recipe is invalid."); }
    }
    async function restoreRecipe(recipe) {
      var c = context();
      if (!c.current || !c.editing || !c.editing.token || reviewingSaved) throw new Error("Open the original model before loading its recipe.");
      var modelId = c.modelId, token = c.editing.token, response = await jsonRequest("/api/viewer/edit/restore", { token: token, recipe: recipe });
      // The server now holds what this restore left held, even if applying the
      // state below fails: show exactly that.
      if (response.heldFaceOutlines) heldReport = { token: token, value: response.heldFaceOutlines };
      if (!context().current || context().modelId !== modelId) throw new Error("The model changed while its recipe was loading. Try again.");
      if (!response.state) throw new Error("The model edit recipe is invalid.");
      var previous = editingState();
      var previousDocuments = options.captureTextureDocuments ? options.captureTextureDocuments() : null;
      try {
        c.rig.restoreAuthoringState(response.state);
        if (options.restoreTextureState) await options.restoreTextureState(response.state.textures || []);
        if (response.mesh_state && options.restoreMeshState) await options.restoreMeshState(response.mesh_state);
      } catch (error) {
        if (context().modelId === modelId) {
          c.rig.restoreAuthoringState(previous);
          if (previousDocuments && options.restoreTextureDocuments) await options.restoreTextureDocuments(previousDocuments);
          else if (options.restoreTextureState) await options.restoreTextureState(previous.textures || []);
        }
        throw error;
      }
      if (!context().current || context().modelId !== modelId) throw new Error("The model changed while its recipe was loading. Try again.");
      var notice = response.notice && typeof response.notice === "object" && typeof response.notice.text === "string" ? response.notice : null;
      say("Edit recipe restored from the original model.", "restored", "", notice ? [notice] : []);
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
      var ownOriginal = samePaths(c.loadedPaths, resultSourcePaths) || samePaths(c.loadedPaths, originalPaths) ||
        !!(result && samePaths(c.loadedPaths, paths(result.reedit_paths)));
      var mesh = editingMeshState();
      if (!reviewingSaved && (editCount(current) || mesh) && (!ownOriginal || !result || !result.recipe ||
          canonicalBody(current, c.editing) !== canonicalBody(resultBodyState || result.recipe.state || {}, c.editing) ||
          JSON.stringify(mesh) !== JSON.stringify(resultMeshState))) {
        say("Save current model changes before opening the saved result.", "error"); return;
      }
      authoringInspection = ownOriginal && options.captureInspection ? options.captureInspection() : sourceInspection;
      setBusy(true); carryModName(previewPaths);
      try {
        await options.openFiles(previewPaths.slice(), result && result.preview_variants);
        reviewingSaved = samePaths(context().loadedPaths, previewPaths);
        if (!reviewingSaved) throw new Error("The saved model could not be opened.");
        if (context().rig) context().rig.setEvaluationMode("animation");
        say("Reviewing the saved copy. Re-edit from original to continue.", "reviewing");
      } catch (failure) { say(failure.message, "error"); }
      finally { carriedModName = null; setBusy(false); }
    }
    // Remembers a typed Mod name for the model about to open (refreshModForm takes it).
    function carryModName(paths) { carriedModName = manualModName ? { name: element("viewer-mod-name").value, paths: paths.slice() } : null; }
    // The originals the edited preview selected. A face the preview added
    // automatically is reopened the same way, as the body's face companion
    // found beside it, never as a second selected model (one Mod ZIP holds
    // one costume). Older results list every original.
    function reeditSelection() {
      var selected = paths(result.reedit_paths).filter(function (path) { return originalPaths.indexOf(path) >= 0; });
      if (!selected.length) return { paths: originalPaths.slice(), variants: result.original_variants, autoFace: undefined };
      return { paths: selected, variants: result.reedit_variants || {}, autoFace: result.reedit_auto_face === true ? true : undefined };
    }
    async function reeditOriginal() {
      if (busy || !result || !result.recipe || !originalPaths.length) return;
      var recipe = result.recipe, selection = reeditSelection(), originals = selection.paths;
      carryModName(originals); setBusy(true); say("Opening the original model and edit recipe…", "saving");
      try {
        await options.openFiles(originals, selection.variants, authoringInspection || sourceInspection, { autoFace: selection.autoFace });
        reviewingSaved = false;
        if (!samePaths(context().loadedPaths, originals)) throw new Error("The original model could not be opened.");
        await restoreRecipe(recipe);
        var inspection = authoringInspection || sourceInspection;
        if (inspection && inspection.textureDocuments && options.restoreTextureDocuments) await options.restoreTextureDocuments(inspection.textureDocuments);
      } catch (failure) { say(failure.message, "error"); }
      finally { carriedModName = null; setBusy(false); }
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
    // The name is one line in the ZIP and in the game: Enter does not break
    // it, and pasted line breaks become spaces (one for one, so the caret stays).
    listen("viewer-mod-name", "keydown", function (event) { if (event.key === "Enter" && !event.isComposing && event.keyCode !== 229) event.preventDefault(); });
    listen("viewer-mod-name", "input", function () {
      if (/[\r\n]/.test(this.value)) { var start = this.selectionStart, end = this.selectionEnd; this.value = this.value.replace(/[\r\n]/g, " "); this.setSelectionRange(start, end); }
      manualModName = true; modChanged();
    });
    listen("viewer-mod-name-auto", "click", function () { manualModName = false; modChanged(); });
    ["viewer-mod-character", "viewer-mod-variant", "viewer-mod-include-face"].forEach(function (id) { listen(id, "change", modChanged); });
    var thumbnailChoice = element("viewer-mod-thumbnail-mode");
    if (thumbnailChoice) {
      try { if (global.localStorage.getItem("sifas_costume_thumbnail_mode") === "3d") thumbnailChoice.value = "3d"; } catch (_) {}
      listen("viewer-mod-thumbnail-mode", "change", function () {
        try { global.localStorage.setItem("sifas_costume_thumbnail_mode", this.value); } catch (_) {}
        modChanged();
      });
    }
    var fullThumbnailChoice = element("viewer-mod-thumbnail-fit-full");
    if (fullThumbnailChoice) {
      try { fullThumbnailChoice.checked = global.localStorage.getItem("elichika.thumbnail.fit-full.v1") === "true"; } catch (_) {}
      listen("viewer-mod-thumbnail-fit-full", "change", function () {
        try { global.localStorage.setItem("elichika.thumbnail.fit-full.v1", String(this.checked)); } catch (_) {}
        modChanged();
      });
    }
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
      updateLanguage: function () { renderOutputs(); element("viewer-save-status").textContent = statusText(statusKey); refresh(); },
      labelsChanged: function () { if (disposed) return; renderOutputs(); refresh(); },
      dispose: function () {
        disposed = true;
        if (!installing) { if (requestController) requestController.abort(); if (eventSource) eventSource.close(); }
        events.forEach(function (remove) { remove(); });
      } };
  }
  global.ViewerPersistence = { create: create };
})(window);
