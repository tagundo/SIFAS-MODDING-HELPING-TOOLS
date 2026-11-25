/* Progress of an MV import from the game: the server's plan/progress records
   (?progress=1 on game-stream) and the page's own model loading, as one
   monotonic percentage with the current step, member count, bytes read and
   elapsed time. Pure state; mv-studio.js renders it. An older server sends
   no plan: the tracker then stays indeterminate until the project arrives. */
(function (global) {
  "use strict";

  const STEP_LABELS = Object.freeze({
    resolve: "Reading game data…",
    timeline: "Reading the live timeline…",
    stage: "Converting the stage…",
    effect: "Converting stage effects…",
    props: "Converting stage props…",
    member: "Converting member {index}/{count}: {name}",
    audio: "Decoding the soundtrack…",
    finish: "Finishing the MV project…",
  });
  const PHASE_LABELS = Object.freeze({
    motion: "Reading choreography…",
    textures: "Textures {done}",
    animation: "Building dance motion… {done}%",
  });
  const DONE = new Set(["done", "cached", "skipped", "failed"]);
  // The server's conversion is this share of the bar; the page's own model
  // loading after the project arrives is the rest.
  const SERVER_SHARE = 0.9;
  const finite = Number.isFinite;
  const clamp01 = (value) => Math.min(1, Math.max(0, finite(value) ? value : 0));

  function stepKey(id, index) { return id === "member" ? "member:" + index : id; }

  function create(now = 0) {
    const state = {
      started: now, plan: null, steps: [], fractions: new Map(), current: null, phase: null,
      read: 0, bytes: 0, members: 0, membersDone: 0, stageReady: false, complete: false,
      page: null, percent: 0, cached: false, cancelling: false,
    };

    // Within a member: choreography, then textures (count only), then the dance bake.
    function phaseFraction(key, phase, done, total) {
      const member = key.startsWith("member:");
      if (phase === "motion") return member ? 0.05 : 0;
      if (phase === "textures") {
        const curve = 1 - 1 / (1 + Math.max(0, done || 0) / 15);
        return member ? 0.15 + 0.3 * curve : 0.9 * curve;
      }
      if (phase === "animation" && finite(done) && finite(total) && total > 0) {
        return (member ? 0.45 : 0.5) + 0.5 * clamp01(done / total);
      }
      return 0;
    }

    function raise(key, value) {
      if (!state.fractions.has(key)) return;
      state.fractions.set(key, Math.max(state.fractions.get(key), clamp01(value)));
    }

    function plan(event) {
      if (!event || !Array.isArray(event.steps) || !event.steps.length) return false;
      const steps = [];
      for (const step of event.steps) {
        if (!step || typeof step.id !== "string" || !finite(step.w) || step.w < 0) return false;
        steps.push({ id: step.id, key: stepKey(step.id, step.index), w: step.w, index: step.index, of: step.of,
                     label: typeof step.label === "string" ? step.label : "" });
      }
      state.plan = event;
      state.steps = steps;
      state.fractions = new Map(steps.map((step) => [step.key, 0]));
      state.bytes = finite(event.bytes) ? event.bytes : 0;
      state.members = finite(event.members) ? event.members : 0;
      return true;
    }

    function progress(event) {
      if (!event || typeof event !== "object") return false;
      if (finite(event.read)) state.read = Math.max(state.read, event.read);
      const id = typeof event.step === "string" ? event.step : state.current?.id;
      if (!id) return true;
      const key = stepKey(id, event.index ?? state.current?.index);
      if (typeof event.state === "string") {
        if (event.state === "start") {
          state.current = { id, key, index: event.index, of: event.of, name: typeof event.name === "string" ? event.name : "" };
          state.phase = null;
          state.cached = false;
        } else if (DONE.has(event.state)) {
          raise(key, 1);
          if (id === "member") state.membersDone = Math.max(state.membersDone, finite(event.index) ? event.index : 0);
          state.cached = event.state === "cached";
          if (state.current?.key === key) state.phase = null;
        }
      } else if (typeof event.phase === "string") {
        state.phase = { name: event.phase, done: event.done, total: event.total };
        raise(key, phaseFraction(key, event.phase, event.done, event.total));
      }
      return true;
    }

    // Server events: "plan" and "progress" records of the game stream.
    function record(event) {
      if (event?.type === "plan") return plan(event);
      if (event?.type === "progress") return progress(event);
      return false;
    }

    function stage() { state.stageReady = true; }

    // The project arrived: the server part is finished whatever was reported.
    function complete() {
      state.complete = true;
      for (const key of state.fractions.keys()) state.fractions.set(key, 1);
      state.current = null;
      state.phase = null;
      state.page = { done: 0, total: 0, phase: "models" };
    }

    // The page loads the scene: models (done/total), then effects.
    function page(update) {
      if (!state.complete || !update) return;
      state.page = { ...state.page, ...update };
    }

    function serverFraction() {
      if (state.complete) return 1;
      let total = 0, done = 0;
      for (const step of state.steps) {
        total += step.w;
        done += step.w * (state.fractions.get(step.key) || 0);
      }
      return total > 0 ? done / total : 0;
    }

    function pageFraction() {
      const current = state.page;
      if (!current) return 0;
      if (current.phase === "effects") return 0.8;
      if (current.phase === "ready") return 1;
      return current.total > 0 ? 0.7 * clamp01(current.done / current.total) : 0;
    }

    // What to show: { determinate, percent, step: [label, values], phase: [label, values] | null,
    // members: [done, count] | null, bytes: [read, total] | null, elapsed (seconds), stageReady, cached }.
    function snapshot(now = state.started) {
      const determinate = !!state.plan || state.complete;
      let percent = state.percent;
      if (determinate) {
        const share = state.plan ? SERVER_SHARE : 0;
        percent = Math.max(percent, Math.floor(100 * (share * serverFraction() + (1 - share) * (state.complete ? pageFraction() : 0))));
        state.percent = percent = Math.min(percent, 100);
      }
      let step = ["Preparing MV from game…", {}], phase = null;
      if (state.page) {
        step = state.page.phase === "effects" || state.page.phase === "ready" ? ["Preparing effects…", {}]
          : ["Loading 3D models {done}/{total}…", { done: state.page.done || 0, total: state.page.total || 0 }];
      } else if (state.current) {
        const planned = state.steps.find((item) => item.key === state.current.key);
        const label = STEP_LABELS[state.current.id] || planned?.label || "Preparing MV from game…";
        step = [label, { index: state.current.index ?? "", count: state.current.of ?? state.members, name: state.current.name }];
        if (state.phase && PHASE_LABELS[state.phase.name]) {
          const done = state.phase.name === "animation" && finite(state.phase.total) && state.phase.total > 0
            ? Math.round(100 * clamp01(state.phase.done / state.phase.total)) : state.phase.done ?? "";
          phase = [PHASE_LABELS[state.phase.name], { done }];
        }
      } else if (state.stageReady) {
        step = ["Stage is ready. Members are still loading.", {}];
      }
      return {
        determinate, percent, step, phase, stageReady: state.stageReady, cached: state.cached,
        members: state.members ? [Math.min(state.membersDone, state.members), state.members] : null,
        bytes: state.bytes ? [state.read, state.bytes] : null,
        elapsed: Math.max(0, (now - state.started) / 1000), cancelling: state.cancelling,
      };
    }

    return { record, stage, complete, page, snapshot, cancel() { state.cancelling = true; }, get planned() { return !!state.plan; } };
  }

  function formatElapsed(seconds) {
    const whole = Math.max(0, Math.floor(seconds));
    return Math.floor(whole / 60) + ":" + String(whole % 60).padStart(2, "0");
  }

  function megabytes(bytes) {
    return (Math.max(0, bytes) / (1024 * 1024)).toFixed(1);
  }

  global.MVStudioImportProgress = Object.freeze({ create, formatElapsed, megabytes, STEP_LABELS, PHASE_LABELS, SERVER_SHARE });
})(typeof window !== "undefined" ? window : globalThis);
