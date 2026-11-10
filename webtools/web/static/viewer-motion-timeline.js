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
  function weightWithTiming(segment, time, spec) {
    var local = time - segment.start, span = segment.duration;
    if (local < 0) return spec.preMode && local >= -spec.preTime ? number(segment.weight, 1) : 0;
    if (local > span) return spec.postMode && local <= span + spec.postTime ? number(segment.weight, 1) : 0;
    var incoming = spec.blendIn >= 0 ? spec.blendIn : spec.easeIn;
    var outgoing = spec.blendOut >= 0 ? spec.blendOut : spec.easeOut;
    var value = number(segment.weight, 1);
    if (incoming > 0 && local < incoming) value *= curve(spec.mixIn, local / incoming, local / incoming);
    if (outgoing > 0 && local > span - outgoing) value *= curve(spec.mixOut, (local - span + outgoing) / outgoing, (span - local) / outgoing);
    return clamp(value, 0, 1);
  }
  function weight(segment, time) { return weightWithTiming(segment, time, timing(segment.timing)); }
  // GL3.12 MemberEyeContactBase uses 45 horizontal / 30 vertical degrees.
  // Targets31..36 are explicit pose directions; Camera/Audience/member targets
  // are positions transformed into the animated face's local rotation basis.
  // These are the original iris pose clips, never synthetic eye/head rotations.
  function gazeAxes(horizontal, vertical) {
    horizontal = clamp(number(horizontal, 0), -1, 1); vertical = clamp(number(vertical, 0), -1, 1);
    var sum = Math.abs(horizontal) + Math.abs(vertical), result = {};
    if (sum > 1) { horizontal /= sum; vertical /= sum; }
    if (horizontal) result[horizontal > 0 ? 6 : 7] = Math.abs(horizontal);
    if (vertical) result[vertical > 0 ? 8 : 9] = Math.abs(vertical);
    return result;
  }
  function createGaze(root, animations, metadata, options) {
    options = options || {};
    var T = global.THREE, info = metadata || {}, byName = {}, groups = {}, poses = {}, warnings = [], lastWeights = {}, missingTargets = [];
    var face = null, eyeCandidates = [], faceCandidates = [], headCandidates = [];
    function name(node) { return node.userData && node.userData.originalName || node.name.replace(/__\d+$/, ""); }
    root.traverse(function (node) {
      if (node.userData && node.userData.viewerHelper) return;
      if (name(node) === "Eye_Root") eyeCandidates.push(node);
      if (name(node) === "Face_Root") faceCandidates.push(node);
      if (name(node) === "Head_Face") headCandidates.push(node);
    });
    // LiveMemberEyeContact.Initialize finds original Eye_Root (metadata
    // literal7617). Head_Face is a90degree bone-axis reference on real faces;
    // Eye_Root/Face_Root cancel it. Neutral/custom rigs may only have Head_Face.
    if (eyeCandidates.length === 1) face = eyeCandidates[0];
    else if (!eyeCandidates.length && faceCandidates.length === 1) face = faceCandidates[0];
    else if (!eyeCandidates.length && !faceCandidates.length && headCandidates.length === 1) face = headCandidates[0];
    (animations || []).forEach(function (clip) { byName[clip.name] = clip; });
    var aliases = options.aliases || (info.expressionCatalog && info.expressionCatalog.gaze && info.expressionCatalog.gaze.clips) || [];
    for (var direction = 6; direction <= 11; direction += 1) {
      var candidates = (info.clips || []).filter(function (entry) {
        if (!byName[entry.name]) return false;
        if (aliases.length) return aliases.some(function (alias) {
          return (alias.kind === undefined || alias.kind === "eyes") && alias.index === direction &&
            (alias.name ? alias.name === entry.name : alias.sourceHash === entry.sourceHash && alias.sourceName === entry.sourceName);
        });
        return new RegExp("(?:^|_)LiveFacial_eye_0*" + direction + "(?:__\\d+)?$").test(entry.sourceName || entry.name);
      });
      var prepared = [];
      candidates.forEach(function (entry) {
        var clip = byName[entry.name], records = [];
        clip.tracks.forEach(function (track) {
          var binding = T.PropertyBinding.create(root, track.name); binding.bind();
          var node = binding.targetObject || binding.node, property = binding.parsedPath && binding.parsedPath.propertyName;
          if (!node || !node.isBone || node.userData && node.userData.viewerHelper || !/^(?:Left|Right)Eye(?:[12]|_Root)$/.test(name(node)) ||
              ["position", "quaternion", "scale"].indexOf(property) < 0) return;
          var value = Array.prototype.slice.call(track.createInterpolant().evaluate(clip.duration));
          if (value.length !== (property === "quaternion" ? 4 : 3) || !value.every(function (v) { return typeof v === "number" && isFinite(v); })) return;
          var key = node.uuid + ":" + property;
          records.push({ key: key, node: node, property: property, value: value });
        });
        if (records.length) prepared.push(records.sort(function (a, b) { return a.key.localeCompare(b.key); }));
      });
      if (!prepared.length) continue;
      var signature = function (records) { return JSON.stringify(records.map(function (r) { return [r.key, r.value]; })); };
      if (prepared.some(function (records) { return signature(records) !== signature(prepared[0]); })) {
        warnings.push("Some original gaze poses are ambiguous for this model."); continue;
      }
      poses[direction] = prepared[0];
      prepared[0].forEach(function (record) {
        if (!groups[record.key]) groups[record.key] = { node: record.node, property: record.property, base: record.node[record.property].toArray() };
      });
    }
    var rotationPath = [], worldQuaternion = new T.Quaternion(), direction = new T.Vector3(), facePosition = new T.Vector3();
    for (var ancestor = face; ancestor; ancestor = ancestor.parent) rotationPath.push(ancestor);
    function worldRotation() {
      worldQuaternion.set(0, 0, 0, 1);
      for (var index = rotationPath.length - 1; index >= 0; index -= 1) worldQuaternion.multiply(rotationPath[index].quaternion);
      return worldQuaternion.normalize();
    }
    function targetWeights(target, context) {
      var fixed = { 31: 8, 32: 9, 33: 7, 34: 6, 35: 11, 36: 10 }[target];
      if (fixed) { var result = {}; result[fixed] = 1; return result; }
      if (target === 0) return {};
      context = context || {};
      var point = target === 21 ? context.camera : target === 22 ? context.audience :
        target >= 1 && target <= 12 ? (context.members || {})[target] : (context.cameras || {})[target];
      if (!face || !Array.isArray(point) || point.length !== 3 || !point.every(function (v) { return typeof v === "number" && isFinite(v); })) {
        if (missingTargets.indexOf(target) < 0) missingTargets.push(target);
        return null;
      }
      missingTargets = missingTargets.filter(function (value) { return value !== target; });
      // getWorldPosition updates this face's ancestor chain. Updating every
      // mesh and bone in the model again for each gaze request is unnecessary.
      direction.fromArray(point).sub(face.getWorldPosition(facePosition));
      if (direction.lengthSq() < 1e-12) return {};
      direction.normalize().applyQuaternion(worldRotation().invert());
      // The converter mirrors Unity's X coordinate, including its eye poses.
      var horizontal = Math.abs(direction.x) <= .001 && Math.abs(direction.z) <= .001 ? 0 : Math.atan2(-direction.x, direction.z) * 180 / Math.PI / 45;
      var vertical = Math.abs(direction.y) <= .001 ? 0 : Math.atan2(direction.y, Math.hypot(direction.x, direction.z)) * 180 / Math.PI / 30;
      return gazeAxes(horizontal, vertical);
    }
    function apply(weights, neutral) {
      lastWeights = Object.assign({}, weights); var contributions = {}, requested = false;
      Object.keys(weights).forEach(function (id) {
        if (!(weights[id] > 0)) return;
        requested = true;
        if (!poses[id]) { if (warnings.indexOf("Some original gaze poses are unavailable for this model.") < 0) warnings.push("Some original gaze poses are unavailable for this model."); return; }
        poses[id].forEach(function (record) { if (!contributions[record.key]) contributions[record.key] = []; contributions[record.key].push({ value: record.value, weight: weights[id] }); });
      });
      Object.keys(groups).forEach(function (key) {
        var group = groups[key], entries = contributions[key] || [], total = entries.reduce(function (sum, entry) { return sum + entry.weight; }, 0);
        if (!entries.length && !neutral) return;
        var remainder = Math.max(0, 1 - total), result = group.base.slice();
        if (group.property === "quaternion") {
          var q = new T.Quaternion().fromArray(group.base), accumulated = remainder;
          entries.forEach(function (entry) { var next = new T.Quaternion().fromArray(entry.value); if (!accumulated) q.copy(next); else q.slerp(next, entry.weight / (accumulated + entry.weight)); accumulated += entry.weight; });
          group.node.quaternion.copy(q.normalize());
        } else {
          for (var i = 0; i < result.length; i += 1) { result[i] = group.base[i] * remainder; entries.forEach(function (entry) { result[i] += entry.value[i] * entry.weight; }); result[i] /= Math.max(1, total); }
          group.node[group.property].fromArray(result);
        }
      });
      return requested && Object.keys(contributions).length > 0 || neutral && Object.keys(groups).length > 0;
    }
    return { warnings: warnings, targetWeights: targetWeights, axes: gazeAxes, apply: apply,
      evaluate: function (requests, context) {
        missingTargets = []; var combined = {};
        (requests || []).forEach(function (request) { var values = targetWeights(request.target, context); if (!values) return;
          Object.keys(values).forEach(function (id) { combined[id] = (combined[id] || 0) + values[id] * clamp(number(request.weight, 1), 0, 1); }); });
        return apply(combined, false);
      },
      properties: function () { var result = {}; Object.keys(groups).forEach(function (key) { var group = groups[key], id = group.node.userData && group.node.userData.elichika_node;
        if (id !== undefined) { if (!result[String(id)]) result[String(id)] = {}; result[String(id)][group.property] = true; } }); return result; },
      operations: function () { return Object.keys(groups).map(function (key) { var group = groups[key], node = group.node.userData && group.node.userData.elichika_node;
        return { node: node, kind: group.property, value: group.node[group.property].toArray(), source: "expression" }; }).filter(function (operation) { return Number.isInteger(operation.node); }); },
      getState: function () { return { available: Object.keys(poses).length > 0, directions: Object.keys(poses).map(Number), weights: Object.assign({}, lastWeights), missingTargets: missingTargets.slice(), warnings: warnings.slice() }; }
    };
  }
  function create(root, animations, metadata, descriptor, options) {
    options = options || {};
    var THREE = global.THREE, warnings = [], compatibilityDetails = [], groups = {}, facialGroups = {}, gazeGroups = {}, visibility = [], nativeEvents = new Set(), used = 0;
    var info = metadata || {}, clips = info.clips || [], expressions = info.expressionCatalog || {};
    var animationByName = {}, nodeByIndex = {}, faceChannels = {}, facePresets = {}, morphGroups = {}, sampleFrame = 0;
    var clipIdentities = new Map(), bindingsByName = new Map(), staticSamples = new WeakMap(), facialMatches = new Map();
    var sampledSegments = new WeakMap(), sampleTime = null, sampleRevision = 0;
    function beginSample(time, fresh) {
      if (fresh || sampleTime !== time) { sampleTime = time; sampleRevision += 1; }
    }
    function sampleSegment(segment, time) {
      var sample = sampledSegments.get(segment);
      if (!sample) { sample = {}; sampledSegments.set(segment, sample); }
      if (sample.revision !== sampleRevision) {
        var spec = timing(segment.timing);
        sample.revision = sampleRevision; sample.spec = spec;
        sample.weight = weightWithTiming(segment, time, spec);
        sample.local = (time - segment.start) * number(segment.timeScale, 1) + number(segment.clipIn, 0);
        sample.mode = time < segment.start ? spec.preMode : time > segment.start + segment.duration ? spec.postMode : 1;
      }
      return sample;
    }
    function sampleWeight(segment, time) { return sampleSegment(segment, time).weight; }
    animations.forEach(function (clip) { animationByName[clip.name] = clip; });
    clips.forEach(function (entry) { if (!animationByName[entry.name]) return; var key = JSON.stringify([entry.sourceHash, entry.sourceName]);
      if (!clipIdentities.has(key)) clipIdentities.set(key, []); clipIdentities.get(key).push(entry); });
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
      var matches = clipIdentities.get(JSON.stringify([segment.sourceHash, segment.sourceName])) || [];
      if (!matches.length) {
        compatibilityDetails.push({ sourceName: segment.sourceName || "", reason: "The selected body clip is missing from the loaded motion files." }); return null;
      }
      if (matches.length > 1 && !matches.slice(1).every(function (entry) { return identicalAnimation(animationByName[matches[0].name], animationByName[entry.name]); })) {
        compatibilityDetails.push({ sourceName: segment.sourceName || "", reason: "Different clips have the same original motion identity." }); return null;
      }
      if (matches.some(function (entry) { return entry.bindingComplete === false; })) warn("Some original Animator parameters or unmatched tracks are unavailable. The compatible character tracks are playing.");
      return animationByName[matches[0].name];
    }
    function register(collection, clip, segment, staticPose, gazeOnly) {
      var registered = 0;
      clip.tracks.forEach(function (track) {
        var key = track.name, group = collection[key], binding = group && group.binding || bindingsByName.get(key);
        if (!binding) { binding = THREE.PropertyBinding.create(root, key); binding.bind(); bindingsByName.set(key, binding); }
        if (gazeOnly && (!binding.node || !binding.node.isBone || !/^(?:Left|Right)Eye(?:[12]|_Root)$/.test(binding.node.userData.originalName || binding.node.name.replace(/__\d+$/, "")))) return;
        var base = new Array(track.getValueSize()); binding.getValue(base, 0);
        if (!denseFinite(base)) return;
        var staticValue = null;
        if (staticPose) {
          var endpoints = staticSamples.get(track);
          if (!endpoints) { endpoints = new Map(); staticSamples.set(track, endpoints); }
          staticValue = endpoints.get(clip.duration);
          if (!staticValue) { staticValue = track.createInterpolant().evaluate(clip.duration); endpoints.set(clip.duration, staticValue); }
        }
        var record = { segment: segment, interpolant: staticPose ? null : track.createInterpolant(), staticValue: staticValue, duration: clip.duration, staticPose: !!staticPose,
          weightedSample: { value: null, weight: 0 } };
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
        if (!group) group = collection[key] = { binding: binding, base: base, quaternion: track.ValueTypeName === "quaternion", tracks: [],
          values: [], result: base.slice(), rotation: new THREE.Quaternion(), nextRotation: new THREE.Quaternion() };
        group.tracks.push(record); registered += 1;
      });
      return registered;
    }
    (descriptor.bodySegments || []).slice(0, 1024).forEach(function (segment) {
      var clip = sourceClip(segment);
      if (!clip) { warn("A selected body segment is incompatible with this model."); return; }
      if (register(groups, clip, segment, false)) used += 1;
      else { compatibilityDetails.push({ sourceName: segment.sourceName || "", reason: "The body clip's tracks do not bind to this model's bones." }); warn("A selected body segment is incompatible with this model."); }
    });
    var events = descriptor.facial && descriptor.facial.events || [], gazeEvents = [];
    var modelGaze = info.expressionCatalog && info.expressionCatalog.gaze, retargetedGaze = !!(modelGaze && modelGaze.available &&
      Number.isInteger(modelGaze.owner) && Number.isInteger(descriptor.targetCharacter) && modelGaze.owner !== descriptor.targetCharacter);
    // Direction indices are the game's common six-pose semantics. When a
    // retained motion belongs to another character, use this face's verified
    // endpoints instead of writing the old character's absolute iris positions.
    var gaze = createGaze(root, animations, info, { aliases: retargetedGaze ? modelGaze.clips : descriptor.facialClips || [] });
    events.slice(0, 12000).forEach(function (event) {
      if (event.kind === "gaze") {
        gazeEvents.push(event);
        return;
      }
      if (event.kind !== "eyes" && event.kind !== "mouth") return;
      var kind = event.kind === "eyes" ? "eye" : "mouth", identity = event.kind + ":" + event.index, matches = facialMatches.get(identity);
      if (!matches) {
        var pattern = new RegExp("(?:^|_)LiveFacial_" + kind + "_0*" + event.index + "(?:__\\d+)?$");
        var alias = (descriptor.facialClips || []).filter(function (entry) { return entry.kind === event.kind && entry.index === event.index; });
        matches = clips.filter(function (entry) {
          return animationByName[entry.name] && (alias.length ? alias.some(function (facial) { return facial.sourceHash === entry.sourceHash && facial.sourceName === entry.sourceName; }) : pattern.test(entry.sourceName || entry.name));
        });
        facialMatches.set(identity, matches);
      }
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
    // Collections and track/interpolant buffers are fixed for this controller.
    // Reuse them while sampling, rather than allocating per bone every frame.
    var bodyGroups = Object.keys(groups).map(function (key) { return groups[key]; });
    var faceGroups = Object.keys(facialGroups).map(function (key) { return facialGroups[key]; });
    var gazeTrackGroups = Object.keys(gazeGroups).map(function (key) { return gazeGroups[key]; });
    var shapeGroups = Object.keys(morphGroups).map(function (key) { return morphGroups[key]; });
    function evaluateGroups(collection, time) {
      collection.forEach(function (group) {
        var values = group.values, total = 0; values.length = 0;
        group.tracks.forEach(function (record) {
          var sample = sampleSegment(record.segment, time), amount = sample.weight;
          if (amount <= 0) return;
          var local = sample.local;
          // Facial clips are original poses (many have one key at the end).
          if (record.staticPose) local = record.duration;
          else {
            var mode = sample.mode;
            if (mode === 2 && record.duration) local = ((local % record.duration) + record.duration) % record.duration;
            else if (mode === 3 && record.duration) { var phase = ((local % (2 * record.duration)) + 2 * record.duration) % (2 * record.duration); local = phase <= record.duration ? phase : 2 * record.duration - phase; }
            else local = clamp(local, 0, record.duration);
          }
          // Each record owns an interpolant and its result buffer, so another
          // track cannot overwrite this sample before this group is blended.
          var entry = record.weightedSample;
          entry.value = record.staticPose ? record.staticValue : record.interpolant.evaluate(local); entry.weight = amount;
          values.push(entry); total += amount;
        });
        if (!values.length) return;
        var result = group.result, remainder = Math.max(0, 1 - total), denominator = total + remainder;
        if (group.quaternion) {
          var q = group.rotation.fromArray(group.base), next = group.nextRotation, accumulated = remainder;
          values.forEach(function (entry) {
            next.fromArray(entry.value);
            if (!accumulated) q.copy(next); else q.slerp(next, entry.weight / (accumulated + entry.weight));
            accumulated += entry.weight;
          }); q.normalize().toArray(result);
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
    var fallbackTargets = {};
    function targetsFor(kind, index) {
      var semantic = (kind === "mouth" ? 10000 : 0) + index;
      if (fallbackTargets[semantic]) return fallbackTargets[semantic];
      var preset = facePresets[semantic];
      return fallbackTargets[semantic] = preset && preset.targets || (expressions.rawChannels || []).filter(function (channel) {
        return channel.group === kind;
      }).map(function (channel) {
        var expected = (kind === "mouth" ? "MouthBlendShape.mouth_facial_" : "EyeBlendShape.eye_facial_") + ("00" + index).slice(-3);
        return { node: channel.node, index: channel.index, value: channel.name.toLowerCase() === expected.toLowerCase() ? 1 : 0 };
      });
    }
    function applyShapes(time) {
      var active = { eyes: [], mouth: [] }, contributions = {};
      sampleFrame += 1;
      shapeGroups.forEach(function (group) {
        var key = group.node.uuid + ":" + group.index;
        group.tracks.forEach(function (track) {
          var record = track.record, amount = sampleWeight(record.segment, time); if (amount <= 0) return;
          if (record.sampleFrame !== sampleFrame) { record.sample = record.staticValue; record.sampleFrame = sampleFrame; }
          if (!contributions[key]) contributions[key] = [];
          contributions[key].push({ value: record.sample[track.component], weight: amount });
        });
      });
      events.forEach(function (event) { if (active[event.kind] && !nativeEvents.has(event)) { var w = sampleWeight(event, time); if (w > 0) active[event.kind].push({ event: event, weight: w }); } });
      // Navi speech follows decoded voice amplitude between authored mouth
      // poses. MV songs always use their original vowel timeline.
      var hasAuthoredMouth = events.some(function (event) { return event.kind === "mouth" && sampleWeight(event, time) > 0; });
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
          var targets = targetsFor(kind, record.event.index);
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
    return { warnings: warnings, compatibleSegments: used, compatibilityDetails: compatibilityDetails,
      animatedProperties: function (time) {
        beginSample(time, false);
        var owned = {};
        [bodyGroups, faceGroups, gazeTrackGroups].forEach(function (collection) {
          collection.forEach(function (group) {
            var binding = group.binding, property = binding.parsedPath && binding.parsedPath.propertyName;
            if (["position", "quaternion", "scale"].indexOf(property) < 0 ||
                !group.tracks.some(function (record) { return sampleWeight(record.segment, time) > 0; })) return;
            var node = binding.targetObject || binding.node, id = node && node.userData && node.userData.elichika_node;
            if (id === undefined) return;
            if (!owned[String(id)]) owned[String(id)] = {};
            owned[String(id)][property] = true;
          });
        });
        if (gazeEvents.some(function (event) { return sampleWeight(event, time) > 0; })) {
          var gazeProperties = gaze.properties(); Object.keys(gazeProperties).forEach(function (id) { owned[id] = Object.assign(owned[id] || {}, gazeProperties[id]); });
        }
        return owned;
      },
      duration: Math.max(number(descriptor.facial && descriptor.facial.duration, 0), number(descriptor.audio && descriptor.audio.duration, 0),
        (descriptor.audio && descriptor.audio.tracks || []).reduce(function (end, track) { return Math.max(end, number(track.startTime, 0) + Math.max(0, number(track.duration, 0))); }, 0),
        (descriptor.bodySegments || []).reduce(function (end, segment) { return Math.max(end, segment.start + segment.duration); }, 0)),
      evaluate: function (time) { beginSample(time, true); evaluateGroups(bodyGroups, time); evaluateGroups(faceGroups, time); applyShapes(time);
        gaze.evaluate(gazeEvents.map(function (event) { return { target: event.target, weight: sampleWeight(event, time) }; }).filter(function (event) { return event.weight > 0; }), options.getGazeContext ? options.getGazeContext() : {});
        gaze.warnings.forEach(warn);
        if (gaze.getState().missingTargets.length) warn("An original gaze target is unavailable in this single-model preview.");
      },
      getGazeState: function () { return Object.assign(gaze.getState(), { retargeted: retargetedGaze, sourceOwner: retargetedGaze ? modelGaze.owner : descriptor.targetCharacter || null }); },
      followsGazeTarget: function () { return gazeEvents.some(function (event) { return event.target === 21 || event.target >= 37; }); },
      applyVisibility: function (time) { beginSample(time, false); visibility.forEach(function (record) {
        if (sampleWeight(record.event, time) <= .5) return;
        var track = record.track, node = nodeByIndex[String(track.node)];
        if (!node || !track.values || !track.values.length) return;
        var value = track.values[track.values.length - 1];
        node.traverse(function (child) { if (child.isMesh) child.visible = value; });
      }); }
    };
  }
  global.ViewerGaze = { create: createGaze, axes: gazeAxes };
  global.ViewerMotionTimeline = { create: create, weight: weight, curve: curve };
}(window));
