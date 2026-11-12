/* Signed numeric entry without changing native number validation or model state. */
(function (global) {
  "use strict";
  var entries = new WeakMap(), observer = null;
  var words = { "Change sign": ["부호 바꾸기", "符号を切り替え"], "Change sign of": ["부호 바꾸기:", "符号を切り替え:"] };
  function text(key) {
    var language = (document.documentElement.lang || "en").split("-")[0];
    return words[key] && (language === "ko" || language === "ja") ? words[key][language === "ko" ? 0 : 1] : key;
  }
  function signed(input) {
    return input && input.type === "number" && input.hasAttribute("min") && isFinite(Number(input.min)) && Number(input.min) < 0;
  }
  function fieldName(input) {
    var label = input.closest("label"), first = label && label.querySelector("span:not(.viewer-signed-number-entry)");
    return input.getAttribute("aria-label") || first && first.textContent.trim() || input.id || "";
  }
  function nextValue(input) {
    if (input.validity.badInput) return null;
    var raw = input.value.trim(), value = raw ? Number(raw) : 0;
    if (!isFinite(value)) return null;
    var next = value === 0 ? raw.charAt(0) === "-" ? "0" : "-0" : String(-value);
    // A detached native number input checks min/max/required/step without
    // copying application-level custom errors that a sign change can repair.
    var probe = input.cloneNode(false); probe.removeAttribute("id"); probe.disabled = false; probe.readOnly = false;
    probe.value = next;
    return probe.checkValidity() ? next : null;
  }
  function update(input) {
    var entry = entries.get(input); if (!entry || !entry.button) return;
    var disabled = input.disabled || input.matches(":disabled") || input.readOnly || !signed(input);
    if (entry.button.disabled !== disabled) entry.button.disabled = disabled;
    var name = fieldName(input), label = text("Change sign of") + (name ? " " + name : "");
    var title = text("Change sign");
    if (entry.button.title !== title) entry.button.title = title;
    if (entry.button.getAttribute("aria-label") !== label) entry.button.setAttribute("aria-label", label);
  }
  function observe() {
    if (observer || !global.MutationObserver) return;
    observer = new MutationObserver(function (records) {
      var changed = new Set();
      records.forEach(function (record) {
        if (entries.has(record.target)) changed.add(record.target);
        else if (record.attributeName === "lang" || record.target.tagName === "FIELDSET") {
          record.target.querySelectorAll("input[data-viewer-signed-number]").forEach(function (input) { changed.add(input); });
        }
      });
      changed.forEach(update);
    });
    observer.observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ["disabled", "readonly", "min", "max", "step", "lang"] });
  }
  function attach(input, options) {
    options = options || {};
    if (!signed(input)) return null;
    if (entries.has(input)) return entries.get(input);
    input.inputMode = "text";
    input.dataset.viewerSignedNumber = "true";
    var entry = { input: input, button: null };
    entries.set(input, entry);
    if (options.signButton === false) return entry;
    var parent = input.parentNode;
    if (!parent) return entry;
    var group = document.createElement("span"), button = document.createElement("button");
    group.className = "viewer-signed-number-entry";
    if (options.width) group.style.width = options.width;
    parent.insertBefore(group, input); group.appendChild(input);
    button.type = "button"; button.className = "viewer-number-sign"; button.textContent = "±";
    group.appendChild(button); entry.button = button;
    // Keep the active number field and soft keyboard focused when using ±.
    button.addEventListener("pointerdown", function (event) { event.preventDefault(); });
    button.addEventListener("click", function () {
      if (button.disabled || input.disabled || input.matches(":disabled") || input.readOnly) return;
      var next = nextValue(input);
      if (next === null) { input.focus(); input.reportValidity(); return; }
      var previous = input.value, sameNumber = previous.trim() && Number(previous) === Number(next);
      input.value = next;
      // 0 ↔ -0 is only a typing prefix; do not create an authoring edit.
      if (!sameNumber) {
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      update(input);
      try { input.focus({ preventScroll: true }); } catch (_) { input.focus(); }
    });
    input.addEventListener("input", function () { update(input); });
    input.addEventListener("change", function () { update(input); });
    input.addEventListener("focus", function () { update(input); });
    update(input); observe();
    return entry;
  }
  global.ViewerSignedInputs = { attach: attach };
})(typeof window !== "undefined" ? window : globalThis);
