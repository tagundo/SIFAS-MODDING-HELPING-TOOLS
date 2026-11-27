'use strict';

// AS/General/Transparent and AS/Coloring/Transparent variants drawn in real WebGL. Each case
// covers the viewport with one 1x1 texel over a known background; the expected pixel is the
// variant's arithmetic transcribed from its GLES3 fragment program (reference() below) and
// Unity's blend equation (SrcFactor * fragment + DstFactor * target, the fragment clamped to the
// 8-bit target first).
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const BACKGROUND = [0.2, 0.4, 0.6, 1];
const TEXEL = [200, 120, 60, 153];
const TINT = [0.9, 0.7, 0.8, 0.85];
const COLOR = [0.9, 0.8, 0.7, 0.4];
const PALETTE = [180, 90, 240, 200];

// [label, kind, fields]
const CASES = [
  ['transparent additive', 'transparent', { blend: [5, 1] }],
  ['transparent alpha blend', 'transparent', { blend: [5, 10], alphaBlend: true }],
  ['transparent saturate, COLOR (_SATURATE_ON _VERTEX_COLOR_ON)', 'transparent',
    { blend: [5, 10], alphaBlend: true, saturate: true, vertexColor: true }],
  ['transparent saturate, One One', 'transparent', { blend: [1, 1], saturate: true }],
  ['transparent multiply (DstColor Zero, 12030 shadow_02)', 'transparent', { blend: [2, 0] }],
  ['coloring', 'coloring', {}],
  ['coloring COLOR (_VERTEX_COLOR_ON)', 'coloring', { vertexColor: true }],
  ['coloring saturate, COLOR (_SATURATE_ON _VERTEX_COLOR_ON)', 'coloring', { saturate: true, vertexColor: true }],
  ['coloring auto play (_AUTO_PLAY_ON _VERTEX_COLOR_ON, 12001)', 'coloring', { autoPlay: true, vertexColor: true }],
];

const unit = (bytes) => bytes.map(value => value / 255);
const clamp = (value) => Math.min(1, Math.max(0, value));

function factor(mode, source, target) {
  const [r, g, b, a] = source, [dr, dg, db, da] = target;
  switch (mode) {
    case 0: return [0, 0, 0, 0];
    case 1: return [1, 1, 1, 1];
    case 2: return [dr, dg, db, da];
    case 5: return [a, a, a, a];
    case 10: return [1 - a, 1 - a, 1 - a, 1 - a];
    default: throw new Error(`factor ${mode}`);
  }
}

function reference(kind, fields) {
  const texel = unit(TEXEL), color = fields.vertexColor ? COLOR : [1, 1, 1, 1];
  let fragment;
  if (kind === 'transparent') {
    // u_xlat16_0 = tex * _TintColor (* vs_COLOR0); _SATURATE_ON: rgb = (tex.rgb^2)^2 + u_xlat16_0.rgb.
    fragment = texel.map((value, axis) => value * TINT[axis] * color[axis]);
  } else {
    // palette * _TintColor * main (* vs_COLOR0), then the same _SATURATE_ON addition of main.
    const palette = unit(PALETTE);
    fragment = texel.map((value, axis) => palette[axis] * TINT[axis] * value * color[axis]);
  }
  if (fields.saturate) for (let axis = 0; axis < 3; axis++) fragment[axis] += texel[axis] ** 4;
  fragment = fragment.map(clamp);
  const [source, destination] = kind === 'coloring' ? [5, 1] : fields.blend;
  const sf = factor(source, fragment, BACKGROUND), df = factor(destination, fragment, BACKGROUND);
  return fragment.map((value, axis) => clamp(sf[axis] * value + df[axis] * BACKGROUND[axis]));
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    for (const script of ['vendor/three-r128/three.min.js', 'mv-studio-lighting.js', 'mv-studio-stage-material.js',
      'mv-studio-stage-overlay.js', 'mv-studio-stage-coloring.js']) {
      await page.addScriptTag({ path: path.resolve(__dirname, '../webtools/web/static', script) });
    }
    const results = await page.evaluate(async ({ cases, background, texel, tint, color, palette }) => {
      const T = THREE;
      const renderer = new T.WebGLRenderer({ antialias: false, stencil: true });
      renderer.setSize(8, 8);
      const target = new T.WebGLRenderTarget(8, 8, { depthBuffer: true, stencilBuffer: true });
      const camera = new T.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
      camera.position.set(0, 0, 5);
      const pixel = new T.DataTexture(new Uint8Array(texel), 1, 1);
      pixel.needsUpdate = true;
      const paletteBytes = new Uint8Array(256 * 4);
      for (let index = 0; index < 256; index++) paletteBytes.set(palette, index * 4);
      const parser = { getDependency: async (type) => type === 'bufferView' ? paletteBytes.buffer : pixel };
      const out = [];
      for (const [label, kind, fields] of cases) {
        const scene = new T.Scene(), owner = new T.Group();
        const geometry = new T.PlaneGeometry(4, 4);
        const count = geometry.getAttribute('position').count;
        geometry.setAttribute('_stage_color', new T.Float32BufferAttribute(new Array(count).fill(color).flat(), 4));
        geometry.setAttribute('_stage_color_index', new T.Float32BufferAttribute(new Array(count * 2).fill(0.5), 2));
        if (kind === 'transparent') {
          owner.userData.mvStageNode = { active: true, path: 0, binding: 'binding' };
          geometry.userData.mvStageOverlay = { texture: 0, tint, uv: [1, 1, 0, 0], vertexColor: fields.vertexColor === true,
            cull: 0, queue: 3000, world: true, sortCenter: [0, 0, 0], zTest: 8, stencil: [8, 2, 0, 0], ...fields };
        } else {
          geometry.userData.mvStageColoring = { target: label, palette: { bytes: 0, size: [256, 1] }, main: 0,
            shaftTextures: [], tint, speed: 1, shift: 0, cull: 0, queue: 3000, mainUV: [1, 1, 0, 0],
            indexScale: 1, indexOffset: 0, ...fields };
        }
        const mesh = new T.Mesh(geometry, new T.MeshBasicMaterial());
        owner.add(mesh);
        scene.add(owner);
        const controller = kind === 'transparent' ? await MVStudioStageOverlay.apply(T, scene, parser)
          : await MVStudioStageColoring.apply(T, scene, parser);
        if (kind === 'coloring') controller.update(12.5, { tracks: [] }, (seconds) => seconds + 3);
        renderer.setRenderTarget(target);
        renderer.setClearColor(new T.Color(background[0], background[1], background[2]), background[3]);
        renderer.clear(true, true, true);
        renderer.autoClear = false;
        renderer.render(scene, camera);
        const read = new Uint8Array(4);
        renderer.readRenderTargetPixels(target, 4, 4, 1, 1, read);
        out.push({ label, pixel: Array.from(read), material: mesh.material.name, selfTime: mesh.material.uniforms.uSelfTime?.value,
          defines: Object.keys(mesh.material.defines || {}) });
        controller.dispose();
      }
      return out;
    }, { cases: CASES, background: BACKGROUND, texel: TEXEL, tint: TINT, color: COLOR, palette: PALETTE });
    assert.deepEqual(errors, []);
    for (const [index, [label, kind, fields]] of CASES.entries()) {
      const result = results[index];
      assert.notEqual(result.material, 'MeshBasicMaterial', label);
      const expected = reference(kind, fields).map(value => value * 255);
      for (let axis = 0; axis < 3; axis++) {
        assert.ok(Math.abs(result.pixel[axis] - expected[axis]) <= 2,
          `${label}: channel ${axis} ${result.pixel[axis]} vs ${expected[axis].toFixed(2)}`);
      }
      if (kind === 'coloring') {
        // _AUTO_PLAY_ON reads _Time.y (the game clock), the other programs _SelfTime (0 without a track).
        assert.equal(result.selfTime, fields.autoPlay ? 15.5 : 0, label);
      }
    }
    console.log(`${CASES.length} AS/General/Transparent and AS/Coloring/Transparent variants match their GLES3 arithmetic.`);
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
