(function (global) {
  "use strict";

  // The native job advances once per accepted game frame, independent of
  // elapsed seconds or the display's refresh rate. A slow frame does not
  // replay additional physics steps against the same animated input pose.
  function createClock() {
    let previous = null, elapsed = 0, frameRate = 0;
    function reset() {
      previous = null;
      elapsed = 0;
      frameRate = 0;
    }
    function step(stamp, fps) {
      if (!Number.isFinite(stamp)) return 0;
      const interval = 1000 / fps;
      if (previous === null || frameRate !== fps || stamp < previous) {
        previous = stamp;
        elapsed = 0;
        frameRate = fps;
        return 1 / fps;
      }
      elapsed += stamp - previous;
      previous = stamp;
      const crossed = Math.floor((elapsed + 1e-7) / interval);
      if (!crossed) return 0;
      elapsed = Math.max(0, elapsed - crossed * interval);
      return 1 / fps;
    }
    return { reset, step };
  }

  function vector3(value) {
    return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
  }

  function create(root, catalog, motionSettings) {
    const source = global.ViewerGamePhysics;
    if (!catalog?.available || !Array.isArray(catalog.managers) || !Array.isArray(catalog.components) ||
        catalog.managers.some((manager) => ![manager?.bones, manager?.lodBones, manager?.colliders].every(Array.isArray)) ||
        catalog.components.some((record) => !record || typeof record.id !== "string") ||
        !source?.catalogReadiness(catalog).coreAvailable) return null;
    const nodes = new Map();
    root.traverse((node) => {
      const id = node.userData.elichika_node;
      if (!node.userData.viewerHelper && Number.isInteger(id)) nodes.set(id, nodes.has(id) ? null : node);
    });
    const components = new Map(catalog.components.map((record) => [record.id, record]));
    const dynamic = new Map();
    const original = {};
    for (const [id, object] of nodes) if (object) {
      original[id] = { position: object.position.toArray(), quaternion: object.quaternion.toArray(), scale: object.scale.toArray() };
    }

    function trackNode(id, property) {
      const object = nodes.get(id);
      if (!object) return false;
      if (!dynamic.has(id)) dynamic.set(id, { object });
      dynamic.get(id)[property] = object[property].clone();
      return true;
    }

    for (const manager of catalog.managers) {
      for (const id of [...manager.bones, ...manager.lodBones]) {
        const record = components.get(id);
        const values = record?.values, simulation = record?.simulation;
        if (record?.kind !== "bone" || !values || !simulation ||
            ![values.stiffnessForce, values.dragForce, simulation.radius].every(Number.isFinite) ||
            ![values.lowRotationLimit, values.highRotationLimit, simulation.boneAxis, simulation.externalForce].every(vector3) ||
            !trackNode(record.node, "quaternion") || !trackNode(simulation.childNode, "position")) return null;
      }
      for (const id of manager.colliders) {
        const record = components.get(id);
        if (record?.kind !== "collider" || !Number.isFinite(record.values?.radius) ||
            !vector3(record.values?.offset) || !nodes.get(record.node)) return null;
      }
    }
    if (!dynamic.size) return null;
    const runtime = catalog.native.runtime || {};
    const flags = {};
    for (const entry of Array.isArray(runtime.sources) ? runtime.sources : []) {
      if (entry?.known && typeof entry.skirtsafeDisable === "boolean") flags[entry.sourceIndex] = entry.skirtsafeDisable;
    }
    const settings = { bones: true, colliders: true, profile: "live", skirtsafeDisableBySource: flags,
      skirtsafeDisableByComponent: runtime.skirtsafeDisableByComponent || {},
      safeSwingBone: motionSettings?.safeSwingBoneKnown === true ? motionSettings.safeSwingBone : undefined };
    let engine = null, active = false, applied = false, simulated = null;

    function restorePose() {
      if (!applied) return;
      for (const { object, position, quaternion } of dynamic.values()) {
        if (position) object.position.copy(position);
        if (quaternion) object.quaternion.copy(quaternion);
        if (!object.matrixAutoUpdate) object.updateMatrix();
      }
      applied = false;
    }

    function reset(reason) {
      active = false;
      simulated = null;
      engine?.resetSimulation(reason);
    }

    // Unity keeps the LateUpdate swing-bone result in the transforms until the
    // next frame's Animator. Constraints evaluated before that LateUpdate read
    // it, while restorePose() has already put the animated pose back here.
    function captureSimulated() {
      simulated ||= new Map();
      for (const [id, { object, position, quaternion }] of dynamic) {
        const row = simulated.get(id) || { position: position ? object.position.clone() : null,
          quaternion: quaternion ? object.quaternion.clone() : null };
        row.position?.copy(object.position);
        row.quaternion?.copy(object.quaternion);
        simulated.set(id, row);
      }
    }

    function apply(time, delta, quality, motion) {
      // LiveCoreMemberManager receives MemberSwingBone as enableSwingBoneLod.
      // The original base bones and colliders still run at lower qualities.
      const enableLod = quality.member_swing_bone_mv !== false;
      if (settings.enableLod !== enableLod) {
        settings.enableLod = enableLod;
        if (active) reset("quality-lod");
      }
      if (!active && !delta) return;
      engine ||= source.create(root, catalog, null, { initializationPose: original });
      for (const { object, position, quaternion } of dynamic.values()) {
        if (position) position.copy(object.position);
        if (quaternion) quaternion.copy(object.quaternion);
      }
      applied = true;
      if (delta > 0) {
        engine.captureAnimationPose({ time, advancing: true, animatedProperties: motion?.animatedProperties?.(time) || {} });
      }
      engine.apply(delta, settings);
      active = true;
      captureSimulated();
    }

    function dispose() {
      restorePose();
      engine?.dispose();
      engine = null;
      active = false;
      simulated = null;
    }
    return { restorePose, reset, apply, dispose, simulatedPose: () => simulated };
  }

  global.MVStudioPhysics = { create, createClock };
}(window));
