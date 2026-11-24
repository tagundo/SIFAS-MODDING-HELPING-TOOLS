/* Timeline category tabs, member filter and lane plan of MV Studio.

   Categories are derived on the client from each track's native class and
   binding (the exporter forbids a stored track field). Everything here is a
   pure function of the project, except the two small DOM builders at the end. */
(function (global) {
  "use strict";

  const TABS = Object.freeze([
    { id: "edit", label: "Edit" }, { id: "all", label: "All" }, { id: "dance", label: "Dance" },
    { id: "camera", label: "Camera" }, { id: "expression", label: "Expression" }, { id: "mouth", label: "Mouth" },
    { id: "lighting", label: "Lighting" }, { id: "stage", label: "Stage" }, { id: "effects", label: "Effects" },
    { id: "props", label: "Props" }, { id: "post", label: "Screen effects" }, { id: "crowd", label: "Crowd" },
    { id: "sound", label: "Sound" }, { id: "other", label: "Other" },
  ].map(Object.freeze));
  const TAB_IDS = TABS.map((tab) => tab.id);
  const ALWAYS = new Set(["edit", "all"]);

  const CLASSES = Object.freeze({
    LiveMemberScalingTrack: "dance", LiveMemberCullerTrack: "dance", LiveMemberIKTrack: "dance", LiveMemberShadowTrack: "dance",
    LiveCameraOffsetTrack: "camera", LiveSplitScreenTrack: "camera", LiveCameraCutMarkerTrack: "camera", LiveDepthOfFieldTrack: "camera",
    MemberEyeTrack: "expression", MemberGazeTrack: "expression", MemberCheekTrack: "expression",
    MemberLipSyncTrack: "mouth",
    LiveBaseLightTrack: "lighting", LiveMemberAmbientTrack: "lighting", LiveRimlightTrack: "lighting",
    LiveStageAmbientTrack: "lighting", LiveStageSingleAmbientTrack: "lighting", LiveStageEmissiveTrack: "lighting",
    LiveMemberSpotLightAreaTrack: "lighting", LiveMemberSpotLightShaftTrack: "lighting", LiveFlashLightTrack: "lighting",
    LivePropAmbientTrack: "lighting", LivePropRimlightTrack: "lighting",
    LiveColoringTrack: "stage", LiveDisplayTrack: "stage", LiveDisplayCameraTrack: "stage",
    CustomControlTrack: "effects", ControlTrack: "effects",
    LivePropColoringTrack: "props",
    LiveBloomTrack: "post", LiveFlareTrack: "post",
    LivePenlightTrack: "crowd",
    AudioTrack: "sound", NaviVoiceTrack: "sound",
  });
  const KINDS = Object.freeze({
    camera: "camera", split: "camera", dof: "camera", dance: "dance", eyes: "expression", gaze: "expression",
    cheek: "expression", mouth: "mouth", lighting: "lighting", bloom: "post", display: "stage", stage: "stage",
    effects: "effects", props: "props", crowd: "crowd", sound: "sound",
  });
  // mv_studio_props._MEMBER_PROP: a prop carried on a performer bone.
  const MEMBER_PROP = /^\/EntryPoint\/Live\/Members\/ske_[A-Za-z0-9_]+\/Member[1-9][0-9]*\/Model\/[A-Za-z0-9_]+(?:\/[A-Za-z0-9_]+)*\/chp[0-9]+$/;
  const MEMBER_SLOT = /\/Members\/(?:ske_[A-Za-z0-9_]+\/)?Member([1-9][0-9]*)(?:\/|$)/;
  const LABEL_SLOT = /(?:^|\/)Member([1-9][0-9]*)(?: \(\d+\))?(?:\/|$)/;
  const TIMING = new Set(["clipIn", "timeScale", "easeIn", "easeOut", "blendIn", "blendOut",
    "preExtrapolationMode", "postExtrapolationMode", "preExtrapolationTime", "postExtrapolationTime"]);
  const IDENTITY = new Set(["asset", "playableClass", "animation", "animationName", "mixIn", "mixOut", "prefabGameObject"]);
  const text = (value) => String(value == null ? "" : value);

  function bindings(track) {
    const list = [];
    if (typeof track.binding === "string" && track.binding) list.push(track.binding);
    if (Array.isArray(track.bindings)) for (const item of track.bindings) if (typeof item === "string" && item) list.push(item);
    return list;
  }

  function isGroup(track) {
    return track.nativeClass === "GroupTrack" || (!track.nativeClass && track.kind === "group");
  }

  // First matching rule wins (spec §4.1).
  function tabOf(track) {
    if (!track || typeof track !== "object") return "other";
    if (isGroup(track)) return "group";
    const nativeClass = typeof track.nativeClass === "string" ? track.nativeClass : "";
    if (nativeClass && CLASSES[nativeClass]) return CLASSES[nativeClass];
    const binding = text(track.binding);
    if (nativeClass === "AnimationTrack" && binding) {
      if (binding.includes("/Cameras/")) return "camera";
      if (/\/Members\/Member[1-9][0-9]*\/Model$/.test(binding)) return "dance";
      if (MEMBER_PROP.test(binding)) return "props";
      if (binding.includes("/Stages/") && /\/effect\//i.test(binding)) return "effects";
      if (binding.includes("/Stages/")) return "stage";
    }
    if (nativeClass === "ActivationTrack") return MEMBER_PROP.test(binding) ? "props" : "stage";
    return KINDS[track.kind] || "other";
  }

  // The performer slot a track is bound to (binding first, then a MemberN label segment
  // for tracks without a binding), or null.
  function memberSlot(track) {
    if (!track || isGroup(track)) return null;
    const list = bindings(track);
    for (const binding of list) {
      const match = MEMBER_SLOT.exec(binding);
      if (match) return Number(match[1]);
    }
    if (list.length) return null;
    const match = LABEL_SLOT.exec(text(track.label));
    return match ? Number(match[1]) : null;
  }

  function nativeGroup(track) {
    const label = text(track && track.label);
    const cut = label.lastIndexOf("/");
    return cut > 0 ? label.slice(0, cut) : "";
  }

  function eventValueEditable(track, event) {
    if (!event || track.editable === false || event.editable === false) return false;
    const keys = Array.isArray(event.editableValues) ? event.editableValues
      : Object.keys(event.values || {}).filter((key) => !IDENTITY.has(key) && !key.startsWith("m_"));
    return keys.some((key) => !TIMING.has(key));
  }

  // A track with any event whose editableValues carries a non-timing key.
  function valueEditable(track) {
    return !!track && !isGroup(track) && Array.isArray(track.events) && track.events.some((event) => eventValueEditable(track, event));
  }

  function census(tracks) {
    const counts = {};
    for (const id of [...TAB_IDS, "group"]) counts[id] = { tracks: 0, events: 0 };
    for (const track of tracks || []) {
      const tab = tabOf(track), events = Array.isArray(track.events) ? track.events.length : 0;
      counts[tab].tracks++; counts[tab].events += events;
      if (tab !== "group") { counts.all.tracks++; counts.all.events += events; }
    }
    counts.all.tracks += counts.group.tracks;
    return counts;
  }

  function visibleTabs(counts) {
    return TAB_IDS.filter((id) => ALWAYS.has(id) || (counts[id] && counts[id].tracks > 0));
  }

  // Roving focus model: ←/→ wrap, Home/End jump. Returns the id to focus or null.
  function keyTarget(ids, current, key) {
    if (!ids.length) return null;
    const index = Math.max(0, ids.indexOf(current));
    if (key === "ArrowRight" || key === "ArrowDown") return ids[(index + 1) % ids.length];
    if (key === "ArrowLeft" || key === "ArrowUp") return ids[(index - 1 + ids.length) % ids.length];
    if (key === "Home") return ids[0];
    if (key === "End") return ids[ids.length - 1];
    return null;
  }

  function fold(value) {
    return text(value).normalize("NFKC").toLowerCase();
  }

  // Performer slots for the member filter: performers first (with their names), then
  // slots that only appear in track bindings.
  function memberChoices(project) {
    const slots = new Map();
    for (const performer of (project && project.performers) || []) {
      const slot = Number(performer && performer.position);
      if (!Number.isInteger(slot) || slot < 1 || slots.has(slot)) continue;
      const name = text(performer.label || performer.memberName).trim();
      slots.set(slot, { slot, name: name && !/^Member \d+$/.test(name) && name !== text(performer.memberId) ? name : "",
        color: Array.isArray(performer.themeColor) ? performer.themeColor.slice(0, 3) : null });
    }
    for (const track of (project && project.tracks) || []) {
      const slot = memberSlot(track);
      if (slot !== null && !slots.has(slot)) slots.set(slot, { slot, name: "", color: null });
    }
    return [...slots.values()].sort((first, second) => first.slot - second.slot);
  }

  /* Rows of the timeline for one tab and its filters.
     options: { tab, member (slot|null), search, editableOnly, group, edited: Set<eventId>,
                extra: [{ id, after, label, title, render, members? }] }
     → { rows: [{type:"track"|"group"|"extra"|"separator"|"hint", track?, lane?}], tracks, memberTracks, groups } */
  function plan(tracks, options = {}) {
    const tab = TAB_IDS.includes(options.tab) ? options.tab : "all";
    const edited = options.edited instanceof Set ? options.edited : new Set();
    const query = fold(options.search).trim();
    const list = Array.isArray(tracks) ? tracks : [];
    const extra = Array.isArray(options.extra) ? options.extra.filter((lane) => lane && lane.id != null) : [];
    const base = list.filter((track) => tab === "all" || tab === "edit" ? !isGroup(track) : tabOf(track) === tab);
    const memberTracks = base.some((track) => memberSlot(track) !== null);
    const member = memberTracks && Number.isInteger(options.member) ? options.member : null;
    const groups = [...new Set(base.map(nativeGroup).filter(Boolean))];
    const group = groups.includes(options.group) ? options.group : "";
    const searchable = (track) => fold(track.label || track.kind);
    const keep = (track) => (member === null || memberSlot(track) === member) && (!query || searchable(track).includes(query)) &&
      (!group || nativeGroup(track) === group);
    const keepLane = (lane) => (member === null || (Array.isArray(lane.members) && lane.members.includes(member))) &&
      (!query || fold(lane.label).includes(query));
    const hasEdit = (track) => (track.events || []).some((event) => event && edited.has(event.id));
    const rows = [], shown = [];
    if (tab === "edit") {
      const changed = base.filter((track) => hasEdit(track));
      for (const track of changed.filter(keep)) { rows.push({ type: "track", track }); shown.push(track); }
      for (const lane of extra.filter(keepLane)) rows.push({ type: "extra", lane });
      if (!changed.length && !extra.length) rows.push({ type: "hint" });
      rows.push({ type: "separator" });
      for (const track of base) {
        if (changed.includes(track) || !valueEditable(track) || !keep(track)) continue;
        rows.push({ type: "track", track }); shown.push(track);
      }
      return { rows, tracks: shown, memberTracks, groups, member, group };
    }
    const filtering = member !== null || !!query || !!options.editableOnly || !!group;
    const accept = (track) => keep(track) && (!options.editableOnly || valueEditable(track));
    const visible = new Set(base.filter(accept));
    const trackRows = [];
    for (const track of list) {
      if (tab === "all" && isGroup(track)) {
        const prefix = text(track.label) + "/";
        if (!filtering || [...visible].some((item) => text(item.label).startsWith(prefix))) trackRows.push({ type: "group", track });
        continue;
      }
      if (!visible.has(track)) continue;
      trackRows.push({ type: "track", track });
      shown.push(track);
    }
    const lanes = extra.filter(keepLane);
    const head = lanes.filter((lane) => lane.after == null);
    const tail = [];
    rows.push(...head.map((lane) => ({ type: "extra", lane })));
    for (const row of trackRows) {
      rows.push(row);
      if (row.type !== "track") continue;
      for (const lane of lanes) if (lane.after != null && lane.after === row.track.id) rows.push({ type: "extra", lane });
    }
    for (const lane of lanes) if (lane.after != null && !shown.some((track) => track.id === lane.after)) tail.push({ type: "extra", lane });
    rows.push(...tail);
    return { rows, tracks: shown, memberTracks, groups, member, group };
  }

  /* DOM: the tablist. tabs = [{ id, label, count, tracks, clips }] (already translated). */
  function renderTabs(container, { tabs, active, title, onSelect }) {
    container.replaceChildren();
    for (const tab of tabs) {
      const selected = tab.id === active;
      const control = document.createElement("button");
      control.type = "button";
      control.id = "mv-tab-" + tab.id;
      control.className = "mv-tab";
      control.dataset.mvTab = tab.id;
      control.setAttribute("role", "tab");
      control.setAttribute("aria-selected", String(selected));
      control.setAttribute("aria-controls", "mv-timeline-scroll");
      control.tabIndex = selected ? 0 : -1;
      if (title) control.title = title(tab);
      const count = document.createElement("span");
      count.className = "mv-tab-count";
      count.textContent = String(tab.count);
      control.append(document.createTextNode(tab.label + " "), count);
      control.addEventListener("click", () => onSelect(tab.id, false));
      container.append(control);
    }
  }

  /* DOM: the member radiogroup. choices = [{ value (slot|""), label, title, color }]. */
  function renderChips(container, { choices, active, onSelect }) {
    container.replaceChildren();
    for (const choice of choices) {
      const selected = String(choice.value) === String(active);
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "mv-chip";
      chip.dataset.mvMember = String(choice.value);
      chip.setAttribute("role", "radio");
      chip.setAttribute("aria-checked", String(selected));
      chip.tabIndex = selected ? 0 : -1;
      if (choice.title) chip.title = choice.title;
      if (choice.color) {
        const dot = document.createElement("span");
        dot.className = "mv-chip-dot";
        dot.setAttribute("aria-hidden", "true");
        dot.style.background = `rgb(${choice.color.map((value) => Math.round(Math.max(0, Math.min(1, value)) * 255)).join(",")})`;
        chip.append(dot);
      }
      chip.append(document.createTextNode(choice.label));
      chip.addEventListener("click", () => onSelect(choice.value, false));
      container.append(chip);
    }
  }

  // Arrow/Home/End roving on a radiogroup or tablist: moves focus and activates.
  // A tablist uses ←/→ only; a radiogroup also ↑/↓.
  function roving(container, selector, valueOf, onSelect, { vertical = false } = {}) {
    container.addEventListener("keydown", (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (!vertical && (event.key === "ArrowUp" || event.key === "ArrowDown")) return;
      const items = [...container.querySelectorAll(selector)].filter((item) => !item.hidden);
      const current = items.indexOf(document.activeElement);
      if (current < 0) return;
      const ids = items.map(valueOf);
      const next = keyTarget(ids, ids[current], event.key);
      if (next === null) return;
      event.preventDefault();
      onSelect(next, true);
    });
  }

  global.MVStudioTimelineTabs = Object.freeze({
    TABS, TAB_IDS, CLASSES, KINDS, TIMING, tabOf, memberSlot, nativeGroup, valueEditable, eventValueEditable,
    census, visibleTabs, keyTarget, memberChoices, plan, fold, isGroup, renderTabs, renderChips, roving,
  });
})(typeof window !== "undefined" ? window : globalThis);
