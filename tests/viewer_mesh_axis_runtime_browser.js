/* Real Three/WebGL pointers: source-local axes through skin/mapping transforms. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..'), source = path.join(root, 'webtools/web/static');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'mesh-axis-runtime-'));
fs.mkdirSync(evidence, { recursive: true });
const report = { status: 'RUNNING', cases: [], scope: 'Actual product Three/WebGL runtime with trusted mouse/touch pointers and generated skinned/morphed source mapping. Parent integration test covers real Unity/HTTP export/Undo.' };
let browser;
const vector = (a, b, tolerance, message) => a.forEach((v, i) => assert(Math.abs(v - b[i]) < tolerance, message + ': ' + JSON.stringify({ a, b })));
(async () => { try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1000, height: 800 }, hasTouch: true }), errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await page.setContent('<body style="margin:0"><div id="stage" class="viewer-stage" style="width:800px;height:600px;border:0"></div></body>');
  await page.addStyleTag({ path: path.join(source, 'style.css') });
  for (const name of ['vendor/three-r128/three.min.js', 'vendor/three-r128/OrbitControls.js', 'viewer-near-clip.js', 'viewer-mesh-runtime.js', 'viewer-mesh-tools.js']) await page.addScriptTag({ path: path.join(source, name) });
  await page.evaluate(() => {
    const T = THREE, renderer = new T.WebGLRenderer({ antialias: true }); renderer.setSize(800, 600); document.getElementById('stage').append(renderer.domElement);
    const camera = new T.PerspectiveCamera(42, 800 / 600, .01, 50); camera.position.set(2.2, 1.7, 4.5); camera.lookAt(0, 0, 0);
    const scene = new T.Scene(), model = new T.Group(); scene.add(model); model.rotation.y = .22; model.position.set(.1, .05, -.1);
    const sourcePositions = [[-.35, -.25, 0], [.35, -.25, 0], [0, .4, 0]], positionMatrix = new T.Matrix4().makeRotationZ(.23).scale(new T.Vector3(1.3, .8, 1.1));
    const geometry = new T.BufferGeometry(), positions = sourcePositions.flatMap(p => new T.Vector3().fromArray(p).applyMatrix4(positionMatrix).toArray());
    geometry.setAttribute('position', new T.Float32BufferAttribute(positions, 3)); geometry.setIndex([0, 1, 2]);
    geometry.setAttribute('skinIndex', new T.Uint16BufferAttribute([0,0,0,0, 0,1,0,0, 1,0,0,0], 4));
    geometry.setAttribute('skinWeight', new T.Float32BufferAttribute([1,0,0,0, .4,.6,0,0, 1,0,0,0], 4));
    geometry.morphTargetsRelative = true; geometry.morphAttributes.position = [new T.Float32BufferAttribute([0,0,.04, 0,0,.04, 0,0,.04], 3)];
    const identity = { source: 0, file: 0, id: 'axes' };
    geometry.userData.viewerMesh = { version: 1, writable: true, vertexOrder: 'identity', boneOrder: 'identity', mesh: identity, positionMatrix: positionMatrix.toArray(), vertexCount: 3, faceCount: 1, firstFace: 0, submesh: 0 };
    const mesh = new T.SkinnedMesh(geometry, new T.MeshBasicMaterial({ color: 0xeeeeee, side: T.DoubleSide, skinning: true, morphTargets: true }));
    mesh.position.set(.1, -.05, .03); mesh.scale.set(.9, 1.1, .8); const bone0 = new T.Bone(), bone1 = new T.Bone(); bone0.add(bone1); bone1.position.set(.1,.2,0); mesh.add(bone0); model.add(mesh); model.updateMatrixWorld(true); mesh.bind(new T.Skeleton([bone0,bone1]));
    bone1.rotation.z = .25; bone1.scale.x = 1.15; mesh.morphTargetInfluences[0] = .6;
    const original = { positions: Array.from(geometry.attributes.position.array), weights: Array.from(geometry.attributes.skinWeight.array) };
    const data = { mesh: identity, positions: sourcePositions, positionWritable: true }, state = { data, selected: new Set([0,1,2]), marked: new Set(), deleted: new Set(), positions: {}, weights: {}, geometryRevision: 0 };
    const context = { mesh: state, modify: true, mode: 'drag', dragAxis: 'screen', submesh: 0, radius: 20, erase: false, showSelection: true, showVertices: true, interactive: true };
    const runtime = { model, scene, camera, renderer, domElement: renderer.domElement, controls: new T.OrbitControls(camera,renderer.domElement), requestRender() {} }, calls = { begin: 0, end: 0, cancelled: 0, select: 0, drag: 0 };
    let before = null;
    const controller = ViewerMeshRuntime.create({ getRuntime: () => runtime, getContext: () => context,
      onBegin() { calls.begin++; before = JSON.stringify(state.positions); },
      onSelect(vertex, additive, dragging) { calls.select++; if (!dragging || !state.selected.has(vertex)) state.selected = new Set([vertex]); controller.sync([state]); },
      onDrag(values) { calls.drag++; Object.assign(state.positions, values); state.geometryRevision++; controller.sync([state]); },
      onEnd(cancel) { calls.end++; if (cancel) { calls.cancelled++; state.positions = JSON.parse(before); state.geometryRevision++; } controller.sync([state]); }
    });
    const refresh = () => { model.updateMatrixWorld(true); camera.updateMatrixWorld(true); controller.sync([state]); renderer.render(scene,camera); };
    function sample() { refresh(); return { source: [0,1,2].map(i => (state.positions[i] || data.positions[i]).slice()), world: [0,1,2].map(i => ViewerMeshRuntime.vertexWorld(mesh,i).toArray()), camera: { position: camera.position.toArray(), quaternion: camera.quaternion.toArray() }, calls: {...calls}, runtime: controller.getState(), controls: runtime.controls.enabled }; }
    window.axisTest = { T, scene, model, mesh, camera, runtime, renderer, controller, state, context, calls, positionMatrix, original, refresh, sample };
    refresh();
  });
  const initial = await page.evaluate(() => axisTest.sample());
  async function handleDrag(axis, touch) {
    const before = await page.evaluate(() => axisTest.sample()), h = before.runtime.gizmo.handles.find(h => h.axis === axis);
    assert(h, 'A real source-local ' + axis + ' axis handle is visible');
    const length = Math.hypot(h.end.x-h.start.x,h.end.y-h.start.y), dx = (h.end.x-h.start.x)/length*42, dy = (h.end.y-h.start.y)/length*42;
    if (touch) { const cdp = await page.context().newCDPSession(page); await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:h.x,y:h.y,id:1}]}); for(let i=1;i<=8;i++) await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:h.x+dx*i/8,y:h.y+dy*i/8,id:1}]}); await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]}); await cdp.detach(); }
    else { await page.mouse.move(h.x,h.y); await page.mouse.down(); await page.mouse.move(h.x+dx,h.y+dy,{steps:8}); await page.mouse.up(); }
    const after = await page.evaluate(() => axisTest.sample()), index = 'xyz'.indexOf(axis), amount = after.source[0][index]-before.source[0][index];
    assert(Math.abs(amount)>.005, 'Handle drag actually changes source positions: '+JSON.stringify({axis,touch,before:before.calls,after:after.calls,handle:h,sourceBefore:before.source,sourceAfter:after.source}));
    after.source.forEach((p,v) => p.forEach((value,k) => assert(Math.abs(value-before.source[v][k]-(k===index?amount:0))<1e-8,'Same source axis amount, other coordinates unchanged')));
    assert.deepEqual(after.camera,before.camera); assert.equal(after.calls.begin-before.calls.begin,1); assert.equal(after.calls.end-before.calls.end,1); assert.equal(after.calls.select,before.calls.select,'Axis handle retains exact selected group'); assert.equal(after.controls,true);
    const expected = await page.evaluate(({index,amount}) => { const t=axisTest,T=t.T; return [0,1,2].map(vertex=>{const linear=new T.Matrix3().setFromMatrix4(new T.Matrix4().copy(t.mesh.matrixWorld).multiply(ViewerMeshRuntime.skinMatrix(t.mesh,vertex)).multiply(t.positionMatrix)),p=new T.Vector3();p.setComponent(index,amount);return p.applyMatrix3(linear).toArray();}); },{index,amount});
    after.world.forEach((p,v)=>vector(p.map((value,k)=>value-before.world[v][k]),expected[v],2e-6,'Rendered morph+skin world delta matches source-local axis'));
    report.cases.push({name:(touch?'Touch':'Mouse')+' '+axis.toUpperCase()+' handle keeps source identity and skin transforms',amount});
  }
  await handleDrag('x',false); await handleDrag('y',true); await handleDrag('z',false);
  const scaling = await page.evaluate(() => { const t=axisTest,T=t.T; t.refresh();const centre=new T.Vector3().fromArray(t.controller.getState().gizmo.centre.world);t.camera.lookAt(centre);t.refresh();const before=t.controller.getState().gizmo,offset=t.camera.position.clone().sub(centre).multiplyScalar(2);t.camera.position.copy(centre).add(offset);t.camera.lookAt(centre);t.refresh();return {before,after:t.controller.getState().gizmo}; });
  for (const h of scaling.before.handles) { const next=scaling.after.handles.find(n=>n.axis===h.axis);assert(next);assert(Math.abs(Math.hypot(h.end.x-h.start.x,h.end.y-h.start.y)-Math.hypot(next.end.x-next.start.x,next.end.y-next.start.y))<.5,'Axis targets keep screen size when zooming'); }
  report.cases.push({name:'Axis arrow targets keep their screen size while camera distance changes'});
  const depthPick=await page.evaluate(()=>{const t=axisTest,T=t.T;t.state.selected=new Set([2]);t.context.dragAxis='z';t.refresh();const centre=new T.Vector3().fromArray(t.controller.getState().gizmo.centre.world),linear=new T.Matrix3().setFromMatrix4(new T.Matrix4().copy(t.mesh.matrixWorld).multiply(ViewerMeshRuntime.skinMatrix(t.mesh,2)).multiply(t.positionMatrix)),axis=new T.Vector3(0,0,1).applyMatrix3(linear).normalize();t.camera.position.copy(centre).addScaledVector(axis,4);t.camera.lookAt(centre);t.refresh();return{before:t.sample(),point:t.controller.projectVertex(t.state.data.mesh,2)};});
  await page.mouse.move(depthPick.point.x,depthPick.point.y);await page.mouse.down();await page.mouse.move(depthPick.point.x,depthPick.point.y-40,{steps:8});await page.mouse.up();
  const depthAfter=await page.evaluate(()=>axisTest.sample());assert(Math.abs(depthAfter.source[2][2]-depthPick.before.source[2][2])>.01);vector(depthAfter.source[2].slice(0,2),depthPick.before.source[2].slice(0,2),1e-8,'Camera-aligned depth drag preserves source XY');assert.deepEqual(depthAfter.camera,depthPick.before.camera);
  report.cases.push({name:'Explicit camera-aligned source Z axis uses stable depth drag instead of an unstable ray solve'});
  const cancelStart=await page.evaluate(()=>{axisTest.context.dragAxis='screen';axisTest.refresh();return{before:axisTest.sample(),handle:axisTest.controller.getState().gizmo.handles.find(h=>h.axis==='x')};});assert(cancelStart.handle);
  const cdp=await page.context().newCDPSession(page);await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:cancelStart.handle.x,y:cancelStart.handle.y,id:9}]});await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:cancelStart.handle.x+35,y:cancelStart.handle.y,id:9}]});await cdp.send('Input.dispatchTouchEvent',{type:'touchCancel',touchPoints:[]});await cdp.detach();
  const cancelled=await page.evaluate(()=>axisTest.sample());assert.deepEqual(cancelled.source,cancelStart.before.source);assert.equal(cancelled.calls.cancelled-cancelStart.before.calls.cancelled,1);assert.equal(cancelled.controls,true);
  report.cases.push({name:'Native touch cancellation restores transaction and camera controls exactly once'});
  const hiddenSelection=await page.evaluate(()=>{const t=axisTest,before=Array.from(t.state.selected),depth=-new t.T.Vector3().fromArray(t.controller.getState().gizmo.centre.world).applyMatrix4(t.camera.matrixWorldInverse).z;t.camera.near=depth+.01;t.camera.userData.viewerNearClipEnabled=true;t.camera.updateProjectionMatrix();t.refresh();const hidden=t.controller.getState().gizmo.visible,after=Array.from(t.state.selected);t.camera.near=.01;t.camera.userData.viewerNearClipEnabled=false;t.camera.updateProjectionMatrix();t.refresh();return{before,after,hidden,restored:t.controller.getState().gizmo.visible};});assert.equal(hiddenSelection.hidden,false);assert(hiddenSelection.restored);assert.deepEqual(hiddenSelection.after,hiddenSelection.before);
  report.cases.push({name:'Clipping temporarily hides off-plane handles without clearing the user selection'});
  const helperCheck=await page.evaluate(()=>{const t=axisTest;t.context.mode='orbit';t.refresh();const hidden=!t.controller.getState().gizmo.visible;const helpers=[];t.scene.traverse(o=>{if(o.name==='Selected vertex move axes')o.traverse(child=>helpers.push(!!child.userData.viewerHelper));});t.controller.reset();return{hidden,helpers,positions:Array.from(t.mesh.geometry.attributes.position.array),weights:Array.from(t.mesh.geometry.attributes.skinWeight.array),original:t.original};});
  assert(helperCheck.hidden&&helperCheck.helpers.every(Boolean));assert.deepEqual(helperCheck.positions,helperCheck.original.positions);assert.deepEqual(helperCheck.weights,helperCheck.original.weights);
  report.cases.push({name:'Navigation hides handles; helper geometry stays outside model export and reset restores original geometry/weights'});
  const clipping=await page.evaluate(()=>{
    const t=axisTest,T=t.T;t.controller.dispose();t.scene.remove(t.model);t.camera.position.set(0,0,0);t.camera.lookAt(0,0,-1);t.camera.near=.01;t.camera.far=10;t.camera.userData.viewerNearClipEnabled=false;t.camera.updateProjectionMatrix();
    const model=new T.Group(),geometry=new T.BufferGeometry(),coords=[-.25,-.2,-.05, .25,-.2,-.4, 0,.25,-.4],identity={source:0,file:0,id:'clip'};geometry.setAttribute('position',new T.Float32BufferAttribute(coords,3));geometry.setIndex([0,1,2]);geometry.userData.viewerMesh={version:1,writable:true,vertexOrder:'identity',mesh:identity,positionMatrix:new T.Matrix4().toArray(),vertexCount:3,faceCount:1,firstFace:0,submesh:0};
    const mesh=new T.Mesh(geometry,new T.MeshBasicMaterial({color:0x1188ff,side:T.DoubleSide}));model.add(mesh);const blocker=new T.Mesh(new T.PlaneGeometry(.3,.3),new T.MeshBasicMaterial({color:0xff3300,side:T.DoubleSide}));blocker.position.z=-.06;model.add(blocker);t.scene.add(model);
    const data={mesh:identity,positions:[coords.slice(0,3),coords.slice(3,6),coords.slice(6,9)],positionWritable:true},state={data,selected:new Set(),marked:new Set(),deleted:new Set(),positions:{},weights:{},geometryRevision:0},context={mesh:state,modify:false,mode:'paint',submesh:0,radius:8,showSelection:true,showVertices:false,interactive:true},runtime={...t.runtime,model};let controller;
    controller=ViewerMeshRuntime.create({getRuntime:()=>runtime,getContext:()=>context,onPaint(indices){indices.forEach(i=>state.marked.add(i));controller.sync([state]);}});controller.sync([state]);t.renderer.render(t.scene,t.camera);
    const point=new T.Vector3(.05,-.02,-.33).project(t.camera),rect=t.renderer.domElement.getBoundingClientRect();window.clipTest={mesh,blocker,state,context,runtime,controller};return{x:rect.left+(point.x+1)*rect.width/2,y:rect.top+(1-point.y)*rect.height/2};
  });
  await page.mouse.click(clipping.x,clipping.y);assert.deepEqual(await page.evaluate(()=>Array.from(clipTest.state.marked)),[],'OFF retains normal front-surface occlusion');
  await page.evaluate(()=>{const t=axisTest;t.camera.near=.1;t.camera.userData.viewerNearClipEnabled=true;t.camera.updateProjectionMatrix();clipTest.controller.beforeRender();t.renderer.render(t.scene,t.camera);});
  await page.mouse.click(clipping.x,clipping.y);assert.deepEqual(await page.evaluate(()=>Array.from(clipTest.state.marked)),[0],'Clipped front surface cannot block a visible triangle crossing near plane');
  await page.evaluate(()=>{clipTest.state.marked.clear();axisTest.camera.userData.viewerNearClipEnabled=false;clipTest.controller.sync([clipTest.state]);});await page.mouse.click(clipping.x,clipping.y);assert.deepEqual(await page.evaluate(()=>Array.from(clipTest.state.marked)),[],'OFF preserves its original crossing-triangle candidate policy');
  await page.evaluate(()=>{axisTest.camera.userData.viewerNearClipEnabled=true;clipTest.controller.beforeRender();});await page.mouse.click(clipping.x,clipping.y);assert.deepEqual(await page.evaluate(()=>Array.from(clipTest.state.marked)),[0],'Changing clip enabled flag invalidates coarse candidates even with identical projection matrix');
  const generic=await page.evaluate(()=>{const T=THREE,g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute([-.1,-.1,-.05,.1,-.1,-.05,0,.1,-.05, -.1,-.1,-.4,.1,-.1,-.4,0,.1,-.4],3));g.setIndex([0,1,2,3,4,5]);const m=new T.Mesh(g),ray=new T.Ray(new T.Vector3(),new T.Vector3(0,0,-1));m.updateMatrixWorld(true);return{plain:ViewerMeshRuntime.raycastMesh(ray,m).faceIndex,filtered:ViewerMeshRuntime.raycastMesh(ray,m,{hitFilter:ViewerNearClip.filterForCamera(axisTest.camera)}).faceIndex};});assert.deepEqual(generic,{plain:0,filtered:1});
  report.cases.push({name:'Optional depth filter rejects clipped nearest hits before choosing visible interior and retains crossing-triangle paint candidates'});
  assert.deepEqual(errors,[]);await page.screenshot({path:path.join(evidence,'axis-clipping.png')});report.status='PASS';
} catch(error){report.status='FAIL';report.error=String(error.stack||error);process.exitCode=1;}
finally{if(browser)await browser.close();fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,cases:report.cases.length,evidence,error:report.error}));}})();
