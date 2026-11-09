/* Outline width edits use the stock character shader's authored red mask. */
(function (global) {
  "use strict";
  var words = {
    "Character outline": ["캐릭터 외곽선", "キャラクターの輪郭線"],
    "All editable meshes": ["편집 가능한 메시 전체", "編集可能なメッシュすべて"],
    "Outline mesh": ["외곽선 조절 메시", "輪郭線を調整するメッシュ"],
    "Outline thickness": ["외곽선 두께", "輪郭線の太さ"],
    "Reset outline": ["외곽선 원본값으로", "輪郭線を元の値に戻す"],
    "No editable original outline data is available.": ["편집할 수 있는 원본 외곽선 데이터가 없습니다.", "編集可能な元の輪郭線データがありません。"],
    "Open a character model to adjust its outline.": ["캐릭터 모델을 불러오면 외곽선을 조절할 수 있습니다.", "キャラクターモデルを読み込むと輪郭線を調整できます。"],
    "Original maximum thickness can limit increases.": ["원본의 최대 두께에 도달한 부분은 더 굵어지지 않습니다.", "元の最大値に達した部分はそれ以上太くなりません。"],
    "Only meshes from the selected original files are changed. Open the face file explicitly to edit an automatically added face.": ["선택한 원본 파일의 메시에 적용합니다. 자동 추가된 얼굴을 조절하려면 얼굴 파일도 함께 불러오세요.", "選択した元ファイルのメッシュに適用します。自動追加された顔を調整するには顔ファイルも読み込んでください。"],
    "Use Save to write the outline into a new model copy.": ["저장을 누르면 새 모델 사본에 외곽선을 반영합니다.", "保存すると新しいモデルのコピーに輪郭線を反映します。"],
    "Enable SIFAS rendering to preview the outline.": ["외곽선을 미리 보려면 SIFAS 렌더링을 켜세요.", "輪郭線をプレビューするにはSIFASレンダリングを有効にしてください。"],
    "Enter an outline percentage between 0 and 200.": ["외곽선 두께를 0~200% 사이로 입력하세요.", "輪郭線の太さを0～200%で入力してください。"],
    "Different values": ["서로 다른 값", "異なる値"]
  };
  function translated(key, fallback) {
    var lang = (document.documentElement.lang || "en").split("-")[0], index = { ko: 0, ja: 1 }[lang];
    return words[key] && index !== undefined ? words[key][index] : fallback ? fallback(key) : key;
  }
  function checked(values, catalogue) {
    if (!Array.isArray(values) || values.length > 256) throw new Error("The outline edit is invalid.");
    var known = Object.create(null), used = Object.create(null);
    ((catalogue || {}).meshes || []).forEach(function (mesh) { known[mesh.id] = mesh; });
    return values.map(function (value) {
      if (!value || Object.keys(value).some(function (key) { return key !== "id" && key !== "factor"; }) ||
          typeof value.id !== "string" || !known[value.id] || used[value.id] || typeof value.factor !== "number" ||
          !Number.isFinite(value.factor) || value.factor < 0 || value.factor > 2) throw new Error("The outline edit is invalid.");
      used[value.id] = true; return { id: value.id, factor: value.factor };
    }).filter(function (value) { return value.factor !== 1; }).sort(function (a, b) { return a.id.localeCompare(b.id); });
  }
  function create(options) {
    var host = document.getElementById("viewer-control-panel"); if (!host) return null;
    var panel = document.createElement("details"); panel.id = "viewer-outline-card";
    panel.className = "viewer-adjustments viewer-outline-card"; panel.dataset.panelKey = panel.id;
    function make(tag, text) { var node = document.createElement(tag); if (text) node.dataset.outlineText = text; return node; }
    var summary = make("summary", "Character outline"), body = make("div"), label = make("label"), select = make("select");
    select.id = "viewer-outline-mesh"; label.append(make("span", "Outline mesh"), select);
    var strength = make("label"), range = make("input"), number = make("input"), output = make("output");
    range.type = "range"; range.min = "0"; range.max = "200"; range.step = "1"; range.id = "viewer-outline-range";
    number.type = "number"; number.min = "0"; number.max = "200"; number.step = "any"; number.id = "viewer-outline-number";
    output.id = "viewer-outline-value"; strength.append(make("span", "Outline thickness"), range, number, output);
    var reset = make("button", "Reset outline"); reset.type = "button"; reset.id = "viewer-outline-reset";
    var status = make("p"); status.id = "viewer-outline-status"; status.setAttribute("role", "status"); status.className = "viewer-render-note";
    var bounds = make("p", "Original maximum thickness can limit increases."); bounds.className = "viewer-render-note";
    var scope = make("p", "Only meshes from the selected original files are changed. Open the face file explicitly to edit an automatically added face."); scope.className = "viewer-render-note";
    var save = make("p", "Use Save to write the outline into a new model copy."); save.className = "viewer-render-note";
    body.append(label, strength, reset, status, bounds, scope, save); panel.append(summary, body);
    host.insertBefore(panel, document.getElementById("viewer-body-adjustments"));
    var disposed = false, refreshing = false, currentRig = null, cacheKey = "", applied = "";
    function context() { return options.context() || {}; }
    function t(key) { return translated(key, options.translate); }
    function catalogue(c) { return c.editing && c.editing.outlines || { meshes: [] }; }
    function edits(c) { return c.rig && c.rig.getOutlineEdits ? c.rig.getOutlineEdits() : []; }
    function targets(c) { return catalogue(c).meshes.filter(function (mesh) { return !select.value || mesh.id === select.value; }); }
    function refresh() {
      if (disposed || refreshing) return; refreshing = true;
      try {
        var c = context(), data = catalogue(c), values = edits(c), key = JSON.stringify(data.meshes || []);
        var newRig = c.rig !== currentRig;
        if (newRig) { currentRig = c.rig; applied = ""; number.setCustomValidity(""); range.setCustomValidity(""); }
        if (key !== cacheKey) {
          cacheKey = key; var previous = select.value; select.textContent = "";
          var all = make("option"); all.value = ""; all.textContent = t("All editable meshes"); select.appendChild(all);
          (data.meshes || []).forEach(function (mesh) { var option = make("option"); option.value = mesh.id; option.textContent = mesh.name; select.appendChild(option); });
          select.value = Array.prototype.some.call(select.options, function (item) { return item.value === previous; }) ? previous : "";
        }
        var eligible = targets(c), factors = eligible.map(function (mesh) { var value = values.filter(function (entry) { return entry.id === mesh.id; })[0]; return value ? value.factor : 1; });
        var uniform = factors.length && factors.every(function (value) { return Math.abs(value - factors[0]) < 1e-10; });
        var display = uniform ? String(Math.round(factors[0] * 10000) / 100) : "";
        if (newRig || document.activeElement !== number || number.disabled) number.value = display;
        number.placeholder = t("Different values"); range.value = uniform ? String(factors[0] * 100) : "100";
        output.textContent = uniform ? display + "%" : t("Different values");
        var enabled = c.current && c.rig && c.rig.setOutlineEdits && eligible.length && !c.busy;
        [select, range, number, reset].forEach(function (node) { node.disabled = !enabled; });
        reset.disabled = !enabled || !number.validationMessage && !eligible.some(function (mesh) { return values.some(function (value) { return value.id === mesh.id; }); });
        var fingerprint = JSON.stringify(values);
        if (c.materials && c.materials.setOutlineEdits && fingerprint !== applied) { applied = fingerprint; c.materials.setOutlineEdits(values); }
        var materialState = c.materials && c.materials.getState();
        status.textContent = t(!c.rig ? "Open a character model to adjust its outline." : !eligible.length ? "No editable original outline data is available." : materialState && !materialState.enabled ? "Enable SIFAS rendering to preview the outline." : "Use Save to write the outline into a new model copy.");
        panel.querySelectorAll("[data-outline-text]").forEach(function (node) { node.textContent = t(node.dataset.outlineText); });
      } finally { refreshing = false; }
    }
    function change(event) {
      var input = event.target, amount = Number(input.value), valid = input.value.trim() && Number.isFinite(amount) && amount >= 0 && amount <= 200;
      input.setCustomValidity(valid ? "" : t("Enter an outline percentage between 0 and 200."));
      if (!valid) { if (options.onChange) options.onChange(); return; }
      number.setCustomValidity(""); range.setCustomValidity("");
      var c = context(), selected = targets(c), ids = new Set(selected.map(function (mesh) { return mesh.id; }));
      var next = edits(c).filter(function (value) { return !ids.has(value.id); });
      selected.forEach(function (mesh) { if (amount !== 100) next.push({ id: mesh.id, factor: amount / 100 }); });
      c.rig.setOutlineEdits(next); refresh(); if (options.onChange) options.onChange();
    }
    range.addEventListener("input", change); number.addEventListener("input", change);
    select.addEventListener("change", function () { number.setCustomValidity(""); refresh(); if (options.onChange) options.onChange(); });
    reset.addEventListener("click", function () {
      number.setCustomValidity(""); range.setCustomValidity("");
      var c = context(), ids = new Set(targets(c).map(function (mesh) { return mesh.id; }));
      c.rig.setOutlineEdits(edits(c).filter(function (value) { return !ids.has(value.id); })); refresh(); if (options.onChange) options.onChange();
    });
    refresh();
    return { refresh: refresh, updateLanguage: function () { cacheKey = ""; refresh(); },
      getState: function () { var c = context(); return { available: catalogue(c).meshes.length > 0, selected: select.value, edits: edits(c), shaderEnabled: !!(c.materials && c.materials.getState().enabled) }; },
      invalid: function () { return !!number.validationMessage; },
      dispose: function () { disposed = true; panel.remove(); } };
  }
  global.ViewerOutlines = { create: create, checked: checked };
}(window));
