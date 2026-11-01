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
  var metadata = null;
  var generation = 0;
  var controller = null;
  var loading = false;
  var active = false;
  var lost = false;
  var renderer = null;
  var scene = null;
  var camera = null;
  var controls = null;
  var model = null;
  var frame = 0;
  var resizeObserver = null;
  var bounds = null;
  var expanded = false;
  var statusKey = "Choose a costume file to begin.";
  var statusError = false;
  var statusDetail = "";
  var destroyed = false;
  var renderedFrames = 0;

  function node(id) { return document.getElementById(id); }
  function t(key) { return config && config.translate ? config.translate(key) : key; }
  function basename(path) { return String(path).replace(/\/+$/, "").split("/").pop(); }
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
        renderFiles();
        filesChanged();
      });
      item.appendChild(name);
      item.appendChild(remove);
      list.appendChild(item);
    });
    node("viewer-add").textContent = t(paths.length ? "Add file" : "Choose costume file");
    node("viewer-add").disabled = loading || paths.length >= MAX_FILES;
    node("viewer-load").disabled = loading || !paths.length;
  }

  function filesChanged() {
    if (!paths.length) setStatus("Choose a costume file to begin.");
    else if (model && JSON.stringify(paths) !== JSON.stringify(loadedPaths)) {
      setStatus("Files changed. Press Open model to refresh the preview.");
    } else if (model && node("viewer-auto-face").checked !== loadedAutoFace) {
      setStatus("Face option changed. Press Open model to refresh the preview.");
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
    renderFiles();
    showFaceStatus();
  }

  function cancelLoading() {
    generation += 1;
    if (controller) controller.abort();
    controller = null;
    setLoading(false);
    setStatus("Loading cancelled.");
  }

  function requestRender() {
    if (frame || !active || document.hidden || !renderer || lost || destroyed) return;
    frame = window.requestAnimationFrame(draw);
  }

  function draw() {
    frame = 0;
    if (!active || document.hidden || !renderer || lost || destroyed) return;
    var changed = controls.update();
    renderer.render(scene, camera);
    renderedFrames += 1;
    if (changed) requestRender();
  }

  function pauseRender() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
  }

  function resize() {
    if (!renderer || !active || destroyed) return;
    var stage = node("viewer-stage");
    var width = stage.clientWidth;
    var height = stage.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    requestRender();
  }

  function ensureRenderer() {
    if (renderer) {
      if (lost) setStatus("3D graphics were interrupted. Wait a moment, then open the model again.", true);
      return !lost;
    }
    if (!window.THREE || !window.THREE.OrbitControls || !window.THREE.GLTFLoader) {
      setStatus("The 3D viewer files could not be loaded. Reopen the app and try again.", true);
      return false;
    }
    try {
      renderer = new window.THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "low-power" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
      renderer.outputEncoding = window.THREE.sRGBEncoding;
      renderer.toneMapping = window.THREE.NoToneMapping;
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
        // Abort the client load as well. A late preparation response must not
        // replace this interruption message with a misleading ready state.
        if (loading) {
          generation += 1;
          if (controller) controller.abort();
          controller = null;
          setLoading(false);
        }
        setStatus("3D graphics were interrupted. Wait a moment, then open the model again.", true);
        showFaceStatus();
      });
      renderer.domElement.addEventListener("webglcontextrestored", function () {
        lost = false;
        setStatus(model ? "Model ready." : "Choose a costume file to begin.");
        filesChanged();
        resize();
      });
      setBackground();
      resize();
      return true;
    } catch (error) {
      if (renderer) {
        renderer.dispose();
        if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
      if (controls) controls.dispose();
      renderer = null;
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
    var distance = (Math.max(halfWidth / Math.tan(halfHorizontal),
      halfHeight / Math.tan(halfVertical)) + halfDepth) * 1.12;
    camera.near = Math.max(0.001, radius / 1000);
    camera.far = Math.max(100, radius * 100);
    camera.up.set(0, 1, 0);
    camera.position.copy(sphere.center).addScaledVector(view, distance);
    camera.updateProjectionMatrix();
    controls.target.copy(sphere.center);
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

  function disposeObject(object) {
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
      if (texture.image && typeof texture.image.close === "function") texture.image.close();
      texture.dispose();
    });
  }

  function updateAppearance() {
    if (!model) return;
    var showTextures = node("viewer-textures").checked;
    var wireframe = node("viewer-wireframe").checked;
    model.traverse(function (child) {
      if (!child.isMesh) return;
      if (!child.userData.viewerOriginalMaterials) child.userData.viewerOriginalMaterials = child.material;
      if (!showTextures && !child.userData.viewerSolidMaterials) {
        var original = child.userData.viewerOriginalMaterials;
        var create = function () {
          return new window.THREE.MeshStandardMaterial({ color: 0xadb8c8, roughness: 0.85, metalness: 0, side: window.THREE.DoubleSide });
        };
        child.userData.viewerSolidMaterials = Array.isArray(original) ? original.map(create) : create();
      }
      child.material = showTextures ? child.userData.viewerOriginalMaterials : child.userData.viewerSolidMaterials;
      forEachMaterial(child.material, function (material) { material.wireframe = wireframe; });
    });
    requestRender();
  }

  function buildParts() {
    var list = node("viewer-parts");
    list.textContent = "";
    var count = 0;
    model.traverse(function (child) {
      if (!child.isMesh) return;
      count += 1;
      var label = document.createElement("label");
      var input = document.createElement("input");
      input.type = "checkbox";
      if (child.userData.hidden_default === true || child.userData.hideInPreview === true) child.visible = false;
      input.checked = child.visible;
      input.addEventListener("change", function () { child.visible = input.checked; requestRender(); });
      var title = document.createElement("span");
      title.textContent = child.name || t("Part") + " " + count;
      label.appendChild(input);
      label.appendChild(title);
      list.appendChild(label);
    });
  }

  function showWarnings(warnings) {
    var box = node("viewer-warning");
    var messages = (warnings || []).map(function (warning) {
      if (typeof warning === "string") return t(warning);
      return warning && warning.message ? t(warning.message) : "";
    }).filter(function (message, index, values) { return message && values.indexOf(message) === index; });
    box.hidden = !messages.length;
    box.textContent = messages.join("\n");
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
        node("viewer-auto-face").checked === loadedAutoFace) {
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

  async function loadSelected() {
    if (!paths.length) { setStatus("Choose a costume file to begin.", true); return; }
    if (!ensureRenderer()) return;
    var current = ++generation;
    if (controller) controller.abort();
    controller = new window.AbortController();
    var requestController = controller;
    var selected = paths.slice();
    var selectedAutoFace = node("viewer-auto-face").checked;
    setLoading(true);
    setStatus(selectedAutoFace ? "Checking model and face…" : "Preparing model…");
    try {
      var response = await window.fetch("/api/viewer/prepare", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: selected, auto_face: selectedAutoFace }), signal: requestController.signal
      });
      var prepared = await response.json();
      if (!response.ok || prepared.error) throw new Error(prepared.error || "The costume file could not be opened.");
      if (current !== generation || selectedAutoFace !== node("viewer-auto-face").checked) return;
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
      if (current !== generation || selectedAutoFace !== node("viewer-auto-face").checked) return;
      var gltf = await new Promise(function (resolve, reject) {
        new window.THREE.GLTFLoader().parse(data, "", resolve, reject);
      });
      if (current !== generation || selectedAutoFace !== node("viewer-auto-face").checked || destroyed) {
        disposeObject(gltf.scene); return;
      }
      var next = gltf.scene;
      var nextBounds = new window.THREE.Box3().setFromObject(next);
      if (nextBounds.isEmpty() || !isFinite(nextBounds.min.x) || !isFinite(nextBounds.max.x)) {
        disposeObject(next);
        throw new Error(t("No visible model was found in these files."));
      }
      if (model) { scene.remove(model); disposeObject(model); }
      model = next;
      bounds = nextBounds;
      metadata = prepared;
      loadedPaths = selected;
      loadedAutoFace = selectedAutoFace;
      scene.add(model);
      node("viewer-empty").hidden = true;
      buildParts();
      updateAppearance();
      showWarnings(prepared.warnings);
      resize();
      setView("front");
      setStatus("Model ready.");
    } catch (error) {
      if (current !== generation) return;
      if (error && error.name === "AbortError") setStatus("Loading cancelled.");
      else setStatus("The model could not be displayed.", true, error && error.message ? error.message : "");
    } finally {
      if (current === generation) {
        controller = null;
        setLoading(false);
        if (selectedAutoFace !== node("viewer-auto-face").checked) filesChanged();
      }
    }
  }

  function setExpanded(value) {
    expanded = value;
    node("tab-viewer").classList.toggle("viewer-expanded", value);
    node("viewer-expand").textContent = t(value ? "Close expanded view" : "Expand view");
    document.body.classList.toggle("viewer-is-expanded", value);
    resize();
  }

  function mount(options) {
    config = options;
    if (mounted) { updateLanguage(); return; }
    mounted = true;
    node("viewer-add").addEventListener("click", function () {
      if (paths.length >= MAX_FILES) return;
      config.pickFile(function (path) {
        if (paths.indexOf(path) < 0) paths.push(path);
        renderFiles();
        filesChanged();
      });
    });
    node("viewer-load").addEventListener("click", loadSelected);
    node("viewer-cancel").addEventListener("click", cancelLoading);
    node("viewer-auto-face").addEventListener("change", filesChanged);
    node("viewer-fit").addEventListener("click", function () { fitModel(); });
    node("viewer-expand").addEventListener("click", function () { setExpanded(!expanded); });
    document.querySelectorAll("[data-viewer-view]").forEach(function (button) {
      button.addEventListener("click", function () { setView(button.dataset.viewerView); });
    });
    node("viewer-textures").addEventListener("change", updateAppearance);
    node("viewer-wireframe").addEventListener("change", updateAppearance);
    node("viewer-background").addEventListener("change", setBackground);
    node("viewer-fov").addEventListener("input", function () {
      node("viewer-fov-value").textContent = this.value + "°";
      if (camera) { camera.fov = Number(this.value); camera.updateProjectionMatrix(); requestRender(); }
    });
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", function () { if (document.hidden) pauseRender(); else requestRender(); });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape" && expanded) setExpanded(false); });
    if (window.ResizeObserver) { resizeObserver = new window.ResizeObserver(resize); resizeObserver.observe(node("viewer-stage")); }
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
    node("viewer-expand").textContent = t(expanded ? "Close expanded view" : "Expand view");
    if (renderer) renderer.domElement.setAttribute("aria-label", t("3D model"));
    if (metadata) showWarnings(metadata.warnings);
    showFaceStatus();
  }

  function setVisible(value) {
    active = !!value;
    if (!active) { pauseRender(); if (expanded) setExpanded(false); return; }
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
    renderFiles();
    return loadSelected();
  }

  function dispose() {
    destroyed = true;
    generation += 1;
    if (controller) controller.abort();
    pauseRender();
    if (resizeObserver) resizeObserver.disconnect();
    if (controls) controls.dispose();
    disposeObject(model);
    if (renderer) renderer.dispose();
    model = null;
  }

  window.ModelViewer = {
    mount: mount, open: open, setVisible: setVisible, updateLanguage: updateLanguage, dispose: dispose,
    getState: function () {
      var names = [];
      if (model) model.traverse(function (child) { if (child.isMesh) names.push(child.name); });
      return { paths: paths.slice(), loadedPaths: loadedPaths.slice(), loading: loading, loaded: !!model,
        autoFace: node("viewer-auto-face") ? node("viewer-auto-face").checked : true,
        loadedAutoFace: loadedAutoFace, faces: metadata && metadata.faces ? metadata.faces : null,
        visible: active, contextLost: lost, hasRenderer: !!renderer, stats: metadata ? metadata.stats : null,
        meshNames: names, trianglesRendered: renderer ? renderer.info.render.triangles : 0,
        renderedFrames: renderedFrames, error: statusError ? statusDetail || statusKey : "",
        modelId: metadata ? metadata.id : null };
    },
    // Device QA only: an optional denser grid can inspect small colored details.
    // Keep the original 11x11 samples by default, and read the framebuffer once
    // rather than issuing a GPU read for each sample. No model data is changed.
    renderProbe: function (gridSize) {
      if (!renderer || !model || lost) return { ready: false };
      renderer.render(scene, camera);
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
        triangles: renderer.info.render.triangles, renderedFrames: renderedFrames,
        width: width, height: height, glError: gl.getError() };
    }
  };
}());
