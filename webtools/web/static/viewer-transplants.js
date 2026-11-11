/* Real costume grafts: current wearer -> saved copy -> existing Unity tools. */
(function (global) {
  "use strict";
  var TEXT = {
    "Costume transplant": ["코스튬 이식", "衣装移植"],
    "Costume part transplant": ["코스튬 부분 이식", "衣装パーツ移植"],
    "Lower body replacement": ["하체 교체", "下半身の交換"],
    "Donor model": ["Donor 모델", "ドナーモデル"],
    "Choose donor costume": ["Donor 의상 불러오기", "ドナー衣装を選択"],
    "Load donor from game": ["게임에서 Donor 가져오기", "ゲームからドナーを選択"],
    "No donor selected.": ["Donor 의상을 선택해 주세요.", "ドナー衣装を選択してください。"],
    "Transplant": ["이식", "移植"], "Replace lower body": ["하체 교체", "下半身を交換"],
    "Part root bone": ["이식할 부분의 루트 본", "パーツのルートボーン"],
    "Choose a part": ["부분 선택", "パーツを選択"],
    "Upper cut Y": ["상단 절단면 Y", "上側の切断面 Y"],
    "Lower cut Y": ["하단 절단면 Y", "下側の切断面 Y"],
    "Cut preset": ["절단 범위 프리셋", "切断範囲プリセット"],
    "Knee to waist": ["무릎부터 허리까지", "膝から腰まで"],
    "Calf to waist": ["종아리부터 허리까지", "ふくらはぎから腰まで"],
    "Ankle to waist": ["발목부터 허리까지", "足首から腰まで"],
    "Custom range": ["직접 범위 지정", "範囲を指定"],
    "Replacement region": ["교체할 본 영역", "交換するボーン領域"],
    "Lower body": ["하체", "下半身"], "Lower body and belly": ["하체와 아랫배", "下半身と下腹部"],
    "Central body": ["몸통 중앙", "体の中心"],
    "The mesh between the blue lower plane and orange upper plane is replaced.": ["파란 하단 절단면과 주황 상단 절단면 사이의 메시를 교체합니다.", "青い下側の面とオレンジ色の上側の面の間のメッシュを交換します。"],
    "Uses the displayed wearer and preserves its current body edits in a new copy.": ["현재 표시된 모델에 이식하고 체형 편집을 반영한 새 복사본을 만듭니다.", "表示中のモデルに移植し、現在の体型編集を反映したコピーを作ります。"],
    "Use a single Unity model or a ZIP containing one model for transplanting.": ["이식에는 단일 Unity 모델이나 모델이 하나 들어 있는 ZIP을 사용하세요.", "移植には単独のUnityモデルか、モデルが1つのZIPを使用してください。"],
    "Preparing donor…": ["Donor 준비 중…", "ドナーを準備中…"],
    "Open a wearer model first.": ["먼저 이식받을 모델을 열어 주세요.", "先に移植先モデルを開いてください。"],
    "Transplanting…": ["이식 중…", "移植中…"],
    "Transplanted. The result is now displayed.": ["이식이 완료되어 결과를 표시합니다.", "移植が完了し、結果を表示しています。"],
    "The result was saved. Open it to inspect the transplant.": ["결과를 저장했습니다. 결과 열기로 이식 상태를 확인하세요.", "結果を保存しました。開いて移植を確認してください。"],
    "Open transplant result": ["이식 결과 열기", "移植結果を開く"],
    "The lower cut must be below the upper cut.": ["하단 절단면은 상단보다 낮아야 합니다.", "下側の切断面は上側より低くしてください。"],
    "The donor preview could not be displayed.": ["Donor 미리보기를 표시할 수 없습니다.", "ドナープレビューを表示できませんでした。"],
    "Correct invalid body values before transplanting.": ["유효하지 않은 체형 값을 수정한 뒤 이식해 주세요.", "体型の入力値を修正してから移植してください。"],
    "Save mesh edits before transplanting.": ["메시 편집을 저장한 뒤 이식해 주세요.", "メッシュの編集を保存してから移植してください。"]
  };
  Object.assign(TEXT, {
    "Match skin colour": ["피부색 자동 맞춤", "肌色を自動調整"],
    "Skin only (preserve outfit colours)": ["피부만 보정 (의상 색상 유지)", "肌だけ補正（衣装の色を維持）"],
    "Exclude separate accessories": ["분리된 작은 액세서리 제외", "分離した小さいアクセサリーを除外"],
    "Replacement selection": ["교체할 메시 범위", "交換するメッシュ範囲"],
    "Body skin": ["피부 메시", "肌メッシュ"],
    "Donor mesh": ["Donor 메시", "ドナーメッシュ"],
    "Wearer mesh": ["현재 모델의 교체할 메시", "移植先で交換するメッシュ"],
    "Whole mesh (include outfit)": ["전체 메시 (의상 포함)", "メッシュ全体（衣装を含む）"],
    "Whole lower body": ["하체 전체", "下半身全体"],
    "Preview height": ["미리보기 높이", "プレビューの高さ"],
    "Click a part on the donor model to select its bone subtree.": ["Donor 모델의 이식할 부분을 클릭하면 해당 부분의 본 묶음을 선택합니다.", "ドナーモデルの移植する部分をクリックしてボーン群を選択します。"],
    "Highlighted donor faces are inserted. Wearer faces crossing either cut are retained to prevent gaps.": ["강조된 Donor 면을 이식합니다. 절단면에 걸친 착용자 면은 틈이 생기지 않도록 유지합니다.", "強調されたドナー面を移植します。切断面をまたぐ着用者の面は隙間を防ぐため残します。"],
    "No selectable costume part at this point.": ["이 지점에서 선택할 수 있는 의상 부분이 없습니다.", "この位置に選択可能な衣装パーツがありません。"]
  });
  Object.assign(TEXT, {
    "Part selection": ["이식 부위 선택", "移植パーツの選択"],
    "Bones": ["본으로 선택", "ボーンで選択"],
    "Model / texture faces": ["모델·텍스처에서 면 선택", "モデル・テクスチャの面を選択"],
    "Add a bone": ["본 추가", "ボーンを追加"],
    "Include child bones": ["하위 본 함께 선택", "子ボーンも選択"],
    "Find a donor bone": ["Donor 본 검색", "ドナーボーンを検索"],
    "Clear part selection": ["부위 선택 해제", "パーツ選択を解除"],
    "Undo selection": ["선택 되돌리기", "選択を元に戻す"],
    "Redo selection": ["선택 다시 실행", "選択をやり直す"],
    "Start from selected bones": ["선택한 본의 면으로 시작", "選択ボーンの面から開始"],
    "Donor editing": ["Donor에서 선택", "ドナー上で選択"],
    "Orbit model": ["모델 회전", "モデルを回転"],
    "Paint faces": ["면 칠해서 선택", "面を塗って選択"],
    "Erase faces": ["면 선택 지우기", "面の選択を消す"],
    "Connected faces": ["연결된 면 선택", "つながった面を選択"],
    "Brush radius": ["브러시 크기", "ブラシ半径"],
    "Donor texture": ["Donor 텍스처", "ドナーテクスチャ"],
    "Material / submesh": ["머티리얼·하위 메시", "マテリアル・サブメッシュ"],
    "Texture zoom": ["텍스처 확대", "テクスチャ拡大"],
    "Move texture": ["텍스처 이동", "テクスチャを移動"],
    "Fit texture": ["텍스처 맞춤", "テクスチャを合わせる"],
    "Select multiple bones; selecting a parent also selects its descendants. Click the model to add a bone.": ["여러 본을 함께 선택할 수 있습니다. 하위 본 함께 선택을 켜면 부모와 자손을 선택합니다. 모델을 클릭해 본을 추가하세요.", "複数のボーンを選択できます。子ボーン選択を有効にすると親と子孫を選択します。モデルをクリックしてボーンを追加します。"],
    "Paint on the donor model or its UV texture. Green faces are transplanted together. Alt or right-drag rotates the model.": ["Donor 모델이나 UV 텍스처에 칠해 선택하세요. 초록색 면을 함께 이식합니다. Alt 또는 오른쪽 드래그로 모델을 회전합니다.", "ドナーモデルまたはUVテクスチャを塗って選択します。緑の面をまとめて移植します。Altまたは右ドラッグでモデルを回転します。"],
    "UV overlaps select every face at that texture position. Use the 3D model to select only the visible surface.": ["UV가 겹치면 같은 텍스처 위치의 면이 함께 선택됩니다. 보이는 표면만 선택하려면 3D 모델을 사용하세요.", "UVが重なる位置では全ての面を選択します。見えている表面だけを選ぶ場合は3Dモデルを使ってください。"],
    "No UV texture is available for this material.": ["이 머티리얼에는 표시할 UV 텍스처가 없습니다.", "このマテリアルには表示できるUVテクスチャがありません。"],
    "Select a donor region first.": ["먼저 이식할 Donor 부위를 선택하세요.", "移植するドナー領域を選択してください。"]
  });
  Object.assign(TEXT, {
    "Reuse empty UV areas": ["빈 UV 영역 재사용", "空きUV領域を再利用"],
    "Try the donor's original UV position first. If occupied, use an atlas or enable moving to another empty UV area. No padding is added.": ["Donor의 원래 UV 위치를 먼저 사용합니다. 겹치면 아틀라스로 합치거나 다른 빈 UV 영역으로 옮기기를 켜세요. 패딩은 추가하지 않습니다.", "ドナーの元のUV位置を優先します。重なる場合はアトラスに結合するか、別の空きUV領域への移動を有効にしてください。パディングは追加しません。"],
    "Move to another empty UV area": ["다른 빈 UV 영역으로 옮기기", "別の空きUV領域へ移動"],
    "If the original UV position is occupied, find another empty area without reducing source pixel detail. No padding is added.": ["원래 UV 위치가 사용 중이면 원본 픽셀의 세부 표현을 유지한 채 다른 빈 영역을 찾습니다. 패딩은 추가하지 않습니다.", "元のUV位置が使用中なら、元画像の細部を維持して別の空き領域を探します。パディングは追加しません。"]
  });
  TEXT["Selected bones"] = ["선택 본", "選択ボーン"];
  TEXT["Selected faces"] = ["이식할 면", "移植する面"];
  function selectedBoneManifest(parts, selected) {
    var names = Array.from(selected || []).sort(), covered = new Set(), roots = [];
    (parts || []).slice().sort(function (a, b) { return (a.depth || 0) - (b.depth || 0); }).forEach(function (part) {
      var subtree = part.bones || [part.value];
      if (!covered.has(part.value) && selected.has(part.value) && subtree.every(function (name) { return selected.has(name); })) {
        roots.push(part.value); subtree.forEach(function (name) { covered.add(name); });
      }
    });
    return covered.size === names.length ? { partRoots: roots, includeDescendants: true } : { partRoots: names, includeDescendants: false };
  }
  function setBoneSelection(parts, selected, name, includeChildren, add) {
    var part = (parts || []).find(function (row) { return row.value === name; });
    if (!part) return;
    (includeChildren ? part.bones || [name] : [name]).forEach(function (value) { if (add) selected.add(value); else selected.delete(value); });
  }
  Object.assign(TEXT, {
    "Undo transplant": ["이식 되돌리기", "移植を元に戻す"],
    "Redo transplant": ["이식 다시 실행", "移植をやり直す"],
    "Restoring model…": ["이전 모델 복원 중…", "モデルを復元中…"],
    "Transplant undone.": ["이식 전 모델로 되돌렸습니다.", "移植前のモデルに戻しました。"],
    "Transplant redone.": ["이식 결과를 다시 표시합니다.", "移植結果を再表示しました。"],
    "The viewer changed. The saved result was kept.": ["표시 모델이 변경되어 저장된 결과를 유지했습니다.", "表示モデルが変更されたため、保存済みの結果を保持しました。"],
    "This model cannot be restored safely.": ["이 모델의 이전 상태를 안전하게 복원할 수 없습니다.", "このモデルの以前の状態を安全に復元できません。"],
    "The original model files changed. The displayed model was kept.": ["원본 모델 파일이 변경되어 현재 표시 모델을 유지했습니다.", "元のモデルファイルが変更されたため、表示中のモデルを保持しました。"],
    "The original face could not be restored. The displayed model was kept.": ["원래 얼굴을 복원할 수 없어 현재 표시 모델을 유지했습니다.", "元の顔を復元できないため、表示中のモデルを保持しました。"]
  });
  function create(options) {
    options = options || {};
    var disposed = false, busy = false, jobId = "", events = null, entries = [];
    var undoHistory = [], redoHistory = [], historyIdentity = "", historySwitch = false, MAX_HISTORY = 8;
    function identity(c) {
      return JSON.stringify([c.modelId || "", c.loadedPaths || [], c.loadedVariants || [], c.autoFace, c.loadEpoch]);
    }
    function copy(value) { return JSON.parse(JSON.stringify(value)); }
    function viewerChanged() { var error = new Error("The viewer changed. The saved result was kept."); error.viewerStale = true; return error; }
    function checkpoint() {
      if (!options.captureCheckpoint || !options.restoreCheckpoint) throw new Error("This model cannot be restored safely.");
      var value = options.captureCheckpoint();
      if (!value) throw new Error("This model cannot be restored safely.");
      return copy(value);
    }
    function pushHistory(stack, item) { stack.push(item); if (stack.length > MAX_HISTORY) stack.shift(); }
    function synchronizeHistory(c) {
      if (historySwitch) return;
      var current = identity(c);
      if (historyIdentity && current !== historyIdentity) { undoHistory = []; redoHistory = []; }
      if (c.current || undoHistory.length || redoHistory.length) historyIdentity = current;
    }
    function t(key) {
      var lang = (document.documentElement.lang || "en").split("-")[0], value = TEXT[key];
      return value && (lang === "ko" || lang === "ja") ? value[lang === "ko" ? 0 : 1] : options.translate ? options.translate(key) : key;
    }
    function element(tag, attributes, children) {
      var node = document.createElement(tag);
      Object.keys(attributes || {}).forEach(function (key) {
        if (key === "text") { node.textContent = t(attributes[key]); if (TEXT[attributes[key]]) node.dataset.transplantLabel = attributes[key]; }
        else if (key === "className") node.className = attributes[key];
        else node.setAttribute(key, attributes[key]);
      });
      (children || []).forEach(function (child) { node.appendChild(child); }); return node;
    }
    function label(key, control) { return element("label", {}, [element("span", { "data-transplant-label": key, text: key }), control]); }
    function context() {
      if (options.context) return options.context() || {};
      var state = global.ModelViewer && global.ModelViewer.getState();
      return state ? { modelId: state.modelId, editing: global.ModelViewer.getEditingMetadata(),
        authoring: global.ModelViewer.getAuthoringState(), current: state.loaded && !state.loading,
        persistence: state.persistence } : {};
    }
    function authoring(c) { return c.authoring || c.rig && c.rig.getAuthoringState && c.rig.getAuthoringState(); }
    function status(entry, message, error) {
      entry.statusKey = message;
      var value = t(message); if (entry.status.textContent !== value) entry.status.textContent = value;
      if (entry.status.classList.contains("viewer-warning") !== !!error) entry.status.classList.toggle("viewer-warning", !!error);
    }
    function selectionSnapshot(entry) { return { bones: Array.from(entry.selectedBones).sort(), faces: Array.from(entry.selectedFaces).sort(function (a, b) { return a - b; }), mode: entry.selectionMode.value }; }
    function selectionChanged(entry, before) {
      var after = selectionSnapshot(entry);
      if (before && JSON.stringify(before) !== JSON.stringify(after)) {
        entry.selectionHistory.push(before); entry.selectionFuture = [];
        while (entry.selectionHistory.length > 12 || entry.selectionHistory.reduce(function (sum, value) { return sum + value.faces.length + value.bones.length; }, 0) > 1000000) entry.selectionHistory.shift();
      }
      entry.selectionRevision++; updatePartUI(entry); if (entry.preview) entry.preview.cuts(); refresh();
    }
    function mutateSelection(entry, operation) { var before = selectionSnapshot(entry); operation(); selectionChanged(entry, before); }
    function restoreSelection(entry, redo) {
      var source = redo ? entry.selectionFuture : entry.selectionHistory, destination = redo ? entry.selectionHistory : entry.selectionFuture;
      if (!source.length || busy || entry.inspecting) return;
      var value = source.pop(); destination.push(selectionSnapshot(entry));
      entry.selectedBones = new Set(value.bones); entry.selectedFaces = new Set(value.faces); entry.selectionMode.value = value.mode;
      selectionChanged(entry);
    }
    function boneFaces(entry) {
      var g = entry.geometry, result = new Set();
      if (!g || !g.skin || !g.boneNames || !entry.selectedBones.size) return result;
      var inPart = g.boneNames.map(function (name) { return entry.selectedBones.has(name); });
      var vertices = g.skin.map(function (weights) { return weights.reduce(function (sum, pair) { return sum + (inPart[pair[0]] ? pair[1] : 0); }, 0) >= .5; });
      g.triangles.forEach(function (face, index) { if (face.every(function (vertex) { return vertices[vertex]; })) result.add(index); });
      return result;
    }
    function updatePartUI(entry) {
      if (entry.operation !== "part") return;
      var faces = entry.selectionMode.value === "triangles";
      entry.boneControls.hidden = faces; entry.faceControls.hidden = !faces; entry.texturePanel.hidden = !faces || entry.inspecting;
      entry.partHint.dataset.transplantLabel = faces ? "Paint on the donor model or its UV texture. Green faces are transplanted together. Alt or right-drag rotates the model." : "Select multiple bones; selecting a parent also selects its descendants. Click the model to add a bone.";
      entry.partHint.textContent = t(entry.partHint.dataset.transplantLabel);
      entry.highlightedFaces = faces ? entry.selectedFaces : boneFaces(entry); entry.selectedTriangles = entry.highlightedFaces.size;
      (entry.boneRows || []).forEach(function (row) {
        var selected = entry.selectedBones.has(row.part.value), descendants = row.part.bones || [row.part.value], covered = descendants.filter(function (name) { return entry.selectedBones.has(name); }).length;
        row.input.checked = selected; row.input.indeterminate = covered > 0 && covered < descendants.length;
      });
      entry.selectionStatus.textContent = t("Selected bones") + ": " + entry.selectedBones.size + " · " + t("Selected faces") + ": " + entry.selectedTriangles;
      entry.selectionUndo.disabled = !entry.selectionHistory.length || busy; entry.selectionRedo.disabled = !entry.selectionFuture.length || busy;
      if (entry.preview) entry.preview.selectionModeChanged();
    }
    function fillPartChoices(entry, inspected) {
      entry.partOptions = inspected.parts || []; entry.donorSha256 = inspected.sha256; entry.donorSelectionFingerprint = inspected.selectionFingerprint;
      if (entry.operation !== "part") return;
      entry.selectedBones = new Set(); entry.selectedFaces = new Set(); entry.selectionHistory = []; entry.selectionFuture = []; entry.selectionRevision++;
      entry.parts.replaceChildren(element("option", { value: "", text: "Add a bone" }));
      entry.boneTree.replaceChildren(); entry.boneRows = [];
      entry.partOptions.forEach(function (part) {
        var option = element("option", { value: part.value }); option.textContent = new Array((part.depth || 0) + 1).join("　") + part.value; entry.parts.appendChild(option);
        var checkbox = element("input", { type: "checkbox", value: part.value, "aria-label": part.value });
        var text = element("span", {}); text.textContent = part.value;
        var row = element("label", { className: "viewer-transplant-bone-row", "data-bone": part.value }, [checkbox, text]);
        row.style.setProperty("--bone-depth", Math.min(16, part.depth || 0)); entry.boneTree.appendChild(row);
        checkbox.addEventListener("change", function () { if (busy || entry.inspecting) return; var add = checkbox.checked; mutateSelection(entry, function () { setBoneSelection(entry.partOptions, entry.selectedBones, part.value, entry.includeChildren.checked, add); }); });
        entry.boneRows.push({ part: part, input: checkbox, row: row });
      });
      entry.boneSearch.value = ""; updatePartUI(entry);
    }
    function refresh() {
      if (disposed) return;
      var c = context(), body = authoring(c), locked = busy || !!(c.persistence && c.persistence.busy) || !!(c.meshTools && c.meshTools.busy);
      synchronizeHistory(c);
      var ready = c.current && c.editing && c.editing.available && body && !(body.unsupported || []).length;
      var meshDirty = !!(c.meshTools && c.meshTools.dirty && (!c.getMeshEdits || c.meshTools.hasUnappliedSelection));
      ready = ready && !meshDirty;
      entries.forEach(function (entry) {
        var targets = c.targetMeshes || [], targetKey = JSON.stringify(targets);
        if (entry.targetMesh && entry.targetMeshKey !== targetKey) {
          entry.targetMeshKey = targetKey; var previous = entry.targetMesh.value;
          entry.targetMesh.replaceChildren(element("option", { value: "", text: "Body" }));
          targets.forEach(function (mesh) { entry.targetMesh.appendChild(element("option", { value: mesh.value, text: mesh.label })); });
          if (targets.some(function (mesh) { return mesh.value === previous; })) entry.targetMesh.value = previous;
          else { var bodyMesh = targets.find(function (mesh) { return /^Body(?:_|$)/i.test(mesh.label); }); entry.targetMesh.value = bodyMesh ? bodyMesh.value : ""; }
        }
        if (entry.pick.disabled !== locked) entry.pick.disabled = locked;
        if (entry.game.disabled !== locked) entry.game.disabled = locked;
        entry.donorMesh.disabled = locked || entry.inspecting || !entry.donor;
        entry.targetMesh.disabled = locked || entry.inspecting || !ready;
        if (entry.operation === "part") {
          var selectionLocked = locked || entry.inspecting || !entry.donor;
          [entry.selectionMode, entry.parts, entry.includeChildren, entry.boneSearch, entry.sceneAction, entry.brushRadius, entry.fromBones, entry.textureMaterial, entry.textureZoom, entry.texturePan, entry.textureFit, entry.selectionClear, entry.reuseEmptyUV].forEach(function (control) { control.disabled = selectionLocked; });
          entry.relocateEmptyUV.disabled = selectionLocked || !entry.reuseEmptyUV.checked;
          (entry.boneRows || []).forEach(function (row) { row.input.disabled = selectionLocked; });
          entry.selectionUndo.disabled = selectionLocked || !entry.selectionHistory.length; entry.selectionRedo.disabled = selectionLocked || !entry.selectionFuture.length;
        }
        var disabled = !!(locked || !ready || !entry.donor || entry.inspecting || entry.operation === "part" && !entry.selectedTriangles);
        if (entry.run.disabled !== disabled) entry.run.disabled = disabled;
        var cancelHidden = !entry.running || !!entry.opening;
        if (entry.cancel.hidden !== cancelHidden) entry.cancel.hidden = cancelHidden;
        var undoDisabled = !!(locked || !c.current || meshDirty || !undoHistory.length || !options.restoreCheckpoint);
        var redoDisabled = !!(locked || !c.current || meshDirty || !redoHistory.length || !options.restoreCheckpoint);
        if (entry.undo.disabled !== undoDisabled) entry.undo.disabled = undoDisabled;
        if (entry.redo.disabled !== redoDisabled) entry.redo.disabled = redoDisabled;
        var undoTitle = undoHistory.length ? t(undoHistory[undoHistory.length - 1].title) : "";
        var redoTitle = redoHistory.length ? t(redoHistory[redoHistory.length - 1].title) : "";
        if (entry.undo.title !== undoTitle) entry.undo.title = undoTitle;
        if (entry.redo.title !== redoTitle) entry.redo.title = redoTitle;
        if (meshDirty && !entry.running) status(entry, "Save mesh edits before transplanting.");
        if (!meshDirty && entry.statusKey === "Save mesh edits before transplanting.") status(entry, "");
        if (!meshDirty && !entry.donor && !entry.running && !entry.status.classList.contains("viewer-warning")) status(entry, ready ? "No donor selected." : "Open a wearer model first.");
      });
    }
    async function json(url, payload, signal) {
      var response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: signal });
      var data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText); return data;
    }
    function disposeObject(object) {
      if (!object) return;
      var textures = new Set();
      object.traverse(function (child) {
        if (child.geometry) child.geometry.dispose();
        var materials = Array.isArray(child.material) ? child.material : child.material ? [child.material] : [];
        materials.forEach(function (material) { Object.keys(material).forEach(function (key) { var value = material[key]; if (value && value.isTexture) textures.add(value); }); material.dispose(); });
      }); textures.forEach(function (texture) { texture.dispose(); });
    }
    function preview(entry) {
      if (entry.preview) return entry.preview;
      var THREE = global.THREE;
      if (!THREE || !THREE.GLTFLoader) throw new Error("The donor preview could not be displayed.");
      var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); renderer.setPixelRatio(Math.min(global.devicePixelRatio || 1, 1.5));
      renderer.setClearColor(0x172130, 1); renderer.outputEncoding = THREE.sRGBEncoding; entry.stage.replaceChildren(renderer.domElement);
      var scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(32, 1, .001, 1000);
      scene.add(new THREE.HemisphereLight(0xffffff, 0x657080, 2));
      var light = new THREE.DirectionalLight(0xffffff, .9); light.position.set(2, 3, 4); scene.add(light);
      var controls = new THREE.OrbitControls(camera, renderer.domElement); controls.enableDamping = false; controls.mouseButtons.RIGHT = THREE.MOUSE.ROTATE;
      var model = null, band = null, planes = [], size = null, selection = null, meshes = [], bindings = [], refs = {}, graph = null;
      var worldCache = {}, projected = null, projectedRect = "", visibility = {}, stageSize = "", lastMode = "", view = { zoom: 1, x: 0, y: 0 }, cursor = null, textureStroke = null, texturePointers = new Map(), sceneStroke = null, scenePointers = new Map();
      if (entry.operation === "part") { cursor = element("div", { id: "viewer-part-transplant-brush-cursor", className: "viewer-transplant-brush-cursor", hidden: "" }); document.body.appendChild(cursor); }
      function mapping(mesh) { return mesh.geometry.userData.viewerMesh || mesh.userData.viewerMesh || {}; }
      function isBody(mesh) { var map = mapping(mesh), g = entry.geometry; return !!(g && map.mesh && map.mesh.source === 0 && String(map.mesh.id) === String(g.mesh) && String(map.renderer) === String(g.renderer)); }
      function editable() { return entry.operation === "part" && !busy && !entry.inspecting && !!entry.donor && !!model; }
      function world(mesh) { return worldCache[mesh.uuid] || (worldCache[mesh.uuid] = new Array(mesh.geometry.attributes.position.count)); }
      function vertex(mesh, index) { var cached = world(mesh); return cached[index] || (cached[index] = global.ViewerMeshRuntime.vertexWorld(mesh, index)); }
      function invalidateProjection() { projected = null; visibility = {}; }
      function draw() {
        if (!entry.panel.open || entry.panel.hidden || !renderer.domElement.isConnected) return;
        var width = entry.stage.clientWidth, height = entry.stage.clientHeight;
        if (!width || !height) return;
        var key = width + ":" + height; if (stageSize !== key) { stageSize = key; invalidateProjection(); }
        renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix(); renderer.render(scene, camera);
      }
      function textureBinding() { return bindings.find(function (binding) { return binding.mesh.uuid === entry.textureMaterial.value; }) || null; }
      function textureUV(binding, vertexIndex) {
        var p = new THREE.Vector2().fromBufferAttribute(binding.mesh.geometry.attributes.uv, vertexIndex);
        if (binding.texture) { if (binding.texture.matrixAutoUpdate) binding.texture.updateMatrix(); binding.texture.transformUv(p); }
        return [p.x, p.y];
      }
      function uvPoint(point) { var width = entry.textureCanvas.width; return [(view.x + point[0] * view.zoom) * width, (view.y + point[1] * view.zoom) * width]; }
      function drawTexture() {
        if (entry.operation !== "part") return;
        var canvas = entry.textureCanvas, ctx = canvas.getContext("2d"), binding = textureBinding(), width = canvas.width;
        ctx.clearRect(0, 0, width, width); entry.textureZoom.value = String(view.zoom); entry.textureZoomText.textContent = Math.round(view.zoom * 100) + "%";
        if (!binding || !binding.mesh.geometry.attributes.uv) { entry.textureStatus.textContent = t("No UV texture is available for this material."); return; }
        entry.textureStatus.textContent = "";
        var image = binding.texture && binding.texture.image;
        if (image) { try { ctx.imageSmoothingEnabled = view.zoom < 2; ctx.drawImage(image, view.x * width, view.y * width, view.zoom * width, view.zoom * width); } catch (_) {} }
        var index = binding.mesh.geometry.index, faces = entry.highlightedFaces;
        ctx.lineWidth = .65; ctx.strokeStyle = global.ViewerUVColor ? global.ViewerUVColor.stroke(.55) : "rgba(235,242,255,.25)";
        for (var offset = 0; offset < index.count; offset += 3) {
          var points = [0, 1, 2].map(function (slot) { return uvPoint(textureUV(binding, index.getX(offset + slot))); });
          if (points.every(function (p) { return p[0] < 0; }) || points.every(function (p) { return p[0] > width; }) || points.every(function (p) { return p[1] < 0; }) || points.every(function (p) { return p[1] > width; })) continue;
          ctx.beginPath(); points.forEach(function (p, i) { if (i) ctx.lineTo(p[0], p[1]); else ctx.moveTo(p[0], p[1]); }); ctx.closePath();
          if (faces.has(binding.map.firstFace + offset / 3)) { ctx.fillStyle = "rgba(40,245,156,.52)"; ctx.fill(); } ctx.stroke();
        }
      }
      function highlight() {
        if (selection) { scene.remove(selection); disposeObject(selection); selection = null; }
        var values = [], runtime = global.ViewerMeshRuntime;
        if (!model || !runtime || !entry.geometry) return;
        var selected = entry.highlightedFaces;
        if (entry.operation === "lower") {
          var g = entry.geometry, scores = {}, mask = [], low = Number(entry.low.value), high = Number(entry.high.value);
          g.triangles.forEach(function (face, index) {
            var heights = face.map(function (v) { return g.positions[v][1]; }), take = Math.max.apply(null, heights) >= low && Math.min.apply(null, heights) <= high;
            if (entry.scope.value === "skin") take = take && face.every(function (v) { return g.anatomy[v]; }) && face.filter(function (v) { return g.regions[entry.region.value][v]; }).length >= 2;
            mask[index] = take; if (take) { var component = g.components[face[0]]; scores[component] = (scores[component] || 0) + 1; }
          });
          var threshold = Math.max(1, Math.max.apply(null, Object.values(scores).concat([0])) * .04); selected = new Set();
          mask.forEach(function (take, i) { if (take && (entry.scope.value !== "skin" || !entry.exclude.checked || scores[g.components[g.triangles[i][0]]] >= threshold)) selected.add(i); });
          entry.selectedTriangles = selected.size;
        }
        bindings.forEach(function (binding) {
          var index = binding.mesh.geometry.index;
          for (var offset = 0; offset < index.count; offset += 3) if (selected && selected.has(binding.map.firstFace + offset / 3)) [0, 1, 2].forEach(function (slot) { var point = vertex(binding.mesh, index.getX(offset + slot)); values.push(point.x, point.y, point.z); });
        });
        if (values.length) {
          var geometry = new THREE.BufferGeometry(); geometry.setAttribute("position", new THREE.Float32BufferAttribute(values, 3));
          selection = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: 0x35e8a5, transparent: true, opacity: .45, side: THREE.DoubleSide, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
          selection.userData.viewerHelper = true; selection.renderOrder = 50; scene.add(selection);
        }
        drawTexture();
      }
      function cuts() {
        highlight();
        if (entry.operation !== "lower" || !size) { draw(); return; }
        planes.forEach(function (plane) { scene.remove(plane); disposeObject(plane); }); planes = [];
        if (band) { scene.remove(band); disposeObject(band); band = null; }
        var low = Number(entry.low.value), high = Number(entry.high.value); if (!isFinite(low) || !isFinite(high) || low >= high) { draw(); return; }
        var extent = Math.max(size.x, size.z, .2) * 1.35;
        [low, high].forEach(function (height, index) { var plane = new THREE.Mesh(new THREE.PlaneGeometry(extent, extent), new THREE.MeshBasicMaterial({ color: index ? 0xffa44a : 0x42aaff, transparent: true, opacity: .32, side: THREE.DoubleSide, depthWrite: false })); plane.rotation.x = -Math.PI / 2; plane.position.y = height; scene.add(plane); planes.push(plane); });
        band = new THREE.Mesh(new THREE.BoxGeometry(extent, high - low, extent), new THREE.MeshBasicMaterial({ color: 0x5cb8f4, wireframe: true, transparent: true, opacity: .2, depthWrite: false })); band.position.y = (low + high) / 2; scene.add(band); draw();
      }
      function rebind() {
        bindings = []; refs = {}; graph = null; worldCache = {}; invalidateProjection();
        meshes.filter(isBody).forEach(function (mesh) {
          var map = mapping(mesh), geometry = mesh.geometry;
          if (map.vertexOrder !== "identity" || !geometry.index || geometry.index.count / 3 !== map.faceCount || geometry.attributes.position.count !== map.vertexCount) return;
          var material = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material, texture = material && material.map;
          var binding = { mesh: mesh, map: map, texture: texture }; bindings.push(binding);
          for (var index = 0; index < map.faceCount; index++) refs[map.firstFace + index] = { binding: binding, local: index };
        });
        if (entry.operation === "part") {
          entry.textureMaterial.replaceChildren();
          bindings.forEach(function (binding) { var material = Array.isArray(binding.mesh.material) ? binding.mesh.material[0] : binding.mesh.material; var option = element("option", { value: binding.mesh.uuid }); option.textContent = (material && material.name || t("Material / submesh")) + " · " + (binding.map.submesh + 1); entry.textureMaterial.appendChild(option); });
          view = { zoom: 1, x: 0, y: 0 }; updatePartUI(entry);
        }
        cuts();
      }
      function nearestRay(ray) {
        var hit = null; meshes.forEach(function (mesh) { if (!mesh.geometry || !mesh.geometry.attributes.position) return; var next = global.ViewerMeshRuntime.raycastMesh(ray, mesh, { vertices: world(mesh) }); if (next && (!hit || next.distance < hit.distance)) hit = next; }); return hit;
      }
      function rayAt(x, y) { var rect = renderer.domElement.getBoundingClientRect(), ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((x - rect.left) / rect.width * 2 - 1, -(y - rect.top) / rect.height * 2 + 1), camera); return ray; }
      function sourceHit(x, y) { var hit = nearestRay(rayAt(x, y).ray); return hit && isBody(hit.object) ? hit : null; }
      function connect(seeds, binding, erase) {
        if (!global.ViewerMeshTools || !entry.geometry) return;
        if (!graph) graph = global.ViewerMeshTools.buildFaceConnectivity(entry.geometry, false);
        var faces = global.ViewerMeshTools.connectedFaces(graph, seeds, function (face) { return !binding || refs[face] && refs[face].binding === binding; });
        faces.forEach(function (face) { if (erase) entry.selectedFaces.delete(face); else entry.selectedFaces.add(face); });
      }
      function moveCursor(event, canvas) {
        if (!cursor) return;
        var active = editable() && entry.selectionMode.value === "triangles" && entry.sceneAction.value !== "orbit" && scenePointers.size < 2 && texturePointers.size < 2 && !(canvas === entry.textureCanvas && entry.texturePan.checked);
        cursor.hidden = !active; if (!active) return;
        var radius = +entry.brushRadius.value || 20; cursor.style.left = event.clientX - radius + "px"; cursor.style.top = event.clientY - radius + "px"; cursor.style.width = cursor.style.height = radius * 2 + "px"; cursor.style.borderColor = entry.sceneAction.value === "erase" ? "#ff6f8c" : "#35e8a5";
      }
      function projectedFaces() {
        var rect = renderer.domElement.getBoundingClientRect(), key = [rect.left, rect.top, rect.width, rect.height].join(":");
        if (projected && projectedRect === key) return projected;
        projectedRect = key; projected = [];
        bindings.forEach(function (binding) { var index = binding.mesh.geometry.index, cache = [];
          function point(i) { if (!cache[i]) { var p = vertex(binding.mesh, i).clone().project(camera); cache[i] = [rect.left + (p.x + 1) * rect.width / 2, rect.top + (1 - p.y) * rect.height / 2, p.z]; } return cache[i]; }
          for (var offset = 0; offset < index.count; offset += 3) { var vertices = [0, 1, 2].map(function (slot) { return index.getX(offset + slot); }); projected.push({ source: binding.map.firstFace + offset / 3, binding: binding, vertices: vertices, points: vertices.map(point) }); }
        }); return projected;
      }
      function stampScene(event) {
        var hit = sourceHit(event.clientX, event.clientY); if (!hit) return;
        var binding = bindings.find(function (b) { return b.mesh === hit.object; }), face = binding.map.firstFace + hit.faceIndex, erase = entry.sceneAction.value === "erase" || event.shiftKey;
        if (entry.sceneAction.value === "connected") { connect([face], binding, erase); return; }
        var radius = +entry.brushRadius.value || 20;
        projectedFaces().forEach(function (candidate) {
          if (candidate.points.some(function (p) { return p[2] < -1 || p[2] > 1; }) || !global.ViewerMeshTools.circleIntersectsTriangle(event.clientX, event.clientY, radius, candidate.points[0], candidate.points[1], candidate.points[2])) return;
          var visible = visibility[candidate.source];
          if (visible === undefined) {
            var centre = candidate.vertices.reduce(function (sum, v) { return sum.add(vertex(candidate.binding.mesh, v)); }, new THREE.Vector3()).divideScalar(3), p = centre.clone().project(camera), ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2(p.x, p.y), camera);
            var surface = nearestRay(ray.ray); visible = visibility[candidate.source] = !!(surface && surface.object === candidate.binding.mesh && candidate.binding.map.firstFace + surface.faceIndex === candidate.source);
          }
          if (visible || candidate.source === face) { if (erase) entry.selectedFaces.delete(candidate.source); else entry.selectedFaces.add(candidate.source); }
        });
      }
      function pickBone(event) {
        var hit = sourceHit(event.clientX, event.clientY); if (!hit || !hit.object.isSkinnedMesh) return;
        var mesh = hit.object, si = mesh.geometry.attributes.skinIndex, sw = mesh.geometry.attributes.skinWeight, weights = {};
        [hit.face.a, hit.face.b, hit.face.c].forEach(function (v, slot) { ["X", "Y", "Z", "W"].forEach(function (axis) { var bone = mesh.skeleton.bones[si["get" + axis](v)]; if (bone) { var name = bone.userData.originalName || bone.name; weights[name] = (weights[name] || 0) + sw["get" + axis](v) * hit.barycoord.getComponent(slot); } }); });
        var name = Object.keys(weights).sort(function (a, b) { return weights[b] - weights[a]; })[0];
        if (!(entry.partOptions || []).some(function (p) { return p.value === name; })) { status(entry, "No selectable costume part at this point."); return; }
        mutateSelection(entry, function () { setBoneSelection(entry.partOptions, entry.selectedBones, name, entry.includeChildren.checked, !event.shiftKey); }); entry.parts.value = name; status(entry, "");
      }
      function selectionModeChanged() {
        var faces = entry.operation === "part" && entry.selectionMode.value === "triangles";
        controls.enabled = !faces || entry.sceneAction.value === "orbit";
        renderer.domElement.style.cursor = faces && entry.sceneAction.value !== "orbit" ? "crosshair" : "grab";
        var key = faces + ":" + (entry.sceneAction && entry.sceneAction.value); if (cursor && lastMode !== key) cursor.hidden = true; lastMode = key;
      }
      var down = null;
      renderer.domElement.addEventListener("pointerdown", function (event) {
        if (!editable()) return; down = [event.clientX, event.clientY, event.button];
        var edit = entry.selectionMode.value === "triangles" && entry.sceneAction.value !== "orbit" && !event.altKey && event.button === 0;
        if (!edit) { controls.enabled = true; return; }
        event.preventDefault(); event.stopImmediatePropagation(); renderer.domElement.setPointerCapture(event.pointerId); scenePointers.set(event.pointerId, [event.clientX, event.clientY]);
        if (scenePointers.size > 1) {
          if (sceneStroke && sceneStroke.before) { entry.selectedFaces = new Set(sceneStroke.before.faces); selectionChanged(entry); }
          var points = Array.from(scenePointers.values()); sceneStroke = { kind: "pinch", distance: Math.max(1, Math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1])), position: camera.position.clone(), target: controls.target.clone() }; if (cursor) cursor.hidden = true; return;
        }
        controls.enabled = false; sceneStroke = { kind: event.pointerType === "touch" ? "pending" : "paint", before: selectionSnapshot(entry), generation: entry.generation };
        if (sceneStroke.kind === "paint") { stampScene(event); updatePartUI(entry); cuts(); }
      }, true);
      renderer.domElement.addEventListener("pointermove", function (event) {
        moveCursor(event, renderer.domElement); if (!scenePointers.has(event.pointerId) || !sceneStroke) return;
        event.preventDefault(); event.stopImmediatePropagation(); scenePointers.set(event.pointerId, [event.clientX, event.clientY]);
        if (sceneStroke.kind === "pinch" && scenePointers.size > 1) { var points = Array.from(scenePointers.values()), factor = sceneStroke.distance / Math.max(1, Math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1])); camera.position.copy(sceneStroke.position).sub(sceneStroke.target).multiplyScalar(Math.max(.1, Math.min(10, factor))).add(sceneStroke.target); camera.lookAt(controls.target); invalidateProjection(); draw(); return; }
        if (!sceneStroke.before || sceneStroke.generation !== entry.generation) return;
        if (sceneStroke.kind === "pending" && down && Math.hypot(event.clientX - down[0], event.clientY - down[1]) < 4) return;
        sceneStroke.kind = "paint"; stampScene(event); updatePartUI(entry); cuts();
      }, true);
      function endScene(event) {
        if (scenePointers.has(event.pointerId)) {
          event.preventDefault(); event.stopImmediatePropagation(); scenePointers.delete(event.pointerId); var previous = sceneStroke;
          if (previous && previous.before && previous.generation === entry.generation) { if (previous.kind === "pending" && event.type === "pointerup") stampScene(event); selectionChanged(entry, previous.before); }
          sceneStroke = scenePointers.size ? { kind: "pinch" } : null; if (!scenePointers.size) selectionModeChanged(); return;
        }
        if (editable() && entry.selectionMode.value === "bones" && event.type === "pointerup" && down && down[2] === 0 && Math.hypot(event.clientX - down[0], event.clientY - down[1]) <= 5) pickBone(event);
        down = null; Promise.resolve().then(selectionModeChanged);
      }
      ["pointerup", "pointercancel", "lostpointercapture"].forEach(function (name) { renderer.domElement.addEventListener(name, endScene, true); });
      renderer.domElement.addEventListener("pointerleave", function () { if (cursor) cursor.hidden = true; });
      renderer.domElement.addEventListener("wheel", function (event) {
        if (!editable() || entry.selectionMode.value !== "triangles" || entry.sceneAction.value === "orbit") return;
        event.preventDefault(); event.stopImmediatePropagation();
        camera.position.sub(controls.target).multiplyScalar(Math.exp(Math.max(-1, Math.min(1, event.deltaY * .001)))).add(controls.target); camera.lookAt(controls.target); invalidateProjection(); draw();
      }, { passive: false, capture: true });
      function setView(value) { view = { zoom: Math.max(1, Math.min(16, value.zoom)), x: 0, y: 0 }; view.x = Math.max(1 - view.zoom, Math.min(0, value.x)); view.y = Math.max(1 - view.zoom, Math.min(0, value.y)); drawTexture(); }
      function texturePosition(event) { var r = entry.textureCanvas.getBoundingClientRect(); return [(event.clientX - r.left) / r.width, (event.clientY - r.top) / r.height]; }
      function stampTexture(point, connected, erase) {
        var binding = textureBinding(); if (!binding || !binding.mesh.geometry.attributes.uv) return;
        var uv = [(point[0] - view.x) / view.zoom, (point[1] - view.y) / view.zoom], radius = connected ? 0 : (+entry.brushRadius.value || 20) / entry.textureCanvas.getBoundingClientRect().width / view.zoom, seeds = [], index = binding.mesh.geometry.index;
        for (var offset = 0; offset < index.count; offset += 3) { var tri = [0, 1, 2].map(function (slot) { return textureUV(binding, index.getX(offset + slot)); }); if (global.ViewerMeshTools.circleIntersectsTriangle(uv[0], uv[1], radius, tri[0], tri[1], tri[2])) { var face = binding.map.firstFace + offset / 3; if (connected) seeds.push(face); else if (erase) entry.selectedFaces.delete(face); else entry.selectedFaces.add(face); } }
        if (connected) connect(seeds, binding, erase);
      }
      if (entry.operation === "part") {
        entry.textureMaterial.addEventListener("change", drawTexture);
        entry.textureZoom.addEventListener("input", function () { setView(global.ViewerMeshTools.zoomView(view, +entry.textureZoom.value)); });
        entry.textureFit.addEventListener("click", function () { setView({ zoom: 1, x: 0, y: 0 }); });
        entry.textureCanvas.addEventListener("wheel", function (event) { if (!editable()) return; event.preventDefault(); setView(global.ViewerMeshTools.zoomView(view, view.zoom * Math.exp(-event.deltaY * .002), texturePosition(event))); if (cursor) cursor.hidden = true; }, { passive: false });
        entry.textureCanvas.addEventListener("pointerdown", function (event) {
          if (!editable() || event.button > 2) return; event.preventDefault(); entry.textureCanvas.setPointerCapture(event.pointerId);
          var point = texturePosition(event); texturePointers.set(event.pointerId, point);
          if (texturePointers.size > 1) { if (textureStroke && textureStroke.before) { entry.selectedFaces = new Set(textureStroke.before.faces); selectionChanged(entry); } var points = Array.from(texturePointers.values()); textureStroke = { kind: "pinch", distance: Math.max(.0001, Math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1])), centre: [(points[0][0] + points[1][0]) / 2, (points[0][1] + points[1][1]) / 2], view: Object.assign({}, view) }; if (cursor) cursor.hidden = true; return; }
          var pan = entry.texturePan.checked || entry.sceneAction.value === "orbit" || event.altKey || event.button > 0;
          textureStroke = { kind: pan ? "pan" : event.pointerType === "touch" ? "pending" : "paint", anchor: point, view: Object.assign({}, view), before: pan ? null : selectionSnapshot(entry), erase: entry.sceneAction.value === "erase" || event.shiftKey, connected: entry.sceneAction.value === "connected" };
          if (textureStroke.kind === "paint") { stampTexture(point, textureStroke.connected, textureStroke.erase); updatePartUI(entry); cuts(); }
        });
        entry.textureCanvas.addEventListener("pointermove", function (event) {
          moveCursor(event, entry.textureCanvas); if (!texturePointers.has(event.pointerId) || !textureStroke) return; event.preventDefault(); var point = texturePosition(event); texturePointers.set(event.pointerId, point);
          if (textureStroke.kind === "pinch" && texturePointers.size > 1) { var points = Array.from(texturePointers.values()), centre = [(points[0][0] + points[1][0]) / 2, (points[0][1] + points[1][1]) / 2], zoom = Math.max(1, Math.min(16, textureStroke.view.zoom * Math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1]) / textureStroke.distance)); setView({ zoom: zoom, x: centre[0] - (textureStroke.centre[0] - textureStroke.view.x) / textureStroke.view.zoom * zoom, y: centre[1] - (textureStroke.centre[1] - textureStroke.view.y) / textureStroke.view.zoom * zoom }); return; }
          if (textureStroke.kind === "pan") { setView({ zoom: textureStroke.view.zoom, x: textureStroke.view.x + point[0] - textureStroke.anchor[0], y: textureStroke.view.y + point[1] - textureStroke.anchor[1] }); return; }
          if (!textureStroke.before || textureStroke.connected) return;
          if (textureStroke.kind === "pending" && Math.hypot(point[0] - textureStroke.anchor[0], point[1] - textureStroke.anchor[1]) * entry.textureCanvas.getBoundingClientRect().width < 4) return;
          textureStroke.kind = "paint"; stampTexture(point, false, textureStroke.erase); updatePartUI(entry); cuts();
        });
        function endTexture(event) {
          if (!texturePointers.has(event.pointerId)) return; var point = texturePointers.get(event.pointerId), previous = textureStroke; texturePointers.delete(event.pointerId);
          if (previous && previous.before) { if (previous.kind === "pending" && event.type === "pointerup") stampTexture(point, previous.connected, previous.erase); selectionChanged(entry, previous.before); }
          textureStroke = texturePointers.size ? { kind: "pan", anchor: Array.from(texturePointers.values())[0], view: Object.assign({}, view) } : null;
        }
        ["pointerup", "pointercancel", "lostpointercapture"].forEach(function (name) { entry.textureCanvas.addEventListener(name, endTexture); });
        entry.textureCanvas.addEventListener("pointerleave", function () { if (cursor) cursor.hidden = true; }); entry.textureCanvas.addEventListener("contextmenu", function (event) { event.preventDefault(); });
      }
      controls.addEventListener("change", function () { invalidateProjection(); draw(); }); var observer = new ResizeObserver(draw); observer.observe(entry.stage); entry.panel.addEventListener("toggle", draw);
      entry.preview = {
        draw: draw, cuts: cuts, rebind: rebind, drawTexture: drawTexture, selectionModeChanged: selectionModeChanged,
        getTextureView: function () { return { zoom: view.zoom, x: view.x, y: view.y, submesh: textureBinding() && textureBinding().map.submesh }; },
        set: function (object) {
          if (model) { scene.remove(model); disposeObject(model); } model = object; scene.add(model); model.updateMatrixWorld(true);
          meshes = []; model.traverse(function (child) { if (child.isMesh) meshes.push(child); if (child.isSkinnedMesh) child.frustumCulled = false; });
          var bounds = new THREE.Box3().setFromObject(model); size = bounds.getSize(new THREE.Vector3());
          var centre = bounds.getCenter(new THREE.Vector3()), distance = Math.max(size.x, size.y, size.z, .1) / (2 * Math.tan(camera.fov * Math.PI / 360)) * 1.18;
          controls.target.copy(centre); camera.position.copy(centre).add(new THREE.Vector3(distance * .2, distance * .05, distance)); camera.lookAt(centre); controls.update(); rebind();
        },
        dispose: function () { observer.disconnect(); entry.panel.removeEventListener("toggle", draw); controls.dispose(); disposeObject(model); planes.forEach(disposeObject); disposeObject(band); disposeObject(selection); if (cursor) cursor.remove(); renderer.dispose(); renderer.forceContextLoss(); }
      }; return entry.preview;
    }
    async function chooseDonor(entry, paths, variants) {
      if (busy || disposed || !paths || paths.length !== 1) return;
      var token = ++entry.generation;
      if (entry.request) entry.request.abort();
      var controller = new AbortController(); entry.request = controller;
      entry.donor = paths[0]; entry.variant = variants && variants[0] || variants && variants["0"] || "primary";
      entry.file.value = String(paths[0]).replace(/\\/g, "/").split("/").pop();
      entry.inspecting = true; entry.stage.hidden = true; if (entry.operation === "part") entry.texturePanel.hidden = true; status(entry, "Preparing donor…"); refresh();
      try {
        var inspected = await json("/api/viewer/transplant/inspect", { donor: entry.donor, variant: entry.variant }, controller.signal);
        if (token !== entry.generation || disposed) return;
        entry.geometry = inspected.geometry; fillPartChoices(entry, inspected);
        entry.donorMesh.replaceChildren();
        (inspected.renderers || []).forEach(function (mesh) { entry.donorMesh.appendChild(element("option", { value: mesh.value, text: mesh.label })); });
        entry.donorMesh.value = inspected.geometry.renderer;
        var payload = { paths: [entry.donor], rigged: true, auto_face: true, preview_only: true };
        if (entry.variant === "unmasked") payload.archive_variants = { 0: entry.variant };
        var prepared = await json("/api/viewer/prepare", payload, controller.signal);
        if (!/^\/api\/viewer\/model\/[a-f0-9]{32}\.glb$/.test(prepared.url || "")) throw new Error("The donor preview could not be displayed.");
        var response = await fetch(prepared.url, { signal: controller.signal });
        if (!response.ok || Number(response.headers.get("Content-Length")) > 64 * 1024 * 1024) throw new Error("The donor preview could not be displayed.");
        var bytes = await response.arrayBuffer();
        if (bytes.byteLength > 64 * 1024 * 1024) throw new Error("The donor preview could not be displayed.");
        var gltf = await new Promise(function (resolve, reject) { new global.THREE.GLTFLoader().parse(bytes, "", resolve, reject); });
        if (disposed || token !== entry.generation) { disposeObject(gltf.scene); return; }
        var nodes = {}; gltf.scene.traverse(function (object) { if (object.userData.elichika_node !== undefined) nodes[String(object.userData.elichika_node)] = object; });
        ((prepared.rig && prepared.rig.scaling || {}).components || []).forEach(function (component) {
          (component.entries || []).forEach(function (saved) {
            var object = nodes[String(saved.node)], value = saved.kind === "rotation" ? saved.scaledQuaternion : saved.scaled;
            if (saved.supported && object && Array.isArray(value)) {
              var property = saved.kind === "rotation" ? "quaternion" : saved.kind;
              if (object[property] && object[property].fromArray) object[property].fromArray(value);
            }
          });
        });
        preview(entry).set(gltf.scene); entry.stage.hidden = false; status(entry, "");
      } catch (error) {
        if (token === entry.generation && error.name !== "AbortError") { entry.donor = ""; status(entry, error.message, true); }
      } finally { if (token === entry.generation) { entry.inspecting = false; entry.request = null; if (entry.operation === "part") updatePartUI(entry); refresh(); } }
    }
    function finish(entry) {
      if (events) events.close(); events = null; jobId = ""; busy = false; entry.running = false; entry.opening = false;
      entry.progress.hidden = true; if (options.busyChanged) options.busyChanged(false); refresh();
    }
    async function run(entry) {
      if (entry.run.disabled || busy) return;
      var c = context(), authored = authoring(c);
      if (!c.current || !c.editing || !authored) return;
      if (c.meshTools && (c.meshTools.busy || c.meshTools.dirty && (!c.getMeshEdits || c.meshTools.hasUnappliedSelection))) { status(entry, "Save mesh edits before transplanting.", true); return; }
      if (authored.unsupported && authored.unsupported.length) { status(entry, authored.unsupported[0], true); return; }
      var low = Number(entry.low.value), high = Number(entry.high.value);
      if (!isFinite(low) || !isFinite(high) || low >= high) { status(entry, "The lower cut must be below the upper cut.", true); return; }
      var state = JSON.parse(JSON.stringify(authored)); delete state.unsupported;
      var payload = { token: c.editing.token, state: state, donor: entry.donor, variant: entry.variant || "primary", operation: entry.operation,
        partRoot: entry.operation === "part" ? entry.parts.value : "", cutLow: low, cutHigh: high, region: entry.region.value,
        matchSkin: entry.matchSkin.checked, skinOnly: entry.skinOnly.checked, excludeAccessories: entry.exclude.checked,
        selectionScope: entry.scope.value, donorRenderer: entry.geometry && entry.geometry.renderer || "", targetRenderer: entry.targetMesh.value };
      var meshState = c.getMeshEdits ? c.getMeshEdits() : null;
      if (meshState && meshState.meshes && meshState.meshes.length) payload.mesh_state = meshState;
      if (entry.operation === "part") {
        payload.reuseEmptyUV = entry.reuseEmptyUV.checked;
        payload.relocateEmptyUV = entry.relocateEmptyUV.checked;
        var manifest = selectedBoneManifest(entry.partOptions, entry.selectedBones);
        payload.partRoot = manifest.partRoots[0] || ""; payload.partSelectionMode = entry.selectionMode.value;
        payload.partRoots = manifest.partRoots; payload.includeDescendants = manifest.includeDescendants;
        payload.triangleIndices = entry.selectionMode.value === "triangles" ? Array.from(entry.selectedFaces).sort(function (a, b) { return a - b; }) : [];
        payload.donorSha256 = entry.donorSha256; payload.donorMesh = entry.geometry.mesh; payload.donorSelectionFingerprint = entry.donorSelectionFingerprint;
      }
      var fingerprint = JSON.stringify(authored), modelId = c.modelId, sourceIdentity = identity(c), before;
      try { before = checkpoint(); } catch (error) { status(entry, error.message, true); return; }
      busy = true; entry.running = true; entry.log.textContent = ""; entry.log.hidden = false; entry.progress.hidden = false; entry.progress.removeAttribute("value"); entry.result.hidden = true;
      if (options.busyChanged) options.busyChanged(true); status(entry, "Transplanting…"); refresh();
      try {
        var data = await json("/api/viewer/transplant/run", payload);
        if (!/^[a-f0-9]{12}$/.test(data.job_id || "")) throw new Error("The costume operation could not be started.");
        jobId = data.job_id; events = new EventSource("/api/jobs/" + jobId + "/events");
        events.onmessage = async function (message) {
          if (disposed || !entry.running) return;
          try {
            var item = JSON.parse(message.data);
            if (item.type === "log") entry.log.textContent = (entry.log.textContent + String(item.line || "") + "\n").slice(-20000);
            if (item.type === "progress" && item.total > 0) { entry.progress.max = item.total; entry.progress.value = item.done; }
            if (item.type === "transplant") entry.resultVariant = item.variant || "primary";
            if (item.type !== "done") return;
            if (events) events.close(); events = null; jobId = "";
            if (item.status !== "done") { finish(entry); status(entry, item.summary || "Cancelled", item.status === "error"); return; }
            var paths = item.output_paths;
            if (!Array.isArray(paths) || paths.length !== 1 || typeof paths[0] !== "string") throw new Error("The costume operation did not publish a model.");
            entry.resultPaths = paths; entry.result.hidden = false;
            var now = context();
            if (now.current && now.modelId === modelId && identity(now) === sourceIdentity && JSON.stringify(authoring(now)) === fingerprint &&
                (!c.getMeshEdits || JSON.stringify(now.getMeshEdits && now.getMeshEdits()) === JSON.stringify(meshState))) {
              await openResult(entry, before, sourceIdentity); status(entry, "Transplanted. The result is now displayed.");
            } else { finish(entry); status(entry, "The result was saved. Open it to inspect the transplant."); }
          } catch (error) { finish(entry); status(entry, error.message, true); }
        };
        events.onerror = function () { if (events && events.readyState === EventSource.CLOSED) { finish(entry); status(entry, "The costume operation connection closed. Check the server log.", true); } };
      } catch (error) { finish(entry); status(entry, error.message, true); }
    }
    async function openResult(entry, before, expectedIdentity) {
      if (historySwitch || busy && !entry.running) return;
      var c = context();
      if (!entry.running && (!c.current || c.meshTools && (c.meshTools.busy || c.meshTools.dirty && (!c.getMeshEdits || c.meshTools.hasUnappliedSelection)))) { status(entry, "Save mesh edits before transplanting.", true); return; }
      before = before || checkpoint(); expectedIdentity = expectedIdentity || identity(c);
      var variants = /\.zip$/i.test(entry.resultPaths[0]) && entry.resultVariant === "unmasked" ? { 0: "unmasked" } : null;
      busy = true; historySwitch = true; entry.opening = true; if (options.busyChanged) options.busyChanged(true); refresh();
      try {
        if (identity(context()) !== expectedIdentity) throw viewerChanged();
        var committed = options.openFiles ? await options.openFiles(entry.resultPaths, variants, before) : false;
        var after = context();
        if (committed === false || !after.current || JSON.stringify(after.loadedPaths || []) !== JSON.stringify(entry.resultPaths)) throw viewerChanged();
        pushHistory(undoHistory, { checkpoint: before, title: entry.title }); redoHistory = [];
        historyIdentity = identity(after);
      } catch (error) {
        if (!error.viewerStale && context().modelId === c.modelId && JSON.stringify(context().loadedPaths || []) === JSON.stringify(c.loadedPaths || [])) historyIdentity = identity(context());
        throw error;
      } finally { historySwitch = false; finish(entry); }
    }
    async function restoreHistory(entry, redo) {
      var source = redo ? redoHistory : undoHistory, destination = redo ? undoHistory : redoHistory;
      if (busy || !source.length || (redo ? entry.redo : entry.undo).disabled) return;
      var current;
      try { current = checkpoint(); } catch (error) { status(entry, error.message, true); return; }
      var step = source[source.length - 1], origin = context(), expected = identity(origin);
      busy = true; historySwitch = true; if (options.busyChanged) options.busyChanged(true); status(entry, "Restoring model…"); refresh();
      try {
        if (identity(context()) !== expected) throw viewerChanged();
        var restored = await options.restoreCheckpoint(copy(step.checkpoint), current);
        if (restored === false || !context().current) throw viewerChanged();
        source.pop(); pushHistory(destination, { checkpoint: current, title: step.title }); historyIdentity = identity(context());
        status(entry, redo ? "Transplant redone." : "Transplant undone.");
      } catch (error) {
        if (!error.viewerStale && context().modelId === origin.modelId && JSON.stringify(context().loadedPaths || []) === JSON.stringify(origin.loadedPaths || [])) historyIdentity = identity(context());
        status(entry, error.message, true);
      }
      finally { historySwitch = false; busy = false; if (options.busyChanged) options.busyChanged(false); refresh(); }
    }
    function addPanel(operation, id, title) {
      var entry = { operation: operation, title: title, generation: 0, donor: "", variant: "primary", inspecting: false, running: false, resultPaths: [],
        selectedBones: new Set(), selectedFaces: new Set(), highlightedFaces: new Set(), selectionRevision: 0, selectionHistory: [], selectionFuture: [] };
      entry.panel = element("details", { id: id, className: "viewer-adjustments viewer-transplant-panel", "data-panel-key": id });
      entry.panel.appendChild(element("summary", { "data-transplant-label": title, text: title }));
      entry.panel.appendChild(element("p", { className: "viewer-render-note", "data-transplant-label": "Uses the displayed wearer and preserves its current body edits in a new copy.", text: "Uses the displayed wearer and preserves its current body edits in a new copy." }));
      entry.file = element("input", { type: "text", readonly: "", "aria-label": t("Donor model") });
      entry.pick = element("button", { type: "button", "data-transplant-label": "Choose donor costume", text: "Choose donor costume" });
      entry.game = element("button", { type: "button", "data-transplant-label": "Load donor from game", text: "Load donor from game" });
      entry.panel.append(label("Donor model", entry.file), element("div", { className: "viewer-transplant-actions" }, [entry.pick, entry.game]));
      entry.stage = element("div", { className: "viewer-transplant-stage", hidden: "", "aria-label": t("Donor model") }); entry.panel.appendChild(entry.stage);
      entry.height = element("input", { type: "range", min: "180", max: "720", step: "10", value: "300", "aria-label": t("Preview height") });
      entry.panel.appendChild(label("Preview height", entry.height));
      entry.height.addEventListener("input", function () { entry.stage.style.height = entry.height.value + "px"; if (entry.preview) entry.preview.draw(); });
      entry.parts = element("select", { id: id + "-part" }); entry.parts.appendChild(element("option", { value: "", text: "Choose a part" }));
      if (operation === "part") {
        entry.selectionMode = element("select", { id: id + "-selection-mode" }, [element("option", { value: "bones", text: "Bones" }), element("option", { value: "triangles", text: "Model / texture faces" })]);
        entry.panel.appendChild(label("Part selection", entry.selectionMode));
        entry.boneControls = element("div", { className: "viewer-transplant-bone-controls" });
        entry.includeChildren = element("input", { type: "checkbox", checked: "", id: id + "-include-children" });
        entry.boneSearch = element("input", { type: "search", id: id + "-bone-search", "aria-label": t("Find a donor bone") });
        entry.boneTree = element("div", { className: "viewer-transplant-bone-tree", id: id + "-bones", role: "group", "aria-label": t("Bones") });
        entry.boneControls.append(label("Add a bone", entry.parts), label("Include child bones", entry.includeChildren), label("Find a donor bone", entry.boneSearch), entry.boneTree); entry.panel.appendChild(entry.boneControls);
        entry.faceControls = element("div", { className: "viewer-transplant-face-controls", hidden: "" });
        entry.sceneAction = element("select", { id: id + "-scene-action" });
        [["paint", "Paint faces"], ["erase", "Erase faces"], ["connected", "Connected faces"], ["orbit", "Orbit model"]].forEach(function (row) { entry.sceneAction.appendChild(element("option", { value: row[0], text: row[1] })); });
        entry.brushRadius = element("input", { type: "range", min: "2", max: "80", step: "1", value: "20", id: id + "-brush-radius" });
        entry.fromBones = element("button", { type: "button", text: "Start from selected bones", id: id + "-faces-from-bones" });
        entry.faceControls.append(label("Donor editing", entry.sceneAction), label("Brush radius", entry.brushRadius), entry.fromBones); entry.panel.appendChild(entry.faceControls);
        entry.partHint = element("p", { className: "viewer-render-note" }); entry.panel.appendChild(entry.partHint);
        entry.texturePanel = element("div", { className: "viewer-transplant-texture-panel", hidden: "" });
        entry.textureMaterial = element("select", { id: id + "-texture-material" });
        entry.texturePan = element("input", { type: "checkbox", id: id + "-texture-pan" });
        entry.textureZoom = element("input", { type: "range", min: "1", max: "16", step: ".25", value: "1", id: id + "-texture-zoom" });
        entry.textureZoomText = element("output", {}); entry.textureZoomText.textContent = "100%";
        entry.textureFit = element("button", { type: "button", text: "Fit texture", id: id + "-texture-fit" });
        entry.textureCanvas = element("canvas", { width: "768", height: "768", id: id + "-texture", tabindex: "0", "aria-label": t("Donor texture") });
        entry.textureStatus = element("p", { className: "viewer-render-note" });
        if (global.ViewerUVColor) entry.uvColor = global.ViewerUVColor.control(entry.texturePanel, { id: id + "-uv-color", translate: t,
          onChange: function () { if (entry.preview) entry.preview.drawTexture(); } });
        entry.texturePanel.append(label("Material / submesh", entry.textureMaterial), label("Move texture", entry.texturePan), element("div", { className: "viewer-transplant-texture-zoom" }, [label("Texture zoom", entry.textureZoom), entry.textureZoomText, entry.textureFit]), entry.textureCanvas, entry.textureStatus,
          element("p", { className: "viewer-render-note", "data-transplant-label": "UV overlaps select every face at that texture position. Use the 3D model to select only the visible surface.", text: "UV overlaps select every face at that texture position. Use the 3D model to select only the visible surface." })); entry.panel.appendChild(entry.texturePanel);
        entry.selectionClear = element("button", { type: "button", text: "Clear part selection", id: id + "-selection-clear" });
        entry.selectionUndo = element("button", { type: "button", text: "Undo selection", id: id + "-selection-undo" });
        entry.selectionRedo = element("button", { type: "button", text: "Redo selection", id: id + "-selection-redo" });
        entry.selectionStatus = element("p", { role: "status", "aria-live": "polite", className: "viewer-render-note", id: id + "-selection-status" });
        entry.panel.append(element("div", { className: "viewer-transplant-actions" }, [entry.selectionClear, entry.selectionUndo, entry.selectionRedo]), entry.selectionStatus);
        entry.selectionMode.addEventListener("change", function () { selectionChanged(entry); });
        entry.boneSearch.addEventListener("input", function () { var query = entry.boneSearch.value.trim().toLowerCase(); (entry.boneRows || []).forEach(function (row) { row.row.hidden = !!query && row.part.value.toLowerCase().indexOf(query) < 0; }); });
        entry.selectionClear.addEventListener("click", function () { mutateSelection(entry, function () { entry.selectedBones.clear(); entry.selectedFaces.clear(); }); });
        entry.selectionUndo.addEventListener("click", function () { restoreSelection(entry, false); }); entry.selectionRedo.addEventListener("click", function () { restoreSelection(entry, true); });
        entry.sceneAction.addEventListener("change", function () { if (entry.preview) entry.preview.selectionModeChanged(); });
        entry.fromBones.addEventListener("click", function () { mutateSelection(entry, function () { entry.selectedFaces = boneFaces(entry); entry.selectionMode.value = "triangles"; }); });
      } else { var partLabel = label("Part root bone", entry.parts); partLabel.hidden = true; entry.panel.appendChild(partLabel); }
      entry.matchSkin = element("input", { type: "checkbox" });
      entry.skinOnly = element("input", { type: "checkbox", checked: "" }); entry.skinOnly.disabled = true;
      entry.panel.appendChild(element("div", { className: "viewer-transplant-options" }, [label("Match skin colour", entry.matchSkin), label("Skin only (preserve outfit colours)", entry.skinOnly)]));
      entry.matchSkin.addEventListener("change", function () { entry.skinOnly.disabled = !entry.matchSkin.checked; });
      if (operation === "part") {
        entry.reuseEmptyUV = element("input", { type: "checkbox", checked: "", id: id + "-reuse-empty-uv" });
        entry.panel.appendChild(label("Reuse empty UV areas", entry.reuseEmptyUV));
        var reuseHint = "Try the donor's original UV position first. If occupied, use an atlas or enable moving to another empty UV area. No padding is added.";
        entry.panel.appendChild(element("p", { className: "viewer-render-note", "data-transplant-label": reuseHint, text: reuseHint }));
        entry.relocateEmptyUV = element("input", { type: "checkbox", id: id + "-relocate-empty-uv" });
        entry.panel.appendChild(label("Move to another empty UV area", entry.relocateEmptyUV));
        var relocateHint = "If the original UV position is occupied, find another empty area without reducing source pixel detail. No padding is added.";
        entry.panel.appendChild(element("p", { className: "viewer-render-note", "data-transplant-label": relocateHint, text: relocateHint }));
        entry.reuseEmptyUV.addEventListener("change", function () {
          if (!entry.reuseEmptyUV.checked) entry.relocateEmptyUV.checked = false;
          refresh();
        });
      }
      entry.low = element("input", { type: "number", step: ".005", min: "-10", max: "10", value: ".5", id: id + "-low" });
      entry.high = element("input", { type: "number", step: ".005", min: "-10", max: "10", value: ".92", id: id + "-high" });
      entry.preset = element("select", {});
      [{ value: "hip_fix", label: "Knee to waist" }, { value: "calf", label: "Calf to waist" }, { value: "ankle", label: "Ankle to waist" }, { value: "whole", label: "Whole lower body" }, { value: "custom", label: "Custom range" }].forEach(function (value) { entry.preset.appendChild(element("option", { value: value.value, "data-transplant-label": value.label, text: value.label })); });
      entry.region = element("select", {});
      [{ value: "lower", label: "Lower body" }, { value: "lower_belly", label: "Lower body and belly" }, { value: "central", label: "Central body" }].forEach(function (value) { entry.region.appendChild(element("option", { value: value.value, "data-transplant-label": value.label, text: value.label })); });
      entry.scope = element("select", {});
      [{ value: "skin", label: "Body skin" }, { value: "mesh", label: "Whole mesh (include outfit)" }].forEach(function (value) { entry.scope.appendChild(element("option", { value: value.value, "data-transplant-label": value.label, text: value.label })); });
      entry.exclude = element("input", { type: "checkbox", checked: "" });
      entry.donorMesh = element("select", { id: id + "-donor-mesh" });
      entry.targetMesh = element("select", { id: id + "-target-mesh" });
      var cuts = element("div", { className: "viewer-transplant-cuts" }, [label("Cut preset", entry.preset), label("Upper cut Y", entry.high), label("Lower cut Y", entry.low), label("Replacement region", entry.region), label("Donor mesh", entry.donorMesh), label("Wearer mesh", entry.targetMesh), label("Replacement selection", entry.scope), label("Exclude separate accessories", entry.exclude)]); cuts.hidden = operation !== "lower"; entry.panel.appendChild(cuts);
      if (operation === "part") entry.panel.insertBefore(element("div", { className: "viewer-transplant-cuts" }, [label("Donor mesh", entry.donorMesh), label("Wearer mesh", entry.targetMesh)]), entry.boneControls);
      var hint = element("p", { className: "viewer-render-note", "data-transplant-label": "The mesh between the blue lower plane and orange upper plane is replaced.", text: "The mesh between the blue lower plane and orange upper plane is replaced." }); hint.hidden = operation !== "lower"; entry.panel.appendChild(hint);
      var selectedHint = element("p", { className: "viewer-render-note", "data-transplant-label": "Highlighted donor faces are inserted. Wearer faces crossing either cut are retained to prevent gaps.", text: "Highlighted donor faces are inserted. Wearer faces crossing either cut are retained to prevent gaps." }); selectedHint.hidden = operation !== "lower"; entry.panel.appendChild(selectedHint);
      entry.run = element("button", { type: "button", className: "viewer-primary", "data-transplant-label": operation === "lower" ? "Replace lower body" : "Transplant", text: operation === "lower" ? "Replace lower body" : "Transplant", disabled: "" });
      entry.cancel = element("button", { type: "button", text: "Cancel", hidden: "" });
      entry.result = element("button", { type: "button", "data-transplant-label": "Open transplant result", text: "Open transplant result", hidden: "" });
      entry.undo = element("button", { type: "button", "data-transplant-label": "Undo transplant", text: "Undo transplant", disabled: "" });
      entry.redo = element("button", { type: "button", "data-transplant-label": "Redo transplant", text: "Redo transplant", disabled: "" });
      entry.status = element("p", { className: "viewer-render-note", role: "status", "aria-live": "polite" });
      entry.progress = element("progress", { hidden: "" }); entry.log = element("pre", { className: "viewer-transplant-log", hidden: "" });
      entry.panel.append(element("div", { className: "viewer-transplant-actions" }, [entry.run, entry.cancel, entry.result, entry.undo, entry.redo]), entry.status, entry.progress, entry.log,
        element("p", { className: "viewer-render-note", "data-transplant-label": "Use a single Unity model or a ZIP containing one model for transplanting.", text: "Use a single Unity model or a ZIP containing one model for transplanting." }));
      document.getElementById("viewer-control-panel").appendChild(entry.panel);
      entry.pick.addEventListener("click", function () {
        var callback = function (path) { if (path) chooseDonor(entry, [path]); };
        if (options.pickFile) options.pickFile(callback); else if (global.openPicker) global.openPicker("path", callback, "models");
      });
      entry.game.addEventListener("click", function () { if (global.ViewerGameAssets) global.ViewerGameAssets.pick(function (paths, variants) { chooseDonor(entry, paths, variants); }); });
      entry.parts.addEventListener("change", function () {
        if (entry.operation === "part" && entry.parts.value) mutateSelection(entry, function () { setBoneSelection(entry.partOptions, entry.selectedBones, entry.parts.value, entry.includeChildren.checked, true); });
        else { if (entry.preview) entry.preview.cuts(); refresh(); }
      }); entry.run.addEventListener("click", function () { run(entry); });
      [entry.region, entry.scope, entry.exclude].forEach(function (control) { control.addEventListener("change", function () { if (entry.preview) entry.preview.cuts(); }); });
      entry.donorMesh.addEventListener("change", async function () {
        if (busy || entry.inspecting) return;
        var generation = entry.generation, controller = new AbortController(); entry.request = controller;
        entry.inspecting = true; refresh();
        try {
          var donor = entry.donor, mesh = entry.donorMesh.value;
          var result = await json("/api/viewer/transplant/inspect", { donor: donor, variant: entry.variant, renderer: mesh }, controller.signal);
          if (!disposed && generation === entry.generation && donor === entry.donor && mesh === entry.donorMesh.value) { entry.geometry = result.geometry; fillPartChoices(entry, result); if (entry.preview) entry.preview.rebind(); }
        } catch (error) { if (!disposed && generation === entry.generation && error.name !== "AbortError") status(entry, error.message, true); }
        finally { if (!disposed && generation === entry.generation) { if (entry.request === controller) entry.request = null; entry.inspecting = false; refresh(); } }
      });
      entry.result.addEventListener("click", function () { openResult(entry).catch(function (error) { status(entry, error.message, true); }); });
      entry.undo.addEventListener("click", function () { restoreHistory(entry, false); });
      entry.redo.addEventListener("click", function () { restoreHistory(entry, true); });
      entry.cancel.addEventListener("click", function () { if (jobId) fetch("/api/jobs/" + jobId + "/cancel", { method: "POST" }); });
      entry.preset.addEventListener("change", function () {
        var preset = { hip_fix: [.5, .92], calf: [.3, .96], ankle: [.11, .96], whole: [-.05, 1.06] }[entry.preset.value];
        if (preset) { entry.low.value = preset[0]; entry.high.value = preset[1]; if (entry.preview) entry.preview.cuts(); }
      });
      [entry.low, entry.high].forEach(function (input) { input.addEventListener("input", function () { entry.preset.value = "custom"; if (entry.preview) entry.preview.cuts(); }); });
      entries.push(entry);
    }
    addPanel("costume", "viewer-costume-transplant", "Costume transplant");
    addPanel("part", "viewer-part-transplant", "Costume part transplant");
    addPanel("lower", "viewer-lower-transplant", "Lower body replacement");
    refresh();
    return {
      refresh: refresh,
      getEditHistory: function () { return undoHistory.map(function (entry) { return entry.title; }); },
      updateLanguage: function () {
        entries.forEach(function (entry) { entry.panel.querySelectorAll("[data-transplant-label]").forEach(function (node) { node.textContent = t(node.dataset.transplantLabel); }); if (entry.uvColor) entry.uvColor.updateLanguage(); if (entry.operation === "part") updatePartUI(entry); status(entry, entry.statusKey || ""); }); refresh();
      },
      getState: function () { return { busy: busy, jobId: jobId, undoCount: undoHistory.length, redoCount: redoHistory.length, historyLimit: MAX_HISTORY, donors: entries.map(function (entry) { var manifest = selectedBoneManifest(entry.partOptions, entry.selectedBones), result = { operation: entry.operation, donor: entry.donor, part: entry.parts.value, cutLow: Number(entry.low.value), cutHigh: Number(entry.high.value), matchSkin: entry.matchSkin.checked, skinOnly: entry.skinOnly.checked, selectionScope: entry.scope.value, excludeAccessories: entry.exclude.checked, selectedTriangles: entry.selectedTriangles || 0 };
        if (entry.operation === "part") Object.assign(result, { reuseEmptyUV: entry.reuseEmptyUV.checked, relocateEmptyUV: entry.relocateEmptyUV.checked, selectionMode: entry.selectionMode.value, includeChildren: entry.includeChildren.checked, partRoots: manifest.partRoots, includeDescendants: manifest.includeDescendants, selectedBones: Array.from(entry.selectedBones).sort(), selectedFaces: Array.from(entry.selectedFaces).sort(function (a, b) { return a - b; }), highlightedFaces: Array.from(entry.highlightedFaces).sort(function (a, b) { return a - b; }), donorSha256: entry.donorSha256 || "", donorSelectionFingerprint: entry.donorSelectionFingerprint || "", donorRenderer: entry.geometry && entry.geometry.renderer, donorMesh: entry.geometry && entry.geometry.mesh, selectionUndoCount: entry.selectionHistory.length, selectionRedoCount: entry.selectionFuture.length, textureView: entry.preview && entry.preview.getTextureView(), availableBones: (entry.partOptions || []).map(function (row) { return { value: row.value, parent: row.parent, depth: row.depth, bones: row.bones }; }) }); return result; }) }; },
      dispose: function () { disposed = true; if (events) events.close(); if (jobId) fetch("/api/jobs/" + jobId + "/cancel", { method: "POST" }); entries.forEach(function (entry) { if (entry.request) entry.request.abort(); if (entry.uvColor) entry.uvColor.dispose(); if (entry.preview) entry.preview.dispose(); entry.panel.remove(); }); }
    };
  }
  global.ViewerTransplants = { create: create, selectedBoneManifest: selectedBoneManifest, setBoneSelection: setBoneSelection };
}(window));
