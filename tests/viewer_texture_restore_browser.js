"use strict";
// Real HTTP, Unity source texture, exact layer history, browser pointer and busy guards.
const assert = require('assert'), fs = require('fs'), path = require('path'), net = require('net'), os = require('os'), crypto = require('crypto');
const {spawn,execFileSync} = require('child_process'), {chromium} = require('playwright');
const product=process.env.VIEWER_PRODUCT_ROOT||path.resolve(__dirname,'..'), repo=path.dirname(product);
const python=process.env.VIEWER_PYTHON||'/workspace/.venv-elichika/bin/python';
const root=process.env.EVIDENCE_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'texture-restore-evidence-'));fs.mkdirSync(root,{recursive:true});
const candidate=process.env.VIEWER_TEXTURE_TOOLS_OVERRIDE||null;
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'texture-restore-library-'));fs.mkdirSync(directory+'/extracted/3d_model',{recursive:true});
const generated=JSON.parse(execFileSync(python,['-B','-c',`import base64,hashlib,io,json,sys,UnityPy
from pathlib import Path
from PIL import Image
root=Path(sys.argv[1]);source=Path('tests/fixtures/viewer_persistence.unity').read_bytes();bundle=UnityPy.load(source)
original=Image.new('RGBA',(16,16),(80,130,190,255));original.putpixel((15,15),(9,8,7,0))
upper=Image.new('RGBA',(16,16),(210,40,80,255));upper.putpixel((15,14),(30,160,70,128));upper.putpixel((15,15),(1,2,3,0))
def png(im):
 result=io.BytesIO();im.save(result,format='PNG');return result.getvalue()
def url(im):return 'data:image/png;base64,'+base64.b64encode(png(im)).decode()
for obj in bundle.objects:
 if obj.type.name=='Texture2D':
  texture=obj.read();texture.image=original;texture.m_Name='ch0001_co0001_body';texture.save()
model=root/'small-model.unity';model.write_bytes(bundle.file.save(packer='original'));(root/'small-import.png').write_bytes(png(upper))
project={'format':'elichika-texture-project','version':1,'width':16,'height':16,'activeLayer':'qa-overlay','layers':[{'id':'qa-base','name':'QA base','visible':True,'opacity':1,'png':url(Image.new('RGBA',(16,16),(20,60,80,255)))},{'id':'qa-overlay','name':'QA overlay','visible':True,'opacity':.5,'png':url(upper)}]}
print(json.dumps({'project':project,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'original_test_fixture_sha256':hashlib.sha256(source).hexdigest()}))`,directory+'/extracted/3d_model'],{cwd:product,encoding:'utf8',env:{...process.env,PYTHONPATH:product+path.delimiter+repo},maxBuffer:2*1024*1024}));
const project=generated.project, hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const sourceHashes=()=>Object.fromEntries(['viewer-texture-tools.js','texture-paint-engine.js','texture-png.js'].map(name=>[name,hash(fs.readFileSync(path.join(product,'webtools/web/static',name)))]));
const candidateBytes=candidate?fs.readFileSync(candidate):null;
const expectedScriptSHA=hash(candidateBytes||fs.readFileSync(path.join(product,'webtools/web/static/viewer-texture-tools.js')));
let server,browser;const report={status:'RUNNING',qualification:'Actual product HTTP and Chromium; no native OS dialog or Mac runtime approval',sourceBefore:sourceHashes(),fixture:generated,candidateOverride:!!candidate,expectedLoadedTextureToolsSHA256:expectedScriptSHA,loadedScripts:[],cases:[],errors:[]};
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function settled(page){await page.waitForFunction(()=>!ModelViewer.getTextureTools().getState().pending);await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));}
async function snapshot(page, expression='ModelViewer.getTextureTools()'){
 return page.evaluate(expression=>{const c=eval(expression), s=c.getState(), p=c.getProject();return {project:p&&{...p,layers:p.layers.map(layer=>({...layer,image:{width:layer.image.width,height:layer.image.height,data:Array.from(layer.image.data)}}))},undo:s.selection&&s.selection.undoCount,redo:s.selection&&s.selection.redoCount,selected:s.selection&&s.selection.selectedPixels,selectionActive:s.selection&&s.selection.selectionActive,floating:s.selection&&s.selection.floatingSelection,pending:s.pending,revision:s.revision};},expression);
}
(async()=>{try{
 const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
 const log=fs.createWriteStream(root+'/restore-server.log');server=spawn(python,['-B','-m','webtools','--no-browser','--host','127.0.0.1','--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:product+path.delimiter+repo,SUKUSTA_DIR:directory},stdio:['ignore','pipe','pipe']});server.stdout.pipe(log);server.stderr.pipe(log);
 const url='http://127.0.0.1:'+port;for(let i=0;i<150;i++){try{if((await fetch(url+'/api/tools')).ok)break;}catch{}await delay(100);}
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||(fs.existsSync('/usr/bin/chromium')?'/usr/bin/chromium':chromium.executablePath()),args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 for(const variant of [{name:'desktop',viewport:{width:1440,height:900},isMobile:false},{name:'phone',viewport:{width:390,height:844},isMobile:true}]){
  const context=await browser.newContext({viewport:variant.viewport,isMobile:variant.isMobile,hasTouch:variant.isMobile});const page=await context.newPage();page.on('pageerror',error=>report.errors.push(String(error)));
  if(candidateBytes)await page.route('**/viewer-texture-tools.js',route=>route.fulfill({body:candidateBytes,contentType:'application/javascript'}));
  const scriptResponse=page.waitForResponse(response=>new URL(response.url()).pathname.endsWith('/viewer-texture-tools.js'));
  await page.addInitScript(()=>localStorage.setItem('sifas_lang','ko'));await page.goto(url);
  const loadedScriptSHA=hash(await (await scriptResponse).body());assert.equal(loadedScriptSHA,expectedScriptSHA,'The executed browser response must be the exact frozen source bytes');report.loadedScripts.push({variant:variant.name,file:'viewer-texture-tools.js',sha256:loadedScriptSHA});
  await page.waitForFunction(()=>window.ModelViewer&&ModelViewer.getTextureTools());
  await page.evaluate(p=>{document.getElementById('viewer-auto-face').checked=false;openModelViewer([p]);},directory+'/extracted/3d_model/small-model.unity');
  await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading,{timeout:60000});
  await page.locator('#viewer-texture-select').evaluate(e=>{for(let p=e;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;});
  await page.waitForFunction(()=>document.getElementById('viewer-texture-select').options.length>1);await page.locator('#viewer-texture-select').selectOption({index:1});await settled(page);
  await page.evaluate(()=>ModelViewer.getTextureTools().openPaint());await settled(page);
  if(!await page.locator('#viewer-texture-reset').isVisible())await page.locator('#viewer-texture-toggle-inspector').click();
  const original=await snapshot(page);
  await page.evaluate(project=>ModelViewer.getTextureTools().openProject(project,'guarded-layers'),project);await settled(page);
  // Real selection state remains independent of the one-operation stack restore.
  await page.locator('#viewer-texture-paint-tool').selectOption('select-rectangle');
  const region=await page.locator('#viewer-texture-canvas-host canvas').evaluate(canvas=>{const r=canvas.getBoundingClientRect(),v=ModelViewer.getTextureTools().getState().selection.view;return{x1:r.x+v.x+2*v.zoom,y1:r.y+v.y+2*v.zoom,x2:r.x+v.x+8*v.zoom,y2:r.y+v.y+9*v.zoom};});
  await page.mouse.move(region.x1,region.y1);await page.mouse.down();await page.mouse.move(region.x2,region.y2,{steps:4});await page.mouse.up();
  await settled(page);
  const before=await snapshot(page);assert.equal(before.project.layers.length,2);assert(before.selectionActive&&before.selected>0&&before.selected<256,'A genuine partial rectangle selection is present');
  await page.locator('#viewer-texture-reset').click();assert.equal(await page.locator('#viewer-texture-restore-prompt').isVisible(),true);assert.deepEqual(await snapshot(page),before,'Opening the guard must retain all layers/history/selection');
  await page.locator('#viewer-texture-restore-cancel').click();assert.deepEqual(await snapshot(page),before,'Keep editing must be a strict no-op');report.cases.push({variant:variant.name,name:'open and cancel preserve exact document/history/selection',status:'PASS'});
  await page.locator('#viewer-texture-reset').click();await page.locator('#viewer-texture-restore-confirm').click();await settled(page);
  const restored=await snapshot(page);assert.equal(restored.undo,before.undo+1);assert.equal(restored.project.layers.length,1);assert.deepEqual(restored.project.layers[0].image,original.project.layers[0].image);assert.equal(restored.selected,before.selected);assert.equal(restored.selectionActive,before.selectionActive);
  await page.locator('#viewer-texture-undo').click();await settled(page);const undone=await snapshot(page);assert.deepEqual(undone.project,before.project);assert.equal(undone.undo,before.undo);assert.equal(undone.selected,before.selected);
  await page.locator('#viewer-texture-redo').click();await settled(page);assert.deepEqual((await snapshot(page)).project,restored.project);
  await page.locator('#viewer-texture-undo').click();await settled(page);report.cases.push({variant:variant.name,name:'one undo restores both exact edited layers and redo restores loaded original',status:'PASS'});
  await page.locator('#viewer-texture-reset').click();await page.locator('#viewer-texture-layer-name').fill('Changed after guard');await page.locator('#viewer-texture-layer-name').dispatchEvent('change');await settled(page);
  assert.equal(await page.locator('#viewer-texture-restore-prompt').isVisible(),false);const changed=await snapshot(page);await page.locator('#viewer-texture-restore-confirm').dispatchEvent('click');assert.deepEqual(await snapshot(page),changed);report.cases.push({variant:variant.name,name:'stale confirmation cannot revert a newer layer edit',status:'PASS'});
  await page.evaluate(()=>{const c=ModelViewer.getTextureTools();c.clipboardAction('copySelection');c.clipboardAction('pasteClipboard');});
  const floating=await snapshot(page);assert(floating.floating);assert(await page.locator('#viewer-texture-reset').isDisabled());await page.locator('#viewer-texture-reset').dispatchEvent('click');assert.deepEqual(await snapshot(page),floating);assert.equal(await page.locator('#viewer-texture-restore-prompt').isVisible(),false);
  await page.evaluate(()=>ModelViewer.getTextureTools().clipboardAction('cancelFloating'));await settled(page);report.cases.push({variant:variant.name,name:'floating pixels retain their state and block restore',status:'PASS'});
  let release;const barrier=new Promise(resolve=>release=resolve);await page.route('**/api/texture/editor/open',async route=>{await barrier;await route.continue();});
  await page.evaluate(p=>{window.__opening=ModelViewer.getTextureTools().importPNGPath(p);},directory+'/extracted/3d_model/small-import.png');await page.waitForFunction(()=>ModelViewer.getTextureTools().getState().loading>0);
  const busy=await snapshot(page);assert(await page.locator('#viewer-texture-reset').isDisabled());await page.locator('#viewer-texture-reset').dispatchEvent('click');assert.deepEqual(await snapshot(page),busy);assert.equal(await page.locator('#viewer-texture-restore-prompt').isVisible(),false);release();await page.evaluate(()=>window.__opening);await page.unroute('**/api/texture/editor/open');await settled(page);report.cases.push({variant:variant.name,name:'pending PNG import blocks restore without losing queued data',status:'PASS'});
  for(const [code,label] of [['en','Restore original texture'],['ko','편집 전 텍스쳐로 되돌리기'],['ja','編集前のテクスチャに戻す']]){await page.evaluate(code=>changeLang(code),code);assert.equal(await page.locator('#viewer-texture-reset').textContent(),label);}report.cases.push({variant:variant.name,name:'English Korean Japanese explicitly describe reverting the loaded image',status:'PASS'});
  await page.screenshot({path:root+'/restore-'+variant.name+'.png'});await context.close();
 }
 assert.deepEqual(report.errors,[]);report.status='PASS_RESTORE_GUARD_BROWSER';
}catch(error){report.status='FAIL_RESTORE_GUARD_BROWSER';report.error=String(error.stack||error);throw error;}finally{if(browser)await browser.close();if(server)server.kill('SIGTERM');report.sourceAfter=sourceHashes();assert.deepEqual(report.sourceAfter,report.sourceBefore);fs.writeFileSync(root+'/report.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,cases:report.cases.length,error:report.error}));}})().catch(()=>process.exitCode=1);
