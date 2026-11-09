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
    // Accessory corrections are derived from immutable originals. They are
    // never folded into manual body edits or the next animation baseline.
    var accessoryUnclip = null, accessoryCorrections = {};
    var nodeCompensations = {}, compensationStatuses = {}, automaticTargets = [];
    var automaticMatrices = [];
    var body = { breastPreset: "loaded" };
    var skirtOverrides = {};
    var authoredNodes = {};
    var nodeEditor = null, expressionPanel = null, physicsController = null;
    var selectedNode = "";
    var editingMethods = {}, meshConversions = {}, editorGroup = "node", editorSelections = {}, evaluationMode = "authoring", restoredCompensationReference = {};
    var selectedClip = "";
    var playing = false;
    var interactive = true, authoringEnabled = true;
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
      var record = { object: object, authored: snapshot(object), base: snapshot(object), frame: snapshot(object), frameMatrix: new THREE.Matrix4() };
      all.push(record);
      if (index !== undefined) authoredNodes[String(index)] = record;
      if (object.isMesh) {
        var visible = object.visible && object.userData.hidden_default !== true && object.userData.hideInPreview !== true;
        object.visible = visible;
        parts.push({ object: object, fileVisible: visible, visible: visible, userVisible: undefined, userChanged: false });
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
      clipEntries.push({ name: clip.name, animation: clip, duration: clip.duration, loop: entry.loop !== false, partial: entry.bindingComplete === false, visibility: visibilityTracks(entry.visibility) });
    });
    (info && info.clips || []).forEach(function (entry) {
      if (clipEntries.some(function (clip) { return clip.name === entry.name; })) return;
      var tracks = visibilityTracks(entry.visibility);
      if (tracks.length) clipEntries.push({ name: entry.name, animation: null, duration: Math.max(0, finite(entry.duration, 0)), loop: entry.loop === true, partial: entry.bindingComplete === false, visibility: tracks });
    });
    // A clip's internal name (including ch0301 or eye_900) never establishes a
    // default pose. Only the backend's verified game-resource mapping may do so.
    var previewMotion = info && info.previewMotion;
    var previewMatches = previewMotion && previewMotion.verified === true &&
      previewMotion.kind === "sifas_suit_preview" && typeof previewMotion.name === "string" ?
      clipEntries.filter(function (clip) { return clip.name === previewMotion.name && !clip.partial && clip.animation && isFinite(clip.duration) && clip.duration > 0; }) : [];
    var defaultClip = rigEditable && previewMatches.length === 1 ? previewMatches[0].name : "";
    (rigEditable && info.bones || []).forEach(function (bone) {
      var object = nodes[String(bone.node)];
      if (object) bones.push({ id: String(bone.node), name: bone.path || bone.name || object.name, object: object });
    });
    if (rigEditable && !bones.length) all.forEach(function (record) {
      var object = record.object, index = object.userData && object.userData.elichika_node;
      if (object.isBone && index !== undefined) bones.push({ id: String(index), name: object.name, object: object });
    });
    var boneObjects = new Map(), objectRecords = new Map();
    bones.forEach(function (bone) { boneObjects.set(bone.object, bone); });
    all.forEach(function (record) { objectRecords.set(record.object, record); });

    function boneName(bone) {
      return String(bone.object.userData.originalName || bone.object.name || bone.name).replace(/__\d+$/, "");
    }
    function descendants(bone, immediate) {
      var found = [];
      function visit(object) {
        (object.children || []).forEach(function (child) {
          if (isHelper(child)) return;
          var entry = boneObjects.get(child);
          if (entry) found.push(entry);
          if (!entry || !immediate) visit(child);
        });
      }
      visit(bone.object);
      return found;
    }
    function defaultCompensationMode(bone) {
      return /^Spine/.test(boneName(bone)) && descendants(bone, false).filter(function (child) { return boneName(child) === "Spine2"; }).length === 1 ? "spine2" : "auto";
    }
    function compensationSelection(id) {
      var bone = bones.filter(function (entry) { return entry.id === id; })[0];
      if (!bone) return null;
      var setting = nodeCompensations[id];
      return { bone: bone, enabled: !!(setting && setting.enabled), mode: setting ? setting.mode : defaultCompensationMode(bone) };
    }
    function compensationTargets(selection) {
      var names = { spine2: ["Spine2"], spine1: ["Spine1"], both: ["Spine1", "Spine2"] }[selection.mode];
      if (!names) {
        var children = descendants(selection.bone, true);
        return { bones: children, reason: children.length ? "" : "No descendant bone matches this target choice." };
      }
      var children = descendants(selection.bone, false), result = [];
      for (var index = 0; index < names.length; index += 1) {
        // Resolve inside this exact hierarchy only. Other source armatures can
        // legitimately contain the same names and must never be guessed here.
        var matches = children.filter(function (child) { return boneName(child) === names[index]; });
        if (matches.length !== 1) return { bones: result, reason: matches.length ? "The target name is ambiguous in this bone’s descendants." : "No descendant bone matches this target choice." };
        result.push(matches[0]);
      }
      return { bones: result, reason: "" };
    }
    function compensationStatus(id) {
      if (compensationStatuses[id]) return compensationStatuses[id];
      var selection = compensationSelection(id);
      if (!selection) return null;
      var targets = compensationTargets(selection);
      return { node: id, enabled: selection.enabled, mode: selection.mode, state: "off", reason: targets.reason,
        targets: targets.bones.map(function (bone) { return { node: bone.id, name: boneName(bone) }; }), scaleDelta: [1, 1, 1] };
    }
    function releaseAutomaticMatrices() {
      var released = [];
      automaticMatrices.forEach(function (entry) {
        entry.object.matrixAutoUpdate = entry.autoUpdate;
        // The affine matrix belongs to this evaluation only. Its underlying
        // TRS always contains the ordinary/manual endpoints, never a lossy
        // decomposition of automatic shear.
        entry.object.updateMatrix();
        released.push(entry.object);
      });
      automaticMatrices = []; automaticTargets = [];
      return released;
    }
    function invertible(matrix) {
      var determinant = matrix.determinant(), e = matrix.elements;
      var volume = Math.hypot(e[0], e[1], e[2]) * Math.hypot(e[4], e[5], e[6]) * Math.hypot(e[8], e[9], e[10]);
      // Judge singularity relative to the basis lengths: a small, valid model
      // unit scale is not itself a singular frame.
      return e.every(function (value) { return isFinite(value); }) && isFinite(determinant) &&
        isFinite(volume) && volume > 0 && Math.abs(determinant) / volume > 1e-12;
    }
    function relativeBaseline(parent, child) {
      var path = [], current = child;
      while (current && current !== parent) {
        var record = objectRecords.get(current);
        var reference = record && restoredCompensationReference[String(current.userData && current.userData.elichika_node)];
        var matrix = reference ? new THREE.Matrix4().compose(reference.position, reference.quaternion, reference.scale) : record && record.frameMatrix;
        if (!record || !matrix || !invertible(matrix)) return null;
        path.unshift(matrix); current = current.parent;
      }
      if (current !== parent) return null;
      var result = new THREE.Matrix4();
      path.forEach(function (matrix) { result.multiply(matrix); });
      return invertible(result) ? result : null;
    }
    function hasShear(matrix) {
      var e = matrix.elements, columns = [[e[0], e[1], e[2]], [e[4], e[5], e[6]], [e[8], e[9], e[10]]];
      return columns.some(function (left, index) { return columns.some(function (right, next) {
        if (next <= index) return false;
        var dot = left.reduce(function (sum, value, axis) { return sum + value * right[axis]; }, 0);
        var lengths = Math.sqrt(left.reduce(function (sum, value) { return sum + value * value; }, 0) * right.reduce(function (sum, value) { return sum + value * value; }, 0));
        return Math.abs(dot) > 1e-7 * lengths;
      }); });
    }
    function applyCompensations() {
      var corrections = {}, order = Object.keys(nodeCompensations);
      compensationStatuses = {};
      function depth(id) { var count = 0, object = nodes[id]; while (object && object !== root) { count += 1; object = object.parent; } return count; }
      order.sort(function (left, right) { return depth(left) - depth(right); });
      order.forEach(function (id) {
        var selection = compensationSelection(id);
        if (!selection) return;
        var resolved = compensationTargets(selection), baseline = restoredCompensationReference[id] || objectRecords.get(selection.bone.object).frame;
        var state = { node: id, enabled: selection.enabled, mode: selection.mode, state: selection.enabled ? "ready" : "off", reason: "",
          targets: resolved.bones.map(function (bone) { return { node: bone.id, name: boneName(bone) }; }), scaleDelta: [1, 1, 1] };
        compensationStatuses[id] = state;
        if (!selection.enabled) return;
        if (resolved.reason) { state.state = "unavailable"; state.reason = resolved.reason; return; }
        var manual = adjustments[id], scales = manual && manual.scale || [];
        var invalidBaseline = baseline.scale.toArray().some(function (value) { return !isFinite(value) || Math.abs(value) < 1e-8; });
        if (invalidBaseline || !invertible(new THREE.Matrix4().compose(baseline.position, baseline.quaternion, baseline.scale))) {
          state.state = "unavailable"; state.reason = "A baseline transform has zero or invalid scale."; return;
        }
        state.scaleDelta = baseline.scale.toArray().map(function (value, axis) {
          return typeof scales[axis] === "number" ? scales[axis] / value : 1;
        });
        if (state.scaleDelta.some(function (value) { return !isFinite(value) || Math.abs(value) < 1e-8; })) {
          state.state = "unavailable"; state.reason = "The edited scale cannot be inverted."; return;
        }
        var candidates = [], inverse = new THREE.Matrix4().makeScale(1 / state.scaleDelta[0], 1 / state.scaleDelta[1], 1 / state.scaleDelta[2]);
        resolved.bones.forEach(function (bone) {
          var relative = relativeBaseline(selection.bone.object, bone.object);
          if (!relative) return;
          // Mesh Baker's full-frame rule: C = L^-1 S_delta^-1 L. Keep C
          // affine: rotated/nonuniform descendant frames require its shear.
          var correction = relative.clone().invert().multiply(inverse).multiply(relative);
          if (invertible(correction)) candidates.push({ bone: bone, correction: correction });
        });
        if (candidates.length !== resolved.bones.length) {
          state.state = "unavailable"; state.reason = "A baseline transform has zero or invalid scale."; return;
        }
        if (state.scaleDelta.every(function (value) { return Math.abs(value - 1) <= 1e-10; })) return;
        state.state = "active";
        candidates.forEach(function (candidate) {
          var target = corrections[candidate.bone.id];
          if (!target) target = corrections[candidate.bone.id] = { bone: candidate.bone, correction: new THREE.Matrix4(), from: [] };
          // Closer ancestors cancel first when several edited parents target
          // this bone. Each child's own absolute manual transform stays last.
          target.correction.premultiply(candidate.correction); target.from.push(id);
        });
      });
      Object.keys(corrections).forEach(function (id) {
        var entry = corrections[id], object = entry.bone.object, reference = restoredCompensationReference[id];
        var baseline = reference ? new THREE.Matrix4().compose(reference.position, reference.quaternion, reference.scale) : objectRecords.get(object).frameMatrix;
        var manual = new THREE.Matrix4().compose(object.position, object.quaternion, object.scale);
        // B_target C B_target^-1 M_target preserves explicit child endpoints,
        // including translation and rotation, without undoing source scaling.
        var matrix = baseline.clone().multiply(entry.correction).multiply(baseline.clone().invert()).multiply(manual);
        automaticMatrices.push({ object: object, autoUpdate: object.matrixAutoUpdate });
        object.matrixAutoUpdate = false; object.matrix.copy(matrix); object.matrixWorldNeedsUpdate = true;
        automaticTargets.push({ node: id, name: boneName(entry.bone), from: entry.from.slice(), matrix: matrix.toArray(), correction: entry.correction.toArray(), shear: hasShear(matrix) });
      });
    }
    var savedGroups = {}, rawSaved = {}, conflictKeys = {};
    function differentVector(left, right, rotation) {
      if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length || !left.length) return false;
      var direct = Math.max.apply(null, left.map(function (value, axis) { return Math.abs(value - right[axis]); }));
      var antipodal = rotation ? Math.max.apply(null, left.map(function (value, axis) { return Math.abs(value + right[axis]); })) : Infinity;
      return Math.min(direct, antipodal) > 1e-7;
    }
    (scaling.components || []).forEach(function (component) {
      (component.entries || []).forEach(function (entry) {
        var rawKey = String(entry.node) + ":" + entry.kind;
        if (!rawSaved[rawKey]) rawSaved[rawKey] = [];
        rawSaved[rawKey].push(JSON.parse(JSON.stringify(entry)));
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
        conflictKeys[key] = true; savedConflicts += 1; savedSkipped += values.length; return;
      }
      savedOperations.push(first);
    });
    function savedPart(operation) {
      // Names group labels for people; every actual target/value comes from the
      // verified metadata above, including each separate parent/child skirt bone.
      var name = String(operation.name || "").split("/").pop();
      var groups = [[/^Move$/, "model", "Whole model"], [/Breast/i, "breast", "Breast size"], [/Skirt/i, "skirt", "Skirt"],
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

    function rawControl(kind) { return (scaling.controls || []).filter(function (value) { return value.id === kind; })[0]; }
    function bodyControl(kind) {
      if (!rigEditable) return null;
      var control = rawControl(kind);
      var mode = { breast: "breast_tool_presets", skirt: "absolute_skirt_root_scale", hips: "relative_body_scale", thighs: "compensated_thickness", waist: "compensated_thickness" }[kind];
      return control && control.available === true && control.mode === mode &&
        control.nodes && control.nodes.length && control.nodes.every(function (target) { return !!nodes[String(target.node)]; }) ? control : null;
    }
    function breastPresets() {
      var control = bodyControl("breast"), seen = {};
      return (control && control.presets || []).filter(function (preset) {
        if (!preset || typeof preset.id !== "string" || preset.id === "loaded" || seen[preset.id] ||
            !Array.isArray(preset.scale) || preset.scale.length !== 3 ||
            !preset.scale.every(function (value) { return typeof value === "number" && isFinite(value) && value > 0; })) return false;
        seen[preset.id] = true; return true;
      });
    }
    function applyBodyPreset(get) {
      var control = bodyControl("breast");
      var preset = breastPresets().filter(function (value) { return value.id === body.breastPreset; })[0];
      if (preset) control.nodes.forEach(function (operation) { get(String(operation.node)).scale.fromArray(preset.scale); });
    }
    function applyBody(get) {
      Object.keys(skirtOverrides).forEach(function (id) { var target = get(id); if (target) target.scale.fromArray(skirtOverrides[id]); });
    }
    function authoredMap() {
      var values = {};
      Object.keys(authoredNodes).forEach(function (id) { values[id] = editing.clone(authoredNodes[id].authored); });
      return values;
    }
    function storedFileMap() {
      var values = authoredMap();
      savedOperations.forEach(function (operation) { values[operation.node][operation.kind === "rotation" ? "quaternion" : operation.kind === "scale" ? "scale" : "position"].fromArray(operation.value); });
      return values;
    }
    function fileValues(id) {
      var record = authoredNodes[id], result = {};
      ["scale", "position", "rotation"].forEach(function (kind) {
        var key = id + ":" + kind, entries = rawSaved[key] || [];
        var values = entries.map(function (entry) {
          if (kind !== "rotation") return entry.scaled;
          if (Array.isArray(entry.unityEulerScaled)) return entry.unityEulerScaled;
          var q = entry.scaledQuaternion;
          return Array.isArray(q) && q.length === 4 ? editing.quaternionUI(THREE, new THREE.Quaternion().fromArray(q)) : null;
        }).filter(function (value) { return Array.isArray(value) && value.length === 3 && value.every(function (part) { return typeof part === "number" && isFinite(part); }); });
        var supported = savedOperations.some(function (operation) { return operation.node === id && operation.kind === kind; });
        var status = conflictKeys[key] || entries.some(function (entry) { return entry.reason === "conflicting_saved_entries"; }) ? "conflict" : entries.length ? (!supported || entries.some(function (entry) { return !entry.supported; }) ? "unsupported" : "saved") : "authored";
        var authored = record && (kind === "rotation" ? editing.quaternionUI(THREE, record.authored.quaternion) : record.authored[kind === "position" ? "position" : "scale"].toArray());
        var sourcePosition = info && info.sourcePositions && info.sourcePositions[id];
        if (kind === "position" && Array.isArray(sourcePosition) && sourcePosition.length === 3 &&
            sourcePosition.every(function (part) { return typeof part === "number" && isFinite(part); })) authored = sourcePosition;
        result[kind] = { status: status, value: status === "authored" ? authored.slice() : status === "saved" ? values[0].slice() : null, values: values.map(function (value) { return value.slice(); }) };
        if (kind === "position" && authored === sourcePosition) result[kind].runtime = record.authored.position.toArray();
      });
      return result;
    }
    function fileMap() {
      var values = {};
      Object.keys(authoredNodes).forEach(function (id) { values[id] = editing.clone(authoredNodes[id].authored); });
      activeSavedOperations().forEach(function (operation) {
        values[operation.node][operation.kind === "rotation" ? "quaternion" : operation.kind === "scale" ? "scale" : "position"].fromArray(operation.value);
      });
      return values;
    }
    function applyUser(target, values, id) {
      ["scale", "position"].forEach(function (kind) {
        (values[kind] || []).forEach(function (value, axis) { if (typeof value === "number" && isFinite(value)) target[kind].setComponent(axis, value); });
      });
      if ((values.rotation || []).some(function (value) { return typeof value === "number"; })) {
        var euler = editing.quaternionUI(THREE, target.quaternion, savedEuler(id));
        values.rotation.forEach(function (value, axis) { if (typeof value === "number" && isFinite(value)) euler[axis] = value; });
        target.quaternion.copy(editing.uiQuaternion(THREE, euler));
      }
    }
    function staticMap(adjusted) {
      var values = fileMap();
      applyBodyPreset(function (id) { return values[id]; });
      applyBody(function (id) { return values[id]; });
      if (expressionPanel) expressionPanel.getBoneOperations().forEach(function (operation) {
        var target = values[String(operation.node)];
        if (target && ["position", "scale", "quaternion"].indexOf(operation.kind) >= 0) target[operation.kind].fromArray(operation.value);
      });
      if (adjusted) Object.keys(adjustments).forEach(function (id) { if (values[id]) applyUser(values[id], adjustments[id], id); });
      return values;
    }
    function editingValues(id) {
      var value = editing.toUI(THREE, staticMap(true)[id], savedEuler(id)), manual = adjustments[id];
      if (manual && (manual.rotation || []).some(function (part) { return part !== null; })) {
        value.rotation = editing.toUI(THREE, staticMap(false)[id], savedEuler(id)).rotation;
        manual.rotation.forEach(function (part, axis) { if (typeof part === "number") value.rotation[axis] = part; });
      }
      return value;
    }
    function nodeFlags(id) {
      var operations = savedOperations.filter(function (operation) { return operation.node === id; });
      var active = activeSavedOperations();
      var bodyChanged = !!skirtOverrides[id] || body.breastPreset !== "loaded" && !!bodyControl("breast") && bodyControl("breast").nodes.some(function (target) { return String(target.node) === id; });
      return { saved: operations.length > 0, fileChanged: operations.some(function (operation) { return operation.changed && active.indexOf(operation) >= 0; }),
        modified: !editing.adjustmentEmpty(adjustments[id]) || !!nodeCompensations[id] || !!meshConversions[id], body: bodyChanged,
        expression: !!expressionPanel && expressionPanel.getBoneOperations().some(function (operation) { return String(operation.node) === id; }) };
    }
    function savedEuler(id) {
      var entry = activeSavedOperations().filter(function (operation) { return operation.node === id && operation.kind === "rotation"; })[0];
      return entry && entry.sourceEuler;
    }
    function applyAdjustments(released, beforeAnimation) {
      activeSavedOperations().forEach(function (operation) {
        nodes[operation.node][operation.kind === "rotation" ? "quaternion" : operation.kind === "scale" ? "scale" : "position"].fromArray(operation.value);
      });
      applyBodyPreset(function (id) { return nodes[id]; });
      applyBody(function (id) { return nodes[id]; });
      if (expressionPanel) expressionPanel.applyBonesAndMorphs();
      all.forEach(function (record) {
        capture(record.object, record.frame);
        record.frameMatrix.compose(record.frame.position, record.frame.quaternion, record.frame.scale);
      });
      Object.keys(adjustments).forEach(function (id) {
        var target = nodes[id], values = adjustments[id];
        if (!target) return;
        applyUser(target, values, id);
      });
      // A source may originally manage its own matrix. On release it still
      // needs this frame's restored TRS rather than the last affine matrix.
      (released || []).forEach(function (object) { object.updateMatrix(); });
      if (!beforeAnimation) applyCompensations();
      Object.keys(accessoryCorrections).forEach(function (id) {
        var target = nodes[id], delta = accessoryCorrections[id];
        if (!target) return;
        // The server derives this in the final compensated parent's frame.
        // A directly compensated anchor may have an affine/sheared matrix;
        // translate that finished matrix, not a TRS that C will scale again.
        target.position.add(delta);
        if (target.matrixAutoUpdate === false) {
          target.matrix.elements[12] += delta.x;
          target.matrix.elements[13] += delta.y;
          target.matrix.elements[14] += delta.z;
          target.matrixWorldNeedsUpdate = true;
        }
      });
      parts.forEach(function (part) { part.object.visible = part.visible; });
      if (currentClip) currentClip.visibility.forEach(function (track) {
        var time = currentTime(), value = track.values[0];
        for (var index = 1; index < track.times.length && track.times[index] <= time; index += 1) value = track.values[index];
        track.targets.forEach(function (target) { target.visible = target.visible && value; });
      });
      if (currentClip && currentClip.timeline) currentClip.timeline.applyVisibility(currentTime());
      if (expressionPanel) expressionPanel.applyVisibility(parts);
      parts.forEach(function (part) { if (part.userChanged && typeof part.userVisible === "boolean") part.object.visible = part.userVisible; });
      root.updateMatrixWorld(true);
      root.traverse(function (object) { if (object.isSkinnedMesh) object.skeleton.update(); });
    }
    function replayAnimationTracks() {
      if (!currentClip || !currentClip.animation) return;
      if (!currentClip.replayTracks) currentClip.replayTracks = currentClip.animation.tracks.map(function (track) {
        var binding = THREE.PropertyBinding.create(root, track.name); binding.bind();
        return { binding: binding, interpolant: track.createInterpolant() };
      });
      // Three's PropertyMixer skips writing an unchanged constant value. We
      // restore authoring values each frame, so explicitly replay each loaded
      // single-action track after update, including paused/scrubbed frames.
      currentClip.replayTracks.forEach(function (track) { track.binding.setValue(track.interpolant.evaluate(currentTime()), 0); });
    }
    function evaluate(delta) {
      if (disposed) return;
      var released = releaseAutomaticMatrices();
      if (evaluationMode === "animation") {
        // Inspect the loaded clip's own track writes. This deliberately does
        // not pretend that changing a bone is the same as baking its mesh.
        all.forEach(function (record) { restore(record.object, record.authored); });
        applyAdjustments(released, true);
        if (mixer) mixer.update(delta || 0);
        replayAnimationTracks();
        if (currentClip && currentClip.timeline) currentClip.timeline.evaluate(currentTime());
        // Facial choices remain render-only inspection controls in both modes;
        // changing the body's evaluation order must not disable face review.
        if (expressionPanel) { expressionPanel.applyBonesAndMorphs(); expressionPanel.applyVisibility(parts); }
        root.updateMatrixWorld(true);
        root.traverse(function (object) { if (object.isSkinnedMesh) object.skeleton.update(); });
      } else {
        all.forEach(function (record) { restore(record.object, currentClip && currentClip.timeline ? record.authored : record.base); });
        if (mixer) mixer.update(delta || 0);
        if (currentClip && currentClip.timeline) currentClip.timeline.evaluate(currentTime());
        all.forEach(function (record) { capture(record.object, record.base); });
        applyAdjustments(released);
      }
      if (physicsController) physicsController.apply(delta || 0);
      if (nodeEditor && nodeEditor.refreshPose) nodeEditor.refreshPose();
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
      var slider = element("viewer-time"), value = String(seconds);
      if (slider.value !== value) slider.value = value;
      var output = element("viewer-time-value"), text = seconds.toFixed(2) + " / " + duration().toFixed(2) + " s";
      if (output.textContent !== text) output.textContent = text;
      var button = element("viewer-play"), label = translate(playing ? "Pause" : "Play");
      if (button.textContent !== label) button.textContent = label;
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
      if (nodeEditor) nodeEditor.setInteractive(enabled && authoringEnabled);
      if (physicsController) physicsController.setInteractive(enabled, authoringEnabled);
      element("viewer-saved-nodes").disabled = !enabled || !authoringEnabled || !savedOperations.length;
      savedParts.forEach(function (part) { if (part.input) part.input.disabled = !enabled || !authoringEnabled || !useSavedNodes; });
      element("viewer-preview-reset").disabled = !enabled || !(bones.length || clipEntries.length || expressions.length);
      ["node", "mesh"].forEach(function (tool) { var tab = element("viewer-editor-" + tool + "-tab"); if (tab) tab.disabled = !enabled || !rigEditable; });
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
    function clearManualScale(targets) {
      targets.forEach(function (target) { var key = String(target.node), value = adjustments[key];
        if (value) { value.scale = [null, null, null]; if (editing.adjustmentEmpty(value)) delete adjustments[key]; }
      });
    }
    function breastProfile() {
      var control = bodyControl("breast"), baseline = fileMap(), current = staticMap(true);
      var targets = control ? control.nodes.map(function (target) {
        var id = String(target.node), file = fileValues(id).scale;
        return { node: id, fileScale: file.value, fileStatus: file.status, activeScale: baseline[id].scale.toArray(), currentScale: current[id].scale.toArray() };
      }) : [];
      function matches(values, preset) { return values.length > 0 && values.every(function (value) { return value && value.every(function (part, axis) { return Math.abs(part - preset.scale[axis]) < 1e-7; }); }); }
      var fileMatch = breastPresets().filter(function (preset) { return matches(targets.map(function (target) { return target.fileScale; }), preset); })[0];
      var selected = breastPresets().filter(function (preset) { return preset.id === body.breastPreset; })[0];
      return { available: !!control, selected: body.breastPreset, fileProfile: fileMatch ? fileMatch.id : null,
        custom: targets.some(function (target) { return (adjustments[target.node] && (adjustments[target.node].scale || []).some(function (part) { return part !== null; })) || target.currentScale.some(function (part, axis) { return Math.abs(part - (selected ? selected.scale : target.activeScale)[axis]) > 1e-7; }); }),
        savedSettingsEnabled: useSavedNodes, targets: targets };
    }
    function skirtValues() {
      var control = rawControl("skirt"), active = fileMap(), current = staticMap(true), seen = {};
      var targets = (control && control.nodes || []).filter(function (target) { var id = String(target.node); if (!nodes[id] || seen[id]) return false; seen[id] = true; return true; }).map(function (target) {
        var id = String(target.node), file = fileValues(id).scale;
        return { node: id, name: target.name || nodes[id].name, sourceName: target.sourceName || "", fileScale: file.value, fileStatus: file.status,
          activeScale: active[id].scale.toArray(), currentScale: current[id].scale.toArray() };
      });
      function uniform(key) {
        if (!targets.length) return null;
        var first = targets.length && targets[0][key] && targets[0][key][0];
        return typeof first === "number" && targets.every(function (target) { return target[key] && target[key].every(function (value) { return Math.abs(value - first) <= 1e-7; }); }) ? first : null;
      }
      return { available: !!bodyControl("skirt"), targets: targets, fileUniform: uniform("fileScale"), currentUniform: uniform("currentScale"),
        edited: Object.keys(skirtOverrides).length > 0 || targets.some(function (target) { return adjustments[target.node] && (adjustments[target.node].scale || []).some(function (value) { return value !== null; }); }),
        overrides: JSON.parse(JSON.stringify(skirtOverrides)), editBounds: control && control.editBounds || { min: .01, max: 10 } };
    }
    function effectiveMethod(id) {
      var explicit = editingMethods[id];
      if (explicit && explicit !== "auto") return explicit;
      var target = ((options.editing || {}).nodes || []).filter(function (entry) { return String(entry.node) === String(id); })[0];
      return target ? target.recommendedMethod : "choose";
    }
    var percentageKinds = ["thighs", "waist"];
    function percentageState(kind) {
      var raw = rawControl(kind), control = bodyControl(kind), baseline = fileMap(), current = staticMap(true);
      var axes = kind === "hips" ? [0, 1, 2] : [1, 2], ratios = [], reason = "";
      var targets = (raw && raw.nodes || []).filter(function (target) { return baseline[String(target.node)] && current[String(target.node)]; }).map(function (target) {
        var id = String(target.node), manual = adjustments[id], original = baseline[id].scale.toArray(), value = current[id].scale.toArray();
        var file = fileValues(id).scale;
        var writable = options.editing && options.editing.available && (options.editing.nodes || []).filter(function (entry) { return String(entry.node) === id; })[0];
        if (!writable || !Array.isArray(writable.methods) || writable.methods.indexOf(raw.method) < 0) reason = "This model cannot save this adjustment with its required method.";
        if (kind !== "hips") {
          var bone = bones.filter(function (entry) { return entry.id === id; })[0];
          var resolved = bone && compensationTargets({ bone: bone, enabled: true, mode: kind === "waist" ? "spine2" : "auto" });
          var expected = (target.compensationTargets || []).map(String).sort();
          var actual = resolved ? resolved.bones.map(function (entry) { return entry.id; }).sort() : [];
          if (!resolved || resolved.reason || !expected.length || expected.join(",") !== actual.join(",")) reason = "The child hierarchy does not match this thickness adjustment. Use advanced controls.";
        }
        if (file.status === "conflict" || file.status === "unsupported") reason = "Resolve conflicting file values before using this control.";
        if (original.some(function (part) { return !isFinite(part) || part <= 0; })) reason = "This control needs positive original scale values.";
        if (editingMethods[id] && editingMethods[id] !== "auto" && editingMethods[id] !== raw.method) reason = "Change this bone's save method in advanced controls before using this adjustment.";
        if (kind !== "hips" && manual && manual.scale && typeof manual.scale[0] === "number" && Math.abs(manual.scale[0] - original[0]) > 1e-7) reason = "Reset length-axis edits in advanced controls before adjusting thickness.";
        if (kind === "hips" && nodeCompensations[id] && nodeCompensations[id].enabled) reason = "Turn child compensation off in advanced controls before using this node adjustment.";
        axes.forEach(function (axis) { if (original[axis] > 0) ratios.push(value[axis] / original[axis] * 100); });
        return { node: id, name: target.name || nodes[id].name, fileScale: file.value, fileStatus: file.status, baseScale: original, currentScale: value };
      });
      var available = !!control && !reason;
      if (!control && !reason) reason = "This model has no unambiguous nodes for this adjustment.";
      var percent = ratios.length && ratios.every(function (part) { return Math.abs(part - ratios[0]) <= 1e-5; }) ? ratios[0] : null;
      return { available: available, reason: reason, targets: targets, currentPercent: percent, edited: targets.some(function (target) {
        return axes.some(function (axis) { return Math.abs(target.currentScale[axis] - target.baseScale[axis]) > 1e-7; });
      }), method: raw && raw.method || (kind === "hips" ? "node" : "mesh"), editedAxes: axes, lengthAxis: kind === "hips" ? null : 0,
        compensate: kind !== "hips", compensationMode: kind === "waist" ? "spine2" : kind === "thighs" ? "auto" : "none",
        editBounds: raw && raw.editBounds || { min: 20, max: 250 } };
    }
    function setPercentage(kind) {
      var state = percentageState(kind), input = element("viewer-" + kind + "-number"), percent = Number(input.value);
      if (!state.available || !input.value.trim() || !isFinite(percent) || percent < state.editBounds.min || percent > state.editBounds.max) {
        input.dataset.viewerPercentageDirty = "true"; input.setAttribute("aria-invalid", "true");
        input.setCustomValidity(translate("Enter a percentage between 20 and 250.")); input.reportValidity(); changed(); return;
      }
      input.setCustomValidity(""); input.removeAttribute("aria-invalid"); delete input.dataset.viewerPercentageDirty;
      state.targets.forEach(function (target) {
        var id = target.node, previous = adjustments[id], value = { mode: "absolute_axes", scale: [null, null, null], position: [null, null, null], rotation: [null, null, null] };
        ["scale", "position", "rotation"].forEach(function (name) { if (previous && Array.isArray(previous[name])) value[name] = previous[name].slice(); });
        state.editedAxes.forEach(function (axis) { value.scale[axis] = Math.abs(percent - 100) <= 1e-10 ? null : target.baseScale[axis] * percent / 100; });
        if (editing.adjustmentEmpty(value)) delete adjustments[id]; else adjustments[id] = value;
        if (Math.abs(percent - 100) > 1e-10) {
          editingMethods[id] = state.method;
          if (state.compensate) nodeCompensations[id] = { enabled: true, mode: state.compensationMode };
        } else {
          if (!(value.scale || []).some(function (part) { return typeof part === "number"; })) delete nodeCompensations[id];
          clearUnusedMethod(id);
        }
      });
      evaluate(0); refreshBodyControls(); refreshNode(); changed();
    }
    function hipsInputs() {
      return ["x", "y", "z"].map(function (axis) { return element("viewer-hips-scale-" + axis); });
    }
    function hipsState() {
      var state = percentageState("hips");
      state.axisValues = [0, 1, 2].map(function (axis) {
        var values = state.targets.map(function (target) { return target.currentScale[axis]; });
        return values.length && values.every(function (value) { return Math.abs(value - values[0]) <= 1e-7; }) ? values[0] : null;
      });
      state.mode = "absolute_axes";
      state.editBounds = { min: 1e-8, max: 1000000 };
      return state;
    }
    function validateHipInput(input) {
      var value = Number(input.value), invalid = !input.value.trim() || !isFinite(value) || value < 1e-8 || value > 1000000;
      input.setCustomValidity(invalid ? translate("Enter a positive finite scale between 0.00000001 and 1000000.") : "");
      if (invalid) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid");
      return !invalid;
    }
    function clearHipDrafts() {
      hipsInputs().forEach(function (input) {
        delete input.dataset.viewerHipsDirty; input.setCustomValidity(""); input.removeAttribute("aria-invalid");
      });
    }
    function applyHipAxes() {
      var state = hipsState(), inputs = hipsInputs(), dirty = inputs.filter(function (input) { return input.dataset.viewerHipsDirty === "true"; });
      if (!state.available || !dirty.length) return;
      var invalid = dirty.filter(function (input) { return !validateHipInput(input); });
      if (invalid.length) { invalid[0].reportValidity(); changed(); return; }
      state.targets.forEach(function (target) {
        var id = target.node, previous = adjustments[id];
        var value = { mode: "absolute_axes", scale: [null, null, null], position: [null, null, null], rotation: [null, null, null] };
        ["scale", "position", "rotation"].forEach(function (kind) { if (previous && Array.isArray(previous[kind])) value[kind] = previous[kind].slice(); });
        // Display rounding never becomes an edit to an untouched axis. Typed
        // values are absolute endpoints on each original, not baseline ratios.
        dirty.forEach(function (input) { value.scale[Number(input.dataset.viewerHipsAxis)] = Number(input.value); });
        adjustments[id] = value; methodForNewEdit(id, "node");
      });
      clearHipDrafts(); evaluate(0); refreshBodyControls(); refreshNode(); changed();
    }
    function undoHipAxes() {
      var control = rawControl("hips"); if (!control || !control.available) return;
      (control.nodes || []).forEach(function (target) {
        var id = String(target.node), value = adjustments[id];
        if (value && Array.isArray(value.scale)) {
          value.scale = [null, null, null];
          if (editing.adjustmentEmpty(value)) delete adjustments[id];
        }
        delete meshConversions[id]; delete nodeCompensations[id]; clearUnusedMethod(id);
      });
      clearHipDrafts(); evaluate(0); refreshBodyControls(); refreshNode(); changed();
    }
    function refreshHipAxes() {
      var state = hipsState(), enabled = interactive && authoringEnabled && !disposed && state.available;
      hipsInputs().forEach(function (input, axis) {
        input.disabled = !enabled;
        if (input.dataset.viewerHipsDirty !== "true") {
          input.value = state.axisValues[axis] === null ? "" : numberText(state.axisValues[axis]);
          input.setCustomValidity(""); input.removeAttribute("aria-invalid");
        }
        input.placeholder = translate(state.targets.length ? "Different values" : "Not available for this model.");
      });
      element("viewer-hips-apply").disabled = !enabled;
      element("viewer-hips-reset").disabled = !interactive || !authoringEnabled || disposed ||
        (!state.edited && !hipsInputs().some(function (input) { return input.dataset.viewerHipsDirty === "true"; })) || !rawControl("hips") || !rawControl("hips").available;
      element("viewer-hips-file-values").textContent = state.targets.map(function (target) { return scaleText(target.fileScale, target.fileStatus); }).join("; ") || "—";
      element("viewer-hips-current-values").textContent = state.targets.map(function (target) { return scaleText(target.currentScale); }).join("; ") || "—";
      var status = element("viewer-hips-status");
      status.textContent = state.available ? translate("Children follow this size adjustment; inverse compensation is not used.") : translate(state.reason);
      status.classList.toggle("error", !state.available && !!rawControl("hips"));
    }
    function thighPresets() {
      var control = rawControl("thighs"), seen = {};
      if (!control || control.presetApplication !== "relative_to_original_static_scale" ||
          control.presetPercentagePolicy !== "replace_same_axes" || control.presetSourceRequired !== true) return [];
      var bounds = control.editBounds || { min: 20, max: 250 };
      return (control.presets || []).filter(function (preset) {
        var scale = preset.scaleDelta;
        if (typeof preset.id !== "string" || !preset.id || seen[preset.id] ||
            typeof preset.sourceLabel !== "string" || typeof preset.targetLabel !== "string" ||
            !Array.isArray(scale) || scale.length !== 3 || Math.abs(scale[0] - 1) > 1e-12 ||
            !scale.every(function (value) { return typeof value === "number" && isFinite(value) && value > 0; }) ||
            !scale.slice(1).every(function (value) { return value * 100 >= bounds.min && value * 100 <= bounds.max; })) return false;
        seen[preset.id] = true; return true;
      });
    }
    function thighPresetLabel(preset) {
      return translate(preset.sourceLabel) + " → " + translate(preset.targetLabel);
    }
    function thighProfileState() {
      var state = percentageState("thighs"), original = storedFileMap(), presets = thighPresets();
      var targets = state.targets.map(function (target) {
        return { node: target.node, originalScale: original[target.node].scale.toArray(), currentScale: target.currentScale };
      });
      function matches(scale) {
        return targets.length && targets.every(function (target) {
          return [1, 2].every(function (axis) {
            return Math.abs(target.currentScale[axis] / target.originalScale[axis] - scale[axis]) <= 1e-7;
          });
        });
      }
      var selected = matches([1, 1, 1]) ? "loaded" : "custom";
      var compensated = targets.every(function (target) {
        return effectiveMethod(target.node) === "mesh" && nodeCompensations[target.node] && nodeCompensations[target.node].enabled;
      });
      presets.forEach(function (preset) { if (compensated && matches(preset.scaleDelta)) selected = preset.id; });
      var savedEnabled = !savedOperations.length || useSavedNodes && savedParts.every(function (part) { return part.enabled; });
      return { available: state.available && !!presets.length && savedEnabled, selected: selected,
        reason: !savedEnabled ? "Turn saved file settings on before saving body changes." : state.reason,
        targets: targets, presets: presets };
    }
    function applyThighPreset() {
      var state = thighProfileState(), selected = element("viewer-thighs-preset").value;
      var preset = state.presets.filter(function (entry) { return entry.id === selected; })[0];
      if (!state.available || !preset) return;
      state.targets.forEach(function (target) {
        var id = target.node, previous = adjustments[id];
        var value = { mode: "absolute_axes", scale: [null, null, null], position: [null, null, null], rotation: [null, null, null] };
        ["scale", "position", "rotation"].forEach(function (name) { if (previous && Array.isArray(previous[name])) value[name] = previous[name].slice(); });
        [1, 2].forEach(function (axis) { value.scale[axis] = target.originalScale[axis] * preset.scaleDelta[axis]; });
        adjustments[id] = value; editingMethods[id] = "mesh"; nodeCompensations[id] = { enabled: true, mode: "auto" };
      });
      // A preset replaces the percentage operation, including an unapplied
      // invalid draft. Unequal Y/Z is a valid mixed display, not a Save error.
      var input = element("viewer-thighs-number"); input.value = "";
      input.setCustomValidity(""); input.removeAttribute("aria-invalid"); delete input.dataset.viewerPercentageDirty;
      evaluate(0); refreshBodyControls(); refreshNode(); changed();
    }
    function refreshThighPresets() {
      var select = element("viewer-thighs-preset"); if (!select) return;
      var state = thighProfileState(), enabled = interactive && authoringEnabled && !disposed && state.available;
      select.textContent = ""; appendOption(select, "", translate("Choose source → target"));
      if (state.selected === "custom") { appendOption(select, "custom", translate("Custom adjustment")); select.lastChild.disabled = true; }
      state.presets.forEach(function (preset) { appendOption(select, preset.id, thighPresetLabel(preset)); });
      select.value = state.selected === "loaded" ? "" : state.selected; select.disabled = !enabled;
      element("viewer-thighs-preset-apply").disabled = !enabled || !state.presets.some(function (preset) { return preset.id === select.value; });
      var selected = state.presets.filter(function (preset) { return preset.id === state.selected; })[0];
      element("viewer-thighs-preset-status").textContent = !state.available && state.reason ? translate(state.reason) :
        translate("Current thigh preset") + ": " + (selected ? thighPresetLabel(selected) : translate(state.selected === "loaded" ? "No extra edits" : "Custom adjustment"));
    }
    function undoPercentage(kind) {
      var input = element("viewer-" + kind + "-number"), raw = rawControl(kind);
      if (!raw || !raw.available) return;
      var axes = kind === "hips" ? [0, 1, 2] : [1, 2];
      (raw.nodes || []).forEach(function (target) {
        var id = String(target.node), value = adjustments[id];
        if (value && Array.isArray(value.scale)) {
          axes.forEach(function (axis) { value.scale[axis] = null; });
          if (editing.adjustmentEmpty(value)) delete adjustments[id];
        }
        if (!adjustments[id] || !(adjustments[id].scale || []).some(function (part) { return typeof part === "number"; })) delete nodeCompensations[id];
        clearUnusedMethod(id);
      });
      input.value = "100"; input.setCustomValidity(""); input.removeAttribute("aria-invalid"); delete input.dataset.viewerPercentageDirty;
      evaluate(0); refreshBodyControls(); refreshNode(); changed();
    }
    function refreshPercentages() {
      percentageKinds.forEach(function (kind) {
        var input = element("viewer-" + kind + "-number"); if (!input) return;
        var state = percentageState(kind), enabled = interactive && authoringEnabled && !disposed && state.available;
        input.disabled = !enabled; input.min = String(state.editBounds.min); input.max = String(state.editBounds.max);
        if (document.activeElement !== input) {
          // Mixed or out-of-card-range values can come from valid advanced
          // edits. A display value is not an invalid user draft.
          input.value = state.currentPercent === null ? "" : numberText(state.currentPercent);
          input.setCustomValidity(""); input.removeAttribute("aria-invalid"); delete input.dataset.viewerPercentageDirty;
        }
        input.placeholder = translate(state.targets.length ? "Different values" : "Not available for this model.");
        element("viewer-" + kind + "-apply").disabled = !enabled;
        element("viewer-" + kind + "-reset").disabled = !interactive || !authoringEnabled || disposed || !state.edited || !rawControl(kind) || !rawControl(kind).available;
        element("viewer-" + kind + "-file-values").textContent = state.targets.map(function (target) { return scaleText(target.fileScale, target.fileStatus); }).join("; ") || "—";
        element("viewer-" + kind + "-current-values").textContent = state.targets.map(function (target) { return scaleText(target.currentScale); }).join("; ") || "—";
        var status = element("viewer-" + kind + "-status"); status.textContent = state.available ? translate(kind === "hips" ? "Children follow this size adjustment; inverse compensation is not used." : kind === "waist" ? "Keeps bone length. Spine2 compensation preserves the chest, shoulders and head." : "Keeps bone length. Child compensation preserves the calves and feet.") : translate(state.reason);
        status.classList.toggle("error", !state.available && !!rawControl(kind));
      });
    }
    function clearUnusedMethod(id) {
      if (!editing.adjustmentEmpty(adjustments[id]) || meshConversions[id] || skirtOverrides[id]) return;
      var breast = bodyControl("breast");
      if (body.breastPreset !== "loaded" && breast && breast.nodes.some(function (target) { return String(target.node) === id; })) return;
      delete editingMethods[id];
    }
    function methodForNewEdit(id, tool) {
      if (!Object.prototype.hasOwnProperty.call(editingMethods, id)) editingMethods[id] = tool || editorGroup;
    }
    function toolAccepts(id) {
      var bone = bones.filter(function (entry) { return entry.id === String(id); })[0];
      if (!bone) return false;
      var names = editorGroup === "node" ? ["Move", "Head", "Head_Hair", "Neck_Hair"] : ["LeftArm", "RightArm", "LeftForeArm", "RightForeArm", "LeftLeg", "RightLeg"];
      return names.indexOf(boneName(bone)) >= 0 && (!(options.editing && options.editing.available) || effectiveMethod(id) === editorGroup);
    }
    function setEditorGroup(group) {
      if (disposed || ["node", "mesh"].indexOf(group) < 0) return;
      var previous = editorGroup;
      if (nodeEditor) editorSelections[previous] = nodeEditor.getSelected();
      editorGroup = group;
      var shared = element("viewer-shared-bone-editor"), slot = element(group === "mesh" ? "viewer-mesh-tool-slot" : "viewer-node-tool-slot");
      if (shared && slot && shared.parentNode !== slot) slot.appendChild(shared);
      ["node", "mesh"].forEach(function (tool) {
        var selected = tool === group, tab = element("viewer-editor-" + tool + "-tab"), panel = element("viewer-editor-" + tool + "-panel");
        if (tab) { tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1; }
        if (panel) panel.hidden = !selected;
      });
      if (nodeEditor) {
        var filter = element("viewer-node-filter"), search = element("viewer-node-search");
        if (filter) filter.value = options.editing && options.editing.available ? "tool" : "all";
        if (search) search.value = "";
        if (editorSelections[group] && toolAccepts(editorSelections[group])) nodeEditor.select(editorSelections[group], false);
        else nodeEditor.refresh(true);
      }
      if (options.onSelection) options.onSelection();
    }
    function chooseBreastProfile(id) {
      if (!bodyControl("breast") || id !== "loaded" && !breastPresets().some(function (preset) { return preset.id === id; })) return;
      body.breastPreset = id; restoredCompensationReference = {}; clearManualScale(bodyControl("breast").nodes);
      bodyControl("breast").nodes.forEach(function (target) { var node = String(target.node); delete meshConversions[node]; if (id !== "loaded") methodForNewEdit(node, "node"); else clearUnusedMethod(node); });
      evaluate(0); refreshBodyControls(); refreshNode(); changed();
    }
    function setSkirt() {
      var state = skirtValues(), input = element("viewer-skirt-number"), value = Number(input.value);
      if (!state.available || !input.value.trim() || !isFinite(value) || value < state.editBounds.min || value > state.editBounds.max) {
        input.setCustomValidity(translate("Skirt scale must be between 0.01 and 10.")); input.reportValidity(); return;
      }
      input.setCustomValidity(""); restoredCompensationReference = {}; state.targets.forEach(function (target) { skirtOverrides[target.node] = [value, value, value]; delete meshConversions[target.node]; methodForNewEdit(String(target.node), "node"); }); clearManualScale(state.targets);
      evaluate(0); refreshBodyControls(); refreshNode(); changed();
    }
    function undoSkirt() {
      var state = skirtValues(); skirtOverrides = {}; restoredCompensationReference = {}; clearManualScale(state.targets);
      state.targets.forEach(function (target) { delete meshConversions[target.node]; clearUnusedMethod(String(target.node)); });
      evaluate(0); refreshBodyControls(); refreshNode(); changed();
    }
    function numberText(value) { return String(Number(value.toPrecision(7))); }
    function scaleText(value, status) {
      if (!value) return translate(status === "conflict" ? "Conflicting file values" : "Unsupported file value");
      return value.map(numberText).join(" / ") + (status === "authored" ? " · " + translate("Authored fallback") : "");
    }
    function initializeNodeCards() {
      var states = { breast: breastProfile(), hips: hipsState(), skirt: skirtValues() };
      Object.keys(states).forEach(function (kind) {
        var card = element("viewer-" + kind + "-card"), state = states[kind];
        if (!card) return;
        // The default is the actual XYZ endpoint, including saved settings,
        // rather than 100% of a possibly non-unit loaded shape. Unknown values
        // stay open so their explanation is visible.
        var unit = state.available && state.targets.length && state.targets.every(function (target) {
          return target.fileStatus !== "conflict" && target.fileStatus !== "unsupported" &&
            Array.isArray(target.currentScale) && target.currentScale.length === 3 &&
            target.currentScale.every(function (value) { return value === 1; });
        });
        card.open = !unit;
      });
    }
    function refreshBodyControls() {
      refreshHipAxes();
      refreshPercentages();
      refreshThighPresets();
      var skirt = skirtValues(), noSkirt = !skirt.targets.length, enabled = interactive && authoringEnabled && !disposed && skirt.available, input = element("viewer-skirt-number");
      input.disabled = !enabled; input.min = String(skirt.editBounds.min); input.max = String(skirt.editBounds.max);
      if (noSkirt || document.activeElement !== input) input.value = skirt.currentUniform === null ? "" : numberText(skirt.currentUniform);
      input.placeholder = translate(noSkirt ? "Not available for this model." : "Different values"); element("viewer-skirt-apply").disabled = !enabled;
      var badFile = skirt.targets.some(function (target) { return target.fileStatus === "conflict"; }) ? "Conflicting file values" : skirt.targets.some(function (target) { return target.fileStatus === "unsupported"; }) ? "Unsupported file value" : null;
      element("viewer-skirt-file").textContent = noSkirt ? translate("Not available for this model.") : badFile ? translate(badFile) : (skirt.fileUniform === null ? translate("Different values") : numberText(skirt.fileUniform)) + (skirt.targets.some(function (target) { return target.fileStatus === "authored"; }) ? " · " + translate("Authored fallback") : "");
      element("viewer-skirt-value").textContent = noSkirt ? translate("Not available for this model.") : skirt.currentUniform === null ? translate("Different values") : numberText(skirt.currentUniform);
      element("viewer-skirt-reset").disabled = !interactive || !authoringEnabled || disposed || !skirt.edited;
      var rows = element("viewer-skirt-nodes"); rows.textContent = "";
      var repeatedNames = {};
      skirt.targets.forEach(function (target) { repeatedNames[target.name] = (repeatedNames[target.name] || 0) + 1; });
      skirt.targets.forEach(function (target) { var row = document.createElement("tr"); row.dataset.viewerSkirtNode = target.node;
        [target.name + (repeatedNames[target.name] > 1 ? " [" + target.node + "]" : ""), scaleText(target.fileScale, target.fileStatus), scaleText(target.currentScale)].forEach(function (text, index) {
          var cell = document.createElement("td"); cell.textContent = text;
          if (!index && target.sourceName) { cell.title = target.sourceName; cell.setAttribute("aria-label", target.name + " · " + target.sourceName + " · " + target.node); }
          row.appendChild(cell);
        }); rows.appendChild(row);
      });
      var state = breastProfile(), preset = breastPresets().filter(function (value) { return value.id === state.selected; })[0];
      var fileProfile = breastPresets().filter(function (value) { return value.id === state.fileProfile; })[0];
      function label(value) { return translate(value.id === "stock" ? "Reference baseline" : value.label); }
      element("viewer-breast-loaded").textContent = state.targets.some(function (target) { return target.fileStatus === "conflict" || target.fileStatus === "unsupported"; }) ? translate("File value unavailable") : fileProfile ? label(fileProfile) : translate("Custom shape");
      element("viewer-breast-value").textContent = !state.available ? translate("This model has no verified breast-size node.") : state.custom ? translate("Custom shape") : preset ? label(preset) : translate("No extra edits");
      element("viewer-breast-file-values").textContent = state.targets.map(function (target) { return scaleText(target.fileScale, target.fileStatus); }).join("; ") || "—";
      element("viewer-breast-current-values").textContent = state.targets.map(function (target) { return scaleText(target.currentScale); }).join("; ") || "—";
      var select = element("viewer-breast-preset"); select.disabled = !interactive || !authoringEnabled || disposed || !state.available; select.value = body.breastPreset;
      element("viewer-breast-reset").disabled = !interactive || !authoringEnabled || disposed || !state.available || state.selected === "loaded" && !state.custom;
      element("viewer-height-value").textContent = translate("Height correction unavailable");
      var metadata = (scaling.components || []).filter(function (part) { return typeof part.heightScale === "number" && isFinite(part.heightScale); });
      var source = element("viewer-height-source"); source.hidden = !metadata.length;
      source.textContent = "heightScale: " + metadata.map(function (part) { return part.targetName + " = " + numberText(part.heightScale); }).join("; ");
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
      refreshAvailability(); refreshMotionStatus(); updateTime(); refreshExpression(); refreshNode(); changed();
    }
    function reset() {
      adjustments = {}; nodeCompensations = {}; editingMethods = {}; meshConversions = {}; restoredCompensationReference = {}; body = { breastPreset: "loaded" }; skirtOverrides = {};
      accessoryUnclip = null; accessoryCorrections = {};
      clearHipDrafts();
      if (expressionPanel) expressionPanel.reset(true);
      if (physicsController) physicsController.reset();
      parts.forEach(function (part) { part.visible = part.fileVisible; part.userVisible = undefined; part.userChanged = false; });
      useSavedNodes = savedOperations.length > 0; element("viewer-saved-nodes").checked = useSavedNodes;
      savedParts.forEach(function (part) { part.enabled = true; if (part.input) part.input.checked = true; });
      setClip(defaultClip); refreshNode(); refreshExpression(); refreshSavedStatus();
    }
    function refreshSavedStatus() {
      var message = !savedOperations.length ? translate("No verified saved node settings are available.") :
        translate(useSavedNodes ? "Saved node settings are applied." : "Using the file's authored shape. Saved node settings are off.");
      if (savedOperations.length) message += " " + translate("Applied settings") + ": " + activeSavedOperations().length + " / " + savedOperations.length + ".";
      if (savedSkipped || savedMetadataWarnings.length) message += " " + translate("Unsupported or conflicting saved settings were skipped.") + (savedSkipped ? " (" + savedSkipped + ")" : "");
      element("viewer-saved-status").textContent = message;
      element("viewer-saved-status").classList.toggle("error", savedConflicts > 0 || savedMetadataWarnings.length > 0);
      element("viewer-saved-parts").hidden = !savedParts.length;
      savedParts.forEach(function (part) { if (part.title) part.title.textContent = translate(part.label) + " (" + part.operations.length + ")"; });
    }
    function refreshMotionStatus() {
      var text = translate(clipEntries.length ? "Play or pause a motion to inspect the model's pose." : bones.length || expressions.length ? "No compatible motion is available. You can adjust this model's bones and expressions." : "This model supports a static preview only.");
      if (currentClip && currentClip.partial || (info && info.animationWarnings || []).length) text += " " + translate("Some animation tracks could not be applied.");
      element("viewer-rig-status").textContent = text;
    }
    function updateLanguage() {
      if (element("viewer-editor-tabs")) element("viewer-editor-tabs").setAttribute("aria-label", translate("Body editing tools"));
      ["node", "mesh"].forEach(function (tool) { var count = element("viewer-editor-" + tool + "-count"); if (count) count.setAttribute("aria-label", translate(tool === "node" ? "Node edits" : "Mesh edits")); });
      element("viewer-pose-actions").setAttribute("aria-label", translate("Pose"));
      element("viewer-pose-basic").textContent = translate("Basic pose");
      element("viewer-pose-preview").textContent = translate("Posed view");
      element("viewer-pose-help").textContent = translate("No compatible preview motion is available.");
      var motion = element("viewer-motion"); motion.textContent = "";
      appendOption(motion, "", translate("Saved pose"));
      clipEntries.forEach(function (clip) {
        var label = (info && info.expressionCatalog && info.expressionCatalog.clips || []).filter(function (value) { return value.name === clip.name; })[0];
        appendOption(motion, clip.name, (clip.name === defaultClip ? translate("SIFAS costume preview") : label ? translate(label.label) : clip.name) + (clip.partial ? " · " + translate("Partially supported motion") : ""));
      }); motion.value = selectedClip;
      if (nodeEditor) nodeEditor.updateLanguage();
      if (expressionPanel) expressionPanel.updateLanguage();
      if (physicsController) physicsController.updateLanguage();
      var preset = element("viewer-breast-preset");
      if (preset) {
        preset.textContent = ""; appendOption(preset, "loaded", translate("No extra edits"));
        var control = bodyControl("breast");
        ["smaller", "stock", "larger"].forEach(function (group) {
          var entries = breastPresets().filter(function (value) { return value.group === group; });
          if (!entries.length) return;
          var holder = document.createElement("optgroup"); holder.label = translate(group === "smaller" ? "Below reference baseline" : group === "larger" ? "Above reference baseline" : "Reference baseline");
          entries.forEach(function (value) { appendOption(holder, value.id, translate(value.id === "stock" ? "Reference baseline" : value.label)); });
          preset.appendChild(holder);
        });
        preset.value = body.breastPreset;
      }
      element("viewer-rig-status").textContent = translate(clipEntries.length ? "Play or pause a motion to inspect the model's pose." :
        bones.length || expressions.length ? "No compatible motion is available. You can adjust this model's bones and expressions." : "This model supports a static preview only.");
      refreshMotionStatus(); updateTime(); refreshSavedStatus(); refreshExpression(); refreshAvailability();
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
    function posedBounds(visitVertex) {
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
          point.applyMatrix4(mesh.matrixWorld);
          box.expandByPoint(point);
          // Explicit framing can reuse this exact skin/morph evaluation. The
          // point is scratch storage: a visitor must copy any values it keeps.
          if (visitVertex) visitVertex(point, mesh, vertex);
        }
      });
      return box.isEmpty() ? null : box;
    }
    buildSavedParts();
    expressionPanel = window.ViewerExpressions.create({ THREE: THREE, translate: translate, nodes: nodes,
      channels: expressions, catalog: info && info.expressionCatalog || {},
      change: function () { evaluate(0); refreshBodyControls(); refreshNode(); changed(); } });
    nodeEditor = editing.createNodeEditor({ THREE: THREE, translate: translate, nodes: nodes, bones: bones, scaling: scaling,
      defaultFilter: options.editing && options.editing.available ? "tool" : "all", forTool: toolAccepts,
      value: function (id, adjusted) { return staticMap(adjusted)[id]; }, fileValues: fileValues, poseValue: function (id) { return snapshot(nodes[id]); }, flags: nodeFlags, savedEuler: savedEuler,
      savedEntries: function (id) {
        var active = activeSavedOperations();
        return savedOperations.filter(function (operation) { return operation.node === id; }).map(function (operation) {
          return { kind: operation.kind, value: operation.value, sourceEuler: operation.sourceEuler, applied: active.indexOf(operation) >= 0 };
        });
      },
      adjustment: function (id) { return adjustments[id]; }, onSelect: function (id) { selectedNode = id; if (options.onSelection) options.onSelection(); },
      compensation: function (id) { return { parent: compensationStatus(id), canEdit: effectiveMethod(id) === "mesh", incoming: automaticTargets.filter(function (target) { return target.node === id; }) }; },
      changeCompensation: function (id, value) {
        if (!compensationSelection(id) || !value || ["auto", "spine2", "spine1", "both"].indexOf(value.mode) < 0 || value.enabled && effectiveMethod(id) !== "mesh") return;
        nodeCompensations[id] = { enabled: !!value.enabled, mode: value.mode };
        evaluate(0); refreshNode(); changed();
      },
      change: function (id, value) {
        if (value) { adjustments[id] = value; methodForNewEdit(id); }
        else { delete adjustments[id]; delete nodeCompensations[id]; delete editingMethods[id]; delete meshConversions[id]; }
        evaluate(0); refreshBodyControls(); changed();
      } });
    ["node", "mesh"].forEach(function (tool) {
      if (!element("viewer-editor-" + tool + "-tab")) return;
      listen("viewer-editor-" + tool + "-tab", "click", function () { setEditorGroup(tool); });
      listen("viewer-editor-" + tool + "-tab", "keydown", function (event) {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(event.key) < 0) return;
        event.preventDefault();
        var next = event.key === "Home" ? "node" : event.key === "End" ? "mesh" : tool === "node" ? "mesh" : "node";
        setEditorGroup(next); element("viewer-editor-" + next + "-tab").focus();
      });
    });
    setEditorGroup("node");
    listen("viewer-breast-preset", "change", function () { chooseBreastProfile(this.value); });
    listen("viewer-breast-reset", "click", function () { if (!this.disabled) chooseBreastProfile("loaded"); });
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
    percentageKinds.forEach(function (kind) {
      listen("viewer-" + kind + "-apply", "click", function () { if (!this.disabled) setPercentage(kind); });
      listen("viewer-" + kind + "-number", "input", function () {
        this.dataset.viewerPercentageDirty = "true";
        var value = Number(this.value), invalid = !this.value.trim() || !isFinite(value) || value < Number(this.min) || value > Number(this.max);
        this.setCustomValidity(invalid ? translate("Enter a percentage between 20 and 250.") : "");
        if (invalid) this.setAttribute("aria-invalid", "true"); else this.removeAttribute("aria-invalid");
        changed();
      });
      listen("viewer-" + kind + "-reset", "click", function () { if (!this.disabled) undoPercentage(kind); });
    });
    hipsInputs().forEach(function (input) {
      listen(input.id, "input", function () {
        if (this.disabled) return;
        this.dataset.viewerHipsDirty = "true"; validateHipInput(this); refreshHipAxes(); changed();
      });
    });
    listen("viewer-hips-apply", "click", function () { if (!this.disabled) applyHipAxes(); });
    listen("viewer-hips-reset", "click", function () { if (!this.disabled) undoHipAxes(); });
    listen("viewer-thighs-preset", "change", function () {
      var state = thighProfileState(), selected = this.value;
      element("viewer-thighs-preset-apply").disabled = !interactive || !authoringEnabled || disposed || !state.available ||
        !state.presets.some(function (preset) { return preset.id === selected; });
    });
    listen("viewer-thighs-preset-apply", "click", function () { if (!this.disabled) applyThighPreset(); });
    listen("viewer-skirt-apply", "click", function () { if (!this.disabled) setSkirt(); });
    listen("viewer-skirt-number", "input", function () { this.setCustomValidity(""); });
    listen("viewer-skirt-reset", "click", function () { if (!this.disabled) undoSkirt(); });
    listen("viewer-saved-nodes", "change", function () {
      useSavedNodes = this.checked && savedOperations.length > 0; evaluate(0); refreshSavedStatus(); refreshAvailability(); refreshNode(); changed();
    });
    listen("viewer-preview-reset", "click", reset);
    if (window.ViewerPhysics) physicsController = window.ViewerPhysics.create(root, options.editing && options.editing.physics || {}, {
      translate: translate, onChange: function () { evaluate(0); changed(); }
    });
    clearHipDrafts(); updateLanguage(); setClip(defaultClip); refreshNode(); refreshExpression();
    if (options.initializeNodeCards !== false) initializeNodeCards();

    function getAuthoringState() {
      // Source-authoring TRS comes from immutable file values and explicit
      // body edits. Never serialize record.base/frame: those contain animation.
      var baseline = storedFileMap(), desired = fileMap(), unsupported = [], edits = [];
      applyBodyPreset(function (id) { return desired[id]; });
      applyBody(function (id) { return desired[id]; });
      Object.keys(adjustments).forEach(function (id) { if (desired[id]) applyUser(desired[id], adjustments[id], id); });
      // Numeric steps control spinner increments, not the precision of Unity
      // file values or explicit edits. A fractional untouched TRS can be off
      // that grid while remaining a valid finite authoring value.
      var invalid = Array.prototype.some.call(document.querySelectorAll("#viewer-node-fields input, #viewer-skirt-number, .viewer-percentage-control input, #viewer-hips-card input"), function (input) {
        if (input.closest(".viewer-hips-control")) {
          // An invalid draft remains unresolved if an advanced method change
          // disables the dedicated fields. Only reset or an explicit valid
          // replacement clears it; untouched file values are never drafts.
          if (input.dataset.viewerHipsDirty !== "true") return false;
        } else if (input.disabled || input.closest(".viewer-percentage-control") && input.dataset.viewerPercentageDirty !== "true") return false;
        var validity = input.validity;
        return input.getAttribute("aria-invalid") === "true" || validity &&
          (validity.badInput || validity.customError || validity.rangeOverflow || validity.rangeUnderflow || validity.typeMismatch || validity.valueMissing);
      });
      if (invalid) unsupported.push("Correct the invalid editing values before saving.");
      if (physicsController && physicsController.invalid()) unsupported.push("Correct the invalid physics values before saving.");
      var savedEnabled = !savedOperations.length || useSavedNodes && savedParts.every(function (part) { return part.enabled; });
      if (!savedEnabled) unsupported.push("Turn saved file settings on before saving body changes.");
      if (savedConflicts || savedSkipped || savedMetadataWarnings.length) unsupported.push("Unsupported saved settings must be resolved before saving body changes.");
      bones.forEach(function (bone) {
        var id = bone.id, initial = baseline[id], current = desired[id];
        if (!initial || !current) return;
        var edit = { node: Number(id), method: editingMethods[id] || "auto", compensate: false };
        var scale = current.scale.toArray(), position = current.position.toArray();
        if (differentVector(initial.scale.toArray(), scale, false) || meshConversions[id]) edit.scale = scale;
        if (differentVector(initial.position.toArray(), position, false)) edit.position = position;
        if (differentVector(initial.quaternion.toArray(), current.quaternion.toArray(), true)) {
          edit.rotation = editing.quaternionUI(THREE, current.quaternion, savedEuler(id));
          var manual = adjustments[id];
          if (manual && manual.rotation) manual.rotation.forEach(function (value, axis) { if (typeof value === "number") edit.rotation[axis] = value; });
        }
        var compensation = nodeCompensations[id] && nodeCompensations[id].enabled && edit.scale ? compensationStatus(id) : null;
        if (compensation && compensation.enabled && edit.scale) {
          if (compensation.state === "unavailable") unsupported.push(compensation.reason || "Child compensation is unavailable.");
          edit.compensate = true; edit.compensationTargets = compensation.targets.map(function (target) { return Number(target.node); });
          if (edit.method === "node") unsupported.push("Child compensation requires a mesh scale edit.");
        }
        if (edit.method === "auto" && (edit.position || edit.rotation)) unsupported.push("Choose a save method explicitly for position or rotation edits; MV compatibility differs by motion.");
        if (edit.scale || edit.position || edit.rotation) edits.push(edit);
      });
      if (options.editing && options.editing.available) {
        var writableNodes = {};
        (options.editing.nodes || []).forEach(function (entry) { writableNodes[String(entry.node)] = true; });
        if (edits.some(function (edit) { return !writableNodes[String(edit.node)]; })) unsupported.push("Some edited bones are read-only. Open their original model file to save them.");
        (options.editing.nodes || []).forEach(function (target) {
          var edit = edits.filter(function (entry) { return entry.node === target.node; })[0];
          if (edit && edit.method === "auto" && !edit.compensate && target.recommendedMethod === "choose") unsupported.push("Choose a save method for unverified body nodes in advanced settings.");
          if (edit && edit.position && target.positionWritable === false) unsupported.push("Edit an attached model's original position in its own source model file.");
        });
      }
      var state = { version: 1, edits: edits, savedSettingsEnabled: savedEnabled,
        unsupported: unsupported.filter(function (message, index, values) { return values.indexOf(message) === index; }) };
      if (physicsController && physicsController.getEdits().length) state.physics = physicsController.getEdits();
      if (accessoryUnclip) state.accessoryUnclip = Object.assign({}, accessoryUnclip);
      if (edits.some(function (edit) { return edit.compensate; })) {
        var reference = fileMap(), writable = {};
        applyBodyPreset(function (id) { return reference[id]; });
        applyBody(function (id) { return reference[id]; });
        ((options.editing || {}).nodes || []).forEach(function (entry) { writable[String(entry.node)] = true; });
        state.compensationReference = bones.filter(function (bone) { return writable[bone.id] && reference[bone.id]; }).map(function (bone) {
          var value = restoredCompensationReference[bone.id] || reference[bone.id];
          return { node: Number(bone.id), scale: value.scale.toArray(), position: value.position.toArray(),
            rotation: editing.quaternionUI(THREE, value.quaternion, savedEuler(bone.id)) };
        });
      }
      return state;
    }
    function restoreAuthoringState(state, restoreOptions) {
      if (!state || state.version !== 1 || !Array.isArray(state.edits) || state.edits.length > bones.length || state.savedSettingsEnabled !== true) {
        throw new Error("The body edit recipe is invalid.");
      }
      var next = {}, methods = {}, compensations = {}, seen = {};
      var restoredAccessory = checkedAccessory(state.accessoryUnclip);
      state.edits.forEach(function (edit) {
        var id = String(edit.node);
        if (!Number.isInteger(edit.node) || !authoredNodes[id] || seen[id] || ["auto", "node", "mesh"].indexOf(edit.method) < 0) throw new Error("The body edit recipe is invalid.");
        seen[id] = true;
        var value = { mode: "absolute_axes", scale: [null, null, null], position: [null, null, null], rotation: [null, null, null] };
        ["scale", "position", "rotation"].forEach(function (kind) {
          if (edit[kind] === undefined) return;
          if (!Array.isArray(edit[kind]) || edit[kind].length !== 3 || !edit[kind].every(function (number) {
            return typeof number === "number" && isFinite(number) && Math.abs(number) <= 1000000 && (kind !== "scale" || Math.abs(number) >= 1e-8);
          })) throw new Error("The body edit recipe is invalid.");
          value[kind] = edit[kind].slice();
        });
        if (editing.adjustmentEmpty(value)) throw new Error("The body edit recipe is invalid.");
        if (edit.compensate) {
          var choice = compensationSelection(id), targets = edit.compensationTargets;
          if (!choice || !Array.isArray(targets)) throw new Error("The body edit recipe is invalid.");
          var mode = ["auto", "spine2", "spine1", "both"].filter(function (candidate) {
            var resolved = compensationTargets({ bone: choice.bone, enabled: true, mode: candidate });
            var actual = resolved.bones.map(function (bone) { return Number(bone.id); }).sort(function (a, b) { return a - b; });
            return !resolved.reason && JSON.stringify(actual) === JSON.stringify(targets.slice().sort(function (a, b) { return a - b; }));
          })[0];
          if (!mode) throw new Error("The body edit recipe is invalid.");
          compensations[id] = { enabled: true, mode: mode };
        }
        next[id] = value; methods[id] = edit.method;
      });
      var references = {};
      (state.compensationReference || []).forEach(function (entry) {
        var id = String(entry.node);
        if (!Number.isInteger(entry.node) || !authoredNodes[id] || references[id] || !["scale", "position", "rotation"].every(function (kind) {
          return Array.isArray(entry[kind]) && entry[kind].length === 3 && entry[kind].every(function (value) {
            return typeof value === "number" && isFinite(value) && Math.abs(value) <= 1000000 && (kind !== "scale" || Math.abs(value) >= 1e-8);
          });
        })) throw new Error("The body edit recipe is invalid.");
        references[id] = { scale: new THREE.Vector3().fromArray(entry.scale), position: new THREE.Vector3().fromArray(entry.position), quaternion: editing.uiQuaternion(THREE, entry.rotation) };
      });
      if (physicsController) physicsController.restore(state.physics || []);
      else if (state.physics && state.physics.length) throw new Error("The model has no compatible physics editor.");
      adjustments = next; editingMethods = methods; nodeCompensations = compensations; restoredCompensationReference = references; meshConversions = {};
      accessoryUnclip = restoredAccessory; accessoryCorrections = {};
      clearHipDrafts();
      var baseline = storedFileMap();
      state.edits.forEach(function (edit) {
        var id = String(edit.node);
        if (edit.method === "mesh" && edit.scale && baseline[id] && !differentVector(baseline[id].scale.toArray(), edit.scale, false)) meshConversions[id] = true;
      });
      body = { breastPreset: "loaded" }; skirtOverrides = {};
      useSavedNodes = savedOperations.length > 0; element("viewer-saved-nodes").checked = useSavedNodes;
      savedParts.forEach(function (part) { part.enabled = true; if (part.input) part.input.checked = true; });
      evaluate(0); refreshSavedStatus(); refreshBodyControls(); refreshNode();
      if (!restoreOptions || restoreOptions.initializeNodeCards !== false) initializeNodeCards();
      changed();
    }
    function motionScaleTargets() {
      if (!currentClip || !currentClip.animation) return [];
      var result = [];
      currentClip.animation.tracks.forEach(function (track) {
        if (!/\.scale$/.test(track.name)) return;
        bones.forEach(function (bone) {
          if (track.name === bone.object.name + ".scale" && result.indexOf(bone.id) < 0) result.push(bone.id);
        });
      });
      return result;
    }
    function checkedAccessory(value) {
      if (value === undefined || value === null) return null;
      if (typeof value !== "object" || Array.isArray(value) || Object.keys(value).some(function (key) {
        return ["strength", "overlap", "closeGaps"].indexOf(key) < 0;
      })) throw new Error("The accessory correction settings are invalid.");
      var result = { strength: value.strength === undefined ? 1 : value.strength,
        overlap: value.overlap === undefined ? .15 : value.overlap,
        closeGaps: value.closeGaps === undefined ? false : value.closeGaps };
      if (typeof result.strength !== "number" || !isFinite(result.strength) || result.strength < 0 || result.strength > 3 ||
          typeof result.overlap !== "number" || !isFinite(result.overlap) || result.overlap < 0 || result.overlap > 1 ||
          typeof result.closeGaps !== "boolean") throw new Error("The accessory correction settings are invalid.");
      return result;
    }
    return {
      getAuthoringState: getAuthoringState,
      restoreAuthoringState: restoreAuthoringState,
      getAccessoryUnclip: function () { return accessoryUnclip && Object.assign({}, accessoryUnclip); },
      setAccessoryUnclip: function (value) {
        var next = checkedAccessory(value);
        if (JSON.stringify(next) === JSON.stringify(accessoryUnclip)) return;
        accessoryUnclip = next; accessoryCorrections = {}; evaluate(0); changed();
      },
      setAccessoryCorrections: function (values) {
        if (!Array.isArray(values) || values.length > bones.length) throw new Error("The accessory preview response is invalid.");
        var next = {};
        values.forEach(function (value) {
          var id = value && String(value.node);
          if (!value || !Number.isInteger(value.node) || !authoredNodes[id] || next[id] ||
              !Array.isArray(value.delta) || value.delta.length !== 3 || !value.delta.every(function (number) {
                return typeof number === "number" && isFinite(number) && Math.abs(number) <= 1000000;
              })) throw new Error("The accessory preview response is invalid.");
          next[id] = new THREE.Vector3().fromArray(value.delta);
        });
        if (!accessoryUnclip) next = {};
        var ids = Object.keys(next), previousIds = Object.keys(accessoryCorrections);
        if (ids.length === previousIds.length && ids.every(function (id) {
          return accessoryCorrections[id] && next[id].equals(accessoryCorrections[id]);
        })) return;
        accessoryCorrections = next; evaluate(0); changed();
      },
      setEditingMethod: function (id, method) {
        id = String(id);
        if (!authoredNodes[id] || ["auto", "node", "mesh"].indexOf(method) < 0) throw new Error("Choose a valid body save method.");
        editingMethods[id] = method;
        if (method === "mesh") meshConversions[id] = true; else delete meshConversions[id];
        refreshNode(); refreshBodyControls(); changed();
      },
      setEditorGroup: setEditorGroup,
      setMotionTimeline: function (descriptor) {
        if (!window.ViewerMotionTimeline || !descriptor || descriptor.version !== 2) throw new Error("The game motion timeline is unavailable.");
        var name = "game-timeline:" + String(descriptor.category) + ":" + String(descriptor.motion) + ":" + String(descriptor.performerPosition || 1);
        var existing = clipEntries.filter(function (entry) { return entry.name === name; })[0];
        if (!existing) {
          all.forEach(function (record) { restore(record.object, record.authored); });
          var timeline = window.ViewerMotionTimeline.create(root, clips, info, descriptor);
          if (!timeline.compatibleSegments) { evaluate(0); throw new Error(translate("No compatible motion is available. You can adjust this model's bones and expressions.")); }
          existing = { name: name, label: descriptor.label || name, animation: null, timeline: timeline,
            duration: timeline.duration, loop: descriptor.category !== "voice", partial: timeline.warnings.length > 0, visibility: [] };
          clipEntries.push(existing);
        }
        updateLanguage(); setClip(name);
        return { clipName: name, warnings: existing.timeline.warnings.slice() };
      },
      setEvaluationMode: function (mode) {
        if (["authoring", "animation"].indexOf(mode) < 0 || mode === evaluationMode) return;
        if (mode === "authoring") {
          releaseAutomaticMatrices();
          all.forEach(function (record) { restore(record.object, record.authored); });
          if (mixer) mixer.update(0);
          replayAnimationTracks();
          all.forEach(function (record) { capture(record.object, record.base); });
        }
        evaluationMode = mode; evaluate(0); refreshNode(); changed();
      },
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
      setAuthoringEnabled: function (value) { if (!!value !== authoringEnabled) { authoringEnabled = !!value; refreshAvailability(); } },
      updateLanguage: updateLanguage,
      getBounds: posedBounds,
      getPlaybackState: function () { return { selectedClip: selectedClip, playing: playing, time: currentTime(), duration: duration() }; },
      getPartVisibility: function (object) { var part = parts.filter(function (item) { return item.object === object; })[0]; return part ? { fileVisible: part.fileVisible, selected: part.visible, userVisible: part.userVisible, userChanged: part.userChanged, visible: part.object.visible } : null; },
      reset: reset,
      dispose: function () { disposed = true; playing = false; releaseAutomaticMatrices(); root.updateMatrixWorld(true); refreshAvailability(); events.forEach(function (remove) { remove(); }); if (nodeEditor) nodeEditor.dispose(); if (expressionPanel) expressionPanel.dispose(); if (physicsController) physicsController.dispose(); if (mixer) { mixer.stopAllAction(); mixer.uncacheRoot(root); } },
      getState: function () {
        var values = bones.map(function (bone) { return { node: bone.id, name: bone.name, position: bone.object.position.toArray(), quaternion: bone.object.quaternion.toArray(), scale: bone.object.scale.toArray() }; });
        return { available: !!bones.length, authoringEnabled: authoringEnabled, editorGroup: editorGroup, meshConversions: Object.assign({}, meshConversions), bones: values, evaluation: { mode: evaluationMode, scaleTargets: motionScaleTargets(), hasMotion: !!currentClip }, editingMethods: Object.assign({}, editingMethods), restoredCompensationReference: Object.keys(restoredCompensationReference).length, clipNames: clipEntries.map(function (clip) { return clip.name; }), selectedClip: selectedClip, defaultClip: defaultClip,
          accessoryUnclip: accessoryUnclip && Object.assign({}, accessoryUnclip), accessoryCorrectedAnchors: Object.keys(accessoryCorrections).length,
          playing: playing, time: currentTime(), duration: duration(), visibilityTracks: currentClip ? currentClip.visibility.length : 0,
          physics: physicsController ? physicsController.getState() : null,
          parts: parts.map(function (part) { return { name: part.object.name, node: part.object.userData.elichika_node, fileVisible: part.fileVisible, selected: part.visible,
            userVisible: part.userVisible, userChanged: part.userChanged, visible: part.object.visible }; }),
          expressions: expressions.map(function (value) { return { key: value.key, name: value.name, weight: value.object.morphTargetInfluences[value.index] }; }),
          bodyControls: { hips: hipsState(), thighs: percentageState("thighs"), waist: percentageState("waist") }, thighProfile: thighProfileState(),
          body: { breastPreset: body.breastPreset, skirtMode: Object.keys(skirtOverrides).length ? "absolute" : "file" }, skirtValues: skirtValues(), breastProfile: breastProfile(), heightMode: "saved_settings_only", scaling: scaling,
          nodeAdjustments: JSON.parse(JSON.stringify(adjustments)), selectedNode: selectedNode,
          nodeCompensations: JSON.parse(JSON.stringify(nodeCompensations)),
          compensation: { selected: selectedNode ? compensationStatus(selectedNode) : null,
            parents: Object.keys(compensationStatuses).map(function (id) { return compensationStatuses[id]; }), targets: automaticTargets.slice() },
          nodeValues: selectedNode ? editingValues(selectedNode) : null,
          nodeFileValues: selectedNode ? fileValues(selectedNode) : null,
          expressionPanel: expressionPanel ? expressionPanel.getState() : null, expressionLimits: expressionLimits(),
          savedNodes: { available: savedOperations.length > 0, enabled: useSavedNodes, applied: activeSavedOperations().length,
            skipped: savedSkipped, conflicts: savedConflicts, metadataWarnings: savedMetadataWarnings.slice(), operations: JSON.parse(JSON.stringify(savedOperations)),
            groups: savedParts.map(function (part) { return { id: part.id, label: translate(part.label), enabled: part.enabled, nodes: part.nodes.slice(), settings: part.operations.length }; }) } };
      }
    };
  }
  window.ViewerRig = { create: create };
}());
