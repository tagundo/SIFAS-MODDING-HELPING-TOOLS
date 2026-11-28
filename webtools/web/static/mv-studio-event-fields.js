/* MV Studio inspector controls for clip values (editor plugin "event-fields").

   A descriptor table picks the control for each value of a native playable class:
   HDR colours, sliders, labelled vectors, enum selects, 0/1 checkboxes and facial
   index selects, all with translated labels. Writability still comes only from the
   event's editableValues (info.writable, decided by the server): a value that is not
   writable is shown read-only, and a key without a descriptor keeps the host's
   built-in field. Identity and raw native data (asset ids, pointers, m_* fields, mix
   curves, seeds) are collected in one closed "Native data (read only)" section.

   Every writable input keeps data-mv-field="<path>"; read-only values have none.
   Gestures (spec §6.1 with the fix2 rules): a colour swatch begins its gesture on
   pointerdown and on click (a picker opened from the keyboard) and ends it on change;
   a range slider begins on pointerdown and ends on change or pointerup, never on click
   (a slider's change comes before its click). Each is one undo step. */
(function (global) {
  "use strict";

  // The table is JSON (tests/test_mv_studio_editable_values.py reads it):
  //   trackMute: which track mutes reach the game (trackMuteNote; the export's own rule is
  //            mv_studio_timeline.track_mute_refusal): the notes, the eye and mouth track
  //            classes whose mute the game sets itself, and per quality root the category
  //            names (no spaces, lower case) whose direct child tracks the game's quality
  //            settings switch;
  //   sets:    named option lists [[value, English label]];
  //   labels:  English label per value key (a descriptor's "label" overrides it);
  //   classes: playable class → value key → { control, ... }.
  // Controls: number (min, max, step, integer), slider (min, max, step), vector (unit),
  //   color, enum (set), enum-observed (scope: track | timeline, set or format),
  //   enum-members (gaze targets), member-slot (the project's member slots), bool-int,
  //   text (maxLength), facial-index (facial: eyes | mouth), readonly (set, member).
  //   member: true shows a slot as "Member n · name". member-colors: a penlight palette
  //   (colour, colour source, member per entry). badge "not-previewed": the
  //   value is exported but the 3D preview does not show it.
  const TABLE = /* descriptors:begin */ {
    "trackMute": {
      "notes": {
        "group": "A group track's mute does not reach the game. Mute the tracks inside it.",
        "quality": "The game's quality settings turn this track on and off, so its mute does not reach the game.",
        "facial": "The game turns eye and mouth tracks on and off itself, so this mute does not reach the game."
      },
      "facialClasses": ["MemberEyeTrack", "MemberLipSyncTrack"],
      "qualityRoots": {
        "StageEffect": ["ambient", "animation", "audience", "coloring", "control", "display", "emissive", "flashlight",
                        "overlayeffect", "post"],
        "MemberEffect": ["memberambient", "memberrimlight", "memberspotlightarea", "memberspotlightshaft"],
        "PropEffect": ["propambient", "propcoloring", "proprimlight"],
        "GlobalEffect": ["baselight"],
        "MotionMisc": ["splitscreen"]
      }
    },
    "sets": {
      "colorSource": [[0, "Custom colour"], [1, "Member colour"], [2, "Original member colour"]],
      "kernelSize": [[0, "Small"], [1, "Medium"], [2, "Large"], [3, "Very large"]],
      "flashStatus": [[0, "Off"], [1, "On"], [2, "All"]],
      "cheekType": [[0, "Blush pattern 1"], [1, "Blush pattern 2"]],
      "bodyPart": [[0, "Head"], [1, "Head (all)"], [2, "Face"], [3, "Hips"], [4, "Neck"]],
      "focusTarget": [[0, "The chosen member"], [1, "The nearest member"], [2, "The member nearest the centre"]],
      "swingMode": [[0, "Still"], [1, "Front-back swing"], [2, "Rising swing"], [3, "Side swing"], [4, "Sway"]]
    },
    "labels": {
      "color": "Colour",
      "tintColor": "Tint colour",
      "blendColor": "Blend colour",
      "ambientColor": "Ambient colour",
      "ambientTintColor": "Ambient tint colour",
      "rimlightColor": "Rim light colour",
      "rimlightIntensity": "Rim light intensity",
      "rimlightSharpness": "Rim light sharpness",
      "rimlightDirection": "Rim light direction (°)",
      "ambientColorType": "Ambient colour source",
      "rimlightColorType": "Rim light colour source",
      "ambientMemberPosition": "Ambient colour member",
      "rimlightMemberPosition": "Rim light colour member",
      "colorSpecifiedType": "Colour source",
      "memberPosition": "Member position",
      "intensity": "Intensity",
      "sharpness": "Sharpness",
      "direction": "Direction (°)",
      "speed": "Speed",
      "weight": "Weight",
      "scale": "Scale"
    },
    "classes": {
      "MemberLipSyncClip": {
        "index": {"control": "facial-index", "facial": "mouth", "label": "Mouth shape"},
        "weight": {"control": "slider", "min": 0, "max": 1, "step": 0.001},
        "paramName": {"control": "text", "maxLength": 120, "label": "Parameter name", "badge": "not-previewed"}
      },
      "MemberEyeClip": {
        "index": {"control": "facial-index", "facial": "eyes", "label": "Eye shape"},
        "weight": {"control": "slider", "min": 0, "max": 1, "step": 0.001}
      },
      "MemberGazeClip": {
        "target": {"control": "enum-members", "label": "Look at"},
        "weightForDirection": {"control": "slider", "min": 0, "max": 1, "step": 0.001, "label": "Gaze strength"}
      },
      "MemberCheekClip": {
        "cheekType": {"control": "enum", "set": "cheekType", "label": "Blush pattern"},
        "intensity": {"control": "slider", "min": 0, "max": 1, "step": 0.001, "label": "Blush intensity"}
      },
      "LiveBloomClip": {
        "intensity": {"control": "number", "min": 0, "max": 100, "label": "Bloom intensity"},
        "threshold": {"control": "number", "min": -100, "max": 100, "label": "Threshold"},
        "softKnee": {"control": "slider", "min": 0, "max": 1, "step": 0.001, "label": "Soft knee"},
        "radius": {"control": "slider", "min": 1, "max": 7, "step": 0.01, "label": "Radius"},
        "antiFlicker": {"control": "bool-int", "label": "Anti-flicker"}
      },
      "LiveDepthOfFieldClip": {
        "focusDistance": {"control": "number", "min": 0, "max": 10000, "label": "Focus distance (m)"},
        "aperture": {"control": "number", "min": -100, "max": 10000, "label": "Aperture"},
        "focalLength": {"control": "number", "min": 0, "max": 10000, "label": "Focal length (mm)"},
        "useCameraFov": {"control": "bool-int", "label": "Use the camera field of view"},
        "antiAura": {"control": "bool-int", "label": "Anti-aura"},
        "kernelSize": {"control": "enum", "set": "kernelSize", "label": "Blur size"},
        "useMemberDistance": {"control": "bool-int", "label": "Focus on the member"},
        "bodyPart": {"control": "enum-observed", "scope": "timeline", "set": "bodyPart", "label": "Focus body part"},
        "cameraAutoDistanceMode": {"control": "enum", "set": "focusTarget", "label": "Focus target"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Focus member"},
        "focusTransitionTime": {"control": "number", "min": 0, "max": 60, "label": "Focus transition time (s)"}
      },
      "LiveBaseLightClip": {
        "ambientColor": {"control": "color"},
        "ambientTintColor": {"control": "color"},
        "rimlightColor": {"control": "color"},
        "rimlightIntensity": {"control": "number", "min": 0, "max": 100},
        "rimlightSharpness": {"control": "number", "min": 0, "max": 1000},
        "rimlightDirection": {"control": "vector", "unit": "deg"},
        "ambientColorType": {"control": "enum", "set": "colorSource"},
        "rimlightColorType": {"control": "enum", "set": "colorSource"},
        "ambientMemberPosition": {"control": "member-slot", "member": true},
        "rimlightMemberPosition": {"control": "member-slot", "member": true}
      },
      "LiveMemberAmbientClip": {
        "color": {"control": "color"},
        "tintColor": {"control": "color"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LiveStageAmbientClip": {
        "color": {"control": "color"},
        "tintColor": {"control": "color"},
        "blendColor": {"control": "color"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LiveStageSingleAmbientClip": {
        "color": {"control": "color"},
        "tintColor": {"control": "color"},
        "blendColor": {"control": "color"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LiveStageEmissiveClip": {
        "color": {"control": "color"},
        "intensity": {"control": "number", "min": 0, "max": 100},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LiveMemberSpotLightAreaClip": {
        "color": {"control": "color"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LiveMemberSpotLightShaftClip": {
        "color": {"control": "color"},
        "scale": {"control": "vector"},
        "offsetHeight": {"control": "number", "min": -100, "max": 100, "label": "Height offset (m)"},
        "smoothTime": {"control": "number", "min": 0, "max": 100, "label": "Follow smoothing (s)"},
        "drawObjectIndex": {"control": "enum-observed", "scope": "track", "format": "Shaft shape {n}", "label": "Shaft shape"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LiveRimlightClip": {
        "color": {"control": "color"},
        "intensity": {"control": "number", "min": 0, "max": 100},
        "sharpness": {"control": "number", "min": 0, "max": 1000},
        "direction": {"control": "vector", "unit": "deg"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LiveFlareClip": {
        "color": {"control": "color"},
        "center": {"control": "vector", "label": "Centre"},
        "intensity": {"control": "number", "min": 0, "max": 100},
        "smoothness": {"control": "number", "min": 0, "max": 1000, "label": "Smoothness"},
        "roundness": {"control": "number", "min": 0, "max": 100, "label": "Roundness"},
        "rounded": {"control": "bool-int", "label": "Rounded"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LiveFlashLightClip": {
        "tintColor": {"control": "color"},
        "speed": {"control": "number", "min": 0, "max": 1000},
        "status": {"control": "enum", "set": "flashStatus", "label": "Flash lights"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LiveDisplayClip": {
        "scrollSpeed": {"control": "vector", "label": "Scroll speed"},
        "ambientColor": {"control": "color"},
        "materialIndex": {"control": "enum-observed", "scope": "track", "format": "Screen material {n}", "label": "Screen material"}
      },
      "LiveColoringClip": {
        "shift": {"control": "number", "min": -100000, "max": 100000, "integer": true, "label": "Palette shift"},
        "tintColor": {"control": "color"},
        "speed": {"control": "number", "min": -1000, "max": 1000},
        "textureIndex": {"control": "enum-observed", "scope": "track", "format": "Light texture {n}", "label": "Light texture"}
      },
      "LiveCameraOffsetClip": {
        "intensity": {"control": "number", "min": 0, "max": 100, "label": "Offset strength"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Height from member"}
      },
      "LivePenlightClip": {
        "tintColor": {"control": "color"},
        "fogIntensity": {"control": "number", "min": -100, "max": 100, "label": "Fog intensity"},
        "randomBrightness": {"control": "slider", "min": 0, "max": 1, "step": 0.001, "label": "Random brightness"},
        "beatLength": {"control": "number", "min": 0, "max": 1000, "label": "Beat length"},
        "beatOffset": {"control": "number", "min": -1000, "max": 1000, "label": "Beat offset"},
        "randomDelay": {"control": "vector", "label": "Random delay"},
        "randomUp": {"control": "vector", "label": "Random rise"},
        "randomSwingIntensity": {"control": "slider", "min": 0, "max": 1, "step": 0.001, "label": "Random swing strength"},
        "swingMode": {"control": "enum", "set": "swingMode", "label": "Swing motion"},
        "memberColors": {"control": "member-colors", "label": "Penlight colours"},
        "position": {"control": "vector", "label": "Crowd position (m)"},
        "basicYZMoveY": {"control": "number", "min": -10, "max": 10, "label": "Front-back swing: lift (m)"},
        "basicYZMoveZ": {"control": "number", "min": -10, "max": 10, "label": "Front-back swing: reach (m)"},
        "basicYZRotateZ": {"control": "number", "min": -10, "max": 10, "label": "Front-back swing: tilt (rad)"},
        "basicYZSwingBackZ": {"control": "number", "min": -10, "max": 10, "label": "Front-back swing: rest point"},
        "basicYZSwingPowerZ": {"control": "number", "min": 0, "max": 100, "label": "Front-back swing: snap"},
        "growthYZMoveY": {"control": "number", "min": -10, "max": 10, "label": "Rising swing: lift (m)"},
        "growthYZMoveZ": {"control": "number", "min": -10, "max": 10, "label": "Rising swing: reach (m)"},
        "growthYZRotateZ": {"control": "number", "min": -10, "max": 10, "label": "Rising swing: tilt (rad)"},
        "growthYZSwingBackZ": {"control": "number", "min": -10, "max": 10, "label": "Rising swing: rest point"},
        "growthYZSwingPowerZ": {"control": "number", "min": 0, "max": 100, "label": "Rising swing: snap"},
        "growthYZSwingBottomZ": {"control": "number", "min": 0.01, "max": 0.99, "label": "Rising swing: turn point"},
        "growthYZSwingPowerY": {"control": "readonly", "label": "Rising swing: lift curve"},
        "basicXRotateX": {"control": "number", "min": -10, "max": 10, "label": "Side swing: tilt (rad)"},
        "basicXMoveX": {"control": "number", "min": -10, "max": 10, "label": "Side swing: reach (m)"},
        "basicXMoveY": {"control": "number", "min": -10, "max": 10, "label": "Side swing: lift (m)"},
        "simpleXZRotateX": {"control": "number", "min": -10, "max": 10, "label": "Sway: side tilt (rad)"},
        "simpleXZRotateZ": {"control": "number", "min": -10, "max": 10, "label": "Sway: front tilt (rad)"}
      },
      "CustomControlClip": {
        "weight": {"control": "slider", "min": 0, "max": 1, "step": 0.001, "badge": "not-previewed"},
        "offset": {"control": "vector", "label": "Offset (m)", "badge": "not-previewed"}
      },
      "LiveMemberScalingClip": {
        "intensity": {"control": "slider", "min": 0, "max": 1, "step": 0.001, "label": "Scaling strength"}
      },
      "LivePropAmbientClip": {
        "color": {"control": "color"},
        "tintColor": {"control": "color"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      },
      "LivePropRimlightClip": {
        "color": {"control": "color"},
        "intensity": {"control": "number", "min": 0, "max": 100},
        "sharpness": {"control": "number", "min": 0, "max": 1000},
        "direction": {"control": "vector", "unit": "deg"},
        "colorSpecifiedType": {"control": "enum", "set": "colorSource"},
        "memberPosition": {"control": "member-slot", "member": true, "label": "Colour member"}
      }
    }
  } /* descriptors:end */;

  const DESCRIPTORS = TABLE.classes, SETS = TABLE.sets, LABELS = TABLE.labels;
  const NOT_PREVIEWED = "Not shown in the preview";
  const NOT_PREVIEWED_TITLE = "This value is exported to the game, but the 3D preview does not show it.";
  // Identity and raw native fields: shown once, read only, in "Native data".
  const IDENTITY = { asset: "Playable asset", playableClass: "Playable class", animation: "Animation clip",
    animationName: "Animation name", mixIn: "Mix-in curve", mixOut: "Mix-out curve", prefabGameObject: "Effect prefab",
    particleRandomSeed: "Particle random seed", overwriteRandomSeed: "Overwrite random seed" };
  const AXES = ["x", "y", "z", "w"];
  const CHANNELS = ["r", "g", "b", "a"];
  const own = (object, key) => object != null && Object.prototype.hasOwnProperty.call(object, key);
  const finite = Number.isFinite;
  const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const round = (value, places = 6) => { const scale = 10 ** places; return Math.round(value * scale) / scale; };
  let serial = 0;

  // ---- Pure helpers (exported for tests) -------------------------------------------

  function descriptorFor(event, key) {
    const native = event && event.values && event.values.playableClass;
    const fields = typeof native === "string" && own(DESCRIPTORS, native) ? DESCRIPTORS[native] : null;
    return fields && own(fields, key) ? fields[key] : null;
  }

  function isPointer(value) {
    return isObject(value) && Object.keys(value).length === 2 && own(value, "m_FileID") && own(value, "m_PathID");
  }

  function identityKey(key, value) {
    return own(IDENTITY, key) || /^m_/.test(key) || isPointer(value);
  }

  function isColor(value) {
    return isObject(value) && Object.keys(value).length === 4 && CHANNELS.every((channel) => finite(value[channel]));
  }

  function vectorAxes(value) {
    if (!isObject(value)) return null;
    const keys = Object.keys(value);
    const axes = AXES.slice(0, keys.length);
    return keys.length >= 2 && keys.length <= 4 && axes.every((axis) => own(value, axis) && finite(value[axis])) ? axes : null;
  }

  // HDR colour: the swatch shows rgb / k with k = max(1, r, g, b), and k is the intensity.
  function colorParts(value) {
    const k = Math.max(1, value.r, value.g, value.b);
    const hex = "#" + ["r", "g", "b"].map((channel) => {
      const byte = Math.round(Math.min(1, Math.max(0, value[channel] / k)) * 255);
      return byte.toString(16).padStart(2, "0");
    }).join("");
    return { hex, k };
  }

  // A picked swatch colour at intensity k; alpha is kept.
  function pickColor(value, hex, k) {
    const rgb = parseInt(String(hex).slice(1), 16);
    if (!/^#[0-9a-f]{6}$/i.test(String(hex)) || !finite(rgb)) return null;
    return { r: round((rgb >> 16 & 255) / 255 * k), g: round((rgb >> 8 & 255) / 255 * k), b: round((rgb & 255) / 255 * k), a: value.a };
  }

  // The same hue at another intensity: the brightest channel becomes the intensity, so
  // for an intensity of 1 or more the result's k is that intensity. For an HDR colour this
  // is rgb / k * intensity; a colour whose brightest channel is below 1 is scaled the same
  // way. A black colour has no hue to scale: null.
  function scaleColor(value, intensity) {
    const brightest = Math.max(value.r, value.g, value.b);
    if (!(brightest > 0)) return null;
    return { r: round(value.r / brightest * intensity), g: round(value.g / brightest * intensity),
      b: round(value.b / brightest * intensity), a: value.a };
  }

  // Distinct values of the field on this track (or anywhere in the timeline) for the
  // same playable class: current values and the originals of edited clips.
  function observedValues(ctx, track, event, key, scope) {
    const project = ctx.project();
    const native = event.values.playableClass, values = new Set();
    const add = (value) => { if (Number.isInteger(value)) values.add(value); };
    const tracks = scope === "timeline" && project ? project.tracks : [track];
    for (const item of tracks) {
      for (const clip of item.events || []) {
        if (!clip || !clip.values || clip.values.playableClass !== native) continue;
        add(clip.values[key]);
        const original = ctx.history && ctx.history.originals.get(clip.id);
        if (original && original.values) add(original.values[key]);
      }
    }
    return [...values].sort((first, second) => first - second);
  }

  function memberSlots(ctx) {
    const project = ctx.project();
    const tabs = global.MVStudioTimelineTabs;
    const names = new Map();
    if (tabs && typeof tabs.memberChoices === "function") {
      for (const choice of tabs.memberChoices(project)) names.set(choice.slot, choice.name);
    }
    const slots = new Set();
    for (const performer of (project && project.performers) || []) {
      const slot = Number(performer && performer.position);
      if (Number.isInteger(slot) && slot >= 1 && slot <= 12) slots.add(slot);
    }
    return [...slots].sort((first, second) => first - second).map((slot) => ({ slot, name: names.get(slot) || "" }));
  }

  function memberLabel(ctx, slot, name = "") {
    const text = ctx.format("Member {n}", { n: slot });
    return name ? `${text} · ${name}` : text;
  }

  // MemberGazeClip.target: members, the camera, the audience, fixed eye directions,
  // split-screen cameras (ViewerMotionTimeline targetWeights).
  function gazeLabel(ctx, value, names) {
    if (value === 0) return ctx.t("None");
    if (value >= 1 && value <= 12) return memberLabel(ctx, value, names.get(value) || "");
    if (value === 21) return ctx.t("Camera");
    if (value === 22) return ctx.t("Audience");
    if (value >= 31 && value <= 36) return ctx.format("Fixed eye direction {n}", { n: value - 30 });
    if (value >= 37 && value <= 40) return ctx.format("Split-screen camera {n}", { n: value - 36 });
    return ctx.format("Value {n}", { n: value });
  }

  function gazeOptions(ctx, info) {
    const members = memberSlots(ctx), names = new Map(members.map((member) => [member.slot, member.name]));
    const values = new Set([...members.map((member) => member.slot), 21, 22,
      ...observedValues(ctx, info.track, info.event, info.key, "timeline")]);
    if (Number.isInteger(info.value)) values.add(info.value);
    const order = (value) => value >= 1 && value <= 12 ? value : value + 100;
    return [...values].sort((first, second) => order(first) - order(second)).map((value) => [value, gazeLabel(ctx, value, names)]);
  }

  function facialOptions(ctx, info, kind) {
    const ids = (global.ViewerMotionTimeline && global.ViewerMotionTimeline.LIVE_FACIAL_IDS || {})[kind] || [];
    const options = ids.map((id) => [id, kind === "mouth" && id === 0 ? ctx.t("0 · vowel of the parameter name") : String(id)]);
    if (Number.isInteger(info.value) && !ids.includes(info.value)) {
      options.push([info.value, ctx.format("{n} (not played in MVs)", { n: info.value })]);
    }
    return options;
  }

  function enumOptions(ctx, info, spec) {
    const set = spec.set && own(SETS, spec.set) ? SETS[spec.set] : null;
    let options;
    if (spec.control === "enum-observed") {
      const labels = new Map(set || []);
      options = observedValues(ctx, info.track, info.event, info.key, spec.scope).map((value) => [value,
        labels.has(value) ? ctx.t(labels.get(value)) : spec.format ? ctx.format(spec.format, { n: value }) : String(value)]);
    } else if (spec.control === "enum-members") {
      options = gazeOptions(ctx, info);
    } else if (spec.control === "member-slot") {
      options = memberSlots(ctx).map(({ slot, name }) => [slot, memberLabel(ctx, slot, name)]);
    } else if (spec.control === "facial-index") {
      options = facialOptions(ctx, info, spec.facial);
    } else options = (set || []).map(([value, label]) => [value, ctx.t(label)]);
    if (Number.isInteger(info.value) && !options.some(([value]) => value === info.value)) {
      options.push([info.value, ctx.format("Value {n}", { n: info.value })]);
    }
    return options;
  }

  // The English note (for ctx.t) on why a track's mute does not reach the game, or null when it does:
  // a GroupTrack, an eye or mouth track (the game sets their mute when it sets up each member's head),
  // or a track directly inside a quality category group (<root>/<difficulty>/<category>/<track>),
  // whose mute the game's quality settings decide.
  function trackMuteNote(track) {
    const rule = TABLE.trackMute;
    if (!isObject(track) || track.nativeClass === "GroupTrack") return rule.notes.group;
    if (rule.facialClasses.includes(track.nativeClass)) return rule.notes.facial;
    const parts = typeof track.label === "string" ? track.label.split("/") : [];
    if (parts.length === 4 && own(rule.qualityRoots, parts[0])) {
      if (rule.qualityRoots[parts[0]].includes(parts[2].replace(/ /g, "").toLowerCase())) return rule.notes.quality;
    }
    return null;
  }

  // ---- DOM ---------------------------------------------------------------------------

  function labelOf(key, spec) {
    return spec.label || (own(LABELS, key) ? LABELS[key] : key);
  }

  function badge(ctx) {
    return ctx.make("span", ctx.t(NOT_PREVIEWED), { class: "mv-field-badge", title: ctx.t(NOT_PREVIEWED_TITLE) });
  }

  // One labelled row. A single input sits in a <label>; several inputs form a group.
  function row(ctx, key, spec, controls, { wide = false, group = false, kind = "" } = {}) {
    const id = `mv-value-${String(key).replace(/[^A-Za-z0-9_-]/g, "_")}-${++serial}`;
    const element = ctx.make(group ? "div" : "label", null, { class: "mv-field mv-value-field" + (wide ? " mv-value-wide" : "") +
      (kind ? " mv-value-" + kind : ""), "data-mv-value": key });
    const caption = ctx.make("span", null, { class: "mv-value-label", id });
    caption.append(ctx.make("span", ctx.t(labelOf(key, spec))));
    if (spec.badge === "not-previewed") caption.append(badge(ctx));
    if (group) { element.setAttribute("role", "group"); element.setAttribute("aria-labelledby", id); }
    element.append(caption, ...controls);
    return element;
  }

  // A number box that commits on change (clamped to its bounds) and can be set from outside.
  function numberBox(ctx, value, attrs, commit, { integer = false } = {}) {
    const box = ctx.make("input", null, { type: "number", step: integer ? 1 : "any", ...attrs });
    let current = value;
    box.value = finite(value) ? String(round(value, 6)) : "";
    box.addEventListener("change", () => {
      if (box.value !== "" && finite(box.valueAsNumber)) {
        const min = box.hasAttribute("min") ? Number(box.min) : -Infinity;
        const max = box.hasAttribute("max") ? Number(box.max) : Infinity;
        let next = Math.min(max, Math.max(min, box.valueAsNumber));
        if (integer) next = Math.round(next);
        current = next;
        commit(next);
      }
      box.value = finite(current) ? String(round(current, 6)) : "";
    });
    box.show = (next) => { current = next; box.value = finite(next) ? String(round(next, 6)) : ""; };
    return box;
  }

  // The value as written, read back from the event (history writes it in place).
  function stored(info, fallback) {
    const value = info.event && info.event.values ? info.event.values[info.key] : undefined;
    return value === undefined ? fallback : value;
  }

  function numberControl(ctx, info, spec) {
    if (!finite(info.value) && info.value !== null) return undefined;
    const bounds = {};
    if (finite(spec.min)) bounds.min = spec.min;
    if (finite(spec.max)) bounds.max = spec.max;
    const box = numberBox(ctx, info.value, { ...bounds, "data-mv-field": info.path }, (next) => info.set(next),
      { integer: spec.integer === true });
    return row(ctx, info.key, spec, [box]);
  }

  function sliderControl(ctx, info, spec) {
    if (!finite(info.value)) return undefined;
    const label = ctx.t(labelOf(info.key, spec));
    const step = finite(spec.step) ? spec.step : "any";
    const range = ctx.make("input", null, { type: "range", min: spec.min, max: spec.max, step, class: "mv-value-range",
      "aria-label": label, "data-mv-range": info.path });
    range.value = String(info.value);
    const box = numberBox(ctx, info.value, { min: spec.min, max: spec.max, "data-mv-field": info.path, "aria-label": label },
      (next) => { info.set(next); range.value = String(next); });
    // One drag = one undo step: begin on press, end on change or release. Not on click:
    // a slider's change comes before its click, which would open a second, empty gesture.
    range.addEventListener("pointerdown", (event) => { if (event.isPrimary !== false) info.gesture.begin(); });
    range.addEventListener("input", () => {
      const next = Number(range.value);
      if (!finite(next)) return;
      info.set(next);
      box.show(next);
    });
    range.addEventListener("change", () => info.gesture.end());
    range.addEventListener("pointerup", () => info.gesture.end());
    range.addEventListener("pointercancel", () => info.gesture.end());
    const pair = ctx.make("span", null, { class: "mv-value-slider" });
    pair.append(range, box);
    return row(ctx, info.key, spec, [pair], { group: true, kind: "slider-row" });
  }

  function colorControl(ctx, info, spec) {
    if (!isColor(info.value)) return undefined;
    const label = ctx.t(labelOf(info.key, spec));
    let state = { ...info.value }, pickIntensity = null;
    const swatch = ctx.make("input", null, { type: "color", class: "mv-color-swatch", "data-mv-field": info.path, "aria-label": label });
    // k = max(1, r, g, b) is never below 1, so the box is not either (an entry below 1
    // clamps to 1); a darker colour is picked on the swatch or typed in the exact values.
    // An entry sets the brightest channel to it, so the box then shows the entry and the
    // same entry again writes nothing. An entry equal to the value the box shows, k to 4
    // places, writes nothing either. A black colour has no hue to scale: nothing is
    // written and the box goes back to its value.
    const intensity = numberBox(ctx, 1, { min: 1, max: 1000, class: "mv-color-intensity", "data-mv-field": info.path + ".intensity",
      "aria-label": ctx.format("{label}: intensity", { label }),
      title: ctx.t("Intensity (×): the colour's brightest channel, shown as 1 when it is lower. An entry of 1 or more scales the colour so that channel equals it. Pick a darker colour on the swatch.") },
    (next) => {
      pickIntensity = null;
      write(next === round(colorParts(state).k, 4) ? null : scaleColor(state, next));
    });
    const boxes = {};
    for (const channel of CHANNELS) {
      boxes[channel] = numberBox(ctx, state[channel], { min: 0, max: 1000, "data-mv-field": `${info.path}.${channel}`,
        "aria-label": `${label} ${channel.toUpperCase()}` }, (next) => { pickIntensity = null; write({ ...state, [channel]: next }); });
    }
    function show() {
      const parts = colorParts(state);
      swatch.value = parts.hex;
      intensity.show(round(parts.k, 4));
      for (const channel of CHANNELS) boxes[channel].show(state[channel]);
    }
    function write(next) {
      if (!next || !isColor(next)) { show(); return; }
      info.set(next);
      const value = stored(info, next);
      state = isColor(value) ? { ...value } : next;
      show();
    }
    // Picking keeps the intensity the swatch had when the picker opened.
    const intensityOfPick = () => pickIntensity ?? (pickIntensity = colorParts(state).k);
    // A press starts a picker session; the click that follows it (or alone, from the
    // keyboard) belongs to the same session.
    const begin = (fresh) => { info.gesture.begin(); if (fresh) pickIntensity = null; intensityOfPick(); };
    swatch.addEventListener("pointerdown", (event) => { if (event.isPrimary !== false) begin(true); });
    swatch.addEventListener("click", () => begin(false));
    swatch.addEventListener("input", () => write(pickColor(state, swatch.value, intensityOfPick())));
    swatch.addEventListener("change", () => {
      const next = pickColor(state, swatch.value, intensityOfPick());
      if (next && JSON.stringify(next) !== JSON.stringify(state)) write(next);
      pickIntensity = null;
      info.gesture.end();
    });
    const main = ctx.make("span", null, { class: "mv-color-main" });
    main.append(swatch, ctx.make("span", "×", { class: "mv-color-times", "aria-hidden": "true" }), intensity);
    const exact = ctx.make("details", null, { class: "mv-color-channels" });
    exact.append(ctx.make("summary", ctx.t("Exact values")));
    const grid = ctx.make("span", null, { class: "mv-inline-fields mv-axis-fields" });
    for (const channel of CHANNELS) {
      const axis = ctx.make("label", null, { class: "mv-axis" });
      axis.append(ctx.make("span", channel.toUpperCase()), boxes[channel]);
      grid.append(axis);
    }
    exact.append(grid);
    show();
    return row(ctx, info.key, spec, [main, exact], { wide: true, group: true });
  }

  function vectorControl(ctx, info, spec) {
    const axes = vectorAxes(info.value);
    if (!axes) return undefined;
    const label = ctx.t(labelOf(info.key, spec));
    let state = { ...info.value };
    const grid = ctx.make("span", null, { class: "mv-inline-fields mv-axis-fields" });
    const boxes = {};
    for (const axis of axes) {
      const wrapper = ctx.make("label", null, { class: "mv-axis" });
      boxes[axis] = numberBox(ctx, state[axis], { min: -1000000, max: 1000000, "data-mv-field": `${info.path}.${axis}`,
        "aria-label": `${label} ${axis.toUpperCase()}` }, (next) => {
        info.set({ ...state, [axis]: next });
        const value = stored(info, null);
        if (vectorAxes(value)) state = { ...value };
        for (const name of axes) boxes[name].show(state[name]);
      });
      wrapper.append(ctx.make("span", axis.toUpperCase()), boxes[axis]);
      grid.append(wrapper);
    }
    return row(ctx, info.key, spec, [grid], { wide: true, group: true });
  }

  function selectControl(ctx, info, spec) {
    if (!Number.isInteger(info.value)) return undefined;
    const select = ctx.make("select", null, { "data-mv-field": info.path });
    for (const [value, label] of enumOptions(ctx, info, spec)) select.append(new Option(label, String(value)));
    select.value = String(info.value);
    select.addEventListener("change", () => {
      const next = Number(select.value);
      if (Number.isInteger(next)) info.set(next);
    });
    return row(ctx, info.key, spec, [select]);
  }

  function boolControl(ctx, info, spec) {
    const boolean = typeof info.value === "boolean";
    if (!boolean && info.value !== 0 && info.value !== 1) return numberControl(ctx, info, { ...spec, integer: true });
    const box = ctx.make("input", null, { type: "checkbox", "data-mv-field": info.path });
    box.checked = info.value === true || info.value === 1;
    // Real booleans stay booleans; native 0/1 ints stay ints.
    box.addEventListener("change", () => info.set(boolean ? box.checked : box.checked ? 1 : 0));
    return row(ctx, info.key, spec, [box]);
  }

  function textControl(ctx, info, spec) {
    if (typeof info.value !== "string") return undefined;
    const input = ctx.make("input", null, { type: "text", maxlength: finite(spec.maxLength) ? spec.maxLength : 120, "data-mv-field": info.path });
    input.value = info.value;
    input.addEventListener("change", () => {
      if (input.value.includes("\0")) { input.value = stored(info, ""); return; }
      info.set(input.value);
    });
    return row(ctx, info.key, spec, [input]);
  }

  // LivePenlightClip.memberColors: one group per palette entry with its colour, colour source and
  // member. The list keeps its length; each control writes the whole list with one entry changed.
  function memberColorsControl(ctx, info, spec) {
    const list = info.value;
    if (!Array.isArray(list) || !list.length || list.length > 12 || !list.every((entry) => isObject(entry) &&
      isColor(entry.color) && Number.isInteger(entry.colorSpecifiedType) && Number.isInteger(entry.memberPosition))) return undefined;
    const current = () => { const value = stored(info, list); return Array.isArray(value) && value.length === list.length ? value : list; };
    const entries = list.map((_, index) => {
      const entry = () => current()[index];
      const part = (key) => ({ ...info, key, path: `${info.path}.${index}.${key}`, value: entry()[key],
        event: { values: { get [key]() { return entry()[key]; } } },
        set: (next) => info.set(current().map((item, at) => at === index ? { ...item, [key]: next } : item)) });
      const group = ctx.make("fieldset", null, { class: "mv-value-entry", "data-mv-entry": String(index) });
      group.append(ctx.make("legend", ctx.format("Colour {n}", { n: index + 1 })),
        colorControl(ctx, part("color"), { control: "color" }),
        selectControl(ctx, part("colorSpecifiedType"), { control: "enum", set: "colorSource" }),
        selectControl(ctx, part("memberPosition"), { control: "member-slot", member: true, label: "Colour member" }));
      return group;
    });
    return row(ctx, info.key, spec, entries, { wide: true, group: true });
  }

  // A value that is not writable: the same reading, no input and no data-mv-field.
  function readonlyControl(ctx, info, spec) {
    const value = info.value;
    const output = ctx.make("output", null, { class: "mv-value-readonly" });
    const listed = spec.set || ["enum", "enum-observed", "enum-members", "facial-index"].includes(spec.control);
    if (isColor(value)) {
      const parts = colorParts(value);
      const chip = ctx.make("span", null, { class: "mv-color-chip", "aria-hidden": "true" });
      chip.style.background = parts.hex;
      const text = CHANNELS.map((channel) => `${channel.toUpperCase()} ${round(value[channel], 3)}`).join(" · ");
      output.append(chip, ctx.make("span", text + (parts.k > 1 ? ` (×${round(parts.k, 3)})` : "")));
    } else if (vectorAxes(value)) {
      output.textContent = vectorAxes(value).map((axis) => `${axis.toUpperCase()} ${round(value[axis], 4)}`).join(" · ");
    } else if (spec.member === true && Number.isInteger(value)) {
      const names = new Map(memberSlots(ctx).map((member) => [member.slot, member.name]));
      output.textContent = value >= 1 && value <= 12 ? memberLabel(ctx, value, names.get(value) || "") : ctx.format("Value {n}", { n: value });
    } else if (listed && Number.isInteger(value)) {
      const option = enumOptions(ctx, info, spec.control === "readonly" ? { ...spec, control: "enum" } : spec)
        .find(([item]) => item === value);
      output.textContent = option ? option[1] : String(value);
    } else if (spec.control === "bool-int" && (value === 0 || value === 1 || typeof value === "boolean")) {
      output.textContent = ctx.t(value === true || value === 1 ? "On" : "Off");
    } else if (finite(value)) {
      output.textContent = String(round(value, 6));
    } else if (typeof value === "string") {
      output.textContent = value;
    } else return undefined;
    return row(ctx, info.key, spec, [output]);
  }

  const builders = {
    number: numberControl, slider: sliderControl, vector: vectorControl, color: colorControl,
    enum: selectControl, "enum-observed": selectControl, "enum-members": selectControl, "member-slot": selectControl,
    "facial-index": selectControl,
    "bool-int": boolControl, text: textControl, "member-colors": memberColorsControl,
  };

  function valueControl(ctx, info) {
    if (!info || !info.event || !isObject(info.event.values)) return undefined;
    if (identityKey(info.key, info.value)) return null;
    const spec = descriptorFor(info.event, info.key);
    if (!spec) return undefined;
    if (spec.control === "readonly" || !info.writable) return readonlyControl(ctx, info, spec);
    const build = builders[spec.control];
    return build ? build(ctx, info, spec) : undefined;
  }

  function formatNative(value) {
    if (Array.isArray(value)) return value.length + " × " + JSON.stringify(value).slice(0, 160);
    const text = typeof value === "object" && value !== null ? JSON.stringify(value) : String(value);
    return text.length > 240 ? text.slice(0, 239) + "…" : text;
  }

  // The identity/raw keys valueControl hid, once per clip, collapsed and read only.
  function eventFooter(ctx, { event }) {
    const values = event && isObject(event.values) ? event.values : null;
    if (!values) return undefined;
    const keys = Object.keys(values).filter((key) => identityKey(key, values[key]));
    if (!keys.length) return undefined;
    const details = ctx.make("details", null, { class: "mv-native-fields", id: "mv-native-fields" });
    details.append(ctx.make("summary", ctx.t("Native data (read only)")));
    const list = ctx.make("dl", null, { class: "mv-native-list" });
    for (const key of keys) {
      list.append(ctx.make("dt", own(IDENTITY, key) ? ctx.t(IDENTITY[key]) : key, { title: key }),
        ctx.make("dd", formatNative(values[key]), { "data-mv-native": key }));
    }
    details.append(list);
    return details;
  }

  const plugin = { id: "event-fields", order: 10, valueControl, eventFooter };
  (global.MVStudioPlugins ||= []).push(plugin);
  global.MVStudioEventFields = Object.freeze({ TABLE, plugin, descriptorFor, identityKey, trackMuteNote, colorParts, pickColor, scaleColor,
    observedValues, enumOptions, isColor, vectorAxes });
})(typeof window !== "undefined" ? window : globalThis);
