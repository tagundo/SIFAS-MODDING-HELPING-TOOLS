/* MV Studio lists the 3D preview's runtime notes (MVStudioScene onWarning, e.g. a
   depth-of-field clip whose focus target the preview cannot find) with the
   project's import notes: once per message, shown in the warnings panel, never
   saved into the project, and cleared when the next project loads. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div', id = '') {
    this.tagName = tag.toUpperCase(); this.id = id; this.children = []; this.options = []; this.dataset = {};
    this.attributes = {}; this.listeners = {}; this.hidden = false; this.disabled = false; this.checked = false;
    this.textContent = ''; this.value = ''; this.valueAsNumber = NaN; this.open = false;
    this.clientWidth = 640; this.clientHeight = 120; this.scrollLeft = 0; this.scrollWidth = 640;
    this.parentElement = null;
    this.style = { values: {}, setProperty(key, value) { this.values[key] = value; },
      removeProperty(key) { delete this.values[key]; }, getPropertyValue(key) { return this.values[key] || ''; } };
    const classes = new Set();
    this.classList = { toggle: (name, force) => ((force ?? !classes.has(name)) ? classes.add(name) : classes.delete(name)),
      add: (...names) => names.forEach(name => classes.add(name)), remove: (...names) => names.forEach(name => classes.delete(name)),
      contains: (name) => classes.has(name) };
  }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key] ?? null; }
  hasAttribute(key) { return key in this.attributes; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  removeEventListener() {}
  append(...nodes) { for (const node of nodes) this.appendChild(node); }
  appendChild(node) {
    if (node instanceof Element) node.parentElement = this;
    if (this.tagName === 'SELECT' && node instanceof Element) this.options.push(node);
    this.children.push(node);
    return node;
  }
  replaceChildren(...nodes) { this.children = []; this.options = []; this.append(...nodes); }
  remove() {}
  querySelector() { return new Element(); }
  querySelectorAll() { return []; }
  closest() { return null; }
  getBoundingClientRect() { return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight }; }
  focus() {} showModal() { this.open = true; } close() { this.open = false; } load() {} pause() {}
  play() { return Promise.resolve(); }
  setPointerCapture() {} releasePointerCapture() {}
}

const elements = new Map();
const document = {
  hidden: false,
  getElementById(id) {
    if (!elements.has(id)) {
      const element = new Element(id === 'mv-seek' ? 'input' : 'div', id);
      element.parentElement = new Element();
      elements.set(id, element);
    }
    return elements.get(id);
  },
  createElement: (tag) => new Element(tag),
  addEventListener() {},
};
const text = (element) => element.children.map(child => child.textContent);

const scenes = [];
// resize() draws in the real scene; `drawing` marks a draw in progress, so a
// resize while it is set is a nested draw.
class FakeScene {
  constructor(options) { this.options = options; this.loaded = []; this.resizes = 0; this.drawing = false; this.nested = 0; }
  resize() { this.resizes++; if (this.drawing) this.nested++; }
  // The scene reports a note from inside its draw (MVStudioDofFocus.sample in renderView).
  warnWhileDrawing(message) {
    this.drawing = true;
    try { this.options.onWarning(message); } finally { this.drawing = false; }
  }
  setVisible() {} setPlaying() {} dispose() {} setCamera() {} frameAll() {} setScreenFade() {}
  seek() {} playbackFrame() {}
  load(project) { this.loaded.push(project); return Promise.resolve(); }
}

let opened = 0;
const projectFor = (index) => ({ version: 1, name: `MV ${index}`, duration: 10, tracks: [], performers: [], assets: [],
  warnings: index === 1 ? ['Imported timeline note.'] : [] });
const window = {
  document, performance: { now: () => 0 }, Option: class extends Element {
    constructor(label, value) { super('option'); this.textContent = label; this.value = value; }
  },
  localStorage: { getItem: () => null, setItem() {} },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  requestAnimationFrame: () => 1, cancelAnimationFrame() {}, addEventListener() {},
  getComputedStyle: () => ({ rowGap: '0', getPropertyValue: () => '0' }),
  ElichikaPlatform: { requestJSON: async () => ({ project: projectFor(++opened) }) },
  MVStudioScene: { create: (_mount, options) => { const scene = new FakeScene(options); scenes.push(scene); return scene; } },
};
window.window = window;
const context = vm.createContext({ ...window, window, console, setTimeout, clearTimeout, AbortController, URL,
  encodeURIComponent, JSON, Math, Number, Object, Array, Promise, Set, Map, String });
vm.runInContext(fs.readFileSync(require.resolve('../webtools/web/static/mv-studio.js'), 'utf8'), context);

(async () => {
  const studio = context.window.MVStudio || context.MVStudio;
  const settings = { translate: (label) => label, language: () => 'en', pickFile: (callback) => callback('/mods/project.json') };
  studio.mount(settings);
  studio.setVisible(true);
  const settle = () => new Promise(resolve => setTimeout(resolve, 0));
  studio.open();
  await settle(); await settle();
  assert.equal(scenes.length, 1, 'the studio creates its scene with the project');
  const scene = scenes[0];
  assert.equal(typeof scene.options.onWarning, 'function', 'the scene receives a warning sink');
  const list = document.getElementById('mv-warning-list'), panel = document.getElementById('mv-warnings');
  assert.deepEqual(text(list), ['Imported timeline note.']);

  const note = 'A depth-of-field clip targets member 2, which this MV does not have; ' +
    "the game keeps the previous frame's depth of field, and so does this preview.";
  const microtask = () => Promise.resolve();
  scene.warnWhileDrawing(note);
  scene.warnWhileDrawing(note);
  await microtask();
  assert.deepEqual(text(list), ['Imported timeline note.', note], 'a preview note is listed once after the import notes');
  assert.deepEqual(studio.getState().project.warnings, ['Imported timeline note.'], 'preview notes are not saved into the project');

  // The next project has no import notes; its preview note alone opens the panel.
  studio.open();
  await settle(); await settle();
  assert.equal(scene.loaded.length, 2);
  assert.deepEqual(text(list), [], 'loading another project clears the previous preview notes');
  assert.equal(panel.hidden, true, 'no notes: the warnings panel stays closed');
  const resizes = scene.resizes;
  scene.warnWhileDrawing(note);
  assert.equal(scene.nested, 0, 'opening the panel for a note does not resize (draw) inside the draw that reported it');
  assert.equal(scene.resizes, resizes, 'nothing resizes before the reporting draw returns');
  assert.equal(panel.hidden, true, 'the panel opens after the reporting draw');
  await microtask();
  assert.deepEqual(text(list), [note]);
  assert.equal(panel.hidden, false, 'a preview note shows the warnings panel');
  assert(scene.resizes > resizes, 'the scene is resized for the opened panel once the draw has returned');
  assert.equal(scene.nested, 0);
  // Several notes in one draw update the list together.
  const second = 'A depth-of-field clip targets body part 5, which BodyPartManager never holds; ' +
    "the game keeps the previous frame's depth of field, and so does this preview.";
  const third = 'A depth-of-field clip picks a member by cameraAutoDistanceMode 1, but this MV has no performers; ' +
    "this preview keeps the previous frame's depth of field.";
  const before = scene.resizes;
  scene.drawing = true;
  scene.options.onWarning(second);
  scene.options.onWarning(third);
  scene.drawing = false;
  assert.deepEqual(text(list), [note], 'the list waits for the reporting draw to return');
  await microtask();
  assert.deepEqual(text(list), [note, second, third]);
  assert.equal(scene.resizes, before, 'an open panel is not laid out again');
  assert.equal(scene.nested, 0);
  console.log('MV Studio preview warnings: listed once with the import notes, panel shown after the reporting draw (no nested draw), not saved, cleared on the next project.');
})().catch((error) => { console.error(error); process.exitCode = 1; });
