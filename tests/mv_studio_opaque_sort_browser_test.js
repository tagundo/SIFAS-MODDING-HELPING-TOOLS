'use strict';

// Real WebGL depth ties: two stage renderers with the same vertices (10120's
// AS/Blend/Opaque sky dome over the stage's AS/General/Opaque sky submesh)
// produce bit-identical depths through MVStudioStageMaterial's one vertex
// shader, so ZTest LEqual lets the later draw win on every pixel, and
// MVStudioOpaqueSort decides which draws later as Unity does: front to back
// by renderer bounds centre.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    for (const script of ['vendor/three-r128/three.min.js', 'mv-studio-lighting.js', 'mv-studio-stage-material.js',
      'mv-studio-opaque-sort.js']) {
      await page.addScriptTag({ path: path.resolve(__dirname, '../webtools/web/static', script) });
    }
    const result = await page.evaluate(async () => {
      const T = THREE;
      const renderer = new T.WebGLRenderer({ alpha: false, antialias: false, stencil: true });
      const width = 96, height = 64;
      renderer.setSize(width, height);
      const target = new T.WebGLRenderTarget(width, height);
      const solid = (rgb) => {
        const texture = new T.DataTexture(new Uint8Array([...rgb, 255]), 1, 1);
        texture.needsUpdate = true;
        return texture;
      };
      const red = solid([255, 0, 0]), blue = solid([0, 0, 255]), green = solid([0, 255, 0]);
      // A tilted, subdivided sheet: its depth changes across every pixel.
      const sheet = new T.PlaneGeometry(40, 40, 24, 24);
      sheet.rotateX(-1.1);
      sheet.rotateY(.35);
      sheet.translate(.37, 2.13, -12.71);
      const positions = sheet.getAttribute('position').array;
      const count = positions.length / 3;
      function geometry(meta, color) {
        const copy = new T.BufferGeometry();
        copy.setAttribute('position', new T.BufferAttribute(new Float32Array(positions), 3));
        copy.setAttribute('normal', sheet.getAttribute('normal').clone());
        copy.setAttribute('uv', sheet.getAttribute('uv').clone());
        copy.setIndex(sheet.getIndex().clone());
        if (color) copy.setAttribute('_stage_color', new T.Float32BufferAttribute(new Array(count).fill([1, 1, 1, 0]).flat(), 4));
        copy.userData.mvStageMaterial = meta;
        return copy;
      }
      const scene = new T.Scene(), stage = new T.Group(), effects = new T.Group();
      scene.add(stage, effects);
      const general = { shader: 'general', colors: { _AmbientColor: [1, 1, 1, 0], _TintColor: [1, 1, 1, 1] }, cull: 0,
        uvTransform: [1, 1, 0, 0], vertexColor: false, opaqueSort: { queue: 2000, center: [0, 39.1, -.36] } };
      const blend = { shader: 'blend', colors: { _AmbientColor: [1, 1, 1, 0], _TintColor: [1, 1, 1, 1] }, cull: 0,
        blendRate: 0, uvTransform: [1, 1, 0, 0], blendUVTransform: [1, 1, 0, 0], vertexColor: true,
        mainTexture: 0, blendTexture: 1, opaqueSort: { queue: 2000, center: [0, 40.3, -1.6] } };
      const stageRoot = new T.Group();
      const stageSky = new T.Mesh(geometry(general, false), new T.MeshBasicMaterial({ map: red }));
      stageRoot.add(stageSky);
      stage.add(stageRoot);
      // The effect GLB keeps the dome under its animated prefab nodes (identity TRS).
      const effectRoot = new T.Group(), prefab = new T.Group(), sky01 = new T.Group();
      prefab.quaternion.set(-0, 0, 0, 1);
      sky01.position.set(-0, 0, 0);
      sky01.userData.mvStageNode = { active: true, binding: 'binding', path: 769206466 };
      effectRoot.add(prefab);
      prefab.add(sky01);
      const dome = new T.Mesh(geometry(blend, true), new T.MeshBasicMaterial());
      sky01.add(dome);
      effects.add(effectRoot);
      const parser = { getDependency: async (_, index) => [blue, green][index] };
      // The dome's material is made first, so three.js alone would draw it first and lose every tie.
      const effectRecord = { stageMaterial: await MVStudioStageMaterial.apply(T, effectRoot, parser) };
      const stageRecord = { stageMaterial: await MVStudioStageMaterial.apply(T, stageRoot, parser) };
      const records = [stageRecord, effectRecord];
      const sorter = MVStudioOpaqueSort.create(T, renderer);
      const camera = new T.PerspectiveCamera(48, width / height, .1, 1000);
      camera.position.set(.3, 1.4, 6);
      camera.lookAt(0, 3, -12);
      const pixels = new Uint8Array(width * height * 4);
      function draw(sorted) {
        renderer.setRenderTarget(target);
        renderer.setClearColor(0x000000, 1);
        const sorting = sorted && sorter.begin(scene, camera, records);
        try { renderer.render(scene, camera); } finally { if (sorting) sorter.end(); }
        renderer.readRenderTargetPixels(target, 0, 0, width, height, pixels);
        renderer.setRenderTarget(null);
        const counts = { red: 0, blue: 0, green: 0, other: 0, clear: 0 };
        for (let i = 0; i < pixels.length; i += 4) {
          const [r, g, b] = pixels.subarray(i, i + 3);
          if (r === 0 && g === 0 && b === 0) counts.clear++;
          else if (r === 255 && g === 0 && b === 0) counts.red++;
          else if (r === 0 && g === 0 && b === 255) counts.blue++;
          else if (r === 0 && g === 255 && b === 0) counts.green++;
          else counts.other++;
        }
        return { ...counts, sorting: Boolean(sorting) };
      }
      const outcomes = {};
      // Three.js alone: its program and material order decides, still without a mixed pixel.
      outcomes.three = draw(false);
      outcomes.native = draw(true);
      // A crane above both centres reaches the dome's bounds first: the stage sky wins.
      camera.position.set(.3, 60, 6);
      camera.lookAt(0, 3, -12);
      outcomes.crane = draw(true);
      camera.position.set(.3, 1.4, 6);
      camera.lookAt(0, 3, -12);
      // The night map once _BlendRate reaches 1.
      MVStudioStageMaterial.materialChannel(sky01, 'overlayScalar', '_BlendRate').value = 1;
      outcomes.night = draw(true);
      return outcomes;
    });
    assert.deepEqual(errors, []);
    const covered = result.native.red + result.native.blue;
    assert.ok(covered > 3000, `the sheets cover the view (${JSON.stringify(result)})`);
    for (const [name, counts] of Object.entries(result)) {
      assert.equal(counts.other, 0, `${name}: no blended or partial pixel`);
      assert.equal([counts.red, counts.blue, counts.green].filter(Boolean).length, 1,
        `${name}: one surface wins every pixel (${JSON.stringify(counts)})`);
    }
    assert.deepEqual([result.native.blue, result.native.red, result.native.sorting], [covered, 0, true],
      'the dome draws after the nearer stage bounds and wins every equal-depth pixel');
    assert.deepEqual([result.three.red, result.three.blue], [covered, 0], 'three.js alone draws the dome first');
    assert.ok(result.crane.red > 1000 && result.crane.blue === 0, 'from above the stage sky draws last');
    assert.equal(result.night.green, covered, 'the night map replaces the day map');
    console.log(`Opaque depth ties: the later stage renderer wins all ${covered} pixels.`);
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
