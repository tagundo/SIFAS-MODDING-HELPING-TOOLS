(function (global) {
  "use strict";

  // LLAS.Scene.Live.Components.LiveCoreLossyScale.LateUpdate (GL 3.12.0,
  // 0x2f63fa0): localScale = localScale / lossyScale + offsetScale, after the
  // animators. lossyScale is localScale times the parent's lossy scale P, so
  // the local scale becomes 1 / P + offsetScale each frame whatever the clip
  // wrote. The exporter tags the retained nodes with mvLossyScaleOffset.
  function create(T, root) {
    const entries = [];
    root?.traverse?.(node => {
      const offset = node.userData?.mvLossyScaleOffset;
      if (!node.parent || !Array.isArray(offset) || offset.length !== 3 || !offset.every(Number.isFinite)) return;
      entries.push({node, offset: new T.Vector3().fromArray(offset), rest: node.scale.clone()});
    });
    if (!entries.length) return null;
    const parentScale = new T.Vector3(), position = new T.Vector3(), rotation = new T.Quaternion();
    const f32 = Math.fround;

    function apply() {
      for (const {node, offset} of entries) {
        node.parent.updateWorldMatrix(true, false);
        node.parent.matrixWorld.decompose(position, rotation, parentScale);
        if (![parentScale.x, parentScale.y, parentScale.z].every(value => Number.isFinite(value) && value !== 0)) continue;
        node.scale.set(f32(f32(1 / parentScale.x) + offset.x), f32(f32(1 / parentScale.y) + offset.y), f32(f32(1 / parentScale.z) + offset.z));
        node.updateMatrix();
      }
    }

    function reset() {
      for (const {node, rest} of entries) {
        node.scale.copy(rest);
        node.updateMatrix();
      }
    }

    return {nodes: entries.map(entry => entry.node), apply, reset, dispose: reset};
  }

  global.MVStudioLossyScale = {create};
})(typeof window !== "undefined" ? window : globalThis);
