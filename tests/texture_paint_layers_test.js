/* Independent public-API fixtures for layered pixels and floating selections.
 * Expected bytes below are deliberately tiny fixed examples, not a copy of the
 * production compositor. Canvas/clipboard permissions are not test shortcuts.
 */
"use strict";
const assert = require("node:assert/strict");
const { create } = require("../webtools/web/static/texture-paint-engine.js");
const cases = [];
function test(name, run) { run(); cases.push(name); }
function image(width, height, pixels) {
  const values = pixels.length === 4 ? Array.from({ length: width * height }, () => pixels).flat() : pixels.flat();
  assert.equal(values.length, width * height * 4);
  return { width, height, data: new Uint8ClampedArray(values) };
}
function bytes(value) { return Array.from(value.data); }
function pixel(value, x, y) { const offset = (y * value.width + x) * 4; return Array.from(value.data.subarray(offset, offset + 4)); }
function engine(value) { const instance = create(); instance.setImage(value); return instance; }
function active(instance) { return instance.getState().activeLayerId; }
function layers(instance) { return instance.getLayers().map(row => ({ id: row.id, name: row.name, visible: row.visible, opacity: row.opacity })); }
function region(instance, selected) { instance.setMask(new Uint8Array(selected)); }
function add(instance, name, pixels) { instance.addLayer({ name, ...(pixels ? { image: pixels } : {}) }); return active(instance); }

test("transparent upper layers preserve every original hidden and partial-alpha byte", () => {
  const original = image(3, 1, [[9, 8, 7, 0], [30, 160, 70, 128], [240, 90, 33, 255]]);
  const editor = engine(original), originalLayer = active(editor);
  const blank = add(editor, "Blank");
  assert.notEqual(blank, originalLayer);
  assert.deepEqual(bytes(editor.getImage()), bytes(original));
  assert.deepEqual(bytes(editor.getActiveImage()), new Array(12).fill(0));
  editor.setLayerOpacity(blank, .37);
  assert.deepEqual(bytes(editor.getImage()), bytes(original));
  editor.setLayerVisible(blank, false);
  assert.deepEqual(bytes(editor.getImage()), bytes(original));
  const clone = editor.getImage(); clone.data.fill(0);
  assert.deepEqual(bytes(editor.getImage()), bytes(original), "Public pixel copies must not mutate the document");
});

test("layer opacity and source-over use straight-alpha pixels with predictable native bytes", () => {
  const editor = engine(image(2, 1, [[20, 40, 60, 255], [20, 40, 60, 128]]));
  const top = add(editor, "Color", image(2, 1, [[220, 140, 80, 255], [220, 140, 80, 128]]));
  assert.deepEqual(pixel(editor.getImage(), 1, 0), [154, 107, 73, 192]);
  editor.setLayerOpacity(top, .5);
  assert.deepEqual(pixel(editor.getImage(), 0, 0), [120, 90, 70, 255]);
  assert.deepEqual(pixel(editor.getActiveImage(), 0, 0), [220, 140, 80, 255], "Opacity must not destructively rewrite layer pixels");
  editor.setLayerVisible(top, false);
  assert.deepEqual(bytes(editor.getImage()), [20, 40, 60, 255, 20, 40, 60, 128]);
});

test("painting, filling and erasing stay inside the selection on the active layer", () => {
  const original = image(4, 1, [10, 20, 30, 255]), editor = engine(original);
  add(editor, "Paint"); region(editor, [0, 255, 0, 0]);
  editor.paintStroke([{ x: 1.5, y: .5 }], { size: 1, softness: 0, opacity: 1, color: [200, 100, 50, 255] });
  assert.deepEqual(bytes(editor.getImage()), [10, 20, 30, 255, 200, 100, 50, 255, 10, 20, 30, 255, 10, 20, 30, 255]);
  assert.deepEqual(pixel(editor.getActiveImage(), 0, 0), [0, 0, 0, 0]);
  editor.setBrush({ color: [4, 180, 210, 255], opacity: 1, tolerance: 255 });
  editor.fillAt(0, 0);
  assert.deepEqual(pixel(editor.getImage(), 0, 0), [10, 20, 30, 255]);
  editor.fillAt(1, 0);
  assert.deepEqual(pixel(editor.getImage(), 1, 0), [4, 180, 210, 255]);
  editor.paintStroke([{ x: 1.5, y: .5 }], { size: 1, opacity: 1, softness: 0, erase: true });
  assert.deepEqual(bytes(editor.getImage()), bytes(original));
  editor.undo(); assert.deepEqual(pixel(editor.getImage(), 1, 0), [4, 180, 210, 255]);
  assert.deepEqual(pixel(editor.getActiveImage(), 2, 0), [0, 0, 0, 0]);
});

test("pixel undo targets its original layer after another layer becomes active", () => {
  const original = image(2, 1, [25, 35, 45, 255]), editor = engine(original), base = active(editor);
  const paint = add(editor, "Paint");
  editor.paintStroke([{ x: .5, y: .5 }], { size: 1, softness: 0, color: [201, 31, 99, 255] });
  editor.selectLayer(base); editor.undo();
  assert.deepEqual(bytes(editor.getImage()), bytes(original));
  editor.selectLayer(paint); assert.deepEqual(pixel(editor.getActiveImage(), 0, 0), [0, 0, 0, 0]);
  editor.redo(); assert.deepEqual(pixel(editor.getActiveImage(), 0, 0), [201, 31, 99, 255]);
  editor.selectLayer(base); assert.deepEqual(bytes(editor.getActiveImage()), bytes(original));
});

test("reorder, remove, duplicate and merge remain reversible without sharing layer buffers", () => {
  const editor = engine(image(2, 1, [[9, 8, 7, 0], [40, 80, 120, 128]]));
  const base = active(editor), upper = add(editor, "Upper", image(2, 1, [[6, 5, 4, 0], [200, 100, 50, 190]]));
  editor.setLayerOpacity(upper, .65);
  const before = editor.getImage(), structure = layers(editor);
  editor.mergeLayerDown(upper);
  assert.equal(editor.getLayers().length, 1); assert.deepEqual(bytes(editor.getImage()), bytes(before));
  editor.undo(); assert.deepEqual(layers(editor), structure); assert.deepEqual(bytes(editor.getImage()), bytes(before));
  editor.moveLayer(upper, 0); assert.deepEqual(editor.getLayers().map(row => row.id), [upper, base]);
  editor.undo(); assert.deepEqual(editor.getLayers().map(row => row.id), [base, upper]);
  editor.removeLayer(upper); assert.equal(editor.getLayers().length, 1);
  editor.undo(); assert.deepEqual(layers(editor), structure);
  editor.duplicateLayer(upper); const duplicate = active(editor);
  assert.notEqual(duplicate, upper);
  editor.paintStroke([{ x: 1.5, y: .5 }], { size: 1, softness: 0, color: [12, 233, 80, 255] });
  editor.selectLayer(upper); assert.deepEqual(pixel(editor.getActiveImage(), 1, 0), [200, 100, 50, 190]);
});

test("active-layer preview composites with other layers and never edits committed pixels", () => {
  const editor = engine(image(1, 1, [20, 40, 60, 255]));
  add(editor, "Upper", image(1, 1, [220, 140, 80, 255]));
  editor.setLayerOpacity(active(editor), .5);
  const committed = editor.getImage(), activeBefore = editor.getActiveImage();
  editor.setPreviewImage(image(1, 1, [100, 200, 240, 255]));
  assert.deepEqual(bytes(editor.getImage()), bytes(committed));
  assert.deepEqual(bytes(editor.getActiveImage()), bytes(activeBefore));
  assert.deepEqual(bytes(editor.getDisplayImage()), [60, 120, 150, 255]);
  editor.setPreviewImage(null); assert.deepEqual(bytes(editor.getDisplayImage()), bytes(committed));
  editor.setDisplayOverride(image(1, 1, [3, 2, 1, 128]));
  assert.deepEqual(bytes(editor.getDisplayImage()), [3, 2, 1, 128]);
  assert.deepEqual(bytes(editor.getImage()), bytes(committed));
  editor.setDisplayOverride(null);
});

test("flattened recipe replacement replaces the whole stack and undo restores all layers", () => {
  const editor = engine(image(2, 1, [20, 40, 60, 255]));
  add(editor, "Upper", image(2, 1, [220, 140, 80, 128]));
  editor.setLayerOpacity(active(editor), .5);
  const before = editor.getImage(), structure = layers(editor), replacement = image(2, 1, [[9, 8, 7, 0], [60, 70, 80, 123]]);
  editor.replaceImageData(replacement, { label: "Restore flattened recipe" });
  assert.equal(editor.getLayers().length, 1); assert.deepEqual(bytes(editor.getImage()), bytes(replacement));
  editor.undo(); assert.deepEqual(layers(editor), structure); assert.deepEqual(bytes(editor.getImage()), bytes(before));
  editor.redo(); assert.equal(editor.getLayers().length, 1); assert.deepEqual(bytes(editor.getImage()), bytes(replacement));
});

test("color application updates only the active layer and leaves the stack intact", () => {
  const editor = engine(image(1, 1, [20, 40, 60, 255])), base = active(editor);
  const upper = add(editor, "Upper", image(1, 1, [220, 140, 80, 255]));
  editor.setLayerOpacity(upper, .5);
  const before = editor.getImage(), structure = layers(editor);
  editor.applyImageData(image(1, 1, [100, 200, 240, 255]), { label: "OKLCH active layer" });
  assert.deepEqual(layers(editor), structure);
  assert.deepEqual(bytes(editor.getActiveImage()), [100, 200, 240, 255]);
  assert.deepEqual(bytes(editor.getImage()), [60, 120, 150, 255]);
  editor.selectLayer(base); assert.deepEqual(bytes(editor.getActiveImage()), [20, 40, 60, 255]);
  editor.undo(); assert.deepEqual(bytes(editor.getImage()), bytes(before));
});

test("project import is one undoable stack replacement and public snapshots own their pixels", () => {
  const source = engine(image(2, 1, [[9, 8, 7, 0], [60, 70, 80, 123]]));
  const upper = add(source, "Skin accent", image(2, 1, [180, 120, 90, 128]));
  source.setLayerOpacity(upper, .35); source.renameLayer(upper, "피부 · Skin");
  const snapshot = source.getProject(), target = engine(image(2, 1, [13, 24, 35, 255]));
  const before = target.getImage(), structure = layers(target);
  target.restoreProject(snapshot);
  assert.deepEqual(layers(target), layers(source)); assert.equal(active(target), active(source));
  assert.deepEqual(bytes(target.getImage()), bytes(source.getImage()));
  snapshot.layers[0].image.data.fill(0);
  assert.deepEqual(pixel(source.getProject().layers[0].image, 0, 0), [9, 8, 7, 0]);
  assert.deepEqual(pixel(target.getProject().layers[0].image, 0, 0), [9, 8, 7, 0]);
  target.undo(); assert.deepEqual(layers(target), structure); assert.deepEqual(bytes(target.getImage()), bytes(before));
  target.redo(); assert.deepEqual(bytes(target.getImage()), bytes(source.getImage()));
});

test("invalid project layers fail atomically instead of partly replacing the active stack", () => {
  const editor = engine(image(2, 1, [31, 42, 53, 164])); add(editor, "Upper");
  const before = editor.getImage(), structure = layers(editor), undo = editor.getState().undoCount;
  for (const mutate of [project => { project.activeLayer = "missing-layer"; },
    project => { project.layers[1].id = project.layers[0].id; },
    project => { project.layers[0].opacity = NaN; },
    project => { project.layers[0].image = image(1, 1, [1, 2, 3, 4]); }]) {
    const invalid = editor.getProject(); mutate(invalid);
    assert.throws(() => editor.restoreProject(invalid));
    assert.deepEqual(layers(editor), structure); assert.deepEqual(bytes(editor.getImage()), bytes(before));
    assert.equal(editor.getState().undoCount, undo);
  }
});

test("cut copies original partial alpha, clears only selected pixels and is reversible", () => {
  const original = image(2, 1, [[100, 20, 30, 128], [20, 100, 30, 255]]), editor = engine(original);
  region(editor, [255, 0]); editor.cutSelection();
  assert.deepEqual(bytes(editor.getImage()), [100, 20, 30, 0, 20, 100, 30, 255]);
  editor.undo(); assert.deepEqual(bytes(editor.getImage()), bytes(original));
  editor.redo(); assert.deepEqual(bytes(editor.getImage()), [100, 20, 30, 0, 20, 100, 30, 255]);
});

test("floating cut-move cancels exactly, zero-distance commit is a no-op and a move is one undo", () => {
  const original = image(2, 1, [[100, 20, 30, 128], [20, 100, 30, 255]]), editor = engine(original);
  region(editor, [255, 0]); const history = editor.getState().undoCount;
  editor.startMoveSelection(); editor.moveFloating(1, 0);
  assert.deepEqual(bytes(editor.getImage()), bytes(original), "Uncommitted movement must not enter model exports");
  assert.deepEqual(bytes(editor.getDisplayImage()), [100, 20, 30, 0, 60, 60, 30, 255]);
  editor.cancelFloating(); assert.deepEqual(bytes(editor.getImage()), bytes(original));
  assert.equal(editor.getState().undoCount, history);
  editor.startMoveSelection(); editor.commitFloating();
  assert.deepEqual(bytes(editor.getImage()), bytes(original)); assert.equal(editor.getState().undoCount, history);
  editor.startMoveSelection(); editor.moveFloating(1, 0); editor.commitFloating();
  assert.deepEqual(bytes(editor.getImage()), [100, 20, 30, 0, 60, 60, 30, 255]);
  assert.equal(editor.getState().undoCount, history + 1);
  editor.undo(); assert.deepEqual(bytes(editor.getImage()), bytes(original));
  editor.redo(); assert.deepEqual(bytes(editor.getImage()), [100, 20, 30, 0, 60, 60, 30, 255]);
});

test("portable internal clipboard pastes with destination clipping and one undo", () => {
  const source = engine(image(3, 1, [[9, 8, 7, 0], [200, 30, 40, 128], [20, 220, 80, 255]]));
  region(source, [0, 255, 255]); const beforeCopy = source.getState().undoCount;
  source.copySelection(); assert.equal(source.getState().undoCount, beforeCopy);
  const targetOriginal = image(3, 2, [33, 44, 55, 0]), target = engine(targetOriginal);
  target.importClipboard(source.exportClipboard()); target.pasteClipboard(); target.moveFloating(-1, 1);
  assert.deepEqual(bytes(target.getImage()), bytes(targetOriginal));
  assert.deepEqual(pixel(target.getDisplayImage(), 0, 1), [20, 220, 80, 255]);
  target.commitFloating();
  assert.deepEqual(pixel(target.getImage(), 0, 1), [20, 220, 80, 255]);
  assert.deepEqual(pixel(target.getImage(), 1, 1), [33, 44, 55, 0]);
  target.undo(); assert.deepEqual(bytes(target.getImage()), bytes(targetOriginal));
  target.redo(); assert.deepEqual(pixel(target.getImage(), 0, 1), [20, 220, 80, 255]);
});

test("moving a selection moves its mask and undo restores both mask and source pixels", () => {
  const original = image(3, 1, [[100, 20, 30, 128], [20, 100, 30, 255], [7, 8, 9, 0]]), editor = engine(original);
  region(editor, [255, 0, 0]); editor.startMoveSelection(); editor.moveFloating(2, 0); editor.commitFloating();
  assert.deepEqual(Array.from(editor.getMask()), [0, 0, 255]);
  assert.deepEqual(pixel(editor.getImage(), 2, 0), [100, 20, 30, 128]);
  editor.undo(); assert.deepEqual(Array.from(editor.getMask()), [255, 0, 0]);
  assert.deepEqual(bytes(editor.getImage()), bytes(original));
  editor.redo(); assert.deepEqual(Array.from(editor.getMask()), [0, 0, 255]);
  assert.deepEqual(pixel(editor.getImage(), 2, 0), [100, 20, 30, 128]);
});

test("duplicating a hidden translucent layer preserves metadata and separate pixel ownership", () => {
  const editor = engine(image(2, 1, [30, 40, 50, 255]));
  const source = add(editor, "Accent", image(2, 1, [190, 120, 70, 144]));
  editor.setLayerOpacity(source, .35); editor.setLayerVisible(source, false); editor.duplicateLayer(source);
  const duplicate = active(editor), row = editor.getLayers().find(layer => layer.id === duplicate);
  assert.notEqual(duplicate, source); assert.equal(row.visible, false); assert.equal(row.opacity, .35);
  editor.setLayerVisible(duplicate, true); editor.setLayerOpacity(duplicate, 1);
  editor.paintStroke([{ x: .5, y: .5 }], { size: 1, softness: 0, color: [10, 220, 230, 255] });
  editor.selectLayer(source); assert.deepEqual(pixel(editor.getActiveImage(), 0, 0), [190, 120, 70, 144]);
});

test("hidden and zero-opacity active layers reject destructive edits", () => {
  const editor = engine(image(2, 1, [30, 40, 50, 255]));
  const upper = add(editor, "Hidden", image(2, 1, [190, 120, 70, 144]));
  editor.setLayerVisible(upper, false); const before = editor.getActiveImage(), history = editor.getState().undoCount;
  assert.throws(() => editor.paintStroke([{ x: .5, y: .5 }]));
  assert.throws(() => editor.fillAt(0, 0));
  assert.throws(() => editor.applyImageData(image(2, 1, [1, 2, 3, 4])));
  assert.deepEqual(bytes(editor.getActiveImage()), bytes(before)); assert.equal(editor.getState().undoCount, history);
  editor.setLayerVisible(upper, true); editor.setLayerOpacity(upper, 0);
  assert.throws(() => editor.paintStroke([{ x: .5, y: .5 }], { erase: true }));
  assert.deepEqual(bytes(editor.getActiveImage()), bytes(before));
});

test("structural undo retains the proper image owners across add, paint and remove", () => {
  const original = image(2, 1, [11, 22, 33, 255]), editor = engine(original), base = active(editor);
  const upper = add(editor, "Paint");
  editor.paintStroke([{ x: .5, y: .5 }], { size: 1, softness: 0, color: [200, 100, 50, 255] });
  editor.removeLayer(base); assert.deepEqual(editor.getLayers().map(layer => layer.id), [upper]);
  editor.undo(); assert.deepEqual(editor.getLayers().map(layer => layer.id), [base, upper]);
  editor.undo(); assert.deepEqual(bytes(editor.getImage()), bytes(original));
  editor.undo(); assert.deepEqual(editor.getLayers().map(layer => layer.id), [base]);
  assert.deepEqual(bytes(editor.getImage()), bytes(original));
  editor.redo(); assert.deepEqual(editor.getLayers().map(layer => layer.id), [base, upper]);
  editor.redo(); assert.deepEqual(pixel(editor.getImage(), 0, 0), [200, 100, 50, 255]);
  editor.redo(); assert.deepEqual(editor.getLayers().map(layer => layer.id), [upper]);
  assert.deepEqual(pixel(editor.getImage(), 0, 0), [200, 100, 50, 255]);
});

test("layer count and aggregate image budgets reject additions before changing the stack", () => {
  const tiny = engine(image(1, 1, [11, 22, 33, 255]));
  for (let layer = 1; layer < 8; layer++) add(tiny, "Layer " + layer);
  const structure = layers(tiny), history = tiny.getState().undoCount;
  assert.throws(() => add(tiny, "Excess"));
  assert.deepEqual(layers(tiny), structure); assert.equal(tiny.getState().undoCount, history);
  // Exactly two 4096² layers fill the 32-megapixel/128 MiB image budget.
  const large = engine({ width: 4096, height: 4096, data: new Uint8ClampedArray(4096 * 4096 * 4) });
  add(large, "Second"); const before = layers(large), largeHistory = large.getState().undoCount;
  assert.equal(large.getState().layerBytes, 128 * 1024 * 1024);
  assert.throws(() => add(large, "Too much image memory"));
  assert.deepEqual(layers(large), before); assert.equal(large.getState().undoCount, largeHistory);
  large.destroy(); tiny.destroy();
});

process.stdout.write(JSON.stringify({ status: "PASS", cases: cases.length, names: cases }) + "\n");
