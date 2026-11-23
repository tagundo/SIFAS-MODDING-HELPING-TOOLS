'use strict';
/* LiveMvDarkFilterField and the live-end overlay blur (GL 3.12.0): the black filter
   fades from alpha 1 to 0 over 2.0 s from the start, then at the music end to
   alpha 0.5 over 0.25 s while the overlay camera's Gaussian blur spread ramps
   0 -> 4 (_SampleSize = spread / 2); the blur is two 11-tap passes, vertical then
   horizontal, with exp(-(i-5)^2/18) normalized weights. */
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

global.window = {};
require('../webtools/web/static/mv-studio-screen-fade.js');
const fade = window.MVStudioScreenFade;
const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-6, `${message}: ${actual} != ${expected}`);

close(fade.state(0, 100).alpha, 1, 'black at the start');
close(fade.state(.5, 100).alpha, .75, 'linear brightness');
close(fade.state(2, 100).alpha, 0, 'clear after 2.0 s');
assert.equal(fade.state(50, 100).sampleSize, 0);
close(fade.state(100, 100).alpha, .5, 'half dark after the end effect');
close(fade.state(100, 100).sampleSize, 2, 'full spread 4.0');
close(fade.state(100, 100, .125).alpha, .25, 'end fade midpoint');
close(fade.state(100, 100, .125).sampleSize, 1, 'blur ramp midpoint');
close(fade.state(.5, .5, 0).alpha, .75, 'the end fade starts from the current brightness');
close(fade.state(.5, .5, .125).alpha, .625, 'and moves toward 0.5');
assert.equal(fade.state(10, Infinity).alpha, 0);
const kernel = fade.kernel;
assert.equal(kernel.length, 11);
close(kernel.reduce((sum, value) => sum + value, 0), 1, 'normalized kernel');
close(kernel[5] / kernel[0], Math.exp(25 / 18), 'sigma 3 taps');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    for (const script of ['vendor/three-r128/three.min.js', 'mv-studio-screen-fade.js']) {
      await page.addScriptTag({ path: path.resolve(__dirname, '../webtools/web/static', script) });
    }
    const result = await page.evaluate(() => {
      const T = THREE, width = 64, height = 32;
      const renderer = new T.WebGLRenderer({ alpha: false, antialias: true, stencil: true, preserveDrawingBuffer: true });
      renderer.setPixelRatio(1);
      renderer.setSize(width, height);
      const gl = renderer.getContext();
      // One white column and one white row on black, drawn straight into the canvas.
      gl.disable(gl.SCISSOR_TEST);
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.SCISSOR_TEST);
      gl.clearColor(1, 1, 1, 1);
      gl.scissor(30, 0, 1, height); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.scissor(0, 10, width, 1); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.disable(gl.SCISSOR_TEST);
      const screen = MVStudioScreenFade.create(T, renderer);
      screen.draw({ alpha: .5, sampleSize: 2 });
      const pixels = new Uint8Array(width * height * 4);
      gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      const at = (x, y) => pixels[(y * width + x) * 4];
      const row = Array.from({ length: 15 }, (_, i) => at(23 + i, 25));
      const column = Array.from({ length: 15 }, (_, i) => at(50, 3 + i));
      screen.draw({ alpha: 0, sampleSize: 0 });
      const errorCode = gl.getError();
      screen.dispose();
      return { row, column, errorCode, kernel: MVStudioScreenFade.kernel };
    });
    assert.deepEqual(errors, []);
    assert.equal(result.errorCode, 0);
    // A one-texel line blurred with taps 2 texels apart keeps the kernel weight on
    // every other texel, then the filter halves it.
    const expected = offset => (Math.abs(offset) % 2 || Math.abs(offset) > 10 ? 0 : result.kernel[5 + offset / 2]) * 255 * .5;
    result.row.forEach((value, index) => assert.ok(Math.abs(value - expected(index - 7)) <= 2,
      `vertical line, x offset ${index - 7}: ${value} vs ${expected(index - 7)}`));
    result.column.forEach((value, index) => assert.ok(Math.abs(value - expected(index - 7)) <= 2,
      `horizontal line, y offset ${index - 7}: ${value} vs ${expected(index - 7)}`));
    console.log('PASS: MV dark filter fade, live-end blur ramp and the 11-tap separable kernel');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
