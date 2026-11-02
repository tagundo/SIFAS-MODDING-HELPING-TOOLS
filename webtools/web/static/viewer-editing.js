/* Viewer-only editing helpers. Original Unity data and authored TRS stay intact. */
(function () {
  "use strict";
  var AXES = ["x", "y", "z"];
  function finite(value, fallback) { value = Number(value); return isFinite(value) ? value : fallback; }
  function near(a, b) { return Math.abs(a - b) < 1e-7; }
  // Unity TRS uses float32. Keep runtime precision, but hide binary rounding
  // noise in the editor (for example, 1.3f must read as 130%, not 129.999995%).
  function format(value) { return String(Number(value.toPrecision(7))); }
  function clone(value) { return { position: value.position.clone(), quaternion: value.quaternion.clone(), scale: value.scale.clone() }; }
  function curveValue(control, x) {
    var knots = control.curve || [], domain = control.curveDomain || {};
    if (!isFinite(x) || x < domain.minX - 1e-8 || x >= domain.maxX || knots.length < 2) return null;
    for (var index = 1; index < knots.length; index += 1) {
      var left = knots[index - 1], right = knots[index];
      if (x <= right[0]) {
        var t = (x - left[0]) / (right[0] - left[0]);
        return left.map(function (value, axis) { return value + (right[axis] - value) * t; });
      }
    }
    return null;
  }
  function breastFactors(control, x, percent) {
    if (near(percent, 100)) return [1, 1, 1];
    var before = curveValue(control, x), after = curveValue(control, x * percent / 100);
    return before && after ? after.map(function (value, axis) { return value / before[axis]; }) : null;
  }
  function breastRange(control, targets) {
    var domain = control.curveDomain || {}, low = finite(control.min, 25), high = finite(control.max, 200);
    for (var index = 0; index < targets.length; index += 1) {
      var x = targets[index].scale.x;
      if (!curveValue(control, x)) return null;
      low = Math.max(low, Math.ceil(domain.minX / x * 100 - 1e-7));
      high = Math.min(high, Math.ceil(domain.maxX / x * 100) - 1);
    }
    return low <= 100 && high >= 100 ? { min: low, max: high } : null;
  }
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
    return { scale: value.scale.toArray().map(function (part) { return part * 100; }),
      position: [-value.position.x, value.position.y, value.position.z],
      rotation: quaternionUI(THREE, value.quaternion, savedEuler) };
  }
  function adjustmentEmpty(value) {
    return !value || value.scale.every(function (part) { return near(part, 1); }) &&
      value.position.every(function (part) { return near(part, 0); }) &&
      (value.quaternion ? Math.abs(value.quaternion[3]) > 1 - 1e-10 :
        value.rotation.every(function (part) { return near(part, 0); }));
  }

  function createNodeEditor(options) {
    var THREE = options.THREE, translate = options.translate, bones = options.bones;
    var selected = "", enabled = true, disposed = false, events = [], fields = {}, list = document.getElementById("viewer-node");
    var search = document.getElementById("viewer-node-search"), filter = document.getElementById("viewer-node-filter");
    var shortcutButtons = {}, changeButtons = {};
    var ownedLists = [document.getElementById("viewer-node-shortcuts"), document.getElementById("viewer-node-change-list")];
    ownedLists.forEach(function (container) { if (container) container.textContent = ""; });
    if (search) search.value = "";
    if (filter) filter.value = "all";
    var labels = { Head: "Head", Head_Hair: "Hair", Neck_Hair: "Back hair", Spine: "Waist and torso",
      Spine2: "Upper body", HipsSize: "Hip size", BreastSize: "Breast size", Move: "Height",
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
      return (options.scaling.recommendedTargets || []).some(function (item) { return String(item.node) === bone.id; });
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
        var category = mode === "all" || mode === "saved" && state.saved ||
          mode === "changed" && (state.modified || state.body || state.fileChanged || state.expression) ||
          mode === "frequent" && isFrequent(bone);
        return category && (!term || (friendly(bone) + " " + bone.name).toLowerCase().indexOf(term) >= 0);
      });
      // A value can become unchanged halfway through typing. Do not silently
      // retarget the still-focused XYZ input to the next filtered bone.
      if (holder.contains(document.activeElement) && selected && !visible.some(function (bone) { return bone.id === selected; })) {
        var pinned = bones.filter(function (bone) { return bone.id === selected; })[0];
        if (pinned) visible.unshift(pinned);
      }
      list.textContent = "";
      visible.forEach(function (bone) {
        var option = document.createElement("option"); option.value = bone.id; option.textContent = optionLabel(bone); list.appendChild(option);
      });
      if (!visible.some(function (bone) { return bone.id === selected; })) {
        selected = visible.length ? visible[0].id : ""; options.onSelect(selected);
      }
      if (!visible.length) { var empty = document.createElement("option"); empty.textContent = translate("No matching bones"); empty.value = ""; list.appendChild(empty); }
      list.value = selected; list.disabled = !enabled || !visible.length;
      if (search) search.disabled = !enabled || !bones.length;
      if (filter) filter.disabled = !enabled || !bones.length;
      var shortcuts = document.getElementById("viewer-node-shortcuts"), changes = document.getElementById("viewer-node-change-list");
      updateButtons(shortcuts, shortcutButtons, bones.filter(isFrequent), "No recommended bones in this model.");
      updateButtons(changes, changeButtons, bones.filter(function (bone) {
        var value = flags(bone.id); return value.modified || value.body || value.fileChanged || value.expression;
      }), "No changed bones.");
    }
    function read(kind, axis, input) {
      if (!selected || !enabled || !input.value.trim() || !isFinite(Number(input.value))) return;
      var value = Number(input.value), baseline = options.value(selected, false), current = options.value(selected, true);
      if (kind === "scale" && Math.abs(baseline.scale.getComponent(axis)) < 1e-8) return;
      var desired = toUI(THREE, current, options.savedEuler(selected));
      if (kind === "scale" && Math.abs(value) < .001) return;
      desired[kind][axis] = Math.max(Number(input.min), Math.min(Number(input.max), value));
      var delta = options.adjustment(selected) || { scale: [1, 1, 1], position: [0, 0, 0], rotation: [0, 0, 0] };
      delta = JSON.parse(JSON.stringify(delta));
      if (kind === "scale") delta.scale = desired.scale.map(function (part, index) {
        var base = baseline.scale.getComponent(index);
        return Math.abs(base) < 1e-8 ? 1 : part / 100 / base;
      });
      if (kind === "position") delta.position = desired.position.map(function (part, index) {
        return (index === 0 ? -part : part) - baseline.position.getComponent(index);
      });
      if (kind === "rotation") {
        var quaternion = baseline.quaternion.clone().invert().multiply(uiQuaternion(THREE, desired.rotation)).normalize();
        delta.quaternion = quaternion.toArray(); delta.rotation = quaternionUI(THREE, quaternion);
      }
      if (!delta.scale.concat(delta.position, delta.rotation, delta.quaternion || []).every(function (part) { return isFinite(part); })) return;
      options.change(selected, adjustmentEmpty(delta) ? null : delta);
      refresh(false);
    }
    function refresh(force) {
      if (disposed) return;
      refreshLists();
      var exists = !!selected, baselineValue = exists ? options.value(selected, false) : null;
      var value = exists ? toUI(THREE, options.value(selected, true), options.savedEuler(selected)) : null;
      Object.keys(fields).forEach(function (kind) {
        fields[kind].forEach(function (input, axis) {
          input.disabled = !enabled || !exists || kind === "scale" && Math.abs(baselineValue.scale.getComponent(axis)) < 1e-8;
          if (!exists) { input.value = ""; return; }
          if (force || document.activeElement !== input) input.value = format(value[kind][axis]);
        });
      });
      document.getElementById("viewer-node-reset").disabled = !enabled || !exists || !flags(selected).modified;
      var status = document.getElementById("viewer-node-status"), baseline = document.getElementById("viewer-node-baseline");
      if (status) status.textContent = exists ? optionLabel(bones.filter(function (bone) { return bone.id === selected; })[0]) : translate("Choose a bone to edit.");
      if (status && exists && baselineValue.scale.toArray().some(function (part) { return Math.abs(part) < 1e-8; }))
        status.textContent += " · " + translate("Zero-scale axes cannot be edited safely.");
      if (baseline) {
        baseline.textContent = "";
        if (exists) {
          var source = toUI(THREE, options.value(selected, false), options.savedEuler(selected));
          (options.savedEntries ? options.savedEntries(selected) : []).forEach(function (entry) {
            var values = entry.kind === "scale" ? entry.value.map(function (value) { return value * 100; }) :
              entry.kind === "position" ? [-entry.value[0], entry.value[1], entry.value[2]] :
              entry.sourceEuler || quaternionUI(THREE, new THREE.Quaternion().fromArray(entry.value));
            var line = document.createElement("div");
            var label = entry.kind === "scale" ? "Scale (%)" : entry.kind === "position" ? "Position (model units)" : "Rotation (degrees)";
            line.textContent = translate("File saved value") + " · " + translate(label) + ": " + values.map(format).join(" / ") +
              (entry.applied ? "" : " · " + translate("Not applied"));
            baseline.appendChild(line);
          });
          [["scale", "Scale (%)"], ["rotation", "Rotation (degrees)"], ["position", "Position (model units)"]].forEach(function (item) {
            var line = document.createElement("div");
            line.textContent = translate("File and body baseline") + " · " + translate(item[1]) + ": " + source[item[0]].map(format).join(" / ");
            baseline.appendChild(line);
          });
        }
      }
    }
    var holder = document.getElementById("viewer-node-fields"); holder.textContent = "";
    [["scale", "Scale (%)", -1000, 1000, .1], ["rotation", "Rotation (degrees)", -720, 720, 1],
      ["position", "Position (model units)", -10, 10, .001]].forEach(function (definition) {
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
      }); holder.appendChild(row);
    });
    listen(list, "change", function () { select(this.value, false); });
    listen(search, "input", function () { refresh(true); });
    listen(filter, "change", function () { refresh(true); });
    listen(document.getElementById("viewer-node-reset"), "click", function () { if (selected) { options.change(selected, null); refresh(true); } });
    selected = bones.some(function (bone) { return plainName(bone) === "Head"; }) ?
      bones.filter(function (bone) { return plainName(bone) === "Head"; })[0].id : bones.length ? bones[0].id : "";
    options.onSelect(selected);
    return { refresh: refresh, select: select, getSelected: function () { return selected; },
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
        disposed = true; enabled = false;
        events.forEach(function (remove) { remove(); }); holder.textContent = "";
        ownedLists.forEach(function (container) { if (container) container.textContent = ""; });
        shortcutButtons = {}; changeButtons = {};
      }
    };
  }
  window.ViewerEditing = { clone: clone, curveValue: curveValue, breastFactors: breastFactors, breastRange: breastRange,
    uiQuaternion: uiQuaternion, quaternionUI: quaternionUI, toUI: toUI, adjustmentEmpty: adjustmentEmpty,
    createNodeEditor: createNodeEditor };
}());
