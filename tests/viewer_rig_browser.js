/* Run against the local WebUI: VIEWER_URL=http://127.0.0.1:8898 node tests/viewer_rig_browser.js.
 * All geometry/skin/morph/animation data below is generated; no game asset is used.
 */
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

function fixture(options = {}) {
  if(options.skirtSet)options=Object.assign({},options,{allSaved:true});
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
  const mouthMorph=options.semanticExpressions?attribute([0,0,0,0,0,0,0,-.25,0],Float32Array,'VEC3',5126,3):null;
  const identity = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
  const breastBind = identity.slice(); breastBind[13] = -.5;
  const tipBind = identity.slice(); tipBind[13] = -1.5;
  const childBind=identity.slice();childBind[13]=-2;
  const headBind=identity.slice();headBind[13]=-1.5;
  const hairBind=identity.slice();hairBind[13]=-1.1;hairBind[14]=-.1;
  const binds = attribute(identity.concat(breastBind,tipBind,options.allSaved?childBind:[],headBind,hairBind), Float32Array, 'MAT4', 5126, (options.allSaved?4:3)+2);
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
    doc.nodes[3].name='SkirtA1_Dyna';doc.nodes[3].children=[5];
    doc.nodes.push({name:'LeftSkirtChild_Dyna',translation:[0,.5,0],extras:{elichika_node:5,role:'bone'}});
    doc.skins[0].joints.push(5);
  }else doc.nodes.push({name:'ReservedAuxiliary',extras:{elichika_node:5,role:'bone'}});
  // Unweighted source joints retain the original visible triangle while
  // checking profiles leave authored world-space head/hair transforms untouched.
  doc.nodes.push({name:'Head',translation:[0,1.5,0],extras:{elichika_node:6,role:'bone'}},
    {name:'Neck_Hair',translation:[0,1.1,.1],extras:{elichika_node:7,role:'bone'}});
  doc.nodes[1].children.push(6,7);doc.skins[0].joints.push(6,7);
  const skirtNames=['SkirtA1_Dyna','SkirtE1_Dyna','LeftSkirtB1_Dyna','RightSkirtB1_Dyna','LeftSkirtC1_Dyna','RightSkirtC1_Dyna','LeftSkirtD1_Dyna','RightSkirtD1_Dyna'];
  const skirtRootIds=options.allSaved?[3]:[],skirtDescendantIds=options.allSaved?[5]:[];
  if(options.skirtSet){
    function addBone(name,parent){const id=doc.nodes.length;doc.nodes.push({name,translation:[0,.1,0],extras:{elichika_node:id,role:'bone'}});(doc.nodes[parent].children||(doc.nodes[parent].children=[])).push(id);return id;}
    doc.nodes[5].name='SkirtA2_Dyna';skirtDescendantIds.push(addBone('SkirtA3_Dyna',5));
    for(const name of skirtNames.slice(1)){
      // An exact named root may be nested; the source tool still edits its local XYZ once.
      const root=addBone(name,name==='SkirtE1_Dyna'?5:1);skirtRootIds.push(root);
      const child=addBone(name.replace('1_Dyna','2_Dyna'),root);skirtDescendantIds.push(child,addBone(name.replace('1_Dyna','3_Dyna'),child));
    }
  }
  if(options.shader)doc.materials[0].extras={sifas:{version:1,shader:'AS/Member',colors:{_TintColor:[.2,.5,.8,1],_AmbientColor:[1,1,1,0]},floats:{_CullMode:0},features:{},textures:{}}};
  if(options.semanticExpressions){
    doc.meshes[0].weights=options.rawWeights||[0,0];
    doc.meshes[0].extras.targetNames=['EyeBlendShape.eye_facial_001','MouthBlendShape.mouth_facial_007'];
    doc.meshes[0].primitives[0].targets.push({POSITION:mouthMorph});
  }
  if(options.textureData){
    doc.images=[{uri:options.textureData}];doc.textures=[{source:0,sampler:0}];
    doc.samplers=[{magFilter:9728,minFilter:9728,wrapS:33071,wrapT:33071}];
    doc.materials[0].pbrMetallicRoughness.baseColorTexture={index:0};
  }
  if(options.authoredHidden)doc.nodes[4].extras.hidden_default=true;
  if(options.zeroAuthoredAxis)doc.nodes[6].scale=[0,1,1];
  if(options.authoredSkirtScale)skirtRootIds.forEach(node=>doc.nodes[node].scale=options.authoredSkirtScale.slice());
  const json = Buffer.from(JSON.stringify(doc)), jsonPadded = Buffer.concat([json,Buffer.alloc((4-json.length%4)%4,32)]);
  const bin = Buffer.concat(chunks), binPadded = Buffer.concat([bin,Buffer.alloc((4-bin.length%4)%4)]);
  const header = Buffer.alloc(12), jh = Buffer.alloc(8), bh = Buffer.alloc(8);
  header.writeUInt32LE(0x46546c67,0);header.writeUInt32LE(2,4);header.writeUInt32LE(12+8+jsonPadded.length+8+binPadded.length,8);
  jh.writeUInt32LE(jsonPadded.length);jh.writeUInt32LE(0x4e4f534a,4);bh.writeUInt32LE(binPadded.length);bh.writeUInt32LE(0x004e4942,4);
  const authored=node=>({node,name:doc.nodes[node].name,parent:doc.nodes.findIndex(parent=>(parent.children||[]).includes(node)),
    basePosition:doc.nodes[node].translation||[0,0,0],baseQuaternion:doc.nodes[node].rotation||[0,0,0,1],baseScale:doc.nodes[node].scale||[1,1,1]});
  // Literal independent source-tool profiles: these irregular triples are not curve samples.
  const breastProfiles=[
    {id:'stock',label:'Stock',scale:[1,1,1],group:'stock'},
    {id:'yoshiko_shioriko',label:'Yoshiko/Shioriko',scale:[.95,.99,.98],group:'smaller'},
    {id:'honoka_maki',label:'Honoka/Maki',scale:[.90,.98,.96],group:'smaller'},
    {id:'umi_ruby_kasumi',label:'Umi/Ruby/Kasumi',scale:[.80,.96,.92],group:'smaller'},
    {id:'rin',label:'Rin',scale:[.72,.95,.90],group:'smaller'},
    {id:'nico',label:'Nico',scale:[.64,.94,.88],group:'smaller'},
    {id:'rina',label:'Rina',scale:[.61,.91,.85],group:'smaller'},
    {id:'chika_you_ayumu',label:'Chika/You/Ayumu',scale:[1.04,1.02,1.04],group:'larger'},
    {id:'hanayo_setsuna',label:'Hanayo/Setsuna',scale:[1.08,1.04,1.08],group:'larger'},
    {id:'hanamaru_ai',label:'Hanamaru/Ai',scale:[1.12,1.06,1.12],group:'larger'},
    {id:'lanzhu',label:'Lanzhu',scale:[1.14,1.07,1.14],group:'larger'},
    {id:'eli_kanan_kanata',label:'Eli/Kanan/Kanata',scale:[1.16,1.08,1.16],group:'larger'},
    {id:'mari',label:'Mari',scale:[1.20,1.10,1.20],group:'larger'},
    {id:'karin',label:'Karin',scale:[1.22,1.11,1.22],group:'larger'},
    {id:'nozomi',label:'Nozomi',scale:[1.30,1.15,1.30],group:'larger'},
    {id:'emma',label:'Emma',scale:[1.30,1.18,1.30],group:'larger'}
  ];
  const controls=[{id:'height',label:'Height',available:false,mode:'saved_height_metadata_only',nodes:[],
      source:'LiveCoreMemberNodeScaling.heightScale',unavailableReason:'unverified_height_formula',gameHeightFormulaVerified:false},
    {id:'breast',label:'Breast reference shape',available:true,default:'loaded',unit:'profile',mode:'breast_tool_presets',
      baseline:'loaded_saved_settings',presets:breastProfiles,presetApplication:'absolute_local_scale',interpolation:'none',
      continuousAdjustmentSupported:false,nodes:[authored(2)]},
    {id:'skirt',label:'Skirt length and flare',available:!!options.allSaved,unit:'local_scale_factor',
      mode:'absolute_skirt_root_scale',application:'absolute_local_scale',supportsAbsoluteUniform:!!options.allSaved,
      editBounds:{min:.01,max:10,source:'viewer_preview_bounds',appliesTo:'explicit_uniform_edits_only'},
      uniformTolerance:1e-7,targetSelection:'exact_named_roots',exactRootNames:skirtNames,nodes:skirtRootIds.map(authored)}];
  const components=[{targetName:'SyntheticFixture',heightScale:.97,entries:[
    {node:2,name:'BreastSize',kind:'scale',supported:true,application:'absolute_local_scale',origin:[1,1,1],scaled:options.breastSavedScale||[1.3,.9,1],state:'pending'},
    {node:3,kind:'rotation',supported:false,application:null,scaled:[20,0,0]},
    {node:3,kind:'position',supported:true,application:'absolute_local_position',scaled:[0,1,0]},
    {node:3,kind:'position',supported:true,application:'absolute_local_position',scaled:[0,2,0]}
  ]}];
  if(options.allSaved){
    const sourceEuler=options.allSavedEuler||[30,0,0],half=sourceEuler.map(value=>value*Math.PI/360);
    const [sx,sy,sz]=half.map(Math.sin),[cx,cy,cz]=half.map(Math.cos);
    const quaternion=[cy*sx*cz+sy*cx*sz,-(sy*cx*cz-cy*sx*sz),-(cy*cx*sz-sy*sx*cz),cy*cx*cz+sy*sx*sz];
    const rotation=value=>({node:3,name:'SkirtA1_Dyna',kind:'rotation',supported:true,application:'absolute_local_quaternion',scaledQuaternion:value,scaled:value,origin:[0,0,0,1],unityEulerOrigin:[0,0,0],unityEulerScaled:sourceEuler,rotationOrder:'ZXY'});
    components[0].entries=[
      {node:2,name:'BreastSize',kind:'scale',supported:true,application:'absolute_local_scale',scaled:[1.3,.9,1]},
      {node:3,name:'SkirtA1_Dyna',kind:'position',supported:true,application:'absolute_local_position',origin:[0,1,0],scaled:[-.1,.9,0]},
      {node:3,name:'SkirtA1_Dyna',kind:'scale',supported:true,application:'absolute_local_scale',origin:[1,1,1],scaled:[.7,.7,.7]},
      {node:5,name:'LeftSkirtChild_Dyna',kind:'scale',supported:true,application:'absolute_local_scale',scaled:[.6,.6,.6]},
      rotation(quaternion),rotation(quaternion.map(value=>-value))
    ];
    if(options.rotationConflict)components[0].entries.push(rotation([0,0,0,1]));
    if(options.skirtSet){
      components[0].entries=components[0].entries.filter(entry=>entry.kind!=='scale'||entry.node===2);
      if(!options.authoredSkirtScale)skirtRootIds.forEach((node,index)=>components[0].entries.push({node,name:doc.nodes[node].name,kind:'scale',supported:true,application:'absolute_local_scale',origin:[1,1,1],scaled:options.skirtFileScales?options.skirtFileScales[index]:[.85,.85,.85]}));
      skirtDescendantIds.forEach(node=>components[0].entries.push({node,name:doc.nodes[node].name,kind:'scale',supported:true,application:'absolute_local_scale',origin:[1,1,1],scaled:[1,1,1]}));
    }
  }
  if(options.backendConflict){
    components[0].entries=components[0].entries.filter(entry=>entry.kind!=='position');
    for(const scaled of [[0,1,0],[0,2,0]])components[0].entries.push({node:3,kind:'position',supported:false,reason:'conflicting_saved_entries',application:null,scaled});
  }
  const visibility=(times,values)=>[{node:4,times,values,interpolation:'STEP',sourceProperty:'Renderer.m_Enabled'}];
  const rig = {enabled:true,available:true,root:0,bones:[{node:1,name:'Move'},{node:2,name:'BreastSize'},{node:3,name:'Tip'},{node:6,name:'Head'},{node:7,name:'Neck_Hair'}],bounds:{min:[-.3,0,0],max:[.3,1.2,0]},scaling:{version:4,baseline:'authored',savedOverridesApplied:false,controls,components},clips:[
    {name:clipName,duration:1,loop:true},
    {name:'Synthetic motion visibility',duration:1,loop:false,visibility:visibility([0,.6],[false,true])},
    {name:'Synthetic visibility only',duration:1,loop:false,channels:0,index:null,visibility:visibility([0,.25,.75],[true,false,true])}
  ]};
  if(options.allSaved){rig.bones[2].name='SkirtA1_Dyna';rig.bones.push({node:5,name:doc.nodes[5].name});}
  if(options.skirtSet)skirtRootIds.concat(skirtDescendantIds).filter(node=>node!==3&&node!==5).forEach(node=>rig.bones.push({node,name:doc.nodes[node].name}));
  if(options.partialMotion)rig.clips[0].bindingComplete=false;
  rig.scaling.nodes=rig.bones.map(bone=>Object.assign(authored(bone.node),{label:bone.name,category:bone.node===2?'breast':bone.node===6?'head':bone.node===7?'hair':bone.node===1?'model':'skirt',
    hasSavedSettings:components.some(c=>c.entries.some(e=>e.node===bone.node)),savedKinds:[...new Set(components.flatMap(c=>c.entries.filter(e=>e.node===bone.node).map(e=>e.kind)))]}));
  rig.scaling.recommendedTargets=rig.scaling.nodes.filter(node=>[1,2,3,6,7].includes(node.node)).map(node=>({node:node.node,name:node.name,label:node.label,category:node.category}));
  if(options.semanticExpressions){
    const eye={node:4,index:0,name:doc.meshes[0].extras.targetNames[0]},mouth={node:4,index:1,name:doc.meshes[0].extras.targetNames[1]};
    rig.expressionCatalog={version:1,groups:[{id:'eyes',label:'Eyes'},{id:'mouth',label:'Mouth'}],
      controls:[{id:'fixture-eyes-closed',group:'eyes',label:'Closed eyelids',semanticId:1,targets:[eye],resetTargets:[eye],complete:false,scope:'shape'},
        {id:'fixture-mouth-smile',group:'mouth',label:'Smiling mouth',semanticId:10007,targets:[mouth],resetTargets:[mouth],complete:false,scope:'shape'}],
      rawChannels:[Object.assign({part:'SyntheticTriangle',group:'eyes',label:'Closed eyelids',known:true},eye),
        Object.assign({part:'SyntheticTriangle',group:'mouth',label:'Smiling mouth',known:true},mouth)],
      presets:[{id:'fixture-eyes-closed',group:'eyes',label:'Closed eyelids',targets:[Object.assign({value:1},eye)],source:'verified_morph_shape',complete:false,scope:'shape'},
        {id:'fixture-mouth-smile',group:'mouth',label:'Smiling mouth',targets:[Object.assign({value:1},mouth)],source:'verified_morph_shape',complete:false,scope:'shape'},
        {id:'fixture-smile',group:'all',label:'Smile',targets:[Object.assign({value:1},eye),Object.assign({value:1},mouth)],components:['fixture-eyes-closed','fixture-mouth-smile'],source:'viewer_combination',complete:false},
        {id:'fixture-invalid-channel',group:'eyes',label:'Invalid preset',targets:[{node:4,index:99,name:'not-a-target',value:1}],source:'verified_morph_shape',complete:false}]};
  }
  if(options.semanticExpressions&&options.authoredHidden)rig.expressionCatalog.presets[0].visibility=[{node:4,visible:true}];
  if(options.semanticExpressions&&options.expressionBone)rig.expressionCatalog.presets[0].bones=[{node:2,kind:'scale',value:[.8,.7,.6]}];
  if(options.metadataWarning)rig.scaling.warnings=['scaling_invalid_entry'];
  if(Object.prototype.hasOwnProperty.call(options,'previewVerified'))rig.previewMotion={name:options.previewReference||clipName,kind:options.previewKind||'sifas_suit_preview',verified:options.previewVerified};
  return {glb:Buffer.concat([header,jh,jsonPadded,bh,binPadded]),rig};
}

module.exports={fixture};
if(require.main===module)(async()=>{
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
    await page.evaluate(()=>{
      const original=THREE.GLTFLoader.prototype.parse;
      THREE.GLTFLoader.prototype.parse=function(data,path,onLoad,onError){
        return original.call(this,data,path,function(gltf){window.__actualBodyControlScene=gltf.scene;return onLoad.apply(this,arguments);},onError);
      };
      window.__bodyControlWorld=function(name){
        const source=window.__actualBodyControlScene;
        if(!source)throw new Error('The actual product GLTF scene was not observed');
        source.updateMatrixWorld(true);
        const bones=ModelViewer.getState().rig.bones.filter(b=>b.name===name||b.name.endsWith('/'+name));
        if(bones.length!==1)throw new Error('Expected one actual '+name+' joint');
        const targets=[];source.traverse(o=>{if(o.userData&&!o.userData.viewerHelper&&String(o.userData.elichika_node)===String(bones[0].node))targets.push(o);});
        if(targets.length!==1)throw new Error('Expected one source object for '+name);
        const values=targets[0].matrixWorld.toArray();
        return{matrixAutoUpdate:targets[0].matrixAutoUpdate,position:values.slice(12,15),linear:[values[0],values[1],values[2],values[4],values[5],values[6],values[8],values[9],values[10]],matrix:values};
      };
    });
    await page.evaluate(()=>openModelViewer(['/synthetic/rig.unity']));
    await page.waitForFunction(()=>ModelViewer.getState().loaded&&!ModelViewer.getState().loading);
    const state=()=>page.evaluate(()=>ModelViewer.getState());
    const capture=(save,compare)=>page.evaluate(([save,compare])=>new Promise((resolve,reject)=>{
      const previousSize=(window.__poseButtonFrameSizes||{})[compare];
      // Locator actions may scroll the page; pixel comparisons use the same
      // outer-page position as their reference. The inspector keeps its scroll.
      window.scrollTo(previousSize?previousSize.windowScrollX||0:0,previousSize?previousSize.windowScroll:0);
      let previousGeometry=null,lastGeometry=null,finished=false;
      const timeout=setTimeout(()=>{finished=true;reject(new Error('Pose capture geometry did not settle: '+JSON.stringify(lastGeometry)));},30000);
      function readyFrame(){
        if(finished)return;
        const stage=document.getElementById('viewer-stage'),canvas=document.getElementById('viewer-canvas');
        const s=ModelViewer.getState(),q=s.quality,layout=s.layout,box=stage.getBoundingClientRect();
        const gl=canvas&&(canvas.getContext('webgl2')||canvas.getContext('webgl'));
        const coherent=!!(q&&q.ready&&!s.contextLost&&gl&&layout.stage.width===stage.clientWidth&&layout.stage.height===stage.clientHeight&&
          Math.abs(layout.stage.top-box.top)<1e-6&&Math.abs(layout.stage.left-box.left)<1e-6&&
          q.cssWidth===stage.clientWidth&&q.cssHeight===stage.clientHeight&&
          canvas.width===q.width&&canvas.height===q.height&&gl.drawingBufferWidth===q.width&&gl.drawingBufferHeight===q.height);
        lastGeometry={coherent,stage:{width:stage.clientWidth,height:stage.clientHeight,top:box.top,left:box.left},layout,
          canvas:canvas&&{width:canvas.width,height:canvas.height},quality:q,windowScroll:scrollY};
        const key=JSON.stringify([stage.clientWidth,stage.clientHeight,box.top,box.left,canvas&&canvas.width,canvas&&canvas.height,scrollX,scrollY]);
        if(coherent&&key===previousGeometry){
          finished=true;clearTimeout(timeout);
          // Capture in this same coherent frame. Polling never renders a probe
          // or consumes GL errors; the original capture below performs both.
          try{resolve(captureFrame());}catch(error){reject(error);}
        }else{previousGeometry=coherent?key:null;requestAnimationFrame(readyFrame);}
      }
      function captureFrame(){
      const probe=ModelViewer.renderProbe(33),canvas=document.getElementById('viewer-canvas'),gl=canvas.getContext('webgl2')||canvas.getContext('webgl');
      const width=gl.drawingBufferWidth,height=gl.drawingBufferHeight,pixels=new Uint8Array(width*height*4);gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);const error=gl.getError();
      const frames=window.__poseButtonFrames||(window.__poseButtonFrames={});let changedPixels=null;
      if(compare){const previous=frames[compare];if(!previous||previous.length!==pixels.length)throw new Error('Pose comparison viewport changed: '+JSON.stringify({reference:compare,previousBytes:previous&&previous.length,current:{width,height,bytes:pixels.length},previousSize:(window.__poseButtonFrameSizes||{})[compare],layout:ModelViewer.getState().layout,windowScroll:scrollY,sidebarScroll:document.querySelector('.viewer-control-panel').scrollTop}));changedPixels=0;for(let offset=0;offset<pixels.length;offset+=4)if(Math.abs(pixels[offset]-previous[offset])+Math.abs(pixels[offset+1]-previous[offset+1])+Math.abs(pixels[offset+2]-previous[offset+2])>24)changedPixels++;}
      if(save){frames[save]=pixels;(window.__poseButtonFrameSizes||(window.__poseButtonFrameSizes={}))[save]={width,height,layout:ModelViewer.getState().layout,windowScrollX:scrollX,windowScroll:scrollY,sidebarScroll:document.querySelector('.viewer-control-panel').scrollTop};}return{probe,glError:error,changedPixels,width,height};
      }
      requestAnimationFrame(readyFrame);
    }),[save,compare]);
    const pressed=()=>page.evaluate(()=>['viewer-pose-basic','viewer-pose-preview'].map(id=>document.getElementById(id).getAttribute('aria-pressed')));
    const slider=async(id,value)=>{
      if(id==='viewer-expression-value'){
        await page.locator('#viewer-expression-advanced').evaluate(e=>e.open=true);
        if(!await page.locator('#viewer-expression').inputValue()){
          const first=await page.locator('#viewer-expression option').evaluateAll(options=>options.find(option=>option.value).value);
          await page.locator('#viewer-expression').selectOption(first);
        }
      }
      return page.locator('#'+id).evaluate((input,value)=>{input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));},value);
    };
    const profile=id=>page.locator('#viewer-breast-preset').selectOption(id);
    const eyePreset=async()=>{await page.locator('[data-viewer-expression-group="eyes"]').click();await page.locator('[data-viewer-expression-preset="fixture-eyes-closed"]').click();};
    const applySkirt=async value=>{await page.locator('#viewer-skirt-number').fill(String(value));await page.locator('#viewer-skirt-apply').click();};
    const noContinuousControls=async()=>{for(const id of ['viewer-height','viewer-height-number','viewer-breast','viewer-breast-number','viewer-skirt'])assert.equal(await page.locator('#'+id).count(),0,'Unsupported continuous control must not exist: '+id);};
    const inputNode=async(node,kind,axis,value)=>{
      await page.locator('.viewer-node-editor').evaluate(e=>e.open=true);
      await page.locator('#viewer-node-filter').selectOption('all');await page.locator('#viewer-node-search').fill('');
      await page.locator('#viewer-node').selectOption(String(node));
      await page.locator('[data-viewer-node-kind="'+kind+'"][data-axis="'+axis+'"]').fill(String(value));
    };
    const world=async name=>page.evaluate(name=>window.__bodyControlWorld(name),name);
    const nearVector=(actual,expected,message,tolerance=1e-6)=>{
      assert.equal(actual.length,expected.length,message);
      actual.forEach((value,axis)=>assert(Math.abs(value-expected[axis])<=tolerance,message+' axis'+axis+': '+value+' vs '+expected[axis]));
    };
    const expectedUnityMatrix=degrees=>{
      const [x,y,z]=degrees.map(value=>value*Math.PI/180),sx=Math.sin(x),sy=Math.sin(y),sz=Math.sin(z),cx=Math.cos(x),cy=Math.cos(y),cz=Math.cos(z);
      // Independent column-vector Ry*Rx*Rz followed by Unity-to-glTF X reflection.
      return[cy*cz+sy*sx*sz,cy*sz-sy*sx*cz,-sy*cx,-cx*sz,cx*cz,-sx,sy*cz-cy*sx*sz,sy*sz+cy*sx*cz,cy*cx];
    };
    const quaternionMatrix=([x,y,z,w])=>[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)];
    assert.equal(requests[0].rigged,true);
    const initial=await state();assert(initial.rig.available);await noContinuousControls();assert.equal(initial.rig.heightMode,'saved_settings_only');assert(!('heightCompensation' in initial.rig));assert.deepEqual(initial.rig.body,{breastPreset:'loaded',skirtMode:'file'});assert.deepEqual(initial.rig.clipNames,['Synthetic test motion','Synthetic motion visibility','Synthetic visibility only']);
    assert.equal(initial.rig.savedNodes.enabled,true);assert.equal(initial.rig.savedNodes.applied,1);assert.equal(initial.rig.bones.find(b=>b.name==='BreastSize').scale[0],1.3);
    // A model without any skirt targets has no numeric source/current factor.
    // Exercise real language changes so an unavailable card cannot look like a zero-valued file.
    assert.equal(initial.rig.skirtValues.available,false);assert.deepEqual(initial.rig.skirtValues.targets,[]);
    assert.equal(initial.rig.skirtValues.fileUniform,null);assert.equal(initial.rig.skirtValues.currentUniform,null);
    const unavailableSkirtLanguages=[];
    for(const [code,text] of [['en','Not available for this model.'],['ko','이 모델에서는 조절할 수 없는 부위입니다.'],['ja','このモデルでは調整できません。'],['en','Not available for this model.']]){
      await page.locator('#lang-select').selectOption(code);
      await page.waitForFunction(([code,text])=>document.documentElement.lang===code&&document.getElementById('viewer-skirt-file').textContent===text&&document.getElementById('viewer-skirt-value').textContent===text,[code,text]);
      assert(await page.locator('#viewer-skirt-number').isDisabled());assert(await page.locator('#viewer-skirt-apply').isDisabled());
      assert.equal(await page.locator('#viewer-skirt-number').inputValue(),'');
      assert.equal(await page.locator('#viewer-skirt-number').getAttribute('placeholder'),text);
      const current=await state();assert.equal(current.rig.skirtValues.fileUniform,null);assert.equal(current.rig.skirtValues.currentUniform,null);
      assert.deepEqual(current.camera,initial.camera);assert.deepEqual(current.rig.nodeAdjustments,initial.rig.nodeAdjustments);
      assert.equal(current.rig.selectedClip,initial.rig.selectedClip);assert.equal(current.rig.time,initial.rig.time);assert.deepEqual(current.rig.body,initial.rig.body);
      unavailableSkirtLanguages.push({code,text,skirt:current.rig.skirtValues});
    }
    await page.locator('.viewer-node-editor').evaluate(e=>e.open=true);await page.locator('#viewer-node').selectOption('2');
    const importedFields=await page.locator('[data-viewer-node-kind="scale"]').evaluateAll(inputs=>inputs.map(input=>Number(input.value)));
    nearVector(importedFields,[1.3,.9,1],'Advanced fields must display actual saved NodeScaling values');
    assert.deepEqual((await state()).rig.nodeAdjustments,{},'Selecting a source bone must not create an edit');
    assert.equal(await page.locator('#viewer-node-change-list button').count(),0,'File-only saved values are not My changes');
    await page.locator('[data-viewer-node-kind="scale"][data-axis="X"]').fill('1.4');
    nearVector((await state()).rig.bones.find(b=>b.name==='BreastSize').scale,[1.4,.9,1],'Editing X must retain the other imported axes');
    assert.deepEqual((await state()).rig.nodeAdjustments['2'],{mode:'absolute_axes',scale:[1.4,null,null],position:[null,null,null],rotation:[null,null,null]},'Only the edited factor axis is absolute; untouched axes inherit');
    await page.locator('#viewer-saved-nodes').uncheck();const absoluteOff=await state();
    nearVector(absoluteOff.rig.bones.find(b=>b.node==='2').scale,[1.4,1,1],'Edited X must not drift when the saved baseline is off');
    nearVector(absoluteOff.rig.breastProfile.targets[0].fileScale,[1.3,.9,1],'File XYZ is immutable while saved settings are off');
    nearVector(absoluteOff.rig.breastProfile.targets[0].activeScale,[1,1,1],'Active baseline is separate from file XYZ');
    await page.locator('#viewer-saved-nodes').check();nearVector((await state()).rig.bones.find(b=>b.node==='2').scale,[1.4,.9,1],'Inherited Y/Z follow the restored baseline without rebasing X');

    assert((await page.locator('#viewer-node-change-list').innerText()).includes('BreastSize'),'Changed source/user bones need a visible list');
    await page.locator('#viewer-node-reset').click();nearVector((await state()).rig.bones.find(b=>b.name==='BreastSize').scale,[1.3,.9,1],'Selected reset restores the loaded saved baseline');
    assert.deepEqual((await state()).rig.nodeAdjustments,{});
    await profile('rin');await inputNode(2,'scale','X',1.3);
    nearVector((await state()).rig.bones.find(b=>b.node==='2').scale,[1.3,.95,.9],'Typing a file-equal value while a profile differs still pins the requested endpoint');
    assert.deepEqual((await state()).rig.nodeAdjustments['2'].scale,[1.3,null,null]);
    await page.locator('#viewer-breast-reset').click();
    assert.deepEqual(await pressed(),['true','false']);assert(await page.locator('#viewer-pose-preview').isDisabled());await page.locator('#viewer-info').evaluate(element=>element.open=true);assert(await page.locator('#viewer-pose-help').isVisible());await page.locator('#viewer-info').evaluate(element=>element.open=false);
    const probe=await page.evaluate(()=>ModelViewer.renderProbe());assert(probe.ready&&probe.nonBackgroundSamples>0&&probe.glError===0);
    await page.locator('#viewer-body-adjustments').evaluate(e=>e.open=true);
    await page.locator('#viewer-saved-nodes').uncheck();
    await inputNode(6,'rotation','Z',45);await inputNode(7,'rotation','X',30);
    const headBeforeProfile=await world('Head'),hairBeforeProfile=await world('Neck_Hair'),moveBeforeProfile=await world('Move');
    assert(Math.abs(headBeforeProfile.linear[1])>.5,'The authored head is genuinely rotated during profile isolation checks');
    await profile('rin');await profile('rin');
    nearVector((await state()).rig.bones.find(b=>b.name==='BreastSize').scale,[.72,.95,.90],'A breast profile applies its absolute source XYZ, with no percent or custom-baseline ratio');
    nearVector((await world('Head')).matrix,headBeforeProfile.matrix,'A breast profile must not reshape or reorient the head');
    nearVector((await world('Neck_Hair')).matrix,hairBeforeProfile.matrix,'A breast profile must not reshape or reorient back hair');
    nearVector((await world('Move')).matrix,moveBeforeProfile.matrix,'A breast profile must not stretch whole-model height');
    assert.equal((await world('Head')).matrixAutoUpdate,headBeforeProfile.matrixAutoUpdate,'No hidden head matrix compensation is introduced');
    assert.equal((await state()).rig.savedNodes.enabled,false);
    await page.locator('#viewer-saved-nodes').check();
    const saved=await state();assert.equal(saved.rig.savedNodes.applied,1);assert.equal(saved.rig.savedNodes.skipped,3);assert.equal(saved.rig.savedNodes.conflicts,1);
    nearVector(saved.rig.bones.find(b=>b.name==='BreastSize').scale,[.72,.95,.90],'An absolute profile is retained when saved file settings are enabled');
    assert.deepEqual(saved.rig.bones.find(b=>b.name==='Tip').position,[0,1,0],'Conflicting positions must stay untouched');
    await page.locator('#viewer-node').selectOption('3');
    assert.equal(await page.locator('[data-viewer-value-source="file"][data-viewer-value-kind="position"]').getAttribute('data-viewer-file-status'),'conflict','Conflicting source endpoints must be explicit, not labelled saved');
    assert((await page.locator('[data-viewer-value-source="file"][data-viewer-value-kind="position"]').innerText()).includes('Conflicting'));
    await page.locator('#viewer-node').selectOption('7');

    await page.locator('#viewer-saved-nodes').uncheck();nearVector((await state()).rig.bones.find(b=>b.name==='BreastSize').scale,[.72,.95,.90],'An absolute profile is retained when saved file settings are disabled');
    await page.locator('#viewer-node-reset').click();await page.locator('#viewer-node').selectOption('6');await page.locator('#viewer-node-reset').click();
    assert.deepEqual((await state()).camera,initial.camera,'Changing a reference shape must preserve the camera');
    const scaledProbe=await page.evaluate(()=>ModelViewer.renderProbe(33));
    await page.locator('#viewer-fit').click();
    assert.notDeepEqual((await state()).camera.position,initial.camera.position,'Fit should account for posed/skinned body bounds');
    await page.locator('#viewer-motion').selectOption('Synthetic test motion');await slider('viewer-time',.5);
    const posed=await state();assert(posed.rig.bones.find(b=>b.name==='BreastSize').quaternion[2]>.2);assert.equal(posed.rig.bones.find(b=>b.name==='BreastSize').scale[0],.72);
    await page.locator('#viewer-node').selectOption('2');
    nearVector(await page.locator('[data-viewer-node-kind="rotation"]').evaluateAll(inputs=>inputs.map(input=>Number(input.value))),[0,0,0],'Static editing values must not become animated pose values');
    assert(await page.locator('[data-viewer-value-source="pose"][data-viewer-value-kind="rotation"]').count(),'Different live rotation has its own source-labelled readout');

    const poseReadoutAtHalf=await page.locator('[data-viewer-value-source="pose"][data-viewer-value-kind="rotation"]').innerText();
    await slider('viewer-time',1);assert((await state()).rig.bones.find(b=>b.name==='BreastSize').quaternion[2]>.49,'Scrub end must inspect last frame, not wrap to first');
    assert.notEqual(await page.locator('[data-viewer-value-source="pose"][data-viewer-value-kind="rotation"]').innerText(),poseReadoutAtHalf,'Scrubbing refreshes the selected bone pose readout without reselecting it');
    nearVector(await page.locator('[data-viewer-node-kind="rotation"]').evaluateAll(inputs=>inputs.map(input=>Number(input.value))),[0,0,0],'Scrubbing leaves static editing fields unchanged');
    await slider('viewer-time',0);assert.equal(await page.locator('[data-viewer-value-source="pose"][data-viewer-value-kind="rotation"]').count(),0,'A pose value equal to the static editing value needs no duplicate row');
    await slider('viewer-time',.5);
    const poseReadoutBeforePlay=await page.locator('[data-viewer-value-source="pose"][data-viewer-value-kind="rotation"]').innerText();
    await page.locator('#viewer-play').click();await page.waitForTimeout(150);const playing=await state();assert(playing.rig.playing);assert.notEqual(playing.rig.time,posed.rig.time);
    assert.notEqual(await page.locator('[data-viewer-value-source="pose"][data-viewer-value-kind="rotation"]').innerText(),poseReadoutBeforePlay,'Playback refreshes the selected live pose readout without rebuilding static inputs');
    nearVector(await page.locator('[data-viewer-node-kind="rotation"]').evaluateAll(inputs=>inputs.map(input=>Number(input.value))),[0,0,0],'Playback preserves static editor values');
    await page.locator('[data-tab="tools"]').click();await page.waitForTimeout(80);const hidden=await state();await page.waitForTimeout(150);assert.equal((await state()).rig.time,hidden.rig.time,'Hidden viewer must not advance animation');
    await page.locator('[data-tab="viewer"]').click();await page.waitForTimeout(120);assert.notEqual((await state()).rig.time,hidden.rig.time,'Visible viewer resumes playback');
    await page.locator('#viewer-play').click();const paused=await state();await page.waitForTimeout(130);assert.equal((await state()).rig.time,paused.rig.time);
    await slider('viewer-expression-value',75);assert.equal((await state()).rig.expressions[0].weight,.75);
    await page.locator('.viewer-node-editor').evaluate(e=>e.open=true);
    await page.locator('#viewer-node').selectOption('3');await page.locator('[data-viewer-node-kind="rotation"][data-axis="X"]').fill('30');
    assert(Math.abs((await state()).rig.bones.find(b=>b.name==='Tip').quaternion[0])>.2);
    await page.locator('#viewer-node-reset').click();assert.deepEqual((await state()).rig.bones.find(b=>b.name==='Tip').quaternion,[0,0,0,1]);
    await page.locator('#viewer-preview-reset').click();const reset=await state();assert.equal(reset.rig.selectedClip,'');assert.deepEqual(reset.rig.body,{breastPreset:'loaded',skirtMode:'file'});assert.equal(reset.rig.expressions[0].weight,0);assert.deepEqual(reset.rig.nodeAdjustments,{});
    assert.equal(reset.rig.savedNodes.enabled,true);await page.locator('#viewer-saved-nodes').uncheck();
    await page.locator('.viewer-options').evaluate(e=>e.open=true);
    await page.locator('#viewer-textures').uncheck();const solidProbe=await page.evaluate(()=>ModelViewer.renderProbe(33));
    await page.locator('#viewer-textures').check();const restoredTextureProbe=await page.evaluate(()=>ModelViewer.renderProbe(33));
    assert(restoredTextureProbe.chromaticSamples>solidProbe.chromaticSamples,'Restoring textures must restore unknown source materials');
    await page.evaluate(()=>{var c=document.getElementById('viewer-canvas');var gl=c.getContext('webgl2')||c.getContext('webgl');window.__testLostContext=gl.getExtension('WEBGL_lose_context');window.__testLostContext.loseContext();});
    await page.waitForFunction(()=>ModelViewer.getState().contextLost);assert(await page.locator('#viewer-breast-preset').isDisabled());
    await page.waitForTimeout(250);await page.evaluate(()=>window.__testLostContext.restoreContext());
    await page.waitForFunction(()=>!ModelViewer.getState().contextLost);assert.equal(await page.locator('#viewer-breast-preset').isDisabled(),false);assert((await page.evaluate(()=>ModelViewer.renderProbe())).glError===0);
    for(const lang of ['ko','ja','en']){await page.locator('#lang-select').selectOption(lang);assert((await page.locator('#viewer-body-adjustments > summary').innerText()).length>0);}
    for(const viewport of [{width:320,height:900},{width:720,height:400},{width:1366,height:900}]){await page.setViewportSize(viewport);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}
    await page.locator('#viewer-motion').selectOption('Synthetic motion visibility');
    const hiddenAtStart=await page.evaluate(()=>ModelViewer.renderProbe());assert.equal(hiddenAtStart.triangles,0);assert.equal((await state()).rig.visibilityTracks,1);
    await page.waitForFunction(()=>!document.querySelector('#viewer-parts input').checked);
    await page.locator('#viewer-parts input').check();await slider('viewer-time',.1);
    assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).sourceTriangles,1,'Explicit user-visible wins over a hiding motion');
    await page.locator('#viewer-parts input').uncheck();await slider('viewer-time',.8);
    assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).triangles,0,'Explicit user-hidden wins over a revealing motion');
    await page.locator('#viewer-preview-reset').click();assert.equal((await state()).rig.parts[0].userChanged,false,'Global reset clears manual part choices');
    assert.equal(await page.locator('#viewer-parts input').isChecked(),true,'Global reset follows the default authored visibility');
    await page.locator('#viewer-motion').selectOption('Synthetic visibility only');await slider('viewer-time',.5);assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).triangles,0);
    await page.waitForFunction(()=>!document.querySelector('#viewer-parts input').checked);
    await slider('viewer-time',.9);assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).sourceTriangles,1);
    await page.waitForFunction(()=>document.querySelector('#viewer-parts input').checked);
    await slider('viewer-time',0);await page.locator('#viewer-play').click();await page.waitForFunction(()=>ModelViewer.getState().rig.time>.1);await page.locator('#viewer-play').click();assert((await state()).rig.time>.1,'Visibility-only clips need a real playback clock');
    await page.locator('#viewer-preview-reset').click();assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).sourceTriangles,1);
    unsupported=true;await page.evaluate(()=>openModelViewer(['/synthetic/fallback.unity']));
    const fallback=await state();assert.equal(fallback.rig.available,false);assert.equal(fallback.rig.bones.length,0);
    for(const id of ['viewer-node','viewer-breast-preset','viewer-saved-nodes'])assert(await page.locator('#'+id).isDisabled(),'Unsupported rig control must be disabled: '+id);
    assert.equal(await page.locator('#viewer-expression').isDisabled(),false,'Independent expression channels remain available');
    unsupported=false;generated=fixture({shifted:true,shader:true});await page.evaluate(()=>openModelViewer(['/synthetic/shifted-skin.unity']));
    await page.locator('#viewer-body-adjustments').evaluate(e=>e.open=true);await page.locator('#viewer-saved-nodes').uncheck();await page.locator('#viewer-fit').click();
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
      {previewName:'eye_900',rotationStart:.25},
      {previewName,rotationStart:.25,previewVerified:true,partialMotion:true}
    ]){
      generated=fixture(options);await page.evaluate(()=>openModelViewer(['/synthetic/unverified-preview.unity']));
      const current=await state();assert.equal(current.rig.defaultClip,'');assert.equal(current.rig.selectedClip,'');
      assert(await page.locator('#viewer-pose-preview').isDisabled());assert.deepEqual(await pressed(),['true','false']);
      assert.deepEqual(current.rig.bones.find(b=>b.name==='BreastSize').quaternion,[0,0,0,1],'Unverified motion must retain the authored pose');
      previewCases.push({options,selectedClip:current.rig.selectedClip,defaultClip:current.rig.defaultClip});
    }
    await page.locator('#viewer-motion').selectOption(previewName);
    assert((await page.locator('#viewer-motion option:checked').innerText()).includes('Partially supported motion'));
    assert((await page.locator('#viewer-rig-status').innerText()).includes('Some animation tracks could not be applied.'));
    assert.equal((await state()).rig.defaultClip,'','A partial clip must not qualify for a verified default pose');
    const partialMotionState=await state();
    generated=fixture({previewName,rotationStart:.25,previewVerified:true});
    unsupported=true;await page.evaluate(()=>openModelViewer(['/synthetic/unsupported-preview.unity']));assert.equal((await state()).rig.defaultClip,'');
    unsupported=false;await page.evaluate(()=>openModelViewer(['/synthetic/verified-preview.unity']));
    const previewInitial=await state();assert.equal(previewInitial.rig.selectedClip,previewName);assert.equal(previewInitial.rig.defaultClip,previewName);assert.equal(previewInitial.rig.playing,false);assert.equal(previewInitial.rig.time,0);
    assert.deepEqual(await pressed(),['false','true']);assert.equal(await page.locator('#viewer-pose-help').isVisible(),false);
    assert(Math.abs(previewInitial.rig.bones.find(b=>b.name==='BreastSize').quaternion[2]-.25)<1e-6,'Verified preview must apply its first authored keyframe at load');
    assert.equal(await page.locator('#viewer-motion option:checked').innerText(),'SIFAS costume preview');
    const previewProbe=await page.evaluate(()=>ModelViewer.renderProbe(33));assert.equal(previewProbe.glError,0);assert(previewProbe.nonBackgroundSamples>0);
    await page.waitForTimeout(150);assert.equal((await state()).rig.time,0,'Default preview remains paused until Play');
    await page.locator('#viewer-body-adjustments').evaluate(e=>e.open=true);
    await page.locator('#viewer-saved-nodes').uncheck();
    for(let n=0;n<2;n++)await profile('rin');
    const previewScaled=await state();assert.deepEqual(previewScaled.rig.bones.find(b=>b.name==='Move').scale,[1,1,1]);nearVector(previewScaled.rig.bones.find(b=>b.name==='BreastSize').scale,[.72,.95,.90],'A repeated profile retains absolute source values');
    assert(Math.abs(previewScaled.rig.bones.find(b=>b.name==='BreastSize').quaternion[2]-.25)<1e-6,'Repeated body edits preserve the selected preview pose');
    await page.locator('#viewer-play').click();await page.waitForTimeout(150);assert((await state()).rig.time>0);await page.locator('#viewer-play').click();
    const previewPaused=await state();await page.waitForTimeout(150);assert.equal((await state()).rig.time,previewPaused.rig.time);
    await slider('viewer-time',.5);assert((await state()).rig.bones.find(b=>b.name==='BreastSize').quaternion[2]>.25);
    await page.locator('#viewer-motion').selectOption('');assert.deepEqual((await state()).rig.bones.find(b=>b.name==='BreastSize').quaternion,[0,0,0,1],'Saved pose stays independently selectable');
    await slider('viewer-expression-value',75);await page.locator('#viewer-preview-reset').click();
    const previewReset=await state();assert.equal(previewReset.rig.selectedClip,previewName);assert.equal(previewReset.rig.defaultClip,previewName);assert.equal(previewReset.rig.playing,false);assert.equal(previewReset.rig.time,0);assert.deepEqual(previewReset.rig.body,{breastPreset:'loaded',skirtMode:'file'});assert.equal(previewReset.rig.expressions[0].weight,0);assert.equal(previewReset.rig.savedNodes.enabled,true);
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
    await page.locator('.viewer-node-editor').evaluate(e=>e.open=true);await page.locator('#viewer-node').selectOption('3');
    nearVector(await page.locator('[data-viewer-node-kind="scale"]').evaluateAll(inputs=>inputs.map(input=>Number(input.value))),[.7,.7,.7],'Imported skirt scale is shown in the editor');
    nearVector(await page.locator('[data-viewer-node-kind="position"]').evaluateAll(inputs=>inputs.map(input=>Number(input.value))),[.1,.9,0],'Imported position uses source Unity X direction');
    nearVector(await page.locator('[data-viewer-node-kind="rotation"]').evaluateAll(inputs=>inputs.map(input=>Number(input.value))),[30,0,0],'Imported rotation shows source Unity Euler values');
    assert.deepEqual((await state()).rig.nodeAdjustments,{},'Inspecting saved scale, position and rotation must not create overrides');
    await applySkirt(.85);nearVector(bone(await state(),3).scale,[.85,.85,.85],'Skirt apply sets an absolute source-tool value');
    nearVector(bone(await state(),5).scale,[.6,.6,.6],'A skirt child must not get the root multiplier a second time');
    await page.locator('#viewer-skirt-reset').click();assert.equal((await state()).rig.body.skirtMode,'file');
    assert.equal((await capture(null,'all-saved-default')).changedPixels,0,'Skirt reset restores the complete imported file defaults');
    await page.locator('#viewer-body-adjustments').evaluate(e=>e.open=true);await page.locator('#viewer-saved-parts').evaluate(e=>e.open=true);
    assert((await page.locator('#viewer-saved-status').innerText()).includes('5 / 5'));
    await page.locator('[data-viewer-saved-part="skirt"]').uncheck();const partial=await state();assert.equal(partial.rig.savedNodes.applied,1);assert((await page.locator('#viewer-saved-status').innerText()).includes('1 / 5'));
    assert.deepEqual(bone(partial,3).scale,[1,1,1]);assert.deepEqual(bone(partial,5).scale,[1,1,1]);assert.deepEqual(bone(partial,3).quaternion,[0,0,0,1]);
    await profile('emma');await slider('viewer-expression-value',75);
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
    await page.locator('#viewer-preview-reset').click();const buttonReset=await state();assert.equal(buttonReset.rig.savedNodes.enabled,true);assert.equal(buttonReset.rig.savedNodes.applied,5);assert(buttonReset.rig.savedNodes.groups.every(part=>part.enabled));
    assert.deepEqual(buttonReset.rig.body,{breastPreset:'loaded',skirtMode:'file'},'Reset restores active loaded settings and clears only the chosen reference profile');assert.deepEqual(buttonReset.rig.nodeAdjustments,{});assert.deepEqual(await pressed(),['false','true']);assert.equal((await capture(null,'all-saved-default')).changedPixels,0);
    const responsiveButtons=[];
    for(const [lang,basicLabel,posedLabel] of [['ko','기본 자세','포즈 자세'],['ja','基本姿勢','プレビュー姿勢'],['en','Basic pose','Posed view']]){
      await page.locator('#lang-select').selectOption(lang);await page.waitForFunction(label=>document.getElementById('viewer-pose-basic').textContent===label,basicLabel);assert.equal(await page.locator('#viewer-pose-preview').innerText(),posedLabel);
      for(const viewport of [{width:320,height:900},{width:720,height:400},{width:1366,height:900}]){
        await page.setViewportSize(viewport);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
        const compact=viewport.width<760&&viewport.height<=560;
        await page.waitForFunction(expected=>ModelViewer.getState().layout.compactControls===expected,compact);
        assert(await page.locator('#tab-viewer').evaluate(element=>element.classList.contains('viewer-vertical-controls')));
        for(const id of ['viewer-pose-basic','viewer-pose-preview']){
          await page.locator('#'+id).scrollIntoViewIfNeeded();const button=await page.locator('#'+id).evaluate(element=>{const r=element.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return{width:r.width,height:r.height,left:r.x,right:r.right,viewport:innerWidth,hit:hit===element||element.contains(hit),insideDetails:!!element.closest('details'),pressed:element.getAttribute('aria-pressed')};});
          assert(button.width>=32&&button.height>=32&&button.left>=0&&button.right<=button.viewport);assert(button.hit);assert.equal(button.insideDetails,false,'Pose buttons remain visible in their vertical column at every viewport');responsiveButtons.push({lang,viewport,id,...button});
        }

      }
    }
    await page.screenshot({path:path.join(evidence,'synthetic-pose-buttons-ui.png'),fullPage:true});
    const inspectorLayouts=[];
    const twoFrames=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    for(const viewport of [{width:320,height:900},{width:768,height:640},{width:853,height:590},{width:1024,height:768},{width:1280,height:800},{width:1440,height:900}]){
      await page.setViewportSize(viewport);
      if(await page.locator('#tab-viewer').evaluate(element=>element.classList.contains('viewer-expanded')))await page.locator('#viewer-expand').click();
      await page.evaluate(()=>{window.scrollTo(0,0);document.querySelector('.viewer-control-panel').scrollTop=0;});await twoFrames();
      const normal=await page.evaluate(()=>{
        const rect=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
        return{stage:rect('#viewer-stage'),controls:rect('.viewer-control-panel'),cameraActions:rect('.viewer-camera-actions'),camera:ModelViewer.getState().camera,overflow:document.documentElement.scrollWidth>innerWidth};
      });
      assert.equal(normal.overflow,false,'The normal inspector must fit the viewport');
      if(viewport.width>=720){
        assert(normal.stage.right<=normal.controls.x+.5,'Wide normal mode places the model to the LEFT of adjustments');
        assert(normal.cameraActions.x>=normal.stage.x-.5&&normal.cameraActions.right<=normal.stage.right+.5,'View/camera controls remain with the left model');
        assert(normal.stage.width>=300&&normal.controls.width>=280,'Tablet columns keep a usable editor and a visible model');
        if(viewport.width<1200)assert(normal.controls.width<=380,'Compact tablet editors stay bounded');
        else assert(normal.stage.width<=normal.stage.height*1.27,'Wide tablets use the freed width for editing');
      }
      await page.locator('#viewer-expand').click();await twoFrames();
      const expanded=await page.evaluate(()=>{
        const stage=document.getElementById('viewer-stage').getBoundingClientRect(),controls=document.querySelector('.viewer-control-panel').getBoundingClientRect();
        return{stage:{width:stage.width,height:stage.height,bottom:stage.bottom},controls:{y:controls.y,displayed:document.querySelector('.viewer-control-panel').getClientRects().length>0},camera:ModelViewer.getState().camera,overflow:document.documentElement.scrollWidth>innerWidth};
      });
      assert.equal(expanded.overflow,false);assert.equal(expanded.controls.displayed,false,'Expanded mode reserves the viewport for the model');
      assert(expanded.stage.height>=viewport.height*.88,'Expanded view fills screen height');
      assert(expanded.stage.width>=normal.stage.width-.5&&expanded.stage.height>=normal.stage.height-.5,'Expanded mode increases the model viewport');
      assert.deepEqual(expanded.camera,normal.camera,'Changing the layout must not reset the model camera');
      await page.locator('#viewer-expand').click();await twoFrames();
      assert.deepEqual((await state()).camera,normal.camera,'Closing expanded mode preserves the source camera');
      inspectorLayouts.push({viewport,normal,expanded});
    }
    await page.setViewportSize({width:1024,height:768});await twoFrames();
    assert.equal(await page.locator('#viewer-node-shortcuts #viewer-node').count(),1,'Opening successive models reuses the single body-part selector');
    assert.equal(await page.locator('#viewer-node-shortcuts [data-viewer-bone]').count(),0,'Common body parts do not create a wall of buttons');
    await page.locator('#viewer-node').selectOption('6');
    assert.equal(await page.locator('#viewer-node').inputValue(),'6','A frequent-bone shortcut selects its real node');
    assert(await page.locator('#viewer-node-editor').evaluate(details=>details.open));
    const beforeBoneSearch=(await state()).rig.nodeAdjustments;
    await page.locator('#viewer-node-search').fill('Head');
    assert.equal(await page.locator('#viewer-node option').count(),1);assert.equal(await page.locator('#viewer-node').inputValue(),'6');
    assert.deepEqual((await state()).rig.nodeAdjustments,beforeBoneSearch,'Searching and selecting must not create edits');
    await page.locator('#viewer-node-search').fill('');await page.locator('#viewer-node-filter').selectOption('saved');
    assert(await page.locator('#viewer-node option[value="2"]').count(),'The imported BreastSize setting is discoverable by the saved filter');
    await page.locator('#viewer-node-filter').selectOption('all');
    generated=fixture({allSaved:true});await page.evaluate(()=>openModelViewer(['/synthetic/tool-breast-presets.unity']));
    await noContinuousControls();
    const sourceProfiles=generated.rig.scaling.controls.find(value=>value.id==='breast').presets;
    assert.equal(sourceProfiles.length,16);assert.equal(sourceProfiles.filter(value=>value.group==='smaller').length,6);
    const profileOptionIds=await page.locator('#viewer-breast-preset option').evaluateAll(options=>options.map(option=>option.value));assert.equal(profileOptionIds[0],'loaded');assert.deepEqual(profileOptionIds.slice().sort(),['loaded',...sourceProfiles.map(value=>value.id)].sort(),'Loaded file shape is independent from all16 unique source-tool profiles');
    const loadedProfileState=await state();assert.equal(loadedProfileState.rig.breastProfile.selected,'loaded');assert.equal(loadedProfileState.rig.breastProfile.fileProfile,null);
    nearVector(loadedProfileState.rig.breastProfile.targets[0].fileScale,[1.3,.9,1],'Loaded profile preserves custom saved XYZ');
    assert.equal(await page.locator('#viewer-height-card').evaluate(card=>card.open),false,'Height reference starts collapsed after the active controls');
    await page.locator('#viewer-height-card').evaluate(card=>card.open=true);
    assert((await page.locator('#viewer-height-source').innerText()).includes('0.97'),'Opening the height reference reveals the saved metadata');
    await page.locator('#viewer-height-card').evaluate(card=>card.open=false);
    await inputNode(6,'rotation','Z',45);await inputNode(7,'rotation','X',30);await applySkirt(.85);
    const profileInvariant={Move:await world('Move'),Head:await world('Head'),Neck_Hair:await world('Neck_Hair')},profileResults=[];
    for(const expected of sourceProfiles){
      await profile(expected.id);await profile(expected.id);
      const current=await state();nearVector(bone(current,2).scale,expected.scale,'Exact absolute tool profile '+expected.id,1e-12);
      assert.equal(current.rig.breastProfile.selected,expected.id);assert.equal(current.rig.breastProfile.custom,false);
      assert.equal(current.rig.body.skirtMode,'absolute','Choosing a breast reference retains skirt edits');assert.equal(current.rig.skirtValues.currentUniform,.85);
      for(const name of Object.keys(profileInvariant))nearVector((await world(name)).matrix,profileInvariant[name].matrix,'Profile '+expected.id+' leaves '+name+' world TRS intact',1e-12);
      profileResults.push({id:expected.id,scale:bone(current,2).scale});
    }
    // Manual changes remain exact; choosing a reference clears only breast SCALE.
    await inputNode(2,'position','X',.02);await inputNode(2,'rotation','Z',15);await inputNode(2,'scale','X',1.4);
    const manualProfile=await state();assert.equal(manualProfile.rig.breastProfile.custom,true);assert((await page.locator('#viewer-breast-value').innerText()).includes('Custom shape'));
    await profile('rina');const replacedProfile=await state();nearVector(bone(replacedProfile,2).scale,[.61,.91,.85],'A new reference clears the previous manual breast scale');
    nearVector(bone(replacedProfile,2).position,bone(manualProfile,2).position,'Reference selection retains breast placement',1e-12);
    nearVector(bone(replacedProfile,2).quaternion,bone(manualProfile,2).quaternion,'Reference selection retains breast rotation',1e-12);
    for(const id of ['6','7'])assert.deepEqual(replacedProfile.rig.nodeAdjustments[id],manualProfile.rig.nodeAdjustments[id],'Reference selection retains other bones');
    await page.locator('#viewer-breast-reset').click();const restoredProfile=await state();nearVector(bone(restoredProfile,2).scale,[1.3,.9,1],'Reset restores this custom file shape, not Stock');
    nearVector(bone(restoredProfile,2).position,bone(manualProfile,2).position,'Profile reset retains manual placement',1e-12);
    nearVector(bone(restoredProfile,2).quaternion,bone(manualProfile,2).quaternion,'Profile reset retains manual rotation',1e-12);
    await page.locator('#viewer-node-reset').click();
    await profile('stock');nearVector(bone(await state(),2).scale,[1,1,1],'Stock is an explicit absolute reference distinct from the custom file');
    await page.locator('#viewer-breast-reset').click();nearVector(bone(await state(),2).scale,[1.3,.9,1],'Loaded shape is recoverable independently from Stock');
    await page.locator('#viewer-saved-parts').evaluate(details=>details.open=true);
    await page.locator('[data-viewer-saved-part="breast"]').uncheck();nearVector(bone(await state(),2).scale,[1,1,1],'Loaded follows the active authored baseline when its saved part is off');
    await profile('emma');await page.locator('[data-viewer-saved-part="breast"]').check();nearVector(bone(await state(),2).scale,[1.3,1.18,1.3],'An explicit source profile survives saved-part changes');
    await page.locator('#viewer-saved-nodes').uncheck();nearVector(bone(await state(),2).scale,[1.3,1.18,1.3],'An explicit source profile survives global saved-settings opt-out');
    await page.locator('#viewer-breast-reset').click();nearVector(bone(await state(),2).scale,[1,1,1],'Loaded reset respects the active authored baseline');
    await page.locator('#viewer-saved-nodes').check();nearVector(bone(await state(),2).scale,[1.3,.9,1],'Re-enabling saved settings recovers the exact custom file shape');
    await page.locator('#viewer-motion').selectOption('Synthetic test motion');await slider('viewer-time',.5);await slider('viewer-expression-value',75);
    const beforeProfileSwitch=await state();await profile('rin');const afterProfileSwitch=await state();
    assert.equal(afterProfileSwitch.rig.selectedClip,beforeProfileSwitch.rig.selectedClip);assert.equal(afterProfileSwitch.rig.time,beforeProfileSwitch.rig.time);assert.deepEqual(afterProfileSwitch.rig.expressions,beforeProfileSwitch.rig.expressions);assert.equal(afterProfileSwitch.rig.body.skirtMode,'absolute');assert.equal(afterProfileSwitch.rig.skirtValues.currentUniform,.85);
    const toolPresetState=afterProfileSwitch;
    generated=fixture({allSaved:true,allSavedEuler:[35,45,60]});await page.evaluate(()=>openModelViewer(['/synthetic/multi-axis-unity-saved-rotation.unity']));
    await page.locator('.viewer-node-editor').evaluate(details=>details.open=true);await page.locator('#viewer-node').selectOption('3');
    nearVector(await page.locator('[data-viewer-node-kind="rotation"]').evaluateAll(inputs=>inputs.map(input=>Number(input.value))),[35,45,60],'Multi-axis saved Unity Euler values are imported without an order swap');
    const loadedMultiAxis=await state();nearVector(quaternionMatrix(loadedMultiAxis.rig.bones.find(bone=>bone.node==='3').quaternion),expectedUnityMatrix([35,45,60]),'Imported quaternion follows the source native RyRxRz convention');
    await page.locator('[data-viewer-node-kind="rotation"][data-axis="Y"]').fill('55');
    const editedMultiAxis=await state();nearVector(quaternionMatrix(editedMultiAxis.rig.bones.find(bone=>bone.node==='3').quaternion),expectedUnityMatrix([35,55,60]),'Editing one Euler component preserves the other source components and native order');
    await page.locator('#viewer-saved-nodes').uncheck();
    nearVector(quaternionMatrix(bone(await state(),3).quaternion),expectedUnityMatrix([0,55,0]),'An edited absolute Unity Y must stay55 while inherited X/Z follow authored baseline');
    assert.deepEqual((await state()).rig.nodeAdjustments['3'].rotation,[null,55,null]);
    await page.locator('#viewer-saved-nodes').check();
    nearVector(quaternionMatrix(bone(await state(),3).quaternion),expectedUnityMatrix([35,55,60]),'Saved rotation restores inherited axes without rebasing edited Y');
    await page.locator('#viewer-node-reset').click();
    nearVector(quaternionMatrix((await state()).rig.bones.find(bone=>bone.node==='3').quaternion),expectedUnityMatrix([35,45,60]),'Reset restores the original multi-axis saved quaternion');
    const multiAxisState=await state();
    generated=fixture({breastSavedScale:[.5,.8,.9]});await page.evaluate(()=>openModelViewer(['/synthetic/custom-file-breast-profile.unity']));
    await noContinuousControls();assert.equal(await page.locator('#viewer-breast-preset').isDisabled(),false,'Custom files can select discrete references without a fabricated curve domain');
    await inputNode(2,'scale','X',.55);nearVector(bone(await state(),2).scale,[.55,.8,.9],'Advanced editing retains custom source axes');
    assert.equal((await state()).rig.breastProfile.custom,true);
    await profile('rina');nearVector(bone(await state(),2).scale,[.61,.91,.85],'A small custom file still receives the exact selected reference');
    await page.locator('#viewer-breast-reset').click();nearVector(bone(await state(),2).scale,[.5,.8,.9],'Reset never replaces a custom loaded file with a reference');
    const customProfileState=await state();
    generated=fixture({semanticExpressions:true});await page.evaluate(()=>openModelViewer(['/synthetic/named-expression-controls.unity']));
    await profile('rin');const beforeExpressionBody=(await state()).rig.body;
    const namedExpressionBase=await capture('named-expression-base');
    assert.equal(await page.locator('[data-viewer-expression-preset="fixture-smile"]').innerText(),'Smile','Normal expression selection has a meaningful label');
    assert.equal(await page.locator('[data-viewer-expression-preset="fixture-invalid-channel"]').count(),0,'An invalid morph recipe must never appear as a usable expression');
    await page.locator('[data-viewer-expression-preset="fixture-smile"]').click();
    nearVector((await state()).rig.expressions.map(value=>value.weight),[1,1],'A full-face preview preset drives the declared eye and mouth channels together');
    assert((await capture(null,'named-expression-base')).changedPixels>32,'Named expression presets must change actual morph geometry');
    await page.locator('[data-viewer-expression-group="mouth"]').click();
    await page.locator('#viewer-expression-shapes').evaluate(details=>details.open=true);
    await page.locator('[data-viewer-expression-control="fixture-mouth-smile"]').evaluate(input=>{input.value='45';input.dispatchEvent(new Event('input',{bubbles:true}));});
    nearVector((await state()).rig.expressions.map(value=>value.weight),[1,.45],'Mouth fine-tuning preserves the separately selected eyes');
    await page.locator('#viewer-expression-reset').click();
    nearVector((await state()).rig.expressions.map(value=>value.weight),[0,0],'Expression reset restores the original morph state');
    assert.deepEqual((await state()).rig.body,beforeExpressionBody,'Expression reset must not remove body adjustments');
    assert.equal((await capture(null,'named-expression-base')).changedPixels,0,'Expression reset restores the source framebuffer');
    const namedExpressionState=await state();
    // The source skirt tool edits eight named local roots, including a nested
    // root, while sixteen ordinary descendants retain their saved identity.
    generated=fixture({skirtSet:true});await page.evaluate(()=>openModelViewer(['/synthetic/eight-absolute-skirt-roots.unity']));
    await page.locator('#viewer-body-adjustments').evaluate(details=>details.open=true);
    const skirtInitial=await state(),rootIds=skirtInitial.rig.skirtValues.targets.map(target=>target.node);
    const descendantIds=skirtInitial.rig.bones.filter(value=>/Skirt/.test(value.name)&&!rootIds.includes(value.node)).map(value=>value.node);
    assert.equal(rootIds.length,8);assert.equal(new Set(rootIds).size,8);assert.equal(descendantIds.length,16);
    assert.equal(skirtInitial.rig.skirtValues.fileUniform,.85);assert.equal(skirtInitial.rig.skirtValues.currentUniform,.85);
    assert.equal(await page.locator('#viewer-skirt-number').inputValue(),'0.85');assert.equal(await page.locator('#viewer-skirt-file').innerText(),'0.85');
    assert.equal(await page.locator('#viewer-skirt-nodes tr').count(),8);
    await page.locator('#viewer-skirt-number').fill('.7');
    assert.equal((await state()).rig.skirtValues.currentUniform,.85,'Typing does not apply a skirt edit before the explicit Apply button');
    for(let cycle=0;cycle<2;cycle++){
      await applySkirt(.85);const current=await state();
      rootIds.forEach(id=>nearVector(bone(current,id).scale,[.85,.85,.85],'Every exact named root receives .85 once, including nested roots'));
      descendantIds.forEach(id=>nearVector(bone(current,id).scale,[1,1,1],'Ordinary descendants receive no additional local scale'));
    }
    await page.locator('#viewer-skirt-reset').click();
    await page.locator('#viewer-saved-nodes').uncheck();let skirtOff=await state();
    assert.equal(skirtOff.rig.skirtValues.fileUniform,.85);assert.equal(skirtOff.rig.skirtValues.currentUniform,1);
    assert.equal(await page.locator('#viewer-skirt-file').innerText(),'0.85');assert.equal(await page.locator('#viewer-skirt-number').inputValue(),'1');
    await inputNode(3,'position','X',.2);await inputNode(3,'rotation','Y',45);await inputNode(3,'scale','X',.6);
    let rootManual=await state();assert.deepEqual(rootManual.rig.nodeAdjustments['3'].scale,[.6,null,null]);
    await applySkirt(.85);let skirtApplied=await state();
    assert.deepEqual(skirtApplied.rig.nodeAdjustments['3'].scale,[null,null,null],'Absolute skirt Apply replaces manual root scale only');
    for(const kind of ['position','quaternion'])nearVector(bone(skirtApplied,3)[kind],bone(rootManual,3)[kind],'Absolute skirt Apply preserves root '+kind);
    assert.equal(skirtApplied.rig.savedNodes.enabled,false);
    await inputNode(3,'scale','Z',.65);await page.locator('#viewer-skirt-reset').click();let skirtUndo=await state();
    assert.equal(skirtUndo.rig.body.skirtMode,'file');assert.equal(skirtUndo.rig.skirtValues.edited,false);assert.equal(skirtUndo.rig.skirtValues.currentUniform,1);
    assert.deepEqual(skirtUndo.rig.nodeAdjustments['3'].scale,[null,null,null]);
    for(const kind of ['position','quaternion'])nearVector(bone(skirtUndo,3)[kind],bone(rootManual,3)[kind],'Undo skirt edits preserves manual root '+kind);
    assert.equal(skirtUndo.rig.savedNodes.enabled,false,'Undo edits preserves the saved-settings opt-out');
    await page.locator('#viewer-saved-nodes').check();let rootSaved=await state();
    nearVector(bone(rootSaved,3).position,[-.2,.9,0],'Absolute Unity X stays fixed while inherited position Y follows saved settings');
    nearVector(quaternionMatrix(bone(rootSaved,3).quaternion),expectedUnityMatrix([30,45,0]),'Absolute manual Y stays fixed while inherited saved X rotation returns');
    assert.deepEqual(rootSaved.rig.nodeAdjustments['3'].position,[-.2,null,null]);assert.deepEqual(rootSaved.rig.nodeAdjustments['3'].rotation,[null,45,null]);
    await page.locator('#viewer-saved-parts').evaluate(details=>details.open=true);await page.locator('[data-viewer-saved-part="skirt"]').uncheck();
    let rootPartOff=await state();assert.equal(rootPartOff.rig.skirtValues.fileUniform,.85);assert.equal(rootPartOff.rig.skirtValues.currentUniform,1);
    nearVector(bone(rootPartOff,3).position,[-.2,1,0],'Per-part opt-out inherits authored Y without rebasing manual X');
    nearVector(quaternionMatrix(bone(rootPartOff,3).quaternion),expectedUnityMatrix([0,45,0]),'Per-part opt-out inherits authored X/Z without rebasing manual rotation Y');
    await applySkirt(.9);assert.equal((await state()).rig.skirtValues.currentUniform,.9);await page.locator('#viewer-skirt-reset').click();
    assert.equal((await state()).rig.skirtValues.currentUniform,1);assert.equal(await page.locator('[data-viewer-saved-part="skirt"]').isChecked(),false);
    await page.locator('[data-viewer-saved-part="breast"]').uncheck();
    const breastFileReadout=await page.locator('#viewer-breast-file-values').innerText();
    assert.equal(breastFileReadout,'1.3 / 0.9 / 1');assert.equal(await page.locator('#viewer-breast-current-values').innerText(),'1 / 1 / 1');
    nearVector((await state()).rig.breastProfile.targets[0].fileScale,[1.3,.9,1],'Breast file XYZ is immutable during per-part opt-out');
    await page.locator('#viewer-saved-nodes').uncheck();assert.equal(await page.locator('#viewer-breast-file-values').innerText(),breastFileReadout);
    const absoluteControlsState=await state();
    // An authored numeric zero in actual nodes remains distinct from no targets.
    generated=fixture({skirtSet:true,authoredSkirtScale:[0,0,0]});await page.evaluate(()=>openModelViewer(['/synthetic/zero-authored-skirt.unity']));
    const zeroSkirt=await state();assert.equal(zeroSkirt.rig.skirtValues.targets.length,8);assert.equal(zeroSkirt.rig.skirtValues.available,true);
    assert.equal(zeroSkirt.rig.skirtValues.fileUniform,0);assert.equal(zeroSkirt.rig.skirtValues.currentUniform,0);
    assert(zeroSkirt.rig.skirtValues.targets.every(target=>target.fileStatus==='authored'));
    assert.equal(await page.locator('#viewer-skirt-file').innerText(),'0 · Authored fallback');assert.equal(await page.locator('#viewer-skirt-value').innerText(),'0');
    assert.equal(await page.locator('#viewer-skirt-number').inputValue(),'0');assert(!(await page.locator('#viewer-skirt-number').isDisabled()));
    assert.equal(await page.locator('#viewer-skirt-number').getAttribute('placeholder'),'Different values');
    // A zero saved endpoint still follows the existing unsupported-value path.
    generated=fixture({skirtSet:true,skirtFileScales:Array.from({length:8},()=>[0,0,0])});await page.evaluate(()=>openModelViewer(['/synthetic/unsupported-zero-skirt.unity']));
    const unsupportedZeroSkirt=await state();assert.equal(unsupportedZeroSkirt.rig.skirtValues.targets.length,8);
    assert.equal(unsupportedZeroSkirt.rig.skirtValues.fileUniform,null);assert.equal(unsupportedZeroSkirt.rig.skirtValues.currentUniform,1);
    assert(unsupportedZeroSkirt.rig.skirtValues.targets.every(target=>target.fileStatus==='unsupported'));
    assert.equal(await page.locator('#viewer-skirt-file').innerText(),'Unsupported file value');assert.equal(await page.locator('#viewer-skirt-value').innerText(),'1');
    assert.equal(await page.locator('#viewer-skirt-number').inputValue(),'1');
    const mixedSource=Array.from({length:8},(_,index)=>index===0?[.85,.9,.95]:index===1?[.8,.8,.8]:[.85,.85,.85]);
    generated=fixture({skirtSet:true,skirtFileScales:mixedSource});await page.evaluate(()=>openModelViewer(['/synthetic/mixed-skirt-file.unity']));
    const mixedSkirt=await state();assert.equal(mixedSkirt.rig.skirtValues.fileUniform,null);assert.equal(mixedSkirt.rig.skirtValues.currentUniform,null);
    assert.equal(await page.locator('#viewer-skirt-number').inputValue(),'');assert.equal(await page.locator('#viewer-skirt-file').innerText(),'Different values');assert.equal(await page.locator('#viewer-skirt-value').innerText(),'Different values');
    await page.locator('#viewer-skirt-details').evaluate(details=>details.open=true);
    const rootRow=page.locator('#viewer-skirt-nodes tr[data-viewer-skirt-node="3"]');
    assert.equal(await rootRow.locator('td').nth(1).innerText(),'0.85 / 0.9 / 0.95');assert.equal(await rootRow.locator('td').nth(2).innerText(),'0.85 / 0.9 / 0.95');
    await applySkirt(.85);assert.equal((await state()).rig.skirtValues.currentUniform,.85);assert.equal((await state()).rig.skirtValues.fileUniform,null);
    await page.locator('#viewer-skirt-reset').click();assert.equal((await state()).rig.skirtValues.currentUniform,null);assert.equal(await page.locator('#viewer-skirt-number').inputValue(),'');

    generated=fixture({semanticExpressions:true,expressionBone:true});await page.evaluate(()=>openModelViewer(['/synthetic/manual-axis-expression-baseline.unity']));
    await inputNode(2,'scale','X',1.4);await eyePreset();
    nearVector(bone(await state(),2).scale,[1.4,.7,.6],'Absolute X stays fixed while unedited Y/Z inherit an expression transform');
    await page.locator('#viewer-expression-reset').click();nearVector(bone(await state(),2).scale,[1.4,.9,1],'Expression reset restores inherited file axes without rebasing manual X');
    await page.locator('#viewer-saved-nodes').uncheck();nearVector(bone(await state(),2).scale,[1.4,1,1],'Manual endpoint remains absolute through another baseline change');

    generated=fixture({semanticExpressions:true,authoredHidden:true});await page.evaluate(()=>openModelViewer(['/synthetic/hidden-expression-visibility-reset.unity']));
    await page.locator('.viewer-options').evaluate(details=>details.open=true);
    assert.equal((await state()).rig.parts[0].fileVisible,false);assert.equal(await page.locator('#viewer-parts input').isChecked(),false);
    await page.locator('#viewer-parts input').check();assert.equal((await state()).rig.parts[0].userChanged,true);
    await page.locator('#viewer-preview-reset').click();assert.equal((await state()).rig.parts[0].userChanged,false);assert.equal(await page.locator('#viewer-parts input').isChecked(),false);
    await eyePreset();
    assert.equal(await page.locator('#viewer-parts input').isChecked(),true,'A verified expression can reveal authored-hidden parts again after global reset');
    assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).sourceTriangles,1);
    await page.locator('#viewer-parts input').uncheck();await eyePreset();
    assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).triangles,0,'Manual hidden choice wins over repeated expression reveals');
    await page.locator('#viewer-parts input').check();await page.locator('#viewer-expression-reset').click();
    assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).sourceTriangles,1,'Manual shown choice wins over the source-hidden expression reset');
    await page.locator('#viewer-preview-reset').click();assert.equal((await page.evaluate(()=>ModelViewer.renderProbe())).triangles,0);assert.equal((await state()).rig.parts[0].fileVisible,false);
    const visibilityChoiceState=await state();

    generated=fixture({semanticExpressions:true,rawWeights:[-.25,1.5]});await page.evaluate(()=>openModelViewer(['/synthetic/unclamped-source-expression-weights.unity']));
    nearVector((await state()).rig.expressions.map(value=>value.weight),[-.25,1.5],'Source morph weights outside0..1 remain exact');
    await page.locator('#viewer-expression-advanced').evaluate(details=>details.open=true);
    const rawOptions=await page.locator('#viewer-expression option').evaluateAll(options=>options.filter(option=>option.value).map(option=>option.value));
    assert.equal(rawOptions.length,2);
    for(const [index,weight]of [[0,-.25],[1,1.5]]){
      await page.locator('#viewer-expression').selectOption(rawOptions[index]);
      assert.equal(Number(await page.locator('#viewer-expression-value').inputValue()),weight*100);assert.equal(Number(await page.locator('#viewer-expression-number').inputValue()),weight*100);
      const panel=(await state()).rig.expressionPanel;assert(panel.rawRange.min<=weight*100&&panel.rawRange.max>=weight*100);
      assert.equal(panel.rawWeights[index].sourceWeight,weight);
    }
    await page.locator('#viewer-expression-number').fill('175');assert.equal((await state()).rig.expressions[1].weight,1.75);
    await page.locator('#viewer-expression-number').fill('10001');let invalidRaw=await state();
    assert.equal(invalidRaw.rig.expressions[1].weight,1.75,'Invalid numeric raw weights must leave the current model unchanged');assert(invalidRaw.rig.expressionPanel.rawInputError);
    await page.locator('#viewer-expression-number').fill('-50');assert.equal((await state()).rig.expressions[1].weight,-.5);
    await page.locator('#viewer-expression-reset').click();nearVector((await state()).rig.expressions.map(value=>value.weight),[-.25,1.5],'Expression reset restores exact immutable source weights');
    const rawExpressionState=await state();

    generated=fixture({backendConflict:true});await page.evaluate(()=>openModelViewer(['/synthetic/backend-marked-conflict.unity']));
    await page.locator('.viewer-node-editor').evaluate(details=>details.open=true);await page.locator('#viewer-node').selectOption('3');
    const backendConflictState=await state();assert.equal(backendConflictState.rig.nodeFileValues.position.status,'conflict');
    assert.deepEqual(backendConflictState.rig.nodeFileValues.position.values,[[0,1,0],[0,2,0]],'Both rejected backend conflict endpoints remain visible as raw file values');
    assert.equal(await page.locator('[data-viewer-value-source="file"][data-viewer-value-kind="position"]').getAttribute('data-viewer-file-status'),'conflict');
    assert.equal(backendConflictState.rig.nodeFileValues.rotation.status,'unsupported');assert.equal(backendConflictState.rig.nodeFileValues.scale.status,'authored');
    generated=fixture();generated.rig.sourcePositions={'6':[0,1.5,-.001]};await page.evaluate(()=>openModelViewer(['/synthetic/native-initialized-position.unity']));
    await page.locator('.viewer-node-editor').evaluate(details=>details.open=true);await page.locator('#viewer-node').selectOption('6');
    const initializedPosition=await state();
    nearVector(initializedPosition.rig.nodeFileValues.position.value,[0,1.5,-.001],'File position retains the original source before native initialization');
    nearVector(initializedPosition.rig.nodeFileValues.position.runtime,[0,1.5,0],'Game initialization is separate from the original source');
    nearVector(bone(initializedPosition,6).position,[0,1.5,0],'Actual current bone retains initialized runtime position');
    assert((await page.locator('[data-viewer-value-source="initialization"][data-viewer-value-kind="position"]').innerText()).includes('Game initial value'));
    assert(!initializedPosition.rig.nodeAdjustments['6'],'Native initialization is not a user adjustment');
    await inputNode(6,'position','Z',.2);await page.locator('#viewer-node-reset').click();
    nearVector(bone(await state(),6).position,[0,1.5,0],'Reset restores the initialized position instead of the raw source position');
    nearVector((await state()).rig.nodeFileValues.position.value,[0,1.5,-.001],'Reset does not rewrite the original file position');
    generated=fixture({zeroAuthoredAxis:true});await page.evaluate(()=>openModelViewer(['/synthetic/zero-axis-absolute-edit.unity']));
    await inputNode(6,'scale','X',.5);nearVector(bone(await state(),6).scale,[.5,1,1],'A zero authored axis can be explicitly edited to a nonzero absolute factor');
    assert.deepEqual((await state()).rig.nodeAdjustments['6'].scale,[.5,null,null]);
    generated=fixture({previewName,rotationStart:.25,previewVerified:true,allSaved:true,rotationConflict:true});await page.evaluate(()=>openModelViewer(['/synthetic/conflicting-rotation.unity']));
    const rotationConflict=await state();assert.equal(rotationConflict.rig.savedNodes.conflicts,1);assert.equal(rotationConflict.rig.savedNodes.skipped,3);assert.equal(rotationConflict.rig.savedNodes.applied,4);assert.deepEqual(bone(rotationConflict,3).quaternion,[0,0,0,1]);
    generated=fixture({allSaved:true,metadataWarning:true});await page.evaluate(()=>openModelViewer(['/synthetic/omitted-invalid-setting.unity']));
    const invalidMetadata=await state();assert.equal(invalidMetadata.rig.savedNodes.skipped,0);assert.deepEqual(invalidMetadata.rig.savedNodes.metadataWarnings,['scaling_invalid_entry']);assert((await page.locator('#viewer-saved-status').innerText()).includes('Unsupported or conflicting saved settings were skipped.'));assert(!(await page.locator('#viewer-saved-status').innerText()).includes('(0)'),'Omitted invalid metadata has no invented skip count');
    assert(await page.locator('#viewer-pose-preview').isDisabled());const beforeDisabled=await state();await page.locator('#viewer-pose-preview').evaluate(element=>element.click());assert.deepEqual((await state()).rig,beforeDisabled.rig);assert.deepEqual(await pressed(),['true','false']);
    assert(!gpuMessages.some(message=>/INVALID_OPERATION|GL_INVALID|THREE.WebGLProgram/.test(message)),JSON.stringify(gpuMessages));
    assert.deepEqual(errors,[]);
    await page.screenshot({path:path.join(evidence,'synthetic-rig-ui.png'),fullPage:true});
    await page.evaluate(()=>ModelViewer.dispose());assert(await page.locator('#viewer-pose-basic').isDisabled());assert(await page.locator('#viewer-pose-preview').isDisabled());assert.deepEqual(await pressed(),['false','false']);
    const report={status:'PASS',scope:'Generated original skinned triangle; product viewer/WebGL and real UI events',requests,initialProbe:probe,scaledProbe,resetRig:reset.rig,unsupportedRig:fallback.rig,visibilityStart:hiddenAtStart,shiftedInitial,shiftedBasic,shiftedMember,memberRecovered,afterContextReload,
      bodyTools:{headBeforeProfile,hairBeforeProfile,moveBeforeProfile,profileInvariant,profileResults,loadedProfile:loadedProfileState.rig.breastProfile,manualProfile:manualProfile.rig.breastProfile,restoredProfile:restoredProfile.rig.breastProfile,toolPresetState:toolPresetState.rig.body,customProfile:customProfileState.rig.breastProfile},inspectorLayouts,
      multiAxisUnity:{loaded:loadedMultiAxis.rig.bones.find(bone=>bone.node==='3'),edited:editedMultiAxis.rig.bones.find(bone=>bone.node==='3'),reset:multiAxisState.rig.bones.find(bone=>bone.node==='3')},
      sourceValueControls:{unavailableSkirtLanguages,zeroSkirt:zeroSkirt.rig.skirtValues,unsupportedZeroSkirt:unsupportedZeroSkirt.rig.skirtValues,initialSkirt:skirtInitial.rig.skirtValues,absoluteControls:absoluteControlsState.rig,mixedSkirt:mixedSkirt.rig.skirtValues,partialMotion:partialMotionState.rig,visibilityChoice:visibilityChoiceState.rig.parts,rawExpressions:rawExpressionState.rig.expressionPanel,backendConflict:backendConflictState.rig.nodeFileValues,initializedPosition:initializedPosition.rig.nodeFileValues},
      namedExpressions:{base:namedExpressionBase,final:namedExpressionState.rig},
      previewMotion:{rejected:previewCases,initial:previewInitial.rig,scaled:previewScaled.rig,reset:previewReset.rig,probe:previewProbe},poseButtons:{allSavedInitial:allSavedInitial.rig,retained:retained.rig,basicFrame,retainedFrame,repeated,responsiveButtons,reset:buttonReset.rig,rotationConflict:rotationConflict.rig,invalidMetadata:invalidMetadata.rig,disposedPressed:await pressed()},errors,gpuMessages};
    fs.writeFileSync(process.env.VIEWER_REPORT||path.join(evidence,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
