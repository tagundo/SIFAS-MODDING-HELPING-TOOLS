/* Live AS/Member rim rules in the reconstructed material.

   - CommonCoreMember.Initialize -> LiveCoreMemberRimlight.ApplyIntensity(0):
     a live performer starts with rim intensity 0, so an always-evaluated rim
     term draws exactly what a material without rim draws.
   - ApplyIntensity -> ApplyEnable(final > 0), non-legacy shader:
     _OutlineStencilComp = 3 (Equal) while lit, 8 (Always) otherwise. The MAIN
     pass writes stencil 1 (Replace), so an Equal outline survives only over
     member pixels. */
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
      // GLB textures: 0 main, 1 rim mask, 2/3 cheek array slices 0/1.
      const textures = [image([200, 180, 160, 255]), image([255, 0, 0, 255]), image([128, 64, 255, 255]), image([255, 128, 64, 255])];
      async function build({ live, rimlight = true, backFacing = false, keywords = [], cheek = 'layers', authoredRim = 1 }) {
        const scene = new T.Scene(); scene.background = new T.Color(0x202020);
        const geometry = new T.PlaneBufferGeometry(1, 1);
        geometry.setAttribute('_sifas_color', new T.Float32BufferAttribute(Array(4).fill([1, 1, 1, 1]).flat(), 4));
        const original = new T.MeshBasicMaterial({ map: textures[0] });
        original.name = 'head';
        const floats = { _RimglightIntensity: authoredRim, _RimglightPower: 1, _CullMode: 2, _OutlineStencilComp: 8,
          _CheekIntensity: 0, _CheekTexArrayIndex: 0 };
        const cheekSlot = cheek === 'layers' ? { _CheekTex: { index: 2, arrayLayer: 0, name: 'cheek_array', depth: 2,
          layers: [{ index: 2, arrayLayer: 0, name: 'cheek_array' }, { index: 3, arrayLayer: 1, name: 'cheek_array' }] } } : {};
        original.userData.sifas = { version: 1, shader: 'AS/Member', keywords, limitations: [],
          colors: { _RimlightColor: [0, 1, 0, 1], _RimlightDirection: [0, 0, 0, 0] }, floats,
          features: { rimlight: true, cheek: cheek === 'layers', outline: true },
          textures: { _MainTex: { index: 0 }, _RimlightTex: { index: 1, name: 'head_rim' }, ...cheekSlot } };
        const mesh = new T.Mesh(geometry, original); scene.add(mesh);
        if (backFacing) mesh.rotation.y = Math.PI;
        const controller = SifasMaterial.apply(scene, renderer, { parser: { getDependency: async (_, index) => textures[index] },
          rimlight, liveMember: live });
        await controller.ready;
        const outline = mesh.children.find((child) => child.userData.sifasOutline);
        function draw(x = 32, y = 32) {
          renderer.render(scene, camera);
          const pixel = new Uint8Array(4); gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
          return Array.from(pixel.slice(0, 3));
        }
        return { controller, mesh, draw, uniforms: mesh.material.uniforms,
          stencil: () => [outline.material.stencilFunc, mesh.material.userData.sifasRuntime.outlineStencilComp],
          defined: (name) => !!mesh.material.defines[name] };
      }
      const out = { Equal: T.EqualStencilFunc, Always: T.AlwaysStencilFunc };
      // 1. Live baseline: rim evaluated at intensity 0 == no rim at all.
      const noRim = await build({ live: true, rimlight: false });
      const live = await build({ live: true });
      out.baseline = { rimOff: noRim.draw(), rimZero: live.draw(), intensity: live.uniforms.uRimglightIntensity.value,
        defined: live.defined('SIFAS_RIMLIGHT'), stencil: live.stencil() };
      // Static viewer keeps the authored intensity.
      const authored = await build({ live: false });
      out.authored = { intensity: authored.uniforms.uRimglightIntensity.value, stencil: authored.stencil() };
      // 2. ApplyEnable(final > 0): Equal while lit, Always at 0; the static viewer never changes it.
      // A direction behind the surface makes the rim term 1 at the plane centre.
      const rim = { color: [0, 1, 0, 1], direction: [0, 0, 10, 0], intensity: .5, power: 1 };
      live.controller.setLiveLighting({ rim });
      out.lit = { stencil: live.stencil(), pixel: live.draw() };
      live.controller.setLiveLighting({ rim: { ...rim, intensity: 0 } });
      out.unlit = { stencil: live.stencil(), pixel: live.draw() };
      live.controller.setLiveLighting(null);
      out.noLighting = { stencil: live.stencil(), intensity: live.uniforms.uRimglightIntensity.value };
      authored.controller.setLiveLighting({ rim });
      out.authoredLit = authored.stencil();
      // 3. An outline-only pixel (back-facing plane: MAIN culled, OUTLINE drawn,
      //    no stencil written) is drawn with Always and dropped with Equal.
      const shell = await build({ live: true, backFacing: true });
      shell.controller.setLiveLighting({ rim: { ...rim, intensity: 0 } });
      out.shellAlways = shell.draw();
      shell.controller.setLiveLighting({ rim });
      out.shellEqual = shell.draw();
      out.glError = gl.getError();
      return out;
    });
    assert.deepEqual(errors, []);
    const near = (actual, expected, label, tolerance = 2) => actual.forEach((value, index) =>
      assert(Math.abs(value - expected[index]) <= tolerance, `${label}: ${actual} vs ${expected}`));
    // 1
    assert.deepEqual(result.baseline.rimZero, result.baseline.rimOff, 'rim at intensity 0 draws exactly the unlit surface');
    assert.equal(result.baseline.intensity, 0, 'CommonCoreMember.Initialize -> ApplyIntensity(0)');
    assert.equal(result.baseline.defined, true, 'every AS/Member variant evaluates the rim');
    assert.deepEqual(result.baseline.stencil, [result.Always, 8], 'ApplyEnable(false) at initialization');
    assert.deepEqual(result.authored, { intensity: 1, stencil: [result.Always, 8] }, 'the static viewer keeps authored values');
    // 2
    assert.deepEqual(result.lit.stencil, [result.Equal, 3]);
    assert(result.lit.pixel[1] > result.baseline.rimOff[1] + 20, `lit rim adds green: ${result.lit.pixel}`);
    assert.deepEqual(result.unlit.stencil, [result.Always, 8]);
    assert.deepEqual(result.unlit.pixel, result.baseline.rimOff);
    assert.deepEqual(result.noLighting, { stencil: [result.Always, 8], intensity: 0 });
    assert.deepEqual(result.authoredLit, [result.Always, 8], 'only a live performer runs LiveCoreMemberRimlight');
    // 3: outline color is the main texel * .35 (70, 63, 56) over a 32-grey background.
    near(result.shellAlways, [70, 63, 56], 'Always draws the outline-only pixel', 3);
    near(result.shellEqual, [32, 32, 32], 'Equal drops the outline outside stencil-1 pixels', 1);
    assert.equal(result.glError, 0);
    console.log('PASS: live rim baseline 0, ApplyEnable outline stencil, Equal drops outline-only pixels');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
