/* One display preference for UV overlays; never changes model/texture bytes. */
(function (global) {
  "use strict";
  var key = "elichika.viewer.uv-color.v1", value = "#ebf5ff", eventName = "elichika-uv-color";
  function valid(color) { return typeof color === "string" && /^#[0-9a-f]{6}$/i.test(color); }
  try { var stored = global.localStorage.getItem(key); if (valid(stored)) value = stored.toLowerCase(); } catch (_) {}
  function set(color) {
    if (!valid(color) || color.toLowerCase() === value) return;
    value = color.toLowerCase();
    try { global.localStorage.setItem(key, value); } catch (_) {}
    global.dispatchEvent(new CustomEvent(eventName));
  }
  function stroke(alpha) {
    return "rgba(" + [1, 3, 5].map(function (index) { return parseInt(value.slice(index, index + 2), 16); }).join(",") + "," + alpha + ")";
  }
  function control(parent, options) {
    var translate = options.translate || function (text) { return text; };
    var label = document.createElement("label"), title = document.createElement("span"), input = document.createElement("input");
    label.className = "viewer-uv-color-control"; title.dataset.i18n = "UV line color";
    input.type = "color"; input.value = value; input.id = options.id;
    label.appendChild(title); label.appendChild(input); parent.appendChild(label);
    function language() { title.textContent = translate("UV line color"); input.setAttribute("aria-label", title.textContent); }
    function changed() { input.value = value; if (options.onChange) options.onChange(value); }
    function inputChanged() { set(input.value); }
    input.addEventListener("input", inputChanged); global.addEventListener(eventName, changed); language();
    return { updateLanguage: language, dispose: function () { input.removeEventListener("input", inputChanged); global.removeEventListener(eventName, changed); label.remove(); } };
  }
  global.ViewerUVColor = { get: function () { return value; }, set: set, stroke: stroke, control: control };
}(window));
