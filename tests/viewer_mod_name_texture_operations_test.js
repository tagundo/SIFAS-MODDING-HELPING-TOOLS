/* The automatic Mod name's texture part through the public persistence controller.
 *
 * The page is the product's index.html (without its scripts) and the real
 * viewer-persistence.js; the texture tools are a controlled fixture, so the
 * test names exactly what the name is built from. The texture tools' own
 * undo-aware bookkeeping is driven end to end by viewer_texture_name_kinds_browser.js.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const product = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(product, "webtools/web/index.html"), "utf8")
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "").replace(/<link\b[^>]*>/gi, "");
const KO = { "Costume colour": "의상 컬러", "Skin tone": "스킨톤", "Texture painting": "텍스쳐 페인팅", "Baked blush": "홍조 굽기" };

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true, args: ["--no-sandbox"] });
  const cases = [];
  try {
    const page = await browser.newPage(), pageErrors = [];
    page.on("pageerror", error => pageErrors.push(String(error)));
    await page.setContent(html);
    await page.addScriptTag({ path: path.join(product, "webtools/web/static/viewer-persistence.js") });
    await page.evaluate(ko => {
      const identity = id => ({ source: 0, file: 0, id: String(id) });
      // What the texture tools report: the saved rows (one kind each) and the
      // operations each texture carries now. The revision never moves here, so
      // only the operations themselves can change the name.
      window.fixture = { rows: [], operations: [], tools: true };
      window.context = { current: true, modelId: "original", loadedPaths: ["/models/ch0001_co0001.unity"],
        editing: { available: true, token: "texture-name-fixture", nodes: [], modPackaging: { nameBase: "ch0001_co0001" } },
        rig: { getAuthoringState: () => ({ version: 1, edits: [], savedSettingsEnabled: true, unsupported: [] }), getState: () => ({}), setAuthoringEnabled() {} },
        get textureTools() {
          const tools = { getEdits: () => fixture.rows.map(row => ({ texture: identity(row.id), sourceSha256: "a".repeat(64), png: "data:image/png;base64,", kind: row.kind, ...(row.blush ? { blush: { layer: 0, k: 1.65 } } : {}) })),
            hasPending: () => false, getRevision: () => 7 };
          if (fixture.tools) tools.getAppliedOperations = () => fixture.operations.map((operations, index) => ({ texture: identity(index + 1), operations: operations.slice() }));
          return tools;
        } };
      // Save and "Open saved result" against controlled answers: the saved copy has no edits of its own.
      window.fetch = async (url, options) => {
        if (url === "/api/viewer/edit/export") return { ok: true, json: async () => ({ job_id: "name-job" }) };
        if (url === "/api/viewer/edit/result/name-job") return { ok: true, json: async () => ({ output_paths: ["/saved/ch0001_co0001.unity", "/saved/recipe.json"],
          preview_paths: ["/saved/ch0001_co0001.unity"], original_paths: ["/originals/ch0001_co0001.unity"], recipe_path: "/saved/recipe.json", recipe: { state: {} } }) };
        throw new Error("Unexpected request " + url);
      };
      window.EventSource = class { constructor() { setTimeout(() => this.onmessage && this.onmessage({ data: JSON.stringify({ type: "done", status: "done" }) }), 0); } close() {} };
      window.persistence = ViewerPersistence.create({ translate: value => ko[value] || value, context: () => window.context, pickFile() {},
        openFiles: async paths => { context.loadedPaths = paths; context.modelId = "saved"; context.editing = Object.assign({}, context.editing, { token: "saved-copy" }); fixture.rows = []; fixture.operations = []; } });
      window.nameFor = (rows, operations, tools = true) => {
        fixture.rows = rows; fixture.operations = operations; fixture.tools = tools; persistence.refresh();
        return document.getElementById("viewer-mod-name").value;
      };
    }, KO);
    const name = (rows, operations, tools) => page.evaluate(args => nameFor(...args), [rows, operations, tools]);
    const head = { id: 14, kind: "paint", blush: true }, body = { id: 901, kind: "costume" };

    // Several operations on one texture are listed separately, once each across textures, in a fixed order.
    assert.equal(await name([head], [["skin", "paint"]]), "ch0001_co0001 · 스킨톤 · 텍스쳐 페인팅");
    assert.equal(await name([head, body], [["blush", "paint"], ["costume", "skin"]]), "ch0001_co0001 · 의상 컬러 · 스킨톤 · 홍조 굽기 · 텍스쳐 페인팅");
    assert.equal(await name([head, body], [["skin", "paint"], ["skin"]]), "ch0001_co0001 · 스킨톤 · 텍스쳐 페인팅");
    cases.push("each operation once, in the order costume colour, skin tone, baked blush, painting");
    // The same rows with other operations (an Undo, say) change the name.
    assert.equal(await name([head], [["skin"]]), "ch0001_co0001 · 스킨톤");
    assert.equal(await name([head], [["skin", "blush", "paint"]]), "ch0001_co0001 · 스킨톤 · 홍조 굽기 · 텍스쳐 페인팅");
    assert.equal(await name([], []), "ch0001_co0001");
    cases.push("the name follows the operations even when the saved rows and revision stay the same");
    // Without the texture tools' operations, each row names its one kind and its baked blush.
    assert.equal(await name([head, body], [], false), "ch0001_co0001 · 의상 컬러 · 홍조 굽기 · 텍스쳐 페인팅");
    assert.equal(await name([{ id: 14, kind: "blush", blush: true }], [], false), "ch0001_co0001 · 홍조 굽기");
    cases.push("rows alone keep their one kind and the blush");
    // A typed name is never replaced; Automatic brings the suggestion back.
    await page.evaluate(() => { const field = document.getElementById("viewer-mod-name"); field.value = "내 의상"; field.dispatchEvent(new Event("input", { bubbles: true })); });
    assert.equal(await name([head], [["costume", "skin", "paint"]]), "내 의상");
    await page.evaluate(() => { const auto = document.getElementById("viewer-mod-name-auto"); auto.disabled = false; auto.click(); });
    assert.equal(await page.evaluate(() => document.getElementById("viewer-mod-name").value), "ch0001_co0001 · 의상 컬러 · 스킨톤 · 텍스쳐 페인팅");
    cases.push("a typed name stays; Automatic returns the suggestion");
    // Saved, then the saved copy reviewed: a Mod ZIP from it is named after the edits it was saved with.
    await name([head, body], [["skin", "blush", "paint"], ["costume"]]);
    await page.evaluate(() => document.getElementById("viewer-save").click());
    await page.waitForFunction(() => !persistence.getState().busy && persistence.getState().status === "done");
    await page.evaluate(() => document.getElementById("viewer-open-saved").click());
    await page.waitForFunction(() => !persistence.getState().busy && persistence.getState().reviewingSaved);
    assert.equal(await page.evaluate(() => { persistence.refresh(); return document.getElementById("viewer-mod-name").value; }), "ch0001_co0001 · 의상 컬러 · 스킨톤 · 홍조 굽기 · 텍스쳐 페인팅");
    cases.push("the reviewed saved copy keeps the name of the edits it was saved with");
    assert.deepEqual(pageErrors, []); await page.close();
  } finally { await browser.close(); }
  process.stdout.write(JSON.stringify({ status: "PASS", cases }) + "\n");
})().catch(error => { console.error(error); process.exitCode = 1; });
