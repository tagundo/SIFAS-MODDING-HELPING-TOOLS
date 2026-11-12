/* Viewer-only editing helpers. Original Unity data and authored TRS stay intact. */
(function () {
  "use strict";
  var AXES = ["x", "y", "z"];
  function finite(value, fallback) { value = Number(value); return isFinite(value) ? value : fallback; }
  function near(a, b) { return Math.abs(a - b) <= 1e-7; }
  // Unity TRS uses float32. Keep runtime precision, but hide binary rounding
  // noise in the editor (for example, 1.3f should read as the local factor 1.3).
  function format(value, kind) {
    return String(Number(value.toPrecision(7)));
  }
  function clone(value) { return { position: value.position.clone(), quaternion: value.quaternion.clone(), scale: value.scale.clone() }; }
  function uiQuaternion(THREE, degrees) {
    // Unity applies extrinsic Z, then X, then Y (Ry * Rx * Rz).
    // Three names the equivalent intrinsic decomposition YXZ.
    var unity = new THREE.Quaternion().setFromEuler(new THREE.Euler(
      degrees[0] * Math.PI / 180, degrees[1] * Math.PI / 180, degrees[2] * Math.PI / 180, "YXZ"));
    return new THREE.Quaternion(unity.x, -unity.y, -unity.z, unity.w);
  }
  function quaternionUI(THREE, value, savedEuler) {
    if (savedEuler) {
      var expected = uiQuaternion(THREE, savedEuler);
      if (Math.abs(expected.dot(value)) > 1 - 1e-10) return savedEuler.slice();
    }
    var unity = new THREE.Quaternion(value.x, -value.y, -value.z, value.w);
    var angle = new THREE.Euler().setFromQuaternion(unity, "YXZ");
    return [angle.x, angle.y, angle.z].map(function (part) { return part * 180 / Math.PI; });
  }
  function toUI(THREE, value, savedEuler) {
    return { scale: value.scale.toArray(),
      position: [-value.position.x, value.position.y, value.position.z],
      rotation: quaternionUI(THREE, value.quaternion, savedEuler) };
  }
  function adjustmentEmpty(value) {
    return !value || ["scale", "position", "rotation"].every(function (kind) {
      return Array.isArray(value[kind]) && value[kind].length === 3 && value[kind].every(function (part) { return part === null; });
    });
  }

  function createNodeEditor(options) {
    var THREE = options.THREE, translate = options.translate, bones = options.bones;
    var selected = "", enabled = true, disposed = false, events = [], fields = {}, list = document.getElementById("viewer-node");
    var search = document.getElementById("viewer-node-search"), filter = document.getElementById("viewer-node-filter");
    var changeButtons = {};
    var poseCache = null;
    var compensationCheck = document.getElementById("bone-compensate-children"), compensationChoice = document.getElementById("bone-compensate-target");
    var compensationStatus = document.getElementById("bone-compensation-status"), automaticRow = null;
    var ownedLists = [document.getElementById("viewer-node-change-list")];
    ownedLists.forEach(function (container) { if (container) container.textContent = ""; });
    if (search) search.value = "";
    if (filter) filter.value = options.defaultFilter || "all";
    var labels = { Head: "Head", Head_Hair: "Hair", Neck_Hair: "Back hair", Spine: "Waist and torso",
      Spine2: "Upper body", HipsSize: "Hip size", BreastSize: "Breast size", Move: "Whole model",
      LeftThigh: "Left thigh", RightThigh: "Right thigh", LeftArm: "Left arm", RightArm: "Right arm" };
    function plainName(bone) { return (bone.object.name || bone.name).replace(/__\d+$/, ""); }
    function friendly(bone) {
      var name = plainName(bone), recommendation = (options.scaling.recommendedTargets || []).filter(function (item) {
        return String(item.node) === bone.id;
      })[0];
      return translate(labels[name] || recommendation && recommendation.label || (/Skirt/.test(name) ? "Skirt" : name));
    }
    function flags(id) { return options.flags(id); }
    function isFrequent(bone) {
      return ["Move", "Head", "Head_Hair", "Neck_Hair", "LeftArm", "RightArm", "LeftForeArm", "RightForeArm", "LeftLeg", "RightLeg"].indexOf(plainName(bone)) >= 0 && (!options.forTool || options.forTool(bone.id));
    }
    function optionLabel(bone) {
      var state = flags(bone.id), tags = [];
      if (state.saved) tags.push(translate("Saved settings"));
      if (state.modified) tags.push(translate("My changes"));
      if (state.body) tags.push(translate("Body adjustment"));
      if (state.expression) tags.push(translate("Expression"));
      return friendly(bone) + " · " + plainName(bone) + (tags.length ? " — " + tags.join(", ") : "");
    }
    function listen(target, name, handler) {
      if (!target) return;
      target.addEventListener(name, handler);
      events.push(function () { target.removeEventListener(name, handler); });
    }
    function select(id, open) {
      if (disposed) return;
      selected = id; list.value = id; options.onSelect(id);
      if (open) document.getElementById("viewer-node-editor").open = true;
      refresh(true);
    }
    function button(bone) {
      var value = document.createElement("button"); value.type = "button";
      value.textContent = optionLabel(bone); value.dataset.viewerBone = bone.id;
      value.disabled = !enabled;
      listen(value, "click", function () {
        if (search) search.value = ""; if (filter) filter.value = "all";
        select(bone.id, true);
      });
      return value;
    }
    function updateButtons(container, cache, items, emptyText) {
      if (!container) return;
      var visible = {};
      items.forEach(function (bone) {
        visible[bone.id] = true;
        if (!cache[bone.id]) { cache[bone.id] = button(bone); container.appendChild(cache[bone.id]); }
        cache[bone.id].textContent = optionLabel(bone); cache[bone.id].disabled = !enabled;
      });
      Object.keys(cache).forEach(function (id) { cache[id].style.display = visible[id] ? "" : "none"; });
      var empty = container.querySelector("[data-viewer-node-empty]");
      if (!empty) { empty = document.createElement("span"); empty.dataset.viewerNodeEmpty = "true"; container.appendChild(empty); }
      empty.textContent = translate(emptyText); empty.style.display = items.length ? "none" : "";
    }
    function refreshLists() {
      var term = search ? search.value.trim().toLowerCase() : "", mode = filter ? filter.value : "all";
      var visible = bones.filter(function (bone) {
        var state = flags(bone.id);
        var category = mode === "all" || mode === "tool" && (!options.forTool || options.forTool(bone.id)) || mode === "saved" && state.saved ||
          mode === "changed" && (state.modified || state.body || state.expression) ||
          mode === "frequent" && isFrequent(bone);
        return category && (!term || (friendly(bone) + " " + bone.name).toLowerCase().indexOf(term) >= 0);
      });
      // Filtering and switching tools must not retarget an existing edit.
      // A dedicated/advanced selection remains selected internally, while the
      // detail list asks for a new explicit choice rather than repeating it.
      list.textContent = "";
      var matched = visible.some(function (bone) { return bone.id === selected; });
      if (!matched) { var placeholder = document.createElement("option"); placeholder.value = ""; placeholder.disabled = true; placeholder.textContent = translate(visible.length ? "Choose a detail part" : "No matching bones"); list.appendChild(placeholder); }
      var groups = {}, groupOrder = ["model", "head", "arms", "legs", "other"];
      var groupLabels = { model: "Whole model", head: "Head and hair", arms: "Upper body and arms", legs: "Legs and feet", other: "Other bones" };
      visible.forEach(function (bone) {
        var name = plainName(bone), group = name === "Move" ? "model" : /Head|Hair/.test(name) ? "head" : /Arm|Shoulder|Spine|Hand|Breast/.test(name) ? "arms" : /Leg|Foot|Toe|Thigh|Hips/.test(name) ? "legs" : "other";
        if (!groups[group]) { groups[group] = document.createElement("optgroup"); groups[group].label = translate(groupLabels[group]); }
        var option = document.createElement("option"); option.value = bone.id; option.textContent = optionLabel(bone); groups[group].appendChild(option);
      });
      groupOrder.forEach(function (group) { if (groups[group]) list.appendChild(groups[group]); });
      list.value = matched ? selected : ""; list.disabled = !enabled || !visible.length;
      if (search) search.disabled = !enabled || !bones.length;
      if (filter) filter.disabled = !enabled || !bones.length;
      var changes = document.getElementById("viewer-node-change-list");
      updateButtons(changes, changeButtons, bones.filter(function (bone) {
        var value = flags(bone.id); return value.modified || value.body || value.expression;
      }), "No changed bones.");
    }
    function refreshInputValidation() {
      var messages = [];
      Object.keys(fields).forEach(function (kind) {
        fields[kind].forEach(function (input) {
          var key = input.dataset.viewerValidation;
          if (key) messages.push(input.dataset.axis + ": " + translate(key));
        });
      });
      validation.textContent = messages.join(" "); validation.hidden = !messages.length;
    }
    function clearInputValidation(input) {
      input.setCustomValidity(""); input.removeAttribute("aria-invalid"); input.removeAttribute("aria-describedby"); input.removeAttribute("title");
      delete input.dataset.viewerValidation;
    }
    function read(kind, axis, input) {
      if (!selected || !enabled) return;
      var value = Number(input.value), baseline = options.value(selected, false);
      if (!baseline) return;
      var invalid = !input.value.trim() || !isFinite(value) || value < Number(input.min) || value > Number(input.max) || kind === "scale" && Math.abs(value) < 1e-8;
      if (invalid) {
        var key = kind === "scale" ? "Scale must be a finite nonzero number between -1000000 and 1000000." : "Enter a finite number between -1000000 and 1000000.";
        input.dataset.viewerValidation = key; input.setCustomValidity(translate(key)); input.setAttribute("aria-invalid", "true");
        input.setAttribute("aria-describedby", validation.id); input.title = translate(key); refreshInputValidation();
        return;
      }
      clearInputValidation(input); refreshInputValidation();
      var previous = options.adjustment(selected);
      var absolute = { mode: "absolute_axes", scale: [null, null, null], position: [null, null, null], rotation: [null, null, null] };
      ["scale", "position", "rotation"].forEach(function (name) {
        if (!previous || previous.mode !== "absolute_axes" || !Array.isArray(previous[name])) return;
        for (var index = 0; index < 3; index += 1) {
          if (typeof previous[name][index] === "number" && isFinite(previous[name][index])) absolute[name][index] = previous[name][index];
        }
      });
      // Only the edited axis becomes explicit. Every other null axis inherits
      // its current animation/profile baseline; typed endpoints never become
      // ratios, offsets, or a quaternion delta when that baseline changes.
      // Re-entering the displayed baseline is still an explicit endpoint. Only
      // reset clears the null mask; a later Saved/profile switch must not move it.
      absolute[kind][axis] = kind === "position" && axis === 0 ? -value : value;
      options.change(selected, adjustmentEmpty(absolute) ? null : absolute);
      refresh(false);
    }
    function refreshCompensation() {
      var value = selected && options.compensation ? options.compensation(selected) : null;
      var state = value && value.parent, incoming = value && value.incoming || [], canEdit = !!(value && value.canEdit);
      // An old invalid Node+compensation edit may still be turned off. New
      // compensation is available only for the actual mesh save method.
      if (compensationCheck) {
        var checked = !!(state && state.enabled), checkDisabled = !enabled || !state || !canEdit && !state.enabled;
        if (compensationCheck.checked !== checked) compensationCheck.checked = checked;
        if (compensationCheck.disabled !== checkDisabled) compensationCheck.disabled = checkDisabled;
      }
      if (compensationChoice) {
        var mode = state ? state.mode : "auto", choiceDisabled = !enabled || !state || !canEdit;
        if (compensationChoice.value !== mode) compensationChoice.value = mode;
        if (compensationChoice.disabled !== choiceDisabled) compensationChoice.disabled = choiceDisabled;
      }
      if (compensationStatus) {
        var labels = { off: "Child compensation is off.", ready: "Child compensation is ready; change this bone’s scale to activate it.",
          active: "Child compensation is active.", unavailable: "Child compensation is unavailable." };
        var text = state ? translate(!canEdit ? state.enabled ? "Child compensation needs mesh baking. Turn it off or choose Mesh Baker." : "The current Node save method does not support child compensation. Use Mesh Baker when compensation is needed." : labels[state.state]) : translate("Choose a bone to edit.");
        if (state && state.reason && state.enabled) text += " " + translate(state.reason);
        if (state && state.state === "unavailable") text += " " + translate("No compensation was applied.");
        if (state) text += " " + translate("Targets") + ": " + (state.targets.length ? state.targets.map(function (target) { return target.name + " [" + target.node + "]"; }).join(", ") : "—");
        if (state && state.mode === "both") text += ". " + translate("Each target boundary is corrected separately; corrections accumulate farther down the hierarchy.");
        if (compensationStatus.textContent !== text) compensationStatus.textContent = text;
        var compensationState = state ? state.state : "off";
        if (compensationStatus.dataset.viewerCompensationState !== compensationState) compensationStatus.dataset.viewerCompensationState = compensationState;
        compensationStatus.classList.toggle("error", !!state && state.state === "unavailable");
      }
      var baseline = document.getElementById("viewer-node-baseline");
      if (!baseline) return;
      if (!incoming.length) { if (automaticRow && automaticRow.parentNode) automaticRow.parentNode.removeChild(automaticRow); return; }
      if (!automaticRow) {
        automaticRow = document.createElement("div"); automaticRow.dataset.viewerValueSource = "compensation"; automaticRow.dataset.viewerValueKind = "affine";
      }
      var parentIds = [], shear = incoming.some(function (target) { return target.shear; });
      incoming.forEach(function (target) { target.from.forEach(function (id) { if (parentIds.indexOf(id) < 0) parentIds.push(id); }); });
      var parents = parentIds.map(function (id) { var bone = bones.filter(function (entry) { return entry.id === id; })[0]; return bone ? plainName(bone) + " [" + id + "]" : id; });
      automaticRow.textContent = translate("Automatic affine compensation") + ": " + parents.join(", ") + ". " +
        translate(shear ? "Includes shear; manual TRS values stay unchanged." : "Manual TRS values stay unchanged.");
      automaticRow.dataset.viewerCompensationShear = String(shear);
      if (!automaticRow.parentNode) baseline.appendChild(automaticRow);
    }
    function refreshPose() {
      refreshCompensation();
      if (disposed || !poseCache || poseCache.selected !== selected) return;
      var poseValue = options.poseValue ? options.poseValue(selected) : null;
      var pose = poseValue ? toUI(THREE, poseValue, poseCache.savedEuler) : null;
      var poseQuaternion = poseValue ? poseValue.quaternion.toArray() : null;
      ["scale", "rotation", "position"].forEach(function (kind) {
        var row = poseCache.rows[kind], differs = false;
        if (pose && kind === "rotation") {
          differs = !poseCache.quaternion.every(function (part, axis) { return near(part, poseQuaternion[axis]); }) &&
            !poseCache.quaternion.every(function (part, axis) { return near(part, -poseQuaternion[axis]); });
        } else if (pose) differs = pose[kind].some(function (part, axis) { return !near(part, poseCache.values[kind][axis]); });
        if (!differs) {
          if (row.parentNode) row.parentNode.removeChild(row);
          return;
        }
        var label = kind === "scale" ? "Scale (local factor)" : kind === "position" ? "Position (model units)" : "Rotation (degrees)";
        var text = translate("Current pose value") + " · " + translate(label) + ": " +
          pose[kind].map(function (part) { return format(part, kind); }).join(" / ");
        if (row.textContent !== text) row.textContent = text;
        if (!row.parentNode) poseCache.parent.insertBefore(row, poseCache.anchors[kind].nextSibling);
      });
    }
    function refresh(force) {
      if (disposed) return;
      poseCache = null;
      refreshLists();
      var exists = !!selected, baselineValue = exists ? options.value(selected, false) : null;
      var currentValue = exists ? options.value(selected, true) : null;
      var savedEuler = exists && options.savedEuler ? options.savedEuler(selected) : null;
      var value = exists ? toUI(THREE, currentValue, savedEuler) : null;
      var absolute = exists ? options.adjustment(selected) : null;
      if (value && absolute && absolute.mode === "absolute_axes") {
        // Preserve the typed Unity Euler representation (350 must not become
        // -10 after a quaternion round-trip). Untouched axes still come from
        // the static active baseline, rather than a moving animation frame.
        var baselineEuler = quaternionUI(THREE, baselineValue.quaternion, savedEuler);
        value.rotation = baselineEuler.map(function (part, axis) {
          return absolute.rotation[axis] === null ? part : absolute.rotation[axis];
        });
      }
      Object.keys(fields).forEach(function (kind) {
        fields[kind].forEach(function (input, axis) {
          input.disabled = !enabled || !exists;
          if (!exists) { input.value = ""; clearInputValidation(input); return; }
          if (force || document.activeElement !== input) { input.value = format(value[kind][axis], kind); clearInputValidation(input); }
        });
      });
      refreshInputValidation();
      document.getElementById("viewer-node-reset").disabled = !enabled || !exists || !flags(selected).modified;
      var status = document.getElementById("viewer-node-status"), baseline = document.getElementById("viewer-node-baseline");
      if (status) status.textContent = exists ? optionLabel(bones.filter(function (bone) { return bone.id === selected; })[0]) : translate("Choose a bone to edit.");
      if (baseline) {
        baseline.textContent = "";
        if (exists) {
          var file = options.fileValues ? options.fileValues(selected) || {} : {};
          poseCache = { selected: selected, parent: baseline, rows: {}, anchors: {},
            values: { scale: value.scale.slice(), rotation: value.rotation.slice(), position: value.position.slice() },
            quaternion: currentValue.quaternion.toArray(), savedEuler: savedEuler ? savedEuler.slice() : null };
          function appendLine(category, kind, title, text, fileStatus) {
            var line = document.createElement("div");
            line.dataset.viewerValueSource = category; line.dataset.viewerValueKind = kind;
            if (fileStatus) line.dataset.viewerFileStatus = fileStatus;
            line.textContent = translate(title) + " · " + translate(kind === "scale" ? "Scale (local factor)" : kind === "position" ? "Position (model units)" : "Rotation (degrees)") + ": " + text;
            baseline.appendChild(line);
            return line;
          }
          function tripleText(parts, kind) {
            return parts.map(function (part, axis) { return format(kind === "position" && axis === 0 ? -part : part, kind); }).join(" / ");
          }
          ["scale", "rotation", "position"].forEach(function (kind) {
            var entry = file[kind] || {}, fileStatus = entry.status || "unavailable";
            var title = { saved: "File saved value", authored: "File authored value", conflict: "Conflicting file values", unsupported: "Unsupported file value" }[fileStatus] || "File value unavailable";
            var triples = fileStatus === "conflict" || fileStatus === "unsupported" ? entry.values || [] : [];
            if (!triples.length && Array.isArray(entry.value)) triples = [entry.value];
            appendLine("file", kind, title, triples.length ? triples.map(function (parts) { return tripleText(parts, kind); }).join(" | ") : "—", fileStatus);
            if (Array.isArray(entry.runtime)) appendLine("initialization", kind, "Game initial value", tripleText(entry.runtime, kind));
            poseCache.anchors[kind] = appendLine("editing", kind, "Current editing value", value[kind].map(function (part) { return format(part, kind); }).join(" / "));
            var row = document.createElement("div");
            row.dataset.viewerValueSource = "pose"; row.dataset.viewerValueKind = kind;
            poseCache.rows[kind] = row;
          });
          refreshPose();
        }
      }
      refreshCompensation();
    }
    var holder = document.getElementById("viewer-node-fields"); holder.textContent = "";
    var validation = document.createElement("p"); validation.id = "viewer-node-validation"; validation.className = "viewer-status error";
    validation.hidden = true; validation.setAttribute("role", "status"); validation.setAttribute("aria-live", "polite");
    holder.parentNode.insertBefore(validation, holder.nextSibling);
    [["scale", "Scale (local factor)", -1000000, 1000000, .001], ["rotation", "Rotation (degrees)", -1000000, 1000000, 1],
      ["position", "Position (model units)", -1000000, 1000000, .001]].forEach(function (definition) {
      var kind = definition[0], row = document.createElement("div"); row.className = "viewer-node-vector";
      var title = document.createElement("span"); title.dataset.label = definition[1]; row.appendChild(title); fields[kind] = [];
      AXES.forEach(function (axis, index) {
        var label = document.createElement("label"); label.appendChild(document.createTextNode(axis.toUpperCase()));
        var input = document.createElement("input"); input.type = "number"; input.min = definition[2]; input.max = definition[3]; input.step = definition[4];
        input.dataset.viewerNodeKind = kind; input.dataset.axis = axis.toUpperCase();
        listen(input, "input", function () { read(kind, index, input); });
        listen(input, "change", function () { refresh(true); });
        listen(input, "blur", function () { refresh(true); });
        fields[kind].push(input); label.appendChild(input); row.appendChild(label);
        if (window.ViewerSignedInputs) window.ViewerSignedInputs.attach(input, { signButton: false });
      }); holder.appendChild(row);
    });
    listen(list, "change", function () { if (this.value) select(this.value, true); });
    listen(search, "input", function () { refresh(true); });
    listen(filter, "change", function () { refresh(true); });
    function changeCompensation() {
      if (!selected || !enabled || !options.changeCompensation) return;
      options.changeCompensation(selected, { enabled: !!(compensationCheck && compensationCheck.checked), mode: compensationChoice ? compensationChoice.value : "auto" });
      refresh(true);
    }
    listen(compensationCheck, "change", changeCompensation);
    listen(compensationChoice, "change", changeCompensation);
    listen(document.getElementById("viewer-node-reset"), "click", function () { if (selected) { options.change(selected, null); refresh(true); } });
    selected = bones.some(function (bone) { return plainName(bone) === "Head"; }) ?
      bones.filter(function (bone) { return plainName(bone) === "Head"; })[0].id : bones.length ? bones[0].id : "";
    options.onSelect(selected);
    return { refresh: refresh, refreshPose: refreshPose, select: select, getSelected: function () { return selected; },
      setInteractive: function (value) { if (!disposed) { enabled = !!value; refresh(false); } },
      updateLanguage: function () {
        Array.prototype.forEach.call(holder.children, function (row) {
          row.firstChild.textContent = translate(row.firstChild.dataset.label);
          Array.prototype.forEach.call(row.querySelectorAll("input"), function (input) {
            input.setAttribute("aria-label", translate(row.firstChild.dataset.label) + " " + input.dataset.axis);
          });
        }); refresh(true);
      },
      dispose: function () {
        if (disposed) return;
        disposed = true; enabled = false; poseCache = null;
        if (compensationCheck) { compensationCheck.checked = false; compensationCheck.disabled = true; }
        if (compensationChoice) compensationChoice.disabled = true;
        if (compensationStatus) compensationStatus.textContent = "";
        if (automaticRow && automaticRow.parentNode) automaticRow.parentNode.removeChild(automaticRow);
        automaticRow = null;
        events.forEach(function (remove) { remove(); }); holder.textContent = "";
        if (validation.parentNode) validation.parentNode.removeChild(validation);
        ownedLists.forEach(function (container) { if (container) container.textContent = ""; });
        changeButtons = {};
      }
    };
  }
  window.ViewerEditing = { clone: clone, uiQuaternion: uiQuaternion, quaternionUI: quaternionUI, toUI: toUI, adjustmentEmpty: adjustmentEmpty,
    createNodeEditor: createNodeEditor };
}());
