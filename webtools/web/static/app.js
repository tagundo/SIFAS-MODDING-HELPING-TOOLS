"use strict";

const state = {
  tools: [],
  roots: {},
  currentTool: null,
  currentMode: "single",
  es: null,
  picker: null, // { type: 'path'|'dir', onPick: fn, cwd: str }
};

const $ = (sel) => document.querySelector(sel);
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

  try {
    const data = await (await fetch("/api/tools")).json();
    state.tools = data.tools || [];
    state.roots = data.roots || {};
    renderToolList();
  } catch (e) {
    $("#tool-panel").innerHTML = "<p class='hint'>Failed to load tools: " + e + "</p>";
  }
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  $("#tab-" + name).classList.add("active");
}

// ------------------------------------------------------------------- tools
function renderToolList() {
  const list = $("#tool-list");
  list.innerHTML = "";
  for (const tool of state.tools) {
    const b = el("button", { onclick: () => selectTool(tool.id) },
      [el("span", { text: tool.label }), el("small", { text: tool.description || "" })]);
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
        text: m === "single" ? "Single file" : "Batch folder",
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
  form.appendChild(el("button", { class: "run-btn", type: "submit", text: "Run" }));
  panel.appendChild(form);
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
      const o = el("option", { value: opt, text: opt });
      if (opt === field.default) o.selected = true;
      sel.appendChild(o);
    }
    wrap.appendChild(sel);
  } else if (field.type === "path" || field.type === "dir") {
    const input = el("input", { type: "text", id, value: defaultPath(field) });
    input.dataset.name = field.name;
    input.dataset.ftype = field.type;
    const browse = el("button", {
      type: "button", text: "Browse",
      onclick: () => openPicker(field.type, (p) => { input.value = p; }, field.root, input.value),
    });
    wrap.appendChild(el("div", { class: "path-row" }, [input, browse]));
  } else {
    const input = el("input", {
      type: field.type === "number" ? "text" : "text", id,
      value: field.default !== undefined ? String(field.default) : "",
    });
    if (field.type === "number") input.setAttribute("inputmode", "decimal");
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

function collectParams() {
  const params = { mode: state.currentMode };
  document.querySelectorAll("#tool-form [data-name]").forEach((inp) => {
    const name = inp.dataset.name;
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
  if (missing.length) return alert("Please fill in: " + missing.join(", "));

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
  appendLog("[cancelling…]");
  try { await fetch("/api/jobs/" + state.jobId + "/cancel", { method: "POST" }); } catch {}
}

function openConsole(title) {
  $("#console").classList.remove("hidden");
  $("#console-title").textContent = title + " — running…";
  $("#log").textContent = "";
  $("#cancel-btn").disabled = false;
  setProgress(0, 1);
}
function finishConsole(status) {
  const label = status === "done" ? "done ✓" : status === "cancelled" ? "cancelled" : "error ✗";
  $("#console-title").textContent = (state.currentTool ? state.currentTool.label : "Job") + " — " + label;
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
  $("#picker-title").textContent = type === "dir" ? "Choose a folder" : "Choose a bundle file";
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
  } catch (e) { alert("Cannot open: " + e); return; }
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
  grid.innerHTML = "<p class='hint'>Loading…</p>";
  if (!path) { grid.innerHTML = "<p class='hint'>Pick a folder first.</p>"; return; }
  let data;
  try { data = await (await fetch("/api/fs/list?path=" + encodeURIComponent(path))).json(); }
  catch (e) { grid.innerHTML = "<p class='hint'>Error: " + e + "</p>"; return; }
  if (data.error) { grid.innerHTML = "<p class='hint'>" + data.error + "</p>"; return; }
  const bundles = data.entries.filter((e) => !e.is_dir && e.is_bundle);
  grid.innerHTML = "";
  if (!bundles.length) { grid.innerHTML = "<p class='hint'>No bundles here.</p>"; return; }
  for (const b of bundles) {
    const img = el("img", { src: "/api/thumb?path=" + encodeURIComponent(b.path), alt: b.name, loading: "lazy" });
    img.addEventListener("error", () => {
      const ph = el("div", { class: "noimg", text: "no preview" });
      img.replaceWith(ph);
    });
    grid.appendChild(el("div", { class: "gcard" }, [img, el("div", { class: "cap", text: b.name })]));
  }
}

window.addEventListener("DOMContentLoaded", init);
