'use strict';

// Renders the stage display screen programs on sample texels (WebGL2, float target) and compares
// every pixel with the original GLES3 programs transcribed below from the shader bundles:
// AS/General/Opaque (_VERTEX_COLOR_ON) and AS/General/Transparent (_SATURATE_ON _VERTEX_COLOR_ON).
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
    for (const script of ['vendor/three-r128/three.min.js', 'viewer-motion-timeline.js', 'mv-studio-lighting.js',
      'mv-studio-stage-display.js']) {
      await page.addScriptTag({ path: path.resolve(__dirname, '../webtools/web/static', script) });
    }
    const results = await page.evaluate(async () => {
      const T = THREE, W = 4, H = 2;
      const renderer = new T.WebGLRenderer({ stencil: true });
      if (!renderer.capabilities.isWebGL2 || !renderer.extensions.get('EXT_color_buffer_float')) throw new Error('float target');
      const target = new T.WebGLRenderTarget(W, H, { type: T.FloatType, format: T.RGBAFormat,
        minFilter: T.NearestFilter, magFilter: T.NearestFilter });
      const camera = new T.OrthographicCamera(-1, 1, 1, -1, -1, 1);
      // Sample texels, rows bottom (t = 0) to top; RGBA bytes.
      const images = {
        1: [[200, 40, 90, 255], [10, 250, 30, 128], [120, 120, 0, 64], [0, 0, 255, 255],
          [255, 255, 255, 200], [60, 20, 180, 255], [5, 5, 5, 255], [90, 160, 220, 30]],
        2: [[0, 0, 0, 255], [1, 0, 0, 255], [0, 200, 100, 255], [250, 10, 10, 0]],
        3: [[255, 128, 0, 255], [0, 64, 255, 128], [32, 32, 32, 255], [200, 200, 255, 16],
          [10, 220, 90, 200], [128, 0, 64, 255], [255, 255, 0, 96], [0, 0, 0, 255]]
      };
      const sizes = { 1: [4, 2], 2: [2, 2], 3: [4, 2] };
      const texels = {};
      const textures = new Map(Object.entries(images).map(([index, rows]) => {
        const [w, h] = sizes[index];
        const data = new Uint8Array(rows.flat());
        texels[index] = { w, h, data };
        const texture = new T.DataTexture(data, w, h);
        texture.wrapS = texture.wrapT = T.RepeatWrapping;
        texture.needsUpdate = true;
        return [Number(index), texture];
      }));
      const parser = { getDependency: (_, index) => Promise.resolve(textures.get(index)) };
      const color = [.5, .75, 1, .5];
      function fetch(index, s, t) {
        if (index === null) return [1, 1, 1, 1];
        const { w, h, data } = texels[index];
        const fract = (value) => value - Math.floor(value);
        const x = Math.min(w - 1, Math.floor(fract(s) * w)), y = Math.min(h - 1, Math.floor(fract(t) * h));
        return Array.from(data.slice((y * w + x) * 4, (y * w + x) * 4 + 4), (value) => value / 255);
      }
      // A Unity texture coordinate (uv * scale + offset, V up) sampled from the V-flipped glTF texture.
      const unity = ([u, v], [sx, sy, ox, oy]) => [u * sx + ox, 1 - ((1 - v) * sy + oy)];
      const add = (a, b) => a.map((value, i) => value + b[i]);
      const mul = (a, b) => a.map((value, i) => value * b[i]);
      const scale = (a, k) => a.map((value) => value * k);
      // --- the original GLES3 fragment programs ---
      const original = {
        general(f, at) {  // AS/General/Opaque, _VERTEX_COLOR_ON
          let t = fetch(f.texture, ...unity(at, f.uv));
          const lerp = add(mul(scale(t.slice(0, 3), -1), color), f.ambient.slice(0, 3));
          t = mul(t, color);
          const rgb = add(scale(lerp, f.ambient[3]), t.slice(0, 3));
          return mul([...rgb, t[3]], f.tint);
        },
        transparent(f, at) {  // AS/General/Transparent, _SATURATE_ON _VERTEX_COLOR_ON
          let t = fetch(f.texture, ...unity(at, f.uv));
          const square = mul(t, t).slice(0, 3);
          t = mul(mul(t, f.tint), color);
          return [...add(mul(square, square), t.slice(0, 3)), t[3]];
        },
      };
      const stencil = { stencil: 2, stencilComp: 8, stencilPass: 2, stencilZFail: 0, queue: 2000 };
      const cases = [
        { name: 'general', kind: 'general', fields: { kind: 'general', texture: 1, uv: [2, 1, .25, .5], cull: 0,
          tint: [.9, 1.25, .5, .75], ambient: [.2, .4, .6, .35], vertexColor: true, ...stencil } },
        { name: 'transparent', kind: 'transparent', fields: { kind: 'transparent', texture: 1, uv: [1, 2, 0, .25], cull: 0,
          tint: [1.5, .5, 1, .8], blend: [1, 0], zTest: 8, zWrite: false, saturate: true, vertexColor: true,
          ...stencil, stencilPass: 0, queue: 3000 } }
      ];
      const out = [];
      for (const test of cases) {
        const scene = new T.Scene();
        const geometry = new T.PlaneGeometry(2, 2);
        geometry.setAttribute('_stage_color', new T.Float32BufferAttribute(Array(4).fill(color).flat(), 4));
        geometry.userData.mvStageDisplay = { target: 'screen', fallback: test.fields, initial: { unsupported: 'test' },
          variants: [{ background: test.fields, logo: null }] };
        const mesh = new T.Mesh(geometry, new T.MeshBasicMaterial());
        mesh.frustumCulled = false;
        scene.add(mesh);
        const controller = await MVStudioStageDisplay.apply(T, scene, parser);
        // No LiveDisplayTrack and a disabled display: material2DReference with its authored values.
        controller.update(0, { tracks: [], quality: { values: { stage_display: false } } },
          test.time === undefined ? null : () => test.time);
        renderer.setRenderTarget(target);
        renderer.setClearColor(0x000000, 0);
        renderer.clear();
        renderer.render(scene, camera);
        const pixels = new Float32Array(W * H * 4);
        renderer.readRenderTargetPixels(target, 0, 0, W, H, pixels);
        let worst = 0;
        for (let y = 0; y < H; y++) {
          for (let x = 0; x < W; x++) {
            const at = [(x + .5) / W, (y + .5) / H];
            const expected = original[test.kind](test.fields, at, test.kind === 'waveTexture' ? test.time : test.feed);
            const got = pixels.slice((y * W + x) * 4, (y * W + x) * 4 + 4);
            for (let i = 0; i < 4; i++) worst = Math.max(worst, Math.abs(got[i] - expected[i]));
          }
        }
        out.push({ name: test.name, worst, sample: Array.from(pixels.slice(0, 4)) });
        controller.dispose();
      }
      renderer.setRenderTarget(null);
      return out;
    });
    assert.deepEqual(errors, []);
    for (const result of results) {
      assert.ok(result.worst < 2e-4, `${result.name}: worst channel difference ${result.worst}`);
    }
    console.log('Stage display programs match the original GLES3 math:',
      results.map((result) => `${result.name} ${result.worst.toExponential(1)}`).join(', '));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
