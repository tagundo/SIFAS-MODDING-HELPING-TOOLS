(function (global) {
  "use strict";

  function create(T, renderer) {
    if (!renderer.setTransparentSort) return null;
    const slots = new Map(), buckets = new Map(), entries = [];
    const viewProjection = new T.Matrix4(), frustum = new T.Frustum();
    const eye = new T.Vector3(), point = new T.Vector3();
    const f32 = Math.fround;

    function compare(a, b) {
      if (a.groupOrder !== b.groupOrder) return a.groupOrder - b.groupOrder;
      if (a.renderOrder !== b.renderOrder) return a.renderOrder - b.renderOrder;
      const aSlot = slots.get(a.object) || a, bSlot = slots.get(b.object) || b;
      if (aSlot.z !== bSlot.z) return bSlot.z - aSlot.z;
      return aSlot.id - bSlot.id;
    }

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
      const {node, anchor, center, queue} = entry;
      if (node.renderOrder !== queue || !node.material?.transparent || !node.material.visible ||
          !node.layers.test(camera.layers)) return;
      const group = groupOrder(node, source, camera);
      if (group === null) return;
      node.updateWorldMatrix(true, false);
      if (node.frustumCulled && !frustum.intersectsObject(node)) return;
      const projectedDepth = point.setFromMatrixPosition(node.matrixWorld).applyMatrix4(viewProjection).z;
      if (!Number.isFinite(projectedDepth)) return;

      if (anchor !== node) anchor.updateWorldMatrix(true, false);
      point.copy(center).applyMatrix4(anchor.matrixWorld);
      let distance;
      if (camera.isOrthographicCamera) {
        distance = f32(-point.applyMatrix4(camera.matrixWorldInverse).z);
      } else {
        const dx = f32(f32(point.x) - eye.x), dy = f32(f32(point.y) - eye.y), dz = f32(f32(point.z) - eye.z);
        distance = f32(dz * dz + f32(dx * dx + f32(dy * dy)));
      }
      if (!Number.isFinite(distance)) return;
      const key = `${group}:${queue}`;
      let bucket = buckets.get(key);
      if (!bucket) buckets.set(key, bucket = []);
      bucket.push({node, z: projectedDepth, id: node.id, distance});
    }

    function prepare(source, camera, records) {
      if (!camera.isPerspectiveCamera && !camera.isOrthographicCamera) return false;
      for (const {stageSoftBillboards, stageOverlay} of records) {
        if (stageSoftBillboards) entries.push(...stageSoftBillboards.sortEntries());
        if (stageOverlay) entries.push(...stageOverlay.sortEntries());
      }
      if (entries.length < 2) return false;
      camera.updateWorldMatrix(true, false);
      viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
      frustum.setFromProjectionMatrix(viewProjection);
      eye.setFromMatrixPosition(camera.matrixWorld);
      eye.set(f32(eye.x), f32(eye.y), f32(eye.z));
      for (const entry of entries) collect(entry, source, camera);
      for (const bucket of buckets.values()) {
        if (bucket.length < 2) continue;
        // Reuse these meshes' default draw positions within each queue. Other
        // transparent renderers keep their positions in the same draw list.
        const nativeOrder = bucket.slice().sort((a, b) => b.distance - a.distance);
        bucket.sort((a, b) => b.z - a.z || a.id - b.id);
        for (let index = 0; index < bucket.length; index++) {
          if (nativeOrder[index] !== bucket[index]) slots.set(nativeOrder[index].node, bucket[index]);
        }
      }
      return slots.size > 0;
    }

    return { draw(source, camera, records) {
      let sorting = false;
      try {
        sorting = prepare(source, camera, records);
        if (sorting) renderer.setTransparentSort(compare);
        renderer.render(source, camera);
      } finally {
        if (sorting) renderer.setTransparentSort(null);
        slots.clear();
        buckets.clear();
        entries.length = 0;
      }
    } };
  }

  global.MVStudioTransparentSort = {create};
})(window);
