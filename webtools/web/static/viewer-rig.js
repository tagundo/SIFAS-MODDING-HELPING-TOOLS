/* Read-only pose, expression and body adjustments for the loaded glTF rig. */
(function () {
  "use strict";

  function finite(value, fallback) { value = Number(value); return isFinite(value) ? value : fallback; }
  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function element(id) { return document.getElementById(id); }
  function isHelper(object) { return object.userData && object.userData.viewerHelper === true; }

  function create(root, animations, info, options) {
    var THREE = window.THREE;
    var editing = window.ViewerEditing;
    var translate = options.translate;
    var changed = options.onChange;
    var nodes = {};
    var all = [];
    var bones = [];
    var expressions = [];
    var adjustments = {};
    var body = { height: 100, breast: 100, skirt: 100, breastPreset: "" };
    var bodyKinds = ["height", "breast", "skirt"];
    var authoredNodes = {};
    var nodeEditor = null, expressionPanel = null;
    var compensated = [];
    var selectedNode = "";
    var selectedClip = "";
    var playing = false;
    var interactive = true;
    var disposed = false;
    var events = [];
    var clips = animations || [];
    var clipEntries = [];
    var currentClip = null;
    var playhead = 0;
    var parts = [];
    var mixer = clips.length ? new THREE.AnimationMixer(root) : null;
    var action = null;
    var scaling = info && (info.scaling || info.controls) || {};
    var rigEditable = !!(info && info.available === true);
    var useSavedNodes = false;
    var savedOperations = [];
    var savedParts = [];
    var savedPartMap = {};
    var savedSkipped = 0;
    var savedConflicts = 0;
    var savedMetadataWarnings = Array.isArray(scaling.warnings) ? scaling.warnings.slice() : [];

    function snapshot(object) {
      return { position: object.position.clone(), quaternion: object.quaternion.clone(), scale: object.scale.clone(),
        morphs: object.morphTargetInfluences ? object.morphTargetInfluences.slice() : null };
    }
    function restore(object, value) {
      object.position.copy(value.position); object.quaternion.copy(value.quaternion); object.scale.copy(value.scale);
      if (value.morphs) value.morphs.forEach(function (weight, index) { object.morphTargetInfluences[index] = weight; });
    }
    function capture(object, value) {
      value.position.copy(object.position); value.quaternion.copy(object.quaternion); value.scale.copy(object.scale);
      if (value.morphs) object.morphTargetInfluences.forEach(function (weight, index) { value.morphs[index] = weight; });
    }
    root.traverse(function (object) {
      if (isHelper(object)) return;
      // Three r128 tests SkinnedMesh visibility against the undeformed geometry
      // sphere. A posed or bone-placed body can then disappear in a face close-up
      // while its outline still draws. This bounded character preview draws each
      // source skin and lets the GPU clip its triangles against the camera.
      if (object.isSkinnedMesh) object.frustumCulled = false;
      var index = object.userData && object.userData.elichika_node;
      if (index !== undefined) nodes[String(index)] = object;
      var record = { object: object, authored: snapshot(object), base: snapshot(object) };
      all.push(record);
      if (index !== undefined) authoredNodes[String(index)] = record;
      if (object.isMesh) {
        var visible = object.visible && object.userData.hidden_default !== true && object.userData.hideInPreview !== true;
        object.visible = visible;
        parts.push({ object: object, visible: visible, userVisible: undefined, userChanged: false });
      }
      if (object.morphTargetDictionary && object.morphTargetInfluences) {
        Object.keys(object.morphTargetDictionary).forEach(function (name) {
          expressions.push({ key: expressions.length.toString(), object: object, node: String(index), index: object.morphTargetDictionary[name],
            name: (object.name || translate("Part")) + " / " + name });
        });
      }
    });
    function visibilityTracks(tracks) {
      var verified = [];
      (tracks || []).forEach(function (track) {
        var target = nodes[String(track.node)];
        var valid = track.interpolation === "STEP" && target && !isHelper(target) &&
          (target.isMesh || target.userData.role === "mesh") && Array.isArray(track.times) && Array.isArray(track.values) &&
          track.times.length > 0 && track.times.length === track.values.length &&
          track.values.every(function (value) { return typeof value === "boolean"; }) &&
          track.times.every(function (value, index) { return typeof value === "number" && isFinite(value) && value >= 0 && (!index || value > track.times[index - 1]); });
        if (!valid) return;
        var targets = [];
        target.traverse(function (child) { if (child.isMesh && !isHelper(child)) targets.push(child); });
        if (targets.length) verified.push({ node: track.node, times: track.times.slice(), values: track.values.slice(), targets: targets });
      });
      return verified;
    }
    clips.forEach(function (clip) {
      var entry = (info && info.clips || []).filter(function (item) { return item.name === clip.name; })[0] || {};
      clipEntries.push({ name: clip.name, animation: clip, duration: clip.duration, loop: entry.loop !== false, visibility: visibilityTracks(entry.visibility) });
    });
    (info && info.clips || []).forEach(function (entry) {
      if (clipEntries.some(function (clip) { return clip.name === entry.name; })) return;
      var tracks = visibilityTracks(entry.visibility);
      if (tracks.length) clipEntries.push({ name: entry.name, animation: null, duration: Math.max(0, finite(entry.duration, 0)), loop: entry.loop === true, visibility: tracks });
    });
    // A clip's internal name (including ch0301 or eye_900) never establishes a
    // default pose. Only the backend's verified game-resource mapping may do so.
    var previewMotion = info && info.previewMotion;
    var previewMatches = previewMotion && previewMotion.verified === true &&
      previewMotion.kind === "sifas_suit_preview" && typeof previewMotion.name === "string" ?
      clipEntries.filter(function (clip) { return clip.name === previewMotion.name && clip.animation && isFinite(clip.duration) && clip.duration > 0; }) : [];
    var defaultClip = rigEditable && previewMatches.length === 1 ? previewMatches[0].name : "";
    (rigEditable && info.bones || []).forEach(function (bone) {
      var object = nodes[String(bone.node)];
      if (object) bones.push({ id: String(bone.node), name: bone.path || bone.name || object.name, object: object });
    });
    if (rigEditable && !bones.length) all.forEach(function (record) {
      var object = record.object, index = object.userData && object.userData.elichika_node;
      if (object.isBone && index !== undefined) bones.push({ id: String(index), name: object.name, object: object });
    });
    var savedGroups = {};
    function differentVector(left, right, rotation) {
      if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length || !left.length) return false;
      var direct = Math.max.apply(null, left.map(function (value, axis) { return Math.abs(value - right[axis]); }));
      var antipodal = rotation ? Math.max.apply(null, left.map(function (value, axis) { return Math.abs(value + right[axis]); })) : Infinity;
      return Math.min(direct, antipodal) > 1e-7;
    }
    (scaling.components || []).forEach(function (component) {
      (component.entries || []).forEach(function (entry) {
        var rotation = entry.kind === "rotation", values = rotation ? entry.scaledQuaternion : entry.scaled;
        var application = rotation ? "absolute_local_quaternion" : "absolute_local_" + entry.kind;
        var valid = rigEditable && entry.supported === true && ["scale", "position", "rotation"].indexOf(entry.kind) >= 0 &&
          entry.application === application && nodes[String(entry.node)] && Array.isArray(values) &&
          values.length === (rotation ? 4 : 3) && values.every(function (value) { return typeof value === "number" && isFinite(value); });
        if (valid && rotation) valid = Math.abs(values.reduce(function (sum, value) { return sum + value * value; }, 0) - 1) <= 1e-3;
        if (!valid || (entry.kind === "scale" && values.some(function (value) { return Math.abs(value) < 1e-8; }))) {
          savedSkipped += 1; return;
        }
        var key = String(entry.node) + ":" + entry.kind;
        if (!savedGroups[key]) savedGroups[key] = [];
      savedGroups[key].push({ node: String(entry.node), kind: entry.kind, value: values.slice(), name: entry.name || nodes[String(entry.node)].name,
          sourceEuler: rotation && entry.unityEulerScaled ? entry.unityEulerScaled.slice() : null,
          changed: differentVector(entry.origin, values, rotation) || differentVector(entry.authored, values, rotation) });
      });
    });
    Object.keys(savedGroups).forEach(function (key) {
      var values = savedGroups[key], first = values[0];
      if (values.some(function (entry) {
        var direct = Math.max.apply(null, entry.value.map(function (value, axis) { return Math.abs(value - first.value[axis]); }));
        var antipodal = first.kind === "rotation" ? Math.max.apply(null, entry.value.map(function (value, axis) { return Math.abs(value + first.value[axis]); })) : Infinity;
        return Math.min(direct, antipodal) > 1e-6;
      })) {
        savedConflicts += 1; savedSkipped += values.length; return;
      }
      savedOperations.push(first);
    });
    function savedPart(operation) {
      // Names group labels for people; every actual target/value comes from the
      // verified metadata above, including each separate parent/child skirt bone.
      var name = String(operation.name || "").split("/").pop();
      var groups = [[/^Move$/, "height", "Height"], [/Breast/i, "breast", "Breast size"], [/Skirt/i, "skirt", "Skirt"],
        [/^Head(?:_|$)/, "head", "Head"], [/Hair/i, "hair", "Hair"], [/Eye/i, "eyes", "Eyes"],
        [/Spine|Hips|Waist/i, "torso", "Torso"], [/Arm|Shoulder/i, "arms", "Arms"], [/Hand|Finger/i, "hands", "Hands"],
        [/Thigh|Calf|Leg/i, "legs", "Legs"], [/Foot|Toe/i, "feet", "Feet"]];
      var group = groups.filter(function (value) { return value[0].test(name); })[0];
      return { id: group ? group[1] : "node-" + operation.node, label: group ? group[2] : name || "Part" };
    }
    savedOperations.forEach(function (operation) {
      var identity = savedPart(operation), part = savedPartMap[identity.id];
      if (!part) { part = { id: identity.id, label: identity.label, enabled: true, operations: [], nodes: [], input: null, title: null }; savedParts.push(part); savedPartMap[part.id] = part; }
      operation.part = part.id; part.operations.push(operation);
      if (part.nodes.indexOf(operation.node) < 0) part.nodes.push(operation.node);
    });
    useSavedNodes = savedOperations.length > 0;
    element("viewer-saved-nodes").checked = useSavedNodes;
    function activeSavedOperations() {
      return useSavedNodes ? savedOperations.filter(function (operation) { return savedPartMap[operation.part].enabled; }) : [];
    }

    function bodyControl(kind) {
      if (!rigEditable) return null;
      var control = (scaling.controls || []).filter(function (value) { return value.id === kind; })[0];
      var mode = { height: "height_vertical_preserve_head", breast: "breast_tool_curve", skirt: "multiply_authored_local_scale" }[kind];
      return control && control.available === true && control.mode === mode &&
        control.nodes && control.nodes.length && control.nodes.every(function (target) { return !!nodes[String(target.node)]; }) ? control : null;
    }
    function applyBodyPreset(get) {
      var control = bodyControl("breast");
      var preset = control && (control.presets || []).filter(function (value) { return value.id === body.breastPreset; })[0];
      if (preset) control.nodes.forEach(function (operation) { get(String(operation.node)).scale.fromArray(preset.scale); });
    }
    function applyBody(get, skipHeight) {
      bodyKinds.forEach(function (kind) {
        var control = bodyControl(kind);
        if (!control || body[kind] === 100 || kind === "height" && skipHeight) return;
        var ratio = body[kind] / 100;
        control.nodes.forEach(function (operation) {
          var target = get(String(operation.node));
          if (!target) return;
          var factors = kind === "breast" && control.mode === "breast_tool_curve" ?
            editing.breastFactors(control, target.scale.x, body.breast) : (operation.axes || []).map(function (axis) { return axis === 1 ? ratio : 1; });
          if (factors) target.scale.multiply(new THREE.Vector3().fromArray(factors));
        });
      });
    }
    function clearHeightCompensation() {
      compensated.forEach(function (record) { record.object.matrixAutoUpdate = record.auto; record.object.matrix.copy(record.local); record.object.matrixWorldNeedsUpdate = true; });
      compensated = [];
    }
    function applyHeight() {
      var control = bodyControl("height"), ratio = body.height / 100;
      if (!control || ratio === 1) return;
      root.updateMatrixWorld(true);
      var roots = [];
      control.nodes.forEach(function (operation) {
        (operation.compensationRoots || []).forEach(function (value) {
          var object = nodes[String(value.node)];
          if (object && roots.every(function (record) { return record.object !== object; })) roots.push({ object: object, before: object.matrixWorld.clone(), local: object.matrix.clone(), auto: object.matrixAutoUpdate });
        });
      });
      control.nodes.forEach(function (operation) { nodes[String(operation.node)].scale.y *= ratio; });
      root.updateMatrixWorld(true);
      roots.forEach(function (record) {
        var object = record.object;
        // Preserve the complete world basis, not a local inverse-Y scale:
        // the latter shears a tilted head under a nonuniformly scaled parent.
        var desired = record.before.clone().setPosition(new THREE.Vector3().setFromMatrixPosition(object.matrixWorld));
        var parent = object.parent ? object.parent.matrixWorld : new THREE.Matrix4();
        object.matrix.copy(parent.clone().invert().multiply(desired));
        object.matrixAutoUpdate = false; object.matrixWorldNeedsUpdate = true;
      });
      compensated = roots;
    }
    function applyUser(target, values) {
      target.scale.multiply(new THREE.Vector3().fromArray(values.scale));
      target.position.add(new THREE.Vector3().fromArray(values.position));
      target.quaternion.multiply(values.quaternion ? new THREE.Quaternion().fromArray(values.quaternion) : editing.uiQuaternion(THREE, values.rotation));
    }
    function staticMap(adjusted) {
      var values = {};
      Object.keys(authoredNodes).forEach(function (id) { values[id] = editing.clone(authoredNodes[id].authored); });
      activeSavedOperations().forEach(function (operation) {
        values[operation.node][operation.kind === "rotation" ? "quaternion" : operation.kind === "scale" ? "scale" : "position"].fromArray(operation.value);
      });
      applyBodyPreset(function (id) { return values[id]; });
      applyBody(function (id) { return values[id]; }, true);
      if (expressionPanel) expressionPanel.getBoneOperations().forEach(function (operation) {
        var target = values[String(operation.node)];
        if (target && ["position", "scale", "quaternion"].indexOf(operation.kind) >= 0) target[operation.kind].fromArray(operation.value);
      });
      if (adjusted) Object.keys(adjustments).forEach(function (id) { if (values[id]) applyUser(values[id], adjustments[id]); });
      var height = bodyControl("height");
      if (height) height.nodes.forEach(function (target) { values[String(target.node)].scale.y *= body.height / 100; });
      return values;
    }
    function nodeFlags(id) {
      var operations = savedOperations.filter(function (operation) { return operation.node === id; });
      var active = activeSavedOperations();
      var bodyChanged = bodyKinds.some(function (kind) {
        var control = bodyControl(kind);
        if (!control || body[kind] === 100 && !(kind === "breast" && body.breastPreset)) return false;
        return control.nodes.some(function (target) {
          return String(target.node) === id || kind === "height" && (target.compensationRoots || []).some(function (value) { return String(value.node) === id; });
        });
      });
      return { saved: operations.length > 0, fileChanged: operations.some(function (operation) { return operation.changed && active.indexOf(operation) >= 0; }),
        modified: !editing.adjustmentEmpty(adjustments[id]), body: bodyChanged,
        expression: !!expressionPanel && expressionPanel.getBoneOperations().some(function (operation) { return String(operation.node) === id; }) };
    }
    function savedEuler(id) {
      var entry = activeSavedOperations().filter(function (operation) { return operation.node === id && operation.kind === "rotation"; })[0];
      return entry && entry.sourceEuler;
    }
    function applyAdjustments() {
      activeSavedOperations().forEach(function (operation) {
        nodes[operation.node][operation.kind === "rotation" ? "quaternion" : operation.kind === "scale" ? "scale" : "position"].fromArray(operation.value);
      });
      applyBodyPreset(function (id) { return nodes[id]; });
      applyBody(function (id) { return nodes[id]; }, true);
      if (expressionPanel) expressionPanel.applyBonesAndMorphs();
      Object.keys(adjustments).forEach(function (id) {
        var target = nodes[id], values = adjustments[id];
        if (!target) return;
        applyUser(target, values);
      });
      parts.forEach(function (part) { part.object.visible = part.visible; });
      if (currentClip) currentClip.visibility.forEach(function (track) {
        var time = currentTime(), value = track.values[0];
        for (var index = 1; index < track.times.length && track.times[index] <= time; index += 1) value = track.values[index];
        track.targets.forEach(function (target) { target.visible = target.visible && value; });
      });
      if (expressionPanel) expressionPanel.applyVisibility(parts);
      applyHeight();
      root.updateMatrixWorld(true);
      root.traverse(function (object) { if (object.isSkinnedMesh) object.skeleton.update(); });
    }
    function evaluate(delta) {
      if (disposed) return;
      clearHeightCompensation();
      all.forEach(function (record) { restore(record.object, record.base); });
      if (mixer) mixer.update(delta || 0);
      all.forEach(function (record) { capture(record.object, record.base); });
      applyAdjustments();
    }
    function listen(id, event, handler) {
      var target = element(id); target.addEventListener(event, handler);
      events.push(function () { target.removeEventListener(event, handler); });
    }
    function appendOption(select, value, label) {
      var option = document.createElement("option"); option.value = value; option.textContent = label; select.appendChild(option);
    }
    function duration() { return currentClip ? Math.max(0, currentClip.duration) : 0; }
    function currentTime() { return action ? action.time : playhead; }
    function updateTime() {
      var seconds = currentTime();
      element("viewer-time").value = String(seconds);
      element("viewer-time-value").textContent = seconds.toFixed(2) + " / " + duration().toFixed(2) + " s";
      element("viewer-play").textContent = translate(playing ? "Pause" : "Play");
    }
    function refreshAvailability() {
      var enabled = interactive && !disposed;
      element("viewer-pose-basic").disabled = !enabled;
      element("viewer-pose-preview").disabled = !enabled || !defaultClip;
      element("viewer-pose-basic").setAttribute("aria-pressed", String(!disposed && selectedClip === ""));
      element("viewer-pose-preview").setAttribute("aria-pressed", String(!disposed && !!defaultClip && selectedClip === defaultClip));
      element("viewer-pose-help").hidden = !disposed && !!defaultClip;
      element("viewer-motion").disabled = !enabled || !clipEntries.length;
      element("viewer-play").disabled = !enabled || !currentClip || duration() <= 0;
      element("viewer-time").disabled = !enabled || !currentClip || duration() <= 0;
      if (expressionPanel) expressionPanel.setInteractive(enabled);
      if (nodeEditor) nodeEditor.setInteractive(enabled);
      element("viewer-saved-nodes").disabled = !enabled || !savedOperations.length;
      savedParts.forEach(function (part) { if (part.input) part.input.disabled = !enabled || !useSavedNodes; });
      element("viewer-preview-reset").disabled = !enabled || !(bones.length || clipEntries.length || expressions.length);
      refreshBodyControls();
    }
    function refreshExpression() {
      if (expressionPanel) expressionPanel.refresh();
    }
    function expressionLimits() {
      return all.filter(function (record) { return !!record.object.morphTargetInfluences; }).map(function (record) {
        var object = record.object;
        return { name: object.name, active: object.morphTargetInfluences.filter(function (value) { return Math.abs(value) > 1e-6; }).length,
          maximum: object.geometry.morphAttributes.normal && object.geometry.morphAttributes.normal.length ? 4 : 8 };
      });
    }
    function refreshNode() {
      if (nodeEditor) nodeEditor.refresh(false);
    }
    function breastBaseTargets() {
      var values = {};
      Object.keys(authoredNodes).forEach(function (id) { values[id] = editing.clone(authoredNodes[id].authored); });
      activeSavedOperations().forEach(function (operation) {
        values[operation.node][operation.kind === "rotation" ? "quaternion" : operation.kind === "scale" ? "scale" : "position"].fromArray(operation.value);
      });
      applyBodyPreset(function (id) { return values[id]; });
      var control = bodyControl("breast");
      return control ? control.nodes.map(function (target) { return values[String(target.node)]; }) : [];
    }
    function bodyRange(kind) {
      var control = bodyControl(kind);
      if (!control) return null;
      return kind === "breast" && control.mode === "breast_tool_curve" ?
        editing.breastRange(control, breastBaseTargets()) :
        { min: finite(control.min, 80), max: finite(control.max, 120) };
    }
    function refreshBodyControls() {
      bodyKinds.forEach(function (kind) {
        var control = bodyControl(kind), range = bodyRange(kind), enabled = interactive && !disposed && !!range;
        ["viewer-" + kind, "viewer-" + kind + "-number"].forEach(function (id) {
          var input = element(id);
          if (!input) return;
          input.disabled = !enabled;
          if (range) { input.min = String(range.min); input.max = String(range.max); }
          if (document.activeElement !== input) input.value = String(body[kind]);
        });
        element("viewer-" + kind + "-value").textContent = body[kind] + "%";
        var resetButton = element("viewer-" + kind + "-reset");
        if (resetButton) resetButton.disabled = !interactive || disposed || !control || body[kind] === 100 && !(kind === "breast" && body.breastPreset);
        var note = !control ? (kind === "height" ? "This model has no supported height control." :
          kind === "breast" ? "This model has no verified breast-size node." : "This model has no supported skirt roots.") :
          !range ? "This custom breast size is outside the tool curve. Use individual bone editing." :
          kind === "height" ? "Changes vertical body height while keeping the head and hair proportions." :
          kind === "breast" ? "Width follows the breast tool curve; height and depth adjust proportionally." :
          "Uses the skirt tool's root bones. Length and flare change together.";
        element("viewer-" + kind + "-note").textContent = translate(note);
      });
      var select = element("viewer-breast-preset");
      if (select) select.disabled = !interactive || disposed || !bodyControl("breast");
    }
    function setBody(kind, input) {
      var range = bodyRange(kind);
      if (!range || !input.value.trim() || !isFinite(Number(input.value))) return;
      body[kind] = clamp(Number(input.value), range.min, range.max);
      evaluate(0); refreshBodyControls(); refreshNode(); changed();
    }
    function setClip(name) {
      playing = false;
      clearHeightCompensation();
      all.forEach(function (record) { restore(record.object, record.base); });
      if (mixer) mixer.stopAllAction();
      all.forEach(function (record) { restore(record.object, record.authored); capture(record.object, record.base); });
      selectedClip = name;
      currentClip = clipEntries.filter(function (item) { return item.name === name; })[0] || null;
      playhead = 0;
      action = currentClip && currentClip.animation && mixer ? mixer.clipAction(currentClip.animation).reset().play() : null;
      if (action) {
        action.setLoop(currentClip.loop ? THREE.LoopRepeat : THREE.LoopOnce, currentClip.loop ? Infinity : 1);
        action.clampWhenFinished = true;
      }
      if (action) { action.paused = false; evaluate(0); }
      else evaluate(0);
      element("viewer-motion").value = name;
      element("viewer-time").max = String(duration());
      refreshAvailability(); updateTime(); refreshExpression(); refreshNode(); changed();
    }
    function reset() {
      adjustments = {}; body = { height: 100, breast: 100, skirt: 100, breastPreset: "" };
      if (expressionPanel) expressionPanel.reset(true);
      useSavedNodes = savedOperations.length > 0; element("viewer-saved-nodes").checked = useSavedNodes;
      savedParts.forEach(function (part) { part.enabled = true; if (part.input) part.input.checked = true; });
      setClip(defaultClip); refreshNode(); refreshExpression(); refreshSavedStatus();
    }
    function refreshSavedStatus() {
      var message = !savedOperations.length ? translate("No verified saved node settings are available.") :
        translate(useSavedNodes ? "Saved node settings are applied. 100% adds no extra scaling." : "Using the file's authored shape. Saved node settings are off.");
      if (savedOperations.length) message += " " + translate("Applied settings") + ": " + activeSavedOperations().length + " / " + savedOperations.length + ".";
      if (savedSkipped || savedMetadataWarnings.length) message += " " + translate("Unsupported or conflicting saved settings were skipped.") + (savedSkipped ? " (" + savedSkipped + ")" : "");
      element("viewer-saved-status").textContent = message;
      element("viewer-saved-status").classList.toggle("error", savedConflicts > 0 || savedMetadataWarnings.length > 0);
      element("viewer-saved-parts").hidden = !savedParts.length;
      savedParts.forEach(function (part) { if (part.title) part.title.textContent = translate(part.label) + " (" + part.operations.length + ")"; });
    }
    function updateLanguage() {
      element("viewer-pose-actions").setAttribute("aria-label", translate("Pose"));
      element("viewer-pose-basic").textContent = translate("Basic pose");
      element("viewer-pose-preview").textContent = translate("Posed view");
      element("viewer-pose-help").textContent = translate("No compatible preview motion is available.");
      var motion = element("viewer-motion"); motion.textContent = "";
      appendOption(motion, "", translate("Saved pose"));
      clipEntries.forEach(function (clip) {
        var label = (info && info.expressionCatalog && info.expressionCatalog.clips || []).filter(function (value) { return value.name === clip.name; })[0];
        appendOption(motion, clip.name, clip.name === defaultClip ? translate("SIFAS costume preview") : label ? translate(label.label) : clip.name);
      }); motion.value = selectedClip;
      if (nodeEditor) nodeEditor.updateLanguage();
      if (expressionPanel) expressionPanel.updateLanguage();
      var preset = element("viewer-breast-preset");
      if (preset) {
        preset.textContent = ""; appendOption(preset, "", translate("Loaded shape"));
        var control = bodyControl("breast");
        (control && control.presets || []).forEach(function (value) { appendOption(preset, value.id, translate(value.label)); });
        preset.value = body.breastPreset;
      }
      element("viewer-rig-status").textContent = translate(clipEntries.length ? "Play or pause a motion to inspect the model's pose." :
        bones.length || expressions.length ? "No compatible motion is available. You can adjust this model's bones and expressions." : "This model supports a static preview only.");
      updateTime(); refreshSavedStatus(); refreshExpression(); refreshAvailability();
    }
    function buildSavedParts() {
      var holder = element("viewer-saved-part-list"); holder.textContent = "";
      savedParts.forEach(function (part) {
        var label = document.createElement("label"), input = document.createElement("input"), title = document.createElement("span");
        input.type = "checkbox"; input.checked = part.enabled; input.dataset.viewerSavedPart = part.id;
        function change() { part.enabled = input.checked; evaluate(0); refreshSavedStatus(); refreshBodyControls(); refreshNode(); changed(); }
        input.addEventListener("change", change); events.push(function () { input.removeEventListener("change", change); });
        part.input = input; part.title = title; label.appendChild(input); label.appendChild(title); holder.appendChild(label);
      });
    }
    function posedBounds() {
      if (!bones.length) return null;
      var box = new THREE.Box3(), point = new THREE.Vector3(), original = new THREE.Vector3();
      var source = new THREE.Vector3(), weighted = new THREE.Vector3(), transformed = new THREE.Vector3();
      var matrix = new THREE.Matrix4();
      root.updateMatrixWorld(true);
      root.traverseVisible(function (mesh) {
        if (!mesh.isMesh || isHelper(mesh) || !mesh.geometry || !mesh.geometry.attributes.position) return;
        var geometry = mesh.geometry, position = geometry.attributes.position;
        var morphs = geometry.morphAttributes.position || [];
        var skinIndex = geometry.attributes.skinIndex, skinWeight = geometry.attributes.skinWeight;
        if (mesh.isSkinnedMesh) mesh.skeleton.update();
        for (var vertex = 0; vertex < position.count; vertex += 1) {
          point.fromBufferAttribute(position, vertex); original.copy(point);
          morphs.forEach(function (morph, index) {
            var weight = mesh.morphTargetInfluences[index] || 0;
            if (!weight) return;
            transformed.fromBufferAttribute(morph, vertex);
            if (!geometry.morphTargetsRelative) transformed.sub(original);
            point.addScaledVector(transformed, weight);
          });
          if (mesh.isSkinnedMesh && skinIndex && skinWeight) {
            source.copy(point).applyMatrix4(mesh.bindMatrix); weighted.set(0, 0, 0);
            ["getX", "getY", "getZ", "getW"].forEach(function (accessor) {
              var weight = skinWeight[accessor](vertex), bone = skinIndex[accessor](vertex);
              if (!weight || !mesh.skeleton.bones[bone]) return;
              matrix.multiplyMatrices(mesh.skeleton.bones[bone].matrixWorld, mesh.skeleton.boneInverses[bone]);
              transformed.copy(source).applyMatrix4(matrix); weighted.addScaledVector(transformed, weight);
            });
            point.copy(weighted).applyMatrix4(mesh.bindMatrixInverse);
          }
          box.expandByPoint(point.applyMatrix4(mesh.matrixWorld));
        }
      });
      return box.isEmpty() ? null : box;
    }
    buildSavedParts();
    expressionPanel = window.ViewerExpressions.create({ THREE: THREE, translate: translate, nodes: nodes,
      channels: expressions, catalog: info && info.expressionCatalog || {},
      change: function () { evaluate(0); refreshNode(); changed(); } });
    nodeEditor = editing.createNodeEditor({ THREE: THREE, translate: translate, nodes: nodes, bones: bones, scaling: scaling,
      value: function (id, adjusted) { return staticMap(adjusted)[id]; }, flags: nodeFlags, savedEuler: savedEuler,
      savedEntries: function (id) {
        var active = activeSavedOperations();
        return savedOperations.filter(function (operation) { return operation.node === id; }).map(function (operation) {
          return { kind: operation.kind, value: operation.value, sourceEuler: operation.sourceEuler, applied: active.indexOf(operation) >= 0 };
        });
      },
      adjustment: function (id) { return adjustments[id]; }, onSelect: function (id) { selectedNode = id; },
      change: function (id, value) { if (value) adjustments[id] = value; else delete adjustments[id]; evaluate(0); changed(); } });
    var presetHolder = element("viewer-body-presets");
    if (presetHolder) {
      presetHolder.textContent = "";
      var presetLabel = document.createElement("label"), presetTitle = document.createElement("span"), presetSelect = document.createElement("select");
      presetTitle.textContent = translate("Breast tool presets"); presetTitle.setAttribute("data-i18n", "Breast tool presets");
      presetSelect.id = "viewer-breast-preset"; presetLabel.appendChild(presetTitle); presetLabel.appendChild(presetSelect); presetHolder.appendChild(presetLabel);
      listen("viewer-breast-preset", "change", function () { body.breastPreset = this.value; body.breast = 100; evaluate(0); refreshBodyControls(); refreshNode(); changed(); });
    }
    listen("viewer-pose-basic", "click", function () { if (!this.disabled) setClip(""); });
    listen("viewer-pose-preview", "click", function () { if (!this.disabled && defaultClip) setClip(defaultClip); });
    listen("viewer-motion", "change", function () { setClip(this.value); });
    if (mixer) mixer.addEventListener("finished", function (event) { if (event.action === action) { playing = false; updateTime(); } });
    listen("viewer-play", "click", function () {
      playing = !playing;
      if (playing && action && (action.paused || action.time >= duration() - 1e-7)) { action.reset().play(); evaluate(0); }
      if (playing && !action && playhead >= duration()) { playhead = 0; evaluate(0); }
      updateTime(); changed();
    });
    listen("viewer-time", "input", function () {
      if (!currentClip) return;
      // Looping actions wrap an exact end time to zero. Inspect the last frame
      // just before the boundary so dragging the scrubber to its end stays put.
      playing = false;
      var time = clamp(finite(this.value, 0), 0, Math.max(0, duration() - (action && currentClip.loop ? 1e-7 : 0)));
      if (action) { action.paused = false; action.enabled = true; action.time = time; }
      else playhead = time;
      evaluate(0); updateTime(); refreshExpression(); changed();
    });
    bodyKinds.forEach(function (kind) {
      listen("viewer-" + kind, "input", function () { setBody(kind, this); });
      listen("viewer-" + kind + "-number", "input", function () { setBody(kind, this); });
      listen("viewer-" + kind + "-number", "change", refreshBodyControls);
      listen("viewer-" + kind + "-reset", "click", function () {
        body[kind] = 100;
        if (kind === "breast") { body.breastPreset = ""; element("viewer-breast-preset").value = ""; }
        evaluate(0); refreshBodyControls(); refreshNode(); changed();
      });
    });
    listen("viewer-saved-nodes", "change", function () {
      useSavedNodes = this.checked && savedOperations.length > 0; evaluate(0); refreshSavedStatus(); refreshAvailability(); refreshNode(); changed();
    });
    listen("viewer-preview-reset", "click", reset);
    updateLanguage(); setClip(defaultClip); refreshNode(); refreshExpression();

    return {
      update: function (delta) {
        if (playing && currentClip) {
          delta = clamp(delta, 0, .1);
          if (!action) {
            playhead += delta;
            if (playhead >= duration()) { if (currentClip.loop && duration()) playhead %= duration(); else { playhead = duration(); playing = false; } }
          }
          evaluate(action ? delta : 0); updateTime(); refreshExpression();
        }
        return playing && !!currentClip;
      },
      setPartVisible: function (object, value) {
        parts.forEach(function (part) { if (part.object === object) { part.visible = !!value; part.userVisible = !!value; part.userChanged = true; } });
        evaluate(0); changed();
      },
      setInteractive: function (value) { interactive = !!value; refreshAvailability(); },
      updateLanguage: updateLanguage,
      getBounds: posedBounds,
      reset: reset,
      dispose: function () { disposed = true; playing = false; clearHeightCompensation(); refreshAvailability(); events.forEach(function (remove) { remove(); }); if (nodeEditor) nodeEditor.dispose(); if (expressionPanel) expressionPanel.dispose(); if (mixer) { mixer.stopAllAction(); mixer.uncacheRoot(root); } },
      getState: function () {
        var values = bones.map(function (bone) { return { node: bone.id, name: bone.name, position: bone.object.position.toArray(), quaternion: bone.object.quaternion.toArray(), scale: bone.object.scale.toArray() }; });
        return { available: !!bones.length, bones: values, clipNames: clipEntries.map(function (clip) { return clip.name; }), selectedClip: selectedClip, defaultClip: defaultClip,
          playing: playing, time: currentTime(), duration: duration(), visibilityTracks: currentClip ? currentClip.visibility.length : 0,
          parts: parts.map(function (part) { return { name: part.object.name, node: part.object.userData.elichika_node, selected: part.visible,
            userVisible: part.userVisible, userChanged: part.userChanged, visible: part.object.visible }; }),
          expressions: expressions.map(function (value) { return { key: value.key, name: value.name, weight: value.object.morphTargetInfluences[value.index] }; }),
          body: { height: body.height, breast: body.breast, skirt: body.skirt, breastPreset: body.breastPreset }, scaling: scaling,
          nodeAdjustments: JSON.parse(JSON.stringify(adjustments)), selectedNode: selectedNode,
          nodeValues: selectedNode ? editing.toUI(THREE, staticMap(true)[selectedNode], savedEuler(selectedNode)) : null,
          expressionPanel: expressionPanel ? expressionPanel.getState() : null, expressionLimits: expressionLimits(),
          heightCompensation: compensated.map(function (record) { return { node: String(record.object.userData.elichika_node), name: record.object.name, worldBasisPreserved: true }; }),
          savedNodes: { available: savedOperations.length > 0, enabled: useSavedNodes, applied: activeSavedOperations().length,
            skipped: savedSkipped, conflicts: savedConflicts, metadataWarnings: savedMetadataWarnings.slice(), operations: savedOperations,
            groups: savedParts.map(function (part) { return { id: part.id, label: translate(part.label), enabled: part.enabled, nodes: part.nodes.slice(), settings: part.operations.length }; }) } };
      }
    };
  }
  window.ViewerRig = { create: create };
}());
