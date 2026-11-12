/* Actual Unity bundle + HTTP backend + normal app UI. No model preparation,
 * export, rendering or picking success response is fabricated. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), os = require("node:os"), net = require("node:net"), crypto = require("node:crypto");
const { spawn, execFileSync } = require("node:child_process"), { chromium } = require("playwright");
const root = path.resolve(__dirname, ".."), python = process.env.VIEWER_PYTHON || "python3";
const out = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), "near-clip-app-")); fs.mkdirSync(out, { recursive: true });
const library = fs.mkdtempSync(path.join(os.tmpdir(), "near-clip-library-")), source = path.join(library, "extracted/3d_model/near-clip-layers.unity"); fs.mkdirSync(path.dirname(source), { recursive: true });
const hash = bytes => crypto.createHash("sha256").update(bytes).digest("hex"), wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const fixture = JSON.parse(execFileSync(python, ["-B", "-c", `import json,struct,sys,UnityPy
from pathlib import Path
env=UnityPy.load(Path('tests/fixtures/viewer_persistence.unity').read_bytes())
points=[(-.5,0,.25),(.5,0,.25),(0,1.5,.25),(-.5,0,-.25),(.5,0,-.25),(0,1.5,-.25)]
for obj in env.objects:
 if obj.type.name=='Mesh':
  tree=obj.read_typetree(); data=tree['m_VertexData']; buffer=bytearray(data['m_DataSize']); stride=len(buffer)//data['m_VertexCount']; assert data['m_VertexCount']==6 and stride==56
  for i,p in enumerate(points):
   struct.pack_into('<3f',buffer,i*stride,*p);struct.pack_into('<3f',buffer,i*stride+12,0,0,1)
   struct.pack_into('<2f',buffer,i*stride+24,*[(.1,.1),(.9,.1),(.5,.9)][i%3])
  data['m_DataSize']=bytes(buffer);tree['m_IndexBuffer']=struct.pack('<6H',0,1,2,3,4,5)
  sub=tree['m_SubMeshes'][0];sub['indexCount']=6;sub['vertexCount']=6
  sub['localAABB']={'m_Center':{'x':0.,'y':.75,'z':0.},'m_Extent':{'x':.5,'y':.75,'z':.25}}
  tree['m_LocalAABB']=sub['localAABB'];obj.save_typetree(tree)
Path(sys.argv[1]).write_bytes(env.file.save(packer='original'))
print(json.dumps({'positions':points,'triangles':[[0,1,2],[3,4,5]]}))`, source], { cwd: root, env: { ...process.env, PYTHONPATH: root + path.delimiter + path.dirname(root) }, encoding: "utf8" }));
const sourceHash = hash(fs.readFileSync(source));
const observedSourceFiles = ["webtools/web/index.html", ...["model-viewer.js", "viewer-near-clip.js", "viewer-interaction-tools.js", "viewer-mesh-tools.js", "viewer-mesh-runtime.js"].map(name => "webtools/web/static/" + name)];
const sourceHashes = () => Object.fromEntries(observedSourceFiles.map(file => [file, hash(fs.readFileSync(path.join(root, file)))]));
const report = { status: "RUNNING", scope: "Actual generated UnityFS fixture through production backend/index/WebGL; UI preference, projection, authored-state/source preservation and real mesh selection. No native app claim.", fixture, sourceHash, sourceBefore: sourceHashes(), cases: [], errors: [] };
let server, browser;
async function frames(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function state(page) { return page.evaluate(() => ({ clip: ModelViewer.getState().nearClip, camera: ModelViewer.getState().camera, authoring: ModelViewer.getAuthoringState() })); }
async function openModel(page, url) {
  page.on("pageerror", error => report.errors.push(String(error)));
  await page.route("**/static/viewer-quality.js", async route => {
    const response = await route.fetch(); await route.fulfill({ response, body: (await response.text()) + "\n(()=>{const create=ViewerQuality.create;ViewerQuality.create=function(renderer){const controller=create.apply(this,arguments),render=controller.render;controller.render=function(scene,camera){window.__nearClipObserved={scene,camera,renderer};return render.apply(this,arguments);};return controller;};})();" });
  });
  await page.goto(url); await page.waitForFunction(() => typeof openModelViewer === "function");
  await page.evaluate(source => { document.getElementById("viewer-auto-face").checked = false; openModelViewer([source]); }, source);
  await page.waitForFunction(() => { const state = ModelViewer.getState(); return state.loaded && !state.loading && state.nearClip.near > 0 && window.__nearClipObserved; });
  await frames(page);
}
async function viewSettings(page) {
  const summary = page.locator("#viewer-display-options > summary"); await summary.scrollIntoViewIfNeeded();
  if (!(await page.locator("#viewer-display-options").evaluate(element => element.open))) await summary.click();
  await frames(page);
}
async function closeSettings(page) {
  if (await page.locator("#viewer-display-options").evaluate(element => element.open)) await page.locator("#viewer-display-options > summary").click();
  await page.locator("#viewer-stage").scrollIntoViewIfNeeded(); await frames(page);
}
async function distance(page, value) {
  const input = page.locator("#viewer-near-clip-distance"); await input.fill(String(value)); await input.press("Tab"); await frames(page);
}
async function projection(page) { return page.evaluate(() => __nearClipObserved.camera.projectionMatrix.toArray()); }
async function show(page, id) {
  const target = page.locator(id); await target.evaluate(element => { for (let parent = element.parentElement; parent; parent = parent.parentElement) if (parent.tagName === "DETAILS") parent.open = true; });
  return target;
}
async function authorPendingPose(page) {
  const name = await page.evaluate(() => { const state = ModelViewer.getState(); const bone = state.rig.bones.find(bone => /BreastSize/i.test(bone.name)); return bone && String(bone.node); });
  assert(name, "The actual source rig exposes its editable body bone");
  await (await show(page, "#viewer-node-filter")).selectOption("all");
  await (await show(page, "#viewer-node")).selectOption(name);
  const field = await show(page, '#viewer-node-fields input[data-viewer-node-kind="scale"][data-axis="X"]'); await field.fill("1.4"); await field.dispatchEvent("input"); await frames(page);
  assert((await state(page)).authoring.edits.length > 0, "Use a real pending authoring edit while testing view-only clipping");
  await page.locator("#viewer-stage").scrollIntoViewIfNeeded(); await frames(page);
}
async function desktop(page, url) {
  await openModel(page, url); const initial = await state(page);
  assert.equal(initial.clip.enabled, false); assert.equal(initial.clip.distance, .03); assert(initial.clip.near > 0 && initial.clip.near < .03);
  await viewSettings(page); assert(!(await page.locator("#viewer-near-clip").isChecked())); assert(await page.locator("#viewer-near-clip-distance").isDisabled());
  report.cases.push("Fresh actual app starts with clipping OFF, .03 model-unit distance and the normal automatic near plane");
  await closeSettings(page); await authorPendingPose(page); const retained = await state(page), beforeProjection = await projection(page);
  await viewSettings(page); await page.locator("#viewer-near-clip").check(); await frames(page);
  const enabled = await state(page); assert.equal(enabled.clip.enabled, true); assert.equal(enabled.clip.near, .03); assert(!(await page.locator("#viewer-near-clip-distance").isDisabled()));
  assert.deepEqual(enabled.camera, retained.camera); assert.deepEqual(enabled.authoring, retained.authoring); assert.notDeepEqual(await projection(page), beforeProjection);
  await distance(page, .15); const moved = await state(page); assert.equal(moved.clip.near, .15); assert.equal(moved.clip.distance, .15); assert.deepEqual(moved.camera, retained.camera); assert.deepEqual(moved.authoring, retained.authoring);
  await page.locator("#viewer-near-clip").uncheck(); await frames(page); const restored = await state(page);
  assert.equal(restored.clip.near, retained.clip.near); assert.deepEqual(await projection(page), beforeProjection); assert.deepEqual(restored.camera, retained.camera); assert.deepEqual(restored.authoring, retained.authoring);
  report.cases.push("Actual View controls update projection immediately, restore OFF exactly, and preserve real pending pose/camera/source state");
  await page.locator("#viewer-near-clip").check(); await distance(page, .125); await page.reload();
  await page.waitForFunction(() => typeof openModelViewer === "function"); await page.evaluate(source => { document.getElementById("viewer-auto-face").checked = false; openModelViewer([source]); }, source);
  await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading); await frames(page);
  const reopened = await state(page); assert.equal(reopened.clip.enabled, true); assert.equal(reopened.clip.distance, .125); assert.equal(reopened.clip.near, .125);
  await viewSettings(page); assert(await page.locator("#viewer-near-clip").isChecked()); assert.equal(await page.locator("#viewer-near-clip-distance").inputValue(), "0.125");
  await page.locator("#viewer-near-clip").uncheck(); await frames(page); await page.reload();
  await page.waitForFunction(() => typeof ModelViewer === "object" && ModelViewer.getState().nearClip); assert.equal(await page.evaluate(() => ModelViewer.getState().nearClip.enabled), false);
  report.cases.push("Explicit enabled distance and subsequent OFF preference persist through actual page reloads");
  await page.evaluate(source => { document.getElementById("viewer-auto-face").checked = false; openModelViewer([source]); }, source); await page.waitForFunction(() => ModelViewer.getState().loaded && !ModelViewer.getState().loading); await frames(page);
  await meshPicking(page);
}
async function meshPicking(page) {
  await (await show(page, "#viewer-mesh-modify-load")).click();
  await page.waitForFunction(() => [...document.getElementById("viewer-mesh-modify-select").options].some(option => option.value && !option.disabled));
  const value = await page.locator("#viewer-mesh-modify-select option").evaluateAll(options => options.find(option => option.value && !option.disabled).value);
  await page.locator("#viewer-mesh-modify-select").selectOption(value);
  await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy && ModelViewer.getState().meshTools.runtime.boundPrimitives > 0);
  await page.locator("#viewer-stage").scrollIntoViewIfNeeded(); await page.locator("#viewer-interaction-edit").click();
  const brush = page.locator('[data-viewer-edit-action="modify:paint"]'); if (!(await brush.isVisible())) await page.locator("#viewer-interaction-edit").click();
  await brush.click(); await frames(page);
  const layered = await page.evaluate(value => {
    const identity = JSON.parse(value), camera = __nearClipObserved.camera;
    const vertices = Array.from({ length: 6 }, (_, i) => { const p = ModelViewer.projectMeshVertex(identity, i); return { index: i, ...p, depthUnits: ViewerNearClip.viewDepth(camera, { x: p.world[0], y: p.world[1], z: p.world[2] }) }; });
    const groups = [vertices.slice(0, 3), vertices.slice(3, 6)].sort((a, b) => a.reduce((sum, p) => sum + p.depthUnits, 0) - b.reduce((sum, p) => sum + p.depthUnits, 0));
    return { vertices, front: groups[0], back: groups[1], distance: (groups[0][0].depthUnits + groups[1][0].depthUnits) / 2 };
  }, value);
  assert(layered.distance > .001 && layered.distance < 10);
  const click = points => ({ x: points.reduce((sum, p) => sum + p.x, 0) / 3, y: points.reduce((sum, p) => sum + p.y, 0) / 3 });
  const frontPoint = click(layered.front); await page.mouse.click(frontPoint.x, frontPoint.y); await frames(page);
  const selectedFront = await page.evaluate(() => ModelViewer.getState().meshTools.selectedVertices);
  assert(selectedFront.length && selectedFront.every(vertex => layered.front.some(point => point.index === vertex)), "OFF selects only the actual visible outer layer");
  await page.locator("#viewer-interaction-clear").click();
  await viewSettings(page); await page.locator("#viewer-near-clip").check(); await distance(page, layered.distance); await closeSettings(page);
  const selectedBefore = await page.evaluate(() => ModelViewer.getState().meshTools.selectedVertices); assert.deepEqual(selectedBefore, []);
  const backPoint = click(layered.back); await page.mouse.click(backPoint.x, backPoint.y); await frames(page);
  const selectedBack = await page.evaluate(() => ModelViewer.getState().meshTools.selectedVertices);
  assert(selectedBack.length && selectedBack.every(vertex => layered.back.some(point => point.index === vertex)), "ON skips clipped front geometry and permits selection of the visible interior layer");
  report.meshPicking = { layered, selectedFront, selectedBack };
  report.cases.push("Real 3D brush selects outer vertices OFF and only the visible interior vertices after clipping");
}
async function phone(page, url) {
  await openModel(page, url); await viewSettings(page);
  assert(!(await page.locator("#viewer-near-clip").isChecked())); const before = await state(page);
  await page.locator("#viewer-near-clip").scrollIntoViewIfNeeded(); await frames(page);
  const target = await page.locator("#viewer-near-clip").evaluate(element => { const label = element.closest("label"), r = label.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return { width: r.width, height: r.height, within: r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight, hit: hit === label || label.contains(hit) }; });
  report.phoneTarget = target; assert(target.within && target.hit && target.width >= 44 && target.height >= 44, "Phone View settings exposes the actual clipping checkbox with a 44px touch target");
  await page.locator("#viewer-near-clip").check(); await distance(page, .075); const after = await state(page);
  assert.equal(after.clip.near, .075); assert.deepEqual(after.camera, before.camera); assert.deepEqual(after.authoring, before.authoring);
  await page.locator("#viewer-near-clip").uncheck(); await frames(page); assert.equal((await state(page)).clip.near, before.clip.near);
  await page.screenshot({ path: path.join(out, "phone.png") });
  report.phoneTarget = target; report.cases.push("Phone View settings clipping controls are reachable, preserve the view and restore OFF");
}
(async () => {
  try {
    const socket = net.createServer(); await new Promise(resolve => socket.listen(0, "127.0.0.1", resolve)); const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
    const log = fs.createWriteStream(path.join(out, "server.log"));
    server = spawn(python, ["-B", "-m", "webtools", "--no-browser", "--host", "127.0.0.1", "--port", String(port)], { cwd: root,
      env: { ...process.env, SUKUSTA_DIR: library, PYTHONPATH: root + path.delimiter + path.dirname(root) }, stdio: ["ignore", "pipe", "pipe"] }); server.stdout.pipe(log); server.stderr.pipe(log);
    const url = "http://127.0.0.1:" + port; for (let i = 0; i < 100; i++) { try { if ((await fetch(url + "/api/tools")).ok) break; } catch (_) {} await wait(100); }
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
    const context = await browser.newContext({ viewport: { width: 1360, height: 900 } }); await context.addInitScript(() => localStorage.setItem("sifas_lang", "en"));
    const page = await context.newPage(); await desktop(page, url); await page.screenshot({ path: path.join(out, "desktop.png") }); await context.close();
    const mobile = await browser.newContext({ viewport: { width: 450, height: 1016 }, hasTouch: true }); await mobile.addInitScript(() => localStorage.setItem("sifas_lang", "en"));
    await phone(await mobile.newPage(), url); await mobile.close();
    assert.equal(hash(fs.readFileSync(source)), sourceHash, "View clipping and selection never modify the actual Unity source"); assert.deepEqual(report.errors, []);
    report.sourceAfter = sourceHashes(); assert.deepEqual(report.sourceAfter, report.sourceBefore, "The actual app sources stay fixed throughout this full test");
    report.status = "PASS"; console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence: out }));
  } catch (error) { report.status = "FAIL"; report.error = String(error.stack || error); console.error(error); process.exitCode = 1; }
  finally { if (browser) await browser.close(); if (server) server.kill(); fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2) + "\n"); }
})();
