(function (global) {
  "use strict";

  // Unity's forward renderer draws each opaque render queue (2500 and below)
  // front to back by the distance from the camera to every renderer's bounds
  // centre. With ZTest LEqual a later fragment at the same depth replaces the
  // earlier one, so this order decides coplanar opaque surfaces, such as a
  // song effect's sky dome over the stage's own sky with the same vertices
  // (10120: the dome's bounds centre sits above the stage's, so the stage
  // draws first and the dome shows).
  //
  // Three.js sorts its opaque list by program and material before depth. The
  // stage renderers given an opaque sort source (MVStudioStageMaterial
  // opaqueSortEntries) keep the draw positions that order gives them and
  // fill them in the native order; every other mesh keeps its own position.
  function create(T, renderer) {
    if (!renderer.setOpaqueSort || !renderer.properties?.get) return null;
    const slots = new Map(), buckets = new Map(), entries = [];
    const viewProjection = new T.Matrix4(), frustum = new T.Frustum();
    const eye = new T.Vector3(), point = new T.Vector3();
    const f32 = Math.fround;

    // three.js r128 painterSortStable, with the participants' keys exchanged.
    function compare(a, b) {
      if (a.groupOrder !== b.groupOrder) return a.groupOrder - b.groupOrder;
      if (a.renderOrder !== b.renderOrder) return a.renderOrder - b.renderOrder;
      const x = slots.get(a.object), y = slots.get(b.object);
      const ap = x ? x.program : a.program.id, bp = y ? y.program : b.program.id;
      if (ap !== bp) return ap - bp;
      const am = x ? x.material : a.material.id, bm = y ? y.material : b.material.id;
      if (am !== bm) return am - bm;
      const az = x ? x.z : a.z, bz = y ? y.z : b.z;
      if (az !== bz) return az - bz;
      return (x ? x.id : a.id) - (y ? y.id : b.id);
    }

    // The renderOrder of the nearest visible Group, as WebGLRenderer.projectObject assigns it.
    function groupOrder(node, source, camera) {
      let order;
      for (let parent = node; parent; parent = parent.parent) {
        if (!parent.visible) return null;
        if (parent === source) return order ?? 0;
        if (order === undefined && parent.isGroup && parent.layers.test(camera.layers)) order = parent.renderOrder;
      }
      return null;
    }

    function collect(entry, source, camera) {
      const {node, material, center, queue} = entry;
      if (node.material !== material || material.transparent || !material.visible || !material.depthWrite ||
          !material.depthTest || material.depthFunc !== T.LessEqualDepth || !node.layers.test(camera.layers)) return;
      const group = groupOrder(node, source, camera);
      if (group === null) return;
      node.updateWorldMatrix(true, false);
      if (node.frustumCulled && !frustum.intersectsObject(node)) return;
      const z = point.setFromMatrixPosition(node.matrixWorld).applyMatrix4(viewProjection).z;
      if (!Number.isFinite(z)) return;
      point.copy(center).applyMatrix4(node.matrixWorld);
      let distance;
      if (camera.isOrthographicCamera) {
        distance = f32(-point.applyMatrix4(camera.matrixWorldInverse).z);
      } else {
        const dx = f32(f32(point.x) - eye.x), dy = f32(f32(point.y) - eye.y), dz = f32(f32(point.z) - eye.z);
        distance = f32(dz * dz + f32(dx * dx + f32(dy * dy)));
      }
      if (!Number.isFinite(distance)) return;
      const program = renderer.properties.get(material).program;
      const bucketKey = `${group}:${node.renderOrder}`;
      let bucket = buckets.get(bucketKey);
      if (!bucket) buckets.set(bucketKey, bucket = []);
      bucket.push({ node, queue, distance,
        key: { program: program ? program.id : -1, material: material.id, z, id: node.id } });
    }

    function byKey(a, b) {
      const x = a.key, y = b.key;
      return x.program - y.program || x.material - y.material || x.z - y.z || x.id - y.id;
    }

    // records: the scene records; each stage material record offers its entries.
    function begin(source, camera, records) {
      if (!camera.isPerspectiveCamera && !camera.isOrthographicCamera) return false;
      for (const {stageMaterial} of records) if (stageMaterial?.opaqueSortEntries) entries.push(...stageMaterial.opaqueSortEntries());
      if (entries.length < 2) {
        entries.length = 0;
        return false;
      }
      camera.updateWorldMatrix(true, false);
      viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
      frustum.setFromProjectionMatrix(viewProjection);
      eye.setFromMatrixPosition(camera.matrixWorld);
      eye.set(f32(eye.x), f32(eye.y), f32(eye.z));
      for (const entry of entries) collect(entry, source, camera);
      for (const bucket of buckets.values()) {
        if (bucket.length < 2) continue;
        // Lower queues first, then nearer bounds; equal distances (the
        // submeshes of one renderer) keep the editor's order.
        const native = bucket.slice().sort((a, b) => a.queue - b.queue || a.distance - b.distance || byKey(a, b));
        bucket.sort(byKey);
        for (let index = 0; index < bucket.length; index++) {
          if (native[index] !== bucket[index]) slots.set(native[index].node, bucket[index].key);
        }
      }
      entries.length = 0;
      buckets.clear();
      if (!slots.size) return false;
      renderer.setOpaqueSort(compare);
      return true;
    }

    function end() {
      renderer.setOpaqueSort(null);
      slots.clear();
    }

    return { begin, end, compare };
  }

  global.MVStudioOpaqueSort = { create };
})(typeof window !== "undefined" ? window : globalThis);
