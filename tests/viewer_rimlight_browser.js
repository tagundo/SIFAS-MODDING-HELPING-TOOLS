/* Actual UI/persistence checks using an independently generated glTF fixture. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), os = require('os'), path = require('path');
const { chromium } = require('playwright');
const { fixture } = require('./viewer_rig_browser');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-rimlight-'));
fs.mkdirSync(evidence, { recursive: true });
const url = process.env.VIEWER_URL || 'http://127.0.0.1:8898', key = 'elichika.viewer.rimlight.v1';

function rimFixture() {
  const generated = fixture({ semanticExpressions: true });
  const length = generated.glb.readUInt32LE(12), doc = JSON.parse(generated.glb.subarray(20, 20 + length));
  const binary = Buffer.from(generated.glb.subarray(28 + length));
  const normal = doc.accessors[doc.meshes[0].primitives[0].attributes.NORMAL], view = doc.bufferViews[normal.bufferView];
  for (let i = 0; i < normal.count; i++) {
    const offset = (view.byteOffset || 0) + (normal.byteOffset || 0) + i * 12;
    binary.writeFloatLE(1, offset); binary.writeFloatLE(0, offset + 4); binary.writeFloatLE(0, offset + 8);
  }
  doc.nodes[4].extras.viewerFacialRole = 'mouth';
  doc.materials[0].extras = { sifas: { version: 1, shader: 'AS/Member', colors: {
    _TintColor: [.3, .45, .6, 1], _AmbientColor: [1, 1, 1, 0], _RimlightColor: [1, .2, .1, 1]
  }, floats: { _CullMode: 0, _RimglightIntensity: .3, _RimglightPower: 3 },
  features: { rimlight: true, outline: true }, textures: { _MainTex: { default: [1, 1, 1, 1] }, _RimlightTex: { default: [1, 1, 1, 1] } }, limitations: [] } };
  const json = Buffer.from(JSON.stringify(doc)), padded = Buffer.alloc(Math.ceil(json.length / 4) * 4, 0x20); json.copy(padded);
  const header = Buffer.alloc(20); header.write('glTF'); header.writeUInt32LE(2, 4); header.writeUInt32LE(28 + padded.length + binary.length, 8);
  header.writeUInt32LE(padded.length, 12); header.write('JSON', 16);
  const binHeader = Buffer.alloc(8); binHeader.writeUInt32LE(binary.length); binHeader.write('BIN\0', 4);
  return { rig: generated.rig, glb: Buffer.concat([header, padded, binHeader, binary]), authored: doc.materials[0].extras.sifas };
}

(async () => {
  const launch = { headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] };
  if (process.env.CHROMIUM_EXECUTABLE) launch.executablePath = process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(launch), generated = rimFixture(), requests = [], errors = [], vendorDiagnostics = [], rows = [];
  const sourceHash = crypto.createHash('sha256').update(generated.glb).digest('hex');
  let context;
  async function pageFor(storageState) {
    context = await browser.newContext({ viewport: { width: 1080, height: 900 }, storageState });
    await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      // Three r128 reports this existing deprecated getter during model copy;
      // retain it separately from real page/GL/shader failures.
      if (message.text() === 'THREE.Mesh: .drawMode has been removed. The renderer now always assumes THREE.TrianglesDrawMode.') vendorDiagnostics.push(message.text());
      else errors.push(message.text());
    });
    await page.route('**/api/viewer/prepare', route => {
      requests.push(route.request().postDataJSON());
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        id: 'rimlight-fixture', url: '/api/viewer/model/rimlight-fixture.glb',
        stats: { meshes: 1, vertices: 3, triangles: 1, materials: 1, textures: 0 }, warnings: [], rig: generated.rig
      }) });
    });
    await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: generated.glb }));
    await page.goto(url); await page.waitForFunction(() => !!window.ModelViewer && !!window.SifasMaterial);
    await page.evaluate(() => {
      const create = ViewerRig.create;
      ViewerRig.create = function () { window.__rimRoot = arguments[0]; return create.apply(this, arguments); };
    });
    return page;
  }
  async function open(page, name) {
    await page.evaluate(name => { openModelViewer(['/synthetic/' + name + '.unity']); }, name);
    try {
      await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading, null, { timeout: 30000 });
    } catch (error) {
      fs.writeFileSync(path.join(evidence, 'failure.json'), JSON.stringify({ errors, requests,
        state: await page.evaluate(() => ModelViewer.getState()) }, null, 2));
      await page.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true }); throw error;
    }
    await page.locator('#viewer-display-options').evaluate(node => { node.open = true; });
    await page.evaluate(() => ModelViewer.renderProbe());
  }
  async function capture(page, label) {
    const row = await page.evaluate(label => {
      const probe = ModelViewer.renderProbe(33), canvas = document.getElementById('viewer-canvas');
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl'), width = gl.drawingBufferWidth, height = gl.drawingBufferHeight;
      const pixels = new Uint8Array(width * height * 4); gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      const histogram = new Map(), bg = Array.from(pixels.slice((width + 1) * 4, (width + 1) * 4 + 4));
      for (let i = 0; i < pixels.length; i += 4) {
        if (Math.abs(pixels[i] - bg[0]) + Math.abs(pixels[i + 1] - bg[1]) + Math.abs(pixels[i + 2] - bg[2]) < 30) continue;
        const key = Array.from(pixels.slice(i, i + 4)).join(','); histogram.set(key, (histogram.get(key) || 0) + 1);
      }
      const dominant = [...histogram].sort((a, b) => b[1] - a[1])[0];
      const source = [];
      window.__rimRoot.traverse(mesh => {
        if (!mesh.isMesh || mesh.userData.viewerHelper) return;
        const material = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
        const outline = mesh.children.find(child => child.userData.sifasOutline);
        source.push({ name: mesh.name, metadata: material.userData.sifas,
          geometry: Object.fromEntries(Object.entries(mesh.geometry.attributes).filter(([key]) => !/^morph(?:Target|Normal)\d+$/.test(key)).map(([key, attr]) => [key, Array.from(attr.array)])),
          indices: Array.from(mesh.geometry.index.array), morphs: mesh.morphTargetInfluences.slice(),
          vertexShader: material.vertexShader, fragmentShader: material.fragmentShader,
          outlineVertex: outline.material.vertexShader, outlineFragment: outline.material.fragmentShader });
      });
      const frames = window.__rimFrames || (window.__rimFrames = {}); let changed = null;
      if (frames.off && frames.off.length === pixels.length) changed = pixels.reduce((sum, value, i) => sum + (value !== frames.off[i]), 0);
      if (label === 'off') frames.off = pixels;
      return { label, checkbox: document.getElementById('viewer-rimlight').checked,
        stored: localStorage.getItem('elichika.viewer.rimlight.v1'), state: ModelViewer.getState(), probe,
        dominant: dominant && dominant[0].split(',').map(Number), differentChannelsFromOff: changed, source };
    }, label);
    assert.equal(row.probe.glError, 0); assert(row.dominant, 'A real rendered object must be present'); rows.push(row); return row;
  }
  async function set(page, enabled) {
    await page.locator('#viewer-rimlight').setChecked(enabled);
    await page.waitForFunction(enabled => ModelViewer.getState().materials.rimlightEnabled === enabled, enabled);
    await page.evaluate(() => ModelViewer.renderProbe());
  }
  try {
    let page = await pageFor(); await open(page, 'rim-default');
    const off = await capture(page, 'off'); assert.equal(off.checkbox, false); assert.equal(off.state.materials.rimlightEnabled, false);
    assert.equal(off.stored, null, 'A fresh profile uses the UI default rather than inventing a saved choice');
    const count = requests.length; await set(page, true); const on = await capture(page, 'on');
    assert.equal(on.stored, 'true'); assert.equal(requests.length, count, 'Display-only lighting does not reimport or reload the model');
    assert(on.dominant[0] > off.dominant[0] + 15, 'The authored rim visibly changes actual GPU pixels');
    assert.deepEqual(on.source, off.source, 'Rim preview keeps authored material, source geometry, morphs and both program texts');
    assert.deepEqual(on.state.rig, off.state.rig, 'Display-only lighting preserves pose/edits');
    await set(page, false); const returned = await capture(page, 'returned-off'); assert.equal(returned.stored, 'false');
    assert.equal(returned.differentChannelsFromOff, 0, 'Off/on/off restores the exact original framebuffer');
    assert.deepEqual(returned.source, off.source);
    await set(page, true); await open(page, 'rim-model-reload'); const modelReload = await capture(page, 'model-reload-on');
    assert(modelReload.checkbox && modelReload.state.materials.rimlightEnabled, 'New models keep the current display preference');
    assert.deepEqual(modelReload.dominant, on.dominant);
    const savedOn = await context.storageState(); await context.close();
    page = await pageFor(savedOn); await open(page, 'rim-context-reopen-on'); const reopened = await capture(page, 'context-reopen-on');
    assert(reopened.checkbox && reopened.state.materials.rimlightEnabled && reopened.stored === 'true', 'Persisted same-origin storage restores ON in a fresh browser context');
    await set(page, false); const savedOff = await context.storageState(); await context.close();
    page = await pageFor(savedOff); await open(page, 'rim-context-reopen-off'); const reopenedOff = await capture(page, 'context-reopen-off');
    assert(!reopenedOff.checkbox && !reopenedOff.state.materials.rimlightEnabled && reopenedOff.stored === 'false', 'Persisted OFF survives a fresh browser context');
    assert.deepEqual(reopenedOff.dominant, off.dominant);
    assert.equal(crypto.createHash('sha256').update(generated.glb).digest('hex'), sourceHash);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify({ status: 'PASS', scope: 'Actual main UI and generated glTF; same-origin browser storage persistence, not a native port-change claim', sourceHash, requests, rows, errors, vendorDiagnostics }, null, 2));
    console.log(JSON.stringify({ status: 'PASS', frames: rows.length, prepares: requests.length, evidence }));
  } finally { if (context) await context.close(); await browser.close(); }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
