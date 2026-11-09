/* Real costume grafts: current wearer -> saved copy -> existing Unity tools. */
(function (global) {
  "use strict";
  var TEXT = {
    "Costume transplant": ["코스튬 이식", "衣装移植"],
    "Costume part transplant": ["코스튬 부분 이식", "衣装パーツ移植"],
    "Lower body replacement": ["하체 교체", "下半身の交換"],
    "Donor model": ["Donor 모델", "ドナーモデル"],
    "Choose donor costume": ["Donor 의상 불러오기", "ドナー衣装を選択"],
    "Load donor from game": ["게임에서 Donor 가져오기", "ゲームからドナーを選択"],
    "No donor selected.": ["Donor 의상을 선택해 주세요.", "ドナー衣装を選択してください。"],
    "Transplant": ["이식", "移植"], "Replace lower body": ["하체 교체", "下半身を交換"],
    "Part root bone": ["이식할 부분의 루트 본", "パーツのルートボーン"],
    "Choose a part": ["부분 선택", "パーツを選択"],
    "Upper cut Y": ["상단 절단면 Y", "上側の切断面 Y"],
    "Lower cut Y": ["하단 절단면 Y", "下側の切断面 Y"],
    "Cut preset": ["절단 범위 프리셋", "切断範囲プリセット"],
    "Knee to waist": ["무릎부터 허리까지", "膝から腰まで"],
    "Calf to waist": ["종아리부터 허리까지", "ふくらはぎから腰まで"],
    "Ankle to waist": ["발목부터 허리까지", "足首から腰まで"],
    "Custom range": ["직접 범위 지정", "範囲を指定"],
    "Replacement region": ["교체할 본 영역", "交換するボーン領域"],
    "Lower body": ["하체", "下半身"], "Lower body and belly": ["하체와 아랫배", "下半身と下腹部"],
    "Central body": ["몸통 중앙", "体の中心"],
    "The mesh between the blue lower plane and orange upper plane is replaced.": ["파란 하단 절단면과 주황 상단 절단면 사이의 메시를 교체합니다.", "青い下側の面とオレンジ色の上側の面の間のメッシュを交換します。"],
    "Uses the displayed wearer and preserves its current body edits in a new copy.": ["현재 표시된 모델에 이식하고 체형 편집을 반영한 새 복사본을 만듭니다.", "表示中のモデルに移植し、現在の体型編集を反映したコピーを作ります。"],
    "Use a single Unity model or a ZIP containing one model for transplanting.": ["이식에는 단일 Unity 모델이나 모델이 하나 들어 있는 ZIP을 사용하세요.", "移植には単独のUnityモデルか、モデルが1つのZIPを使用してください。"],
    "Preparing donor…": ["Donor 준비 중…", "ドナーを準備中…"],
    "Open a wearer model first.": ["먼저 이식받을 모델을 열어 주세요.", "先に移植先モデルを開いてください。"],
    "Transplanting…": ["이식 중…", "移植中…"],
    "Transplanted. The result is now displayed.": ["이식이 완료되어 결과를 표시합니다.", "移植が完了し、結果を表示しています。"],
    "The result was saved. Open it to inspect the transplant.": ["결과를 저장했습니다. 결과 열기로 이식 상태를 확인하세요.", "結果を保存しました。開いて移植を確認してください。"],
    "Open transplant result": ["이식 결과 열기", "移植結果を開く"],
    "The lower cut must be below the upper cut.": ["하단 절단면은 상단보다 낮아야 합니다.", "下側の切断面は上側より低くしてください。"],
    "The donor preview could not be displayed.": ["Donor 미리보기를 표시할 수 없습니다.", "ドナープレビューを表示できませんでした。"],
    "Correct invalid body values before transplanting.": ["유효하지 않은 체형 값을 수정한 뒤 이식해 주세요.", "体型の入力値を修正してから移植してください。"],
    "Save mesh edits before transplanting.": ["메시 편집을 저장한 뒤 이식해 주세요.", "メッシュの編集を保存してから移植してください。"]
  };
  function create(options) {
    options = options || {};
    var disposed = false, busy = false, jobId = "", events = null, entries = [];
    function t(key) {
      var lang = (document.documentElement.lang || "en").split("-")[0], value = TEXT[key];
      return value && (lang === "ko" || lang === "ja") ? value[lang === "ko" ? 0 : 1] : options.translate ? options.translate(key) : key;
    }
    function element(tag, attributes, children) {
      var node = document.createElement(tag);
      Object.keys(attributes || {}).forEach(function (key) {
        if (key === "text") node.textContent = t(attributes[key]);
        else if (key === "className") node.className = attributes[key];
        else node.setAttribute(key, attributes[key]);
      });
      (children || []).forEach(function (child) { node.appendChild(child); }); return node;
    }
    function label(key, control) { return element("label", {}, [element("span", { "data-transplant-label": key, text: key }), control]); }
    function context() {
      if (options.context) return options.context() || {};
      var state = global.ModelViewer && global.ModelViewer.getState();
      return state ? { modelId: state.modelId, editing: global.ModelViewer.getEditingMetadata(),
        authoring: global.ModelViewer.getAuthoringState(), current: state.loaded && !state.loading,
        persistence: state.persistence } : {};
    }
    function authoring(c) { return c.authoring || c.rig && c.rig.getAuthoringState && c.rig.getAuthoringState(); }
    function status(entry, message, error) {
      entry.statusKey = message;
      var value = t(message); if (entry.status.textContent !== value) entry.status.textContent = value;
      if (entry.status.classList.contains("viewer-warning") !== !!error) entry.status.classList.toggle("viewer-warning", !!error);
    }
    function refresh() {
      if (disposed) return;
      var c = context(), body = authoring(c), locked = busy || !!(c.persistence && c.persistence.busy) || !!(c.meshTools && c.meshTools.busy);
      var ready = c.current && c.editing && c.editing.available && body && !(body.unsupported || []).length;
      var meshDirty = !!(c.meshTools && c.meshTools.dirty);
      ready = ready && !meshDirty;
      entries.forEach(function (entry) {
        if (entry.pick.disabled !== locked) entry.pick.disabled = locked;
        if (entry.game.disabled !== locked) entry.game.disabled = locked;
        var disabled = !!(locked || !ready || !entry.donor || entry.inspecting || entry.operation === "part" && !entry.parts.value);
        if (entry.run.disabled !== disabled) entry.run.disabled = disabled;
        if (entry.cancel.hidden !== !entry.running) entry.cancel.hidden = !entry.running;
        if (meshDirty && !entry.running) status(entry, "Save mesh edits before transplanting.");
        if (!meshDirty && entry.statusKey === "Save mesh edits before transplanting.") status(entry, "");
        if (!meshDirty && !entry.donor && !entry.running && !entry.status.classList.contains("viewer-warning")) status(entry, ready ? "No donor selected." : "Open a wearer model first.");
      });
    }
    async function json(url, payload, signal) {
      var response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: signal });
      var data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText); return data;
    }
    function disposeObject(object) {
      if (!object) return;
      var textures = new Set();
      object.traverse(function (child) {
        if (child.geometry) child.geometry.dispose();
        var materials = Array.isArray(child.material) ? child.material : child.material ? [child.material] : [];
        materials.forEach(function (material) { Object.keys(material).forEach(function (key) { var value = material[key]; if (value && value.isTexture) textures.add(value); }); material.dispose(); });
      }); textures.forEach(function (texture) { texture.dispose(); });
    }
    function preview(entry) {
      if (entry.preview) return entry.preview;
      var THREE = global.THREE;
      if (!THREE || !THREE.GLTFLoader) throw new Error("The donor preview could not be displayed.");
      var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); renderer.setPixelRatio(Math.min(global.devicePixelRatio || 1, 1.5));
      renderer.setClearColor(0x172130, 1); renderer.outputEncoding = THREE.sRGBEncoding;
      entry.stage.replaceChildren(renderer.domElement);
      var scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(32, 1, .001, 1000);
      scene.add(new THREE.HemisphereLight(0xffffff, 0x657080, 2));
      var light = new THREE.DirectionalLight(0xffffff, .9); light.position.set(2, 3, 4); scene.add(light);
      var controls = new THREE.OrbitControls(camera, renderer.domElement); controls.enableDamping = false;
      var model = null, band = null, planes = [], size = null;
      function draw() {
        if (!entry.panel.open || entry.panel.hidden || !renderer.domElement.isConnected) return;
        var width = entry.stage.clientWidth, height = entry.stage.clientHeight;
        if (!width || !height) return;
        renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix(); renderer.render(scene, camera);
      }
      function cuts() {
        if (entry.operation !== "lower" || !size) { draw(); return; }
        planes.forEach(function (plane) { scene.remove(plane); plane.geometry.dispose(); plane.material.dispose(); }); planes = [];
        if (band) { scene.remove(band); band.geometry.dispose(); band.material.dispose(); band = null; }
        var low = Number(entry.low.value), high = Number(entry.high.value);
        if (!isFinite(low) || !isFinite(high) || low >= high) { draw(); return; }
        var extent = Math.max(size.x, size.z, .2) * 1.35;
        [low, high].forEach(function (height, index) {
          var plane = new THREE.Mesh(new THREE.PlaneGeometry(extent, extent), new THREE.MeshBasicMaterial({ color: index ? 0xffa44a : 0x42aaff, transparent: true, opacity: .32, side: THREE.DoubleSide, depthWrite: false }));
          plane.rotation.x = -Math.PI / 2; plane.position.y = height; scene.add(plane); planes.push(plane);
        });
        band = new THREE.Mesh(new THREE.BoxGeometry(extent, high - low, extent), new THREE.MeshBasicMaterial({ color: 0x5cb8f4, wireframe: true, transparent: true, opacity: .2, depthWrite: false }));
        band.position.y = (low + high) / 2; scene.add(band); draw();
      }
      controls.addEventListener("change", draw);
      var observer = new ResizeObserver(draw); observer.observe(entry.stage);
      entry.panel.addEventListener("toggle", draw);
      entry.preview = {
        draw: draw, cuts: cuts,
        set: function (object) {
          if (model) { scene.remove(model); disposeObject(model); }
          model = object; scene.add(model); model.updateMatrixWorld(true);
          var bounds = new THREE.Box3().setFromObject(model); size = bounds.getSize(new THREE.Vector3());
          var centre = bounds.getCenter(new THREE.Vector3()), distance = Math.max(size.x, size.y, size.z, .1) / (2 * Math.tan(camera.fov * Math.PI / 360)) * 1.18;
          controls.target.copy(centre); camera.position.copy(centre).add(new THREE.Vector3(distance * .2, distance * .05, distance)); camera.lookAt(centre); controls.update(); cuts();
        },
        dispose: function () { observer.disconnect(); entry.panel.removeEventListener("toggle", draw); controls.dispose(); disposeObject(model); planes.forEach(disposeObject); disposeObject(band); renderer.dispose(); renderer.forceContextLoss(); }
      }; return entry.preview;
    }
    async function chooseDonor(entry, paths, variants) {
      if (busy || disposed || !paths || paths.length !== 1) return;
      var token = ++entry.generation;
      if (entry.request) entry.request.abort();
      var controller = new AbortController(); entry.request = controller;
      entry.donor = paths[0]; entry.variant = variants && variants[0] || variants && variants["0"] || "primary";
      entry.file.value = String(paths[0]).replace(/\\/g, "/").split("/").pop();
      entry.inspecting = true; status(entry, "Preparing donor…"); refresh();
      try {
        var inspected = await json("/api/viewer/transplant/inspect", { donor: entry.donor, variant: entry.variant }, controller.signal);
        if (token !== entry.generation || disposed) return;
        entry.parts.replaceChildren(element("option", { value: "", text: "Choose a part" }));
        (inspected.parts || []).forEach(function (part) { entry.parts.appendChild(element("option", { value: part.value, text: part.label })); });
        if ((inspected.parts || []).length) entry.parts.value = inspected.parts[0].value;
        var payload = { paths: [entry.donor], rigged: false, auto_face: false };
        if (entry.variant === "unmasked") payload.archive_variants = { 0: entry.variant };
        var prepared = await json("/api/viewer/prepare", payload, controller.signal);
        if (!/^\/api\/viewer\/model\/[a-f0-9]{32}\.glb$/.test(prepared.url || "")) throw new Error("The donor preview could not be displayed.");
        var response = await fetch(prepared.url, { signal: controller.signal });
        if (!response.ok || Number(response.headers.get("Content-Length")) > 64 * 1024 * 1024) throw new Error("The donor preview could not be displayed.");
        var bytes = await response.arrayBuffer();
        if (bytes.byteLength > 64 * 1024 * 1024) throw new Error("The donor preview could not be displayed.");
        var gltf = await new Promise(function (resolve, reject) { new global.THREE.GLTFLoader().parse(bytes, "", resolve, reject); });
        if (disposed || token !== entry.generation) { disposeObject(gltf.scene); return; }
        preview(entry).set(gltf.scene); entry.stage.hidden = false; status(entry, "");
      } catch (error) {
        if (token === entry.generation && error.name !== "AbortError") { entry.donor = ""; status(entry, error.message, true); }
      } finally { if (token === entry.generation) { entry.inspecting = false; entry.request = null; refresh(); } }
    }
    function finish(entry) {
      if (events) events.close(); events = null; jobId = ""; busy = false; entry.running = false;
      entry.progress.hidden = true; if (options.busyChanged) options.busyChanged(false); refresh();
    }
    async function run(entry) {
      if (entry.run.disabled || busy) return;
      var c = context(), authored = authoring(c);
      if (!c.current || !c.editing || !authored) return;
      if (c.meshTools && (c.meshTools.dirty || c.meshTools.busy)) { status(entry, "Save mesh edits before transplanting.", true); return; }
      if (authored.unsupported && authored.unsupported.length) { status(entry, authored.unsupported[0], true); return; }
      var low = Number(entry.low.value), high = Number(entry.high.value);
      if (!isFinite(low) || !isFinite(high) || low >= high) { status(entry, "The lower cut must be below the upper cut.", true); return; }
      var state = JSON.parse(JSON.stringify(authored)); delete state.unsupported;
      var payload = { token: c.editing.token, state: state, donor: entry.donor, variant: entry.variant || "primary", operation: entry.operation,
        partRoot: entry.operation === "part" ? entry.parts.value : "", cutLow: low, cutHigh: high, region: entry.region.value };
      var fingerprint = JSON.stringify(authored), modelId = c.modelId;
      busy = true; entry.running = true; entry.log.textContent = ""; entry.log.hidden = false; entry.progress.hidden = false; entry.progress.removeAttribute("value"); entry.result.hidden = true;
      if (options.busyChanged) options.busyChanged(true); status(entry, "Transplanting…"); refresh();
      try {
        var data = await json("/api/viewer/transplant/run", payload);
        if (!/^[a-f0-9]{12}$/.test(data.job_id || "")) throw new Error("The costume operation could not be started.");
        jobId = data.job_id; events = new EventSource("/api/jobs/" + jobId + "/events");
        events.onmessage = async function (message) {
          if (disposed || !entry.running) return;
          try {
            var item = JSON.parse(message.data);
            if (item.type === "log") entry.log.textContent = (entry.log.textContent + String(item.line || "") + "\n").slice(-20000);
            if (item.type === "progress" && item.total > 0) { entry.progress.max = item.total; entry.progress.value = item.done; }
            if (item.type === "transplant") entry.resultVariant = item.variant || "primary";
            if (item.type !== "done") return;
            finish(entry);
            if (item.status !== "done") { status(entry, item.summary || "Cancelled", item.status === "error"); return; }
            var paths = item.output_paths;
            if (!Array.isArray(paths) || paths.length !== 1 || typeof paths[0] !== "string") throw new Error("The costume operation did not publish a model.");
            entry.resultPaths = paths; entry.result.hidden = false;
            var now = context();
            if (now.current && now.modelId === modelId && JSON.stringify(authoring(now)) === fingerprint) {
              await openResult(entry); status(entry, "Transplanted. The result is now displayed.");
            } else status(entry, "The result was saved. Open it to inspect the transplant.");
          } catch (error) { finish(entry); status(entry, error.message, true); }
        };
        events.onerror = function () { if (events && events.readyState === EventSource.CLOSED) { finish(entry); status(entry, "The costume operation connection closed. Check the server log.", true); } };
      } catch (error) { finish(entry); status(entry, error.message, true); }
    }
    async function openResult(entry) {
      var variants = /\.zip$/i.test(entry.resultPaths[0]) && entry.resultVariant === "unmasked" ? { 0: "unmasked" } : null;
      if (options.openFiles) await options.openFiles(entry.resultPaths, variants);
      else if (global.openModelViewer) await global.openModelViewer(entry.resultPaths, variants);
    }
    function addPanel(operation, id, title) {
      var entry = { operation: operation, generation: 0, donor: "", variant: "primary", inspecting: false, running: false, resultPaths: [] };
      entry.panel = element("details", { id: id, className: "viewer-adjustments viewer-transplant-panel", "data-panel-key": id });
      entry.panel.appendChild(element("summary", { "data-transplant-label": title, text: title }));
      entry.panel.appendChild(element("p", { className: "viewer-render-note", "data-transplant-label": "Uses the displayed wearer and preserves its current body edits in a new copy.", text: "Uses the displayed wearer and preserves its current body edits in a new copy." }));
      entry.file = element("input", { type: "text", readonly: "", "aria-label": t("Donor model") });
      entry.pick = element("button", { type: "button", "data-transplant-label": "Choose donor costume", text: "Choose donor costume" });
      entry.game = element("button", { type: "button", "data-transplant-label": "Load donor from game", text: "Load donor from game" });
      entry.panel.append(label("Donor model", entry.file), element("div", { className: "viewer-transplant-actions" }, [entry.pick, entry.game]));
      entry.stage = element("div", { className: "viewer-transplant-stage", hidden: "", "aria-label": t("Donor model") }); entry.panel.appendChild(entry.stage);
      entry.parts = element("select", { id: id + "-part" }); entry.parts.appendChild(element("option", { value: "", text: "Choose a part" }));
      var partLabel = label("Part root bone", entry.parts); partLabel.hidden = operation !== "part"; entry.panel.appendChild(partLabel);
      entry.low = element("input", { type: "number", step: ".005", min: "-10", max: "10", value: ".5", id: id + "-low" });
      entry.high = element("input", { type: "number", step: ".005", min: "-10", max: "10", value: ".96", id: id + "-high" });
      entry.preset = element("select", {});
      [{ value: "hip_fix", label: "Knee to waist" }, { value: "calf", label: "Calf to waist" }, { value: "ankle", label: "Ankle to waist" }, { value: "custom", label: "Custom range" }].forEach(function (value) { entry.preset.appendChild(element("option", { value: value.value, "data-transplant-label": value.label, text: value.label })); });
      entry.region = element("select", {});
      [{ value: "lower", label: "Lower body" }, { value: "lower_belly", label: "Lower body and belly" }, { value: "central", label: "Central body" }].forEach(function (value) { entry.region.appendChild(element("option", { value: value.value, "data-transplant-label": value.label, text: value.label })); });
      var cuts = element("div", { className: "viewer-transplant-cuts" }, [label("Cut preset", entry.preset), label("Upper cut Y", entry.high), label("Lower cut Y", entry.low), label("Replacement region", entry.region)]); cuts.hidden = operation !== "lower"; entry.panel.appendChild(cuts);
      var hint = element("p", { className: "viewer-render-note", "data-transplant-label": "The mesh between the blue lower plane and orange upper plane is replaced.", text: "The mesh between the blue lower plane and orange upper plane is replaced." }); hint.hidden = operation !== "lower"; entry.panel.appendChild(hint);
      entry.run = element("button", { type: "button", className: "viewer-primary", "data-transplant-label": operation === "lower" ? "Replace lower body" : "Transplant", text: operation === "lower" ? "Replace lower body" : "Transplant", disabled: "" });
      entry.cancel = element("button", { type: "button", text: "Cancel", hidden: "" });
      entry.result = element("button", { type: "button", "data-transplant-label": "Open transplant result", text: "Open transplant result", hidden: "" });
      entry.status = element("p", { className: "viewer-render-note", role: "status", "aria-live": "polite" });
      entry.progress = element("progress", { hidden: "" }); entry.log = element("pre", { className: "viewer-transplant-log", hidden: "" });
      entry.panel.append(element("div", { className: "viewer-transplant-actions" }, [entry.run, entry.cancel, entry.result]), entry.status, entry.progress, entry.log,
        element("p", { className: "viewer-render-note", "data-transplant-label": "Use a single Unity model or a ZIP containing one model for transplanting.", text: "Use a single Unity model or a ZIP containing one model for transplanting." }));
      document.getElementById("viewer-control-panel").appendChild(entry.panel);
      entry.pick.addEventListener("click", function () {
        var callback = function (path) { if (path) chooseDonor(entry, [path]); };
        if (options.pickFile) options.pickFile(callback); else if (global.openPicker) global.openPicker("path", callback, "models");
      });
      entry.game.addEventListener("click", function () { if (global.ViewerGameAssets) global.ViewerGameAssets.pick(function (paths, variants) { chooseDonor(entry, paths, variants); }); });
      entry.parts.addEventListener("change", refresh); entry.run.addEventListener("click", function () { run(entry); });
      entry.result.addEventListener("click", function () { openResult(entry); });
      entry.cancel.addEventListener("click", function () { if (jobId) fetch("/api/jobs/" + jobId + "/cancel", { method: "POST" }); });
      entry.preset.addEventListener("change", function () {
        var preset = { hip_fix: [.5, .96], calf: [.3, .96], ankle: [.11, .96] }[entry.preset.value];
        if (preset) { entry.low.value = preset[0]; entry.high.value = preset[1]; if (entry.preview) entry.preview.cuts(); }
      });
      [entry.low, entry.high].forEach(function (input) { input.addEventListener("input", function () { entry.preset.value = "custom"; if (entry.preview) entry.preview.cuts(); }); });
      entries.push(entry);
    }
    addPanel("costume", "viewer-costume-transplant", "Costume transplant");
    addPanel("part", "viewer-part-transplant", "Costume part transplant");
    addPanel("lower", "viewer-lower-transplant", "Lower body replacement");
    refresh();
    return {
      refresh: refresh,
      updateLanguage: function () {
        entries.forEach(function (entry) { entry.panel.querySelectorAll("[data-transplant-label]").forEach(function (node) { node.textContent = t(node.dataset.transplantLabel); }); status(entry, entry.statusKey || ""); }); refresh();
      },
      getState: function () { return { busy: busy, jobId: jobId, donors: entries.map(function (entry) { return { operation: entry.operation, donor: entry.donor, part: entry.parts.value, cutLow: Number(entry.low.value), cutHigh: Number(entry.high.value) }; }) }; },
      dispose: function () { disposed = true; if (events) events.close(); if (jobId) fetch("/api/jobs/" + jobId + "/cancel", { method: "POST" }); entries.forEach(function (entry) { if (entry.request) entry.request.abort(); if (entry.preview) entry.preview.dispose(); entry.panel.remove(); }); }
    };
  }
  global.ViewerTransplants = { create: create };
}(window));
