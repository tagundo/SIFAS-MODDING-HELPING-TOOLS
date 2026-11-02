/* Run against the local WebUI: VIEWER_URL=http://127.0.0.1:8898 node tests/viewer_rig_browser.js.
 * All geometry/skin/morph/animation data below is generated; no game asset is used.
 */
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

function fixture(options = {}) {
  const chunks = [], views = [], accessors = [];
  let length = 0;
  function attribute(values, Type, type, componentType, count, bounds) {
    const raw = Buffer.from(new Type(values).buffer);
    const padding = (4 - length % 4) % 4; if (padding) { chunks.push(Buffer.alloc(padding)); length += padding; }
    const view = views.length; views.push({ buffer: 0, byteOffset: length, byteLength: raw.length }); chunks.push(raw); length += raw.length;
    const result = { bufferView: view, componentType, count, type };
    if (bounds) Object.assign(result, bounds);
    accessors.push(result); return accessors.length - 1;
  }
  const offset=options.shifted?50:0;
  const positions = attribute([offset-.3,0,0,offset+.3,0,0,offset,1.2,0], Float32Array, 'VEC3', 5126, 3, {min:[offset-.3,0,0],max:[offset+.3,1.2,0]});
  const normals = attribute([0,0,1,0,0,1,0,0,1], Float32Array, 'VEC3', 5126, 3);
  const uv = attribute([0,0,1,0,.5,1], Float32Array, 'VEC2', 5126, 3);
  const joints = attribute(options.allSaved?[2,0,0,0,3,0,0,0,1,0,0,0]:[0,0,0,0,0,0,0,0,1,0,0,0], Uint16Array, 'VEC4', 5123, 3);
  const weights = attribute([1,0,0,0,1,0,0,0,1,0,0,0], Float32Array, 'VEC4', 5126, 3);
  const indices = attribute([0,1,2], Uint16Array, 'SCALAR', 5123, 3);
  const morph = attribute([0,0,0,0,0,0,.2,0,0], Float32Array, 'VEC3', 5126, 3);
  const identity = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
  const breastBind = identity.slice(); breastBind[13] = -.5;
  const tipBind = identity.slice(); tipBind[13] = -1.5;
  const childBind=identity.slice();childBind[13]=-2;
  const binds = attribute(identity.concat(breastBind,tipBind,options.allSaved?childBind:[]), Float32Array, 'MAT4', 5126, options.allSaved?4:3);
  const times = attribute([0,1], Float32Array, 'SCALAR', 5126, 2, {min:[0],max:[1]});
  const rotationStart=options.rotationStart||0,clipName=options.previewName||'Synthetic test motion';
  const rotations = attribute([0,0,rotationStart,Math.sqrt(1-rotationStart*rotationStart),0,0,.5,Math.sqrt(.75)], Float32Array, 'VEC4', 5126, 2);
  const doc = {asset:{version:'2.0',generator:'Original synthetic rig regression'},scene:0,scenes:[{nodes:[0]}],
    nodes:[{name:'SyntheticRoot',children:[1,4],extras:{elichika_node:0,role:'root'}},
      {name:'Move',translation:[-offset,0,0],children:[2],extras:{elichika_node:1,role:'bone'}},
      {name:'BreastSize',translation:[0,.5,0],children:[3],extras:{elichika_node:2,role:'bone'}},
      {name:'Tip',translation:[0,1,0],extras:{elichika_node:3,role:'bone'}},
      {name:'SyntheticTriangle',mesh:0,skin:0,extras:{elichika_node:4,role:'mesh'}}],
    skins:[{joints:[1,2,3],inverseBindMatrices:binds,skeleton:1}],
    meshes:[{name:'SyntheticTriangle',weights:[0],extras:{targetNames:['SyntheticExpression']},primitives:[{attributes:{POSITION:positions,NORMAL:normals,TEXCOORD_0:uv,JOINTS_0:joints,WEIGHTS_0:weights},indices,material:0,targets:[{POSITION:morph}]}]}],
    animations:[{name:clipName,samplers:[{input:times,output:rotations,interpolation:'LINEAR'}],channels:[{sampler:0,target:{node:2,path:'rotation'}}]}],
    materials:[{name:'Synthetic neutral material',pbrMetallicRoughness:{baseColorFactor:[.8,.15,.1,1],metallicFactor:0,roughnessFactor:1},extensions:{KHR_materials_unlit:{}}}],
    extensionsUsed:['KHR_materials_unlit'],buffers:[{byteLength:length}],bufferViews:views,accessors};
  doc.animations.push(Object.assign({},doc.animations[0],{name:'Synthetic motion visibility'}));
  if(options.allSaved){
    doc.nodes[3].name='LeftSkirtA_Dyna';doc.nodes[3].children=[5];
    doc.nodes.push({name:'LeftSkirtChild_Dyna',translation:[0,.5,0],extras:{elichika_node:5,role:'bone'}});
    doc.skins[0].joints.push(5);
  }
  if(options.shader)doc.materials[0].extras={sifas:{version:1,shader:'AS/Member',colors:{_TintColor:[.2,.5,.8,1],_AmbientColor:[1,1,1,0]},floats:{_CullMode:0},features:{},textures:{}}};
  const json = Buffer.from(JSON.stringify(doc)), jsonPadded = Buffer.concat([json,Buffer.alloc((4-json.length%4)%4,32)]);
  const bin = Buffer.concat(chunks), binPadded = Buffer.concat([bin,Buffer.alloc((4-bin.length%4)%4)]);
  const header = Buffer.alloc(12), jh = Buffer.alloc(8), bh = Buffer.alloc(8);
  header.writeUInt32LE(0x46546c67,0);header.writeUInt32LE(2,4);header.writeUInt32LE(12+8+jsonPadded.length+8+binPadded.length,8);
  jh.writeUInt32LE(jsonPadded.length);jh.writeUInt32LE(0x4e4f534a,4);bh.writeUInt32LE(binPadded.length);bh.writeUInt32LE(0x004e4942,4);
  const controls = [{id:'height',node:1,min:50,max:150},{id:'breast',node:2,min:25,max:200}].map(c=>({id:c.id,available:true,default:100,min:c.min,max:c.max,unit:'percent',mode:'multiply_authored_local_scale',nodes:[{node:c.node,axes:[1,1,1]}]}));
  const components=[{targetName:'SyntheticFixture',heightScale:.97,entries:[
    {node:2,kind:'scale',supported:true,application:'absolute_local_scale',origin:[1,1,1],scaled:[1.3,.9,1],state:'pending'},
    {node:3,kind:'rotation',supported:false,application:null,scaled:[20,0,0]},
    {node:3,kind:'position',supported:true,application:'absolute_local_position',scaled:[0,1,0]},
    {node:3,kind:'position',supported:true,application:'absolute_local_position',scaled:[0,2,0]}
  ]}];
  if(options.allSaved){
    const quaternion=[Math.sin(Math.PI/12),0,0,Math.cos(Math.PI/12)];
    const rotation=value=>({node:3,name:'LeftSkirtA_Dyna',kind:'rotation',supported:true,application:'absolute_local_quaternion',scaledQuaternion:value,scaled:value,origin:[0,0,0,1]});
    components[0].entries=[
      {node:2,name:'BreastSize',kind:'scale',supported:true,application:'absolute_local_scale',scaled:[1.3,.9,1]},
      {node:3,name:'LeftSkirtA_Dyna',kind:'position',supported:true,application:'absolute_local_position',scaled:[-.1,.9,0]},
      {node:3,name:'LeftSkirtA_Dyna',kind:'scale',supported:true,application:'absolute_local_scale',scaled:[.7,.7,.7]},
      {node:5,name:'LeftSkirtChild_Dyna',kind:'scale',supported:true,application:'absolute_local_scale',scaled:[.6,.6,.6]},
      rotation(quaternion),rotation(quaternion.map(value=>-value))
    ];
    if(options.rotationConflict)components[0].entries.push(rotation([0,0,0,1]));
  }
  const visibility=(times,values)=>[{node:4,times,values,interpolation:'STEP',sourceProperty:'Renderer.m_Enabled'}];
  const rig = {enabled:true,available:true,root:0,bones:[{node:1,name:'Move'},{node:2,name:'BreastSize'},{node:3,name:'Tip'}],bounds:{min:[-.3,0,0],max:[.3,1.2,0]},scaling:{version:1,baseline:'authored',savedOverridesApplied:false,controls,components},clips:[
    {name:clipName,duration:1,loop:true},
    {name:'Synthetic motion visibility',duration:1,loop:false,visibility:visibility([0,.6],[false,true])},
    {name:'Synthetic visibility only',duration:1,loop:false,channels:0,index:null,visibility:visibility([0,.25,.75],[true,false,true])}
  ]};
  if(options.allSaved){rig.bones[2].name='LeftSkirtA_Dyna';rig.bones.push({node:5,name:'LeftSkirtChild_Dyna'});}
  if(options.metadataWarning)rig.scaling.warnings=['scaling_invalid_entry'];
  if(Object.prototype.hasOwnProperty.call(options,'previewVerified'))rig.previewMotion={name:options.previewReference||clipName,kind:options.previewKind||'sifas_suit_preview',verified:options.previewVerified};
  return {glb:Buffer.concat([header,jh,jsonPadded,bh,binPadded]),rig};
}

(async()=>{
  let generated=fixture();
  const launch={headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']};
  if(process.env.CHROMIUM_EXECUTABLE)launch.executablePath=process.env.CHROMIUM_EXECUTABLE;
  const evidence=process.env.EVIDENCE_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'viewer-rig-'));
  fs.mkdirSync(evidence,{recursive:true});
  const browser=await chromium.launch(launch);
  try {
    const page=await browser.newPage({viewport:{width:1000,height:900}}),errors=[],requests=[],gpuMessages=[];let unsupported=false;
    page.on('pageerror',e=>errors.push(String(e)));
    page.on('console',m=>{if(/WebGL|GL_INVALID|THREE.WebGLProgram/.test(m.text()))gpuMessages.push(m.text());});
    await page.addInitScript(()=>localStorage.setItem('sifas_lang','en'));
    await page.route('**/api/viewer/prepare',route=>{requests.push(route.request().postDataJSON());return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:'rig-fixture',url:'/api/viewer/model/rig-fixture.glb',stats:{meshes:1,vertices:3,triangles:1,materials:1,textures:0},warnings:[],rig:Object.assign({},generated.rig,{available:!unsupported})})});});
    await page.route('**/api/viewer/model/*.glb',route=>route.fulfill({status:200,contentType:'model/gltf-binary',body:generated.glb}));
    await page.goto(process.env.VIEWER_URL||'http://127.0.0.1:8898');
    await page.waitForFunction(()=>typeof openModelViewer==='function'&&!!window.ViewerRig);
    await page.evaluate(()=>openModelViewer(['/synthetic/rig.unity']));
    await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading);
    const state=()=>page.evaluate(()=>ModelViewer.getState());
    const capture=(save,compare)=>page.evaluate(([save,compare])=>{
      const probe=ModelViewer.renderProbe(33),canvas=document.getElementById('viewer-canvas'),gl=canvas.getContext('webgl2')||canvas.getContext('webgl');
      const width=gl.drawingBufferWidth,height=gl.drawingBufferHeight,pixels=new Uint8Array(width*height*4);gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);const error=gl.getError();
      const frames=window.__poseButtonFrames||(window.__poseButtonFrames={});let changedPixels=null;
      if(compare){const previous=frames[compare];if(!previous||previous.length!==pixels.length)throw new Error('Pose comparison viewport changed');changedPixels=0;for(let offset=0;offset<pixels.length;offset+=4)if(Math.abs(pixels[offset]-previous[offset])+Math.abs(pixels[offset+1]-previous[offset+1])+Math.abs(pixels[offset+2]-previous[offset+2])>24)changedPixels++;}
      if(save)frames[save]=pixels;return{probe,glError:error,changedPixels,width,height};
    },[save,compare]);
    const pressed=()=>page.evaluate(()=>['viewer-pose-basic','viewer-pose-preview'].map(id=>document.getElementById(id).getAttribute('aria-pressed')));
    const slider=async(id,value)=>page.locator('#'+id).evaluate((input,value)=>{input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));},value);
    assert.equal(requests[0].rigged,true);
    const initial=await state();assert(initial.rig.available);assert.deepEqual(initial.rig.clipNames,['Synthetic test motion','Synthetic motion visibility','Synthetic visibility only']);
    assert.equal(initial.rig.savedNodes.enabled,true);assert.equal(initial.rig.savedNodes.applied,1);assert.equal(initial.rig.bones.find(b=>b.name==='BreastSize').scale[0],1.3);
    assert.deepEqual(await pressed(),['true','false']);assert(await page.locator('#viewer-pose-preview').isDisabled());assert(await page.locator('#viewer-pose-help').isVisible());
    const probe=await page.evaluate(()=>ModelViewer.renderProbe());assert(probe.ready&&probe.nonBackgroundSamples>0&&probe.glError===0);
    await page.locator('#viewer-adjustments').evaluate(e=>e.open=true);
    await page.locator('#viewer-saved-nodes').uncheck();
    await slider('viewer-height',120);assert.equal((await state()).rig.bones.find(b=>b.name==='Move').scale[1],1.2);
    await slider('viewer-breast',150);assert.equal((await state()).rig.bones.find(b=>b.name==='BreastSize').scale[0],1.5);
    assert.equal((await state()).rig.savedNodes.enabled,false);
    await page.locator('#viewer-saved-nodes').check();
    const saved=await state();assert.equal(saved.rig.savedNodes.applied,1);assert.equal(saved.rig.savedNodes.skipped,3);assert.equal(saved.rig.savedNodes.conflicts,1);
    assert(Math.abs(saved.rig.bones.find(b=>b.name==='BreastSize').scale[0]-1.95)<1e-6);
    assert.deepEqual(saved.rig.bones.find(b=>b.name==='Tip').position,[0,1,0],'Conflicting positions must stay untouched');
    await page.locator('#viewer-saved-nodes').uncheck();assert.equal((await state()).rig.bones.find(b=>b.name==='BreastSize').scale[0],1.5);
    await slider('viewer-height',120);assert.equal((await state()).rig.bones.find(b=>b.name==='Move').scale[1],1.2,'Repeated input must not compound');
    assert.deepEqual((await state()).camera,initial.camera,'Changing body size must preserve the camera');
    const scaledProbe=await page.evaluate(()=>ModelViewer.renderProbe(33));
    await page.locator('#viewer-fit').click();
    assert.notDeepEqual((await state()).camera.position,initial.camera.position,'Fit should account for posed/skinned body bounds');
    await page.locator('#viewer-motion').selectOption('Synthetic test motion');await slider('viewer-time',.5);
    const posed=await state();assert(posed.rig.bones.find(b=>b.name==='BreastSize').quaternion[2]>.2);assert.equal(posed.rig.bones.find(b=>b.name==='BreastSize').scale[0],1.5);
    await slider('viewer-time',1);assert((await state()).rig.bones.find(b=>b.name==='BreastSize').quaternion[2]>.49,'Scrub end must inspect last frame, not wrap to first');await slider('viewer-time',.5);
    await page.locator('#viewer-play').click();await page.waitForTimeout(150);const playing=await state();assert(playing.rig.playing);assert.notEqual(playing.rig.time,posed.rig.time);
    await page.locator('[data-tab="tools"]').click();await page.waitForTimeout(80);const hidden=await state();await page.waitForTimeout(150);assert.equal((await state()).rig.time,hidden.rig.time,'Hidden viewer must not advance animation');
    await page.locator('[data-tab="viewer"]').click();await page.waitForTimeout(120);assert.notEqual((await state()).rig.time,hidden.rig.time,'Visible viewer resumes playback');
    await page.locator('#viewer-play').click();const paused=await state();await page.waitForTimeout(130);assert.equal((await state()).rig.time,paused.rig.time);
    await slider('viewer-expression-value',75);assert.equal((await state()).rig.expressions[0].weight,.75);
    await page.locator('.viewer-node-editor').evaluate(e=>e.open=true);
    await page.locator('#viewer-node').selectOption('3');await page.locator('[data-viewer-node-kind="rotation"][data-axis="X"]').fill('30');
    assert(Math.abs((await state()).rig.bones.find(b=>b.name==='Tip').quaternion[0])>.2);
    await page.locator('#viewer-node-reset').click();assert.deepEqual((await state()).rig.bones.find(b=>b.name==='Tip').quaternion,[0,0,0,1]);
    await page.locator('#viewer-preview-reset').click();const reset=await state();assert.equal(reset.rig.selectedClip,'');assert.equal(reset.rig.body.height,100);assert.equal(reset.rig.body.breast,100);assert.equal(reset.rig.expressions[0].weight,0);assert.deepEqual(reset.rig.nodeAdjustments,{});
    assert.equal(reset.rig.savedNodes.enabled,true);await page.locator('#viewer-saved-nodes').uncheck();
    await page.locator('.viewer-options').evaluate(e=>e.open=true);
    await page.locator('#viewer-textures').uncheck();const solidProbe=await page.evaluate(()=>ModelViewer.renderProbe(33));
    await page.locator('#viewer-textures').check();const restoredTextureProbe=await page.evaluate(()=>ModelViewer.renderProbe(33));
    assert(restoredTextureProbe.chromaticSamples>solidProbe.chromaticSamples,'Restoring textures must restore unknown source materials');
    await page.evaluate(()=>{var c=document.getElementById('viewer-canvas');var gl=c.getContext('webgl2')||c.getContext('webgl');window.__testLostContext=gl.getExtension('WEBGL_lose_context');window.__testLostContext.loseContext();});
    await page.waitForFunction(()=>ModelViewer.getState().contextLost);assert(await page.locator('#viewer-height').isDisabled());
    await page.waitForTimeout(250);await page.evaluate(()=>window.__testLostContext.restoreContext());
    await page.waitForFunction(()=>!ModelViewer.getState().contextLost);assert.equal(await page.locator('#viewer-height').isDisabled(),false);assert((await page.evaluate(()=>ModelViewer.renderProbe())).glError===0);
    for(const lang of ['ko','ja','en']){await page.locator('#lang-select').selectOption(lang);assert((await page.locator('#viewer-adjustments > summary').innerText()).length>0);}
    for(const viewport of [{width:320,height:900},{width:720,height:400},{width:1366,height:900}]){await page.setViewportSize(viewport);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}
    await page.locator('#viewer-motion').selectOption('Synthetic motion visibility');
    const hiddenAtStart=await page.evaluate(()=>ModelViewer.renderProbe());assert.equal(hiddenAtStart.triangles,0);assert.equal((await state()).rig.visibilityTracks,1);
    await slider('viewer-time',.7);assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).sourceTriangles,1);
    await page.locator('#viewer-parts input').uncheck();await slider('viewer-time',.8);assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).triangles,0,'Clip visibility must not override part checkbox');
    await page.locator('#viewer-parts input').check();assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).sourceTriangles,1);
    await page.locator('#viewer-motion').selectOption('Synthetic visibility only');await slider('viewer-time',.5);assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).triangles,0);
    await slider('viewer-time',.9);assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).sourceTriangles,1);
    await slider('viewer-time',0);await page.locator('#viewer-play').click();await page.waitForFunction(()=>ModelViewer.getState().rig.time>.1);await page.locator('#viewer-play').click();assert((await state()).rig.time>.1,'Visibility-only clips need a real playback clock');
    await page.locator('#viewer-preview-reset').click();assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).sourceTriangles,1);
    unsupported=true;await page.evaluate(()=>openModelViewer(['/synthetic/fallback.unity']));
    const fallback=await state();assert.equal(fallback.rig.available,false);assert.equal(fallback.rig.bones.length,0);
    for(const id of ['viewer-node','viewer-height','viewer-breast','viewer-saved-nodes'])assert(await page.locator('#'+id).isDisabled(),'Unsupported rig control must be disabled: '+id);
    assert.equal(await page.locator('#viewer-expression').isDisabled(),false,'Independent expression channels remain available');
    unsupported=false;generated=fixture({shifted:true,shader:true});await page.evaluate(()=>openModelViewer(['/synthetic/shifted-skin.unity']));
    await page.locator('#viewer-adjustments').evaluate(e=>e.open=true);await page.locator('#viewer-saved-nodes').uncheck();await page.locator('#viewer-fit').click();
    assert.equal((await state()).rig.bones.find(b=>b.name==='Move').position[0],-50,'Skin must actually move geometry far from its raw bounds');
    const shiftedInitial=await page.evaluate(()=>ModelViewer.renderProbe(33));
    assert.equal(shiftedInitial.glError,0,JSON.stringify({shiftedInitial,gpuMessages}));
    await page.locator('#viewer-shader').selectOption('basic');const shiftedBasic=await page.evaluate(()=>ModelViewer.renderProbe(33));
    assert.equal(shiftedBasic.glError,0,JSON.stringify({shiftedBasic,gpuMessages}));assert.equal(shiftedBasic.triangles,1);assert(shiftedBasic.nonBackgroundSamples>10,'A skin outside its raw bounds must draw its main material');
    await page.locator('#viewer-shader').selectOption('sifas');const shiftedMember=await page.evaluate(()=>ModelViewer.renderProbe(33));
    assert.equal(shiftedMember.glError,0,JSON.stringify({shiftedMember,gpuMessages}));assert.equal(shiftedMember.sourceTriangles,1);assert.equal(shiftedMember.triangles,2);assert(shiftedMember.nonBackgroundSamples>10,'Both main and outline passes must draw the moved skin');
    await page.evaluate(()=>{var c=document.getElementById('viewer-canvas'),gl=c.getContext('webgl2')||c.getContext('webgl');window.__testLostContext=gl.getExtension('WEBGL_lose_context');window.__testLostContext.loseContext();});
    await page.waitForFunction(()=>ModelViewer.getState().contextLost);await page.waitForTimeout(250);await page.evaluate(()=>window.__testLostContext.restoreContext());await page.waitForFunction(()=>!ModelViewer.getState().contextLost);
    const memberRecovered=await page.evaluate(()=>ModelViewer.renderProbe(33));assert.equal(memberRecovered.glError,0,JSON.stringify({memberRecovered,gpuMessages}));assert.equal(memberRecovered.triangles,2);
    generated=fixture();await page.evaluate(()=>openModelViewer(['/synthetic/after-shader-context.unity']));const afterContextReload=await page.evaluate(()=>ModelViewer.renderProbe(33));
    assert.equal(afterContextReload.glError,0,JSON.stringify({afterContextReload,gpuMessages}));assert(afterContextReload.nonBackgroundSamples>10);
    // Shared game-motion names and eye_900 are insufficient evidence of a
    // default pose. The test geometry and keys remain wholly synthetic.
    const previewName='ch0301_GEN_preview1_L',previewCases=[];
    for(const options of [
      {previewName,rotationStart:.25},
      {previewName,rotationStart:.25,previewVerified:false},
      {previewName,rotationStart:.25,previewVerified:'true'},
      {previewName,rotationStart:.25,previewVerified:true,previewKind:'unverified_motion'},
      {previewName,rotationStart:.25,previewVerified:true,previewReference:'Missing clip'},
      {previewName:'eye_900',rotationStart:.25}
    ]){
      generated=fixture(options);await page.evaluate(()=>openModelViewer(['/synthetic/unverified-preview.unity']));
      const current=await state();assert.equal(current.rig.defaultClip,'');assert.equal(current.rig.selectedClip,'');
      assert(await page.locator('#viewer-pose-preview').isDisabled());assert.deepEqual(await pressed(),['true','false']);
      assert.deepEqual(current.rig.bones.find(b=>b.name==='BreastSize').quaternion,[0,0,0,1],'Unverified motion must retain the authored pose');
      previewCases.push({options,selectedClip:current.rig.selectedClip,defaultClip:current.rig.defaultClip});
    }
    generated=fixture({previewName,rotationStart:.25,previewVerified:true});
    unsupported=true;await page.evaluate(()=>openModelViewer(['/synthetic/unsupported-preview.unity']));assert.equal((await state()).rig.defaultClip,'');
    unsupported=false;await page.evaluate(()=>openModelViewer(['/synthetic/verified-preview.unity']));
    const previewInitial=await state();assert.equal(previewInitial.rig.selectedClip,previewName);assert.equal(previewInitial.rig.defaultClip,previewName);assert.equal(previewInitial.rig.playing,false);assert.equal(previewInitial.rig.time,0);
    assert.deepEqual(await pressed(),['false','true']);assert.equal(await page.locator('#viewer-pose-help').isVisible(),false);
    assert(Math.abs(previewInitial.rig.bones.find(b=>b.name==='BreastSize').quaternion[2]-.25)<1e-6,'Verified preview must apply its first authored keyframe at load');
    assert.equal(await page.locator('#viewer-motion option:checked').innerText(),'SIFAS costume preview');
    const previewProbe=await page.evaluate(()=>ModelViewer.renderProbe(33));assert.equal(previewProbe.glError,0);assert(previewProbe.nonBackgroundSamples>0);
    await page.waitForTimeout(150);assert.equal((await state()).rig.time,0,'Default preview remains paused until Play');
    await page.locator('#viewer-adjustments').evaluate(e=>e.open=true);
    await page.locator('#viewer-saved-nodes').uncheck();
    for(let n=0;n<2;n++){await slider('viewer-height',120);await slider('viewer-breast',150);}
    const previewScaled=await state();assert.equal(previewScaled.rig.bones.find(b=>b.name==='Move').scale[1],1.2);assert.equal(previewScaled.rig.bones.find(b=>b.name==='BreastSize').scale[0],1.5);
    assert(Math.abs(previewScaled.rig.bones.find(b=>b.name==='BreastSize').quaternion[2]-.25)<1e-6,'Repeated body edits preserve the selected preview pose');
    await page.locator('#viewer-play').click();await page.waitForTimeout(150);assert((await state()).rig.time>0);await page.locator('#viewer-play').click();
    const previewPaused=await state();await page.waitForTimeout(150);assert.equal((await state()).rig.time,previewPaused.rig.time);
    await slider('viewer-time',.5);assert((await state()).rig.bones.find(b=>b.name==='BreastSize').quaternion[2]>.25);
    await page.locator('#viewer-motion').selectOption('');assert.deepEqual((await state()).rig.bones.find(b=>b.name==='BreastSize').quaternion,[0,0,0,1],'Saved pose stays independently selectable');
    await slider('viewer-expression-value',75);await page.locator('#viewer-preview-reset').click();
    const previewReset=await state();assert.equal(previewReset.rig.selectedClip,previewName);assert.equal(previewReset.rig.defaultClip,previewName);assert.equal(previewReset.rig.playing,false);assert.equal(previewReset.rig.time,0);assert.equal(previewReset.rig.body.height,100);assert.equal(previewReset.rig.body.breast,100);assert.equal(previewReset.rig.expressions[0].weight,0);assert.equal(previewReset.rig.savedNodes.enabled,true);
    assert(Math.abs(previewReset.rig.bones.find(b=>b.name==='BreastSize').quaternion[2]-.25)<1e-6,'Reset returns to the verified preview first frame');
    for(const [lang,label] of [['ko','SIFAS 의상 미리보기'],['ja','SIFAS衣装プレビュー'],['en','SIFAS costume preview']]){
      await page.locator('#lang-select').selectOption(lang);await page.waitForFunction(label=>document.querySelector('#viewer-motion option:checked').textContent===label,label);assert.equal((await state()).rig.selectedClip,previewName);
    }
    // Real button events retain all saved/relative settings. The parent and
    // child skirt joints have distinct absolute endpoints and real vertex weights.
    generated=fixture({previewName,rotationStart:.25,previewVerified:true,allSaved:true});
    await page.evaluate(()=>openModelViewer(['/synthetic/all-saved-settings.unity']));
    const allSavedInitial=await state();assert.equal(allSavedInitial.rig.savedNodes.enabled,true);assert.equal(allSavedInitial.rig.savedNodes.applied,5);assert.equal(allSavedInitial.rig.savedNodes.conflicts,0);assert.equal(allSavedInitial.rig.savedNodes.skipped,0);
    const bone=(current,id)=>current.rig.bones.find(value=>value.node===String(id));
    assert.deepEqual(bone(allSavedInitial,3).position,[-.1,.9,0]);assert.deepEqual(bone(allSavedInitial,3).scale,[.7,.7,.7]);assert.deepEqual(bone(allSavedInitial,5).scale,[.6,.6,.6]);
    assert(Math.abs(bone(allSavedInitial,3).quaternion[0]-Math.sin(Math.PI/12))<1e-7,'Verified saved quaternion must apply at load');
    assert.deepEqual(allSavedInitial.rig.savedNodes.groups.find(part=>part.id==='skirt').nodes,['3','5']);
    const allSavedFrame=await capture('all-saved-default');assert.equal(allSavedFrame.glError,0);assert(allSavedFrame.probe.nonBackgroundSamples>0);
    await page.locator('#viewer-adjustments').evaluate(e=>e.open=true);await page.locator('#viewer-saved-parts').evaluate(e=>e.open=true);
    assert((await page.locator('#viewer-saved-status').innerText()).includes('5 / 5'));
    await page.locator('[data-viewer-saved-part="skirt"]').uncheck();const partial=await state();assert.equal(partial.rig.savedNodes.applied,1);assert((await page.locator('#viewer-saved-status').innerText()).includes('1 / 5'));
    assert.deepEqual(bone(partial,3).scale,[1,1,1]);assert.deepEqual(bone(partial,5).scale,[1,1,1]);assert.deepEqual(bone(partial,3).quaternion,[0,0,0,1]);
    await slider('viewer-height',110);await slider('viewer-breast',120);await slider('viewer-expression-value',75);
    await page.locator('.viewer-node-editor').evaluate(e=>e.open=true);await page.locator('#viewer-node').selectOption('3');await page.locator('[data-viewer-node-kind="rotation"][data-axis="X"]').fill('5');
    const retained=await state(),retainedFrame=await capture('button-retained');
    await page.locator('#viewer-pose-basic').click();assert.deepEqual(await pressed(),['true','false']);const basicRetained=await state(),basicFrame=await capture('button-basic','button-retained');
    assert(basicFrame.changedPixels>100);assert.equal(basicRetained.rig.playing,false);assert.equal(basicRetained.rig.time,0);assert.deepEqual(basicRetained.rig.savedNodes,retained.rig.savedNodes);assert.deepEqual(basicRetained.rig.body,retained.rig.body);assert.deepEqual(basicRetained.rig.nodeAdjustments,retained.rig.nodeAdjustments);assert.deepEqual(basicRetained.rig.expressions,retained.rig.expressions);assert.deepEqual(basicRetained.camera,retained.camera);
    await page.locator('#viewer-pose-preview').focus();await page.locator('#viewer-pose-preview').press('Space');assert.deepEqual(await pressed(),['false','true']);assert.equal((await capture(null,'button-retained')).changedPixels,0);
    const repeated=[];
    for(let cycle=0;cycle<5;cycle++){
      await page.locator('[data-viewer-saved-part="skirt"]').check();
      const enabled=await state();assert.deepEqual(bone(enabled,3).scale,[.7,.7,.7]);assert.deepEqual(bone(enabled,5).scale,[.6,.6,.6]);assert.equal(enabled.rig.savedNodes.applied,5);
      if(!cycle)await capture('skirt-enabled');else assert.equal((await capture(null,'skirt-enabled')).changedPixels,0,'Repeated parent/child skirt enable must not compound');
      await page.locator('[data-viewer-saved-part="skirt"]').uncheck();assert.equal((await capture(null,'button-retained')).changedPixels,0);
      await page.locator('#viewer-saved-nodes').uncheck();assert.equal((await state()).rig.savedNodes.applied,0);assert(await page.locator('[data-viewer-saved-part="skirt"]').isDisabled());
      await page.locator('#viewer-pose-basic').click();await page.locator('#viewer-pose-preview').click();assert.equal((await state()).rig.savedNodes.enabled,false);
      await page.locator('#viewer-saved-nodes').check();
      await page.locator('#viewer-pose-basic').click();assert.equal((await capture(null,'button-basic')).changedPixels,0);
      await page.locator('#viewer-pose-preview').click();const current=await state();assert.deepEqual(current.rig.savedNodes,retained.rig.savedNodes);assert.deepEqual(current.rig.nodeAdjustments,retained.rig.nodeAdjustments);assert.equal(current.rig.playing,false);assert.equal(current.rig.time,0);
      const frame=await capture(null,'button-retained');assert.equal(frame.changedPixels,0);repeated.push(frame);
    }
    await page.locator('#viewer-play').click();await page.waitForTimeout(120);assert((await state()).rig.playing);assert.deepEqual(await pressed(),['false','true']);
    await page.locator('#viewer-pose-basic').focus();await page.locator('#viewer-pose-basic').press('Enter');assert.equal((await state()).rig.playing,false);assert.equal((await state()).rig.time,0);assert.deepEqual(await pressed(),['true','false']);
    await page.locator('#viewer-motion').selectOption('Synthetic motion visibility');assert.deepEqual(await pressed(),['false','false']);
    await page.locator('#viewer-pose-preview').click();assert.deepEqual(await pressed(),['false','true']);
    await page.locator('#viewer-preview-reset').click();const buttonReset=await state();assert.equal(buttonReset.rig.savedNodes.enabled,true);assert.equal(buttonReset.rig.savedNodes.applied,5);assert(buttonReset.rig.savedNodes.groups.every(part=>part.enabled));assert.deepEqual(buttonReset.rig.body,{height:100,breast:100});assert.deepEqual(buttonReset.rig.nodeAdjustments,{});assert.deepEqual(await pressed(),['false','true']);assert.equal((await capture(null,'all-saved-default')).changedPixels,0);
    const responsiveButtons=[];
    for(const [lang,basicLabel,posedLabel] of [['ko','기본 자세','포즈 자세'],['ja','基本姿勢','プレビュー姿勢'],['en','Basic pose','Posed view']]){
      await page.locator('#lang-select').selectOption(lang);await page.waitForFunction(label=>document.getElementById('viewer-pose-basic').textContent===label,basicLabel);assert.equal(await page.locator('#viewer-pose-preview').innerText(),posedLabel);
      for(const viewport of [{width:320,height:900},{width:720,height:400},{width:1366,height:900}]){
        await page.setViewportSize(viewport);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
        for(const id of ['viewer-pose-basic','viewer-pose-preview']){
          await page.locator('#'+id).scrollIntoViewIfNeeded();const button=await page.locator('#'+id).evaluate(element=>{const r=element.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return{width:r.width,height:r.height,left:r.x,right:r.right,viewport:innerWidth,hit:hit===element||element.contains(hit),insideDetails:!!element.closest('details'),pressed:element.getAttribute('aria-pressed')};});
          assert(button.width>=44&&button.height>=44&&button.left>=0&&button.right<=button.viewport);assert(button.hit&&!button.insideDetails);responsiveButtons.push({lang,viewport,id,...button});
        }
      }
    }
    await page.screenshot({path:path.join(evidence,'synthetic-pose-buttons-ui.png'),fullPage:true});
    generated=fixture({previewName,rotationStart:.25,previewVerified:true,allSaved:true,rotationConflict:true});await page.evaluate(()=>openModelViewer(['/synthetic/conflicting-rotation.unity']));
    const rotationConflict=await state();assert.equal(rotationConflict.rig.savedNodes.conflicts,1);assert.equal(rotationConflict.rig.savedNodes.skipped,3);assert.equal(rotationConflict.rig.savedNodes.applied,4);assert.deepEqual(bone(rotationConflict,3).quaternion,[0,0,0,1]);
    generated=fixture({allSaved:true,metadataWarning:true});await page.evaluate(()=>openModelViewer(['/synthetic/omitted-invalid-setting.unity']));
    const invalidMetadata=await state();assert.equal(invalidMetadata.rig.savedNodes.skipped,0);assert.deepEqual(invalidMetadata.rig.savedNodes.metadataWarnings,['scaling_invalid_entry']);assert((await page.locator('#viewer-saved-status').innerText()).includes('Unsupported or conflicting saved settings were skipped.'));assert(!(await page.locator('#viewer-saved-status').innerText()).includes('(0)'),'Omitted invalid metadata has no invented skip count');
    assert(await page.locator('#viewer-pose-preview').isDisabled());const beforeDisabled=await state();await page.locator('#viewer-pose-preview').evaluate(element=>element.click());assert.deepEqual((await state()).rig,beforeDisabled.rig);assert.deepEqual(await pressed(),['true','false']);
    assert(!gpuMessages.some(message=>/INVALID_OPERATION|GL_INVALID|THREE.WebGLProgram/.test(message)),JSON.stringify(gpuMessages));
    assert.deepEqual(errors,[]);
    await page.screenshot({path:path.join(evidence,'synthetic-rig-ui.png'),fullPage:true});
    await page.evaluate(()=>ModelViewer.dispose());assert(await page.locator('#viewer-pose-basic').isDisabled());assert(await page.locator('#viewer-pose-preview').isDisabled());assert.deepEqual(await pressed(),['false','false']);
    const report={status:'PASS',scope:'Generated original skinned triangle; product viewer/WebGL and real UI events',requests,initialProbe:probe,scaledProbe,resetRig:reset.rig,unsupportedRig:fallback.rig,visibilityStart:hiddenAtStart,shiftedInitial,shiftedBasic,shiftedMember,memberRecovered,afterContextReload,previewMotion:{rejected:previewCases,initial:previewInitial.rig,scaled:previewScaled.rig,reset:previewReset.rig,probe:previewProbe},poseButtons:{allSavedInitial:allSavedInitial.rig,retained:retained.rig,basicFrame,retainedFrame,repeated,responsiveButtons,reset:buttonReset.rig,rotationConflict:rotationConflict.rig,invalidMetadata:invalidMetadata.rig,disposedPressed:await pressed()},errors,gpuMessages};
    fs.writeFileSync(process.env.VIEWER_REPORT||path.join(evidence,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
