"use strict";

const assert = require("node:assert/strict");
const T = require("../webtools/web/static/vendor/three-r128/three.min.js");
require("../webtools/web/static/mv-studio-stage-motion.js");
require("../webtools/web/static/mv-studio-title.js");
require("../webtools/web/static/mv-studio-stage-particles.js");
require("../webtools/web/static/mv-studio-center-stars.js");

function mip(size) {
  const header = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(header);
  header.writeUInt32BE(13, 8);
  header.write("IHDR", 12);
  header.writeUInt32BE(size, 16);
  header.writeUInt32BE(size, 20);
  return {png: header.toString("base64"), width: size, height: size};
}

function near(actual, expected) {
  assert.ok(Math.abs(actual - expected) < 4e-7, `expected ${expected}, received ${actual}`);
}

async function run() {
  const root = new T.Scene();
  const texture = Array.from({length: 10}, (_, index) => mip(512 >> index));
  // Compact paired stock values for fx_dis_so2056_09/stars_center. The
  // expected rolls and sizes below were sampled from Unity's ARM64 routines.
  const descriptor = {
    seed: 3710075818, size: 2, lifetime: 1, rate: 2, cycle: 5,
    rollRange: [-6.283185005187988, 6.283185005187988],
    position: [0, 3.049999952316284, -7], uv: [.25, .25, 0, .25], maxViewportWidth: .5,
    palette: {
      rgb: [[16384, 255, 255, 255], [32768, 179, 204, 255], [49151, 255, 185, 179],
        [55705, 128, 170, 255], [65535, 179, 255, 216]],
      alpha: [[0, 255], [65535, 255]],
    },
    colorKeys: [[0, 255, 255, 255, 0], [.10000763088464737, 255, 255, 255, 255],
      [.9000076055526733, 255, 255, 255, 255], [1, 255, 255, 255, 0]],
    sizeCurve: ["cubic", [[0, [230.27524708881245, -23.027524679489083, -2.5, 1]],
      [.10000000149011612, [-269.72472310886616, 53.944945798144566, -.19724738597869873, .75]],
      [.20000000298023224, [0, 0, 0, 1]]]],
    sizePeriod: .20000000298023224,
    texture,
  };
  const loaded = [], disposed = [];
  const local = {...T, TextureLoader: class {
    async loadAsync(url) {
      const level = texture[loaded.length];
      assert.equal(url, "data:image/png;base64," + level.png);
      const value = new T.Texture({width: level.width, height: level.height});
      value.addEventListener("dispose", () => disposed.push(level.width));
      loaded.push(value);
      return value;
    }
  }};
  assert.equal(await MVStudioCenterStars.apply(local, root, {...descriptor, texture: texture.slice(0, -1)}), null);
  assert.equal(await MVStudioCenterStars.apply(local, root, {...descriptor, uv: [.25, .25, 0, .5]}), null);
  assert.equal(loaded.length, 0);
  assert.equal(root.children.length, 0);

  const stars = await MVStudioCenterStars.apply(local, root, descriptor);
  assert.ok(stars);
  assert.equal(root.children.length, 1);
  const [mesh] = root.children;
  const {geometry, material} = mesh;
  assert.equal(mesh.visible, false);
  assert.deepEqual(mesh.position.toArray(), descriptor.position);
  assert.ok(geometry.isInstancedBufferGeometry);
  assert.equal(geometry.groups.length, 0, "all live stars share one indexed draw");
  assert.deepEqual([...geometry.index.array], [0, 2, 1, 0, 3, 2]);
  assert.deepEqual([...geometry.getAttribute("uv").array], [0, .25, .25, .25, .25, .5, 0, .5]);
  const shapes = geometry.getAttribute("rollAndSize"), colors = geometry.getAttribute("starColor");
  assert.ok(shapes.isInstancedBufferAttribute && colors.isInstancedBufferAttribute);
  assert.equal(shapes.count, 4);
  assert.equal(colors.count, 4);
  assert.equal(material.transparent, true);
  assert.equal(material.depthFunc, T.LessEqualDepth);
  assert.equal(material.depthWrite, false);
  assert.equal(material.blending, T.CustomBlending);
  assert.equal(material.blendSrc, T.SrcAlphaFactor);
  assert.equal(material.blendDst, T.OneFactor);
  assert.equal(material.stencilWrite, true);
  assert.equal(material.stencilFunc, T.EqualStencilFunc);
  assert.equal(material.stencilRef, 2);
  assert.deepEqual([material.stencilFail, material.stencilZFail, material.stencilZPass], Array(3).fill(T.KeepStencilOp));
  assert.equal(material.uniforms.uMaxViewportWidth.value, .5);
  assert.equal(material.uniforms.uTexture.value, loaded[0]);
  assert.equal(loaded[0].generateMipmaps, false);
  assert.equal(loaded[0].minFilter, T.LinearMipmapNearestFilter);
  assert.equal(loaded[0].flipY, false);
  const levelSizes = texture.map(level => level.width);
  assert.deepEqual(loaded[0].mipmaps.map(image => image.width), levelSizes);
  assert.deepEqual(disposed, levelSizes.slice(1));

  function sample(time, count) {
    stars.update(time);
    assert.equal(mesh.visible, count > 0, `visibility at cue age ${time}`);
    assert.equal(geometry.instanceCount, count, `instance count at cue age ${time}`);
  }

  function checkParticle(index, roll, rgba) {
    near(shapes.getX(index), Math.cos(roll));
    near(shapes.getY(index), Math.sin(roll));
    const observed = Array.from(colors.array.subarray(index * 4, index * 4 + 4), value => Math.round(value * 255));
    assert.deepEqual(observed, rgba);
  }

  sample(0, 0); // The initial burst starts with zero alpha.
  sample(.05, 1);
  checkParticle(0, 4.593316078186035, [179, 255, 216, 127]);
  near(shapes.getZ(0), 1.6924312114715576);
  sample(.15, 1);
  checkParticle(0, 4.593316078186035, [179, 255, 216, 255]);
  near(shapes.getZ(0), 1.6825687885284424);
  sample(.25, 1);
  near(shapes.getZ(0), 1.6924312114715576);
  sample(.35, 1);
  near(shapes.getZ(0), 1.6825686693191528);
  sample(.5, 1);
  near(shapes.getZ(0), 1.5);
  sample(.55, 2);
  checkParticle(0, 6.263189315795898, [179, 204, 255, 127]);
  checkParticle(1, 4.593316078186035, [179, 255, 216, 255]);
  sample(.95, 2);
  checkParticle(1, 4.593316078186035, [179, 255, 216, 128]);
  sample(1, 1); // The initial burst is gone at exactly one lifetime.

  sample(5, 1);
  checkParticle(0, 5.986086845397949, [255, 255, 255, 255]);
  sample(5.05, 3);
  // The renderer visits newest particles first. The t=5 continuous emission
  // consumes its native draw before the t=5 burst consumes the next draw.
  checkParticle(0, -2.5738635063171387, [255, 255, 255, 127]);
  checkParticle(1, 5.556103706359863, [255, 185, 179, 127]);
  checkParticle(2, 5.986086845397949, [255, 255, 255, 255]);
  near(shapes.getZ(0), 1.6924312114715576);
  near(shapes.getZ(1), 1.6924312114715576);
  near(shapes.getZ(2), 1.6825687885284424);

  const shapeBytes = [...shapes.array], colorBytes = [...colors.array];
  stars.update(null); // The parent disables the effect outside its display cue.
  assert.equal(mesh.visible, false);
  sample(.05, 1);
  checkParticle(0, 4.593316078186035, [179, 255, 216, 127]);
  sample(5.05, 3);
  assert.deepEqual([...shapes.array], shapeBytes);
  assert.deepEqual([...colors.array], colorBytes);
  assert.equal(root.children.length, 1);

  let materials = 0, geometries = 0;
  material.addEventListener("dispose", () => materials++);
  geometry.addEventListener("dispose", () => geometries++);
  stars.dispose();
  stars.dispose();
  stars.update(5.05);
  assert.equal(materials, 1);
  assert.equal(geometries, 1);
  assert.equal(root.children.length, 0);
  assert.deepEqual(disposed, [...levelSizes.slice(1), 512]);
  console.log("Native center stars: fixed-seed emission, palette, wrapped size, instancing, mask, mips, and cleanup.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
