"use strict";
const assert = require("assert");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
global.THREE = T;
const material = require("../webtools/web/static/sifas-material.js");
const cases = [];
async function test(name, run) { await run(); cases.push(name); }
const identity = id => ({ source: 0, file: 0, id: String(id) });
function dataTexture(size, channel) {
  const bytes = new Uint8Array(size * size * 4);
  for (let i = 0; i < bytes.length; i += 4) bytes.set([channel, 90, 140, 128], i);
  const texture = new T.DataTexture(bytes, size, size, T.RGBAFormat);
  texture.encoding = T.sRGBEncoding; texture.flipY = false;
  texture.wrapS = T.RepeatWrapping; texture.wrapT = T.MirroredRepeatWrapping;
  texture.generateMipmaps = false;
  return texture;
}
function fixture(deferred = false) {
  const root = new T.Group(), textures = [dataTexture(4, 60), dataTexture(1, 220), dataTexture(2, 80), dataTexture(1, 100)];
  const original = new T.MeshBasicMaterial({ map: textures[0] });
  original.userData.sifas = { version: 1, shader: "AS/Member", colors: {}, floats: {},
    features: { rimlight: true, outline: true }, textures: {
      _MainTex: { index: 0, mipmaps: [0, 2, 3], filterMode: 2 }, _RimlightTex: { index: 1, filterMode: 1 }
    } };
  const geometry = new T.PlaneBufferGeometry(1, 1), mesh = new T.Mesh(geometry, original); root.add(mesh);
  const waiting = [];
  const parser = { json: { textures: textures.map((_, index) => ({ extras: { viewerTexture: identity(index === 0 ? 42 : index === 1 ? 43 : 100 + index) } })) },
    getDependency(kind, index) {
      assert.strictEqual(kind, "texture");
      return deferred ? new Promise(resolve => waiting.push(() => resolve(textures[index]))) : Promise.resolve(textures[index]);
    } };
  const controller = material.apply(root, { capabilities: { isWebGL2: true } }, { parser, enabled: true, rimlight: true });
  return { controller, root, mesh, original, textures, waiting, geometry,
    async ready() { if (deferred) { while (waiting.length) { waiting.splice(0).forEach(done => done()); await Promise.resolve(); await Promise.resolve(); } } await controller.ready; } };
}
function canvasTexture(channel = 250) {
  const image = { width: 4, height: 4, closeCalls: 0, close() { this.closeCalls++; } };
  const texture = new T.CanvasTexture(image);
  texture.encoding = T.sRGBEncoding; texture.flipY = true;
  let disposals = 0; texture.addEventListener("dispose", () => disposals++);
  return { texture, image, disposals: () => disposals };
}

(async () => {
  await test("main override uses Gamma/Linear sampling with regenerated mips and exact undo refs", async () => {
    const f = fixture(); await f.ready();
    const originalMain = f.mesh.material.uniforms.uMainTex.value, originalRim = f.mesh.material.uniforms.uRimlightTex.value;
    const owned = f.controller.getState().ownedTextures, external = canvasTexture();
    assert.strictEqual(f.controller.getOriginalMaterials(f.mesh), f.original);
    assert.strictEqual(originalMain.mipmaps.length, 3);
    f.controller.setTextureOverride(identity(42), external.texture);
    const replacement = f.mesh.material.uniforms.uMainTex.value;
    assert.notStrictEqual(replacement, external.texture); assert.strictEqual(replacement.image, external.image);
    assert.strictEqual(replacement.encoding, T.LinearEncoding); assert.strictEqual(replacement.generateMipmaps, true);
    assert.strictEqual(replacement.mipmaps.length, 0); assert.strictEqual(replacement.flipY, originalMain.flipY);
    assert.strictEqual(replacement.wrapS, originalMain.wrapS); assert.strictEqual(replacement.wrapT, originalMain.wrapT);
    assert.strictEqual(replacement.minFilter, originalMain.minFilter); assert.strictEqual(replacement.magFilter, originalMain.magFilter);
    assert.strictEqual(f.mesh.material.uniforms.uRimlightTex.value, originalRim);
    assert.strictEqual(f.original.map, f.textures[0]);
    assert.strictEqual(f.controller.getState().textureOverrides, 1); assert.strictEqual(f.controller.getState().ownedTextures, owned + 1);
    let disposals = 0; replacement.addEventListener("dispose", () => disposals++);
    f.controller.setTextureOverride(identity(42), null);
    assert.strictEqual(f.mesh.material.uniforms.uMainTex.value, originalMain); assert.strictEqual(f.mesh.material.uniforms.uRimlightTex.value, originalRim);
    assert.strictEqual(disposals, 1); assert.strictEqual(f.controller.getState().ownedTextures, owned);
    assert.strictEqual(external.disposals(), 0); assert.strictEqual(external.image.closeCalls, 0);
    f.controller.dispose(); assert.strictEqual(disposals, 1); f.geometry.dispose(); f.original.dispose();
  });

  await test("auxiliary map identities remain separate and rimlight preference is retained", async () => {
    const f = fixture(); await f.ready(); const external = canvasTexture();
    const main = f.mesh.material.uniforms.uMainTex.value, rim = f.mesh.material.uniforms.uRimlightTex.value;
    f.controller.setTextureOverride(identity(43), external.texture);
    assert.strictEqual(f.mesh.material.uniforms.uMainTex.value, main);
    assert.notStrictEqual(f.mesh.material.uniforms.uRimlightTex.value, rim);
    assert.strictEqual(f.controller.getState().rimlightEnabled, true);
    f.controller.setRimlight(false); f.controller.setTextureOverride(identity(43), null);
    assert.strictEqual(f.controller.getState().rimlightEnabled, false);
    assert.strictEqual(f.mesh.material.defines.SIFAS_RIMLIGHT, undefined);
    assert.strictEqual(f.mesh.material.uniforms.uRimlightTex.value, rim);
    f.controller.setTextureOverride({ source: 1, file: 0, id: "42" }, external.texture);
    assert.strictEqual(f.mesh.material.uniforms.uMainTex.value, main, "Same path ID in a different source must not match");
    f.controller.clearTextureOverrides(); assert.strictEqual(f.controller.getState().textureOverrides, 0);
    f.controller.setEnabled(false); assert.strictEqual(f.mesh.material, f.original);
    f.controller.setEnabled(true); assert.notStrictEqual(f.mesh.material, f.original);
    assert.strictEqual(f.controller.getOriginalMaterials(f.mesh), f.original);
    assert.strictEqual(external.disposals(), 0); f.controller.dispose(); f.geometry.dispose(); f.original.dispose();
  });

  await test("overrides queued before authored texture loading bind after ready and undo safely", async () => {
    const f = fixture(true), external = canvasTexture();
    f.controller.setTextureOverride(identity(42), external.texture);
    await f.ready();
    assert.strictEqual(f.mesh.material.uniforms.uMainTex.value.image, external.image);
    assert.strictEqual(f.mesh.material.uniforms.uMainTex.value.generateMipmaps, true);
    f.controller.setTextureOverride(identity(42), null);
    assert.strictEqual(f.mesh.material.uniforms.uMainTex.value.image, f.textures[0].image);
    assert.strictEqual(f.mesh.material.uniforms.uMainTex.value.mipmaps.length, 3);
    assert.strictEqual(external.disposals(), 0); f.controller.dispose(); f.geometry.dispose(); f.original.dispose();
  });

  await test("replaced and final owned GPU clones release once without disposing caller textures", async () => {
    const f = fixture(); await f.ready(); const first = canvasTexture(), second = canvasTexture();
    f.controller.setTextureOverride(identity(42), first.texture);
    const cloneA = f.mesh.material.uniforms.uMainTex.value; let disposedA = 0, disposedB = 0;
    cloneA.addEventListener("dispose", () => disposedA++);
    f.controller.setTextureOverride(identity(42), second.texture);
    const cloneB = f.mesh.material.uniforms.uMainTex.value; cloneB.addEventListener("dispose", () => disposedB++);
    assert.strictEqual(disposedA, 1); assert.strictEqual(disposedB, 0);
    f.controller.dispose(); f.controller.dispose();
    assert.strictEqual(disposedA, 1); assert.strictEqual(disposedB, 1);
    assert.strictEqual(first.disposals(), 0); assert.strictEqual(second.disposals(), 0);
    assert.strictEqual(first.image.closeCalls, 0); assert.strictEqual(second.image.closeCalls, 0);
    assert.strictEqual(f.mesh.material, f.original);
    assert.strictEqual(f.controller.getState().textureOverrides, 0, "Disposed controller must release its override image references");
    assert.strictEqual(f.controller.getState().ownedTextures, 0);
    f.geometry.dispose(); f.original.dispose();
  });

  await test("invalid preview identities and non-textures are refused", async () => {
    const f = fixture(); await f.ready();
    assert.throws(() => f.controller.setTextureOverride({ id: "42" }, canvasTexture().texture), /identity/);
    assert.throws(() => f.controller.setTextureOverride(identity(42), {}), /valid texture/);
    f.controller.dispose(); f.geometry.dispose(); f.original.dispose();
  });
  console.log(JSON.stringify({ status: "PASS", cases: cases.length, names: cases }));
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
