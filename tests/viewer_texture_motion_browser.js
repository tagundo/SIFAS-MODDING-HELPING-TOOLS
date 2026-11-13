/* Actual product HTTP, DOM, WebGL and Unity texture round trips. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), http = require('http'), net = require('net'), os = require('os'), path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');
const product = path.resolve(__dirname, '..'), repo = path.dirname(product);
const python = process.env.VIEWER_PYTHON || 'python3';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'texture-editors-e2e-'));
const library = fs.mkdtempSync(path.join(os.tmpdir(), 'texture-editors-library-')), models = path.join(library, 'extracted/3d_model');
const source = path.join(models, '001-texture-colors.unity'), originalPNG = path.join(evidence, 'original.png'), standalonePNG = path.join(evidence, 'standalone.png');
fs.mkdirSync(evidence, { recursive: true }); fs.mkdirSync(models, { recursive: true });
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const report = { status: 'RUNNING', scope: 'Actual product host Chromium/HTTP/serialized Unity; no native Android/Mac or original SIFAS playback claim', cases: [], evidence };
const sourceFiles = ['webtools/server.py', 'webtools/web/index.html', 'webtools/web/static/app.js', 'webtools/core/texture_image_io.py', 'webtools/core/viewer_texture_tools.py', 'webtools/core/model_edits.py', 'webtools/core/model_viewer.py', 'webtools/web/static/model-viewer.js', 'webtools/web/static/viewer-persistence.js', 'webtools/web/static/viewer-rig.js', 'webtools/web/static/viewer-texture-tools.js', 'webtools/web/static/viewer-texture-tools.css', 'webtools/web/static/texture-paint-engine.js', 'webtools/web/static/texture-color-math.js', 'webtools/web/static/texture-color-worker.js', 'webtools/web/static/texture-png.js', 'webtools/web/static/sifas-material.js'];
sourceFiles.push('webtools/web/static/viewer-signed-inputs.js', 'webtools/web/static/viewer-signed-inputs.css', 'tests/viewer_texture_motion_browser.js');
function sourceHashes() { return Object.fromEntries(sourceFiles.filter(n => fs.existsSync(path.join(product,n))).map(n => [n,sha(fs.readFileSync(path.join(product,n)))])); }
report.sourceBefore = sourceHashes();
function py(code, args = []) { return JSON.parse(execFileSync(python, ['-B', '-c', code, ...args], { cwd: product, env: {...process.env,PYTHONPATH: product + path.delimiter + repo}, encoding:'utf8', maxBuffer: 8*1024*1024 })); }
const fixture = py(`
import base64,json,struct,sys
from pathlib import Path
import UnityPy
from PIL import Image
env=UnityPy.load(Path('tests/fixtures/viewer_persistence.unity').read_bytes())
im=Image.new('RGBA',(16,16))
for y in range(16):
 for x in range(16):im.putpixel((x,y),(219-y*3,190-y*2,157-y,255) if x<8 else (17+y,70+y*2,210-y,255))
im.putpixel((15,14),(30,160,70,128));im.putpixel((15,15),(9,8,7,0))
im.save(sys.argv[2])
for obj in env.objects:
 if obj.type.name=='Texture2D':
  texture=obj.read();texture.image=im;texture.m_Name='ch0001_co0001_body';texture.save()
 elif obj.type.name=='Mesh':
  tree=obj.read_typetree();tree['m_IndexBuffer']=struct.pack('<9H',0,1,2,1,3,2,3,4,5);tree['m_SubMeshes'][0]['indexCount']=9;obj.save_typetree(tree)
Path(sys.argv[1]).write_bytes(env.file.save(packer='original'))
standalone=im.copy();standalone.putpixel((0,0),(90,20,210,80));standalone.save(sys.argv[3])
print(json.dumps({'width':16,'height':16,'rgba':list(im.tobytes()),'standalone':list(standalone.tobytes())}))
`, [source, originalPNG, standalonePNG]);
const originalSourceSHA = sha(fs.readFileSync(source));
const pickerPNG=path.join(library,'extracted/textures/picked.png');fs.mkdirSync(path.dirname(pickerPNG),{recursive:true});fs.copyFileSync(standalonePNG,pickerPNG);
async function startServer() {
  const s=net.createServer();await new Promise(resolve=>s.listen(0,'127.0.0.1',resolve));const port=s.address().port;await new Promise(resolve=>s.close(resolve));
  const log=fs.createWriteStream(path.join(evidence,'server.log'));
  const child=spawn(python,['-B','-m','webtools','--no-browser','--host','127.0.0.1','--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:product+path.delimiter+repo,SUKUSTA_DIR:library},stdio:['ignore','pipe','pipe']});
  child.stdout.pipe(log);child.stderr.pipe(log);const url='http://127.0.0.1:'+port;
  for(let i=0;i<150;i++){if(child.exitCode!==null)throw new Error('Product server exited');try{if((await fetch(url+'/api/tools')).ok)return{url,child,log};}catch(_){}await wait(100);}child.kill();throw new Error('Server did not become ready');
}

const motion = path.join(models, 'one-motion.unity');
py(`import json,sys,UnityPy;from pathlib import Path
v=UnityPy.load(Path(sys.argv[1]).read_bytes())
for obj in list(v.objects):
 if obj.type.name!='AnimationClip':del obj.assets_file.objects[obj.path_id]
 else:
  tree=obj.read_typetree();tree['m_Name']='Texture retention motion';obj.save_typetree(tree)
Path(sys.argv[2]).write_bytes(v.file.save(packer='original'))
print(json.dumps({'saved':True}))`,[source,motion]);
const originalMotionSHA=sha(fs.readFileSync(motion));
const face=path.join(models,'face-texture-colors.unity');
if(process.env.MULTI_SOURCE==='1')py(`import json,sys,UnityPy;from pathlib import Path
v=UnityPy.load(Path(sys.argv[1]).read_bytes())
for obj in v.objects:
 if obj.type.name in ('Mesh','Material','Texture2D'):
  t=obj.read_typetree();t['m_Name']='Face' if obj.type.name=='Mesh' else 'ch0001_co0001_face';obj.save_typetree(t)
Path(sys.argv[2]).write_bytes(v.file.save(packer='original'));print(json.dumps({'saved':True}))`,[source,face]);

const originalFaceSHA=fs.existsSync(face)?sha(fs.readFileSync(face)):null;
async function show(page, selector) { const target=page.locator(selector);await target.evaluate(e=>{for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;});await target.scrollIntoViewIfNeeded();return target; }
async function frames(page) { await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))); }
async function idle(page) { await page.waitForFunction(()=>{const t=ModelViewer.getTextureTools();return t&&!t.getState().pending&&!t.getState().loading;});await frames(page); }
function canonicalShaderRows(rows) {
 const stable=value=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.keys(value).sort().map(key=>[key,stable(value[key])])):Array.isArray(value)?value.map(stable):value;
 return rows.slice().sort((left,right)=>JSON.stringify(stable(left)).localeCompare(JSON.stringify(stable(right))));
}
// Traversal order is not material identity. Equal source records remain a
// multiset: neither duplicate surfaces nor a changed RGBA value may disappear.
{
 const a={binding:{mesh:{source:0,file:0,id:'7'},material:0},name:'same label',identity:null,rgba:[1,2,3,255]},b={binding:{mesh:{source:1,file:0,id:'7'},material:0},name:'same label',identity:null,rgba:[9,8,7,255]};
 assert.deepStrictEqual(canonicalShaderRows([a,b,a]),canonicalShaderRows([b,a,a]));
 assert.equal(canonicalShaderRows([a,b,a]).length,3);
 assert.notDeepStrictEqual(canonicalShaderRows([a,b]),canonicalShaderRows([b,a,a]));
 assert.notDeepStrictEqual(canonicalShaderRows([a,b,a]),canonicalShaderRows([a,b,{...a,rgba:[1,2,4,255]}]));
}
async function snapshot(page) { const result=await page.evaluate(()=>{
 const t=ModelViewer.getTextureTools(), documents=t.captureDocuments(true), edits=t.getEdits(), state=t.getState(), shaders=[];
 const identity=value=>value?{source:value.source,file:value.file,id:String(value.id)}:null;
 __textureObserved.scene.traverse(mesh=>{if(!mesh.isMesh||mesh.userData&&mesh.userData.viewerHelper)return;const provenance=mesh.geometry&&mesh.geometry.userData&&mesh.geometry.userData.viewerMesh||mesh.userData&&mesh.userData.viewerMesh, materials=Array.isArray(mesh.material)?mesh.material:[mesh.material];for(const [slot,material] of materials.entries()){
  if(material.uniforms&&material.uniforms.uMainTex){const texture=material.uniforms.uMainTex.value;shaders.push({binding:{mesh:identity(provenance&&provenance.mesh),renderer:identity(provenance&&provenance.rendererIdentity),submesh:provenance&&provenance.submesh,material:slot},name:mesh.name,identity:identity(texture.userData&&texture.userData.viewerTexture),rgba:texture.image&&texture.image.data?Array.from(texture.image.data):null});}
 }});
 return {edits,sourceSha256:state.sourceSha256,state,viewer:ModelViewer.getState(),sourceFlags:{autoFace:document.getElementById('viewer-auto-face').checked,includeFace:document.getElementById('viewer-mod-include-face').checked,catalogue:ModelViewer.getEditingMetadata().textures.textures},documents:{activeTexture:documents.activeTexture,documents:documents.documents.map(d=>({texture:d.texture,sourceSha256:d.sourceSha256,png:d.png,modified:d.modified,kind:d.kind,mask:d.mask&&Array.from(d.mask),project:d.project&&{...d.project,layers:d.project.layers.map(l=>({...l,image:{...l.image,data:Array.from(l.image.data)}}))}}))},shaders};
 }); result.shaderTraversal=result.shaders.map(row=>row.binding);result.shaders=canonicalShaderRows(result.shaders);return result; }
async function main(){let server,browser,page;const errors=[];
 try{
  server=await startServer();browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1480,height:1100},hasTouch:true});await context.addInitScript(()=>localStorage.setItem('sifas_lang','en'));
  page=await context.newPage();page.setDefaultTimeout(45000);page.on('pageerror',e=>errors.push(String(e.stack||e)));
  await page.route('**/static/viewer-quality.js',async route=>{const response=await route.fetch(),body=await response.text();await route.fulfill({response,body:body+'\n(()=>{const create=ViewerQuality.create;ViewerQuality.create=function(){const renderer=arguments[0],c=create.apply(this,arguments),render=c.render;c.render=function(scene,camera){window.__textureObserved={scene,camera,renderer};return render.apply(this,arguments);};return c;};})();'});});
  if(process.env.BASELINE_STATIC){report.baselineOverrides={};for(const name of ['model-viewer.js','viewer-texture-tools.js']){const data=fs.readFileSync(path.join(process.env.BASELINE_STATIC,name));report.baselineOverrides[name]=sha(data);await page.route('**/static/'+name,route=>route.fulfill({status:200,contentType:'application/javascript',body:data}));}}
  if(process.env.NO_BOUND_TOKEN==='1')await page.route('**/api/viewer/prepare',async route=>{const r=await route.fetch(),d=await r.json();d.editing.available=false;await route.fulfill({response:r,json:d});});
  await page.goto(server.url);await page.waitForFunction(()=>window.ModelViewer&&ModelViewer.getTextureTools&&ModelViewer.getTextureTools());
  if(process.env.NO_BOUND_TOKEN==='1')await page.evaluate(()=>document.documentElement.dataset.noBoundToken='true');
  await page.evaluate(sources=>{document.getElementById('viewer-auto-face').checked=false;return openModelViewer(sources);},process.env.MULTI_SOURCE==='1'?[source,face]:[source]);
  await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading&&(ModelViewer.getEditingMetadata().available||document.documentElement.dataset.noBoundToken==='true')&&window.__textureObserved);
  if(process.env.NO_BOUND_TOKEN==='1'){
   assert.equal(await page.evaluate(()=>ModelViewer.getTextureTools().getState().token),null);
   await page.evaluate(async rgba=>{const png=await TexturePNG.encodeRGBA({width:16,height:16,data:new Uint8ClampedArray(rgba)}),response=await fetch('/api/texture/editor/decode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({png})});ModelViewer.getTextureTools().openImage(await response.json(),'standalone.png');},fixture.rgba);await idle(page);
   await (await show(page,'#viewer-texture-paint-tool')).selectOption('brush');await page.locator('#viewer-texture-paint-color').evaluate(e=>{e.value='#20e060';e.dispatchEvent(new Event('input',{bubbles:true}));});
   const c=page.locator('#viewer-texture-canvas-host canvas').filter({visible:true});await c.scrollIntoViewIfNeeded();const b=await c.boundingBox(),v=await page.evaluate(()=>ModelViewer.getTextureTools().getState().selection.view);await page.mouse.click(b.x+v.x+4.5*v.zoom,b.y+v.y+4.5*v.zoom);await idle(page);
   const before=await page.evaluate(()=>({state:ModelViewer.getTextureTools().getState(),project:ModelViewer.getTextureTools().getProject(),modelId:ModelViewer.getState().modelId}));assert(before.state.standalone&&before.state.selection.undoCount>0);
   await page.evaluate(file=>ModelViewer.addMotion([file]),motion);await page.waitForFunction(()=>!ModelViewer.getState().loading);await idle(page);
   const after=await page.evaluate(()=>({state:ModelViewer.getTextureTools().getState(),project:ModelViewer.getTextureTools().getProject(),modelId:ModelViewer.getState().modelId}));assert.equal(after.state.token,null);assert(after.state.standalone);assert.equal(after.state.selection.undoCount,before.state.selection.undoCount);assert.deepStrictEqual(after.project,before.project);assert.notEqual(after.modelId,before.modelId);
   report.cases.push({name:'Non-editable rig with no model texture token still imports a real clip and preserves standalone image/history',before:before.state,after:after.state});report.status='PASS';return;
  }
  await (await show(page,'#viewer-texture-select')).selectOption({index:1});await idle(page);
  await (await show(page,'#viewer-shader')).selectOption('sifas');await (await show(page,'#viewer-high-quality')).check();await frames(page);
  if(process.env.MULTI_SOURCE==='1'){
   await (await show(page,'#viewer-texture-select')).selectOption({index:2});await idle(page);await page.evaluate(()=>ModelViewer.getTextureTools().setTab('paint'));
   await (await show(page,'#viewer-texture-paint-tool')).selectOption('brush');await page.locator('#viewer-texture-paint-color').evaluate(e=>{e.value='#20e060';e.dispatchEvent(new Event('input',{bubbles:true}));});
   const c=page.locator('#viewer-texture-canvas-host canvas').filter({visible:true});await c.scrollIntoViewIfNeeded();const b=await c.boundingBox(),v=await page.evaluate(()=>ModelViewer.getTextureTools().getState().selection.view);await page.mouse.click(b.x+v.x+4.5*v.zoom,b.y+v.y+4.5*v.zoom);await idle(page);
   await (await show(page,'#viewer-texture-select')).selectOption({index:1});await idle(page);
  }
  await page.evaluate(()=>ModelViewer.getTextureTools().setTab('skin'));
  await (await show(page,'#viewer-texture-selection-tool')).selectOption('select-rectangle');
  const canvas=page.locator('#viewer-texture-canvas-host canvas').filter({visible:true});await canvas.scrollIntoViewIfNeeded();const box=await canvas.boundingBox(),view=await page.evaluate(()=>ModelViewer.getTextureTools().getState().selection.view);
  await page.mouse.move(box.x+view.x,box.y+view.y);await page.mouse.down();await page.mouse.move(box.x+view.x+8*view.zoom,box.y+view.y+16*view.zoom,{steps:8});await page.mouse.up();await idle(page);
  await (await show(page,'#viewer-texture-source-tone')).selectOption('default');await (await show(page,'#viewer-texture-target-tone')).selectOption('bright');
  await page.evaluate(()=>ModelViewer.getTextureTools().preparePreview());await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);
  await (await show(page,'#viewer-texture-apply')).click();await idle(page);
  const before=await snapshot(page);assert.equal(before.edits.length,process.env.MULTI_SOURCE==='1'?2:1);assert.equal(before.edits[0].kind,'skin');assert(before.state.selection.undoCount>0);assert(before.shaders.some(s=>s.rgba),'actual SIFAS material must use the edited DataTexture before import');
  report.before=before;await page.screenshot({path:path.join(evidence,'before-motion.png')});
  const restoreRequests=[];page.on('request',r=>{if(/\/api\/viewer\/texture\/(data|decode)$/.test(r.url()))restoreRequests.push(r.url());});
  if(process.env.FAULT_TEXTURE_RESTORE==='1')await page.route(/\/api\/viewer\/texture\/(data|decode)$/,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Controlled texture reload outage'})}));
  report.motionResult=await page.evaluate(async motion=>{try{await ModelViewer.addMotion([motion]);return{ok:true};}catch(error){return{ok:false,error:String(error.stack||error)};}},motion);
  await page.waitForFunction(()=>!ModelViewer.getState().loading);await idle(page);const after=await snapshot(page);report.after=after;await page.screenshot({path:path.join(evidence,'after-motion.png')});
  assert(report.motionResult.ok,report.motionResult.error);assert.deepStrictEqual(after.edits,before.edits,'one motion import must retain the exact committed PNG recipe and skin source identity');assert.deepStrictEqual(after.shaders,before.shaders,'rebuilt 3D materials must keep the exact applied skin pixels');
  assert.deepStrictEqual(after.documents,before.documents,'motion-only import retains every layer, mask, active source and committed pixel document');assert.equal(after.state.selection.undoCount,before.state.selection.undoCount,'motion-only import preserves texture Undo history');assert.equal(after.state.selection.redoCount,before.state.selection.redoCount,'motion-only import preserves texture Redo history');
  assert(after.viewer.motionLibraryPaths.includes(motion));assert.deepStrictEqual(after.viewer.loadedPaths,before.viewer.loadedPaths);assert.deepStrictEqual(errors,[]);
  assert.equal(restoreRequests.length,0,'motion-only import must reuse exact committed pixels without fresh data/decode transport');
  report.restoreRequests=restoreRequests;
  report.cases.push({name:'Apply real skin-only bright tone then add exactly one real AnimationClip; exact recipe/layers/mask/shader/undo preserved'});
  const retained=(a,b,label)=>{assert.deepStrictEqual(b.edits,a.edits,label+' PNG/source recipe');assert.deepStrictEqual(b.documents,a.documents,label+' exact editable layers/mask');assert.deepStrictEqual(b.shaders,a.shaders,label+' actual3D texture');assert.deepStrictEqual(b.sourceFlags,a.sourceFlags,label+' exact body/face source flags');assert.equal(b.state.selection.undoCount,a.state.selection.undoCount,label+' Undo');assert.equal(b.state.selection.redoCount,a.state.selection.redoCount,label+' Redo');};
  await page.evaluate(()=>ModelViewer.getTextureTools().setTab('paint'));await (await show(page,'#viewer-texture-layer-add')).click();await idle(page);
  await (await show(page,'#viewer-texture-paint-tool')).selectOption('brush');
  for(const [id,value] of [['viewer-texture-paint-color','#ff0000'],['viewer-texture-brush-size','2'],['viewer-texture-opacity','100'],['viewer-texture-softness','0']])await page.locator('#'+id).evaluate((e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));},value);
  await canvas.scrollIntoViewIfNeeded();const paintBox=await canvas.boundingBox(),paintView=await page.evaluate(()=>ModelViewer.getTextureTools().getState().selection.view);await page.mouse.click(paintBox.x+paintView.x+3.5*paintView.zoom,paintBox.y+paintView.y+5.5*paintView.zoom);await idle(page);
  const painted=await snapshot(page);assert.equal(painted.state.selection.layers.length,2);assert.notDeepStrictEqual(painted.edits,after.edits,'actual brush adds independently editable pixels');
  await (await show(page,'#viewer-texture-undo')).click();await idle(page);const pendingRedo=await snapshot(page);assert(pendingRedo.state.selection.redoCount>0);
  await (await show(page,'#viewer-clear-motion-library')).click();await page.waitForFunction(()=>!ModelViewer.getState().loading&&!ModelViewer.getState().loadedMotionPaths.length);await idle(page);
  const removed=await snapshot(page);retained(pendingRedo,removed,'remove motion with painted layer and Redo');
  await (await show(page,'#viewer-texture-redo')).click();await idle(page);const redone=await snapshot(page);assert.deepStrictEqual(redone.edits,painted.edits,'retained Redo restores exact pre-motion brush PNG');assert.deepStrictEqual(redone.shaders,painted.shaders,'retained Redo updates actual shader');
  report.cases.push({name:'Painted layer plus pending Redo survive actual motion-list clear; Redo restores exact PNG/3D pixels',before:pendingRedo.state.selection,after:removed.state.selection});
  await page.evaluate(()=>ModelViewer.getTextureTools().setTab('costume'));await (await show(page,'#viewer-texture-hue')).evaluate(e=>{e.value='45';e.dispatchEvent(new Event('input',{bubbles:true}));});
  await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);await (await show(page,'#viewer-texture-apply')).click();await idle(page);
  const costume=await snapshot(page);assert.equal(costume.edits[0].kind,'costume');assert.notDeepStrictEqual(costume.edits,redone.edits,'real OKLCH color operation changes active painted layer');
  await page.evaluate(file=>ModelViewer.addMotion([file]),motion);await page.waitForFunction(()=>!ModelViewer.getState().loading);await idle(page);const recolored=await snapshot(page);retained(costume,recolored,'costume color and painted layer one-motion add');
  report.cases.push({name:'Real OKLCH costume color and full painted-layer history survive one-motion addition'});
  await (await show(page,'#viewer-clear-motion-library')).click();await page.waitForFunction(()=>!ModelViewer.getState().loading&&!ModelViewer.getState().loadedMotionPaths.length);await idle(page);const intact=await snapshot(page);
  await page.route('**/api/viewer/prepare',async route=>{const r=await route.fetch(),d=await r.json();if(d.editing&&d.editing.textures)for(const t of d.editing.textures.textures)t.sourceSha256='0'.repeat(64);await route.fulfill({response:r,json:d});});
  const rejected=await page.evaluate(async file=>{try{await ModelViewer.addMotion([file]);return{accepted:true};}catch(error){return{accepted:false,message:error.message};}},motion);await page.unroute('**/api/viewer/prepare');await idle(page);const refused=await snapshot(page);
  report.refusal={rejected,intactModelId:intact.viewer.modelId,afterModelId:refused.viewer.modelId};assert(!rejected.accepted&&/texture source changed/i.test(rejected.message));retained(intact,refused,'changed source catalogue refusal');assert.equal(refused.viewer.modelId,intact.viewer.modelId,'invalid next catalogue must not replace the current model');
  report.cases.push({name:'Changed original-texture hash is refused before model replacement; current exact pixels/layers/Undo/Redo remain',rejected});
  await page.route('**/api/viewer/prepare',async route=>{const r=await route.fetch(),d=await r.json();d.editing.available=false;await route.fulfill({response:r,json:d});});
  const unavailable=await page.evaluate(async file=>{try{await ModelViewer.addMotion([file]);return{accepted:true};}catch(error){return{accepted:false,message:error.message};}},motion);await page.unroute('**/api/viewer/prepare');await idle(page);const unavailableState=await snapshot(page);retained(intact,unavailableState,'unavailable next texture editor refusal');assert(!unavailable.accepted&&/texture editor is unavailable/i.test(unavailable.message));assert.equal(unavailableState.viewer.modelId,intact.viewer.modelId);report.cases.push({name:'Prepared editor unavailable despite a token rejects before disposal when real texture documents exist',unavailable});
  report.status='PASS';
 }catch(error){report.status='FAIL';report.error=String(error.stack||error);report.pageErrors=errors;throw error;}
 finally{report.sourceAfter=sourceHashes();report.originalSourceUnchanged=sha(fs.readFileSync(source))===originalSourceSHA;report.originalMotionUnchanged=sha(fs.readFileSync(motion))===originalMotionSHA;report.originalFaceUnchanged=originalFaceSHA===null||sha(fs.readFileSync(face))===originalFaceSHA;fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2));if(browser)await browser.close();if(server){server.child.kill();await wait(200);server.log.end();}fs.rmSync(library,{recursive:true,force:true});console.log(JSON.stringify({status:report.status,evidence,error:report.error}));}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
