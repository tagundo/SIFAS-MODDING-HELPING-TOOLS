/* Original-bound accessory corrections; derived offsets never become body edits. */
(function (global) {
  "use strict";
  function node(id) { return document.getElementById(id); }
  function create(options) {
    var enabled = node("viewer-accessory-enabled"), strength = node("viewer-accessory-strength");
    var overlap = node("viewer-accessory-overlap"), gaps = node("viewer-accessory-close-gaps");
    var message = node("viewer-accessory-status"), retry = node("viewer-accessory-retry");
    var targets = node("viewer-accessory-targets");
    if (!enabled || !strength || !overlap || !gaps || !message || !retry) return null;
    var disposed = false, refreshing = false, timer = null, flight = null, wanted = null;
    var currentRig = null, lastKey = "", lastResult = null, failedKey = "", error = "", draftError = "";
    var phase = "idle", count = 0, lastNotification = "", events = [];
    var translate = options.translate;
    function translatedMessage(value) {
      var prefix = "The accessory skin cannot be analyzed safely: ";
      return value.indexOf(prefix) === 0 ? translate(prefix.trim()) + " " + translate(value.slice(prefix.length)) : translate(value);
    }
    function snapshot() {
      return { enabled: !!(currentRig && currentRig.getAccessoryUnclip && currentRig.getAccessoryUnclip()),
        pending: phase === "pending", error: error || draftError, errorText: error || draftError ? translatedMessage(error || draftError) : "", status: phase, changed: count };
    }
    function notify() {
      var value = JSON.stringify(snapshot());
      if (value === lastNotification) return;
      lastNotification = value;
      if (options.onChange) options.onChange();
    }
    function stopTimer() { if (timer !== null) global.clearTimeout(timer); timer = null; }
    function clearPreview(rig) { if (rig && rig.setAccessoryCorrections) rig.setAccessoryCorrections([]); }
    function display(key, detail) {
      message.textContent = translatedMessage(key) + (detail ? " " + detail : "");
      message.classList.toggle("error", phase === "error");
      retry.hidden = phase !== "error";
      retry.disabled = !wanted || !!flight;
      if (targets) { targets.hidden = true; targets.textContent = ""; }
    }
    function resultDisplay() {
      if (count) {
        display("Corrected accessory anchors", ": " + count);
        if (targets && wanted) {
          var metadata = (options.context() || {}).editing || {};
          var names = lastResult.corrections.map(function (correction) {
            var target = (metadata.nodes || []).filter(function (entry) { return entry.node === correction.node; })[0];
            return target ? target.name : String(correction.node);
          });
          targets.textContent = translate("Affected anchors") + ": " + names.slice(0, 8).join(", ") + (names.length > 8 ? "…" : "");
          targets.hidden = false;
        }
      }
      else {
        var status = lastResult && lastResult.summary && lastResult.summary.status;
        display(status === "no_scaling" ? "No resized saved body regions were found." :
          "No overlapping accessories need correction for these settings.");
      }
    }
    function validResponse(value) {
      return value && Array.isArray(value.corrections) && value.summary && typeof value.summary === "object";
    }
    async function dispatch() {
      timer = null;
      if (disposed || flight || !wanted || draftError || failedKey === wanted.key || wanted.key === lastKey) return;
      var request = wanted;
      var controller = new AbortController();
      flight = { key: request.key, controller: controller };
      try {
        var response = await global.fetch("/api/viewer/edit/accessories", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: request.token, state: request.state }), signal: controller.signal });
        var data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Accessory correction could not be checked.");
        if (!validResponse(data)) throw new Error("The accessory preview response is invalid.");
        if (data.summary.status === "no_skin" || (data.summary.sources || []).some(function (source) { return source.status === "no_skin"; })) {
          throw new Error("This model's skinning cannot be checked safely. Turn accessory correction off to save other edits.");
        }
        if (disposed || !wanted || wanted.key !== request.key || currentRig !== request.rig) return;
        // A successful key is installed before the rig's change callback. Its
        // replacement overlay cannot recursively enqueue the same calculation.
        lastKey = request.key; lastResult = data; failedKey = ""; error = "";
        phase = "ready"; count = data.corrections.length;
        request.rig.setAccessoryCorrections(data.corrections);
        resultDisplay();
      } catch (failure) {
        if (disposed || !wanted || wanted.key !== request.key || currentRig !== request.rig) return;
        lastKey = ""; lastResult = null; failedKey = request.key;
        error = String(failure.message || failure); phase = "error"; count = 0;
        clearPreview(request.rig); display(error);
      } finally {
        flight = null;
        if (!disposed) {
          retry.disabled = !wanted;
          notify();
          // Do not abort then immediately issue another parse: aborting fetch
          // does not stop UnityPy on the server. Let one request finish first.
          if (wanted && wanted.key !== lastKey && wanted.key !== failedKey && !draftError && timer === null) dispatch();
        }
      }
    }
    function refresh() {
      if (disposed || refreshing) return;
      refreshing = true;
      try {
        var context = options.context() || {}, rig = context.rig, metadata = context.editing || {};
        if (currentRig !== rig) {
          currentRig = rig || null; wanted = null; lastKey = ""; lastResult = null;
          failedKey = ""; error = ""; draftError = ""; count = 0; stopTimer();
        }
        var config = rig && rig.getAccessoryUnclip && rig.getAccessoryUnclip();
        var ready = !!(context.current && !context.reviewingSaved && metadata.available && metadata.token &&
          rig && rig.getAuthoringState && rig.getState().authoringEnabled !== false);
        var locked = !ready || context.busy;
        enabled.disabled = locked; enabled.checked = !!config;
        [strength, overlap, gaps].forEach(function (input) { input.disabled = locked || !config; });
        if (config) {
          if (document.activeElement !== strength) strength.value = String(config.strength);
          if (document.activeElement !== overlap) overlap.value = String(config.overlap);
          gaps.checked = config.closeGaps;
        }
        if (!ready || !config) {
          wanted = null; stopTimer(); failedKey = ""; error = ""; draftError = ""; count = 0;
          phase = !ready ? "idle" : "off"; clearPreview(rig);
          display(!ready ? context.reviewingSaved ? "Reviewing the saved copy. Re-edit from original to continue." :
            context.current ? "Accessory correction is unavailable for this model." : "Open a model to check accessories." : "Accessory correction is off.");
          return;
        }
        var authored = rig.getAuthoringState();
        if (draftError || authored.unsupported && authored.unsupported.length) {
          wanted = null; stopTimer(); clearPreview(rig); phase = "error";
          error = draftError || authored.unsupported[0]; display(error); return;
        }
        delete authored.unsupported;
        var key = JSON.stringify([context.modelId, metadata.token, authored]);
        if (wanted && wanted.key === key) {
          if (phase === "ready") {
            // Restoring the same recipe clears the rig's derived overlay.
            // Reinstall the cached replacement without another server parse.
            if (lastResult) rig.setAccessoryCorrections(lastResult.corrections);
            resultDisplay();
          }
          else display(phase === "error" ? error : "Checking accessory clipping…");
          return;
        }
        wanted = { key: key, token: metadata.token, state: authored, rig: rig };
        error = ""; failedKey = ""; count = 0; clearPreview(rig); stopTimer();
        if (key === lastKey && lastResult) {
          phase = "ready"; count = lastResult.corrections.length;
          rig.setAccessoryCorrections(lastResult.corrections); resultDisplay();
        } else {
          phase = "pending"; display("Checking accessory clipping…");
          timer = global.setTimeout(dispatch, 300);
        }
      } finally { refreshing = false; notify(); }
    }
    function listen(target, name, callback) {
      target.addEventListener(name, callback);
      events.push(function () { target.removeEventListener(name, callback); });
    }
    function readInputs() {
      var config = { strength: Number(strength.value), overlap: Number(overlap.value), closeGaps: gaps.checked };
      draftError = "";
      [[strength, config.strength, 3], [overlap, config.overlap, 1]].forEach(function (entry) {
        var invalid = !entry[0].value.trim() || !isFinite(entry[1]) || entry[1] < 0 || entry[1] > entry[2];
        var text = invalid ? "Enter a correction strength from 0 to 3 and an overlap from 0 to 1." : "";
        entry[0].setCustomValidity(translate(text));
        if (invalid) { entry[0].setAttribute("aria-invalid", "true"); draftError = text; }
        else entry[0].removeAttribute("aria-invalid");
      });
      if (!draftError && currentRig) currentRig.setAccessoryUnclip(config);
      refresh();
    }
    listen(enabled, "change", function () {
      if (!currentRig || enabled.disabled) return;
      draftError = "";
      [strength, overlap].forEach(function (input) { input.setCustomValidity(""); input.removeAttribute("aria-invalid"); });
      if (enabled.checked) {
        node("viewer-accessory-card").open = true;
        strength.value = "1"; overlap.value = "0.15"; gaps.checked = false;
        currentRig.setAccessoryUnclip({ strength: 1, overlap: .15, closeGaps: false });
      } else currentRig.setAccessoryUnclip(null);
      refresh();
    });
    [strength, overlap].forEach(function (input) { listen(input, "input", readInputs); });
    listen(gaps, "change", readInputs);
    listen(retry, "click", function () { failedKey = ""; error = ""; wanted = null; refresh(); });
    refresh();
    return { refresh: refresh, getState: snapshot,
      updateLanguage: function () { translate = options.translate; refresh(); },
      dispose: function () {
        if (disposed) return;
        disposed = true; stopTimer(); wanted = null;
        if (flight) flight.controller.abort();
        events.forEach(function (remove) { remove(); }); clearPreview(currentRig); currentRig = null;
      } };
  }
  global.ViewerAccessories = { create: create };
})(window);
