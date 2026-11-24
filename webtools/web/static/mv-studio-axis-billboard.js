(function (global) {
  "use strict";

  // Unity Transform.rotation: the product of the local rotations, independent of parent scale.
  function worldRotation(object, target) {
    target.identity();
    for (let node = object; node; node = node.parent) target.premultiply(node.quaternion);
    return target;
  }

  // LLAS AxisBillboard.RunAxisBillboardY: right = normalize(up x toCamera),
  // forward = normalize(right x up), rotation = matrix columns (right, up, forward).
  // In the X-mirrored preview both cross products change sign, so the same
  // formula yields the mirrored Unity rotation without a correction.
  function axisRotation(up, direction, target, scratch) {
    const { right, forward, basis } = scratch;
    right.crossVectors(up, direction);
    if (!(right.lengthSq() > 1e-12)) return false;
    right.normalize();
    forward.crossVectors(right, up).normalize();
    target.setFromRotationMatrix(basis.makeBasis(right, up, forward));
    return true;
  }

  function scratch(T) {
    return { right: new T.Vector3(), forward: new T.Vector3(), basis: new T.Matrix4() };
  }

  function shown(node) {
    for (let current = node; current; current = current.parent) if (!current.visible) return false;
    return true;
  }

  // Nodes tagged by the exporter are the AxisBillboard transforms listed in
  // LiveCoreStageEffect.axisBillboards. Their local rotation is never
  // animated, and the billboard keeps the up axis, so each draw derives it
  // from the parent's current world rotation and the authored local rotation.
  function create(T, root) {
    const entries = [];
    root?.traverse?.(node => {
      if (node.userData?.mvAxisBillboard !== 1 || !node.parent) return;
      entries.push({ node, rest: node.quaternion.clone() });
      // AxisBillboard.Start enlarges the mesh bounds to cover every turn.
      node.traverse(child => { if (child.isMesh) child.frustumCulled = false; });
    });
    if (!entries.length) return null;
    const work = scratch(T);
    const up = new T.Vector3(), position = new T.Vector3(), eye = new T.Vector3(), direction = new T.Vector3();
    const parentRotation = new T.Quaternion(), rotation = new T.Quaternion();

    function apply(camera) {
      if (!camera?.isObject3D) return;
      camera.updateWorldMatrix(true, false);
      eye.setFromMatrixPosition(camera.matrixWorld);
      for (const { node, rest } of entries) {
        if (!shown(node)) continue;
        const parent = node.parent;
        worldRotation(parent, parentRotation);
        up.set(0, 1, 0).applyQuaternion(rotation.multiplyQuaternions(parentRotation, rest)).normalize();
        parent.updateWorldMatrix(true, false);
        position.copy(node.position).applyMatrix4(parent.matrixWorld);
        if (axisRotation(up, direction.subVectors(eye, position), rotation, work)) {
          // Transform.rotation = R sets the local rotation parent^-1 * R.
          node.quaternion.copy(parentRotation.invert()).multiply(rotation);
        } else {
          node.quaternion.copy(rest);
        }
        node.updateMatrix();
      }
    }

    // Read-only: the local rotation apply() would give each shown billboard for an eye
    // position, from its authored rest rotation (no node, matrix or camera is written).
    function preview(eyePosition) {
      const result = new Map();
      const up = new T.Vector3(), position = new T.Vector3(), direction = new T.Vector3();
      const parentRotation = new T.Quaternion(), rotation = new T.Quaternion(), local = scratch(T);
      for (const { node, rest } of entries) {
        if (!shown(node)) continue;
        const parent = node.parent;
        worldRotation(parent, parentRotation);
        up.set(0, 1, 0).applyQuaternion(rotation.multiplyQuaternions(parentRotation, rest)).normalize();
        position.copy(node.position).applyMatrix4(parent.matrixWorld);
        result.set(node, axisRotation(up, direction.subVectors(eyePosition, position), rotation, local)
          ? parentRotation.clone().invert().multiply(rotation) : rest.clone());
      }
      return result;
    }

    function reset() {
      for (const { node, rest } of entries) {
        node.quaternion.copy(rest);
        node.updateMatrix();
      }
    }

    return { nodes: entries.map(entry => entry.node), apply, preview, reset, dispose: reset };
  }

  global.MVStudioAxisBillboard = { create, axisRotation, worldRotation, scratch };
})(typeof window !== "undefined" ? window : globalThis);
