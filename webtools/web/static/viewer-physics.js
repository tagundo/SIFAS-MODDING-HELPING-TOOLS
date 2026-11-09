/* Serialized SwingBone/SwingCollider controls with an optional spring preview. */
(function () {
  "use strict";
  var labels = {
    "Physics preview": ["물리 미리보기", "物理プレビュー"],
    "Apply SwingBone": ["스윙본 적용", "SwingBoneを適用"],
    "Apply SwingCollider": ["스윙 콜라이더 적용", "SwingColliderを適用"],
    "Show colliders": ["콜라이더 표시", "コライダーを表示"],
    "Breast dynamics": ["가슴 Dynamic", "胸のダイナミクス"],
    "Thigh SwingCollider": ["허벅지 SwingCollider", "太もものSwingCollider"],
    "Other physics components": ["기타 물리 컴포넌트", "その他の物理コンポーネント"],
    "Tool recommendations": ["기존 도구 추천 값", "既存ツールの推奨値"],
    "Loaded values": ["불러온 값", "読み込み時の値"],
    "Softer": ["매우 부드럽게", "より柔らかく"], "Soft": ["부드럽게", "柔らかく"], "Firm": ["단단하게", "硬く"],
    "Undo physics edits": ["물리 편집 되돌리기", "物理編集を元に戻す"],
    "No compatible physics components.": ["호환되는 물리 컴포넌트가 없습니다.", "対応する物理コンポーネントがありません。"],
    "Physics preview is approximate. Play a motion to inspect it; saved copies retain the Unity physics values.": ["물리 미리보기는 근사 시뮬레이션입니다. 모션을 재생해 확인하세요. 저장한 복사본에는 Unity 물리 값이 적용됩니다.", "物理プレビューは近似です。モーションを再生して確認してください。保存したコピーにはUnityの物理値が適用されます。"],
    "Collider recommendations keep each original radius and offset; capsule ends can have different values.": ["콜라이더 권장 값은 각 원본의 반경과 오프셋입니다. 캡슐 양끝의 값은 서로 다를 수 있습니다.", "コライダーの推奨値は各原本の半径とオフセットです。カプセルの両端は異なる値を持つ場合があります。"],
    "Correct the invalid physics values before saving.": ["저장하기 전에 잘못된 물리 값을 수정하세요.", "保存する前に無効な物理値を修正してください。"]
  };
  function create(root, catalog, options) {
    var THREE = window.THREE, components = catalog && catalog.components || [], edits = {}, controls = [], regions = [];
    var nodes = {}, interactive = true, writable = true, disposed = false;
    var applyBones = false, applyColliders = false, showColliders = false, spheres = [], springs = [], helperGroup = new THREE.Group();
    var base = {}, lang = function () { return document.documentElement.lang || "en"; };
    helperGroup.userData.viewerHelper = true; root.add(helperGroup);
    root.traverse(function (object) { if (object.userData && object.userData.elichika_node !== undefined) nodes[String(object.userData.elichika_node)] = object; });
    function t(key) { var pair = labels[key], index = lang() === "ko" ? 0 : lang() === "ja" ? 1 : -1; return pair && index >= 0 ? pair[index] : options.translate(key); }
    function element(tag, text, parent) { var el = document.createElement(tag); if (text) { el.textContent = t(text); el.dataset.physicsLabel = text; } if (parent) parent.appendChild(el); return el; }
    function region(parent, title) { if (!parent) return null; var box = element("details", null, parent); box.className = "viewer-save-advanced viewer-physics-region"; element("summary", title, box); regions.push(box); return box; }
    function current(record) { return Object.assign({}, record.values, edits[record.id] || {}); }
    function notify() { if (!disposed && options.onChange) options.onChange(); }
    function validField(record, name, value) {
      if (Array.isArray(record.values[name])) return Array.isArray(value) && value.length === 3 && value.every(function (v) { return typeof v === "number" && isFinite(v) && Math.abs(v) <= (name === "offset" ? 10 : 180); });
      return typeof value === "number" && isFinite(value) && value >= 0 && value <= (name === "dragForce" ? 1 : 10);
    }
    function validValues(record, values) {
      if (!values || typeof values !== "object" || Array.isArray(values) || !Object.keys(values).length || Object.keys(values).some(function (name) { return record.values[name] === undefined || !validField(record, name, values[name]); })) return false;
      var value = Object.assign({}, record.values, values);
      return record.kind !== "bone" || value.lowRotationLimit.every(function (v, i) { return v <= value.highRotationLimit[i]; });
    }
    function updateEdit(record, values) {
      var changed = {};
      Object.keys(values).forEach(function (name) { if (JSON.stringify(values[name]) !== JSON.stringify(record.values[name])) changed[name] = values[name]; });
      if (Object.keys(changed).length) edits[record.id] = changed; else delete edits[record.id];
    }
    function refreshFields(selected) {
      controls.forEach(function (row) { if (!row.record || selected && selected.indexOf(row.record.id) < 0) return; var value = current(row.record)[row.name]; row.input.value = row.axis === undefined ? String(value) : String(value[row.axis]); row.input.setCustomValidity(""); row.input.removeAttribute("aria-invalid"); delete row.input.dataset.physicsDirty; });
    }
    function field(record, name, axis, parent) {
      var label = element("label", null, parent), text = element("span", null, label);
      text.textContent = name + (axis === undefined ? "" : " " + "XYZ"[axis]);
      var input = element("input", null, label), bound = name === "offset" ? 10 : 180;
      input.type = "number"; input.step = "any"; input.required = true;
      input.min = axis === undefined ? "0" : String(-bound); input.max = axis === undefined ? name === "dragForce" ? "1" : "10" : String(bound);
      input.dataset.physicsComponent = record.id; input.dataset.physicsField = name; if (axis !== undefined) input.dataset.physicsAxis = String(axis);
      input.setAttribute("aria-label", record.name + " " + text.textContent);
      controls.push({ input: input, record: record, name: name, axis: axis, write: true });
      input.addEventListener("input", function () {
        input.dataset.physicsDirty = "true";
        var values = Object.assign({}, current(record)), number = input.value.trim() ? Number(input.value) : NaN;
        if (axis === undefined) values[name] = number; else { values[name] = values[name].slice(); values[name][axis] = number; }
        var valid = validValues(record, values);
        input.setCustomValidity(valid ? "" : t("Correct the invalid physics values before saving."));
        if (valid) { input.removeAttribute("aria-invalid"); updateEdit(record, values); } else input.setAttribute("aria-invalid", "true");
        notify();
      });
    }
    function componentEditor(record, parent) {
      var box = element("details", null, parent); box.className = "viewer-save-advanced";
      element("summary", null, box).textContent = record.name + " · " + record.kind + (record.sibling ? " · capsule" : "");
      var original = element("p", null, box); original.className = "viewer-render-note";
      original.textContent = t("Loaded values") + ": " + Object.keys(record.values).map(function (key) { return key + "=" + (Array.isArray(record.values[key]) ? record.values[key].join("/") : record.values[key]); }).join(" · ");
      Object.keys(record.values).forEach(function (name) { if (Array.isArray(record.values[name])) [0, 1, 2].forEach(function (axis) { field(record, name, axis, box); }); else field(record, name, undefined, box); });
    }
    function toggle(key, name, callback, available, parent) {
      var label = element("label", null, parent), input = element("input", null, label); input.type = "checkbox"; input.id = name;
      element("span", key, label); input.disabled = !available;
      controls.push({ input: input, available: available, write: false });
      input.addEventListener("change", function () { callback(input.checked); springs.forEach(function (spring) { spring.tip = null; spring.previous = null; }); notify(); });
    }
    var pose = document.getElementById("viewer-adjustments"), preview = region(pose, "Physics preview");
    if (preview) {
      toggle("Apply SwingBone", "viewer-physics-bones", function (v) { applyBones = v; }, components.some(function (v) { return v.kind === "bone" && v.node !== null && v.enabled; }), preview);
      toggle("Apply SwingCollider", "viewer-physics-colliders", function (v) { applyColliders = v; }, components.some(function (v) { return v.kind === "collider" && v.node !== null && v.enabled; }), preview);
      toggle("Show colliders", "viewer-physics-show-colliders", function (v) { showColliders = v; helperGroup.visible = v; }, components.some(function (v) { return v.kind === "collider" && v.node !== null; }), preview);
      var note = element("p", "Physics preview is approximate. Play a motion to inspect it; saved copies retain the Unity physics values.", preview); note.className = "viewer-render-note";
      if (!components.length) element("p", "No compatible physics components.", preview);
    }
    [["breast", "viewer-breast-card", "Breast dynamics"], ["thighs", "viewer-thighs-card", "Thigh SwingCollider"], ["other", "viewer-body-adjustments", "Other physics components"]].forEach(function (group) {
      var records = components.filter(function (r) { return r.group === group[0]; }); if (!records.length) return;
      var parent = document.getElementById(group[1]), container = region(parent && (parent.querySelector(".viewer-card-content") || parent), group[2]);
      if (!container) return;
      if (group[0] === "breast" && records.some(function (r) { return r.kind === "bone"; })) {
        var label = element("label", null, container); element("span", "Tool recommendations", label);
        var select = element("select", null, label); select.id = "viewer-physics-breast-preset";
        var original = element("option", "Loaded values", select); original.value = "";
        (catalog.presets || []).forEach(function (preset) { var option = element("option", null, select); option.value = preset.id; option.textContent = t(preset.label) + " (" + preset.stiffnessForce + " / " + preset.dragForce + ")"; });
        controls.push({ input: select, write: true });
        select.addEventListener("change", function () { var preset = (catalog.presets || []).filter(function (p) { return p.id === select.value; })[0]; var selected = records.filter(function (r) { return r.kind === "bone"; }); selected.forEach(function (r) { var v = current(r); ["stiffnessForce", "dragForce"].forEach(function (name) { v[name] = preset ? preset[name] : r.values[name]; }); updateEdit(r, v); }); refreshFields(selected.map(function (r) { return r.id; })); notify(); });
        element("p", null, container).textContent = "sifas_breast_tuner.py";
      }
      if (group[0] === "thighs") { var note = element("p", "Collider recommendations keep each original radius and offset; capsule ends can have different values.", container); note.className = "viewer-render-note"; }
      records.forEach(function (record) { componentEditor(record, container); });
      var reset = element("button", "Undo physics edits", container); reset.type = "button"; controls.push({ input: reset, write: true });
      reset.addEventListener("click", function () { records.forEach(function (r) { delete edits[r.id]; }); refreshFields(records.map(function (r) { return r.id; })); notify(); });
    });
    components.forEach(function (record) {
      var object = nodes[String(record.node)]; if (!object) return;
      base[record.id] = record;
      if (record.kind === "collider") {
        var geometry = new THREE.SphereGeometry(1, 12, 8), material = new THREE.MeshBasicMaterial({ color: 0x39a4dd, wireframe: true, depthTest: false, transparent: true, opacity: .5 });
        var helper = new THREE.Mesh(geometry, material); helper.userData.viewerHelper = true; helper.renderOrder = 1000; helperGroup.add(helper);
        spheres.push({ record: record, object: object, helper: helper });
      } else if (record.enabled) springs.push({ record: record, object: object, tip: null, previous: null, quaternion: object.quaternion.clone(), length: .08 });
    });
    helperGroup.visible = false; refreshFields();
    function colliderWorld(sphere) {
      var value = current(sphere.record), center = new THREE.Vector3(-value.offset[0], value.offset[1], value.offset[2]).applyMatrix4(sphere.object.matrixWorld);
      var scale = sphere.object.getWorldScale(new THREE.Vector3()), radius = value.radius * Math.max(Math.abs(scale.x), Math.abs(scale.y), Math.abs(scale.z));
      return { center: center, radius: radius };
    }
    function apply(delta) {
      if (disposed) return;
      root.updateMatrixWorld(true);
      var world = {};
      spheres.forEach(function (sphere) {
        var value = colliderWorld(sphere); world[sphere.record.id] = value;
        if (showColliders) { sphere.helper.position.copy(root.worldToLocal(value.center.clone())); var rs = root.getWorldScale(new THREE.Vector3()); sphere.helper.scale.set(value.radius / Math.abs(rs.x || 1), value.radius / Math.abs(rs.y || 1), value.radius / Math.abs(rs.z || 1)); }
      });
      if (!applyBones) return;
      delta = Math.max(0, Math.min(.05, Number(delta) || 0));
      springs.forEach(function (spring) {
        var object = spring.object, record = spring.record, values = current(record), origin = object.getWorldPosition(new THREE.Vector3());
        var child = object.children.filter(function (o) { return !o.userData.viewerHelper && o.position.lengthSq() > 1e-8; })[0];
        var local = child ? child.position.clone() : new THREE.Vector3(0, spring.length, 0);
        var rest = local.clone().applyMatrix4(object.matrixWorld), length = Math.max(.001, rest.distanceTo(origin));
        if (!spring.tip || !delta) { spring.tip = rest.clone(); spring.previous = rest.clone(); return; }
        var tip = spring.tip.clone(), velocity = tip.clone().sub(spring.previous).multiplyScalar(Math.pow(Math.max(0, 1 - values.dragForce), delta * 60));
        spring.previous.copy(tip); tip.add(velocity).lerp(rest, Math.min(1, values.stiffnessForce * delta * 60));
        var gravity = record.gravity || [0, -.1, 0]; tip.add(new THREE.Vector3(-gravity[0], gravity[1], gravity[2]).multiplyScalar(delta * delta));
        if (applyColliders) spheres.forEach(function (sphere) {
          if (!sphere.record.enabled || sphere.object === object) return;
          var shape = world[sphere.record.id], center = shape.center.clone(), radius = shape.radius;
          var sibling = world[sphere.record.sibling];
          if (sibling) { var line = sibling.center.clone().sub(center), distance = line.lengthSq(), along = distance ? Math.max(0, Math.min(1, tip.clone().sub(center).dot(line) / distance)) : 0; center.addScaledVector(line, along); radius += (sibling.radius - radius) * along; }
          var away = tip.clone().sub(center), distance = away.length(); if (distance < radius) tip.copy(center).addScaledVector(distance ? away.divideScalar(distance) : new THREE.Vector3(0, 1, 0), radius);
        });
        tip.sub(origin).normalize().multiplyScalar(length).add(origin);
        var restDirection = rest.clone().sub(origin).normalize(), direction = tip.clone().sub(origin).normalize();
        var worldRotation = object.getWorldQuaternion(new THREE.Quaternion()), desired = new THREE.Quaternion().setFromUnitVectors(restDirection, direction).multiply(worldRotation);
        if (object.parent) desired.premultiply(object.parent.getWorldQuaternion(new THREE.Quaternion()).invert());
        var relative = object.quaternion.clone().invert().multiply(desired), euler = new THREE.Euler().setFromQuaternion(relative, "ZXY");
        ["x", "y", "z"].forEach(function (axis, i) { var lo = values.lowRotationLimit[i] * Math.PI / 180, hi = values.highRotationLimit[i] * Math.PI / 180; if (axis !== "x") { var a = lo; lo = -hi; hi = -a; } euler[axis] = Math.max(lo, Math.min(hi, euler[axis])); });
        object.quaternion.multiply(new THREE.Quaternion().setFromEuler(euler)); object.updateMatrixWorld(true);
        spring.tip.copy(local.applyMatrix4(object.matrixWorld));
      });
      root.updateMatrixWorld(true); root.traverse(function (object) { if (object.isSkinnedMesh) object.skeleton.update(); });
    }
    return {
      apply: apply,
      getEdits: function () { return Object.keys(edits).sort().map(function (id) { return { id: id, values: JSON.parse(JSON.stringify(edits[id])) }; }); },
      invalid: function () { return controls.some(function (c) { return c.record && c.input.dataset.physicsDirty === "true" && !c.input.disabled && !c.input.checkValidity(); }); },
      restore: function (rows) { var next = {}; if (!Array.isArray(rows) || rows.length > components.length) throw new Error("The physics recipe is invalid."); rows.forEach(function (row) { var record = components.filter(function (r) { return r.id === row.id; })[0]; if (!record || next[row.id] || !validValues(record, row.values)) throw new Error("The physics recipe is invalid."); next[row.id] = JSON.parse(JSON.stringify(row.values)); }); edits = next; refreshFields(); },
      reset: function () { edits = {}; springs.forEach(function (s) { s.tip = null; s.previous = null; }); refreshFields(); },
      setInteractive: function (value, authoring) { interactive = !!value; writable = !!authoring; controls.forEach(function (row) { row.input.disabled = !interactive || row.write && !writable || row.available === false; }); },
      updateLanguage: function () { regions.forEach(function (region) { region.querySelectorAll("[data-physics-label]").forEach(function (el) { el.textContent = t(el.dataset.physicsLabel); }); }); },
      getState: function () { return { available: components.length > 0, swingBone: applyBones, swingCollider: applyColliders, showColliders: showColliders, components: components.length, dynamicBones: springs.length, edited: Object.keys(edits).length }; },
      dispose: function () { disposed = true; regions.forEach(function (r) { r.remove(); }); root.remove(helperGroup); spheres.forEach(function (s) { s.helper.geometry.dispose(); s.helper.material.dispose(); }); }
    };
  }
  window.ViewerPhysics = { create: create };
}());
