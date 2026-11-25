'use strict';
// Refusal sentences from the Python core reach the page in its language, with
// slot names, sizes and counts kept; the receiving-mesh hint follows the
// model's head flag, never the mesh label.
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm');
const window = {}, context = vm.createContext({ window, Set, Map });
const sourcePath = process.argv[2] || path.join(__dirname, '../webtools/web/static/viewer-transplants.js');
vm.runInContext(fs.readFileSync(sourcePath, 'utf8'), context);
const api = window.ViewerTransplants;

const noSpace = 'The head texture has no free area for the selected part outside the face, eyes, mouth, blush and existing head meshes. Choose Body as the receiving mesh, or select a smaller part.';
const island = 'Island 3 of 22 (93×129 px) found no free texels in _RimlightTex.';
const refusal = noSpace + ' ' + island;
assert.strictEqual(api.reasonText(refusal, 'en'), refusal, 'English stays as the core wrote it');
const ko = api.reasonText(refusal, 'ko');
assert(ko.startsWith('머리 텍스처에 얼굴·눈·입·홍조와 기존 머리 메시를 피해'), ko);
assert(ko.endsWith('UV 섬 22개 중 3번째(93×129 px)가 _RimlightTex에서 빈 텍셀을 찾지 못했습니다.'), ko);
assert(!/[A-Za-z]{4,}/.test(ko.replace(/_RimlightTex|Body/g, '')), 'no English words remain: ' + ko);
const ja = api.reasonText(refusal, 'ja');
assert(ja.endsWith('UVアイランド22個中3番目（93×129 px）は_RimlightTexで空きテクセルを見つけられませんでした。'), ja);

const map = "A texture of the selected part has finer pixels for its UV area than the matching head texture. The head's textures keep their size, because the face, eyes and mouth are drawn from them. Choose Body as the receiving mesh. _RimlightTex: the part uses 512×512 for a 1024×1024 main texture; the head uses 128×128 for 1024×1024.";
assert(api.reasonText(map, 'ko').endsWith('_RimlightTex: 이식할 부분은 1024×1024 메인 텍스처에 512×512를 쓰고, 머리는 1024×1024에 128×128를 씁니다.'),
  api.reasonText(map, 'ko'));
const cull = "ch0203_co0015_head: _CullMode is 0, while ch0212_co0001_body uses 2. One game material holds one culling setting, so the donor's and the receiving mesh's materials must match. Choose a receiving mesh whose material uses the same culling, such as Body or Hair.";
assert(api.reasonText(cull, 'ja').startsWith('ch0203_co0015_head：_CullModeは0ですが、ch0212_co0001_bodyは2です。'), api.reasonText(cull, 'ja'));
assert(!/receiving mesh|wearer/.test(api.reasonText(cull, 'ko')), api.reasonText(cull, 'ko'));

const option = flag => ({ getAttribute: name => (name === 'data-head-mesh' ? flag : null) });
assert.strictEqual(api.receivingMeshKind('', option('true')), 'body', 'the default Body entry');
assert.strictEqual(api.receivingMeshKind('12', option('false')), 'body', 'a mesh named Hair outside a merged head');
assert.strictEqual(api.receivingMeshKind('12', option('true')), 'head');
assert.strictEqual(api.receivingMeshKind('12', null), 'body');
console.log('PASS: refusal sentences and detail templates translate with values kept; hint follows the head flag');
