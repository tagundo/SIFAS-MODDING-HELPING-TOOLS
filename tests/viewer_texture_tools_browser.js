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
sourceFiles.push('webtools/web/static/viewer-signed-inputs.js', 'webtools/web/static/viewer-signed-inputs.css');
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
async function show(page, selector) { const target=page.locator(selector);await target.evaluate(e=>{for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;});await target.scrollIntoViewIfNeeded();return target; }
async function frames(page) { await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))); }
// Scroll strips deliberately keep off-screen tools in the DOM. Measure actual
// ancestor clipping, then prove every strip tool becomes fully usable by scroll.
function visibleTextureControls(root) {
  const controls = [...root.querySelectorAll('button,input,select')].map(e => {
    const r = e.getBoundingClientRect(); if (!r.width || !r.height) return null;
    let left = r.left, right = r.right, top = r.top, bottom = r.bottom;
    for (let p = e.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
      const style = getComputedStyle(p), box = p.getBoundingClientRect();
      if (/auto|scroll|hidden|clip/.test(style.overflowX)) { left = Math.max(left, box.left); right = Math.min(right, box.right); }
      if (/auto|scroll|hidden|clip/.test(style.overflowY)) { top = Math.max(top, box.top); bottom = Math.min(bottom, box.bottom); }
    }
    if (right - left <= 1 || bottom - top <= 1) return null;
    const strip = !!e.closest('.viewer-texture-tool-rail'), hit = document.elementFromPoint((left + right) / 2, (top + bottom) / 2);
    return { id: e.id, strip, left: strip ? left : r.left, right: strip ? right : r.right, top, bottom, reachable: hit === e || e.contains(hit) };
  }).filter(Boolean);
  return { width: root.clientWidth, scroll: root.scrollWidth, controls };
}
async function reachableTextureRail(page) {
  const buttons = page.locator('#viewer-texture-tools .viewer-texture-tool-rail > button'), rows = [];
  const minimum = await page.evaluate(() => matchMedia('(pointer: coarse)').matches || innerWidth <= 600 ? 44 : 32);
  assert(await buttons.count() >= 8, 'the complete texture tool strip is present');
  for (let i = 0; i < await buttons.count(); i++) {
    const button = buttons.nth(i); await button.scrollIntoViewIfNeeded(); await frames(page);
    const row = await button.evaluate(e => { const r = e.getBoundingClientRect(), hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return { tool: e.dataset.textureTool, x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height, viewport: { width: innerWidth, height: innerHeight }, reachable: hit === e || e.contains(hit) }; });
    assert(row.x >= -1 && row.y >= -1 && row.right <= row.viewport.width + 1 && row.bottom <= row.viewport.height + 1, 'scrolling brings each tool fully into the viewport: ' + JSON.stringify(row));
    assert(row.reachable && row.width >= minimum && row.height >= minimum, 'each scroll-strip tool has a full-size actual pointer target: ' + JSON.stringify(row)); rows.push(row);
  }
  return rows;
}
async function toolsState(page) { return page.evaluate(()=>ModelViewer.getTextureTools().getState()); }
async function idle(page) { await page.waitForFunction(()=>{const t=ModelViewer.getTextureTools();return t&&!t.getState().pending&&!t.getState().loading;});await frames(page); }
async function setField(page,id,value,event='input') { await page.locator(id).evaluate((e,args)=>{e.value=String(args.value);e.dispatchEvent(new Event(args.event,{bubbles:true}));},{value,event}); }
async function decodedPNG(data) { return py("import base64,io,json,sys;from PIL import Image;im=Image.open(io.BytesIO(base64.b64decode(sys.argv[1].split(',',1)[-1]))).convert('RGBA');print(json.dumps({'width':im.width,'height':im.height,'rgba':list(im.tobytes())}))",[data]); }
async function pixels(page) {
  const rows=await page.evaluate(()=>ModelViewer.getTextureTools().getEdits());
  return rows.length ? (await decodedPNG(rows[0].png)).rgba : fixture.rgba.slice();
}
async function shaderState(page) {
  return page.evaluate(()=>{
    const result=[];__textureObserved.scene.traverse(mesh=>{if(!mesh.isMesh||mesh.userData&&mesh.userData.viewerHelper)return;const materials=Array.isArray(mesh.material)?mesh.material:[mesh.material];for(const material of materials){if(material.uniforms&&material.uniforms.uMainTex){const texture=material.uniforms.uMainTex.value;result.push({mesh:mesh.name,shader:true,dataTexture:!!texture.isDataTexture,width:texture.image&&texture.image.width,height:texture.image&&texture.image.height,rgba:texture.image&&texture.image.data?Array.from(texture.image.data):null});}}});return{materials:ModelViewer.getState().materials,shaders:result};
  });
}
function changedInterior(before, after) {
  const changed = i => after[i*4+3]===255 && [0,1,2].some(c=>after[i*4+c]!==before[i*4+c]);
  for(let y=1;y<15;y++)for(let x=1;x<15;x++){
    if([-17,-16,-15,-1,0,1,15,16,17].every(delta=>changed(y*16+x+delta)))return{point:[x+.5,y+.5],offset:(y*16+x)*4};
  }
  throw new Error('The fixture must expose a changed, opaque interior pixel independently of selection overlays');
}
async function selectionDisplay(page, pixel) {
  await frames(page);
  return page.evaluate(pixel => {
    const tools = ModelViewer.getTextureTools(), state = tools.getState(), checkbox = document.getElementById('viewer-texture-show-selection');
    const label = checkbox.parentElement, box = label.getBoundingClientRect(), hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    let overlays = 0; __textureObserved.scene.traverse(mesh => { if (mesh.userData && mesh.userData.viewerTextureSelection) overlays++; });
    const canvas = [...document.querySelectorAll('#viewer-texture-canvas-host canvas')].find(c => c.getClientRects().length), view = state.selection.view;
    const ratio = Math.min(2, devicePixelRatio || 1), point = pixel || [4.5, 7.5];
    const rgba = Array.from(canvas.getContext('2d').getImageData(Math.floor((view.x + point[0] * view.zoom) * ratio), Math.floor((view.y + point[1] * view.zoom) * ratio), 1, 1).data);
    return { checked: checkbox.checked, engineVisible: state.selection.selectionVisible, selectedPixels: state.selection.selectedPixels,
      selectionRevision: state.selection.selectionRevision, undoCount: state.selection.undoCount, revision: state.selection.revision, overlays, rgba,
      directlyBesideCanvas: !!label.closest('.viewer-texture-color-actions') && !label.closest('.viewer-texture-menu-body') && Math.max(0, box.top - canvas.getBoundingClientRect().bottom) <= 120,
      label: { width: box.width, height: box.height, hit: hit === label || label.contains(hit) }, information: document.getElementById('viewer-texture-info').textContent };
  }, pixel);
}
async function modelFrame(page) {
  return page.evaluate(() => {
    ModelViewer.renderProbe();
    const gl = __textureObserved.renderer.getContext(), width = gl.drawingBufferWidth, height = gl.drawingBufferHeight, pixels = new Uint8Array(width * height * 4);
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let hash = 2166136261; for (const value of pixels) hash = Math.imul(hash ^ value, 16777619) >>> 0;
    return { hash, width, height, glError: gl.getError() };
  });
}
async function facePoint(page,face=0) {
  await page.locator('#viewer-stage').scrollIntoViewIfNeeded();await frames(page);
  return page.evaluate(face=>{
    const observed=__textureObserved;observed.scene.updateMatrixWorld(true);observed.camera.updateMatrixWorld(true);
    let target;observed.scene.traverse(mesh=>{if(!target&&mesh.isMesh&&mesh.geometry&&mesh.geometry.attributes.uv&&!(mesh.userData&&mesh.userData.viewerHelper)&&(mesh.geometry.userData.viewerMesh||mesh.userData.viewerMesh))target=mesh;});
    if(!target)throw new Error('No actual writable mesh was rendered');window.__textureTarget=target;
    const idx=target.geometry.index,position=target.geometry.attributes.position,points=[];
    for(let i=0;i<3;i++){const vertex=idx?idx.getX(face*3+i):face*3+i,v=new THREE.Vector3().fromBufferAttribute(position,vertex);if(target.isSkinnedMesh)target.boneTransform(vertex,v);v.applyMatrix4(target.matrixWorld).project(observed.camera);points.push(v);}
    const rect=document.querySelector('#viewer-stage canvas').getBoundingClientRect();
    return{x:rect.left+(points.reduce((v,p)=>v+p.x/3,0)+1)*rect.width/2,y:rect.top+(1-points.reduce((v,p)=>v+p.y/3,0))*rect.height/2,name:target.name};
  },face);
}
async function selectPixelRect(page, left,top,right,bottom) {
  await (await show(page,'#viewer-texture-selection-tool')).selectOption('select-rectangle');
  const canvas=page.locator('#viewer-texture-canvas-host canvas').filter({visible:true});
  await canvas.scrollIntoViewIfNeeded();const box=await canvas.boundingBox();const view=(await toolsState(page)).selection.view;
  await page.mouse.move(box.x+view.x+left*view.zoom,box.y+view.y+top*view.zoom);await page.mouse.down();
  await page.mouse.move(box.x+view.x+right*view.zoom,box.y+view.y+bottom*view.zoom,{steps:8});await page.mouse.up();await idle(page);
}
async function clickPixel(page,x,y) {
  const canvas=page.locator('#viewer-texture-canvas-host canvas').filter({visible:true});await canvas.scrollIntoViewIfNeeded();
  const box=await canvas.boundingBox(),view=(await toolsState(page)).selection.view;
  await page.mouse.click(box.x+view.x+x*view.zoom,box.y+view.y+y*view.zoom);await idle(page);
}
async function saveModel(page,mod=false) {
  if(mod){await setField(page,'#viewer-mod-name','Texture and body QA','change');await (await show(page,'#viewer-mod-thumbnail-mode')).selectOption('texture');}
  await (await show(page,mod?'#viewer-save-mod':'#viewer-save')).click();
  await page.waitForFunction(mod=>{const p=ModelViewer.getState().persistence;return !p.busy&&(p.error||(mod?p.modPackage&&p.modPackage.packagePath:p.recipePath));},mod);
  const p=await page.evaluate(()=>ModelViewer.getState().persistence);assert(!p.error,p.error);return p;
}
function bundlePixels(file) {
  return py(`import io,json,sys,zipfile,UnityPy
from pathlib import Path
p=Path(sys.argv[1]);data=p.read_bytes()
if zipfile.is_zipfile(io.BytesIO(data)):
 z=zipfile.ZipFile(io.BytesIO(data));rows=[]
 for name in z.namelist():
  if name.endswith('.unity'):
   rows.extend(UnityPy.load(z.read(name)).objects)
else: rows=UnityPy.load(data).objects
result=[]
for obj in rows:
 if obj.type.name=='Texture2D':
  v=obj.read();im=v.image.convert('RGBA');result.append({'name':v.m_Name,'width':im.width,'height':im.height,'rgba':list(im.tobytes())})
print(json.dumps(result))`,[file]);
}
async function importRecipe(page,recipePath){
 await (await show(page,'#viewer-recipe-open')).click();await page.waitForFunction(()=>!document.getElementById('picker').classList.contains('hidden'));
 await page.evaluate(directory=>navigate(directory),path.dirname(recipePath));await page.waitForFunction(directory=>document.getElementById('picker-crumb').textContent===directory,path.dirname(recipePath));
 await page.locator('#picker-entries li').filter({hasText:path.basename(recipePath)}).click();await page.waitForFunction(()=>document.getElementById('picker').classList.contains('hidden'));
 await page.waitForFunction(()=>{const p=ModelViewer.getState().persistence;return !p.busy&&(p.error||p.status==='restored');});const p=await page.evaluate(()=>ModelViewer.getState().persistence);assert(!p.error,p.error);await idle(page);
}
async function pickPNG(page,file){
 const originalPickerZ=await page.locator('#picker').evaluate(el=>el.style.zIndex);
 await (await show(page,'#viewer-texture-import')).click();await page.waitForFunction(()=>!document.getElementById('picker').classList.contains('hidden'));
 await page.evaluate(directory=>navigate(directory),path.dirname(file));await page.waitForFunction(directory=>document.getElementById('picker-crumb').textContent===directory,path.dirname(file));
 const entry=page.locator('#picker-entries li').filter({hasText:path.basename(file)});await entry.scrollIntoViewIfNeeded();const pickerHit=await entry.evaluate(el=>{const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return{reachable:hit===el||el.contains(hit),hit:hit&&{id:hit.id,tag:hit.tagName},expanded:ModelViewer.getTextureTools().getState().expanded};});assert(pickerHit.reachable,'the PNG picker file entry receives pointer hits above expanded editors');await entry.click();await page.waitForFunction(()=>document.getElementById('picker').classList.contains('hidden'));await idle(page);assert.equal(await page.locator('#picker').evaluate(el=>el.style.zIndex),originalPickerZ,'PNG picker restores its original stacking style after selection');return pickerHit;
}
async function declaredOversize(url){
 return new Promise((resolve,reject)=>{const request=http.request(url,{method:'POST',headers:{'Content-Type':'application/json','Content-Length':String(64*1024*1024),'Connection':'close'}},response=>{let body='';response.on('data',chunk=>body+=chunk);response.on('end',()=>resolve({status:response.statusCode,body}));});request.on('error',reject);request.setTimeout(5000,()=>request.destroy(new Error('Oversized request was not rejected before reading its body')));request.end('{}');});
}
async function clearEdits(page){await page.evaluate(()=>ModelViewer.restoreAuthoringState({version:1,savedSettingsEnabled:true,edits:[],unsupported:[],textures:[]}));await idle(page);await page.evaluate(()=>ModelViewer.getTextureTools().cancelPreview());await idle(page);}
function differentPixels(left,right){let n=0;for(let p=0;p<left.length;p+=4)if(left.slice(p,p+4).some((v,k)=>v!==right[p+k]))n++;return n;}
async function main(){let server,browser,context,androidContext,page;const errors=[];
 try{
  server=await startServer();browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  context=await browser.newContext({viewport:{width:1480,height:1100},hasTouch:true});await context.addInitScript(()=>localStorage.setItem('sifas_lang','en'));
  page=await context.newPage();page.setDefaultTimeout(45000);page.on('pageerror',e=>errors.push(String(e.stack||e)));
  await page.route('**/static/viewer-quality.js',async route=>{const response=await route.fetch(),body=await response.text();await route.fulfill({response,body:body+'\n(()=>{const create=ViewerQuality.create;ViewerQuality.create=function(){const renderer=arguments[0],c=create.apply(this,arguments),render=c.render;c.render=function(scene,camera){window.__textureObserved={scene,camera,renderer};return render.apply(this,arguments);};return c;};})();'});});
  await page.goto(server.url);await page.waitForFunction(()=>window.ModelViewer&&ModelViewer.getTextureTools&&ModelViewer.getTextureTools());
  await page.evaluate(source=>{document.getElementById('viewer-auto-face').checked=false;return openModelViewer([source]);},source);
  await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading&&ModelViewer.getEditingMetadata().available&&window.__textureObserved);
  await (await show(page,'#viewer-texture-select')).selectOption({index:1});await idle(page);
  const initial=await toolsState(page);assert.equal(initial.textureCount,1);assert.equal(initial.selection.width,16);assert.equal(initial.selection.height,16);assert.equal(initial.editedTextures.length,0);assert.equal(initial.selection.selectedPixels,0);
  const sourceData=await page.evaluate(async()=>{const state=ModelViewer.getTextureTools().getState();return(await fetch('/api/viewer/texture/data',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:state.token,texture:state.activeTexture})})).json();});
  assert.deepStrictEqual((await decodedPNG(sourceData.image)).rgba,fixture.rgba,'backend returns exact straight-alpha original pixels');
  report.cases.push({name:'actual model catalogue and lossless source texture decode',initial});
  await page.screenshot({path:path.join(evidence,'initial-tools.png')});
  await (await show(page,'#viewer-shader')).selectOption('sifas');await (await show(page,'#viewer-high-quality')).check();await frames(page);
  await (await show(page,'#viewer-texture-scene-mode')).selectOption('face');
  let hit=await facePoint(page);report.hit=hit;await page.mouse.click(hit.x,hit.y);await wait(300);
  report.hitDiagnostics=await page.evaluate(hit=>{const dom=document.querySelector('#viewer-stage canvas'),rect=dom.getBoundingClientRect(),ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((hit.x-rect.left)/rect.width*2-1,1-(hit.y-rect.top)/rect.height*2),__textureObserved.camera);return{state:ModelViewer.getTextureTools().getState(),elements:document.elementsFromPoint(hit.x,hit.y).map(e=>({id:e.id,tag:e.tagName})),hits:ray.intersectObject(__textureObserved.scene,true).map(h=>({name:h.object.name,face:h.faceIndex,uv:h.uv&&h.uv.toArray(),helper:h.object.userData.viewerHelper})).slice(0,6)};},hit);
  await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().selection.selectedPixels>0);await idle(page);
  const single=await toolsState(page);assert(single.selection.selectionActive&&single.selection.selectedPixels>0);
  await (await show(page,'#viewer-texture-scene-mode')).selectOption('connected');hit=await facePoint(page);await page.mouse.click(hit.x,hit.y);await idle(page);
  const connected=await toolsState(page);assert(connected.selection.selectedPixels>single.selection.selectedPixels,'actual connected-face pick expands the selected source region');
  const observed=await page.evaluate(()=>{let count=0;__textureObserved.scene.traverse(o=>{if(o.userData&&o.userData.viewerTextureSelection)count++;});return{overlays:count,faces:ModelViewer.getTextureTools().getState().lastModelSelection||null};});
  assert(observed.overlays>0&&connected.performance.maskOverlays>0,'actual 3D mesh selection overlay exists');
  if(observed.faces)assert.deepStrictEqual(observed.faces.faces,[0,1],'a vertex-only touching island is not edge-connected');
  await (await show(page,'#viewer-texture-show-selection')).uncheck();await frames(page);const hiddenSelection=await page.evaluate(()=>{let overlays=0;__textureObserved.scene.traverse(o=>{if(o.userData&&o.userData.viewerTextureSelection)overlays++;});return{overlays,state:ModelViewer.getTextureTools().getState().selection};});assert.equal(hiddenSelection.overlays,0);assert.equal(hiddenSelection.state.selectionVisible,false);assert.equal(hiddenSelection.state.selectedPixels,connected.selection.selectedPixels);assert.equal(hiddenSelection.state.undoCount,connected.selection.undoCount);await page.locator('#viewer-texture-show-selection').check();await frames(page);
  report.cases.push({name:'real 3D pointer face and connected-edge selection with 3D/texture mask',single,connected,observed});
  await page.screenshot({path:path.join(evidence,'connected-3d-selection.png')});
  const signedFields=await page.evaluate(()=>['viewer-texture-lightness','viewer-texture-hue','viewer-texture-skin-lightness','viewer-texture-skin-hue'].map(id=>{const e=document.getElementById(id);return{id,type:e.type,inputmode:e.inputMode,min:Number(e.min),max:Number(e.max),step:e.step,compact:e.parentElement.classList.contains('viewer-texture-slider')};}));
  assert(signedFields.every(f=>f.type==='number'&&f.inputmode==='text'&&f.min<0&&f.compact),'signed color fields request a full keyboard while preserving native number constraints and compact layout');
  const signedField=await show(page,'#viewer-texture-lightness'),numericBefore=(await toolsState(page)).selection;
  await signedField.fill('');await signedField.pressSequentially('-');
  const partial=await signedField.evaluate(e=>({value:e.value,badInput:e.validity.badInput}));assert.equal(partial.value,'');assert(partial.badInput,'a real typed minus remains a native incomplete draft instead of being coerced to zero');
  assert.equal(await page.evaluate(()=>ModelViewer.getTextureTools().preparePreview()),false);assert.equal(await page.evaluate(()=>ModelViewer.getTextureTools().applyPreview()),false,'an incomplete signed draft cannot silently commit a different color');assert.equal((await toolsState(page)).selection.undoCount,numericBefore.undoCount);assert.equal((await toolsState(page)).selection.revision,numericBefore.revision);
  await signedField.pressSequentially('15');await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);assert.equal(await signedField.inputValue(),'-15');await (await show(page,'#viewer-texture-cancel')).click();await idle(page);
  await signedField.fill('');await signedField.pressSequentially('-0.5');await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);assert.equal(await signedField.inputValue(),'-0.5','intermediate negative zero is preserved while typing a negative fraction');await (await show(page,'#viewer-texture-cancel')).click();await idle(page);
  await signedField.fill('');await signedField.pressSequentially('-');await signedField.press('Tab');await page.waitForFunction(()=>document.getElementById('viewer-texture-lightness').value==='-0.5');await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);await (await show(page,'#viewer-texture-cancel')).click();await idle(page);assert.deepStrictEqual(await pixels(page),fixture.rgba,'negative drafts, canceled previews and blur restoration never alter committed pixels');
  report.cases.push({name:'real signed color typing preserves minus and negative fractions, refuses incomplete Apply and retains last valid value on blur',signedFields,partial});
  await setField(page,'#viewer-texture-lightness',5);await setField(page,'#viewer-texture-chroma',120);await setField(page,'#viewer-texture-hue',75);
  await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);await frames(page);
  const preview=await shaderState(page);assert(preview.materials.enabled&&preview.materials.textureOverrides===1);const shader=preview.shaders.find(s=>s.rgba);
  assert(shader&&shader.shader&&shader.dataTexture,'the actual high-quality SIFAS uMainTex receives a DataTexture override');
  assert.notDeepStrictEqual(shader.rgba,fixture.rgba);for(let i=3;i<shader.rgba.length;i+=4)assert.equal(shader.rgba[i],fixture.rgba[i],'OKLCH preview preserves original alpha');
  await (await show(page,'#viewer-texture-show-uv')).uncheck();await frames(page);
  const coloredPixel=changedInterior(fixture.rgba,shader.rgba),cleanPreview=await selectionDisplay(page,coloredPixel.point);
  assert(!cleanPreview.checked&&!cleanPreview.engineVisible&&cleanPreview.overlays===0,'color sliders automatically remove both 2D cyan and 3D amber tint');
  assert.equal(cleanPreview.selectedPixels,connected.selection.selectedPixels,'hiding color tint keeps the exact source mask');
  assert.equal(cleanPreview.selectionRevision,connected.selection.selectionRevision);assert.equal(cleanPreview.undoCount,connected.selection.undoCount,'automatic visibility does not add a mask or color history entry');
  assert.deepStrictEqual(cleanPreview.rgba,shader.rgba.slice(coloredPixel.offset,coloredPixel.offset+4),'the actual texture canvas shows the exact preview color without selection tint');
  assert(cleanPreview.directlyBesideCanvas&&cleanPreview.label.height>=44&&cleanPreview.label.hit,'the same selection checkbox is adjacent to the canvas with a reachable 44px touch label');
  assert(/Selection kept/.test(cleanPreview.information),'nearby status explains that only the tint is hidden');
  report.cases.push({name:'unmixed costume preview hides only the 2D/3D selection tint while keeping source mask/history and exact canvas pixels',cleanPreview});
  assert.equal((await page.evaluate(()=>ModelViewer.getTextureTools().getEdits())).length,0,'unapplied previews are not saved recipes');
  assert(await page.locator('#viewer-save').isDisabled(),'pending color preview blocks persistent model export');
  const historyBefore=(await toolsState(page)).selection.undoCount;
  await (await show(page,'#viewer-texture-apply')).click();await idle(page);
  const colored=await pixels(page);assert.deepStrictEqual(colored,shader.rgba,'committed exact PNG agrees with the shader preview');
  assert.equal((await toolsState(page)).selection.undoCount,historyBefore+1,'one color Apply creates one undo entry');
  assert(!(await page.locator('#viewer-save').isDisabled()),'texture-only changes activate model saving');
  await (await show(page,'#viewer-texture-undo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),fixture.rgba);
  await (await show(page,'#viewer-texture-redo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),colored);
  const appliedClean=await selectionDisplay(page,coloredPixel.point);assert(!appliedClean.checked&&!appliedClean.engineVisible&&appliedClean.overlays===0,'Apply and color Undo/Redo keep the changed color unobscured');
  await (await show(page,'#viewer-texture-compare')).check();await frames(page);const originalComparison=await shaderState(page);assert.equal(originalComparison.materials.textureOverrides,0,'Compare original removes generated texture overrides');assert(originalComparison.shaders.every(row=>!row.dataTexture),'Compare original uses authored original texture objects and mip levels');assert.deepStrictEqual(await pixels(page),colored,'comparison does not change the committed PNG recipe');await page.locator('#viewer-texture-compare').uncheck();await frames(page);const editedComparison=await shaderState(page);assert.equal(editedComparison.materials.textureOverrides,1);assert.deepStrictEqual(editedComparison.shaders.find(s=>s.rgba).rgba,colored);assert.deepStrictEqual(await pixels(page),colored);
  report.cases.push({name:'OKLCH preview reaches actual SIFAS uniform, commits losslessly once, undo/redo and texture-only save enabled',preview,historyBefore});
  await (await show(page,'#viewer-texture-select-none')).click();hit=await facePoint(page);await page.mouse.click(hit.x,hit.y);await idle(page);
  const autoRestored=await selectionDisplay(page,coloredPixel.point);assert(autoRestored.checked&&autoRestored.engineVisible&&autoRestored.overlays>0,'a new real region selection restores a tint that was hidden automatically');assert.equal(autoRestored.selectedPixels,connected.selection.selectedPixels);
  await setField(page,'#viewer-texture-lightness',9);await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);await (await show(page,'#viewer-texture-cancel')).click();await idle(page);
  const cancelledPreview=await selectionDisplay(page,coloredPixel.point);assert(!cancelledPreview.checked&&!cancelledPreview.engineVisible&&cancelledPreview.overlays===0,'Cancel preview also leaves the committed color unobscured');assert.equal(cancelledPreview.selectedPixels,autoRestored.selectedPixels);assert.equal(cancelledPreview.undoCount,autoRestored.undoCount);assert.deepStrictEqual(await pixels(page),colored,'canceling never changes the committed PNG or source mask');
  const beforeVisibility=(await toolsState(page)).selection;
  await (await show(page,'#viewer-texture-show-selection')).uncheck();await frames(page);const unfilteredFrame=await modelFrame(page),cleanPixels=await selectionDisplay(page,coloredPixel.point);
  await page.locator('#viewer-texture-show-selection').check();await frames(page);const tintedFrame=await modelFrame(page),tintedPixels=await selectionDisplay(page,coloredPixel.point);
  assert.notEqual(tintedFrame.hash,unfilteredFrame.hash,'selection visibility changes actual rendered model pixels, not just inspector state');assert.notDeepStrictEqual(tintedPixels.rgba,cleanPixels.rgba,'the visible texture tint is distinguishable from the exact color');
  await page.locator('#viewer-texture-show-selection').uncheck();await frames(page);const restoredFrame=await modelFrame(page);assert.deepStrictEqual(restoredFrame,unfilteredFrame,'turning the tint back off restores the exact clean model framebuffer');
  const afterVisibility=(await toolsState(page)).selection;assert.equal(afterVisibility.undoCount,beforeVisibility.undoCount);assert.equal(afterVisibility.revision,beforeVisibility.revision);assert.equal(afterVisibility.selectionRevision,beforeVisibility.selectionRevision);assert.deepStrictEqual(await pixels(page),colored);
  await (await show(page,'#viewer-texture-select-none')).click();hit=await facePoint(page);await page.mouse.click(hit.x,hit.y);await idle(page);const manualHidden=await selectionDisplay(page,coloredPixel.point);assert(!manualHidden.checked&&!manualHidden.engineVisible&&manualHidden.overlays===0,'new selections honor a manually disabled tint');assert.equal(manualHidden.selectedPixels,connected.selection.selectedPixels);
  report.cases.push({name:'adjacent tint toggle preserves authored pixels, masks and Undo; new selection restores automatic hiding while manual OFF remains honored',appliedClean,autoRestored,cancelledPreview,unfilteredFrame,tintedFrame,restoredFrame,manualHidden});
  const selectedBounds=await page.evaluate(()=>{const mesh=__textureTarget,uv=mesh.geometry.attributes.uv;let texture;const old=SifasMaterial;__textureObserved.scene.traverse(o=>{if(o===mesh){const ms=Array.isArray(o.material)?o.material:[o.material];for(const m of ms)if(m.uniforms&&m.uniforms.uMainTex)texture=m.uniforms.uMainTex.value;}});if(!texture)throw Error('No texture');const points=[0,1,2,3].map(i=>texture.transformUv(new THREE.Vector2(uv.getX(i),uv.getY(i))));return{x0:Math.min(...points.map(v=>v.x))*16,x1:Math.max(...points.map(v=>v.x))*16,y0:Math.min(...points.map(v=>v.y))*16,y1:Math.max(...points.map(v=>v.y))*16};});
  let untouched=0;for(let y=0;y<16;y++)for(let x=0;x<16;x++){if(x+.5<selectedBounds.x0||x+.5>selectedBounds.x1||y+.5<selectedBounds.y0||y+.5>selectedBounds.y1){const i=(y*16+x)*4;assert.deepStrictEqual(colored.slice(i,i+4),fixture.rgba.slice(i,i+4),'unselected pixels remain byte-exact');untouched++;}}
  assert(untouched>=96,'independent UV rectangle reference includes a substantial unselected region');
  const saved=await saveModel(page);assert(saved.previewPaths.length&&saved.recipePath);const rawTexture=bundlePixels(saved.previewPaths[0]).find(t=>t.name==='ch0001_co0001_body');assert(rawTexture);assert.deepStrictEqual(rawTexture.rgba,colored,'actual exported Unity texture matches committed PNG including hidden RGB and alpha');
  const recipe=JSON.parse(fs.readFileSync(saved.recipePath,'utf8'));assert(JSON.stringify(recipe).includes('sourceSha256'),'saved recipe includes original texture source binding');
  await clearEdits(page);assert.equal((await page.evaluate(()=>ModelViewer.getTextureTools().getEdits())).length,0);assert.equal((await shaderState(page)).materials.textureOverrides,0,'clear recipe removes original shader overrides');
  await importRecipe(page,saved.recipePath);assert.deepStrictEqual(await pixels(page),colored,'actual recipe picker restores PNG color edits');
  await (await show(page,'#viewer-texture-undo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),fixture.rgba,'restored recipe has one undoable pixel operation');
  await (await show(page,'#viewer-texture-redo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),colored);
  const mixed=await page.evaluate(async()=>{const current=ModelViewer.getAuthoringState(),node=ModelViewer.getEditingMetadata().nodes.find(n=>n.name==='BreastSize');if(!node)throw Error('Missing real body bone');current.edits=[{node:node.node,scale:[1.08,1.02,1.03],method:'node',compensate:false}];await ModelViewer.restoreAuthoringState(current);return ModelViewer.getAuthoringState();});await idle(page);assert.equal(mixed.textures.length,1);assert.equal(mixed.edits.length,1);
  const packaged=await saveModel(page,true);assert(fs.existsSync(packaged.modPackage.packagePath));const zippedTexture=bundlePixels(packaged.modPackage.packagePath).find(t=>t.name==='ch0001_co0001_body');assert(zippedTexture);assert.deepStrictEqual(zippedTexture.rgba,colored,'installer ZIP keeps exact texture with simultaneous body edits');
  report.cases.push({name:'unselected pixels exact; real Unity save and Mod ZIP with body edits; recipe picker clear/restore/undo',untouched,selectedBounds,saved,packaged,mixed});
  await (await show(page,'#viewer-open-saved')).click();await page.waitForFunction(()=>{const p=ModelViewer.getState().persistence;return !p.busy&&(p.error||p.reviewingSaved);});assert.equal(await page.evaluate(()=>ModelViewer.getState().persistence.reviewingSaved),true);
  await (await show(page,'#viewer-texture-select')).selectOption({index:1});await idle(page);const readonly=await toolsState(page);assert(readonly.selection.readOnly);assert(await page.locator('#viewer-texture-readonly-note').isVisible());assert(await page.locator('#viewer-texture-apply').isDisabled());
  await page.evaluate(()=>ModelViewer.getTextureTools().setTab('paint'));await (await show(page,'#viewer-texture-paint-tool')).selectOption('brush');const readonlyBefore=await toolsState(page);await clickPixel(page,3.5,3.5);const readonlyAfter=await toolsState(page);assert.equal(readonlyAfter.selection.revision,readonlyBefore.selection.revision);assert.equal(readonlyAfter.editedTextures.length,0,'saved-copy pointer gestures cannot create source-bound edits');
  const readonlyCanvas=page.locator('#viewer-texture-canvas-host canvas').filter({visible:true});await readonlyCanvas.scrollIntoViewIfNeeded();const readonlyBox=await readonlyCanvas.boundingBox();await page.mouse.move(readonlyBox.x+readonlyBox.width/2,readonlyBox.y+readonlyBox.height/2);await page.mouse.wheel(0,-120);await frames(page);assert((await toolsState(page)).selection.view.zoom>readonlyAfter.selection.view.zoom,'saved-copy zoom remains available');
  const readonlyDownload=page.waitForEvent('download');await (await show(page,'#viewer-texture-export')).click();const readonlyPNG=path.join(evidence,'readonly-saved-export.png');await(await readonlyDownload).saveAs(readonlyPNG);assert.deepStrictEqual((await decodedPNG('data:image/png;base64,'+fs.readFileSync(readonlyPNG).toString('base64'))).rgba,colored,'read-only source exports exact saved pixels');
  await (await show(page,'#viewer-reedit-original')).click();await page.waitForFunction(()=>{const p=ModelViewer.getState().persistence;return !p.busy&&(p.error||!p.reviewingSaved);});assert.equal(await page.evaluate(()=>ModelViewer.getState().persistence.error),'');await idle(page);await (await show(page,'#viewer-texture-select')).selectOption({index:1});await idle(page);assert.equal((await toolsState(page)).selection.readOnly,false);assert.deepStrictEqual(await pixels(page),colored,'Re-edit restores the original source and previous exact PNG edit');
  report.cases.push({name:'saved-copy texture review is read-only; original source re-edit restores exact body/texture recipe',readonly,readonlyAfter});
  await clearEdits(page);await page.evaluate(()=>ModelViewer.getTextureTools().setTab('skin'));await selectPixelRect(page,0,0,8,16);
  assert.equal((await toolsState(page)).selection.selectedPixels,128,'explicit texture rectangle confirms exactly the skin half');
  await (await show(page,'#viewer-texture-source-tone')).selectOption('default');await (await show(page,'#viewer-texture-target-tone')).selectOption('bright');
  await page.evaluate(()=>ModelViewer.getTextureTools().preparePreview());await frames(page);const skinPreview=(await shaderState(page)).shaders.find(s=>s.rgba).rgba;
  const skinPixel=changedInterior(fixture.rgba,skinPreview),cleanSkin=await selectionDisplay(page,skinPixel.point);assert(!cleanSkin.checked&&!cleanSkin.engineVisible&&cleanSkin.overlays===0);assert.equal(cleanSkin.selectedPixels,128,'skin preview also preserves its exact confirmed mask');assert.deepStrictEqual(cleanSkin.rgba,skinPreview.slice(skinPixel.offset,skinPixel.offset+4),'skin preview canvas also shows the actual untinted color');
  let skinChanged=0;for(let y=0;y<16;y++)for(let x=0;x<16;x++){const i=(y*16+x)*4;assert.equal(skinPreview[i+3],fixture.rgba[i+3]);if(x>=8)assert.deepStrictEqual(skinPreview.slice(i,i+4),fixture.rgba.slice(i,i+4),'cloth pixels are untouched by confirmed skin adjustment');else if(skinPreview.slice(i,i+3).some((v,k)=>v!==fixture.rgba[i+k]))skinChanged++;}
  assert(skinChanged>100);assert.notDeepStrictEqual(skinPreview.slice(0,3),skinPreview.slice(16*15*4,16*15*4+3),'skin shading remains a gradient');
  await (await show(page,'#viewer-texture-apply')).click();await idle(page);assert.deepStrictEqual(await pixels(page),skinPreview);await (await show(page,'#viewer-texture-undo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),fixture.rgba);await (await show(page,'#viewer-texture-redo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),skinPreview);
  report.cases.push({name:'confirmed skin-only default→bright keeps cloth/alpha byte exact and shading; apply undo/redo',skinChanged});
  await clearEdits(page);await page.evaluate(()=>ModelViewer.getTextureTools().setTab('paint'));await (await show(page,'#viewer-texture-selection-clear')).click();
  await (await show(page,'#viewer-texture-paint-tool')).selectOption('brush');await setField(page,'#viewer-texture-paint-color','#ff0000');await setField(page,'#viewer-texture-paint-alpha',50);await setField(page,'#viewer-texture-brush-size',1);await setField(page,'#viewer-texture-opacity',50);await setField(page,'#viewer-texture-softness',0);
  await clickPixel(page,15.5,14.5);const painted=await pixels(page),at=(14*16+15)*4;
  const sa=.5*.5,da=128/255,oa=sa+da*(1-sa),expected=[30,160,70].map((v,i)=>Math.round(([255,0,0][i]*sa+v*da*(1-sa))/oa)).concat(Math.round(oa*255));assert.deepStrictEqual(painted.slice(at,at+4),expected,'actual pointer brush uses correct straight-alpha source over');
  for(let i=0;i<painted.length;i++)if(i<at||i>=at+4)assert.equal(painted[i],fixture.rgba[i],'one pixel brush preserves every other byte');
  assert.deepStrictEqual((await shaderState(page)).shaders.find(s=>s.rgba).rgba,painted);await (await show(page,'#viewer-texture-undo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),fixture.rgba);await (await show(page,'#viewer-texture-redo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),painted);
  await (await show(page,'#viewer-texture-paint-tool')).selectOption('eraser');await setField(page,'#viewer-texture-opacity',100);await clickPixel(page,15.5,14.5);const erased=await pixels(page);assert.deepStrictEqual(erased.slice(at,at+3),painted.slice(at,at+3));assert.equal(erased[at+3],0,'eraser clears alpha, preserving hidden RGB');await (await show(page,'#viewer-texture-undo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),painted);
  report.cases.push({name:'actual pixel brush straight-alpha source-over and eraser; model override PNG exact, Undo/Redo',expected,paintedPixel:painted.slice(at,at+4)});
  const importHistory=(await toolsState(page)).selection.undoCount;await pickPNG(page,pickerPNG);assert.deepStrictEqual(await pixels(page),fixture.standalone,'in-app path import applies exact RGBA to the currently bound model texture');assert.deepStrictEqual((await shaderState(page)).shaders.find(s=>s.rgba).rgba,fixture.standalone);assert.equal((await toolsState(page)).sourceSha256,sourceData.sourceSha256,'PNG import keeps original model texture identity');assert.equal((await toolsState(page)).selection.undoCount,importHistory+1);await (await show(page,'#viewer-texture-undo')).click();await idle(page);assert.deepStrictEqual(await pixels(page),painted,'one Undo restores the pre-import bound model texture');report.cases.push({name:'native in-app PNG path import updates bound model/shader as one undoable edit, preserving source identity'});
  const beforeView=(await toolsState(page)).selection.view,beforePixels=await pixels(page);const canvas=page.locator('#viewer-texture-canvas-host canvas').filter({visible:true});await canvas.scrollIntoViewIfNeeded();let box=await canvas.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.wheel(0,-240);await frames(page);const zoomed=(await toolsState(page)).selection.view;assert(zoomed.zoom>beforeView.zoom);
  await page.mouse.down({button:'right'});await page.mouse.move(box.x+box.width/2+35,box.y+box.height/2+23,{steps:5});await page.mouse.up({button:'right'});await frames(page);const panned=(await toolsState(page)).selection.view;assert(Math.abs(panned.x-zoomed.x)>20&&Math.abs(panned.y-zoomed.y)>10);await setField(page,'#viewer-texture-uv-color','#ff5500');assert.equal(await page.evaluate(()=>ViewerUVColor.get()),'#ff5500');assert.deepStrictEqual(await pixels(page),beforePixels);
  const smallCanvas=await canvas.boundingBox();await (await show(page,'#viewer-texture-expand')).click();await frames(page);let expandedBox=await page.locator('#viewer-texture-tools').boundingBox();box=await canvas.boundingBox();assert((await toolsState(page)).expanded&&box.width>smallCanvas.width*1.5&&box.height>smallCanvas.height);assert(expandedBox.x>=0&&expandedBox.y>=0&&expandedBox.x+expandedBox.width<=1481&&expandedBox.y+expandedBox.height<=1101);
  const expandedHits=(await page.locator('#viewer-texture-tools').evaluate(visibleTextureControls)).controls.filter(e=>e.top>=0&&e.bottom<=1100);assert(expandedHits.length>8&&expandedHits.every(x=>x.reachable),'expanded desktop controls receive pointer hits above the model and sidebars');
  await page.screenshot({path:path.join(evidence,'expanded-desktop.png')});await page.keyboard.press('Escape');assert.equal((await toolsState(page)).expanded,false);
  await page.setViewportSize({width:390,height:844});await frames(page);await (await show(page,'#viewer-texture-expand')).click();await frames(page);expandedBox=await page.locator('#viewer-texture-tools').boundingBox();assert(expandedBox.x>=0&&expandedBox.y>=0&&expandedBox.x+expandedBox.width<=391&&expandedBox.y+expandedBox.height<=845);
  const overflow=await page.locator('#viewer-texture-tools').evaluate(visibleTextureControls);assert(overflow.scroll<=overflow.width+2,'expanded mobile editor has no horizontal toolbar overflow');assert(overflow.controls.every(c=>c.left>=0&&c.right<=391),'all actually visible mobile controls stay within viewport');const railReach=await reachableTextureRail(page);await page.screenshot({path:path.join(evidence,'expanded-mobile.png')});await page.keyboard.press('Escape');assert.equal((await toolsState(page)).expanded,false);await page.setViewportSize({width:1480,height:1100});await frames(page);
  report.cases.push({name:'wheel anchored zoom, right-button pan, UV color do not edit pixels; desktop/mobile expansion Escape and toolbar bounds',beforeView,zoomed,panned,overflow,railReach});
  await (await show(page,'#viewer-fullscreen')).click();await page.waitForFunction(()=>!!document.fullscreenElement&&ModelViewer.getState().layout.fullscreen==='browser');await page.evaluate(()=>ModelViewer.getTextureTools().setExpanded(true));await frames(page);const fullscreenEditor=await page.locator('#viewer-texture-tools').evaluate(el=>{const f=document.fullscreenElement,button=document.getElementById('viewer-texture-tab-paint'),r=button.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return{fullscreen:f&&f.id,contained:!!f&&f.contains(el),parent:el.parentElement.id,reachable:hit===button||button.contains(hit),width:r.width,height:r.height};});assert.equal(fullscreenEditor.fullscreen,'tab-viewer');assert(fullscreenEditor.contained&&fullscreenEditor.reachable&&fullscreenEditor.width>0,'expanded texture editor remains visible and interactive inside the actual browser fullscreen subtree');await page.locator('#viewer-texture-tab-paint').click();assert.equal((await toolsState(page)).activeTab,'paint');await page.screenshot({path:path.join(evidence,'fullscreen-texture-editor.png')});await page.locator('#viewer-texture-expand').click();await (await show(page,'#viewer-fullscreen')).click();await page.waitForFunction(()=>!document.fullscreenElement&&ModelViewer.getState().layout.fullscreen==='none');await frames(page);report.cases.push({name:'actual browser viewer fullscreen contains expanded texture editor with reachable interactive controls',fullscreenEditor});
  await clearEdits(page);await page.evaluate(()=>ModelViewer.getTextureTools().setTab('costume'));await (await show(page,'#viewer-texture-select-none')).click();await (await show(page,'#viewer-texture-scene-mode')).selectOption('brush');await setField(page,'#viewer-texture-brush-size',2);await (await show(page,'#viewer-texture-selection-mode')).selectOption('replace');
  const brushStart=await toolsState(page);hit=await facePoint(page);await page.mouse.move(hit.x,hit.y);await frames(page);const cursor=page.locator('#viewer-texture-model-brush-cursor');assert(await cursor.isVisible(),'actual 3D surface hover displays a brush diameter cursor');const cursorBox=await cursor.boundingBox();assert(cursorBox.width>4&&cursorBox.width<=360);
  await page.mouse.down();await page.mouse.move(hit.x+12,hit.y-8,{steps:6});await page.mouse.up();await idle(page);const brushed=await toolsState(page);assert(brushed.selection.selectedPixels>0&&brushed.selection.selectedPixels<32,'fine 3D brush selects source texture pixels, smaller than a complete mesh face');assert(brushed.lastModelSelection&&brushed.lastModelSelection.brush);assert.equal(brushed.selection.undoCount,brushStart.selection.undoCount+1,'one 3D brush drag creates one mask undo entry');
  await (await show(page,'#viewer-texture-undo')).click();await idle(page);assert.equal((await toolsState(page)).selection.selectedPixels,0);await (await show(page,'#viewer-texture-redo')).click();await idle(page);assert.equal((await toolsState(page)).selection.selectedPixels,brushed.selection.selectedPixels);assert.deepStrictEqual(await pixels(page),fixture.rgba,'3D region painting changes only selection, never source pixels');await page.screenshot({path:path.join(evidence,'fine-3d-brush.png')});report.cases.push({name:'actual fine 3D surface selection brush with visible diameter, stroke-level Undo/Redo and exact source pixels',cursorBox,brushStart:brushStart.selection,brushed:brushed.selection});
  await clearEdits(page);await page.evaluate(()=>ModelViewer.getTextureTools().setTab('costume'));await (await show(page,'#viewer-texture-select-all')).click();
  await setField(page,'#viewer-texture-hue',60);await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);
  const race=await page.evaluate(async()=>{const field=document.getElementById('viewer-texture-hue');field.value='100';field.dispatchEvent(new Event('input',{bubbles:true}));const immediatelyDisabled=document.getElementById('viewer-texture-apply').disabled;return{immediatelyDisabled};});report.debounceRace=race;
  await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);await (await show(page,'#viewer-texture-cancel')).click();await idle(page);
  const stale=await page.evaluate(async()=>{const t=ModelViewer.getTextureTools(),before=t.getState().performance.previewsDiscarded,p=t.preparePreview();t.cancelPreview();const ready=await p;return{ready,before,state:t.getState()};});await idle(page);assert.equal(stale.ready,false);assert(stale.state.performance.previewsDiscarded>stale.before);assert.equal((await toolsState(page)).preview,false);assert.equal((await page.evaluate(()=>ModelViewer.getTextureTools().getEdits())).length,0);assert.equal((await shaderState(page)).materials.textureOverrides,0);
  const clearWhileWorking=await page.evaluate(async()=>{const t=ModelViewer.getTextureTools(),p=t.preparePreview();await t.restoreEdits([]);await p;return t.getState();});await idle(page);assert.equal(clearWhileWorking.preview,false);assert.equal((await page.evaluate(()=>ModelViewer.getTextureTools().getEdits())).length,0);assert.equal((await shaderState(page)).materials.textureOverrides,0);
  report.cases.push({name:'debounce Apply blocks old previews; canceled/in-flight clear results are discarded without persistent edits or shader leaks',race,stale:stale.state.performance,clearWhileWorking});
  await setField(page,'#viewer-texture-lightness',0);await setField(page,'#viewer-texture-chroma',100);await setField(page,'#viewer-texture-hue',0);await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().preview&&!document.getElementById('viewer-texture-apply').disabled);await (await show(page,'#viewer-texture-apply')).click();await idle(page);assert.equal((await toolsState(page)).preview,false);assert.equal((await page.evaluate(()=>ModelViewer.getTextureTools().getEdits())).length,0,'identity Apply creates no persistent edit or stuck pending preview');report.cases.push({name:'identity/no-op color Apply clears pending work without inventing an edit'});
  const standalonePage=await context.newPage();standalonePage.setDefaultTimeout(45000);standalonePage.on('pageerror',e=>errors.push(String(e.stack||e)));await standalonePage.goto(server.url);await standalonePage.waitForFunction(()=>window.ModelViewer&&ModelViewer.getTextureTools());
  await (await show(standalonePage,'#texture-editor-launch')).click();await standalonePage.locator('#viewer-texture-paint-panel input[type="file"][accept*="image/png"]').setInputFiles(standalonePNG);await idle(standalonePage);const standaloneState=await toolsState(standalonePage);assert(standaloneState.standalone);assert(standaloneState.expanded,'standalone launch opens the canvas workspace directly');assert.equal(await standalonePage.evaluate(()=>ModelViewer.getState().loaded),false);
  await (await show(standalonePage,'#viewer-texture-selection-clear')).click();await (await show(standalonePage,'#viewer-texture-paint-tool')).selectOption('brush');await setField(standalonePage,'#viewer-texture-paint-color','#2040ff');await setField(standalonePage,'#viewer-texture-brush-size',1);await setField(standalonePage,'#viewer-texture-opacity',100);await setField(standalonePage,'#viewer-texture-softness',0);await clickPixel(standalonePage,1.5,1.5);
  const downloaded=standalonePage.waitForEvent('download'),saveResponse=standalonePage.waitForResponse(r=>r.url()===server.url+'/api/texture/editor/save'&&r.request().method()==='POST');await (await show(standalonePage,'#viewer-texture-export')).click();const download=await downloaded,downloadPath=path.join(evidence,'standalone-export.png'),savedPNG=await(await saveResponse).json();await download.saveAs(downloadPath);const actualPNG=await decodedPNG('data:image/png;base64,'+fs.readFileSync(downloadPath).toString('base64')),standaloneExpected=fixture.standalone.slice();standaloneExpected.splice((1*16+1)*4,4,32,64,255,255);assert.deepStrictEqual(actualPNG.rgba,standaloneExpected,'standalone import→actual brush→download keeps straight alpha and hidden RGB exact');assert.equal((await standalonePage.evaluate(()=>ModelViewer.getTextureTools().getEdits())).length,0,'standalone PNG painting does not create source-bound model edits');
  assert(savedPNG.path.startsWith(path.join(library,'modded/textures')+path.sep)&&fs.existsSync(savedPNG.path),'PNG save writes inside the native application library');assert.equal(new URL(savedPNG.url,server.url).origin,server.url);assert.equal(download.url(),new URL(savedPNG.url,server.url).href,'native export downloads through an HTTP URL');assert.deepStrictEqual(fs.readFileSync(savedPNG.path),fs.readFileSync(downloadPath),'persisted PNG and actual HTTP download are byte identical');assert((await standalonePage.locator('#viewer-texture-saved-path').textContent()).includes(savedPNG.path));assert.equal(await standalonePage.locator('#viewer-texture-download').getAttribute('href'),savedPNG.url);
  await (await show(standalonePage,'#viewer-texture-undo')).click();await idle(standalonePage);await (await show(standalonePage,'#viewer-texture-redo')).click();await idle(standalonePage);await standalonePage.screenshot({path:path.join(evidence,'standalone-editor.png')});
  report.cases.push({name:'no-model texture editor: browser PNG import, pointer paint, Undo/Redo and persisted HTTP lossless PNG',standaloneState,downloadPath,savedPNG});
  await (await show(standalonePage,'#viewer-texture-expand')).click();await frames(standalonePage);assert.equal((await toolsState(standalonePage)).expanded,false,'standalone workspace can still collapse after direct expanded launch');await (await show(standalonePage,'#viewer-texture-expand')).click();await frames(standalonePage);assert((await toolsState(standalonePage)).expanded);
  const beforePickerCancel=await toolsState(standalonePage),pickerZ=await standalonePage.locator('#picker').evaluate(e=>e.style.zIndex);await (await show(standalonePage,'#viewer-texture-import')).click();await standalonePage.waitForFunction(()=>!document.getElementById('picker').classList.contains('hidden'));await standalonePage.locator('#picker-cancel').click();await standalonePage.waitForFunction(()=>document.getElementById('picker').classList.contains('hidden'));await idle(standalonePage);const afterPickerCancel=await toolsState(standalonePage);assert(afterPickerCancel.expanded);assert.deepStrictEqual(afterPickerCancel.selection,beforePickerCancel.selection,'canceling expanded PNG chooser preserves pan, selection and edit history');assert.equal(await standalonePage.locator('#picker').evaluate(e=>e.style.zIndex),pickerZ,'picker cancellation restores stacking style');
  const openedPNG=standalonePage.waitForResponse(r=>r.url()===server.url+'/api/texture/editor/open'&&r.request().method()==='POST');const expandedPickerHit=await pickPNG(standalonePage,pickerPNG);assert((await toolsState(standalonePage)).expanded,'expanded PNG import preserves the editor layout');const pickerDecoded=await(await openedPNG).json();assert.equal(pickerDecoded.width,16);assert.equal((await toolsState(standalonePage)).standalone,true);await (await show(standalonePage,'#viewer-texture-selection-clear')).click();await clickPixel(standalonePage,2.5,2.5);const nativeSavedResponse=standalonePage.waitForResponse(r=>r.url()===server.url+'/api/texture/editor/save'&&r.request().method()==='POST'),nativeDownload=standalonePage.waitForEvent('download');await (await show(standalonePage,'#viewer-texture-export')).click();const nativeSaved=await(await nativeSavedResponse).json(),nativePath=path.join(evidence,'native-picker-export.png');await(await nativeDownload).saveAs(nativePath);const nativeExpected=fixture.standalone.slice();nativeExpected.splice((2*16+2)*4,4,32,64,255,255);assert.deepStrictEqual((await decodedPNG('data:image/png;base64,'+fs.readFileSync(nativePath).toString('base64'))).rgba,nativeExpected,'existing native in-app picker→path open→actual paint→HTTP PNG keeps exact RGBA');const nativeHTTP=await fetch(server.url+nativeSaved.url);assert.equal(nativeHTTP.status,200);assert(/attachment/i.test(nativeHTTP.headers.get('content-disposition')));assert.deepStrictEqual(Buffer.from(await nativeHTTP.arrayBuffer()),fs.readFileSync(nativeSaved.path));
  report.cases.push({name:'expanded editor native-compatible PNG picker receives pointer hits above its overlay, path open and persisted HTTP export',picked:pickerPNG,expandedPickerHit,nativeSaved});await standalonePage.close();
  androidContext=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,userAgent:'Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A.240405.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.0.0 Mobile Safari/537.36'});const androidPage=await androidContext.newPage();androidPage.setDefaultTimeout(45000);let androidDownloads=0;androidPage.on('download',()=>androidDownloads++);androidPage.on('pageerror',e=>errors.push(String(e.stack||e)));await androidPage.goto(server.url);await androidPage.waitForFunction(()=>window.ModelViewer&&ModelViewer.getTextureTools());await (await show(androidPage,'#texture-editor-launch')).click();await pickPNG(androidPage,pickerPNG);const androidURL=androidPage.url(),androidSaveResponse=androidPage.waitForResponse(r=>r.url()===server.url+'/api/texture/editor/save'&&r.request().method()==='POST');await (await show(androidPage,'#viewer-texture-export')).click();const androidSaved=await(await androidSaveResponse).json();await androidPage.waitForFunction(path=>document.getElementById('viewer-texture-saved-path').textContent===path,androidSaved.path);await frames(androidPage);await wait(300);assert.equal(androidPage.url(),androidURL,'embedded Android keeps its editor open after PNG save');assert.equal(androidDownloads,0,'embedded Android does not attempt unsupported automatic downloads');assert(await androidPage.locator('#viewer-texture-download').isVisible());assert(fs.existsSync(androidSaved.path));assert.deepStrictEqual((await decodedPNG('data:image/png;base64,'+fs.readFileSync(androidSaved.path).toString('base64'))).rgba,fixture.standalone,'Android UA path persists exact PNG without a browser download');await androidPage.screenshot({path:path.join(evidence,'android-webview-png-save.png')});report.cases.push({name:'Android WebView UA path persists PNG and keeps editor open without automatic navigation/download',androidSaved,androidDownloads});await androidContext.close();androidContext=null;
  const multiplePaths=[source];for(let i=1;i<4;i++){const p=path.join(models,'00'+(i+1)+'-texture-colors.unity');fs.copyFileSync(source,p);multiplePaths.push(p);}
  await page.evaluate(paths=>openModelViewer(paths),multiplePaths);await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading&&ModelViewer.getEditingMetadata().available);await idle(page);
  const fourRows=await page.evaluate(async png=>{const t=ModelViewer.getTextureTools(),state=t.getState(),catalogue=await(await fetch('/api/viewer/texture/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:state.token})})).json(),rows=[];for(const record of catalogue.textures){const d=await(await fetch('/api/viewer/texture/data',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:state.token,texture:record.texture})})).json();rows.push({texture:record.texture,sourceSha256:d.sourceSha256,png,kind:'costume'});}await t.restoreEdits(rows);return rows;},await page.evaluate(rgba=>TexturePNG.encodeRGBA({width:16,height:16,data:new Uint8ClampedArray(rgba)}),colored));
  await idle(page);assert.equal(fourRows.length,4);const fourActual=await page.evaluate(()=>ModelViewer.getTextureTools().getEdits());assert.equal(fourActual.length,4,'restoring more than the decoded cache capacity retains all edited textures');for(const row of fourActual)assert.deepStrictEqual((await decodedPNG(row.png)).rgba,colored);
  const fourBefore=JSON.stringify(fourActual),invalidRows=JSON.parse(fourBefore);invalidRows[2].sourceSha256='0'.repeat(64);const rejection=await page.evaluate(async rows=>{try{await ModelViewer.getTextureTools().restoreEdits(rows);return null;}catch(e){return e.message;}},invalidRows);assert(rejection&&/source changed/i.test(rejection));await idle(page);assert.equal(JSON.stringify(await page.evaluate(()=>ModelViewer.getTextureTools().getEdits())),fourBefore,'one stale texture hash rejects the complete recipe atomically');
  report.cases.push({name:'four source-bound textures survive cache pressure; invalid hash rejects recipe atomically',count:fourActual.length,rejection});
  const guardResults=[];for(const endpoint of ['open','save']){
    const body=endpoint==='open'?{path:pickerPNG}:{png:'data:image/png;base64,'+fs.readFileSync(pickerPNG).toString('base64'),name:'qa.png'};
    for(const headers of [{Origin:'https://not-this-app.invalid'},{'Sec-Fetch-Site':'cross-site'}]){const response=await fetch(server.url+'/api/texture/editor/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify(body)});assert.equal(response.status,403,'native PNG routes reject cross-origin work');guardResults.push({endpoint,headers,status:response.status});}
    const oversize=await declaredOversize(server.url+'/api/texture/editor/'+endpoint);assert.equal(oversize.status,400,'declared oversized PNG requests are rejected before body read');guardResults.push({endpoint,oversize});
  }
  for(const body of [{path:'/etc/passwd'},{path:source},{path:pickerPNG,extra:true}]){const response=await fetch(server.url+'/api/texture/editor/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});assert([400,403].includes(response.status),'path open rejects forbidden files, non-PNGs and unsupported fields');guardResults.push({body,status:response.status});}
  report.cases.push({name:'native PNG endpoints bound requests and reject forbidden paths and cross-origin operations',guardResults});
  assert(report.debounceRace.immediatelyDisabled,'Apply is disabled during debounce so a previous preview cannot be committed');
  assert.deepStrictEqual(errors,[]);assert.equal(sha(fs.readFileSync(source)),originalSourceSHA);
  report.final=await toolsState(page);report.pageErrors=errors;report.sourceAfter=sourceHashes();assert.deepStrictEqual(report.sourceAfter,report.sourceBefore,'production source changed during QA; rerun against one revision');report.status='PASS';
 }catch(error){report.status='FAIL';report.error=String(error.stack||error);report.pageErrors=errors;if(page){report.failureState=await page.evaluate(()=>({viewer:ModelViewer.getState(),texture:ModelViewer.getTextureTools().getState()})).catch(()=>null);await page.screenshot({path:path.join(evidence,'failure.png')}).catch(()=>{});}throw error;}
 finally{fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2)+'\n');if(androidContext)await androidContext.close();if(context)await context.close();if(browser)await browser.close();if(server){server.child.kill('SIGTERM');server.log.end();}console.log(JSON.stringify({status:report.status,cases:report.cases.length,evidence}));}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
