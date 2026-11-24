(function (global) {
  "use strict";

  const mainCamera = "/EntryPoint/Live/Cameras/MainCamera";
  const enabled = (value) => value === true || value === 1;
  // LiveDepthOfFieldClip..ctor (GL 3.12.0 libil2cpp 0x29235cc). A timeline
  // serialized before a field existed keeps the initialiser at runtime; most
  // native clips lack cameraAutoDistanceMode, focusTransitionTime and antiAura.
  const CLIP_DEFAULTS = Object.freeze({
    focusDistance: 1, aperture: 1, focalLength: 15, kernelSize: 0, useMemberDistance: 0, cameraAutoDistanceMode: 0,
    focusTransitionTime: 1, memberPosition: 1, bodyPart: 0, useCameraFov: 0, antiAura: 0,
  });
  // BodyPartManager.Initialize puts Head 0, HeadAll 1, Face 2, Hips 3 and Neck 4
  // in partMap; GetPart returns null for HeadMaterial 5 and anything else.
  const BODY_PARTS = new Set([0, 1, 2, 3, 4]);
  // CalcFocusDistance returns the member distance plus -0.1f (0x56f5e14).
  const FOCUS_OFFSET = Math.fround(-0.1);
  const f32 = Math.fround;
  // CalcFocusDistance reads Members[memberPosition - 1] behind an array bounds
  // check (IndexOutOfRangeException, 0x2924148) and GetPart(bodyPart).transform
  // behind a null check (NullReferenceException, 0x29241a0). Nothing in
  // LiveMixerBase`2.ProcessFrame (0x2b3996c; its only landing pad ends in
  // _Unwind_Resume) or the DOF mixer catches it, so PostProcess (0x29242f4) is
  // skipped and the camera keeps the DepthOfFieldModel.Settings the previous
  // frame wrote. PostProcess is the only per-frame writer of
  // SetDepthOfFieldEnabled/Settings; the other caller of SetDepthOfFieldEnabled
  // is LiveCoreCameraPostProcess.SetDisabledAll (0x2f614bc), which only turns
  // the depth of field off, on the director's reset path
  // (LiveDirectorBase.ResetComponents 0x2926fb0 -> LiveCoreCameraManager.ResetAll
  // -> LiveCoreCamera.ResetComponentsState).
  const KEEP_PREVIOUS = Symbol("keep the previous frame's depth of field");

  // DepthOfFieldComponent.CalculateFocalLength (0x2cce59c) resolves the lens
  // when the camera renders, not when the settings are written: useCameraFov
  // takes 0.012 / tan(Camera.fieldOfView / 2), otherwise the settings'
  // focalLength (millimetres) / 1000. `settings` carries the unresolved lens
  // (useCameraFov, clipFocalLength) that SetDepthOfFieldSettings (0x2f63aa8)
  // stores; the result adds focalLength resolved at `fov`, or is null.
  function resolveLens(settings, fov) {
    if (!settings) return null;
    const focal = settings.useCameraFov ? 0.012 / Math.tan(fov * Math.PI / 360) : settings.clipFocalLength / 1000;
    return focal > 0 && Number.isFinite(focal) ? { ...settings, focalLength: focal } : null;
  }

  function clipValue(value, key) {
    const native = value[key];
    return native === undefined || native === null ? CLIP_DEFAULTS[key] : native;
  }

  // LiveDepthOfFieldMixer transition fields as PreProcess-time state:
  // startTime, prevPos, prevDistance, prevUnfinishedDistance, unfinishedStartTime.
  function createState() {
    return { startTime: -1, prevPos: -1, prevDistance: 0, prevUnfinishedDistance: 0, unfinishedStartTime: -1 };
  }

  function settle(state, position, distance) {
    state.startTime = -1;
    state.prevPos = position;
    state.prevDistance = distance;
    state.prevUnfinishedDistance = distance;
    state.unfinishedStartTime = -1;
  }

  // UnityEngine.Mathf.Lerp clamps t to [0, 1].
  function lerp(from, to, t) {
    const amount = Math.min(1, Math.max(0, t));
    return f32(from + f32(f32(to - from) * amount));
  }

  // UnityEngine.Vector3.Angle, in degrees.
  function vectorAngle(from, to) {
    const denominator = Math.sqrt((from.x * from.x + from.y * from.y + from.z * from.z) *
      (to.x * to.x + to.y * to.y + to.z * to.z));
    if (!(denominator >= 1e-15)) return 0;
    const dot = Math.min(1, Math.max(-1, (from.x * to.x + from.y * to.y + from.z * to.z) / denominator));
    return Math.acos(dot) * 180 / Math.PI;
  }

  // Clip-local playable time (TimelineClip.ToLocalTime inside the clip).
  function localTime(event, time) {
    const value = event.values || {};
    const scale = Number.isFinite(value.timeScale) ? value.timeScale : 1;
    const clipIn = Number.isFinite(value.clipIn) ? value.clipIn : 0;
    return f32((time - event.start) * scale + clipIn);
  }

  // LiveDepthOfFieldMixer.CalcFocusDistance (0x29237fc). cameraAutoDistanceMode
  // 1 takes the nearest member and 2 the member closest to the view axis; every
  // other value uses memberPosition. Only mode 2 runs the focusTransitionTime
  // lerp, when the chosen member changes; modes 0 and 1 reset it every call.
  // Returns the focus distance, undefined when this preview lacks a part the
  // client would have (the caller keeps focusDistance), or KEEP_PREVIOUS. The
  // client throws for a body part partMap never holds and for a memberPosition
  // the MV has no performer for. The editor also keeps the previous frame
  // while a performer of the MV is not loaded (still loading, or its load
  // failed and was reported). That is an editor loading rule, not client
  // behaviour: the client fills Members for every spawned member in
  // LiveDirector.PostprocessInitializeAsync, before playback starts.
  function memberFocus(value, local, distance, options, state) {
    const part = clipValue(value, "bodyPart"), mode = clipValue(value, "cameraAutoDistanceMode");
    if (!BODY_PARTS.has(part)) {
      options.warn?.(`A depth-of-field clip targets body part ${part}, which BodyPartManager never holds; ` +
        "the game keeps the previous frame's depth of field, and so does this preview.");
      return KEEP_PREVIOUS;
    }
    const loaded = Array.isArray(options.members);
    const members = loaded ? options.members : [];
    let focus;
    // Modes 1 and 2 with no loaded member: an editor loading rule. The client's
    // Members is never empty in an MV with performers; with an empty one, mode 1
    // would skip its loop and return +inf - 0.1 (0x2923b98 -> 0x2924218) and
    // mode 2 would throw on Members[0] (0x2923f80). An MV without performers is
    // reported once; performers still loading are silent (a failed load reports
    // through onError).
    if ((mode === 1 || mode === 2) && loaded && !members.length) {
      if (Array.isArray(options.performers) && !options.performers.length) {
        options.warn?.(`A depth-of-field clip picks a member by cameraAutoDistanceMode ${mode}, but this MV has no ` +
          "performers; this preview keeps the previous frame's depth of field.");
      }
      return KEEP_PREVIOUS;
    }
    if (mode === 1) {
      focus = Infinity;
      for (const slot of members) {
        const candidate = distance(slot, part);
        if (!Number.isFinite(candidate)) return undefined;
        if (candidate < focus) focus = candidate;
      }
      if (!Number.isFinite(focus)) return undefined;
      settle(state, -1, f32(focus));
    } else if (mode === 2) {
      if (typeof options.angle !== "function" || !members.length) return undefined;
      let best = 0, bestAngle = Infinity;
      members.forEach((slot, index) => {
        const angle = options.angle(slot, part);
        if (angle < bestAngle) {
          bestAngle = angle;
          best = index;
        }
      });
      focus = distance(members[best], part);
      if (!Number.isFinite(focus)) return undefined;
      focus = f32(focus);
      const period = f32(clipValue(value, "focusTransitionTime"));
      if (state.prevPos < 0) settle(state, best, focus);
      else if (state.prevPos !== best) {
        if (state.startTime < 0) state.startTime = local;
        const t = f32(f32(local - state.startTime) / period);
        if (!(t < 1)) settle(state, best, focus);
        else {
          focus = lerp(state.prevDistance, focus, t);
          state.prevUnfinishedDistance = focus;
          state.unfinishedStartTime = local;
        }
      } else if (state.unfinishedStartTime > 0) {
        const t = f32(f32(local - state.unfinishedStartTime) / period);
        if (!(t < 1)) settle(state, best, focus);
        else {
          focus = lerp(state.prevUnfinishedDistance, focus, t);
          state.startTime = -1;
          state.prevDistance = focus;
        }
      }
    } else {
      const slot = clipValue(value, "memberPosition");
      if (loaded && !members.includes(slot)) {
        // A performer of this MV that has not loaded has its own load error.
        if (Array.isArray(options.performers) && !options.performers.includes(slot)) {
          options.warn?.(`A depth-of-field clip targets member ${slot}, which this MV does not have; ` +
            "the game keeps the previous frame's depth of field, and so does this preview.");
        }
        return KEEP_PREVIOUS;
      }
      focus = distance(slot, part);
      if (!Number.isFinite(focus)) return undefined;
      settle(state, -1, f32(focus));
    }
    return f32(focus + FOCUS_OFFSET);
  }

  // memberDistance(slot, part): distance from the main camera rig to the
  // member's BodyPartManager part. fov: the main camera's current field of
  // view, which resolves the lens. options: members (loaded slots in Members
  // order), performers (every slot the MV has), angle(slot, part)
  // (Vector3.Angle between the view axis and the part), state (createState(),
  // persists the mode-2 transition), previous (a result of the previous
  // evaluated frame; on the client's exception path its settings stay and its
  // lens resolves again at `fov`) and warn(message).
  // Result: null (no depth of field) or { distance, aperture, kernelSize,
  // antiAura, useCameraFov, clipFocalLength (weighted clip focalLength, mm),
  // focalLength (resolved, metres) }.
  function sample(project, time, fov, memberDistance, options = {}) {
    if (project?.quality?.values?.posteffect !== true || !global.MVStudioLighting?.nativeWeight) return null;
    const tracks = project.tracks.filter(track => !track.muted && track.binding === mainCamera &&
      track.nativeClass === "LiveDepthOfFieldTrack");
    if (tracks.length !== 1) return null;

    const state = options.state || createState();
    let highest = 0, discrete, distance = 0, aperture = 0, focalLength = 0;
    for (const event of tracks[0].events) {
      const value = event.values;
      if (value?.playableClass !== "LiveDepthOfFieldClip") continue;
      const weight = global.MVStudioLighting.nativeWeight(event, time);
      if (!(weight > 0)) continue;
      let focus = clipValue(value, "focusDistance");
      if (enabled(clipValue(value, "useMemberDistance"))) {
        const member = typeof memberDistance === "function"
          ? memberFocus(value, localTime(event, time), memberDistance, options, state) : undefined;
        if (member === KEEP_PREVIOUS) return resolveLens(options.previous, fov);
        if (Number.isFinite(member)) focus = member;
        else {
          options.warn?.(`A depth-of-field clip targets body part ${clipValue(value, "bodyPart")} of member ` +
            `${clipValue(value, "memberPosition")} (mode ${clipValue(value, "cameraAutoDistanceMode")}), ` +
            "which this preview cannot locate; its focusDistance is used instead.");
        }
      }
      const clipAperture = clipValue(value, "aperture"), clipFocal = clipValue(value, "focalLength");
      if (![focus, clipAperture, clipFocal].every(Number.isFinite)) return null;
      distance = f32(distance + f32(focus * weight));
      aperture = f32(aperture + f32(clipAperture * weight));
      focalLength = f32(focalLength + f32(clipFocal * weight));
      if (weight > highest) {
        highest = weight;
        discrete = value;
      }
    }
    const kernelSize = discrete && clipValue(discrete, "kernelSize");
    if (!discrete || ![0, 1, 2, 3].includes(kernelSize)) return null;
    return resolveLens({ distance, aperture, kernelSize, antiAura: enabled(clipValue(discrete, "antiAura")),
      useCameraFov: enabled(clipValue(discrete, "useCameraFov")), clipFocalLength: focalLength }, fov);
  }

  global.MVStudioDofFocus = { sample, createState, resolveLens, vectorAngle, CLIP_DEFAULTS };
})(typeof window !== "undefined" ? window : globalThis);
