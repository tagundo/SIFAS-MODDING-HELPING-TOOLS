/* Shared panel preferences. Keep the standalone adminui/ui copy identical. */
(function () {
  "use strict";
  var words = {
    "Panel settings": ["칸 설정", "パネル設定"],
    "Choose visible panels and their order.": ["표시할 칸을 선택하고 순서를 바꿀 수 있습니다.", "表示するパネルと順序を設定できます。"],
    "Changes are saved on this device.": ["설정은 이 기기에 자동으로 저장됩니다.", "設定はこの端末に自動保存されます。"],
    "Could not save settings on this device.": ["이 기기에 설정을 저장할 수 없습니다.", "この端末に設定を保存できません。"],
    "Move up": ["위로 이동", "上へ移動"], "Move down": ["아래로 이동", "下へ移動"],
    "Restore defaults": ["기본 설정 복원", "初期設定に戻す"], "Close": ["닫기", "閉じる"],
    "3D model": ["3D 모델", "3Dモデル"], "Tools": ["에셋 편집 도구", "アセット編集ツール"],
    "Server content": ["서버 콘텐츠", "サーバーコンテンツ"],
    "Texture editor": ["텍스쳐 편집기", "テクスチャエディター"]
  };
  function language() {
    var select = document.getElementById("lang-select");
    return select && select.value || document.documentElement.lang || "en";
  }
  function text(key) {
    var index = { ko: 0, ja: 1 }[language()];
    return words[key] && index !== undefined ? words[key][index] : key;
  }
  function element(tag, className, value) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }
  function title(node) {
    if (node.getAttribute("data-panel-title")) return text(node.getAttribute("data-panel-title"));
    var summary = node.querySelector(":scope > summary");
    return (summary || node).textContent.trim();
  }
  function installStyle() {
    var style = element("style");
    style.textContent = ".panel-setting-hidden{display:none!important}" +
      ".panel-settings-toolbar{flex:0 0 auto}.panel-settings-toolbar>button{width:100%;min-height:44px;padding:8px 10px;border:1px solid var(--accent,#3b6fd4);border-radius:8px;background:var(--panel2,#eee);color:var(--text,#222);font:inherit;font-size:14px;cursor:pointer}.panel-settings-toolbar>button:focus-visible{outline:2px solid var(--accent,#3b6fd4);outline-offset:2px}" +
      ".panel-settings-dialog{box-sizing:border-box;width:min(520px,calc(100vw - 24px));max-height:min(760px,calc(100dvh - 32px));overflow:auto;background:var(--panel,#fff);color:var(--text,#222);border:1px solid var(--line,#ccc);border-radius:14px;padding:18px}" +
      ".panel-settings-dialog::backdrop{background:rgba(0,0,0,.5)}.panel-settings-dialog h2{font-size:18px;margin:0 0 10px}.panel-settings-dialog p{font-size:14px;line-height:1.5;margin:8px 0;color:var(--muted,#666)}" +
      ".panel-settings-dialog h3{font-size:13px;margin:18px 0 6px;color:var(--muted,#666)}.panel-settings-dialog ul{list-style:none;padding:0;margin:0}" +
      ".panel-settings-dialog li{display:flex;align-items:center;gap:6px;border-bottom:1px solid var(--line,#ccc);min-height:50px}.panel-settings-dialog label{display:flex;align-items:center;gap:10px;flex:1;min-width:0;min-height:44px;cursor:pointer;font-size:14px;overflow-wrap:anywhere}" +
      ".panel-settings-dialog input{width:18px;height:18px;flex:0 0 auto;accent-color:var(--accent,#3b6fd4)}.panel-settings-dialog button{background:var(--panel2,#eee);color:var(--text,#222);border:1px solid var(--line,#ccc);border-radius:8px;min-width:44px;min-height:44px;padding:7px 10px;cursor:pointer;font:inherit}" +
      ".panel-settings-dialog button:disabled{opacity:.35;cursor:default}.panel-settings-actions{display:flex;gap:10px;justify-content:space-between;margin-top:16px;flex-wrap:wrap}.panel-settings-save-error{color:var(--err,#a00)!important}";
    document.head.appendChild(style);
  }
  var nativeSequence = 0;
  function nativeHost() {
    var description = window.ElichikaDesktop;
    var handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.elichika;
    try {
      return window.top === window.self && location.protocol === "http:" &&
        ["127.0.0.1", "localhost"].indexOf(location.hostname) >= 0 && description &&
        description.platform === "macos" && description.version === 1 &&
        Array.isArray(description.capabilities) && description.capabilities.indexOf("setPanelSettings") >= 0 &&
        handler && typeof handler.postMessage === "function" ? { description: description, handler: handler } : null;
    } catch (_) { return null; }
  }
  function validSettings(value) {
    return !!value && !Array.isArray(value) && Object.keys(value).sort().join(",") === "hidden,order" &&
      [value.hidden, value.order].every(function (values) {
        return Array.isArray(values) && values.length <= 256 && values.every(function (id, index) {
          return typeof id === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(id) && values.indexOf(id) === index;
        });
      });
  }
  function attach(options) {
    var scope = options.key.split(".")[2], native = nativeHost();
    var saved = { hidden: [], order: [] }, defaults = new Map(), nextDefault = 0, refreshing = false;
    var items = [], groups = [], dialog = null, opener = null, observer, saveFailed = false;
    var raw = null;
    try { raw = JSON.parse(localStorage.getItem(options.key)); } catch (_) { /* Native bootstrap can still restore preferences. */ }
    if (!validSettings(raw) && native) raw = (native.description.panelSettings || {})[scope];
    if (validSettings(raw)) saved = { hidden: raw.hidden.slice(), order: raw.order.slice() };
    function persist() {
      try { localStorage.setItem(options.key, JSON.stringify(saved)); saveFailed = false; }
      catch (_) { saveFailed = true; }
      if (!native) return;
      var payload = { panelScope: scope, panelSettings: JSON.parse(JSON.stringify(saved)) };
      if (window.ElichikaPlatform && window.ElichikaPlatform.supports("setPanelSettings")) {
        window.ElichikaPlatform.request("setPanelSettings", payload).then(function () {
          saveFailed = false; updateStatus();
        }, function () { saveFailed = true; updateStatus(); });
      } else {
        // Server content is a standalone WebUI without the model-viewer adapter.
        // The native receiver still validates its top frame, origin and payload.
        try {
          native.handler.postMessage({ id: "panel-settings-" + (++nativeSequence), action: "setPanelSettings",
            panelScope: payload.panelScope, panelSettings: payload.panelSettings });
          saveFailed = false;
        } catch (_) { saveFailed = true; }
      }
    }
    function collect() {
      items = options.items(); groups = [];
      items.forEach(function (item, index) {
        if (!defaults.has(item.id)) {
          var following = items.slice(index + 1).find(function (next) { return next.node.parentNode === item.node.parentNode && defaults.has(next.id); });
          var previous = items.slice(0, index).reverse().find(function (next) { return next.node.parentNode === item.node.parentNode && defaults.has(next.id); });
          var before = previous && defaults.get(previous.id), after = following && defaults.get(following.id);
          defaults.set(item.id, following ? previous && before < after ? (before + after) / 2 : after - .5 : nextDefault++);
        }
        var group = groups.find(function (value) { return value.parent === item.node.parentNode; });
        if (!group) {
          group = { parent: item.node.parentNode, label: item.group || options.label, items: [] };
          groups.push(group);
        }
        group.items.push(item);
      });
    }
    function apply() {
      groups.forEach(function (group) {
        var ordered = group.items.slice().sort(function (a, b) {
          var first = saved.order.indexOf(a.id), second = saved.order.indexOf(b.id);
          return (first < 0 ? saved.order.length + defaults.get(a.id) : first) -
            (second < 0 ? saved.order.length + defaults.get(b.id) : second);
        });
        if (ordered.some(function (item, index) { return item !== group.items[index]; })) {
          // Retain non-panel siblings, values, event listeners and focusable fields.
          var slots = group.items.map(function (item) {
            var slot = document.createComment("panel position");
            group.parent.replaceChild(slot, item.node); return slot;
          });
          ordered.forEach(function (item, index) { group.parent.replaceChild(item.node, slots[index]); });
          group.items = ordered;
        }
        group.items.forEach(function (item) { item.node.classList.toggle("panel-setting-hidden", saved.hidden.indexOf(item.id) !== -1); });
      });
    }
    function saveOrder() {
      var current = [].concat.apply([], groups.map(function (group) { return group.items.map(function (item) { return item.id; }); }));
      saved.order = current.concat(saved.order.filter(function (id) { return current.indexOf(id) < 0; }));
      persist();
    }
    function refresh() {
      if (refreshing) return;
      refreshing = true;
      if (observer) observer.disconnect();
      if (options.toolbar && !options.toolbar.isConnected) options.toolbarHome.insertBefore(options.toolbar, options.toolbarHome.firstChild);
      collect(); apply();
      options.button.textContent = text("Panel settings");
      options.button.setAttribute("aria-label", text("Panel settings") + " · " + text(options.label));
      if (dialog && dialog.open) render();
      if (observer) observer.observe(options.root, { childList: true, subtree: true });
      refreshing = false;
    }
    function render(focusId, moveDirection) {
      var scrollTop = dialog.scrollTop;
      dialog.textContent = "";
      var heading = element("h2", "", text("Panel settings") + " · " + text(options.label));
      heading.id = options.dialogId + "-title"; dialog.appendChild(heading);
      dialog.appendChild(element("p", "", text("Choose visible panels and their order.")));
      groups.forEach(function (group, groupIndex) {
        if (groups.length > 1) dialog.appendChild(element("h3", "", group.label));
        var list = element("ul");
        group.items.forEach(function (item, index) {
          var row = element("li"), label = element("label"), checkbox = element("input");
          row.dataset.panelId = item.id;
          checkbox.type = "checkbox"; checkbox.checked = saved.hidden.indexOf(item.id) < 0;
          checkbox.addEventListener("change", function () {
            saved.hidden = saved.hidden.filter(function (id) { return id !== item.id; });
            if (!checkbox.checked) saved.hidden.push(item.id);
            item.node.classList.toggle("panel-setting-hidden", !checkbox.checked); persist();
            updateStatus();
          });
          label.appendChild(checkbox); label.appendChild(element("span", "", item.label)); row.appendChild(label);
          ["up", "down"].forEach(function (direction) {
            var move = element("button", "", direction === "up" ? "↑" : "↓");
            move.type = "button"; move.dataset.move = direction;
            move.setAttribute("aria-label", text(direction === "up" ? "Move up" : "Move down") + " · " + item.label);
            move.disabled = direction === "up" ? index === 0 : index === group.items.length - 1;
            move.addEventListener("click", function () {
              var target = index + (direction === "up" ? -1 : 1);
              var swapped = group.items[target]; group.items[target] = item; group.items[index] = swapped;
              saveOrder(); refresh(); render(item.id, direction);
            });
            row.appendChild(move);
          });
          list.appendChild(row);
        });
        dialog.appendChild(list);
      });
      dialog.appendChild(element("p", "panel-settings-save-status")); updateStatus();
      var actions = element("div", "panel-settings-actions"), reset = element("button", "", text("Restore defaults")), close = element("button", "", text("Close"));
      reset.type = close.type = "button";
      reset.addEventListener("click", function () { saved = { hidden: [], order: [] }; persist(); refresh(); });
      close.addEventListener("click", function () { dialog.close(); });
      actions.appendChild(reset); actions.appendChild(close); dialog.appendChild(actions);
      if (focusId) {
        var row = Array.prototype.find.call(dialog.querySelectorAll("li"), function (candidate) { return candidate.dataset.panelId === focusId; });
        var control = row && row.querySelector("button[data-move='" + moveDirection + "']");
        if (control && control.disabled) control = row.querySelector("input");
        if (control) control.focus({ preventScroll: true });
      }
      dialog.scrollTop = scrollTop;
    }
    function updateStatus() {
      var status = dialog && dialog.querySelector(".panel-settings-save-status");
      if (status) {
        status.textContent = text(saveFailed ? "Could not save settings on this device." : "Changes are saved on this device.");
        status.classList.toggle("panel-settings-save-error", saveFailed); status.setAttribute("role", "status");
      }
    }
    options.button.addEventListener("click", function () {
      refresh(); opener = document.activeElement;
      if (!dialog) {
        dialog = element("dialog", "panel-settings-dialog"); dialog.id = options.dialogId;
        dialog.setAttribute("aria-labelledby", options.dialogId + "-title");
        dialog.addEventListener("close", function () { if (opener && opener.isConnected) opener.focus({ preventScroll: true }); });
        (options.dialogHome || document.body).appendChild(dialog);
      }
      render(); dialog.showModal();
    });
    refresh();
    var pending = false;
    observer = new MutationObserver(function (records) {
      // Motion timers and changing numeric readouts are not panel additions.
      // Keep preference work out of the animation frame path.
      var changed = records.some(function (record) {
        if (record.target === options.root) return true;
        return Array.prototype.some.call(record.addedNodes, isPanelTree) ||
          Array.prototype.some.call(record.removedNodes, isPanelTree);
      });
      if (pending || !changed) return;
      pending = true; queueMicrotask(function () { pending = false; refresh(); });
    });
    observer.observe(options.root, { childList: true, subtree: true });
    function isPanelTree(node) {
      return node.nodeType === 1 && (node.matches("details[id],[data-panel-setting][id],button[data-id]") ||
        !!node.querySelector(".viewer-body-card[id],#viewer-shared-bone-editor,[data-panel-setting][id]"));
    }
    var lang = document.getElementById("lang-select");
    if (lang) lang.addEventListener("change", function () { setTimeout(refresh, 0); });
    new MutationObserver(refresh).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
    return { refresh: refresh };
  }
  function init() {
    installStyle();
    var viewer = document.getElementById("viewer-control-panel"), viewerButton = document.getElementById("viewer-panel-settings");
    if (viewer && viewerButton) attach({
      key: "elichika.panels.viewer.v1", label: "3D model", root: viewer, button: viewerButton,
      dialogId: "viewer-panel-settings-dialog", dialogHome: document.getElementById("tab-viewer"),
      items: function () {
        return Array.prototype.map.call(viewer.querySelectorAll(":scope > details[id],.viewer-body-card[id],#viewer-shared-bone-editor > details[id],[data-panel-setting][id]"), function (node) {
          var section = node.closest("[role='tabpanel']"), label = section && document.getElementById(section.getAttribute("aria-labelledby"));
          var parentPanel = node.parentNode.closest("details"), group = label && label.querySelector("span");
          return { id: node.id, node: node, label: title(node), group: group ? group.textContent : parentPanel ? title(parentPanel) : text("3D model") };
        });
      }
    });
    var list = document.getElementById("tool-list");
    if (list) {
      var navigation = list.closest(".tool-navigation"), toolbar = document.getElementById("tools-panel-settings-toolbar");
      if (!navigation) {
        navigation = element("aside", "tool-navigation"); list.parentNode.replaceChild(navigation, list); navigation.appendChild(list);
      }
      if (!toolbar) { toolbar = element("div", "panel-settings-toolbar"); toolbar.id = "tools-panel-settings-toolbar"; navigation.insertBefore(toolbar, list); }
      var button = document.getElementById("tools-panel-settings");
      if (!button) { button = element("button", "panel-settings-button"); button.id = "tools-panel-settings"; toolbar.appendChild(button); }
      button.type = "button";
      function toolbarTop() {
        var header = document.querySelector("body > header"), bottom = header ? header.getBoundingClientRect().bottom : 0;
        navigation.style.setProperty("--tool-navigation-top", Math.max(8, bottom + 8) + "px");
      }
      toolbarTop(); window.addEventListener("resize", toolbarTop, { passive: true });
      if (window.ResizeObserver) { var header = document.querySelector("body > header"); if (header) new ResizeObserver(toolbarTop).observe(header); }
      var content = !document.getElementById("tab-tools");
      attach({ key: "elichika.panels." + (content ? "content" : "tools") + ".v1", label: content ? "Server content" : "Tools",
        root: list, button: button, toolbar: toolbar, toolbarHome: navigation, dialogId: "tools-panel-settings-dialog",
        items: function () {
          return Array.prototype.map.call(list.querySelectorAll(":scope > button[data-id]"), function (node) {
            return { id: node.dataset.id, node: node, label: node.textContent.trim() };
          });
        }
      });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
