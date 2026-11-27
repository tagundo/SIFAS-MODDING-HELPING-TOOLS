'use strict';

// MVStudioStageMaterial against the AS/Stage GLES3 variants, drawn in real
// WebGL. Each case is a lightmapped floor under a camera, with 1x1 sample
// texels and one colour per cube face; the expected colour of every sampled
// pixel is the variant's arithmetic transcribed from its compiled fragment
// program (see reference() below), in Unity's axes (the editor mirrors X).
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const CASES = [
  // [label, descriptor fields, reflection variant or null]
  ['cube off', {}, null],
  ['fragment, parallax, alpha blend, COLOR.a (12035/3 floor family)', {},
    { mode: 'fragment', parallax: true, op: 'alpha-blend', reflectivity: 'vertex', fresnel: false }],
  ['fragment, no parallax, alpha blend, COLOR.a (12035/1 bg0007_02_stageA_opa_ref_mt)', {},
    { mode: 'fragment', parallax: false, op: 'alpha-blend', reflectivity: 'vertex', fresnel: false }],
  ['fragment, parallax, alpha blend, _MainTex.a (12035/2 bg0008_01_stageA_opa_ref_mt)', {},
    { mode: 'fragment', parallax: true, op: 'alpha-blend', reflectivity: 'texture', fresnel: false }],
  ['fragment, parallax, alpha blend, multiply (11054/3 bg0022_01_floorA_opa_ref_mt)', {},
    { mode: 'fragment', parallax: true, op: 'alpha-blend', reflectivity: 'multiply', fresnel: false }],
  ['fragment, parallax, add, _MainTex.a (12023/3 bg0025_01_stageA_opa_ref_mt)', {},
    { mode: 'fragment', parallax: true, op: 'add', reflectivity: 'texture', fresnel: false }],
  ['fragment, parallax, fresnel, emissive (10001/3 bg0001_01_stageB1_opa_emi_ref_mt)', { emissive: true },
    { mode: 'fragment', parallax: true, op: 'alpha-blend', reflectivity: 'vertex', fresnel: true }],
  ['fragment, no parallax, add, fresnel', {},
    { mode: 'fragment', parallax: false, op: 'add', reflectivity: 'texture', fresnel: true }],
  ['vertex, parallax, add, COLOR.a (10120/3 bg0018_01_stageB_opa_ref_mt)', {},
    { mode: 'vertex', parallax: true, op: 'add', reflectivity: 'vertex', fresnel: false }],
  ['vertex, parallax, alpha blend, fresnel, emissive (11078/3 bg0024_01_stageA1_opa_emi_ref_mt)', { emissive: true },
    { mode: 'vertex', parallax: true, op: 'alpha-blend', reflectivity: 'vertex', fresnel: true }],
  ['vertex, no parallax, alpha blend, emissive', { emissive: true },
    { mode: 'vertex', parallax: false, op: 'alpha-blend', reflectivity: 'multiply', fresnel: false }],
  // _BlendMode transparent materials: the pass blends by the alpha _ALPHA_TRANSPARENCY selects.
  ['Blend SrcAlpha OneMinusSrcAlpha, ZWrite Off (10006/3 bg0004_01_stageB_cut_mt)',
    { blend: [5, 10], depthWrite: false }, null],
  ['_ALPHA_TRANSPARENCY_MULTIPLY in queue 3000 (10022/3 bg0007_04_plantsA_tra_mt)',
    { blend: [5, 10], depthWrite: false, queue: 3000, alphaSource: 'multiply' }, null],
  ['Blend SrcAlpha One, vertex cube by COLOR.a (11009/3 bg0010_01_stageA_add_ref_mt)',
    { blend: [5, 1], depthWrite: false, queue: 3000, alphaSource: 'vertex' },
    { mode: 'vertex', parallax: false, op: 'add', reflectivity: 'vertex', fresnel: false }],
  // AS/General/TransparentCutout: no lightmap; _Cutoff discards by _MainTex.a alone.
  ['cutout (10022/3 bg0007_04_plantsA_cut_mt keeps a fragment)', { shader: 'cutout', cutoff: 0.5 }, null],
  ['cutout, COLOR (12026/3 mat_stg_so2026_oth_02)', { shader: 'cutout', cutoff: 0.5, vertexColor: true, queue: 3000 }, null],
  ['cutout, COLOR, saturate (12030/3 mat_stg_so2030_alb_oth_01)',
    { shader: 'cutout', cutoff: 0.5, vertexColor: true, saturate: true }, null],
  ['cutout, saturate', { shader: 'cutout', cutoff: 0.2, saturate: true }, null],
  ['cutout discarding (_Cutoff above _MainTex.a)', { shader: 'cutout', cutoff: 0.7, vertexColor: true }, null],
  // Hidden/AS/Coloring/Opaque with its default white palette.
  ['coloring, COLOR (10008/3 cmn_mat_lit_02)', { shader: 'coloring', vertexColor: true }, null],
  ['coloring', { shader: 'coloring' }, null],
];

const SAMPLE = {
  main: [200, 120, 60, 153], light: [100, 140, 180, 255], emissiveMap: [128, 30, 220, 255],
  color: [0.9, 0.8, 0.7, 0.4],
  tint: [0.9, 0.7, 0.8, 0.85], ambient: [0.2, 0.5, 0.9, 0.35], blend: [0.95, 0.55, 0.35, 0.25],
  emissiveColor: [1, 0.75, 0.4, 0.3], emissiveIntensity: 1.7,
  // Unity cube faces +X, -X, +Y, -Y, +Z, -Z.
  faces: [[255, 0, 0], [0, 255, 0], [40, 90, 230], [255, 255, 0], [0, 255, 255], [255, 0, 255]],
  // A low ceiling and a capture point below the floor: parallax correction
  // turns the near floor's reflections from the -Z face to the +Y face.
  boxMin: [-60, -1, -60], boxMax: [60, 4, 60], origin: [0.5, -3, -0.5],
  camera: [0.7, 5.5, 6.5], target: [0, 0, 0], size: 24,
};

// The cube face a Unity-space direction samples, and how far it is from a face edge.
function cubeFace(direction) {
  const magnitudes = direction.map(Math.abs);
  const axis = magnitudes.indexOf(Math.max(...magnitudes));
  const others = magnitudes.filter((_, index) => index !== axis);
  return { face: 2 * axis + (direction[axis] < 0 ? 1 : 0), margin: 1 - Math.max(...others) / magnitudes[axis] };
}

// The reflection direction of a floor point (normal +Y) in Unity's axes.
function reflectionDirection(variant, point) {
  const view = SAMPLE.camera.map((c, i) => c - point[i]);
  const length = Math.hypot(...view);
  const ray = [-view[0] / length, view[1] / length, -view[2] / length];
  if (!variant.parallax) return ray;
  const walls = [0, 1, 2].map(i => Math.max((SAMPLE.boxMax[i] - point[i]) / ray[i], (SAMPLE.boxMin[i] - point[i]) / ray[i]));
  const distance = Math.min(...walls);
  return ray.map((r, i) => r * distance + point[i] - SAMPLE.origin[i]);
}

// The compiled AS/Stage fragment arithmetic (GLES3 variants, unity_Lightmap_HDR.x = 2).
function reference(fields, variant, point) {
  const v = (c) => c / 255;
  const tex = SAMPLE.main.map(v), light = SAMPLE.light.slice(0, 3).map(v), color = SAMPLE.color;
  const mix = (a, b, t) => a.map((x, i) => x + (b[i] - x) * t);
  if (fields.shader === 'cutout' || fields.shader === 'coloring') {
    // The compiled AS/General/TransparentCutout and Hidden/AS/Coloring/Opaque fragment programs.
    if (fields.shader === 'cutout' && tex[3] < fields.cutoff) return [0, 0, 0, 0];
    let out = [...mix(tex.slice(0, 3), SAMPLE.ambient.slice(0, 3), SAMPLE.ambient[3]).map((x, i) => x * SAMPLE.tint[i]),
      tex[3] * SAMPLE.tint[3]];
    if (fields.vertexColor) out = out.map((x, i) => x * color[i]);
    if (fields.saturate) out = out.map((x, i) => i < 3 ? x + tex[i] ** 4 : x);
    return out.map(x => Math.round(Math.min(Math.max(x, 0), 1) * 255));
  }
  const ambientSurface = mix(tex.slice(0, 3), SAMPLE.ambient.slice(0, 3), SAMPLE.ambient[3]);
  let lit = ambientSurface.map((x, i) => 2 * light[i] * x * color[i]);
  if (variant) {
    const face = SAMPLE.faces[cubeFace(reflectionDirection(variant, point)).face].map(v);
    const reflected = mix(face, SAMPLE.ambient.slice(0, 3), SAMPLE.ambient[3]);
    let r = { vertex: color[3], texture: tex[3], multiply: tex[3] * color[3] }[variant.reflectivity];
    const viewDotNormal = (SAMPLE.camera[1] - point[1]) / Math.hypot(...SAMPLE.camera.map((c, i) => c - point[i]));
    if (variant.fresnel) r = (1 - r) * (1 - viewDotNormal) ** 5 + r;
    r = Math.min(Math.max(r, 0), 1);
    lit = variant.op === 'add' ? lit.map((x, i) => x + reflected[i] * r) : mix(lit, reflected, r);
  }
  let out = mix(lit.map((x, i) => x * SAMPLE.tint[i]), SAMPLE.blend.slice(0, 3), SAMPLE.blend[3]);
  if (fields.emissive) {
    const emission = mix(ambientSurface, SAMPLE.emissiveColor.slice(0, 3), SAMPLE.emissiveColor[3])
      .map(x => x * SAMPLE.emissiveIntensity);
    out = mix(out, emission, v(SAMPLE.emissiveMap[0]));
  }
  const alpha = { vertex: color[3], texture: tex[3], multiply: tex[3] * color[3] }[fields.alphaSource || 'texture'] * SAMPLE.tint[3];
  const clamp = x => Math.min(Math.max(x, 0), 1);
  let result = [...out.map(clamp), clamp(alpha)];
  if (fields.blend) {
    // Over the cleared black, transparent target: source * SrcAlpha + 0 for colour and alpha alike.
    result = result.map(x => x * result[3]);
  }
  return result.map(x => Math.round(x * 255));
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    for (const script of ['vendor/three-r128/three.min.js', 'mv-studio-lighting.js', 'mv-studio-stage-material.js']) {
      await page.addScriptTag({ path: path.resolve(__dirname, '../webtools/web/static', script) });
    }
    const drawn = await page.evaluate(async ({ cases, sample }) => {
      const T = THREE, size = sample.size;
      const renderer = new T.WebGLRenderer({ antialias: false, alpha: true, stencil: true });
      renderer.setSize(size, size);
      const target = new T.WebGLRenderTarget(size, size);
      const camera = new T.PerspectiveCamera(50, 1, 0.1, 100);
      // The editor's scene mirrors Unity X.
      camera.position.set(-sample.camera[0], sample.camera[1], sample.camera[2]);
      camera.lookAt(-sample.target[0], sample.target[1], sample.target[2]);
      camera.updateMatrixWorld(true);
      const solid = (rgba) => {
        const texture = new T.DataTexture(new Uint8Array(rgba), 1, 1);
        texture.needsUpdate = true;
        return texture;
      };
      // Unity's cube: face-major RGBA levels 64 ... 1 with one colour per face.
      const levels = [64, 32, 16, 8, 4, 2, 1], cube = [];
      for (const face of sample.faces) for (const side of levels) for (let i = 0; i < side * side; i++) cube.push(...face, 255);
      const cubeBuffer = new Uint8Array(cube).buffer;
      const results = [];
      for (const [label, fields, variant] of cases) {
        // Fine enough that per-vertex reflection varyings track the per-pixel values.
        const floor = new T.PlaneGeometry(80, 80, 96, 96);
        floor.rotateX(-Math.PI / 2);
        const count = floor.getAttribute('position').count;
        floor.setAttribute('_stage_light_uv', floor.getAttribute('uv').clone());
        floor.setAttribute('_stage_emissive_uv', floor.getAttribute('uv').clone());
        floor.setAttribute('_stage_color', new T.Float32BufferAttribute(Array(count).fill(sample.color).flat(), 4));
        const meta = fields.shader === 'coloring' ? {
          shader: 'coloring', colors: { _TintColor: sample.tint, _AmbientColor: sample.ambient }, cull: 0,
          uvTransform: [1, 1, 0, 0], vertexColor: Boolean(fields.vertexColor), queue: 2000,
        } : fields.shader === 'cutout' ? {
          shader: 'cutout', colors: { _TintColor: sample.tint, _AmbientColor: sample.ambient }, cull: 0,
          uvTransform: [1, 1, 0, 0], vertexColor: Boolean(fields.vertexColor), alphaCutoff: fields.cutoff,
          queue: fields.queue ?? 2450, ...(fields.saturate ? { saturate: true } : {}),
        } : {
          shader: 'stage', colors: { _TintColor: sample.tint, _AmbientColor: sample.ambient, _BlendColor: sample.blend },
          cull: 2, uvTransform: [1, 1, 0, 0], vertexColor: true, mipBias: 0, lightmap: 0, reflectionToggle: Boolean(variant),
          queue: fields.queue ?? 2000,
        };
        for (const key of ['blend', 'depthWrite', 'alphaSource']) if (fields[key] !== undefined) meta[key] = fields[key];
        if (variant) {
          meta.reflection = { bufferView: 0, size: 64, ...variant };
          if (variant.parallax) Object.assign(meta.reflection, { boxMin: sample.boxMin, boxMax: sample.boxMax, origin: sample.origin });
        }
        if (fields.emissive) {
          meta.emissive = { texture: 1, color: sample.emissiveColor, intensity: sample.emissiveIntensity, uvTransform: [1, 1, 0, 0] };
        }
        floor.userData.mvStageMaterial = meta;
        const scene = new T.Scene();
        const mesh = new T.Mesh(floor, new T.MeshBasicMaterial({ map: solid(sample.main) }));
        scene.add(mesh);
        const textures = [solid(sample.light), solid(sample.emissiveMap)];
        const controller = await MVStudioStageMaterial.apply(T, scene, {
          getDependency: async (kind, index) => kind === 'bufferView' ? cubeBuffer : textures[index],
        });
        controller.update(0, { quality: { values: {} }, tracks: [] });
        renderer.setRenderTarget(target);
        renderer.setClearColor(0x000000, 0);
        renderer.clear();
        renderer.render(scene, camera);
        const pixels = new Uint8Array(size * size * 4);
        renderer.readRenderTargetPixels(target, 0, 0, size, size, pixels);
        renderer.setRenderTarget(null);
        // The floor point under each pixel centre, in Unity axes.
        const samples = [];
        for (let y = 1; y < size; y += 2) for (let x = 1; x < size; x += 2) {
          const ray = new T.Vector3((x + .5) / size * 2 - 1, (y + .5) / size * 2 - 1, .5).unproject(camera).sub(camera.position).normalize();
          const point = camera.position.clone().addScaledVector(ray, -camera.position.y / ray.y);
          samples.push({ x, y, point: [-point.x, point.y, point.z], pixel: Array.from(pixels.subarray((y * size + x) * 4, (y * size + x) * 4 + 4)) });
        }
        const { transparent, blending, depthWrite } = mesh.material;
        results.push({ label, native: mesh.material.isShaderMaterial === true, defines: { ...mesh.material.defines }, samples,
          state: { transparent, custom: blending === T.CustomBlending, depthWrite, renderOrder: mesh.renderOrder } });
        controller.dispose();
      }
      return results;
    }, { cases: CASES, sample: SAMPLE });
    assert.deepEqual(errors, []);
    for (const [index, result] of drawn.entries()) {
      const [label, fields, variant] = CASES[index];
      assert.equal(result.native, true, `${label}: native stage material`);
      assert.equal(Boolean(result.defines.CUBEMAP), Boolean(variant), `${label}: cube define`);
      assert.equal(result.defines.CUTOUT === 1, fields.shader === 'cutout', `${label}: cutout define`);
      assert.deepEqual(result.state, { transparent: (fields.queue ?? 2000) > 2500, custom: Boolean(fields.blend),
        depthWrite: fields.depthWrite !== false, renderOrder: (fields.queue ?? 0) > 2500 ? fields.queue : 0 }, `${label}: pass state`);
      let checked = 0;
      const faces = new Set();
      for (const { x, y, point, pixel } of result.samples) {
        if (variant) {
          // Seamless filtering blends neighbouring faces near a cube edge.
          const { face, margin } = cubeFace(reflectionDirection(variant, point));
          if (margin < .15) continue;
          faces.add(face);
        }
        const expected = reference(fields, variant, point);
        for (let channel = 0; channel < 4; channel++) {
          assert.ok(Math.abs(pixel[channel] - expected[channel]) <= 2,
            `${label} pixel (${x}, ${y}) channel ${channel}: ${pixel} vs ${expected}`);
        }
        checked++;
      }
      assert.ok(checked >= 100, `${label}: ${checked} sampled pixels`);
      if (variant?.parallax) assert.ok(faces.has(2) && faces.has(5), `${label}: parallax reaches both the +Y and -Z faces`);
      if (variant && !variant.parallax) assert.ok(faces.has(5), `${label}: the far floor reflects the -Z face`);
    }
    console.log(`AS/Stage variants: ${drawn.length} keyword combinations match their compiled fragment arithmetic.`);
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
