"use strict";
const assert = require("assert");
const path = require("path");
const { Worker: NativeWorker } = require("worker_threads");
const math = require("../webtools/web/static/texture-color-math.js");
const names = [], previousWorker = global.Worker;
const input = Uint8ClampedArray.from([220, 190, 157, 255, 40, 90, 220, 17]);
const mask = Uint8Array.from([255, 0]);
const bytes = value => Array.from(value);
async function test(name, run) { await run(); names.push(name); }

class ManualWorker {
  constructor(url) { this.url = url; this.messages = []; this.posts = 0; ManualWorker.latest = this; }
  postMessage(payload, transfers) {
    this.messages.push(structuredClone(payload, { transfer: transfers }));
    this.posts++;
  }
  finish() {
    const request = this.messages.shift(); assert(request);
    const rgba = new Uint8ClampedArray(request.rgba);
    const selection = request.mask ? new Uint8Array(request.mask) : null;
    const result = math.adjustRGBA(rgba, request.width, request.height, selection, request.options);
    this.onmessage({ data: { id: request.id, ok: true, rgba: result.buffer } });
  }
  terminate() { this.terminated = true; }
}

class ThreadWorker {
  constructor(url) {
    assert.strictEqual(url, "/static/texture-color-worker.js");
    const staticDir = path.resolve(__dirname, "../webtools/web/static");
    const bootstrap = `
      const fs=require('fs'),path=require('path'),vm=require('vm');
      const {parentPort}=require('worker_threads');
      globalThis.self=globalThis;
      globalThis.importScripts=name=>vm.runInThisContext(fs.readFileSync(path.join(${JSON.stringify(staticDir)},name),'utf8'),{filename:name});
      globalThis.postMessage=(message,transfers)=>parentPort.postMessage(message,transfers);
      vm.runInThisContext(fs.readFileSync(path.join(${JSON.stringify(staticDir)},'texture-color-worker.js'),'utf8'),{filename:'texture-color-worker.js'});
      parentPort.on('message',data=>self.onmessage({data}));
    `;
    this.worker = new NativeWorker(bootstrap, { eval: true });
    this.worker.on("message", data => { if (this.onmessage) this.onmessage({ data }); });
    this.worker.on("error", error => { if (this.onerror) this.onerror(error); });
  }
  postMessage(data, transfers) { this.worker.postMessage(data, transfers); }
  terminate() { this.worker.terminate(); }
}

async function run() {
  await test("transferred buffers are copies and only the latest pending preview executes", async () => {
    global.Worker = ManualWorker;
    const processor = math.createProcessor(), worker = ManualWorker.latest;
    const original = bytes(input), originalMask = bytes(mask);
    const first = processor.process("adjust", input, 2, 1, mask, { hue: 30 });
    const second = processor.process("adjust", input, 2, 1, mask, { hue: 60 }).catch(error => error);
    const third = processor.process("adjust", input, 2, 1, mask, { hue: 90 });
    assert.strictEqual(worker.posts, 1);
    assert.strictEqual(processor.getState().queued, true);
    assert.strictEqual((await second).name, "AbortError");
    assert.strictEqual(input.byteLength, 8); assert.strictEqual(mask.byteLength, 2);
    worker.finish();
    assert.deepStrictEqual(bytes(await first), bytes(math.adjustRGBA(input, 2, 1, mask, { hue: 30 })));
    assert.strictEqual(worker.posts, 2); assert.strictEqual(worker.messages[0].id, 3);
    worker.finish();
    assert.deepStrictEqual(bytes(await third), bytes(math.adjustRGBA(input, 2, 1, mask, { hue: 90 })));
    assert.deepStrictEqual(bytes(input), original); assert.deepStrictEqual(bytes(mask), originalMask);
    assert.strictEqual(processor.getState().busy, false);
    processor.dispose(); assert(worker.terminated);
  });

  await test("worker load failures stay visible and do not silently switch algorithms", async () => {
    global.Worker = ManualWorker;
    const processor = math.createProcessor(), worker = ManualWorker.latest;
    const first = processor.process("adjust", input, 2, 1, mask, {}).catch(error => error);
    const queued = processor.process("adjust", input, 2, 1, mask, {}).catch(error => error);
    worker.onerror({ message: "Worker resource unavailable" });
    assert.match((await first).message, /Worker resource unavailable/);
    assert.match((await queued).message, /Worker resource unavailable/);
    await assert.rejects(processor.process("adjust", input, 2, 1, mask, {}), /Worker resource unavailable/);
    assert(worker.terminated); processor.dispose();
  });

  await test("closing the editor cancels every pending operation and terminates its worker", async () => {
    global.Worker = ManualWorker;
    const processor = math.createProcessor(), worker = ManualWorker.latest;
    const first = processor.process("adjust", input, 2, 1, mask, {}).catch(error => error);
    const second = processor.process("skin", input, 2, 1, mask, { source: "default", target: "bright" }).catch(error => error);
    processor.dispose(); processor.dispose();
    assert.strictEqual((await first).name, "AbortError"); assert.strictEqual((await second).name, "AbortError");
    assert.strictEqual(worker.terminated, true);
    await assert.rejects(processor.process("adjust", input, 2, 1, mask, {}), { name: "AbortError" });
  });

  await test("blocked Worker construction is a visible operation error, not an editor crash", async () => {
    global.Worker = class { constructor() { throw new Error("Worker blocked by policy"); } };
    const processor = math.createProcessor();
    assert.match(processor.getState().error, /Worker blocked by policy/);
    await assert.rejects(processor.process("adjust", input, 2, 1, mask, {}), /Worker blocked by policy/);
    processor.dispose();
  });

  await test("runtimes without Worker retain Promise/error and bounded queue semantics", async () => {
    delete global.Worker;
    const processor = math.createProcessor();
    const first = processor.process("adjust", input, 2, 1, mask, { hue: 20 });
    const second = processor.process("adjust", input, 2, 1, mask, { hue: 40 }).catch(error => error);
    const third = processor.process("adjust", input, 2, 1, mask, { hue: 60 });
    assert.strictEqual((await second).name, "AbortError");
    assert.deepStrictEqual(bytes(await first), bytes(math.adjustRGBA(input, 2, 1, mask, { hue: 20 })));
    assert.deepStrictEqual(bytes(await third), bytes(math.adjustRGBA(input, 2, 1, mask, { hue: 60 })));
    await assert.rejects(processor.process("skin", input, 2, 1, null, { target: "bright" }), /Select and confirm/);
    assert.strictEqual(processor.getState().worker, false); processor.dispose();
  });

  await test("actual colour worker executes adjust, skin and grow through transferable IPC", async () => {
    global.Worker = ThreadWorker;
    const processor = math.createProcessor();
    try {
      const original = bytes(input), selection = bytes(mask);
      const adjusted = await processor.process("adjust", input, 2, 1, mask, { mode: "colorize", color: "#b03481" });
      assert(adjusted instanceof Uint8ClampedArray);
      assert.deepStrictEqual(bytes(adjusted), bytes(math.adjustRGBA(input, 2, 1, mask, { mode: "colorize", color: "#b03481" })));
      const skin = await processor.process("skin", input, 2, 1, mask, { source: "default", target: "bright" });
      assert.deepStrictEqual(bytes(skin), bytes(math.skinRGBA(input, 2, 1, mask, { source: "default", target: "bright" })));
      const selected = await processor.process("grow", input, 2, 1, mask, { seeds: [[0, 0]], tolerance: .1 });
      assert(selected instanceof Uint8Array); assert.deepStrictEqual(bytes(selected), [255, 0]);
      assert.deepStrictEqual(bytes(input), original); assert.deepStrictEqual(bytes(mask), selection);
      await assert.rejects(processor.process("adjust", input, 2, 1, mask, { hue: NaN }), /Invalid hue/);
    } finally { processor.dispose(); }
  });
}
run().then(() => {
  if (previousWorker === undefined) delete global.Worker; else global.Worker = previousWorker;
  console.log(JSON.stringify({ status: "PASS", cases: names.length, names }));
}, error => {
  if (previousWorker === undefined) delete global.Worker; else global.Worker = previousWorker;
  console.error(error.stack || error); process.exitCode = 1;
});
