/* MV Studio free camera views (MVStudioFreeCamera): the 3D model tab's Front / Back / Left /
   Right buttons for the MV preview's free camera, with a target and distance / FOV controls.

   - Target: the stage centre (the stage origin at chest height) or a member's chest. A view
     button orbits the free camera around it to that side, keeping the current distance,
     height angle and FOV, so the target sits at the screen centre. Front is the audience side
     (the side the members face), Left and Right are the members' left and right.
   - No fit-to-screen: whether to fit the stage or the members is ambiguous, so the framing is
     the user's: Distance moves the camera forward and back (the mouse wheel does too) and FOV
     widens or narrows the lens (Shift+wheel does too).
   - Follow member (off by default, so the view stays where it was put): while a member is the
     target, the free camera moves with that member as the MV plays or the playhead moves.

   Preview only: nothing here writes the project, a timeline, the game camera or an export.
   "Key current view" (mv-studio-camera-keys.js) keys whatever the free camera shows. */
(function (global) {
  "use strict";

  // [id, label, tooltip]; the labels are the 3D model tab's.
  const VIEWS = Object.freeze([
    ["front", "Front", "Look from the audience side (the side the members face)."],
    ["back", "Back", "Look from behind the stage."],
    ["left", "Left side", "Look from the members' left."],
    ["right", "Right side", "Look from the members' right."],
  ]);
  // The slider ranges; the number boxes take the same values. Distance slides on a log scale.
  const DISTANCE = Object.freeze({ min: .3, max: 300, steps: 1000 });
  const FOV = Object.freeze({ min: 5, max: 120 });
  const LOG_SPAN = Math.log(DISTANCE.max / DISTANCE.min);
  const finite = Number.isFinite;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const sliderOf = (metres) => Math.round(clamp(Math.log(metres / DISTANCE.min) / LOG_SPAN, 0, 1) * DISTANCE.steps);
  const metresOf = (value) => DISTANCE.min * Math.exp(LOG_SPAN * clamp(value, 0, DISTANCE.steps) / DISTANCE.steps);
  const round = (value, digits) => Number(value.toFixed(digits));

  const STRINGS = Object.freeze([
    "Free camera views", "Target", "Stage centre", "The free camera looks at this point and turns around it.",
    "View direction", ...VIEWS.flatMap(([, label, title]) => [label, title]),
    "Distance", "Distance from the target (m). The mouse wheel also moves the camera forward and back.",
    "FOV", "Vertical field of view (°). Shift+mouse wheel also changes it.",
    "Follow member", "While a member is the target, the free camera moves with that member as the MV plays or the playhead moves. Preview only.",
  ]);

  // Gap (px) between the bar and the preview controls, the bar's margin from the preview's edge
  // (mv-studio-free-camera.css) and the narrowest bar placed beside the controls.
  const GAP = 6, EDGE = 8, MIN_BESIDE = 160;
  // A bar that does not fit drops its sliders (the number boxes stay), then its captions.
  const COMPACT = Object.freeze(["mv-freecam-compact", "mv-freecam-tight"]);

  let ctx = null, refs = null, scene = null, unsubscribe = null, queued = 0, targetsKey = "", placed = 0, wasHidden = true;
  // The member target a reload left out: it comes back when that member slot loads again, until
  // another target is picked.
  let missingTarget = null;

  const t = (label) => ctx && typeof ctx.t === "function" ? ctx.t(label) : label;
  const freeView = () => scene && scene.freeView ? scene.freeView : null;
  const modeSelect = () => global.document.getElementById("mv-camera-mode");

  // Text, title and aria-label that follow a language switch (app.js data-i18n, and the host's
  // translateAria for the attributes).
  function make(tag, { text, title, aria, ...attrs } = {}) {
    const element = ctx.make(tag, text == null ? null : t(text), attrs);
    if (text != null) element.dataset.i18n = text;
    if (title) { element.title = t(title); element.dataset.i18nTitle = title; }
    if (aria) { element.setAttribute("aria-label", t(aria)); element.dataset.i18nAriaLabel = aria; }
    return element;
  }

  function build() {
    const controls = global.document.getElementById("mv-preview-controls");
    if (!controls || global.document.getElementById("mv-free-camera")) return null;
    const bar = make("div", { id: "mv-free-camera", class: "mv-freecam", role: "toolbar", aria: "Free camera views" });
    bar.hidden = true;
    const box = {};

    const target = make("label", { class: "mv-freecam-field", title: "The free camera looks at this point and turns around it." });
    box.target = make("select", { id: "mv-freecam-target" });
    box.target.append(make("option", { text: "Stage centre", value: "stage" }));
    target.append(make("span", { text: "Target" }), box.target);
    box.target.addEventListener("change", () => chooseTarget(box.target.value));

    const views = make("div", { class: "mv-freecam-views", role: "group", aria: "View direction" });
    for (const [id, label, title] of VIEWS) {
      const control = make("button", { text: label, title, type: "button", "data-mv-freecam-view": id });
      control.addEventListener("click", () => orbit(id));
      views.append(control);
    }

    box.distance = range("distance", "Distance", "Distance from the target (m). The mouse wheel also moves the camera forward and back.",
      { min: 0, max: DISTANCE.steps, step: 1 }, { min: DISTANCE.min, max: DISTANCE.max, step: .05 }, "m",
      (value) => metresOf(value), (metres) => freeView()?.setDistance(metres));
    box.fov = range("fov", "FOV", "Vertical field of view (°). Shift+mouse wheel also changes it.",
      { min: FOV.min, max: FOV.max, step: 1 }, { min: FOV.min, max: FOV.max, step: .5 }, "°",
      (value) => value, (degrees) => freeView()?.setFov(degrees));

    const follow = make("label", { class: "mv-check mv-freecam-follow",
      title: "While a member is the target, the free camera moves with that member as the MV plays or the playhead moves. Preview only." });
    box.follow = ctx.make("input", null, { type: "checkbox", id: "mv-freecam-follow" });
    box.follow.addEventListener("change", () => { freeView()?.setFollow(box.follow.checked); sync(); });
    follow.append(box.follow, make("span", { text: "Follow member" }));

    bar.append(target, views, box.distance.wrap, box.fov.wrap, follow);
    controls.after(bar);
    box.bar = bar;
    return box;
  }

  // A slider and a number box for one value; the slider previews while it moves, and every
  // finished change (slider release, number entry) counts as a finished camera move.
  function range(id, label, title, sliderRange, numberRange, unit, fromSlider, apply) {
    const wrap = make("div", { class: "mv-freecam-field mv-freecam-range", role: "group", title, aria: label });
    const slider = ctx.make("input", null, { type: "range", id: `mv-freecam-${id}-slider`, ...stringValues(sliderRange) });
    slider.dataset.i18nAriaLabel = label;
    slider.setAttribute("aria-label", t(label));
    const number = ctx.make("input", null, { type: "number", id: `mv-freecam-${id}`, ...stringValues(numberRange) });
    number.dataset.i18nAriaLabel = label;
    number.setAttribute("aria-label", t(label));
    slider.addEventListener("input", () => { apply(fromSlider(slider.valueAsNumber)); });
    slider.addEventListener("change", () => { apply(fromSlider(slider.valueAsNumber)); commit(); });
    // The box then shows the value applied (clamped and rounded), also while it keeps focus
    // after Enter; an empty or invalid entry gets the current value back.
    number.addEventListener("change", () => {
      if (number.value !== "" && finite(number.valueAsNumber)) {
        apply(clamp(number.valueAsNumber, numberRange.min, numberRange.max));
        commit();
      }
      sync(number);
    });
    number.addEventListener("blur", () => sync());
    wrap.append(make("span", { text: label }), slider, number, ctx.make("span", unit, { class: "mv-freecam-unit", "aria-hidden": "true" }));
    return { wrap, slider, number };
  }

  const stringValues = (values) => Object.fromEntries(Object.entries(values).map(([key, value]) => [key, String(value)]));

  function commit() { freeView()?.commit(); }

  function orbit(view) {
    const api = freeView();
    if (!api) return;
    refreshTargets();
    if (api.orbit(view)) commit();
    sync();
  }

  function chooseTarget(id) {
    const api = freeView();
    if (!api) return;
    missingTarget = null;
    if (!api.setTarget(id)) api.setTarget("stage");
    commit();
    sync();
  }

  // The scene is created with the first project; hook its change notices once per scene.
  function hookScene() {
    const next = ctx && typeof ctx.scene === "function" ? ctx.scene() : null;
    if (next === scene) return;
    if (unsubscribe) unsubscribe();
    unsubscribe = null;
    scene = next;
    if (scene && scene.freeView) unsubscribe = scene.freeView.onChange(queueSync);
  }

  function queueSync() {
    if (!queued) queued = global.requestAnimationFrame(() => { queued = 0; sync(); });
  }

  // The target list follows the loaded members (the scene reports each one as it loads). A target
  // member that is not loaded leaves the stage centre as the target (which turns Follow member
  // off) until that member slot is back.
  function refreshTargets() {
    const api = freeView();
    if (!refs || !api) return;
    const targets = api.targets();
    const performers = new Map(((ctx.project() || {}).performers || []).map((item) => [item.position, item]));
    const key = targets.map((item) => item.id + ":" + (performers.get(item.slot)?.label || "")).join("|");
    if (key !== targetsKey) {
      targetsKey = key;
      const stage = refs.target.querySelector('option[value="stage"]');
      refs.target.replaceChildren(stage, ...targets.filter((item) => item.kind === "member").map((item) => {
        const name = performers.get(item.slot)?.label;
        return new Option(name ? `${item.slot} · ${name}` : String(item.slot), item.id);
      }));
    }
    const state = api.state(), listed = (id) => targets.some((item) => item.id === id);
    if (!listed(state.target)) {
      if (state.target !== "stage") missingTarget = state.target;
      api.setTarget("stage", { recentre: false });
    } else if (missingTarget && state.target === "stage" && listed(missingTarget)) {
      api.setTarget(missingTarget, { recentre: false });
      missingTarget = null;
    }
    refs.target.value = api.state().target;
  }

  // The bar shows only while the preview draws the free camera; its values follow the camera.
  // A focused box or slider keeps what is being typed or dragged, except `forced`. The target
  // is checked also while the bar is hidden, so a reload never leaves a missing member followed.
  function sync(forced = null) {
    if (!refs) return;
    hookScene();
    const mode = modeSelect();
    const api = freeView();
    refs.bar.hidden = !api || !mode || mode.value !== "orbit";
    // Place the bar when it appears or goes (size changes reach place() through the observer).
    if (wasHidden !== refs.bar.hidden) {
      wasHidden = refs.bar.hidden;
      place();
    }
    refreshTargets();
    if (refs.bar.hidden) return;
    const state = api.state();
    const keep = (element) => element !== forced && element === global.document.activeElement;
    if (!keep(refs.distance.number)) refs.distance.number.value = String(round(state.distance, state.distance < 10 ? 2 : 1));
    if (!keep(refs.fov.number)) refs.fov.number.value = String(round(state.fov, 1));
    if (!keep(refs.distance.slider)) refs.distance.slider.value = String(sliderOf(state.distance));
    if (!keep(refs.fov.slider)) refs.fov.slider.value = String(round(clamp(state.fov, FOV.min, FOV.max), 0));
    refs.follow.checked = state.follow;
    refs.follow.disabled = state.target === "stage";
  }

  // The bar never covers the preview controls, and the view keeps the game camera's canvas, so
  // "Key current view" keys the lens as shown. The bar is one row at the bottom of the view,
  // below the controls. A preview too short for both gets the bar beside the controls (a phone
  // in landscape); with no room beside them either (a phone held upright), the preview keeps
  // the height both need while the bar shows (see holdPreview).
  function place() {
    placed = 0;
    if (!refs) return;
    const bar = refs.bar, preview = bar.parentElement, controls = global.document.getElementById("mv-preview-controls");
    bar.classList.remove("mv-freecam-beside");
    let needed = 0;
    if (bar.offsetParent !== null && preview && controls && controls.offsetParent === preview) {
      compact(bar);
      const below = controls.offsetTop + controls.offsetHeight + GAP;
      const start = controls.offsetLeft + controls.offsetWidth + GAP;
      if (preview.clientWidth - start - GAP < MIN_BESIDE) needed = below + bar.offsetHeight + EDGE;
      else if (bar.offsetTop < below) {
        bar.style.setProperty("--mv-freecam-top", `${controls.offsetTop}px`);
        bar.style.setProperty("--mv-freecam-start", `${start}px`);
        bar.classList.add("mv-freecam-beside");
        compact(bar);
      }
    }
    holdPreview(preview?.closest(".mv-workspace"), needed);
  }

  // The workspace's --mv-preview-min (the preview's least height, which the host's timeline
  // resizer keeps free) becomes at least `height` px; 0 gives it back its own value. The host
  // sizes the timeline again on a window resize.
  function holdPreview(workspace, height) {
    if (!workspace) return;
    const held = workspace.style.getPropertyValue("--mv-preview-min");
    workspace.style.removeProperty("--mv-preview-min");
    const own = parseFloat(global.getComputedStyle(workspace).getPropertyValue("--mv-preview-min")) || 0;
    const next = height > own ? `${Math.ceil(height)}px` : "";
    if (next) workspace.style.setProperty("--mv-preview-min", next);
    if (next !== held) global.dispatchEvent(new global.Event("resize"));
  }

  function compact(bar) {
    bar.classList.remove(...COMPACT);
    for (const level of COMPACT) {
      if (bar.scrollWidth <= bar.clientWidth) return;
      bar.classList.add(level);
    }
  }

  // Resize observer notices: placed on the next frame, outside the observer callback.
  function queuePlace() {
    if (!placed) placed = global.requestAnimationFrame(place);
  }

  // Shift+wheel over the free camera changes its FOV (the plain wheel dollies, OrbitControls).
  // Chromium reports a Shift+wheel as a horizontal scroll, so either axis counts.
  function wheel(event) {
    if (!event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
    const api = freeView(), mode = modeSelect();
    if (!api || !mode || mode.value !== "orbit") return;
    const delta = (event.deltaY || event.deltaX) * (event.deltaMode === 1 ? 33 : event.deltaMode === 2 ? 400 : 1);
    if (!delta) return;
    event.preventDefault();
    event.stopPropagation();
    api.setFov(clamp(api.state().fov * Math.exp(clamp(delta, -400, 400) * .0012), FOV.min, FOV.max));
    commit();
  }

  const plugin = Object.freeze({
    id: "free-camera",
    order: 5,
    attach(context) {
      ctx = context;
      refs = build();
      if (!refs) return;
      modeSelect()?.addEventListener("change", () => sync());
      // "Frame scene" switches the select to the free camera without a change event.
      global.document.getElementById("mv-frame-scene")?.addEventListener("click", () => global.requestAnimationFrame(() => sync()));
      global.document.getElementById("mv-scene")?.addEventListener("wheel", wheel, { capture: true, passive: false });
      if (global.ResizeObserver) {
        const observer = new global.ResizeObserver(queuePlace);
        // The fields too: a language switch or a longer member name changes what fits.
        for (const element of [refs.bar.parentElement, global.document.getElementById("mv-preview-controls"), refs.bar, ...refs.bar.children]) {
          if (element) observer.observe(element);
        }
      }
      sync();
    },
    projectChanged() { sync(); },
  });

  (global.MVStudioPlugins ||= []).push(plugin);
  global.MVStudioFreeCamera = Object.freeze({ plugin, VIEWS, DISTANCE, FOV, STRINGS, sliderOf, metresOf });
}(window));
