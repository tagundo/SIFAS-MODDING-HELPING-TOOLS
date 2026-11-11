/* Shared enlargement for existing UV tools and texture preview cards.
 * Elements stay in place: their canvas, selections, undo history and listeners
 * are never cloned/recreated. The texture editor has its own workspace control.
 */
(function (global) {
  "use strict";
  var definitions = [
    { selector: "#viewer-mesh-deleter", canvas: "canvas", kind: "mesh" },
    { selector: "#viewer-mesh-modify", canvas: "canvas", kind: "mesh" },
    { selector: ".viewer-transplant-texture-panel", canvas: "canvas", kind: "donor" },
    { selector: "#gallery-grid .gcard", image: "img", kind: "gallery" }
  ];
  var records = new Map(), active = null, observer = null, languageObserver = null;
  var pending = 0, started = false, backdrop = null, serial = 0;
  var words = {
    "Enlarge texture": ["텍스처 크게 보기", "テクスチャを大きく表示"],
    "Restore size": ["원래 크기로", "元の大きさに戻す"],
    "Tool settings": ["도구 설정", "ツール設定"],
    "Close settings": ["설정 닫기", "設定を閉じる"],
    "Resize texture view": ["텍스처 표시 영역 크기 조절", "テクスチャ表示領域のサイズを変更"],
    "Drag to resize. Arrow keys change height; Home fits the texture.": ["드래그로 크기를 조절합니다. 방향키로 높이를 조절하고 Home으로 맞춥니다.", "ドラッグでサイズを変更。矢印キーで高さを変更し、Homeで全体表示します。"]
  };
  function text(key) {
    var language = (document.documentElement.lang || "en").split("-")[0];
    return words[key] && (language === "ko" || language === "ja") ? words[key][language === "ko" ? 0 : 1] : key;
  }
  function signal(record) {
    var canvas = record.node.querySelector(record.definition.canvas || "__no_canvas__");
    if (canvas) canvas.dispatchEvent(new Event("texturepanechange"));
    document.dispatchEvent(new CustomEvent("texturepanechange", { detail: { target: record.node, expanded: active === record } }));
  }
  function hideCursors() {
    document.querySelectorAll("#viewer-mesh-uv-cursor,.viewer-transplant-brush-cursor").forEach(function (cursor) { cursor.hidden = true; });
  }
  function captureCursors(record) {
    document.querySelectorAll("#viewer-mesh-uv-cursor,.viewer-transplant-brush-cursor").forEach(function (cursor) {
      if (record.node.contains(cursor)) return;
      record.cursorHosts.push({ cursor: cursor, parent: cursor.parentNode, next: cursor.nextSibling });
      record.node.appendChild(cursor);
    });
  }
  function restoreCursors(record) {
    (record.cursorHosts || []).forEach(function (item) {
      if (!item.cursor.isConnected) return;
      if (item.parent && item.parent.isConnected) item.parent.insertBefore(item.cursor, item.next && item.next.parentNode === item.parent ? item.next : null);
      else item.cursor.remove();
    });
    record.cursorHosts = [];
  }
  function updateButton(record) {
    var label = text(active === record ? "Restore size" : "Enlarge texture");
    if (record.button.textContent !== label) record.button.textContent = label;
    if (record.button.getAttribute("aria-label") !== label) record.button.setAttribute("aria-label", label);
    if (record.button.getAttribute("title") !== label) record.button.setAttribute("title", label);
    var expanded = String(active === record), disabled = !!(record.definition.image && !record.node.querySelector(record.definition.image));
    if (record.button.getAttribute("aria-expanded") !== expanded) record.button.setAttribute("aria-expanded", expanded);
    if (record.button.disabled !== disabled) record.button.disabled = disabled;
  }
  function attachWorkspace(record) {
    var workspace = record.node.querySelector('.uv-edit-workspace'), stage = workspace && workspace.querySelector('.uv-canvas-stage');
    if (!stage) return;
    var canvas = stage.querySelector('canvas'), inspector = workspace.querySelector('.uv-edit-inspector'), settings = workspace.querySelector('[data-uv-settings]'), handle = workspace.querySelector('.uv-canvas-resizer');
    if (!canvas || !inspector || !settings || !handle) return;
    var preference = 'elichika.uv-view-height.v1.' + record.node.id, height = 0, scheduled = 0, drag = null, shortLayout = false, moved = [], rail = null;
    try { height = +localStorage.getItem(preference) || 0; } catch (_) {}
    if (!Number.isFinite(height) || height < 180 || height > 900) height = 0;
    var heading = document.createElement('div'), caption = document.createElement('strong'), close = document.createElement('button');
    heading.className = 'uv-inspector-heading'; close.type = 'button'; close.textContent = '×'; heading.append(caption, close); inspector.insertBefore(heading, inspector.firstChild);
    inspector.id = record.node.id + '-settings'; caption.id = record.node.id + '-settings-label'; inspector.setAttribute('aria-labelledby', caption.id); settings.setAttribute('aria-controls', inspector.id);
    function listen(target, type, fn, options) { target.addEventListener(type, fn, options); record.removers.push(function () { target.removeEventListener(type, fn, options); }); }
    function maximum() { return Math.max(220, Math.min(900, Math.floor(global.innerHeight * .85))); }
    function restorePositions() { moved.forEach(function (item) { if (item.marker.parentNode) item.marker.replaceWith(item.node); }); moved = []; if (rail) rail.remove(); rail = null; stage.parentElement.classList.remove('uv-short-columns'); }
    function compactLayout(value) {
      if (shortLayout === value) return;
      if (shortLayout) restorePositions();
      shortLayout = value; workspace.classList.toggle('uv-short-workspace', value);
      if (!value) return;
      function move(node, parent) { if (!node) return; var marker = document.createComment('UV workspace position'); node.parentNode.insertBefore(marker, node); moved.push({ node: node, marker: marker }); parent.appendChild(node); }
      move(workspace.querySelector('.uv-edit-source'), inspector);
      workspace.querySelectorAll('.uv-edit-footer > button').forEach(function (button) {
        button.classList.add(button.classList.contains('mesh-save') ? 'uv-save-button' : 'uv-delete-button'); button.title = button.textContent;
        move(button, workspace.querySelector('.uv-edit-toolbar'));
      });
      if (viewport().width >= 600) {
        var main = stage.parentElement; rail = document.createElement('div'); rail.className = 'uv-short-rail'; main.insertBefore(rail, main.firstChild); main.classList.add('uv-short-columns');
        move(workspace.querySelector('.uv-edit-toolbar'), rail); move(workspace.querySelector('.uv-edit-viewbar'), rail);
        Array.from(main.children).filter(function (node) { return node.classList.contains('viewer-render-note'); }).forEach(function (node) { move(node, rail); });
      }
      accessibleIcons();
    }
    function fit() {
      scheduled = 0;
      if (!stage.isConnected || !stage.getClientRects().length) return;
      compactLayout(active === record && viewport().height < 500 ? viewport().width >= 600 ? 'columns' : 'stack' : false);
      if (active === record) {
        // <details> groups its body in an anonymous box on older WebViews;
        // an explicit remaining height works there as well as in flex layouts.
        var rootRect = record.node.getBoundingClientRect(), workspaceRect = workspace.getBoundingClientRect(), rootStyle = global.getComputedStyle(record.node);
        var available = Math.max(120, Math.floor(rootRect.bottom - workspaceRect.top - (parseFloat(rootStyle.paddingBottom) || 0) - (parseFloat(rootStyle.borderBottomWidth) || 0)));
        if (workspace.style.height !== available + 'px') workspace.style.height = available + 'px';
      } else if (workspace.style.height) workspace.style.removeProperty('height');
      if (active !== record) {
        if (stage.style.flex) stage.style.removeProperty('flex');
        var desired = Math.max(180, Math.min(maximum(), height || stage.clientWidth));
        if (stage.style.height !== desired + 'px') stage.style.height = desired + 'px';
      } else if (!rail) {
        var main = stage.parentElement, siblings = Array.from(main.children).filter(function (node) { return node !== stage && node.getClientRects().length && global.getComputedStyle(node).display !== 'none'; });
        var occupied = siblings.reduce(function (total, node) { return total + node.getBoundingClientRect().height; }, 0) + (parseFloat(global.getComputedStyle(main).rowGap) || 0) * siblings.length;
        var fitted = Math.max(1, Math.floor(Math.min(stage.clientWidth, main.clientHeight - occupied)));
        var flex = '0 0 ' + fitted + 'px'; if (stage.style.flex !== flex) stage.style.flex = flex;
      } else if (stage.style.flex) stage.style.removeProperty('flex');
      var side = Math.max(1, Math.floor(Math.min(stage.clientWidth, stage.clientHeight)));
      if (canvas.style.width !== side + 'px') canvas.style.width = side + 'px';
      if (canvas.style.height !== side + 'px') canvas.style.height = side + 'px';
      var values = { 'aria-valuemin': '180', 'aria-valuemax': String(maximum()), 'aria-valuenow': String(Math.round(stage.clientHeight)) };
      Object.keys(values).forEach(function (key) { if (handle.getAttribute(key) !== values[key]) handle.setAttribute(key, values[key]); });
    }
    function schedule() { if (!scheduled) scheduled = global.requestAnimationFrame(fit); }
    function setHeight(value) {
      height = Math.max(180, Math.min(maximum(), value));
      try { localStorage.setItem(preference, String(Math.round(height))); } catch (_) {}
      schedule();
    }
    function toggle(open) {
      inspector.hidden = !open; workspace.classList.toggle('uv-inspector-open', open); settings.setAttribute('aria-expanded', String(open)); schedule();
      if (!open) settings.focus({ preventScroll: true });
      else close.focus({ preventScroll: true });
    }
    function accessibleIcons() {
      workspace.querySelectorAll('.uv-undo-button,.uv-redo-button,.uv-refresh-button,.uv-save-button,.uv-delete-button,.uv-zoom-out-button,.uv-zoom-in-button,.uv-fit-button,.uv-selection-menu > summary').forEach(function (node) {
        var label = node.textContent.trim(); if (node.getAttribute('aria-label') !== label) node.setAttribute('aria-label', label); if (node.title !== label) node.title = label;
      });
    }
    function language() {
      caption.textContent = text('Tool settings'); close.setAttribute('aria-label', text('Close settings')); close.title = text('Close settings');
      settings.setAttribute('aria-label', text('Tool settings')); settings.title = text('Tool settings'); accessibleIcons();
      handle.setAttribute('aria-label', text('Resize texture view')); handle.title = text('Drag to resize. Arrow keys change height; Home fits the texture.');
    }
    listen(settings, 'click', function (event) { event.preventDefault(); toggle(inspector.hidden); });
    listen(close, 'click', function () { toggle(false); });
    workspace.querySelectorAll('.uv-selection-menu').forEach(function (menu) {
      var content = menu.querySelector('div');
      function placeMenu() {
        if (!menu.open || !rail) return;
        var rect = menu.querySelector('summary').getBoundingClientRect(), bounds = content.getBoundingClientRect(), view = viewport();
        var left = Math.max(view.x + 8, Math.min(rect.left, view.x + view.width - bounds.width - 8));
        var top = Math.max(view.y + 8, Math.min(rect.bottom + 4, view.y + view.height - bounds.height - 8));
        content.style.setProperty('--uv-menu-left', left + 'px'); content.style.setProperty('--uv-menu-top', top + 'px');
      }
      listen(menu, 'click', function (event) { if (event.target.closest('button')) menu.open = false; });
      listen(workspace, 'pointerdown', function (event) { if (menu.open && !menu.contains(event.target)) menu.open = false; });
      listen(menu, 'keydown', function (event) { if (event.key === 'Escape' && menu.open) { event.preventDefault(); event.stopPropagation(); menu.open = false; menu.querySelector('summary').focus(); } });
      listen(menu, 'toggle', placeMenu); listen(workspace, 'scroll', placeMenu, true);
    });
    workspace.querySelectorAll('.uv-edit-viewbar > button').forEach(function (button, index) { if (index < 3) { button.classList.add(['uv-zoom-out-button', 'uv-zoom-in-button', 'uv-fit-button'][index]); button.title = button.textContent; } });
    listen(handle, 'pointerdown', function (event) { if (event.button !== 0 || active === record) return; event.preventDefault(); drag = { id: event.pointerId, y: event.clientY, height: stage.clientHeight }; handle.setPointerCapture(event.pointerId); });
    listen(handle, 'pointermove', function (event) { if (!drag || event.pointerId !== drag.id) return; event.preventDefault(); setHeight(drag.height + event.clientY - drag.y); });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (type) { listen(handle, type, function () { drag = null; }); });
    listen(handle, 'keydown', function (event) {
      if (active === record) return;
      if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); setHeight(stage.clientHeight + (event.key === 'ArrowUp' ? -32 : 32)); }
      else if (event.key === 'Home') { event.preventDefault(); height = 0; try { localStorage.removeItem(preference); } catch (_) {} schedule(); }
    });
    listen(handle, 'dblclick', function () { height = 0; try { localStorage.removeItem(preference); } catch (_) {} schedule(); });
    if (typeof ResizeObserver === 'function') { var observer = new ResizeObserver(schedule); observer.observe(stage); record.removers.push(function () { observer.disconnect(); }); }
    listen(global, 'resize', schedule); listen(record.node, 'toggle', schedule); listen(canvas, 'texturepanechange', schedule);
    record.removers.push(function () { if (scheduled) global.cancelAnimationFrame(scheduled); });
    record.removers.push(restorePositions);
    record.workspace = { layout: schedule, language: language, inspectorOpen: function () { return !inspector.hidden; }, closeInspector: function () { toggle(false); } }; language(); schedule();
  }
  function viewport() {
    var v = global.visualViewport;
    return { x: v ? v.offsetLeft : 0, y: v ? v.offsetTop : 0,
      width: v ? v.width : global.innerWidth, height: v ? v.height : global.innerHeight };
  }
  function resize() {
    if (!active) return;
    var view = viewport(), margin = view.width < 600 ? 8 : 16;
    var style = active.node.style;
    style.setProperty("--texture-pane-left", view.x + margin + "px");
    style.setProperty("--texture-pane-top", view.y + margin + "px");
    style.setProperty("--texture-pane-width", Math.max(1, view.width - margin * 2) + "px");
    style.setProperty("--texture-pane-height", Math.max(1, view.height - margin * 2) + "px");
    signal(active); hideCursors();
  }
  function cancelPointers(record) {
    var canvas = record.node.querySelector(record.definition.canvas || "__no_canvas__");
    if (!canvas) return;
    Array.from(record.pointers.entries()).forEach(function (entry) {
      canvas.dispatchEvent(new PointerEvent("pointercancel", { pointerId: entry[0], pointerType: entry[1] }));
      try { if (canvas.hasPointerCapture(entry[0])) canvas.releasePointerCapture(entry[0]); } catch (_) {}
    });
    record.pointers.clear();
  }
  function restoreAttribute(node, name, value) { if (value === null) node.removeAttribute(name); else node.setAttribute(name, value); }
  function lift(record) {
    var node = record.node;
    record.oldPopover = node.getAttribute("popover"); record.topLayer = false; record.raised = [];
    record.oldRole = node.getAttribute("role"); record.oldModal = node.getAttribute("aria-modal");
    node.setAttribute("role", "dialog"); node.setAttribute("aria-modal", "true");
    if (typeof node.showPopover === "function") {
      try { node.setAttribute("popover", "manual"); node.showPopover(); record.topLayer = true; return; }
      catch (_) { restoreAttribute(node, "popover", record.oldPopover); }
    }
    // Legacy WebViews have no popover top layer. Lift only this ancestor path,
    // and remove its clipping/containing blocks until the workspace closes.
    // The original DOM elements and every inline style are retained/restored.
    for (var parent = node.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      var before = { node: parent, position: parent.style.getPropertyValue("position"), priority: parent.style.getPropertyPriority("position") };
      if (global.getComputedStyle(parent).position === "static") parent.style.setProperty("position", "relative");
      parent.classList.add("texture-pane-overlay-path"); record.raised.push(before);
    }
  }
  function lower(record) {
    if (record.topLayer && typeof record.node.hidePopover === "function") {
      try { record.node.hidePopover(); } catch (_) {}
    }
    restoreAttribute(record.node, "popover", record.oldPopover);
    restoreAttribute(record.node, "role", record.oldRole); restoreAttribute(record.node, "aria-modal", record.oldModal);
    (record.raised || []).forEach(function (before) {
      before.node.classList.remove("texture-pane-overlay-path");
      if (before.position) before.node.style.setProperty("position", before.position, before.priority); else before.node.style.removeProperty("position");
    });
    record.raised = []; record.topLayer = false;
  }
  function collapse(options) {
    if (!active) return;
    options = options || {};
    var record = active; active = null; cancelPointers(record);
    restoreCursors(record); lower(record); record.node.classList.remove("texture-pane-expanded");
    ["left", "top", "width", "height"].forEach(function (name) { record.node.style.removeProperty("--texture-pane-" + name); });
    document.body.style.overflow = record.bodyOverflow;
    if (backdrop) backdrop.hidden = true;
    hideCursors(); updateButton(record); signal(record);
    global.requestAnimationFrame(function () {
      if (options.restoreScroll !== false) {
        record.scroll.forEach(function (item) { if (item.node.isConnected) { item.node.scrollLeft = item.x; item.node.scrollTop = item.y; } });
        global.scrollTo(record.windowScroll.x, record.windowScroll.y);
      }
      if (options.restoreFocus !== false && record.node.isConnected) {
        var focus = record.previousFocus && record.previousFocus.isConnected ? record.previousFocus : record.button;
        try { focus.focus({ preventScroll: true }); } catch (_) { focus.focus(); }
      }
      signal(record);
    });
  }
  function expand(target) {
    var record = typeof target === "string" ? records.get(document.querySelector(target)) : records.get(target);
    if (!record || record.button.disabled) return false;
    if (active === record) return true;
    if (active) collapse({ restoreFocus: false, restoreScroll: false });
    record.previousFocus = document.activeElement; record.scroll = [];
    record.windowScroll = { x: global.scrollX, y: global.scrollY };
    for (var parent = record.node.parentElement; parent; parent = parent.parentElement) {
      record.scroll.push({ node: parent, x: parent.scrollLeft, y: parent.scrollTop });
      if (parent.tagName === "DETAILS") parent.open = true;
    }
    if (record.node.tagName === "DETAILS") record.node.open = true;
    record.bodyOverflow = document.body.style.overflow;
    active = record; record.cursorHosts = []; record.node.classList.add("texture-pane-expanded"); lift(record); captureCursors(record);
    document.body.style.overflow = "hidden";
    backdrop.hidden = false; updateButton(record); resize();
    record.button.focus({ preventScroll: true });
    global.requestAnimationFrame(function () {
      if (active !== record) return;
      signal(record);
      var canvas = record.node.querySelector(record.definition.canvas || "__no_canvas__");
      if (canvas) canvas.scrollIntoView({ block: "center", inline: "nearest" });
    });
    return true;
  }
  function remove(record) {
    if (active === record) collapse({ restoreFocus: false, restoreScroll: false });
    record.removers.forEach(function (removeListener) { removeListener(); });
    record.toolbar.remove(); records.delete(record.node);
  }
  function register(node, definition) {
    if (records.has(node)) return;
    if (!node.id) node.id = "legacy-texture-pane-" + (++serial);
    var toolbar = document.createElement("span"), button = document.createElement("button");
    toolbar.className = "texture-pane-controls"; button.type = "button"; button.className = "texture-pane-expand-button";
    button.setAttribute("aria-controls", node.id); toolbar.appendChild(button);
    var summary = node.tagName === "DETAILS" ? node.querySelector("summary") : null;
    if (summary) summary.appendChild(toolbar); else node.insertBefore(toolbar, node.firstChild);
    var record = { node: node, definition: definition, toolbar: toolbar, button: button, removers: [], pointers: new Map() };
    records.set(node, record); updateButton(record); attachWorkspace(record);
    function listen(target, type, handler, options) {
      target.addEventListener(type, handler, options);
      record.removers.push(function () { target.removeEventListener(type, handler, options); });
    }
    listen(button, "click", function (event) { event.preventDefault(); event.stopPropagation(); if (active === record) collapse(); else expand(node); });
    listen(node, "toggle", function () { if (active === record && node.tagName === "DETAILS" && !node.open) collapse(); });
    var canvas = definition.canvas && node.querySelector(definition.canvas);
    if (canvas) {
      listen(canvas, "pointerdown", function (event) { record.pointers.set(event.pointerId, event.pointerType); }, true);
      ["pointerup", "pointercancel", "lostpointercapture"].forEach(function (type) { listen(canvas, type, function (event) { record.pointers.delete(event.pointerId); }, true); });
    }
    if (definition.image) listen(node, "click", function (event) {
      if (active === record && event.target.closest(".gallery-view-model")) collapse({ restoreFocus: false, restoreScroll: false });
    }, true);
  }
  function refresh() {
    if (!started) return;
    definitions.forEach(function (definition) { document.querySelectorAll(definition.selector).forEach(function (node) { register(node, definition); }); });
    records.forEach(function (record) {
      if (!record.node.isConnected) remove(record);
      else {
        updateButton(record);
        if (active === record) captureCursors(record);
        var ancestorHidden = false;
        for (var parent = record.node.parentElement; active === record && parent; parent = parent.parentElement) {
          if (parent.hidden || global.getComputedStyle(parent).display === "none") { ancestorHidden = true; break; }
        }
        if (active === record && (!record.node.getClientRects().length || record.button.disabled || ancestorHidden)) collapse({ restoreFocus: false, restoreScroll: false });
      }
    });
  }
  function scheduleRefresh() { if (!pending) pending = global.requestAnimationFrame(function () { pending = 0; refresh(); }); }
  function keydown(event) {
    if (active && event.key === "Escape") {
      event.preventDefault(); event.stopImmediatePropagation();
      var menu = active.node.querySelector('.uv-selection-menu[open]');
      if (menu) { menu.open = false; menu.querySelector('summary').focus(); }
      else if (active.workspace && active.workspace.inspectorOpen()) active.workspace.closeInspector();
      else collapse();
    }
    else if (active && event.key === "Tab") {
      var targets = Array.from(active.node.querySelectorAll("button,input,select,textarea,a[href],summary,[tabindex]"))
        .filter(function (target) { return !target.disabled && target.tabIndex >= 0 && target.getClientRects().length; });
      if (!targets.length) return;
      var first = targets[0], last = targets[targets.length - 1], outside = !active.node.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || outside)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || outside)) { event.preventDefault(); first.focus(); }
    }
  }
  function init() {
    if (started || !document.body) return;
    started = true;
    backdrop = document.createElement("div"); backdrop.className = "texture-pane-backdrop"; backdrop.hidden = true;
    backdrop.setAttribute("aria-hidden", "true"); backdrop.addEventListener("click", function () { collapse(); }); document.body.appendChild(backdrop);
    document.addEventListener("keydown", keydown, true); global.addEventListener("resize", resize);
    if (global.visualViewport) { global.visualViewport.addEventListener("resize", resize); global.visualViewport.addEventListener("scroll", resize); }
    observer = new MutationObserver(function (changes) {
      if (changes.some(function (change) { return change.type === "childList" || active && (change.target === active.node || change.target.contains(active.node)); })) scheduleRefresh();
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "class", "open"] });
    languageObserver = new MutationObserver(function () { records.forEach(function (record) { updateButton(record); if (record.workspace) record.workspace.language(); }); });
    languageObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
    refresh();
  }
  function dispose() {
    collapse({ restoreFocus: false }); started = false;
    if (pending) global.cancelAnimationFrame(pending); pending = 0;
    if (observer) observer.disconnect(); if (languageObserver) languageObserver.disconnect();
    document.removeEventListener("keydown", keydown, true); global.removeEventListener("resize", resize);
    if (global.visualViewport) { global.visualViewport.removeEventListener("resize", resize); global.visualViewport.removeEventListener("scroll", resize); }
    Array.from(records.values()).forEach(remove); if (backdrop) backdrop.remove(); backdrop = null;
  }
  global.TexturePanelExpand = { init: init, refresh: refresh, expand: expand, collapse: collapse, dispose: dispose,
    getState: function () { return { expanded: active && active.node.id || "", topLayer: !!(active && active.topLayer), registered: Array.from(records.keys()).map(function (node) { return node.id; }) }; } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})(typeof window !== "undefined" ? window : globalThis);
