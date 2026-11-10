/* Verified expression controls. Recipes come from the exported rig catalog;
 * unknown channels remain available by their original name in advanced UI. */
(function (global) {
  "use strict";
  function create(options) {
    var translate = options.translate || function (value) { return value; };
    var nodes = options.nodes || {}, channels = options.channels || [], catalog = options.catalog || {};
    var change = options.change || function () {}, disposed = false, interactive = false;
    var overrides = {}, boneOperations = {}, visibilityOperations = {}, selectedPresets = {};
    var channelByKey = {}, channelsByTarget = {}, metadataByTarget = {}, targetFamilies = {}, authoredWeights = {};
    var boneFamilies = {}, visibilityFamilies = {}, controls = [], presets = [], currentGroup = "";
    var selectedRaw = "", lastSelection = null, unavailable = 0, events = [], controlElements = [], partSelections = [];
    var presetButtons = [], groupButtons = [], rawError = "", rawInputValues = {};
    var gaze = global.ViewerGaze && options.root ? global.ViewerGaze.create(options.root, options.animations || [], options.metadata || {}) : null;
    var gazeSettings = { mode: "motion", horizontal: 0, vertical: 0, strength: 1 }, gazeOperations = [], gazeUi = null;
    function element(id) { return document.getElementById(id); }
    var ui = { panel: element("viewer-expression-panel"), groups: element("viewer-expression-groups"),
      presets: element("viewer-expression-presets"), raw: element("viewer-expression"),
      strength: element("viewer-expression-value"), number: element("viewer-expression-number"),
      output: element("viewer-expression-output"), source: element("viewer-expression-source"),
      status: element("viewer-expression-status"), reset: element("viewer-expression-reset"),
      selection: element("viewer-expression-selection"), advanced: element("viewer-expression-advanced"),
      gazeHost: element("viewer-pose-gaze") };
    function finite(value) { return typeof value === "number" && isFinite(value); }
    function percentNumber(value) { return finite(value) ? String(Number((value * 100).toFixed(2))) : ""; }
    function percent(value) { return finite(value) ? percentNumber(value) + "%" : "—"; }
    function own(object, key) { return Object.prototype.hasOwnProperty.call(object, key); }
    function property(target, name, value) { if (target[name] !== value) target[name] = value; }
    function attribute(target, name, value) { if (target.getAttribute(name) !== value) target.setAttribute(name, value); }
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
      // This is the file's actual glTF weight before motion or viewer overrides.
      // Keep it separate from the live influences that change during playback.
      authoredWeights[String(channel.key)] = channel.object.morphTargetInfluences[channel.index];
      var key = token(channel.node, channel.index);
      if (!channelsByTarget[key]) channelsByTarget[key] = [];
      channelsByTarget[key].push(channel);
    });
    channels = channels.filter(function (channel) { return channel && channelByKey[String(channel.key)] === channel; });
    Object.freeze(authoredWeights);
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
    function rawRange(channel) {
      var source = authoredWeights[String(channel.key)], current = channel.object.morphTargetInfluences[channel.index];
      return { min: Math.min(0, finite(source) ? source * 100 : 0, finite(current) ? current * 100 : 0),
        max: Math.max(100, finite(source) ? source * 100 : 100, finite(current) ? current * 100 : 100) };
    }
    function inputError(value) {
      rawError = value ? "Expression weight must be a finite number between -10000% and 10000%." : "";
      if (ui.number) {
        ui.number.setCustomValidity(rawError ? translate(rawError) : "");
        ui.number.setAttribute("aria-invalid", String(!!rawError));
      }
    }
    function selectPreset(preset) {
      if (!interactive || disposed) return;
      inputError(false);
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
      inputError(false);
      clearFamily(family(control.group));
      (control.resetTargets || []).forEach(function (target) { assignTarget(target, 0); });
      control.targets.forEach(function (target) { assignTarget(target, Math.max(0, Math.min(1, value))); });
      lastSelection = { label: control.label, note: control.note || "Shape control only.", kind: "shape", id: control.id, group: family(control.group) };
      changed();
    }
    function setRaw(value, typedPercent) {
      var channel = channelByKey[selectedRaw];
      if (!interactive || disposed || !channel) return;
      // Match the exporter's preview bound, without turning a rejected edit
      // into a different weight. Named game presets retain their 0..1 endpoints.
      if (!finite(value) || Math.abs(value) > 100) { inputError(true); refresh(); return; }
      inputError(false);
      overrides[selectedRaw] = value;
      if (typeof typedPercent === "string") rawInputValues[selectedRaw] = { weight: value, text: typedPercent };
      else delete rawInputValues[selectedRaw];
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
    function gazeAvailable() { return !!gaze && gaze.getState().available; }
    function gazeChanged() { gazeOperations = []; changed(); }
    function makeGazeUi() {
      if (!(ui.gazeHost || ui.panel) || !gaze) return;
      var holder = document.createElement("details"), heading = document.createElement("summary"), fields = document.createElement("div");
      holder.id = "viewer-expression-gaze"; holder.className = "viewer-expression-advanced viewer-expression-gaze";
      holder.appendChild(heading); fields.className = "viewer-expression-controls"; holder.appendChild(fields);
      var modeLabel = document.createElement("label"), modeTitle = document.createElement("span"), mode = document.createElement("select");
      mode.id = "viewer-gaze-mode"; modeLabel.className = "viewer-expression-control";
      modeLabel.appendChild(modeTitle); modeLabel.appendChild(mode); fields.appendChild(modeLabel);
      var controls = [];
      [["horizontal", -100, 100], ["vertical", -100, 100], ["strength", 0, 100]].forEach(function (spec) {
        var label = document.createElement("label"), title = document.createElement("span"), slider = document.createElement("input"), numberInput = document.createElement("input");
        label.className = "viewer-expression-control"; slider.type = "range"; slider.min = String(spec[1]); slider.max = String(spec[2]); slider.step = "any";
        slider.id = "viewer-gaze-" + spec[0]; numberInput.id = slider.id + "-number"; numberInput.type = "number";
        numberInput.min = slider.min; numberInput.max = slider.max; numberInput.step = "any";
        label.appendChild(title); label.appendChild(slider); label.appendChild(numberInput); fields.appendChild(label);
        function input(value) {
          if (!interactive || !gazeAvailable()) return;
          if (!value.trim() || !isFinite(Number(value)) || Number(value) < spec[1] || Number(value) > spec[2]) { numberInput.setCustomValidity(translate("Enter a gaze value within the displayed range.")); return; }
          numberInput.setCustomValidity(""); gazeSettings[spec[0]] = Number(value) / 100;
          if (spec[0] !== "strength") gazeSettings.mode = "direction";
          gazeChanged();
        }
        listen(slider, "input", function () { input(slider.value); }); listen(numberInput, "input", function () { input(numberInput.value); });
        listen(numberInput, "blur", function () { numberInput.setCustomValidity(""); refreshGazeUi(); });
        controls.push({ key: spec[0], title: title, slider: slider, number: numberInput });
      });
      var resetButton = document.createElement("button"), status = document.createElement("p"); resetButton.type = "button"; resetButton.id = "viewer-gaze-reset";
      status.id = "viewer-gaze-status"; status.className = "viewer-info"; fields.appendChild(resetButton); fields.appendChild(status);
      var host = ui.gazeHost || ui.panel;
      host.insertBefore(holder, host.firstChild);
      gazeUi = { holder: holder, heading: heading, mode: mode, modeTitle: modeTitle, controls: controls, reset: resetButton, status: status };
      listen(mode, "change", function () { if (!interactive || !gazeAvailable()) return; gazeSettings.mode = mode.value; gazeChanged(); });
      listen(resetButton, "click", function () { if (!interactive) return; gazeSettings = { mode: "motion", horizontal: 0, vertical: 0, strength: 1 }; gazeChanged(); });
    }
    function refreshGazeUi() {
      if (!gazeUi) return;
      var available = gazeAvailable(), enabled = interactive && available, state = gazeSettings.mode === "motion" && options.getMotionGazeState && options.getMotionGazeState() || gaze.getState();
      property(gazeUi.heading, "textContent", translate("Gaze")); property(gazeUi.modeTitle, "textContent", translate("Gaze control"));
      if (gazeUi.mode.options.length !== 4 || gazeUi.mode.dataset.language !== translate("Follow motion gaze")) {
        gazeUi.mode.textContent = "";
        [["motion", "Follow motion gaze"], ["camera", "Look at the preview camera"], ["front", "Look straight ahead"], ["direction", "Adjust gaze direction"]].forEach(function (entry) { addOption(gazeUi.mode, entry[0], translate(entry[1])); });
        gazeUi.mode.dataset.language = translate("Follow motion gaze");
      }
      property(gazeUi.mode, "value", gazeSettings.mode); property(gazeUi.mode, "disabled", !enabled);
      gazeUi.controls.forEach(function (control) {
        var title = control.key === "horizontal" ? "Horizontal gaze" : control.key === "vertical" ? "Vertical gaze" : "Gaze strength";
        property(control.title, "textContent", translate(title));
        property(control.slider, "disabled", !enabled || control.key !== "strength" && gazeSettings.mode !== "direction");
        property(control.number, "disabled", control.slider.disabled);
        property(control.slider, "value", percentNumber(gazeSettings[control.key]));
        if (document.activeElement !== control.number) property(control.number, "value", percentNumber(gazeSettings[control.key]));
        control.slider.setAttribute("aria-label", translate(title)); control.number.setAttribute("aria-label", translate(title));
      });
      property(gazeUi.reset, "textContent", translate("Follow motion gaze")); property(gazeUi.reset, "disabled", !enabled || gazeSettings.mode === "motion");
      property(gazeUi.status, "textContent", !available ? translate("Open the original face and its eye-pose animation bank to adjust gaze.") :
        state.missingTargets.length ? translate("The original gaze target is unavailable in this preview.") : translate("Gaze uses the original eye poses without changing eyelids or mouth shapes."));
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
          input.type = "range"; input.min = "0"; input.max = "100"; input.step = "any";
          input.dataset.viewerExpressionControl = control.id; input.setAttribute("aria-label", translate(control.label));
          input.oninput = function () { selectControl(control, Number(input.value) / 100); };
          var mixedButton = document.createElement("button"); mixedButton.type = "button";
          mixedButton.textContent = translate("Set shape to 100%"); mixedButton.dataset.viewerExpressionMixed = control.id;
          mixedButton.title = translate("Editing this shape replaces mixed values.");
          mixedButton.onclick = function () { selectControl(control, 1); };
          label.appendChild(title); label.appendChild(input); label.appendChild(output);
          label.appendChild(mixedButton);
          if (control.note) { var note = document.createElement("small"); note.textContent = translate(control.note); label.appendChild(note); }
          controlHolder.appendChild(label); controlElements.push({ control: control, input: input, output: output, mixedButton: mixedButton });
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
      if (ui.panel) property(ui.panel, "hidden", !channels.length && (!!ui.gazeHost || !gazeAvailable()));
      refreshGazeUi();
      groupButtons.forEach(function (entry) { property(entry.element, "disabled", !enabled); attribute(entry.element, "aria-pressed", String(entry.group === currentGroup)); });
      presetButtons.forEach(function (entry) {
        property(entry.element, "disabled", !enabled);
        attribute(entry.element, "aria-pressed", String(selectedPresets[family(entry.preset.group)] === entry.preset.id));
      });
      controlElements.forEach(function (entry) {
        var values = weightsFor(entry.control), value = values.length ? values[0] : 0;
        var mixed = values.some(function (item) { return Math.abs(item - value) > 1e-6; });
        var outside = !finite(value) || value < 0 || value > 1;
        // A range has no indeterminate state. Do not give its first target a
        // precise-looking thumb when the grouped renderer weights differ.
        property(entry.input, "hidden", mixed || outside);
        property(entry.input, "disabled", !enabled || mixed || outside);
        if (!mixed && !outside) property(entry.input, "value", percentNumber(value));
        attribute(entry.input, "aria-valuetext", mixed ? translate("Mixed values") : percent(value));
        property(entry.output, "textContent", mixed ? translate("Mixed values") : percent(value));
        property(entry.output, "title", translate("Current weight") + ": " + values.map(percent).join(", "));
        property(entry.mixedButton, "hidden", !mixed && !outside);
        property(entry.mixedButton, "disabled", !enabled);
      });
      if (ui.raw) property(ui.raw, "disabled", !enabled);
      var channel = channelByKey[selectedRaw], value = channel ? channel.object.morphTargetInfluences[channel.index] : null;
      if (ui.strength) {
        property(ui.strength, "disabled", !enabled || !channel || !finite(value));
        if (channel) {
          var range = rawRange(channel); property(ui.strength, "min", String(range.min)); property(ui.strength, "max", String(range.max)); property(ui.strength, "step", "any");
          if (finite(value)) property(ui.strength, "value", percentNumber(value));
          attribute(ui.strength, "aria-valuetext", percent(value));
        }
      }
      if (ui.number) {
        property(ui.number, "min", "-10000"); property(ui.number, "max", "10000"); property(ui.number, "step", "any");
        property(ui.number, "disabled", !enabled || !channel);
        if (document.activeElement !== ui.number && !rawError) property(ui.number, "value", channel && finite(value) ?
          percentNumber(value) : "");
        ui.number.setCustomValidity(rawError ? translate(rawError) : "");
      }
      if (ui.output) property(ui.output, "textContent", percent(value));
      if (ui.source) {
        property(ui.source, "hidden", !channel);
        property(ui.source, "textContent", channel ? translate("File weight") + ": " + percent(authoredWeights[selectedRaw]) +
          " · " + translate("Current weight") + ": " + percent(value) : "");
      }
      if (ui.reset) property(ui.reset, "disabled", !interactive || !(Object.keys(overrides).length || Object.keys(boneOperations).length || Object.keys(visibilityOperations).length || gazeSettings.mode !== "motion"));
      if (ui.selection) {
        property(ui.selection, "textContent", lastSelection ? translate(lastSelection.label) + (lastSelection.note ? " — " + translate(lastSelection.note) : "") :
          !controls.length && !presets.length && channels.length ? translate("Only original channel names are available for this model.") : "");
      }
      if (ui.status) {
        var seen = [], exceeded = channels.some(function (item) {
          if (seen.indexOf(item.object) >= 0) return false; seen.push(item.object);
          var active = item.object.morphTargetInfluences.filter(function (weight) { return Math.abs(weight) > 1e-6; }).length;
          var normals = item.object.geometry && item.object.geometry.morphAttributes && item.object.geometry.morphAttributes.normal;
          return active > (normals && normals.length ? 4 : 8);
        });
        var notices = [];
        if (rawError) notices.push(translate(rawError));
        if (exceeded) notices.push(translate("Too many expression channels are active. Some may be omitted by the viewer."));
        if (unavailable) notices.push(translate("Some expression presets are unavailable for this model."));
        property(ui.status, "hidden", !notices.length); property(ui.status, "textContent", notices.join(" "));
      }
    }
    function explicitBoneOperations() {
      return Object.keys(boneOperations).sort().map(function (key) {
        var value = boneOperations[key]; return { node: value.node, kind: value.kind, value: value.value.slice(), source: "expression" };
      });
    }
    function getBoneOperations() {
      var result = explicitBoneOperations();
      gazeOperations.forEach(function (operation) {
        result = result.filter(function (current) { return current.node !== operation.node || current.kind !== operation.kind; });
        result.push({ node: operation.node, kind: operation.kind, value: operation.value.slice(), source: "expression" });
      });
      return result;
    }
    function applyBonesAndMorphs() {
      if (disposed) return;
      explicitBoneOperations().forEach(function (operation) { nodes[String(operation.node)][operation.kind].fromArray(operation.value); });
      Object.keys(overrides).forEach(function (key) {
        var channel = channelByKey[key]; if (channel) channel.object.morphTargetInfluences[channel.index] = overrides[key];
      });
      gazeOperations = [];
      if (gaze && gazeSettings.mode !== "motion") {
        var values = gazeSettings.mode === "direction" ? gaze.axes(gazeSettings.horizontal, gazeSettings.vertical) :
          gazeSettings.mode === "camera" ? gaze.targetWeights(21, options.getGazeContext ? options.getGazeContext() : {}) : {};
        if (values) {
          Object.keys(values).forEach(function (id) { values[id] *= gazeSettings.strength; });
          if (gaze.apply(values, true)) gazeOperations = gaze.operations();
        }
      }
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
        var choice;
        if (typeof part.userChanged === "boolean") {
          // The rig explicitly clears this flag on global reset. Old selection
          // history must not turn an authored-hidden part into a manual veto.
          if (part.userChanged) choice = typeof part.userVisible === "boolean" ? part.userVisible : part.visible;
        } else choice = typeof part.userVisible === "boolean" ? part.userVisible : record.touched ? part.visible : undefined;
        if (choice === false) hidden.push(part.object);
      });
      Object.keys(visibilityOperations).forEach(function (key) { nodes[key].visible = visibilityOperations[key].visible; });
      hidden.forEach(function (object) { object.visible = false; });
    }
    function reset(silent) {
      overrides = {}; boneOperations = {}; visibilityOperations = {}; selectedPresets = {}; lastSelection = null; selectedRaw = "";
      rawInputValues = {}; partSelections = [];
      gazeSettings = { mode: "motion", horizontal: 0, vertical: 0, strength: 1 }; gazeOperations = [];
      inputError(false);
      if (ui.raw) ui.raw.value = "";
      if (!silent) changed(); else refresh();
    }
    function restoreState(state) {
      if (disposed || !state || typeof state !== "object" || Array.isArray(state) ||
          !state.overrides || typeof state.overrides !== "object" || Array.isArray(state.overrides) ||
          !Array.isArray(state.boneOperations) || !Array.isArray(state.visibility) ||
          !state.selectedPresets || typeof state.selectedPresets !== "object" || Array.isArray(state.selectedPresets) ||
          typeof state.group !== "string" || typeof state.selectedRaw !== "string" ||
          !(groups.length ? groups.some(function (group) { return group.id === state.group; }) : state.group === "") ||
          state.selectedRaw && !own(channelByKey, state.selectedRaw)) return false;
      var nextOverrides = {}, nextBones = {}, nextVisibility = {}, nextPresets = {}, valid = true;
      Object.keys(state.overrides).forEach(function (key) {
        var value = state.overrides[key];
        if (!own(channelByKey, key) || !finite(value) || Math.abs(value) > 100) valid = false;
        else nextOverrides[key] = value;
      });
      state.boneOperations.forEach(function (operation) {
        if (!boneValid(operation)) { valid = false; return; }
        var key = token(operation.node, operation.kind);
        if (own(nextBones, key)) { valid = false; return; }
        nextBones[key] = { node: operation.node, kind: operation.kind, value: operation.value.slice(),
          group: boneFamilies[String(operation.node)] || "all" };
      });
      state.visibility.forEach(function (operation) {
        if (!visibilityValid(operation) || own(nextVisibility, String(operation.node))) { valid = false; return; }
        nextVisibility[String(operation.node)] = { node: operation.node, visible: operation.visible,
          group: visibilityFamilies[String(operation.node)] || "all" };
      });
      Object.keys(state.selectedPresets).forEach(function (group) {
        var id = state.selectedPresets[group];
        if (!presets.some(function (preset) { return preset.id === id && family(preset.group) === group; })) valid = false;
        else nextPresets[group] = id;
      });
      if (!valid) return false;
      var nextGaze = { mode: "motion", horizontal: 0, vertical: 0, strength: 1 };
      if (state.gaze !== undefined) {
        if (!state.gaze || ["motion", "camera", "front", "direction"].indexOf(state.gaze.mode) < 0 ||
            !["horizontal", "vertical", "strength"].every(function (key) { return finite(state.gaze[key]) && Math.abs(state.gaze[key]) <= 1; }) || state.gaze.strength < 0 ||
            state.gaze.mode !== "motion" && !gazeAvailable()) return false;
        nextGaze = { mode: state.gaze.mode, horizontal: state.gaze.horizontal, vertical: state.gaze.vertical, strength: state.gaze.strength };
      }
      // Commit only after validating the complete snapshot. Display rounding
      // never feeds back into the restored morph weights or bone transforms.
      overrides = nextOverrides; boneOperations = nextBones; visibilityOperations = nextVisibility;
      selectedPresets = nextPresets; currentGroup = state.group; selectedRaw = state.selectedRaw;
      gazeSettings = nextGaze; gazeOperations = [];
      rawInputValues = {}; partSelections = []; lastSelection = null; inputError(false);
      var selection = state.lastSelection;
      if (selection && selection.kind === "preset") {
        var preset = presets.filter(function (entry) { return entry.id === selection.id; })[0];
        if (preset) lastSelection = { label: preset.label, note: preset.note || "", kind: "preset", id: preset.id, group: family(preset.group) };
      } else if (selection && selection.kind === "shape") {
        var control = controls.filter(function (entry) { return entry.id === selection.id; })[0];
        if (control) lastSelection = { label: control.label, note: control.note || "Shape control only.", kind: "shape", id: control.id, group: family(control.group) };
      } else if (selectedRaw) {
        var channel = channelByKey[selectedRaw], meta = metadataByTarget[token(channel.node, channel.index)];
        lastSelection = { label: meta ? meta.label : "Original channel", note: "Original expression channel name is available in advanced controls.", kind: "raw", id: selectedRaw, group: channelFamily(channel) };
      }
      renderPanel(); changed(); return true;
    }
    listen(ui.raw, "change", function () { selectedRaw = ui.raw.value; inputError(false); refresh(); });
    listen(ui.strength, "input", function () { setRaw(Number(ui.strength.value) / 100); });
    listen(ui.number, "input", function () { setRaw(ui.number.value.trim() ? Number(ui.number.value) / 100 : NaN, ui.number.value); });
    listen(ui.number, "change", function () { if (rawError) ui.number.reportValidity(); else refresh(); });
    listen(ui.number, "blur", function () { if (!rawError) refresh(); });
    listen(ui.reset, "click", function () { if (!ui.reset.disabled) reset(false); });
    makeGazeUi(); renderPanel(); refresh();
    return {
      applyBonesAndMorphs: applyBonesAndMorphs, applyVisibility: applyVisibility, getBoneOperations: getBoneOperations,
      refresh: refresh, reset: reset, restoreState: restoreState,
      setInteractive: function (value) { interactive = !!value; refresh(); },
      updateLanguage: function () { renderPanel(); refresh(); },
      getState: function () { return { group: currentGroup, selectedRaw: selectedRaw, selectedPresets: Object.assign({}, selectedPresets), lastSelection: lastSelection && Object.assign({}, lastSelection),
        rawWeights: channels.map(function (channel) { return { key: String(channel.key), sourceWeight: authoredWeights[String(channel.key)],
          currentWeight: channel.object.morphTargetInfluences[channel.index] }; }),
        rawRange: channelByKey[selectedRaw] ? rawRange(channelByKey[selectedRaw]) : null, rawInputError: rawError,
        overrides: Object.assign({}, overrides), boneOperations: explicitBoneOperations(),
        gaze: Object.assign({}, gaze && gaze.getState() || { available: false, directions: [], weights: {}, missingTargets: [], warnings: [] }, gazeSettings),
        visibility: Object.keys(visibilityOperations).map(function (key) { var value = visibilityOperations[key]; return {node: value.node, visible: value.visible}; }),
        controls: controls.map(function (control) { return { id: control.id, group: control.group, label: control.label, values: weightsFor(control) }; }),
        presets: presets.map(function (preset) { return { id: preset.id, group: preset.group, label: preset.label, complete: preset.complete, source: preset.source, scope: preset.scope }; }),
        unavailablePresets: unavailable, truncatedCatalog: !!catalog.truncated }; },
      dispose: function () {
        disposed = true; events.forEach(function (remove) { remove(); });
        if (gazeUi && gazeUi.holder.parentNode) gazeUi.holder.parentNode.removeChild(gazeUi.holder);
        [ui.groups, ui.presets, controlHolder].forEach(function (node) { if (node) node.textContent = ""; });
        groupButtons = []; presetButtons = []; controlElements = []; partSelections = [];
      }
    };
  }
  global.ViewerExpressions = { create: create };
})(window);
