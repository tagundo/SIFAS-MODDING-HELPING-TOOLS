/* Public persistence UI transitions: recipe ordering must not become an edit.
 * Job replies are neutral fixtures; pixel/Unity round trips live in the HTTP QA.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "webtools/web/index.html"), "utf8")
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
  .replace(/<link\b[^>]*>/gi, "");

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
    headless: true, args: ["--no-sandbox"] });
  const cases = [];
  try {
    for (const changedPixels of [false, true]) {
      const page = await browser.newPage();
      const errors = [];
      page.on("pageerror", error => errors.push(String(error)));
      await page.setContent(html);
      await page.addScriptTag({ path: path.join(root, "webtools/web/static/viewer-persistence.js") });
      await page.evaluate(() => {
        const original = "/models/original.unity", saved = "/models/edited.unity";
        const body = { version: 1, edits: [], savedSettingsEnabled: true, unsupported: [] };
        const row = (source, file, id, png) => ({ texture: { source, file, id }, sourceSha256: "a".repeat(64), png, kind: "paint" });
        // The last two IDs differ below Number precision and share their prefix.
        window.testTextures = [row(1, 2, "-9007199254740993", "pixels-C"),
          row(0, 0, "9007199254740993", "pixels-B"), row(0, 0, "9007199254740992", "pixels-A")];
        window.testContext = { current: true, modelId: "original", loadedPaths: [original],
          editing: { available: true, token: "texture-source", nodes: [], modPackaging: { available: false } },
          rig: { getAuthoringState: () => ({ ...body, edits: [] }), getState: () => ({}),
            setAuthoringEnabled() {}, setEvaluationMode() {} },
          textureTools: { getEdits: () => window.testTextures, hasPending: () => false, getRevision: () => 1 } };
        window.openCalls = [];
        window.fetch = async (url, options) => {
          if (url === "/api/viewer/edit/export") {
            window.savedRequest = JSON.parse(options.body);
            return { ok: true, json: async () => ({ job_id: "texture-order-job" }) };
          }
          if (url === "/api/viewer/edit/result/texture-order-job") return { ok: true, json: async () => ({
            output_paths: [saved], preview_paths: [saved], original_paths: [original], recipe_path: "/models/edit.json",
            recipe: { format: "fixture", state: window.savedRequest.state } }) };
          throw new Error("Unexpected request " + url);
        };
        window.EventSource = class {
          constructor() { setTimeout(() => this.onmessage && this.onmessage({ data: JSON.stringify({ type: "done", status: "done" }) }), 0); }
          close() {}
        };
        window.persistence = ViewerPersistence.create({ translate: value => value, context: () => window.testContext,
          openFiles: async paths => { window.openCalls.push(paths); window.testContext.loadedPaths = paths; window.testContext.modelId = "saved"; },
          pickFile() {} });
        document.getElementById("viewer-save").click();
      });
      await page.waitForFunction(() => !persistence.getState().busy && persistence.getState().status === "done");
      await page.evaluate(changed => {
        // Restore-style JSON uses a different operation and object-key order.
        window.testTextures = window.testTextures.slice().reverse().map(row => ({
          kind: row.kind, png: row.png, sourceSha256: row.sourceSha256,
          texture: { id: row.texture.id, file: row.texture.file, source: row.texture.source } }));
        if (changed) window.testTextures[0].png += "-edited";
        persistence.refresh();
        document.getElementById("viewer-open-saved").click();
      }, changedPixels);
      await page.waitForFunction(() => !persistence.getState().busy);
      const result = await page.evaluate(() => ({ state: persistence.getState(), calls: openCalls }));
      assert.deepEqual(errors, [], "Controller must not raise a page exception");
      if (changedPixels) {
        assert.equal(result.calls.length, 0, "Actual pixel changes still prevent opening an old saved result");
        assert.equal(result.state.status, "error");
      } else {
        assert.equal(result.calls.length, 1, "Equivalent ordering and key-order changes must open the saved result");
        assert.equal(result.state.reviewingSaved, true);
      }
      cases.push(changedPixels ? "changed pixels remain protected" : "reversed recipe/key order with signed 64-bit IDs stays equivalent");
      await page.close();
    }
    process.stdout.write(JSON.stringify({ status: "PASS", cases }) + "\n");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
