/* Source-bound texture colouring and painting. Canvas is only a display: exact
 * RGBA comes from TexturePNG and persistent PNGs use its lossless encoder.
 * getEdits() returns the body recipe's textures ARRAY. Loading/colour previews
 * and PNG encoding are explicit pending work; the host must block export then.
 */
(function (global) {
  "use strict";
  function key(identity) {
    return identity && Number.isInteger(identity.source) && Number.isInteger(identity.file) && typeof identity.id === "string"
      ? identity.source + ":" + identity.file + ":" + identity.id : "";
  }
  function same(left, right) { return !!key(left) && key(left) === key(right); }
  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function copyImage(value) { return { width: value.width, height: value.height, data: new Uint8ClampedArray(value.data) }; }
  function equalPixels(left, right) {
    if (!left || !right || left.width !== right.width || left.height !== right.height || left.data.length !== right.data.length) return false;
    for (var index = 0; index < left.data.length; index++) if (left.data[index] !== right.data[index]) return false;
    return true;
  }
  function hex(rgba) { return "#" + [0, 1, 2].map(function (i) { return clamp(Math.round(rgba[i]), 0, 255).toString(16).padStart(2, "0"); }).join(""); }
  function wrapped(value, wrap) {
    if (wrap === 1000 || wrap === "repeat") return value - Math.floor(value);
    if (wrap === 1002 || wrap === "mirror") { var tile = Math.floor(value), unit = value - tile; return Math.abs(tile % 2) ? 1 - unit : unit; }
    return clamp(value, 0, 1);
  }
  // Matrix3 elements follow THREE's column-major layout. GLB UVs are already
  // V-flipped; only Texture.flipY is applied, exactly as Texture.transformUv.
  function rawUv(texture, uv) {
    if (texture.matrixAutoUpdate && texture.updateMatrix) texture.updateMatrix();
    var m = texture.matrix && texture.matrix.elements;
    return m ? [m[0] * uv[0] + m[3] * uv[1] + m[6], m[1] * uv[0] + m[4] * uv[1] + m[7]] : uv.slice();
  }
  function sampledUv(texture, uv) {
    var value = rawUv(texture, uv), u = wrapped(value[0], texture.wrapS), v = wrapped(value[1], texture.wrapT);
    return [u, texture.flipY ? 1 - v : v];
  }
  function tiles(low, high, wrap) {
    if (wrap !== 1000 && wrap !== 1002 && wrap !== "repeat" && wrap !== "mirror") return [0];
    var start = Math.floor(low), end = Math.floor(high), result = [];
    if (end - start > 32) throw new Error("This UV triangle repeats too many times to select safely.");
    for (var i = start; i <= end; i++) result.push(i);
    return result;
  }
  function tilePoint(value, tile, wrap) {
    if (wrap === 1000 || wrap === "repeat") return value - tile;
    if (wrap === 1002 || wrap === "mirror") return Math.abs(tile % 2) ? 1 - (value - tile) : value - tile;
    return clamp(value, 0, 1);
  }
  function triangleCopies(texture, vertices) {
    var raw = vertices.map(function (uv) { return rawUv(texture, uv); }), xs = raw.map(function (v) { return v[0]; }), ys = raw.map(function (v) { return v[1]; }), copies = [];
    var tx = tiles(Math.min.apply(null, xs), Math.max.apply(null, xs), texture.wrapS), ty = tiles(Math.min.apply(null, ys), Math.max.apply(null, ys), texture.wrapT);
    if (tx.length * ty.length > 64) throw new Error("This UV triangle repeats too many times to select safely.");
    tx.forEach(function (x) { ty.forEach(function (y) { copies.push(raw.map(function (uv) {
      var v = tilePoint(uv[1], y, texture.wrapT); return [tilePoint(uv[0], x, texture.wrapS), texture.flipY ? 1 - v : v];
    })); }); });
    return copies;
  }
  function rasterTriangle(mask, width, height, vertices) {
    var p = vertices.map(function (v) { return [v[0] * width, v[1] * height]; }), a = p[0], b = p[1], c = p[2];
    var area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    if (!Number.isFinite(area)) return;
    if (Math.abs(area) < 1e-10) {
      // Clamped UVs can sample a single border texel or line.
      for (var edge = 0; edge < 3; edge++) {
        var from = p[edge], to = p[(edge + 1) % 3], steps = Math.min(width + height, Math.ceil(Math.max(Math.abs(from[0] - to[0]), Math.abs(from[1] - to[1]))));
        for (var n = 0; n <= steps; n++) { var t = steps ? n / steps : 0, x = clamp(Math.floor(from[0] + (to[0] - from[0]) * t), 0, width - 1), y = clamp(Math.floor(from[1] + (to[1] - from[1]) * t), 0, height - 1); mask[y * width + x] = 255; }
      }
      return;
    }
    var minY = Math.max(0, Math.floor(Math.min(a[1], b[1], c[1]))), maxY = Math.min(height - 1, Math.ceil(Math.max(a[1], b[1], c[1])) - 1);
    // Include every texel whose area overlaps the triangle. Testing only its
    // centre leaves a thin unselected border and loses subpixel UV details.
    // A triangle clipped to one pixel-high strip is convex: its X projection
    // is one span. Fill that span without adding a padding ring or examining
    // every pixel separately. Cells that only touch an edge stay unselected.
    for (var y = minY; y <= maxY; y++) {
      var low = Infinity, high = -Infinity, bottom = y + 1;
      for (var edge = 0; edge < 3; edge++) {
        var from = p[edge], to = p[(edge + 1) % 3];
        if (from[1] >= y && from[1] <= bottom) { low = Math.min(low, from[0]); high = Math.max(high, from[0]); }
        if (from[1] < y && to[1] > y || to[1] < y && from[1] > y) {
          var atTop = from[0] + (y - from[1]) * (to[0] - from[0]) / (to[1] - from[1]);
          low = Math.min(low, atTop); high = Math.max(high, atTop);
        }
        if (from[1] < bottom && to[1] > bottom || to[1] < bottom && from[1] > bottom) {
          var atBottom = from[0] + (bottom - from[1]) * (to[0] - from[0]) / (to[1] - from[1]);
          low = Math.min(low, atBottom); high = Math.max(high, atBottom);
        }
      }
      if (!Number.isFinite(low) || !Number.isFinite(high)) continue;
      var tolerance = 1e-10 + Number.EPSILON * 16 * Math.max(width, height, Math.abs(low), Math.abs(high));
      var left = Math.max(0, Math.floor(low + tolerance)), right = Math.min(width, Math.ceil(high - tolerance));
      if (right > left) mask.fill(255, y * width + left, y * width + right);
    }
  }
  function rasterFaces(width, height, triangles, uvs, faces, texture) {
    var mask = new Uint8Array(width * height);
    faces.forEach(function (face) {
      var indices = triangles[face]; if (!indices) return;
      var points = indices.map(function (index) { return uvs[index]; });
      if (points.some(function (p) { return !p || !Number.isFinite(p[0]) || !Number.isFinite(p[1]); })) return;
      triangleCopies(texture, points).forEach(function (copy) { rasterTriangle(mask, width, height, copy); });
    });
    return mask;
  }
  // Brush masks use texture-pixel coordinates, independent of model distance.
  // The source mask remains immutable for intersect strokes and cancellation.
  function stampMaskCircle(mask, source, width, height, x, y, radius, mode) {
    radius = Math.max(.5, radius); var left = clamp(Math.floor(x - radius), 0, width - 1), right = clamp(Math.ceil(x + radius), 0, width - 1);
    var top = clamp(Math.floor(y - radius), 0, height - 1), bottom = clamp(Math.ceil(y + radius), 0, height - 1), changed = false, covered = false;
    for (var py = top; py <= bottom; py++) for (var px = left; px <= right; px++) {
      if ((px + .5 - x) * (px + .5 - x) + (py + .5 - y) * (py + .5 - y) > radius * radius) continue;
      covered = true; var index = py * width + px, value = mode === "subtract" ? 0 : mode === "intersect" ? source ? source[index] : 255 : 255;
      if (mask[index] !== value) { mask[index] = value; changed = true; }
    }
    // A one-pixel brush on a UV grid corner must still select its sampled texel.
    if (!covered) { var nearest = clamp(Math.floor(y), 0, height - 1) * width + clamp(Math.floor(x), 0, width - 1), next = mode === "subtract" ? 0 : mode === "intersect" ? source ? source[nearest] : 255 : 255; if (mask[nearest] !== next) { mask[nearest] = next; changed = true; } }
    return changed ? { left: left, top: top, right: right, bottom: bottom } : null;
  }
  function brushMask(source, size, mode) {
    if (mode === "add" || mode === "subtract") { var mask = source ? new Uint8Array(source) : new Uint8Array(size); if (!source && mode === "subtract") mask.fill(255); return mask; }
    return new Uint8Array(size);
  }
  var WORDS = {
    "Layers": ["레이어", "レイヤー"], "Layer": ["레이어", "レイヤー"], "Layer name": ["레이어 이름", "レイヤー名"], "Layer opacity": ["레이어 불투명도", "レイヤーの不透明度"],
    "Add layer": ["레이어 추가", "レイヤーを追加"], "Duplicate layer": ["레이어 복제", "レイヤーを複製"], "Delete layer": ["레이어 삭제", "レイヤーを削除"], "Layer up": ["위로", "上へ"], "Layer down": ["아래로", "下へ"], "Merge down": ["아래 레이어와 합치기", "下のレイヤーと結合"],
    "Show layer": ["레이어 표시", "レイヤーを表示"], "Copy": ["복사", "コピー"], "Cut": ["잘라내기", "切り取り"], "Paste": ["붙여넣기", "貼り付け"], "Move selected pixels": ["선택 영역 이동", "選択範囲を移動"], "Draw rectangle": ["사각형 그리기", "四角形を描く"],
    "Apply moved pixels": ["이동 적용", "移動を適用"], "Cancel move": ["이동 취소", "移動を取り消す"], "Apply or cancel moved pixels first.": ["이동 중인 영역을 먼저 적용하거나 취소하세요.", "移動中の範囲を先に適用または取り消してください。"],
    "Rectangle selection clips fill and paint. Move drags selected pixels.": ["사각형으로 선택한 안쪽만 채우거나 그릴 수 있습니다. 이동 도구로 선택한 픽셀을 끌어 옮기세요.", "矩形選択の内側だけ塗りつぶしたり描画できます。移動ツールで選択したピクセルをドラッグします。"],
    "Ctrl/Cmd+C copy · X cut · V paste · Enter apply · Esc cancel": ["Ctrl/Cmd+C 복사 · X 잘라내기 · V 붙여넣기 · Enter 적용 · Esc 취소", "Ctrl/Cmd+C コピー・X 切り取り・V 貼り付け・Enter 適用・Esc 取り消し"],
    "PNG and game saves flatten visible layers. Save a layer project to keep layers editable.": ["PNG와 게임 저장은 보이는 레이어를 합칩니다. 레이어를 계속 편집하려면 레이어 프로젝트로 저장하세요.", "PNGやゲームへの保存では表示中のレイヤーを結合します。再編集するにはレイヤープロジェクトで保存してください。"],
    "Open layer project": ["레이어 프로젝트 열기", "レイヤープロジェクトを開く"], "Save layer project": ["레이어 프로젝트 저장", "レイヤープロジェクトを保存"], "Opening layer project…": ["레이어 프로젝트를 여는 중…", "レイヤープロジェクトを読み込み中…"], "Saving layer project…": ["레이어 프로젝트를 저장하는 중…", "レイヤープロジェクトを保存中…"], "Layer project saved on this device.": ["이 기기에 레이어 프로젝트를 저장했습니다.", "この端末にレイヤープロジェクトを保存しました。"], "Download layer project": ["레이어 프로젝트 다운로드", "レイヤープロジェクトをダウンロード"],
    "Opening a project replaces this texture's layers and can be undone.": ["프로젝트를 열면 이 텍스쳐의 레이어를 교체합니다. 되돌리기로 복구할 수 있습니다.", "プロジェクトを開くとこのテクスチャのレイヤーを置き換えます。「元に戻す」で復元できます。"],
    "Layer memory is full. Save layer projects before opening another model.": ["레이어 메모리가 가득 찼습니다. 레이어 프로젝트를 저장한 뒤 다른 모델을 열어 주세요.", "レイヤーのメモリがいっぱいです。レイヤープロジェクトを保存してから別のモデルを開いてください。"],
    "Invalid layer project.": ["올바른 레이어 프로젝트가 아닙니다.", "正しいレイヤープロジェクトではありません。"], "Apply or cancel the color preview first.": ["색상 미리보기를 먼저 적용하거나 취소하세요.", "色のプレビューを先に適用または取り消してください。"],
    "This saved copy is read-only. Reopen the original to edit.": ["저장한 사본은 읽기 전용입니다. 편집하려면 원본을 다시 여세요.", "保存したコピーは読み取り専用です。編集するには元のモデルを開き直してください。"], "Texture and color tools": ["텍스쳐·컬러 편집", "テクスチャ・色編集"], "Costume color": ["의상 컬러", "衣装カラー"], "Skin tone": ["스킨톤", "肌色"], "Paint": ["그림판", "ペイント"],
    "Texture": ["텍스쳐", "テクスチャ"], "Choose a texture": ["텍스쳐 선택", "テクスチャを選択"], "Open a model to edit textures.": ["텍스쳐를 편집할 모델을 열어 주세요.", "テクスチャを編集するモデルを開いてください。"],
    "Loading textures…": ["텍스쳐 목록을 불러오는 중…", "テクスチャ一覧を読み込み中…"], "Loading texture…": ["텍스쳐를 불러오는 중…", "テクスチャを読み込み中…"],
    "3D selection brush": ["3D 선택 브러시", "3D選択ブラシ"], "Model selection": ["모델에서 선택", "モデルで選択"], "Orbit": ["회전·이동", "回転・移動"], "Face": ["면 선택", "面を選択"], "Connected faces": ["연결된 면", "つながった面"],
    "Skin sample": ["피부 표본", "肌のサンプル"], "Exclude sample": ["제외 표본", "除外サンプル"], "Selection tool": ["영역 선택", "範囲選択"],
    "Selection brush": ["선택 브러시", "選択ブラシ"], "Rectangle selection": ["사각형 선택", "矩形選択"], "Lasso selection": ["올가미 선택", "投げ縄選択"], "Magic wand": ["마술봉", "自動選択"],
    "Replace": ["새로 선택", "置換"], "Add": ["추가", "追加"], "Subtract": ["제외", "除外"], "Intersect": ["교집합", "共通範囲"],
    "Select all": ["모두 선택", "すべて選択"], "Select none": ["선택 없음", "選択なし"], "Clear selection": ["선택 제한 해제", "選択制限を解除"], "Invert selection": ["선택 반전", "選択反転"],
    "Undo": ["되돌리기", "元に戻す"], "Redo": ["다시 실행", "やり直す"], "Fit": ["화면에 맞춤", "全体を表示"], "Zoom": ["확대", "ズーム"], "Show UV": ["UV 표시", "UV表示"], "Show selection": ["선택 영역 표시", "選択範囲を表示"],
    "Selection kept; tint hidden.": ["선택 유지 · 색상 확인 중", "選択保持・色を確認中"],
    "Color adjustments hide selection tint without clearing the selection.": ["색을 조절하면 선택 영역을 유지한 채 표시 색만 숨깁니다.", "色の調整時は選択範囲を保持したまま表示色だけを隠します。"],
    "Complete the number before applying color.": ["숫자 입력을 마친 뒤 색상을 적용하세요.", "数値の入力を完了してから色を適用してください。"],
    "Relative OKLCH": ["OKLCH 상대 조절", "OKLCH相対調整"], "Target color, keep shading": ["목표색 · 명암 보존", "指定色・陰影を保持"], "Mode": ["방식", "方式"], "Target color": ["목표색", "指定色"],
    "Lightness": ["명도", "明度"], "Chroma": ["채도", "彩度"], "Hue": ["색상각", "色相"], "Strength": ["강도", "強度"], "Apply color": ["색상 적용", "色を適用"],
    "Cancel preview": ["미리보기 취소", "プレビューを取り消す"], "Compare original": ["원본 비교", "元画像を比較"], "Restore original texture": ["편집 전 텍스쳐로 되돌리기", "編集前のテクスチャに戻す"],
    "Restore the image loaded before editing? This replaces all its layers and can be undone.": ["처음 불러온 편집 전 이미지로 되돌릴까요? 이 텍스쳐의 모든 레이어를 교체하며, 되돌리기로 복구할 수 있습니다.", "読み込み時の編集前画像に戻しますか？ このテクスチャの全レイヤーを置き換えます。「元に戻す」で復元できます。"],
    "Restore texture": ["편집 전으로 되돌리기", "編集前に戻す"], "Keep editing": ["계속 편집", "編集を続ける"],
    "The texture changed. Review it before restoring.": ["텍스쳐가 변경되었습니다. 현재 내용을 확인한 뒤 다시 되돌리기를 선택하세요.", "テクスチャが変更されました。現在の内容を確認してから、もう一度戻す操作を選択してください。"],
    "Original texture restored. Undo restores your edited layers.": ["편집 전 텍스쳐로 되돌렸습니다. 되돌리기를 누르면 편집한 레이어를 복구합니다.", "編集前のテクスチャに戻しました。「元に戻す」で編集したレイヤーを復元できます。"],
    "Source tone": ["원본 스킨톤", "元の肌色"], "Target tone": ["대상 스킨톤", "変換先の肌色"], "Auto from selection": ["선택 영역에서 추정", "選択範囲から推定"], "Slight (approximate)": ["slight (근사)", "slight（近似）"],
    "Apply skin tone": ["스킨톤 적용", "肌色を適用"], "Sample tolerance": ["표본 허용치", "サンプル許容差"], "Connected pixels only": ["연결된 픽셀만", "つながったピクセルのみ"],
    "Limit samples to current selection": ["표본 찾기를 현재 선택 범위로 제한", "サンプルを現在の選択範囲内に制限"], "Feather inward": ["선택 안쪽 경계 흐림", "選択範囲の内側をぼかす"],
    "Pick skin on the model or texture, then refine with the selection brush.": ["모델 또는 텍스쳐에서 피부를 찍은 뒤 선택 브러시로 영역을 보정하세요.", "モデルやテクスチャの肌をクリックし、選択ブラシで範囲を調整してください。"],
    "Skin changes require an explicit selection.": ["스킨톤을 바꾸려면 피부 영역을 먼저 선택하세요.", "肌色を変更する範囲を先に選択してください。"],
    "Brush": ["브러시", "ブラシ"], "Eraser": ["지우개", "消しゴム"], "Fill": ["채우기", "塗りつぶし"], "Line": ["직선", "直線"], "Rectangle": ["사각형", "矩形"], "Ellipse": ["타원", "楕円"], "Eyedropper": ["스포이드", "スポイト"], "Pan": ["이동", "移動"],
    "Brush size": ["브러시 크기", "ブラシの大きさ"], "Opacity": ["불투명도", "不透明度"], "Softness": ["부드러움", "ぼかし"], "Color": ["색상", "色"], "Color alpha": ["색상 알파", "色のアルファ"],
    "Filled shapes": ["도형 내부 채우기", "図形を塗りつぶす"], "Import PNG": ["PNG 불러오기", "PNGを読み込む"], "Export PNG": ["PNG 저장", "PNGを書き出す"],
    "Shared UV pixels also change every face using those pixels.": ["UV를 공유하는 면은 같은 픽셀이 함께 바뀝니다. 모델 미리보기에서 확인하세요.", "UVを共有する面は同じピクセルが一緒に変わります。モデルで確認してください。"],
    "Choose faces or a texture region before applying color.": ["색상을 적용할 면 또는 텍스쳐 영역을 선택하세요.", "色を適用する面またはテクスチャ範囲を選択してください。"],
    "Preparing exact texture pixels…": ["정확한 텍스쳐 픽셀을 준비하는 중…", "正確なテクスチャピクセルを準備中…"], "Preparing color preview…": ["색상 미리보기를 준비하는 중…", "色のプレビューを準備中…"],
    "Preview ready. Apply to keep this change.": ["미리보기가 준비됐습니다. 적용하면 편집 내용에 남습니다.", "プレビューできました。適用すると編集に保存されます。"],
    "Texture edits ready. Save model edits or a Mod ZIP to export.": ["텍스쳐 편집이 준비됐습니다. 모델 편집 저장 또는 모드 ZIP으로 내보내세요.", "テクスチャを編集しました。モデル編集やMod ZIPで保存してください。"],
    "Texture dimensions must match the original.": ["텍스쳐 크기는 원본과 같아야 합니다.", "テクスチャのサイズは元画像と同じにしてください。"],
    "Lossless pixels; saved texture data can use more memory.": ["픽셀을 손실 없이 저장하므로 텍스쳐 데이터 용량이 늘어날 수 있습니다.", "ピクセルを可逆保存するためテクスチャ容量が増える場合があります。"],
    "Selected pixels": ["선택 픽셀", "選択ピクセル"], "Estimated source": ["추정 원본", "推定元"], "Saved changes": ["편집 텍스쳐", "編集テクスチャ"],
    "Expand editor": ["편집창 확대", "編集画面を拡大"], "Collapse editor": ["편집창 축소", "編集画面を縮小"],
    "UV island": ["UV 섬 선택", "UVアイランド選択"], "UV face": ["UV 면 선택", "UV面選択"],
    "Texture tools": ["텍스쳐 조작 도구", "テクスチャ操作ツール"], "File": ["파일", "ファイル"], "View": ["보기", "表示"], "Selection": ["선택", "選択"],
    "Color and layers": ["색상·레이어", "色・レイヤー"], "Help": ["도움말", "ヘルプ"],
    "Resize texture canvas": ["텍스쳐 표시 크기 조절", "テクスチャ表示サイズを調整"], "Resize tool settings": ["설정 패널 너비 조절", "設定パネルの幅を調整"],
    "Open a model texture to select UV regions.": ["UV 영역을 선택하려면 모델의 텍스쳐를 여세요.", "UV範囲を選ぶにはモデルのテクスチャを開いてください。"],
    "Opening PNG…": ["PNG를 불러오는 중…", "PNGを読み込み中…"], "Saving PNG…": ["PNG를 저장하는 중…", "PNGを保存中…"],
    "PNG saved on this device.": ["이 기기에 PNG를 저장했습니다.", "この端末にPNGを保存しました。"], "Download PNG": ["PNG 다운로드", "PNGをダウンロード"],
    "Import a PNG to start painting, or choose a model texture.": ["PNG를 불러와 그리거나 모델 텍스쳐를 선택하세요.", "PNGを読み込むか、モデルのテクスチャを選択してください。"],
    "Image changes ready. Use Export PNG to save.": ["이미지 편집이 준비됐습니다. PNG 저장으로 내보내세요.", "画像を編集しました。PNGで書き出してください。"],
    "Include this costume's face/mouth edits when saving a Mod ZIP to save these face textures.": ["이 얼굴 텍스쳐를 모드에 넣으려면 저장할 때 ‘이 코스튬의 얼굴·입 편집 포함’을 켜세요.", "この顔テクスチャをModに保存するには、この衣装の顔・口の編集を含める設定を有効にしてください。"],
    "The texture source changed. Reload the original model.": ["텍스쳐 원본이 달라졌습니다. 원본 모델을 다시 열어 주세요.", "テクスチャの元データが変わりました。元モデルを開き直してください。"]
  };
  function create(options) {
    options = options || {};
    var document = global.document, holder = options.holder || document && document.getElementById("viewer-texture-tool-slot");
    if (!holder || !global.TexturePaintEngine || !global.TextureColorMath) return null;
    var T = global.THREE, math = global.TextureColorMath, processor = math.createProcessor ? math.createProcessor({ workerUrl: "/static/texture-color-worker.js" }) : null;
    var disposed = false, currentToken = null, epoch = 0, revision = 0, sequence = 0, previewTimer = null, previewJobs = 0, loading = 0;
    var catalogue = [], entries = new Map(), active = null, activeTab = "costume", sceneMode = "orbit", labels = [], units = [], listeners = [], overlays = [], genericMaps = new Map();
    var overlayState = null, brushStroke = null, hoverAt = 0, lastEditable = null, selectionAutoHidden = false;
    var requestControllers = new Set(), sceneElement = null, pointer = null, space = false, geometryCache = new WeakMap(), lastModel = null, pendingRestore = null, cataloguePromise = null, restoringDocuments = 0, suppressed = 0, notifiedPending = false;
    var modelRebindOwner = {}, rebindingModel = false;
    var statusText = "", error = "", performance = { previewsStarted: 0, previewsDiscarded: 0, textureUploads: 0, maskOverlays: 0, encodes: 0 };
    function t(text) {
      var translated = options.translate && options.translate(text); if (translated && translated !== text) return translated;
      var lang = document.documentElement.lang || global.SIFAS_LANG || "en", pair = WORDS[text];
      return pair ? pair[lang.slice(0, 2) === "ko" ? 0 : lang.slice(0, 2) === "ja" ? 1 : -1] || text : text;
    }
    function node(tag, parent, text, className) {
      var item = document.createElement(tag); if (className) item.className = className;
      if (text) {
        var target = item;
        if (tag === "label") { target = document.createElement("span"); item.appendChild(target); }
        labels.push([target, text]); target.textContent = t(text);
      }
      if (parent) parent.appendChild(item); return item;
    }
    function listen(item, event, fn, capture) { item.addEventListener(event, fn, capture || false); listeners.push(function () { item.removeEventListener(event, fn, capture || false); }); }
    function runtime() { return options.getRuntime ? options.getRuntime() || {} : {}; }
    function requestRender() { var r = runtime(); if (r.requestRender) r.requestRender(); }
    function canEdit(entry) { return !!(entry && (entry.standalone || (!options.isReadOnly || !options.isReadOnly()) && (!options.isInteractive || options.isInteractive()))); }
    function changed() { revision++; if (options.onChange) options.onChange(); refreshButtons(); requestRender(); }
    function say(text, detail) { statusText = text || ""; error = detail || ""; status.textContent = (text ? t(text) : "") + (detail ? " " + t(detail) : ""); status.classList.toggle("viewer-texture-error", !!detail); }
    function api(path, value) {
      var controller = new AbortController(); requestControllers.add(controller);
      return global.fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value), signal: controller.signal }).then(function (response) {
        return response.json().then(function (data) { if (!response.ok || data.error) throw new Error(data.error || response.statusText); return data; });
      }).finally(function () { requestControllers.delete(controller); });
    }
    function exact(data) {
      if (!global.TexturePNG || !global.TexturePNG.decodeRGBA) throw new Error("The lossless texture pixel reader is unavailable.");
      return global.TexturePNG.decodeRGBA(data);
    }
    function encode(image) {
      if (!global.TexturePNG || !global.TexturePNG.encodeRGBA) return Promise.reject(new Error("The lossless texture PNG writer is unavailable."));
      performance.encodes++; return Promise.resolve(global.TexturePNG.encodeRGBA(image));
    }
    function decodePatch(entry, png) { return api("/api/viewer/texture/decode", { token: currentToken, texture: entry.record.texture, png: png }).then(exact); }
    var section = node("details", holder, null, "viewer-control-section viewer-adjustments viewer-texture-tools"); section.id = "viewer-texture-tools";
    node("summary", section, "Texture and color tools");
    var content = node("div", section, null, "viewer-texture-content"), tabs = node("div", content, null, "viewer-texture-tabs"); tabs.setAttribute("role", "tablist");
    var expanded = false, expandAnchor = null, pickerStackCleanup = null, expandButton = button(content, "Expand editor", function () { setExpanded(!expanded); }, "viewer-texture-expand");
    expandButton.setAttribute("aria-pressed", "false");
    var tabButtons = {};
    [["costume", "Costume color"], ["skin", "Skin tone"], ["paint", "Paint"]].forEach(function (pair) {
      var button = node("button", tabs, pair[1]); button.type = "button"; button.id = "viewer-texture-tab-" + pair[0]; button.setAttribute("role", "tab"); tabButtons[pair[0]] = button; listen(button, "click", function () { setTab(pair[0]); });
    });
    var textureLabel = node("label", content, "Texture", "viewer-texture-field"); var textureSelect = node("select", textureLabel); textureSelect.id = "viewer-texture-select"; textureSelect.setAttribute("aria-label", t("Texture"));
    var sceneRow = node("div", content, null, "viewer-texture-row");
    function select(parent, label, choices, id) {
      var wrap = node("label", parent, label, "viewer-texture-field"), input = node("select", wrap); if (id) input.id = id;
      choices.forEach(function (pair) { var option = node("option", input, pair[1]); option.value = pair[0]; }); return input;
    }
    function check(parent, label, value, id) { var wrap = node("label", parent, null, "viewer-texture-check"), input = node("input", wrap); input.type = "checkbox"; input.checked = value; if (id) input.id = id; node("span", wrap, label); return input; }
    function button(parent, label, fn, id) { var b = node("button", parent, label); b.type = "button"; if (id) b.id = id; listen(b, "click", fn); return b; }
    function number(parent, label, value, min, max, step, id) {
      var wrap = node("label", parent, label, "viewer-texture-field"), field = node("input", wrap); field.type = "number"; field.value = value; field.min = min; field.max = max; field.step = step; if (id) field.id = id; return field;
    }
    function slider(parent, label, value, min, max, step, id, callback) {
      var wrap = node("label", parent, null, "viewer-texture-slider"), title = node("span", wrap, label), range = node("input", wrap), field = node("input", wrap);
      var unit = label === "Lightness" ? " Δ (%p)" : ["Chroma", "Strength", "Opacity", "Softness"].indexOf(label) >= 0 ? " (%)" : label === "Hue" ? " (°)" : ["Brush size", "Feather inward"].indexOf(label) >= 0 ? " (px)" : "";
      if (unit) { units.push([title, unit]); title.textContent += unit; }
      title.className = "viewer-texture-slider-title"; range.type = "range"; field.type = "number"; range.min = field.min = min; range.max = field.max = max; range.step = field.step = step; range.value = field.value = value; field.id = id; range.setAttribute("aria-label", t(label));
      if (min < 0 && global.ViewerSignedInputs) global.ViewerSignedInputs.attach(field, { signButton: false });
      function incomplete() { return !field.value.trim() || field.validity && field.validity.badInput || !isFinite(Number(field.value)); }
      function change(from, to) {
        if (from === field && incomplete()) {
          // Keep the browser's '-' / '-.' draft and last valid preview intact.
          if (callback === schedulePreview) { sequence++; if (previewTimer) global.clearTimeout(previewTimer); previewTimer = null; refreshButtons(); }
          return;
        }
        var raw = Number(from.value), value = Math.round(clamp(raw, min, max) * 1000) / 1000;
        to.value = String(value); if (from === range || raw !== value) from.value = String(value);
        if (callback) callback();
      }
      listen(range, "input", function () { change(range, field); }); listen(field, "input", function () { change(field, range); });
      listen(field, "change", function () { if (incomplete()) { field.value = range.value; if (callback) callback(); } });
      return { field: field, range: range, value: function () { return Number(incomplete() ? range.value : field.value); }, set: function (v) { field.value = range.value = String(v); } };
    }
    var sceneSelect = select(sceneRow, "Model selection", [["orbit", "Orbit"], ["brush", "3D selection brush"], ["face", "Face"], ["connected", "Connected faces"], ["skin", "Skin sample"], ["exclude", "Exclude sample"]], "viewer-texture-scene-mode");
    var selectTool = select(sceneRow, "Selection tool", [["select-uv-island", "UV island"], ["select-uv-face", "UV face"], ["select-brush", "Selection brush"], ["select-rectangle", "Rectangle selection"], ["select-lasso", "Lasso selection"], ["select-wand", "Magic wand"], ["pan", "Pan"]], "viewer-texture-selection-tool");
    selectTool.value = "select-brush";
    var selectionMode = select(sceneRow, "Mode", [["replace", "Replace"], ["add", "Add"], ["subtract", "Subtract"], ["intersect", "Intersect"]], "viewer-texture-selection-mode");
    var selectionActions = node("div", content, null, "viewer-texture-actions");
    button(selectionActions, "Select all", function () { if (active && active.engine && canEdit(active)) { cancelPreview(); active.engine.selectAll(); } }, "viewer-texture-select-all");
    button(selectionActions, "Select none", function () { if (active && active.engine && canEdit(active)) { cancelPreview(); active.engine.selectNone(); } }, "viewer-texture-select-none");
    button(selectionActions, "Clear selection", function () { if (active && active.engine && canEdit(active)) { cancelPreview(); active.engine.clearSelection(); } }, "viewer-texture-selection-clear");
    button(selectionActions, "Invert selection", function () { if (active && active.engine && canEdit(active)) { cancelPreview(); active.engine.invertSelection(); } });
    var colorPanel = node("div", content, null, "viewer-texture-panel"); colorPanel.id = "viewer-texture-costume-panel";
    var colorMode = select(colorPanel, "Mode", [["relative", "Relative OKLCH"], ["colorize", "Target color, keep shading"]], "viewer-texture-color-mode");
    var targetLabel = node("label", colorPanel, "Target color", "viewer-texture-field"), targetColor = node("input", targetLabel); targetColor.type = "color"; targetColor.value = "#ce416a"; targetColor.id = "viewer-texture-target-color";
    var colorL = slider(colorPanel, "Lightness", 0, -100, 100, .1, "viewer-texture-lightness", schedulePreview), colorC = slider(colorPanel, "Chroma", 100, 0, 300, 1, "viewer-texture-chroma", schedulePreview), colorH = slider(colorPanel, "Hue", 0, -180, 180, 1, "viewer-texture-hue", schedulePreview), colorStrength = slider(colorPanel, "Strength", 100, 0, 100, 1, "viewer-texture-color-strength", schedulePreview);
    var skinPanel = node("div", content, null, "viewer-texture-panel"); skinPanel.id = "viewer-texture-skin-panel"; skinPanel.hidden = true;
    var tones = [["auto", "Auto from selection"], ["default", "default"], ["bright", "bright"], ["slight", "Slight (approximate)"], ["medium_tone", "medium_tone"]];
    var skinRow = node("div", skinPanel, null, "viewer-texture-row"), sourceTone = select(skinRow, "Source tone", tones, "viewer-texture-source-tone"), targetTone = select(skinRow, "Target tone", tones.slice(1), "viewer-texture-target-tone"); targetTone.value = "bright";
    node("p", skinPanel, "Pick skin on the model or texture, then refine with the selection brush.", "viewer-texture-hint");
    var seedRow = node("div", skinPanel, null, "viewer-texture-actions");
    button(seedRow, "Skin sample", function () { setSceneMode("skin"); if (active && active.engine) active.engine.setTool("picker"); });
    button(seedRow, "Exclude sample", function () { setSceneMode("exclude"); if (active && active.engine) active.engine.setTool("picker"); });
    var tolerance = slider(skinPanel, "Sample tolerance", .08, .01, .3, .01, "viewer-texture-sample-tolerance", function () { if (active && active.seeds.length) growSelection(active); });
    var connected = check(skinPanel, "Connected pixels only", true, "viewer-texture-connected-pixels"), sampleGate = check(skinPanel, "Limit samples to current selection", false, "viewer-texture-sample-gate");
    var feather = slider(skinPanel, "Feather inward", 0, 0, 8, 1, "viewer-texture-feather", schedulePreview);
    var skinL = slider(skinPanel, "Lightness", 0, -100, 100, .1, "viewer-texture-skin-lightness", schedulePreview), skinC = slider(skinPanel, "Chroma", 100, 0, 300, 1, "viewer-texture-skin-chroma", schedulePreview), skinH = slider(skinPanel, "Hue", 0, -180, 180, 1, "viewer-texture-skin-hue", schedulePreview), skinStrength = slider(skinPanel, "Strength", 100, 0, 100, 1, "viewer-texture-skin-strength", schedulePreview);
    var toneEstimate = node("output", skinPanel, null, "viewer-texture-hint"); toneEstimate.id = "viewer-texture-tone-estimate";
    var paintPanel = node("div", content, null, "viewer-texture-panel"); paintPanel.id = "viewer-texture-paint-panel"; paintPanel.hidden = true;
    var paintRow = node("div", paintPanel, null, "viewer-texture-row");
    var paintTool = select(paintRow, "Paint", [["brush", "Brush"], ["eraser", "Eraser"], ["fill", "Fill"], ["select-uv-island", "UV island"], ["select-uv-face", "UV face"], ["select-rectangle", "Rectangle selection"], ["select-lasso", "Lasso selection"], ["select-wand", "Magic wand"], ["select-brush", "Selection brush"], ["move", "Move selected pixels"], ["line", "Line"], ["rectangle", "Draw rectangle"], ["ellipse", "Ellipse"], ["picker", "Eyedropper"], ["pan", "Pan"]], "viewer-texture-paint-tool");
    var colorLabel = node("label", paintRow, "Color", "viewer-texture-field"), paintColor = node("input", colorLabel); paintColor.type = "color"; paintColor.value = "#e84e76"; paintColor.id = "viewer-texture-paint-color";
    var paintAlpha = number(paintRow, "Color alpha", 100, 0, 100, 1, "viewer-texture-paint-alpha");
    var brushSize = slider(content, "Brush size", 24, 1, 512, 1, "viewer-texture-brush-size", syncBrush), opacity = slider(content, "Opacity", 100, 0, 100, 1, "viewer-texture-opacity", syncBrush), softness = slider(paintPanel, "Softness", 20, 0, 100, 1, "viewer-texture-softness", syncBrush);
    var filled = check(paintPanel, "Filled shapes", true), imageActions = node("div", paintPanel, null, "viewer-texture-actions"), fileInput = node("input", paintPanel); fileInput.type = "file"; fileInput.accept = "image/png,.png"; fileInput.hidden = true;
    button(imageActions, "Import PNG", choosePNG, "viewer-texture-import"); var exportButton = button(imageActions, "Export PNG", exportPNG, "viewer-texture-export");
    var clipboardActions = node("div", paintPanel, null, "viewer-texture-actions"), clipboardButtons = {};
    [["copy", "Copy", "copySelection"], ["cut", "Cut", "cutSelection"], ["paste", "Paste", "pasteClipboard"], ["move", "Move selected pixels", "startMoveSelection"], ["commit", "Apply moved pixels", "commitFloating"], ["cancel", "Cancel move", "cancelFloating"]].forEach(function (row) {
      clipboardButtons[row[0]] = button(clipboardActions, row[1], function () { clipboardAction(row[2]); }, "viewer-texture-" + (row[0] === "cancel" ? "cancel-move" : row[0]));
    });
    var floatingHint = node("output", paintPanel, null, "viewer-texture-hint"); floatingHint.id = "viewer-texture-floating-info";
    node("p", paintPanel, "Rectangle selection clips fill and paint. Move drags selected pixels.", "viewer-texture-hint");
    node("p", paintPanel, "Ctrl/Cmd+C copy · X cut · V paste · Enter apply · Esc cancel", "viewer-texture-hint");
    var layerPanel = node("div", paintPanel, null, "viewer-texture-layers"); node("strong", layerPanel, "Layers");
    var layerList = node("div", layerPanel, null, "viewer-texture-layer-list"); layerList.id = "viewer-texture-layer-list"; layerList.setAttribute("role", "list");
    var layerEdit = node("div", layerPanel, null, "viewer-texture-row"), layerNameLabel = node("label", layerEdit, "Layer name", "viewer-texture-field"), layerName = node("input", layerNameLabel); layerName.id = "viewer-texture-layer-name"; layerName.type = "text"; layerName.maxLength = 128;
    var layerOpacityLabel = node("label", layerEdit, "Layer opacity", "viewer-texture-field"), layerOpacity = node("input", layerOpacityLabel); layerOpacity.type = "range"; layerOpacity.min = 0; layerOpacity.max = 100; layerOpacity.step = 1; layerOpacity.id = "viewer-texture-layer-opacity";
    var layerOpacityValue = node("output", layerOpacityLabel); layerOpacityValue.id = "viewer-texture-layer-opacity-value";
    var layerActions = node("div", layerPanel, null, "viewer-texture-actions"), layerButtons = {}, layerSignature = "";
    [["add", "Add layer"], ["duplicate", "Duplicate layer"], ["remove", "Delete layer"], ["up", "Layer up"], ["down", "Layer down"], ["merge", "Merge down"]].forEach(function (row) { layerButtons[row[0]] = button(layerActions, row[1], function () { changeLayer(row[0]); }, "viewer-texture-layer-" + row[0]); });
    node("p", layerPanel, "PNG and game saves flatten visible layers. Save a layer project to keep layers editable.", "viewer-texture-hint");
    var projectActions = node("div", layerPanel, null, "viewer-texture-actions"), projectFile = node("input", layerPanel); projectFile.type = "file"; projectFile.accept = "application/json,.json"; projectFile.hidden = true;
    var projectOpenButton = button(projectActions, "Open layer project", chooseProject, "viewer-texture-project-open"), projectSaveButton = button(projectActions, "Save layer project", saveProject, "viewer-texture-project-save");
    node("p", layerPanel, "Opening a project replaces this texture's layers and can be undone.", "viewer-texture-hint");
    var adjustmentActions = node("div", content, null, "viewer-texture-actions");
    var applyButton = button(adjustmentActions, "Apply color", applyPreview, "viewer-texture-apply"), cancelButton = button(adjustmentActions, "Cancel preview", cancelPreview, "viewer-texture-cancel");
    var compare = check(adjustmentActions, "Compare original", false, "viewer-texture-compare");
    var restoreTextureButton = button(adjustmentActions, "Restore original texture", requestTextureRestore, "viewer-texture-reset");
    var restoreTexturePrompt = node("div", adjustmentActions, null, "viewer-texture-hint"); restoreTexturePrompt.id = "viewer-texture-restore-prompt"; restoreTexturePrompt.hidden = true;
    restoreTexturePrompt.setAttribute("role", "alertdialog"); restoreTexturePrompt.setAttribute("aria-labelledby", "viewer-texture-restore-question");
    var restoreTextureQuestion = node("p", restoreTexturePrompt, "Restore the image loaded before editing? This replaces all its layers and can be undone."); restoreTextureQuestion.id = "viewer-texture-restore-question";
    var restoreTextureActions = node("div", restoreTexturePrompt, null, "viewer-texture-actions");
    var restoreTextureConfirm = button(restoreTextureActions, "Restore texture", confirmTextureRestore, "viewer-texture-restore-confirm");
    button(restoreTextureActions, "Keep editing", function () { closeTextureRestore(); restoreTextureButton.focus({ preventScroll: true }); }, "viewer-texture-restore-cancel");
    var textureRestoreRequest = null;
    restoreTextureButton.setAttribute("aria-controls", restoreTexturePrompt.id); restoreTextureButton.setAttribute("aria-expanded", "false");
    var views = node("div", content, null, "viewer-texture-actions");
    var undoButton = button(views, "Undo", undo, "viewer-texture-undo"), redoButton = button(views, "Redo", redo, "viewer-texture-redo");
    button(views, "Fit", function () { if (active && active.engine) active.engine.fit(); });
    button(views, "−", function () { if (active && active.engine) { var view = active.engine.getView(); view.zoom /= 1.4; active.engine.setView(view); } });
    button(views, "+", function () { if (active && active.engine) { var view = active.engine.getView(); view.zoom *= 1.4; active.engine.setView(view); } });
    var showSelection = check(views, "Show selection", true, "viewer-texture-show-selection");
    var showUV = check(views, "Show UV", true, "viewer-texture-show-uv"), uvControl = global.ViewerUVColor ? global.ViewerUVColor.control(views, { id: "viewer-texture-uv-color", translate: t, onChange: function () { if (active && active.engine) active.engine.render(); } }) : null;
    var canvasHost = node("div", content, null, "viewer-texture-canvas-host"); canvasHost.id = "viewer-texture-canvas-host";
    var information = node("output", content, null, "viewer-texture-info"); information.id = "viewer-texture-info";
    var status = node("output", content, null, "viewer-texture-status"); status.id = "viewer-texture-status"; status.setAttribute("aria-live", "polite");
    var readonlyNote = node("p", content, "This saved copy is read-only. Reopen the original to edit.", "viewer-texture-hint"); readonlyNote.id = "viewer-texture-readonly-note"; readonlyNote.hidden = true;
    var savedFile = node("div", content, null, "viewer-texture-hint"); savedFile.id = "viewer-texture-saved-file"; savedFile.hidden = true;
    node("span", savedFile, "PNG saved on this device."); node("br", savedFile);
    var savedPath = node("code", savedFile); savedPath.id = "viewer-texture-saved-path"; node("br", savedFile);
    var savedDownload = node("a", savedFile, "Download PNG"); savedDownload.id = "viewer-texture-download"; savedDownload.rel = "noopener";
    var savedProjectFile = node("div", content, null, "viewer-texture-hint"); savedProjectFile.id = "viewer-texture-project-saved"; savedProjectFile.hidden = true;
    node("span", savedProjectFile, "Layer project saved on this device."); node("br", savedProjectFile);
    var savedProjectPath = node("code", savedProjectFile); savedProjectPath.id = "viewer-texture-project-saved-path"; node("br", savedProjectFile);
    var savedProjectDownload = node("a", savedProjectFile, "Download layer project"); savedProjectDownload.id = "viewer-texture-project-download";
    var faceNote = node("p", content, "Include this costume's face/mouth edits when saving a Mod ZIP to save these face textures.", "viewer-texture-hint"); faceNote.id = "viewer-texture-face-note"; faceNote.hidden = true;
    node("p", content, "Shared UV pixels also change every face using those pixels.", "viewer-texture-hint");
    node("p", content, "Lossless pixels; saved texture data can use more memory.", "viewer-texture-hint");
    var modelCursor = node("div", document.body, null, "viewer-texture-model-brush-cursor"); modelCursor.id = "viewer-texture-model-brush-cursor"; modelCursor.hidden = true; modelCursor.setAttribute("aria-hidden", "true");
    // Keep the same stateful controls and canvas, but give the image its own
    // workspace. Tool choice never requires scrolling through the inspector.
    var workspace = {}, toolButtons = [], workspacePreferences = {};
    try { workspacePreferences = JSON.parse(global.localStorage.getItem("elichika.texture.workspace.v2") || "{}"); } catch (_) {}
    buildWorkspace();
    function move(parent, items) { items.forEach(function (item) { if (item) parent.appendChild(item); }); }
    function compact(button, symbol) { button.classList.add("viewer-texture-icon-button"); button.dataset.symbol = symbol; button.title = button.textContent; return button; }
    function buildWorkspace() {
      var header = node("div", content, null, "viewer-texture-header"), fileMenu = node("details", header, null, "viewer-texture-file-menu");
      node("summary", fileMenu, "File"); var fileMenuBody = node("div", fileMenu, null, "viewer-texture-menu-body"); move(fileMenuBody, [imageActions, projectActions]);
      move(header, [textureLabel, tabs, expandButton]); compact(expandButton, "↗︎");
      var settingsButton = button(header, "Color and layers", function () { workspace.inspector.open = !workspace.inspector.open; }, "viewer-texture-toggle-inspector"); compact(settingsButton, ""); settingsButton.setAttribute("aria-expanded", "true"); settingsButton.setAttribute("aria-label", t("Color and layers"));
      var workbench = node("div", content, null, "viewer-texture-workbench"); workbench.id = "viewer-texture-workbench";
      var stage = node("div", workbench, null, "viewer-texture-stage-column"), tools = node("div", stage, null, "viewer-texture-context-bar"); tools.id = "viewer-texture-toolstrip";
      move(tools, [selectTool.parentNode, paintTool.parentNode, selectionMode.parentNode]);
      var more = node("details", tools, null, "viewer-texture-selection-menu"); node("summary", more, "Selection"); var selectionBody = node("div", more, null, "viewer-texture-menu-body"); move(selectionBody, [selectionActions, clipboardActions]);
      var viewBar = node("div", stage, null, "viewer-texture-view-bar"); move(viewBar, [views]);
      var viewOptions = node("details", views, null, "viewer-texture-view-options"); node("summary", viewOptions, "View");
      var viewMenuBody = node("div", viewOptions, null, "viewer-texture-menu-body");
      Array.from(views.children).forEach(function (item) { if (item !== viewOptions && item.tagName !== "BUTTON") viewMenuBody.appendChild(item); });
      showSelection.parentNode.classList.add("viewer-texture-selection-toggle");
      showSelection.parentNode.title = t("Color adjustments hide selection tint without clearing the selection.");
      showSelection.setAttribute("aria-describedby", "viewer-texture-info");
      compact(undoButton, "↶"); compact(redoButton, "↷");
      var quick = node("div", stage, null, "viewer-texture-quick-options");
      move(quick, [brushSize.field.parentNode, opacity.field.parentNode, colorLabel]);
      var frame = node("div", stage, null, "viewer-texture-canvas-frame"), rail = node("div", frame, null, "viewer-texture-tool-rail"); rail.setAttribute("role", "toolbar"); rail.setAttribute("aria-label", t("Texture tools"));
      var icons = { "select-uv-island": "M3 4h7l2 4 7 1 2 8-6 4-5-4-7 1z M10 4v13 M3 10l16-1 M10 17l9-8", "select-uv-face": "M4 20 11 3l10 17z M4 20l11-9", "select-rectangle": "M3 8V3h5 M16 3h5v5 M21 16v5h-5 M8 21H3v-5", "select-lasso": "M7 18c-8-3-5-13 4-14 10-1 15 9 7 13-4 2-11 3-11 0 0-4 8-3 7 1-1 4-4 4-5 3", "select-wand": "m4 20 12-12 M12 4l1 3 M17 3l-1 3 M21 7l-3 1 M20 12l-3-1 M7 4v4 M5 6h4", "select-brush": "M5 9V5h4 M15 5h4v4 M19 15v4h-4 M9 19H5v-4 M9 12h6 M12 9v6", "brush": "m9 14 9-11 3 3-11 9 M10 15c2 6-4 7-7 6 3-1 0-6 4-6z", "eraser": "m3 15 10-11 8 7-10 10H8z M8 10l8 7 M11 21h10", "fill": "m4 12 8-8 8 8-8 8z M9 2l7 7 M3 22h18 M21 16c-3 4-3 5 0 5s3-1 0-5", "move": "M12 3v18 M3 12h18 M8 7l4-4 4 4 M8 17l4 4 4-4 M7 8l-4 4 4 4 M17 8l4 4-4 4", "picker": "m4 16 11-11 4 4L8 20H4z M13 3l8 8 M17 3l4 4", "pan": "M5 13V9c0-2 3-2 3 0V5c0-2 3-2 3 0v5-7c0-2 3-2 3 0v7-5c0-2 3-2 3 0v8l2-3c2-2 4 0 2 3l-4 7H9l-6-7c-1-2 1-3 2 0z", "line": "M4 20 20 4", "rectangle": "M4 4h16v16H4z", "ellipse": "M21 12a9 7 0 1 1-18 0 9 7 0 1 1 18 0" };
      var names = { "select-uv-island": "UV island", "select-uv-face": "UV face", "select-rectangle": "Rectangle selection", "select-lasso": "Lasso selection", "select-wand": "Magic wand", "select-brush": "Selection brush", "brush": "Brush", "eraser": "Eraser", "fill": "Fill", "move": "Move selected pixels", "picker": "Eyedropper", "pan": "Pan", "line": "Line", "rectangle": "Draw rectangle", "ellipse": "Ellipse" };
      ["pan", "select-uv-island", "select-uv-face", "select-rectangle", "select-lasso", "select-wand", "select-brush", "brush", "eraser", "fill", "move", "picker", "line", "rectangle", "ellipse"].forEach(function (tool) {
        var b = button(rail, "", function () { setCanvasTool(tool); }); b.className = "viewer-texture-icon-button viewer-texture-svg-button"; b.title = t(names[tool]);
        var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"), path = document.createElementNS("http://www.w3.org/2000/svg", "path"); svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.classList.add("viewer-texture-tool-icon"); path.setAttribute("d", icons[tool]); svg.appendChild(path); b.appendChild(svg); node("span", b, names[tool], "viewer-texture-tool-label");
        b.dataset.textureTool = tool; b.setAttribute("aria-label", t(names[tool])); b.setAttribute("aria-pressed", "false"); toolButtons.push({ node: b, tool: tool, name: names[tool], paintOnly: ["brush", "eraser", "fill", "move", "line", "rectangle", "ellipse"].indexOf(tool) >= 0 });
        if (tool === "pan") { b.id = "viewer-texture-pan"; views.insertBefore(b, viewOptions); }
      });
      move(frame, [canvasHost]);
      var floatingBar = node("div", stage, null, "viewer-texture-floating-actions"); floatingBar.hidden = true; move(floatingBar, [clipboardButtons.commit, clipboardButtons.cancel, floatingHint]);
      var sizeHandle = node("div", stage, null, "viewer-texture-canvas-resizer"); sizeHandle.id = "viewer-texture-canvas-resizer"; sizeHandle.tabIndex = 0; sizeHandle.setAttribute("role", "separator"); sizeHandle.setAttribute("aria-orientation", "horizontal"); sizeHandle.setAttribute("aria-label", t("Resize texture canvas"));
      var dockHandle = node("div", workbench, null, "viewer-texture-inspector-resizer"); dockHandle.id = "viewer-texture-inspector-resizer"; dockHandle.tabIndex = 0; dockHandle.setAttribute("role", "separator"); dockHandle.setAttribute("aria-orientation", "vertical"); dockHandle.setAttribute("aria-label", t("Resize tool settings"));
      var inspector = node("details", workbench, null, "viewer-texture-inspector"); inspector.id = "viewer-texture-inspector"; inspector.open = true; node("summary", inspector, "Color and layers");
      var properties = node("div", inspector, null, "viewer-texture-properties"); move(properties, [colorPanel, skinPanel, paintPanel, adjustmentActions]);
      paintPanel.insertBefore(layerPanel, paintPanel.firstChild);
      [["add", "+"], ["duplicate", "⧉"], ["remove", "−"], ["up", "↑"], ["down", "↓"], ["merge", "⇩"]].forEach(function (row) { compact(layerButtons[row[0]], row[1]); });
      var modelOptions = node("details", properties, null, "viewer-texture-model-options"); node("summary", modelOptions, "Model selection"); move(modelOptions, [sceneSelect.parentNode]);
      var help = node("details", properties, null, "viewer-texture-help"); node("summary", help, "Help");
      Array.from(paintPanel.querySelectorAll("p.viewer-texture-hint")).forEach(function (item) { help.appendChild(item); });
      Array.from(content.children).forEach(function (item) { if (item.classList.contains("viewer-texture-hint") && item !== savedFile && item !== savedProjectFile && item !== faceNote && item !== readonlyNote) help.appendChild(item); });
      var colorActions = node("div", stage, null, "viewer-texture-color-actions"); move(colorActions, [showSelection.parentNode, applyButton, cancelButton, compare.parentNode]);
      var statusBar = node("div", content, null, "viewer-texture-status-bar"); move(statusBar, [information, status]);
      move(content, [header, workbench, statusBar, readonlyNote, faceNote, savedFile, savedProjectFile]);
      sceneRow.remove();
      workspace = { header: header, workbench: workbench, stage: stage, frame: frame, rail: rail, inspector: inspector, properties: properties, quick: quick, colorActions: colorActions, resizer: sizeHandle, dockResizer: dockHandle, settingsButton: settingsButton, floatingBar: floatingBar };
      section.classList.add("viewer-texture-inspector-open");
      applyWorkspaceSize();
      listen(inspector, "toggle", function () { section.classList.toggle("viewer-texture-inspector-open", inspector.open); settingsButton.setAttribute("aria-expanded", String(inspector.open)); });
      bindWorkspaceResize(sizeHandle, "height"); bindWorkspaceResize(dockHandle, "width");
      [fileMenu, viewOptions, more].forEach(function (menu) {
        listen(menu, "toggle", function () { if (menu.open) [fileMenu, viewOptions, more].forEach(function (other) { if (other !== menu && other.open) other.open = false; }); });
        listen(menu, "click", function (event) { var action = event.target.closest && event.target.closest("button"); if (action && !action.disabled) { menu.open = false; if (menu !== fileMenu && active && active.canvas) active.canvas.focus({ preventScroll: true }); } });
        listen(menu, "keydown", function (event) { if (event.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus({ preventScroll: true }); event.preventDefault(); event.stopPropagation(); } });
      });
      listen(section, "pointerdown", function (event) { [fileMenu, viewOptions, more].forEach(function (menu) { if (menu.open && !menu.contains(event.target)) menu.open = false; }); });
      listen(section, "keydown", function (event) {
        if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
        var shortcuts = { b: "brush", e: "eraser", f: "fill", m: "select-rectangle", l: "select-lasso", w: "select-wand", u: event.shiftKey ? "select-uv-face" : "select-uv-island", v: "move", h: "pan", i: "picker" }, tool = shortcuts[String(event.key || "").toLowerCase()];
        if (tool && setCanvasTool(tool)) { event.preventDefault(); event.stopPropagation(); }
      });
    }
    function applyWorkspaceSize() {
      var height = clamp(+workspacePreferences.canvasHeight || 360, 220, 1200), width = clamp(+workspacePreferences.inspectorWidth || 268, 190, 420);
      section.style.setProperty("--texture-canvas-height", height + "px"); section.style.setProperty("--texture-inspector-width", width + "px");
      if (workspacePreferences.expandedHeight) section.style.setProperty("--texture-editor-height", clamp(+workspacePreferences.expandedHeight, 360, Math.max(360, global.innerHeight - 24)) + "px");
      if (workspace.resizer) workspace.resizer.setAttribute("aria-valuenow", String(Math.round(height)));
      if (workspace.dockResizer) workspace.dockResizer.setAttribute("aria-valuenow", String(Math.round(width)));
    }
    function saveWorkspaceSize() { try { global.localStorage.setItem("elichika.texture.workspace.v2", JSON.stringify(workspacePreferences)); } catch (_) {} }
    function bindWorkspaceResize(handle, direction) {
      var drag = null;
      function resize(value) { if (direction === "height") { if (expanded) workspacePreferences.expandedHeight = clamp(value + (drag ? drag.chrome : section.getBoundingClientRect().height - workspace.frame.getBoundingClientRect().height), 360, Math.max(360, global.innerHeight - 24)); else workspacePreferences.canvasHeight = clamp(value, 220, 1200); } else workspacePreferences.inspectorWidth = clamp(value, 190, 420); applyWorkspaceSize(); }
      listen(handle, "pointerdown", function (event) { event.preventDefault(); event.stopPropagation(); handle.focus({ preventScroll: true }); drag = { id: event.pointerId, start: direction === "height" ? event.clientY : event.clientX, value: direction === "height" ? workspace.frame.getBoundingClientRect().height : workspace.inspector.getBoundingClientRect().width, chrome: section.getBoundingClientRect().height - workspace.frame.getBoundingClientRect().height }; handle.setPointerCapture(event.pointerId); });
      listen(handle, "pointermove", function (event) { if (drag && drag.id === event.pointerId) resize(drag.value + (direction === "height" ? event.clientY - drag.start : drag.start - event.clientX)); });
      ["pointerup", "pointercancel", "lostpointercapture"].forEach(function (name) { listen(handle, name, function () { if (drag) { drag = null; saveWorkspaceSize(); } }); });
      listen(handle, "keydown", function (event) { var delta = event.key === "ArrowDown" || event.key === "ArrowRight" ? 20 : event.key === "ArrowUp" || event.key === "ArrowLeft" ? -20 : 0; if (delta) { event.preventDefault(); resize((direction === "height" ? expanded ? workspace.frame.getBoundingClientRect().height : +workspacePreferences.canvasHeight || 360 : +workspacePreferences.inspectorWidth || 268) + delta); saveWorkspaceSize(); } });
    }
    function setCanvasTool(tool) {
      var choices = activeTab === "paint" ? paintTool : selectTool;
      if (!Array.from(choices.options).some(function (option) { return option.value === tool; })) { if (activeTab !== "paint") setTab("paint"); choices = paintTool; }
      var option = Array.from(choices.options).filter(function (option) { return option.value === tool; })[0]; if (!option || option.disabled) return false;
      choices.value = tool; cancelPreview(); selectCanvasTool(); syncBrush(); refreshToolstrip(); return true;
    }
    function refreshToolstrip() {
      if (!workspace.inspector) return;
      var chosen = activeTab === "paint" ? paintTool.value : selectTool.value, uvAvailable = !!(active && !active.standalone && bindings(active).length), blocked = !active || !active.engine || !canEdit(active) || !!loading || !!pendingRestore;
      selectTool.parentNode.hidden = activeTab === "paint"; paintTool.parentNode.hidden = activeTab !== "paint"; colorLabel.hidden = activeTab !== "paint"; compare.parentNode.hidden = activeTab === "paint";
      workspace.floatingBar.hidden = !floating(active);
      toolButtons.forEach(function (item) { var pressed = item.tool === chosen, disabled = blocked || item.tool.indexOf("select-uv-") === 0 && !uvAvailable; item.node.hidden = item.paintOnly && activeTab !== "paint"; if (item.node.disabled !== disabled) item.node.disabled = disabled; if (item.node.getAttribute("aria-pressed") !== String(pressed)) item.node.setAttribute("aria-pressed", String(pressed)); item.node.classList.toggle("active", pressed); });
      [selectTool, paintTool].forEach(function (select) { Array.from(select.options).forEach(function (option) { if (option.value.indexOf("select-uv-") === 0 && option.disabled !== !uvAvailable) option.disabled = !uvAvailable; }); });
      if (workspace.lastTool !== chosen) {
        workspace.lastTool = chosen;
        var selected = toolButtons.filter(function (item) { return item.tool === chosen; })[0], rail = workspace.rail;
        if (selected && !selected.node.hidden && selected.node.parentNode === rail) {
          if (rail.scrollWidth > rail.clientWidth) { if (selected.node.offsetLeft + selected.node.offsetWidth > rail.scrollLeft + rail.clientWidth) rail.scrollLeft = selected.node.offsetLeft + selected.node.offsetWidth - rail.clientWidth; else if (selected.node.offsetLeft < rail.scrollLeft + 46) rail.scrollLeft = Math.max(0, selected.node.offsetLeft - 46); }
          else if (selected.node.offsetTop + selected.node.offsetHeight > rail.scrollTop + rail.clientHeight) rail.scrollTop = selected.node.offsetTop + selected.node.offsetHeight - rail.clientHeight;
        }
      }
    }
    function getOriginalMaterials(mesh) {
      var r = runtime(), controller = r.materialController;
      return controller && controller.getOriginalMaterials ? controller.getOriginalMaterials(mesh) : mesh.userData && mesh.userData.viewerOriginalMaterials || mesh.material;
    }
    function bindings(entry) {
      var r = runtime(), list = []; if (!r.model) return list;
      if (entry.standalone) return list;
      r.model.traverse(function (mesh) {
        if (!mesh.isMesh || mesh.userData && mesh.userData.viewerHelper) return;
        var original = getOriginalMaterials(mesh), materials = Array.isArray(original) ? original : [original];
        materials.forEach(function (material, index) {
          var texture = material && (genericMaps.get(material) || material.map);
          if (texture && texture.userData && same(texture.userData.viewerTexture, entry.record.texture)) list.push({ mesh: mesh, material: material, materialIndex: index, texture: texture });
        });
      }); return list;
    }
    function liveImage(entry, image) {
      if (!T || !entry || !image || entry.standalone) return;
      var r = runtime(), matches = bindings(entry), template = matches.length ? matches[0].texture : null;
      if (!entry.liveTexture) {
        // Never round-trip texture bytes through a premultiplied canvas.
        entry.liveTexture = new T.DataTexture(image.data, image.width, image.height, T.RGBAFormat, T.UnsignedByteType);
        if (template) {
          ["wrapS", "wrapT", "minFilter", "magFilter", "anisotropy", "flipY", "encoding", "colorSpace", "mapping", "channel", "rotation", "matrixAutoUpdate"].forEach(function (name) { if (template[name] !== undefined) entry.liveTexture[name] = template[name]; });
          ["offset", "repeat", "center", "matrix"].forEach(function (name) { if (entry.liveTexture[name] && template[name]) entry.liveTexture[name].copy(template[name]); });
        } else { entry.liveTexture.flipY = false; if (T.sRGBEncoding !== undefined) entry.liveTexture.encoding = T.sRGBEncoding; }
        entry.liveTexture.unpackAlignment = 1;
        entry.liveTexture.userData = Object.assign({}, entry.liveTexture.userData, { viewerTexture: Object.assign({}, entry.record.texture) });
        entry.liveTexture.mipmaps = []; entry.liveTexture.generateMipmaps = true;
      }
      entry.liveTexture.userData.viewerTexture = Object.assign({}, entry.record.texture);
      entry.liveTexture.image = { data: image.data, width: image.width, height: image.height }; entry.liveTexture.needsUpdate = true;
      matches.forEach(function (binding) {
        if (!genericMaps.has(binding.material)) genericMaps.set(binding.material, binding.material.map);
        binding.material.map = entry.liveTexture; binding.material.needsUpdate = true;
      });
      if (r.materialController && r.materialController.setTextureOverride) r.materialController.setTextureOverride(entry.record.texture, entry.liveTexture);
      performance.textureUploads++; requestRender();
    }
    function restoreLive(entry, keepTexture) {
      if (!entry) return;
      genericMaps.forEach(function (original, material) { if (material.map === entry.liveTexture) { material.map = original; material.needsUpdate = true; genericMaps.delete(material); } });
      var r = runtime(); if (r.materialController && r.materialController.setTextureOverride) r.materialController.setTextureOverride(entry.record.texture, null);
      if (entry.liveTexture && !keepTexture) { entry.liveTexture.dispose(); entry.liveTexture = null; } requestRender();
    }
    function floating(entry) { return entry && entry.engine && entry.engine.getState().floatingSelection || null; }
    function colorImage(entry) { return entry.engine.getActiveImage ? entry.engine.getActiveImage(false) : entry.engine.getImage(false); }
    function layerStamp(entry) { var state = entry.engine.getState(); return [state.activeLayerId || state.activeLayer || "", state.revision, state.projectRevision, state.selectionRevision].join(":"); }
    function replaceImage(entry, image, config) {
      var result = entry.engine.replaceImageData ? entry.engine.replaceImageData(image, config || {}) : entry.engine.applyImageData(image, config || {});
      if (entry === active && compare.checked && entry.engine.setDisplayOverride) entry.engine.setDisplayOverride(entry.original);
      entry.savedProject = null; if (entry.engine.getLayers) entry.initialLayerSignature = JSON.stringify(entry.engine.getLayers()); return result;
    }
    function canRestoreTexture() {
      return !!(active && active.engine && active.original && canEdit(active) && !hasPending());
    }
    function closeTextureRestore() {
      textureRestoreRequest = null; restoreTexturePrompt.hidden = true; restoreTextureButton.setAttribute("aria-expanded", "false");
    }
    function requestTextureRestore() {
      if (!canRestoreTexture()) return;
      textureRestoreRequest = { entry: active, epoch: epoch, stamp: layerStamp(active) };
      restoreTexturePrompt.hidden = false; restoreTextureButton.setAttribute("aria-expanded", "true"); restoreTextureConfirm.focus({ preventScroll: true });
    }
    function confirmTextureRestore() {
      var request = textureRestoreRequest;
      if (!request) return;
      if (request.entry !== active || request.epoch !== epoch || request.stamp !== layerStamp(request.entry)) { closeTextureRestore(); say("The texture changed. Review it before restoring."); return; }
      if (!canRestoreTexture()) return;
      var entry = request.entry, previousKind = entry.kind;
      try {
        entry.kind = activeTab;
        // The engine keeps the complete prior stack as one undoable operation.
        // Never pass history:false or change the loaded original image.
        replaceImage(entry, entry.original, { label: "Restore original texture" });
        cancelPreview(); closeTextureRestore(); say("Original texture restored. Undo restores your edited layers.");
      } catch (err) { entry.kind = previousKind; say("", err.message); }
      refreshButtons();
    }
    function displayed(entry) { return compare.checked && entry.original ? entry.original : entry.engine && (entry.engine.getDisplayImage ? entry.engine.getDisplayImage() : entry.preview || entry.engine.getImage(false)); }
    function upload(entry) {
      if (!entry || !entry.engine || entry.standalone) return;
      if (compare.checked || !entry.modified && !entry.preview && !entry.strokePreview && !floating(entry)) restoreLive(entry);
      else liveImage(entry, displayed(entry));
    }
    function removeOverlays() {
      overlays.forEach(function (row) { if (row.mesh.parent) row.mesh.parent.remove(row.mesh); row.materials.forEach(function (material) { material.dispose(); }); row.textures.forEach(function (texture) { texture.dispose(); }); });
      overlays = []; overlayState = null;
    }
    function syncSelectionDisplay() {
      entries.forEach(function (entry) { if (entry.engine && entry.engine.setSelectionVisible) entry.engine.setSelectionVisible(showSelection.checked); });
      updateOverlay(); updateInformation(); requestRender();
    }
    function hideSelectionForColor() {
      if (!showSelection.checked) return;
      selectionAutoHidden = true; showSelection.checked = false; syncSelectionDisplay();
    }
    function restoreAutomaticSelectionDisplay() {
      if (!selectionAutoHidden) return false;
      selectionAutoHidden = false; showSelection.checked = true; syncSelectionDisplay(); return true;
    }
    function updateOverlay(maskOverride, dirty) {
      if (!active || !active.engine || !T || active.standalone || !section.open || !showSelection.checked) { removeOverlays(); return; }
      var mask = maskOverride || active.modelBrushMask || active.engine.getMask(), image = active.engine.getImage(false);
      if (!mask || !image || !maskOverride && !active.modelBrushMask && !active.engine.getState().selectedPixels) { removeOverlays(); return; }
      var matches = bindings(active), signature = key(active.record.texture) + ":" + image.width + ":" + image.height + ":" + matches.map(function (b) { return b.mesh.uuid + ":" + b.mesh.geometry.uuid + ":" + b.materialIndex + ":" + b.texture.uuid; }).join(";");
      if (!overlayState || overlayState.signature !== signature) {
        removeOverlays();
        var pixels = new Uint8Array(image.width * image.height * 4);
        for (var rgb = 0; rgb < mask.length; rgb++) { pixels[rgb * 4] = 255; pixels[rgb * 4 + 1] = 190; pixels[rgb * 4 + 2] = 32; }
        overlayState = { signature: signature, pixels: pixels, textures: [] }; dirty = null;
        var groups = new Map(); matches.forEach(function (binding) { if (!groups.has(binding.mesh)) groups.set(binding.mesh, []); groups.get(binding.mesh).push(binding); });
        groups.forEach(function (rows, mesh) {
          var originals = getOriginalMaterials(mesh), array = Array.isArray(originals), count = array ? originals.length : 1, materials = [], textures = [];
          for (var slot = 0; slot < count; slot++) {
            var binding = rows.filter(function (r) { return r.materialIndex === slot; })[0], material;
            if (binding) {
              var texture = new T.DataTexture(pixels, image.width, image.height, T.RGBAFormat, T.UnsignedByteType), template = binding.texture;
              ["wrapS", "wrapT", "flipY", "rotation", "matrixAutoUpdate"].forEach(function (name) { if (template[name] !== undefined) texture[name] = template[name]; });
              ["offset", "repeat", "center", "matrix"].forEach(function (name) { if (texture[name] && template[name]) texture[name].copy(template[name]); });
              texture.mipmaps = []; texture.generateMipmaps = false; texture.minFilter = texture.magFilter = T.LinearFilter; texture.unpackAlignment = 1; textures.push(texture); overlayState.textures.push(texture);
              material = new T.MeshBasicMaterial({ map: texture, skinning: !!mesh.isSkinnedMesh, morphTargets: !!mesh.morphTargetInfluences, transparent: true, alphaTest: .005, depthTest: true, depthWrite: false, side: T.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2, toneMapped: false });
            } else { material = new T.MeshBasicMaterial(); material.visible = false; }
            materials.push(material);
          }
          var overlay = mesh.isSkinnedMesh ? new T.SkinnedMesh(mesh.geometry, array ? materials : materials[0]) : new T.Mesh(mesh.geometry, array ? materials : materials[0]);
          overlay.userData.viewerHelper = true; overlay.userData.viewerTextureSelection = true; overlay.name = "Texture selection"; overlay.frustumCulled = false; overlay.renderOrder = 980;
          if (mesh.isSkinnedMesh) { overlay.bindMode = mesh.bindMode; overlay.bind(mesh.skeleton, mesh.bindMatrix); }
          overlay.morphTargetInfluences = mesh.morphTargetInfluences; overlay.morphTargetDictionary = mesh.morphTargetDictionary; mesh.add(overlay);
          overlays.push({ mesh: overlay, original: mesh, materials: materials, textures: textures });
        });
      }
      var left = dirty ? dirty.left : 0, right = dirty ? dirty.right : image.width - 1, top = dirty ? dirty.top : 0, bottom = dirty ? dirty.bottom : image.height - 1;
      for (var y = top; y <= bottom; y++) for (var x = left; x <= right; x++) { var index = y * image.width + x; overlayState.pixels[index * 4 + 3] = Math.round(mask[index] * .55); }
      overlayState.textures.forEach(function (texture) { texture.needsUpdate = true; }); performance.maskOverlays++; requestRender();
    }
    function geometryData(mesh) {
      var geometry = mesh.geometry, cached = geometryCache.get(geometry), position = geometry.attributes.position, uv = geometry.attributes.uv, index = geometry.index;
      if (!position || !uv) return null;
      if (cached && cached.position === position && cached.positionVersion === position.version && cached.uv === uv && cached.uvVersion === uv.version && cached.index === index && cached.version === (index && index.version || 0)) return cached;
      var positions = [], uvs = [], triangles = [], skin = [], indices = geometry.attributes.skinIndex, weights = geometry.attributes.skinWeight;
      for (var vertex = 0; vertex < position.count; vertex++) {
        positions.push([position.getX(vertex), position.getY(vertex), position.getZ(vertex)]); uvs.push([uv.getX(vertex), uv.getY(vertex)]);
        if (indices && weights) { var row = []; for (var channel = 0; channel < 4; channel++) row.push([indices.array[vertex * indices.itemSize + channel], weights.array[vertex * weights.itemSize + channel]]); skin.push(row); }
      }
      var count = index ? index.count : position.count;
      for (var offset = 0; offset + 2 < count; offset += 3) triangles.push(index ? [index.getX(offset), index.getX(offset + 1), index.getX(offset + 2)] : [offset, offset + 1, offset + 2]);
      cached = { positions: positions, uvs: uvs, triangles: triangles, skin: skin, graph: null, position: position, positionVersion: position.version, uv: uv, uvVersion: uv.version, index: index, version: index && index.version || 0 }; geometryCache.set(geometry, cached); return cached;
    }
    function edgeGraph(triangles) {
      var edges = new Map(), graph = triangles.map(function () { return []; });
      triangles.forEach(function (triangle, face) { for (var edge = 0; edge < 3; edge++) { var a = triangle[edge], b = triangle[(edge + 1) % 3], k = Math.min(a, b) + ":" + Math.max(a, b), previous = edges.get(k); if (previous === undefined) edges.set(k, face); else { graph[face].push(previous); graph[previous].push(face); } } }); return graph;
    }
    function faceAllowed(geometry, face, materialIndex) {
      var first = face * 3, range = geometry.drawRange || { start: 0, count: Infinity }, groups = geometry.groups || [];
      return first >= range.start && first + 2 < range.start + range.count && (!groups.length || groups.some(function (g) { return (g.materialIndex || 0) === materialIndex && first >= g.start && first + 2 < g.start + g.count; }));
    }
    function uvSelectionData(entry) {
      var matches = bindings(entry), signature = matches.map(function (binding) {
        var g = binding.mesh.geometry, texture = binding.texture; if (texture.matrixAutoUpdate && texture.updateMatrix) texture.updateMatrix();
        return [binding.mesh.uuid, g.uuid, g.index && g.index.version, g.attributes.uv && g.attributes.uv.version, JSON.stringify(g.drawRange), JSON.stringify(g.groups), binding.materialIndex, texture.matrix && texture.matrix.elements.join(","), texture.wrapS, texture.wrapT, texture.flipY].join("|");
      }).join(";");
      if (entry.uvSelectionData && entry.uvSelectionSignature === signature) return entry.uvSelectionData;
      var polygons = [];
      matches.forEach(function (binding) {
        var data = geometryData(binding.mesh); if (!data) return;
        data.triangles.forEach(function (triangle, face) {
          if (!faceAllowed(binding.mesh.geometry, face, binding.materialIndex)) return;
          triangleCopies(binding.texture, triangle.map(function (vertex) { return data.uvs[vertex]; })).forEach(function (points) { polygons.push({ points: points, meshId: binding.mesh.uuid, group: binding.materialIndex, face: face }); });
        });
      });
      entry.uvSelectionData = { polygons: polygons, index: global.TextureUVSelection.build(polygons) }; entry.uvSelectionSignature = signature;
      return entry.uvSelectionData;
    }
    function selectUVAt(entry, point, tool, mode) {
      if (entry !== active || !canEdit(entry) || loading || pendingRestore) return false;
      if (entry.standalone || !global.TextureUVSelection || !bindings(entry).length) { say("Open a model texture to select UV regions."); return false; }
      var image = entry.engine.getImage(false), data = uvSelectionData(entry), hits = data.index.hit(point.x / image.width, point.y / image.height, tool), mask = new Uint8Array(image.width * image.height), faces = new Set();
      hits.forEach(function (index) { var polygon = data.polygons[index]; rasterTriangle(mask, image.width, image.height, polygon.points); faces.add(polygon.meshId + ":" + polygon.face); });
      cancelPreview(); entry.lastUVSelection = { mode: tool, polygonCount: hits.length, faceCount: faces.size }; entry.engine.selectRegion(mask, mode); return true;
    }
    function drawUV(entry, context, view) {
      if (!showUV.checked || entry !== active || !entry.engine) return;
      var image = entry.engine.getImage(false), matches = bindings(entry); if (!image || !matches.length) return;
      context.save(); context.translate(view.x, view.y); context.scale(view.zoom, view.zoom); context.beginPath(); context.rect(0, 0, image.width, image.height); context.clip();
      context.strokeStyle = global.ViewerUVColor ? global.ViewerUVColor.stroke(.75) : "rgba(230,245,255,.75)"; context.lineWidth = 1 / view.zoom;
      var signature = matches.map(function (binding) {
        var g = binding.mesh.geometry, texture = binding.texture; if (texture.matrixAutoUpdate && texture.updateMatrix) texture.updateMatrix();
        return [g.uuid, g.index && g.index.version, g.attributes.uv && g.attributes.uv.version, JSON.stringify(g.drawRange), binding.materialIndex, texture.matrix && texture.matrix.elements.join(","), texture.wrapS, texture.wrapT, texture.flipY].join("|");
      }).join(";");
      if (entry.uvPath && entry.uvPathSignature === signature) { context.stroke(entry.uvPath); context.restore(); return; }
      var path = global.Path2D ? new global.Path2D() : null, drawing = path || context; if (!path) context.beginPath();
      var seen = new Set();
      matches.forEach(function (binding) {
        var data = geometryData(binding.mesh); if (!data) return;
        data.triangles.forEach(function (triangle, face) {
          if (!faceAllowed(binding.mesh.geometry, face, binding.materialIndex)) return;
          triangleCopies(binding.texture, triangle.map(function (vertex) { return data.uvs[vertex]; })).forEach(function (copy) {
            for (var edge = 0; edge < 3; edge++) {
              var a = copy[edge], b = copy[(edge + 1) % 3], signature = a.join(",") + ":" + b.join(","); if (seen.has(signature)) continue; seen.add(signature);
              drawing.moveTo(a[0] * image.width, a[1] * image.height); drawing.lineTo(b[0] * image.width, b[1] * image.height);
            }
          });
        });
      }); if (path) { entry.uvPath = path; entry.uvPathSignature = signature; context.stroke(path); } else context.stroke(); context.restore();
    }
    function layerChanged(entry) {
      if (!entry || entry.loading || suppressed) return;
      entry.stats = null; entry.featherCache = null; cancelPreview();
      if (entry === active && compare.checked && entry.engine.setDisplayOverride) entry.engine.setDisplayOverride(entry.original);
      if (entry === active) { layerSignature = ""; refreshLayers(); updateTone(); }
      upload(entry); refreshButtons();
    }
    function floatingChanged(entry) {
      if (!entry || entry.loading || suppressed) return;
      entry.strokePreview = !!floating(entry); entry.needsLiveUpdate = true;
      if (entry === active) refreshButtons(); requestRender();
    }
    function flushLiveUpdate() {
      var entry = active; if (!entry || !entry.needsLiveUpdate) return;
      var remaining = 100 - (Date.now() - (entry.lastLiveUpdate || 0));
      if (remaining <= 0) { if (entry.liveTimer) global.clearTimeout(entry.liveTimer); entry.liveTimer = null; entry.lastLiveUpdate = Date.now(); entry.needsLiveUpdate = false; upload(entry); }
      else if (!entry.liveTimer) {
        var born = epoch;
        entry.liveTimer = global.setTimeout(function () { entry.liveTimer = null; if (!disposed && born === epoch && entry === active && entry.needsLiveUpdate) requestRender(); }, remaining + 1);
      }
    }
    function refreshLayers() {
      var engine = active && active.engine, rows = engine && engine.getLayers ? engine.getLayers() : [], state = engine && engine.getState(), current = state && (state.activeLayerId || state.activeLayer), blocked = !engine || !canEdit(active) || !!loading || !!pendingRestore || !!floating(active);
      var signature = JSON.stringify([current, blocked, rows]);
      if (signature !== layerSignature) {
        layerSignature = signature; layerList.textContent = "";
        rows.slice().reverse().forEach(function (row) {
          var item = node("div", layerList, null, "viewer-texture-layer-row"), visible = node("input", item), choose = node("button", item), percent = node("span", item);
          item.setAttribute("role", "listitem"); item.dataset.layerId = row.id; item.classList.toggle("active", row.id === current);
          visible.type = "checkbox"; visible.checked = row.visible !== false; visible.disabled = blocked; visible.setAttribute("aria-label", t("Show layer") + ": " + row.name);
          visible.onchange = function () { layerOperation(function () { return engine.setLayerVisible(row.id, visible.checked); }); };
          choose.type = "button"; choose.textContent = row.name; choose.setAttribute("aria-pressed", String(row.id === current)); choose.disabled = !!loading || !!floating(active);
          choose.onclick = function () { if (!floating(active)) { cancelPreview(); engine.selectLayer(row.id); refreshLayers(); } };
          percent.textContent = Math.round(row.opacity * 100) + "%";
        });
      }
      var selected = rows.filter(function (row) { return row.id === current; })[0], index = rows.indexOf(selected);
      layerName.disabled = layerOpacity.disabled = blocked || !selected;
      if (selected) {
        if (document.activeElement !== layerName) layerName.value = selected.name;
        if (document.activeElement !== layerOpacity) layerOpacity.value = Math.round(selected.opacity * 100);
        layerOpacityValue.textContent = Math.round(selected.opacity * 100) + "%";
      } else { layerName.value = ""; layerOpacityValue.textContent = ""; }
      Object.keys(layerButtons).forEach(function (name) { layerButtons[name].disabled = blocked || !selected || name === "add" && rows.length >= 8 || name === "remove" && rows.length <= 1 || name === "up" && index >= rows.length - 1 || (name === "down" || name === "merge") && index <= 0; });
      var pendingFloat = floating(active);
      clipboardButtons.copy.disabled = !engine || !!loading || !!pendingFloat;
      ["cut", "move"].forEach(function (name) { clipboardButtons[name].disabled = blocked || !state || state.selectionActive && !state.selectedPixels; });
      clipboardButtons.paste.disabled = blocked || !state || state.clipboardAvailable === false;
      clipboardButtons.commit.disabled = clipboardButtons.cancel.disabled = !engine || !pendingFloat || !canEdit(active);
      floatingHint.textContent = pendingFloat ? t("Apply or cancel moved pixels first.") + " (" + Math.round(pendingFloat.x) + ", " + Math.round(pendingFloat.y) + ")" : "";
      projectOpenButton.disabled = !!loading || !!pendingRestore || !!pendingFloat || !!active && !canEdit(active);
      projectSaveButton.disabled = !engine || !!loading || !!pendingRestore || !!pendingFloat || !!(active && active.preview) || !!previewTimer || !!previewJobs;
      exportButton.disabled = projectSaveButton.disabled;
    }
    function layerOperation(operation) {
      if (!active || !active.engine || !canEdit(active) || loading || pendingRestore || floating(active)) return false;
      cancelPreview();
      try { var result = operation(); layerSignature = ""; refreshLayers(); refreshButtons(); return result; }
      catch (err) { say("", err.message); refreshLayers(); return false; }
    }
    function changeLayer(action) {
      return layerOperation(function () {
        var engine = active.engine, state = engine.getState(), id = state.activeLayerId || state.activeLayer, rows = engine.getLayers(), index = rows.findIndex(function (row) { return row.id === id; });
        if (action === "add" || action === "duplicate") ensureLayerBudget(state.width * state.height * 4);
        if (action === "add") return engine.addLayer({ name: t("Layer") + " " + (rows.length + 1) });
        if (action === "duplicate") return engine.duplicateLayer(id);
        if (action === "remove") return engine.removeLayer(id);
        if (action === "up" || action === "down") return engine.moveLayer(id, index + (action === "up" ? 1 : -1));
        if (action === "merge") return engine.mergeLayerDown(id);
        return false;
      });
    }
    function layerBufferBytes(except) {
      var buffers = new Set(), bytes = 0;
      entries.forEach(function (entry) {
        if (entry === except) return;
        var project = entry.engine && entry.engine.getProject ? entry.engine.getProject(false) : entry.savedProject;
        if (project) project.layers.forEach(function (layer) { if (!buffers.has(layer.image.data)) { buffers.add(layer.image.data); bytes += layer.image.data.byteLength; } });
      }); return bytes;
    }
    function ensureLayerBudget(extra, except) {
      var limit = 128 * 1024 * 1024;
      if (layerBufferBytes(except) + extra > limit) evict(true);
      if (layerBufferBytes(except) + extra > limit) throw new Error(t("Layer memory is full. Save layer projects before opening another model."));
    }
    function clipboardAction(method) {
      if (!active || !active.engine || loading || pendingRestore || method !== "copySelection" && !canEdit(active)) return false;
      if (floating(active) && method !== "commitFloating" && method !== "cancelFloating") { say("Apply or cancel moved pixels first."); return false; }
      cancelPreview();
      try {
        var result = active.engine[method]();
        if (floating(active)) { paintTool.value = "move"; selectCanvasTool(); }
        active.strokePreview = !!floating(active); upload(active); refreshButtons();
        if (active.canvas) active.canvas.focus(); return result;
      } catch (err) { say("", err.message); refreshButtons(); return false; }
    }
    function touchEntry(entry) {
      if (!entry || !entry.engine || suppressed || entry.loading) return;
      entry.preview = null; entry.previewMask = null; entry.strokePreview = false; sequence++; entry.encodeGeneration = (entry.encodeGeneration || 0) + 1;
      entry.modified = !equalPixels(entry.engine.getImage(false), entry.original); entry.kind = entry.nextKind || activeTab; entry.nextKind = null; entry.used = Date.now(); entry.encodeError = null;
      var generation = entry.encodeGeneration, born = epoch;
      upload(entry); changed();
      if (!entry.modified || entry.standalone) { entry.encoding = false; if (!entry.modified) entry.png = null; if (entry.standalone) say("Image changes ready. Use Export PNG to save."); return; }
      entry.encoding = true; refreshButtons(); say("Preparing exact texture pixels…");
      encode(entry.engine.getImage()).then(function (png) {
        if (disposed || born !== epoch || generation !== entry.encodeGeneration) return;
        entry.png = png; entry.encoding = false; evict(); say("Texture edits ready. Save model edits or a Mod ZIP to export."); changed();
      }).catch(function (err) { if (born === epoch && generation === entry.encodeGeneration) { entry.encoding = false; entry.encodeError = err.message; say("", err.message); changed(); } });
    }
    function selectionChanged(entry) {
      if (!entry || entry.loading || suppressed) return;
      cancelPreview(); entry.userSelected = true; entry.stats = null; entry.featherCache = null; if (!restoreAutomaticSelectionDisplay()) updateOverlay(); updateInformation(); updateTone(); refreshButtons();
    }
    function canClearSelection() {
      return !!(active && active.engine && !loading && !pointer && !brushStroke && canEdit(active) &&
        (active.hasSelection || active.hasFloatingSelection));
    }
    function clearSelection() {
      if (!canClearSelection()) return false;
      cancelPreview();
      if (active.hasFloatingSelection && active.engine.cancelFloating) active.engine.cancelFloating();
      active.seeds = []; active.exclusions = []; active.lastModelSelection = null; active.lastUVSelection = null;
      active.engine.clearSelection();
      updateOverlay(); refreshButtons(); return true;
    }
    function makeEngine(entry, image) {
      var pane = node("div", canvasHost, null, "viewer-texture-canvas-pane"), canvas = node("canvas", pane); canvas.tabIndex = 0; canvas.setAttribute("aria-label", t("Texture"));
      entry.pane = pane; entry.canvas = canvas;
      entry.engine = global.TexturePaintEngine.create({ canvas: canvas, maxHistoryBytes: 64 * 1024 * 1024, maxHistoryEntries: 40,
        onChange: function () { touchEntry(entry); }, onSelectionChange: function (event) { entry.hasSelection = !!(event.state.selectionActive && event.state.selectedPixels); selectionChanged(entry); }, onHistoryChange: refreshButtons,
        onLayerChange: function () { layerChanged(entry); }, onFloatingChange: function (event) { entry.hasFloatingSelection = !!event.state.floatingSelection; floatingChanged(entry); },
        onSelectUV: function (point, tool, mode) { return selectUVAt(entry, point, tool, mode); },
        onPick: function (rgba, point) { if (activeTab === "skin" && (sceneMode === "skin" || sceneMode === "exclude")) seed(entry, point, sceneMode === "exclude"); else { paintColor.value = hex(rgba); paintAlpha.value = Math.round(rgba[3] / 255 * 100); syncBrush(); } },
        onViewChange: updateInformation, onError: function (err) { say("", err.message || String(err)); }, drawOverlay: function (context, view) { drawUV(entry, context, view); } });
      entry.events = [];
      function protect(event) {
        if (entry.engine && entry.engine.setReadOnly) entry.engine.setReadOnly(!canEdit(entry));
        if (event.type === "pointerdown" && canEdit(entry) && entry.engine.getState().tool.indexOf("select-") === 0) restoreAutomaticSelectionDisplay();
      }
      ["pointerdown", "keydown"].forEach(function (name) { canvas.addEventListener(name, protect, true); entry.events.push(function () { canvas.removeEventListener(name, protect, true); }); });
      function liveStroke(event) {
        if (entry !== active || entry.standalone || activeTab !== "paint" || !entry.engine || !canEdit(entry)) return;
        var tool = entry.engine.getState().tool; if (["brush", "eraser", "fill", "line", "rectangle", "ellipse", "move"].indexOf(tool) < 0) return;
        if (event.type === "pointermove" && !event.buttons) return;
        entry.strokePreview = event.type === "pointerdown" || event.type === "pointermove";
        entry.needsLiveUpdate = true; requestRender();
      }
      ["pointerdown", "pointermove", "pointerup", "pointercancel"].forEach(function (name) { canvas.addEventListener(name, liveStroke); entry.events.push(function () { canvas.removeEventListener(name, liveStroke); }); });
      entry.hasSelection = false; entry.hasFloatingSelection = false;
      entry.engine.setImage(image); entry.engine.selectNone();
      entry.initialLayerSignature = entry.engine.getLayers ? JSON.stringify(entry.engine.getLayers()) : "";
      if (entry.engine.setSelectionVisible) entry.engine.setSelectionVisible(showSelection.checked); entry.pane.hidden = entry !== active; return entry.engine;
    }
    function destroyEngine(entry) { if (entry.liveTimer) global.clearTimeout(entry.liveTimer); entry.liveTimer = null; (entry.events || []).forEach(function (remove) { remove(); }); entry.events = []; if (entry.engine) entry.engine.destroy(); entry.engine = null; if (entry.pane) entry.pane.remove(); entry.pane = null; entry.canvas = null; }
    function entryBytes(entry) {
      var state = entry.engine && entry.engine.getState(), image = entry.engine && entry.engine.getImage(false), arrays = new Set(), total = 0;
      var project = entry.engine && entry.engine.getProject ? entry.engine.getProject(false) : entry.savedProject;
      var buffers = [entry.original && entry.original.data, image && image.data, entry.preview && entry.preview.data, entry.savedMask, entry.liveTexture && entry.liveTexture.image && entry.liveTexture.image.data, entry.modelBrushMask];
      if (project) project.layers.forEach(function (layer) { buffers.push(layer.image.data); });
      buffers.forEach(function (array) { if (array && !arrays.has(array)) { arrays.add(array); total += array.byteLength; } });
      return total + (state ? state.historyBytes + (state.selectionActive ? state.width * state.height : 0) : 0);
    }
    function evict(force) {
      if (pendingRestore || restoringDocuments) return;
      var loaded = Array.from(entries.values()).filter(function (e) { return e.engine && e !== active && !e.standalone && !e.encoding && !e.loading; }).sort(function (a, b) { return a.used - b.used; });
      var bytes = Array.from(entries.values()).reduce(function (total, entry) { return total + entryBytes(entry); }, 0), budget = 192 * 1024 * 1024;
      // An active maximum-size document can exceed this budget on its own. Keep
      // it usable, and release all inactive engines before retaining more data.
      while (loaded.length && (force || loaded.length > 2 || bytes > budget)) {
        var entry = loaded.shift(); if (entry.modified && !entry.png) continue;
        var before = entryBytes(entry); entry.savedMask = entry.engine.getMask(); entry.savedView = entry.engine.getView();
        if (entry.engine.getProject && JSON.stringify(entry.engine.getLayers()) !== entry.initialLayerSignature) entry.savedProject = entry.engine.getProject(false);
        destroyEngine(entry); entry.original = null; entry.preview = null;
        bytes -= before - entryBytes(entry);
      }
    }
    function load(record) {
      var id = key(record.texture), entry = entries.get(id), born = epoch;
      if (!entry) { entry = { record: record, loading: false, encoding: false, modified: false, kind: "paint", png: null, sourceSha256: "", seeds: [], exclusions: [], used: Date.now() }; entries.set(id, entry); }
      if (entry.engine) return Promise.resolve(entry);
      if (entry.promise) return entry.promise;
      entry.loading = true; loading++; say("Loading texture…"); refreshButtons();
      entry.promise = api("/api/viewer/texture/data", { token: currentToken, texture: record.texture }).then(function (data) {
        if (disposed || born !== epoch) throw abort();
        entry.sourceSha256 = data.sourceSha256; var image = exact(data); entry.original = copyImage(image); makeEngine(entry, image);
        if (entry.savedProject && entry.engine.restoreProject) { suppressed++; try { entry.engine.restoreProject(entry.savedProject, { history: false }); entry.savedProject = null; } finally { suppressed--; } return; }
        if (entry.png) return decodePatch(entry, entry.png).then(function (restored) { if (born !== epoch) throw abort(); suppressed++; try { replaceImage(entry, restored, { label: "Restore texture", history: false }); } finally { suppressed--; } });
      }).then(function () {
        if (born !== epoch) throw abort();
        if (entry.savedMask) { suppressed++; entry.engine.setMask(entry.savedMask); suppressed--; entry.savedMask = null; }
        entry.loading = false; entry.promise = null; entry.used = Date.now(); if (entry === active) { entry.pane.hidden = false; syncBrush(); selectCanvasTool(); if (entry.savedView) { entry.engine.setView(entry.savedView); entry.savedView = null; } else entry.engine.fit(); upload(entry); updateOverlay(); }
        evict(); return entry;
      }).catch(function (err) { entry.loading = false; entry.promise = null; if (err.name !== "AbortError" && born === epoch) say("", err.message); throw err; }).finally(function () { if (born === epoch) loading = Math.max(0, loading - 1); refreshButtons(); });
      return entry.promise;
    }
    function abort() { var err = new Error("Texture request was replaced."); err.name = "AbortError"; return err; }
    function selectTexture(identity) {
      if (floating(active) && !same(active.record.texture, identity)) { textureSelect.value = key(active.record.texture); say("Apply or cancel moved pixels first."); return Promise.reject(new Error(t("Apply or cancel moved pixels first."))); }
      var record = catalogue.filter(function (r) { return same(r.texture, identity); })[0]; if (!record || record.available === false) return Promise.reject(new Error(record && record.reason || "Choose an editable texture."));
      cancelPreview(); if (compare.checked && active && active.engine) { compare.checked = false; if (active.engine.setDisplayOverride) active.engine.setDisplayOverride(null); else active.engine.setPreviewImage(active.preview); upload(active); }
      if (active && active.pane) active.pane.hidden = true;
      active = entries.get(key(identity)) || { record: record, loading: false, encoding: false, modified: false, kind: "paint", png: null, sourceSha256: "", seeds: [], exclusions: [], used: Date.now() };
      entries.set(key(identity), active); textureSelect.value = key(identity); removeOverlays(); var selected = active;
      return load(record).then(function (entry) { if (entry !== active) { if (entry.pane) entry.pane.hidden = true; return entry; } entry.pane.hidden = false; say("Choose faces or a texture region before applying color."); updateInformation(); updateTone(); refreshButtons(); return entry; });
    }
    function syncBrush() {
      if (sceneMode === "brush") modelCursor.hidden = true;
      if (!active || !active.engine) return;
      var rgb = [1, 3, 5].map(function (start) { return parseInt(paintColor.value.slice(start, start + 2), 16); }); rgb.push(Math.round(clamp(+paintAlpha.value || 0, 0, 100) * 2.55));
      active.engine.setBrush({ size: brushSize.value(), opacity: opacity.value() / 100, softness: softness.value() / 100, color: rgb, tolerance: Math.round(tolerance.value() * 255), contiguous: connected.checked, fill: filled.checked });
      active.engine.setSelectionMode(selectionMode.value);
    }
    function selectCanvasTool() { if (active && active.engine) active.engine.setTool(activeTab === "paint" ? paintTool.value : (sceneMode === "skin" || sceneMode === "exclude") && activeTab === "skin" ? "picker" : selectTool.value); refreshToolstrip(); }
    function setTab(tab) {
      if (["costume", "skin", "paint"].indexOf(tab) < 0) return;
      if (floating(active) && tab !== activeTab) { say("Apply or cancel moved pixels first."); return; }
      cancelPreview(); activeTab = tab; colorPanel.hidden = tab !== "costume"; skinPanel.hidden = tab !== "skin"; paintPanel.hidden = tab !== "paint"; applyButton.hidden = tab === "paint"; cancelButton.hidden = tab === "paint";
      targetLabel.hidden = tab !== "costume" || colorMode.value !== "colorize";
      Object.keys(tabButtons).forEach(function (name) { tabButtons[name].setAttribute("aria-selected", String(name === tab)); tabButtons[name].classList.toggle("active", name === tab); });
      if (active && active.engine && !active.userSelected) { suppressed++; if (tab === "paint") active.engine.clearSelection(); else active.engine.selectNone(); suppressed--; updateOverlay(); }
      selectCanvasTool(); syncBrush(); updateInformation(); refreshButtons();
    }
    function setSceneMode(mode) {
      if (["orbit", "brush", "face", "connected", "skin", "exclude"].indexOf(mode) < 0) return sceneMode;
      if (brushStroke) cancelModelBrush();
      sceneMode = mode; sceneSelect.value = mode; modelCursor.hidden = true;
      if (options.onSceneModeChange) options.onSceneModeChange(mode);
      selectCanvasTool(); requestRender(); return mode;
    }
    function meanLightness(entry) {
      var state = entry.engine.getState(), signature = layerStamp(entry);
      if (entry.stats && entry.stats.signature === signature) return entry.stats.lightness;
      var image = colorImage(entry), mask = entry.engine.getMask(), sum = [0, 0, 0], total = 0;
      for (var index = 0; index < image.width * image.height; index++) {
        var weight = (mask ? mask[index] / 255 : 1) * image.data[index * 4 + 3] / 255; if (!weight) continue;
        total += weight; for (var channel = 0; channel < 3; channel++) sum[channel] += image.data[index * 4 + channel] * weight;
      }
      var value = total ? math.rgbToOklch(sum.map(function (n) { return n / total; }))[0] : .5; entry.stats = { signature: signature, lightness: value }; return value;
    }
    function adjustment(entry) {
      if (activeTab === "skin") return { source: sourceTone.value, target: targetTone.value, strength: skinStrength.value() / 100, fine: { lightness: skinL.value() / 100, chroma: skinC.value() / 100, hue: skinH.value() } };
      var value = { mode: colorMode.value, lightness: colorL.value() / 100, chroma: colorC.value() / 100, hue: colorH.value(), strength: colorStrength.value() / 100 };
      if (value.mode === "colorize") {
        value.color = targetColor.value; value.preserveLightness = true;
        var rgb = [1, 3, 5].map(function (start) { return parseInt(targetColor.value.slice(start, start + 2), 16); });
        value.lightness = clamp(value.lightness + math.rgbToOklch(rgb)[0] - meanLightness(entry), -1, 1);
      }
      return value;
    }
    function validSelection(entry) { var state = entry && entry.engine && entry.engine.getState(); return !!(state && state.selectionActive && state.selectedPixels); }
    function incompleteAdjustment() {
      var fields = activeTab === "skin" ? [skinL, skinC, skinH, skinStrength, feather] : activeTab === "costume" ? [colorL, colorC, colorH, colorStrength] : [];
      for (var i = 0; i < fields.length; i++) { var field = fields[i].field; if (!field.value.trim() || field.validity && field.validity.badInput || !isFinite(Number(field.value))) return field; }
      return null;
    }
    function schedulePreview() {
      if (!canEdit(active)) return;
      if (previewTimer) global.clearTimeout(previewTimer); sequence++;
      if (activeTab === "paint") return;
      if (incompleteAdjustment()) { previewTimer = null; refreshButtons(); return; }
      if (validSelection(active)) hideSelectionForColor();
      previewTimer = global.setTimeout(function () { previewTimer = null; preparePreview(true); }, 100); refreshButtons();
    }
    function preparePreview(keepSelectionDisplay) {
      if (!canEdit(active)) return Promise.resolve(false);
      if (previewTimer) global.clearTimeout(previewTimer); previewTimer = null;
      if (loading || pendingRestore || floating(active)) return Promise.resolve(false);
      if (incompleteAdjustment()) return Promise.resolve(false);
      var entry = active; if (!entry || !entry.engine || !validSelection(entry)) { say(activeTab === "skin" ? "Skin changes require an explicit selection." : "Choose faces or a texture region before applying color."); refreshButtons(); return Promise.resolve(false); }
      if (!keepSelectionDisplay) hideSelectionForColor();
      var born = epoch, serial = ++sequence, tab = activeTab, stamp = layerStamp(entry), image = colorImage(entry), mask = entry.engine.getMask(), optionsValue = adjustment(entry);
      if (tab === "skin" && feather.value()) {
        var signature = entry.engine.getState().selectionRevision + ":" + feather.value();
        if (!entry.featherCache || entry.featherCache.signature !== signature) entry.featherCache = { signature: signature, mask: math.featherMask(mask, image.width, image.height, feather.value()) };
        mask = entry.featherCache.mask;
      }
      previewJobs++; performance.previewsStarted++; say("Preparing color preview…"); refreshButtons();
      var promise = processor ? processor.process(tab === "skin" ? "skin" : "adjust", image.data, image.width, image.height, mask, optionsValue) : Promise.resolve().then(function () { return (tab === "skin" ? math.skinRGBA : math.adjustRGBA)(image.data, image.width, image.height, mask, optionsValue); });
      return promise.then(function (rgba) {
        if (disposed || born !== epoch || serial !== sequence || entry !== active || tab !== activeTab || stamp !== layerStamp(entry) || floating(entry)) { performance.previewsDiscarded++; return false; }
        entry.preview = { width: image.width, height: image.height, data: rgba }; entry.previewKind = tab; entry.previewStamp = stamp; entry.engine.setPreviewImage(entry.preview); upload(entry); say("Preview ready. Apply to keep this change."); return true;
      }).catch(function (err) {
        if (err.name !== "AbortError" && born === epoch && serial === sequence) { entry.preview = null; entry.engine.setPreviewImage(null); upload(entry); say("", err.message); }
        return false;
      }).finally(function () { if (born === epoch) previewJobs = Math.max(0, previewJobs - 1); refreshButtons(); });
    }
    function cancelPreview() {
      sequence++; if (previewTimer) global.clearTimeout(previewTimer); previewTimer = null;
      entries.forEach(function (entry) { entry.previewStamp = null; if (entry.preview) { entry.preview = null; if (entry.engine) entry.engine.setPreviewImage(null); upload(entry); } }); refreshButtons();
    }
    function applyPreview() {
      if (!active || !active.engine || !canEdit(active) || floating(active)) return Promise.resolve(false);
      var incomplete = incompleteAdjustment();
      if (incomplete) { say("Complete the number before applying color."); incomplete.focus(); if (incomplete.reportValidity) incomplete.reportValidity(); return Promise.resolve(false); }
      var entry = active;
      if (previewTimer || previewJobs) { if (previewTimer) global.clearTimeout(previewTimer); previewTimer = null; entry.preview = null; entry.engine.setPreviewImage(null); return preparePreview().then(function (ready) { return ready && applyPreview(); }); }
      if (!entry.preview) return preparePreview().then(function (ready) { return ready && applyPreview(); });
      if (entry.previewStamp && entry.previewStamp !== layerStamp(entry)) { cancelPreview(); return Promise.resolve(false); }
      sequence++; if (previewTimer) global.clearTimeout(previewTimer); previewTimer = null;
      var image = entry.preview; entry.preview = null; entry.nextKind = entry.previewKind || activeTab; entry.engine.setPreviewImage(null);
      try { entry.engine.applyImageData(image, { label: activeTab === "skin" ? "Skin tone" : "OKLCH color" }); }
      catch (err) { entry.nextKind = null; entry.preview = image; entry.engine.setPreviewImage(image); upload(entry); say("", err.message); refreshButtons(); return Promise.resolve(false); }
      entry.nextKind = null; colorL.set(0); colorC.set(100); colorH.set(0); skinL.set(0); skinC.set(100); skinH.set(0);
      // An identity adjustment produces no engine change event; still release
      // its pending preview and restore the ordinary material/save state.
      upload(entry); refreshButtons(); return Promise.resolve(true);
    }
    function seed(entry, point, exclude) {
      if (!entry || !entry.engine || !canEdit(entry)) return Promise.resolve(false);
      cancelPreview(); var image = colorImage(entry), seedPoint = [clamp(Math.floor(point.x), 0, image.width - 1), clamp(Math.floor(point.y), 0, image.height - 1)];
      (exclude ? entry.exclusions : entry.seeds).push(seedPoint); return growSelection(entry);
    }
    function growSelection(entry) {
      if (!canEdit(entry)) return Promise.resolve(false);
      if (!entry.seeds.length || !entry.engine) return Promise.resolve(false);
      var born = epoch, serial = ++sequence, stamp = layerStamp(entry), image = colorImage(entry), gate = sampleGate.checked ? entry.engine.getMask() : null;
      var opts = { seeds: entry.seeds.slice(), tolerance: tolerance.value(), connected: connected.checked, excludeSeeds: entry.exclusions.slice() };
      previewJobs++; refreshButtons(); var promise = processor ? processor.process("grow", image.data, image.width, image.height, gate, opts) : Promise.resolve(math.growMask(image.data, image.width, image.height, opts.seeds, Object.assign({}, opts, { gate: gate })));
      return promise.then(function (mask) { if (disposed || born !== epoch || serial !== sequence || entry !== active || stamp !== layerStamp(entry) || floating(entry)) return false; entry.engine.setMask(mask); return true; }).catch(function (err) { if (err.name !== "AbortError" && born === epoch) say("", err.message); return false; }).finally(function () { if (born === epoch) previewJobs = Math.max(0, previewJobs - 1); refreshButtons(); });
    }
    function updateTone() {
      if (!active || !active.engine || !validSelection(active)) { toneEstimate.textContent = t("Skin changes require an explicit selection."); return; }
      try { var image = colorImage(active), result = math.analyzeToneFromMask(image.data, image.width, image.height, active.engine.getMask()); toneEstimate.textContent = t("Estimated source") + ": " + result.tone + " · " + Math.round(result.confidence * 100) + "%"; } catch (err) { toneEstimate.textContent = t(err.message); }
    }
    function updateInformation() {
      var faceToggle = document.getElementById("viewer-mod-include-face");
      faceNote.hidden = !(active && active.record.automaticFace && faceToggle && !faceToggle.checked);
      if (!active || !active.engine) { information.textContent = ""; return; }
      var state = active.engine.getState(); information.textContent = state.width + " × " + state.height + " · " + t("Selected pixels") + ": " + (state.selectionActive ? state.selectedPixels.toLocaleString() : state.width * state.height) + " · " + t("Zoom") + ": " + (Math.round(state.view.zoom * 1000) / 10) + "% · " + t("Saved changes") + ": " + getEdits().length + (selectionAutoHidden && state.selectionActive ? " · " + t("Selection kept; tint hidden.") : "");
    }
    function hasPending() { return !!(loading || pendingRestore || restoringDocuments || previewTimer || previewJobs || brushStroke || Array.from(entries.values()).some(function (e) { return e.encoding || e.encodeError || e.preview || floating(e); })); }
    function refreshButtons() {
      if (disposed) return;
      restoreTextureButton.disabled = restoreTextureConfirm.disabled = !canRestoreTexture();
      if (textureRestoreRequest && (textureRestoreRequest.entry !== active || textureRestoreRequest.epoch !== epoch || textureRestoreRequest.stamp !== layerStamp(textureRestoreRequest.entry))) closeTextureRestore();
      var state = active && active.engine && active.engine.getState(); undoButton.disabled = !state || !state.undoCount || !!loading || !canEdit(active); redoButton.disabled = !state || !state.redoCount || !!loading || !canEdit(active);
      applyButton.disabled = !state || !canEdit(active) || !validSelection(active) || !!incompleteAdjustment() || !!loading || !!previewTimer || !!previewJobs || !!(active && active.encoding) || !!brushStroke || !!floating(active); cancelButton.disabled = !previewTimer && !(active && active.preview) && !previewJobs;
      labels.forEach(function (pair) { if (pair[0] === applyButton) pair[0].textContent = t(activeTab === "skin" ? "Apply skin tone" : "Apply color"); });
      var blocked = !!active && !canEdit(active); lastEditable = !blocked; readonlyNote.hidden = !(active && !active.standalone && options.isReadOnly && options.isReadOnly());
      [colorL, colorC, colorH, colorStrength, skinL, skinC, skinH, skinStrength, tolerance, feather].forEach(function (control) { control.field.disabled = control.range.disabled = blocked; });
      [colorMode, targetColor, sourceTone, targetTone].forEach(function (control) { control.disabled = blocked; });
      textureSelect.disabled = !catalogue.length || !!loading || !!floating(active); section.classList.toggle("viewer-texture-busy", !!loading || !!previewJobs); updateInformation(); refreshLayers();
      entries.forEach(function (entry) { if (entry.engine && entry.engine.setReadOnly) entry.engine.setReadOnly(!canEdit(entry)); if (entry.canvas) { entry.canvas.style.pointerEvents = loading || pendingRestore ? "none" : ""; entry.canvas.setAttribute("aria-disabled", String(!!loading || !!pendingRestore)); } });
      var pending = hasPending();
      refreshToolstrip();
      if (pending !== notifiedPending) { notifiedPending = pending; if (options.onPendingChange) options.onPendingChange(pending); else if (options.onChange) options.onChange(); }
      if (options.onSelectionChange) options.onSelectionChange(canClearSelection());
    }
    function getEdits() {
      if (pendingRestore) return pendingRestore.map(function (row) { return Object.assign({}, row, { texture: Object.assign({}, row.texture) }); });
      return Array.from(entries.values()).filter(function (entry) { return !entry.standalone && entry.modified && entry.png; }).map(function (entry) { return { texture: Object.assign({}, entry.record.texture), sourceSha256: entry.sourceSha256, png: entry.png, kind: entry.kind }; });
    }
    function applyImported(entry, image, born) {
      if (born !== epoch || entry !== active || !canEdit(entry) || floating(entry)) return false;
      if (image.width !== entry.original.width || image.height !== entry.original.height) throw new Error(t("Texture dimensions must match the original."));
      entry.nextKind = "paint";
      try { replaceImage(entry, image, { label: "Import PNG" }); } finally { entry.nextKind = null; }
      upload(entry); refreshButtons(); return true;
    }
    function finishPickerStack() { if (pickerStackCleanup) { var cleanup = pickerStackCleanup; pickerStackCleanup = null; cleanup(); } }
    function elevatePicker() {
      finishPickerStack();
      var picker = document.getElementById("picker"), platform = global.ElichikaPlatform;
      if (!picker || platform && platform.supports && platform.supports("openFiles")) return;
      var value = picker.style.getPropertyValue("z-index"), priority = picker.style.getPropertyPriority("z-index"), opened = false, observer = null;
      pickerStackCleanup = function () { if (observer) observer.disconnect(); if (value) picker.style.setProperty("z-index", value, priority); else picker.style.removeProperty("z-index"); };
      function update() {
        var visible = !picker.hidden && !picker.classList.contains("hidden");
        if (visible) { opened = true; picker.style.setProperty("z-index", "1301"); }
        else if (opened) finishPickerStack();
      }
      if (global.MutationObserver) { observer = new global.MutationObserver(update); observer.observe(picker, { attributes: true, attributeFilter: ["class", "hidden"] }); }
      update();
    }
    function choosePNG() {
      if (floating(active)) { say("Apply or cancel moved pixels first."); return; }
      if (loading || pendingRestore || active && !canEdit(active)) return;
      if (typeof options.pickPNG !== "function") { fileInput.click(); return; }
      elevatePicker();
      try {
        var picked = options.pickPNG(function (path) { finishPickerStack(); if (path) importPNGPath(path).catch(function (err) { if (err.name !== "AbortError") say("", err.message); }); });
        if (picked && typeof picked.finally === "function") picked.finally(finishPickerStack).catch(function (err) { say("", err.message); });
        else if (picked && typeof picked.catch === "function") picked.catch(function (err) { finishPickerStack(); say("", err.message); });
      } catch (err) { finishPickerStack(); say("", err.message); }
    }
    function importPNGPath(path) {
      if (typeof path !== "string" || !path.trim() || loading || pendingRestore || floating(active) || active && !canEdit(active)) return Promise.resolve(false);
      var entry = active && !active.standalone ? active : null, born = epoch;
      cancelPreview(); loading++; say("Opening PNG…"); refreshButtons();
      return api("/api/texture/editor/open", { path: path }).then(function (response) {
        if (born !== epoch) return false;
        if (!entry) return openImage(response, response.name || path.split(/[\\/]/).pop());
        return applyImported(entry, exact(response), born);
      }).finally(function () { if (born === epoch) loading = Math.max(0, loading - 1); refreshButtons(); });
    }
    function importPNG(file) {
      if (!file || loading || pendingRestore || floating(active) || active && !canEdit(active)) return Promise.resolve(false);
      if (file.size > 8 * 1024 * 1024 || file.type && file.type !== "image/png") return Promise.reject(new Error("Choose a PNG smaller than 8 MiB."));
      var entry = active && !active.standalone ? active : null, born = epoch; cancelPreview(); loading++; refreshButtons();
      return file.arrayBuffer().then(function (buffer) {
        var bytes = new Uint8Array(buffer), text = ""; for (var offset = 0; offset < bytes.length; offset += 32768) text += String.fromCharCode.apply(null, bytes.subarray(offset, offset + 32768));
        var png = "data:image/png;base64," + global.btoa(text);
        return entry ? decodePatch(entry, png).then(function (image) { return { image: image }; }) : api("/api/texture/editor/decode", { png: png }).then(function (response) { return { response: response }; });
      }).then(function (result) {
        if (born !== epoch) return false;
        if (!entry) return openImage(result.response, file.name);
        return applyImported(entry, result.image, born);
      }).finally(function () { if (born === epoch) loading = Math.max(0, loading - 1); refreshButtons(); });
    }
    function openImage(data, name) {
      return openImageData(exact(data), name);
    }
    function openImageData(image, name) {
      var identity = { source: -1, file: 0, id: "standalone" }, id = key(identity), previous = entries.get(id);
      cancelPreview(); removeOverlays(); if (previous) { destroyEngine(previous); entries.delete(id); }
      if (active && active.pane) active.pane.hidden = true;
      var record = { texture: identity, name: (name || "image").replace(/\.png$/i, ""), sourceName: "PNG", width: image.width, height: image.height, format: "RGBA", available: true };
      catalogue = catalogue.filter(function (r) { return key(r.texture) !== id; }); catalogue.unshift(record);
      active = { record: record, standalone: true, sourceSha256: "", loading: true, encoding: false, modified: false, kind: "paint", png: null, seeds: [], exclusions: [], used: Date.now(), original: copyImage(image) };
      entries.set(id, active); makeEngine(active, image); active.loading = false; rebuildTextureSelect(); textureSelect.value = id; section.open = true; setTab("paint"); active.engine.fit(); say("Image changes ready. Use Export PNG to save."); changed(); return active;
    }
    function chooseProject() {
      if (loading || pendingRestore || floating(active) || active && !canEdit(active)) return;
      if (typeof options.pickProject !== "function") { projectFile.click(); return; }
      elevatePicker();
      try {
        var picked = options.pickProject(function (path) { finishPickerStack(); if (path) openProjectPath(path).catch(function (err) { if (err.name !== "AbortError") say("", err.message); }); });
        if (picked && typeof picked.finally === "function") picked.finally(finishPickerStack).catch(function (err) { say("", err.message); });
      } catch (err) { finishPickerStack(); say("", err.message); }
    }
    function validateProject(project) {
      if (!project || project.format !== "elichika-texture-project" || project.version !== 1 || !Number.isInteger(project.width) || !Number.isInteger(project.height) || project.width < 1 || project.height < 1 || project.width * project.height > 16777216 || !Array.isArray(project.layers) || !project.layers.length || project.layers.length > 8 || project.width * project.height * project.layers.length > 33554432) throw new Error(t("Invalid layer project."));
      var seen = new Set(), encodedBytes = 0;
      project.layers.forEach(function (layer) {
        if (!layer || typeof layer.id !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(layer.id) || seen.has(layer.id) || typeof layer.name !== "string" || !layer.name.trim() || Array.from(layer.name).length > 128 || /[\u0000-\u001f\u007f]/.test(layer.name) || typeof layer.visible !== "boolean" || !Number.isFinite(layer.opacity) || layer.opacity < 0 || layer.opacity > 1 || typeof layer.png !== "string" || layer.png.indexOf("data:image/png;base64,") !== 0 || layer.png.length > 11184840) throw new Error(t("Invalid layer project."));
        seen.add(layer.id); encodedBytes += layer.png.length + layer.name.length * 4 + 256;
      });
      if (!seen.has(project.activeLayer) || encodedBytes > 32 * 1024 * 1024) throw new Error(t("Invalid layer project."));
      return project;
    }
    function loadProject(read, name) {
      if (loading || pendingRestore || floating(active) || active && !canEdit(active)) return Promise.resolve(false);
      var initial = active, entry = active && !active.standalone ? active : null, born = epoch;
      cancelPreview(); loading++; say("Opening layer project…"); refreshButtons();
      return Promise.resolve().then(read).then(validateProject).then(function (project) {
        if (born !== epoch || active !== initial) throw abort();
        if (entry && (project.width !== entry.original.width || project.height !== entry.original.height)) throw new Error(t("Texture dimensions must match the original."));
        ensureLayerBudget(project.width * project.height * project.layers.length * 4, initial);
        var raw = { format: project.format, version: project.version, width: project.width, height: project.height, activeLayer: project.activeLayer, layers: [] }, chain = Promise.resolve();
        project.layers.forEach(function (layer) { chain = chain.then(function () {
          if (born !== epoch || active !== initial) throw abort();
          return api("/api/texture/editor/decode", { png: layer.png }).then(function (response) {
            var image = exact(response); if (image.width !== project.width || image.height !== project.height) throw new Error(t("Texture dimensions must match the original."));
            raw.layers.push({ id: layer.id, name: layer.name, visible: layer.visible, opacity: layer.opacity, image: image });
          });
        }); }); return chain.then(function () { return raw; });
      }).then(function (raw) {
        if (born !== epoch || active !== initial || entry && !canEdit(entry)) throw abort();
        if (entry) { entry.nextKind = "paint"; try { entry.engine.restoreProject(raw); } finally { entry.nextKind = null; } }
        else {
          entry = openImageData(raw.layers[0].image, name || "project"); entry.loading = true; suppressed++;
          try { entry.engine.restoreProject(raw, { history: false }); } finally { suppressed--; entry.loading = false; }
          entry.original = entry.engine.getImage(); entry.modified = false;
        }
        setTab("paint"); layerSignature = ""; upload(entry); refreshButtons(); return true;
      }).finally(function () { if (born === epoch) loading = Math.max(0, loading - 1); refreshButtons(); });
    }
    function openProject(project, name) { return loadProject(function () { return project; }, name); }
    function openProjectPath(path) { if (typeof path !== "string" || !path.trim()) return Promise.resolve(false); return loadProject(function () { return api("/api/texture/editor/project/open", { path: path }).then(function (response) { return response.project; }); }, path.split(/[\\/]/).pop().replace(/\.elichika-texture\.json$/i, "")); }
    function importProject(file) {
      if (!file) return Promise.resolve(false);
      if (file.size > 32 * 1024 * 1024) return Promise.reject(new Error(t("Invalid layer project.")));
      return loadProject(function () { return file.text().then(JSON.parse); }, file.name.replace(/\.elichika-texture\.json$/i, ""));
    }
    function autoDownload(link) {
      var agent = global.navigator && global.navigator.userAgent || "";
      if (!(/Android/.test(agent) && /; wv\)|Version\/4\.0/.test(agent))) link.click();
    }
    function saveProject() {
      if (!active || !active.engine || loading || pendingRestore) return Promise.resolve(false);
      if (floating(active)) { say("Apply or cancel moved pixels first."); return Promise.resolve(false); }
      if (active.preview || previewTimer || previewJobs) return Promise.resolve(false);
      var entry = active, born = epoch, project = entry.engine.getProject(false), payload = { format: project.format, version: project.version, width: project.width, height: project.height, activeLayer: project.activeLayer, layers: [] }, chain = Promise.resolve();
      loading++; say("Saving layer project…"); refreshButtons();
      project.layers.forEach(function (layer) { chain = chain.then(function () { if (born !== epoch) throw abort(); return encode(layer.image).then(function (png) { payload.layers.push({ id: layer.id, name: layer.name, visible: layer.visible, opacity: layer.opacity, png: png }); }); }); });
      return chain.then(function () {
        if (born !== epoch) throw abort();
        return api("/api/texture/editor/project/save", { project: payload, name: entry.record.name || "texture" });
      }).then(function (saved) {
        if (born !== epoch) return false;
        if (!saved || typeof saved.path !== "string" || typeof saved.url !== "string" || !/^\/api\/download\?/.test(saved.url)) throw new Error(t("Invalid layer project."));
        savedProjectPath.textContent = saved.path; savedProjectDownload.href = saved.url; savedProjectDownload.download = saved.name; savedProjectFile.hidden = false; say("Layer project saved on this device."); autoDownload(savedProjectDownload); return saved;
      }).catch(function (err) { if (err.name !== "AbortError") say("", err.message); return false; }).finally(function () { if (born === epoch) loading = Math.max(0, loading - 1); refreshButtons(); });
    }
    function openPaint() { section.open = true; setTab("paint"); setExpanded(true); if (active && active.engine) active.engine.fit(); else say("Import a PNG to start painting, or choose a model texture."); return true; }
    function expandedParent() {
      var fullscreen = document.fullscreenElement || document.webkitFullscreenElement, owner = holder.closest && holder.closest("#tab-viewer");
      return fullscreen && fullscreen !== section ? fullscreen : owner && owner.classList.contains("viewer-expanded") ? owner : document.body;
    }
    function positionExpandedEditor() { if (expanded) { var target = expandedParent(); if (section.parentNode !== target) target.appendChild(section); } }
    function setExpanded(value) {
      var entering = !!value && !expanded;
      expanded = !!value;
      // Escape the viewer sidebar's stacking context so file panels cannot cover
      // the expanded editor. The same nodes/listeners are moved and restored.
      if (expanded && !expandAnchor) { expandAnchor = document.createComment("texture editor location"); section.parentNode.insertBefore(expandAnchor, section); }
      positionExpandedEditor();
      if (!expanded && expandAnchor) { if (expandAnchor.parentNode) expandAnchor.parentNode.insertBefore(section, expandAnchor); expandAnchor.remove(); expandAnchor = null; }
      section.classList.toggle("viewer-texture-expanded", expanded); expandButton.setAttribute("aria-pressed", String(expanded)); expandButton.textContent = t(expanded ? "Collapse editor" : "Expand editor");
      expandButton.dataset.symbol = expanded ? "↙︎" : "↗︎"; expandButton.title = expandButton.textContent;
      if (entering) workspace.inspector.open = global.innerWidth >= 760 && global.innerHeight >= 540;
      if (expanded) section.open = true;
      var fit = function () { if (active && active.engine) active.engine.fit(); };
      if (global.requestAnimationFrame) global.requestAnimationFrame(fit); else global.setTimeout(fit, 0);
    }
    function exportPNG() {
      if (!active || !active.engine) return Promise.resolve(false);
      if (floating(active)) { say("Apply or cancel moved pixels first."); return Promise.resolve(false); }
      if (active.preview || previewTimer || previewJobs) { say("Apply or cancel the color preview first."); return Promise.resolve(false); }
      var entry = active, name = (entry.record.name || "texture").replace(/[\\/:*?"<>|]/g, "_") + ".png";
      say("Saving PNG…");
      return encode(entry.engine.getImage()).then(function (png) {
        return api("/api/texture/editor/save", { png: png, name: name }).then(function (saved) {
          if (!saved || typeof saved.path !== "string" || typeof saved.url !== "string" || !/^\/api\/download\?/.test(saved.url)) throw new Error("The PNG was not saved to a downloadable file.");
          savedPath.textContent = saved.path; savedDownload.href = saved.url; savedDownload.download = saved.name || name; savedFile.hidden = false; say("PNG saved on this device.");
          if (options.onDownloadPNG) return options.onDownloadPNG(png, saved.name || name, saved);
          // Android's embedded WebView has no DownloadListener. The file is
          // already stored in shared Downloads: keep the editor open and show
          // its path/link rather than navigating the WebView to a download.
          autoDownload(savedDownload);
          return saved;
        });
      }).catch(function (err) { if (err.name !== "AbortError") say("", err.message); return false; });
    }
    function undo() { if (!active || !active.engine || loading || !canEdit(active)) return false; cancelPreview(); var result = active.engine.undo(); refreshButtons(); return result; }
    function redo() { if (!active || !active.engine || loading || !canEdit(active)) return false; cancelPreview(); var result = active.engine.redo(); refreshButtons(); return result; }
    function selectFaces(mesh, faces, mode, texture) {
      if (!active || !active.engine || !canEdit(active)) return false;
      var data = geometryData(mesh); if (!data) return false;
      var binding = bindings(active).filter(function (b) { return b.mesh === mesh; })[0]; texture = texture || binding && binding.texture; if (!texture) return false;
      cancelPreview(); var image = active.engine.getImage(false), mask = rasterFaces(image.width, image.height, data.triangles, data.uvs, faces, texture);
      active.lastModelSelection = { mesh: mesh.name || "Mesh", faceCount: faces.length, faces: faces.slice(0, 32) };
      active.engine.selectRegion(mask, mode || selectionMode.value); return true;
    }
    function faceMaterial(mesh, hit) {
      var original = getOriginalMaterials(mesh), index = hit.face && hit.face.materialIndex || 0, material = Array.isArray(original) ? original[index] : original;
      return { material: material, index: index, texture: material && (genericMaps.get(material) || material.map) };
    }
    function sceneHit(event) {
      var r = runtime(); if (!T || !r.model || !r.camera || !r.domElement || options.isInteractive && !options.isInteractive()) return null;
      var rect = r.domElement.getBoundingClientRect(); if (!rect.width || !rect.height) return null;
      var ray = new T.Raycaster(); ray.setFromCamera(new T.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2), r.camera);
      var hits = ray.intersectObject(r.model, true).filter(function (hit) { for (var p = hit.object; p; p = p.parent) { if (!p.visible || p.userData && p.userData.viewerHelper) return false; if (p === r.model) break; } return !!hit.uv && (!global.ViewerNearClip || global.ViewerNearClip.visiblePoint(r.camera, hit.point)); });
      if (!hits.length) return null;
      var hit = hits[0], binding = faceMaterial(hit.object, hit), identity = binding.texture && binding.texture.userData && binding.texture.userData.viewerTexture;
      if (!identity || !catalogue.some(function (row) { return same(row.texture, identity) && row.available !== false; })) return { invalid: true };
      return { hit: hit, binding: binding, identity: identity };
    }
    function scenePick(event) {
      var picked = sceneHit(event); if (!picked) return;
      if (picked.invalid) { say("", "This face has no editable original main texture."); return; }
      var hit = picked.hit, binding = picked.binding, identity = picked.identity;
      var born = epoch, operation = sceneMode, mode = event.altKey ? "subtract" : event.shiftKey ? "add" : selectionMode.value;
      var ready = active && same(active.record.texture, identity) && active.engine ? Promise.resolve(active) : selectTexture(identity);
      ready.then(function (entry) {
        if (born !== epoch || entry !== active || !canEdit(entry)) return;
        if (operation === "skin" || operation === "exclude") {
          setTab("skin"); var uv = sampledUv(binding.texture, [hit.uv.x, hit.uv.y]), image = entry.engine.getImage(false); return seed(entry, { x: uv[0] * image.width, y: uv[1] * image.height }, operation === "exclude");
        }
        var data = geometryData(hit.object), faces = [hit.faceIndex];
        if (operation === "connected") {
          if (!data.graph) data.graph = global.ViewerMeshTools && global.ViewerMeshTools.buildFaceConnectivity ? global.ViewerMeshTools.buildFaceConnectivity({ positions: data.positions, triangles: data.triangles, skin: data.skin }, true) : edgeGraph(data.triangles);
          var accept = function (face) { return faceAllowed(hit.object.geometry, face, binding.index); };
          if (global.ViewerMeshTools && global.ViewerMeshTools.connectedFaces) faces = global.ViewerMeshTools.connectedFaces(data.graph, faces, accept);
          else { var seen = new Set(faces); for (var i = 0; i < faces.length; i++) data.graph[faces[i]].forEach(function (face) { if (!seen.has(face) && accept(face)) { seen.add(face); faces.push(face); } }); }
        }
        return selectFaces(hit.object, faces, mode, binding.texture);
      }).catch(function (err) { if (err.name !== "AbortError") say("", err.message); });
    }
    function showModelCursor(event, picked) {
      if (sceneMode !== "brush" || !section.open || !picked || picked.invalid || space) { modelCursor.hidden = true; return; }
      var r = runtime(), rect = r.domElement.getBoundingClientRect(), hit = picked.hit, geometry = hit.object.geometry, uv = geometry.attributes.uv, position = geometry.attributes.position;
      var indices = [hit.face.a, hit.face.b, hit.face.c], projected = [], texels = [], record = catalogue.filter(function (row) { return same(row.texture, picked.identity); })[0];
      if (!record) { modelCursor.hidden = true; return; }
      indices.forEach(function (index) {
        var point = new T.Vector3().fromBufferAttribute(position, index), morphs = geometry.morphAttributes.position, influence = hit.object.morphTargetInfluences;
        if (morphs && influence) morphs.forEach(function (attribute, slot) { if (!influence[slot]) return; var delta = new T.Vector3().fromBufferAttribute(attribute, index); if (!geometry.morphTargetsRelative) delta.sub(new T.Vector3().fromBufferAttribute(position, index)); point.addScaledVector(delta, influence[slot]); });
        if (hit.object.isSkinnedMesh && hit.object.boneTransform) hit.object.boneTransform(index, point);
        point.applyMatrix4(hit.object.matrixWorld).project(r.camera); projected.push([point.x * rect.width / 2, point.y * rect.height / 2]);
        var transformed = rawUv(picked.binding.texture, [uv.getX(index), uv.getY(index)]); texels.push([transformed[0] * record.width, transformed[1] * record.height]);
      });
      var ratios = []; for (var edge = 0; edge < 3; edge++) { var next = (edge + 1) % 3, length = Math.hypot(texels[edge][0] - texels[next][0], texels[edge][1] - texels[next][1]); if (length > .001) ratios.push(Math.hypot(projected[edge][0] - projected[next][0], projected[edge][1] - projected[next][1]) / length); }
      ratios.sort(function (a, b) { return a - b; }); var radius = clamp(brushSize.value() / 2 * (ratios[Math.floor(ratios.length / 2)] || 1), 2, 180);
      modelCursor.style.left = event.clientX + "px"; modelCursor.style.top = event.clientY + "px"; modelCursor.style.width = modelCursor.style.height = radius * 2 + "px"; modelCursor.classList.toggle("subtract", event.altKey || selectionMode.value === "subtract"); modelCursor.hidden = false;
    }
    function cancelModelBrush() {
      var stroke = brushStroke; if (!stroke) return;
      brushStroke = null; stroke.cancelled = true;
      if (stroke.entry) stroke.entry.modelBrushMask = null; updateOverlay(); refreshButtons();
    }
    function stampModelBrush(stroke, picked) {
      if (!picked || picked.invalid || !same(picked.identity, stroke.identity)) { stroke.last = null; return; }
      if (!stroke.entry) { if (stroke.queue.length < 2048) stroke.queue.push(picked); return; }
      var entry = stroke.entry, image = entry.engine.getImage(false), sample = sampledUv(picked.binding.texture, [picked.hit.uv.x, picked.hit.uv.y]), x = sample[0] * image.width, y = sample[1] * image.height, radius = stroke.radius;
      var previous = stroke.last, distance = previous ? Math.hypot(x - previous.x, y - previous.y) : 0;
      // Interpolate only neighbouring UV samples. Never bridge an atlas seam.
      var steps = previous && previous.mesh === picked.hit.object && distance <= radius * 4 ? Math.max(1, Math.ceil(distance / Math.max(.5, radius * .35))) : 1;
      for (var step = 1; step <= steps; step++) {
        var amount = step / steps, dirty = stampMaskCircle(stroke.mask, stroke.source, image.width, image.height, steps > 1 ? previous.x + (x - previous.x) * amount : x, steps > 1 ? previous.y + (y - previous.y) * amount : y, radius, stroke.mode);
        if (dirty) { stroke.dirty = stroke.dirty ? { left: Math.min(stroke.dirty.left, dirty.left), top: Math.min(stroke.dirty.top, dirty.top), right: Math.max(stroke.dirty.right, dirty.right), bottom: Math.max(stroke.dirty.bottom, dirty.bottom) } : dirty; }
      }
      stroke.last = { x: x, y: y, mesh: picked.hit.object }; stroke.faces.add(picked.hit.faceIndex); stroke.mesh = picked.hit.object;
      entry.modelBrushMask = stroke.mask;
      if (Date.now() - (stroke.uploaded || 0) > 75) { updateOverlay(stroke.mask, stroke.dirty); stroke.dirty = null; stroke.uploaded = Date.now(); }
    }
    function finishModelBrush(stroke) {
      if (stroke !== brushStroke || !stroke.entry || stroke.cancelled || stroke.born !== epoch || stroke.entry !== active) return;
      brushStroke = null; stroke.entry.modelBrushMask = null;
      if (canEdit(stroke.entry)) {
        stroke.entry.lastModelSelection = { mesh: stroke.mesh && stroke.mesh.name || "Mesh", faceCount: stroke.faces.size, faces: Array.from(stroke.faces).slice(0, 32), brush: true };
        stroke.entry.engine.setMask(stroke.mask);
      }
      updateOverlay(); refreshButtons();
    }
    function beginModelBrush(event, picked) {
      if (!picked || picked.invalid) { if (picked && picked.invalid) say("", "This face has no editable original main texture."); return; }
      cancelModelBrush(); cancelPreview(); restoreAutomaticSelectionDisplay();
      var stroke = { born: epoch, identity: picked.identity, mode: event.altKey ? "subtract" : event.shiftKey ? "add" : selectionMode.value, radius: brushSize.value() / 2, queue: [], faces: new Set(), entry: null, done: false };
      brushStroke = stroke; stampModelBrush(stroke, picked);
      var ready = active && same(active.record.texture, picked.identity) && active.engine ? Promise.resolve(active) : selectTexture(picked.identity);
      ready.then(function (entry) {
        if (stroke !== brushStroke || stroke.born !== epoch || entry !== active || !canEdit(entry)) { if (stroke === brushStroke) cancelModelBrush(); return; }
        stroke.entry = entry; stroke.source = entry.engine.getMask(); var image = entry.engine.getImage(false); stroke.mask = brushMask(stroke.source, image.width * image.height, stroke.mode);
        var queued = stroke.queue; stroke.queue = []; queued.forEach(function (hit) { stampModelBrush(stroke, hit); });
        if (stroke.done) finishModelBrush(stroke); else refreshButtons();
      }).catch(function (err) { if (stroke === brushStroke) cancelModelBrush(); if (err.name !== "AbortError") say("", err.message); });
    }
    function attachScene() {
      var r = runtime(), element = r.domElement; if (!element || element === sceneElement) return;
      sceneElement = element;
      function down(event) {
        if (sceneMode === "orbit" || space || event.button !== 0 || !section.open) return;
        if (options.isInteractive && !options.isInteractive() || options.isSceneInteractive && !options.isSceneInteractive() || options.isReadOnly && options.isReadOnly()) return;
        pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, controls: r.controls, enabled: r.controls && r.controls.enabled };
        if (r.controls) r.controls.enabled = false; event.preventDefault(); event.stopImmediatePropagation();
        if (element.setPointerCapture) element.setPointerCapture(event.pointerId);
        if (sceneMode === "brush") { var picked = sceneHit(event); showModelCursor(event, picked); beginModelBrush(event, picked); }
      }
      function move(event) {
        if (sceneMode !== "brush" || !section.open || space) { modelCursor.hidden = true; return; }
        if (!pointer && Date.now() - hoverAt < 32) return; hoverAt = Date.now();
        var picked = sceneHit(event); showModelCursor(event, picked);
        if (pointer && pointer.id === event.pointerId && brushStroke) { event.preventDefault(); event.stopImmediatePropagation(); stampModelBrush(brushStroke, picked); }
      }
      function up(event) {
        if (!pointer || pointer.id !== event.pointerId) return;
        var previous = pointer; pointer = null; if (previous.controls) previous.controls.enabled = previous.enabled;
        event.preventDefault(); event.stopImmediatePropagation();
        if (brushStroke) { stampModelBrush(brushStroke, sceneHit(event)); brushStroke.done = true; if (brushStroke.entry) finishModelBrush(brushStroke); }
        else if (sceneMode !== "brush" && Math.hypot(event.clientX - previous.x, event.clientY - previous.y) < 8) scenePick(event);
        if (element.hasPointerCapture && element.hasPointerCapture(event.pointerId)) element.releasePointerCapture(event.pointerId);
      }
      function cancel() { if (pointer && pointer.controls) pointer.controls.enabled = pointer.enabled; pointer = null; cancelModelBrush(); modelCursor.hidden = true; }
      listen(element, "pointerdown", down, true); listen(element, "pointermove", move, true); listen(element, "pointerup", up, true); listen(element, "pointercancel", cancel, true); listen(element, "pointerleave", function () { if (!pointer) modelCursor.hidden = true; }, true);
    }
    function reset(keepStandalone, silent) {
      rebindingModel = false;
      cancelModelBrush(); modelCursor.hidden = true;
      entries.forEach(function (entry) { if (entry.liveTimer) global.clearTimeout(entry.liveTimer); entry.liveTimer = null; });
      var standalone = keepStandalone !== false && entries.get("-1:0:standalone");
      epoch++; sequence++; if (previewTimer) global.clearTimeout(previewTimer); previewTimer = null; requestControllers.forEach(function (c) { c.abort(); }); requestControllers.clear();
      if (pointer && pointer.controls) pointer.controls.enabled = pointer.enabled; pointer = null;
      removeOverlays(); entries.forEach(function (entry) { if (entry === standalone) return; restoreLive(entry); destroyEngine(entry); });
      genericMaps.forEach(function (map, material) { material.map = map; material.needsUpdate = true; }); genericMaps.clear();
      entries.clear(); catalogue = []; active = standalone || null; if (standalone) { entries.set("-1:0:standalone", standalone); catalogue.push(standalone.record); if (standalone.pane) standalone.pane.hidden = false; }
      pendingRestore = null; cataloguePromise = null; restoringDocuments = 0; loading = 0; previewJobs = 0; currentToken = null; lastModel = null; geometryCache = new WeakMap();
      rebuildTextureSelect(); information.textContent = ""; toneEstimate.textContent = ""; say(standalone ? "Image changes ready. Use Export PNG to save." : "Open a model to edit textures."); revision++; if (!silent && options.onChange) options.onChange(); refreshButtons();
    }
    function rebuildTextureSelect() {
      textureSelect.innerHTML = ""; var blank = node("option", textureSelect, "Choose a texture"); blank.value = "";
      catalogue.forEach(function (record) { var option = node("option", textureSelect); option.value = key(record.texture); option.textContent = record.name + " · " + record.width + "×" + record.height + (record.sourceName ? " · " + record.sourceName : ""); option.disabled = record.available === false; option.title = record.reason || ""; });
      if (active) textureSelect.value = key(active.record.texture);
    }
    function refresh() {
      if (disposed) return Promise.resolve();
      if (rebindingModel) { refreshButtons(); return Promise.resolve(); }
      attachScene(); var token = options.getToken && options.getToken(), r = runtime();
      if (token === currentToken && r.model === lastModel) { refreshButtons(); return cataloguePromise || Promise.resolve(); }
      reset(true, true); currentToken = token; lastModel = r.model;
      if (!token || !r.model) return Promise.resolve();
      var born = epoch; loading++; say("Loading textures…"); refreshButtons();
      var prepared = r.metadata && r.metadata.editing && r.metadata.editing.textures;
      cataloguePromise = (prepared && Array.isArray(prepared.textures) ? Promise.resolve(prepared) : api("/api/viewer/texture/inspect", { token: token })).then(function (data) {
        if (disposed || born !== epoch) return;
        catalogue = data.textures || []; var standalone = entries.get("-1:0:standalone"); if (standalone) catalogue.unshift(standalone.record); rebuildTextureSelect();
        say("Choose faces or a texture region before applying color.");
      }).catch(function (err) { if (err.name !== "AbortError" && born === epoch) say("", err.message); }).finally(function () { if (born === epoch) { loading = Math.max(0, loading - 1); cataloguePromise = null; } refreshButtons(); });
      return cataloguePromise;
    }
    // A motion-only rebuild changes scene/material objects, not source pixels.
    // Validate every open document before replacing the old model, then retain
    // its engine so layers, exact PNGs and Undo/Redo never need reconstruction.
    function prepareModelRebind(nextRuntime, token) {
      if (!Array.from(entries.values()).some(function (entry) { return !entry.standalone; })) return Promise.resolve(null);
      if (disposed || hasPending() || !nextRuntime || !nextRuntime.model || !token) return Promise.reject(new Error("Finish texture editing before changing motions."));
      if (!nextRuntime.metadata || !nextRuntime.metadata.editing || nextRuntime.metadata.editing.available !== true || nextRuntime.metadata.editing.token !== token) return Promise.reject(new Error("The texture editor is unavailable for the prepared model. The current model was kept."));
      var born = epoch, sourceModel = lastModel, sourceToken = currentToken;
      var prepared = nextRuntime.metadata && nextRuntime.metadata.editing && nextRuntime.metadata.editing.textures;
      return (prepared && Array.isArray(prepared.textures) ? Promise.resolve(prepared) : api("/api/viewer/texture/inspect", { token: token })).then(function (data) {
        if (disposed || born !== epoch || sourceModel !== lastModel || sourceToken !== currentToken) throw abort();
        if (!data || !Array.isArray(data.textures)) throw new Error("The texture catalogue could not be restored.");
        var plans = [], identities = new Set();
        entries.forEach(function (entry) {
          if (entry.standalone) return;
          var candidates = data.textures.filter(function (record) {
            return record.available !== false && record.texture && record.texture.file === entry.record.texture.file && record.texture.id === entry.record.texture.id && record.sourceSha256 === entry.sourceSha256;
          }), exactMatch = candidates.filter(function (record) { return same(record.texture, entry.record.texture); });
          var record = exactMatch.length === 1 ? exactMatch[0] : candidates.length === 1 ? candidates[0] : null;
          if (!record || !key(record.texture) || identities.has(key(record.texture)) || record.width !== entry.record.width || record.height !== entry.record.height || entry.modified && !entry.engine && !entry.liveTexture) throw new Error(t("The texture source changed. Reload the original model."));
          identities.add(key(record.texture)); plans.push({ entry: entry, record: record });
        });
        return { owner: modelRebindOwner, epoch: born, sourceModel: sourceModel, sourceToken: sourceToken,
          model: nextRuntime.model, token: token, catalogue: data.textures, plans: plans, used: false };
      });
    }
    function detachModelForRebind(plan) {
      if (!plan || plan.owner !== modelRebindOwner || plan.used || plan.epoch !== epoch || plan.sourceModel !== lastModel || plan.sourceToken !== currentToken || hasPending()) throw new Error("The texture documents changed while loading this motion.");
      rebindingModel = true; removeOverlays(); modelCursor.hidden = true;
      entries.forEach(function (entry) { if (entry.liveTimer) global.clearTimeout(entry.liveTimer); entry.liveTimer = null; if (!entry.standalone) restoreLive(entry, true); });
      genericMaps.clear(); geometryCache = new WeakMap();
    }
    function commitModelRebind(plan) {
      var r = runtime(), token = options.getToken && options.getToken();
      if (!rebindingModel || !plan || plan.owner !== modelRebindOwner || plan.used || plan.epoch !== epoch || r.model !== plan.model || token !== plan.token) throw new Error("The texture documents could not be bound to the new model.");
      var retained = new Map(); entries.forEach(function (entry, identity) { if (entry.standalone) retained.set(identity, entry); });
      plan.plans.forEach(function (row) { row.entry.record = row.record; row.entry.uvSelectionData = row.entry.uvSelectionSignature = null; retained.set(key(row.record.texture), row.entry); });
      entries = retained; catalogue = plan.catalogue.slice();
      var standalone = entries.get("-1:0:standalone"); if (standalone) catalogue.unshift(standalone.record);
      currentToken = plan.token; lastModel = plan.model; plan.used = true; rebindingModel = false; epoch++;
      rebuildTextureSelect();
      plan.plans.forEach(function (row) {
        var entry = row.entry;
        if (entry.engine) upload(entry);
        else if (!compare.checked && entry.modified && entry.liveTexture) liveImage(entry, entry.liveTexture.image);
      });
      updateOverlay(); updateInformation(); updateTone(); changed();
    }
    // These snapshots stay in memory; the portable project/PNG channels remain
    // explicit files. copy=false is only for an immediately frozen model reload.
    function captureDocuments(copy) {
      var clone = copy !== false, documents = [], arrays = new Set(), bytes = 0;
      entries.forEach(function (entry) {
        if (entry.standalone || !/^[a-f0-9]{64}$/.test(entry.sourceSha256 || "")) return;
        var project = entry.engine && entry.engine.getProject ? entry.engine.getProject(clone) : entry.savedProject;
        if (project && !entry.engine && clone) project = { format: project.format, version: project.version, width: project.width, height: project.height, activeLayer: project.activeLayer, layers: project.layers.map(function (layer) { return { id: layer.id, name: layer.name, visible: layer.visible, opacity: layer.opacity, image: copyImage(layer.image) }; }) };
        var mask = entry.engine ? entry.engine.getMask() : entry.savedMask ? clone ? new Uint8Array(entry.savedMask) : entry.savedMask : null;
        if (project) project.layers.forEach(function (layer) { if (!arrays.has(layer.image.data)) { arrays.add(layer.image.data); bytes += layer.image.data.byteLength; } });
        if (mask && !arrays.has(mask)) { arrays.add(mask); bytes += mask.byteLength; }
        documents.push({ texture: Object.assign({}, entry.record.texture), sourceSha256: entry.sourceSha256, sourceName: entry.record.sourceName || "", project: project || null, mask: mask, view: entry.engine ? entry.engine.getView() : entry.savedView ? Object.assign({}, entry.savedView) : null, png: entry.png, modified: !!entry.modified, kind: entry.kind, userSelected: !!entry.userSelected, seeds: entry.seeds.map(function (point) { return point.slice(); }), exclusions: entry.exclusions.map(function (point) { return point.slice(); }) });
      });
      return { version: 1, token: currentToken, epoch: epoch, activeTexture: active && !active.standalone ? Object.assign({}, active.record.texture) : null, documents: documents, bytes: bytes };
    }
    function restoreDocuments(snapshot) {
      if (!snapshot || snapshot.version !== 1 || !Array.isArray(snapshot.documents)) return Promise.reject(new Error("Invalid texture document snapshot."));
      var ready = refresh(), born = epoch, plans = [], retained = new Set(); restoringDocuments++; loading++; refreshButtons();
      return ready.then(function () {
        var chain = Promise.resolve();
        snapshot.documents.forEach(function (row) { chain = chain.then(function () {
          if (born !== epoch) throw abort();
          if (!row || !key(row.texture) || row.texture.source < 0 || retained.has(key(row.texture)) || !/^[a-f0-9]{64}$/.test(row.sourceSha256 || "") || typeof row.modified !== "boolean" || ["costume", "skin", "paint"].indexOf(row.kind) < 0 || row.png !== null && (typeof row.png !== "string" || row.png.indexOf("data:image/png;base64,") !== 0) || row.modified && !row.png) throw new Error("Invalid texture document snapshot.");
          retained.add(key(row.texture));
          var candidates = catalogue.filter(function (record) { return record.available !== false && record.texture.file === row.texture.file && record.texture.id === row.texture.id && (!record.sourceSha256 || record.sourceSha256 === row.sourceSha256); }), exactMatch = candidates.filter(function (record) { return same(record.texture, row.texture); });
          var record = exactMatch.length === 1 ? exactMatch[0] : candidates.length === 1 ? candidates[0] : null;
          if (!record || plans.some(function (plan) { return same(plan.record.texture, record.texture); })) throw new Error(t("The texture source changed. Reload the original model."));
          return load(record).then(function (entry) {
            if (born !== epoch) throw abort();
            if (entry.sourceSha256 !== row.sourceSha256) throw new Error(t("The texture source changed. Reload the original model."));
            var size = entry.original.width * entry.original.height;
            if (row.mask && (!(row.mask instanceof Uint8Array) || row.mask.length !== size)) throw new Error("Invalid texture document snapshot.");
            if (row.view && (!Number.isFinite(row.view.x) || !Number.isFinite(row.view.y) || !Number.isFinite(row.view.zoom) || row.view.zoom <= 0)) throw new Error("Invalid texture document snapshot.");
            if (row.project) {
              if (row.project.width !== entry.original.width || row.project.height !== entry.original.height || !Array.isArray(row.project.layers) || !row.project.layers.length || row.project.layers.length > 8) throw new Error("Invalid texture document snapshot.");
              validateProject({ format: row.project.format, version: row.project.version, width: row.project.width, height: row.project.height, activeLayer: row.project.activeLayer, layers: row.project.layers.map(function (layer) { return { id: layer.id, name: layer.name, visible: layer.visible, opacity: layer.opacity, png: "data:image/png;base64," }; }) });
              row.project.layers.forEach(function (layer) { if (!layer.image || layer.image.width !== entry.original.width || layer.image.height !== entry.original.height || !(layer.image.data instanceof Uint8ClampedArray || layer.image.data instanceof Uint8Array) || layer.image.data.length !== size * 4) throw new Error("Invalid texture document snapshot."); });
              plans.push({ row: row, record: record, entry: entry, project: row.project }); return;
            }
            var image = row.png ? decodePatch(entry, row.png) : Promise.resolve(entry.original);
            return image.then(function (value) { if (born !== epoch) throw abort(); if (value.width !== entry.original.width || value.height !== entry.original.height) throw new Error("Invalid texture document snapshot."); plans.push({ row: row, record: record, entry: entry, image: value }); });
          });
        }); }); return chain;
      }).then(function () {
        if (born !== epoch) throw abort();
        // All identities, immutable hashes and payload dimensions have passed.
        // No editor is replaced until the entire transaction is ready.
        cancelPreview(); var wanted = new Set(plans.map(function (plan) { return key(plan.record.texture); }));
        entries.forEach(function (entry) {
          if (entry.standalone || wanted.has(key(entry.record.texture))) return;
          entry.encodeGeneration = (entry.encodeGeneration || 0) + 1; entry.encoding = false; entry.encodeError = null;
          if (entry.engine && entry.original) { suppressed++; try { if (floating(entry)) entry.engine.cancelFloating(); replaceImage(entry, entry.original, { history: false }); } finally { suppressed--; } }
          entry.savedProject = null; entry.png = null; entry.modified = false; restoreLive(entry);
        });
        plans.forEach(function (plan) {
          var entry = plan.entry, row = plan.row;
          entry.encodeGeneration = (entry.encodeGeneration || 0) + 1; entry.encoding = false; entry.encodeError = null; suppressed++;
          try {
            if (floating(entry)) entry.engine.cancelFloating();
            if (plan.project) entry.engine.restoreProject(plan.project, { history: false }); else replaceImage(entry, plan.image, { history: false });
            entry.engine.setMask(row.mask || null, { history: false }); if (row.view) entry.engine.setView(row.view);
          } finally { suppressed--; }
          entry.savedProject = null; entry.modified = !!row.modified; entry.png = row.png || null; entry.kind = row.kind || "paint"; entry.userSelected = row.userSelected; entry.stats = null; entry.featherCache = null;
          entry.seeds = (row.seeds || []).map(function (point) { return point.slice(); }); entry.exclusions = (row.exclusions || []).map(function (point) { return point.slice(); });
          if (entry === active && compare.checked && entry.engine.setDisplayOverride) entry.engine.setDisplayOverride(entry.original);
          upload(entry);
        });
        var selected = snapshot.activeTexture && plans.filter(function (plan) { return same(plan.row.texture, snapshot.activeTexture); })[0];
        if (selected) { if (active && active.pane) active.pane.hidden = true; active = selected.entry; active.pane.hidden = false; textureSelect.value = key(active.record.texture); syncBrush(); selectCanvasTool(); }
        layerSignature = ""; updateOverlay(); changed(); return true;
      }).catch(function (err) { if (err.name !== "AbortError" && born === epoch) say("", err.message); throw err; }).finally(function () { if (born === epoch) { restoringDocuments = Math.max(0, restoringDocuments - 1); loading = Math.max(0, loading - 1); evict(); } refreshButtons(); });
    }
    function restoreEdits(rows) {
      rows = rows || []; if (!Array.isArray(rows)) return Promise.reject(new Error("Invalid texture recipe."));
      var identities = new Set();
      for (var index = 0; index < rows.length; index++) {
        var value = rows[index], identity = value && key(value.texture);
        if (!identity || value.texture.source < 0 || value.texture.file < 0 || identities.has(identity) || typeof value.sourceSha256 !== "string" || !/^[a-f0-9]{64}$/.test(value.sourceSha256) || typeof value.png !== "string" || value.png.indexOf("data:image/png;base64,") !== 0 || ["costume", "skin", "paint"].indexOf(value.kind) < 0) return Promise.reject(new Error("Invalid texture recipe."));
        identities.add(identity);
      }
      var ready = refresh();
      pendingRestore = rows.map(function (row) { return Object.assign({}, row, { texture: Object.assign({}, row.texture) }); }); var retained = pendingRestore, born = epoch, plans = [];
      loading++; refreshButtons();
      return ready.then(function () {
        var chain = Promise.resolve();
        rows.forEach(function (row) { chain = chain.then(function () {
          if (born !== epoch) throw abort();
          var record = catalogue.filter(function (r) { return same(r.texture, row.texture); })[0]; if (!record) throw new Error("The texture source changed. Reload the original model.");
          return load(record).then(function (entry) {
            if (born !== epoch) throw abort(); if (entry.sourceSha256 !== row.sourceSha256) throw new Error("The texture source changed. Reload the original model.");
            var layerRows = entry.engine.getLayers ? entry.engine.getLayers() : [], flatBase = !layerRows.length || layerRows.length === 1 && layerRows[0].visible && layerRows[0].opacity === 1;
            if (entry.png === row.png && !entry.encoding && !entry.preview && flatBase && !floating(entry)) { plans.push({ entry: entry, row: row, image: entry.engine.getImage(false), same: true }); return; }
            return decodePatch(entry, row.png).then(function (image) {
              if (born !== epoch) throw abort();
              if (image.width !== entry.original.width || image.height !== entry.original.height) throw new Error("Texture dimensions must match the original.");
              plans.push({ entry: entry, row: row, image: image });
            });
          });
        }); });
        return chain;
      }).then(function () {
        if (born !== epoch || pendingRestore !== retained) throw abort();
        cancelPreview(); var wanted = new Set(plans.map(function (p) { return key(p.entry.record.texture); }));
        entries.forEach(function (entry) { if (entry.engine) { suppressed++; try { if (floating(entry)) entry.engine.cancelFloating(); entry.engine.setTool(entry.engine.getState().tool); } finally { suppressed--; } } });
        entries.forEach(function (entry) {
          if (entry.standalone) return;
          entry.encodeGeneration = (entry.encodeGeneration || 0) + 1; entry.encoding = false; entry.encodeError = null;
          if (wanted.has(key(entry.record.texture))) return;
          if (entry.engine && entry.original) { suppressed++; try { replaceImage(entry, entry.original, { label: "Restore original texture" }); } finally { suppressed--; } }
          entry.savedProject = null; entry.png = null; entry.modified = false; entry.preview = null; restoreLive(entry);
        });
        plans.forEach(function (plan) {
          var entry = plan.entry;
          if (!plan.same) { suppressed++; try { replaceImage(entry, plan.image, { label: "Restore texture" }); } finally { suppressed--; } }
          entry.png = plan.row.png; entry.kind = plan.row.kind || "paint"; entry.modified = !equalPixels(plan.image, entry.original); upload(entry);
        });
        pendingRestore = null; evict(); updateOverlay(); changed();
      }).catch(function (err) {
        if (born === epoch && pendingRestore === retained) { pendingRestore = null; evict(); changed(); }
        if (err.name !== "AbortError" && born === epoch) say("", err.message); throw err;
      }).finally(function () { if (born === epoch) loading = Math.max(0, loading - 1); refreshButtons(); });
    }
    function handleShortcut(event) {
      if (!active || !active.engine || event.defaultPrevented || loading || !canEdit(active)) return false;
      if (event.target && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return false;
      if (!section.contains(event.target) && sceneMode === "orbit") return false;
      return active.engine.handleShortcut(event);
    }
    listen(textureSelect, "change", function () { var record = catalogue.filter(function (r) { return key(r.texture) === textureSelect.value; })[0]; if (record) selectTexture(record.texture).catch(function () {}); });
    listen(sceneSelect, "change", function () { setSceneMode(sceneSelect.value); });
    listen(selectTool, "change", function () { cancelPreview(); if (active && active.engine) active.engine.setTool(selectTool.value); refreshToolstrip(); });
    listen(selectionMode, "change", syncBrush); listen(paintTool, "change", function () { cancelPreview(); selectCanvasTool(); });
    listen(layerName, "change", function () { var name = layerName.value; layerOperation(function () { var state = active.engine.getState(); return active.engine.renameLayer(state.activeLayerId || state.activeLayer, name); }); });
    listen(layerOpacity, "input", function () { layerOpacityValue.textContent = Math.round(+layerOpacity.value) + "%"; });
    listen(layerOpacity, "change", function () { var value = +layerOpacity.value / 100; layerOperation(function () { var state = active.engine.getState(); return active.engine.setLayerOpacity(state.activeLayerId || state.activeLayer, value); }); });
    listen(colorMode, "change", function () { targetLabel.hidden = colorMode.value !== "colorize"; schedulePreview(); }); listen(targetColor, "input", schedulePreview);
    [sourceTone, targetTone].forEach(function (item) { listen(item, "change", schedulePreview); });
    [connected, sampleGate].forEach(function (item) { listen(item, "change", function () { syncBrush(); if (active && active.seeds.length) growSelection(active); }); });
    [paintColor, paintAlpha, filled].forEach(function (item) { listen(item, "input", syncBrush); });
    listen(compare, "change", function () { if (active) { if (active.engine) { if (active.engine.setDisplayOverride) active.engine.setDisplayOverride(compare.checked ? active.original : null); else active.engine.setPreviewImage(compare.checked ? active.original : active.preview); } upload(active); } });
    listen(showUV, "change", function () { if (active && active.engine) active.engine.render(); });
    listen(showSelection, "change", function () { selectionAutoHidden = false; syncSelectionDisplay(); });
    var faceToggle = document.getElementById("viewer-mod-include-face"); if (faceToggle) listen(faceToggle, "change", updateInformation);
    listen(fileInput, "change", function () { var file = fileInput.files && fileInput.files[0]; fileInput.value = ""; importPNG(file).catch(function (err) { say("", err.message); }); });
    listen(projectFile, "change", function () { var file = projectFile.files && projectFile.files[0]; projectFile.value = ""; importProject(file).catch(function (err) { if (err.name !== "AbortError") say("", err.message); }); });
    listen(section, "toggle", function () { if (section.open) { refresh(); if (active && active.engine) { active.engine.fit(); updateOverlay(); } } else { setSceneMode("orbit"); removeOverlays(); setExpanded(false); } });
    listen(document, "keydown", function (event) {
      if (event.defaultPrevented) return;
      if (floating(active) && (event.key === "Escape" || event.key === "Enter") && section.contains(event.target)) { clipboardAction(event.key === "Escape" ? "cancelFloating" : "commitFloating"); event.preventDefault(); event.stopPropagation(); return; }
      if (event.code === "Space" && !/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) space = true;
      if (event.key === "Escape" && expanded) { setExpanded(false); event.preventDefault(); }
    });
    ["fullscreenchange", "webkitfullscreenchange"].forEach(function (name) { listen(document, name, function () { if (global.requestAnimationFrame) global.requestAnimationFrame(positionExpandedEditor); else positionExpandedEditor(); }); });
    listen(document, "keyup", function (event) { if (event.code === "Space") space = false; });
    listen(global, "blur", function () { space = false; if (pointer) { if (pointer.controls) pointer.controls.enabled = pointer.enabled; if (sceneElement && sceneElement.hasPointerCapture && sceneElement.hasPointerCapture(pointer.id)) { try { sceneElement.releasePointerCapture(pointer.id); } catch (_) {} } pointer = null; } if (brushStroke) cancelModelBrush(); modelCursor.hidden = true; });
    setTab("costume"); say("Open a model to edit textures.");
    return {
      getEdits: getEdits, restoreEdits: restoreEdits, captureDocuments: captureDocuments, restoreDocuments: restoreDocuments, prepareModelRebind: prepareModelRebind, commitModelRebind: commitModelRebind, hasPending: hasPending, getRevision: function () { return revision; }, refresh: refresh, reset: reset,
      beforeModelDispose: function (rebind) { if (rebind) detachModelForRebind(rebind); else reset(true, true); }, beforeRender: function () { attachScene(); if (lastEditable !== (!active || canEdit(active))) refreshButtons(); flushLiveUpdate(); overlays.forEach(function (row) { row.mesh.geometry = row.original.geometry; row.mesh.morphTargetInfluences = row.original.morphTargetInfluences; row.mesh.morphTargetDictionary = row.original.morphTargetDictionary; }); },
      getState: function () { return { available: !!currentToken || !!(active && active.standalone), token: currentToken, activeTexture: active ? Object.assign({}, active.record.texture) : null, activeTab: activeTab, sceneMode: sceneMode, standalone: !!(active && active.standalone), expanded: expanded, pending: hasPending(), loading: loading, preview: !!(active && active.preview), revision: revision, editedTextures: getEdits().map(function (row) { return { texture: row.texture, kind: row.kind }; }), textureCount: catalogue.length, sourceSha256: active && active.sourceSha256 || "", selection: active && active.engine ? active.engine.getState() : null, lastModelSelection: active && active.lastModelSelection || null, lastUVSelection: active && active.lastUVSelection || null, workspace: { inspectorOpen: workspace.inspector.open, preferences: Object.assign({}, workspacePreferences) }, status: statusText, error: error, performance: Object.assign({ loadedTextureBytes: Array.from(entries.values()).reduce(function (total, entry) { return total + entryBytes(entry); }, 0), loadedEngines: Array.from(entries.values()).filter(function (entry) { return !!entry.engine; }).length }, performance) }; },
      getSceneMode: function () { return sceneMode; }, canClearSelection: canClearSelection, clearSelection: clearSelection, setCanvasTool: setCanvasTool, undo: undo, redo: redo, handleShortcut: handleShortcut, selectTexture: selectTexture, setTab: setTab, setSceneMode: setSceneMode, selectFaces: selectFaces, preparePreview: preparePreview, applyPreview: applyPreview, cancelPreview: cancelPreview, importPNG: importPNG, importPNGPath: importPNGPath, exportPNG: exportPNG, openPaint: openPaint, openImage: openImage, setExpanded: setExpanded,
      openProject: openProject, openProjectPath: openProjectPath, importProject: importProject, saveProject: saveProject, getProject: function (copy) { return active && active.engine && active.engine.getProject ? active.engine.getProject(copy !== false) : null; },
      changeLayer: changeLayer, clipboardAction: clipboardAction,
      updateLanguage: function () { labels.forEach(function (pair) { pair[0].textContent = t(pair[1]); }); units.forEach(function (pair) { pair[0].textContent += pair[1]; }); expandButton.textContent = t(expanded ? "Collapse editor" : "Expand editor"); toolButtons.forEach(function (item) { item.node.title = t(item.name); item.node.setAttribute("aria-label", t(item.name)); }); section.querySelectorAll(".viewer-texture-icon-button:not(.viewer-texture-svg-button)").forEach(function (item) { item.title = item.textContent; }); workspace.settingsButton.setAttribute("aria-label", t("Color and layers")); showSelection.parentNode.title = t("Color adjustments hide selection tint without clearing the selection."); workspace.resizer.setAttribute("aria-label", t("Resize texture canvas")); workspace.dockResizer.setAttribute("aria-label", t("Resize tool settings")); if (uvControl) uvControl.updateLanguage(); updateInformation(); updateTone(); refreshButtons(); if (statusText || error) say(statusText, error); },
      dispose: function () { if (disposed) return; reset(false, true); disposed = true; listeners.forEach(function (remove) { remove(); }); finishPickerStack(); if (expanded) setExpanded(false); if (uvControl) uvControl.dispose(); if (processor) processor.dispose(); modelCursor.remove(); section.remove(); }
    };
  }
  var exported = { create: create, key: key, sameIdentity: same, equalPixels: equalPixels, sampledUv: sampledUv, triangleCopies: triangleCopies, rasterTriangle: rasterTriangle, rasterFaces: rasterFaces, stampMaskCircle: stampMaskCircle, brushMask: brushMask };
  global.ViewerTextureTools = exported;
  if (typeof module === "object" && module.exports) module.exports = exported;
}(typeof window !== "undefined" ? window : globalThis));
