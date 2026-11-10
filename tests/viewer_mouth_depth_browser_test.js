/* Actual SifasMaterial GPU regression on independently authored geometry.
 * No game files, shader replacements, fabricated capabilities or AA changes. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mouth-depth-'));
fs.mkdirSync(evidence, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage(), errors = [];
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    for (const file of ['webtools/web/static/vendor/three-r128/three.min.js', 'webtools/web/static/sifas-material.js', 'tests/viewer_mouth_depth_scene.js']) {
      await page.addScriptTag({ path: path.join(root, file) });
    }
    const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/viewer_mouth_depth.json')));
    const result = await page.evaluate(async fixture => {
      const T = THREE, observations = [], checks = [];
      function check(condition, label) { checks.push({ label, pass: !!condition }); if (!condition) throw Error(label); }
      function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
      function renderer(webgl1) {
        const options = { antialias: true, alpha: false, depth: true, stencil: true };
        if (webgl1) { options.canvas = document.createElement('canvas'); options.context = options.canvas.getContext('webgl', options); check(!!options.context, 'Actual WebGL1 context exists'); }
        const value = new T.WebGLRenderer(options); value.setSize(64, 64); value.setClearColor(0); return value;
      }
      function pixel(r, scene) {
        r.render(scene.scene, scene.camera); const gl = r.getContext(), data = new Uint8Array(4);
        gl.readPixels(32, 31, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, data);
        check(gl.getError() === 0, 'Actual GPU render has no GL error'); return Array.from(data);
      }
      async function runCase(label, options) {
        const r = renderer(options.webgl1), gl = r.getContext(), scene = createNeutralSifasScene(T, fixture, { role: options.role });
        const sourcePositions = Array.from(scene.geometry.attributes.position.array), sourceUV = Array.from(scene.geometry.attributes.uv.array);
        if (options.parentRole) { delete scene.mesh.userData.viewerFacialRole; scene.root.userData.viewerFacialRole = 'mouth'; }
        if (options.outsideRole) { const outer = new T.Group(); outer.userData.viewerFacialRole = 'mouth'; outer.add(scene.root); scene.scene.add(outer); }
        const controller = SifasMaterial.apply(scene.root, r, { enabled: true, mouthCentroidDepth: options.enabled });
        await controller.ready;
        const active = options.enabled && r.capabilities.isWebGL2 && (options.role === 'mouth' || options.parentRole) && !options.outsideRole;
        check(active ? /centroid/.test(scene.mesh.material.vertexShader) : scene.mesh.material.vertexShader === SifasMaterial.vertexShader, label + ': correct vertex-program scope');
        check(active ? /gl_FragDepth/.test(scene.mesh.material.fragmentShader) : scene.mesh.material.fragmentShader === SifasMaterial.fragmentShader, label + ': correct depth-program scope');
        const helper = scene.mesh.children.find(child => child.userData.sifasOutline);
        check(active ? /centroid/.test(helper.material.vertexShader) && /gl_FragDepth/.test(helper.material.fragmentShader) :
          helper.material.vertexShader === SifasMaterial.outlineVertexShader && helper.material.fragmentShader === SifasMaterial.outlineFragmentShader,
        label + ': correct outline depth-program scope');
        for (const range of [[0, 1], [.2, .8]]) for (const order of [[0, 1], [1, 0]]) for (const occlusion of ['none', 'front', 'rear']) {
          scene.setOrder(order); scene.removeOccluders();
          if (occlusion !== 'none') scene.addOccluder(occlusion).renderOrder = order[0] ? -1 : 2;
          gl.depthRange(range[0], range[1]); const rgba = pixel(r, scene);
          if (active) check(same(rgba, occlusion === 'front' ? fixture.oracle.foregroundOccluderRGBA : fixture.oracle.centroidRGBA), label + ': correct actual sample occlusion');
          observations.push({ label, active, webgl2: r.capabilities.isWebGL2, samples: gl.getParameter(gl.SAMPLES), depthBits: gl.getParameter(gl.DEPTH_BITS), range, order, occlusion, rgba });
        }
        scene.setOrder([0, 1]);
        check(same(Array.from(scene.geometry.attributes.position.array), sourcePositions), label + ': source vertices unchanged');
        check(same(Array.from(scene.geometry.attributes.uv.array), sourceUV), label + ': source UV unchanged');
        check(gl.getParameter(gl.SAMPLES) > 1, label + ': multisampling remains enabled');
        controller.dispose(); scene.dispose(); r.dispose();
      }
      await runCase('marked WebGL2 mouth', { enabled: true, role: 'mouth' });
      await runCase('GLTF multi-primitive group', { enabled: true, role: null, parentRole: true });
      await runCase('unmarked named mesh', { enabled: true, role: null });
      await runCase('marker outside supplied model', { enabled: true, role: null, outsideRole: true });
      await runCase('capability option disabled', { enabled: false, role: 'mouth' });
      await runCase('real WebGL1 fallback', { enabled: true, role: 'mouth', webgl1: true });
      async function outlineCase(label, options) {
        const r = renderer(options.webgl1), gl = r.getContext();
        const scene = createNeutralSifasScene(T, fixture, { role: options.role, reverseWinding: true });
        const controller = SifasMaterial.apply(scene.root, r, { enabled: true, mouthCentroidDepth: true }); await controller.ready;
        const helper = scene.mesh.children.find(child => child.userData.sifasOutline), active = !options.webgl1 && options.role === 'mouth';
        check(helper.material.side === T.BackSide && helper.material.depthTest && helper.material.depthWrite, label + ': native outline culling/depth are retained');
        scene.mesh.material.visible = false; // Standalone QA: isolate the actual product outline helper.
        scene.setOrder([0]); const reference = pixel(r, scene);
        for (const range of [[0, 1], [.2, .8]]) for (const order of [[0, 1], [1, 0]]) for (const occlusion of ['none', 'front', 'rear']) {
          scene.setOrder(order); scene.removeOccluders();
          if (occlusion !== 'none') scene.addOccluder(occlusion).renderOrder = order[0] ? -1 : 2;
          gl.depthRange(range[0], range[1]); const rgba = pixel(r, scene);
          if (active) check(same(rgba, occlusion === 'front' ? fixture.oracle.foregroundOccluderRGBA : reference), label + ': rear outline sliver cannot leak through foreground');
          observations.push({ label, pass: 'outline', active, webgl2: r.capabilities.isWebGL2, samples: gl.getParameter(gl.SAMPLES), range, order, occlusion, rgba, reference });
        }
        if (active) {
          scene.removeOccluders(); scene.setOrder([0]); gl.depthRange(0, 1);
          const color = scene.geometry.attributes._sifas_color;
          for (let i = 0; i < color.count; i++) color.setY(i, 0);
          color.needsUpdate = true;
          const occluder = scene.addOccluder('front'), position = occluder.geometry.attributes.position;
          for (let i = 0; i < position.count; i++) position.setZ(i, .00035);
          position.needsUpdate = true;
          check(same(pixel(r, scene), fixture.oracle.foregroundOccluderRGBA), 'Outline centroid captures the original G=0 z-push after it is applied');
        } else {
          check(helper.material.vertexShader === SifasMaterial.outlineVertexShader && helper.material.fragmentShader === SifasMaterial.outlineFragmentShader,
            label + ': unmarked/WebGL1 outline programs are byte-identical');
        }
        check(gl.getParameter(gl.SAMPLES) > 1, label + ': outline test retains actual MSAA');
        controller.dispose(); scene.dispose(); r.dispose();
      }
      await outlineCase('marked WebGL2 outline', { role: 'mouth' });
      await outlineCase('unmarked WebGL2 outline', { role: null });
      await outlineCase('marked real WebGL1 outline fallback', { role: 'mouth', webgl1: true });
      await outlineCase('unmarked real WebGL1 outline fallback', { role: null, webgl1: true });
      const r = renderer(false), source = createNeutralSifasScene(T, fixture, { role: 'mouth' });
      const face = new T.Mesh(source.geometry, source.originalMaterial); face.name = 'Unmarked shared head material'; face.visible = false; source.root.add(face);
      const controller = SifasMaterial.apply(source.root, r, { enabled: true, mouthCentroidDepth: true }); await controller.ready;
      check(source.mesh.material !== face.material, 'Mouth has a separate cache entry from the shared head');
      check(face.material.vertexShader === SifasMaterial.vertexShader && face.material.fragmentShader === SifasMaterial.fragmentShader, 'Face/head program remains original');
      const outline = source.mesh.children.find(child => child.userData.sifasOutline);
      check(/centroid/.test(outline.material.vertexShader) && /gl_FragDepth/.test(outline.material.fragmentShader), 'Verified Mouth outline has the covered-depth adaptation');
      check(outline.material.vertexShader.lastIndexOf('vSifasMouthClipZW =') > outline.material.vertexShader.indexOf('gl_Position.z +='), 'Outline clip depth is captured after native expansion and z-push');
      const faceOutline = face.children.find(child => child.userData.sifasOutline);
      check(faceOutline.material.vertexShader === SifasMaterial.outlineVertexShader && faceOutline.material.fragmentShader === SifasMaterial.outlineFragmentShader, 'Unmarked shared-head outline programs remain original');
      const sourceBytes = Array.from(source.geometry.attributes.position.array), context = r.getContext();
      const extension = context.getExtension('WEBGL_lose_context');
      check(!!extension, 'The real context-loss extension is available');
      const lost = new Promise(resolve => r.domElement.addEventListener('webglcontextlost', event => {
        event.preventDefault(); controller.invalidateGPU(); resolve();
      }, { once: true }));
      extension.loseContext(); await lost;
      await new Promise(resolve => setTimeout(resolve, 80));
      const restored = new Promise(resolve => r.domElement.addEventListener('webglcontextrestored', resolve, { once: true }));
      extension.restoreContext(); await restored;
      check(same(pixel(r, source), fixture.oracle.centroidRGBA), 'Restored actual Mouth programs retain correct covered-depth occlusion');
      check(/gl_FragDepth/.test(source.mesh.material.fragmentShader) && /gl_FragDepth/.test(outline.material.fragmentShader), 'Both scoped depth programs survive GPU restoration');
      check(same(sourceBytes, Array.from(source.geometry.attributes.position.array)), 'Context restoration preserves source geometry');
      controller.dispose(); source.dispose(); r.dispose();
      return { status: 'PASS', scope: 'Actual product shaders and independent six-vertex fixture; host browser GPU, not native application FPS', checks, observations };
    }, fixture);
    result.consoleErrors = errors;
    assert.equal(errors.length, 0, errors.join('\n'));
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({ status: result.status, checks: result.checks.length, renders: result.observations.length, evidence }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
