/* Real product picker/API/SSE/decryption/Unity-to-GLB flow with original fixtures. */
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto');
const {spawn}=require('child_process');const {chromium}=require('playwright');
const product=path.resolve(__dirname,'..'),evidence=process.env.EVIDENCE_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'viewer-game-assets-'));
fs.mkdirSync(evidence,{recursive:true});const report={status:'RUNNING',scope:'Host Chromium plus isolated real product catalog/SSE/pack decryption/Unity-to-GLB; no physical device or original game playback claim',cases:[]};
const files=['webtools/core/game_models.py','webtools/server.py','webtools/web/static/viewer-game-assets.js'];
const hashes=()=>Object.fromEntries(files.map(n=>[n,crypto.createHash('sha256').update(fs.readFileSync(path.join(product,n))).digest('hex')]));report.sourceBefore=hashes();
let child,browser;
(async()=>{try{
 child=spawn(process.env.VIEWER_PYTHON||'python3',[path.join(__dirname,'game_models_browser_server.py')],{cwd:product,env:process.env,stdio:['ignore','pipe','pipe']});
 const ready=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(new Error('Server did not start')),15000);child.stdout.on('data',chunk=>{text+=chunk;if(text.includes('\n')){try{clearTimeout(timer);resolve(JSON.parse(text.split('\n')[0]));}catch(e){reject(e);}}});child.once('exit',code=>reject(new Error('Server exited '+code)));});
 child.stdout.on('data',()=>{});const logs=fs.createWriteStream(path.join(evidence,'server.log'));child.stderr.pipe(logs);
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE||undefined,headless:true,args:['--no-sandbox','--enable-webgl','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 for(const profile of [{name:'phone-ko',width:448,height:998,touch:true,lang:'ko'},{name:'wide-en',width:1600,height:1000,touch:false,lang:'en'}]){
  const context=await browser.newContext({viewport:{width:profile.width,height:profile.height},hasTouch:profile.touch});
  const page=await context.newPage(),errors=[];page.setDefaultTimeout(30000);page.on('pageerror',e=>errors.push(String(e)));
  await page.addInitScript(lang=>localStorage.setItem('sifas_lang',lang),profile.lang);await page.goto(ready.url);
  await page.waitForFunction(()=>typeof openModelViewer==='function'&&!!window.ModelViewer);
  await page.locator('.tab[data-tab="viewer"]').click();
  await page.locator('#viewer-file-options').evaluate(n=>n.open=true);await page.locator('#viewer-auto-face').uncheck();await page.locator('#viewer-file-options').evaluate(n=>n.open=false);
  await page.locator('#viewer-game-assets').click();await page.waitForFunction(()=>document.getElementById('viewer-game-character').options.length>1);
  const initial=await page.locator('#viewer-game-assets-dialog').evaluate(d=>({open:d.open,width:d.getBoundingClientRect().width,height:d.getBoundingClientRect().height,within:d.getBoundingClientRect().left>=0&&d.getBoundingClientRect().right<=innerWidth&&d.getBoundingClientRect().top>=0&&d.getBoundingClientRect().bottom<=innerHeight}));assert(initial.open&&initial.within);await page.screenshot({path:path.join(evidence,profile.name+'-dialog.png')});
  await page.locator('#viewer-game-character').selectOption('101');await page.waitForFunction(()=>Array.from(document.getElementById('viewer-game-costume').options).some(n=>n.value==='suit:1'));
  await page.locator('#viewer-game-costume').selectOption('suit:1');await page.locator('#viewer-game-download').uncheck();await page.locator('#viewer-game-import').click();
  await page.waitForFunction(()=>!document.getElementById('viewer-game-assets-dialog').open&&ModelViewer.getState().loaded&&!ModelViewer.getState().loading);
  const opened=await page.evaluate(()=>({state:ModelViewer.getState(),probe:ModelViewer.renderProbe(33)}));assert.equal(opened.state.loadedPaths.length,1);assert(opened.state.loadedPaths[0].includes('/game-models/'));assert(opened.probe.ready&&opened.probe.glError===0&&opened.probe.nonBackgroundSamples>=3);
  // Reuse the real game catalog/decrypt picker for the donor without replacing
  // the main wearer or its camera/authoring session.
  const donorPanel=page.locator('#viewer-costume-transplant');await donorPanel.evaluate(node=>node.open=true);
  await donorPanel.locator('[data-transplant-label="Load donor from game"]').click();
  await page.waitForFunction(()=>document.getElementById('viewer-game-character').options.length>1);
  await page.locator('#viewer-game-character').selectOption('101');await page.waitForFunction(()=>document.getElementById('viewer-game-costume').value==='suit:1');
  await page.locator('#viewer-game-download').uncheck();await page.locator('#viewer-game-import').click();
  await page.waitForFunction(()=>!document.getElementById('viewer-game-assets-dialog').open);
  await donorPanel.locator('.viewer-transplant-stage canvas').waitFor({state:'visible'});
  const donorState=await page.evaluate(()=>ModelViewer.getState());assert.equal(donorState.modelId,opened.state.modelId);
  assert(donorState.transplants.donors.find(row=>row.operation==='costume').donor.includes('/game-models/'));
  // Closing the dialog discards stale requests without clearing the loaded model.
  await page.locator('#viewer-game-assets').click();await page.waitForFunction(()=>document.getElementById('viewer-game-character').options.length>1);
  await page.locator('#viewer-game-search').fill('Rina');await page.waitForFunction(()=>document.getElementById('viewer-game-costume').value==='suit:2');
  await page.waitForFunction(()=>!document.getElementById('viewer-game-variant').parentElement.hidden);await page.locator('#viewer-game-variant').selectOption('unmasked');
  await page.keyboard.press('Escape');assert.equal(await page.locator('#viewer-game-assets-dialog').evaluate(d=>d.open),false);assert.equal((await page.evaluate(()=>ModelViewer.getState())).modelId,opened.state.modelId);
  // Delay a real POST (not its result) to exercise close-before-job-id races.
  await page.locator('#viewer-game-assets').click();await page.waitForFunction(()=>document.getElementById('viewer-game-character').options.length>1);
  await page.locator('#viewer-game-character').selectOption('209');await page.waitForFunction(()=>document.getElementById('viewer-game-costume').value==='suit:2');
  let submitted;const submitting=new Promise(resolve=>submitted=resolve);
  await page.route('**/api/viewer/game/import?**',async route=>{submitted();await new Promise(resolve=>setTimeout(resolve,200));await route.continue();});
  const cancelled=page.waitForRequest(request=>/\/api\/jobs\/[a-f0-9]+\/cancel$/.test(request.url()));
  await page.locator('#viewer-game-import').click();await submitting;await page.locator('#viewer-game-assets-dialog .modal-head button').click();await cancelled;
  await page.unroute('**/api/viewer/game/import?**');
  assert.equal(await page.locator('#viewer-game-assets-dialog').evaluate(d=>d.open),false);assert.equal((await page.evaluate(()=>ModelViewer.getState())).modelId,opened.state.modelId);
  await page.screenshot({path:path.join(evidence,profile.name+'.png')});assert.deepEqual(errors,[]);
  report.cases.push({profile,dialog:initial,loadedPaths:opened.state.loadedPaths,probe:opened.probe,donorGameSelectionKeepsWearer:true,exactRinaVariantListed:true,escapePreservesModel:true,lateCancelledImportPreservesModel:true,pageErrors:errors});
  await context.close();
 }
 report.sourceAfter=hashes();assert.deepEqual(report.sourceAfter,report.sourceBefore);report.status='PASS';
}catch(error){report.status='FAIL';report.error=error.stack||String(error);process.exitCode=1;}
finally{if(browser)await browser.close();if(child&&child.exitCode===null)child.kill('SIGTERM');fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,evidence,error:report.error}));}})();
