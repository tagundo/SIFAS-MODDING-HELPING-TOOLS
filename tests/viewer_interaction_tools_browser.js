/* Actual Unity/HTTP/WebGL navigation and editing-mode regression.
 * A neutral local Unity fixture is opened through the real backend. No model
 * preparation, editing controller, camera or export response is mocked.
 */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),python=process.env.VIEWER_PYTHON||'python3',out=process.env.EVIDENCE_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'viewer-interaction-browser-'));fs.mkdirSync(out,{recursive:true});
const library=fs.mkdtempSync(path.join(os.tmpdir(),'viewer-nav-library-')),source=path.join(library,'extracted/3d_model/neutral.unity');fs.mkdirSync(path.dirname(source),{recursive:true});fs.copyFileSync(root+'/tests/fixtures/viewer_persistence.unity',source);
const wait=ms=>new Promise(r=>setTimeout(r,ms)),dist=s=>Math.hypot(...s.camera.position.map((v,i)=>v-s.camera.target[i]));
let server,browser;const report={status:'RUNNING',scope:'Actual product Unity/HTTP/Chromium141 model navigation; no prepared model/export response is mocked.',cases:[],errors:[]};
async function snapshot(page){return page.evaluate(()=>({camera:ModelViewer.getState().camera,interaction:ModelViewer.getState().interaction,authoring:ModelViewer.getAuthoringState(),texture:ModelViewer.getTextureTools().getState().sceneMode}));}
async function drag(page,dy=45,dx=50){const box=await page.locator('#viewer-canvas').boundingBox();await page.mouse.move(box.x+box.width*.55,box.y+box.height*.45);await page.mouse.down();await page.mouse.move(box.x+box.width*.55+dx,box.y+box.height*.45+dy,{steps:8});await page.mouse.up();await wait(450);}
async function init(context,url){const p=await context.newPage();p.on('pageerror',e=>report.errors.push(String(e)));await p.goto(url);await p.waitForFunction(()=>typeof openModelViewer==='function');assert(await p.evaluate(()=>!!window.ViewerInteractionTools),'The normal app index bundles viewport interaction tools');await p.evaluate(s=>{document.getElementById('viewer-auto-face').checked=false;openModelViewer([s]);},source);await p.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading&&!!ModelViewer.getState().interaction);await wait(150);return p;}
async function hit(page,reveal=false){return page.locator('#viewer-interaction-tools').evaluate((host,reveal)=>{const stage=document.getElementById('viewer-stage').getBoundingClientRect(),row=host.querySelector('.viewer-interaction-row');return [...row.children].map(b=>{if(reveal)b.scrollIntoView({block:'nearest',inline:'nearest'});const r=b.getBoundingClientRect(),e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return{id:b.id,x:r.x,y:r.y,width:r.width,height:r.height,within:r.left>=stage.left&&r.right<=stage.right&&r.top>=stage.top&&r.bottom<=stage.bottom,hit:e===b||b.contains(e)};});},reveal);}
async function touch(page,points){const cdp=await page.context().newCDPSession(page);await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:points[0]});for(const row of points.slice(1)){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:row});await wait(45);}await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await cdp.detach();await wait(350);}
async function assertLeftRail(page) {
  const rail = await page.locator('#viewer-interaction-tools').evaluate(host => {
    const stage = document.getElementById('viewer-stage').getBoundingClientRect(), box = host.getBoundingClientRect();
    const buttons = [...host.querySelectorAll('.viewer-interaction-row > button')];
    return { edge: host.dataset.viewerFramingEdge, orientation: host.firstElementChild.getAttribute('aria-orientation'),
      leftHalf: box.right <= stage.left + stage.width / 2,
      buttons: buttons.map(button => ({ id: button.id, x: button.getBoundingClientRect().x, y: button.getBoundingClientRect().y })) };
  });
  assert.equal(rail.edge, 'left'); assert.equal(rail.orientation, 'vertical'); assert(rail.leftHalf);
  assert(rail.buttons.every((button, index) => !index || button.x === rail.buttons[0].x && button.y > rail.buttons[index - 1].y),
    'Model interaction buttons form one vertical column on the left');
  const edit = rail.buttons.findIndex(button => button.id === 'viewer-interaction-edit');
  assert.equal(rail.buttons[edit + 1].id, 'viewer-interaction-clear', 'Clear selection sits directly below Edit');
  return rail;
}
async function reveal(page, selector) {
  const target = page.locator(selector);
  await target.evaluate(element => { for (let parent = element.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; });
  return target;
}
async function verifyClearSelection(page) {
  await (await reveal(page, '#viewer-mesh-modify-load')).click();
  await page.waitForFunction(() => [...document.getElementById('viewer-mesh-modify-select').options].some(option => option.value && !option.disabled));
  const mesh = await page.locator('#viewer-mesh-modify-select option').evaluateAll(options => options.find(option => option.value && !option.disabled).value);
  await page.locator('#viewer-mesh-modify-select').selectOption(mesh);
  await page.waitForFunction(() => !ModelViewer.getState().meshTools.busy && ModelViewer.getState().meshTools.runtime.boundPrimitives > 0);
  await page.locator('#viewer-stage').scrollIntoViewIfNeeded();
  await page.locator('#viewer-interaction-edit').click(); await page.locator('[data-viewer-edit-action="modify:pick"]').click();
  const all = page.locator('#viewer-mesh-modify').getByRole('button', { name: 'Select all', exact: true, includeHidden: true });
  await all.evaluate(button => { for (let parent = button.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; });
  await all.click();
  await page.waitForFunction(() => ModelViewer.getState().meshTools.selectedVertices.length > 0);
  await page.locator('#viewer-stage').scrollIntoViewIfNeeded();
  await page.waitForFunction(() => !document.getElementById('viewer-interaction-clear').disabled);
  const before = await snapshot(page), selected = await page.evaluate(() => ModelViewer.getState().meshTools.selectedVertices);
  await page.locator('#viewer-interaction-clear').click();
  const after = await snapshot(page);
  assert.deepEqual(await page.evaluate(() => ModelViewer.getState().meshTools.selectedVertices), []);
  assert.deepEqual(after.camera, before.camera, 'Clear selection preserves the exact camera');
  assert.deepEqual(after.authoring, before.authoring, 'Clear selection preserves authored mesh/body/texture edits');
  assert.equal(after.interaction.mode, before.interaction.mode); assert.equal(after.interaction.edit, before.interaction.edit);
  assert(await page.locator('#viewer-interaction-clear').isDisabled(), 'Clear selection becomes unavailable when the active selection is empty');
  await (await reveal(page, '#viewer-mesh-modify-undo')).click();
  assert.deepEqual(await page.evaluate(() => ModelViewer.getState().meshTools.selectedVertices), selected, 'Selection clearing is undoable');
  await page.locator('#viewer-stage').scrollIntoViewIfNeeded(); await page.locator('#viewer-interaction-clear').click();
  report.cases.push('Left-rail Clear removes actual vertex selection, retains edits/mode/camera and supports Undo');

  await page.locator('#viewer-interaction-edit').click(); await page.locator('[data-viewer-edit-action="texture:face"]').click();
  await page.waitForFunction(() => [...document.getElementById('viewer-texture-select').options].some(option => option.value && !option.disabled));
  const texture = await page.locator('#viewer-texture-select option').evaluateAll(options => options.find(option => option.value && !option.disabled).value);
  await (await reveal(page, '#viewer-texture-select')).selectOption(texture);
  await page.waitForFunction(() => { const state = ModelViewer.getTextureTools().getState(); return !state.loading && !!state.selection; });
  await (await reveal(page, '#viewer-texture-select-all')).click();
  await page.waitForFunction(() => ModelViewer.getTextureTools().getState().selection.selectedPixels > 0);
  await page.locator('#viewer-stage').scrollIntoViewIfNeeded();
  report.textureClearSelection = await page.evaluate(() => ({
    canClear: ModelViewer.getTextureTools().canClearSelection(), buttonDisabled: document.getElementById('viewer-interaction-clear').disabled,
    selection: ModelViewer.getTextureTools().getState().selection, interaction: ModelViewer.getState().interaction
  }));
  await page.waitForFunction(() => !document.getElementById('viewer-interaction-clear').disabled);
  const textureBefore = await snapshot(page);
  await page.locator('#viewer-interaction-clear').click();
  const textureAfter = await snapshot(page);
  assert.equal(await page.evaluate(() => ModelViewer.getTextureTools().getState().selection.selectionActive), false);
  assert.deepEqual(textureAfter.camera, textureBefore.camera); assert.deepEqual(textureAfter.authoring, textureBefore.authoring);
  assert.equal(textureAfter.interaction.edit, textureBefore.interaction.edit);
  assert(await page.locator('#viewer-interaction-clear').isDisabled());
  report.cases.push('Left-rail Clear removes actual texture selection without changing pixels or editing mode');
}
async function verifyMediumFontHud(page) {
  const rows = [];
  for (const fontSize of [18, 20, 22, 24, 28, 36]) {
    await page.locator('#viewer-interaction-tools').evaluate((host, size) => { host.style.fontSize = size + 'px'; }, fontSize);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const row = await page.locator('#viewer-interaction-tools').evaluate(host => {
      const stage = document.getElementById('viewer-stage').getBoundingClientRect();
      function inspect(control) {
        const box = control.getBoundingClientRect(), target = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
        return { id: control.id, text: control.textContent, disabled: !!control.disabled,
          width: box.width, height: box.height,
          inside: box.left >= stage.left && box.right <= stage.right && box.top >= stage.top && box.bottom <= stage.bottom,
          hit: target === control || control.contains(target), actualTarget: target && { id: target.id, text: target.textContent } };
      }
      return { font: getComputedStyle(host).fontSize, iconsOnly: host.classList.contains('viewer-interaction-icons-only'),
        navigation: [...host.querySelectorAll('.viewer-interaction-row > button')].map(inspect),
        existingHUD: [...document.querySelectorAll('#viewer-stage [data-viewer-hud-control]')]
          .filter(control => !host.contains(control) && control.getClientRects().length && getComputedStyle(control).visibility !== 'hidden')
          .map(inspect).filter(control => control.width && control.height) };
    });
    rows.push(row);
    assert(row.navigation.every(control => control.hit && control.inside && control.height >= 44),
      'Medium font navigation controls stay inside and clickable: ' + JSON.stringify(row));
    assert(row.existingHUD.filter(control => !control.disabled).every(control => control.hit && control.inside),
      'Navigation never covers existing camera/pose/HUD targets: ' + JSON.stringify(row));
  }
  // Return the fixture to its ordinary labels before independently forcing
  // the separate oversized-text fallback case below.
  await page.locator('#viewer-interaction-tools').evaluate(host => {
    host.style.fontSize = '';
    ModelViewer.getInteractionTools().refreshLayout();
  });
  return rows;
}
async function forceOverflow(page) {
  const fixture = await page.locator('#viewer-interaction-tools').evaluate(host => {
    // Narrow stages start as icons; expose real labels for this overflow fixture.
    host.classList.remove('viewer-interaction-icons-only');
    const labels = [...host.querySelectorAll('.viewer-interaction-label')];
    const button = host.querySelector('button'), stage = document.getElementById('viewer-stage');
    const context = document.createElement('canvas').getContext('2d');
    let fontSize = 36, widths = [], total = 0;
    const margin = 32;
    // Font fallback varies by runner. Measure text independently of the HUD's
    // sizing code and force real text overflow before expecting icon fallback.
    for (let attempt = 0; attempt < 8; attempt++) {
      host.style.fontSize = fontSize + 'px';
      const style = getComputedStyle(button);
      context.font = [style.fontStyle, style.fontWeight, style.fontSize, style.fontFamily].join(' ');
      widths = labels.map(label => context.measureText(label.textContent).width);
      total = widths.reduce((sum, value) => sum + value, 0);
      if (total > stage.clientWidth + margin) break;
      fontSize = Math.ceil(fontSize * 1.4);
    }
    return { fontSize, canvasFont: context.font, measuredLabelWidths: widths,
      textWidth: total, stageWidth: stage.clientWidth, margin,
      actualDOMTextWidthBeforeFallback: labels.reduce((sum, label) => sum + label.getBoundingClientRect().width, 0) };
  });
  assert(fixture.textWidth > fixture.stageWidth + fixture.margin,
    'Large-text fixture actually exceeds the stage width: ' + JSON.stringify(fixture));
  assert(fixture.actualDOMTextWidthBeforeFallback > fixture.stageWidth,
    'Rendered labels independently confirm actual overflow: ' + JSON.stringify(fixture));
  await page.waitForFunction(() => document.getElementById('viewer-interaction-tools').classList.contains('viewer-interaction-icons-only'), null, { timeout: 2000 });
  return fixture;
}
async function verifyShortViewport(browser, url) {
  const context = await browser.newContext({ viewport: { width: 840, height: 195 }, hasTouch: true });
  await context.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
  try {
    const page = await init(context, url);
    await page.locator('#viewer-fit').click();
    const geometry = await page.locator('#viewer-interaction-tools').evaluate(host => {
      const stage = document.getElementById('viewer-stage').getBoundingClientRect(), row = host.getBoundingClientRect();
      return { edge: host.dataset.viewerFramingEdge, stage: stage.toJSON(), row: row.toJSON(),
        existingHUD: [...document.querySelectorAll('#viewer-stage [data-viewer-hud-control]')]
          .filter(button => !host.contains(button) && !button.disabled && button.getClientRects().length)
          .map(button => { const r = button.getBoundingClientRect(), target = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            return { id: button.id, hit: target === button || button.contains(target) }; }) };
    });
    report.shortViewport = geometry;
    assert.equal(geometry.stage.height, 195, 'Exercise the actual short-window layout');
    assert.equal(geometry.edge, 'left', 'Short-window controls retain the left vertical rail');
    assert(geometry.row.right < geometry.stage.x + geometry.stage.width / 2);
    assert(geometry.row.top >= geometry.stage.top && geometry.row.bottom <= geometry.stage.bottom);
    const beforeRailScroll = await snapshot(page), pageScroll = await page.evaluate(() => scrollY);
    const scrollX = geometry.row.x + geometry.row.width / 2;
    await touch(page, [[{ x: scrollX, y: geometry.row.bottom - 20, id: 1 }], [{ x: scrollX, y: geometry.row.top + 30, id: 1 }]]);
    assert(await page.locator('.viewer-interaction-row').evaluate(row => row.scrollTop > 0), 'A real one-finger swipe scrolls the short rail');
    assert.equal(await page.evaluate(() => scrollY), pageScroll, 'Scrolling the rail keeps the model on screen');
    assert.deepEqual((await snapshot(page)).camera, beforeRailScroll.camera, 'Scrolling the rail does not orbit the model');
    report.shortViewport.reachableButtons = await hit(page, true);
    assert(report.shortViewport.reachableButtons.every(button => button.hit && button.within && button.height >= 44), 'Every full-size touch target remains reachable by scrolling only the short rail');
    assert(geometry.existingHUD.every(button => button.hit), 'Left rail keeps all existing HUD controls clickable');
    const before = await snapshot(page), x = geometry.stage.x + geometry.stage.width * .62, y = geometry.stage.y + geometry.stage.height * .74;
    await page.mouse.move(x, y); await page.mouse.down({ button: 'right' });
    await page.mouse.move(x + 12, y + 5, { steps: 3 }); await page.mouse.up({ button: 'right' });
    await wait(200);
    assert.notDeepEqual((await snapshot(page)).camera.target, before.camera.target,
      'The short model area remains available for a real right-drag pan');
    await page.locator('#viewer-interaction-edit').click();
    const chooser = await page.locator('#viewer-interaction-edit-menu').evaluate(menu => {
      const r = menu.getBoundingClientRect(), stage = document.getElementById('viewer-stage').getBoundingClientRect();
      const button = menu.querySelector('button:not(:disabled)'), b = button.getBoundingClientRect(), target = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
      return { box: r.toJSON(), inside: r.left >= stage.left && r.right <= stage.right && r.top >= stage.top && r.bottom <= stage.bottom,
        firstAction: button.dataset.viewerEditAction, hit: target === button || button.contains(target) };
    });
    report.shortViewport.chooser = chooser;
    assert(chooser.inside && chooser.hit, 'The left rail opens its Edit chooser inside the short viewport');
    await page.locator('[data-viewer-edit-action="' + chooser.firstAction + '"]').click();
    assert.equal((await snapshot(page)).interaction.mode, 'edit');
    assert.equal((await snapshot(page)).interaction.menuOpen, false);
    await page.screenshot({ path: path.join(out, 'short-viewport.png') });
  } finally { await context.close(); }
}
async function verifyShortPhoneRail(browser, url) {
  const context = await browser.newContext({ viewport: { width: 360, height: 456 }, hasTouch: true });
  await context.addInitScript(() => localStorage.setItem('sifas_lang', 'en'));
  try {
    const page = await init(context, url);
    await page.locator('#viewer-stage').scrollIntoViewIfNeeded();
    report.shortPhoneRail = await page.locator('#viewer-interaction-tools').evaluate(host => {
      const stage = document.getElementById('viewer-stage').getBoundingClientRect(), box = host.getBoundingClientRect(), row = host.firstElementChild;
      return { leftInset: box.left - stage.left, height: box.height, scrolling: row.scrollHeight > row.clientHeight,
        existingHUD: [...document.querySelectorAll('#viewer-stage [data-viewer-hud-control]')]
          .filter(button => !host.contains(button) && !button.disabled && button.getClientRects().length)
          .map(button => { const r = button.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            return { id: button.id, hit: hit === button || button.contains(hit) }; }) };
    });
    assert(report.shortPhoneRail.leftInset <= 12, 'Use the left gap below pose controls rather than moving the rail toward the model center');
    assert(report.shortPhoneRail.scrolling, 'The short phone rail scrolls in the available left-side gap');
    assert(report.shortPhoneRail.existingHUD.every(button => button.hit));
    report.shortPhoneRail.reachableButtons = await hit(page, true);
    assert(report.shortPhoneRail.reachableButtons.every(button => button.hit && button.within && button.height >= 44));
    await page.screenshot({ path: path.join(out, 'short-phone-rail.png') });
  } finally { await context.close(); }
}
(async()=>{try{const sock=net.createServer();await new Promise(r=>sock.listen(0,'127.0.0.1',r));const port=sock.address().port;await new Promise(r=>sock.close(r));const stream=fs.createWriteStream(path.join(out,'server.log'));server=spawn(python,['-B','-m','webtools','--no-browser','--host','127.0.0.1','--port',String(port)],{cwd:root,env:{...process.env,SUKUSTA_DIR:library,PYTHONPATH:root+':'+path.dirname(root)},stdio:['ignore','pipe','pipe']});server.stdout.pipe(stream);server.stderr.pipe(stream);const url='http://127.0.0.1:'+port;for(let i=0;i<100;i++){try{if((await fetch(url+'/api/tools')).ok)break;}catch{}await wait(100);}browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||undefined,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext({viewport:{width:1360,height:900}});await context.addInitScript(()=>localStorage.setItem('sifas_lang','en'));const p=await init(context,url);const original=await snapshot(p),before=await snapshot(p);await p.locator('#viewer-interaction-orbit').click();await drag(p);const rotated=await snapshot(p);assert.notDeepEqual(rotated.camera.position,before.camera.position);report.cases.push('Rotate button orbits actual camera');
await p.locator('#viewer-interaction-pan').click();const panBefore=await snapshot(p);await drag(p,20,50);const panned=await snapshot(p);assert.notDeepEqual(panned.camera.target,panBefore.camera.target);assert(Math.abs(dist(panned)-dist(panBefore))<.04);report.cases.push('Pan button translates camera and target without changing zoom distance');
await p.locator('#viewer-interaction-zoom').click();const zoomBefore=await snapshot(p);await drag(p,50,0);const zoomed=await snapshot(p);assert(Math.abs(dist(zoomed)-dist(zoomBefore))>.005);assert.deepEqual(zoomed.camera.target,zoomBefore.camera.target,'Zoom retains exact target after a mode switch');report.cases.push('Zoom button maps mouse drag to dolly');
await p.locator('#viewer-canvas').focus();await p.keyboard.press('r');assert.equal((await snapshot(p)).interaction.mode,'orbit');await p.keyboard.press('g');assert.equal((await snapshot(p)).interaction.mode,'pan');await p.keyboard.press('z');assert.equal((await snapshot(p)).interaction.mode,'zoom');report.cases.push('Viewport R/G/Z shortcuts switch modes');
await p.locator('#viewer-interaction-edit').click();await p.locator('[data-viewer-edit-action="texture:face"]').click();assert.equal((await snapshot(p)).texture,'face');assert.equal((await snapshot(p)).interaction.mode,'edit');await p.locator('#viewer-interaction-edit').click();await p.keyboard.press('ArrowDown');assert(await p.evaluate(()=>document.activeElement.matches('[data-viewer-edit-action]')));await p.keyboard.press('Escape');assert.equal(await p.evaluate(()=>document.activeElement.id),'viewer-interaction-edit');assert.equal((await snapshot(p)).interaction.menuOpen,false);report.cases.push('Edit chooser supports arrow navigation and Escape restores its invoking control');const authoring=await p.evaluate(()=>ModelViewer.getAuthoringState());await p.locator('#viewer-canvas').focus();await p.keyboard.down('Space');assert.equal((await snapshot(p)).interaction.mode,'orbit');const box=await p.locator('#viewer-canvas').boundingBox();await p.mouse.move(box.x+box.width*.56,box.y+box.height*.4);await p.mouse.down();await p.mouse.move(box.x+box.width*.56+30,box.y+box.height*.4+10,{steps:5});await p.keyboard.up('Space');assert.equal((await snapshot(p)).interaction.temporary,true);await p.mouse.up();await p.waitForFunction(()=>ModelViewer.getState().interaction.mode==='edit');assert.equal((await snapshot(p)).texture,'face');assert.deepEqual(await p.evaluate(()=>ModelViewer.getAuthoringState()),authoring);report.cases.push('Space navigation restores editing even when released before the pointer');
await p.locator('#viewer-canvas').focus();await p.keyboard.down('Space');await p.evaluate(()=>dispatchEvent(new Event('blur')));assert.equal((await snapshot(p)).interaction.temporary,false);assert.equal((await snapshot(p)).texture,'face');await p.keyboard.up('Space');report.cases.push('Window blur clears temporary navigation without a stuck mode');
await p.evaluate(()=>{const i=document.createElement('input');i.id='qa-typing';document.body.prepend(i);i.focus();});await p.keyboard.press('r');assert.equal((await snapshot(p)).interaction.mode,'edit');await p.evaluate(()=>document.getElementById('qa-typing').remove());report.cases.push('Typing does not trigger viewport shortcuts');
const rects=await hit(p);assert(rects.every(r=>r.hit&&r.within));report.desktopHUD=rects;report.desktopRail=await assertLeftRail(p);await p.screenshot({path:path.join(out,'desktop.png')});report.cases.push('Desktop controls are inside the viewport and unobstructed');await verifyClearSelection(p);await context.close();
const mobile=await browser.newContext({viewport:{width:360,height:800},hasTouch:true});await mobile.addInitScript(()=>localStorage.setItem('sifas_lang','ko'));const m=await init(mobile,url);await m.locator('#viewer-stage').scrollIntoViewIfNeeded();await m.locator('#viewer-interaction-pan').click();const mb=await m.locator('#viewer-canvas').boundingBox(),pt=(x,y,id=1)=>({x:mb.x+x,y:mb.y+y,id});const mp=await snapshot(m);await touch(m,[[pt(mb.width*.58,mb.height*.4)],[pt(mb.width*.58+35,mb.height*.4+20)]]);assert.notDeepEqual((await snapshot(m)).camera.target,mp.camera.target);report.cases.push('Pan uses one finger on the actual touch viewport');
await m.locator('#viewer-interaction-zoom').click();const mz=await snapshot(m);await touch(m,[[pt(mb.width*.58,mb.height*.4)],[pt(mb.width*.58,mb.height*.4+65)]]);assert(Math.abs(dist(await snapshot(m))-dist(mz))>.005);report.cases.push('Zoom uses one-finger drag on touch');
const pinch=await snapshot(m);await touch(m,[[pt(mb.width*.45,mb.height*.4,1),pt(mb.width*.65,mb.height*.4,2)],[pt(mb.width*.40,mb.height*.4,1),pt(mb.width*.70,mb.height*.4,2)]]);assert(Math.abs(dist(await snapshot(m))-dist(pinch))>.005);report.cases.push('Two-finger pinch remains available in Zoom mode');const mr=await hit(m);assert(mr.every(r=>r.hit&&r.within&&r.height>=44));report.mobileHUD=mr;report.mobileRail=await assertLeftRail(m);await m.screenshot({path:path.join(out,'mobile.png')});assert.deepEqual((await snapshot(m)).authoring,original.authoring);report.cases.push('Touch controls have usable targets and navigation never alters model edits');report.mediumFontProbes=await verifyMediumFontHud(m);report.cases.push('Medium font navigation preserves all existing HUD targets');report.overflowFixture=await forceOverflow(m);report.large=await m.locator('#viewer-interaction-tools').evaluate(e=>({className:e.className,font:getComputedStyle(e).fontSize,buttonFont:getComputedStyle(e.querySelector('button')).fontSize,rowWidth:e.firstElementChild.getBoundingClientRect().width,scroll:e.firstElementChild.scrollWidth,stage:document.getElementById('viewer-stage').clientWidth,labels:[...e.querySelectorAll('.viewer-interaction-label')].map(x=>({text:x.textContent,font:getComputedStyle(x).fontSize,width:x.getBoundingClientRect().width,scroll:x.scrollWidth}))}));assert(await m.locator('#viewer-interaction-tools').evaluate(e=>e.classList.contains('viewer-interaction-icons-only')));assert((await hit(m)).every(r=>r.hit&&r.within));await m.screenshot({path:path.join(out,'mobile-large-labels.png')});report.cases.push('Large text uses accessible icon targets rather than clipped labels');await mobile.close();await verifyShortViewport(browser,url);report.cases.push('Short-window left controls preserve real pan and open a usable side Edit chooser');await verifyShortPhoneRail(browser,url);report.cases.push('Short phones keep the rail in the actual left gap with all controls reachable');assert.deepEqual(report.errors,[]);report.status='PASS';console.log(JSON.stringify({status:report.status,cases:report.cases.length,evidence:out}));}catch(e){report.status='FAIL';report.error=String(e.stack||e);console.error(e);}finally{if(browser)await browser.close();if(server)server.kill();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');if(report.status!=='PASS')process.exitCode=1;}})();
