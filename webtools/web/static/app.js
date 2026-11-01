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
  formToolId: null,
  meshDraft: {},
  meshExpertOpen: false,
  meshActivePart: "head",
  jobToolId: null,
  jobLabel: "",
  savedModelPaths: [],
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
  if (window.ModelViewer) window.ModelViewer.updateLanguage();
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
  $("#console-view-model").addEventListener("click", () => openModelViewer(state.savedModelPaths.slice(0, 1)));
  $("#picker-cancel").addEventListener("click", closePicker);
  $("#picker-use-folder").addEventListener("click", () => {
    if (state.picker) { state.picker.onPick(state.picker.cwd); closePicker(); }
  });
  $("#gallery-browse").addEventListener("click", () =>
    openPicker("dir", (p) => { $("#gallery-path").value = p; }, "modded"));
  $("#gallery-load").addEventListener("click", loadGallery);

  state.lang = detectLang();
  await loadI18n();
  applyStaticI18n();
  buildLangSelect();
  await loadTools();
  if (window.ModelViewer) window.ModelViewer.mount({
    translate: T,
    pickFile: (onPick) => openPicker("path", onPick, "models"),
  });
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  $("#tab-" + name).classList.add("active");
  if (window.ModelViewer) window.ModelViewer.setVisible(name === "viewer");
}

function openModelViewer(paths) {
  switchTab("viewer");
  $("#console").classList.add("hidden");
  return window.ModelViewer ? window.ModelViewer.open(paths) : Promise.resolve();
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
  if (state.formToolId === "mesh_baker" && $("#tool-form")) {
    const values = collectParams();
    delete values.mode;
    state.meshDraft = { ...state.meshDraft, ...values };
    const previousExpert = $("#tool-form .expert-options");
    if (previousExpert) state.meshExpertOpen = previousExpert.open;
  }
  const tool = state.currentTool;
  state.formToolId = tool.id;
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
  if (tool.id === "mesh_baker") form.classList.add("mesh-form");
  const expert = el("details", { class: "expert-options" });
  expert.appendChild(el("summary", { text: T("Expert options — individual bones and save settings") }));
  let hasExpert = false;
  for (const field of tool.fields) {
    if (field.mode && field.mode !== state.currentMode) continue;
    if (field.expert) { expert.appendChild(renderField(field)); hasExpert = true; }
    else form.appendChild(renderField(field));
  }
  if (hasExpert) form.appendChild(expert);
  const run = el("button", { class: "run-btn", type: "submit", text: T(tool.id === "mesh_baker" ? "Save model" : "Run") });
  if (tool.id === "mesh_baker") {
    const preview = el("button", { type: "button", id: "mesh-view-input", class: "mesh-preview-btn",
      text: T("View input model"), onclick: () => {
        const path = meshReferencePath();
        if (path) openModelViewer([path]);
      } });
    preview.disabled = true;
    form.appendChild(el("div", { class: "mesh-save-bar" }, [preview, run]));
  } else form.appendChild(run);
  panel.appendChild(form);
  if (tool.id === "mesh_baker") {
    for (const input of form.querySelectorAll("[data-name]")) {
      const value = state.meshDraft[input.dataset.name];
      if (value === undefined) continue;
      if (input.dataset.ftype === "body_parts") input._restoreBodyParts(value);
      else if (input.dataset.ftype === "bone_targets") input._restoreTargets(value);
      else if (input.dataset.ftype === "checkbox") input.checked = !!value;
      else { input.value = value; input.dispatchEvent(new Event("restore")); }
    }
    expert.open = state.meshExpertOpen;
  }
  wireDynamicSelects(tool);
  wireBoneTargets(tool);
}

function meshReferencePath() {
  const ref = document.querySelector('#tool-form [data-name="reference_path"]');
  if (ref && ref.value.trim()) return ref.value.trim();
  for (const name of ["in_path", "in_paths"]) {
    const input = document.querySelector(`#tool-form [data-name="${name}"]`);
    if (input) return input.value.split("\n").find((p) => p.trim()) || "";
  }
  return "";
}

// Ordinary body-part controls follow the chosen input. The more expensive full
// bone list is only inspected when the expert section is opened.
function wireBoneTargets(tool) {
  const parts = document.querySelector('#tool-form [data-ftype="body_parts"]');
  const bones = document.querySelector('#tool-form [data-ftype="bone_targets"]');
  if (!parts && !bones) return;
  const expert = document.querySelector("#tool-form .expert-options");
  function refresh() {
    const preview = $("#mesh-view-input");
    if (preview) preview.disabled = !meshReferencePath();
    if (parts) parts._loadParts();
    if (bones && expert && expert.open) bones._loadBones();
  }
  for (const name of ["in_path", "in_paths", "reference_path"]) {
    const source = document.querySelector(`#tool-form [data-name="${name}"]`);
    if (source) source.addEventListener("change", refresh);
  }
  if (expert && bones) expert.addEventListener("toggle", () => {
    if (expert.open) bones._loadBones();
  });
  if (meshReferencePath()) refresh();
}

const BODY_PART_CONTROLS = [
  ["head", "Head size", "Changes the head and hair together."],
  ["torso", "Waist thickness", "Changes the waist and lower torso; keeps the upper chest and shoulders the same size."],
  ["upper_arms", "Upper arm thickness", "Changes both upper arms; keeps arm length and forearm thickness."],
  ["forearms", "Forearm thickness", "Changes both forearms; keeps arm length and hand size."],
  ["hands", "Hand size", "Changes both hands, including fingers."],
  ["thighs", "Thigh thickness", "Changes both thighs; keeps leg length and calf thickness."],
  ["calves", "Calf thickness", "Changes both lower legs; keeps leg length and foot size."],
  ["feet", "Foot size", "Changes both feet, including toes."],
];

function renderBodyParts(field) {
  const editor = el("div", { class: "body-editor" });
  editor.dataset.name = field.name;
  editor.dataset.ftype = "body_parts";
  const status = el("p", { class: "body-status", role: "status",
    text: T("Choose an input model above to enable the body controls.") });
  const controls = new Map();
  const selector = el("div", { class: "body-part-selector", role: "tablist", "aria-label": T("Choose a body part") });
  const grid = el("div", { class: "body-parts-grid" });
  function selectPart(name) {
    state.meshActivePart = name;
    for (const [part, item] of controls) {
      const active = part === name;
      item.card.hidden = !active;
      item.selector.classList.toggle("active", active);
      item.selector.setAttribute("aria-selected", String(active));
      item.selector.tabIndex = active ? 0 : -1;
    }
  }
  function revealPart(name) {
    selectPart(name);
    const card = controls.get(name).card;
    const header = document.querySelector("header");
    const save = document.querySelector(".mesh-save-bar");
    // Match the actual chrome after window/viewport changes, including short
    // landscape windows where a fixed 150px top margin hides the reset button.
    card.style.scrollMarginTop = ((header ? header.getBoundingClientRect().height : 0) + 12) + "px";
    card.style.scrollMarginBottom = ((save ? save.getBoundingClientRect().height : 0) + 12) + "px";
    card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  for (const [name, title, help] of BODY_PART_CONTROLS) {
    const badge = el("span", { class: "body-part-badge", text: "100%" });
    const partButton = el("button", { type: "button", class: "body-part-choice", role: "tab",
      id: "part-tab-" + name, "aria-controls": "part-card-" + name,
      onclick: () => revealPart(name) }, [el("span", { text: T(title) }), badge]);
    selector.appendChild(partButton);
    const card = el("fieldset", { class: "body-part" });
    card.dataset.part = name;
    card.id = "part-card-" + name;
    card.setAttribute("role", "tabpanel");
    card.setAttribute("aria-labelledby", partButton.id);
    card.disabled = true;
    card.appendChild(el("legend", { text: T(title) }));
    card.appendChild(el("p", { class: "help", text: T(help) }));
    const percent = el("input", { type: "number", min: "50", max: "150", step: "1", value: "100",
      required: "required", "aria-label": T(title) + " (%)" });
    const range = el("input", { type: "range", min: "50", max: "150", step: "1", value: "100",
      "aria-label": T(title) });
    const summary = el("span", { class: "body-part-change", text: T("Original size") });
    function setValue(value) {
      const number = Math.max(50, Math.min(150, Number(value) || 100));
      percent.value = range.value = String(number);
      summary.textContent = number === 100 ? T("Original size")
        : (number > 100 ? "+" : "") + (number - 100) + "%";
      card.classList.toggle("changed", number !== 100);
      partButton.classList.toggle("changed", number !== 100);
      badge.textContent = number + "%";
    }
    range.addEventListener("input", () => setValue(range.value));
    percent.addEventListener("change", () => setValue(percent.value));
    const minus = el("button", { type: "button", text: "−5%", "aria-label": T(title) + " −5%",
      onclick: () => setValue(Number(percent.value) - 5) });
    const plus = el("button", { type: "button", text: "+5%", "aria-label": T(title) + " +5%",
      onclick: () => setValue(Number(percent.value) + 5) });
    const reset = el("button", { type: "button", text: T("Reset"), onclick: () => setValue(100) });
    const value = el("label", { class: "body-percent" }, [percent, el("span", { text: "%" })]);
    card.appendChild(el("div", { class: "body-stepper" }, [minus, value, plus]));
    card.appendChild(range);
    card.appendChild(el("div", { class: "body-part-footer" }, [summary, reset]));
    const availability = el("div", { class: "help body-unavailable" });
    card.appendChild(availability);
    controls.set(name, { card, percent, setValue, availability, selector: partButton });
    grid.appendChild(card);
  }
  selectPart(controls.has(state.meshActivePart) ? state.meshActivePart : "head");
  selector.addEventListener("keydown", (ev) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(ev.key)) return;
    ev.preventDefault();
    const names = [...controls.keys()];
    const current = names.indexOf(state.meshActivePart);
    const next = names[(current + (ev.key === "ArrowLeft" || ev.key === "ArrowUp" ? -1 : 1) + names.length) % names.length];
    revealPart(next);
    controls.get(next).selector.focus({ preventScroll: true });
  });
  editor._collectBodyParts = () => Object.fromEntries([...controls].map(([name, item]) =>
    [name, Number(item.percent.value)]));
  editor._restoreBodyParts = (values) => {
    for (const [name, item] of controls) if (values[name] !== undefined) item.setValue(values[name]);
  };
  let generation = 0;
  let loadedPath = "";
  editor._loadParts = async () => {
    const reference = meshReferencePath();
    if (reference && reference === loadedPath) return;
    const gen = ++generation;
    for (const item of controls.values()) item.card.disabled = true;
    if (!reference) {
      loadedPath = "";
      status.textContent = T("Choose an input model above to enable the body controls.");
      return;
    }
    status.textContent = T("Checking the model's body parts…");
    try {
      const url = "/api/options/mesh_baker/body_parts?reference_path=" + encodeURIComponent(reference);
      const data = await (await fetch(url)).json();
      if (gen !== generation || !editor.isConnected) return;
      if (data.error) throw new Error(data.error);
      const options = new Map((data.options || []).map((item) => [item.value, item]));
      for (const [name, item] of controls) {
        const found = options.get(name);
        item.card.disabled = !found || !found.available;
        item.selector.classList.toggle("unavailable", item.card.disabled);
        item.availability.textContent = item.card.disabled ? T("Not available for this model.") : "";
        if (item.card.disabled) item.setValue(100);
      }
      loadedPath = reference;
      status.textContent = T("Ready. Adjust a slider, then press Save model.");
    } catch (err) {
      loadedPath = "";
      status.textContent = T("Could not read this model. Choose a different input file.") + " " + err.message;
    }
  };
  const reload = el("button", { type: "button", text: T("Check model again"), onclick: () => {
    loadedPath = ""; editor._loadParts();
  } });
  const resetAll = el("button", { type: "button", text: T("Reset all body parts"), onclick: () => {
    for (const item of controls.values()) item.setValue(100);
  } });
  editor.appendChild(status);
  editor.appendChild(selector);
  editor.appendChild(el("div", { class: "body-toolbar" }, [resetAll, reload]));
  editor.appendChild(grid);
  editor.appendChild(el("p", { class: "help", text: T("Clothing attached to a body part can change with it. Save a new model, then choose View saved model to check the result in 3D.") }));
  return editor;
}

function renderBoneTargets(field) {
  const editor = el("div", { class: "bone-editor" });
  editor.dataset.name = field.name;
  editor.dataset.ftype = "bone_targets";
  const listId = "bones_" + field.name;
  const options = el("datalist", { id: listId });
  const bone = el("input", { type: "text", list: listId,
    placeholder: T("Select or type a bone"), "aria-label": T("Bone") });
  const status = el("div", { class: "help", role: "status", text: T("Load a bundle to see its bones, or type a bone name.") });
  const rows = el("div", { class: "bone-targets" });
  editor._collectTargets = () => [...rows.children].map((row) => row._target());
  let generation = 0;
  editor._loadBones = async () => {
    const gen = ++generation;
    const reference = meshReferencePath();
    options.innerHTML = "";
    if (!reference) {
      status.textContent = T("Load a bundle to see its bones, or type a bone name.");
      return;
    }
    status.textContent = T("loading…");
    try {
      const url = "/api/options/mesh_baker/" + encodeURIComponent(field.name) +
        "?reference_path=" + encodeURIComponent(reference);
      const data = await (await fetch(url)).json();
      if (gen !== generation || !editor.isConnected) return;
      for (const item of data.options || []) {
        options.appendChild(el("option", { value: item.value, label: item.label }));
      }
      status.textContent = data.error || ((data.options || []).length
        ? T("Bones loaded. Select or type a name below.") : T("No skinned bones found in this bundle."));
    } catch (err) {
      if (gen === generation && editor.isConnected) status.textContent = String(err);
    }
  };
  function addTarget(values = null) {
    const restoring = values && typeof values.bone === "string";
    const name = restoring ? values.bone : bone.value.trim();
    if (!name) { bone.focus(); return; }
    const existing = [...rows.children].find((r) => r._target().bone === name);
    if (existing) { existing.querySelector("input").focus(); return; }
    const row = el("fieldset", { class: "bone-target" });
    const nameInput = el("input", { type: "text", value: name, list: listId,
      required: "required", "aria-label": T("Bone") });
    const remove = el("button", { type: "button", text: T("Remove"), onclick: () => row.remove() });
    row.appendChild(el("div", { class: "path-row" }, [nameInput, remove]));
    const vectors = {};
    for (const [key, title, initial] of [["scale", "Scale", 1], ["rotate", "Rotation (degrees)", 0], ["translate", "Movement", 0]]) {
      const group = el("div", { class: "bone-vector" });
      group.appendChild(el("span", { text: T(title) }));
      const inputs = [];
      const axes = el("div", { class: "vec3-row" });
      for (const axis of ["X", "Y", "Z"]) {
        const restoredValue = restoring && Array.isArray(values[key]) ? values[key][inputs.length] : initial;
        const input = el("input", { type: "number", step: "any", value: String(restoredValue),
          required: "required", "aria-label": T(title) + " " + axis });
        if (key === "scale") input.min = "0.000000001";
        inputs.push(input);
        axes.appendChild(el("label", {}, [el("span", { text: axis }), input]));
      }
      vectors[key] = inputs;
      group.appendChild(axes);
      row.appendChild(group);
    }
    const comp = el("input", { type: "checkbox" });
    comp.checked = restoring ? !!values.compensate
      : name.startsWith("Spine") || ["LeftUpLeg", "RightUpLeg"].includes(name);
    row.appendChild(el("label", { class: "bone-comp" }, [comp, T("Compensate child scale")]));
    const reset = el("button", { type: "button", text: T("Reset transform"), onclick: () => {
      for (const key of Object.keys(vectors)) vectors[key].forEach((inp) => { inp.value = key === "scale" ? "1" : "0"; });
    } });
    row.appendChild(reset);
    row._target = () => ({ bone: nameInput.value.trim(),
      scale: vectors.scale.map((inp) => Number(inp.value)),
      rotate: vectors.rotate.map((inp) => Number(inp.value)),
      translate: vectors.translate.map((inp) => Number(inp.value)), compensate: comp.checked });
    rows.appendChild(row);
    bone.value = "";
    if (!restoring) nameInput.focus();
  }
  editor._restoreTargets = (targets) => {
    rows.innerHTML = "";
    for (const target of targets || []) addTarget(target);
  };
  const load = el("button", { type: "button", text: T("Load bones"), onclick: () => editor._loadBones() });
  const add = el("button", { type: "button", text: T("Add transform"), onclick: addTarget });
  bone.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); addTarget(); }
  });
  editor.appendChild(el("div", { class: "path-row bone-actions" }, [load]));
  editor.appendChild(status);
  editor.appendChild(el("div", { class: "path-row bone-actions" }, [bone, add]));
  editor.appendChild(options);
  editor.appendChild(rows);
  return editor;
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

  if (field.type === "body_parts") {
    if (field.help) wrap.appendChild(el("div", { class: "help", text: field.help }));
    wrap.appendChild(renderBodyParts(field));
    return wrap;
  } else if (field.type === "bone_targets") {
    wrap.appendChild(renderBoneTargets(field));
  } else if (field.type === "select") {
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
      }, field.root, field.type === "path" && input.value
        ? input.value.replace(/\/[^/]*$/, "") : input.value),
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
          onclick: () => {
            hidden.value = items().filter((q) => q !== p).join("\n"); rerender();
            hidden.dispatchEvent(new Event("change", { bubbles: true }));
          },
        });
        listEl.appendChild(el("li", {}, [el("span", { text: baseName(p) }), rm]));
      }
    };
    hidden.addEventListener("restore", rerender);
    const add = el("button", {
      type: "button", text: T("Add file"),
      onclick: () => openPicker("path", (p) => {
        const cur = items();
        if (!cur.includes(p)) {
          cur.push(p); hidden.value = cur.join("\n"); rerender();
          hidden.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }, field.root, items().length ? items()[items().length - 1].replace(/\/[^/]*$/, "") : ""),
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
    if (inp.dataset.ftype === "body_parts") params[name] = inp._collectBodyParts();
    else if (inp.dataset.ftype === "bone_targets") params[name] = inp._collectTargets();
    else if (inp.dataset.ftype === "checkbox") params[name] = inp.checked;
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
    if (f.required && !String(params[f.name] == null ? "" : params[f.name]).trim()) missing.push(f.label);
  }
  if (missing.length) return alert(T("Please fill in: ") + missing.join(", "));
  if (tool.id === "mesh_baker" && !Object.values(params.body_parts || {}).some((p) => Number(p) !== 100)
      && !(params.targets || []).length && !params.thigh) {
    return alert(T("Choose a body part and move its slider away from 100%, then press Save model."));
  }

  state.jobToolId = tool.id;
  state.jobLabel = tool.label;
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
      if (state.jobToolId === "mesh_baker" && msg.status === "done" && Array.isArray(msg.output_paths)) {
        state.savedModelPaths = msg.output_paths.filter((p) => typeof p === "string" && p);
        $("#console-view-model").hidden = !state.savedModelPaths.length;
      }
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
  state.savedModelPaths = [];
  $("#console-view-model").hidden = true;
  setProgress(0, 1);
}
function finishConsole(status) {
  const label = status === "done" ? T("done ✓") : status === "cancelled" ? T("cancelled") : T("error ✗");
  $("#console-title").textContent = (state.jobLabel || T("Job")) + " — " + label;
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
    const view = el("button", { type: "button", class: "gallery-view-model", text: T("View in 3D"),
      onclick: () => openModelViewer([b.path]) });
    grid.appendChild(el("div", { class: "gcard" }, [img, el("div", { class: "cap", text: b.name }), view]));
  }
}

window.addEventListener("DOMContentLoaded", init);
