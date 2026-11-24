'use strict';

// Pixel checks of the original-particle billboard shader (mv-studio-particle-systems.js):
//  * Local billboard quads with 3D start rotation cover the quad Unity builds: the
//    negated Z, X, Y start angles in Unity's Euler order inside the emitter frame, in the
//    stage's reflected X. View/World X/Y tilt is refused (unevidenced frame handedness).
//  * A Local scaling mode node scale s multiplies the quad axes component-wise in world
//    space after the roll and 3D turn (libunity.so 0xd2844), so a rolled quad on a 5x3
//    node shears; the max size cap is checked on the unscaled quad against the limit over
//    s.x (0xc35c4): it binds for a 3x1 node and not for a 1x3 one with the same particle.
//  * A particle material with stencil Equal Ref 2 (the display particles) draws only where
//    an earlier queue replaced the stencil with 2 (the display background).

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
    for (const script of ['vendor/three-r128/three.min.js', 'mv-studio-stage-motion.js', 'mv-studio-title.js',
      'mv-studio-stage-particles.js', 'mv-studio-particle-systems.js']) {
      await page.addScriptTag({ path: path.resolve(__dirname, '../webtools/web/static', script) });
    }
    const results = await page.evaluate(async () => {
      const T = THREE, P = MVStudioParticleSystems, size = 160;
      const constant = value => ({ mode: 0, scalar: value, min: value });
      const once = { rate: constant(0), bursts: [{ time: 0, count: constant(1), cycles: 1, interval: 0, probability: 1 }] };
      // AlwaysSimulate culling: Automatic culling would pause a looping tilted or scaled system off screen.
      function system(path, alignment, angles, quad, stencil = [8, 2, 0, 0], maxParticleSize = 10) {
        return {
          path, node: 1, layer: 1,
          main: { duration: 10, looping: true, prewarm: false, startDelay: constant(0), worldSpace: false, scalingMode: 1,
            autoRandomSeed: false, randomSeed: 1, maxParticles: 4, lifetime: constant(10), speed: constant(0),
            size: constant(quad), rotation: constant(angles[2]), color: { mode: 0, max: [1, 1, 1, 1] }, gravity: constant(0),
            size3D: false, rotation3D: true, rotationX: constant(angles[0]), rotationY: constant(angles[1]),
            randomizeRotationDirection: 0, stopAction: 0, cullingMode: 3, simulationSpeed: 1 },
          emission: once, shape: null, velocity: null, clamp: null, size: null, rotation: null, color: null, uv: null,
          rotationBySpeed: null,
          renderer: { mode: 0, alignment, sortMode: 0, sortingFudge: 0, minParticleSize: 0, maxParticleSize, lengthScale: 2,
            velocityScale: 0, cameraVelocityScale: 0, pivot: [0, 0, 0], flip: [0, 0, 0], allowRoll: true },
          material: { name: 'white', queue: 3000, tint: [1, 1, 1, 1], st: [1, 1, 0, 0], vertexColor: true, saturate: false,
            blend: [5, 10], cull: 0, zTest: 8, zWrite: 0, stencil, texture: null },
        };
      }
      const renderer = new T.WebGLRenderer({ alpha: false, antialias: false, stencil: true, preserveDrawingBuffer: true });
      renderer.setSize(size, size);
      renderer.setClearColor(0x000000, 1);
      const camera = new T.PerspectiveCamera(40, 1, .1, 100);
      camera.position.set(1.2, .7, -9);
      camera.lookAt(-.3, .2, 0);
      camera.updateMatrixWorld();

      // Unity space (left-handed, Y up); the stage reflects X into three.js space.
      const multiply = (a, b) => a.map((row, i) => [0, 1, 2].map(j => row[0] * b[0][j] + row[1] * b[1][j] + row[2] * b[2][j]));
      const apply = (m, v) => m.map(row => row[0] * v[0] + row[1] * v[1] + row[2] * v[2]);
      const rx = a => [[1, 0, 0], [0, Math.cos(a), -Math.sin(a)], [0, Math.sin(a), Math.cos(a)]];
      const ry = a => [[Math.cos(a), 0, Math.sin(a)], [0, 1, 0], [-Math.sin(a), 0, Math.cos(a)]];
      const rz = a => [[Math.cos(a), -Math.sin(a), 0], [Math.sin(a), Math.cos(a), 0], [0, 0, 1]];
      // Quaternion.Euler order: Z first, then X, then Y.
      const euler = ([x, y, z]) => multiply(ry(y), multiply(rx(x), rz(z)));
      const quaternionMatrix = ([x, y, z, w]) => [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]];

      // Expected screen corners of Unity's quad: s * (frame * Euler(-x, -y, -z) * (+-w/2, +-h/2, 0)),
      // with the unscaled quad capped at maxParticleSize viewport widths over s.x.
      function expectedCorners(alignment, angles, quad, center, emitter, scale, maxParticleSize) {
        const turn = euler(angles.map(value => -value));
        const view = new T.Matrix3().setFromMatrix4(camera.matrixWorldInverse);
        const centerThree = new T.Vector3(-center[0], center[1], center[2]);
        const depth = -centerThree.clone().applyMatrix4(camera.matrixWorldInverse).z;
        const limit = maxParticleSize * 2 * depth / Math.abs(camera.projectionMatrix.elements[0]) / Math.max(scale[0], 1e-5);
        const cap = Math.min(1, limit / Math.max(quad[0], quad[1]));
        // Unity scales world components; reflecting X commutes with that.
        const grown = vector => new T.Vector3(vector.x * scale[0], vector.y * scale[1], vector.z * scale[2]);
        return [[-.5, -.5], [.5, -.5], [.5, .5], [-.5, .5]].map(([u, v]) => {
          const local = apply(turn, [u * quad[0] * cap, v * quad[1] * cap, 0]);
          let offset;
          if (alignment === 0) {
            // An untilted View quad spans the camera's right and up in world space.
            if (angles[0] || angles[1]) throw new Error('View X/Y tilt has no evidenced frame');
            const right = new T.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
            const up = new T.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
            offset = grown(right.multiplyScalar(local[0]).add(up.multiplyScalar(local[1]))).applyMatrix3(view);
          } else {
            const world = alignment === 2 ? apply(quaternionMatrix(emitter), local) : local;
            offset = grown(new T.Vector3(-world[0], world[1], world[2])).applyMatrix3(view);
          }
          const point = centerThree.clone().applyMatrix4(camera.matrixWorldInverse).add(offset).applyMatrix4(camera.projectionMatrix);
          return [(point.x * .5 + .5) * size, (.5 - point.y * .5) * size];
        });
      }

      // Rows covered at a pixel column (the quad edges are straight lines).
      function coverage(pixels) {
        let left = size, right = -1, top = size, bottom = -1;
        const height = column => { let n = 0; for (let y = 0; y < size; y++) n += pixels[((size - 1 - y) * size + column) * 4] > 127; return n; };
        for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
          if (pixels[((size - 1 - y) * size + x) * 4] <= 127) continue;
          left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
        }
        return { left, right, top, bottom, leftHeight: height(left + 2), rightHeight: height(right - 2) };
      }
      function predicted(corners, measured) {
        const xs = corners.map(c => c[0]), ys = corners.map(c => c[1]);
        // Edge height at the pixel centers coverage() measured, from the quad's four edges.
        const at = x => {
          const hits = [];
          for (let i = 0; i < 4; i++) {
            const [a, b] = [corners[i], corners[(i + 1) % 4]];
            if ((a[0] - x) * (b[0] - x) <= 0 && a[0] !== b[0]) hits.push(a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]));
          }
          return hits.length >= 2 ? Math.max(...hits) - Math.min(...hits) : 0;
        };
        const left = Math.min(...xs), right = Math.max(...xs);
        return { left, right, top: Math.min(...ys), bottom: Math.max(...ys), leftHeight: at(measured.left + 2.5),
          rightHeight: at(measured.right - 1.5) };
      }

      async function draw(row, nodeScale, emitter, extra) {
        const scene = new T.Scene(), root = new T.Group();
        scene.add(root);
        if (extra) scene.add(extra);
        const nodes = [{ parent: null, path: 'fx', layer: 1, position: [0, 0, 0], rotation: [0, 0, 0, 1], scale: [1, 1, 1] },
          { parent: 0, path: 'fx/' + row.path, layer: 1, position: [.4, -.2, .5], rotation: emitter, scale: nodeScale }];
        const descriptor = { schema: 1, textures: [], templates: [{ name: 'fx', nodes, systems: [row] }],
          cues: [{ trackId: 't', eventId: 't:0', template: 0, offset: [0, 0, 0], quality: 'stage_display', clipSeed: 1 }] };
        const controller = await P.apply(T, root, descriptor);
        if (!controller) throw new Error('descriptor refused: ' + row.path);
        controller.update(1, { tracks: [{ id: 't', events: [{ id: 't:0', start: .5, duration: 5 }] }],
          quality: { values: { stage_display: true } } });
        renderer.clear(true, true, true);
        renderer.render(scene, camera);
        const pixels = new Uint8Array(size * size * 4);
        const gl = renderer.getContext();
        gl.readPixels(0, 0, size, size, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        controller.dispose();
        return pixels;
      }

      const emitter = [.1, Math.sin(.6), -.05, Math.cos(.6)];
      const norm = Math.hypot(...emitter);
      const unitEmitter = emitter.map(value => value / norm);
      const cases = [
        // fx_dis_par_so2035_02 main display cloud: View, 1 unit on a 5x3 node (rolled 0.3 rad here,
        // so the scaled axes shear the rolled quad).
        { name: 'view-scaled', alignment: 0, angles: [0, 0, .3], quad: 1, scale: [5, 3, 1] },
        // fx_par_so2035_04 light_02: Local, 5 degrees on Y, on a 1.1x1.1 node.
        { name: 'local-y', alignment: 2, angles: [0, .0872664600610733, 0], quad: 3, scale: [1.1, 1.1, 1] },
        { name: 'local-xyz', alignment: 2, angles: [.45, .8, -.35], quad: 2.5, scale: [1, 1, 1] },
        // A rolled Local quad on a non-uniform node: scaled after the roll, in world components.
        { name: 'local-rolled-scaled', alignment: 2, angles: [0, 0, .5], quad: 1, scale: [2.5, 1, 1] },
        // fx_dis_so2025_01 glow_under_p's cap: one unit capped at 0.2 viewport widths (about 1.4 units
        // here). On a 3x1 node the cap sees 3 units and binds; on a 1x3 node it sees 1 unit and does not.
        { name: 'cap-x', alignment: 2, angles: [0, 0, 0], quad: 1, scale: [3, 1, 1], maxParticleSize: .2 },
        { name: 'cap-y', alignment: 2, angles: [0, 0, 0], quad: 1, scale: [1, 3, 1], maxParticleSize: .2 },
      ];
      const report = [];
      // View and World X/Y tilt are refused by the runtime.
      for (const alignment of [0, 1]) {
        if (P.validSimulation(system('refused', alignment, [0, .35, 0], 1))) throw new Error(`alignment ${alignment} tilt drawn`);
      }
      for (const item of cases) {
        const maxParticleSize = item.maxParticleSize ?? 10;
        const pixels = await draw(system(item.name, item.alignment, item.angles, item.quad, undefined, maxParticleSize),
          item.scale, unitEmitter);
        const got = coverage(pixels);
        const want = predicted(expectedCorners(item.alignment, item.angles, [item.quad, item.quad], [.4, -.2, .5], unitEmitter,
          item.scale, maxParticleSize), got);
        report.push({ name: item.name, got, want });
        for (const key of ['left', 'right', 'top', 'bottom']) {
          if (Math.abs(got[key] + .5 - want[key]) > 2.5) throw new Error(`${item.name} ${key}: ${got[key]} vs ${want[key].toFixed(2)}`);
        }
        for (const key of ['leftHeight', 'rightHeight']) {
          if (Math.abs(got[key] - want[key]) > 2) throw new Error(`${item.name} ${key}: ${got[key]} vs ${want[key].toFixed(2)}`);
        }
      }

      // Stencil Equal Ref 2: only where an opaque background replaced the stencil with 2.
      const writer = new T.Mesh(new T.PlaneGeometry(40, 40), new T.MeshBasicMaterial({ color: 0x000000,
        stencilWrite: true, stencilRef: 2, stencilFunc: T.AlwaysStencilFunc, stencilZPass: T.ReplaceStencilOp,
        stencilZFail: T.ReplaceStencilOp, depthWrite: false }));
      writer.renderOrder = 2000;
      // The background covers screen-left of the particle only (three.js +X is screen-left here).
      writer.position.set(20, 0, 2);
      writer.rotation.y = Math.PI;
      const masked = await draw(system('masked', 0, [0, 0, 0], 3, [3, 2, 0, 0]), [1, 1, 1], [0, 0, 0, 1], writer);
      const open = await draw(system('open', 0, [0, 0, 0], 3), [1, 1, 1], [0, 0, 0, 1]);
      const maskedBox = coverage(masked), openBox = coverage(open);
      // The mask edge (x = 0 at z = 2) across the particle's rows.
      const edge = [-2, -1, 0, 1, 2].map(y => (new T.Vector3(0, y, 2).project(camera).x * .5 + .5) * size);
      const split = [Math.min(...edge), Math.max(...edge)];
      report.push({ name: 'stencil', maskedBox, openBox, split });
      if (!(openBox.right > split[1] + 5 && openBox.left < split[0] - 5)) throw new Error('the particle must straddle the mask edge');
      if (!(maskedBox.left === openBox.left && maskedBox.right >= split[0] - 1.5 && maskedBox.right <= split[1] + 1.5)) {
        throw new Error(`stencil Equal 2 drew ${JSON.stringify(maskedBox)} (mask edge ${split})`);
      }
      renderer.dispose();
      return report;
    });
    assert.deepEqual(errors, []);
    console.log('MV Studio original particle billboards: tilt, Local scale, size cap and stencil passed',
      JSON.stringify(results.map(row => row.name)));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
