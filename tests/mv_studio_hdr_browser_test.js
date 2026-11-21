'use strict';

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
    for (const script of ['vendor/three-r128/three.min.js', 'viewer-motion-timeline.js', 'mv-studio-lighting.js',
      'mv-studio-hdr.js', 'mv-studio-post.js']) {
      await page.addScriptTag({ path: path.resolve(__dirname, '../webtools/web/static', script) });
    }
    const results = await page.evaluate(() => {
      const T = THREE;
      function check(condition, message) { if (!condition) throw new Error(message); }
      function run(mode) {
        const renderer = new T.WebGLRenderer({ alpha: false, antialias: mode !== 'single', stencil: true });
        renderer.setSize(64, 36);
        const gl = renderer.getContext();
        const samples = gl.getParameter(gl.SAMPLES);
        check((samples > 0) === (mode !== 'single'), 'default multisample count');
        check(gl.getExtension('EXT_color_buffer_float'), 'packed color extension');
        const fallback = mode.endsWith('fallback');
        const extension = gl.getExtension.bind(gl);
        if (mode === 'fallback') {
          gl.getExtension = name => name === 'EXT_color_buffer_float' ? null : extension(name);
        }
        const originalImage = gl.texImage2D.bind(gl);
        let packedImages = 0, rejectReduced = false;
        gl.texImage2D = (...args) => {
          if (args[2] === gl.R11F_G11F_B10F) {
            packedImages++;
            rejectReduced = mode === 'attachment-fallback' && args[4] === 420;
          }
          return originalImage(...args);
        };
        const attachmentParameter = gl.getFramebufferAttachmentParameter.bind(gl);
        gl.getFramebufferAttachmentParameter = (framebuffer, attachment, key) => {
          if (rejectReduced && key === gl.FRAMEBUFFER_ATTACHMENT_COMPONENT_TYPE) {
            rejectReduced = false;
            return gl.UNSIGNED_NORMALIZED;
          }
          return attachmentParameter(framebuffer, attachment, key);
        };
        function attachment(framebuffer, key, which = gl.COLOR_ATTACHMENT0) {
          return gl.getFramebufferAttachmentParameter(framebuffer, which, key);
        }
        const expectedColor = fallback ? [gl.UNSIGNED_NORMALIZED, 8, 8, 8, 8] : [gl.FLOAT, 11, 11, 10, 0];
        function checkColor(framebuffer) {
          const keys = [gl.FRAMEBUFFER_ATTACHMENT_COMPONENT_TYPE, gl.FRAMEBUFFER_ATTACHMENT_RED_SIZE,
            gl.FRAMEBUFFER_ATTACHMENT_GREEN_SIZE, gl.FRAMEBUFFER_ATTACHMENT_BLUE_SIZE, gl.FRAMEBUFFER_ATTACHMENT_ALPHA_SIZE];
          check(keys.every((key, i) => attachment(framebuffer, key) === expectedColor[i]), 'exact scene color attachment');
        }
        function checkDepth(framebuffer) {
          check(attachment(framebuffer, gl.FRAMEBUFFER_ATTACHMENT_DEPTH_SIZE, gl.DEPTH_ATTACHMENT) === 24 &&
            attachment(framebuffer, gl.FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, gl.STENCIL_ATTACHMENT) === 8,
          'exact stage depth/stencil attachment');
        }
        const scene = new T.Scene(), camera = new T.Camera();
        const geometry = new T.PlaneGeometry(2, 2);
        const vertexShader = 'attribute vec3 position; attribute vec2 uv; varying vec2 at; ' +
          'void main(){ at=uv; gl_Position=vec4(position.xy,.2,1.); }';
        const color = new T.RawShaderMaterial({ vertexShader, fragmentShader: 'precision highp float; ' +
          'void main(){ gl_FragColor=vec4(1.375,1.25,2.,1.); }' });
        const probe = new T.RawShaderMaterial({ vertexShader, fragmentShader: 'precision highp float; varying vec2 at; ' +
          'uniform sampler2D sceneColor; uniform sampler2D sceneDepth;' +
          'void main(){ gl_FragColor=vec4(texture2D(sceneColor,at).rgb*.25,texture2D(sceneDepth,at).r); }',
          uniforms: { sceneColor: { value: null }, sceneDepth: { value: null } } });
        const mesh = new T.Mesh(geometry, color);
        mesh.frustumCulled = false;
        scene.add(mesh);
        const pixelTarget = new T.WebGLRenderTarget(8, 8);
        const post = MVStudioPost.create(T, renderer);
        post.evaluate({ quality: { values: { posteffect: true } }, tracks: [{ nativeClass: 'LiveBloomTrack',
          binding: '/EntryPoint/Live/Cameras/MainCamera', events: [{ start: 0, duration: 2,
            values: { playableClass: 'LiveBloomClip', intensity: .25, threshold: 1, softKnee: .3, radius: 4 } }] }] }, 1);
        let reduced = 0;
        const render = renderer.render.bind(renderer);
        renderer.render = (currentScene, currentCamera) => {
          if (renderer.getRenderTarget()?.height === 420) {
            checkColor(gl.DRAW_FRAMEBUFFER);
            reduced++;
          }
          render(currentScene, currentCamera);
        };
        function draw(needsDepth) {
          let source;
          renderer.autoClear = false;
          renderer.setRenderTarget(null);
          check(post.draw(target => {
            source = target;
            checkColor(gl.DRAW_FRAMEBUFFER);
            mesh.material = color;
            renderer.render(scene, camera);
          }, needsDepth), 'Bloom draw succeeds');
          check(renderer.getRenderTarget() === null && !renderer.autoClear, 'previous render state restored');
          if (needsDepth) {
            check(source.depthTexture?.isDepthTexture, 'sampleable scene depth');
            renderer.setRenderTarget(source);
            if (samples) checkDepth(gl.DRAW_FRAMEBUFFER);
            const previousRead = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING);
            const resolved = renderer.properties.get(source).__webglFramebuffer;
            gl.bindFramebuffer(gl.READ_FRAMEBUFFER, resolved);
            try {
              checkColor(gl.READ_FRAMEBUFFER);
              checkDepth(gl.READ_FRAMEBUFFER);
            } finally {
              gl.bindFramebuffer(gl.READ_FRAMEBUFFER, previousRead);
            }
            probe.uniforms.sceneColor.value = source.texture;
            probe.uniforms.sceneDepth.value = source.depthTexture;
            mesh.material = probe;
            renderer.setRenderTarget(pixelTarget);
            renderer.clear();
            renderer.render(scene, camera);
            const pixel = new Uint8Array(4);
            renderer.readRenderTargetPixels(pixelTarget, 4, 4, 1, 1, pixel);
            const expected = fallback ? [64, 64, 64, 153] : [88, 80, 128, 153];
            check(expected.every((value, index) => Math.abs(value - pixel[index]) <= 1), 'resolved HDR and depth: ' + pixel);
          }
          check(gl.getError() === gl.NO_ERROR, 'no GL error after color/depth resolve');
        }
        draw(false);
        draw(true);
        draw(true);
        renderer.setSize(80, 48);
        draw(true);
        check(reduced === 4, 'all authored draws include packed reduction');
        check(packedImages === ({ fallback: 0, 'attachment-fallback': 2 }[mode] ?? 5),
          'one packed allocation per new color handle');
        renderer.setRenderTarget(null);
        post.dispose();
        pixelTarget.dispose();
        geometry.dispose();
        color.dispose();
        probe.dispose();
        check(renderer.info.memory.textures === 0, 'all scene and Bloom textures released by Three');
        renderer.dispose();
        return { mode, samples, packedImages };
      }
      return ['single', 'multi', 'fallback', 'attachment-fallback'].map(run);
    });
    assert.deepEqual(errors, []);
    console.log('MV Studio packed HDR, ARGB32 fallback, resize and depth resolve passed', results);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
