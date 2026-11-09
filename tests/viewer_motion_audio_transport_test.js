/* Execute the real audio controller against a declared media/DOM boundary.
 * Real decoder/output-thread continuity lives in viewer_audio_continuity_browser.js.
 */
const assert = require('assert'), fs = require('fs'), path = require('path'), vm = require('vm');
class Element {
  constructor(tag) { this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.listeners={};this.checked=false;this.value='';this.parentNode=null; }
  appendChild(child){this.children.push(child);child.parentNode=this;return child;}
  addEventListener(type,handler){(this.listeners[type]||(this.listeners[type]=[])).push(handler);}
  dispatch(type){(this.listeners[type]||[]).forEach(handler=>handler({target:this,type}));}
  setAttribute(name,value){this[name]=value;}
  removeAttribute(name){delete this[name];}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(child=>child!==this);}
  querySelectorAll(){return [];}
  closest(selector){return selector.split(',').some(id=>id.trim()==='#'+this.id)?this:null;}
}
let nextPlayFailures=0;
class Media extends Element {
  constructor(){super('audio');this.paused=true;this.duration=20;this.readyState=4;this.playbackRate=1;this.seeking=false;this.ended=false;this.position=0;this.seeks=0;this.playCalls=0;this.failures=nextPlayFailures;nextPlayFailures=0;}
  get currentTime(){return this.position;}
  set currentTime(value){assert(Number.isFinite(value));this.position=value;this.seeks++;}
  pause(){this.paused=true;}
  play(){this.playCalls++;if(this.failures>0){this.failures--;return Promise.reject(Object.assign(new Error('Interrupted start'),{name:'AbortError'}));}this.paused=false;return Promise.resolve();}
  load(){}
  advance(seconds){if(!this.paused)this.position+=seconds*this.playbackRate;}
}
const body=new Element('body'), panel=new Element('details');panel.id='viewer-adjustments';body.appendChild(panel);
const document=new Element('document');document.documentElement={lang:'en'};document.readyState='complete';document.hidden=false;
document.createElement=tag=>tag==='audio'?new Media():new Element(tag);
document.getElementById=id=>{function visit(node){if(node.id===id)return node;for(const child of node.children){const found=visit(child);if(found)return found;}return null;}return visit(body);};
const state={modelId:'body1',visible:true,loading:false,contextLost:false,layout:{minimized:false},rig:{selectedClip:'Motion A',playing:false,time:0,duration:8,playbackRevision:0}};
const preferences=new Map(),frames=new Map(),timers=new Map();let sequence=0;
const window={ModelViewer:{getMotionState:()=>state},addEventListener:()=>{}};
const context={window,document,console,Number,Array,Math,JSON,URL:{createObjectURL:()=> 'blob:local-original',revokeObjectURL:()=>{}},
  MutationObserver:class{observe(){}},localStorage:{getItem:key=>preferences.get(key)||null,setItem:(key,value)=>preferences.set(key,value)},
  requestAnimationFrame:handler=>{const id=++sequence;frames.set(id,handler);return id;},cancelAnimationFrame:id=>frames.delete(id),
  setTimeout:handler=>{const id=++sequence;timers.set(id,handler);return id;},clearTimeout:id=>timers.delete(id)};
vm.runInNewContext(fs.readFileSync(process.env.VIEWER_AUDIO_SCRIPT||path.resolve(__dirname,'../webtools/web/static/viewer-motion-audio.js'),'utf8'),context);
const api=window.ViewerMotionAudio, track=()=>panel.children.find(child=>child.id==='viewer-motion-audio-controls').children.find(child=>child.tagName==='AUDIO');
const input=id=>document.getElementById(id), descriptor=(overrides={})=>({version:1,tracks:[{url:'/api/viewer/game/motions/audio/'+'a'.repeat(32)+'.wav',cue:'Original cue',startTime:.5,offset:1.25,playDuration:6,playbackRate:.8,...overrides}]});
async function tick(){const callbacks=[...frames.values(),...timers.values()];frames.clear();timers.clear();callbacks.forEach(handler=>handler());await Promise.resolve();await Promise.resolve();}
async function main(){
  api.load(descriptor(),{modelId:'body1',clipNames:['Motion A']});let media=track();
  assert(media.paused);assert.equal(media.currentTime,1.25);state.rig.playing=true;state.rig.time=.3;await tick();assert(media.paused,'Deferred cue retains its authored start');
  state.rig.time=.55;await tick();assert(!media.paused);assert.equal(media.playbackRate,.8);assert(Math.abs(api.getPlaybackClock(state.rig)-.55)<1e-9);
  const seeks=media.seeks;media.advance(.25);state.rig.time=.6;await tick();
  assert.equal(media.seeks,seeks,'A slow render clock must not rewind an independently playing decoder');assert(Math.abs(api.getPlaybackClock(state.rig)-.8)<1e-9);
  state.rig.time=api.getPlaybackClock(state.rig);state.rig.playing=false;await tick();const paused=media.currentTime;await tick();assert.equal(media.currentTime,paused);
  state.rig.time=.75;state.rig.playbackRevision++;api.sync();assert(Math.abs(media.currentTime-1.45)<1e-9);assert.equal(api.getPlaybackClock(state.rig),null);
  state.rig.playing=true;await tick();const mutedSeeks=media.seeks;input('viewer-motion-audio-muted').checked=true;input('viewer-motion-audio-muted').dispatch('change');
  input('viewer-motion-audio-volume').value='.4';input('viewer-motion-audio-volume').dispatch('input');assert(media.muted);assert.equal(media.volume,.4);assert.equal(media.seeks,mutedSeeks);
  state.rig.time=2;state.rig.playbackRevision++;api.sync();media.advance(.2);state.rig.time=.7;await tick();assert(Math.abs(media.currentTime-1.41)<1e-9,'A loop performs one authored-position reset');
  state.modelId='body2';await tick();assert(media.paused);assert.equal(api.getPlaybackClock(state.rig),null);
  api.load(descriptor(),{modelId:'body2',clipNames:['Motion A']});await tick();media=track();assert(!media.paused);assert.equal(typeof api.getPlaybackClock(state.rig),'number');
  state.rig.selectedClip='Different motion';await tick();assert(media.paused);state.rig.selectedClip='Motion A';state.rig.time=0;state.rig.playbackRevision++;
  nextPlayFailures=3;api.load(descriptor({startTime:0,offset:0}),{modelId:'body2',clipNames:['Motion A']});media=track();
  await Promise.resolve();await Promise.resolve();const initialSeeks=media.seeks;
  for(let retry=0;retry<4;retry++){state.rig.time+=.03;await tick();}
  assert.equal(media.failures,0);assert(!media.paused);assert.equal(media.seeks,initialSeeks,'Aborted play retries must not repeatedly restart an asynchronous seek');
  document.hidden=true;await tick();assert(media.paused);assert.equal(api.getPlaybackClock(state.rig),null);document.hidden=false;await tick();assert(!media.paused);
  const file=input('viewer-motion-audio-file');file.files=[{name:'Original local.wav',size:1024}];file.dispatch('change');await tick();assert.equal(api.getState().source,'local');
  assert.equal(typeof api.getPlaybackClock(state.rig),'number');
  assert.throws(()=>api.load({version:1,tracks:[{...descriptor().tracks[0],url:'https://example.invalid/audio.wav'}]}),/invalid/);
  state.rig.playing=false;api.clear();await tick();assert(api.getState().paused);
  console.log('MOTION_AUDIO_TRANSPORT_PASS');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
