/* Local costume viewer. Three.js and its loaders are bundled with the app. */
(function () {
  "use strict";

  var MAX_FILES = 8;
  var MAX_GLB_BYTES = 64 * 1024 * 1024;
  var config = null;
  var mounted = false;
  var pendingOpen = null;
  var paths = [];
  var loadedPaths = [];
  var loadedAutoFace = true;
  var variantChoices = Object.create(null);
  var variantOptions = Object.create(null);
  var loadedVariants = [];
  var variantFocus = "";
  var metadata = null;
  var generation = 0;
  var controller = null;
  var loading = false;
  var active = false;
  var lost = false;
  var renderer = null;
  var qualityController = null;
  var modelRenderInfo = { triangles: 0, calls: 0, lines: 0, points: 0 };
  var scene = null;
  var camera = null;
  var controls = null;
  var model = null;
  var rigController = null;
  var partInputs = [];
  var materialController = null;
  var discardPendingPreview = null;
  var lastFrameTime = 0;
  var materialPreference = "sifas";
  var frame = 0;
  var resizeObserver = null;
  var bounds = null;
  var expanded = false;
  var expandedSnapshot = null;
  var fullscreenMode = "none";
  var fullscreenPending = "";
  var fullscreenWanted = false;
  var fullscreenSnapshot = null;
  var fullscreenTimer = 0;
  var lastFullscreenExit = 0;
  var resizeFrame = 0;
  var compactControls = false;
  var shortHeight = false;
  var layoutHomes = [];
  var shortScroll = null;
  var pickerHome = null;
  var pickerObserver = null;
  var outsideFocus = [];
  var infoAutoOpened = false;
  var seriousWarning = false;
  var materialFailure = false;
  var qualityFailure = false;
  var layoutNotice = "";
  var layoutListeners = [];
  var layoutState = { viewport: null, stage: null, safeInsets: { top: 0, right: 0, bottom: 0, left: 0 } };
  var statusKey = "Choose a costume file to begin.";
  var statusError = false;
  var statusDetail = "";
  var destroyed = false;
  var renderedFrames = 0;

  function node(id) { return document.getElementById(id); }
  function t(key) { return config && config.translate ? config.translate(key) : key; }
  function basename(path) { return String(path).replace(/\/+$/, "").split("/").pop(); }
  function variantsFor(selected) { return selected.map(function (path) { return variantChoices[path] || "primary"; }); }
  function sameSelection(selected, autoFace, variants) {
    return !destroyed && JSON.stringify(paths) === JSON.stringify(selected) &&
      node("viewer-auto-face").checked === autoFace &&
      JSON.stringify(variantsFor(paths)) === JSON.stringify(variants);
  }
  function variantsLoaded() { return JSON.stringify(variantsFor(paths)) === JSON.stringify(loadedVariants); }
  function readVariantOptions(records, selected, variants) {
    var result = Object.create(null), indices = Object.create(null);
    if (records === undefined) records = [];
    if (!Array.isArray(records) || records.length > selected.length) throw new Error(t("The costume variant could not be selected."));
    records.forEach(function (record) {
      var index = record && record.source_index;
      if (typeof index !== "number" || Math.floor(index) !== index || index < 0 || index >= selected.length ||
          indices[index] || !Array.isArray(record.choices) || record.choices.length !== 2 ||
          record.choices.indexOf("primary") < 0 || record.choices.indexOf("unmasked") < 0 ||
          record.selected !== variants[index]) throw new Error(t("The costume variant could not be selected."));
      indices[index] = true;
      result[selected[index]] = { selected: record.selected, choices: ["primary", "unmasked"] };
    });
    selected.forEach(function (path, index) {
      if (variants[index] !== "primary" && !result[path]) throw new Error(t("The costume variant could not be selected."));
    });
    return result;
  }

  function renderVariantOptions() {
    var box = node("viewer-variant-options");
    if (!box) return;
    box.textContent = "";
    var offered = paths.filter(function (path) { return !!variantOptions[path]; });
    box.hidden = !offered.length;
    offered.forEach(function (path) {
      var label = document.createElement("label"), title = document.createElement("span");
      title.textContent = t("Rina face") + (offered.length > 1 ? " · " + basename(path) : "");
      var select = document.createElement("select"), index = paths.indexOf(path);
      select.id = "viewer-variant-" + index;
      select.dataset.viewerVariantIndex = String(index);
      select.setAttribute("aria-label", t("Rina face") + " · " + basename(path));
      select.setAttribute("aria-describedby", "viewer-variant-help");
      ["primary", "unmasked"].forEach(function (choice) {
        var option = document.createElement("option"); option.value = choice;
        option.textContent = t(choice === "primary" ? "Rina board" : "Normal face");
        select.appendChild(option);
      });
      select.value = variantChoices[path] || "primary";
      select.disabled = loading || lost;
      select.addEventListener("change", function () {
        if (loading || lost || (this.value !== "primary" && this.value !== "unmasked")) return;
        variantChoices[path] = this.value; variantFocus = path;
        filesChanged(); loadSelected();
      });
      label.appendChild(title); label.appendChild(select); box.appendChild(label);
      if (!loading && variantFocus === path) { focusElement(select); variantFocus = ""; }
    });
    if (offered.length) {
      var help = document.createElement("p"); help.id = "viewer-variant-help";
      help.textContent = t("Changing the face style reloads the model."); box.appendChild(help);
    }
  }
  function replaceValues(text, values) {
    return text.replace(/\{([a-z_]+)\}/g, function (_, key) {
      return values[key] === undefined ? "" : String(values[key]);
    });
  }

  function setStatus(key, isError, detail) {
    statusKey = key;
    statusError = !!isError;
    statusDetail = detail ? String(detail).slice(0, 350) : "";
    refreshStatus();
  }

  function refreshStatus() {
    var message = t(statusKey);
    if (statusKey === "Model ready." && metadata && metadata.stats) {
      message += " " + replaceValues(t("Meshes: {meshes} · Triangles: {triangles}"), metadata.stats);
    }
    node("viewer-status").textContent = message + (statusDetail ? " " + t(statusDetail) : "");
    node("viewer-status").classList.toggle("error", statusError);
    refreshInfoVisibility();
  }

  function refreshInfoVisibility() {
    var info = node("viewer-info");
    if (!info) return;
    var alert = statusError || seriousWarning || materialFailure || qualityFailure || !!layoutNotice;
    info.classList.toggle("viewer-info-alert", !!alert);
    if (alert && !info.open) { infoAutoOpened = true; info.open = true; }
    else if (!alert && infoAutoOpened) { info.open = false; infoAutoOpened = false; }
    refreshPopoverStack(info.open ? info : null);
  }

  function refreshPopoverStack(preferred) {
    var menu = node("viewer-view-menu"), info = node("viewer-info"), workspace = node("viewer-workspace-menu");
    var popovers = [menu, info, workspace].filter(function (item) { return !!item; });
    var opened = popovers.filter(function (item) { return item.open; });
    if (opened.length > 1) {
      var keep = preferred && preferred.open ? preferred : info && info.open ? info : opened[0];
      popovers.forEach(function (item) {
        if (item === keep || !item.open) return;
        item.open = false;
        if (item === info) infoAutoOpened = false;
      });
    }
    var top = node("viewer-stage-tools-top"), bottom = node("viewer-stage-tools-bottom");
    [top, bottom].forEach(function (hud) {
      if (hud) hud.classList.toggle("viewer-popover-open", popovers.some(function (item) { return item.open && hud.contains(item); }));
    });
  }

  function bindViewportPopover(details) {
    if (!details) return;
    var summary = details.querySelector("summary");
    if (summary) summary.addEventListener("click", function (event) {
      // details' toggle event is deferred. Update stacking during this actual
      // activation so another control can be hit-tested in the same turn.
      event.preventDefault();
      if (details === node("viewer-info")) infoAutoOpened = false;
      details.open = !details.open;
      refreshPopoverStack(details.open ? details : null);
    });
    details.addEventListener("toggle", function () { refreshPopoverStack(details.open ? details : null); });
  }

  function viewportRect() {
    var visual = window.visualViewport;
    return { width: visual && visual.width || window.innerWidth,
      height: visual && visual.height || window.innerHeight,
      top: visual && visual.offsetTop || 0, left: visual && visual.offsetLeft || 0 };
  }

  function scheduleResize() {
    if (resizeFrame || destroyed || !active) return;
    resizeFrame = window.requestAnimationFrame(function () { resizeFrame = 0; resize(); });
  }

  function moveLayoutElement(element, parent, before) {
    if (!element || !parent || element.parentNode === parent) return;
    var focused = element.contains(document.activeElement) ? document.activeElement : null;
    parent.insertBefore(element, before || null);
    if (focused) focusElement(focused);
  }

  function focusViewportControl() {
    [node("viewer-fullscreen"), node("viewer-expand"), node("viewer-view-menu") && node("viewer-view-menu").querySelector("summary")].some(function (element) {
      if (!element) return false;
      var rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height || rect.bottom <= 0 || rect.top >= window.innerHeight) return false;
      focusElement(element); return true;
    });
  }

  function rememberLayoutHomes() {
    if (layoutHomes.length) return;
    var tab = node("tab-viewer");
    [document.querySelector("body > header"), tab.querySelector(".viewer-files"),
      tab.querySelector(".viewer-control-panel"), tab.querySelector(".viewer-camera-actions"), node("viewer-info")].forEach(function (element) {
      if (element) layoutHomes.push({ element: element, parent: element.parentNode, next: element.nextSibling });
    });
  }

  function updateShortLayout(viewport) {
    var workspace = node("viewer-workspace-menu"), content = node("viewer-workspace-menu-content");
    if (!workspace || !content) return;
    rememberLayoutHomes();
    var next = !!(viewport && active && model && viewport.height <= 320);
    var narrow = next && viewport.width < 720;
    var tab = node("tab-viewer"), top = node("viewer-stage-tools-top");
    var viewContent = node("viewer-view-menu-content"), changed = next !== shortHeight;
    var focused = document.activeElement;
    var plans = layoutHomes.map(function (home, index) {
      var parent = home.parent, before = home.next && home.next.parentNode === parent ? home.next : null;
      if (next) {
        if (index < 2 || index === 2 && narrow) { parent = content; before = null; }
        else if (index === 3) { parent = viewContent; before = null; }
        else if (index === 4) { parent = top; before = top.querySelector(".viewer-screen-actions"); }
      }
      return { home: home, parent: parent, before: before };
    });
    var relocating = plans.some(function (plan) { return plan.home.element.parentNode !== plan.parent; });
    // A moved page header crosses the expanded viewer's focus boundary. Restore
    // the previous isolation before moving it, then capture the new boundary.
    if (relocating && expanded) isolateViewer(false);
    if (changed && next) shortScroll = { x: window.scrollX, y: window.scrollY };
    shortHeight = next;
    tab.classList.toggle("viewer-short-height", next);
    document.body.classList.toggle("viewer-short-workspace", next);
    plans.forEach(function (plan) { moveLayoutElement(plan.home.element, plan.parent, plan.before); });
    if (relocating && expanded) isolateViewer(true);
    if (next && focused && content.contains(focused)) workspace.open = true;
    if (!next) {
      workspace.open = false;
      if (focused && (workspace.contains(focused) || expanded && !tab.contains(focused))) focusViewportControl();
      if (changed && shortScroll) {
        var scroll = shortScroll; shortScroll = null;
        window.requestAnimationFrame(function () { if (active && !destroyed && !shortHeight && !expanded) window.scrollTo(scroll.x, scroll.y); });
      }
    }
    refreshPopoverStack(workspace.open ? workspace : null);
  }

  function restoreViewerPicker() {
    if (pickerObserver) pickerObserver.disconnect();
    pickerObserver = null;
    var home = pickerHome; pickerHome = null;
    if (!home) return;
    if (expanded) isolateViewer(false);
    moveLayoutElement(home.element, home.parent, home.next && home.next.parentNode === home.parent ? home.next : null);
    if (expanded) isolateViewer(true);
    if (active && !destroyed) focusElement(home.focus);
  }

  function containViewerPicker() {
    var picker = node("picker");
    if (!picker || pickerHome) return;
    // Browser fullscreen only displays descendants of its owning element. The
    // same chooser must also remain inside the viewer's focus boundary.
    pickerHome = { element: picker, parent: picker.parentNode, next: picker.nextSibling, focus: document.activeElement };
    if (expanded) {
      isolateViewer(false);
      moveLayoutElement(picker, node("tab-viewer"), null);
      isolateViewer(true);
    }
    pickerObserver = new window.MutationObserver(function () {
      if (picker.classList.contains("hidden")) restoreViewerPicker();
    });
    pickerObserver.observe(picker, { attributes: true, attributeFilter: ["class"] });
  }

  function updateCompactControls(viewport) {
    var menu = node("viewer-view-menu"), content = node("viewer-view-menu-content");
    if (!menu || !content) return;
    // A declared costume choice stays reachable inside the same viewport menu
    // even in expanded/fullscreen mode, without adding another HUD row.
    var compact = shortHeight || (viewport.width < 760 && viewport.height <= 560) ||
      paths.some(function (path) { return !!variantOptions[path]; });
    var tab = node("tab-viewer"), top = node("viewer-stage-tools-top");
    var primary = top.querySelector(".viewer-primary-tools");
    var focusedPrimary = primary && primary.contains(document.activeElement) ? document.activeElement : null;
    var focusedSummary = !compact && menu.contains(document.activeElement) && !focusedPrimary;
    var changed = compact !== compactControls;
    if (changed) {
      menu.open = compact && !!focusedPrimary;
      compactControls = compact;
    }
    tab.classList.toggle("viewer-compact-controls", compact);
    moveLayoutElement(primary, compact ? content : top,
      compact ? null : top.querySelector(".viewer-screen-actions"));
    if (changed && focusedPrimary) focusElement(focusedPrimary);
    else if (changed && focusedSummary) focusElement(node("viewer-expand"));
    var list = node("viewer-file-list"), options = node("viewer-file-options");
    var hideList = compact && tab.classList.contains("viewer-has-model");
    if (hideList && list && list.contains(document.activeElement)) options.open = true;
    moveLayoutElement(list, hideList ? options.querySelector(".viewer-file-options-panel") : options.parentNode,
      hideList ? null : options);
    refreshPopoverStack(menu.open ? menu : null);
  }

  function measureSafeInsets() {
    var stage = node("viewer-stage"), rect = stage.getBoundingClientRect();
    var insets = { top: 0, right: 0, bottom: 0, left: 0 };
    stage.querySelectorAll("[data-viewer-hud-edge]").forEach(function (hud) {
      var box = hud.getBoundingClientRect(), edge = hud.dataset.viewerHudEdge;
      if (!box.width || !box.height || window.getComputedStyle(hud).display === "none") return;
      if (edge === "top") insets.top = Math.max(insets.top, Math.max(0, Math.min(rect.height, box.bottom - rect.top)));
      if (edge === "bottom") insets.bottom = Math.max(insets.bottom, Math.max(0, Math.min(rect.height, rect.bottom - box.top)));
      if (edge === "left") insets.left = Math.max(insets.left, Math.max(0, Math.min(rect.width, box.right - rect.left)));
      if (edge === "right") insets.right = Math.max(insets.right, Math.max(0, Math.min(rect.width, rect.right - box.left)));
    });
    return insets;
  }

  function renderFiles() {
    var list = node("viewer-file-list");
    list.textContent = "";
    paths.forEach(function (path, index) {
      var item = document.createElement("li");
      var name = document.createElement("span");
      name.textContent = basename(path);
      name.title = path;
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "viewer-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", t("Remove") + " " + basename(path));
      remove.disabled = loading;
      remove.addEventListener("click", function () {
        paths.splice(index, 1);
        delete variantChoices[path]; delete variantOptions[path];
        renderFiles();
        filesChanged();
      });
      item.appendChild(name);
      item.appendChild(remove);
      list.appendChild(item);
    });
    node("viewer-add").textContent = t(paths.length ? "Add file" : "Choose costume file");
    node("viewer-add").disabled = loading || paths.length >= MAX_FILES;
    node("viewer-add-motion").disabled = loading || paths.length >= MAX_FILES;
    node("viewer-load").disabled = loading || !paths.length;
    renderVariantOptions();
    scheduleResize();
  }

  function filesChanged() {
    if (!paths.length) setStatus("Choose a costume file to begin.");
    else if (model && JSON.stringify(paths) !== JSON.stringify(loadedPaths)) {
      setStatus("Files changed. Press Open model to refresh the preview.");
    } else if (model && node("viewer-auto-face").checked !== loadedAutoFace) {
      setStatus("Face option changed. Press Open model to refresh the preview.");
    } else if (model && !variantsLoaded()) {
      setStatus("Face style changed. Press Open model to refresh the preview.");
    } else if (!model) setStatus("Press Open model to see the costume.");
    else if (!loading) setStatus("Model ready.");
    showFaceStatus();
  }

  function setLoading(value) {
    loading = value;
    node("viewer-busy").hidden = !value;
    node("viewer-cancel").hidden = !value;
    node("viewer-load").hidden = value;
    node("viewer-auto-face").disabled = value;
    node("viewer-high-quality").disabled = value || lost;
    if (rigController) rigController.setInteractive(!value && !lost);
    renderFiles();
    showFaceStatus();
  }

  function cancelLoading() {
    generation += 1;
    if (controller) controller.abort();
    controller = null;
    if (discardPendingPreview) discardPendingPreview();
    setLoading(false);
    setStatus("Loading cancelled.");
  }

  function requestRender() {
    if (frame || !active || document.hidden || !renderer || lost || destroyed) return;
    frame = window.requestAnimationFrame(draw);
  }

  function draw(time) {
    frame = 0;
    if (!active || document.hidden || !renderer || lost || destroyed) return;
    var delta = lastFrameTime ? Math.min(.1, Math.max(0, (time - lastFrameTime) / 1000)) : 0;
    lastFrameTime = time;
    var moving = rigController ? rigController.update(delta) : false;
    syncPartVisibility();
    if (materialController && materialController.update) moving = materialController.update(delta) || moving;
    var changed = controls.update();
    renderScene();
    renderedFrames += 1;
    if (changed || moving) requestRender();
    else lastFrameTime = 0;
  }

  function pauseRender() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
    lastFrameTime = 0;
  }

  function refreshQualityStatus() {
    var status = node("viewer-quality-status");
    var quality = qualityController ? qualityController.getState() : null;
    var limited = !!(quality && quality.enabled && quality.ready && quality.effectiveSamples < 2);
    status.hidden = !limited;
    var text = limited ? t("Device-resolution rendering is enabled; edge smoothing is unavailable on this device.") : "";
    if (status.textContent !== text) status.textContent = text;
    if (qualityFailure !== limited) { qualityFailure = limited; refreshInfoVisibility(); }
  }

  function renderScene() {
    modelRenderInfo = qualityController.render(scene, camera);
    refreshQualityStatus();
  }

  function resize() {
    if (!active || destroyed) return;
    var viewport = viewportRect();
    updateShortLayout(viewport);
    updateCompactControls(viewport);
    var header = document.querySelector("body > header");
    var headerStyle = header ? window.getComputedStyle(header) : null;
    var pinnedHeader = headerStyle && headerStyle.display !== "none" &&
      (headerStyle.position === "sticky" || headerStyle.position === "fixed");
    var headerBottom = pinnedHeader ? Math.max(viewport.top, header.getBoundingClientRect().bottom) : viewport.top;
    document.documentElement.style.setProperty("--viewer-sticky-top", headerBottom + "px");
    var stage = node("viewer-stage");
    var stageTop = Math.max(viewport.top, headerBottom, stage.getBoundingClientRect().top);
    var available = Math.max(1, viewport.top + viewport.height - stageTop - 10);
    var sideBySide = window.innerWidth >= 720;
    var desired = expanded || shortHeight ? viewport.height : Math.min(available, sideBySide ? viewport.height : viewport.height * .6);
    node("tab-viewer").style.setProperty("--viewer-stage-height", Math.round(desired) + "px");
    node("tab-viewer").style.setProperty("--viewer-viewport-height", Math.round(viewport.height) + "px");
    if (!expanded && !shortHeight && viewport.width >= 1200) {
      var inspect = node("tab-viewer").querySelector(".viewer-inspect-layout");
      // Give a standing model a useful portrait-shaped area, and use the freed
      // width for independent editing cards rather than another empty margin.
      var previewWidth = Math.max(360, Math.min(inspect.clientWidth - 332, desired * 1.25));
      node("tab-viewer").style.setProperty("--viewer-model-width", Math.round(previewWidth) + "px");
    } else node("tab-viewer").style.removeProperty("--viewer-model-width");
    var width = stage.clientWidth;
    var height = stage.clientHeight;
    if (!width || !height) return;
    var box = stage.getBoundingClientRect();
    layoutState = { viewport: viewport, stage: { width: width, height: height, top: box.top, left: box.left }, safeInsets: measureSafeInsets() };
    if (renderer && qualityController) {
      qualityController.resize(width, height);
      // Layout changes preserve the user's orbit, zoom distance and pan. Only
      // the viewport aspect changes; fitting/recentring is an explicit action.
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }
    requestRender();
  }

  function ensureRenderer() {
    if (renderer) {
      if (lost) setStatus("3D graphics were interrupted. Wait a moment, then open the model again.", true);
      return !lost;
    }
    if (!window.THREE || !window.THREE.OrbitControls || !window.THREE.GLTFLoader || !window.ViewerQuality) {
      setStatus("The 3D viewer files could not be loaded. Reopen the app and try again.", true);
      return false;
    }
    try {
      renderer = new window.THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "low-power" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
      renderer.outputEncoding = window.THREE.sRGBEncoding;
      renderer.toneMapping = window.THREE.NoToneMapping;
      qualityController = window.ViewerQuality.create(renderer);
      qualityController.setEnabled(node("viewer-high-quality").checked);
      renderer.domElement.setAttribute("aria-label", t("3D model"));
      renderer.domElement.id = "viewer-canvas";
      renderer.domElement.setAttribute("role", "img");
      node("viewer-stage").insertBefore(renderer.domElement, node("viewer-empty"));
      scene = new window.THREE.Scene();
      camera = new window.THREE.PerspectiveCamera(35, 1, 0.01, 1000);
      camera.position.set(0, 1, 3);
      controls = new window.THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.12;
      controls.screenSpacePanning = true;
      controls.addEventListener("change", requestRender);
      scene.add(new window.THREE.HemisphereLight(0xffffff, 0x737b89, 0.85));
      var light = new window.THREE.DirectionalLight(0xffffff, 0.9);
      light.position.set(-2, 3, 4);
      scene.add(light);
      var fill = new window.THREE.DirectionalLight(0xffffff, 0.35);
      fill.position.set(3, 1, -3);
      scene.add(fill);
      renderer.domElement.addEventListener("webglcontextlost", function (event) {
        event.preventDefault();
        lost = true;
        pauseRender();
        qualityController.invalidateGPU();
        node("viewer-high-quality").disabled = true;
        // r128 replaces its GPU caches on restoration. Detach the old resource
        // disposal listeners while the context is lost, so a later model reload
        // cannot delete handles from the old context generation. Keep CPU data
        // and decoded source images for the restored renderer to upload again.
        if (materialController && materialController.invalidateGPU) materialController.invalidateGPU();
        disposeObject(model, true);
        if (rigController) rigController.setInteractive(false);
        // Abort the client load as well. A late preparation response must not
        // replace this interruption message with a misleading ready state.
        if (loading) {
          generation += 1;
          if (controller) controller.abort();
          controller = null;
          if (discardPendingPreview) discardPendingPreview();
          setLoading(false);
        }
        setStatus("3D graphics were interrupted. Wait a moment, then open the model again.", true);
        renderVariantOptions();
        showFaceStatus();
      });
      renderer.domElement.addEventListener("webglcontextrestored", function () {
        lost = false;
        qualityController.restoreGPU();
        node("viewer-high-quality").disabled = loading;
        setStatus(model ? "Model ready." : "Choose a costume file to begin.");
        filesChanged();
        renderVariantOptions();
        if (rigController) rigController.setInteractive(!loading);
        resize();
      });
      setBackground();
      resize();
      return true;
    } catch (error) {
      if (renderer) {
        if (qualityController) qualityController.dispose();
        renderer.dispose();
        if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
      if (controls) controls.dispose();
      renderer = null;
      qualityController = null;
      setStatus("3D graphics are unavailable here. Update Android System WebView or use a current browser.", true);
      return false;
    }
  }

  function setBackground() {
    if (!scene) return;
    scene.background = new window.THREE.Color(node("viewer-background").value === "dark" ? 0x262c37 : 0xe7ebf1);
    requestRender();
  }

  function fitModel(direction) {
    if (!model || !bounds || !camera) return;
    if (rigController && rigController.getBounds) {
      var posed = rigController.getBounds();
      if (posed) bounds = posed;
    }
    // A view preset must also clear the previous drag's damping and pan. If
    // their deltas survive, OrbitControls moves away again after the next frame.
    var damping = controls.enableDamping;
    controls.enableDamping = false;
    controls.update();
    controls.enableDamping = damping;
    var sphere = bounds.getBoundingSphere(new window.THREE.Sphere());
    var radius = Math.max(sphere.radius, 0.01);
    var halfVertical = camera.fov * Math.PI / 360;
    var halfHorizontal = Math.atan(Math.tan(halfVertical) * camera.aspect);
    var insets = measureSafeInsets(), stage = node("viewer-stage");
    var safeWidth = Math.max(1, stage.clientWidth - insets.left - insets.right) / Math.max(1, stage.clientWidth);
    var safeHeight = Math.max(1, stage.clientHeight - insets.top - insets.bottom) / Math.max(1, stage.clientHeight);
    var view = direction || camera.position.clone().sub(controls.target).normalize();
    if (!view.lengthSq()) view = new window.THREE.Vector3(0, 0, 1);
    view = view.clone().normalize();
    var right = new window.THREE.Vector3().crossVectors(camera.up, view).normalize();
    if (!right.lengthSq()) right.set(1, 0, 0);
    var up = new window.THREE.Vector3().crossVectors(view, right).normalize();
    var halfWidth = 0;
    var halfHeight = 0;
    var halfDepth = 0;
    // Fit projected box extents instead of a sphere: a tall, slender character
    // should fill the view rather than shrink to fit its height across the width.
    for (var corner = 0; corner < 8; corner += 1) {
      var point = new window.THREE.Vector3(
        corner & 1 ? bounds.max.x : bounds.min.x,
        corner & 2 ? bounds.max.y : bounds.min.y,
        corner & 4 ? bounds.max.z : bounds.min.z).sub(sphere.center);
      halfWidth = Math.max(halfWidth, Math.abs(point.dot(right)));
      halfHeight = Math.max(halfHeight, Math.abs(point.dot(up)));
      halfDepth = Math.max(halfDepth, Math.abs(point.dot(view)));
    }
    var distance = (Math.max(halfWidth / (Math.tan(halfHorizontal) * safeWidth),
      halfHeight / (Math.tan(halfVertical) * safeHeight)) + halfDepth) * 1.12;
    var target = sphere.center.clone();
    target.addScaledVector(right, -(insets.left - insets.right) / Math.max(1, stage.clientWidth) * distance * Math.tan(halfHorizontal));
    target.addScaledVector(up, -(insets.bottom - insets.top) / Math.max(1, stage.clientHeight) * distance * Math.tan(halfVertical));
    camera.near = Math.max(0.001, radius / 1000);
    camera.far = Math.max(100, radius * 100);
    camera.up.set(0, 1, 0);
    camera.position.copy(target).addScaledVector(view, distance);
    camera.updateProjectionMatrix();
    controls.target.copy(target);
    controls.minDistance = radius * 0.12;
    controls.maxDistance = radius * 30;
    controls.update();
    requestRender();
  }

  function setView(name) {
    if (!window.THREE) return;
    var directions = { front: [0, 0, 1], back: [0, 0, -1], left: [1, 0, 0], right: [-1, 0, 0] };
    fitModel(new window.THREE.Vector3().fromArray(directions[name] || directions.front));
  }

  function forEachMaterial(materials, callback) {
    (Array.isArray(materials) ? materials : [materials]).forEach(function (material) {
      if (material) callback(material);
    });
  }

  function isViewerHelper(object) {
    return object.userData && object.userData.viewerHelper === true;
  }

  function visibleSourceTriangles() {
    var triangles = 0;
    if (model) model.traverseVisible(function (child) {
      if (!child.isMesh || isViewerHelper(child) || !child.geometry) return;
      var geometry = child.geometry;
      var count = geometry.index ? geometry.index.count : geometry.attributes.position ? geometry.attributes.position.count : 0;
      triangles += count / 3;
    });
    return triangles;
  }

  function disposePreviewControllers() {
    partInputs = [];
    if (rigController) rigController.dispose();
    if (materialController) materialController.dispose();
    rigController = null;
    materialController = null;
    lastFrameTime = 0;
  }

  function disposeObject(object, preserveImages) {
    if (!object) return;
    var geometries = new Set();
    var materials = new Set();
    var textures = new Set();
    object.traverse(function (child) {
      if (child.geometry) geometries.add(child.geometry);
      forEachMaterial(child.material, function (material) { materials.add(material); });
      forEachMaterial(child.userData.viewerOriginalMaterials, function (material) { materials.add(material); });
      forEachMaterial(child.userData.viewerSolidMaterials, function (material) { materials.add(material); });
      if (child.skeleton && child.skeleton.boneTexture) textures.add(child.skeleton.boneTexture);
    });
    materials.forEach(function (material) {
      Object.keys(material).forEach(function (key) {
        if (material[key] && material[key].isTexture) textures.add(material[key]);
      });
      material.dispose();
    });
    geometries.forEach(function (geometry) { geometry.dispose(); });
    textures.forEach(function (texture) {
      if (!preserveImages && texture.image && typeof texture.image.close === "function") texture.image.close();
      texture.dispose();
    });
  }

  function updateAppearance() {
    if (!model) return;
    var showTextures = node("viewer-textures").checked;
    var wireframe = node("viewer-wireframe").checked;
    if (materialController && materialController.setEnabled) {
      materialController.setEnabled(showTextures && !wireframe && node("viewer-shader").value === "sifas");
    }
    model.traverse(function (child) {
      if (!child.isMesh || isViewerHelper(child)) return;
      if (!materialController && !child.userData.viewerOriginalMaterials) child.userData.viewerOriginalMaterials = child.material;
      if (!showTextures && !child.userData.viewerSolidMaterials) {
        var original = materialController && materialController.getMaterial ? materialController.getMaterial(child) : child.userData.viewerOriginalMaterials;
        var create = function () {
          return new window.THREE.MeshStandardMaterial({ color: 0xadb8c8, roughness: 0.85, metalness: 0,
            side: window.THREE.DoubleSide, skinning: !!child.isSkinnedMesh,
            morphTargets: !!child.morphTargetInfluences,
            morphNormals: !!(child.geometry.morphAttributes && child.geometry.morphAttributes.normal) });
        };
        child.userData.viewerSolidMaterials = Array.isArray(original) ? original.map(create) : create();
      }
      child.material = showTextures ? (materialController && materialController.getMaterial ? materialController.getMaterial(child) : child.userData.viewerOriginalMaterials) : child.userData.viewerSolidMaterials;
      forEachMaterial(child.material, function (material) { material.wireframe = wireframe; });
    });
    requestRender();
    refreshMaterialStatus();
  }

  function refreshMaterialStatus() {
    var state = materialController && materialController.getState ? materialController.getState() : null;
    node("viewer-material-status").textContent = !state ? "" : t(!state.recognizedMaterials ?
      "SIFAS material data is unavailable. Basic textures are shown." : node("viewer-shader").value === "basic" ?
      "Basic textures are shown." : "Uses the file's SIFAS material settings. In-game appearance may differ.");
    var failures = state && state.enabled && state.recognizedMaterials ? (state.limitations || []).filter(function (message) {
      return message === "A shader texture could not be loaded." || message === "Auxiliary shader texture loading is unavailable.";
    }) : [];
    materialFailure = failures.length > 0;
    var warning = node("viewer-material-warning");
    if (warning) { warning.hidden = !materialFailure; warning.textContent = failures.map(t).join("\n"); }
    refreshInfoVisibility();
  }

  function buildParts() {
    var list = node("viewer-parts");
    list.textContent = "";
    partInputs = [];
    var count = 0;
    model.traverse(function (child) {
      if (!child.isMesh || isViewerHelper(child)) return;
      count += 1;
      var label = document.createElement("label");
      var input = document.createElement("input");
      input.type = "checkbox";
      if (!rigController && (child.userData.hidden_default === true || child.userData.hideInPreview === true)) child.visible = false;
      input.checked = child.visible;
      var initial = rigController && rigController.getPartVisibility ? rigController.getPartVisibility(child) : null;
      var status = document.createElement("small"); status.className = "viewer-part-state";
      status.id = "viewer-part-state-" + count;
      input.setAttribute("aria-describedby", status.id);
      var entry = { object: child, input: input, status: status,
        fileVisible: initial && typeof initial.fileVisible === "boolean" ? initial.fileVisible :
          initial && typeof initial.selected === "boolean" ? initial.selected : undefined,
        userChanged: false, userVisible: undefined };
      partInputs.push(entry);
      input.addEventListener("change", function () {
        entry.userChanged = true; entry.userVisible = input.checked;
        if (rigController && rigController.setPartVisible) rigController.setPartVisible(child, input.checked);
        else child.visible = input.checked;
        syncPartVisibility();
        requestRender();
      });
      var title = document.createElement("span");
      title.textContent = child.name || t("Part") + " " + count;
      label.appendChild(input);
      label.appendChild(title);
      label.appendChild(status);
      list.appendChild(label);
    });
    syncPartVisibility();
  }

  function syncPartVisibility() {
    // Synchronize the effective result, including STEP animation changes, without
    // sending another rig change or requesting a new animation frame.
    partInputs.forEach(function (entry) {
      var state = rigController && rigController.getPartVisibility ? rigController.getPartVisibility(entry.object) : null;
      var visible = state && typeof state.visible === "boolean" ? state.visible : !!entry.object.visible;
      if (entry.input.checked !== visible) entry.input.checked = visible;
      var current = String(visible);
      if (entry.input.dataset.viewerEffectiveVisible !== current) entry.input.dataset.viewerEffectiveVisible = current;
      var messages = [];
      if (typeof entry.fileVisible === "boolean") messages.push(t("File visibility") + ": " + t(entry.fileVisible ? "Visible" : "Hidden"));
      messages.push(t("Current visibility") + ": " + t(visible ? "Visible" : "Hidden"));
      var changed = state ? state.userChanged : entry.userChanged;
      var choice = state ? state.userVisible : entry.userVisible;
      if (changed && typeof choice === "boolean") messages.push(t("Your visibility choice") + ": " + t(choice ? "Visible" : "Hidden"));
      var text = messages.join(" · ");
      if (entry.status) {
        var hideStatus = !changed && (typeof entry.fileVisible !== "boolean" || entry.fileVisible === visible);
        if (entry.status.hidden !== hideStatus) entry.status.hidden = hideStatus;
        if (entry.status.textContent !== text) entry.status.textContent = text;
      }
    });
  }

  function rigChanged() {
    syncPartVisibility();
    requestRender();
  }

  function showWarnings(warnings) {
    var box = node("viewer-warning");
    var messages = (warnings || []).map(function (warning) {
      if (typeof warning === "string") return t(warning);
      return warning && warning.message ? t(warning.message) : "";
    }).filter(function (message, index, values) { return message && values.indexOf(message) === index; });
    box.hidden = !messages.length;
    box.textContent = messages.join("\n");
    seriousWarning = !!messages.length && (warnings || []).some(function (warning) {
      return typeof warning === "string" || warning && /missing|unavailable|failed|invalid|unsupported|partial|incomplete|limit|timeout|unmatched|conflict/i.test(warning.code || "");
    });
    refreshInfoVisibility();
  }

  function showFaceStatus() {
    var box = node("viewer-face-status");
    var faces = metadata && metadata.faces;
    var hasFaceWarning = metadata && (metadata.warnings || []).some(function (warning) {
      return warning && typeof warning.code === "string" && /^(face_|facial_)/.test(warning.code);
    });
    var message = "";
    if (!loading && !lost && faces && faces.enabled &&
        JSON.stringify(paths) === JSON.stringify(loadedPaths) &&
        node("viewer-auto-face").checked === loadedAutoFace && variantsLoaded()) {
      if (faces.status === "added" && Number(faces.added) > 0) message = "Missing face parts were added automatically.";
      else if (faces.status === "already_present") message = "The model already includes its face.";
      else if (faces.status === "partial" && Number(faces.added) > 0) {
        message = "Some face parts were added; other parts are still missing.";
      } else if (!hasFaceWarning && (faces.status === "partial" || faces.status === "unavailable")) {
        message = "The original face could not be added. The available costume parts are shown.";
      }
    }
    box.hidden = !message;
    box.textContent = message ? t(message) : "";
  }

  function restoreVariantPose(previous) {
    if (!previous || !rigController) return;
    var next = rigController.getState(), clip = previous.selectedClip;
    if (clip && next.clipNames.indexOf(clip) < 0) return;
    var motion = node("viewer-motion");
    motion.value = clip;
    motion.dispatchEvent(new Event("change", { bubbles: true }));
    if (clip && isFinite(previous.time)) {
      node("viewer-time").value = String(previous.time);
      node("viewer-time").dispatchEvent(new Event("input", { bubbles: true }));
      if (previous.playing && !node("viewer-play").disabled) node("viewer-play").click();
    }
  }

  async function loadSelected() {
    if (!paths.length) { setStatus("Choose a costume file to begin.", true); return; }
    if (!ensureRenderer()) return;
    var current = ++generation;
    if (controller) controller.abort();
    if (discardPendingPreview) discardPendingPreview();
    controller = new window.AbortController();
    var requestController = controller;
    var selected = paths.slice();
    var selectedAutoFace = node("viewer-auto-face").checked;
    var selectedVariants = variantsFor(selected);
    var archiveVariants = {};
    selected.forEach(function (path, index) {
      if (variantOptions[path] || selectedVariants[index] !== "primary") archiveVariants[index] = selectedVariants[index];
    });
    var payload = { paths: selected, auto_face: selectedAutoFace, rigged: true };
    if (Object.keys(archiveVariants).length) payload.archive_variants = archiveVariants;
    var pendingModel = null;
    var pendingMaterials = null;
    function discard() {
      if (pendingMaterials) pendingMaterials.dispose();
      if (pendingModel) disposeObject(pendingModel);
      pendingMaterials = null; pendingModel = null;
      if (discardPendingPreview === discard) discardPendingPreview = null;
    }
    setLoading(true);
    setStatus(selectedAutoFace ? "Checking model and face…" : "Preparing model…");
    try {
      var response = await window.fetch("/api/viewer/prepare", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload), signal: requestController.signal
      });
      var prepared = await response.json();
      if (!response.ok || prepared.error) throw new Error(prepared.error || "The costume file could not be opened.");
      if (current !== generation || !sameSelection(selected, selectedAutoFace, selectedVariants)) return;
      var nextVariantOptions = readVariantOptions(prepared.variants, selected, selectedVariants);
      if (typeof prepared.url !== "string" || !/^\/api\/viewer\/model\/[a-zA-Z0-9_-]+\.glb$/.test(prepared.url)) {
        throw new Error(t("The model could not be displayed. Try another costume file."));
      }
      setStatus("Loading 3D model…");
      var modelResponse = await window.fetch(prepared.url, { signal: requestController.signal });
      if (!modelResponse.ok) throw new Error(t("The preview expired. Open the model again."));
      var length = Number(modelResponse.headers.get("Content-Length"));
      if (length > MAX_GLB_BYTES) throw new Error(t("This model is too large to preview on this device."));
      var data = await modelResponse.arrayBuffer();
      if (data.byteLength > MAX_GLB_BYTES) throw new Error(t("This model is too large to preview on this device."));
      if (current !== generation || !sameSelection(selected, selectedAutoFace, selectedVariants)) return;
      var gltf = await new Promise(function (resolve, reject) {
        new window.THREE.GLTFLoader().parse(data, "", resolve, reject);
      });
      if (current !== generation || !sameSelection(selected, selectedAutoFace, selectedVariants)) {
        disposeObject(gltf.scene); return;
      }
      var next = gltf.scene;
      pendingModel = next;
      discardPendingPreview = discard;
      var nextBounds = new window.THREE.Box3().setFromObject(next);
      var restBounds = prepared.rig && prepared.rig.bounds;
      if (restBounds && Array.isArray(restBounds.min) && Array.isArray(restBounds.max) &&
          restBounds.min.concat(restBounds.max).length === 6 && restBounds.min.concat(restBounds.max).every(isFinite)) {
        nextBounds.set(new window.THREE.Vector3().fromArray(restBounds.min), new window.THREE.Vector3().fromArray(restBounds.max));
      }
      if (nextBounds.isEmpty() || !isFinite(nextBounds.min.x) || !isFinite(nextBounds.max.x)) {
        throw new Error(t("No visible model was found in these files."));
      }
      if (window.SifasMaterial && window.SifasMaterial.apply) {
        pendingMaterials = window.SifasMaterial.apply(next, renderer, {
          parser: gltf.parser, enabled: node("viewer-shader").value === "sifas", onChange: requestRender
        });
        if (pendingMaterials.ready) await pendingMaterials.ready;
      }
      if (current !== generation || !sameSelection(selected, selectedAutoFace, selectedVariants)) return;
      var keepView = !!model && JSON.stringify(selected) === JSON.stringify(loadedPaths) &&
        selectedAutoFace === loadedAutoFace && JSON.stringify(selectedVariants) !== JSON.stringify(loadedVariants);
      var previousPose = keepView && rigController ? rigController.getState() : null;
      disposePreviewControllers();
      if (model) { scene.remove(model); disposeObject(model); }
      model = next;
      bounds = nextBounds;
      metadata = prepared;
      loadedPaths = selected;
      loadedAutoFace = selectedAutoFace;
      loadedVariants = selectedVariants;
      variantOptions = nextVariantOptions;
      node("tab-viewer").classList.add("viewer-has-model");
      scene.add(model);
      materialController = pendingMaterials;
      pendingMaterials = null;
      pendingModel = null;
      if (window.ViewerRig) {
        rigController = window.ViewerRig.create(model, gltf.animations || [], prepared.rig || {}, { translate: t, onChange: rigChanged });
        restoreVariantPose(previousPose);
      }
      var materialState = materialController && materialController.getState ? materialController.getState() : null;
      node("viewer-shader").disabled = !materialState || !materialState.recognizedMaterials;
      node("viewer-shader").value = materialState && materialState.recognizedMaterials ? materialPreference : "basic";
      node("viewer-empty").hidden = true;
      buildParts();
      updateAppearance();
      showWarnings(prepared.warnings);
      resize();
      if (!keepView) setView("front");
      setStatus("Model ready.");
    } catch (error) {
      if (current !== generation) return;
      if (error && error.name === "AbortError") setStatus("Loading cancelled.");
      else setStatus("The model could not be displayed.", true, error && error.message ? error.message : "");
    } finally {
      discard();
      if (current === generation) {
        controller = null;
        setLoading(false);
        if (!sameSelection(selected, selectedAutoFace, selectedVariants)) filesChanged();
      }
    }
  }

  function focusElement(element) {
    if (!element || !element.focus || !element.isConnected) return;
    try { element.focus({ preventScroll: true }); } catch (_) { element.focus(); }
  }

  function isolateViewer(value) {
    if (!value) {
      outsideFocus.forEach(function (record) {
        if (record.aria === null) record.element.removeAttribute("aria-hidden");
        else record.element.setAttribute("aria-hidden", record.aria);
        if (record.inert !== null) record.element.inert = record.inert;
        record.tabs.forEach(function (entry) {
          if (entry.value === null) entry.element.removeAttribute("tabindex");
          else entry.element.setAttribute("tabindex", entry.value);
        });
      });
      outsideFocus = []; return;
    }
    var current = node("tab-viewer");
    while (current && current.parentElement) {
      Array.prototype.forEach.call(current.parentElement.children, function (element) {
        if (element === current || /^(SCRIPT|STYLE|LINK)$/.test(element.tagName)) return;
        var record = { element: element, aria: element.getAttribute("aria-hidden"), inert: "inert" in element ? element.inert : null, tabs: [] };
        var candidates = Array.prototype.slice.call(element.querySelectorAll("a[href],button,input,select,textarea,[tabindex],[contenteditable]"));
        if (element.matches("a[href],button,input,select,textarea,[tabindex],[contenteditable]")) candidates.unshift(element);
        candidates.forEach(function (item) { record.tabs.push({ element: item, value: item.getAttribute("tabindex") }); item.setAttribute("tabindex", "-1"); });
        element.setAttribute("aria-hidden", "true");
        if (record.inert !== null) element.inert = true;
        outsideFocus.push(record);
      });
      if (current.parentElement === document.body) break;
      current = current.parentElement;
    }
  }

  function setExpanded(value) {
    value = !!value;
    if (value && (destroyed || !active)) return;
    if (expanded === value) { scheduleResize(); return; }
    if (value) {
      lastFullscreenExit = 0;
      expandedSnapshot = { x: window.scrollX, y: window.scrollY, focus: document.activeElement };
      isolateViewer(true);
    }
    expanded = value;
    node("tab-viewer").classList.toggle("viewer-expanded", value);
    var label = t(value ? "Close expanded view" : "Expand view");
    node("viewer-expand").textContent = label;
    node("viewer-expand").title = label;
    node("viewer-expand").setAttribute("aria-label", label);
    node("viewer-expand").setAttribute("aria-pressed", String(value));
    document.body.classList.toggle("viewer-is-expanded", value);
    resize();
    if (value) focusElement(node("viewer-expand"));
    else {
      var snapshot = expandedSnapshot;
      expandedSnapshot = null;
      isolateViewer(false);
      if (snapshot) window.requestAnimationFrame(function () {
        if (expanded) return;
        if (!destroyed && active) focusElement(snapshot.focus);
        window.scrollTo(snapshot.x, snapshot.y);
        if (!destroyed) scheduleResize();
      });
    }
  }

  function browserFullscreenElement() { return document.fullscreenElement || document.webkitFullscreenElement || null; }
  function nativeFullscreenBridge() {
    var bridge = window.ElichikaViewerFullscreen;
    return bridge && typeof bridge.postMessage === "function" ? bridge : null;
  }
  function refreshFullscreenButton() {
    var button = node("viewer-fullscreen");
    if (!button) return;
    var on = fullscreenWanted || fullscreenMode !== "none";
    var label = t(on ? "Exit full screen" : "Full screen");
    button.textContent = label; button.title = label; button.setAttribute("aria-label", label);
    button.setAttribute("aria-pressed", String(on));
    node("tab-viewer").classList.toggle("viewer-fullscreen", fullscreenMode !== "none");
  }
  function setLayoutNotice(message) {
    layoutNotice = message || "";
    var status = node("viewer-layout-status");
    if (status) { status.hidden = !layoutNotice; status.textContent = layoutNotice ? t(layoutNotice) : ""; }
    refreshInfoVisibility();
  }
  function clearFullscreenTimer() {
    if (fullscreenTimer) window.clearTimeout(fullscreenTimer);
    fullscreenTimer = 0;
  }
  function finishFullscreenExit(forceCollapse) {
    clearFullscreenTimer();
    var snapshot = fullscreenSnapshot;
    fullscreenSnapshot = null; fullscreenWanted = false; fullscreenPending = ""; fullscreenMode = "none";
    lastFullscreenExit = Date.now();
    refreshFullscreenButton();
    setExpanded(forceCollapse ? false : snapshot ? snapshot.expanded : expanded);
    if (snapshot && active && !destroyed && !document.hidden) focusElement(snapshot.focus);
    scheduleResize();
  }
  function fullscreenFailed() {
    if (!fullscreenWanted || destroyed || !active) return;
    clearFullscreenTimer(); fullscreenWanted = false; fullscreenPending = ""; fullscreenMode = "none"; fullscreenSnapshot = null;
    refreshFullscreenButton();
    setLayoutNotice("Full screen is unavailable here. Expanded view is open.");
    scheduleResize();
  }
  function acceptFullscreen(mode) {
    if (!fullscreenWanted || !active || destroyed) { exitFullscreen(!active || destroyed); return; }
    clearFullscreenTimer(); fullscreenPending = ""; fullscreenMode = mode;
    refreshFullscreenButton(); setLayoutNotice(""); scheduleResize();
  }
  function enterFullscreen() {
    if (!active || destroyed) return;
    if (fullscreenWanted || fullscreenMode !== "none") { exitFullscreen(false); return; }
    fullscreenSnapshot = { expanded: expanded, focus: document.activeElement };
    lastFullscreenExit = 0;
    fullscreenWanted = true; fullscreenPending = "enter";
    setLayoutNotice(""); setExpanded(true); refreshFullscreenButton();
    focusElement(node("viewer-fullscreen"));
    fullscreenTimer = window.setTimeout(fullscreenFailed, 4000);
    var bridge = nativeFullscreenBridge();
    if (bridge) {
      try { bridge.postMessage("enter"); } catch (_) { fullscreenFailed(); }
      return;
    }
    var viewer = node("tab-viewer"), request = viewer.requestFullscreen || viewer.webkitRequestFullscreen;
    if (!request) { fullscreenFailed(); return; }
    try {
      var result = request.call(viewer, { navigationUI: "hide" });
      if (result && result.then) result.then(function () {
        if (browserFullscreenElement() === viewer) acceptFullscreen("browser");
      }, fullscreenFailed);
    } catch (_) { fullscreenFailed(); }
  }
  function exitFullscreen(forceCollapse) {
    fullscreenWanted = false;
    if (fullscreenSnapshot && forceCollapse) fullscreenSnapshot.expanded = false;
    clearFullscreenTimer();
    var bridge = nativeFullscreenBridge();
    if (bridge && (fullscreenMode === "native" || fullscreenPending)) {
      fullscreenPending = "exit";
      try { bridge.postMessage("exit"); } catch (_) { /* Native lifecycle also restores chrome on navigation. */ }
    }
    var element = browserFullscreenElement();
    if (element === node("tab-viewer")) {
      var exit = document.exitFullscreen || document.webkitExitFullscreen;
      if (exit) try { var result = exit.call(document); if (result && result.catch) result.catch(function () {}); } catch (_) {}
    }
    // Restore the web layout immediately. A delayed acknowledgement may only
    // confirm exit; it must never bring back an inactive/disposed viewer.
    finishFullscreenExit(!!forceCollapse);
  }
  function fullscreenChanged() {
    if (browserFullscreenElement() === node("tab-viewer")) acceptFullscreen("browser");
    else if (fullscreenMode === "browser" || fullscreenPending === "exit") finishFullscreenExit(false);
  }
  function nativeFullscreenChanged(event) {
    var detail = event && event.detail;
    if (!detail || typeof detail.active !== "boolean") return;
    // Page-finished broadcasts describe initialization, not command settlement.
    // A delayed initial false must not cancel a newer pending/accepted entry.
    if (!detail.active && detail.settled === false) return;
    if (detail.active) {
      if (!fullscreenWanted || destroyed || !active) {
        var bridge = nativeFullscreenBridge();
        if (bridge) try { bridge.postMessage("exit"); } catch (_) {}
        return;
      }
      acceptFullscreen("native");
    } else if (fullscreenMode === "native" || fullscreenPending === "enter" || fullscreenPending === "exit" || document.hidden) finishFullscreenExit(false);
  }
  function listenLayout(target, event, handler) {
    target.addEventListener(event, handler);
    layoutListeners.push(function () { target.removeEventListener(event, handler); });
  }

  function mount(options) {
    config = options;
    if (mounted) { updateLanguage(); return; }
    mounted = true;
    function pickCompanion() {
      if (paths.length >= MAX_FILES) return;
      containViewerPicker();
      try {
        config.pickFile(function (path) {
          if (destroyed) return;
          if (paths.indexOf(path) < 0) paths.push(path);
          renderFiles();
          filesChanged();
        });
        var picker = node("picker");
        if (picker && !picker.classList.contains("hidden")) focusElement(node("picker-cancel"));
      } catch (error) { restoreViewerPicker(); throw error; }
    }
    node("viewer-add").addEventListener("click", pickCompanion);
    node("viewer-add-motion").addEventListener("click", pickCompanion);
    node("viewer-load").addEventListener("click", loadSelected);
    node("viewer-cancel").addEventListener("click", cancelLoading);
    node("viewer-auto-face").addEventListener("change", filesChanged);
    node("viewer-high-quality").addEventListener("change", function () {
      if (qualityController) { qualityController.setEnabled(this.checked); resize(); }
      refreshQualityStatus();
    });
    node("viewer-fit").addEventListener("click", function () { fitModel(); });
    node("viewer-expand").addEventListener("click", function () {
      if (expanded && (fullscreenWanted || fullscreenMode !== "none")) exitFullscreen(true);
      else setExpanded(!expanded);
    });
    if (node("viewer-fullscreen")) node("viewer-fullscreen").addEventListener("click", enterFullscreen);
    bindViewportPopover(node("viewer-view-menu"));
    bindViewportPopover(node("viewer-info"));
    bindViewportPopover(node("viewer-workspace-menu"));
    document.querySelectorAll("[data-viewer-view]").forEach(function (button) {
      button.addEventListener("click", function () { setView(button.dataset.viewerView); });
    });
    node("viewer-textures").addEventListener("change", updateAppearance);
    node("viewer-wireframe").addEventListener("change", updateAppearance);
    node("viewer-shader").addEventListener("change", function () { materialPreference = this.value; updateAppearance(); });
    node("viewer-background").addEventListener("change", setBackground);
    node("viewer-fov").addEventListener("input", function () {
      node("viewer-fov-value").textContent = this.value + "°";
      if (camera) { camera.fov = Number(this.value); camera.updateProjectionMatrix(); requestRender(); }
    });
    listenLayout(window, "resize", scheduleResize);
    listenLayout(window, "orientationchange", scheduleResize);
    listenLayout(window, "scroll", scheduleResize);
    if (window.visualViewport) {
      listenLayout(window.visualViewport, "resize", scheduleResize);
      listenLayout(window.visualViewport, "scroll", scheduleResize);
    }
    listenLayout(document, "fullscreenchange", fullscreenChanged);
    listenLayout(document, "webkitfullscreenchange", fullscreenChanged);
    listenLayout(window, "elichika-native-fullscreen", nativeFullscreenChanged);
    listenLayout(document, "visibilitychange", function () { if (document.hidden) pauseRender(); else { scheduleResize(); requestRender(); } });
    listenLayout(document, "keydown", function (event) {
      if (!active || destroyed || event.defaultPrevented || event.key !== "Escape") return;
      var picker = node("picker");
      if ((shortHeight || pickerHome) && picker && !picker.classList.contains("hidden")) {
        event.preventDefault(); node("picker-cancel").click(); return;
      }
      var workspaceMenu = node("viewer-workspace-menu");
      if (workspaceMenu && workspaceMenu.open) {
        event.preventDefault(); workspaceMenu.open = false; refreshPopoverStack(null); focusElement(workspaceMenu.querySelector("summary")); return;
      }
      var viewMenu = node("viewer-view-menu");
      if (viewMenu && viewMenu.open) {
        event.preventDefault(); viewMenu.open = false; refreshPopoverStack(null); focusElement(viewMenu.querySelector("summary")); return;
      }
      var infoMenu = node("viewer-info");
      if (infoMenu && infoMenu.open) {
        event.preventDefault(); infoMenu.open = false; infoAutoOpened = false; refreshPopoverStack(null); focusElement(infoMenu.querySelector("summary")); return;
      }
      if (fullscreenWanted || fullscreenMode !== "none") { event.preventDefault(); exitFullscreen(false); }
      else if (expanded && Date.now() - lastFullscreenExit > 200) { event.preventDefault(); setExpanded(false); }
    });
    if (window.ResizeObserver) {
      resizeObserver = new window.ResizeObserver(scheduleResize);
      resizeObserver.observe(node("viewer-stage"));
      var header = document.querySelector("body > header");
      if (header) resizeObserver.observe(header);
      var files = node("tab-viewer").querySelector(".viewer-files");
      if (files) resizeObserver.observe(files);
      node("viewer-stage").querySelectorAll("[data-viewer-hud-edge]").forEach(function (hud) { resizeObserver.observe(hud); });
    }
    window.addEventListener("pagehide", function (event) { if (!event.persisted) dispose(); });
    updateLanguage();
    if (pendingOpen) {
      var pending = pendingOpen;
      pendingOpen = null;
      Promise.resolve(open(pending.paths)).then(pending.resolve, pending.resolve);
    }
  }

  function updateLanguage() {
    if (!mounted) return;
    renderFiles();
    refreshStatus();
    var expandLabel = t(expanded ? "Close expanded view" : "Expand view");
    node("viewer-expand").textContent = expandLabel;
    node("viewer-expand").title = expandLabel; node("viewer-expand").setAttribute("aria-label", expandLabel);
    refreshFullscreenButton();
    var notice = node("viewer-layout-status");
    if (notice) notice.textContent = layoutNotice ? t(layoutNotice) : "";
    if (renderer) renderer.domElement.setAttribute("aria-label", t("3D model"));
    if (metadata) showWarnings(metadata.warnings);
    showFaceStatus();
    if (rigController) rigController.updateLanguage();
    syncPartVisibility();
    refreshMaterialStatus();
    refreshQualityStatus();
    scheduleResize();
  }

  function setVisible(value) {
    if (destroyed) return;
    active = !!value;
    if (!active) {
      pauseRender();
      restoreViewerPicker();
      if (node("viewer-view-menu")) node("viewer-view-menu").open = false;
      if (fullscreenWanted || fullscreenMode !== "none" || fullscreenPending) exitFullscreen(true);
      if (expanded) setExpanded(false);
      updateShortLayout(null);
      return;
    }
    window.requestAnimationFrame(function () { resize(); requestRender(); });
  }

  function open(nextPaths) {
    if (!mounted) return new Promise(function (resolve) {
      if (pendingOpen) pendingOpen.resolve();
      pendingOpen = { paths: nextPaths, resolve: resolve };
    });
    var unique = [];
    (Array.isArray(nextPaths) ? nextPaths : [nextPaths]).forEach(function (path) {
      if (typeof path === "string" && path.trim() && unique.indexOf(path) < 0) unique.push(path);
    });
    if (unique.length > MAX_FILES) { setStatus("Choose up to eight costume files at a time.", true); return Promise.resolve(); }
    paths = unique;
    Object.keys(variantChoices).forEach(function (path) { if (paths.indexOf(path) < 0) delete variantChoices[path]; });
    Object.keys(variantOptions).forEach(function (path) { if (paths.indexOf(path) < 0) delete variantOptions[path]; });
    renderFiles();
    return loadSelected();
  }

  function dispose() {
    if (destroyed) return;
    active = false;
    restoreViewerPicker();
    if (node("viewer-view-menu")) node("viewer-view-menu").open = false;
    if (fullscreenWanted || fullscreenMode !== "none" || fullscreenPending) exitFullscreen(true);
    if (expanded) setExpanded(false);
    updateShortLayout(null);
    destroyed = true;
    generation += 1;
    if (controller) controller.abort();
    if (discardPendingPreview) discardPendingPreview();
    pauseRender();
    if (resizeFrame) window.cancelAnimationFrame(resizeFrame);
    resizeFrame = 0;
    clearFullscreenTimer();
    layoutListeners.forEach(function (remove) { remove(); }); layoutListeners = [];
    if (resizeObserver) resizeObserver.disconnect();
    if (controls) controls.dispose();
    disposePreviewControllers();
    disposeObject(model);
    if (qualityController) qualityController.dispose();
    if (renderer) renderer.dispose();
    model = null;
  }

  window.ModelViewer = {
    mount: mount, open: open, setVisible: setVisible, updateLanguage: updateLanguage, dispose: dispose,
    getState: function () {
      var names = [];
      if (model) model.traverse(function (child) { if (child.isMesh && !isViewerHelper(child)) names.push(child.name); });
      return { paths: paths.slice(), loadedPaths: loadedPaths.slice(), loading: loading, loaded: !!model,
        autoFace: node("viewer-auto-face") ? node("viewer-auto-face").checked : true,
        loadedAutoFace: loadedAutoFace, faces: metadata && metadata.faces ? metadata.faces : null,
        archiveVariants: variantsFor(paths), loadedArchiveVariants: loadedVariants.slice(),
        visible: active, contextLost: lost, hasRenderer: !!renderer, stats: metadata ? metadata.stats : null,
        meshNames: names, trianglesRendered: renderer ? modelRenderInfo.triangles : 0,
        sourceTriangles: visibleSourceTriangles(),
        renderedFrames: renderedFrames, error: statusError ? statusDetail || statusKey : "",
        modelId: metadata ? metadata.id : null,
        quality: qualityController ? qualityController.getState() : null,
        layout: { expanded: expanded, fullscreen: fullscreenMode, fullscreenPending: !!fullscreenPending,
          compactControls: compactControls, shortHeight: shortHeight,
          viewport: layoutState.viewport, stage: layoutState.stage, safeInsets: layoutState.safeInsets },
        camera: camera ? { position: camera.position.toArray(), target: controls.target.toArray(), fov: camera.fov } : null,
        rig: rigController ? rigController.getState() : null,
        materials: materialController && materialController.getState ? materialController.getState() : null };
    },
    // Device QA only: an optional denser grid can inspect small colored details.
    // Keep the original 11x11 samples by default, and read the framebuffer once
    // rather than issuing a GPU read for each sample. No model data is changed.
    // triangles/drawTriangles count actual GPU passes; sourceTriangles excludes
    // tagged preview helpers such as the separate SIFAS outline pass.
    renderProbe: function (gridSize) {
      if (!renderer || !model || lost) return { ready: false };
      renderScene();
      renderedFrames += 1;
      var gl = renderer.getContext();
      var size = renderer.getDrawingBufferSize(new window.THREE.Vector2());
      var width = Math.floor(size.x);
      var height = Math.floor(size.y);
      var bytes = width * height * 4;
      var maximumBytes = 32 * 1024 * 1024;
      if (width < 2 || height < 2 || bytes > maximumBytes) {
        return { ready: false, reason: "Framebuffer exceeds diagnostic read limits",
          width: width, height: height, maxReadBytes: maximumBytes };
      }
      var grid = typeof gridSize === "number" && isFinite(gridSize)
        ? Math.max(1, Math.min(65, Math.floor(gridSize))) : 11;
      var pixels = new Uint8Array(bytes);
      gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      var background = (width + 1) * 4;
      var changed = 0;
      var chromatic = 0;
      for (var row = 1; row <= grid; row += 1) {
        var y = Math.floor(height * row / (grid + 1));
        for (var column = 1; column <= grid; column += 1) {
          var x = Math.floor(width * column / (grid + 1));
          var offset = (y * width + x) * 4;
          var red = pixels[offset];
          var green = pixels[offset + 1];
          var blue = pixels[offset + 2];
          if (Math.abs(red - pixels[background]) + Math.abs(green - pixels[background + 1]) +
              Math.abs(blue - pixels[background + 2]) > 24) changed += 1;
          if (Math.max(red, green, blue) - Math.min(red, green, blue) > 64) chromatic += 1;
        }
      }
      return { ready: true, nonBackgroundSamples: changed, chromaticSamples: chromatic, samples: grid * grid,
        gridSize: grid, readPixelsCalls: 1, bytesRead: bytes,
        triangles: modelRenderInfo.triangles, sourceTriangles: visibleSourceTriangles(),
        drawTriangles: modelRenderInfo.triangles, renderedFrames: renderedFrames,
        width: width, height: height, glError: qualityController.readGLError() };
    }
  };
}());
