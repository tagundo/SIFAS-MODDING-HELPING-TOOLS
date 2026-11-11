/* Bounded precise framing/fallback regressions on the actual product renderer.
 * Geometry below is generated. No game asset or user data is used. */
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-framing-'));
fs.mkdirSync(evidence, { recursive: true });

function staticMorphFixture() {
  const parts = [], views = [], accessors = []; let length = 0;
  function attr(values, Type, type, componentType, size, bounds) {
    const buffer = Buffer.from(new Type(values).buffer), padding = (4 - length % 4) % 4;
    if (padding) { parts.push(Buffer.alloc(padding)); length += padding; }
    const view = views.length; views.push({ buffer: 0, byteOffset: length, byteLength: buffer.length });
    parts.push(buffer); length += buffer.length;
    accessors.push({ bufferView: view, componentType, count: values.length / size, type, ...bounds });
    return accessors.length - 1;
  }
  const position = attr([-.4,0,0,.4,0,0,0,1.5,.2], Float32Array, 'VEC3', 5126, 3, { min: [-.4,0,0], max: [.4,1.5,.2] });
  const index = attr([0,1,2], Uint16Array, 'SCALAR', 5123, 1);
  const morph = attr([0,0,0,0,0,0,.3,1,0], Float32Array, 'VEC3', 5126, 3);
  const doc = { asset: { version: '2.0', generator: 'Original static morph framing regression' }, scene: 0,
    scenes: [{ nodes: [0] }], nodes: [{ name: 'FramingMesh', mesh: 0 }],
    meshes: [{ weights: [0], extras: { targetNames: ['GeneratedMorph'] }, primitives: [{ attributes: { POSITION: position }, indices: index, material: 0, targets: [{ POSITION: morph }] }] }],
    materials: [{ pbrMetallicRoughness: { baseColorFactor: [.8,.2,.3,1] }, extensions: { KHR_materials_unlit: {} }, doubleSided: true }],
    extensionsUsed: ['KHR_materials_unlit'], buffers: [{ byteLength: length }], bufferViews: views, accessors };
  const raw = Buffer.from(JSON.stringify(doc)), json = Buffer.concat([raw, Buffer.alloc((4 - raw.length % 4) % 4, 32)]);
  const bytes = Buffer.concat(parts), binary = Buffer.concat([bytes, Buffer.alloc((4 - bytes.length % 4) % 4)]);
  const header = Buffer.alloc(12), jh = Buffer.alloc(8), bh = Buffer.alloc(8);
  header.writeUInt32LE(0x46546c67); header.writeUInt32LE(2,4); header.writeUInt32LE(28 + json.length + binary.length,8);
  jh.writeUInt32LE(json.length); jh.writeUInt32LE(0x4e4f534a,4); bh.writeUInt32LE(binary.length); bh.writeUInt32LE(0x004e4942,4);
  return Buffer.concat([header,jh,json,bh,binary]);
}

(async () => {
  const launch = { headless: true, args: ['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'] };
  if (process.env.CHROMIUM_EXECUTABLE) launch.executablePath = process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(launch), errors = [], results = [];
  try {
    const page = await browser.newPage({ viewport: { width: 448, height: 998 } });
    page.on('pageerror', error => errors.push(String(error))); page.setDefaultTimeout(30000);
    await page.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
    await page.route('**/static/viewer-rig.js', async route => {
      const response = await route.fetch(), body = await response.text();
      await route.fulfill({ response, body: body + `\n(() => {
        const create = ViewerRig.create;
        ViewerRig.create = function(root) {
          window.__framingRoot = root; window.__framingBoundsCalls = 0;
          const result = create.apply(this, arguments), bounds = result.getBounds;
          result.getBounds = function() { __framingBoundsCalls++; return bounds.apply(this, arguments); };
          return result;
        };
      })();` });
    });
    await page.route('**/static/viewer-quality.js', async route => {
      const response = await route.fetch(), body = await response.text();
      await route.fulfill({ response, body: body + `\n(() => {
        const create = ViewerQuality.create;
        ViewerQuality.create = function(renderer) {
          const result = create.apply(this, arguments), render = result.render;
          result.render = function(scene,camera) { window.__framingCamera = camera; return render.apply(this, arguments); };
          return result;
        };
      })();` });
    });
    const glb = staticMorphFixture();
    await page.route('**/api/viewer/prepare', route => route.fulfill({ status:200, contentType:'application/json',
      body: JSON.stringify({ id:'framing-regression',url:'/api/viewer/model/framing-regression.glb',warnings:[],stats:{meshes:1,vertices:3,triangles:1,textures:0,materials:1},rig:{} }) }));
    await page.route('**/api/viewer/model/*.glb', route => route.fulfill({ status:200,contentType:'model/gltf-binary',body:glb }));
    await page.goto(process.env.VIEWER_URL || 'http://127.0.0.1:8898');
    await page.waitForFunction(() => typeof openModelViewer === 'function' && !!window.ViewerRig);
    await page.evaluate(() => openModelViewer(['/original/static-morph.unity']));
    await page.waitForFunction(() => ModelViewer.getState().loaded && !!window.__framingCamera);
    async function fit(label) {
      await page.locator('#viewer-fit').click();
      const value = await page.evaluate(() => {
        const state = ModelViewer.getState(), outside = [];
        __framingCamera.updateMatrixWorld(true); __framingRoot.updateMatrixWorld(true);
        __framingRoot.traverseVisible(mesh => {
          if (!mesh.isMesh || !mesh.geometry || !mesh.geometry.attributes.position) return;
          const positions = mesh.geometry.attributes.position, morphs = mesh.geometry.morphAttributes.position || [];
          // Check actual indexed vertices, not the product's diagnostic summary.
          const indices = mesh.geometry.index ? Array.from(new Set(mesh.geometry.index.array)) : Array.from({ length:positions.count }, (_,i)=>i);
          for (const index of indices) {
            const original = new THREE.Vector3().fromBufferAttribute(positions,index), point = original.clone();
            morphs.forEach((morph,i) => { const weight = mesh.morphTargetInfluences && mesh.morphTargetInfluences[i] || 0;
              const delta = new THREE.Vector3().fromBufferAttribute(morph,index); if (!mesh.geometry.morphTargetsRelative) delta.sub(original); point.addScaledVector(delta,weight); });
            point.applyMatrix4(mesh.matrixWorld).project(__framingCamera);
            if (Math.abs(point.x)>1.00001 || Math.abs(point.y)>1.00001 || Math.abs(point.z)>1.00001) outside.push(index);
          }
        });
        return { framing:state.framing,camera:state.camera,outside,boundsCalls:__framingBoundsCalls };
      });
      assert(value.camera.position.concat(value.camera.target).every(Number.isFinite), label+': finite camera');
      assert.equal(value.framing.pointsOutside,0,label+': conservative or precise frame stays inside');
      assert.deepEqual(value.outside,[],label+': independent actual indexed vertices stay inside');
      results.push({ label,...value }); return value;
    }
    const initial = await fit('static-unskinned');
    await page.evaluate(() => __framingRoot.getObjectByName('FramingMesh').morphTargetInfluences[0] = 1);
    const morph = await fit('static-morph-applied');
    assert.equal(morph.framing.method,'posed-triangles');
    assert(morph.camera.target[1] > initial.camera.target[1] + .4,'An unskinned morph changes the exact world-space fit');
    async function geometry(kind) {
      await page.evaluate(kind => {
        const mesh = __framingRoot.getObjectByName('FramingMesh'), old = mesh.geometry, next = new THREE.BufferGeometry();
        if (kind === 'large') {
          const points = new Float32Array(250001*3); points.set([-.4,0,0,.4,0,0,0,1.5,0]);
          next.setAttribute('position',new THREE.BufferAttribute(points,3)); next.setIndex([0,1,2]);
        } else if (kind === 'budget') {
          next.setAttribute('position',new THREE.Float32BufferAttribute([-.01,-.01,0,.01,-.01,0,0,.01,0,-.57,-1,0,.57,-1,0,-.57,1,0],3));
          const indices = new Uint32Array(500000*3);
          for(let i=0;i<499999;i++)indices.set([0,1,2],i*3); indices.set([3,4,5],499999*3);
          next.setIndex(new THREE.BufferAttribute(indices,1));
        } else { next.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0,0,0,0,0,0,0],3));next.setIndex([0,1,2]); }
        mesh.geometry=next;mesh.morphTargetInfluences=[];mesh.morphTargetDictionary={};mesh.material.needsUpdate=true;old.dispose();
      },kind);
    }
    await geometry('large'); const large = await fit('250001-vertex-fallback');
    assert.equal(large.framing.method,'conservative-large-geometry'); assert.equal(large.framing.snapshotVertices,0);
    assert.equal(large.framing.vertices,250001); assert.equal(large.framing.projectedBoundsKind,'posed-box');
    assert(large.framing.projectedBounds.bottom-large.framing.projectedBounds.top>100,
      'Bottom-center controls must not collapse large-model framing into a one-pixel-wide safe region');
    await geometry('budget'); const budget = await fit('500000-triangle-visit-fallback');
    assert.equal(budget.framing.method,'conservative-controls'); assert.equal(budget.framing.triangles,500000);
    assert(budget.framing.triangleVisits>=1000000,'Repeated near-corner collisions exercise the bounded visit fallback');
    assert(budget.framing.triangleVisits<=1000001);
    assert(budget.framing.projectedBounds.bottom-budget.framing.projectedBounds.top>100,
      'The bounded triangle-visit fallback keeps a useful model scale with centered viewport tools');
    await geometry('degenerate'); await fit('degenerate-triangle');
    await page.evaluate(() => __framingRoot.getObjectByName('FramingMesh').visible=false);
    const hidden = await fit('all-meshes-hidden'); assert.equal(hidden.framing.vertices,0);assert.equal(hidden.framing.snapshotVertices,0);
    const before = await page.evaluate(() => ({count:__framingBoundsCalls,camera:ModelViewer.getState().camera,framing:ModelViewer.getState().framing}));
    // Trigger a normal render-setting event without opening the editor; this
    // is a scan-count regression, not a test of editor control reachability.
    await page.locator('#viewer-background').evaluate(element => { element.value='dark';element.dispatchEvent(new Event('change',{bubbles:true})); });
    await page.setViewportSize({width:480,height:1040});
    await page.evaluate(() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const after = await page.evaluate(() => ({count:__framingBoundsCalls,camera:ModelViewer.getState().camera,framing:ModelViewer.getState().framing}));
    assert.deepEqual(after,before,'Render and resize preserve camera and do not rescan posed geometry');
    assert.deepEqual(errors,[]);
    const report = { status:'PASS',scope:'Product WebGL/DOM using generated static morph/large/degenerate geometry; no user/game files',results,renderResizeNoScan:after,errors };
    fs.writeFileSync(process.env.VIEWER_REPORT || path.join(evidence,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
