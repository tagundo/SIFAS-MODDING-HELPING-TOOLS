"use strict";

const state = {
  tools: [],
  roots: {},
  currentTool: null,
  currentMode: "single",
  es: null,
  picker: null, // { type: 'path'|'dir', onPick: fn, cwd: str }
  lang: "en",
  strings: {},       // { "English source": "translation" } for the active language
  languages: [],     // [["en","English"], ...] from the server
};

const $ = (sel) => document.querySelector(sel);

// ------------------------------------------------------------------ i18n
const SUPPORTED_LANGS = ["en", "ko", "ja"];

function detectLang() {
  const saved = localStorage.getItem("sifas_lang");
  if (saved && SUPPORTED_LANGS.includes(saved)) return saved;
  const nav = (navigator.language || "en").slice(0, 2).toLowerCase();
  return SUPPORTED_LANGS.includes(nav) ? nav : "en";
}

// translate an English source string for the active language (English fallback)
function T(s) {
  return (state.strings && state.strings[s]) || s;
}

async function loadI18n() {
  try {
    const data = await (await fetch("/api/i18n?lang=" + encodeURIComponent(state.lang))).json();
    state.strings = data.strings || {};
    state.languages = data.languages || [];
    state.lang = data.lang || state.lang;
  } catch (e) {
    state.strings = {};
  }
}

// re-translate the static markup (anything tagged with data-i18n / data-i18n-ph)
function applyStaticI18n() {
  document.documentElement.lang = state.lang;
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = T(n.dataset.i18n); });
  document.querySelectorAll("[data-i18n-ph]").forEach((n) => { n.placeholder = T(n.dataset.i18nPh); });
}

function buildLangSelect() {
  const sel = $("#lang-select");
  if (!sel) return;
  sel.innerHTML = "";
  const langs = state.languages.length ? state.languages : SUPPORTED_LANGS.map((c) => [c, c]);
  for (const [code, name] of langs) {
    const o = el("option", { value: code, text: name });
    if (code === state.lang) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => changeLang(sel.value);
}

async function changeLang(code) {
  state.lang = code;
  localStorage.setItem("sifas_lang", code);
  await reloadForLang();
}

// reload everything that carries server-translated text and re-render the UI
async function reloadForLang() {
  await loadI18n();
  applyStaticI18n();
  buildLangSelect();
  await loadTools();
  if (state.currentTool) {
    const keep = state.currentTool.id;
    const again = state.tools.find((t) => t.id === keep);
    if (again) { state.currentTool = again; renderForm(); }
  }
}

async function loadTools() {
  try {
    const data = await (await fetch("/api/tools?lang=" + encodeURIComponent(state.lang))).json();
    state.tools = data.tools || [];
    state.roots = data.roots || {};
    renderToolList();
  } catch (e) {
    $("#tool-panel").innerHTML = "<p class='hint'>" + T("Failed to load tools: ") + e + "</p>";
  }
}
const el = (tag, attrs = {}, children = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  return n;
};

// ----------------------------------------------------------------- bootstrap
async function init() {
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => switchTab(t.dataset.tab)));
  $("#cancel-btn").addEventListener("click", cancelRun);
  $("#console-close").addEventListener("click", () => $("#console").classList.add("hidden"));
  $("#picker-cancel").addEventListener("click", closePicker);
  $("#picker-use-folder").addEventListener("click", () => {
    if (state.picker) { state.picker.onPick(state.picker.cwd); closePicker(); }
  });
  $("#gallery-browse").addEventListener("click", () =>
    openPicker("dir", (p) => { $("#gallery-path").value = p; }, "modded"));
  $("#gallery-load").addEventListener("click", loadGallery);
  $("#preview-browse").addEventListener("click", () =>
    openPicker("path", (p) => { $("#preview-path").value = p; renderBundle(p); }, "modded"));
  $("#preview-load").addEventListener("click", () => {
    const p = $("#preview-path").value;
    if (p) renderBundle(p);
  });

  state.lang = detectLang();
  await loadI18n();
  applyStaticI18n();
  buildLangSelect();
  await loadTools();
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  $("#tab-" + name).classList.add("active");
  // pause the 3D render loop while the preview tab is hidden; resume on return
  if (name !== "preview" && viewer.raf) { cancelAnimationFrame(viewer.raf); viewer.raf = 0; }
  else if (name === "preview" && viewer.renderer && !viewer.raf) resumeViewer();
}

function resumeViewer() {
  const tick = () => {
    viewer.raf = requestAnimationFrame(tick);
    if (viewer.controls) viewer.controls.update();
    if (viewer.renderer) viewer.renderer.render(viewer.scene, viewer.camera);
  };
  tick();
}

// ------------------------------------------------------------------- tools
function renderToolList() {
  const list = $("#tool-list");
  list.innerHTML = "";
  for (const tool of state.tools) {
    // list shows the title only; the description is shown in the tool panel when opened
    const b = el("button", { onclick: () => selectTool(tool.id) },
      [el("span", { text: tool.label })]);
    b.dataset.id = tool.id;
    list.appendChild(b);
  }
}

function selectTool(id) {
  state.currentTool = state.tools.find((t) => t.id === id);
  state.currentMode = (state.currentTool.modes || ["single"])[0];
  document.querySelectorAll("#tool-list button").forEach((b) =>
    b.classList.toggle("active", b.dataset.id === id));
  renderForm();
}

function renderForm() {
  const tool = state.currentTool;
  const panel = $("#tool-panel");
  panel.innerHTML = "";
  panel.appendChild(el("h2", { text: tool.label }));
  panel.appendChild(el("p", { class: "desc", text: tool.description || "" }));

  const modes = tool.modes || ["single"];
  if (modes.length > 1) {
    const toggle = el("div", { class: "mode-toggle" });
    for (const m of modes) {
      const mb = el("button", {
        text: m === "single" ? T("Single file")
          : m === "multi" ? T("Selected files") : T("Batch folder"),
        onclick: () => { state.currentMode = m; renderForm(); },
      });
      if (m === state.currentMode) mb.classList.add("active");
      toggle.appendChild(mb);
    }
    panel.appendChild(toggle);
  }

  const form = el("form", { id: "tool-form", onsubmit: (e) => { e.preventDefault(); runTool(); } });
  for (const field of tool.fields) {
    if (field.mode && field.mode !== state.currentMode) continue;
    form.appendChild(renderField(field));
  }
  form.appendChild(el("button", { class: "run-btn", type: "submit", text: T("Run") }));
  panel.appendChild(form);
  wireDynamicSelects(tool);
}

// Fetch a dynamic_select field's options from the server, keyed on its
// dependency field values (e.g. the donor path), and repopulate the <select>.
async function loadDynamicOptions(field, sel) {
  // Guard against out-of-order responses: only the newest request may repopulate
  // the <select> (a slow reply for an old donor must not clobber a newer one).
  const gen = (sel._optGen = (sel._optGen || 0) + 1);
  const parts = (field.depends || []).map((d) => {
    const dep = document.querySelector(`#tool-form [data-name="${d}"]`);
    return encodeURIComponent(d) + "=" + encodeURIComponent(dep ? dep.value : "");
  });
  parts.push("lang=" + encodeURIComponent(state.lang || "en"));
  const prev = sel.value;
  sel.innerHTML = "";
  sel.appendChild(el("option", { value: "", text: T("loading…") }));
  try {
    const url = "/api/options/" + encodeURIComponent(state.currentTool.id) +
      "/" + encodeURIComponent(field.name) + "?" + parts.join("&");
    const data = await (await fetch(url)).json();
    if (gen !== sel._optGen) return;   // superseded by a newer request
    sel.innerHTML = "";
    sel.appendChild(el("option", { value: "", text: T(field.blank_label || "(auto)") }));
    for (const o of data.options || []) {
      const value = (o && typeof o === "object") ? o.value : o;
      const label = (o && typeof o === "object") ? o.label : o;
      sel.appendChild(el("option", { value: String(value), text: String(label) }));
    }
    if (data.error) sel.appendChild(el("option", { value: "", text: "(" + data.error + ")" }));
    if (prev) sel.value = prev;   // keep the current choice if it's still offered
  } catch (e) {
    if (gen !== sel._optGen) return;
    sel.innerHTML = "";
    sel.appendChild(el("option", { value: "", text: "(error: " + e + ")" }));
  }
}

// After a form is built, wire each dynamic_select: reload when a dependency
// changes, and auto-load once if every dependency already has a value.
function wireDynamicSelects(tool) {
  for (const field of tool.fields) {
    if (field.type !== "dynamic_select") continue;
    if (field.mode && field.mode !== state.currentMode) continue;
    const sel = document.querySelector(`#tool-form [data-name="${field.name}"]`);
    if (!sel) continue;
    for (const dep of field.depends || []) {
      const depEl = document.querySelector(`#tool-form [data-name="${dep}"]`);
      // 'change' (not 'input') so a path picked via Browse or typed-then-blurred
      // triggers ONE reload, not one expensive bundle-inspect per keystroke.
      if (depEl) depEl.addEventListener("change", () => loadDynamicOptions(field, sel));
    }
    const ready = (field.depends || []).every((d) => {
      const e = document.querySelector(`#tool-form [data-name="${d}"]`);
      return e && e.value;
    });
    if (ready) loadDynamicOptions(field, sel);
  }
}

function renderField(field) {
  const wrap = el("div", { class: "field" + (field.type === "checkbox" ? " checkbox" : "") });
  const id = "f_" + field.name;

  if (field.type === "checkbox") {
    const input = el("input", { type: "checkbox", id });
    input.dataset.name = field.name;
    input.dataset.ftype = "checkbox";
    if (field.default) input.checked = true;
    wrap.appendChild(el("label", {}, [input, document.createTextNode(" " + field.label)]));
    if (field.help) wrap.appendChild(el("div", { class: "help", text: field.help }));
    return wrap;
  }

  wrap.appendChild(el("label", { for: id, text: field.label }));

  if (field.type === "select") {
    const sel = el("select", { id });
    sel.dataset.name = field.name;
    sel.dataset.ftype = "select";
    for (const opt of field.options || []) {
      // options may be plain strings (value == label) or {value, label} objects
      const value = (opt && typeof opt === "object") ? opt.value : opt;
      const label = (opt && typeof opt === "object") ? opt.label : opt;
      const o = el("option", { value: String(value), text: String(label) });
      if (value === field.default) o.selected = true;
      sel.appendChild(o);
    }
    wrap.appendChild(sel);
  } else if (field.type === "dynamic_select") {
    // A select whose options are fetched from the server based on a dependency
    // field (e.g. the donor path) — press Load, or it auto-loads when the
    // dependency is set. Collected like a normal select.
    const sel = el("select", { id });
    sel.dataset.name = field.name;
    sel.dataset.ftype = "select";
    sel.appendChild(el("option", { value: "", text: T(field.blank_label || "(auto)") }));
    const load = el("button", {
      type: "button", text: T("Load"),
      onclick: () => loadDynamicOptions(field, sel),
    });
    wrap.appendChild(el("div", { class: "path-row" }, [sel, load]));
  } else if (field.type === "preset") {
    // A convenience picker: choosing a preset fills sibling fields with named
    // values (restores the GUI's preset buttons). UI-only — not submitted.
    const sel = el("select", { id });
    sel.dataset.name = field.name;
    sel.dataset.ftype = "preset";
    for (const opt of field.options || []) {
      sel.appendChild(el("option", { value: opt.label, text: opt.label }));
    }
    sel.addEventListener("change", () => {
      const chosen = (field.options || []).find((o) => o.label === sel.value);
      if (!chosen || !chosen.set) return;
      for (const k in chosen.set) {
        const t = document.querySelector(`#tool-form [data-name="${k}"]`);
        if (!t) continue;
        if (t.dataset.ftype === "checkbox") t.checked = !!chosen.set[k];
        else t.value = String(chosen.set[k]);
      }
    });
    wrap.appendChild(sel);
  } else if (field.type === "vec3") {
    // three small X/Y/Z inputs on one line, each keeping its own param name
    const row = el("div", { class: "vec3-row" });
    for (const [axis, nm] of [["X", field.name_x], ["Y", field.name_y], ["Z", field.name_z]]) {
      const input = el("input", {
        type: "text",
        value: field.default !== undefined ? String(field.default) : "",
      });
      input.setAttribute("inputmode", "decimal");
      input.setAttribute("placeholder", axis);
      input.setAttribute("aria-label", field.label + " " + axis);
      input.dataset.name = nm;
      input.dataset.ftype = "number";
      row.appendChild(input);
    }
    wrap.appendChild(row);
  } else if (field.type === "path" || field.type === "dir") {
    const input = el("input", { type: "text", id, value: defaultPath(field) });
    input.dataset.name = field.name;
    input.dataset.ftype = field.type;
    const browse = el("button", {
      type: "button", text: T("Browse"),
      onclick: () => openPicker(field.type, (p) => {
        input.value = p;
        input.dispatchEvent(new Event("change", { bubbles: true }));  // notify dynamic_select deps
      }, field.root, input.value),
    });
    wrap.appendChild(el("div", { class: "path-row" }, [input, browse]));
  } else if (field.type === "paths") {
    // multi-select: a hidden newline-joined value (collected as the param) plus a
    // visible removable list; "Add file" opens the picker and appends each pick.
    const hidden = el("input", { type: "hidden" });
    hidden.dataset.name = field.name;
    hidden.dataset.ftype = "paths";
    hidden.value = "";
    const listEl = el("ul", { class: "multi-list" });
    const items = () => (hidden.value ? hidden.value.split("\n").filter(Boolean) : []);
    const rerender = () => {
      listEl.innerHTML = "";
      const cur = items();
      if (!cur.length) {
        listEl.appendChild(el("li", { class: "muted", text: T("No files selected.") }));
      }
      for (const p of cur) {
        const rm = el("button", {
          type: "button", class: "multi-rm", text: "✕",
          onclick: () => { hidden.value = items().filter((q) => q !== p).join("\n"); rerender(); },
        });
        listEl.appendChild(el("li", {}, [el("span", { text: baseName(p) }), rm]));
      }
    };
    const add = el("button", {
      type: "button", text: T("Add file"),
      onclick: () => openPicker("path", (p) => {
        const cur = items();
        if (!cur.includes(p)) { cur.push(p); hidden.value = cur.join("\n"); rerender(); }
      }, field.root, ""),
    });
    wrap.appendChild(hidden);
    wrap.appendChild(el("div", { class: "path-row" }, [add]));
    wrap.appendChild(listEl);
    rerender();
  } else if (field.type === "textarea") {
    const ta = el("textarea", { id, rows: "3" });
    ta.value = field.default !== undefined ? String(field.default) : "";
    ta.dataset.name = field.name;
    ta.dataset.ftype = field.type;
    wrap.appendChild(ta);
  } else {
    const input = el("input", {
      type: "text", id,
      value: field.default !== undefined ? String(field.default) : "",
    });
    if (field.type === "number") {
      input.setAttribute("inputmode", "decimal");
      input.classList.add("num"); // narrower than full-width text fields
    }
    input.dataset.name = field.name;
    input.dataset.ftype = field.type;
    wrap.appendChild(input);
  }
  if (field.help) wrap.appendChild(el("div", { class: "help", text: field.help }));
  return wrap;
}

function defaultPath(field) {
  // dir fields prefill with their root; file fields start blank
  if (field.type === "dir" && field.root && state.roots[field.root]) return state.roots[field.root];
  return "";
}

function baseName(p) {
  return String(p).replace(/\/+$/, "").split("/").pop();
}

function collectParams() {
  const params = { mode: state.currentMode };
  document.querySelectorAll("#tool-form [data-name]").forEach((inp) => {
    const name = inp.dataset.name;
    if (inp.dataset.ftype === "preset") return; // UI-only; it fills other fields
    if (inp.dataset.ftype === "checkbox") params[name] = inp.checked;
    else params[name] = inp.value;
  });
  return params;
}

// -------------------------------------------------------------------- run
async function runTool() {
  const params = collectParams();
  const tool = state.currentTool;

  // generic required-field validation (respects the current single/batch mode)
  const missing = [];
  for (const f of tool.fields) {
    if (f.mode && f.mode !== state.currentMode) continue;
    if (f.required && !String(params[f.name] ?? "").trim()) missing.push(f.label);
  }
  if (missing.length) return alert(T("Please fill in: ") + missing.join(", "));

  openConsole(tool.label);
  let resp;
  try {
    resp = await (await fetch("/api/run/" + tool.id, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    })).json();
  } catch (e) {
    appendLog("ERROR: " + e); finishConsole("error"); return;
  }
  if (resp.error) { appendLog("ERROR: " + resp.error); finishConsole("error"); return; }
  streamJob(resp.job_id);
}

function streamJob(jobId) {
  state.jobId = jobId;
  const es = new EventSource("/api/jobs/" + jobId + "/events");
  state.es = es;
  es.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === "log") appendLog(msg.line);
    else if (msg.type === "progress") setProgress(msg.done, msg.total);
    else if (msg.type === "error") appendLog("ERROR: " + msg.message);
    else if (msg.type === "done") {
      if (msg.summary) appendLog("\n" + msg.summary);
      finishConsole(msg.status);
      es.close(); state.es = null;
    }
  };
  es.onerror = () => { /* server closes the stream on done; ignore */ };
}

async function cancelRun() {
  if (!state.jobId) return;
  appendLog(T("[cancelling…]"));
  try { await fetch("/api/jobs/" + state.jobId + "/cancel", { method: "POST" }); } catch {}
}

function openConsole(title) {
  $("#console").classList.remove("hidden");
  $("#console-title").textContent = title + " — " + T("running…");
  $("#log").textContent = "";
  $("#cancel-btn").disabled = false;
  setProgress(0, 1);
}
function finishConsole(status) {
  const label = status === "done" ? T("done ✓") : status === "cancelled" ? T("cancelled") : T("error ✗");
  $("#console-title").textContent = (state.currentTool ? state.currentTool.label : T("Job")) + " — " + label;
  $("#cancel-btn").disabled = true;
}
function appendLog(line) {
  const log = $("#log");
  log.textContent += (line + "\n");
  log.scrollTop = log.scrollHeight;
}
function setProgress(done, total) {
  const p = $("#progress");
  p.max = total || 1; p.value = done || 0;
  $("#progress-text").textContent = (total ? done + " / " + total : "");
}

// ------------------------------------------------------------- file picker
function openPicker(type, onPick, rootName, startPath) {
  state.picker = { type, onPick, cwd: "" };
  $("#picker-title").textContent = type === "dir" ? T("Choose a folder") : T("Choose a bundle file");
  $("#picker-use-folder").style.display = type === "dir" ? "" : "none";
  $("#picker").classList.remove("hidden");
  renderRoots();
  const start = startPath || (rootName && state.roots[rootName]) || state.roots.home;
  navigate(start);
}
function closePicker() { $("#picker").classList.add("hidden"); state.picker = null; }

function renderRoots() {
  const box = $("#picker-roots");
  box.innerHTML = "";
  for (const [name, path] of Object.entries(state.roots)) {
    box.appendChild(el("button", { text: name, onclick: () => navigate(path) }));
  }
}

async function navigate(path) {
  let data;
  try {
    data = await (await fetch("/api/fs/list?path=" + encodeURIComponent(path || ""))).json();
  } catch (e) { alert(T("Cannot open: ") + e); return; }
  if (data.error) { alert(data.error); return; }
  state.picker.cwd = data.path;
  $("#picker-crumb").textContent = data.path;
  const ul = $("#picker-entries");
  ul.innerHTML = "";
  if (data.parent) {
    ul.appendChild(el("li", { onclick: () => navigate(data.parent) },
      [el("span", { class: "ic", text: "↩" }), document.createTextNode("..")]));
  }
  for (const e of data.entries) {
    if (e.is_dir) {
      ul.appendChild(el("li", { onclick: () => navigate(e.path) },
        [el("span", { class: "ic", text: "📁" }), document.createTextNode(e.name)]));
    } else if (state.picker.type === "path") {
      const li = el("li", { class: e.is_bundle ? "bundle" : "", onclick: () => { state.picker.onPick(e.path); closePicker(); } },
        [el("span", { class: "ic", text: e.is_bundle ? "🎁" : "📄" }),
         document.createTextNode(e.name),
         el("span", { class: "sz", text: fmtSize(e.size) })]);
      ul.appendChild(li);
    }
  }
}

function fmtSize(n) {
  if (n === undefined) return "";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

// ---------------------------------------------------------------- gallery
async function loadGallery() {
  const path = $("#gallery-path").value;
  const grid = $("#gallery-grid");
  grid.innerHTML = "<p class='hint'>" + T("Loading…") + "</p>";
  if (!path) { grid.innerHTML = "<p class='hint'>" + T("Pick a folder first.") + "</p>"; return; }
  let data;
  try { data = await (await fetch("/api/fs/list?path=" + encodeURIComponent(path))).json(); }
  catch (e) { grid.innerHTML = "<p class='hint'>" + T("Error") + ": " + e + "</p>"; return; }
  if (data.error) { grid.innerHTML = "<p class='hint'>" + data.error + "</p>"; return; }
  const bundles = data.entries.filter((e) => !e.is_dir && e.is_bundle);
  grid.innerHTML = "";
  if (!bundles.length) { grid.innerHTML = "<p class='hint'>" + T("No bundles here.") + "</p>"; return; }
  for (const b of bundles) {
    const img = el("img", { src: "/api/thumb?path=" + encodeURIComponent(b.path), alt: b.name, loading: "lazy" });
    img.addEventListener("error", () => {
      const ph = el("div", { class: "noimg", text: T("no preview") });
      img.replaceWith(ph);
    });
    // click a card to open it in the 3D preview tab
    const card = el("div", { class: "gcard", title: T("Open in 3D preview"),
      onclick: () => { $("#preview-path").value = b.path; switchTab("preview"); renderBundle(b.path); } },
      [img, el("div", { class: "cap", text: b.name })]);
    grid.appendChild(card);
  }
}

// ---------------------------------------------------------------- 3D preview
// Renders the selected bundle as an interactive glTF model (server builds a GLB
// from the mesh + baked rest pose + body texture). If WebGL is unavailable or the
// model can't be built/parsed, we fall back to the flat texture thumbnail so the
// tab always shows something useful (important on older Android WebViews).
const viewer = { renderer: null, scene: null, camera: null, controls: null, raf: 0, onResize: null };

function preview3DSupported() {
  if (typeof THREE === "undefined") return false;
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext &&
      (c.getContext("webgl") || c.getContext("experimental-webgl")));
  } catch (e) { return false; }
}

function previewFallbackThumb(path, msg) {
  disposeViewer();
  const stage = $("#preview-stage");
  stage.innerHTML = "";
  stage.appendChild(el("div", { class: "hint",
    text: msg || T("3D preview unavailable — showing the texture instead.") }));
  const img = el("img", { class: "preview-thumb",
    src: "/api/thumb?path=" + encodeURIComponent(path), alt: baseName(path) });
  img.addEventListener("error", () =>
    img.replaceWith(el("div", { class: "noimg", text: T("no preview") })));
  stage.appendChild(img);
}

function disposeViewer() {
  if (viewer.raf) cancelAnimationFrame(viewer.raf);
  viewer.raf = 0;
  if (viewer.onResize) { window.removeEventListener("resize", viewer.onResize); viewer.onResize = null; }
  if (viewer.controls) { viewer.controls.dispose(); viewer.controls = null; }
  if (viewer.renderer) {
    const dom = viewer.renderer.domElement;
    viewer.renderer.dispose();
    if (dom && dom.parentNode) dom.parentNode.removeChild(dom);
    viewer.renderer = null;
  }
  viewer.scene = viewer.camera = null;
}

async function renderBundle(path) {
  const stage = $("#preview-stage");
  if (!preview3DSupported()) { previewFallbackThumb(path); return; }
  disposeViewer();
  stage.innerHTML = "<p class='hint'>" + T("Loading 3D preview…") + "</p>";
  let buf;
  try {
    const resp = await fetch("/api/preview?path=" + encodeURIComponent(path));
    if (!resp.ok) { previewFallbackThumb(path); return; }
    buf = await resp.arrayBuffer();
  } catch (e) { previewFallbackThumb(path); return; }

  let loader;
  try { loader = new THREE.GLTFLoader(); }
  catch (e) { previewFallbackThumb(path); return; }
  loader.parse(buf, "",
    (gltf) => {
      try { setupScene(gltf.scene, path); }
      catch (e) { previewFallbackThumb(path, T("3D preview failed to render — showing the texture instead.")); }
    },
    () => previewFallbackThumb(path, T("3D preview failed to load — showing the texture instead.")));
}

function setupScene(root, path) {
  const stage = $("#preview-stage");
  stage.innerHTML = "";
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
  catch (e) { previewFallbackThumb(path); return; }
  const w = stage.clientWidth || 640, h = stage.clientHeight || 480;
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  renderer.setSize(w, h);
  stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 1000);
  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const key = new THREE.DirectionalLight(0xffffff, 0.8); key.position.set(1, 2, 3); scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.4); fill.position.set(-2, 1, -2); scene.add(fill);
  scene.add(root);

  // frame the model: aim the camera at its centre, back off by its size
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  camera.near = maxDim / 100; camera.far = maxDim * 100;
  camera.position.set(center.x, center.y, center.z + maxDim * 2.2);
  camera.updateProjectionMatrix();

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.target.copy(center);
  controls.enableDamping = true;
  controls.update();

  viewer.renderer = renderer; viewer.scene = scene; viewer.camera = camera; viewer.controls = controls;
  viewer.onResize = () => {
    const ww = stage.clientWidth || w, hh = stage.clientHeight || h;
    renderer.setSize(ww, hh); camera.aspect = ww / hh; camera.updateProjectionMatrix();
  };
  window.addEventListener("resize", viewer.onResize);

  const tick = () => {
    viewer.raf = requestAnimationFrame(tick);
    controls.update();
    renderer.render(scene, camera);
  };
  tick();
}

window.addEventListener("DOMContentLoaded", init);
