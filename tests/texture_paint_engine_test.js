/* Behavioral contracts for actual RGBA editing, selection and bounded undo. */
'use strict';
const assert = require('assert');
const { execFileSync } = require('child_process');
const api = require('../webtools/web/static/texture-paint-engine.js');
let cases = 0;
function test(name, fn) { fn(); cases += 1; }
function rgba(width, height, color) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let offset = 0; offset < data.length; offset += 4) data.set(color, offset);
  return { width, height, data };
}
function pixel(image, x, y = 0) { return Array.from(image.data.slice((y * image.width + x) * 4, (y * image.width + x + 1) * 4)); }
function bytes(image) { return Array.from(image.data); }
function mask(maskValue) { return maskValue === null ? null : Array.from(maskValue); }
function count(maskValue) { return Array.from(maskValue).filter(value => value > 0).length; }
function engine(image, options) { const result = api.create(options || {}); result.setImage(image); return result; }
const hardRed = { color: [255, 0, 0, 255], opacity: 1, softness: 0, size: 1 };

test('straight-alpha source over is not premultiplied twice', () => {
  const data = new Uint8ClampedArray([0, 0, 255, 128]);
  api.blendPixel(data, 0, [255, 0, 0, 128], 1, false);
  assert.deepStrictEqual(Array.from(data), [170, 0, 85, 192]);
});

test('painting on transparent pixels keeps the chosen straight RGB', () => {
  const data = new Uint8ClampedArray([13, 200, 30, 0]);
  api.blendPixel(data, 0, [220, 110, 40, 128], 1, false);
  assert.deepStrictEqual(Array.from(data), [220, 110, 40, 128]);
});

test('eraser lowers alpha without inventing a fringe RGB', () => {
  const data = new Uint8ClampedArray([17, 83, 190, 200]);
  api.blendPixel(data, 0, [0, 0, 0, 255], 0.25, true);
  assert.deepStrictEqual(Array.from(data), [17, 83, 190, 150]);
  api.blendPixel(data, 0, [255, 255, 255, 255], 1, true);
  assert.deepStrictEqual(Array.from(data), [17, 83, 190, 0]);
});

test('zero coverage leaves all original bytes exact', () => {
  const data = new Uint8ClampedArray([14, 53, 97, 123]);
  api.blendPixel(data, 0, [255, 0, 0, 255], 0, false);
  assert.deepStrictEqual(Array.from(data), [14, 53, 97, 123]);
});

test('source-over math matches an independent reference across mixed alpha values', () => {
  const source = [231, 57, 119];
  for (const alpha of [0, 17, 89, 128, 224, 255]) {
    for (const destinationAlpha of [0, 33, 127, 192, 255]) {
      for (const coverage of [0, 0.25, 0.6, 1]) {
        const before = [19, 133, 205, destinationAlpha];
        const actual = new Uint8ClampedArray(before);
        api.blendPixel(actual, 0, [...source, alpha], coverage, false);
        const sa = alpha / 255 * coverage, da = destinationAlpha / 255;
        const combined = sa + da * (1 - sa);
        const expected = before.slice();
        if (sa > 0) {
          for (let channel = 0; channel < 3; channel += 1) expected[channel] = Math.round((source[channel] * sa + before[channel] * da * (1 - sa)) / combined);
          expected[3] = Math.round(combined * 255);
        }
        for (let channel = 0; channel < 4; channel += 1) {
          assert(Math.abs(actual[channel] - expected[channel]) <= 1, `alpha ${alpha}/${destinationAlpha}, coverage ${coverage}, channel ${channel}`);
        }
      }
    }
  }
});

test('connected regions respect barriers and color tolerance', () => {
  const image = rgba(4, 3, [100, 100, 100, 255]);
  for (let y = 0; y < 3; y += 1) image.data.set([0, 0, 0, 255], (y * 4 + 2) * 4);
  image.data.set([108, 100, 100, 255], 5 * 4);
  const exact = api.connectedRegion(image, 0, 0, 0);
  assert.equal(count(exact), 5);
  assert.equal(exact[3], 0, 'same color beyond the barrier is excluded');
  const tolerant = api.connectedRegion(image, 0, 0, 10);
  assert.equal(count(tolerant), 6);
  assert.equal(tolerant[5], 255);
  assert.equal(tolerant[11], 0);
});

test('region connectivity is four-neighbor, not diagonal', () => {
  const image = rgba(2, 2, [0, 0, 0, 255]);
  image.data.set([255, 255, 255, 255], 0);
  image.data.set([255, 255, 255, 255], 12);
  assert.deepStrictEqual(mask(api.connectedRegion(image, 0, 0, 0)), [255, 0, 0, 0]);
});

test('a selection gate blocks flood traversal', () => {
  const image = rgba(4, 1, [50, 50, 50, 255]);
  const gate = new Uint8Array([255, 0, 255, 255]);
  assert.deepStrictEqual(mask(api.connectedRegion(image, 0, 0, 0, gate)), [255, 0, 0, 0]);
});

test('transparent region ignores irrelevant hidden RGB', () => {
  const image = { width: 3, height: 1, data: new Uint8ClampedArray([255, 0, 0, 0, 0, 255, 0, 0, 0, 255, 0, 255]) };
  assert.deepStrictEqual(mask(api.connectedRegion(image, 0, 0, 0)), [255, 255, 0]);
});

test('setting an image copies caller bytes and resets document history', () => {
  const input = rgba(2, 1, [11, 22, 33, 255]);
  const editor = engine(input);
  input.data[0] = 200;
  assert.equal(editor.getImage().data[0], 11);
  const copied = editor.getImage(); copied.data[1] = 200;
  assert.equal(editor.getImage().data[1], 22);
  editor.paintStroke([{ x: 0.5, y: 0.5 }], hardRed);
  assert.equal(editor.getState().undoCount, 1);
  editor.setImage(rgba(1, 1, [2, 3, 4, 5]));
  assert.equal(editor.getState().undoCount, 0);
  assert.equal(editor.getState().redoCount, 0);
  assert.equal(editor.getMask(), null);
  assert.deepStrictEqual(pixel(editor.getImage(), 0), [2, 3, 4, 5]);
});

test('masked brush modifies only allowed pixels and honors soft mask coverage', () => {
  const original = rgba(4, 1, [100, 100, 100, 255]);
  const editor = engine(original);
  editor.setMask(new Uint8Array([255, 0, 128, 0]), { history: false });
  editor.paintStroke([{ x: 0.5, y: 0.5 }, { x: 3.5, y: 0.5 }], { ...hardRed, color: [200, 0, 0, 255] });
  const result = editor.getImage();
  assert.deepStrictEqual(pixel(result, 0), [200, 0, 0, 255]);
  assert.deepStrictEqual(pixel(result, 1), pixel(original, 1));
  assert.deepStrictEqual(pixel(result, 3), pixel(original, 3));
  const half = pixel(result, 2);
  assert(half[0] > 100 && half[0] < 200 && half[1] > 0 && half[1] < 100);
  assert.equal(half[3], 255);
});

test('one continuous stroke creates one undo entry and one pixel change notification', () => {
  const changes = [];
  const original = rgba(8, 1, [0, 0, 0, 255]);
  const editor = engine(original, { onChange: change => changes.push(change) });
  changes.length = 0;
  editor.paintStroke([{ x: 0.5, y: 0.5 }, { x: 7.5, y: 0.5 }], hardRed);
  assert.equal(editor.getState().undoCount, 1);
  assert.equal(changes.length, 1);
  const painted = bytes(editor.getImage());
  for (let x = 0; x < 8; x += 1) assert.deepStrictEqual(pixel(editor.getImage(), x), [255, 0, 0, 255]);
  editor.undo();
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
  assert.equal(editor.getState().redoCount, 1);
  editor.redo();
  assert.deepStrictEqual(bytes(editor.getImage()), painted);
});

test('a fresh edit after undo drops the redo branch', () => {
  const editor = engine(rgba(3, 1, [0, 0, 0, 255]));
  editor.paintStroke([{ x: 0.5, y: 0.5 }], hardRed);
  editor.paintStroke([{ x: 1.5, y: 0.5 }], hardRed);
  editor.undo();
  assert.equal(editor.getState().redoCount, 1);
  editor.paintStroke([{ x: 2.5, y: 0.5 }], { ...hardRed, color: [0, 0, 255, 255] });
  assert.equal(editor.getState().redoCount, 0);
  assert.deepStrictEqual(pixel(editor.getImage(), 1), [0, 0, 0, 255]);
  assert.deepStrictEqual(pixel(editor.getImage(), 2), [0, 0, 255, 255]);
});

test('selection mask copies, undo and deselection are independent of pixels', () => {
  const original = rgba(4, 1, [10, 20, 30, 40]);
  const editor = engine(original);
  const input = new Uint8Array([255, 0, 128, 0]);
  editor.setMask(input); input[0] = 0;
  assert.deepStrictEqual(mask(editor.getMask()), [255, 0, 128, 0]);
  const copied = editor.getMask(); copied[1] = 255;
  assert.deepStrictEqual(mask(editor.getMask()), [255, 0, 128, 0]);
  editor.invertSelection();
  assert.deepStrictEqual(mask(editor.getMask()), [0, 255, 127, 255]);
  editor.undo();
  assert.deepStrictEqual(mask(editor.getMask()), [255, 0, 128, 0]);
  editor.clearSelection();
  assert.equal(editor.getMask(), null);
  editor.undo();
  assert.deepStrictEqual(mask(editor.getMask()), [255, 0, 128, 0]);
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
});

test('binary selection replace/add/subtract/intersect have explicit set behavior', () => {
  const editor = engine(rgba(4, 1, [1, 2, 3, 255]));
  editor.selectRegion(new Uint8Array([255, 0, 255, 0]), 'replace');
  editor.selectRegion(new Uint8Array([0, 255, 0, 0]), 'add');
  assert.deepStrictEqual(mask(editor.getMask()), [255, 255, 255, 0]);
  editor.selectRegion(new Uint8Array([255, 0, 0, 0]), 'subtract');
  assert.deepStrictEqual(mask(editor.getMask()), [0, 255, 255, 0]);
  editor.selectRegion(new Uint8Array([0, 0, 255, 255]), 'intersect');
  assert.deepStrictEqual(mask(editor.getMask()), [0, 0, 255, 0]);
  editor.selectNone();
  assert.deepStrictEqual(mask(editor.getMask()), [0, 0, 0, 0]);
  editor.selectAll();
  assert.deepStrictEqual(mask(editor.getMask()), [255, 255, 255, 255]);
});

test('bucket fill stays in the chosen region and remains undoable', () => {
  const original = rgba(4, 1, [100, 100, 100, 255]);
  original.data.set([0, 0, 0, 255], 2 * 4);
  const editor = engine(original);
  editor.setBrush({ color: [1, 2, 3, 255], opacity: 1, tolerance: 0, contiguous: true });
  editor.fillAt(0, 0);
  assert.deepStrictEqual(pixel(editor.getImage(), 0), [1, 2, 3, 255]);
  assert.deepStrictEqual(pixel(editor.getImage(), 1), [1, 2, 3, 255]);
  assert.deepStrictEqual(pixel(editor.getImage(), 2), pixel(original, 2));
  assert.deepStrictEqual(pixel(editor.getImage(), 3), pixel(original, 3));
  editor.undo(); assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
});

test('preview never changes persistent pixels or history', () => {
  const original = rgba(2, 2, [12, 34, 56, 78]);
  const editor = engine(original);
  editor.setPreviewImage(rgba(2, 2, [200, 180, 160, 140]));
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
  assert.equal(editor.getState().undoCount, 0);
  editor.setPreviewImage(null);
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
});

test('external same-size image changes are a single reversible operation', () => {
  const original = rgba(3, 2, [1, 2, 3, 4]);
  const editor = engine(original);
  const replacement = rgba(3, 2, [250, 220, 190, 160]);
  editor.applyImageData(replacement, { label: 'OKLCH adjustment' });
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(replacement));
  assert.equal(editor.getState().undoCount, 1);
  editor.undo(); assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
  editor.redo(); assert.deepStrictEqual(bytes(editor.getImage()), bytes(replacement));
});

test('invalid data dimensions fail without corrupting the document', () => {
  const original = rgba(2, 1, [1, 2, 3, 4]);
  const editor = engine(original);
  assert.throws(() => editor.applyImageData(rgba(1, 2, [0, 0, 0, 0])));
  assert.throws(() => editor.setMask(new Uint8Array(1)));
  assert.throws(() => editor.setPreviewImage(rgba(1, 1, [0, 0, 0, 0])));
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
  assert.equal(editor.getState().undoCount, 0);
});

test('invalid image replacement is rejected before replacing the open document', () => {
  const original = rgba(2, 1, [1, 2, 3, 4]);
  const editor = engine(original);
  for (const invalid of [
    { width: 0, height: 1, data: new Uint8ClampedArray(0) },
    { width: 1.5, height: 1, data: new Uint8ClampedArray(4) },
    { width: 2, height: 2, data: new Uint8ClampedArray(4) },
    { width: 1e9, height: 1e9, data: new Uint8ClampedArray(0) }
  ]) assert.throws(() => editor.setImage(invalid));
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
  assert.equal(editor.getState().undoCount, 0);
});

test('line and rectangle shape masks use continuous image coordinates', () => {
  const line = api.shapeMask(5, 3, 'line', [{ x: 0.5, y: 0.5 }, { x: 4.5, y: 0.5 }], { size: 1 });
  assert.equal(count(line), 5);
  assert.deepStrictEqual(Array.from(line.slice(0, 5)), [255, 255, 255, 255, 255]);
  const rectangle = api.shapeMask(5, 5, 'rectangle', [{ x: 1, y: 1 }, { x: 4, y: 4 }]);
  assert.equal(count(rectangle), 9);
  assert.equal(rectangle[0], 0); assert.equal(rectangle[12], 255); assert.equal(rectangle[24], 0);
  const reverse = api.shapeMask(5, 5, 'rectangle', [{ x: 4, y: 4 }, { x: 1, y: 1 }]);
  assert.deepStrictEqual(mask(reverse), mask(rectangle));
});

test('ellipse and closed lasso masks have explicit interior and exterior pixels', () => {
  const ellipse = api.shapeMask(5, 5, 'ellipse', [{ x: 0, y: 0 }, { x: 5, y: 5 }]);
  assert.equal(count(ellipse), 21);
  assert.equal(ellipse[0], 0); assert.equal(ellipse[12], 255); assert.equal(ellipse[10], 255);
  const lasso = api.shapeMask(5, 5, 'lasso', [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 0, y: 4 }]);
  assert.equal(lasso[0], 255); assert.equal(lasso[6], 255); assert.equal(lasso[18], 0);
  const outside = api.shapeMask(5, 5, 'rectangle', [{ x: -10, y: -10 }, { x: -2, y: -2 }]);
  assert.equal(count(outside), 0);
});

test('shape drawing clips to the selection and is a single undo operation', () => {
  const original = rgba(5, 5, [17, 83, 190, 255]);
  const editor = engine(original);
  const selected = new Uint8Array(25); selected[12] = 255;
  editor.setMask(selected, { history: false });
  editor.drawShape('rectangle', { x: 1, y: 1 }, { x: 4, y: 4 }, { ...hardRed, fill: true });
  for (let index = 0; index < 25; index += 1) {
    const actual = Array.from(editor.getImage().data.slice(index * 4, index * 4 + 4));
    assert.deepStrictEqual(actual, index === 12 ? [255, 0, 0, 255] : [17, 83, 190, 255]);
  }
  assert.equal(editor.getState().undoCount, 1);
  editor.undo(); assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
});

test('eraser tool operation ignores palette alpha and remains reversible', () => {
  const original = rgba(1, 1, [17, 83, 190, 200]);
  const editor = engine(original);
  editor.paintStroke([{ x: 0.5, y: 0.5 }], { ...hardRed, erase: true, color: [0, 0, 0, 0], opacity: 0.5 });
  assert.deepStrictEqual(pixel(editor.getImage(), 0), [17, 83, 190, 100]);
  editor.undo(); assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
});

test('picking and view coordinate conversion leave the texture untouched', () => {
  const original = rgba(2, 2, [12, 34, 56, 78]);
  original.data.set([91, 82, 73, 64], 12);
  const editor = engine(original);
  assert.deepStrictEqual(editor.sample(1.8, 1.3), [91, 82, 73, 64]);
  editor.setView({ zoom: 4, x: 10, y: -3 });
  const screen = editor.imageToView({ x: 2, y: 5 });
  assert.deepStrictEqual(screen, { x: 18, y: 17 });
  assert.deepStrictEqual(editor.viewToImage(screen), { x: 2, y: 5 });
  assert.equal(editor.getState().undoCount, 0);
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
});

test('an edit larger than the undo budget rolls back all touched tiles', () => {
  const original = rgba(64, 64, [10, 20, 30, 255]);
  const editor = engine(original, { maxHistoryBytes: 1024 });
  assert.throws(() => editor.paintStroke([{ x: 10.5, y: 10.5 }], hardRed));
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
  assert.equal(editor.getState().undoCount, 0);
  assert.equal(editor.getState().redoCount, 0);
  assert(editor.getState().historyBytes <= 1024);
});

test('pixel and selection changes travel together in one ordered undo timeline', () => {
  const original = rgba(2, 1, [0, 0, 0, 255]);
  const editor = engine(original);
  editor.setMask(new Uint8Array([255, 0]));
  editor.paintStroke([{ x: 0.5, y: 0.5 }], hardRed);
  editor.clearSelection();
  editor.paintStroke([{ x: 1.5, y: 0.5 }], { ...hardRed, color: [0, 0, 255, 255] });
  const final = bytes(editor.getImage());
  assert.equal(editor.getState().undoCount, 4);
  editor.undo();
  assert.equal(editor.getMask(), null);
  assert.deepStrictEqual(pixel(editor.getImage(), 1), [0, 0, 0, 255]);
  editor.undo();
  assert.deepStrictEqual(mask(editor.getMask()), [255, 0]);
  assert.deepStrictEqual(pixel(editor.getImage(), 0), [255, 0, 0, 255]);
  editor.undo();
  assert.deepStrictEqual(mask(editor.getMask()), [255, 0]);
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
  editor.undo();
  assert.equal(editor.getMask(), null);
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
  for (let step = 0; step < 4; step += 1) editor.redo();
  assert.equal(editor.getMask(), null);
  assert.deepStrictEqual(bytes(editor.getImage()), final);
});

test('soft brushes produce a gradual edge while preserving outside pixels', () => {
  const editor = engine(rgba(7, 1, [0, 0, 0, 255]));
  editor.paintStroke([{ x: 3.5, y: 0.5 }], { ...hardRed, size: 5, softness: 1 });
  const actual = editor.getImage();
  assert.equal(pixel(actual, 3)[0], 255);
  assert(pixel(actual, 2)[0] > pixel(actual, 1)[0] && pixel(actual, 1)[0] > 0);
  assert.deepStrictEqual(pixel(actual, 0), [0, 0, 0, 255]);
  assert.deepStrictEqual(pixel(actual, 6), [0, 0, 0, 255]);
});

test('zero opacity and an identical external image create no undo pollution', () => {
  const original = rgba(2, 1, [10, 20, 30, 40]);
  const editor = engine(original);
  editor.paintStroke([{ x: 0.5, y: 0.5 }], { ...hardRed, opacity: 0 });
  editor.applyImageData(original);
  editor.clearSelection();
  assert.equal(editor.getState().undoCount, 0);
  assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
});

test('history keeps its byte bound across undo and redo, with bounded entry eviction', () => {
  const editor = engine(rgba(3, 1, [0, 0, 0, 255]), { maxHistoryBytes: 1024, maxHistoryEntries: 2 });
  editor.paintStroke([{ x: 0.5, y: 0.5 }], hardRed);
  editor.paintStroke([{ x: 1.5, y: 0.5 }], { ...hardRed, color: [0, 255, 0, 255] });
  editor.paintStroke([{ x: 2.5, y: 0.5 }], { ...hardRed, color: [0, 0, 255, 255] });
  assert.equal(editor.getState().undoCount, 2);
  const retainedBytes = editor.getState().historyBytes;
  assert(retainedBytes > 0 && retainedBytes <= 1024);
  editor.undo(); assert.equal(editor.getState().historyBytes, retainedBytes);
  editor.undo(); assert.equal(editor.getState().historyBytes, retainedBytes);
  assert.equal(editor.getState().undoCount, 0);
  assert.deepStrictEqual(pixel(editor.getImage(), 0), [255, 0, 0, 255]);
  assert.deepStrictEqual(pixel(editor.getImage(), 1), [0, 0, 0, 255]);
  assert.deepStrictEqual(pixel(editor.getImage(), 2), [0, 0, 0, 255]);
  editor.undo(); assert.equal(editor.getState().undoCount, 0);
  editor.redo(); editor.redo();
  assert.deepStrictEqual(pixel(editor.getImage(), 1), [0, 255, 0, 255]);
  assert.deepStrictEqual(pixel(editor.getImage(), 2), [0, 0, 255, 255]);
  assert.equal(editor.getState().historyBytes, retainedBytes);
});

test('hiding selection affects only its overlay, preserving edit clipping and undo', () => {
  const original = rgba(2, 1, [10, 20, 30, 255]), editor = engine(original);
  editor.setMask(new Uint8Array([255, 0]), {history: false});
  assert.equal(editor.getState().selectionVisible, true);
  editor.setSelectionVisible(false);
  assert.equal(editor.getState().selectionVisible, false);
  assert.equal(editor.getState().undoCount, 0);
  assert.deepStrictEqual(mask(editor.getMask()), [255, 0]);
  editor.paintStroke([{x:0.5,y:0.5},{x:1.5,y:0.5}], hardRed);
  assert.deepStrictEqual(pixel(editor.getImage(), 0), [255,0,0,255]);
  assert.deepStrictEqual(pixel(editor.getImage(), 1), [10,20,30,255]);
  editor.undo(); assert.deepStrictEqual(bytes(editor.getImage()), bytes(original));
  assert.equal(editor.getState().selectionVisible, false);
  editor.setSelectionVisible(true);
  assert.equal(editor.getState().undoCount, 0);
});

test('scanline lasso matches an independent even-odd reference on a concave polygon', () => {
  const points = Array.from({length: 31}, (_, index) => {
    const angle = index * Math.PI * 2 / 31, radius = index % 2 ? 5 : 13;
    return {x: 16 + Math.cos(angle) * radius, y: 16 + Math.sin(angle) * radius};
  });
  const actual = api.shapeMask(32, 32, 'lasso', points);
  for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) {
    const px = x + 0.5, py = y + 0.5; let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      if ((points[i].y > py) !== (points[j].y > py) && px < (points[j].x - points[i].x) * (py - points[i].y) / (points[j].y - points[i].y) + points[i].x) inside = !inside;
    }
    assert.equal(actual[y * 32 + x], inside ? 255 : 0);
  }
});

test('very distant off-image pointer travel is clipped before generating brush dabs', () => {
  const script = `const assert=require('assert'), api=require(${JSON.stringify(require.resolve('../webtools/web/static/texture-paint-engine.js'))});
    const data=new Uint8ClampedArray(32*3*4);for(let i=3;i<data.length;i+=4)data[i]=255;
    const e=api.create();e.setImage({width:32,height:3,data});
    e.paintStroke([{x:-1e9,y:1.5},{x:1e9,y:1.5}],{size:1,opacity:1,softness:0,color:'#ff0000'});
    const result=e.getImage().data;for(let y=0;y<3;y++)for(let x=0;x<32;x++){const red=result[(y*32+x)*4];if(y===1)assert(red>=240);else assert.equal(red,0);}
    assert.equal(e.getState().undoCount,1);e.undo();assert.deepStrictEqual(e.getImage().data,data);`;
  execFileSync(process.execPath, ['-e', script], {timeout: 1500});
});

test('read-only interaction consumes modifying shortcuts and preserves history for programmatic restore', () => {
  const editor = engine(rgba(2, 1, [20, 40, 60, 255]));
  editor.paintStroke([{ x: .5, y: .5 }], hardRed);
  const edited = bytes(editor.getImage()), countBefore = editor.getState().undoCount;
  editor.setReadOnly(true);
  assert.equal(editor.getState().readOnly, true);
  for (const key of ['z', 'y', 'a']) {
    let prevented = false;
    assert(editor.handleShortcut({ key, ctrlKey: true, preventDefault() { prevented = true; } }));
    assert(prevented);
    assert.deepStrictEqual(bytes(editor.getImage()), edited);
    assert.equal(editor.getState().undoCount, countBefore);
    assert.equal(editor.getMask(), null);
  }
  editor.setView({ x: 12, y: 8, zoom: 2 });
  assert.deepStrictEqual(editor.getView(), { x: 12, y: 8, zoom: 2 });
  editor.setReadOnly(false);
  assert(editor.undo());
  assert.deepStrictEqual(bytes(editor.getImage()), [20, 40, 60, 255, 20, 40, 60, 255]);
});

test('full 4K image apply and reversible pixel history fit the 64 MiB limit', () => {
  const result = execFileSync(process.execPath, ['--expose-gc', '-e', `
    const assert = require('assert'), api = require(${JSON.stringify(require.resolve('../webtools/web/static/texture-paint-engine.js'))});
    const size = 4096, bytes = size * size * 4;
    const original = new Uint8ClampedArray(bytes).fill(37), changed = new Uint8ClampedArray(bytes).fill(213);
    const editor = api.create({maxHistoryBytes: 64 * 1024 * 1024});
    editor.setImage({width:size,height:size,data:original});editor.selectAll();
    assert(editor.applyImageData({width:size,height:size,data:changed}));
    const check = expected => assert.equal(Buffer.compare(Buffer.from(editor.getImage(false).data.buffer), Buffer.from(expected.buffer)),0);
    check(changed);assert.equal(editor.getState().historyBytes,bytes);assert.equal(editor.getState().undoCount,1);
    for(let repeat=0;repeat<3;repeat++){
      assert(editor.undo());check(original);assert.equal(editor.getState().historyBytes,bytes);
      assert(editor.redo());check(changed);assert.equal(editor.getState().historyBytes,bytes);
    }
    process.stdout.write('PASS');
  `], {timeout:20000,encoding:'utf8',maxBuffer:1024});
  assert.equal(result,'PASS');
});

test('compound selection movement retains one reversible pixel-and-mask operation under its bounded allowance', () => {
  const original = rgba(16, 16, [10, 20, 30, 255]);
  for (let p = 0; p < 256; p++) original.data[p * 4] = p % 16 * 13;
  const editor = engine(original, {maxHistoryBytes: 1024}); editor.selectAll();
  editor.startMoveSelection(); editor.moveFloating(8, 0); editor.commitFloating();
  assert(editor.getState().historyBytes > 1024 && editor.getState().historyBytes <= 2048);
  assert.equal(editor.getState().selectedPixels, 128);
  editor.undo(); assert.deepStrictEqual(bytes(editor.getImage()), bytes(original)); assert.equal(editor.getState().selectedPixels, 256);
  editor.redo(); assert.equal(editor.getState().selectedPixels, 128); assert.equal(pixel(editor.getImage(), 0)[3], 0);
});

test('structural merge retains only bounded original layer owners and restores them exactly', () => {
  const original = rgba(16, 16, [10, 20, 30, 255]), upper = rgba(16, 16, [210, 90, 70, 128]);
  const editor = engine(original, {maxHistoryBytes: 1024}); editor.addLayer({name: 'Upper', image: upper});
  const flattened = bytes(editor.getImage()); editor.mergeLayerDown();
  assert.deepStrictEqual(bytes(editor.getImage()), flattened); assert(editor.getState().historyBytes <= 2048);
  editor.undo(); const project = editor.getProject(); assert.equal(project.layers.length, 2);
  assert.deepStrictEqual(bytes(project.layers[0].image), bytes(original)); assert.deepStrictEqual(bytes(project.layers[1].image), bytes(upper));
  editor.redo(); assert.deepStrictEqual(bytes(editor.getImage()), flattened);
});

test('clipboard preserves irregular selection holes and hidden RGB at transparent selected pixels', () => {
  const source = engine({width:3,height:1,data:new Uint8ClampedArray([200,20,30,255,3,4,5,255,9,8,7,0])});
  source.setMask(new Uint8Array([255,0,255]));source.copySelection();
  const target = engine(rgba(3,1,[80,90,100,0]));target.selectNone();target.importClipboard(source.exportClipboard());target.pasteClipboard();target.moveFloating(0,0);target.commitFloating();
  assert.deepStrictEqual(bytes(target.getImage()),[200,20,30,255,80,90,100,0,9,8,7,0]);
  assert.deepStrictEqual(mask(target.getMask()),[255,0,255]);target.undo();assert.deepStrictEqual(bytes(target.getImage()),[80,90,100,0,80,90,100,0,80,90,100,0]);
});

test('idle and dirty multilayer composites reuse a flattened buffer and preserve untouched pixels', () => {
  const editor = engine(rgba(4,4,[20,40,60,128]));for(let i=0;i<7;i++)editor.addLayer({name:'Layer '+i});
  const flattened = editor.getImage(false);assert.strictEqual(editor.getDisplayImage(),flattened);
  editor.paintStroke([{x:1.5,y:1.5}],hardRed);assert.strictEqual(editor.getImage(false),flattened);
  assert.deepStrictEqual(pixel(editor.getImage(),0,0),[20,40,60,128]);assert.deepStrictEqual(pixel(editor.getImage(),1,1),[255,0,0,255]);
});

console.log(`PASS: ${cases} texture paint compositing, flood, masking, preview and reversible-edit contracts`);
