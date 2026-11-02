/* Verified expression controls. Recipes come from the exported rig catalog;
 * unknown channels remain available by their original name in advanced UI. */
(function (global) {
  "use strict";
  function create(options) {
    var translate = options.translate || function (value) { return value; };
    var nodes = options.nodes || {}, channels = options.channels || [], catalog = options.catalog || {};
    var change = options.change || function () {}, disposed = false, interactive = false;
    var overrides = {}, boneOperations = {}, visibilityOperations = {}, selectedPresets = {};
    var channelByKey = {}, channelsByTarget = {}, metadataByTarget = {}, targetFamilies = {};
    var boneFamilies = {}, visibilityFamilies = {}, controls = [], presets = [], currentGroup = "";
    var selectedRaw = "", lastSelection = null, unavailable = 0, events = [], controlElements = [], partSelections = [];
    var presetButtons = [], groupButtons = [];
    function element(id) { return document.getElementById(id); }
    var ui = { panel: element("viewer-expression-panel"), groups: element("viewer-expression-groups"),
      presets: element("viewer-expression-presets"), raw: element("viewer-expression"),
      strength: element("viewer-expression-value"), output: element("viewer-expression-output"),
      status: element("viewer-expression-status"), reset: element("viewer-expression-reset"),
      selection: element("viewer-expression-selection"), advanced: element("viewer-expression-advanced") };
    function finite(value) { return typeof value === "number" && isFinite(value); }
    function own(object, key) { return Object.prototype.hasOwnProperty.call(object, key); }
    function family(group) {
      if (group === "all") return "all";
      if (/^(?:eyes?|brows?)(?:[-_].*)?$/.test(String(group))) return "eyes";
      return group === "mouth" ? "mouth" : "other";
    }
    function token(node, index) { return String(node) + ":" + String(index); }
    function channelName(channel) {
      var dictionary = channel.object && channel.object.morphTargetDictionary || {};
      return Object.keys(dictionary).filter(function (name) { return dictionary[name] === channel.index; });
    }
    channels.forEach(function (channel) {
      if (!channel || !channel.object || !channel.object.morphTargetInfluences ||
          !Number.isInteger(channel.index) || channel.index < 0 || channel.index >= channel.object.morphTargetInfluences.length) return;
      channelByKey[String(channel.key)] = channel;
      var key = token(channel.node, channel.index);
      if (!channelsByTarget[key]) channelsByTarget[key] = [];
      channelsByTarget[key].push(channel);
    });
    channels = channels.filter(function (channel) { return channel && channelByKey[String(channel.key)] === channel; });
    function targetValid(target) {
      if (!target || !Number.isInteger(target.node) || !Number.isInteger(target.index)) return false;
      var matches = channelsByTarget[token(target.node, target.index)];
      return !!matches && matches.length > 0 && matches.every(function (channel) {
        return typeof target.name !== "string" || channelName(channel).indexOf(target.name) >= 0;
      });
    }
    (catalog.rawChannels || []).forEach(function (entry) {
      if (targetValid(entry)) metadataByTarget[token(entry.node, entry.index)] = entry;
    });
    function boneValid(operation) {
      if (!operation || !Number.isInteger(operation.node) || !nodes[String(operation.node)] ||
          ["position", "quaternion", "scale"].indexOf(operation.kind) < 0 || !Array.isArray(operation.value) ||
          operation.value.length !== (operation.kind === "quaternion" ? 4 : 3) ||
          !operation.value.every(function (value) { return finite(value) && Math.abs(value) <= 1000; })) return false;
      if (operation.kind === "scale" && operation.value.some(function (value) { return Math.abs(value) < 1e-8; })) return false;
      if (operation.kind === "quaternion") {
        var norm = Math.sqrt(operation.value.reduce(function (sum, value) { return sum + value * value; }, 0));
        if (Math.abs(norm - 1) > .001) return false;
      }
      return true;
    }
    function visibilityValid(operation) {
      return operation && Number.isInteger(operation.node) && !!nodes[String(operation.node)] && typeof operation.visible === "boolean";
    }
    if (catalog.version === 1) {
      (catalog.controls || []).forEach(function (control) {
        if (!control || typeof control.id !== "string" || !control.targets || !control.targets.length ||
            !control.targets.every(targetValid) || !(control.resetTargets || []).every(targetValid)) { unavailable += 1; return; }
        controls.push(control);
        control.targets.concat(control.resetTargets || []).forEach(function (target) {
          targetFamilies[token(target.node, target.index)] = family(control.group);
        });
      });
      (catalog.presets || []).forEach(function (preset) {
        if (!preset || typeof preset.id !== "string" ||
            ["verified_game_clip", "verified_morph_shape", "viewer_combination"].indexOf(preset.source) < 0 ||
            !Array.isArray(preset.targets) || !preset.targets.every(function (target) {
              return targetValid(target) && finite(target.value) && target.value >= 0 && target.value <= 1;
            }) || !(preset.bones || []).every(boneValid) || !(preset.visibility || []).every(visibilityValid) ||
            !(preset.resetBones || []).every(function (id) { return Number.isInteger(id) && !!nodes[String(id)]; }) ||
            !(preset.resetVisibility || []).every(function (id) { return Number.isInteger(id) && !!nodes[String(id)]; }) ||
            (!preset.targets.length && !(preset.bones || []).length && !(preset.visibility || []).length)) { unavailable += 1; return; }
        presets.push(preset);
        var group = family(preset.group);
        if (group !== "all") {
          (preset.bones || []).forEach(function (operation) { boneFamilies[String(operation.node)] = group; });
          (preset.visibility || []).forEach(function (operation) { visibilityFamilies[String(operation.node)] = group; });
          preset.targets.forEach(function (target) { targetFamilies[token(target.node, target.index)] = group; });
        }
      });
      presets = presets.filter(function (preset) {
        if (preset.source !== "viewer_combination") return true;
        var valid = Array.isArray(preset.components) && preset.components.length > 0 && preset.components.every(function (id) {
          return presets.some(function (candidate) { return candidate.id === id && candidate.source !== "viewer_combination"; });
        });
        if (!valid) unavailable += 1;
        return valid;
      });
    }
    function channelFamily(channel) {
      var key = token(channel.node, channel.index), meta = metadataByTarget[key];
      return targetFamilies[key] || family(meta && meta.group);
    }
    function assignTarget(target, value) {
      (channelsByTarget[token(target.node, target.index)] || []).forEach(function (channel) { overrides[String(channel.key)] = value; });
    }
    function clearFamily(group) {
      Object.keys(overrides).forEach(function (key) {
        if (group === "all" || channelFamily(channelByKey[key]) === group) delete overrides[key];
      });
      [boneOperations, visibilityOperations].forEach(function (map) {
        Object.keys(map).forEach(function (key) { if (group === "all" || map[key].group === group || map[key].group === "all") delete map[key]; });
      });
      if (group === "all") selectedPresets = {};
      else { delete selectedPresets[group]; delete selectedPresets.all; }
    }
    function changed() {
      if (disposed) return;
      change(); refresh();
    }
    function selectPreset(preset) {
      if (!interactive || disposed) return;
      var group = family(preset.group);
      clearFamily(group);
      (preset.resetBones || []).forEach(function (id) {
        Object.keys(boneOperations).forEach(function (key) { if (boneOperations[key].node === id) delete boneOperations[key]; });
      });
      (preset.resetVisibility || []).forEach(function (id) { delete visibilityOperations[String(id)]; });
      preset.targets.forEach(function (target) { assignTarget(target, target.value); });
      (preset.bones || []).forEach(function (operation) {
        boneOperations[token(operation.node, operation.kind)] = { node: operation.node, kind: operation.kind,
          value: operation.value.slice(), group: boneFamilies[String(operation.node)] || group };
      });
      (preset.visibility || []).forEach(function (operation) {
        visibilityOperations[String(operation.node)] = { node: operation.node, visible: operation.visible,
          group: visibilityFamilies[String(operation.node)] || group };
      });
      selectedPresets[group] = preset.id;
      (preset.components || []).forEach(function (id) {
        var component = presets.filter(function (value) { return value.id === id; })[0];
        if (component) selectedPresets[family(component.group)] = component.id;
      });
      lastSelection = { label: preset.label, note: preset.note || "", kind: "preset", id: preset.id, group: group };
      changed();
    }
    function selectControl(control, value) {
      if (!interactive || disposed || !finite(value)) return;
      clearFamily(family(control.group));
      (control.resetTargets || []).forEach(function (target) { assignTarget(target, 0); });
      control.targets.forEach(function (target) { assignTarget(target, Math.max(0, Math.min(1, value))); });
      lastSelection = { label: control.label, note: control.note || "Shape control only.", kind: "shape", id: control.id, group: family(control.group) };
      changed();
    }
    function setRaw(value) {
      var channel = channelByKey[selectedRaw];
      if (!interactive || disposed || !channel || !finite(value)) return;
      overrides[selectedRaw] = Math.max(0, Math.min(1, value));
      delete selectedPresets[channelFamily(channel)]; delete selectedPresets.all;
      var meta = metadataByTarget[token(channel.node, channel.index)];
      lastSelection = { label: meta ? meta.label : "Original channel", note: "Original expression channel name is available in advanced controls.",
        kind: "raw", id: selectedRaw, group: channelFamily(channel) };
      changed();
    }
    function listen(node, event, handler) {
      if (!node) return;
      node.addEventListener(event, handler); events.push(function () { node.removeEventListener(event, handler); });
    }
    function addOption(parent, value, text) {
      var option = document.createElement("option"); option.value = value; option.textContent = text; parent.appendChild(option);
    }
    function rawLabel(channel) {
      var meta = metadataByTarget[token(channel.node, channel.index)];
      return meta ? translate(meta.label) + " — " + (meta.part || "") + " / " + meta.name : channel.name;
    }
    var groups = [];
    if (presets.some(function (preset) { return preset.group === "all"; })) groups.push({ id: "all", label: "Full face" });
    (catalog.groups || [{ id: "other", label: "Other expression channels" }]).forEach(function (group) {
      var id = family(group.id);
      if (groups.some(function (item) { return item.id === id; })) return;
      if (controls.some(function (control) { return family(control.group) === id; }) || presets.some(function (preset) { return family(preset.group) === id; }) ||
          channels.some(function (channel) { return channelFamily(channel) === id; })) groups.push({ id: id, label: group.label });
    });
    if (!groups.length && channels.length) groups.push({ id: "other", label: "Other expression channels" });
    currentGroup = groups.length ? groups[0].id : "";
    var shapes = element("viewer-expression-shapes"), controlHolder = element("viewer-expression-controls");
    if (!shapes && ui.presets && ui.presets.parentNode) {
      shapes = document.createElement("details"); shapes.id = "viewer-expression-shapes"; shapes.className = "viewer-expression-advanced";
      var heading = document.createElement("summary"); heading.dataset.expressionShapeHeading = "true"; shapes.appendChild(heading);
      controlHolder = document.createElement("div"); controlHolder.id = "viewer-expression-controls"; controlHolder.className = "viewer-expression-controls";
      shapes.appendChild(controlHolder); ui.presets.parentNode.insertBefore(shapes, ui.presets.nextSibling);
    }
    function renderPanel() {
      groupButtons = []; presetButtons = []; controlElements = [];
      if (ui.groups) {
        ui.groups.textContent = "";
        groups.forEach(function (group) {
          var button = document.createElement("button"); button.type = "button"; button.textContent = translate(group.label);
          button.dataset.viewerExpressionGroup = group.id;
          button.onclick = function () { currentGroup = group.id; renderPanel(); refresh(); };
          ui.groups.appendChild(button); groupButtons.push({ element: button, group: group.id });
        });
      }
      if (ui.presets) {
        ui.presets.textContent = "";
        presets.filter(function (preset) { return family(preset.group) === currentGroup; }).forEach(function (preset) {
          var button = document.createElement("button"); button.type = "button";
          button.textContent = translate(preset.label); button.dataset.viewerExpressionPreset = preset.id;
          button.title = translate(preset.note || "Expression preset");
          button.onclick = function () { selectPreset(preset); };
          ui.presets.appendChild(button); presetButtons.push({ element: button, preset: preset });
        });
      }
      if (controlHolder) {
        controlHolder.textContent = "";
        controls.filter(function (control) { return family(control.group) === currentGroup; }).forEach(function (control) {
          var label = document.createElement("label"), title = document.createElement("span"), input = document.createElement("input"), output = document.createElement("output");
          label.className = "viewer-expression-control"; title.textContent = translate(control.label);
          input.type = "range"; input.min = "0"; input.max = "100"; input.step = "1";
          input.dataset.viewerExpressionControl = control.id; input.setAttribute("aria-label", translate(control.label));
          input.oninput = function () { selectControl(control, Number(input.value) / 100); };
          label.appendChild(title); label.appendChild(input); label.appendChild(output);
          if (control.note) { var note = document.createElement("small"); note.textContent = translate(control.note); label.appendChild(note); }
          controlHolder.appendChild(label); controlElements.push({ control: control, input: input, output: output });
        });
      }
      if (shapes) {
        shapes.hidden = !controlElements.length;
        var summary = shapes.querySelector("summary"); if (summary) summary.textContent = translate("Fine-tune shapes");
      }
      if (ui.raw) {
        ui.raw.textContent = ""; addOption(ui.raw, "", translate("Select an expression part"));
        groups.filter(function (group) { return group.id !== "all"; }).forEach(function (group) {
          var holder = document.createElement("optgroup"); holder.label = translate(group.label);
          channels.filter(function (channel) { return channelFamily(channel) === group.id; }).forEach(function (channel) { addOption(holder, String(channel.key), rawLabel(channel)); });
          if (holder.children.length) ui.raw.appendChild(holder);
        });
        ui.raw.value = selectedRaw;
      }
      if (!presets.some(function (preset) { return family(preset.group) === currentGroup; }) && !controlElements.length && ui.advanced && channels.length) ui.advanced.open = true;
    }
    function weightsFor(control) {
      var result = [];
      control.targets.forEach(function (target) {
        (channelsByTarget[token(target.node, target.index)] || []).forEach(function (channel) { result.push(channel.object.morphTargetInfluences[channel.index]); });
      });
      return result;
    }
    function refresh() {
      if (disposed) return;
      var enabled = interactive && channels.length > 0;
      if (ui.panel) ui.panel.hidden = !channels.length;
      groupButtons.forEach(function (entry) { entry.element.disabled = !enabled; entry.element.setAttribute("aria-pressed", String(entry.group === currentGroup)); });
      presetButtons.forEach(function (entry) {
        entry.element.disabled = !enabled;
        entry.element.setAttribute("aria-pressed", String(selectedPresets[family(entry.preset.group)] === entry.preset.id));
      });
      controlElements.forEach(function (entry) {
        var values = weightsFor(entry.control), value = values.length ? values[0] : 0;
        var mixed = values.some(function (item) { return Math.abs(item - value) > 1e-6; });
        entry.input.disabled = !enabled; entry.input.value = String(value * 100);
        entry.output.textContent = mixed ? translate("Mixed values") : Math.round(value * 100) + "%";
      });
      if (ui.raw) ui.raw.disabled = !enabled;
      var channel = channelByKey[selectedRaw], value = channel ? channel.object.morphTargetInfluences[channel.index] * 100 : 0;
      if (ui.strength) { ui.strength.disabled = !enabled || !channel; ui.strength.value = String(value); }
      if (ui.output) ui.output.textContent = Math.round(value) + "%";
      if (ui.reset) ui.reset.disabled = !enabled || !(Object.keys(overrides).length || Object.keys(boneOperations).length || Object.keys(visibilityOperations).length);
      if (ui.selection) {
        ui.selection.textContent = lastSelection ? translate(lastSelection.label) + (lastSelection.note ? " — " + translate(lastSelection.note) : "") :
          !controls.length && !presets.length && channels.length ? translate("Only original channel names are available for this model.") : "";
      }
      if (ui.status) {
        var seen = [], exceeded = channels.some(function (item) {
          if (seen.indexOf(item.object) >= 0) return false; seen.push(item.object);
          var active = item.object.morphTargetInfluences.filter(function (weight) { return Math.abs(weight) > 1e-6; }).length;
          var normals = item.object.geometry && item.object.geometry.morphAttributes && item.object.geometry.morphAttributes.normal;
          return active > (normals && normals.length ? 4 : 8);
        });
        ui.status.hidden = !exceeded && !unavailable;
        ui.status.textContent = exceeded ? translate("Too many expression channels are active. Some may be omitted by the viewer.") :
          unavailable ? translate("Some expression presets are unavailable for this model.") : "";
      }
    }
    function getBoneOperations() {
      return Object.keys(boneOperations).sort().map(function (key) {
        var value = boneOperations[key]; return { node: value.node, kind: value.kind, value: value.value.slice(), source: "expression" };
      });
    }
    function applyBonesAndMorphs() {
      if (disposed) return;
      getBoneOperations().forEach(function (operation) { nodes[String(operation.node)][operation.kind].fromArray(operation.value); });
      Object.keys(overrides).forEach(function (key) {
        var channel = channelByKey[key]; if (channel) channel.object.morphTargetInfluences[channel.index] = overrides[key];
      });
    }
    function applyVisibility(parts) {
      if (disposed) return;
      var hidden = [];
      (parts || []).forEach(function (part) {
        if (!part.object) return;
        var record = partSelections.filter(function (item) { return item.object === part.object; })[0];
        if (!record) { record = { object: part.object, last: part.visible, touched: false }; partSelections.push(record); }
        else if (record.last !== part.visible) record.touched = true;
        record.last = part.visible;
        // An authored-hidden part can be revealed by an original eye recipe.
        // Only an explicit user's hidden choice must veto that recipe.
        var choice = typeof part.userVisible === "boolean" ? part.userVisible :
          part.userChanged === true || record.touched ? part.visible : undefined;
        if (choice === false) hidden.push(part.object);
      });
      Object.keys(visibilityOperations).forEach(function (key) { nodes[key].visible = visibilityOperations[key].visible; });
      hidden.forEach(function (object) { object.visible = false; });
    }
    function reset(silent) {
      overrides = {}; boneOperations = {}; visibilityOperations = {}; selectedPresets = {}; lastSelection = null; selectedRaw = "";
      if (ui.raw) ui.raw.value = "";
      if (!silent) changed(); else refresh();
    }
    listen(ui.raw, "change", function () { selectedRaw = ui.raw.value; refresh(); });
    listen(ui.strength, "input", function () { setRaw(Number(ui.strength.value) / 100); });
    listen(ui.reset, "click", function () { if (!ui.reset.disabled) reset(false); });
    renderPanel(); refresh();
    return {
      applyBonesAndMorphs: applyBonesAndMorphs, applyVisibility: applyVisibility, getBoneOperations: getBoneOperations,
      refresh: refresh, reset: reset,
      setInteractive: function (value) { interactive = !!value; refresh(); },
      updateLanguage: function () { renderPanel(); refresh(); },
      getState: function () { return { group: currentGroup, selectedRaw: selectedRaw, selectedPresets: Object.assign({}, selectedPresets),
        overrides: Object.assign({}, overrides), boneOperations: getBoneOperations(),
        visibility: Object.keys(visibilityOperations).map(function (key) { var value = visibilityOperations[key]; return {node: value.node, visible: value.visible}; }),
        controls: controls.map(function (control) { return { id: control.id, group: control.group, label: control.label, values: weightsFor(control) }; }),
        presets: presets.map(function (preset) { return { id: preset.id, group: preset.group, label: preset.label, complete: preset.complete, source: preset.source, scope: preset.scope }; }),
        unavailablePresets: unavailable, truncatedCatalog: !!catalog.truncated }; },
      dispose: function () {
        disposed = true; events.forEach(function (remove) { remove(); });
        [ui.groups, ui.presets, controlHolder].forEach(function (node) { if (node) node.textContent = ""; });
        groupButtons = []; presetButtons = []; controlElements = []; partSelections = [];
      }
    };
  }
  global.ViewerExpressions = { create: create };
})(window);
