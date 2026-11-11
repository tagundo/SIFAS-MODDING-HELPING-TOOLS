/* Real layer-engine + public persistence-controller failure/re-edit transitions.
 * HTTP/job answers are controlled fixtures; native pixel saving is verified by
 * the separate product HTTP/Unity browser driver, not claimed by this probe.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const product = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(product, "webtools/web/index.html"), "utf8")
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "").replace(/<link\b[^>]*>/gi, "");

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
    headless: true, args: ["--no-sandbox"] });
  const cases = [];
  try {
    for (const scenario of ["failed-recipe", "saved-copy-reedit"]) {
      const page = await browser.newPage(), pageErrors = [];
      page.on("pageerror", error => pageErrors.push(String(error)));
      await page.setContent(html);
      for (const script of ["texture-paint-engine.js", "viewer-persistence.js"]) {
        await page.addScriptTag({ path: path.join(product, "webtools/web/static", script) });
      }
      await page.evaluate(mode => {
        const originalPath = "/models/original.unity", savedPath = "/models/edited.unity";
        const original = { width: 2, height: 1, data: new Uint8ClampedArray([9, 8, 7, 0, 20, 40, 60, 180]) };
        const replacement = { width: 2, height: 1, data: new Uint8ClampedArray([3, 2, 1, 0, 240, 90, 70, 117]) };
        const engine = TexturePaintEngine.create();
        engine.setImage(original);
        engine.addLayer({ name: "피부", image: { width: 2, height: 1,
          data: new Uint8ClampedArray([66, 55, 44, 0, 210, 120, 80, 128]) } });
        engine.setLayerOpacity(engine.getState().activeLayerId, .35);
        const paintLayer = engine.getState().activeLayerId;
        engine.addLayer({ name: "Hidden accent" });
        engine.setLayerVisible(engine.getState().activeLayerId, false);
        engine.selectLayer(paintLayer); engine.setMask(new Uint8Array([128, 255]));
        const identity = { source: 0, file: 0, id: "9007199254740993" }, sourceSha = "a".repeat(64);
        const operation = png => ({ texture: { ...identity }, sourceSha256: sourceSha, png, kind: "paint" });
        let rows = [operation("original-flattened-png")];
        let body = { version: 1, edits: [], savedSettingsEnabled: true, unsupported: [] };
        window.layerEditor = engine;
        window.events = [];
        window.captureDocuments = copy => ({ version: 1, documents: [{ texture: { ...identity }, sourceSha256: sourceSha,
          project: engine.getProject(copy !== false), mask: engine.getMask(), rows: rows.map(row => ({ ...row, texture: { ...row.texture } })) }] });
        window.projectJSON = () => JSON.stringify(engine.getProject().layers.map(layer => ({ ...layer,
          image: { ...layer.image, data: Array.from(layer.image.data) } })));
        window.beforeProject = projectJSON(); window.beforeMask = Array.from(engine.getMask());
        window.beforeActive = engine.getState().activeLayerId;
        window.context = { current: true, modelId: "original", loadedPaths: [originalPath],
          editing: { available: true, token: "immutable-texture-source", nodes: [], modPackaging: { available: false } },
          rig: { getAuthoringState: () => ({ ...body, edits: [] }), getState: () => ({}), setAuthoringEnabled() {}, setEvaluationMode() {},
            restoreAuthoringState: state => { events.push("body"); body = { ...state }; delete body.textures; } },
          textureTools: { getEdits: () => rows, hasPending: () => false, getRevision: () => engine.getState().projectRevision } };
        async function restoreDocuments(snapshot) {
          events.push("documents");
          const document = snapshot.documents[0];
          if (document.sourceSha256 !== sourceSha) throw new Error("Snapshot source changed");
          if (!(document.project.layers[0].image.data instanceof Uint8ClampedArray)) throw new Error("Typed layer pixels were JSON serialized");
          engine.restoreProject(document.project, { history: false }); engine.setMask(document.mask, { history: false });
          rows = document.rows.map(row => ({ ...row, texture: { ...row.texture } }));
        }
        async function restoreTextureState(next) {
          events.push("flattened-texture"); rows = next.map(row => ({ ...row, texture: { ...row.texture } }));
          engine.replaceImageData(replacement, { history: false }); engine.selectNone();
        }
        window.inspections = []; window.openCalls = [];
        window.fetch = async (url, options) => {
          if (url === "/api/viewer/edit/restore") {
            const state = mode === "failed-recipe" ? { ...body, textures: [operation("replacement-png")] } : savedRequest.state;
            return { ok: true, json: async () => ({ state,
              ...(mode === "failed-recipe" ? { mesh_state: { version: 1, meshes: [] } } : {}) }) };
          }
          if (url === "/api/viewer/edit/export") {
            window.savedRequest = JSON.parse(options.body);
            return { ok: true, json: async () => ({ job_id: "layers-rollback-job" }) };
          }
          if (url === "/api/viewer/edit/result/layers-rollback-job") return { ok: true, json: async () => ({
            output_paths: [savedPath], preview_paths: [savedPath], original_paths: [originalPath], recipe_path: "/models/edits.json",
            recipe: { format: "fixture", state: savedRequest.state } }) };
          throw new Error("Unexpected request " + url);
        };
        window.EventSource = class {
          constructor() { setTimeout(() => this.onmessage && this.onmessage({ data: JSON.stringify({ type: "done", status: "done" }) }), 0); }
          close() {}
        };
        window.persistence = ViewerPersistence.create({ translate: value => value, context: () => window.context,
          captureTextureDocuments: () => captureDocuments(false), restoreTextureDocuments: restoreDocuments,
          restoreTextureState, restoreMeshState: async () => { events.push("mesh-failure"); throw new Error("injected mesh restore failure"); },
          captureInspection: () => { const inspection = { textureDocuments: captureDocuments(true) }; inspections.push(inspection); return inspection; },
          openFiles: async (paths, variants, inspection) => {
            events.push(paths[0] === savedPath ? "open-saved" : "open-original");
            openCalls.push({ paths, inspection }); context.loadedPaths = paths;
            context.modelId = paths[0] === savedPath ? "saved" : "original";
            engine.setImage(replacement); rows = [];
          }, pickFile() {} });
      }, scenario);

      if (scenario === "failed-recipe") {
        const result = await page.evaluate(async () => {
          let failure = "";
          try { await persistence.restoreRecipe({ format: "fixture" }); } catch (error) { failure = error.message; }
          return { failure, project: projectJSON(), before: beforeProject, mask: Array.from(layerEditor.getMask()), beforeMask,
            active: layerEditor.getState().activeLayerId, beforeActive, events,
            rows: context.textureTools.getEdits(), layerCount: layerEditor.getLayers().length };
        });
        assert.equal(result.failure, "injected mesh restore failure");
        assert.deepEqual(result.events, ["body", "flattened-texture", "mesh-failure", "body", "documents"]);
        assert.equal(result.project, result.before, "Failure restores the complete layered document rather than one flattened PNG");
        assert.deepEqual(result.mask, result.beforeMask); assert.equal(result.active, result.beforeActive);
        assert.equal(result.layerCount, 3); assert.equal(result.rows[0].png, "original-flattened-png");
        assert.equal(result.rows[0].sourceSha256, "a".repeat(64));
        cases.push("mesh failure after PNG restore rolls back exact layers, active layer, mask and immutable source binding");
      } else {
        await page.evaluate(() => { window.oldActiveBytes = layerEditor.getActiveImage(false).data; document.getElementById("viewer-save").click(); });
        await page.waitForFunction(() => !persistence.getState().busy && persistence.getState().status === "done");
        await page.evaluate(() => document.getElementById("viewer-open-saved").click());
        await page.waitForFunction(() => !persistence.getState().busy && persistence.getState().reviewingSaved);
        await page.evaluate(() => {
          // Mutate a retained buffer from the disposed original document. Both
          // save and inspection snapshots must own their earlier image bytes.
          oldActiveBytes.fill(17);
          document.getElementById("viewer-reedit-original").click();
        });
        await page.waitForFunction(() => !persistence.getState().busy && !persistence.getState().reviewingSaved);
        const result = await page.evaluate(() => ({ state: persistence.getState(), project: projectJSON(), before: beforeProject,
          mask: Array.from(layerEditor.getMask()), beforeMask, active: layerEditor.getState().activeLayerId, beforeActive,
          events, openCalls: openCalls.map(call => ({ paths: call.paths, hasDocuments: !!(call.inspection && call.inspection.textureDocuments) })),
          inspectionCount: inspections.length }));
        assert.equal(result.state.error, "");
        assert(["restored", "ready"].includes(result.state.status), "Re-edit must finish in an editable successful state");
        assert.equal(result.project, result.before, "Re-edit restores the original authoring layers after the saved copy was flattened");
        assert.deepEqual(result.mask, result.beforeMask); assert.equal(result.active, result.beforeActive);
        assert.equal(result.openCalls.length, 2); assert.equal(result.openCalls[1].hasDocuments, true);
        assert.equal(result.inspectionCount, 2);
        assert.equal(result.events.filter(value => value === "documents").length, 1);
        cases.push("save → saved-copy review → re-edit restores immutable typed layer snapshots and selection");
      }
      assert.deepEqual(pageErrors, []); await page.close();
    }
    process.stdout.write(JSON.stringify({ status: "PASS", cases }) + "\n");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
