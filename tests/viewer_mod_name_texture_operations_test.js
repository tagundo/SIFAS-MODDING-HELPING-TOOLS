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
        rig: { getAuthoringState: () => ({ version: 1, edits: [], savedSettingsEnabled: true, unsupported: [] }), getState: () => ({}), setAuthoringEnabled() {}, setEvaluationMode() {}, restoreAuthoringState() {} },
        get textureTools() {
          const tools = { getEdits: () => fixture.rows.map(row => ({ texture: identity(row.id), sourceSha256: "a".repeat(64), png: "data:image/png;base64,", kind: row.kind, ...(row.blush ? { blush: { layer: 0, k: 1.65 } } : {}), ...(row.operations ? { operations: row.operations } : {}) })),
            hasPending: () => false, getRevision: () => 7 };
          if (fixture.tools) tools.getAppliedOperations = () => fixture.operations.map((operations, index) => ({ texture: identity(index + 1), operations: operations.slice() }));
          return tools;
        } };
      // Save and "Open saved result" against controlled answers: the saved copy has no edits of its own.
      window.fetch = async (url, options) => {
        if (url === "/api/viewer/edit/export") return { ok: true, json: async () => ({ job_id: "name-job" }) };
        if (url === "/api/viewer/edit/result/name-job") return { ok: true, json: async () => ({ output_paths: ["/saved/ch0001_co0001.unity", "/saved/recipe.json"],
          preview_paths: ["/saved/ch0001_co0001.unity"], original_paths: ["/originals/ch0001_co0001.unity"], recipe_path: "/saved/recipe.json", recipe: { state: {} } }) };
        if (url === "/api/viewer/edit/restore") return { ok: true, json: async () => ({ state: { version: 1, edits: [], savedSettingsEnabled: true } }) };
        throw new Error("Unexpected request " + url);
      };
      window.EventSource = class { constructor() { setTimeout(() => this.onmessage && this.onmessage({ data: JSON.stringify({ type: "done", status: "done" }) }), 0); } close() {} };
      window.persistence = ViewerPersistence.create({ translate: value => ko[value] || value, context: () => window.context, pickFile() {},
        openFiles: async paths => { context.loadedPaths = paths; context.modelId = paths[0]; context.editing = Object.assign({}, context.editing, { token: paths[0] }); fixture.rows = []; fixture.operations = []; persistence.refresh(); } });
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
    // Without the texture tools' operations, each row names its saved operations
    // (an older row its one kind) and its baked blush.
    assert.equal(await name([head, body], [], false), "ch0001_co0001 · 의상 컬러 · 홍조 굽기 · 텍스쳐 페인팅");
    assert.equal(await name([{ id: 14, kind: "blush", blush: true }], [], false), "ch0001_co0001 · 홍조 굽기");
    assert.equal(await name([{ id: 14, kind: "paint", blush: true, operations: ["skin"] }, body], [], false), "ch0001_co0001 · 의상 컬러 · 스킨톤 · 홍조 굽기");
    cases.push("rows alone keep their saved operations, else their one kind, and the blush");
    // The field shows the whole name as its tooltip too (it is wider than the field).
    assert.equal(await page.evaluate(() => document.getElementById("viewer-mod-name").title), "ch0001_co0001 · 의상 컬러 · 스킨톤 · 홍조 굽기");
    // At most 120 characters: whole labels only, never a dangling separator.
    const long = "ch0001_co0001_a_rather_long_costume_file_name_typed_by_a_modder_for_the_name_truncation_check_x";
    await page.evaluate(base => { context.editing.modPackaging.nameBase = base; }, long);
    const cut = await name([head, body], [["blush", "paint"], ["costume", "skin"]]);
    assert.equal(cut, long + " · 의상 컬러 · 스킨톤 · 홍조 굽기"); assert(cut.length <= 120 && (cut + " · 텍스쳐 페인팅").length > 120, cut.length);
    await page.evaluate(base => { context.editing.modPackaging.nameBase = base; }, "x".repeat(130));
    assert.equal(await name([head], [["skin"]]), "x".repeat(120));
    await page.evaluate(() => { context.editing.modPackaging.nameBase = "ch0001_co0001"; });
    cases.push("a long name keeps whole labels within 120 characters");
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
    // A typed name stays when the saved copy is reviewed and when its original is opened again.
    await page.evaluate(() => { const field = document.getElementById("viewer-mod-name"); field.value = "내 의상 모드"; field.dispatchEvent(new Event("input", { bubbles: true })); });
    await page.evaluate(() => document.getElementById("viewer-reedit-original").click());
    await page.waitForFunction(() => !persistence.getState().busy && persistence.getState().status === "restored");
    assert.equal(await page.evaluate(() => document.getElementById("viewer-mod-name").value), "내 의상 모드");
    assert.equal(await page.evaluate(() => document.getElementById("viewer-mod-name-auto").disabled), false, "Automatic stays offered");
    await page.evaluate(() => document.getElementById("viewer-open-saved").click());
    await page.waitForFunction(() => !persistence.getState().busy && persistence.getState().reviewingSaved);
    assert.equal(await page.evaluate(() => { persistence.refresh(); return document.getElementById("viewer-mod-name").value; }), "내 의상 모드");
    // Opening another model starts with the suggestion again.
    await page.evaluate(() => { context.loadedPaths = ["/models/other.unity"]; context.modelId = "other"; persistence.refresh(); });
    assert.equal(await page.evaluate(() => document.getElementById("viewer-mod-name").value), "ch0001_co0001");
    assert.equal(await page.evaluate(() => document.getElementById("viewer-mod-name-auto").disabled), true, "the suggestion is shown");
    cases.push("a typed name stays through reviewing the saved copy and re-editing its original, not onto another model");
    // With the product's CSS in a side-panel-wide column the field shows the whole
    // multi-label name (it wraps and grows) instead of hiding its end.
    await page.addStyleTag({ path: path.join(product, "webtools/web/static/style.css") });
    await page.evaluate(() => { const column = document.createElement("div"); column.id = "name-column"; column.style.cssText = "width:270px;font-size:14px"; document.body.prepend(column); column.appendChild(document.querySelector(".viewer-mod-form")); });
    const full = await name([head, body], [["blush", "paint"], ["costume", "skin"]]);
    assert.equal(full, "ch0001_co0001 · 의상 컬러 · 스킨톤 · 홍조 굽기 · 텍스쳐 페인팅");
    const shown = await page.evaluate(() => { const field = document.getElementById("viewer-mod-name"), auto = document.getElementById("viewer-mod-name-auto"), f = field.getBoundingClientRect(), a = auto.getBoundingClientRect();
      return { tag: field.tagName, width: f.width, scroll: field.scrollHeight, client: field.clientHeight, lineHeight: parseFloat(getComputedStyle(field).lineHeight), autoBelow: a.top >= f.bottom - 0.5, disabled: field.disabled }; });
    assert.equal(shown.tag, "TEXTAREA");
    assert(shown.width >= 268, "the name takes the whole row: " + shown.width);
    assert(shown.scroll <= shown.client + 1, "no part of the name is hidden: " + JSON.stringify(shown));
    assert(shown.client >= 2 * shown.lineHeight, "the long name wraps onto a second line: " + JSON.stringify(shown));
    assert(shown.autoBelow, "Automatic name sits below the field");
    cases.push("the whole multi-label name is visible in a 270 px column");
    // One line in the ZIP and the game: Enter adds nothing, a pasted line break becomes a space.
    assert.equal(shown.disabled, false, "the field is editable while authoring");
    await page.focus("#viewer-mod-name"); await page.keyboard.press("End"); await page.keyboard.press("Enter");
    assert.equal(await page.evaluate(() => document.getElementById("viewer-mod-name").value), full, "Enter inserts no line break");
    await page.evaluate(() => { const field = document.getElementById("viewer-mod-name"); field.value = "내\n의상\r\n모드"; field.setSelectionRange(3, 3); field.dispatchEvent(new Event("input", { bubbles: true })); });
    assert.deepEqual(await page.evaluate(() => { const field = document.getElementById("viewer-mod-name"); return [field.value, field.selectionStart]; }), ["내 의상 모드", 3]); // a textarea stores \r\n as \n
    cases.push("the name stays on one line: Enter is ignored and pasted line breaks become spaces");
    assert.deepEqual(pageErrors, []); await page.close();
  } finally { await browser.close(); }
  process.stdout.write(JSON.stringify({ status: "PASS", cases }) + "\n");
})().catch(error => { console.error(error); process.exitCode = 1; });
