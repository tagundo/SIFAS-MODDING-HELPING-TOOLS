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

const cull = "ch0203_co0015_head: _CullMode is 0, while ch0212_co0001_body uses 2. One game material holds one culling setting, so the donor's and the receiving mesh's materials must match. Choose a receiving mesh whose material uses the same culling, such as Body or Hair.";
const map = "A texture of the selected part has finer pixels for its UV area than the matching head texture. The head's textures keep their size, because the face, eyes and mouth are drawn from them. Choose Body as the receiving mesh. _RimlightTex: the part uses 512×512 for a 1024×1024 main texture; the head uses 128×128 for 1024×1024.";
assert(api.reasonText(map, 'ko').endsWith('_RimlightTex — 이식할 부분: 512×512 (메인 텍스처 1024×1024 기준), 머리 텍스처: 128×128 (메인 텍스처 1024×1024 기준).'),
  api.reasonText(map, 'ko'));
assert(api.reasonText(cull, 'ko').startsWith('ch0203_co0015_head의 _CullMode: 0, ch0212_co0001_body의 _CullMode: 2.'), api.reasonText(cull, 'ko'));
const streamed = 'A head-texture mesh stores its vertices outside the bundle; reopen the original costume and face.';
assert.strictEqual(api.reasonText(streamed, 'ko'), '머리 텍스처를 쓰는 메시의 정점 데이터가 번들 밖에 저장되어 있습니다. 원래 의상과 얼굴을 다시 여세요.');
assert(!/[A-Za-z]{4,}/.test(api.reasonText(streamed, 'ja')), api.reasonText(streamed, 'ja'));
assert(api.reasonText(cull, 'ja').startsWith('ch0203_co0015_head：_CullModeは0ですが、ch0212_co0001_bodyは2です。'), api.reasonText(cull, 'ja'));
assert(!/receiving mesh|wearer/.test(api.reasonText(cull, 'ko')), api.reasonText(cull, 'ko'));

// What the graft does with a culled part on a two-sided receiver, in the page language.
const own = '[game] Hat (_CullMode 2) keeps its culling: it becomes its own submesh drawn by Body_culled, a copy of Body (_CullMode 0) with _CullMode 2.';
assert.strictEqual(api.reasonText(own, 'ko'), '[game] Hat(_CullMode 2) — 컬링 유지: 별도 서브메시로 나뉘어 Body(_CullMode 0)의 복사본인 Body_culled(_CullMode 2) 머티리얼로 그려집니다.');
assert.strictEqual(api.reasonText(own, 'ja'), '[game] Hat（_CullMode 2）はカリングを保ちます。別のサブメッシュに分かれ、Body（_CullMode 0）を複製して_CullMode 2にしたBody_culledで描画されます。');
const backFaces = '[warn] Hat (_CullMode 2) is drawn from both sides like Body (_CullMode 0); its back faces can show.';
assert.strictEqual(api.reasonText(backFaces, 'ko'), '[warn] Hat(_CullMode 2)는 Body(_CullMode 0)처럼 앞뒷면 모두 그려지므로 뒷면이 보일 수 있습니다.');
assert.strictEqual(api.reasonText(own, 'en'), own);

const option = flag => ({ getAttribute: name => (name === 'data-head-mesh' ? flag : null) });
assert.strictEqual(api.receivingMeshKind('', option('true')), 'body', 'the default Body entry');
assert.strictEqual(api.receivingMeshKind('12', option('false')), 'body', 'a mesh named Hair outside a merged head');
assert.strictEqual(api.receivingMeshKind('12', option('true')), 'head');
assert.strictEqual(api.receivingMeshKind('12', null), 'body');
console.log('PASS: refusal sentences and detail templates translate with values kept; hint follows the head flag');
