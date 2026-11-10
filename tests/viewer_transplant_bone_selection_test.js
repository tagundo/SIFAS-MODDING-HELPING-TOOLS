'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm');
const window = {}, context = vm.createContext({ window, Set, Map });
const sourcePath = process.argv[2] || path.join(__dirname, '../webtools/web/static/viewer-transplants.js');
vm.runInContext(fs.readFileSync(sourcePath, 'utf8'), context);
const api = window.ViewerTransplants, plain = value => JSON.parse(JSON.stringify(value));
const parts = [
  { value: 'Move', depth: 0, bones: ['Move', 'TailRoot', 'Tail1', 'Tail2', 'TailEnd', 'RightArm', 'RightHand'] },
  { value: 'TailRoot', parent: 'Move', depth: 1, bones: ['TailRoot', 'Tail1', 'Tail2', 'TailEnd'] },
  { value: 'Tail1', parent: 'TailRoot', depth: 2, bones: ['Tail1', 'Tail2', 'TailEnd'] },
  { value: 'Tail2', parent: 'Tail1', depth: 3, bones: ['Tail2', 'TailEnd'] },
  { value: 'TailEnd', parent: 'Tail2', depth: 4, bones: ['TailEnd'] },
  { value: 'RightArm', parent: 'Move', depth: 1, bones: ['RightArm', 'RightHand'] },
  { value: 'RightHand', parent: 'RightArm', depth: 2, bones: ['RightHand'] }
];
const selected = new Set();
api.setBoneSelection(parts, selected, 'TailRoot', true, true);
assert.deepStrictEqual([...selected], ['TailRoot', 'Tail1', 'Tail2', 'TailEnd'], 'a zero-weight parent selects its actual descendants');
assert.deepStrictEqual(plain(api.selectedBoneManifest(parts, selected)), { partRoots: ['TailRoot'], includeDescendants: true });
api.setBoneSelection(parts, selected, 'RightArm', true, true);
assert.deepStrictEqual(plain(api.selectedBoneManifest(parts, selected)), { partRoots: ['TailRoot', 'RightArm'], includeDescendants: true }, 'two disjoint roots remain one exact union');
api.setBoneSelection(parts, selected, 'Tail2', true, false);
assert.deepStrictEqual(plain(api.selectedBoneManifest(parts, selected)), { partRoots: ['RightArm', 'RightHand', 'Tail1', 'TailRoot'], includeDescendants: false }, 'removing children cannot silently re-include them via a parent');
api.setBoneSelection(parts, selected, 'Tail2', true, true);
assert.deepStrictEqual(plain(api.selectedBoneManifest(parts, selected)), { partRoots: ['TailRoot', 'RightArm'], includeDescendants: true }, 'restoring a subtree returns to compact roots without duplicate faces');
api.setBoneSelection(parts, selected, 'Move', true, false); assert.equal(selected.size, 0);
api.setBoneSelection(parts, selected, 'TailRoot', false, true);
assert.deepStrictEqual(plain(api.selectedBoneManifest(parts, selected)), { partRoots: ['TailRoot'], includeDescendants: false }, 'own-bone-only mode is explicit');
api.setBoneSelection(parts, selected, 'NotInDonor', true, true); assert.deepStrictEqual([...selected], ['TailRoot']);
console.log('PASS: actual subtree expansion, multi-root union, exact child exclusions and explicit own-bone selection');
