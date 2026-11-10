/* Actual ModelViewer camera-depth regression with generated geometry only.
 * VIEWER_URL must serve the WebUI, as with the other browser suites.
 * ELICHIKA_VIEWER_STATIC_DIR can select a candidate; VIEWER_CAMERA_EXPECT_OLD=1
 * records the expected failing nearest-surface ordering of the old camera.
 */
'use strict';
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert'),crypto=require('crypto');
const {chromium}=require('playwright');
const {fixture}=require('./viewer_rig_browser');
const oracle=require('./viewer_camera_oracle');
const root=path.resolve(__dirname,'..');
const sources=process.env.ELICHIKA_VIEWER_STATIC_DIR||path.join(root,'webtools/web/static');
const evidence=process.env.EVIDENCE_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'viewer-camera-'));
const expectedOld=process.env.VIEWER_CAMERA_EXPECT_OLD==='1',variant=expectedOld?'before':'candidate';
fs.mkdirSync(evidence,{recursive:true});
const sourcePath=path.join(sources,'model-viewer.js'),source=fs.readFileSync(sourcePath),sha=b=>crypto.createHash('sha256').update(b).digest('hex');
let generated=oracle.appendDepthPlanes(fixture()),browser,errors=[],warnings=[],requests=[];
const report={status:'RUNNING',variant,scope:'Actual ModelViewer; generated original skin and independent front-plane ray oracle, real WebGL2 with AA/HQ retained. Software browser rendering, no native/device FPS claim.',testedSourceSha256:sha(source),oracle:oracle.centerRayOracle([0,.6,6],[0,.6,0]),frames:[]};
function scaleFixture(scale){
 const initial=oracle.appendDepthPlanes(fixture()),len=initial.glb.readUInt32LE(12),doc=JSON.parse(initial.glb.subarray(20,20+len)),bin=initial.glb.subarray(28+len);
 for(const node of doc.scenes[0].nodes)doc.nodes[node].scale=[scale,scale,scale];
 const json=Buffer.from(JSON.stringify(doc)),jp=Buffer.concat([json,Buffer.alloc((4-json.length%4)%4,32)]),h=Buffer.alloc(20),bh=Buffer.alloc(8);
 h.writeUInt32LE(0x46546c67,0);h.writeUInt32LE(2,4);h.writeUInt32LE(28+jp.length+bin.length,8);h.writeUInt32LE(jp.length,12);h.writeUInt32LE(0x4e4f534a,16);bh.writeUInt32LE(bin.length);bh.writeUInt32LE(0x004e4942,4);
 return Object.assign({},initial,{glb:Buffer.concat([h,jp,bh,bin])});
}
(async()=>{try{
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||'/usr/bin/chromium',args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1000,height:760},deviceScaleFactor:1});page.setDefaultTimeout(20000);
 page.on('pageerror',e=>errors.push(String(e)));
 page.on('console',m=>{if(m.type()==='error'){if(/drawMode has been removed/.test(m.text()))warnings.push(m.text());else errors.push(m.text());}});
 await page.addInitScript(()=>localStorage.setItem('sifas_lang','en'));
 await page.route('**/static/model-viewer.js*',r=>r.fulfill({status:200,contentType:'application/javascript',body:source}));
 await page.route('**/api/viewer/prepare',r=>{requests.push(r.request().postDataJSON());return r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:'camera-policy-generated',url:'/api/viewer/model/camera-policy-generated.glb',stats:{meshes:3,vertices:11,triangles:5,materials:3,textures:0},warnings:[],rig:generated.rig})});});
 await page.route('**/api/viewer/model/*.glb',r=>r.fulfill({status:200,contentType:'model/gltf-binary',body:generated.glb}));
 await page.goto(process.env.VIEWER_URL||'http://127.0.0.1:8898');await page.waitForFunction(()=>!!window.ModelViewer&&!!window.ViewerRig);
 await page.evaluate(()=>{
  const Rig=ViewerRig.create;ViewerRig.create=function(){window.__nearRoot=arguments[0];window.__nearRig=Rig.apply(this,arguments);return window.__nearRig;};
  const Controls=THREE.OrbitControls;THREE.OrbitControls=function(){window.__nearControls=new Controls(...arguments);window.__nearCamera=arguments[0];return window.__nearControls;};THREE.OrbitControls.prototype=Controls.prototype;
  const Renderer=THREE.WebGLRenderer;THREE.WebGLRenderer=function(){window.__nearRenderer=new Renderer(...arguments);return window.__nearRenderer;};THREE.WebGLRenderer.prototype=Renderer.prototype;
 });
 async function open(label){await page.evaluate(name=>{openModelViewer(['/synthetic/'+name+'.unity']);},label);await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading);await page.locator('#viewer-display-options').evaluate(n=>n.open=true);await page.locator('#viewer-high-quality').check();await page.evaluate(()=>{window.__nearControls.enableDamping=false;ModelViewer.renderProbe(1);});}
 async function camera(position,target,fov=35){return page.evaluate(({position,target,fov})=>{const c=__nearCamera,o=__nearControls;c.position.fromArray(position);o.target.fromArray(target);c.fov=fov;c.updateProjectionMatrix();o.update();ModelViewer.renderProbe(1);return{position:c.position.toArray(),target:o.target.toArray(),fov:c.fov,near:c.near,far:c.far,min:o.minDistance,max:o.maxDistance};},{position,target,fov});}
 async function sample(label,frontFirst=true){
  await page.evaluate('('+oracle.setDepthOrder.toString()+')(__nearRoot,'+frontFirst+')');
  const result=await page.evaluate(label=>{const probe=ModelViewer.renderProbe(1),c=__nearCamera,o=__nearControls,gl=__nearRenderer.getContext(),px=new Uint8Array(4);gl.readPixels(Math.floor(gl.drawingBufferWidth/2),Math.floor(gl.drawingBufferHeight/2),1,1,gl.RGBA,gl.UNSIGNED_BYTE,px);return{label,pixel:Array.from(px),near:c.near,far:c.far,distance:c.position.distanceTo(o.target),minDistance:o.minDistance,position:c.position.toArray(),target:o.target.toArray(),fov:c.fov,depthBits:gl.getParameter(gl.DEPTH_BITS),quality:ModelViewer.getState().quality,probe};},label);
  assert.equal(result.probe.glError,0);assert.equal(result.quality.enabled,true);assert(result.quality.actualSamples>=2);report.frames.push(result);return result;
 }
 await open('initial');
 const beforeView=await camera([0,.6,6],[0,.6,0]);
 const frontFirst=await sample('far-front-first',true),rearFirst=await sample('far-rear-first',false);
 assert.equal(oracle.classifyColor(rearFirst.pixel),'green');
 if(variant==='before'){
  assert.equal(oracle.classifyColor(frontFirst.pixel),'red','Frozen old camera must fail the independent nearest-geometry ordering oracle');
  report.oldSourceFailsIndependentDepthOracle=true;
 }else{
  assert.equal(oracle.classifyColor(frontFirst.pixel),'green','Raised near must preserve analytically closest green plane regardless of draw order');
  assert.deepStrictEqual(frontFirst.position,beforeView.position);assert.deepStrictEqual(frontFirst.target,beforeView.target);assert.equal(frontFirst.fov,beforeView.fov);assert.equal(frontFirst.far,beforeView.far);
  const sourceSnapshot=await page.evaluate(()=>{const rows=[];__nearRoot.traverse(m=>{if(!m.isMesh||m.userData.viewerHelper)return;rows.push({name:m.name,attributes:Object.fromEntries(Object.entries(m.geometry.attributes).map(([k,a])=>[k,Array.from(a.array)])),index:m.geometry.index&&Array.from(m.geometry.index.array),morphs:Object.fromEntries(Object.entries(m.geometry.morphAttributes).map(([k,as])=>[k,as.map(a=>Array.from(a.array))]))});});return rows;});
  const geometrySignature=sha(Buffer.from(JSON.stringify(sourceSnapshot)));report.sourceGeometrySha256=geometrySignature;
  const authored=await page.evaluate(()=>ModelViewer.getAuthoringState());
  const nearMin=await page.evaluate(()=>{const c=__nearCamera,o=__nearControls;o.enableDamping=false;c.position.copy(o.target).add(new THREE.Vector3(0,0,o.minDistance));o.update();ModelViewer.renderProbe(1);return{near:c.near,min:o.minDistance,far:c.far,position:c.position.toArray(),target:o.target.toArray()};});
  const expectedOld=Math.max(.001,(nearMin.min/.12)/1000);assert(Math.abs(nearMin.near-expectedOld)<1e-8,'Minimum supported zoom keeps the original near floor');report.minimumZoom={...nearMin,oldNear:expectedOld};
  await camera([0,.6,6],[0,.6,0]);assert.equal(oracle.classifyColor((await sample('zoom-back-far',true)).pixel),'green');
  for(const [label,pos,target,fov]of[['pan',[.4,.8,6],[.4,.8,0],35],['orbit',[3,.8,5],[0,.6,0],35],['fov-narrow',[0,.6,6],[0,.6,0],15],['fov-wide',[0,.6,6],[0,.6,0],70]]){
   const set=await camera(pos,target,fov),r=await sample(label,true);assert.deepStrictEqual(r.position,set.position);assert.deepStrictEqual(r.target,set.target);assert.equal(r.fov,set.fov);assert.equal(r.far,set.far);
  }
  await camera([0,.6,6],[0,.6,0]);
  const paused=await page.evaluate(()=>{const c=__nearCamera,o=__nearControls,original=c.updateProjectionMatrix;let updates=0;c.updateProjectionMatrix=function(){updates++;return original.apply(this,arguments);};o.enableDamping=true;const prior=ModelViewer.getState().renderedFrames;for(let i=0;i<100;i++){o.update();ModelViewer.renderProbe(1);}c.updateProjectionMatrix=original;return{updates,frames:ModelViewer.getState().renderedFrames-prior,near:c.near};});
  assert.equal(paused.updates,0,'100 unchanged renders must not invalidate projection caches');assert.equal(paused.frames,100);report.paused100=paused;
  await camera([.2,.7,.5],[.1,.6,0]);
  const pausedClose=await page.evaluate(()=>{const c=__nearCamera,o=__nearControls,original=c.updateProjectionMatrix;let updates=0;c.updateProjectionMatrix=function(){updates++;return original.apply(this,arguments);};o.enableDamping=true;const prior=ModelViewer.getState().renderedFrames;for(let i=0;i<100;i++){o.update();ModelViewer.renderProbe(1);}c.updateProjectionMatrix=original;return{updates,frames:ModelViewer.getState().renderedFrames-prior,near:c.near,distance:c.position.distanceTo(o.target)};});
  assert.equal(pausedClose.updates,0,'100 stationary zoom-dependent near renders must tolerate OrbitControls floating-point roundoff');assert.equal(pausedClose.frames,100);assert(pausedClose.near<paused.near);report.pausedClose100=pausedClose;
  await camera([0,.6,6],[0,.6,0]);
  await page.locator('#viewer-adjustments').evaluate(n=>n.open=true);
  await page.locator('#viewer-motion').selectOption('Synthetic test motion');
  await page.evaluate(()=>{const c=__nearCamera;window.__nearUpdateCount=0;window.__nearOriginalProjection=c.updateProjectionMatrix;c.updateProjectionMatrix=function(){__nearUpdateCount++;return __nearOriginalProjection.apply(this,arguments);};window.__nearFirstFrame=ModelViewer.getState().renderedFrames;});
  await page.locator('#viewer-play').click();await page.waitForFunction(()=>ModelViewer.getState().renderedFrames>=window.__nearFirstFrame+100);await page.locator('#viewer-play').click();
  report.live100=await page.evaluate(()=>{const c=__nearCamera;const out={updates:__nearUpdateCount,frames:ModelViewer.getState().renderedFrames-__nearFirstFrame,time:ModelViewer.getState().rig.time};c.updateProjectionMatrix=__nearOriginalProjection;return out;});assert.equal(report.live100.updates,0,'A moving pose with stationary camera must not churn projection matrices');
  const afterLiveSource=await page.evaluate(()=>{const rows=[];__nearRoot.traverse(m=>{if(!m.isMesh||m.userData.viewerHelper)return;rows.push({name:m.name,attributes:Object.fromEntries(Object.entries(m.geometry.attributes).filter(([k])=>!/^morph(?:Target|Normal)\d+$/.test(k)).map(([k,a])=>[k,Array.from(a.array)])),index:m.geometry.index&&Array.from(m.geometry.index.array),morphs:Object.fromEntries(Object.entries(m.geometry.morphAttributes).map(([k,as])=>[k,as.map(a=>Array.from(a.array))]))});});return rows;});
  // Three may add shader binding attributes, but original source arrays remain unchanged.
  for(let i=0;i<sourceSnapshot.length;i++)for(const key of Object.keys(sourceSnapshot[i].attributes))assert.deepStrictEqual(afterLiveSource[i].attributes[key],sourceSnapshot[i].attributes[key]);
  assert.deepStrictEqual(await page.evaluate(()=>ModelViewer.getAuthoringState()),authored);report.originalAuthoredStateNotEdited=true;
  await page.evaluate(()=>{const c=__nearCamera,o=__nearControls;o.enableDamping=false;c.position.set(.2,.7,4);o.target.set(.1,.6,0);c.fov=42;c.updateProjectionMatrix();o.update();ModelViewer.renderProbe(1);});
  const retained=await page.evaluate(()=>({position:__nearCamera.position.toArray(),target:__nearControls.target.toArray(),fov:__nearCamera.fov,far:__nearCamera.far}));
  await page.evaluate(()=>ModelViewer.addMotion(['/synthetic/retained-motion.unity']));await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading);await page.evaluate(()=>ModelViewer.renderProbe(1));
  const afterRetain=await page.evaluate(()=>({position:__nearCamera.position.toArray(),target:__nearControls.target.toArray(),fov:__nearCamera.fov,far:__nearCamera.far}));
  const retainedDelta=Math.max(...retained.position.map((v,i)=>Math.abs(v-afterRetain.position[i])),...retained.target.map((v,i)=>Math.abs(v-afterRetain.target[i])));
  assert(retainedDelta<1e-12,'Motion reload preserves camera apart from existing OrbitControls floating-point roundoff');assert.equal(afterRetain.fov,retained.fov);assert.equal(afterRetain.far,retained.far);report.cameraRetainedAcrossMotionReload={passed:true,maximumWorldCoordinateDelta:retainedDelta};
  await page.evaluate(()=>{window.__nearContext=__nearRenderer.getContext().getExtension('WEBGL_lose_context');__nearContext.loseContext();});await page.waitForFunction(()=>ModelViewer.getState().contextLost);await page.waitForTimeout(200);await page.evaluate(()=>__nearContext.restoreContext());await page.waitForFunction(()=>!ModelViewer.getState().contextLost);await camera([0,.6,6],[0,.6,0]);assert.equal(oracle.classifyColor((await sample('context-restored-far',true)).pixel),'green');report.contextRestore=true;
  // Raw skinned positions can be far from the rendered model. Retained views
  // must reuse the posed radius used by fitModel, not refresh from raw bounds.
  generated=oracle.appendDepthPlanes(fixture({shifted:true}));await open('shifted-skin');await camera([0,.6,60],[0,.6,0]);
  assert.equal(oracle.classifyColor((await sample('shifted-skin-far',true)).pixel),'green');
  const shifted=await page.evaluate(()=>({position:__nearCamera.position.toArray(),target:__nearControls.target.toArray(),near:__nearCamera.near,min:__nearControls.minDistance,max:__nearControls.maxDistance,fov:__nearCamera.fov,far:__nearCamera.far}));
  await page.evaluate(()=>ModelViewer.addMotion(['/synthetic/shifted-retained-motion.unity']));await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading);await page.evaluate(()=>ModelViewer.renderProbe(1));
  const shiftedAfter=await page.evaluate(()=>({position:__nearCamera.position.toArray(),target:__nearControls.target.toArray(),near:__nearCamera.near,min:__nearControls.minDistance,max:__nearControls.maxDistance,fov:__nearCamera.fov,far:__nearCamera.far}));
  const shiftedDelta=Math.max(...shifted.position.map((v,i)=>Math.abs(v-shiftedAfter.position[i])),...shifted.target.map((v,i)=>Math.abs(v-shiftedAfter.target[i])));
  assert(shiftedDelta<1e-12);for(const key of ['near','min','max','fov','far'])assert.equal(shiftedAfter[key],shifted[key],'Motion reload preserves fitted '+key+' on a shifted skin');
  assert.equal(oracle.classifyColor((await sample('shifted-skin-retained-far',true)).pixel),'green');report.shiftedSkinRetainedCamera={before:shifted,after:shiftedAfter,maximumWorldCoordinateDelta:shiftedDelta};
  report.scaleCases=[];
  for(const scale of [.01,10]){generated=scaleFixture(scale);await open('scaled-'+scale);const s=await page.evaluate(()=>({camera:ModelViewer.getState().camera,near:__nearCamera.near,far:__nearCamera.far,min:__nearControls.minDistance,quality:ModelViewer.getState().quality,probe:ModelViewer.renderProbe(1)}));assert.equal(s.probe.glError,0);assert(s.probe.nonBackgroundSamples>0);assert(s.near>0&&s.near<s.far);report.scaleCases.push({scale,...s});}
 }
 assert.deepStrictEqual(errors,[]);assert.equal(sha(fs.readFileSync(sourcePath)),report.testedSourceSha256,'Tested source must remain unchanged');
 report.status='PASS';report.requests=requests;report.errors=errors;report.vendorWarnings=warnings;
}catch(e){report.status='FAIL';report.error=String(e.stack||e);process.exitCode=1;}finally{if(browser)await browser.close();fs.writeFileSync(evidence+'/report.json',JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,variant,evidence,error:report.error,frames:report.frames.length}));}})();
