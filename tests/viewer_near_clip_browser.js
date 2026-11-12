/* Actual WebGL clipping with the production camera policy and HQ renderer.
 * Two visible surfaces stand in for an outer layer and an interior layer;
 * no rendering, ray result or application response is mocked. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), os = require("node:os");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, ".."), out = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), "viewer-near-clip-"));
fs.mkdirSync(out, { recursive: true });
const report = { status: "RUNNING", scope: "Actual Three r128/WebGL and production standard/HQ renderer; synthetic outer/interior geometry, no rendering or picking mocks.", cases: [], pageErrors: [] };
(async () => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
      args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
    const page = await browser.newPage({ viewport: { width: 420, height: 420 }, deviceScaleFactor: 2 });
    page.on("pageerror", error => report.pageErrors.push(String(error)));
    await page.setContent("<!doctype html><html><body></body></html>");
    for (const file of ["vendor/three-r128/three.min.js", "viewer-quality.js", "viewer-near-clip.js"])
      await page.addScriptTag({ path: path.join(root, "webtools/web/static", file) });
    report.frames = await page.evaluate(() => {
      const T = THREE, renderer = new T.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
      renderer.outputEncoding = T.sRGBEncoding; renderer.toneMapping = T.NoToneMapping;
      document.body.appendChild(renderer.domElement);
      const quality = ViewerQuality.create(renderer), scene = new T.Scene(), camera = new T.PerspectiveCamera(35, 1, .001, 100);
      scene.background = new T.Color(0x202030); camera.position.set(0, 0, 0); camera.lookAt(0, 0, -1); camera.updateMatrixWorld(true);
      const geometry = new T.PlaneBufferGeometry(.4, .4), outer = new T.Mesh(geometry, new T.MeshBasicMaterial({ color: 0xff0000 })),
        interior = new T.Mesh(geometry.clone(), new T.MeshBasicMaterial({ color: 0x00ff00 }));
      outer.position.z = -.02; interior.position.z = -.2; scene.add(outer, interior); scene.updateMatrixWorld(true);
      const original = { outer: Array.from(outer.geometry.attributes.position.array), interior: Array.from(interior.geometry.attributes.position.array),
        outerSide: outer.material.side, interiorSide: interior.material.side };
      function draw(high, enabled, distance) {
        quality.setEnabled(high); quality.resize(160, 160);
        const policy = ViewerNearClip.apply(camera, { radius: 1, orbitDistance: .12, enabled, distance });
        quality.render(scene, camera);
        const gl = renderer.getContext(), color = new Uint8Array(4);
        gl.readPixels(Math.floor(gl.drawingBufferWidth / 2), Math.floor(gl.drawingBufferHeight / 2), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, color);
        return { high, enabled, distance, policy, center: Array.from(color), quality: quality.getState(), glError: gl.getError(),
          outerPickVisible: ViewerNearClip.visiblePoint(camera, new T.Vector3(0, 0, -.02)),
          interiorPickVisible: ViewerNearClip.visiblePoint(camera, new T.Vector3(0, 0, -.2)) };
      }
      const frames = [];
      try {
        for (const high of [false, true]) {
          frames.push(draw(high, false, .04));
          frames.push(draw(high, true, .04));
          frames.push(draw(high, true, .3));
          frames.push(draw(high, false, .04));
        }
        const restored = { outer: Array.from(outer.geometry.attributes.position.array), interior: Array.from(interior.geometry.attributes.position.array),
          outerSide: outer.material.side, interiorSide: interior.material.side };
        return { frames, original, restored, cameraPose: { position: camera.position.toArray(), quaternion: camera.quaternion.toArray(), fov: camera.fov } };
      } finally { quality.dispose(); outer.geometry.dispose(); interior.geometry.dispose(); outer.material.dispose(); interior.material.dispose(); renderer.dispose(); }
    });
    const red = color => color[0] > 240 && color[1] < 8 && color[2] < 8;
    const green = color => color[1] > 240 && color[0] < 8 && color[2] < 8;
    for (let group = 0; group < 2; group++) {
      const frames = report.frames.frames.slice(group * 4, group * 4 + 4), name = group ? "HQ" : "standard";
      assert(frames.every(frame => frame.glError === 0 && frame.quality.ready));
      if (group) assert(frames.every(frame => frame.quality.mode === "multisample" && frame.quality.actualSamples >= 2), "HQ exercises its actual multisample target");
      assert(red(frames[0].center), name + " OFF draws the original outer surface");
      assert(green(frames[1].center), name + " enabled clip removes only the near outer surface and reveals the interior");
      assert.deepEqual(frames[2].center, [32, 32, 48, 255], name + " a larger distance clips both surfaces and exposes the actual background");
      assert(red(frames[3].center), name + " disabling immediately restores the original outer surface");
      assert.equal(frames[1].outerPickVisible, false); assert.equal(frames[1].interiorPickVisible, true);
      assert.equal(frames[3].outerPickVisible, true);
      report.cases.push(name + " projection clips front/interior at selected depth, restores OFF, and agrees with pick visibility");
    }
    assert.deepEqual(report.frames.restored, report.frames.original, "Clipping never edits geometry or material culling");
    assert.deepEqual(report.frames.cameraPose.position, [0, 0, 0]);
    assert.equal(report.frames.cameraPose.fov, 35);
    report.cases.push("Source geometry, material sides, camera position and FOV remain unchanged");
    assert.deepEqual(report.pageErrors, []);
    report.status = "PASS";
    console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence: out }));
  } catch (error) { report.status = "FAIL"; report.error = String(error.stack || error); console.error(error); process.exitCode = 1; }
  finally { if (browser) await browser.close(); fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2) + "\n"); }
})();
