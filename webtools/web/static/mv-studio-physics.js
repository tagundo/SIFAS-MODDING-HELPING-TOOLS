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

  // SwingBoneGroupJob has no time step: springs advance once per rendered Unity
  // frame, so the frame rate the live scene requests is the spring rate.
  // Live3DScene.<OnLoad>d__16 calls FpsUtility.set_FPS(RefreshRateMode ? 0 :
  // FrameRate60Fps ? 60 : 30), and CoolAssist clears FrameRate60Fps first.
  // set_FPS(0) uses the display refresh rate (targetFrameRate = round(refresh
  // rate), vSyncCount 1). RefreshRateMode and CoolAssist are device options,
  // not masterdata; both are off unless the caller says otherwise.
  function gameFrameRate(quality, device) {
    if (device?.refreshRateMode === true) {
      const rate = Math.round(Number(device.displayRate));
      if (!(rate >= 1)) throw new Error("Refresh-rate mode needs the display refresh rate.");
      return rate;
    }
    return quality?.frame_rate_60fps === true && device?.coolAssist !== true ? 60 : 30;
  }

  // FOVMOD's MP4 exporter (libfovmod amv_game_time_update) ticks the game at
  // 120 Hz for 120 fps exports and at 60 Hz otherwise, with deltaTime = 1/tick,
  // and encodes every tick/fps ticks. This is the exporter's rule, not the
  // game's, and is only used to reproduce such a recording.
  function exportTickRate(fps) {
    if (![30, 60, 120].includes(fps)) throw new Error("FOVMOD exports are 30, 60 or 120 fps.");
    return fps === 120 ? 120 : 60;
  }

  const ORDERS = ["game", "same-frame"];
  const REFRESH_RATES = [60, 90, 120];

  // Scene-wide stepping settings. "game" order steps the springs before the
  // timeline is evaluated, on the pose the previous frame ended with; the
  // "same-frame" order is the earlier editor behaviour and stays selectable.
  function normalizeTiming(value) {
    const order = value?.order ?? "game";
    if (!ORDERS.includes(order)) throw new Error("The spring order must be game or same-frame.");
    const source = value?.device || {};
    const device = { refreshRateMode: source.refreshRateMode === true, displayRate: null, coolAssist: source.coolAssist === true };
    if (device.refreshRateMode) {
      device.displayRate = Number(source.displayRate);
      if (!REFRESH_RATES.includes(device.displayRate)) throw new Error("Refresh-rate mode is 60, 90 or 120 Hz.");
    }
    const exportFps = value?.exportFps ?? null;
    if (exportFps !== null) exportTickRate(exportFps);
    return { order, device, exportFps };
  }

  function frameRate(quality, timing) {
    return timing?.exportFps ? exportTickRate(timing.exportFps) : gameFrameRate(quality, timing?.device);
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
    let engine = null, active = false, applied = false, stepped = false, previous = null, simulated = null;

    function restorePose() {
      if (!applied) return;
      for (const { object, position, quaternion } of dynamic.values()) {
        if (position) object.position.copy(position);
        if (quaternion) object.quaternion.copy(quaternion);
        if (!object.matrixAutoUpdate) object.updateMatrix();
      }
      applied = false;
    }

    // Keep the authored values restorePose() returns to. Once physics output
    // is on the transforms, they are no longer authored values.
    function remember() {
      if (applied) return;
      for (const { object, position, quaternion } of dynamic.values()) {
        if (position) position.copy(object.position);
        if (quaternion) quaternion.copy(object.quaternion);
      }
      applied = true;
    }

    function reset(reason) {
      active = false;
      stepped = false;
      previous = null;
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

    function configure(quality) {
      // LiveCoreMemberManager receives MemberSwingBone as enableSwingBoneLod.
      // The original base bones and colliders still run at lower qualities.
      const enableLod = quality.member_swing_bone_mv !== false;
      if (settings.enableLod !== enableLod) {
        settings.enableLod = enableLod;
        if (active) reset("quality-lod");
      }
    }

    // Same-frame order: one job on the pose this frame has just animated.
    function apply(time, delta, quality, motion) {
      configure(quality);
      if (!active && !delta) return;
      engine ||= source.create(root, catalog, null, { initializationPose: original });
      applied = false;
      remember();
      if (delta > 0) {
        engine.captureAnimationPose({ time, advancing: true, animatedProperties: motion?.animatedProperties?.(time) || {} });
      }
      engine.apply(delta, settings);
      active = true;
      captureSimulated();
    }

    // Game order, part 1 (LiveCoreMemberManager.Update): called before the
    // timeline is evaluated, so the job reads the pose the previous frame
    // ended with (its animation, springs and LateUpdate correction) and writes
    // world rotations against those parents.
    function update(time, delta, quality, motion) {
      configure(quality);
      if (!(delta > 0)) {
        // A displayed frame with no game frame (display faster than the game's
        // rate): the next job must still read the last game frame's pose.
        if (active) engine?.keepFramePose?.();
        return false;
      }
      engine ||= source.create(root, catalog, null, { initializationPose: original });
      remember();
      const pose = previous || { time, animatedProperties: motion?.animatedProperties?.(time) || {} };
      engine.captureAnimationPose({ time: pose.time, advancing: true, animatedProperties: pose.animatedProperties });
      stepped = engine.step(delta, settings) === true;
      active = true;
      return stepped;
    }

    // Game order, part 2 (LateUpdate): called after the timeline has animated
    // this frame. The job's local rotations stay under the new parents except
    // where the timeline itself animates a bone, then AllSafeCorrect reads
    // this frame's knees. A frame without a job holds the last output.
    function lateUpdate(time, quality, motion) {
      configure(quality);
      if (!active || !engine) { stepped = false; return; }
      remember();
      let next = null;
      if (stepped) {
        next = { time, animatedProperties: motion?.animatedProperties?.(time) || {} };
        previous = next;
      }
      engine.late(settings, next);
      stepped = false;
    }

    // Scene hook: one call before and one after the timeline evaluation.
    function frame(phase, time, delta, quality, motion, order) {
      if (order === "same-frame") {
        if (phase === "late") apply(time, delta, quality, motion);
        return;
      }
      if (phase === "update") update(time, delta, quality, motion);
      else lateUpdate(time, quality, motion);
    }

    function dispose() {
      restorePose();
      engine?.dispose();
      engine = null;
      active = false;
      stepped = false;
      previous = null;
      simulated = null;
    }
    return { restorePose, reset, apply, update, lateUpdate, frame, dispose, simulatedPose: () => simulated };
  }

  global.MVStudioPhysics = { create, createClock, gameFrameRate, exportTickRate, normalizeTiming, frameRate, ORDERS, REFRESH_RATES };
}(typeof window !== "undefined" ? window : globalThis));
