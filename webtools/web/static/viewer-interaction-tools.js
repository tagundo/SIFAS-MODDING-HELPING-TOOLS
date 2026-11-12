/* Viewport-local navigation and existing editing modes. No authoring data is copied. */
(function (global) {
  "use strict";
  var words = {
    "3D interaction": ["3D 조작", "3D操作"], "Rotate": ["회전", "回転"],
    "Pan": ["이동", "移動"], "Zoom": ["확대", "ズーム"], "Edit": ["편집", "編集"],
    "Clear selection": ["선택 해제", "選択解除"],
    "Choose an editing tool": ["편집 도구 선택", "編集ツールを選択"],
    "Space: rotate · Shift+Space: pan · Right drag: pan · Wheel/pinch: zoom": ["Space: 회전 · Shift+Space: 이동 · 우클릭 드래그: 이동 · 휠/두 손가락: 확대", "Space: 回転 · Shift+Space: 移動 · 右ドラッグ: 移動 · ホイール/ピンチ: ズーム"],
    "Click again to change the editing tool.": ["다시 누르면 편집 도구를 바꿀 수 있습니다.", "もう一度押すと編集ツールを変更できます。"],
    "Open a model to use editing tools.": ["모델을 열면 편집 도구를 사용할 수 있습니다.", "モデルを開くと編集ツールを使用できます。"]
  };
  function create(options) {
    var stage = options.stage, host = document.createElement("div"), row = document.createElement("div"), menu = document.createElement("div");
    host.id = "viewer-interaction-tools"; host.className = "viewer-interaction-tools"; host.hidden = true; host.dataset.viewerFramingEdge = "left";
    row.className = "viewer-interaction-row"; row.setAttribute("role", "toolbar"); row.setAttribute("aria-orientation", "vertical");
    menu.id = "viewer-interaction-edit-menu"; menu.className = "viewer-interaction-menu"; menu.hidden = true; menu.setAttribute("role", "menu");
    host.append(row, menu); stage.appendChild(host);
    var mode = "orbit", navigation = "orbit", lastEdit = "", temporary = null, changing = false, disposed = false;
    var buttons = {}, removers = [], canvasRemovers = [], canvas = null, boundControls = null, originalControls = null, rowObserver = null;
    var pointers = new Set(), touchZoom = null, rows = [], lastSignature = "", spaceHeld = false, appliedMode = "";
    function t(key) {
      var language = (document.documentElement.lang || "en").split("-")[0];
      if (words[key] && (language === "ko" || language === "ja")) return words[key][language === "ko" ? 0 : 1];
      return options.translate ? options.translate(key) : key;
    }
    function attr(node, name, value) { value = String(value); if (node.getAttribute(name) !== value) node.setAttribute(name, value); }
    function content(node, value) { if (node.textContent !== value) node.textContent = value; }
    function icon(kind) {
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"), path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
      path.setAttribute("d", { orbit: "M13 6A5.5 5.5 0 1 0 13 11M13 2v4H9", pan: "M8 1v14M1 8h14M5 4l3-3 3 3M5 12l3 3 3-3M4 5L1 8l3 3M12 5l3 3-3 3", zoom: "M10.2 10.2L15 15M11 6.5a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0M4 6.5h5M6.5 4v5", edit: "M3 1v12l3.5-3 2 5 2-1-2-4L13 9Z", clear: "M2 5V2h3M7 2h2M11 2h3v3M14 7v2M5 14H2v-3M2 7v2M8 8l6 6M14 8l-6 6" }[kind]);
      path.setAttribute("fill", "none"); path.setAttribute("stroke", "currentColor"); path.setAttribute("stroke-width", "1.3"); path.setAttribute("stroke-linecap", "round"); path.setAttribute("stroke-linejoin", "round"); svg.appendChild(path); return svg;
    }
    function listen(target, name, fn, opts, list) { target.addEventListener(name, fn, opts); (list || removers).push(function () { target.removeEventListener(name, fn, opts); }); }
    function context() { return options.context ? options.context() : {}; }
    function runtime() { return options.getRuntime ? options.getRuntime() : {}; }
    function actions() { return options.getEditActions ? options.getEditActions() : []; }
    function currentEdit(list) { return list.find(function (item) { return item.active && item.key === lastEdit; }) || list.find(function (item) { return item.active; }); }
    function stopMomentum(r) {
      var controls = r.controls, camera = r.camera; if (!controls || !camera || !controls.enableDamping) return;
      var position = camera.position.clone(), target = controls.target.clone(), rotation = camera.quaternion.clone(), zoom = camera.zoom;
      var damping = controls.enableDamping, automatic = controls.autoRotate;
      // r128 retains a small pan/rotation tail after its idle threshold. Clear
      // it before changing tools, while keeping the exact visible camera pose.
      controls.enableDamping = false; controls.autoRotate = false;
      try {
        controls.update(); camera.position.copy(position); controls.target.copy(target); camera.zoom = zoom; camera.updateProjectionMatrix();
        controls.update(); camera.position.copy(position); controls.target.copy(target); camera.quaternion.copy(rotation);
      } finally { controls.enableDamping = damping; controls.autoRotate = automatic; }
    }
    function controlsForNavigation() {
      var r = runtime(), controls = r.controls, THREE = global.THREE;
      if (!controls || !THREE) return;
      if (controls !== boundControls) {
        if (boundControls && originalControls) { boundControls.mouseButtons.LEFT = originalControls.mouse; boundControls.touches.ONE = originalControls.touch; }
        boundControls = controls; originalControls = { mouse: controls.mouseButtons.LEFT, touch: controls.touches.ONE }; appliedMode = "";
      }
      var key = mode + ":" + navigation + (mode === "edit" ? ":" + lastEdit : "");
      if (appliedMode && appliedMode !== key) stopMomentum(r); appliedMode = key;
      controls.mouseButtons.LEFT = navigation === "pan" ? THREE.MOUSE.PAN : navigation === "zoom" ? THREE.MOUSE.DOLLY : THREE.MOUSE.ROTATE;
      controls.touches.ONE = navigation === "pan" ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE;
      if (r.domElement) { var next = mode === "edit" ? "edit" : navigation; if (r.domElement.dataset.viewerNavigation !== next) r.domElement.dataset.viewerNavigation = next; }
    }
    function closeMenu() { if (!menu.hidden) { menu.hidden = true; attr(buttons.edit, "aria-expanded", false); } }
    function chooseNavigation(next, held) {
      if (["orbit", "pan", "zoom"].indexOf(next) < 0 || context().disabled || pointers.size) return false;
      if (!held) temporary = null;
      changing = true;
      try { if (options.leaveEditing) options.leaveEditing(); navigation = next; mode = next; closeMenu(); controlsForNavigation(); }
      finally { changing = false; }
      refresh(); return true;
    }
    function chooseEdit(key) {
      var value = actions().find(function (item) { return item.key === key; });
      if (!value || value.disabled || context().disabled || pointers.size) return false;
      temporary = null; changing = true;
      try { if (options.chooseEdit) options.chooseEdit(key); lastEdit = key; mode = "edit"; closeMenu(); controlsForNavigation(); }
      finally { changing = false; }
      refresh(); return true;
    }
    function menuItems() {
      menu.replaceChildren(); rows = [];
      var list = actions(), lastGroup = "";
      list.forEach(function (item) {
        if (item.group !== lastGroup) { var heading = document.createElement("div"); heading.className = "viewer-interaction-menu-group"; heading.textContent = item.group; menu.appendChild(heading); lastGroup = item.group; }
        var button = document.createElement("button"); button.type = "button"; button.textContent = item.label;
        button.dataset.viewerEditAction = item.key; button.disabled = !!item.disabled; button.setAttribute("role", "menuitemradio");
        button.setAttribute("aria-checked", String(!!item.active)); button.addEventListener("click", function () { chooseEdit(item.key); if (canvas) canvas.focus({ preventScroll: true }); });
        rows.push({ button: button, key: item.key }); menu.appendChild(button);
      });
      if (!list.length) { var empty = document.createElement("p"); empty.textContent = t("Open a model to use editing tools."); menu.appendChild(empty); }
      var help = document.createElement("p"); help.className = "viewer-interaction-help"; help.textContent = t("Space: rotate · Shift+Space: pan · Right drag: pan · Wheel/pinch: zoom"); menu.appendChild(help);
      layout();
    }
    [["orbit", "Rotate", "R"], ["pan", "Pan", "H/G"], ["zoom", "Zoom", "Z"], ["edit", "Edit", "E"], ["clear", "Clear selection", ""]].forEach(function (definition) {
      var button = document.createElement("button"); button.type = "button"; button.id = "viewer-interaction-" + definition[0];
      var label = document.createElement("span"); label.className = "viewer-interaction-label"; button.append(icon(definition[0]), label); button._label = label;
      button.dataset.viewerInteraction = definition[0]; button.setAttribute("data-viewer-hud-control", ""); if (definition[0] !== "clear") button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", function () {
        if (definition[0] === "clear") { if (!button.disabled && options.clearSelection) options.clearSelection(); refresh(); return; }
        if (definition[0] !== "edit") { chooseNavigation(definition[0]); return; }
        if (mode !== "edit" && lastEdit && chooseEdit(lastEdit)) return;
        if (!menu.hidden) closeMenu(); else { menuItems(); menu.hidden = false; attr(button, "aria-expanded", true); layout(); }
      });
      button.dataset.label = definition[1]; button.dataset.shortcut = definition[2]; buttons[definition[0]] = button; row.appendChild(button);
    });
    attr(buttons.edit, "aria-controls", menu.id); attr(buttons.edit, "aria-expanded", false); attr(buttons.edit, "aria-haspopup", "menu");
    function layout() {
      if (host.hidden || !stage.clientWidth || disposed) return;
      var compact = host.classList.contains("viewer-interaction-icons-only");
      if (compact) host.classList.remove("viewer-interaction-icons-only");
      var naturalWidth = 0, railLimit = Math.min(120, Math.max(44, stage.clientWidth * .27));
      Object.keys(buttons).forEach(function (key) { var button = buttons[key], style = getComputedStyle(button), label = button._label;
        var needed = label.scrollWidth + 15 + (parseFloat(style.columnGap) || 0) + (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0) + (parseFloat(style.borderLeftWidth) || 0) + (parseFloat(style.borderRightWidth) || 0);
        naturalWidth = Math.max(naturalWidth, parseFloat(style.minWidth) || 0, needed);
      });
      if (naturalWidth > railLimit) host.classList.add("viewer-interaction-icons-only");
      var maxHeight = Math.max(44, stage.clientHeight - 12) + "px";
      if (row.style.maxHeight !== maxHeight) row.style.maxHeight = maxHeight;
      var rect = stage.getBoundingClientRect(), width = row.getBoundingClientRect().width, height = row.getBoundingClientRect().height;
      var obstacles = [];
      stage.querySelectorAll("[data-viewer-hud-control]").forEach(function (element) {
        if (host.contains(element)) return;
        var box = element.getBoundingClientRect(); if (!box.width || !box.height || getComputedStyle(element).visibility === "hidden") return;
        obstacles.push({ left: box.left - rect.left - 5, right: box.right - rect.left + 5, top: box.top - rect.top - 5, bottom: box.bottom - rect.top + 5 });
      });
      // Keep the rail in the leftmost free column. The existing pose controls
      // retain their top-left space, and a short rail scrolls within the stage.
      function freePosition() {
        var position = null;
        var minimumHeight = Math.min(height, buttons.orbit.getBoundingClientRect().height * 2 + 2);
        var columns = [6].concat(obstacles.map(function (box) { return Math.max(6, Math.ceil(box.right)); })).sort(function (a, b) { return a - b; });
        for (var column = 0; column < columns.length && !position; column++) {
          var x = columns[column]; if (x + width > stage.clientWidth / 2) continue;
          var intervals = obstacles.filter(function (box) { return box.right > x && box.left < x + width; }).sort(function (a, b) { return a.top - b.top; });
          var y = 6, gaps = [];
          intervals.forEach(function (box) { if (box.top > y) gaps.push([y, Math.min(stage.clientHeight - 6, box.top)]); y = Math.max(y, box.bottom); });
          if (y < stage.clientHeight - 6) gaps.push([y, stage.clientHeight - 6]);
          gaps.forEach(function (gap) {
            var visibleHeight = Math.min(height, Math.floor(gap[1] - gap[0]));
            if (visibleHeight < minimumHeight) return;
            var top = Math.max(gap[0], Math.min((stage.clientHeight - visibleHeight) / 2, gap[1] - visibleHeight));
            var score = Math.abs(top + visibleHeight / 2 - stage.clientHeight / 2);
            if (!position || visibleHeight > position.height || visibleHeight === position.height && score < position.score) position = { left: x, top: top, height: visibleHeight, score: score };
          });
        }
        return position;
      }
      var best = freePosition();
      // Labels can fit the whole stage while still covering its existing
      // camera controls. Compact against the actual free gaps, not width alone.
      if (!best) {
        host.classList.add("viewer-interaction-icons-only");
        width = row.getBoundingClientRect().width; height = row.getBoundingClientRect().height;
        best = freePosition();
      }
      if (!best) { if (host.style.visibility !== "hidden") host.style.visibility = "hidden"; return; }
      if (host.style.visibility) host.style.visibility = "";
      var visibleHeight = best.height + "px";
      if (row.style.maxHeight !== visibleHeight) row.style.maxHeight = visibleHeight;
      height = row.getBoundingClientRect().height;
      var left = Math.round(best.left) + "px", top = Math.round(best.top) + "px";
      if (host.style.left !== left) host.style.left = left; if (host.style.top !== top) host.style.top = top;
      var menuLimit = Math.max(44, Math.min(260, stage.clientHeight - 12)), menuHeight = menuLimit + "px";
      if (host.style.getPropertyValue("--viewer-interaction-menu-height") !== menuHeight) host.style.setProperty("--viewer-interaction-menu-height", menuHeight);
      var menuWidth = Math.max(80, Math.min(250, stage.clientWidth - best.left - width - 12)) + "px"; if (menu.style.width !== menuWidth) menu.style.width = menuWidth;
      var edit = buttons.edit.getBoundingClientRect(), menuY = Math.max(6, Math.min(stage.clientHeight - menuLimit - 6, edit.top - rect.top));
      var menuTop = Math.round(menuY - best.top) + "px", menuLeft = Math.round(width + 6) + "px";
      if (menu.style.top !== menuTop) menu.style.top = menuTop; if (menu.style.left !== menuLeft) menu.style.left = menuLeft;
    }
    function finishTouchZoom() { if (touchZoom && touchZoom.controls) touchZoom.controls.enabled = touchZoom.enabled; touchZoom = null; }
    function attachCanvas() {
      var next = runtime().domElement; if (next === canvas) return;
      canvasRemovers.forEach(function (remove) { remove(); }); canvasRemovers = []; finishTouchZoom(); pointers.clear(); canvas = next;
      if (!canvas) return;
      if (!canvas.hasAttribute("tabindex")) canvas.tabIndex = 0;
      listen(canvas, "pointerdown", function (event) {
        pointers.add(event.pointerId); canvas.focus({ preventScroll: true });
        if (pointers.size > 1) { finishTouchZoom(); return; }
        if (navigation === "zoom" && mode !== "edit" && event.pointerType === "touch" && !context().disabled) {
          var r = runtime(); touchZoom = { id: event.pointerId, y: event.clientY, controls: r.controls, enabled: r.controls && r.controls.enabled };
          if (r.controls) r.controls.enabled = false;
          try { canvas.setPointerCapture(event.pointerId); } catch (_) {}
          event.preventDefault(); event.stopImmediatePropagation();
        }
      }, true, canvasRemovers);
      listen(canvas, "pointermove", function (event) {
        if (!touchZoom || touchZoom.id !== event.pointerId || pointers.size !== 1) return;
        var r = runtime(); if (!r.camera || !r.controls) return;
        var factor = Math.exp(Math.max(-2, Math.min(2, (event.clientY - touchZoom.y) * .008))); touchZoom.y = event.clientY;
        var delta = r.camera.position.clone().sub(r.controls.target), distance = delta.length();
        var minimum = Math.max(r.controls.minDistance || 0, r.camera.near * 1.5, 1e-6), maximum = r.controls.maxDistance || Infinity;
        if (distance > 0) r.camera.position.copy(r.controls.target).add(delta.multiplyScalar(Math.max(minimum, Math.min(maximum, distance * factor)) / distance));
        r.controls.update(); if (r.requestRender) r.requestRender(); event.preventDefault(); event.stopImmediatePropagation();
      }, true, canvasRemovers);
      ["pointerup", "pointercancel", "lostpointercapture"].forEach(function (name) { listen(canvas, name, function (event) { pointers.delete(event.pointerId); if (touchZoom && touchZoom.id === event.pointerId) finishTouchZoom(); if (!pointers.size && !spaceHeld) restoreTemporary(); }, true, canvasRemovers); });
    }
    function viewportFocus(target) { return target === canvas || target === stage || host.contains(target); }
    function typing(target) { return target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)); }
    function restoreTemporary() {
      if (!temporary || pointers.size) return; var before = temporary; temporary = null; navigation = before.navigation;
      if (before.edit && chooseEdit(before.edit)) return; chooseNavigation(before.navigation);
    }
    // Handle viewport shortcuts before document-level paint bindings. A popup
    // Escape closes this chooser without cancelling a separate pixel move.
    listen(global, "keydown", function (event) {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || typing(event.target) || !viewportFocus(event.target) || context().disabled || pointers.size) return;
      if (event.code === "Space") {
        if (event.target !== canvas && event.target !== stage) return;
        event.preventDefault(); spaceHeld = true; if (!temporary) { var edit = currentEdit(actions()); temporary = { navigation: navigation, edit: edit && edit.key }; chooseNavigation(event.shiftKey ? "pan" : "orbit", true); } return;
      }
      if (event.key === "Escape" && !menu.hidden) { event.preventDefault(); closeMenu(); buttons.edit.focus(); return; }
      if (!menu.hidden && ["ArrowDown", "ArrowUp", "Home", "End"].indexOf(event.key) >= 0) {
        var available = rows.filter(function (item) { return !item.button.disabled; }).map(function (item) { return item.button; });
        if (available.length) { var at = available.indexOf(document.activeElement), nextIndex = event.key === "Home" ? 0 : event.key === "End" ? available.length - 1 : at < 0 ? event.key === "ArrowUp" ? available.length - 1 : 0 : (at + (event.key === "ArrowUp" ? -1 : 1) + available.length) % available.length; available[nextIndex].focus(); event.preventDefault(); }
        return;
      }
      if (!menu.hidden && menu.contains(event.target)) return;
      var key = String(event.key || "").toLowerCase(), next = key === "r" ? "orbit" : key === "h" || key === "g" ? "pan" : key === "z" ? "zoom" : "";
      if (next) { event.preventDefault(); chooseNavigation(next); }
      else if (key === "e") { event.preventDefault(); if (!lastEdit || !chooseEdit(lastEdit)) { menuItems(); menu.hidden = false; attr(buttons.edit, "aria-expanded", true); buttons.edit.focus(); } }
    }, true);
    listen(document, "keyup", function (event) { if (event.code === "Space") { spaceHeld = false; restoreTemporary(); } }, true);
    listen(global, "blur", function () { finishTouchZoom(); pointers.clear(); spaceHeld = false; restoreTemporary(); closeMenu(); });
    listen(document, "pointerdown", function (event) { if (!host.contains(event.target)) closeMenu(); }, true);
    listen(document, "change", function (event) {
      var target = event.target; if (!target || !target.id || !/^(viewer-texture-scene-mode|viewer-mesh-(modify|deleter)-scene-mode|viewer-outline-scene-mode)$/.test(target.id)) return;
      var list = actions(), source = list.find(function (item) { return item.control === target.id && item.active; }); if (source) lastEdit = source.key; refresh();
    });
    listen(document, "focusin", function (event) {
      if (!host.contains(event.target)) closeMenu();
      var panel = event.target.closest && event.target.closest("#viewer-mesh-modify,#viewer-mesh-deleter"); if (!panel) return;
      var source = actions().find(function (item) { return item.panel === panel.id && item.active; }); if (source) { lastEdit = source.key; refresh(); }
    });
    function refresh() {
      if (disposed || changing) return;
      attachCanvas(); var c = context(), list = actions(), edit = currentEdit(list);
      if (!temporary) { if (edit) { mode = "edit"; lastEdit = edit.key; } else if (mode === "edit") mode = navigation; }
      var hidden = !c.loaded; if (host.hidden !== hidden) host.hidden = hidden;
      var disabled = !!c.disabled || !!pointers.size;
      Object.keys(buttons).forEach(function (key) {
        var button = buttons[key], label = t(button.dataset.label), title = label + (button.dataset.shortcut ? " (" + button.dataset.shortcut + ")" : "");
        if (key === "edit" && edit) title += " · " + edit.group + ": " + edit.label + ". " + t("Click again to change the editing tool.");
        content(button._label, label); attr(button, "title", title); attr(button, "aria-label", title); if (key !== "clear") attr(button, "aria-pressed", key === mode);
        var unavailable = disabled || key === "clear" && (!options.canClearSelection || !options.canClearSelection());
        if (button.disabled !== unavailable) button.disabled = unavailable;
      });
      attr(row, "aria-label", t("3D interaction")); controlsForNavigation();
      var signature = [hidden, disabled, mode, document.documentElement.lang].join(":"); if (signature !== lastSignature) { lastSignature = signature; layout(); }
      if (!menu.hidden) rows.forEach(function (entry) { var action = list.find(function (item) { return item.key === entry.key; }); if (action) { attr(entry.button, "aria-checked", !!action.active); if (entry.button.disabled !== !!action.disabled) entry.button.disabled = !!action.disabled; } });
    }
    refresh();
    if (global.ResizeObserver) { rowObserver = new ResizeObserver(layout); rowObserver.observe(row); }
    return { refresh: refresh, refreshLayout: layout, updateLanguage: function () { if (!menu.hidden) menuItems(); refresh(); layout(); },
      setMode: function (next) { return next === "edit" ? !!lastEdit && chooseEdit(lastEdit) : chooseNavigation(next); },
      getState: function () { return { mode: mode, navigation: navigation, edit: lastEdit, temporary: !!temporary, menuOpen: !menu.hidden, pointerCount: pointers.size }; },
      dispose: function () { if (disposed) return; disposed = true; finishTouchZoom(); if (rowObserver) rowObserver.disconnect(); removers.concat(canvasRemovers).forEach(function (remove) { remove(); }); if (boundControls && originalControls) { boundControls.mouseButtons.LEFT = originalControls.mouse; boundControls.touches.ONE = originalControls.touch; } host.remove(); }
    };
  }
  global.ViewerInteractionTools = { create: create };
})(typeof window !== "undefined" ? window : globalThis);
