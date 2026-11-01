/* Portable, generated-only WebGL checks for reconstructed AS/Member equations. */
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const evidence = process.env.EVIDENCE_DIR || path.join(os.tmpdir(), 'sifas-material-browser');
fs.mkdirSync(evidence, { recursive: true });

(async () => {
  const options = {
    headless: true,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
  };
  if (process.env.CHROMIUM_EXECUTABLE) options.executablePath = process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(options);
  try {
    const page = await browser.newPage({ viewport: { width: 600, height: 400 } });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.setContent('<!doctype html><html><body></body></html>');
    await page.addScriptTag({ path: path.join(root, 'webtools/web/static/vendor/three-r128/three.min.js') });
    await page.addScriptTag({ path: path.join(root, 'webtools/web/static/sifas-material.js') });
    const results = await page.evaluate(async () => {
      const T = window.THREE;
      const all = [];
      function check(value, detail) { if (!value) throw new Error(detail); }
      function near(actual, expected, name) {
        for (let c = 0; c < 3; c++) check(Math.abs(actual[c] - expected[c]) <= 3,
          name + ': pixel ' + JSON.stringify(actual) + ' expected ' + JSON.stringify(expected));
      }
      function image(rgba, width = 1, height = 1) {
        const data = new Uint8Array(width * height * 4);
        for (let i = 0; i < data.length; i += 4) data.set(rgba, i);
        const result = new T.DataTexture(data, width, height, T.RGBAFormat);
        result.encoding = T.sRGBEncoding;
        result.magFilter = result.minFilter = T.NearestFilter;
        result.generateMipmaps = false; result.needsUpdate = true;
        return result;
      }
      function reference(source, mask, colors, floats, features, samples) {
        const main = source.map(v => v / 255);
        let rgb = main.slice(0, 3).map(v => v * (mask[2] < .1 ? .35 : 1));
        if (features.cheek) rgb = rgb.map((v, i) => v * (1 + (samples.cheek[i] - 1) * floats.cheek));
        if (features.matcap) {
          const c = samples.cap, m = samples.capMask;
          const lum = c[0] * .299 + c[1] * .587 + c[2] * .114;
          const sp = c.slice(0, 3).map((v, i) => v + m[2] * (lum * colors.span[i] * (1 - floats.spanAdd + main[i] * floats.spanAdd) - v));
          const bright = sp.map((v, i) => main[i] + m[1] * colors.cap[i] * (v * (1 - floats.capAdd) + (v * floats.brightG + main[i]) * floats.capAdd - main[i]));
          const metallic = main.slice(0, 3).map((v, i) => {
            const dark = v * floats.darkenR;
            const over = dark < .5 ? 2 * dark * c[3] : 1 - 2 * (1 - dark) * (1 - c[3]);
            const blended = ((1 - floats.capAdd) * c[3] + floats.capAdd * over) * floats.brightR;
            return v + m[0] * colors.cap[i] * (blended - v);
          });
          rgb = rgb.map((v, i) => v + colors.cap[3] * ((metallic[i] + m[1] * (bright[i] - metallic[i])) - v));
        }
        rgb = rgb.map((v, i) => (v + colors.ambient[3] * (colors.ambient[i] - v)) * (1 + colors.tint[3] * (colors.tint[i] - 1)));
        if (features.emissive) {
          const e = samples.emission.map((v, i) => v * samples.scroll[i] * colors.emission[i]);
          rgb = rgb.map((v, i) => v + e[i] * e[3]);
        }
        if (features.rimlight) rgb = rgb.map((v, i) => v + samples.rim * colors.rim[3] * floats.rimIntensity * colors.rim[i]);
        return rgb.map(v => Math.round(Math.max(0, Math.min(1, v)) * 255));
      }
      for (const forceWebGL1 of [false, true]) {
        const canvas = document.createElement('canvas'); document.body.appendChild(canvas);
        const context = forceWebGL1 ? canvas.getContext('webgl', { antialias: false, stencil: true }) : undefined;
        check(!forceWebGL1 || !!context, 'WebGL1 target unavailable');
        const renderer = new T.WebGLRenderer({ canvas, context, antialias: false, stencil: true });
        renderer.setSize(128, 128); renderer.outputEncoding = T.sRGBEncoding; renderer.toneMapping = T.NoToneMapping;
        const gl = renderer.getContext();
        const camera = new T.PerspectiveCamera(35, 1, .01, 10); camera.position.set(0, 0, 3); camera.lookAt(0, 0, 0);
        const target = forceWebGL1 ? 'webgl1' : renderer.capabilities.isWebGL2 ? 'webgl2' : 'default-webgl1';
        async function drawCase(name, args = {}) {
          const scene = new T.Scene(); scene.background = new T.Color(0x202020);
          const root = new T.Group(); scene.add(root);
          const geometry = new T.PlaneBufferGeometry(1, 1);
          const mask = args.mask || [1, 1, 1, 1];
          geometry.setAttribute('_sifas_color', new T.Float32BufferAttribute(Array(4).fill(mask).flat(), 4));
          if (args.rim) geometry.setAttribute('normal', new T.Float32BufferAttribute(Array(4).fill([1, 0, 0]).flat(), 3));
          const textures = [image(args.base || [40, 180, 240, 255])];
          const original = new T.MeshBasicMaterial({ map: textures[0], side: T.DoubleSide });
          const colors = { _TintColor: [1, 1, 1, 1], _AmbientColor: [1, 1, 1, 0], _RimlightColor: [1, 0, 0, .5],
            _MatcapIntensity: [.8, .7, .6, .75], _MatcapSpanCol: [.6, 1.1, .7, 1], _EmissiveIntensity: [.7, .8, .9, .6] };
          if (args.tint) { colors._TintColor = [1.2, .7, 1, .5]; colors._AmbientColor = [.3, .2, .1, .4]; }
          const features = { rimlight: !!args.rim, matcap: !!args.matcap, cheek: !!args.cheek, emissive: !!args.emissive, outline: true };
          const floats = { _RimglightIntensity: args.rim ? .5 : 0, _RimglightPower: 3, _CullMode: 0, _OutlineStencilComp: 8,
            _MatcapTexAdd: .4, _MatcapSpanColTexAdd: .3, _MatcapTexDarkenR: .8, _MatcapBrightR: 1.2, _MatcapBrightG: 1.4, _CheekIntensity: .5 };
          if (args.cull !== undefined) floats._CullMode = args.cull;
          const meta = { version: 1, shader: 'AS/Member', colors, floats, features, textures: { _MainTex: { index: 0 } }, limitations: [] };
          const sample = {};
          function add(key, rgba, sampleName) { const index = textures.length; textures.push(image(rgba)); meta.textures[key] = { index }; sample[sampleName] = rgba.map(v => v / 255); }
          if (args.rim) { add('_RimlightTex', [128, 128, 128, 255], 'rimSample'); sample.rim = 128 / 255; }
          if (args.matcap) { add('_MatcapTex', [128, 64, 32, 192], 'cap'); add('_MatcapMaskTex', [77, 102, 128, 255], 'capMask'); }
          if (args.cheek) add('_CheekTex', [153, 204, 255, 255], 'cheek');
          if (args.emissive) { add('_EmissiveTex', [20, 40, 50, 150], 'emission'); add('_EmissiveScrollTex', [180, 160, 140, 190], 'scroll'); }
          function asymmetricTexture(key) {
            const texture = image([0, 0, 0, 255], 4, 4);
            for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) {
              texture.image.data.set(y < 2 ? [255, 0, 0, 255] : [0, 0, 255, 255], (y * 4 + x) * 4);
            }
            texture.needsUpdate = true;
            meta.textures[key] = { index: textures.length }; textures.push(texture);
          }
          if (args.matcapUv) {
            geometry.setAttribute('normal', new T.Float32BufferAttribute(Array(4).fill([0, .6, .8]).flat(), 3));
            colors._MatcapIntensity = [1, 1, 1, 1]; floats._MatcapTexAdd = 0;
            asymmetricTexture('_MatcapTex'); add('_MatcapMaskTex', [0, 255, 0, 255], 'capMask');
          }
          if (args.emissiveUv) {
            colors._EmissiveIntensity = [1, 1, 1, 1]; colors._EmissiveFlicker = [0, .25, 0, 0];
            asymmetricTexture('_EmissiveScrollTex'); add('_EmissiveTex', [255, 255, 255, 255], 'emission');
          }
          if (args.cheekUv) {
            floats._CheekIntensity = 1; asymmetricTexture('_CheekTex');
          }
          if (args.mips) {
            // A high authored UV frequency plus the source-supported bias6
            // deterministically selects the coarsest level on both APIs.
            geometry.attributes.uv.array.forEach((value, index, array) => { array[index] = value * 8; });
            textures[0].dispose(); textures[0] = image([255, 0, 0, 255], 4, 4); original.map = textures[0];
            textures.push(image([0, 255, 0, 255], 2, 2), image([0, 0, 255, 255], 1, 1));
            meta.textures._MainTex = { index: 0, mipmaps: [0, 1, 2], filterMode: 2 };
            floats._MainTexMipmapBias = 6;
          }
          original.userData.sifas = meta;
          let mesh;
          if (args.skin) {
            geometry.setAttribute('skinIndex', new T.Uint16BufferAttribute(Array(4).fill([0, 0, 0, 0]).flat(), 4));
            geometry.setAttribute('skinWeight', new T.Float32BufferAttribute(Array(4).fill([1, 0, 0, 0]).flat(), 4));
            geometry.morphTargetsRelative = true;
            geometry.morphAttributes.position = [new T.Float32BufferAttribute(Array(4).fill([0, .1, 0]).flat(), 3)];
            geometry.morphAttributes.normal = [new T.Float32BufferAttribute(Array(4).fill([0, 0, 0]).flat(), 3)];
            mesh = new T.SkinnedMesh(geometry, original);
            const bone = new T.Bone(); bone.name = 'Neutral'; mesh.add(bone); mesh.bind(new T.Skeleton([bone]));
            mesh.morphTargetInfluences[0] = .5;
          } else mesh = new T.Mesh(geometry, original);
          if (args.backface) mesh.rotation.y = Math.PI;
          root.add(mesh); root.updateMatrixWorld(true);
          const controller = SifasMaterial.apply(root, renderer, { parser: { getDependency: async (_, index) => textures[index] } });
          await controller.ready;
          if (args.emissiveUv) controller.setBeat(1);
          if (args.cull !== undefined) mesh.children.filter(child => child.userData.viewerHelper).forEach(child => { child.visible = false; });
          renderer.render(scene, camera);
          const pixel = new Uint8Array(4); gl.readPixels(64, 64, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
          const gpuTriangles = renderer.info.render.triangles;
          const state = controller.getState();
          check(state.recognizedMaterials === 1 && state.outlines === 1 && state.pipeline === 'gamma', name + ': metadata');
          check(mesh.children.filter(child => child.userData.viewerHelper).length === 1, name + ': helper');
          check(gpuTriangles === (args.cull !== undefined ? 2 : 4), name + ': source/outline draw triangle count: ' + gpuTriangles);
          const culled = args.cull === 1 && !args.backface || args.cull === 2 && args.backface;
          const expected = culled ? [32, 32, 32] : args.matcapUv || args.emissiveUv ? [255, 0, 0] : args.mips || args.cheekUv ? [0, 0, 255] : reference(args.base || [40, 180, 240, 255], mask,
            { ambient: colors._AmbientColor, tint: colors._TintColor, rim: colors._RimlightColor, cap: colors._MatcapIntensity, span: colors._MatcapSpanCol, emission: colors._EmissiveIntensity },
            { cheek: .5, capAdd: .4, spanAdd: .3, darkenR: .8, brightR: 1.2, brightG: 1.4, rimIntensity: .5 }, features, sample);
          near(Array.from(pixel), expected, target + '/' + name);
          check(gl.getError() === 0, name + ': GPU error');
          if (args.skin) {
            mesh.skeleton.bones[0].position.x = .1; mesh.morphTargetInfluences[0] = .9;
            scene.updateMatrixWorld(true); renderer.render(scene, camera);
            check(gl.getError() === 0, name + ': animated skin/morph compile');
            check(mesh.children.find(child => child.userData.viewerHelper).morphTargetInfluences === mesh.morphTargetInfluences, 'Shared morph updates');
          }
          controller.setEnabled(false); renderer.render(scene, camera);
          check(mesh.material === original && renderer.info.render.triangles === 2, name + ': basic fallback');
          controller.setEnabled(true); renderer.render(scene, camera);
          check(renderer.info.render.triangles === 4, name + ': restore shader');
          controller.dispose(); controller.dispose();
          check(mesh.material === original && !mesh.children.some(child => child.userData.viewerHelper), name + ': restore original/dispose helpers');
          check(controller.getState().ownedTextures === 0 && controller.getState().ownedMaterials === 0, name + ': owned resources released');
          original.dispose(); textures.forEach(texture => texture.dispose()); geometry.dispose();
          all.push({ target, name, pixel: Array.from(pixel), expected, sourceTriangles: 2, gpuTriangles, glError: 0, state });
        }
        await drawCase('gamma-mask', { mask: [1, 1, 0, 1] });
        await drawCase('ambient-tint', { tint: true });
        await drawCase('rim', { rim: true });
        await drawCase('matcap', { matcap: true });
        await drawCase('cheek', { cheek: true });
        await drawCase('emissive', { emissive: true });
        await drawCase('combined-variants', { matcap: true, cheek: true, emissive: true, tint: true, rim: true });
        await drawCase('authored-mips', { mips: true });
        await drawCase('skinned-morph', { skin: true });
        await drawCase('matcap-flipped-png-uv', { matcap: true, matcapUv: true });
        await drawCase('emissive-flipped-png-scroll', { emissive: true, emissiveUv: true, base: [0, 0, 0, 255] });
        await drawCase('cheek-flipped-png-uv', { cheek: true, cheekUv: true, base: [255, 255, 255, 255] });
        for (const cull of [0, 1, 2]) {
          await drawCase('main-cull-' + cull + '-front', { cull });
          await drawCase('main-cull-' + cull + '-back', { cull, backface: true });
        }

        const scene = new T.Scene(), root = new T.Group(); scene.add(root);
        const generic = new T.MeshBasicMaterial({ color: 0x4287d9 });
        const geometry = new T.PlaneBufferGeometry(1, 1), mesh = new T.Mesh(geometry, generic); root.add(mesh);
        const controller = SifasMaterial.apply(root, renderer); await controller.ready;
        check(controller.getState().recognizedMaterials === 0 && mesh.children.length === 0, 'Generic fallback unchanged');
        const temporary = new T.MeshBasicMaterial(); mesh.material = temporary;
        check(controller.getMaterial(mesh) === generic, 'Generic texture mode roundtrip retains original');
        controller.dispose();
        check(mesh.material === generic, 'Unknown solid-mode disposal restores original material');
        generic.dispose(); temporary.dispose(); geometry.dispose();

        const lateRoot = new T.Group(), lateGeometry = new T.PlaneBufferGeometry(1, 1);
        const baseTexture = image([40, 180, 240, 255]);
        const lateOriginal = new T.MeshBasicMaterial({ map: baseTexture });
        lateOriginal.userData.sifas = { version: 1, shader: 'AS/Member',
          colors: {}, floats: {}, features: { rimlight: true },
          textures: { _MainTex: { index: 0 }, _RimlightTex: { index: 1 } } };
        const lateMesh = new T.Mesh(lateGeometry, lateOriginal); lateRoot.add(lateMesh);
        let complete;
        const held = new Promise(resolve => { complete = resolve; });
        const lateController = SifasMaterial.apply(lateRoot, renderer, { parser: {
          getDependency: (_, index) => index === 0 ? Promise.resolve(baseTexture) : held } });
        lateController.dispose();
        const lateTexture = image([255, 255, 255, 255]); let lateDisposals = 0;
        lateTexture.addEventListener('dispose', () => { lateDisposals++; });
        complete(lateTexture); await lateController.ready;
        check(lateMesh.material === lateOriginal && !lateMesh.children.some(child => child.userData.viewerHelper), 'Late texture cannot reinstall cancelled shader');
        check(lateDisposals === 1 && lateController.getState().ownedTextures === 0, 'Late auxiliary texture is released exactly once');
        lateOriginal.dispose(); baseTexture.dispose(); lateGeometry.dispose();
        renderer.dispose(); renderer.forceContextLoss(); canvas.remove();
      }
      return all;
    });
    assert.deepStrictEqual(errors, [], JSON.stringify(errors));
    const report = { status: 'PASS', scope: 'Generated neutral geometry and textures only; GPU pixels compared with independent source-equation calculations. Not a game screenshot comparison.', results, errors };
    fs.writeFileSync(path.join(evidence, 'sifas-material-browser.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: report.status, cases: results.length, evidence }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
