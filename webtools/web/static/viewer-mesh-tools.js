/* UV paint deletion and vertex/skin editing. Edits save to new source-bound copies. */
(function () {
  'use strict';
  var WORDS = {
    'Mesh deleter': ['메시 삭제 도구', 'メッシュ削除'], 'Mesh modify': ['메시 수정 도구', 'メッシュ編集'],
    'Load meshes': ['메시 목록 불러오기', 'メッシュ一覧を読み込む'], 'Mesh': ['메시', 'メッシュ'], 'Material / submesh': ['머티리얼 / 서브메시', 'マテリアル / サブメッシュ'],
    'Choose a mesh': ['메시 선택', 'メッシュを選択'], 'Brush radius': ['브러시 반경', 'ブラシ半径'],
    'Paint': ['칠하기', '塗る'], 'Erase': ['지우기', '消す'], 'Undo': ['실행 취소', '元に戻す'],
    'Redo': ['다시 실행', 'やり直す'], 'Clear selection': ['선택 해제', '選択解除'],
    'Invert selection': ['선택 반전', '選択を反転'], 'Select all': ['모두 선택', 'すべて選択'],
    'Select connected': ['연결된 면 선택', 'つながった面を選択'], 'Connected faces': ['연결된 면 선택', 'つながった面を選択'],
    'Across UV seams': ['UV 경계도 연결', 'UV境界もつなぐ'],
    'Choose a face or vertex first.': ['먼저 면이나 정점을 선택하세요.', '先に面または頂点を選択してください。'],
    'Texture interaction': ['텍스처 조작', 'テクスチャ操作'], 'Move texture': ['텍스처 이동', 'テクスチャを移動'],
    'Brush': ['브러시', 'ブラシ'], 'Linked': ['연결', '接続'], 'Pan': ['이동', '移動'], 'Selection': ['선택', '選択'], 'Tool settings': ['도구 설정', 'ツール設定'],
    'Texture zoom': ['텍스처 확대', 'テクスチャ拡大'], 'Zoom in': ['확대', '拡大'], 'Zoom out': ['축소', '縮小'], 'Fit texture': ['텍스처 맞춤', 'テクスチャを全体表示'],
    'Scroll or pinch to zoom. Use Move texture, Alt-drag or right-drag to pan.': ['스크롤이나 두 손가락으로 확대합니다. 텍스처 이동 모드, Alt+드래그 또는 오른쪽 드래그로 이동합니다.', 'スクロールまたはピンチで拡大します。移動モード、Altドラッグまたは右ドラッグで移動します。'],
    'Connected selection stays in the selected material. Use the model to distinguish overlapping UVs.': ['연결 선택은 선택한 머티리얼 안에서 확장합니다. UV가 겹친 부분은 모델에서 직접 선택하면 구분할 수 있습니다.', '接続選択は選択中のマテリアル内で広がります。UVが重なる部分はモデル上で直接選択して区別できます。'],
    'Show UV lines': ['UV 선 표시', 'UV線を表示'], 'Texture image': ['텍스처 이미지', 'テクスチャ画像'],
    'Save mesh edits and open copy': ['메시 편집 저장 후 사본 열기', 'メッシュ編集を保存してコピーを開く'],
    'Open a model first.': ['먼저 모델을 여세요.', '先にモデルを開いてください。'],
    'Paint texture areas to remove their triangles. Overlapping UVs select all matching faces.': ['텍스처 위에 칠하면 해당 삼각형이 삭제 대상으로 선택됩니다. UV가 겹치는 면은 함께 선택됩니다.', 'テクスチャ上に塗って削除する三角形を選択します。UVが重なる面は一緒に選択されます。'],
    'Paint to select vertices, then edit positions or normalized weights.': ['칠해서 정점을 선택한 후 위치 또는 정규화된 웨이트를 편집하세요.', '塗って頂点を選択し、位置または正規化ウェイトを編集します。'],
    'Selected faces': ['선택된 면', '選択面'], 'Selected vertices': ['선택된 정점', '選択頂点'],
    'Position and weight edits': ['위치 및 웨이트 변경', '位置・ウェイト変更'],
    'Loading…': ['불러오는 중…', '読み込み中…'], 'Saving…': ['저장 중…', '保存中…'],
    'No UV coordinates are available. Select vertices by index.': ['UV 좌표가 없습니다. 정점 번호로 선택하세요.', 'UV座標がありません。頂点番号で選択してください。'],
    'Vertex index': ['정점 번호', '頂点番号'], 'Select vertex': ['정점 선택', '頂点を選択'],
    'Position (mesh local XYZ)': ['위치 (메시 로컬 XYZ)', '位置（メッシュローカルXYZ）'],
    'Set vertex position': ['정점 위치 설정', '頂点位置を設定'], 'Translate selected vertices': ['선택 정점 이동', '選択頂点を移動'],
    'Bone': ['본', 'ボーン'], 'Weight': ['웨이트', 'ウェイト'], 'Weight mode': ['웨이트 편집 방식', 'ウェイトモード'],
    'Set': ['설정', '設定'], 'Add': ['더하기', '加算'], 'Subtract': ['빼기', '減算'], 'Smooth': ['부드럽게', '平滑化'],
    'Transfer from bone': ['원본 본에서 옮기기', '元ボーンから移す'], 'Source bone': ['원본 본', '元ボーン'],
    'Apply weights to selection': ['선택 영역 웨이트 적용', '選択領域に適用'],
    'Lock bone weights': ['본 웨이트 잠금', 'ボーンウェイトをロック'],
    'Locked bones retain their current weights. Remaining weights normalize to a total of 1, with at most four influences.': ['잠근 본의 웨이트를 유지하고 나머지를 합계 1로 정규화합니다. 정점당 최대 4개 본을 유지합니다.', 'ロックしたボーンの値を保持し、残りを合計1に正規化します。影響ボーンは最大4個です。'],
    'Choose one vertex for an absolute position.': ['절대 위치를 설정할 정점 하나를 선택하세요.', '絶対位置を設定する頂点を1つ選択してください。'],
    'Choose vertices first.': ['먼저 정점을 선택하세요.', '先に頂点を選択してください。'],
    'Select a different unlocked bone.': ['잠겨 있지 않은 다른 본을 선택하세요.', 'ロックされていない別のボーンを選んでください。'],
    'No writable skin weights are available.': ['편집할 수 있는 스킨 웨이트가 없습니다.', '編集可能なスキンウェイトがありません。'],
    'This model uses a position format that cannot be edited.': ['이 모델의 정점 위치 형식은 편집을 지원하지 않습니다.', 'この頂点位置形式は編集できません。'],
    'Restore mesh changes': ['메시 변경 초기화', 'メッシュ変更をリセット'],
    'Changes are temporary until saved. Original files are preserved.': ['저장 전까지 변경은 임시 상태이며 원본 파일은 보존됩니다.', '保存するまで変更は一時的です。元ファイルは保持されます。'],
    '3D editing': ['3D 편집', '3D編集'], 'Orbit model': ['모델 회전', 'モデルを回転'], 'Paint on model': ['모델에 칠하기', 'モデルに塗る'],
    'Pick vertices': ['정점 선택', '頂点を選択'], 'Move vertices in 3D': ['3D에서 정점 이동', '3Dで頂点を移動'],
    'Move selected vertices': ['선택 정점 이동', '選択頂点を移動'], 'Pick': ['선택', '選択'], 'Move': ['이동', '移動'], 'Step': ['간격', '移動量'], 'Move axis': ['이동 축', '移動軸'], 'Screen plane': ['화면 평면', '画面の平面'],
    'Move step': ['이동 간격', '移動量'], 'Centre (local XYZ)': ['중심 (로컬 XYZ)', '中心（ローカルXYZ）'],
    'Drag an axis arrow, or use the step buttons. Axis values use the source mesh coordinates.': ['축 화살표를 드래그하거나 간격 버튼으로 이동합니다. 축 값은 원본 메시 좌표를 사용합니다.', '軸の矢印をドラッグするか、移動量ボタンで動かします。軸は元メッシュの座標です。'],
    'Enter a positive move distance.': ['0보다 큰 이동 간격을 입력하세요.', '0より大きい移動量を入力してください。'],
    'Show selection on model': ['모델에 선택 영역 표시', 'モデルに選択範囲を表示'], 'Show vertex targets': ['정점 선택점 표시', '頂点の選択点を表示'],
    'Delete selected faces': ['선택한 면 삭제', '選択面を削除'], 'Save mesh copy': ['메시 사본 저장', 'メッシュコピーを保存'],
    'Saved copies keep their version. Undo restores the live mesh; save again to create a restored copy.': ['저장한 사본은 해당 버전을 유지합니다. 실행 취소로 화면의 메시를 복구한 후 다시 저장하면 복구한 사본이 만들어집니다.', '保存コピーはそのバージョンを保持します。元に戻すと表示中のメッシュが復元され、再保存で復元コピーを作成できます。'],
    'Paint selects faces. Delete selected faces removes them from the model. Ctrl/Cmd+Z restores the mesh.': ['칠하면 면이 선택됩니다. 선택한 면 삭제를 누르면 모델에서도 삭제됩니다. Ctrl/Cmd+Z로 메시를 복구할 수 있습니다.', '塗ると面を選択します。「選択面を削除」でモデルから削除します。Ctrl/Cmd+Zでメッシュを復元します。'],
    'Use Alt or right-drag to orbit while editing. Shift-click adds or removes vertices.': ['편집 중 Alt 또는 오른쪽 드래그로 모델을 회전합니다. Shift+클릭으로 정점을 추가하거나 해제합니다.', '編集中はAltまたは右ドラッグで回転できます。Shift+クリックで頂点の選択を追加・解除します。'],
    'Deleted faces': ['삭제한 면', '削除面'], '3D mapping unavailable for this mesh. UV editing remains available.': ['이 메시의 정확한 3D 편집 연결을 사용할 수 없습니다. UV 편집은 사용할 수 있습니다.', 'このメッシュの正確な3D編集対応がありません。UV編集は利用できます。'],
    'Mesh editing failed.': ['메시 편집에 실패했습니다.', 'メッシュ編集に失敗しました。'],
    'The mesh recipe is invalid.': ['메시 편집 설정이 올바르지 않습니다.', 'メッシュ編集レシピが無効です。'],
    'The mesh recipe exceeds the undo history limit.': ['메시 편집 설정이 실행 취소 기록의 크기 제한을 넘습니다.', 'メッシュ編集レシピが元に戻す履歴の上限を超えています。'],
    'Wait for mesh editing to finish before restoring a recipe.': ['메시 작업이 끝난 뒤 편집 설정을 불러오세요.', 'メッシュの処理が完了してからレシピを復元してください。'],
    'The model changed while restoring mesh edits.': ['메시 편집을 복원하는 동안 모델이 바뀌었습니다.', 'メッシュ編集の復元中にモデルが変更されました。']
  };
  function language() { try { return localStorage.getItem('sifas_lang') || document.documentElement.lang || 'en'; } catch (_) { return document.documentElement.lang || 'en'; } }
  function translated(key, external) { var text = external ? external(key) : key, lang = language().slice(0, 2); return text !== key ? text : WORDS[key] && (lang === 'ko' || lang === 'ja') ? WORDS[key][lang === 'ko' ? 0 : 1] : key; }
  function clone(x) { return JSON.parse(JSON.stringify(x)); }
  function normalize(values, locks, old) {
    var merged = {}, fixed = {}, slots = 4, fixedTotal = 0;
    (values || []).forEach(function (v) { if (v[1] > 0) merged[v[0]] = (merged[v[0]] || 0) + v[1]; });
    (old || []).forEach(function (v) { if (locks && locks[v[0]] && v[1] > 0) { fixed[v[0]] = v[1]; fixedTotal += v[1]; slots--; } });
    var candidates = Object.keys(merged).filter(function (i) { return !locks || !locks[i]; }).map(function (i) { return [+i, merged[i]]; });
    candidates.sort(function (a, b) { return b[1] - a[1] || a[0] - b[0]; }); candidates = candidates.slice(0, Math.max(0, slots));
    var total = candidates.reduce(function (sum, v) { return sum + v[1]; }, 0), remaining = Math.max(0, 1 - fixedTotal);
    if (remaining > 1e-8 && total <= 1e-12) return old ? clone(old) : [];
    var result = Object.keys(fixed).map(function (i) { return [+i, fixed[i]]; });
    candidates.forEach(function (v) { if (remaining > 1e-8 && total > 0) result.push([v[0], v[1] / total * remaining]); });
    return result.sort(function (a, b) { return b[1] - a[1] || a[0] - b[0]; });
  }
  function redistributeInfluence(old, bone, requested, locks, supplied) {
    locks = locks || {};
    if (locks[bone]) return clone(old);
    var values = {}, lockedTotal = 0;
    old.forEach(function (pair) { values[pair[0]] = pair[1]; if (locks[pair[0]]) lockedTotal += pair[1]; });
    if (old.filter(function (pair) { return locks[pair[0]] && pair[1] > 0; }).length >= 4 || lockedTotal >= 1 - 1e-8) return clone(old);
    if (supplied) Object.keys(supplied).forEach(function (i) { values[i] = supplied[i]; });
    var target = Math.max(0, Math.min(1 - lockedTotal, requested));
    var otherTotal = Object.keys(values).reduce(function (sum, i) { return sum + (+i !== bone && !locks[i] ? values[i] : 0); }, 0);
    var remainder = Math.max(0, 1 - lockedTotal - target);
    Object.keys(values).forEach(function (i) { if (+i !== bone && !locks[i]) values[i] = otherTotal ? values[i] / otherTotal * remainder : 0; }); values[bone] = target;
    var priorityLocks = {}, lockedCount = 0; Object.keys(locks).forEach(function (i) { priorityLocks[i] = true; if (values[i] > 0) lockedCount++; });
    var otherPositive = Object.keys(values).some(function (i) { return +i !== bone && !locks[i] && values[i] > 0; });
    if (target > 0) {
      // Reserve a slot and the requested weight for the painted bone. Adding
      // a fifth influence must not silently discard the newly painted bone.
      if (lockedCount >= 3) target = Math.max(0, 1 - lockedTotal);
      if (otherPositive || Math.abs(target + lockedTotal - 1) < 1e-8) {
        priorityLocks[bone] = true; values[bone] = target;
        var priorityOld = old.filter(function (pair) { return pair[0] !== bone; }).concat([[bone, target]]);
        return normalize(Object.keys(values).map(function (i) { return [+i, values[i]]; }), priorityLocks, priorityOld);
      }
      return clone(old);
    }
    return normalize(Object.keys(values).map(function (i) { return [+i, values[i]]; }), locks, old);
  }
  function pointSegment(x, y, a, b) {
    var dx = b[0] - a[0], dy = b[1] - a[1], length = dx * dx + dy * dy;
    var u = length ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / length)) : 0;
    return Math.hypot(x - a[0] - u * dx, y - a[1] - u * dy);
  }
  function intersects(x, y, radius, a, b, c) {
    function sign(p, q) { return (x - q[0]) * (p[1] - q[1]) - (p[0] - q[0]) * (y - q[1]); }
    var d1 = sign(a, b), d2 = sign(b, c), d3 = sign(c, a), area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    if (Math.abs(area) > 1e-12 && !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0))) return true;
    return Math.min(pointSegment(x, y, a, b), pointSegment(x, y, b, c), pointSegment(x, y, c, a)) <= radius;
  }
  // A face component crosses shared edges, never a lone touching vertex. UV
  // seams may duplicate vertices; join only a unique oppositely oriented edge
  // with the same source positions and skin bindings, not coincident shells.
  function buildFaceConnectivity(data, seams) {
    var faces = data.triangles || [], positions = data.positions || [], skin = data.skin || [], neighbors = faces.map(function () { return []; });
    var indexed = new Map(), geometric = seams ? new Map() : null, canonical = seams ? new Map() : null, vertexKeys = [], faceKeys = [], stride = positions.length + 1;
    function vertexKey(index) {
      if (vertexKeys[index] !== undefined) return vertexKeys[index];
      var weights = (skin[index] || []).slice().sort(function (a, b) { return a[0] - b[0]; });
      var signature = JSON.stringify([positions[index], weights]), id = canonical.get(signature);
      if (id === undefined) { id = canonical.size; canonical.set(signature, id); }
      return vertexKeys[index] = id;
    }
    function add(map, key, value) { var entries = map.get(key); if (entries) entries.push(value); else map.set(key, [value]); }
    function connect(a, b) { if (a !== b) { neighbors[a].push(b); neighbors[b].push(a); } }
    faces.forEach(function (face, index) {
      var keys = seams ? face.map(vertexKey) : null; if (keys) faceKeys[index] = keys.slice().sort(function (a, b) { return a - b; }).join('|');
      for (var edge = 0; edge < 3; edge++) {
        var a = face[edge], b = face[(edge + 1) % 3]; if (a === b) continue;
        var key = Math.min(a, b) * stride + Math.max(a, b); add(indexed, key, index);
        if (geometric && keys[edge] !== keys[(edge + 1) % 3]) {
          var first = keys[edge], second = keys[(edge + 1) % 3], forward = first < second;
          add(geometric, Math.min(first, second) * stride + Math.max(first, second), { face: index, forward: forward, indexed: key });
        }
      }
    });
    indexed.forEach(function (entries) { for (var i = 1; i < entries.length; i++) connect(entries[0], entries[i]); });
    if (geometric) geometric.forEach(function (entries) {
      if (entries.length !== 2) return;
      var a = entries[0], b = entries[1];
      if (a.indexed !== b.indexed && a.forward !== b.forward && faceKeys[a.face] !== faceKeys[b.face]) connect(a.face, b.face);
    });
    return neighbors;
  }
  function connectedFaces(graph, seeds, accept) {
    var visited = new Set(), queue = [];
    (seeds || []).forEach(function (face) { if (Number.isInteger(face) && face >= 0 && face < graph.length && (!accept || accept(face)) && !visited.has(face)) { visited.add(face); queue.push(face); } });
    for (var index = 0; index < queue.length; index++) (graph[queue[index]] || []).forEach(function (face) {
      if (!visited.has(face) && (!accept || accept(face))) { visited.add(face); queue.push(face); }
    });
    return queue;
  }
  function clampView(view) {
    var zoom = Math.max(1, Math.min(16, +view.zoom || 1));
    return { zoom: zoom, x: Math.max(1 - zoom, Math.min(0, +view.x || 0)), y: Math.max(1 - zoom, Math.min(0, +view.y || 0)) };
  }
  function uvToView(point, view) { return [view.x + point[0] * view.zoom, view.y + (1 - point[1]) * view.zoom]; }
  function viewToUv(point, view) { return [(point[0] - view.x) / view.zoom, 1 - (point[1] - view.y) / view.zoom]; }
  function zoomView(view, zoom, anchor) {
    anchor = anchor || [.5, .5]; var uv = viewToUv(anchor, view), result = { zoom: Math.max(1, Math.min(16, zoom)) };
    result.x = anchor[0] - uv[0] * result.zoom; result.y = anchor[1] - (1 - uv[1]) * result.zoom; return clampView(result);
  }
  function create(options) {
    options = options || {};
    var holder = document.getElementById('viewer-control-panel'); if (!holder) return null;
    var token = null, records = [], cache = {}, panels = [], disposed = false, busy = false, request = 0, lastSaved = null, editRevision = 0;
    var listeners = [], labels = [], history = [], future = [], historyBytes = 0, activePanel = null, runtimeEngine = null, runtimeGesture = null, savedToken = null, savedFingerprint = null, uvCursor = null;
    function t(key) { return translated(key, options.translate); }
    function interactive() { return !options.isInteractive || options.isInteractive(); }
    function el(tag, parent, key) { var e = document.createElement(tag); if (key) { e.textContent = t(key); labels.push([e, key]); } if (parent) parent.appendChild(e); return e; }
    function on(e, type, handler) { e.addEventListener(type, handler); listeners.push(function () { e.removeEventListener(type, handler); }); }
    function button(parent, key, handler) { var b = el('button', parent, key); b.type = 'button'; on(b, 'click', handler); return b; }
    function select(parent, key, values) { var label = el('label', parent), span = el('span', label, key), s = el('select', label); span.style.display = 'block'; (values || []).forEach(function (entry) { var o = el('option', s, entry[1]); o.value = entry[0]; }); return s; }
    function numeric(parent, key, initial, min, max, step) { var label = el('label', parent); el('span', label, key); var input = el('input', label); input.type = 'number'; input.value = initial; input.min = min; input.max = max; input.step = step; if (window.ViewerSignedInputs) window.ViewerSignedInputs.attach(input, { width: '7rem' }); return input; }
    var style = el('style', document.head); style.textContent = '.viewer-mesh-tools .mesh-row{display:flex;gap:.5rem;align-items:end;flex-wrap:wrap;margin:.6rem 0}.viewer-mesh-tools label{display:flex;gap:.35rem;align-items:center;flex-wrap:wrap}.viewer-mesh-tools .mesh-row>label{min-width:0;max-width:100%}.viewer-mesh-tools select{max-width:100%;min-width:0}.viewer-mesh-tools canvas{display:block;width:100%;height:auto;max-width:640px;aspect-ratio:1;touch-action:none;background:repeating-conic-gradient(#28313f 0% 25%,#323e50 0% 50%) 50%/20px 20px;border:1px solid #667085;border-radius:.35rem;cursor:crosshair}.viewer-mesh-tools input[type=number]{max-width:7rem}.viewer-mesh-tools .mesh-weights{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));max-height:8rem;overflow:auto}.viewer-mesh-tools .mesh-weights label{font-size:.82rem}.viewer-mesh-tools .mesh-value-table{white-space:pre-wrap;font-size:.85rem;overflow-wrap:anywhere}.viewer-mesh-tools .mesh-save{width:100%;margin-top:.6rem}.viewer-mesh-tools summary{min-height:44px}.viewer-mesh-tools .mesh-error{color:#f49595}.viewer-mesh-tools fieldset{min-width:0;border:1px solid #667085;border-radius:.35rem;margin:.6rem 0;padding:.5rem}';
    style.textContent += '.viewer-mesh-tools .mesh-transform-tools{min-width:0;border:1px solid var(--line,#667085);border-radius:6px;padding:5px;display:flex;flex-direction:column;gap:4px}.viewer-mesh-tools .mesh-transform-row{display:flex;flex-wrap:wrap;align-items:center;gap:4px;min-width:0}.viewer-mesh-tools .mesh-transform-tools button{margin:0;min-width:32px;min-height:32px;padding:4px 7px;white-space:nowrap;font-size:12px;line-height:1.2}.viewer-mesh-tools .mesh-transform-tools button[aria-pressed=true]{border-color:var(--accent,#315fbc);box-shadow:inset 0 0 0 1px var(--accent,#315fbc)}.viewer-mesh-tools .mesh-transform-tools label{min-width:0;display:inline-flex;flex-wrap:nowrap;font-size:12px;gap:4px}.viewer-mesh-tools .mesh-transform-tools select{max-width:124px;min-height:32px;margin:0;padding:4px}.viewer-mesh-tools .mesh-transform-tools input{width:82px;min-width:0;min-height:32px;margin:0;padding:4px}.viewer-mesh-tools .mesh-transform-note{font-size:11px;line-height:1.3;margin:0;overflow-wrap:anywhere}.viewer-mesh-tools .mesh-transform-row[hidden]{display:none}.viewer-mesh-tools .mesh-transform-axis-x{color:#c53247}.viewer-mesh-tools .mesh-transform-axis-y{color:#147b4d}.viewer-mesh-tools .mesh-transform-axis-z{color:#255fc7}@media(pointer:coarse){.viewer-mesh-tools .mesh-transform-tools button,.viewer-mesh-tools .mesh-transform-tools select,.viewer-mesh-tools .mesh-transform-tools input{min-height:44px}.viewer-mesh-tools .mesh-transform-tools button{min-width:44px}}';
    style.textContent += '.viewer-mesh-tools.texture-pane-expanded .mesh-transform-tools,.viewer-mesh-tools .mesh-transform-tools [hidden]{display:none!important}.viewer-mesh-tools .mesh-transform-axis-label>span{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}';
    style.textContent += '.viewer-mesh-tools .mesh-transform-tools select{width:104px;max-width:104px;font-size:12px}.viewer-mesh-tools .mesh-transform-tools input{width:64px;font-size:12px}';
    async function api(route, payload) {
      var response = await fetch('/api/viewer/mesh/' + route, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      var result = await response.json(); if (!response.ok || result.error) throw new Error(result.error || t('Mesh editing failed.')); return result;
    }
    function key(mesh) { return JSON.stringify({ source: mesh.source, file: mesh.file, id: mesh.id }); }
    function current(panel) { return cache[panel.mesh.value] || null; }
    function snapshot() { var out = {}; Object.keys(cache).forEach(function (k) { var m = cache[k]; out[k] = { deleted: Array.from(m.deleted), marked: Array.from(m.marked || []), selected: Array.from(m.selected), positions: clone(m.positions), weights: clone(m.weights) }; }); return out; }
    function remember(value) { value = typeof value === 'string' ? value : JSON.stringify(snapshot()); history.push(value); historyBytes += value.length; while (history.length > 24 || historyBytes > 8 * 1024 * 1024) historyBytes -= history.shift().length; future = []; }
    function geometryChanged(m) { m.geometryRevision = (m.geometryRevision || 0) + 1; }
    function restore(value) { var state = JSON.parse(value); Object.keys(cache).forEach(function (k) { var row = state[k] || { deleted: [], marked: [], selected: [], positions: {}, weights: {} }, m = cache[k]; m.deleted = new Set(row.deleted); m.marked = new Set(row.marked || []); m.selected = new Set(row.selected); m.positions = row.positions; m.weights = row.weights; m.weightRevision = (m.weightRevision || 0) + 1; geometryChanged(m); }); panels.forEach(function (p) { p.positionDraft = false; }); changed(); }
    function undo() { if (busy || runtimeGesture || !interactive() || !history.length) return; future.push(JSON.stringify(snapshot())); var value = history.pop(); historyBytes -= value.length; restore(value); }
    function redo() { if (busy || runtimeGesture || !interactive() || !future.length) return; var value = JSON.stringify(snapshot()); history.push(value); historyBytes += value.length; restore(future.pop()); }
    function status(panel, text, error) { panel.status.textContent = text; panel.status.classList.toggle('mesh-error', !!error); }
    function changed() { editRevision++; Object.keys(cache).forEach(function (id) { var m = cache[id]; m.positionCount = Object.keys(m.positions).length; m.weightCount = Object.keys(m.weights).length; }); redraw(); if (options.onChange) options.onChange(); }
    function fillMeshes() {
      panels.forEach(function (p) { var previous = p.mesh.value; p.mesh.textContent = ''; var empty = el('option', p.mesh, 'Choose a mesh'); empty.value = ''; records.forEach(function (r) { var o = el('option', p.mesh); o.value = key(r.mesh); o.textContent = r.name + ' · ' + r.sourceName + ' (' + r.vertices + ')'; o.disabled = !r.available; if (r.reason) o.title = r.reason; }); if (Array.from(p.mesh.options).some(function (o) { return o.value === previous; })) p.mesh.value = previous; });
    }
    async function inspectMeshes(panel) {
      refresh(); if (!token || busy || !interactive()) return;
      var ticket = ++request; busy = true; status(panel, t('Loading…')); redraw(); if (options.onChange) options.onChange();
      try {
        var response = await api('inspect', { token: token }); if (disposed || ticket !== request) return;
        records = response.meshes || [];
        fillMeshes();
        status(panel, records.length + ' ' + t('Mesh'));
      } catch (error) { if (ticket === request) status(panel, error.message, true); }
      finally { if (ticket === request) { busy = false; redraw(); if (options.onChange) options.onChange(); } }
    }
    function makeMesh(data) {
        var m = { data: data, deleted: new Set(), marked: new Set(), selected: new Set(), positions: {}, weights: {}, adjacency: [], connectivity: {}, image: null, weightRevision: 0, geometryRevision: 0, imageRevision: 0, grid: null, positionCount: 0, weightCount: 0, images: [] };
        if (data.uv) {
          var grid = {}, cells = 0; data.triangles.forEach(function (face, index) {
            if (cells > 500000) return; var points = face.map(function (v) { return data.uv[v]; });
            var lowX = Math.max(0, Math.floor(Math.min.apply(null, points.map(function (p) { return p[0]; })) * 16)), highX = Math.min(15, Math.floor(Math.max.apply(null, points.map(function (p) { return p[0]; })) * 16));
            var lowY = Math.max(0, Math.floor(Math.min.apply(null, points.map(function (p) { return p[1]; })) * 16)), highY = Math.min(15, Math.floor(Math.max.apply(null, points.map(function (p) { return p[1]; })) * 16));
            for (var x = lowX; x <= highX; x++) for (var y = lowY; y <= highY; y++) { var cell = x + y * 16; if (!grid[cell]) grid[cell] = []; grid[cell].push(index); cells++; }
          }); if (cells <= 500000) m.grid = grid;
        }
        (data.textures || [data.texture]).forEach(function (uri, index) { if (!uri) return; var img = new Image(); img.onload = function () { m.imageRevision++; if (!disposed) redraw(); }; img.src = uri; m.images[index] = img; }); m.image = m.images[0] || null;
        data.triangles.forEach(function (face) { face.forEach(function (v) { if (!m.adjacency[v]) m.adjacency[v] = new Set(); face.forEach(function (other) { if (v !== other) m.adjacency[v].add(other); }); }); });
        return m;
    }
    async function chooseMesh(panel) {
      var id = panel.mesh.value; if (!id || busy || !interactive()) { redraw(); return; }
      activePanel = panel; if (cache[id]) { fillBones(panel); fillSubmeshes(panel); redraw(); return; }
      var ticket = ++request; busy = true; status(panel, t('Loading…')); redraw(); if (options.onChange) options.onChange();
      try {
        var data = await api('data', { token: token, mesh: JSON.parse(id) }); if (disposed || ticket !== request) return;
        var m = makeMesh(data);
        cache[id] = m; fillBones(panel); fillSubmeshes(panel); status(panel, data.uv ? t('Changes are temporary until saved. Original files are preserved.') : t('No UV coordinates are available. Select vertices by index.'));
      } catch (error) { if (ticket === request) status(panel, error.message, true); }
      finally { if (ticket === request) { busy = false; redraw(); if (options.onChange) options.onChange(); } }
    }
    function checkedRecipe(state) {
      function fail() { throw new Error(t('The mesh recipe is invalid.')); }
      function keys(value, allowed, required) {
        if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(function (name) { return allowed.indexOf(name) < 0; }) ||
            (required || allowed).some(function (name) { return !Object.prototype.hasOwnProperty.call(value, name); })) fail();
      }
      var text;
      try { text = JSON.stringify(state); } catch (_) { fail(); }
      if (!text || text.length > 12 * 1024 * 1024) fail();
      state = JSON.parse(text); keys(state, ['version', 'meshes']);
      if (state.version !== 1 || !Array.isArray(state.meshes) || state.meshes.length > 128) fail();
      var seen = new Set();
      state.meshes.forEach(function (operation) {
        keys(operation, ['mesh', 'deleteFaces', 'positions', 'weights'], ['mesh']);
        var mesh = operation.mesh; keys(mesh, ['source', 'file', 'id']);
        if (!Number.isInteger(mesh.source) || mesh.source < 0 || !Number.isInteger(mesh.file) || mesh.file < 0 ||
            typeof mesh.id !== 'string' || !/^-?[0-9]{1,20}$/.test(mesh.id) || seen.has(key(mesh))) fail();
        seen.add(key(mesh));
        ['deleteFaces', 'positions', 'weights'].forEach(function (field) {
          if (operation[field] === undefined) operation[field] = [];
          if (!Array.isArray(operation[field]) || operation[field].length > (field === 'deleteFaces' ? 200000 : 60000)) fail();
        });
        if (!operation.deleteFaces.length && !operation.positions.length && !operation.weights.length) fail();
      });
      return state;
    }
    function checkedMeshEdits(data, operation) {
      function fail() { throw new Error(t('The mesh recipe is invalid.')); }
      function index(value, length) { if (!Number.isInteger(value) || value < 0 || value >= length) fail(); return value; }
      function number(value) { if (typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value) > 1000000) fail(); return value; }
      function row(value, names) { if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== names.length || names.some(function (name) { return !Object.prototype.hasOwnProperty.call(value, name); })) fail(); }
      if (!data || key(data.mesh || {}) !== key(operation.mesh) || !Array.isArray(data.positions) || !Array.isArray(data.triangles) || !Array.isArray(data.bones)) fail();
      var deleted = new Set(), positions = {}, weights = {}, count = data.positions.length;
      if (operation.deleteFaces.length > data.triangles.length) fail();
      operation.deleteFaces.forEach(function (face) { index(face, data.triangles.length); if (deleted.has(face)) fail(); deleted.add(face); });
      if (operation.positions.length && !data.positionWritable || operation.weights.length && !data.skinWritable) fail();
      operation.positions.forEach(function (value) {
        row(value, ['vertex', 'position']); var vertex = index(value.vertex, count);
        if (Object.prototype.hasOwnProperty.call(positions, vertex) || !Array.isArray(value.position) || value.position.length !== 3) fail();
        positions[vertex] = value.position.map(number);
      });
      operation.weights.forEach(function (value) {
        row(value, ['vertex', 'influences']); var vertex = index(value.vertex, count), influences = value.influences;
        if (Object.prototype.hasOwnProperty.call(weights, vertex) || !Array.isArray(influences) || influences.length < 1 || influences.length > 32) fail();
        influences.forEach(function (pair) { if (!Array.isArray(pair) || pair.length !== 2) fail(); index(pair[0], data.bones.length); number(pair[1]); if (pair[1] < 0 || pair[1] > 1) fail(); });
        var normalized = normalize(influences);
        if (!normalized.length) fail(); weights[vertex] = normalized;
      });
      return { deleted: deleted, positions: positions, weights: weights };
    }
    async function restoreEdits(state) {
      if (disposed) throw new Error(t('The model changed while restoring mesh edits.'));
      if (busy || runtimeEngine && runtimeEngine.getState().activeStroke) throw new Error(t('Wait for mesh editing to finish before restoring a recipe.'));
      state = checkedRecipe(state); refresh();
      if (!token) throw new Error(t('Open a model first.'));
      var selectedToken = token, ticket = ++request;
      function currentRequest() { return !disposed && request === ticket && token === selectedToken && (!options.getToken || options.getToken() === selectedToken); }
      function requireCurrent() { if (!currentRequest()) { var error = new Error(t('The model changed while restoring mesh edits.')); error.name = 'AbortError'; throw error; } }
      var before = JSON.stringify(snapshot());
      if (before.length > 8 * 1024 * 1024) throw new Error(t('The mesh recipe exceeds the undo history limit.'));
      busy = true; redraw(true); if (options.onChange) options.onChange();
      try {
        var listing = await api('inspect', { token: selectedToken }); requireCurrent();
        if (!listing || !Array.isArray(listing.meshes)) throw new Error(t('The mesh recipe is invalid.'));
        var available = new Map(); listing.meshes.forEach(function (record) { if (record.available && record.mesh) available.set(key(record.mesh), record); });
        var prepared = {};
        for (var i = 0; i < state.meshes.length; i++) {
          var operation = state.meshes[i], id = key(operation.mesh), record = available.get(id);
          if (!record) throw new Error(t('The mesh recipe is invalid.'));
          var data = cache[id] ? cache[id].data : await api('data', { token: selectedToken, mesh: record.mesh }); requireCurrent();
          prepared[id] = { data: data, edits: checkedMeshEdits(data, operation) };
        }
        requireCurrent();
        var previous = { cache: cache, values: {}, records: records, history: history.slice(), future: future.slice(), bytes: historyBytes, revision: editRevision, active: activePanel };
        Object.keys(cache).forEach(function (id) { previous.values[id] = Object.assign({}, cache[id]); });
        var panelState = panels.map(function (p) { return { mesh: p.mesh.value, submesh: p.submesh.value, bone: p.bone && p.bone.value, sourceBone: p.sourceBone && p.sourceBone.value }; });
        var next = {};
        Object.keys(cache).forEach(function (id) { var old = cache[id]; next[id] = Object.assign({}, old, { deleted: new Set(), marked: new Set(), selected: new Set(), positions: {}, weights: {}, positionCount: 0, weightCount: 0, weightRevision: old.weightRevision + 1, geometryRevision: (old.geometryRevision || 0) + 1 }); });
        Object.keys(prepared).forEach(function (id) { var item = prepared[id], mesh = next[id] || makeMesh(item.data); mesh.deleted = item.edits.deleted; mesh.positions = item.edits.positions; mesh.weights = item.edits.weights; geometryChanged(mesh); next[id] = mesh; });
        function restorePanels(values, fallback) {
          fillMeshes(); panels.forEach(function (p, index) {
            var value = values[index]; p.mesh.value = cache[value.mesh] ? value.mesh : fallback || '';
            fillBones(p); fillSubmeshes(p);
            [[p.submesh, value.submesh], [p.bone, value.bone], [p.sourceBone, value.sourceBone]].forEach(function (entry) { if (entry[0] && Array.from(entry[0].options).some(function (option) { return option.value === entry[1]; })) entry[0].value = entry[1]; });
            p.baseKey = '';
          });
        }
        try {
          // Runtime bindings and pending image callbacks retain these objects.
          // Commit validated channels into them without replacing their identity.
          Object.keys(next).forEach(function (id) { if (cache[id]) { Object.assign(cache[id], next[id]); next[id] = cache[id]; } });
          cache = next; records = listing.meshes; history.push(before); historyBytes += before.length;
          while (history.length > 24 || historyBytes > 8 * 1024 * 1024) historyBytes -= history.shift().length;
          future = []; restorePanels(panelState, Object.keys(prepared)[0]);
          if (!activePanel || !current(activePanel)) activePanel = panels[0]; changed();
        } catch (error) {
          Object.keys(previous.values).forEach(function (id) { Object.assign(previous.cache[id], previous.values[id]); });
          cache = previous.cache; records = previous.records; history = previous.history; future = previous.future; historyBytes = previous.bytes; editRevision = previous.revision; activePanel = previous.active;
          restorePanels(panelState); redraw(); if (options.onChange) options.onChange(); throw error;
        }
        return clone(operationState());
      } finally { if (currentRequest()) { busy = false; redraw(); if (options.onChange) options.onChange(); } }
    }
    function fillBones(panel) {
      if (!panel.bone) return;
      var m = current(panel); panel.bone.textContent = ''; panel.sourceBone.textContent = ''; panel.locks.textContent = '';
      (m ? m.data.bones : []).forEach(function (name, index) { [panel.bone, panel.sourceBone].forEach(function (s) { var o = el('option', s); o.value = String(index); o.textContent = name + ' [' + index + ']'; }); var label = el('label', panel.locks), input = el('input', label); input.type = 'checkbox'; input.value = String(index); el('span', label).textContent = name; });
    }
    function activeSubmesh(panel, m) {
      return m && m.data.submeshes ? m.data.submeshes[+panel.submesh.value || 0] : null;
    }
    function visibleFace(panel, m, index) {
      var submesh = activeSubmesh(panel, m); return !submesh || index >= submesh.firstFace && index < submesh.firstFace + submesh.faceCount;
    }
    function visibleVertices(panel, m) {
      var result = new Set(); m.data.triangles.forEach(function (face, index) { if (visibleFace(panel, m, index)) face.forEach(function (v) { result.add(v); }); }); return result;
    }
    function fillSubmeshes(panel) {
      var m = current(panel); panel.submesh.textContent = '';
      (m ? m.data.submeshes || [{ index: 0, name: 'Material 1' }] : []).forEach(function (entry) { var option = el('option', panel.submesh); option.value = entry.index; option.textContent = entry.name + ' [' + entry.index + ']'; });
    }
    function draw(panel) {
      var m = current(panel), canvas = panel.canvas, rect = canvas.getBoundingClientRect();
      var target = rect.width > 0 ? Math.max(128, Math.min(2048, Math.round(rect.width * Math.min(2, window.devicePixelRatio || 1)))) : canvas.width;
      if (canvas.width !== target || canvas.height !== target) { canvas.width = target; canvas.height = target; panel.baseKey = ''; }
      var ctx = canvas.getContext('2d'), size = canvas.width, density = size / Math.max(1, rect.width || size);
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, size, size); if (!m || !m.data.uv) return;
      var view = panel.view;
      function point(i) { var uv = m.data.uv[i]; return [uv[0] * size, (1 - uv[1]) * size]; }
      var bone = panel.bone ? +panel.bone.value : 0, submesh = activeSubmesh(panel, m), image = submesh ? (submesh.textureIndex !== null ? m.images[submesh.textureIndex] : null) : m.image;
      function path(context, face) { context.beginPath(); face.forEach(function (v, i) { var p = point(v); if (i) context.lineTo(p[0], p[1]); else context.moveTo(p[0], p[1]); }); context.closePath(); }
      var baseKey = key(m.data.mesh) + '/' + panel.lines.checked + '/' + (window.ViewerUVColor ? window.ViewerUVColor.get() : '') + '/' + (panel.modify ? bone + '/' + m.weightRevision : '') + '/' + m.imageRevision + '/' + (image && image.complete && image.naturalWidth || 0) + '/' + panel.submesh.value + '/' + size + '/' + [view.zoom, view.x, view.y].join('/');
      if (baseKey !== panel.baseKey) {
        if (!panel.base) panel.base = document.createElement('canvas');
        if (panel.base.width !== size || panel.base.height !== size) { panel.base.width = size; panel.base.height = size; }
        var base = panel.base.getContext('2d'); base.setTransform(1, 0, 0, 1, 0, 0); base.clearRect(0, 0, size, size);
        base.setTransform(view.zoom, 0, 0, view.zoom, view.x * size, view.y * size);
        // Resample the original texture into the zoomed viewport. Enlarging a
        // previously reduced 640px image would lose the detail users need.
        if (image && image.complete && image.naturalWidth) base.drawImage(image, 0, 0, size, size);
        if (panel.lines.checked || panel.modify) m.data.triangles.forEach(function (face, index) {
          if (!visibleFace(panel, m, index)) return; path(base, face);
          if (panel.modify && m.data.skin.length) { var value = face.reduce(function (total, v) { var influences = m.weights[v] || m.data.skin[v]; return total + influences.reduce(function (sum, pair) { return sum + (pair[0] === bone ? pair[1] : 0); }, 0); }, 0) / 3; base.fillStyle = 'hsla(' + (240 - value * 240) + ',100%,50%,.35)'; base.fill(); }
          if (panel.lines.checked) { base.strokeStyle = window.ViewerUVColor ? window.ViewerUVColor.stroke(.55) : 'rgba(235,245,255,.55)'; base.lineWidth = .7 * density / view.zoom; base.stroke(); }
        }); panel.baseKey = baseKey;
      }
      ctx.drawImage(panel.base, 0, 0);
      ctx.save(); ctx.setTransform(view.zoom, 0, 0, view.zoom, view.x * size, view.y * size);
      m.deleted.forEach(function (index) { if (!visibleFace(panel, m, index)) return; path(ctx, m.data.triangles[index]); ctx.fillStyle = 'rgba(0,0,0,.8)'; ctx.fill(); });
      m.marked.forEach(function (index) { if (!visibleFace(panel, m, index) || m.deleted.has(index)) return; path(ctx, m.data.triangles[index]); ctx.fillStyle = 'rgba(255,50,80,.65)'; ctx.fill(); });
      if (panel.modify) m.selected.forEach(function (v) { var p = point(v); ctx.beginPath(); ctx.arc(p[0], p[1], 3 * density / view.zoom, 0, Math.PI * 2); ctx.fillStyle = '#ffe05c'; ctx.fill(); });
      ctx.restore();
    }
    function operationState() {
      var result = [];
      Object.keys(cache).forEach(function (id) { var m = cache[id], positions = Object.keys(m.positions).map(function (i) { return { vertex: +i, position: m.positions[i] }; }), weights = Object.keys(m.weights).map(function (i) { return { vertex: +i, influences: m.weights[i] }; }); if (m.deleted.size || positions.length || weights.length) result.push({ mesh: m.data.mesh, deleteFaces: Array.from(m.deleted).sort(function (a, b) { return a - b; }), positions: positions, weights: weights }); });
      return { version: 1, meshes: result };
    }
    function quickStatus() { var count = 0, marked = false; Object.keys(cache).forEach(function (id) { var m = cache[id]; if (m.marked.size) marked = true; if (m.deleted.size || m.marked.size || m.positionCount || m.weightCount) count++; }); return { busy: busy, dirty: count > 0, dirtyCount: count, hasUnappliedSelection: marked, canSave: canSaveCopy(), hasHistory: history.length > 0, redoAvailable: future.length > 0, active: !!activePanel };  }
    function redraw(skipRuntime) {
      var changes = quickStatus().dirtyCount;
      panels.forEach(function (p) {
        var m = current(p); p.load.disabled = !token || busy || !interactive(); p.mesh.disabled = !token || busy || !interactive(); p.save.disabled = !token || busy || !canSaveCopy() || !interactive();
        p.undo.disabled = busy || !!runtimeGesture || !history.length; p.redo.disabled = busy || !!runtimeGesture || !future.length;
        if (p.deleteFaces) p.deleteFaces.disabled = busy || !m || !m.marked.size || !interactive();
        p.canvas.style.opacity = busy ? '.5' : '1';
        p.count.textContent = p.modify ? t('Selected vertices') + ': ' + (m ? m.selected.size : 0) + ' · ' + t('Position and weight edits') + ': ' + (m ? Object.keys(m.positions).length + Object.keys(m.weights).length : 0) : t('Selected faces') + ': ' + (m ? m.marked.size : 0) + ' · ' + t('Deleted faces') + ': ' + (m ? m.deleted.size : 0);
        p.actions.forEach(function (b) { b.disabled = busy || !m || !interactive(); });
        if (p.connected) p.connected.disabled = busy || !m || !(p.modify ? m.selected.size : m.marked.size) || !interactive();
        if (p.zoom) { p.zoom.value = p.view.zoom; p.zoomText.textContent = Math.round(p.view.zoom * 100) + '%'; p.zoom.disabled = busy || !m || !m.data.uv; }
        if (p.viewButtons) p.viewButtons.forEach(function (b) { b.disabled = busy || !m || !m.data.uv; });
        if (p.textureMode) { p.textureMode.disabled = busy || !m || !m.data.uv; p.canvas.style.cursor = p.textureMode.value === 'pan' ? 'grab' : p.textureMode.value === 'connected' ? 'pointer' : 'crosshair'; }
        if (p.syncCanvasTools) p.syncCanvasTools();
        if (p.vertex) {
          p.vertex.max = m ? m.data.positions.length - 1 : 0;
          p.weightApply.disabled = busy || !m || !m.data.skinWritable || !m.selected.size;
          p.positionSet.disabled = busy || !m || !m.data.positionWritable || m.selected.size !== 1;
          p.translate.disabled = busy || !m || !m.data.positionWritable || !m.selected.size;
          var selected = m && Array.from(m.selected), first = selected && selected.length ? selected[0] : null;
          p.values.textContent = first === null ? '' : '#' + first + ' · XYZ: ' + (m.positions[first] || m.data.positions[first]).map(function (v) { return (+v.toFixed(6)); }).join(' / ') + '\n' + (m.weights[first] || m.data.skin[first] || []).map(function (v) { return (m.data.bones[v[0]] || v[0]) + ': ' + (v[1] * 100).toFixed(2) + '%'; }).join(' · ');
          var selectionKey = first === null ? '' : p.mesh.value + ':' + first;
          if (p.positionSelectionKey !== selectionKey) { p.positionSelectionKey = selectionKey; p.positionDraft = false; }
          if (first !== null && !p.positionDraft) p.xyz.forEach(function (field, axis) {
            var value = String((m.positions[first] || m.data.positions[first])[axis]); if (field.value !== value) field.value = value;
          });
          syncMovementTools(p, m);
        }
        draw(p);
      });
      if (skipRuntime !== true) syncRuntime();
    }
    function selection(panel, mode) { var m = current(panel); if (!m || busy) return; remember(); var set = panel.modify ? m.selected : m.marked, count = panel.modify ? m.data.positions.length : m.data.triangles.length, visible = panel.modify ? visibleVertices(panel, m) : null; for (var i = 0; i < count; i++) { if (visible ? !visible.has(i) : !visibleFace(panel, m, i)) continue; if (mode === 'clear') set.delete(i); else if (mode === 'all' || !set.has(i)) set.add(i); else set.delete(i); } changed(); }
    function canClearSelection() {
      if (disposed || busy || runtimeGesture || !interactive() || !activePanel) return false;
      var m = current(activePanel), selected = m && (activePanel.modify ? m.selected : m.marked); return !!(selected && selected.size);
    }
    function clearSelection() {
      if (!canClearSelection()) return false;
      var m = current(activePanel); remember(); (activePanel.modify ? m.selected : m.marked).clear(); changed(); return true;
    }
    function beginRuntimeGesture() {
      if (runtimeGesture) return;
      var before = JSON.stringify(snapshot());
      runtimeGesture = { before: before, history: history.slice(), future: future.slice(), bytes: historyBytes };
      remember(before);
    }
    function endRuntimeGesture(cancel) {
      var gesture = runtimeGesture; runtimeGesture = null;
      if (!gesture) return;
      if (!cancel) {
        var prior = JSON.parse(gesture.before);
        Object.keys(cache).forEach(function (key) {
          var mesh = cache[key], previous = prior[key] && prior[key].positions || {}, altered = false;
          Object.keys(mesh.positions).forEach(function (vertex) {
            var stored = Object.prototype.hasOwnProperty.call(previous, vertex), original = stored ? previous[vertex] : mesh.data.positions[vertex], value = mesh.positions[vertex];
            if (!original || !value.every(function (part, axis) { return Math.abs(part - original[axis]) <= Math.max(1, Math.abs(original[axis])) * 1e-12; })) return;
            if (!stored) { delete mesh.positions[vertex]; altered = true; }
            else if (value.some(function (part, axis) { return part !== original[axis]; })) { mesh.positions[vertex] = original.slice(); altered = true; }
          });
          if (altered) geometryChanged(mesh);
        });
      }
      if (gesture && (cancel || JSON.stringify(snapshot()) === gesture.before)) {
        history = gesture.history; future = gesture.future; historyBytes = gesture.bytes;
        if (cancel) restore(gesture.before); else changed();
      } else {
        panels.forEach(function (p) { p.positionDraft = false; }); changed();
      }
    }
    function setMovementMode(panel, mode) {
      if (busy || runtimeGesture || !interactive() || panel.sceneMode.disabled) return;
      if (window.TexturePanelExpand && window.TexturePanelExpand.getState().expanded === panel.root.id) window.TexturePanelExpand.collapse({ restoreFocus: false });
      activePanel = panel; panel.sceneMode.value = mode; panel.sceneMode.dispatchEvent(new Event('change', { bubbles: true }));
      var runtime = options.getRuntime && options.getRuntime(); if (runtime && runtime.domElement) runtime.domElement.focus({ preventScroll: true });
    }
    function nudgeSelection(panel, axis, sign) {
      var m = current(panel), amount = +panel.moveStep.value;
      if (!m || !m.data.positionWritable || !m.selected.size || busy || runtimeGesture || !interactive()) return;
      if (!panel.moveStep.value.trim() || !panel.moveStep.checkValidity() || !Number.isFinite(amount) || amount <= 0) return status(panel, t('Enter a positive move distance.'), true);
      var updates = {}, valid = true;
      m.selected.forEach(function (vertex) {
        var value = (m.positions[vertex] || m.data.positions[vertex]).slice(); value[axis] += amount * sign;
        if (value.some(function (part) { return !Number.isFinite(part) || Math.abs(part) > 1000000; })) valid = false;
        updates[vertex] = value;
      });
      if (!valid) return;
      activePanel = panel; panel.positionDraft = false; remember();
      Object.keys(updates).forEach(function (vertex) { m.positions[vertex] = updates[vertex]; }); geometryChanged(m); changed();
    }
    function syncMovementTools(panel, m) {
      if (!panel.moveTools) return;
      var locked = busy || !!runtimeGesture || !interactive(), count = m ? m.selected.size : 0;
      panel.moveModeButtons.forEach(function (button) {
        var disabled = locked || !m || panel.sceneMode.disabled, pressed = String(panel.sceneMode.value === button.dataset.meshSceneMode);
        if (button.disabled !== disabled) button.disabled = disabled; if (button.getAttribute('aria-pressed') !== pressed) button.setAttribute('aria-pressed', pressed);
      });
      if (panel.moveAxis.disabled !== locked) panel.moveAxis.disabled = locked;
      if (panel.moveStep.disabled !== locked) panel.moveStep.disabled = locked;
      var moving = panel.sceneMode.value === 'drag';
      if (panel.moveAxis.parentElement.hidden !== !moving) panel.moveAxis.parentElement.hidden = !moving;
      if (panel.moveNudges.hidden !== !(moving && count)) panel.moveNudges.hidden = !(moving && count);
      var invalidStep = !panel.moveStep.value.trim() || !panel.moveStep.checkValidity() || !Number.isFinite(+panel.moveStep.value) || +panel.moveStep.value <= 0;
      var axis = 'xyz'.indexOf(panel.moveAxis.value), name = axis < 0 ? '' : 'XYZ'[axis];
      panel.moveNudgeButtons.forEach(function (button) {
        var disabled = locked || !m || !m.data.positionWritable || !count || invalidStep || axis < 0, sign = button.dataset.meshNudgeSign === '-1' ? '−' : '+';
        if (button.disabled !== disabled) button.disabled = disabled;
        var label = name + sign; if (button.textContent !== label) button.textContent = label;
        var caption = t('Move selected vertices') + ' ' + label; if (button.getAttribute('aria-label') !== caption) button.setAttribute('aria-label', caption);
        var className = axis < 0 ? '' : 'mesh-transform-axis-' + name.toLowerCase(); if (button.className !== className) button.className = className;
      });
    }
    function selectConnected(panel, seeds, erase, toggle, saveHistory) {
      var m = current(panel); if (!m || busy || !interactive()) return;
      var graphKey = panel.seams.checked ? 'seams' : 'indices';
      var graph = m.connectivity[graphKey] || (m.connectivity[graphKey] = buildFaceConnectivity(m.data, panel.seams.checked));
      if (!seeds) {
        seeds = panel.modify ? m.data.triangles.reduce(function (list, face, index) { if (face.some(function (vertex) { return m.selected.has(vertex); })) list.push(index); return list; }, []) : Array.from(m.marked);
      }
      var faces = connectedFaces(graph, seeds, function (face) { return visibleFace(panel, m, face) && !m.deleted.has(face); });
      if (!faces.length) { status(panel, t('Choose a face or vertex first.')); return; }
      var values = faces;
      if (panel.modify) { var vertices = new Set(); faces.forEach(function (face) { m.data.triangles[face].forEach(function (vertex) { vertices.add(vertex); }); }); values = Array.from(vertices); }
      var set = panel.modify ? m.selected : m.marked;
      if (toggle) erase = values.every(function (value) { return set.has(value); });
      if (!values.some(function (value) { return set.has(value) === !!erase; })) return;
      if (saveHistory !== false) remember();
      values.forEach(function (value) { if (erase) set.delete(value); else set.add(value); }); changed();
    }
    function stamp(panel, x, y) {
      var m = current(panel); if (!m || !m.data.uv) return;
      var radius = Math.max(2, Math.min(200, +panel.radius.value || 20)) / Math.max(1, panel.canvas.getBoundingClientRect().width) / panel.view.zoom, add = panel.mode.value === 'paint', uv = m.data.uv;
      if (panel.modify) { var visible = visibleVertices(panel, m); uv.forEach(function (p, i) { if (visible.has(i) && Math.hypot(p[0] - x, p[1] - y) <= radius) { if (add) m.selected.add(i); else m.selected.delete(i); } }); }
      else {
        var candidates = null;
        if (m.grid) { candidates = new Set(); for (var gx = Math.max(0, Math.floor((x - radius) * 16)); gx <= Math.min(15, Math.floor((x + radius) * 16)); gx++) for (var gy = Math.max(0, Math.floor((y - radius) * 16)); gy <= Math.min(15, Math.floor((y + radius) * 16)); gy++) (m.grid[gx + gy * 16] || []).forEach(function (i) { candidates.add(i); }); }
        function paint(i) { if (!visibleFace(panel, m, i)) return; var face = m.data.triangles[i]; if (intersects(x, y, radius, uv[face[0]], uv[face[1]], uv[face[2]])) { if (!m.deleted.has(i)) { if (add) m.marked.add(i); else m.marked.delete(i); } } }
        if (candidates) candidates.forEach(paint); else m.data.triangles.forEach(function (_, i) { paint(i); });
      }
    }
    function attachCanvas(panel) {
      var pointers = new Map(), stroke = null;
      function position(event) { var r = panel.canvas.getBoundingClientRect(); return [(event.clientX - r.left) / Math.max(1, r.width), (event.clientY - r.top) / Math.max(1, r.height)]; }
      function valid() { var m = current(panel); return !busy && interactive() && m && m.data.uv; }
      function view(value) { panel.view = clampView(value); redraw(true); }
      function hideCursor() { if (uvCursor) uvCursor.hidden = true; }
      function beginPaint(point) { remember(); stroke.kind = 'paint'; stroke.previous = viewToUv(point, panel.view); stamp(panel, stroke.previous[0], stroke.previous[1]); redraw(); }
      function connected(point, event) {
        var m = current(panel), uv = viewToUv(point, panel.view), seeds = [];
        m.data.triangles.forEach(function (face, index) { if (visibleFace(panel, m, index) && !m.deleted.has(index) && intersects(uv[0], uv[1], 0, m.data.uv[face[0]], m.data.uv[face[1]], m.data.uv[face[2]])) seeds.push(index); });
        selectConnected(panel, seeds, panel.mode.value === 'erase', !!event.shiftKey);
      }
      function pinch() {
        if (stroke && stroke.kind === 'paint') changed();
        var points = Array.from(pointers.values()), a = points[0], b = points[1];
        stroke = { kind: 'pinch', distance: Math.max(.0001, Math.hypot(a[0] - b[0], a[1] - b[1])), centre: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], view: Object.assign({}, panel.view) }; hideCursor();
      }
      on(panel.canvas, 'pointerdown', function (event) {
        if (!valid() || event.button > 2) return;
        event.preventDefault(); activePanel = panel; panel.canvas.focus({ preventScroll: true });
        var point = position(event); pointers.set(event.pointerId, point); panel.canvas.setPointerCapture(event.pointerId);
        if (pointers.size > 1) { pinch(); return; }
        stroke = { kind: 'pending', anchor: point, view: Object.assign({}, panel.view), event: { shiftKey: event.shiftKey } };
        if (panel.textureMode.value === 'pan' || event.altKey || event.button === 1 || event.button === 2) { stroke.kind = 'pan'; hideCursor(); }
        else if (panel.textureMode.value === 'connected') { stroke.kind = 'connected'; if (event.pointerType !== 'touch') connected(point, event); }
        else if (event.pointerType !== 'touch') beginPaint(point);
      });
      on(panel.canvas, 'pointermove', function (event) {
        if (!pointers.has(event.pointerId) || !stroke) return;
        event.preventDefault(); var point = position(event); pointers.set(event.pointerId, point);
        if (stroke.kind === 'pinch' && pointers.size > 1) {
          var points = Array.from(pointers.values()), a = points[0], b = points[1], centre = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
          var zoom = Math.max(1, Math.min(16, stroke.view.zoom * Math.hypot(a[0] - b[0], a[1] - b[1]) / stroke.distance)), uv = viewToUv(stroke.centre, stroke.view);
          view({ zoom: zoom, x: centre[0] - uv[0] * zoom, y: centre[1] - (1 - uv[1]) * zoom }); return;
        }
        if (stroke.kind === 'pan') { view({ zoom: stroke.view.zoom, x: stroke.view.x + point[0] - stroke.anchor[0], y: stroke.view.y + point[1] - stroke.anchor[1] }); return; }
        if (stroke.kind === 'pending' && Math.hypot(point[0] - stroke.anchor[0], point[1] - stroke.anchor[1]) * panel.canvas.getBoundingClientRect().width >= 4) beginPaint(stroke.anchor);
        if (stroke.kind !== 'paint') return;
        var next = viewToUv(point, panel.view), previous = stroke.previous, distance = Math.hypot(next[0] - previous[0], next[1] - previous[1]);
        var step = Math.max(.0001, (+panel.radius.value || 20) / Math.max(1, panel.canvas.getBoundingClientRect().width) / panel.view.zoom / 2), steps = Math.min(200, Math.max(1, Math.ceil(distance / step)));
        for (var i = 1; i <= steps; i++) stamp(panel, previous[0] + (next[0] - previous[0]) * i / steps, previous[1] + (next[1] - previous[1]) * i / steps);
        stroke.previous = next; redraw();
      });
      function end(event) {
        if (!pointers.has(event.pointerId)) return;
        var point = pointers.get(event.pointerId), previous = stroke; pointers.delete(event.pointerId);
        if (previous && event.type === 'pointerup' && valid()) {
          if (previous.kind === 'pending') beginPaint(point);
          else if (previous.kind === 'connected' && event.pointerType === 'touch') connected(point, previous.event);
        }
        if (pointers.size) { var remaining = Array.from(pointers.values())[0]; stroke = { kind: 'pan', anchor: remaining, view: Object.assign({}, panel.view) }; }
        else { stroke = null; if (previous && (previous.kind === 'paint' || previous.kind === 'pending' || previous.kind === 'connected')) changed(); }
      }
      on(panel.canvas, 'pointerup', end); on(panel.canvas, 'pointercancel', end); on(panel.canvas, 'lostpointercapture', end);
      on(panel.canvas, 'contextmenu', function (event) { event.preventDefault(); });
      // Non-passive is required to keep a wheel gesture over the texture from
      // also scrolling the surrounding editor on Android and desktop WebViews.
      var wheel = function (event) { if (!valid()) return; event.preventDefault(); if (pointers.size) return; activePanel = panel; var delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? panel.canvas.getBoundingClientRect().height : 1); view(zoomView(panel.view, panel.view.zoom * Math.exp(-delta * .002), position(event))); hideCursor(); };
      panel.canvas.addEventListener('wheel', wheel, { passive: false }); listeners.push(function () { panel.canvas.removeEventListener('wheel', wheel); });
      on(panel.canvas, 'keydown', function (event) { if (!valid() || event.ctrlKey || event.metaKey || event.altKey) return; var zoom = event.key === '+' || event.key === '=' ? panel.view.zoom * Math.SQRT2 : event.key === '-' ? panel.view.zoom / Math.SQRT2 : event.key === '0' ? 1 : null; if (zoom === null) return; event.preventDefault(); view(event.key === '0' ? { zoom: 1, x: 0, y: 0 } : zoomView(panel.view, zoom)); hideCursor(); });
    }
    function changePosition(panel, absolute) {
      var m = current(panel); if (!m || !m.selected.size) return status(panel, t('Choose vertices first.'), true);
      if (absolute && m.selected.size !== 1) return status(panel, t('Choose one vertex for an absolute position.'), true);
      var fields = absolute ? panel.xyz : panel.delta, value = fields.map(function (i) { return +i.value; });
      if (fields.some(function (i) { return !i.checkValidity() || !i.value.trim(); }) || value.some(function (v) { return !Number.isFinite(v); })) return;
      remember(); panel.positionDraft = false; m.selected.forEach(function (v) { var old = m.positions[v] || m.data.positions[v]; m.positions[v] = absolute ? value.slice() : old.map(function (n, axis) { return n + value[axis]; }); }); geometryChanged(m); changed();
    }
    function applyWeights(panel) {
      var m = current(panel); if (!m || !m.data.skinWritable || !m.selected.size) return;
      var bone = +panel.bone.value, sourceBone = +panel.sourceBone.value, amount = +panel.weight.value, mode = panel.weightMode.value, locks = {};
      Array.from(panel.locks.querySelectorAll('input:checked')).forEach(function (i) { locks[i.value] = true; });
      if (locks[bone]) return status(panel, t('Select a different unlocked bone.'), true);
      if (!panel.weight.checkValidity() || !Number.isFinite(amount) || !panel.weight.value.trim()) return;
      var before = clone(m.weights), updates = {};
      m.selected.forEach(function (vertex) {
        var old = before[vertex] || m.data.skin[vertex], values = {}, lockedTotal = 0;
        old.forEach(function (pair) { values[pair[0]] = pair[1]; if (locks[pair[0]]) lockedTotal += pair[1]; });
        var target = values[bone] || 0;
        if (mode === 'smooth') { var neighbors = Array.from(m.adjacency[vertex] || []), sum = 0; neighbors.forEach(function (v) { var pairs = before[v] || m.data.skin[v]; sum += pairs.reduce(function (total, p) { return total + (p[0] === bone ? p[1] : 0); }, 0); }); target = neighbors.length ? target * (1 - amount) + sum / neighbors.length * amount : target; }
        else if (mode === 'transfer') { if (sourceBone !== bone && !locks[sourceBone]) { target += (values[sourceBone] || 0) * amount; values[sourceBone] = (values[sourceBone] || 0) * (1 - amount); } }
        else target = mode === 'set' ? amount : mode === 'add' ? target + amount : target - amount;
        updates[vertex] = redistributeInfluence(old, bone, target, locks, values);
      });
      remember(); Object.keys(updates).forEach(function (v) { if (updates[v].length) m.weights[v] = updates[v]; }); m.weightRevision++; geometryChanged(m); changed();
    }
    async function save(panel) {
      var state = operationState(); if (!token || busy || !interactive() || !canSaveCopy()) return;
      var ticket = ++request, selectedToken = token; busy = true; status(panel, t('Saving…')); redraw(); if (options.onChange) options.onChange();
      try {
        var response = await api('export', { token: selectedToken, state: state, bodyState: options.getBodyState ? options.getBodyState() : null });
        if (disposed || ticket !== request) return;
        lastSaved = response; savedToken = selectedToken; savedFingerprint = JSON.stringify(state);
        panels.forEach(function (p) { p.result.textContent = ''; (response.output_paths || []).forEach(function (path) { var item = el('li', p.result), link = el('a', item); link.textContent = String(path).split('/').pop(); link.href = '/api/download?path=' + encodeURIComponent(path); link.download = link.textContent; }); });
        status(panel, (response.output_paths || []).join('\n'));
        if (options.onSaved) await options.onSaved(response, selectedToken);
      } catch (error) { if (!disposed && ticket === request) status(panel, error.message, true); }
      finally { if (!disposed && ticket === request) { busy = false; redraw(); if (options.onChange) options.onChange(); } }
    }
    function canvasWorkspace(p) {
      var box = p.root, original = Array.from(box.children).filter(function (node) { return node.tagName !== 'SUMMARY'; });
      var workspace = el('div', box); workspace.className = 'uv-edit-workspace';
      var main = el('div', workspace); main.className = 'uv-edit-main';
      var source = el('div', main); source.className = 'uv-edit-source';
      if (p.modify) {
        p.moveTools = el('div', main); p.moveTools.className = 'mesh-transform-tools'; p.moveTools.setAttribute('role', 'group'); p.moveTools.setAttribute('aria-label', t('Move selected vertices'));
        var moveRow = el('div', p.moveTools); moveRow.className = 'mesh-transform-row'; p.moveModeButtons = [];
        [['pick', 'Pick'], ['drag', 'Move']].forEach(function (entry) {
          var quick = button(moveRow, entry[1], function () { setMovementMode(p, entry[0]); }); quick.dataset.meshSceneMode = entry[0]; quick.id = p.root.id + '-quick-' + entry[0]; quick.setAttribute('aria-pressed', 'false'); quick.setAttribute('aria-label', t(entry[0] === 'pick' ? 'Pick vertices' : 'Move vertices in 3D')); p.moveModeButtons.push(quick);
        });
        p.moveAxis = select(moveRow, 'Move axis', [['screen', 'Screen plane'], ['x', 'X'], ['y', 'Y'], ['z', 'Z']]); p.moveAxis.id = p.root.id + '-move-axis';
        p.moveAxis.parentElement.classList.add('mesh-transform-axis-label'); p.moveAxis.parentElement.hidden = true; p.moveAxis.setAttribute('aria-label', t('Move axis'));
        on(p.moveAxis, 'change', function () { activePanel = p; if (options.onChange) options.onChange(); syncRuntime(); });
        p.moveNudges = el('div', p.moveTools); p.moveNudges.className = 'mesh-transform-row'; p.moveNudges.hidden = true;
        p.moveStep = numeric(p.moveNudges, 'Step', .01, .000001, 1000000, 'any'); p.moveStep.id = p.root.id + '-move-step'; p.moveStep.setAttribute('aria-label', t('Move step'));
        on(p.moveStep, 'input', function () { syncMovementTools(p, current(p)); });
        p.moveNudgeButtons = [];
        [-1, 1].forEach(function (sign) {
          var quick = button(p.moveNudges, sign < 0 ? '−' : '+', function () { var axis = 'xyz'.indexOf(p.moveAxis.value); if (axis >= 0) nudgeSelection(p, axis, sign); });
          quick.id = p.root.id + '-nudge-' + (sign < 0 ? 'minus' : 'plus'); quick.dataset.meshNudgeSign = String(sign); p.moveNudgeButtons.push(quick);
        });
        p.moveTools.title = t('Drag an axis arrow, or use the step buttons. Axis values use the source mesh coordinates.');
      }
      var tools = el('div', main); tools.className = 'uv-edit-toolbar'; tools.setAttribute('role', 'toolbar'); tools.setAttribute('aria-label', t('Texture interaction'));
      var stage = el('div', main); stage.className = 'uv-canvas-stage'; stage.appendChild(p.canvas);
      var resize = el('div', main); resize.className = 'uv-canvas-resizer'; resize.tabIndex = 0; resize.setAttribute('role', 'separator'); resize.setAttribute('aria-orientation', 'horizontal');
      var view = el('div', main); view.className = 'uv-edit-viewbar';
      var footer = el('div', main); footer.className = 'uv-edit-footer';
      var inspector = el('aside', workspace); inspector.className = 'uv-edit-inspector'; inspector.hidden = true;
      var settings = button(tools, 'Tool settings', function () {}); settings.className = 'uv-icon-button uv-settings-button'; settings.dataset.uvSettings = ''; settings.setAttribute('aria-expanded', 'false');
      original.forEach(function (node) { if (node !== p.canvas) inspector.appendChild(node); });
      function move(control, destination) { if (!control) return; var node = control.parentElement && control.parentElement.tagName === 'LABEL' ? control.parentElement : control; destination.appendChild(node); }
      move(p.load, source); p.load.classList.add('uv-refresh-button'); p.load.title = t('Load meshes'); move(p.mesh, source); move(p.submesh, source);
      var quick = [];
      [['paint', 'Brush'], ['erase', 'Erase'], ['connected', 'Linked'], ['pan', 'Pan']].forEach(function (row) {
        var b = button(null, row[1], function () {
          activePanel = p; p.textureMode.value = row[0] === 'erase' ? 'paint' : row[0]; p.mode.value = row[0] === 'erase' ? 'erase' : 'paint';
          p.textureMode.dispatchEvent(new Event('change', { bubbles: true })); if (uvCursor) uvCursor.hidden = true;
        });
        b.id = p.root.id + '-tool-' + row[0]; b.dataset.uvTool = row[0]; b.title = t(row[0] === 'connected' ? 'Connected faces' : row[0] === 'pan' ? 'Move texture' : row[1]) + ' (' + ({ paint: 'B', erase: 'E', connected: 'L', pan: 'V' }[row[0]]) + ')'; tools.insertBefore(b, settings); quick.push(b);
      });
      move(p.radius, tools); p.radius.parentElement.classList.add('uv-compact-radius');
      tools.insertBefore(p.undo, settings); tools.insertBefore(p.redo, settings); p.undo.classList.add('uv-undo-button'); p.redo.classList.add('uv-redo-button');
      var menu = el('details', tools); menu.className = 'uv-selection-menu'; el('summary', menu, 'Selection'); var items = el('div', menu);
      p.actions.slice(0, 3).forEach(function (b) { items.appendChild(b); }); move(p.connected, items);
      tools.insertBefore(p.radius.parentElement, p.undo); tools.appendChild(settings);
      move(p.zoomOut, view); move(p.zoomIn, view); move(p.fitTexture, view); view.appendChild(p.zoomText); move(p.count, view);
      move(p.deleteFaces, footer); move(p.save, footer); move(p.status, main); move(p.result, inspector);
      Array.from(inspector.querySelectorAll('.mesh-row')).forEach(function (row) { if (!row.children.length) row.remove(); });
      p.syncCanvasTools = function () {
        var selected = p.textureMode.value === 'paint' && p.mode.value === 'erase' ? 'erase' : p.textureMode.value;
        quick.forEach(function (b) { var pressed = String(b.dataset.uvTool === selected); if (b.getAttribute('aria-pressed') !== pressed) b.setAttribute('aria-pressed', pressed); if (b.disabled !== p.textureMode.disabled) b.disabled = p.textureMode.disabled; });
      };
      on(p.mode, 'change', p.syncCanvasTools); on(p.textureMode, 'change', p.syncCanvasTools); p.syncCanvasTools();
      on(p.canvas, 'keydown', function (event) {
        if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
        var key = String(event.key).toLowerCase(), mode = { b: 'paint', e: 'erase', l: 'connected', v: 'pan' }[key];
        if (mode) { var target = quick.find(function (b) { return b.dataset.uvTool === mode; }); if (!target.disabled) { event.preventDefault(); event.stopPropagation(); target.click(); } }
        else if ((key === '[' || key === ']') && !p.textureMode.disabled) { event.preventDefault(); p.radius.value = Math.max(2, Math.min(200, +p.radius.value + (key === '[' ? -2 : 2))); if (uvCursor) uvCursor.hidden = true; }
        else if (key === 'home' && !p.fitTexture.disabled) { event.preventDefault(); p.fitTexture.click(); }
      });
    }
    function build(modify) {
      var box = el('details', holder); box.id = modify ? 'viewer-mesh-modify' : 'viewer-mesh-deleter'; box.className = 'viewer-adjustments viewer-mesh-tools';
      el('summary', box, modify ? 'Mesh modify' : 'Mesh deleter');
      el('p', box, modify ? 'Paint to select vertices, then edit positions or normalized weights.' : 'Paint selects faces. Delete selected faces removes them from the model. Ctrl/Cmd+Z restores the mesh.').className = 'viewer-render-note';
      var p = { root: box, modify: modify, actions: [], view: { zoom: 1, x: 0, y: 0 }, viewButtons: [] }, row = el('div', box); row.className = 'mesh-row';
      p.load = button(row, 'Load meshes', function () { inspectMeshes(p); }); p.mesh = select(row, 'Mesh', [['', 'Choose a mesh']]); on(p.mesh, 'change', function () { chooseMesh(p); });
      p.submesh = select(box, 'Material / submesh'); on(p.submesh, 'change', function () { activePanel = p; var m = current(p); if (m && p.modify) m.selected.clear(); p.baseKey = ''; changed(); });
      row = el('div', box); row.className = 'mesh-row'; p.mode = select(row, 'Paint', [['paint', 'Paint'], ['erase', 'Erase']]); p.radius = numeric(row, 'Brush radius', 30, 2, 200, 1);
      row = el('div', box); row.className = 'mesh-row';
      p.sceneMode = select(row, '3D editing', modify ? [['orbit', 'Orbit model'], ['paint', 'Paint on model'], ['connected', 'Connected faces'], ['pick', 'Pick vertices'], ['drag', 'Move vertices in 3D']] : [['orbit', 'Orbit model'], ['paint', 'Paint on model'], ['connected', 'Connected faces']]);
      on(p.sceneMode, 'change', function () { activePanel = p; if (options.onSceneModeChange) options.onSceneModeChange(p.sceneMode.value); changed(); });
      on(p.sceneMode, 'focus', function () { if (p.sceneMode.value !== 'orbit' && options.onSceneModeChange) options.onSceneModeChange(p.sceneMode.value); });
      function check3d(title, initial) { var label = el('label', row), input = el('input', label); input.type = 'checkbox'; input.checked = initial; el('span', label, title); on(input, 'change', function () { activePanel = p; changed(); }); return input; }
      p.show3d = check3d('Show selection on model', true); p.showVertices = check3d('Show vertex targets', modify); p.liveStatus = el('p', box); p.liveStatus.className = 'viewer-render-note';
      el('p', box, 'Use Alt or right-drag to orbit while editing. Shift-click adds or removes vertices.').className = 'viewer-render-note';
      on(box, 'focusin', function () { activePanel = p; syncRuntime(); });

      var linesLabel = el('label', row); p.lines = el('input', linesLabel); p.lines.type = 'checkbox'; p.lines.checked = true; el('span', linesLabel, 'Show UV lines'); on(p.lines, 'change', redraw);
      if (window.ViewerUVColor) p.uvColor = window.ViewerUVColor.control(row, { id: p.root.id + '-uv-color', translate: t, onChange: function () { redraw(true); } });
      var seamLabel = el('label', row); p.seams = el('input', seamLabel); p.seams.type = 'checkbox'; p.seams.checked = true; el('span', seamLabel, 'Across UV seams');
      row = el('div', box); row.className = 'mesh-row'; p.textureMode = select(row, 'Texture interaction', [['paint', 'Paint'], ['pan', 'Move texture'], ['connected', 'Connected faces']]);
      on(p.textureMode, 'change', function () { activePanel = p; if (uvCursor) uvCursor.hidden = true; redraw(true); });
      function setView(value) { p.view = clampView(value); if (uvCursor) uvCursor.hidden = true; redraw(true); }
      p.zoomOut = button(row, 'Zoom out', function () { setView(zoomView(p.view, p.view.zoom / Math.SQRT2)); });
      p.zoomIn = button(row, 'Zoom in', function () { setView(zoomView(p.view, p.view.zoom * Math.SQRT2)); });
      p.fitTexture = button(row, 'Fit texture', function () { setView({ zoom: 1, x: 0, y: 0 }); }); p.viewButtons.push(p.zoomOut, p.zoomIn, p.fitTexture);
      var zoomLabel = el('label', row); el('span', zoomLabel, 'Texture zoom'); p.zoom = el('input', zoomLabel); p.zoom.type = 'range'; p.zoom.min = 1; p.zoom.max = 16; p.zoom.step = .25; p.zoom.value = 1;
      p.zoomText = el('output', zoomLabel); p.zoomText.textContent = '100%'; on(p.zoom, 'input', function () { setView(zoomView(p.view, +p.zoom.value)); });
      el('p', box, 'Scroll or pinch to zoom. Use Move texture, Alt-drag or right-drag to pan.').className = 'viewer-render-note';
      p.canvas = el('canvas', box); p.canvas.width = 640; p.canvas.height = 640; p.canvas.setAttribute('aria-label', t(modify ? 'Selected vertices' : 'Selected faces')); p.canvas.tabIndex = 0;
      on(p.canvas, 'texturepanechange', function () { if (!disposed) draw(p); });
      if (typeof ResizeObserver === 'function') {
        var textureObserver = new ResizeObserver(function () { if (!disposed && p.canvas.getBoundingClientRect().width > 0) draw(p); });
        textureObserver.observe(p.canvas); listeners.push(function () { textureObserver.disconnect(); });
      }
      var imageLabel = el('label', box); el('span', imageLabel, 'Texture image'); var imageInput = el('input', imageLabel); imageInput.type = 'file'; imageInput.accept = 'image/png,image/jpeg,image/webp';
      on(imageInput, 'change', function () { var m = current(p), file = imageInput.files[0]; if (!m || !file || file.size > 8 * 1024 * 1024) return; var url = URL.createObjectURL(file), img = new Image(); img.onload = function () { URL.revokeObjectURL(url); if (!disposed) { var entry = activeSubmesh(p, m), index = entry && entry.textureIndex !== null ? entry.textureIndex : m.images.length; m.images[index] = img; if (entry) entry.textureIndex = index; else m.image = img; m.imageRevision++; redraw(); } }; img.onerror = function () { URL.revokeObjectURL(url); }; img.src = url; });
      row = el('div', box); row.className = 'mesh-row'; p.undo = button(row, 'Undo', undo); p.redo = button(row, 'Redo', redo);
      ['clear', 'invert', 'all'].forEach(function (mode) { p.actions.push(button(row, { clear: 'Clear selection', invert: 'Invert selection', all: 'Select all' }[mode], function () { selection(p, mode); })); });
      p.connected = button(row, 'Select connected', function () { selectConnected(p); });
      el('p', box, 'Connected selection stays in the selected material. Use the model to distinguish overlapping UVs.').className = 'viewer-render-note';
      p.count = el('p', box); p.count.className = 'viewer-render-note';
      if (!modify) p.deleteFaces = button(box, 'Delete selected faces', function () { deleteMarked(p); });
      if (modify) {
        row = el('div', box); row.className = 'mesh-row'; p.vertex = numeric(row, 'Vertex index', 0, 0, 0, 1);
        var selectVertexButton = button(row, 'Select vertex', function () { var m = current(p), v = +p.vertex.value; if (!m || !Number.isInteger(v) || v < 0 || v >= m.data.positions.length) return; remember(); m.selected.clear(); m.selected.add(v); var value = m.positions[v] || m.data.positions[v]; p.xyz.forEach(function (field, axis) { field.value = value[axis]; }); changed(); }); selectVertexButton.id = box.id + '-select-vertex'; p.actions.push(selectVertexButton);
        p.values = el('p', box); p.values.className = 'mesh-value-table';
        var position = el('fieldset', box); el('legend', position, 'Position (mesh local XYZ)'); row = el('div', position); row.className = 'mesh-row'; p.xyz = ['X', 'Y', 'Z'].map(function (axis) { return numeric(row, axis, 0, -1000000, 1000000, .001); });
        p.positionSet = button(position, 'Set vertex position', function () { changePosition(p, true); });
        row = el('div', position); row.className = 'mesh-row'; p.delta = ['X', 'Y', 'Z'].map(function (axis) { return numeric(row, 'Δ ' + axis, 0, -1000000, 1000000, .001); });
        p.translate = button(position, 'Translate selected vertices', function () { changePosition(p, false); });
        var weight = el('fieldset', box); el('legend', weight, 'Weight'); row = el('div', weight); row.className = 'mesh-row'; p.bone = select(row, 'Bone'); p.sourceBone = select(row, 'Source bone'); on(p.bone, 'change', redraw);
        row = el('div', weight); row.className = 'mesh-row'; p.weightMode = select(row, 'Weight mode', [['set', 'Set'], ['add', 'Add'], ['subtract', 'Subtract'], ['smooth', 'Smooth'], ['transfer', 'Transfer from bone']]); p.weight = numeric(row, 'Weight', .5, 0, 1, .01);
        p.weightApply = button(weight, 'Apply weights to selection', function () { applyWeights(p); });
        var lock = el('details', weight); el('summary', lock, 'Lock bone weights'); p.locks = el('div', lock); p.locks.className = 'mesh-weights';
        el('p', weight, 'Locked bones retain their current weights. Remaining weights normalize to a total of 1, with at most four influences.').className = 'viewer-render-note';
      }
      p.actions.push(button(box, 'Restore mesh changes', function () { var m = current(p); if (!m) return; remember(); m.deleted.clear(); m.marked.clear(); m.selected.clear(); m.positions = {}; m.weights = {}; m.weightRevision++; geometryChanged(m); changed(); }));
      p.save = button(box, 'Save mesh copy', function () { save(p); }); p.save.className = 'mesh-save'; el('p', box, 'Saved copies keep their version. Undo restores the live mesh; save again to create a restored copy.').className = 'viewer-render-note'; p.result = el('ul', box);
      p.status = el('p', box, 'Open a model first.'); p.status.className = 'viewer-render-note'; p.status.setAttribute('role', 'status'); p.status.setAttribute('aria-live', 'polite');
      var prefix = box.id;
      ['load', 'mesh', 'submesh', 'sceneMode', 'show3d', 'showVertices', 'deleteFaces', 'canvas', 'save', 'undo', 'redo', 'count', 'status', 'vertex', 'weight', 'weightMode', 'bone', 'positionSet', 'translate', 'weightApply', 'mode', 'radius', 'seams', 'connected', 'textureMode', 'zoom', 'zoomIn', 'zoomOut', 'fitTexture'].forEach(function (name) {
        if (p[name]) p[name].id = prefix + '-' + ({ mesh: 'select', sceneMode: 'scene-mode', show3d: 'show-selection', showVertices: 'show-vertices', deleteFaces: 'delete', weight: 'weight-value', weightMode: 'weight-mode', bone: 'weight-bone', positionSet: 'position-set', weightApply: 'weight-apply', textureMode: 'texture-mode', zoomIn: 'zoom-in', zoomOut: 'zoom-out', fitTexture: 'fit-texture' }[name] || name);
      });
      if (p.xyz) p.xyz.forEach(function (field, axis) { field.dataset.meshPositionAxis = 'XYZ'[axis]; field.step = 'any'; });
      if (p.xyz) p.xyz.forEach(function (field) { on(field, 'input', function () { p.positionDraft = true; }); on(field, 'change', function () { p.positionDraft = true; }); });
      if (p.delta) p.delta.forEach(function (field, axis) { field.dataset.meshDeltaAxis = 'XYZ'[axis]; field.step = 'any'; });
      if (p.weight) p.weight.step = 'any';
      canvasWorkspace(p);
      panels.push(p); attachCanvas(p);
    }
    function persistentChangeCount() { var count = 0; Object.keys(cache).forEach(function (id) { var m = cache[id]; if (m.deleted.size || m.positionCount || m.weightCount) count++; }); return count; }
    function canSaveCopy() { return !runtimeGesture && (persistentChangeCount() > 0 || savedToken === token && !!savedFingerprint); }
    function deleteMarked(panel) { var m = current(panel); if (!m || !m.marked.size || busy) return; activePanel = panel; remember(); m.marked.forEach(function (face) { m.deleted.add(face); }); m.marked.clear(); geometryChanged(m); changed(); }
    function runtimeContext() {
      var p = activePanel, m = p && current(p); if (!p || !m || p.root.hidden) return null;
      return { mesh: m, modify: p.modify, mode: p.sceneMode.value, submesh: +p.submesh.value || 0,
        dragAxis: p.moveAxis ? p.moveAxis.value : 'screen',
        radius: +p.radius.value || 20, erase: p.mode.value === 'erase', showSelection: p.show3d.checked,
        showVertices: p.modify && p.showVertices.checked, interactive: interactive() && !busy && (!options.isSceneInteractive || options.isSceneInteractive()) };
    }
    function syncRuntime() {
      if (!runtimeEngine) return;
      runtimeEngine.sync(Object.keys(cache).map(function (id) { return cache[id]; }));
      var state = runtimeEngine.getState(); panels.forEach(function (p) { var m = current(p), mapped = m && state.bindings.some(function (binding) { return key(binding.mesh) === key(m.data.mesh); });
        p.sceneMode.disabled = !mapped || busy || !interactive();
        p.liveStatus.textContent = m && !mapped ? t('3D mapping unavailable for this mesh. UV editing remains available.') : '';
        if (p.modify) syncMovementTools(p, m);
      });
    }
    function chooseVertex(vertex, additive, dragging) {
      var p = activePanel, m = p && current(p); if (!m) return;
      if (additive) { if (m.selected.has(vertex)) m.selected.delete(vertex); else m.selected.add(vertex); }
      else if (!dragging || !m.selected.has(vertex)) { m.selected.clear(); m.selected.add(vertex); }
      if (p.vertex) { p.vertex.value = vertex; var value = m.positions[vertex] || m.data.positions[vertex]; p.xyz.forEach(function (field, axis) { field.value = value[axis]; }); }
      changed();
    }
    function initializeRuntime() {
      if (!window.ViewerMeshRuntime || !options.getRuntime) return;
      runtimeEngine = window.ViewerMeshRuntime.create({ getRuntime: options.getRuntime, getContext: runtimeContext,
        onBegin: beginRuntimeGesture,
        onPaint: function (indices, erase, modify) { var m = activePanel && current(activePanel); if (!m) return; var set = modify ? m.selected : m.marked, altered = false; indices.forEach(function (index) { if (erase) { if (set.delete(index)) altered = true; } else if ((modify || !m.deleted.has(index)) && !set.has(index)) { set.add(index); altered = true; } }); if (altered) redraw(); },
        onSelect: chooseVertex,
        onConnected: function (face, erase, toggle) { if (activePanel) selectConnected(activePanel, [face], erase, toggle, false); },
        onDrag: function (values) { var m = activePanel && current(activePanel); if (!m) return; Object.keys(values).forEach(function (vertex) { m.positions[vertex] = values[vertex]; }); geometryChanged(m); changed(); },
        onEnd: endRuntimeGesture
      });
    }
    function handleShortcut(event) {
      if (disposed || busy || !interactive() || !activePanel || (!event.ctrlKey && !event.metaKey) || event.altKey) return false;
      var target = event.target || document.activeElement;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return false;
      var name = String(event.key || '').toLowerCase(), action = null;
      if (name === 'z') action = event.shiftKey ? (future.length ? redo : null) : (history.length ? undo : null);
      else if (name === 'y') action = future.length ? redo : null;
      else if (name === 's' && canSaveCopy()) action = function () { save(activePanel); };
      if (!action) return false;
      event.preventDefault(); if (event.stopImmediatePropagation) event.stopImmediatePropagation(); action(); return true;
    }
    function initializeShortcuts() {
      document.addEventListener('keydown', handleShortcut, true); listeners.push(function () { document.removeEventListener('keydown', handleShortcut, true); });
      uvCursor = el('div', document.body); uvCursor.id = 'viewer-mesh-uv-cursor'; uvCursor.hidden = true; uvCursor.setAttribute('aria-hidden', 'true'); uvCursor.style.cssText = 'position:fixed;z-index:12000;pointer-events:none;border:2px solid #ffdb52;box-shadow:0 0 0 1px #17202b;border-radius:50%;box-sizing:border-box;';
      panels.forEach(function (p) {
        on(p.canvas, 'pointermove', function (event) { var radius = Math.max(2, Math.min(200, +p.radius.value || 20)); uvCursor.hidden = !current(p) || p.textureMode.value !== 'paint' || event.altKey || event.buttons > 1 || event.pointerType === 'touch'; uvCursor.style.width = radius * 2 + 'px'; uvCursor.style.height = radius * 2 + 'px'; uvCursor.style.left = event.clientX - radius + 'px'; uvCursor.style.top = event.clientY - radius + 'px'; });
        on(p.canvas, 'pointerleave', function () { uvCursor.hidden = true; });
      });
    }
    function refresh() {
      var next = options.getToken ? options.getToken() : null;
      if (next !== token) { token = next; request++; editRevision++; busy = false; records = []; cache = {}; history = []; future = []; historyBytes = 0; runtimeGesture = null; savedToken = null; savedFingerprint = null; if (runtimeEngine) runtimeEngine.reset();
        panels.forEach(function (p) { p.baseKey = ''; p.view = { zoom: 1, x: 0, y: 0 }; p.mesh.textContent = ''; var o = el('option', p.mesh, 'Choose a mesh'); o.value = ''; fillBones(p); fillSubmeshes(p); status(p, t(token ? 'Changes are temporary until saved. Original files are preserved.' : 'Open a model first.')); }); }
      redraw();
    }
    build(false); build(true);
    initializeRuntime(); initializeShortcuts(); refresh();
    return { refresh: refresh, getStatus: quickStatus, canClearSelection: canClearSelection, clearSelection: clearSelection, beforeRender: function () { if (runtimeEngine) runtimeEngine.beforeRender(); }, beforeModelDispose: function () { if (runtimeEngine) runtimeEngine.reset(); }, handleShortcut: handleShortcut, undo: undo, redo: redo, save: function () { return save(activePanel || panels[0]); }, projectVertex: function (mesh, index) { return runtimeEngine && runtimeEngine.projectVertex(mesh, index); }, updateLanguage: function () { labels.forEach(function (pair) { pair[0].textContent = t(pair[1]); }); panels.forEach(function (p) { if (p.uvColor) p.uvColor.updateLanguage(); }); redraw(); },
      getEdits: function () { return clone(operationState()); }, getEditRevision: function () { return editRevision; }, restoreEdits: restoreEdits,
      getState: function () { var state = operationState(), summary = quickStatus(); return { token: token, busy: busy, dirty: summary.dirty, dirtyCount: summary.dirtyCount, hasUnappliedSelection: summary.hasUnappliedSelection, canSave: summary.canSave, edits: state, history: history.length, future: future.length, selectedFaces: activePanel && current(activePanel) ? Array.from(current(activePanel).marked) : [], selectedVertices: activePanel && current(activePanel) ? Array.from(current(activePanel).selected) : [], textureViews: panels.map(function (p) { return { panel: p.root.id, zoom: p.view.zoom, x: p.view.x, y: p.view.y, mode: p.textureMode.value }; }), runtime: runtimeEngine && runtimeEngine.getState(), lastSaved: lastSaved }; },
      dispose: function () { disposed = true; request++; runtimeGesture = null; if (runtimeEngine) runtimeEngine.dispose(); if (uvCursor) uvCursor.remove(); listeners.forEach(function (remove) { remove(); }); panels.forEach(function (p) { if (p.uvColor) p.uvColor.dispose(); p.root.remove(); }); style.remove(); cache = {}; } };
  }
  window.ViewerMeshTools = { create: create, normalizeInfluences: normalize, redistributeInfluence: redistributeInfluence, circleIntersectsTriangle: intersects,
    buildFaceConnectivity: buildFaceConnectivity, connectedFaces: connectedFaces, uvToView: uvToView, viewToUv: viewToUv, zoomView: zoomView };
})();
