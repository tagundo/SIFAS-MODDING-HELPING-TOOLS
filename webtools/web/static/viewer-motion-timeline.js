/* The game's selected dancer and facial tracks share one authored playhead. */
(function (global) {
  "use strict";
  function number(value, fallback) { return typeof value === "number" && isFinite(value) ? value : fallback; }
  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function curve(keys, position, fallback) {
    if (!keys || !keys.length) return fallback;
    if (position <= keys[0].time) return keys[0].value;
    for (var i = 1; i < keys.length; i += 1) {
      if (position > keys[i].time) continue;
      var a = keys[i - 1], b = keys[i], length = b.time - a.time;
      if (length <= 0) return b.value;
      var t = (position - a.time) / length, t2 = t * t, t3 = t2 * t;
      return (2 * t3 - 3 * t2 + 1) * a.value + (t3 - 2 * t2 + t) * length * number(a.outSlope, 0) +
        (-2 * t3 + 3 * t2) * b.value + (t3 - t2) * length * number(b.inSlope, 0);
    }
    return keys[keys.length - 1].value;
  }
  function timing(source) {
    source = source || {};
    function read(short, original, fallback) { return number(source[short], number(source[original], fallback)); }
    function keys(short, original) { return source[short] || (source[original] || {}).m_Curve || []; }
    return { easeIn: read("easeIn", "m_EaseInDuration", 0), easeOut: read("easeOut", "m_EaseOutDuration", 0),
      blendIn: read("blendIn", "m_BlendInDuration", -1), blendOut: read("blendOut", "m_BlendOutDuration", -1),
      mixIn: keys("mixIn", "m_MixInCurve"), mixOut: keys("mixOut", "m_MixOutCurve"),
      preMode: read("preMode", "m_PreExtrapolationMode", 0), postMode: read("postMode", "m_PostExtrapolationMode", 0),
      preTime: read("preTime", "m_PreExtrapolationTime", 0), postTime: read("postTime", "m_PostExtrapolationTime", 0) };
  }
  function weight(segment, time) {
    var local = time - segment.start, span = segment.duration, spec = timing(segment.timing);
    if (local < 0) return spec.preMode && local >= -spec.preTime ? number(segment.weight, 1) : 0;
    if (local > span) return spec.postMode && local <= span + spec.postTime ? number(segment.weight, 1) : 0;
    var incoming = spec.blendIn >= 0 ? spec.blendIn : spec.easeIn;
    var outgoing = spec.blendOut >= 0 ? spec.blendOut : spec.easeOut;
    var value = number(segment.weight, 1);
    if (incoming > 0 && local < incoming) value *= curve(spec.mixIn, local / incoming, local / incoming);
    if (outgoing > 0 && local > span - outgoing) value *= curve(spec.mixOut, (local - span + outgoing) / outgoing, (span - local) / outgoing);
    return clamp(value, 0, 1);
  }
  function create(root, animations, metadata, descriptor) {
    var THREE = global.THREE, warnings = [], groups = {}, facialGroups = {}, gazeGroups = {}, visibility = [], nativeEvents = new Set(), used = 0;
    var info = metadata || {}, clips = info.clips || [], expressions = info.expressionCatalog || {};
    var animationByName = {}, nodeByIndex = {}, faceChannels = {}, facePresets = {}, morphGroups = {}, sampleFrame = 0;
    animations.forEach(function (clip) { animationByName[clip.name] = clip; });
    root.traverse(function (node) { if (node.userData && node.userData.elichika_node !== undefined) nodeByIndex[String(node.userData.elichika_node)] = node; });
    (expressions.rawChannels || []).forEach(function (channel) {
      var node = nodeByIndex[String(channel.node)], targets = [];
      if (node) node.traverse(function (target) {
        if (!target.morphTargetInfluences || typeof target.morphTargetInfluences[channel.index] !== "number" || !isFinite(target.morphTargetInfluences[channel.index])) return;
        targets.push({ node: target, index: channel.index, spec: channel });
        morphGroup(target, channel.index);
      });
      if (targets.length) faceChannels[channel.node + ":" + channel.index] = targets;
    });
    (expressions.presets || []).forEach(function (preset) { if (typeof preset.semanticId === "number") facePresets[preset.semanticId] = preset; });
    function morphGroup(node, index) {
      var key = node.uuid + ":" + index;
      if (!morphGroups[key]) morphGroups[key] = { node: node, index: index, base: node.morphTargetInfluences[index], tracks: [] };
      return morphGroups[key];
    }
    function denseFinite(values) {
      for (var i = 0; i < values.length; i += 1) if (typeof values[i] !== "number" || !isFinite(values[i])) return false;
      return true;
    }
    function warn(message) { if (warnings.indexOf(message) < 0) warnings.push(message); }
    function identicalAnimation(left, right) {
      if (left.duration !== right.duration || left.tracks.length !== right.tracks.length) return false;
      return left.tracks.every(function (track, index) {
        var other = right.tracks[index];
        if (track.name !== other.name || track.ValueTypeName !== other.ValueTypeName || track.times.length !== other.times.length || track.values.length !== other.values.length) return false;
        for (var key = 0; key < track.times.length; key += 1) if (track.times[key] !== other.times[key]) return false;
        for (var value = 0; value < track.values.length; value += 1) if (track.values[value] !== other.values[value]) return false;
        return true;
      });
    }
    function sourceClip(segment) {
      var matches = clips.filter(function (entry) { return entry.sourceHash === segment.sourceHash && entry.sourceName === segment.sourceName && animationByName[entry.name]; });
      if (!matches.length || matches.length > 1 && !matches.slice(1).every(function (entry) { return identicalAnimation(animationByName[matches[0].name], animationByName[entry.name]); })) return null;
      if (matches.some(function (entry) { return entry.bindingComplete === false; })) warn("Some original Animator parameters or unmatched tracks are unavailable. The compatible character tracks are playing.");
      return animationByName[matches[0].name];
    }
    function register(collection, clip, segment, staticPose, gazeOnly) {
      var registered = 0;
      clip.tracks.forEach(function (track) {
        var key = track.name, group = collection[key], binding = group && group.binding;
        if (!binding) { binding = THREE.PropertyBinding.create(root, key); binding.bind(); }
        if (gazeOnly && (!binding.node || !binding.node.isBone || !/^(?:Left|Right)Eye(?:[12]|_Root)$/.test(binding.node.userData.originalName || binding.node.name.replace(/__\d+$/, "")))) return;
        var base = new Array(track.getValueSize()); binding.getValue(base, 0);
        if (!denseFinite(base)) return;
        var record = { segment: segment, interpolant: track.createInterpolant(), duration: clip.duration, staticPose: !!staticPose };
        if (collection === facialGroups && binding.parsedPath && binding.parsedPath.propertyName === "morphTargetInfluences") {
          var node = binding.targetObject || binding.node, channel = binding.propertyIndex;
          if (!node || !node.morphTargetInfluences) return;
          if (channel !== undefined) {
            channel = Number(channel); if (!Number.isInteger(channel) || !isFinite(node.morphTargetInfluences[channel])) return;
            morphGroup(node, channel).tracks.push({ record: record, component: 0 });
          } else {
            if (base.length !== node.morphTargetInfluences.length) return;
            for (var index = 0; index < base.length; index += 1) morphGroup(node, index).tracks.push({ record: record, component: index });
          }
          registered += 1; return;
        }
        if (!group) group = collection[key] = { binding: binding, base: base, quaternion: track.ValueTypeName === "quaternion", tracks: [] };
        group.tracks.push(record); registered += 1;
      });
      return registered;
    }
    (descriptor.bodySegments || []).slice(0, 1024).forEach(function (segment) {
      var clip = sourceClip(segment);
      if (!clip) { warn("A selected body segment is incompatible with this model."); return; }
      if (register(groups, clip, segment, false)) used += 1;
      else warn("A selected body segment is incompatible with this model.");
    });
    var events = descriptor.facial && descriptor.facial.events || [];
    events.slice(0, 12000).forEach(function (event) {
      if (event.kind === "gaze") {
        // Original GazingTarget enum (GL3.12.0), paired with the game's
        // GazeDirection eye pose bank. Apply iris bones without changing lids.
        var direction = { 31: 8, 32: 9, 33: 7, 34: 6, 35: 11, 36: 10 }[event.target];
        if (direction) {
          var gazeAlias = (descriptor.facialClips || []).filter(function (entry) { return entry.kind === "eyes" && entry.index === direction; });
          var gazeClips = clips.filter(function (entry) { return animationByName[entry.name] && gazeAlias.some(function (alias) { return alias.sourceHash === entry.sourceHash && alias.sourceName === entry.sourceName; }); });
          if (gazeClips.length === 1) register(gazeGroups, animationByName[gazeClips[0].name], event, true, true);
        }
        return;
      }
      if (event.kind !== "eyes" && event.kind !== "mouth") return;
      var kind = event.kind === "eyes" ? "eye" : "mouth", pattern = new RegExp("(?:^|_)LiveFacial_" + kind + "_0*" + event.index + "(?:__\\d+)?$");
      var alias = (descriptor.facialClips || []).filter(function (entry) { return entry.kind === event.kind && entry.index === event.index; });
      var matches = clips.filter(function (entry) {
        return animationByName[entry.name] && (alias.length ? alias.some(function (facial) { return facial.sourceHash === entry.sourceHash && facial.sourceName === entry.sourceName; }) : pattern.test(entry.sourceName || entry.name));
      });
      if (matches.length === 1 && register(facialGroups, animationByName[matches[0].name], event, true)) {
        var entry = matches[0];
        (entry.visibility || []).forEach(function (track) { visibility.push({ event: event, track: track }); });
        nativeEvents.add(event);
      } else {
        var preset = facePresets[(kind === "mouth" ? 10000 : 0) + event.index];
        var presetBound = preset && (preset.targets || []).some(function (target) { return !!faceChannels[target.node + ":" + target.index]; });
        var rawMatch = (expressions.rawChannels || []).some(function (channel) {
          var expected = (kind === "mouth" ? "MouthBlendShape.mouth_facial_" : "EyeBlendShape.eye_facial_") + ("00" + event.index).slice(-3);
          return channel.name.toLowerCase() === expected.toLowerCase() && !!faceChannels[channel.node + ":" + channel.index];
        });
        if (!presetBound && !rawMatch) warn("Some original facial shapes are unavailable for this model.");
      }
    });
    function evaluateGroups(collection, time, facial) {
      Object.keys(collection).forEach(function (key) {
        var group = collection[key], values = [], total = 0;
        group.tracks.forEach(function (record) {
          var segment = record.segment, amount = weight(segment, time);
          if (amount <= 0) return;
          var local = (time - segment.start) * number(segment.timeScale, 1) + number(segment.clipIn, 0);
          // Facial clips are original poses (many have one key at the end).
          if (record.staticPose) local = record.duration;
          else {
            var spec = timing(segment.timing), mode = time < segment.start ? spec.preMode : time > segment.start + segment.duration ? spec.postMode : 1;
            if (mode === 2 && record.duration) local = ((local % record.duration) + record.duration) % record.duration;
            else if (mode === 3 && record.duration) { var phase = ((local % (2 * record.duration)) + 2 * record.duration) % (2 * record.duration); local = phase <= record.duration ? phase : 2 * record.duration - phase; }
            else local = clamp(local, 0, record.duration);
          }
          values.push({ value: Array.prototype.slice.call(record.interpolant.evaluate(local)), weight: amount }); total += amount;
        });
        if (!values.length) return;
        var result = group.base.slice(), remainder = Math.max(0, 1 - total), denominator = total + remainder;
        if (group.quaternion) {
          var q = new THREE.Quaternion().fromArray(group.base), accumulated = remainder;
          values.forEach(function (entry) {
            var next = new THREE.Quaternion().fromArray(entry.value);
            if (!accumulated) q.copy(next); else q.slerp(next, entry.weight / (accumulated + entry.weight));
            accumulated += entry.weight;
          }); result = q.normalize().toArray();
        } else {
          for (var i = 0; i < result.length; i += 1) {
            result[i] = group.base[i] * remainder;
            values.forEach(function (entry) { result[i] += entry.value[i] * entry.weight; });
            result[i] /= denominator;
          }
        }
        group.binding.setValue(result, 0);
      });
    }
    function applyShapes(time) {
      var active = { eyes: [], mouth: [] }, contributions = {};
      sampleFrame += 1;
      Object.keys(morphGroups).forEach(function (key) {
        morphGroups[key].tracks.forEach(function (track) {
          var record = track.record, amount = weight(record.segment, time); if (amount <= 0) return;
          if (record.sampleFrame !== sampleFrame) { record.sample = Array.prototype.slice.call(record.interpolant.evaluate(record.duration)); record.sampleFrame = sampleFrame; }
          if (!contributions[key]) contributions[key] = [];
          contributions[key].push({ value: record.sample[track.component], weight: amount });
        });
      });
      events.forEach(function (event) { if (active[event.kind] && !nativeEvents.has(event)) { var w = weight(event, time); if (w > 0) active[event.kind].push({ event: event, weight: w }); } });
      // Navi speech follows decoded voice amplitude between authored mouth
      // poses. MV songs always use their original vowel timeline.
      var hasAuthoredMouth = events.some(function (event) { return event.kind === "mouth" && weight(event, time) > 0; });
      if (descriptor.category !== "mv" && !hasAuthoredMouth) {
        (descriptor.audio && descriptor.audio.tracks || []).forEach(function (track) {
          var envelope = track.envelope, local = number(track.offset, 0) + (time - number(track.startTime, 0)) * number(track.playbackRate, 1);
          if (!envelope || !Array.isArray(envelope.values) || !envelope.values.length || !(envelope.step > 0) || local < 0 || time < track.startTime || time > track.startTime + track.duration) return;
          var index = Math.min(envelope.values.length - 1, Math.floor(local / envelope.step));
          var openness = clamp(number(envelope.values[index], 0), 0, 1);
          active.mouth.push({ event: { index: 1 }, weight: openness });
          active.mouth.push({ event: { index: 6 }, weight: 1 - openness });
        });
      }
      Object.keys(active).forEach(function (kind) {
        active[kind].forEach(function (record) {
          var semantic = (kind === "mouth" ? 10000 : 0) + record.event.index, preset = facePresets[semantic];
          var targets = preset && preset.targets;
          if (!targets) targets = (expressions.rawChannels || []).filter(function (channel) { return channel.group === kind; }).map(function (channel) {
            var expected = (kind === "mouth" ? "MouthBlendShape.mouth_facial_" : "EyeBlendShape.eye_facial_") + ("00" + record.event.index).slice(-3);
            return { node: channel.node, index: channel.index, value: channel.name.toLowerCase() === expected.toLowerCase() ? 1 : 0 };
          });
          targets.forEach(function (target) {
            (faceChannels[target.node + ":" + target.index] || []).forEach(function (channel) {
              var key = channel.node.uuid + ":" + channel.index;
              if (!contributions[key]) contributions[key] = [];
              contributions[key].push({ value: target.value, weight: record.weight });
            });
          });
        });
      });
      // Native whole-array and indexed tracks, fallback poses, and speech
      // share the same actual morph channel. Blend them once with the authored
      // remainder, regardless of track name or original semantic alias.
      Object.keys(contributions).forEach(function (key) {
        var group = morphGroups[key], total = 0, value = 0;
        contributions[key].forEach(function (entry) { total += entry.weight; value += entry.value * entry.weight; });
        var remainder = Math.max(0, 1 - total);
        group.node.morphTargetInfluences[group.index] = (group.base * remainder + value) / Math.max(1, total);
      });
    }
    return { warnings: warnings, compatibleSegments: used,
      animatedProperties: function (time) {
        var owned = {};
        [groups, facialGroups, gazeGroups].forEach(function (collection) {
          Object.keys(collection).forEach(function (key) {
            var group = collection[key], binding = group.binding, property = binding.parsedPath && binding.parsedPath.propertyName;
            if (["position", "quaternion", "scale"].indexOf(property) < 0 ||
                !group.tracks.some(function (record) { return weight(record.segment, time) > 0; })) return;
            var node = binding.targetObject || binding.node, id = node && node.userData && node.userData.elichika_node;
            if (id === undefined) return;
            if (!owned[String(id)]) owned[String(id)] = {};
            owned[String(id)][property] = true;
          });
        });
        return owned;
      },
      duration: Math.max(number(descriptor.facial && descriptor.facial.duration, 0), number(descriptor.audio && descriptor.audio.duration, 0),
        (descriptor.audio && descriptor.audio.tracks || []).reduce(function (end, track) { return Math.max(end, number(track.startTime, 0) + Math.max(0, number(track.duration, 0))); }, 0),
        (descriptor.bodySegments || []).reduce(function (end, segment) { return Math.max(end, segment.start + segment.duration); }, 0)),
      evaluate: function (time) { evaluateGroups(groups, time, false); evaluateGroups(facialGroups, time, true); applyShapes(time); evaluateGroups(gazeGroups, time, true); },
      applyVisibility: function (time) { visibility.forEach(function (record) {
        if (weight(record.event, time) <= .5) return;
        var track = record.track, node = nodeByIndex[String(track.node)];
        if (!node || !track.values || !track.values.length) return;
        var value = track.values[track.values.length - 1];
        node.traverse(function (child) { if (child.isMesh) child.visible = value; });
      }); }
    };
  }
  global.ViewerMotionTimeline = { create: create, weight: weight, curve: curve };
}(window));
