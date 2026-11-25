/* AS/MemberProp outline stencil follows the prop rim like a member's.

   - LivePropRimlight inherits LiveCoreMemberRimlight.ApplyEnable (GL 3.12.0
     0x2f6c074): on the current (non-legacy) shader it sets
     _OutlineStencilComp = 3 (Equal) on every material it owns while the final
     rim intensity is above 0, 8 (Always) otherwise.
   - The 12028 GL runtime dump records _OutlineStencilComp 3 on mat_chp0001 at
     every pass (rim intensity 0.1-0.6); the authored value is 8. */
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
    for (const file of ['vendor/three-r128/three.min.js', 'sifas-material.js']) {
      await page.addScriptTag({ path: path.join(root, 'webtools/web/static', file) });
    }
    const result = await page.evaluate(async () => {
      const T = window.THREE;
      const canvas = document.createElement('canvas'); document.body.appendChild(canvas);
      const renderer = new T.WebGLRenderer({ canvas, antialias: false, stencil: true });
      // Complete authored mip chains, as the native MainProp export requires.
      const textures = [];
      function chain(size) {
        const indices = [];
        for (let width = size; width >= 1; width >>= 1) {
          const texture = new T.DataTexture(new Uint8Array(width * width * 4).fill(200), width, width, T.RGBAFormat);
          texture.needsUpdate = true;
          indices.push(textures.length); textures.push(texture);
        }
        return { index: indices[0], mipmaps: indices, filterMode: 1 };
      }
      const main = chain(1024), rim = chain(256);
      function build(intensity) {
        const scene = new T.Scene();
        const geometry = new T.PlaneBufferGeometry(1, 1);
        geometry.setAttribute('_sifas_color', new T.Float32BufferAttribute(Array(4).fill([1, 1, 1, 1]).flat(), 4));
        geometry.setAttribute('_mv_fan_uv', new T.Float32BufferAttribute(Array(4).fill([0, 0]).flat(), 2));
        const original = new T.MeshBasicMaterial();
        original.name = 'mat_chp0001';
        original.userData.sifas = { version: 1, shader: 'AS/MemberProp', pipeline: 'gamma', limitations: [],
          keywords: ['_RIMLIGHT_ON', '_UV2ANGLE_ON'], features: { rimlight: true, outline: true },
          colors: { _RimlightColor: [0, 1, 0, 1], _RimlightDirection: [0, 0, 0, 0] },
          floats: { _CullMode: 2, _OutlineStencilComp: 8, _RimglightIntensity: intensity, _RimglightPower: 1 },
          textures: { _MainTex: main, _RimlightTex: rim } };
        const mesh = new T.Mesh(geometry, original); scene.add(mesh);
        const controller = SifasMaterial.apply(scene, renderer, { memberProp: true, enabled: true, rimlight: true,
          parser: { getDependency: async (_, index) => textures[index] } });
        return controller.ready.then(() => {
          const outline = mesh.children.find((child) => child.userData.sifasOutline);
          return { controller, mesh, stencil: () => [outline.material.stencilFunc, mesh.material.userData.sifasRuntime.outlineStencilComp] };
        });
      }
      const out = { Equal: T.EqualStencilFunc, Always: T.AlwaysStencilFunc };
      const prop = await build(.5);
      out.custom = prop.mesh.material.isShaderMaterial === true && prop.mesh.material.userData.sifas.shader;
      out.authored = prop.stencil();
      const rimLight = { color: [0, 1, 0, 1], direction: [0, 0, 10, 0], power: 1 };
      prop.controller.setLiveLighting({ rim: { ...rimLight, intensity: .3 } });
      out.lit = prop.stencil();
      prop.controller.setLiveLighting({ rim: { ...rimLight, intensity: 0 } });
      out.unlit = prop.stencil();
      // No rim track: the authored intensity (0.5) is the final value.
      prop.controller.setLiveLighting(null);
      out.authoredRim = prop.stencil();
      const dark = await build(0);
      dark.controller.setLiveLighting(null);
      out.authoredZero = dark.stencil();
      return out;
    });
    assert.deepEqual(errors, []);
    assert.equal(result.custom, 'AS/MemberProp');
    // Before any lighting update the authored Always is kept.
    assert.deepEqual(result.authored, [result.Always, 8]);
    assert.deepEqual(result.lit, [result.Equal, 3]);
    assert.deepEqual(result.unlit, [result.Always, 8]);
    assert.deepEqual(result.authoredRim, [result.Equal, 3]);
    assert.deepEqual(result.authoredZero, [result.Always, 8]);
    console.log('AS/MemberProp outline stencil follows ApplyEnable(final rim > 0).');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
