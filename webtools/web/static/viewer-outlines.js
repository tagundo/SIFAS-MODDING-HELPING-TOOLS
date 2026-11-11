/* Stock outline red masks, including source-bound vertex painting. */
(function (global) {
  "use strict";
  var words = {
    "Character outline": ["캐릭터 외곽선", "キャラクターの輪郭線"],
    "All editable meshes": ["편집 가능한 메시 전체", "編集可能なメッシュすべて"],
    "Outline mesh": ["외곽선 조절 메시", "輪郭線を調整するメッシュ"],
    "Outline thickness": ["외곽선 두께", "輪郭線の太さ"],
    "Reset outline": ["외곽선 원본값으로", "輪郭線を元の値に戻す"],
    "Copy outline diagnostics": ["외곽선 진단 복사", "輪郭線の診断をコピー"],
    "Outline diagnostics": ["외곽선 진단", "輪郭線の診断"],
    "Outline diagnostics copied.": ["외곽선 진단을 복사했습니다.", "輪郭線の診断をコピーしました。"],
    "Select and copy the diagnostics below.": ["아래 진단 내용을 선택해 복사하세요.", "下の診断内容を選択してコピーしてください。"],
    "No editable original outline data is available.": ["편집할 수 있는 원본 외곽선 데이터가 없습니다.", "編集可能な元の輪郭線データがありません。"],
    "Open a character model to adjust its outline.": ["캐릭터 모델을 불러오면 외곽선을 조절할 수 있습니다.", "キャラクターモデルを読み込むと輪郭線を調整できます。"],
    "Original maximum thickness can limit increases.": ["원본의 최대 두께에 도달한 부분은 더 굵어지지 않습니다.", "元の最大値に達した部分はそれ以上太くなりません。"],
    "Verified companion face meshes include the jaw. Saving writes new model and face copies.": ["확인된 함께 쓰는 얼굴 메시의 턱도 편집합니다. 저장하면 모델과 얼굴의 새 사본을 만듭니다.", "確認済みの付属顔メッシュの顎も編集できます。保存するとモデルと顔の新しいコピーを作成します。"],
    "Use Save to write the outline into a new model copy.": ["저장을 누르면 새 모델 사본에 외곽선을 반영합니다.", "保存すると新しいモデルのコピーに輪郭線を反映します。"],
    "Enable SIFAS rendering to preview the outline.": ["외곽선을 미리 보려면 SIFAS 렌더링을 켜세요.", "輪郭線をプレビューするにはSIFASレンダリングを有効にしてください。"],
    "Enter an outline percentage between 0 and 200.": ["외곽선 두께를 0~200% 사이로 입력하세요.", "輪郭線の太さを0～200%で入力してください。"],
    "Different values": ["서로 다른 값", "異なる値"],
    "Detailed outline editing": ["외곽선 세부 편집", "輪郭線の詳細編集"],
    "3D editing": ["3D 편집", "3D編集"], "Orbit model": ["모델 회전", "モデルを回転"],
    "Paint outline on model": ["모델에 외곽선 칠하기", "モデルに輪郭線を塗る"],
    "Brush radius": ["브러시 반경", "ブラシ半径"], "Vertex width": ["정점 외곽선 두께", "頂点の輪郭線の太さ"],
    "Restore original with brush": ["브러시로 원본값 복원", "ブラシで元の値に戻す"],
    "Show edited vertices": ["편집한 정점 표시", "編集した頂点を表示"],
    "Vertex index": ["정점 번호", "頂点番号"], "Apply vertex width": ["이 정점에 두께 적용", "この頂点に太さを適用"],
    "Restore vertex": ["이 정점 원본값으로", "この頂点を元に戻す"],
    "Undo outline edit": ["외곽선 편집 되돌리기", "輪郭線の編集を元に戻す"],
    "Redo outline edit": ["외곽선 편집 다시 실행", "輪郭線の編集をやり直す"],
    "Paint individual source vertices. Shift restores originals; Alt or right-drag rotates the model.": ["원본 정점 단위로 칠합니다. Shift는 원본 복원, Alt 또는 오른쪽 드래그는 모델 회전입니다.", "元の頂点ごとに塗ります。Shiftで元に戻し、Altまたは右ドラッグでモデルを回転します。"],
    "Local widths are applied before the whole-mesh percentage. Zero-width vertices can also be painted.": ["세부 두께에 메시 전체 비율을 곱합니다. 원래 두께가 0인 정점에도 칠할 수 있습니다.", "詳細な太さにメッシュ全体の倍率を掛けます。元の太さが0の頂点にも塗れます。"],
    "Select one mesh to edit an exact vertex.": ["정점 번호로 편집하려면 메시 하나를 선택하세요.", "頂点番号で編集するにはメッシュを1つ選択してください。"],
    "Edited vertices": ["편집한 정점", "編集した頂点"],
    "All vertex width to apply (0–255)": ["전체 정점에 적용할 절대 두께 (0–255)", "全頂点に適用する絶対幅（0–255）"],
    "Original width bytes: {min}–{max} · average {mean}": ["원본 두께 값: {min}–{max} · 평균 {mean}", "元の輪郭幅: {min}～{max} · 平均 {mean}"],
    "Apply absolute width to all vertices": ["전체 정점에 절대 두께 적용", "全頂点に絶対幅を適用"],
    "Sets every vertex in the selected meshes to the same original UNorm8 red value. 0 hides the outline; 255 is its maximum. Replaces local widths and resets the percentage to 100%.": ["선택한 메시의 모든 정점을 같은 원본 UNorm8 빨강 값으로 설정합니다. 0은 외곽선 없음, 255는 최대 두께입니다. 세부 두께를 교체하고 전체 비율을 100%로 맞춥니다.", "選択メッシュの全頂点を同じ元のUNorm8赤値に設定します。0は輪郭なし、255は最大幅です。個別幅を置き換え、倍率を100%に戻します。"],
    "Enter an integer outline width between 0 and 255.": ["절대 두께를 0~255 사이의 정수로 입력하세요.", "絶対幅を0～255の整数で入力してください。"],
    "The original vertex width is unavailable.": ["이 정점의 원본 외곽선 값을 확인할 수 없습니다.", "この頂点の元の輪郭幅を確認できません。"],
    "Enter a vertex width between 0 and 100.": ["정점 두께를 0~100% 사이로 입력하세요.", "頂点の太さを0～100%で入力してください。"]
  };
  function translated(key, fallback) {
    var lang = (document.documentElement.lang || "en").split("-")[0], index = { ko: 0, ja: 1 }[lang];
    return words[key] && index !== undefined ? words[key][index] : fallback ? fallback(key) : key;
  }
  function checked(values, catalogue) {
    if (!Array.isArray(values) || values.length > 256) throw new Error("The outline edit is invalid.");
    var known = Object.create(null), used = Object.create(null), total = 0;
    ((catalogue || {}).meshes || []).forEach(function (mesh) { known[mesh.id] = mesh; });
    return values.map(function (value) {
      if (!value || Object.keys(value).some(function (key) { return key !== "id" && key !== "factor" && key !== "vertices" && key !== "absolute"; }) ||
          typeof value.id !== "string" || !known[value.id] || used[value.id] || typeof value.factor !== "number" ||
          !Number.isFinite(value.factor) || value.factor < 0 || value.factor > 2) throw new Error("The outline edit is invalid.");
      if (value.absolute !== undefined && (!Number.isInteger(value.absolute) || value.absolute < 0 || value.absolute > 255)) throw new Error("The absolute outline width is invalid.");
      var vertices = value.vertices === undefined ? [] : value.vertices, seen = Object.create(null);
      if (!Array.isArray(vertices) || vertices.length > known[value.id].vertexCount) throw new Error("The outline vertex edit is invalid.");
      var rows = vertices.map(function (row) {
        if (!row || Object.keys(row).length !== 2 || !Number.isInteger(row.vertex) || row.vertex < 0 || row.vertex >= known[value.id].vertexCount || seen[row.vertex] ||
            typeof row.value !== "number" || !Number.isFinite(row.value) || row.value < 0 || row.value > 1 || Object.keys(row).some(function (key) { return key !== "vertex" && key !== "value"; })) throw new Error("The outline vertex edit is invalid.");
        seen[row.vertex] = true; return { vertex: row.vertex, value: row.value };
      }).sort(function (a, b) { return a.vertex - b.vertex; });
      total += rows.length; if (total > 250000) throw new Error("There are too many outline vertex edits.");
      used[value.id] = true; var result = { id: value.id, factor: value.factor }; if (value.absolute !== undefined) result.absolute = value.absolute; if (rows.length) result.vertices = rows; return result;
    }).filter(function (value) { return value.factor !== 1 || value.absolute !== undefined || value.vertices && value.vertices.length; }).sort(function (a, b) { return a.id.localeCompare(b.id); });
  }
  function create(options) {
    var host = document.getElementById("viewer-control-panel"); if (!host) return null;
    var panel = document.createElement("details"); panel.id = "viewer-outline-card";
    panel.className = "viewer-adjustments viewer-outline-card"; panel.dataset.panelKey = panel.id;
    function make(tag, text) { var node = document.createElement(tag); if (text) node.dataset.outlineText = text; return node; }
    function field(text, input) { var label = make("label"); label.append(make("span", text), input); return label; }
    function button(text, id, fn) { var node = make("button", text); node.type = "button"; node.id = id; node.addEventListener("click", fn); return node; }
    var summary = make("summary", "Character outline"), body = make("div"), select = make("select"); select.id = "viewer-outline-mesh";
    var strength = make("label"), range = make("input"), number = make("input"), output = make("output");
    range.type = "range"; range.min = "0"; range.max = "200"; range.step = "1"; range.id = "viewer-outline-range";
    number.type = "number"; number.min = "0"; number.max = "200"; number.step = "any"; number.id = "viewer-outline-number";
    output.id = "viewer-outline-value"; strength.append(make("span", "Outline thickness"), range, number, output);
    var reset = button("Reset outline", "viewer-outline-reset", resetSelected);
    var absolute = make("input"); absolute.id = "viewer-outline-absolute"; absolute.type = "number"; absolute.min = "0"; absolute.max = "255"; absolute.step = "1"; absolute.value = "128";
    var absoluteApply = button("Apply absolute width to all vertices", "viewer-outline-absolute-apply", applyAbsolute);
    var absoluteHelp = make("p", "Sets every vertex in the selected meshes to the same original UNorm8 red value. 0 hides the outline; 255 is its maximum. Replaces local widths and resets the percentage to 100%."); absoluteHelp.className = "viewer-render-note";
    var detail = make("details"), detailBody = make("div"); detail.id = "viewer-outline-detail"; detail.append(make("summary", "Detailed outline editing"), detailBody);
    var sceneMode = make("select"); sceneMode.id = "viewer-outline-scene-mode";
    [["orbit", "Orbit model"], ["paint", "Paint outline on model"]].forEach(function (row) { var option = make("option", row[1]); option.value = row[0]; sceneMode.append(option); });
    var radius = make("input"); radius.id = "viewer-outline-brush-radius"; radius.type = "range"; radius.min = "4"; radius.max = "120"; radius.step = "1"; radius.value = "24";
    var width = make("input"); width.id = "viewer-outline-vertex-width"; width.type = "number"; width.min = "0"; width.max = "100"; width.step = "any"; width.value = "50";
    var restoreBrush = make("input"); restoreBrush.id = "viewer-outline-brush-restore"; restoreBrush.type = "checkbox";
    var showVertices = make("input"); showVertices.id = "viewer-outline-show-vertices"; showVertices.type = "checkbox"; showVertices.checked = true;
    var vertex = make("input"); vertex.id = "viewer-outline-vertex-index"; vertex.type = "number"; vertex.min = "0"; vertex.step = "1"; vertex.value = "0";
    var exact = make("div"), applyVertex = button("Apply vertex width", "viewer-outline-vertex-apply", function () { exactVertex(false); });
    var restoreVertex = button("Restore vertex", "viewer-outline-vertex-reset", function () { exactVertex(true); }); exact.append(field("Vertex index", vertex), applyVertex, restoreVertex);
    var historyButtons = make("div"), undoButton = button("Undo outline edit", "viewer-outline-undo", undo), redoButton = button("Redo outline edit", "viewer-outline-redo", redo); historyButtons.append(undoButton, redoButton);
    var count = make("p"); count.id = "viewer-outline-detail-count"; count.className = "viewer-render-note";
    detailBody.append(field("3D editing", sceneMode), field("Brush radius", radius), field("Vertex width", width), field("Restore original with brush", restoreBrush), field("Show edited vertices", showVertices), exact,
      make("p", "Paint individual source vertices. Shift restores originals; Alt or right-drag rotates the model."), make("p", "Local widths are applied before the whole-mesh percentage. Zero-width vertices can also be painted."), count);
    var status = make("p"); status.id = "viewer-outline-status"; status.setAttribute("role", "status"); status.className = "viewer-render-note";
    var copyDiagnostics = button("Copy outline diagnostics", "viewer-outline-diagnostics-copy", copyOutlineDiagnostics);
    var diagnosticsStatus = make("p"); diagnosticsStatus.id = "viewer-outline-diagnostics-status"; diagnosticsStatus.setAttribute("role", "status"); diagnosticsStatus.className = "viewer-render-note"; diagnosticsStatus.hidden = true;
    var diagnosticsText = make("textarea"); diagnosticsText.id = "viewer-outline-diagnostics-text"; diagnosticsText.readOnly = true; diagnosticsText.rows = 10; diagnosticsText.hidden = true; diagnosticsText.spellcheck = false;
    Object.assign(diagnosticsText.style, { width: "100%", maxWidth: "100%", boxSizing: "border-box", resize: "vertical" });
    var bounds = make("p", "Original maximum thickness can limit increases."); bounds.className = "viewer-render-note";
    var scope = make("p", "Verified companion face meshes include the jaw. Saving writes new model and face copies."); scope.className = "viewer-render-note";
    var sourceWidth = make("p"); sourceWidth.id = "viewer-outline-source-width"; sourceWidth.className = "viewer-render-note";
    body.append(field("Outline mesh", select), strength, reset, sourceWidth, field("All vertex width to apply (0–255)", absolute), absoluteApply, absoluteHelp, detail, historyButtons, status, copyDiagnostics, diagnosticsStatus, diagnosticsText, bounds, scope); panel.append(summary, body);
    host.insertBefore(panel, document.getElementById("viewer-body-adjustments"));
    var disposed = false, refreshing = false, updating = false, currentRig = null, cacheKey = "", applied = "", controlBefore = null, cachedCatalogue = null, languageKey = "";
    var editRig = null, editRevision = null, editValues = [], editJSON = "[]", pickCache = null, paintFrame = 0, pendingPaint = [], pointPoseKey = "";
    var performanceState = { cacheBuilds: 0, worldVertices: 0, rayQueries: 0, triangleTests: 0, paintSamples: 0, lastPaintMs: 0 };
    var past = [], future = [], runtime = null, canvas = null, removers = [], cursor = null, stroke = null;
    var pointRoot = null, pointGeometry = null, pointRefs = [], pointKey = "", scratch = null, indexKeys = new WeakMap(), indexGeneration = 0;
    var copyingDiagnostics = false;
    function context() { return options.context() || {}; }
    function t(key) { return translated(key, options.translate); }
    function catalogue(c) { return c.editing && c.editing.outlines || { meshes: [] }; }
    function edits(c) {
      if (!c.rig || !c.rig.getOutlineEdits) { editRig = null; editRevision = null; editValues = []; editJSON = "[]"; return editValues; }
      var revision = c.rig.getOutlineRevision ? c.rig.getOutlineRevision() : null;
      if (revision === null || editRig !== c.rig || editRevision !== revision) {
        editRig = c.rig; editRevision = revision; editValues = c.rig.getOutlineEdits(); editJSON = JSON.stringify(editValues);
      }
      return editValues;
    }
    function targets(c) { return catalogue(c).meshes.filter(function (mesh) { return !select.value || mesh.id === select.value; }); }
    function json() { edits(context()); return editJSON; }
    function vertexCount(values, c) { var records = {}; catalogue(c).meshes.forEach(function (row) { records[row.id] = row.vertexCount; }); return values.reduce(function (sum, row) { return sum + (row.absolute !== undefined ? records[row.id] || 0 : (row.vertices || []).length); }, 0); }
    function notify() { if (options.onChange) options.onChange(); }
    function outlineDiagnostics(c) {
      var data = catalogue(c), values = c.rig && c.rig.getOutlineEdits ? c.rig.getOutlineEdits() : [], byId = Object.create(null), roles = Object.create(null);
      values.forEach(function (value) { byId[value.id] = value; });
      var current = options.getRuntime && options.getRuntime();
      if (current && current.model) current.model.traverse(function (mesh) {
        if (!mesh.isMesh || mesh.userData.viewerHelper) return;
        var identity = sourceId(mesh); if (!identity) return;
        for (var parent = mesh; parent; parent = parent.parent) {
          var role = parent.userData && parent.userData.viewerFacialRole;
          if (typeof role === "string" && role) {
            if (!roles[identity]) roles[identity] = [];
            if (roles[identity].indexOf(role) < 0) roles[identity].push(role);
          }
        }
      });
      var result = { format: "elichika-outline-diagnostics", version: 1,
        sources: (data.sources || []).map(function (source) {
          return { sourceIndex: source.sourceIndex, name: String(source.name || "").split(/[\\/]/).pop(), sha256: source.sha256 };
        }),
        rendering: { sifasEnabled: !!(c.materials && c.materials.getState && c.materials.getState().enabled) },
        selection: { meshId: select.value || null, meshCount: targets(c).length },
        editedMeshCount: values.length,
        meshes: (data.meshes || []).map(function (mesh) {
          var edit = byId[mesh.id], row = { id: mesh.id, name: mesh.name, sourceIndex: mesh.sourceIndex,
            semantic: mesh.semantic || null, renderRoles: roles[mesh.id] || [],
            originalWidth: mesh.originalWidth ? { min: mesh.originalWidth.min, max: mesh.originalWidth.max, mean: mesh.originalWidth.mean } : null,
            factor: edit ? edit.factor : 1, localVertexEditCount: edit && edit.vertices ? edit.vertices.length : 0 };
          if (edit && edit.absolute !== undefined) row.absolute = edit.absolute;
          return row;
        }) };
      var appVersion = c.appVersion || global.ElichikaDesktop && global.ElichikaDesktop.appVersion;
      if (typeof appVersion === "string" && appVersion) result.appVersion = appVersion;
      return result;
    }
    async function copyOutlineDiagnostics() {
      var c = context(); if (disposed || copyingDiagnostics || !c.current || !catalogue(c).meshes.length) return;
      var sourceRig = c.rig, text = JSON.stringify(outlineDiagnostics(c), null, 2);
      copyingDiagnostics = true; copyDiagnostics.disabled = true;
      try {
        try {
          if (!global.navigator.clipboard || !global.navigator.clipboard.writeText) throw new Error("Clipboard unavailable");
          await global.navigator.clipboard.writeText(text);
          if (disposed || context().rig !== sourceRig) return;
          diagnosticsText.hidden = true; diagnosticsText.value = "";
          diagnosticsStatus.textContent = t("Outline diagnostics copied.");
        } catch (_) {
          if (disposed || context().rig !== sourceRig) return;
          diagnosticsText.value = text; diagnosticsText.hidden = false; diagnosticsText.focus(); diagnosticsText.select();
          var copied = false; try { copied = !!(document.execCommand && document.execCommand("copy")); } catch (_) {}
          diagnosticsStatus.textContent = t(copied ? "Outline diagnostics copied." : "Select and copy the diagnostics below.");
        }
        diagnosticsStatus.hidden = false;
      } finally { copyingDiagnostics = false; refresh(); }
    }
    function remember(before) {
      if (before === json()) return; past.push(before); future = [];
      var bytes = past.reduce(function (sum, value) { return sum + value.length; }, 0);
      while (past.length > 32 || bytes > 8 * 1024 * 1024 && past.length > 1) bytes -= past.shift().length;
    }
    function setValues(next, before) {
      var c = context(); if (!c.rig || !c.rig.setOutlineEdits) return;
      updating = true;
      try { c.rig.setOutlineEdits(next); } finally { updating = false; }
      if (before !== undefined) remember(before); refresh(); notify();
    }
    function resetSelected() { number.setCustomValidity(""); range.setCustomValidity(""); width.setCustomValidity(""); absolute.setCustomValidity(""); if (!Number.isFinite(Number(width.value)) || Number(width.value) < 0 || Number(width.value) > 100 || !width.value.trim()) width.value = "50"; if (!Number.isInteger(Number(absolute.value)) || Number(absolute.value) < 0 || Number(absolute.value) > 255 || !absolute.value.trim()) absolute.value = "128"; var c = context(), ids = new Set(targets(c).map(function (mesh) { return mesh.id; })); setValues(edits(c).filter(function (value) { return !ids.has(value.id); }), json()); }
    function absoluteValue() { var value = Number(absolute.value), valid = absolute.value.trim() && Number.isInteger(value) && value >= 0 && value <= 255; absolute.setCustomValidity(valid ? "" : t("Enter an integer outline width between 0 and 255.")); return valid ? value : null; }
    function applyAbsolute() {
      var value = absoluteValue(); if (value === null) { absolute.reportValidity(); return; }
      number.setCustomValidity(""); range.setCustomValidity("");
      var c = context(), selected = targets(c), ids = new Set(selected.map(function (mesh) { return mesh.id; })), next = edits(c).filter(function (row) { return !ids.has(row.id); });
      selected.forEach(function (mesh) { next.push({ id: mesh.id, factor: 1, absolute: value }); }); setValues(next, json());
    }
    function undo() { endStroke(false); if (!past.length) return false; var before = past.pop(); future.push(json()); setValues(JSON.parse(before)); return true; }
    function redo() { endStroke(false); if (!future.length) return false; var next = future.pop(); past.push(json()); setValues(JSON.parse(next)); return true; }
    function widthValue() { var value = Number(width.value), valid = width.value.trim() && Number.isFinite(value) && value >= 0 && value <= 100; width.setCustomValidity(valid ? "" : t("Enter a vertex width between 0 and 100.")); return valid ? value / 100 : null; }
    function originalWidth(identity, index) {
      if (!adoptRuntime()) return null; var found = null;
      if (pickCache) for (var i = 0; i < pickCache.records.length; i++) { var mesh = pickCache.records[i].mesh, color = mesh.geometry.attributes._sifas_color; if (sourceId(mesh) === identity && color && index < color.count) return Math.max(0, Math.min(1, color.getX(index))); }
      runtime.model.traverse(function (mesh) { if (found !== null || !mesh.isMesh || mesh.userData.viewerHelper || sourceId(mesh) !== identity) return; var color = mesh.geometry.attributes._sifas_color; if (color && index < color.count) found = Math.max(0, Math.min(1, color.getX(index))); });
      return found;
    }
    function setVertexValues(identity, indices, restore, before) {
      var value = widthValue(); if (value === null && !restore) return;
      var c = context(), values = edits(c), current = values.filter(function (item) { return item.id === identity; })[0] || { id: identity, factor: 1 }, map = Object.create(null);
      (current.vertices || []).forEach(function (row) { map[row.vertex] = row.value; });
      var missing = false;
      indices.forEach(function (index) { if (restore && current.absolute !== undefined) { var original = originalWidth(identity, index); if (original === null) missing = true; else map[index] = original; } else if (restore) delete map[index]; else map[index] = value; });
      if (missing) { status.textContent = t("The original vertex width is unavailable."); return; }
      var next = { id: identity, factor: current.factor }, vertices = Object.keys(map).map(function (key) { return { vertex: +key, value: map[key] }; });
      if (current.absolute !== undefined) next.absolute = current.absolute;
      if (vertices.length) next.vertices = vertices;
      var rows = values.filter(function (item) { return item.id !== identity; }); if (next.factor !== 1 || next.absolute !== undefined || vertices.length) rows.push(next);
      setValues(rows, before);
    }
    function exactVertex(restore) {
      var c = context(), selected = targets(c), index = Number(vertex.value);
      if (!select.value || selected.length !== 1) { status.textContent = t("Select one mesh to edit an exact vertex."); return; }
      if (!Number.isInteger(index) || index < 0 || index >= selected[0].vertexCount || !vertex.value.trim()) { vertex.reportValidity(); return; }
      setVertexValues(selected[0].id, [index], restore, json());
    }
    function refresh() {
      if (disposed || refreshing || updating) return; refreshing = true;
      try {
        var c = context(), data = catalogue(c), values = edits(c), newRig = c.rig !== currentRig;
        var key = data === cachedCatalogue ? cacheKey : JSON.stringify(data.meshes || []); cachedCatalogue = data;
        if (newRig) { currentRig = c.rig; applied = ""; past = []; future = []; controlBefore = null; number.setCustomValidity(""); range.setCustomValidity(""); pointKey = ""; diagnosticsStatus.hidden = true; diagnosticsText.hidden = true; diagnosticsText.value = ""; }
        if (key !== cacheKey) {
          cacheKey = key; var previous = select.value; select.textContent = "";
          var all = make("option"); all.value = ""; all.textContent = t("All editable meshes"); select.appendChild(all);
          (data.meshes || []).forEach(function (mesh) { var option = make("option"); option.value = mesh.id; option.textContent = mesh.name; select.appendChild(option); });
          select.value = Array.prototype.some.call(select.options, function (item) { return item.value === previous; }) ? previous : "";
        }
        var eligible = targets(c), factors = eligible.map(function (mesh) { var value = values.filter(function (entry) { return entry.id === mesh.id; })[0]; return value ? value.factor : 1; });
        var originalWidths = eligible.filter(function (mesh) { return mesh.originalWidth; }); sourceWidth.hidden = !originalWidths.length;
        if (originalWidths.length) {
          var minimum = Math.min.apply(null, originalWidths.map(function (mesh) { return mesh.originalWidth.min; })), maximum = Math.max.apply(null, originalWidths.map(function (mesh) { return mesh.originalWidth.max; }));
          var weight = originalWidths.reduce(function (sum, mesh) { return sum + mesh.vertexCount; }, 0), mean = originalWidths.reduce(function (sum, mesh) { return sum + mesh.originalWidth.mean * mesh.vertexCount; }, 0) / weight;
          sourceWidth.textContent = t("Original width bytes: {min}–{max} · average {mean}").replace("{min}", String(minimum)).replace("{max}", String(maximum)).replace("{mean}", String(Math.round(mean * 100) / 100));
        }
        var uniform = factors.length && factors.every(function (value) { return Math.abs(value - factors[0]) < 1e-10; }), display = uniform ? String(Math.round(factors[0] * 10000) / 100) : "";
        if (newRig || document.activeElement !== number || number.disabled) number.value = display;
        number.placeholder = t("Different values"); range.value = uniform ? String(factors[0] * 100) : "100"; output.textContent = uniform ? display + "%" : t("Different values");
        var enabled = !!(c.current && c.rig && c.rig.setOutlineEdits && eligible.length && !c.busy);
        copyDiagnostics.disabled = !c.current || !data.meshes.length || copyingDiagnostics;
        [select, range, number, reset, absolute, absoluteApply, sceneMode, radius, width, restoreBrush, showVertices].forEach(function (node) { node.disabled = !enabled; });
        [vertex, applyVertex, restoreVertex].forEach(function (node) { node.disabled = !enabled || !select.value; }); vertex.max = eligible.length === 1 ? String(eligible[0].vertexCount - 1) : "0";
        reset.disabled = !enabled || !number.validationMessage && !eligible.some(function (mesh) { return values.some(function (value) { return value.id === mesh.id; }); });
        undoButton.disabled = !enabled || !past.length; redoButton.disabled = !enabled || !future.length;
        var fingerprint = json();
        if (c.materials && c.materials.setOutlineEdits && fingerprint !== applied) { applied = fingerprint; c.materials.setOutlineEdits(values); }
        var materialState = c.materials && c.materials.getState();
        status.textContent = t(!c.rig ? "Open a character model to adjust its outline." : !eligible.length ? "No editable original outline data is available." : materialState && !materialState.enabled ? "Enable SIFAS rendering to preview the outline." : "Use Save to write the outline into a new model copy.");
        count.textContent = t("Edited vertices") + ": " + vertexCount(values, c);
        var language = document.documentElement.lang || "en";
        if (languageKey !== language) { languageKey = language; panel.querySelectorAll("[data-outline-text]").forEach(function (node) { node.textContent = t(node.dataset.outlineText); }); diagnosticsText.setAttribute("aria-label", t("Outline diagnostics")); }
        adoptRuntime();
      } finally { refreshing = false; }
    }
    function change(event) {
      var input = event.target, amount = Number(input.value), valid = input.value.trim() && Number.isFinite(amount) && amount >= 0 && amount <= 200;
      input.setCustomValidity(valid ? "" : t("Enter an outline percentage between 0 and 200."));
      if (!valid) { notify(); return; } number.setCustomValidity(""); range.setCustomValidity("");
      var c = context(), selected = targets(c), ids = new Set(selected.map(function (mesh) { return mesh.id; })), old = edits(c), next = old.filter(function (value) { return !ids.has(value.id); });
      selected.forEach(function (mesh) { var existing = old.filter(function (row) { return row.id === mesh.id; })[0], value = { id: mesh.id, factor: amount / 100 }; if (existing && existing.vertices) value.vertices = existing.vertices; if (existing && existing.absolute !== undefined) value.absolute = existing.absolute; if (value.factor !== 1 || value.absolute !== undefined || value.vertices) next.push(value); });
      setValues(next);
    }
    [range, number].forEach(function (input) {
      input.addEventListener("focus", function () { if (controlBefore === null) controlBefore = json(); });
      input.addEventListener("pointerdown", function () { if (controlBefore === null) controlBefore = json(); });
      input.addEventListener("input", change);
      function finishControl() { if (controlBefore !== null) { remember(controlBefore); controlBefore = null; refresh(); } }
      input.addEventListener("change", finishControl); input.addEventListener("blur", finishControl);
    });
    select.addEventListener("change", function () { number.setCustomValidity(""); refresh(); notify(); });
    sceneMode.addEventListener("change", function () { if (sceneMode.value === "paint") { panel.open = true; detail.open = true; } if (options.onSceneModeChange) options.onSceneModeChange(sceneMode.value); notify(); });
    showVertices.addEventListener("change", function () { pointKey = ""; notify(); });
    width.addEventListener("input", function () { widthValue(); notify(); }); absolute.addEventListener("input", function () { absoluteValue(); notify(); }); radius.addEventListener("input", function () { if (cursor) cursor.style.width = cursor.style.height = Number(radius.value) * 2 + "px"; });
    panel.addEventListener("toggle", function () { if (!panel.open) endStroke(false); if (cursor) cursor.style.display = "none"; notify(); });
    function isSceneEditing() { var c = context(); return !disposed && panel.open && detail.open && sceneMode.value === "paint" && !sceneMode.disabled && c.current && !c.busy; }
    function setSceneEditing(enabled) { sceneMode.value = enabled ? "paint" : "orbit"; if (enabled) { panel.open = true; detail.open = true; } else endStroke(false); if (cursor) cursor.style.display = "none"; notify(); }
    function bindEvent(element, name, handler) { element.addEventListener(name, handler, true); removers.push(function () { element.removeEventListener(name, handler, true); }); }
    function cleanupRuntime() {
      // A model replacement must not restore an old stroke into the new rig.
      // Keep the already authored mask; disposal only releases UI resources.
      var pending = stroke; stroke = null;
      if (paintFrame) global.cancelAnimationFrame(paintFrame); paintFrame = 0; pendingPaint = []; pickCache = null; pointPoseKey = "";
      if (pending && canvas && canvas.hasPointerCapture && canvas.hasPointerCapture(pending.pointerId)) { try { canvas.releasePointerCapture(pending.pointerId); } catch (_) {} }
      removers.forEach(function (remove) { remove(); }); removers = []; if (cursor) cursor.remove(); cursor = null;
      if (pointRoot) { if (pointRoot.parent) pointRoot.parent.remove(pointRoot); pointGeometry.dispose(); pointRoot.material.dispose(); } pointRoot = null; pointGeometry = null; pointRefs = []; pointKey = ""; indexKeys = new WeakMap(); indexGeneration = 0; runtime = null; canvas = null;
    }
    function adoptRuntime() {
      var next = options.getRuntime && options.getRuntime(); if (!next || !next.model || !next.renderer || !next.camera || !global.ViewerMeshRuntime) return false;
      var nextCanvas = next.domElement || next.renderer.domElement;
      if (!runtime || next.model !== runtime.model || nextCanvas !== canvas) {
        cleanupRuntime(); runtime = next; canvas = nextCanvas;
        cursor = make("div"); cursor.className = "viewer-outline-brush-cursor"; cursor.setAttribute("aria-hidden", "true");
        Object.assign(cursor.style, { position: "fixed", pointerEvents: "none", border: "2px solid #58d5ff", borderRadius: "50%", boxSizing: "border-box", zIndex: "1100", display: "none" }); document.body.append(cursor);
        bindEvent(canvas, "pointerdown", pointerDown); bindEvent(canvas, "pointermove", pointerMove); bindEvent(canvas, "pointerup", pointerUp); bindEvent(canvas, "pointercancel", pointerCancel); bindEvent(canvas, "lostpointercapture", pointerCancel);
        bindEvent(canvas, "pointerleave", function () { if (!stroke && cursor) cursor.style.display = "none"; });
      }
      runtime = next;
      var fullscreen = document.fullscreenElement || document.webkitFullscreenElement, cursorHost = fullscreen && fullscreen.contains(canvas) ? fullscreen : document.body;
      if (cursor && cursor.parentNode !== cursorHost) cursorHost.appendChild(cursor);
      return true;
    }
    function visible(mesh) { for (var node = mesh; node; node = node.parent) if (node.visible === false) return false; return true; }
    function mapping(mesh) { return mesh.geometry && mesh.geometry.userData && mesh.geometry.userData.viewerMesh || mesh.userData && mesh.userData.viewerMesh; }
    function sourceId(mesh) { var map = mapping(mesh), value = map && map.mesh; return value ? String(value.source) + ":" + String(value.file) + ":" + String(value.id) : null; }
    function surfaces() { var list = []; runtime.model.traverse(function (mesh) { if (mesh.isMesh && !mesh.userData.viewerHelper && visible(mesh) && mesh.geometry && mesh.geometry.attributes.position) { var materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]; if (!materials.every(function (value) { return !value || value.visible === false || value.opacity === 0; })) list.push(mesh); } }); return list; }
    function poseKey(list) {
      var key = [];
      function attributeKey(attribute) { if (!attribute) return "-"; if (!indexKeys.has(attribute)) indexKeys.set(attribute, ++indexGeneration); return indexKeys.get(attribute) + ":" + attribute.version + ":" + attribute.count; }
      list.forEach(function (mesh) {
        var geometry = mesh.geometry, attributes = geometry.attributes;
        key.push(mesh.uuid, geometry.uuid, mesh.matrixWorld.elements.join(","));
        [geometry.index, attributes.position, attributes.skinIndex, attributes.skinWeight].forEach(function (attribute) { key.push(attributeKey(attribute)); });
        key.push((mesh.morphTargetInfluences || []).join(","), geometry.morphTargetsRelative);
        (geometry.morphAttributes.position || []).forEach(function (attribute) { key.push(attributeKey(attribute)); });
        if (mesh.isSkinnedMesh && mesh.skeleton) {
          key.push(mesh.bindMatrix.elements.join(","), mesh.bindMatrixInverse.elements.join(","));
          mesh.skeleton.bones.forEach(function (bone, index) { var inverse = mesh.skeleton.boneInverses[index]; key.push(bone && bone.matrixWorld ? bone.matrixWorld.elements.join(",") : "-", inverse ? inverse.elements.join(",") : "-"); });
        }
      });
      return key.join("|");
    }
    function sceneIndex(list, rect) {
      var pose = poseKey(list), key = pose + ":" + runtime.camera.matrixWorld.elements.join(",") + ":" + runtime.camera.projectionMatrix.elements.join(",") + ":" + [rect.left, rect.top, rect.width, rect.height].join(",");
      if (pickCache && pickCache.key === key) return pickCache;
      var cell = 24, columns = Math.max(1, Math.ceil(rect.width / cell)), rows = Math.max(1, Math.ceil(rect.height / cell));
      var records = list.map(function (mesh) {
        var geometry = mesh.geometry, index = geometry.index, count = index ? index.count : geometry.attributes.position.count;
        var used = [], seen = new Uint8Array(geometry.attributes.position.count), projected = new Array(seen.length), cells = Object.create(null), wide = [];
        for (var slot = 0; slot < count; slot++) { var vertex = index ? index.getX(slot) : slot; if (!seen[vertex]) { seen[vertex] = 1; used.push(vertex); } }
        var previous = pickCache && pickCache.pose === pose && pickCache.records.filter(function (record) { return record.mesh === mesh; })[0];
        var world = previous ? previous.world : global.ViewerMeshRuntime.worldSnapshot ? global.ViewerMeshRuntime.worldSnapshot(mesh, used) : new Array(seen.length);
        used.forEach(function (vertex) { var point = world[vertex] || (world[vertex] = global.ViewerMeshRuntime.vertexWorld(mesh, vertex)), p = point.clone().project(runtime.camera); projected[vertex] = [rect.left + (p.x + 1) * .5 * rect.width, rect.top + (1 - p.y) * .5 * rect.height, p.z]; });
        if (!previous) performanceState.worldVertices += used.length;
        for (var offset = 0; offset < count; offset += 3) {
          var face = offset / 3, a = projected[index ? index.getX(offset) : offset], b = projected[index ? index.getX(offset + 1) : offset + 1], c = projected[index ? index.getX(offset + 2) : offset + 2];
          // Near-plane crossings and large projected faces remain in every
          // ray query. Their exact world-space intersection still decides.
          if ([a, b, c].some(function (p) { return !p.every(Number.isFinite) || p[2] < -1 || p[2] > 1; })) { wide.push(face); continue; }
          var left = Math.floor((Math.min(a[0], b[0], c[0]) - rect.left) / cell), right = Math.floor((Math.max(a[0], b[0], c[0]) - rect.left) / cell);
          var top = Math.floor((Math.min(a[1], b[1], c[1]) - rect.top) / cell), bottom = Math.floor((Math.max(a[1], b[1], c[1]) - rect.top) / cell);
          if (right < 0 || bottom < 0 || left >= columns || top >= rows) continue;
          left = Math.max(0, left); right = Math.min(columns - 1, right); top = Math.max(0, top); bottom = Math.min(rows - 1, bottom);
          if ((right - left + 1) * (bottom - top + 1) > 128) { wide.push(face); continue; }
          for (var y = top; y <= bottom; y++) for (var x = left; x <= right; x++) { var cellKey = y * columns + x; (cells[cellKey] || (cells[cellKey] = [])).push(face); }
        }
        return { mesh: mesh, used: used, world: world, projected: projected, cells: cells, wide: wide };
      });
      performanceState.cacheBuilds++;
      pickCache = { key: key, pose: pose, records: records, rect: rect, cell: cell, columns: columns, rows: rows }; return pickCache;
    }
    function nearest(ray, indexed, x, y) {
      var result = null, column = Math.floor((x - indexed.rect.left) / indexed.cell), row = Math.floor((y - indexed.rect.top) / indexed.cell), cellKey = row * indexed.columns + column;
      var outside = column < 0 || column >= indexed.columns || row < 0 || row >= indexed.rows;
      performanceState.rayQueries++;
      indexed.records.forEach(function (record) {
        // A brush near the canvas edge can reach projected vertices outside
        // its viewport. Preserve their original off-screen occlusion checks.
        if (outside) {
          performanceState.triangleTests += (record.mesh.geometry.index ? record.mesh.geometry.index.count : record.mesh.geometry.attributes.position.count) / 3;
          var full = global.ViewerMeshRuntime.raycastMesh(ray, record.mesh, { vertices: record.world });
          if (full && (!result || full.distanceSquared < result.distanceSquared)) result = full;
          return;
        }
        var faces = record.cells[cellKey] || [];
        if (record.wide.length) faces = faces.concat(record.wide);
        if (!faces.length) return;
        performanceState.triangleTests += faces.length;
        var hit = global.ViewerMeshRuntime.raycastMesh(ray, record.mesh, { vertices: record.world, faceIndices: faces });
        if (hit && (!result || hit.distanceSquared < result.distanceSquared)) result = hit;
      }); return result;
    }
    function pointerCursor(event) { if (!cursor) return; var r = Number(radius.value); cursor.style.display = isSceneEditing() && !event.altKey ? "block" : "none"; cursor.style.width = cursor.style.height = r * 2 + "px"; cursor.style.left = event.clientX - r + "px"; cursor.style.top = event.clientY - r + "px"; cursor.style.borderColor = restoreBrush.checked || event.shiftKey ? "#ffcd6a" : "#58d5ff"; }
    function paintSelection(event) {
      if (!adoptRuntime() || !isSceneEditing()) return null; runtime.model.updateMatrixWorld(true); runtime.camera.updateMatrixWorld(true);
      var T = global.THREE, rect = canvas.getBoundingClientRect(), raycaster = new T.Raycaster(), list = surfaces(), indexed = sceneIndex(list, rect);
      raycaster.setFromCamera(new T.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2), runtime.camera);
      var hit = nearest(raycaster.ray, indexed, event.clientX, event.clientY); if (!hit) return null;
      var identity = sourceId(hit.object), record = targets(context()).filter(function (row) { return row.id === identity; })[0], map = mapping(hit.object), geometry = hit.object.geometry;
      if (!record || !map || map.vertexOrder !== "identity" || geometry.attributes.position.count !== record.vertexCount) return null;
      var source = indexed.records.filter(function (item) { return item.mesh === hit.object; })[0];
      var r = Number(radius.value), selected = [], nearestVertex = null, nearestDistance = Infinity;
      source.used.forEach(function (index) {
        var point = source.world[index], projected = source.projected[index], x = projected[0], y = projected[1];
        var distance = Math.hypot(x - event.clientX, y - event.clientY);
        if ([hit.face.a, hit.face.b, hit.face.c].indexOf(index) >= 0 && distance < nearestDistance) { nearestDistance = distance; nearestVertex = index; }
        if (projected[2] < -1 || projected[2] > 1 || distance > r) return;
        raycaster.setFromCamera(new T.Vector2((x - rect.left) / rect.width * 2 - 1, 1 - (y - rect.top) / rect.height * 2), runtime.camera); var blocker = nearest(raycaster.ray, indexed, x, y);
        if (blocker && blocker.distance + 1e-5 < raycaster.ray.origin.distanceTo(point) && blocker.point.distanceTo(point) > 1e-4) return;
        selected.push(index);
      });
      if (!selected.length && nearestVertex !== null) selected.push(nearestVertex);
      performanceState.paintSamples++;
      return selected.length ? { identity: identity, indices: selected, restore: !!(event.restore || event.shiftKey), width: event.width } : null;
    }
    function flushPaint() {
      if (paintFrame) global.cancelAnimationFrame(paintFrame); paintFrame = 0;
      if (!stroke || !pendingPaint.length) { pendingPaint = []; return; }
      var started = performance.now(), events = pendingPaint; pendingPaint = [];
      var c = context(), values = edits(c), changes = Object.create(null);
      events.forEach(function (event) {
        var selection = paintSelection(event); if (!selection || selection.width === null && !selection.restore) return;
        var row = changes[selection.identity];
        if (!row) { var old = values.filter(function (value) { return value.id === selection.identity; })[0] || { id: selection.identity, factor: 1 }; row = changes[selection.identity] = { old: old, vertices: Object.create(null) }; (old.vertices || []).forEach(function (value) { row.vertices[value.vertex] = value.value; }); }
        selection.indices.forEach(function (index) {
          if (!selection.restore) row.vertices[index] = selection.width;
          else if (row.old.absolute === undefined) delete row.vertices[index];
          else { var original = originalWidth(selection.identity, index); if (original !== null) row.vertices[index] = original; }
        });
      });
      var identities = Object.keys(changes);
      if (identities.length) {
        var next = values.filter(function (row) { return !Object.prototype.hasOwnProperty.call(changes, row.id); });
        identities.forEach(function (identity) { var change = changes[identity], row = { id: identity, factor: change.old.factor }; if (change.old.absolute !== undefined) row.absolute = change.old.absolute; var vertices = Object.keys(change.vertices).map(function (key) { return { vertex: +key, value: change.vertices[key] }; }); if (vertices.length) row.vertices = vertices; if (row.factor !== 1 || row.absolute !== undefined || vertices.length) next.push(row); });
        setValues(next);
      }
      performanceState.lastPaintMs = performance.now() - started;
    }
    function queuePaint(event, immediate) { pendingPaint.push({ clientX: event.clientX, clientY: event.clientY, shiftKey: !!event.shiftKey, restore: restoreBrush.checked, width: widthValue() }); if (immediate) flushPaint(); else if (!paintFrame) paintFrame = global.requestAnimationFrame(flushPaint); }
    function pointerDown(event) { if (event.button !== 0 || event.altKey || !isSceneEditing()) return; event.preventDefault(); event.stopImmediatePropagation(); if (stroke) return; if (!canvas.hasAttribute("tabindex")) canvas.tabIndex = 0; canvas.focus({ preventScroll: true }); stroke = { before: json(), pointerId: event.pointerId }; try { canvas.setPointerCapture(event.pointerId); } catch (_) {} pointerCursor(event); queuePaint(event, true); }
    function pointerMove(event) { pointerCursor(event); if (stroke && event.pointerId === stroke.pointerId) { event.preventDefault(); event.stopImmediatePropagation(); queuePaint(event, false); } }
    function endStroke(cancel) { if (!stroke) return; var previous = stroke; if (!cancel) flushPaint(); if (paintFrame) global.cancelAnimationFrame(paintFrame); paintFrame = 0; pendingPaint = []; stroke = null; if (cancel) setValues(JSON.parse(previous.before)); else { remember(previous.before); refresh(); } if (canvas && canvas.hasPointerCapture && canvas.hasPointerCapture(previous.pointerId)) { try { canvas.releasePointerCapture(previous.pointerId); } catch (_) {} } }
    function pointerUp(event) { if (!stroke || event.pointerId !== stroke.pointerId) return; event.preventDefault(); event.stopImmediatePropagation(); endStroke(false); }
    function pointerCancel(event) { if (stroke && event.pointerId === stroke.pointerId) endStroke(true); }
    function beforeRender() {
      if (!adoptRuntime()) return; var values = edits(context());
      if (!panel.open || !detail.open || !showVertices.checked || !values.some(function (row) { return row.absolute !== undefined || row.vertices && row.vertices.length; })) { if (pointRoot) pointRoot.visible = false; return; }
      var geometryKey = []; runtime.model.traverse(function (mesh) { if (mesh.isMesh && !mesh.userData.viewerHelper) { var index = mesh.geometry.index; if (index && !indexKeys.has(index)) indexKeys.set(index, ++indexGeneration); geometryKey.push(mesh.uuid + ":" + visible(mesh) + ":" + mesh.geometry.uuid + ":" + (index && indexKeys.get(index))); } });
      var key = json() + ":" + geometryKey.join("|");
      var T = global.THREE;
      if (!pointRoot && runtime.scene) { pointGeometry = new T.BufferGeometry(); pointRoot = new T.Points(pointGeometry, new T.PointsMaterial({ color: 0xffd35a, size: 6, sizeAttenuation: false, depthTest: true, depthWrite: false })); pointRoot.userData.viewerHelper = true; pointRoot.frustumCulled = false; pointRoot.renderOrder = 950; runtime.scene.add(pointRoot); }
      if (!pointRoot) return;
      if (key !== pointKey) {
        pointKey = key; pointPoseKey = ""; pointRefs = []; var lookup = {}; values.forEach(function (row) { if (row.absolute !== undefined || row.vertices) lookup[row.id] = row; });
        runtime.model.traverse(function (mesh) { var row = lookup[sourceId(mesh)]; if (!mesh.isMesh || mesh.userData.viewerHelper || !visible(mesh) || !row || !mapping(mesh) || mapping(mesh).vertexOrder !== "identity") return; var used = null; if (mesh.geometry.index) used = new Set(mesh.geometry.index.array); if (row.absolute !== undefined) { var indices = used ? Array.from(used) : Array.from({ length: mesh.geometry.attributes.position.count }, function (_, index) { return index; }); for (var i = 0; i < indices.length && pointRefs.length < 4096; i++) pointRefs.push({ mesh: mesh, vertex: indices[i] }); } else row.vertices.forEach(function (value) { if (value.vertex < mesh.geometry.attributes.position.count && (!used || used.has(value.vertex)) && pointRefs.length < 4096) pointRefs.push({ mesh: mesh, vertex: value.vertex }); }); });
        pointGeometry.setAttribute("position", new T.Float32BufferAttribute(new Float32Array(pointRefs.length * 3), 3));
      }
      runtime.model.updateMatrixWorld(true); var pose = poseKey(Array.from(new Set(pointRefs.map(function (ref) { return ref.mesh; }))));
      if (pose !== pointPoseKey) {
        pointPoseKey = pose; var positions = pointGeometry.attributes.position; scratch = scratch || new T.Vector3();
        pointRefs.forEach(function (ref, index) { global.ViewerMeshRuntime.vertexWorld(ref.mesh, ref.vertex, scratch); positions.setXYZ(index, scratch.x, scratch.y, scratch.z); }); positions.needsUpdate = true;
      }
      pointRoot.visible = pointRefs.length > 0;
    }
    function projectVertex(identity, index) {
      if (!adoptRuntime()) return null; var found = null, T = global.THREE, key = typeof identity === "string" ? identity : identity && String(identity.source) + ":" + String(identity.file) + ":" + String(identity.id);
      runtime.model.traverse(function (mesh) { if (!found && mesh.isMesh && !mesh.userData.viewerHelper && sourceId(mesh) === key && Number.isInteger(index) && index >= 0 && index < mesh.geometry.attributes.position.count) found = mesh; });
      if (!found) return null; runtime.model.updateMatrixWorld(true); var p = global.ViewerMeshRuntime.vertexWorld(found, index), q = p.clone().project(runtime.camera), rect = canvas.getBoundingClientRect(); return { x: rect.left + (q.x + 1) * .5 * rect.width, y: rect.top + (1 - q.y) * .5 * rect.height, depth: q.z, world: p.toArray() };
    }
    function handleShortcut(event) {
      var target = event.target, typing = target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable);
      var name = String(event.key).toLowerCase();
      if (typing || !(isSceneEditing() || panel.contains(document.activeElement)) || !(event.ctrlKey || event.metaKey) || event.altKey || name !== "z" && name !== "y") return false;
      if (event.shiftKey || name === "y") redo(); else undo(); if (event.preventDefault) event.preventDefault(); if (event.stopImmediatePropagation) event.stopImmediatePropagation(); else if (event.stopPropagation) event.stopPropagation(); return true;
    }
    document.addEventListener("keydown", handleShortcut, true);
    refresh();
    return { refresh: refresh, updateLanguage: function () { cachedCatalogue = null; cacheKey = ""; languageKey = ""; refresh(); }, beforeRender: beforeRender, beforeModelDispose: cleanupRuntime,
      isSceneEditing: isSceneEditing, setSceneEditing: setSceneEditing, handleShortcut: handleShortcut, undo: undo, redo: redo, projectVertex: projectVertex,
      getState: function () { var c = context(), values = edits(c); return { available: catalogue(c).meshes.length > 0, selected: select.value, edits: JSON.parse(json()), shaderEnabled: !!(c.materials && c.materials.getState().enabled), sceneEditing: isSceneEditing(), brushRadius: Number(radius.value), vertexWidth: Number(width.value), absoluteWidth: Number(absolute.value), undo: past.length, redo: future.length, editedVertices: vertexCount(values, c), performance: Object.assign({}, performanceState) }; },
      invalid: function () { return !!(number.validationMessage || width.validationMessage || absolute.validationMessage); },
      dispose: function () { disposed = true; document.removeEventListener("keydown", handleShortcut, true); cleanupRuntime(); panel.remove(); } };
  }
  global.ViewerOutlines = { create: create, checked: checked };
}(window));
