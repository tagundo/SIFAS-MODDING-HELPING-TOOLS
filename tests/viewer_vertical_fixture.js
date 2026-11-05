/* Original generated humanoid geometry, attached to the existing synthetic
 * skin/morph/animation metadata. No game model, texture or account data. */
const { fixture } = require('./viewer_rig_browser');

function humanoidFixture(options = {}) {
  const generated = fixture({ allSaved: true, semanticExpressions: true,
    previewName: 'Original humanoid preview', previewVerified: true,
    shifted: !!options.shifted });
  const jsonLength = generated.glb.readUInt32LE(12);
  const document = JSON.parse(generated.glb.subarray(20, 20 + jsonLength));
  const oldBinary = generated.glb.subarray(28 + jsonLength);
  const chunks = [oldBinary]; let length = oldBinary.length;
  const pos = [], normal = [], indices = [], joints = [], weights = [], morphA = [], morphB = [];
  const sourceOffset = options.shifted ? 50 : 0;
  function vertex(point, n, joint) {
    pos.push(point[0] + sourceOffset, point[1], point[2]); normal.push(...n);
    joints.push(joint, 0, 0, 0); weights.push(1, 0, 0, 0);
    // A real authored morph changes the upper silhouette, not just metadata.
    morphA.push(point[1] > 1.45 ? .16 : 0, 0, 0);
    morphB.push(0, point[1] > 1.45 ? .1 : 0, 0);
  }
  function sphere(center, scale, joint) {
    const start = pos.length / 3, lat = 8, lon = 12;
    for (let y = 0; y <= lat; y++) for (let x = 0; x <= lon; x++) {
      const a = Math.PI * y / lat, b = Math.PI * 2 * x / lon;
      const n = [Math.sin(a) * Math.cos(b), Math.cos(a), Math.sin(a) * Math.sin(b)];
      vertex(n.map((v, i) => center[i] + v * scale[i]), n, joint);
    }
    for (let y = 0; y < lat; y++) for (let x = 0; x < lon; x++) {
      const a = start + y * (lon + 1) + x;
      indices.push(a, a + lon + 1, a + 1, a + 1, a + lon + 1, a + lon + 2);
    }
  }
  function cylinder(a, b, ra, rb, joint) {
    const start = pos.length / 3, segments = 12;
    let axis = b.map((v, i) => v - a[i]); const norm = Math.hypot(...axis); axis = axis.map(v => v / norm);
    let u = [axis[1], -axis[0], 0]; const ul = Math.hypot(...u); u = u.map(v => v / ul);
    const v = [axis[1] * u[2] - axis[2] * u[1], axis[2] * u[0] - axis[0] * u[2], axis[0] * u[1] - axis[1] * u[0]];
    for (const [center, radius] of [[a, ra], [b, rb]]) for (let i = 0; i <= segments; i++) {
      const angle = Math.PI * 2 * i / segments, n = u.map((value, k) => value * Math.cos(angle) + v[k] * Math.sin(angle));
      vertex(n.map((value, k) => center[k] + radius * value), n, joint);
    }
    for (let i = 0; i < segments; i++) indices.push(start + i, start + i + 1, start + i + segments + 1,
      start + i + 1, start + i + segments + 2, start + i + segments + 1);
  }
  function body(x) {
    const p = (xx, y, z = 0) => [x + xx, y, z];
    sphere(p(0, 1.58), [.12, .15, .11], 1);
    cylinder(p(0, .82), p(0, 1.34), .14, .21, 1);
    cylinder(p(0, .58), p(0, .86), .27, .14, 0);
    for (const sign of [-1, 1]) {
      const elbow = options.wide ? .55 : .31, hand = options.wide ? .77 : .36;
      cylinder(p(sign * .19, 1.28), p(sign * elbow, options.wide ? 1.33 : 1.02), .06, .045, 1);
      cylinder(p(sign * elbow, options.wide ? 1.33 : 1.02), p(sign * hand, options.wide ? 1.38 : .76, .02), .042, .032, 1);
      sphere(p(sign * hand, options.wide ? 1.38 : .72, .02), [.041, .06, .035], 1);
      cylinder(p(sign * .105, .63), p(sign * .11, .33), .065, .045, 0);
      cylinder(p(sign * .11, .33), p(sign * .11, .085), .045, .028, 0);
      sphere(p(sign * .11, .05, .05), [.052, .045, .11], 0);
    }
  }
  if (options.twoModels) { body(-.55); body(.55); } else body(0);
  function attribute(values, Type, type, componentType, width) {
    const padding = (4 - length % 4) % 4; if (padding) { chunks.push(Buffer.alloc(padding)); length += padding; }
    const raw = Buffer.from(new Type(values).buffer), view = document.bufferViews.length;
    document.bufferViews.push({ buffer: 0, byteOffset: length, byteLength: raw.length }); chunks.push(raw); length += raw.length;
    const result = { bufferView: view, componentType, count: values.length / width, type };
    if (type === 'VEC3') {
      result.min = [0, 1, 2].map(k => Math.min(...values.filter((v, i) => i % 3 === k)));
      result.max = [0, 1, 2].map(k => Math.max(...values.filter((v, i) => i % 3 === k)));
    }
    document.accessors.push(result); return document.accessors.length - 1;
  }
  function primitiveFor(start, count, selectedIndices) {
    return { material: 0, attributes: {
      POSITION: attribute(pos.slice(start * 3, (start + count) * 3), Float32Array, 'VEC3', 5126, 3),
      NORMAL: attribute(normal.slice(start * 3, (start + count) * 3), Float32Array, 'VEC3', 5126, 3),
      JOINTS_0: attribute(joints.slice(start * 4, (start + count) * 4), Uint16Array, 'VEC4', 5123, 4),
      WEIGHTS_0: attribute(weights.slice(start * 4, (start + count) * 4), Float32Array, 'VEC4', 5126, 4)
    }, indices: attribute(selectedIndices.map(index => index - start), Uint16Array, 'SCALAR', 5123, 1),
    targets: [{ POSITION: attribute(morphA.slice(start * 3, (start + count) * 3), Float32Array, 'VEC3', 5126, 3) },
      { POSITION: attribute(morphB.slice(start * 3, (start + count) * 3), Float32Array, 'VEC3', 5126, 3) }] };
  }
  if (options.twoModels) {
    const count = pos.length / 6, halfIndices = indices.length / 2;
    document.meshes[0].primitives = [primitiveFor(0, count, indices.slice(0, halfIndices))];
    document.meshes.push({ ...document.meshes[0], name: 'Independent generated second humanoid',
      primitives: [primitiveFor(count, count, indices.slice(halfIndices))] });
    const node = document.nodes.length;
    document.nodes.push({ name: 'Independent generated second humanoid', mesh: 1, skin: 0,
      extras: { elichika_node: node, role: 'mesh' } });
    document.nodes[0].children.push(node);
  } else document.meshes[0].primitives = [primitiveFor(0, pos.length / 3, indices)];
  const binary = Buffer.concat(chunks); document.buffers[0].byteLength = binary.length;
  const json = Buffer.from(JSON.stringify(document));
  const jsonPadded = Buffer.concat([json, Buffer.alloc((4 - json.length % 4) % 4, 32)]);
  const binPadded = Buffer.concat([binary, Buffer.alloc((4 - binary.length % 4) % 4)]);
  const header = Buffer.alloc(12), jh = Buffer.alloc(8), bh = Buffer.alloc(8);
  header.writeUInt32LE(0x46546c67, 0); header.writeUInt32LE(2, 4); header.writeUInt32LE(28 + jsonPadded.length + binPadded.length, 8);
  jh.writeUInt32LE(jsonPadded.length); jh.writeUInt32LE(0x4e4f534a, 4); bh.writeUInt32LE(binPadded.length); bh.writeUInt32LE(0x004e4942, 4);
  generated.glb = Buffer.concat([header, jh, jsonPadded, bh, binPadded]);
  generated.stats = { meshes: options.twoModels ? 2 : 1, vertices: pos.length / 3, triangles: indices.length / 3, textures: 0, materials: 1 };
  generated.rig.bounds = { min: [-1.5, 0, -.3], max: [1.5, 1.8, .3] };
  return generated;
}

module.exports = { humanoidFixture };
