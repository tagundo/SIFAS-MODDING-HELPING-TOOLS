/* MemberCheekBase on the head material: ResetAll at initialization, ApplyCheek
   writes _CheekTexArrayIndex/_CheekIntensity, ApplyEnable toggles _CHEEK_ON.
   Only a real exported cheek array slice can tint; the white placeholder never does. */
const assert = require('assert');
const path = require('path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');

(async () => {
  const options = { headless: true, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] };
  if (process.env.CHROMIUM_EXECUTABLE) options.executablePath = process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(options);
  try {
    const page = await browser.newPage({ viewport: { width: 300, height: 300 } });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.setContent('<!doctype html><html><body></body></html>');
    await page.addScriptTag({ path: path.join(root, 'webtools/web/static/vendor/three-r128/three.min.js') });
    await page.addScriptTag({ path: path.join(root, 'webtools/web/static/sifas-material.js') });
    const result = await page.evaluate(async () => {
      const T = window.THREE;
      function image(rgba) {
        const result = new T.DataTexture(new Uint8Array(rgba), 1, 1, T.RGBAFormat);
        result.encoding = T.sRGBEncoding; result.magFilter = result.minFilter = T.NearestFilter;
        result.generateMipmaps = false; result.needsUpdate = true;
        return result;
      }
      const canvas = document.createElement('canvas'); document.body.appendChild(canvas);
      const renderer = new T.WebGLRenderer({ canvas, antialias: false, stencil: true });
      renderer.setSize(64, 64); renderer.outputEncoding = T.sRGBEncoding; renderer.toneMapping = T.NoToneMapping;
      const gl = renderer.getContext();
      const camera = new T.PerspectiveCamera(35, 1, .01, 10); camera.position.set(0, 0, 3); camera.lookAt(0, 0, 0);
      async function build(name, { slot, authored }) {
        const scene = new T.Scene(); scene.background = new T.Color(0x202020);
        const geometry = new T.PlaneBufferGeometry(1, 1);
        geometry.setAttribute('_sifas_color', new T.Float32BufferAttribute(Array(4).fill([1, 1, 1, 1]).flat(), 4));
        const textures = [image([200, 180, 160, 255]), image([128, 64, 255, 255])];
        const original = new T.MeshBasicMaterial({ map: textures[0], side: T.DoubleSide });
        original.name = name;
        const floats = { _RimglightIntensity: 0, _CullMode: 0, _OutlineStencilComp: 8,
          _CheekIntensity: authored, _CheekTexArrayIndex: 0 };
        original.userData.sifas = { version: 1, shader: 'AS/Member', colors: {}, floats, limitations: [],
          features: { cheek: authored !== 0, outline: true },
          textures: { _MainTex: { index: 0 }, ...(slot ? { _CheekTex: { index: 1, arrayLayer: 0 } } : {}) } };
        const mesh = new T.Mesh(geometry, original); scene.add(mesh);
        const controller = SifasMaterial.apply(scene, renderer, { parser: { getDependency: async (_, index) => textures[index] } });
        await controller.ready;
        function draw() {
          renderer.render(scene, camera);
          const pixel = new Uint8Array(4); gl.readPixels(32, 32, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
          return Array.from(pixel.slice(0, 3));
        }
        return { controller, mesh, draw, uniforms: () => [mesh.material.uniforms.uCheekTexArrayIndex.value, mesh.material.uniforms.uCheekIntensity.value],
          defined: () => !!mesh.material.defines.SIFAS_CHEEK };
      }
      const out = {};
      // A real exported slice 0 (authored _CHEEK_ON with nonzero intensity in a mod).
      const real = await build('head', { slot: true, authored: .8 });
      out.authored = real.draw();
      real.controller.setCheek('head', null);
      out.reset = { pixel: real.draw(), uniforms: real.uniforms(), defined: real.defined() };
      real.controller.setCheek('head', { index: 0, intensity: .5 });
      out.on = { pixel: real.draw(), uniforms: real.uniforms(), defined: real.defined() };
      real.controller.setCheek('head', { index: 1, intensity: .5 });
      out.otherSlice = { pixel: real.draw(), uniforms: real.uniforms(), defined: real.defined() };
      real.controller.setCheek('head', { index: 1, intensity: .5, enabled: false });
      out.off = { pixel: real.draw(), uniforms: real.uniforms(), defined: real.defined() };
      real.controller.setCheek('head', { index: 0, intensity: .25, enabled: false });
      out.offSlice = { pixel: real.draw(), uniforms: real.uniforms(), defined: real.defined() };
      real.controller.setCheek('other', { index: 0, intensity: 1 });
      out.otherMaterial = { pixel: real.draw(), uniforms: real.uniforms() };
      // A stock head material: no _CHEEK_ON, authored intensity 0, no exported slot.
      const stock = await build('stock', { slot: false, authored: 0 });
      out.stockBase = stock.draw();
      stock.controller.setCheek('stock', { index: 0, intensity: .317 });
      out.stock = { pixel: stock.draw(), uniforms: stock.uniforms(), defined: stock.defined() };
      out.glError = gl.getError();
      return out;
    });
    assert.deepEqual(errors, []);
    const base = [200, 180, 160];
    const tinted = base.map((value, index) => Math.round(value * (1 + ([128, 64, 255][index] / 255 - 1) * .5)));
    const near = (actual, expected, label) => actual.forEach((value, index) =>
      assert(Math.abs(value - expected[index]) <= 2, `${label}: ${actual} vs ${expected}`));
    near(result.reset.pixel, base, 'ResetAll disables the authored cheek');
    assert.deepEqual(result.reset.uniforms, [0, 0]); assert.equal(result.reset.defined, false);
    near(result.on.pixel, tinted, 'ApplyCheek(0, .5) tints with the real slice');
    assert.deepEqual(result.on.uniforms, [0, .5]); assert.equal(result.on.defined, true);
    near(result.otherSlice.pixel, base, 'an unexported slice is never substituted');
    assert.deepEqual(result.otherSlice.uniforms, [1, .5]); assert.equal(result.otherSlice.defined, false);
    near(result.off.pixel, base, 'ApplyEnable(false) hides the cheek');
    assert.deepEqual(result.off.uniforms, [1, .5], 'the last ApplyCheek floats remain on the material');
    near(result.offSlice.pixel, base, 'kept floats never re-enable _CHEEK_ON');
    assert.deepEqual(result.offSlice.uniforms, [0, .25]); assert.equal(result.offSlice.defined, false);
    assert.deepEqual(result.otherMaterial.uniforms, [0, .25], 'another material name is untouched');
    assert.deepEqual(result.stock.pixel, result.stockBase, 'the placeholder never tints a stock head');
    assert.deepEqual(result.stock.uniforms, [0, .317]); assert.equal(result.stock.defined, false);
    assert.equal(result.glError, 0);
    console.log('PASS: head-material cheek reset, ApplyCheek/ApplyEnable, real-slice gate, placeholder never tints');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
