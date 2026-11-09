/* Actual PCM/WebAudio transport under a stalled 30 FPS render clock.
 * The small timeline host models the viewer's accepted-frame clock; it is not
 * a game/Unity scene. PCM, decoding, output-thread continuity and media seeks
 * run in Chromium. --baseline records the known old hard-seek failure.
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');
const crypto = require('crypto');
const { chromium } = require('playwright');
const source = process.env.VIEWER_AUDIO_SCRIPT || path.resolve(__dirname, '../webtools/web/static/viewer-motion-audio.js');
const baseline = process.argv.includes('--baseline');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-audio-continuity-'));
const token = 'a'.repeat(32), rate = 48000, seconds = 16, channels = 2;
const wav = Buffer.alloc(44 + rate * seconds * channels * 2);
wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8); wav.writeUInt32LE(16, 16);
wav.writeUInt16LE(1, 20); wav.writeUInt16LE(channels, 22); wav.writeUInt32LE(rate, 24);
wav.writeUInt32LE(rate * channels * 2, 28); wav.writeUInt16LE(channels * 2, 32); wav.writeUInt16LE(16, 34);
wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
for (let frame = 0; frame < rate * seconds; frame++) for (let channel = 0; channel < channels; channel++)
  wav.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 997 * frame / rate) * 8000), 44 + (frame * channels + channel) * 2);
const html = `<!doctype html><html lang="en"><body><details id="viewer-adjustments" open></details>
<button id="viewer-play">Play</button><input id="viewer-time" type="range" min="0" max="16" step=".001">
<script>
window.host={modelId:'body1',visible:true,loading:false,contextLost:false,layout:{minimized:false},
 rig:{selectedClip:'Original tone',playing:false,time:0,duration:16,playbackRevision:0}};
window.ModelViewer={getMotionState:()=>host};
window.hostQa={stalls:0,frames:0,wraps:0,stalling:false,last:0,elapsed:0,lastStall:0};
document.getElementById('viewer-play').onclick=()=>{host.rig.playing=!host.rig.playing;};
document.getElementById('viewer-time').oninput=function(){host.rig.time=Number(this.value);host.rig.playbackRevision++;};
function tick(now){const q=hostQa;let dt=q.last?Math.min(.1,(now-q.last)/1000):0;q.last=now;
 if(host.rig.playing){q.elapsed+=dt;if(q.elapsed+1e-8>=1/30){let accepted=q.elapsed;q.elapsed=0;
  const clock=ViewerMotionAudio.getPlaybackClock?ViewerMotionAudio.getPlaybackClock(host.rig):null;
  host.rig.time+=typeof clock==='number'?Math.max(0,clock-host.rig.time):accepted;q.frames++;
  if(host.rig.time>=host.rig.duration){host.rig.time%=host.rig.duration;q.wraps++;}
 }}
 if(q.stalling&&now-q.lastStall>400){q.lastStall=now;q.stalls++;const end=performance.now()+220;while(performance.now()<end){}}
 requestAnimationFrame(tick);
}
requestAnimationFrame(tick);
</script><script src="/audio.js"></script></body></html>`;
const worklet = `class Check extends AudioWorkletProcessor {
 constructor(){super();this.capture=false;this.reset();this.port.onmessage=e=>{if(e.data==='start'){this.reset();this.capture=true;}if(e.data==='report')this.port.postMessage(this.stats);};}
 reset(){this.stats={quanta:0,nonzero:0,zero:0,longestZero:0,discontinuities:0,maxRecurrenceError:0};this.previous=0;this.beforePrevious=0;this.zeros=0;this.warm=0;}
 process(inputs,outputs){const input=inputs[0]||[],output=outputs[0]||[];for(let c=0;c<output.length;c++)if(input[c])output[c].set(input[c]);
 if(this.capture&&input[0]){let sum=0;const samples=input[0],coefficient=2*Math.cos(2*Math.PI*997/sampleRate);
  for(let i=0;i<samples.length;i++){const value=samples[i];sum+=value*value;
   const error=Math.abs(value-coefficient*this.previous+this.beforePrevious);
   if(this.warm>256){this.stats.maxRecurrenceError=Math.max(this.stats.maxRecurrenceError,error);if(error>.02)this.stats.discontinuities++;}
   this.beforePrevious=this.previous;this.previous=value;this.warm++;
  }
  this.stats.quanta++;if(sum/samples.length<1e-7){this.stats.zero++;this.zeros++;this.stats.longestZero=Math.max(this.stats.longestZero,this.zeros);}else{this.stats.nonzero++;this.zeros=0;}
 }return true;
 }}registerProcessor('check-continuity',Check);`;
const server = http.createServer((request, response) => {
  const resource = request.url === '/audio.js' ? fs.readFileSync(source) : request.url === '/worklet.js' ? Buffer.from(worklet) :
    request.url === '/api/viewer/game/motions/audio/' + token + '.wav' ? wav : Buffer.from(html);
  response.setHeader('Content-Type', request.url === '/audio.js' || request.url === '/worklet.js' ? 'text/javascript' : resource === wav ? 'audio/wav' : 'text/html');
  response.setHeader('Cache-Control', 'no-store'); response.setHeader('Accept-Ranges', 'bytes');
  const range = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range || '');
  if (range) { const start=Number(range[1]),end=Math.min(range[2]?Number(range[2]):resource.length-1,resource.length-1);
    response.writeHead(206,{'Content-Length':end-start+1,'Content-Range':`bytes ${start}-${end}/${resource.length}`});response.end(resource.subarray(start,end+1));
  } else { response.setHeader('Content-Length',resource.length);response.end(resource); }
});
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
async function main() {
  fs.mkdirSync(evidence,{recursive:true}); await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||'/usr/bin/chromium',args:['--no-sandbox']});
  const report={scope:'Browser PCM/WebAudio and media transport; controlled accepted30FPS timeline host, not a Unity scene',mode:baseline?'baseline':'regression',sourceSha256:crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex')};
  try {
    const page=await browser.newPage(),errors=[];page.on('pageerror',error=>errors.push(String(error)));
    await page.addInitScript(()=>{window.__audioSeekEvents=0;const descriptor=Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,'currentTime');
      Object.defineProperty(HTMLMediaElement.prototype,'currentTime',{...descriptor,set(value){__audioSeekEvents++;return descriptor.set.call(this,value);}});});
    await page.goto('http://127.0.0.1:'+server.address().port);
    const descriptor={version:1,tracks:[{url:'/api/viewer/game/motions/audio/'+token+'.wav',cue:'Original997HzStereo',startTime:0,offset:0,playDuration:16,playbackRate:1}]};
    await page.evaluate(descriptor=>ViewerMotionAudio.load(descriptor,{modelId:'body1',clipNames:['Original tone']}),descriptor);
    await page.waitForFunction(()=>ViewerMotionAudio.getState().tracks[0].readyState>=2);
    await page.evaluate(async()=>{const context=new AudioContext({sampleRate:48000});await context.audioWorklet.addModule('/worklet.js');
      const check=new AudioWorkletNode(context,'check-continuity');context.createMediaElementSource(document.querySelector('audio')).connect(check).connect(context.destination);
      window.outputQa={context,check,stats:null};check.port.onmessage=event=>outputQa.stats=event.data;});
    if(!baseline) await page.evaluate(()=>{const play=HTMLMediaElement.prototype.play;hostQa.interruptedStarts=0;
      HTMLMediaElement.prototype.play=function(){const result=play.call(this);if(hostQa.interruptedStarts<3){hostQa.interruptedStarts++;this.pause();}return result;};});
    await page.locator('#viewer-play').click();await page.evaluate(()=>outputQa.context.resume());
    await page.waitForFunction(()=>ViewerMotionAudio.getState().time>.3);
    const before=await page.evaluate(()=>{outputQa.check.port.postMessage('start');hostQa.stalling=true;
      return {audio:ViewerMotionAudio.getState(),rig:{...host.rig},frames:hostQa.frames,interruptedStarts:hostQa.interruptedStarts,mediaSeeks:__audioSeekEvents};});
    await wait(3600);
    report.continuous=await page.evaluate(()=>{hostQa.stalling=false;outputQa.check.port.postMessage('report');
      const audio=ViewerMotionAudio.getState();return {audio,rig:{...host.rig},stalls:hostQa.stalls,frames:hostQa.frames,drift:Math.abs(audio.time-host.rig.time)};});
    await page.waitForFunction(()=>outputQa.stats!==null);report.pcm=await page.evaluate(()=>outputQa.stats);report.before=before;
    report.seekEvents=await page.evaluate(()=>__audioSeekEvents)-before.mediaSeeks;
    if(baseline){
      assert(report.seekEvents>=3,'The original controller must reproduce repeated hard seeks');
    }else{
      assert(report.continuous.stalls>=5);assert(report.pcm.nonzero>500,'Audio output thread rendered continuous real PCM');
      assert.equal(before.interruptedStarts,3);assert(before.audio.tracks[0].seeks<=1,'Interrupted play retries must not restart decoder seeks each frame');
      assert.equal(report.pcm.longestZero,0,'A render stall must not insert silent output quanta');
      assert.equal(report.pcm.discontinuities,0,'The PCM tone must retain its sample phase through render stalls');
      assert.equal(report.continuous.audio.tracks[0].seeks,before.audio.tracks[0].seeks,'Continuous playback must not seek the decoder');
      assert(report.continuous.drift<.08,'The accepted-frame motion samples the media clock without accumulating lag');
      await page.locator('#viewer-play').click();await page.waitForFunction(()=>ViewerMotionAudio.getState().paused);
      const held=await page.evaluate(()=>ViewerMotionAudio.getState().time);await wait(180);
      assert(Math.abs(await page.evaluate(()=>ViewerMotionAudio.getState().time)-held)<.01);
      await page.locator('#viewer-time').fill('1.25');await page.locator('#viewer-time').dispatchEvent('input');
      await page.waitForFunction(()=>Math.abs(ViewerMotionAudio.getState().time-1.25)<.03);
      await page.locator('#viewer-play').click();await page.waitForFunction(()=>!ViewerMotionAudio.getState().paused);
      const seeks=await page.evaluate(()=>ViewerMotionAudio.getState().tracks[0].seeks);
      await page.locator('#viewer-motion-audio-controls').evaluate(element=>{element.open=true;});
      await page.locator('#viewer-motion-audio-muted').check();await page.locator('#viewer-motion-audio-volume').fill('0.4');
      await page.locator('#viewer-motion-audio-volume').dispatchEvent('input');await wait(300);
      assert.equal(await page.evaluate(()=>ViewerMotionAudio.getState().tracks[0].seeks),seeks,'Mute/volume must not seek uninterrupted media');
      await page.locator('#viewer-play').click();await page.evaluate(()=>{host.rig.duration=1.4;document.getElementById('viewer-time').value='1.2';document.getElementById('viewer-time').dispatchEvent(new Event('input',{bubbles:true}));});
      await page.locator('#viewer-play').click();await page.waitForFunction(()=>hostQa.wraps>=1);await wait(150);
      report.loop=await page.evaluate(()=>({wraps:hostQa.wraps,audio:ViewerMotionAudio.getState(),rig:{...host.rig}}));
      assert(report.loop.audio.time<.7,'A motion loop must restart its authored audio once');
      await page.evaluate(()=>{host.modelId='body2';});await page.waitForFunction(()=>ViewerMotionAudio.getState().paused);
      await page.evaluate(descriptor=>ViewerMotionAudio.load(descriptor,{modelId:'body2',clipNames:['Original tone']}),descriptor);
      await page.waitForFunction(()=>!ViewerMotionAudio.getState().paused);report.rebound=await page.evaluate(()=>ViewerMotionAudio.getState());
      report.pauseSeekLoopMuteVolumeAndModelRebind=true;
    }
    assert.deepStrictEqual(errors,[]);report.status='PASS';
  }finally{fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2));await browser.close();await new Promise(resolve=>server.close(resolve));}
  console.log(JSON.stringify({status:report.status,evidence,mode:report.mode,seeks:report.continuous.audio.tracks[0].seeks||report.seekEvents,drift:report.continuous.drift,pcm:report.pcm}));
}
main().catch(error=>{console.error(error);process.exitCode=1;server.close();});
