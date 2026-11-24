(function (global) {
  "use strict";

  // LiveMixerBase`2.ProcessFrame (GL 3.12.0, 0x2b3996c) runs ProcessWithSeek (0x2b39be0) while
  // EnableSeek is set: every input whose weight is not Mathf.Approximately 0 is processed. During
  // playback the live tracks run ProcessWithoutSeek (0x2b39dbc, ProcessingMode 1) or
  // ProcessWithoutSeekV2 (0x2b3a224, any other mode; masterdata live_mixer_base_mode, 2 when the
  // row has none). Both walk the inputs (clips in start order, TrackAsset.SortClips) from
  // completedIndex + 1: a frame that moves the director by at most the shortest clip
  // (minDuration) looks at no more than MaxClipBlend (3) inputs past the last completed one,
  // and a longer step ("maybe skipped") walks to the last input. A finished input completes
  // only when it is the next one, so after several inputs end within one frame the next
  // starting input waits a frame. V2 also forgets nextPlayingIndexInMaybeSkipped on a skip.
  // Fields: startedIndex 0x28, completedIndex 0x2c, maybeSkipped 0x30,
  // playingIndexInMaybeSkipped 0x34, nextPlayingIndexInMaybeSkipped 0x38, minDuration 0x40,
  // previousTime 0x48; the .ctor sets -1, -1, -1, INT_MAX and -1.0.
  // LiveMixerBase.OnPlayableCreate (0x20ec360) gives a mixer the masterdata mode when
  // IsLiveTrack (0x20ec458) finds a root track named "StageEffect" in its director's timeline,
  // and sets EnableSeek otherwise.
  const INT_MAX = 0x7fffffff;
  const MAX_CLIP_BLEND = 3;
  const MIXER_TRACKS = new Set([
    "LiveBaseLightTrack", "LiveBloomTrack", "LiveCameraOffsetTrack", "LiveColoringTrack", "LiveDepthOfFieldTrack",
    "LiveDisplayTrack", "LiveDisplayCameraTrack", "LiveFlareTrack", "LiveFlashLightTrack", "LiveMemberAmbientTrack",
    "LiveMemberIKTrack", "LiveMemberShadowTrack", "LiveMemberSpotLightAreaTrack", "LiveMemberSpotLightShaftTrack",
    "LivePenlightTrack", "LivePropAmbientTrack", "LivePropColoringTrack", "LivePropRimlightTrack", "LiveRimlightTrack",
    "LiveMemberScalingTrack", "LiveSplitScreenTrack", "LiveStageAmbientTrack", "LiveStageEmissiveTrack",
    "LiveStageSingleAmbientTrack", "MemberCheekTrack", "MemberEyeTrack", "MemberGazeTrack", "MemberLipSyncTrack",
  ]);
  // Mathf.Approximately(weight, 0): |weight| < 8 * Mathf.Epsilon (the smallest denormal float here).
  const ZERO_WEIGHT = 1.1210387714598537e-44;

  function inputs(track) {
    return (track.events || []).map((event, index) => ({ event, index }))
      .sort((a, b) => a.event.start - b.event.start || a.index - b.index).map(({ event }) => event);
  }

  // The time Timeline gives an input's playable in a frame where its clip is active (within the
  // clip or its extrapolation), clamped to the clip and scaled from clipIn; null when inactive.
  function playableTime(clip, time) {
    const values = clip.values || {};
    const before = values.preExtrapolationMode ? Math.max(0, values.preExtrapolationTime || 0) : 0;
    const after = values.postExtrapolationMode ? Math.max(0, values.postExtrapolationTime || 0) : 0;
    if (time < clip.start - before || time >= clip.start + clip.duration + after) return null;
    const local = Math.min(Math.max(time - clip.start, 0), clip.duration);
    return local * (values.timeScale ?? 1) + (values.clipIn || 0);
  }

  function create() {
    return { started: -1, completed: -1, maybe: false, playing: -1, next: INT_MAX, minDuration: -1, previous: 0,
      timed: new Set() };
  }

  // One ProcessWithoutSeek(V2) frame at director time `time`: the indices of `clips` it processes.
  // weight(index) is the input weight at `time`; `timed` holds the inputs whose playable time
  // Timeline has set above 0 (PrepareFrame of an active clip).
  function walk(state, clips, time, weight, mode = 2) {
    const count = clips.length, processed = [];
    for (let index = 0; index < count; index++) if (playableTime(clips[index], time) > 0) state.timed.add(index);
    if (state.minDuration < 0) {
      state.minDuration = Number.MAX_VALUE;
      for (const clip of clips) state.minDuration = Math.min(state.minDuration, clip.duration);
    }
    let index = state.completed + 1, last;
    if (time - state.previous > state.minDuration) {
      state.maybe = true;
      state.playing = -1;
      if (mode !== 1) state.next = INT_MAX;
      last = count - 1;
    } else {
      last = !state.maybe && state.playing === -1 ? Math.min(state.completed + MAX_CLIP_BLEND, count - 1) : count - 1;
    }
    for (; index <= last; index++) {
      const value = weight(index);
      if (!(Math.abs(value) >= ZERO_WEIGHT)) {
        if (index === state.completed + 1) {
          if (index <= state.started && (state.maybe || state.timed.has(index))) {
            state.completed = index;
            if (state.next !== INT_MAX) {
              state.completed = state.next - 1;
              state.playing = -1;
              state.next = INT_MAX;
            }
          }
        } else if (index <= state.started && !state.maybe && state.playing === -1 && state.timed.has(index)) {
          last = Math.min(index + 2, count - 1);
        }
        continue;
      }
      state.started = Math.max(state.started, index);
      if (state.playing !== -1 && index > state.playing) state.next = Math.min(state.next, index);
      if (state.maybe) {
        state.completed = Math.max(-1, Math.max(state.completed, state.started - 2));
        state.maybe = false;
        state.playing = index;
        state.next = INT_MAX;
      }
      processed.push(index);
    }
    state.previous = time;
    return processed;
  }

  // The live tracks of a project: Live*/Member* mixer tracks of a timeline with a StageEffect root.
  function liveTracks(project) {
    const tracks = (project?.tracks || []).filter((track) => !track.muted && MIXER_TRACKS.has(track.nativeClass));
    const stageEffect = (project?.tracks || []).some((track) => typeof track.label === "string" &&
      track.label.split("/")[0] === "StageEffect");
    return stageEffect ? tracks : [];
  }

  // A scene's mixers over its frame clock. update() runs once per evaluated frame: an advancing
  // frame continues every walk; any other frame starts the walks again and replays the frame
  // clock's history (the frames the game rendered) before `time`. Without history the frame is a
  // seek: every input with a weight is processed (ProcessWithSeek). skipped(event, time) is true
  // for an input with a weight that the walk left out at `time` (this frame or a replayed one).
  function controller(weightOf) {
    let project = null, tracks = [], states = new Map(), clipsOf = new Map(), skippedAt = new Map();

    function frame(time, mode) {
      const skipped = new Set();
      for (const track of tracks) {
        const clips = clipsOf.get(track);
        const state = states.get(track);
        const weights = new Map();
        const weight = (index) => {
          if (!weights.has(index)) weights.set(index, weightOf(clips[index], time));
          return weights.get(index);
        };
        const processed = new Set(walk(state, clips, time, weight, mode));
        for (let index = 0; index < clips.length; index++) {
          if (!processed.has(index) && playableTime(clips[index], time) !== null &&
              Math.abs(weight(index)) >= ZERO_WEIGHT) skipped.add(clips[index]);
        }
      }
      skippedAt.set(time, skipped);
    }

    return {
      update(value, time, frames) {
        const mode = value?.mixerBaseMode === 1 ? 1 : 2;
        if (value !== project) {
          project = value;
          tracks = liveTracks(project);
          clipsOf = new Map(tracks.map((track) => [track, inputs(track)]));
          states = new Map();
        }
        if (!frames?.advancing) {
          skippedAt = new Map();
          states = new Map(tracks.map((track) => [track, create()]));
          const history = frames?.history || [];
          if (!history.length || !Number.isFinite(time)) return;
          for (const past of history) frame(past, mode);
        } else {
          for (const key of [...skippedAt.keys()]) if (key !== time) skippedAt.delete(key);
          if (!states.size) return;
        }
        if (Number.isFinite(time)) frame(time, mode);
      },
      skipped(event, time) {
        return skippedAt.get(time)?.has(event) === true;
      },
      reset() {
        project = null;
        states = new Map();
        skippedAt = new Map();
      },
    };
  }

  // The active scene's controller: MVStudioLighting.nativeWeight asks it.
  let active = null;

  global.MVStudioMixer = {
    INT_MAX, MAX_CLIP_BLEND, MIXER_TRACKS, create, walk, inputs, liveTracks, controller, playableTime,
    activate(value) { active = value || null; },
    release(value) { if (active === value) active = null; },
    skipped(event, time) { return active ? active.skipped(event, time) : false; },
  };
})(typeof window !== "undefined" ? window : globalThis);
