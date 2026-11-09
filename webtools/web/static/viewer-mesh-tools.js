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
    'Show selection on model': ['모델에 선택 영역 표시', 'モデルに選択範囲を表示'], 'Show vertex targets': ['정점 선택점 표시', '頂点の選択点を表示'],
    'Delete selected faces': ['선택한 면 삭제', '選択面を削除'], 'Save mesh copy': ['메시 사본 저장', 'メッシュコピーを保存'],
    'Saved copies keep their version. Undo restores the live mesh; save again to create a restored copy.': ['저장한 사본은 해당 버전을 유지합니다. 실행 취소로 화면의 메시를 복구한 후 다시 저장하면 복구한 사본이 만들어집니다.', '保存コピーはそのバージョンを保持します。元に戻すと表示中のメッシュが復元され、再保存で復元コピーを作成できます。'],
    'Paint selects faces. Delete selected faces removes them from the model. Ctrl/Cmd+Z restores the mesh.': ['칠하면 면이 선택됩니다. 선택한 면 삭제를 누르면 모델에서도 삭제됩니다. Ctrl/Cmd+Z로 메시를 복구할 수 있습니다.', '塗ると面を選択します。「選択面を削除」でモデルから削除します。Ctrl/Cmd+Zでメッシュを復元します。'],
    'Use Alt or right-drag to orbit while editing. Shift-click adds or removes vertices.': ['편집 중 Alt 또는 오른쪽 드래그로 모델을 회전합니다. Shift+클릭으로 정점을 추가하거나 해제합니다.', '編集中はAltまたは右ドラッグで回転できます。Shift+クリックで頂点の選択を追加・解除します。'],
    'Deleted faces': ['삭제한 면', '削除面'], '3D mapping unavailable for this mesh. UV editing remains available.': ['이 메시의 정확한 3D 편집 연결을 사용할 수 없습니다. UV 편집은 사용할 수 있습니다.', 'このメッシュの正確な3D編集対応がありません。UV編集は利用できます。'],
    'Mesh editing failed.': ['메시 편집에 실패했습니다.', 'メッシュ編集に失敗しました。']
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
  function create(options) {
    options = options || {};
    var holder = document.getElementById('viewer-control-panel'); if (!holder) return null;
    var token = null, records = [], cache = {}, panels = [], disposed = false, busy = false, request = 0, lastSaved = null;
    var listeners = [], labels = [], history = [], future = [], historyBytes = 0, activePanel = null, runtimeEngine = null, savedToken = null, savedFingerprint = null, uvCursor = null;
    function t(key) { return translated(key, options.translate); }
    function interactive() { return !options.isInteractive || options.isInteractive(); }
    function el(tag, parent, key) { var e = document.createElement(tag); if (key) { e.textContent = t(key); labels.push([e, key]); } if (parent) parent.appendChild(e); return e; }
    function on(e, type, handler) { e.addEventListener(type, handler); listeners.push(function () { e.removeEventListener(type, handler); }); }
    function button(parent, key, handler) { var b = el('button', parent, key); b.type = 'button'; on(b, 'click', handler); return b; }
    function select(parent, key, values) { var label = el('label', parent), span = el('span', label, key), s = el('select', label); span.style.display = 'block'; (values || []).forEach(function (entry) { var o = el('option', s, entry[1]); o.value = entry[0]; }); return s; }
    function numeric(parent, key, initial, min, max, step) { var label = el('label', parent); el('span', label, key); var input = el('input', label); input.type = 'number'; input.value = initial; input.min = min; input.max = max; input.step = step; return input; }
    var style = el('style', document.head); style.textContent = '.viewer-mesh-tools .mesh-row{display:flex;gap:.5rem;align-items:end;flex-wrap:wrap;margin:.6rem 0}.viewer-mesh-tools label{display:flex;gap:.35rem;align-items:center;flex-wrap:wrap}.viewer-mesh-tools select{max-width:100%;min-width:0}.viewer-mesh-tools canvas{display:block;width:100%;height:auto;max-width:640px;aspect-ratio:1;touch-action:none;background:repeating-conic-gradient(#28313f 0% 25%,#323e50 0% 50%) 50%/20px 20px;border:1px solid #667085;border-radius:.35rem;cursor:crosshair}.viewer-mesh-tools input[type=number]{max-width:7rem}.viewer-mesh-tools .mesh-weights{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));max-height:8rem;overflow:auto}.viewer-mesh-tools .mesh-weights label{font-size:.82rem}.viewer-mesh-tools .mesh-value-table{white-space:pre-wrap;font-size:.85rem;overflow-wrap:anywhere}.viewer-mesh-tools .mesh-save{width:100%;margin-top:.6rem}.viewer-mesh-tools summary{min-height:44px}.viewer-mesh-tools .mesh-error{color:#f49595}.viewer-mesh-tools fieldset{min-width:0;border:1px solid #667085;border-radius:.35rem;margin:.6rem 0;padding:.5rem}';
    async function api(route, payload) {
      var response = await fetch('/api/viewer/mesh/' + route, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      var result = await response.json(); if (!response.ok || result.error) throw new Error(result.error || t('Mesh editing failed.')); return result;
    }
    function key(mesh) { return JSON.stringify(mesh); }
    function current(panel) { return cache[panel.mesh.value] || null; }
    function snapshot() { var out = {}; Object.keys(cache).forEach(function (k) { var m = cache[k]; out[k] = { deleted: Array.from(m.deleted), marked: Array.from(m.marked || []), selected: Array.from(m.selected), positions: clone(m.positions), weights: clone(m.weights) }; }); return out; }
    function remember() { var value = JSON.stringify(snapshot()); history.push(value); historyBytes += value.length; while (history.length > 24 || historyBytes > 8 * 1024 * 1024) historyBytes -= history.shift().length; future = []; }
    function restore(value) { var state = JSON.parse(value); Object.keys(cache).forEach(function (k) { var row = state[k] || { deleted: [], marked: [], selected: [], positions: {}, weights: {} }, m = cache[k]; m.deleted = new Set(row.deleted); m.marked = new Set(row.marked || []); m.selected = new Set(row.selected); m.positions = row.positions; m.weights = row.weights; m.weightRevision = (m.weightRevision || 0) + 1; }); changed(); }
    function undo() { if (busy || !interactive() || !history.length) return; future.push(JSON.stringify(snapshot())); var value = history.pop(); historyBytes -= value.length; restore(value); }
    function redo() { if (busy || !interactive() || !future.length) return; var value = JSON.stringify(snapshot()); history.push(value); historyBytes += value.length; restore(future.pop()); }
    function status(panel, text, error) { panel.status.textContent = text; panel.status.classList.toggle('mesh-error', !!error); }
    function changed() { Object.keys(cache).forEach(function (id) { var m = cache[id]; m.positionCount = Object.keys(m.positions).length; m.weightCount = Object.keys(m.weights).length; }); redraw(); if (options.onChange) options.onChange(); }
    async function inspectMeshes(panel) {
      refresh(); if (!token || busy || !interactive()) return;
      var ticket = ++request; busy = true; status(panel, t('Loading…')); redraw(); if (options.onChange) options.onChange();
      try {
        var response = await api('inspect', { token: token }); if (disposed || ticket !== request) return;
        records = response.meshes || [];
        panels.forEach(function (p) { var previous = p.mesh.value; p.mesh.textContent = ''; var empty = el('option', p.mesh, 'Choose a mesh'); empty.value = ''; records.forEach(function (r) { var o = el('option', p.mesh); o.value = key(r.mesh); o.textContent = r.name + ' · ' + r.sourceName + ' (' + r.vertices + ')'; o.disabled = !r.available; if (r.reason) o.title = r.reason; }); if (Array.from(p.mesh.options).some(function (o) { return o.value === previous; })) p.mesh.value = previous; });
        status(panel, records.length + ' ' + t('Mesh'));
      } catch (error) { if (ticket === request) status(panel, error.message, true); }
      finally { if (ticket === request) { busy = false; redraw(); if (options.onChange) options.onChange(); } }
    }
    async function chooseMesh(panel) {
      var id = panel.mesh.value; if (!id || busy || !interactive()) { redraw(); return; }
      activePanel = panel; if (cache[id]) { fillBones(panel); fillSubmeshes(panel); redraw(); return; }
      var ticket = ++request; busy = true; status(panel, t('Loading…')); redraw(); if (options.onChange) options.onChange();
      try {
        var data = await api('data', { token: token, mesh: JSON.parse(id) }); if (disposed || ticket !== request) return;
        var m = { data: data, deleted: new Set(), marked: new Set(), selected: new Set(), positions: {}, weights: {}, adjacency: [], image: null, weightRevision: 0, imageRevision: 0, grid: null, positionCount: 0, weightCount: 0, images: [] };
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
        cache[id] = m; fillBones(panel); fillSubmeshes(panel); status(panel, data.uv ? t('Changes are temporary until saved. Original files are preserved.') : t('No UV coordinates are available. Select vertices by index.'));
      } catch (error) { if (ticket === request) status(panel, error.message, true); }
      finally { if (ticket === request) { busy = false; redraw(); if (options.onChange) options.onChange(); } }
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
      var m = current(panel), canvas = panel.canvas, ctx = canvas.getContext('2d'), size = canvas.width;
      ctx.clearRect(0, 0, size, size); if (!m || !m.data.uv) return;
      function point(i) { var uv = m.data.uv[i]; return [uv[0] * size, (1 - uv[1]) * size]; }
      var bone = panel.bone ? +panel.bone.value : 0, submesh = activeSubmesh(panel, m), image = submesh ? (submesh.textureIndex !== null ? m.images[submesh.textureIndex] : null) : m.image;
      function path(context, face) { context.beginPath(); face.forEach(function (v, i) { var p = point(v); if (i) context.lineTo(p[0], p[1]); else context.moveTo(p[0], p[1]); }); context.closePath(); }
      var baseKey = key(m.data.mesh) + '/' + panel.lines.checked + '/' + (panel.modify ? bone + '/' + m.weightRevision : '') + '/' + m.imageRevision + '/' + panel.submesh.value;
      if (baseKey !== panel.baseKey) {
        if (!panel.base) { panel.base = document.createElement('canvas'); panel.base.width = size; panel.base.height = size; }
        var base = panel.base.getContext('2d'); base.clearRect(0, 0, size, size);
        if (image && image.complete && image.naturalWidth) base.drawImage(image, 0, 0, size, size);
        if (panel.lines.checked || panel.modify) m.data.triangles.forEach(function (face, index) {
          if (!visibleFace(panel, m, index)) return; path(base, face);
          if (panel.modify && m.data.skin.length) { var value = face.reduce(function (total, v) { var influences = m.weights[v] || m.data.skin[v]; return total + influences.reduce(function (sum, pair) { return sum + (pair[0] === bone ? pair[1] : 0); }, 0); }, 0) / 3; base.fillStyle = 'hsla(' + (240 - value * 240) + ',100%,50%,.35)'; base.fill(); }
          if (panel.lines.checked) { base.strokeStyle = 'rgba(235,245,255,.55)'; base.lineWidth = .7; base.stroke(); }
        }); panel.baseKey = baseKey;
      }
      ctx.drawImage(panel.base, 0, 0);
      m.deleted.forEach(function (index) { if (!visibleFace(panel, m, index)) return; path(ctx, m.data.triangles[index]); ctx.fillStyle = 'rgba(0,0,0,.8)'; ctx.fill(); });
      m.marked.forEach(function (index) { if (!visibleFace(panel, m, index) || m.deleted.has(index)) return; path(ctx, m.data.triangles[index]); ctx.fillStyle = 'rgba(255,50,80,.65)'; ctx.fill(); });
      if (panel.modify) m.selected.forEach(function (v) { var p = point(v); ctx.beginPath(); ctx.arc(p[0], p[1], 3, 0, Math.PI * 2); ctx.fillStyle = '#ffe05c'; ctx.fill(); });
    }
    function operationState() {
      var result = [];
      Object.keys(cache).forEach(function (id) { var m = cache[id], positions = Object.keys(m.positions).map(function (i) { return { vertex: +i, position: m.positions[i] }; }), weights = Object.keys(m.weights).map(function (i) { return { vertex: +i, influences: m.weights[i] }; }); if (m.deleted.size || positions.length || weights.length) result.push({ mesh: m.data.mesh, deleteFaces: Array.from(m.deleted).sort(function (a, b) { return a - b; }), positions: positions, weights: weights }); });
      return { version: 1, meshes: result };
    }
    function quickStatus() { var count = 0; Object.keys(cache).forEach(function (id) { var m = cache[id]; if (m.deleted.size || m.marked.size || m.positionCount || m.weightCount) count++; }); return { busy: busy, dirty: count > 0, dirtyCount: count, canSave: canSaveCopy(), hasHistory: history.length > 0, redoAvailable: future.length > 0, active: !!activePanel };  }
    function redraw() {
      var changes = quickStatus().dirtyCount;
      panels.forEach(function (p) {
        var m = current(p); p.load.disabled = !token || busy || !interactive(); p.mesh.disabled = !token || busy || !interactive(); p.save.disabled = !token || busy || !canSaveCopy() || !interactive();
        p.undo.disabled = busy || !history.length; p.redo.disabled = busy || !future.length;
        if (p.deleteFaces) p.deleteFaces.disabled = busy || !m || !m.marked.size || !interactive();
        p.canvas.style.opacity = busy ? '.5' : '1';
        p.count.textContent = p.modify ? t('Selected vertices') + ': ' + (m ? m.selected.size : 0) + ' · ' + t('Position and weight edits') + ': ' + (m ? Object.keys(m.positions).length + Object.keys(m.weights).length : 0) : t('Selected faces') + ': ' + (m ? m.marked.size : 0) + ' · ' + t('Deleted faces') + ': ' + (m ? m.deleted.size : 0);
        p.actions.forEach(function (b) { b.disabled = busy || !m || !interactive(); });
        if (p.vertex) {
          p.vertex.max = m ? m.data.positions.length - 1 : 0;
          p.weightApply.disabled = busy || !m || !m.data.skinWritable || !m.selected.size;
          p.positionSet.disabled = busy || !m || !m.data.positionWritable || m.selected.size !== 1;
          p.translate.disabled = busy || !m || !m.data.positionWritable || !m.selected.size;
          var selected = m && Array.from(m.selected), first = selected && selected.length ? selected[0] : null;
          p.values.textContent = first === null ? '' : '#' + first + ' · XYZ: ' + (m.positions[first] || m.data.positions[first]).map(function (v) { return (+v.toFixed(6)); }).join(' / ') + '\n' + (m.weights[first] || m.data.skin[first] || []).map(function (v) { return (m.data.bones[v[0]] || v[0]) + ': ' + (v[1] * 100).toFixed(2) + '%'; }).join(' · ');
        }
        draw(p);
      });
      syncRuntime();
    }
    function selection(panel, mode) { var m = current(panel); if (!m || busy) return; remember(); var set = panel.modify ? m.selected : m.marked, count = panel.modify ? m.data.positions.length : m.data.triangles.length, visible = panel.modify ? visibleVertices(panel, m) : null; for (var i = 0; i < count; i++) { if (visible ? !visible.has(i) : !visibleFace(panel, m, i)) continue; if (mode === 'clear') set.delete(i); else if (mode === 'all' || !set.has(i)) set.add(i); else set.delete(i); } changed(); }
    function stamp(panel, x, y) {
      var m = current(panel); if (!m || !m.data.uv) return;
      var radius = Math.max(2, Math.min(200, +panel.radius.value || 20)) / Math.max(1, panel.canvas.getBoundingClientRect().width), add = panel.mode.value === 'paint', uv = m.data.uv;
      if (panel.modify) { var visible = visibleVertices(panel, m); uv.forEach(function (p, i) { if (visible.has(i) && Math.hypot(p[0] - x, p[1] - y) <= radius) { if (add) m.selected.add(i); else m.selected.delete(i); } }); }
      else {
        var candidates = null;
        if (m.grid) { candidates = new Set(); for (var gx = Math.max(0, Math.floor((x - radius) * 16)); gx <= Math.min(15, Math.floor((x + radius) * 16)); gx++) for (var gy = Math.max(0, Math.floor((y - radius) * 16)); gy <= Math.min(15, Math.floor((y + radius) * 16)); gy++) (m.grid[gx + gy * 16] || []).forEach(function (i) { candidates.add(i); }); }
        function paint(i) { if (!visibleFace(panel, m, i)) return; var face = m.data.triangles[i]; if (intersects(x, y, radius, uv[face[0]], uv[face[1]], uv[face[2]])) { if (!m.deleted.has(i)) { if (add) m.marked.add(i); else m.marked.delete(i); } } }
        if (candidates) candidates.forEach(paint); else m.data.triangles.forEach(function (_, i) { paint(i); });
      }
    }
    function attachCanvas(panel) {
      var down = false, previous = null;
      function position(event) { var r = panel.canvas.getBoundingClientRect(); return [(event.clientX - r.left) / r.width, 1 - (event.clientY - r.top) / r.height]; }
      on(panel.canvas, 'pointerdown', function (event) { if (busy || !interactive() || !current(panel) || !current(panel).data.uv || event.button > 0) return; event.preventDefault(); activePanel = panel; panel.canvas.focus({ preventScroll: true }); remember(); down = true; previous = position(event); panel.canvas.setPointerCapture(event.pointerId); stamp(panel, previous[0], previous[1]); redraw(); });
      on(panel.canvas, 'pointermove', function (event) { if (!down) return; event.preventDefault(); var next = position(event), distance = Math.hypot(next[0] - previous[0], next[1] - previous[1]), step = Math.max(.002, +panel.radius.value / 2000), steps = Math.min(100, Math.ceil(distance / step)); for (var i = 1; i <= steps; i++) stamp(panel, previous[0] + (next[0] - previous[0]) * i / steps, previous[1] + (next[1] - previous[1]) * i / steps); previous = next; redraw(); });
      function end() { if (down) { down = false; previous = null; changed(); } }
      on(panel.canvas, 'pointerup', end); on(panel.canvas, 'pointercancel', end); on(panel.canvas, 'lostpointercapture', end);
    }
    function changePosition(panel, absolute) {
      var m = current(panel); if (!m || !m.selected.size) return status(panel, t('Choose vertices first.'), true);
      if (absolute && m.selected.size !== 1) return status(panel, t('Choose one vertex for an absolute position.'), true);
      var fields = absolute ? panel.xyz : panel.delta, value = fields.map(function (i) { return +i.value; });
      if (fields.some(function (i) { return !i.checkValidity() || !i.value.trim(); }) || value.some(function (v) { return !Number.isFinite(v); })) return;
      remember(); m.selected.forEach(function (v) { var old = m.positions[v] || m.data.positions[v]; m.positions[v] = absolute ? value.slice() : old.map(function (n, axis) { return n + value[axis]; }); }); changed();
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
      remember(); Object.keys(updates).forEach(function (v) { if (updates[v].length) m.weights[v] = updates[v]; }); m.weightRevision++; changed();
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
    function build(modify) {
      var box = el('details', holder); box.id = modify ? 'viewer-mesh-modify' : 'viewer-mesh-deleter'; box.className = 'viewer-adjustments viewer-mesh-tools';
      el('summary', box, modify ? 'Mesh modify' : 'Mesh deleter');
      el('p', box, modify ? 'Paint to select vertices, then edit positions or normalized weights.' : 'Paint selects faces. Delete selected faces removes them from the model. Ctrl/Cmd+Z restores the mesh.').className = 'viewer-render-note';
      var p = { root: box, modify: modify, actions: [] }, row = el('div', box); row.className = 'mesh-row';
      p.load = button(row, 'Load meshes', function () { inspectMeshes(p); }); p.mesh = select(row, 'Mesh', [['', 'Choose a mesh']]); on(p.mesh, 'change', function () { chooseMesh(p); });
      p.submesh = select(box, 'Material / submesh'); on(p.submesh, 'change', function () { activePanel = p; var m = current(p); if (m && p.modify) m.selected.clear(); p.baseKey = ''; changed(); });
      row = el('div', box); row.className = 'mesh-row'; p.mode = select(row, 'Paint', [['paint', 'Paint'], ['erase', 'Erase']]); p.radius = numeric(row, 'Brush radius', 30, 2, 200, 1);
      row = el('div', box); row.className = 'mesh-row';
      p.sceneMode = select(row, '3D editing', modify ? [['orbit', 'Orbit model'], ['paint', 'Paint on model'], ['pick', 'Pick vertices'], ['drag', 'Move vertices in 3D']] : [['orbit', 'Orbit model'], ['paint', 'Paint on model']]);
      on(p.sceneMode, 'change', function () { activePanel = p; changed(); });
      function check3d(title, initial) { var label = el('label', row), input = el('input', label); input.type = 'checkbox'; input.checked = initial; el('span', label, title); on(input, 'change', function () { activePanel = p; changed(); }); return input; }
      p.show3d = check3d('Show selection on model', true); p.showVertices = check3d('Show vertex targets', modify); p.liveStatus = el('p', box); p.liveStatus.className = 'viewer-render-note';
      el('p', box, 'Use Alt or right-drag to orbit while editing. Shift-click adds or removes vertices.').className = 'viewer-render-note';
      on(box, 'focusin', function () { activePanel = p; syncRuntime(); });

      var linesLabel = el('label', row); p.lines = el('input', linesLabel); p.lines.type = 'checkbox'; p.lines.checked = true; el('span', linesLabel, 'Show UV lines'); on(p.lines, 'change', redraw);
      p.canvas = el('canvas', box); p.canvas.width = 640; p.canvas.height = 640; p.canvas.setAttribute('aria-label', t(modify ? 'Selected vertices' : 'Selected faces')); p.canvas.tabIndex = 0;
      var imageLabel = el('label', box); el('span', imageLabel, 'Texture image'); var imageInput = el('input', imageLabel); imageInput.type = 'file'; imageInput.accept = 'image/png,image/jpeg,image/webp';
      on(imageInput, 'change', function () { var m = current(p), file = imageInput.files[0]; if (!m || !file || file.size > 8 * 1024 * 1024) return; var url = URL.createObjectURL(file), img = new Image(); img.onload = function () { URL.revokeObjectURL(url); if (!disposed) { var entry = activeSubmesh(p, m), index = entry && entry.textureIndex !== null ? entry.textureIndex : m.images.length; m.images[index] = img; if (entry) entry.textureIndex = index; else m.image = img; m.imageRevision++; redraw(); } }; img.onerror = function () { URL.revokeObjectURL(url); }; img.src = url; });
      row = el('div', box); row.className = 'mesh-row'; p.undo = button(row, 'Undo', undo); p.redo = button(row, 'Redo', redo);
      ['clear', 'invert', 'all'].forEach(function (mode) { p.actions.push(button(row, { clear: 'Clear selection', invert: 'Invert selection', all: 'Select all' }[mode], function () { selection(p, mode); })); });
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
      p.actions.push(button(box, 'Restore mesh changes', function () { var m = current(p); if (!m) return; remember(); m.deleted.clear(); m.marked.clear(); m.selected.clear(); m.positions = {}; m.weights = {}; m.weightRevision++; changed(); }));
      p.save = button(box, 'Save mesh copy', function () { save(p); }); p.save.className = 'mesh-save'; el('p', box, 'Saved copies keep their version. Undo restores the live mesh; save again to create a restored copy.').className = 'viewer-render-note'; p.result = el('ul', box);
      p.status = el('p', box, 'Open a model first.'); p.status.className = 'viewer-render-note'; p.status.setAttribute('role', 'status'); p.status.setAttribute('aria-live', 'polite');
      var prefix = box.id;
      ['load', 'mesh', 'submesh', 'sceneMode', 'show3d', 'showVertices', 'deleteFaces', 'canvas', 'save', 'undo', 'redo', 'count', 'status', 'vertex', 'weight', 'weightMode', 'bone', 'positionSet', 'translate', 'weightApply'].forEach(function (name) {
        if (p[name]) p[name].id = prefix + '-' + ({ mesh: 'select', sceneMode: 'scene-mode', show3d: 'show-selection', showVertices: 'show-vertices', deleteFaces: 'delete', weight: 'weight-value', weightMode: 'weight-mode', bone: 'weight-bone', positionSet: 'position-set', weightApply: 'weight-apply' }[name] || name);
      });
      if (p.xyz) p.xyz.forEach(function (field, axis) { field.dataset.meshPositionAxis = 'XYZ'[axis]; field.step = 'any'; });
      if (p.delta) p.delta.forEach(function (field, axis) { field.dataset.meshDeltaAxis = 'XYZ'[axis]; field.step = 'any'; });
      if (p.weight) p.weight.step = 'any';
      panels.push(p); attachCanvas(p);
    }
    function persistentChangeCount() { var count = 0; Object.keys(cache).forEach(function (id) { var m = cache[id]; if (m.deleted.size || m.positionCount || m.weightCount) count++; }); return count; }
    function canSaveCopy() { return persistentChangeCount() > 0 || savedToken === token && !!savedFingerprint; }
    function deleteMarked(panel) { var m = current(panel); if (!m || !m.marked.size || busy) return; activePanel = panel; remember(); m.marked.forEach(function (face) { m.deleted.add(face); }); m.marked.clear(); changed(); }
    function runtimeContext() {
      var p = activePanel, m = p && current(p); if (!p || !m || p.root.hidden) return null;
      return { mesh: m, modify: p.modify, mode: p.sceneMode.value, submesh: +p.submesh.value || 0,
        radius: +p.radius.value || 20, erase: p.mode.value === 'erase', showSelection: p.show3d.checked,
        showVertices: p.modify && p.showVertices.checked, interactive: interactive() && !busy };
    }
    function syncRuntime() {
      if (!runtimeEngine) return;
      runtimeEngine.sync(Object.keys(cache).map(function (id) { return cache[id]; }));
      var state = runtimeEngine.getState(); panels.forEach(function (p) { var m = current(p), mapped = m && state.bindings.some(function (binding) { return key(binding.mesh) === key(m.data.mesh); });
        p.sceneMode.disabled = !mapped || busy || !interactive();
        p.liveStatus.textContent = m && !mapped ? t('3D mapping unavailable for this mesh. UV editing remains available.') : '';
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
        onBegin: remember,
        onPaint: function (indices, erase, modify) { var m = activePanel && current(activePanel); if (!m) return; var set = modify ? m.selected : m.marked; indices.forEach(function (index) { if (erase) set.delete(index); else if (modify || !m.deleted.has(index)) set.add(index); }); redraw(); },
        onSelect: chooseVertex,
        onDrag: function (values) { var m = activePanel && current(activePanel); if (!m) return; Object.keys(values).forEach(function (vertex) { m.positions[vertex] = values[vertex]; }); changed(); },
        onEnd: function () { changed(); }
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
        on(p.canvas, 'pointermove', function (event) { var radius = Math.max(2, Math.min(200, +p.radius.value || 20)); uvCursor.hidden = !current(p); uvCursor.style.width = radius * 2 + 'px'; uvCursor.style.height = radius * 2 + 'px'; uvCursor.style.left = event.clientX - radius + 'px'; uvCursor.style.top = event.clientY - radius + 'px'; });
        on(p.canvas, 'pointerleave', function () { uvCursor.hidden = true; });
      });
    }
    function refresh() {
      var next = options.getToken ? options.getToken() : null;
      if (next !== token) { token = next; request++; busy = false; records = []; cache = {}; history = []; future = []; historyBytes = 0; savedToken = null; savedFingerprint = null; if (runtimeEngine) runtimeEngine.reset();
        panels.forEach(function (p) { p.baseKey = ''; p.mesh.textContent = ''; var o = el('option', p.mesh, 'Choose a mesh'); o.value = ''; fillBones(p); fillSubmeshes(p); status(p, t(token ? 'Changes are temporary until saved. Original files are preserved.' : 'Open a model first.')); }); }
      redraw();
    }
    build(false); build(true);
    initializeRuntime(); initializeShortcuts(); refresh();
    return { refresh: refresh, getStatus: quickStatus, beforeRender: function () { if (runtimeEngine) runtimeEngine.beforeRender(); }, beforeModelDispose: function () { if (runtimeEngine) runtimeEngine.reset(); }, handleShortcut: handleShortcut, undo: undo, redo: redo, save: function () { return save(activePanel || panels[0]); }, projectVertex: function (mesh, index) { return runtimeEngine && runtimeEngine.projectVertex(mesh, index); }, updateLanguage: function () { labels.forEach(function (pair) { pair[0].textContent = t(pair[1]); }); redraw(); },
      getState: function () { var state = operationState(), summary = quickStatus(); return { token: token, busy: busy, dirty: summary.dirty, dirtyCount: summary.dirtyCount, canSave: summary.canSave, edits: state, history: history.length, future: future.length, selectedFaces: activePanel && current(activePanel) ? Array.from(current(activePanel).marked) : [], selectedVertices: activePanel && current(activePanel) ? Array.from(current(activePanel).selected) : [], runtime: runtimeEngine && runtimeEngine.getState(), lastSaved: lastSaved }; },
      dispose: function () { disposed = true; request++; if (runtimeEngine) runtimeEngine.dispose(); if (uvCursor) uvCursor.remove(); listeners.forEach(function (remove) { remove(); }); panels.forEach(function (p) { p.root.remove(); }); style.remove(); cache = {}; } };
  }
  window.ViewerMeshTools = { create: create, normalizeInfluences: normalize, redistributeInfluence: redistributeInfluence, circleIntersectsTriangle: intersects };
})();
