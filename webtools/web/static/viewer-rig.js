/* Read-only pose, expression and body adjustments for the loaded glTF rig. */
(function () {
  "use strict";

  function finite(value, fallback) { value = Number(value); return isFinite(value) ? value : fallback; }
  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function element(id) { return document.getElementById(id); }
  function isHelper(object) { return object.userData && object.userData.viewerHelper === true; }

  function create(root, animations, info, options) {
    var THREE = window.THREE;
    var translate = options.translate;
    var changed = options.onChange;
    var nodes = {};
    var all = [];
    var bones = [];
    var expressions = [];
    var expressionOverrides = {};
    var adjustments = {};
    var body = { height: 100, breast: 100 };
    var selectedNode = "";
    var selectedExpression = "";
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
    var inputFields = {};
    var scaling = info && (info.scaling || info.controls) || {};
    var rigEditable = !!(info && info.available === true);
    var useSavedNodes = false;
    var savedOperations = [];
    var savedSkipped = 0;
    var savedConflicts = 0;

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
      if (object.isMesh) {
        var visible = object.visible && object.userData.hidden_default !== true && object.userData.hideInPreview !== true;
        object.visible = visible;
        parts.push({ object: object, visible: visible });
      }
      if (object.morphTargetDictionary && object.morphTargetInfluences) {
        Object.keys(object.morphTargetDictionary).forEach(function (name) {
          expressions.push({ key: expressions.length.toString(), object: object, index: object.morphTargetDictionary[name],
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
    (rigEditable && info.bones || []).forEach(function (bone) {
      var object = nodes[String(bone.node)];
      if (object) bones.push({ id: String(bone.node), name: bone.path || bone.name || object.name, object: object });
    });
    if (rigEditable && !bones.length) all.forEach(function (record) {
      var object = record.object, index = object.userData && object.userData.elichika_node;
      if (object.isBone && index !== undefined) bones.push({ id: String(index), name: object.name, object: object });
    });
    var savedGroups = {};
    (scaling.components || []).forEach(function (component) {
      (component.entries || []).forEach(function (entry) {
        if (!rigEditable || entry.supported !== true || (entry.kind !== "scale" && entry.kind !== "position") ||
            entry.application !== "absolute_local_" + entry.kind || !nodes[String(entry.node)] ||
            !Array.isArray(entry.scaled) || entry.scaled.length !== 3 || !entry.scaled.every(function (value) { return typeof value === "number" && isFinite(value); }) ||
            (entry.kind === "scale" && entry.scaled.some(function (value) { return Math.abs(value) < 1e-8; }))) {
          savedSkipped += 1; return;
        }
        var key = String(entry.node) + ":" + entry.kind;
        if (!savedGroups[key]) savedGroups[key] = [];
        savedGroups[key].push(entry);
      });
    });
    Object.keys(savedGroups).forEach(function (key) {
      var values = savedGroups[key], first = values[0];
      if (values.some(function (entry) { return entry.scaled.some(function (value, axis) { return Math.abs(value - first.scaled[axis]) > 1e-6; }); })) {
        savedConflicts += 1; savedSkipped += values.length; return;
      }
      savedOperations.push({ node: String(first.node), kind: first.kind, value: first.scaled.slice() });
    });

    function bodyControl(kind) {
      if (!rigEditable) return null;
      var control = (scaling.controls || []).filter(function (value) { return value.id === kind; })[0];
      return control && control.available === true && control.mode === "multiply_authored_local_scale" &&
        control.nodes && control.nodes.length && control.nodes.every(function (target) { return !!nodes[String(target.node)]; }) ? control : null;
    }
    function applyBody() {
      // The backend describes verified targets and semantics. Unsupported models
      // never get a guessed BreastSize/height transform from a name heuristic.
      ["height", "breast"].forEach(function (kind) {
        var control = bodyControl(kind);
        if (!control || body[kind] === 100) return;
        var ratio = body[kind] / 100;
        control.nodes.forEach(function (operation) {
          var target = nodes[String(operation.node)];
          if (!target) return;
          var axes = operation.axes || [];
          ["x", "y", "z"].forEach(function (axis, index) { if (axes[index] === 1) target.scale[axis] *= ratio; });
        });
      });
    }
    function applyAdjustments() {
      if (useSavedNodes) savedOperations.forEach(function (operation) {
        nodes[operation.node][operation.kind === "scale" ? "scale" : "position"].fromArray(operation.value);
      });
      applyBody();
      Object.keys(adjustments).forEach(function (id) {
        var target = nodes[id], values = adjustments[id];
        if (!target) return;
        target.scale.multiply(new THREE.Vector3().fromArray(values.scale));
        target.position.add(new THREE.Vector3().fromArray(values.position));
        var angle = values.rotation;
        target.quaternion.multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(
          angle[0] * Math.PI / 180, angle[1] * Math.PI / 180, angle[2] * Math.PI / 180, "XYZ")));
      });
      expressions.forEach(function (expression) {
        if (Object.prototype.hasOwnProperty.call(expressionOverrides, expression.key)) {
          expression.object.morphTargetInfluences[expression.index] = expressionOverrides[expression.key];
        }
      });
      parts.forEach(function (part) { part.object.visible = part.visible; });
      if (currentClip) currentClip.visibility.forEach(function (track) {
        var time = currentTime(), value = track.values[0];
        for (var index = 1; index < track.times.length && track.times[index] <= time; index += 1) value = track.values[index];
        track.targets.forEach(function (target) { target.visible = target.visible && value; });
      });
      root.updateMatrixWorld(true);
      root.traverse(function (object) { if (object.isSkinnedMesh) object.skeleton.update(); });
    }
    function evaluate(delta) {
      if (disposed) return;
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
      element("viewer-motion").disabled = !enabled || !clipEntries.length;
      element("viewer-play").disabled = !enabled || !currentClip || duration() <= 0;
      element("viewer-time").disabled = !enabled || !currentClip || duration() <= 0;
      element("viewer-expression").disabled = !enabled || !expressions.length;
      element("viewer-expression-value").disabled = !enabled || !expressions.length;
      element("viewer-node").disabled = !enabled || !bones.length;
      element("viewer-node-reset").disabled = !enabled || !selectedNode;
      element("viewer-saved-nodes").disabled = !enabled || !savedOperations.length;
      element("viewer-preview-reset").disabled = !enabled || !(bones.length || clipEntries.length || expressions.length);
      ["height", "breast"].forEach(function (kind) {
        var control = bodyControl(kind), input = element("viewer-" + kind);
        input.disabled = !enabled || !control;
        if (control) {
          input.min = String(finite(control.min, kind === "height" ? 50 : 25));
          input.max = String(finite(control.max, kind === "height" ? 150 : 200));
        }
      });
      Object.keys(inputFields).forEach(function (kind) {
        inputFields[kind].forEach(function (input) { input.disabled = !enabled || !selectedNode; });
      });
    }
    function refreshExpression() {
      var expression = expressions.filter(function (value) { return value.key === selectedExpression; })[0];
      var value = expression ? expression.object.morphTargetInfluences[expression.index] * 100 : 0;
      element("viewer-expression-value").value = String(value);
      element("viewer-expression-output").textContent = Math.round(value) + "%";
      var exceeded = expressionLimits().some(function (limit) { return limit.active > limit.maximum; });
      element("viewer-expression-status").hidden = !exceeded;
      element("viewer-expression-status").textContent = exceeded ? translate("Too many expression channels are active. Some may be omitted by the viewer.") : "";
    }
    function expressionLimits() {
      return all.filter(function (record) { return !!record.object.morphTargetInfluences; }).map(function (record) {
        var object = record.object;
        return { name: object.name, active: object.morphTargetInfluences.filter(function (value) { return Math.abs(value) > 1e-6; }).length,
          maximum: object.geometry.morphAttributes.normal && object.geometry.morphAttributes.normal.length ? 4 : 8 };
      });
    }
    function currentAdjustment() { return adjustments[selectedNode] || { scale: [1, 1, 1], rotation: [0, 0, 0], position: [0, 0, 0] }; }
    function refreshNode() {
      var values = currentAdjustment();
      Object.keys(inputFields).forEach(function (kind) {
        inputFields[kind].forEach(function (input, index) {
          input.value = String(values[kind][index] * (kind === "scale" ? 100 : 1));
        });
      });
      refreshAvailability();
    }
    function readNode() {
      if (!selectedNode) return;
      var values = currentAdjustment();
      Object.keys(inputFields).forEach(function (kind) {
        values[kind] = inputFields[kind].map(function (input, index) {
          var fallback = values[kind][index] * (kind === "scale" ? 100 : 1);
          return clamp(input.value.trim() ? finite(input.value, fallback) : fallback, Number(input.min), Number(input.max)) / (kind === "scale" ? 100 : 1);
        });
      });
      adjustments[selectedNode] = values;
      evaluate(0); changed();
    }
    function setClip(name) {
      playing = false;
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
      refreshAvailability(); updateTime(); refreshExpression(); changed();
    }
    function reset() {
      adjustments = {}; expressionOverrides = {}; body = { height: 100, breast: 100 };
      useSavedNodes = false; element("viewer-saved-nodes").checked = false;
      ["height", "breast"].forEach(function (kind) { element("viewer-" + kind).value = "100"; element("viewer-" + kind + "-value").textContent = "100%"; });
      setClip(""); refreshNode(); refreshExpression(); refreshSavedStatus();
    }
    function refreshSavedStatus() {
      var message = !savedOperations.length ? translate("No verified saved node settings are available.") :
        translate(useSavedNodes ? "Saved node settings are applied. 100% adds no extra scaling." : "Using the file's authored shape. Saved node settings are off.");
      if (savedSkipped) message += " " + translate("Unsupported or conflicting saved settings were skipped.") + " (" + savedSkipped + ")";
      element("viewer-saved-status").textContent = message;
      element("viewer-saved-status").classList.toggle("error", savedConflicts > 0);
    }
    function updateLanguage() {
      var motion = element("viewer-motion"); motion.textContent = "";
      appendOption(motion, "", translate("Saved pose"));
      clipEntries.forEach(function (clip) { appendOption(motion, clip.name, clip.name); }); motion.value = selectedClip;
      var expressionSelect = element("viewer-expression"); expressionSelect.textContent = "";
      if (!expressions.length) appendOption(expressionSelect, "", translate("No expression channels in this model."));
      expressions.forEach(function (value) { appendOption(expressionSelect, value.key, value.name); });
      expressionSelect.value = selectedExpression;
      var boneSelect = element("viewer-node"); boneSelect.textContent = "";
      if (!bones.length) appendOption(boneSelect, "", translate("No editable bones in this model."));
      bones.forEach(function (bone) { appendOption(boneSelect, bone.id, bone.name); }); boneSelect.value = selectedNode;
      element("viewer-rig-status").textContent = translate(clipEntries.length ? "Choose a supplied motion to play or inspect a pose." :
        bones.length || expressions.length ? "No motion clips were supplied. You can adjust the available bones and expressions." : "This model supports a static preview only.");
      ["height", "breast"].forEach(function (kind) {
        element("viewer-" + kind + "-note").textContent = translate(bodyControl(kind) ? "Relative to the selected pose and body settings." : kind === "height" ? "This model has no supported height control." : "This model has no verified breast-size node.");
      });
      ["scale", "rotation", "position"].forEach(function (kind, row) {
        var key = ["Scale (%)", "Rotation (degrees)", "Movement"][row];
        element("viewer-node-fields").children[row].firstChild.textContent = translate(key);
        inputFields[kind].forEach(function (input, index) { input.setAttribute("aria-label", translate(key) + " " + ["X", "Y", "Z"][index]); });
      });
      updateTime(); refreshSavedStatus(); refreshExpression(); refreshAvailability();
    }
    function buildNodeInputs() {
      var holder = element("viewer-node-fields"); holder.textContent = "";
      [["scale", "Scale (%)", 100, 10, 300, 1], ["rotation", "Rotation (degrees)", 0, -180, 180, 1], ["position", "Movement", 0, -2, 2, .01]].forEach(function (definition) {
        var kind = definition[0], row = document.createElement("div"); row.className = "viewer-node-vector";
        var title = document.createElement("span"); title.textContent = translate(definition[1]); row.appendChild(title);
        inputFields[kind] = [];
        ["X", "Y", "Z"].forEach(function (axis) {
          var label = document.createElement("label"); label.textContent = axis;
          var input = document.createElement("input"); input.type = "number"; input.value = String(definition[2]); input.min = String(definition[3]); input.max = String(definition[4]); input.step = String(definition[5]);
          input.setAttribute("aria-label", translate(definition[1]) + " " + axis); input.dataset.viewerNodeKind = kind; input.dataset.axis = axis;
          input.addEventListener("input", readNode); events.push(function () { input.removeEventListener("input", readNode); });
          input.addEventListener("change", refreshNode); events.push(function () { input.removeEventListener("change", refreshNode); });
          inputFields[kind].push(input); label.appendChild(input); row.appendChild(label);
        }); holder.appendChild(row);
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
    buildNodeInputs();
    selectedNode = bones.length ? bones[0].id : "";
    selectedExpression = expressions.length ? expressions[0].key : "";
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
    ["height", "breast"].forEach(function (kind) {
      listen("viewer-" + kind, "input", function () {
        if (!bodyControl(kind)) return;
        body[kind] = clamp(finite(this.value, 100), Number(this.min), Number(this.max));
        element("viewer-" + kind + "-value").textContent = body[kind] + "%"; evaluate(0); changed();
      });
    });
    listen("viewer-expression", "change", function () { selectedExpression = this.value; refreshExpression(); });
    listen("viewer-saved-nodes", "change", function () {
      useSavedNodes = this.checked && savedOperations.length > 0; evaluate(0); refreshSavedStatus(); changed();
    });
    listen("viewer-expression-value", "input", function () {
      if (!expressions.length) return;
      expressionOverrides[selectedExpression] = clamp(finite(this.value, 0) / 100, 0, 1); evaluate(0); refreshExpression(); changed();
    });
    listen("viewer-node", "change", function () { selectedNode = this.value; refreshNode(); });
    listen("viewer-node-reset", "click", function () { delete adjustments[selectedNode]; evaluate(0); refreshNode(); changed(); });
    listen("viewer-preview-reset", "click", reset);
    updateLanguage(); evaluate(0); refreshNode(); refreshExpression();

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
        parts.forEach(function (part) { if (part.object === object) part.visible = !!value; });
        evaluate(0); changed();
      },
      setInteractive: function (value) { interactive = !!value; refreshAvailability(); },
      updateLanguage: updateLanguage,
      getBounds: posedBounds,
      reset: reset,
      dispose: function () { disposed = true; playing = false; events.forEach(function (remove) { remove(); }); if (mixer) { mixer.stopAllAction(); mixer.uncacheRoot(root); } },
      getState: function () {
        var values = bones.map(function (bone) { return { node: bone.id, name: bone.name, position: bone.object.position.toArray(), quaternion: bone.object.quaternion.toArray(), scale: bone.object.scale.toArray() }; });
        return { available: !!bones.length, bones: values, clipNames: clipEntries.map(function (clip) { return clip.name; }), selectedClip: selectedClip,
          playing: playing, time: currentTime(), duration: duration(), visibilityTracks: currentClip ? currentClip.visibility.length : 0,
          parts: parts.map(function (part) { return { name: part.object.name, node: part.object.userData.elichika_node, selected: part.visible, visible: part.object.visible }; }),
          expressions: expressions.map(function (value) { return { key: value.key, name: value.name, weight: value.object.morphTargetInfluences[value.index] }; }),
          body: { height: body.height, breast: body.breast }, scaling: scaling, nodeAdjustments: JSON.parse(JSON.stringify(adjustments)), expressionLimits: expressionLimits(),
          savedNodes: { available: savedOperations.length > 0, enabled: useSavedNodes, applied: useSavedNodes ? savedOperations.length : 0,
            skipped: savedSkipped, conflicts: savedConflicts, operations: savedOperations } };
      }
    };
  }
  window.ViewerRig = { create: create };
}());
