/* The game's selected dancer and facial tracks share one authored playhead. */
(function (global) {
  "use strict";
  var MASK_MIN_RATE = Math.fround(.51);
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
  function weightWithTiming(segment, time, spec, sourceWeight) {
    var local = time - segment.start, span = segment.duration, value = number(sourceWeight, number(segment.weight, 1));
    if (local < 0) return spec.preMode && local >= -spec.preTime ? value : 0;
    if (local > span) return spec.postMode && local <= span + spec.postTime ? value : 0;
    var incoming = spec.blendIn >= 0 ? spec.blendIn : spec.easeIn;
    var outgoing = spec.blendOut >= 0 ? spec.blendOut : spec.easeOut;
    if (incoming > 0 && local < incoming) value *= curve(spec.mixIn, local / incoming, local / incoming);
    if (outgoing > 0 && local > span - outgoing) value *= curve(spec.mixOut, (local - span + outgoing) / outgoing, (span - local) / outgoing);
    return clamp(value, 0, 1);
  }
  function weight(segment, time) { return weightWithTiming(segment, time, timing(segment.timing)); }
  function buildTimingIndex(records, getSegment, getTiming) {
    var ranges = [];
    for (var ordinal = 0; ordinal < records.length; ordinal += 1) {
      var record = records[ordinal], segment = getSegment ? getSegment(record) : record;
      var spec = getTiming(segment), start = segment.start, span = segment.duration;
      // Leave nonstandard inputs on the original evaluator.
      if (!Number.isFinite(start) || !Number.isFinite(span) || span < 0) return null;
      var before = spec.preMode ? Math.max(0, spec.preTime) : 0;
      var after = spec.postMode ? Math.max(0, spec.postTime) : 0;
      // Pad the coarse bounds for roundoff. The original relative-time weight
      // still makes the exact inclusive boundary and extrapolation decisions.
      var pad = 8 * Number.EPSILON * Math.max(1, Math.abs(start), span, before, after);
      var low = start - before - pad, high = start + (span + after) + pad;
      if (!Number.isFinite(low) || !Number.isFinite(high)) return null;
      ranges.push({ record: record, ordinal: ordinal, low: low, high: high });
    }
    ranges.sort(function (a, b) { return a.low - b.low || a.ordinal - b.ordinal; });
    var end = -Infinity;
    ranges.forEach(function (range) { end = Math.max(end, range.high); range.end = end; });
    return { ranges: ranges, matches: [], active: [], time: NaN };
  }
  function activeTimingRecords(index, time) {
    if (time === index.time) return index.active;
    var ranges = index.ranges, low = 0, high = ranges.length;
    while (low < high) {
      var mid = (low + high) >>> 1;
      if (ranges[mid].low <= time) low = mid + 1;
      else high = mid;
    }
    var matches = index.matches, active = index.active;
    matches.length = 0; active.length = 0;
    for (var i = low - 1; i >= 0 && ranges[i].end >= time; i -= 1) {
      if (ranges[i].high >= time) matches.push(ranges[i]);
    }
    // Quaternion blending and visibility overrides use authored traversal
    // order, irrespective of the order clips start on the timeline.
    matches.sort(function (a, b) { return a.ordinal - b.ordinal; });
    for (var j = 0; j < matches.length; j += 1) active.push(matches[j].record);
    index.time = time;
    return active;
  }
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
    var gazeWrites = options.restorePose ? [] : null;
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
    var nativeEye = eyeCandidates.length === 1 ? eyeCandidates[0] : null;
    if (nativeEye) face = nativeEye;
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
        if (gazeWrites) gazeWrites.push(group);
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
      eyePosition: function (result) { return nativeEye && nativeEye.getWorldPosition(result); },
      restorePose: function () {
        if (!gazeWrites) return;
        gazeWrites.forEach(function (group) { group.node[group.property].fromArray(group.base); });
        gazeWrites.length = 0;
      },
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
    var indexTiming = options.indexTiming === true;
    // Studio samples a standalone model. The shared rig viewer restores its
    // own pose before evaluating, including properties controlled elsewhere.
    var restoreFace = indexTiming && descriptor.category === "mv";
    var faceWrites = restoreFace ? [] : null, morphWrites = restoreFace ? [] : null;
    var visibilityWrites = restoreFace ? new Map() : null;
    var nativeEyePoses = new Map(), nativeEyeEvents = [], nativeEyeMeshes = new Map(), nativeEyeVisibility = new Map(), nativeEyeRevision = -1;
    var rendererEnabledEpsilon = Math.fround(.001);
    var timingSpecs = indexTiming ? new WeakMap() : null, timingIndexes = indexTiming ? new WeakMap() : null;
    function getTiming(segment) {
      if (!indexTiming) return timing(segment.timing);
      var spec = timingSpecs.get(segment);
      if (!spec) { spec = timing(segment.timing); timingSpecs.set(segment, spec); }
      return spec;
    }
    function timedRecords(records, time, getSegment) {
      if (!indexTiming || records.length < 8 || !Number.isFinite(time)) return records;
      if (!timingIndexes.has(records)) timingIndexes.set(records, buildTimingIndex(records, getSegment, getTiming));
      var index = timingIndexes.get(records);
      return index ? activeTimingRecords(index, time) : records;
    }
    function trackSegment(record) { return record.segment; }
    function morphSegment(track) { return track.record.segment; }
    function visibilitySegment(record) { return record.event; }
    function invalidateTiming() {
      if (indexTiming) { timingSpecs = new WeakMap(); timingIndexes = new WeakMap(); }
      sampleRevision += 1;
    }
    function beginSample(time, fresh) {
      if (fresh || sampleTime !== time) { sampleTime = time; sampleRevision += 1; }
    }
    // A masked head whose timeline has no Rina tracks runs InitializeMask's
    // LiveMemberAnimationMask instead of the default facial blend. Its eye and
    // lip mixers sum each index's input weight; ProcessFrameMask ignores sums
    // below minRateToActive (0x3f028f5c), and UpdateAnimationMask resets every
    // input and sets the requested clip to 1. The last qualifying index wins;
    // without one every input stays 0 and the head keeps its default dots.
    var selection = descriptor.facial && descriptor.facial.trackSelection;
    var maskEvents = selection && selection.mask === true ? { eyes: [], mouth: [] } : null;
    var maskMembers = maskEvents ? new Set() : null, maskWinners = {}, maskRevision = -1;
    function maskWinner(kind, time) {
      if (maskRevision !== sampleRevision) { maskRevision = sampleRevision; maskWinners = {}; }
      if (maskWinners[kind]) return maskWinners[kind];
      var sums = new Map(), first = new Map(), winner = null;
      timedRecords(maskEvents[kind], time).forEach(function (event) {
        var amount = splitGate(event) ? weightWithTiming(event, time, getTiming(event)) : 0;
        if (!(amount > 0)) return;
        sums.set(event.index, Math.fround(Math.fround(sums.get(event.index) || 0) + Math.fround(amount)));
        if (!first.has(event.index)) first.set(event.index, event);
      });
      sums.forEach(function (rate, index) { if (!(MASK_MIN_RATE > rate)) winner = first.get(index); });
      return maskWinners[kind] = { event: winner };
    }
    // LiveMemberLipSync.Initialize stores WeightRate = MemberFaceData.LipSync.Weight
    // for AnimationForLipsync (A, I, U, E, O, N = 1..6) and 1 for every other
    // index; ProcessFrameDefault sets each input weight to w * WeightRate.
    var head = info.memberHead || {}, lipSyncRate = typeof head.lipSyncWeight === "number" && isFinite(head.lipSyncWeight) ?
      Math.fround(clamp(head.lipSyncWeight, 0, 1)) : 1;
    function inputRate(segment) {
      return lipSyncRate !== 1 && segment.kind === "mouth" && segment.index >= 1 && segment.index <= 6 ? lipSyncRate : 1;
    }
    // MemberEyeMixer.Process: when the clip's splitScreenSetting.UseSetting is
    // set and LiveCoreCameraManager.IsSplitScreenEnabled (the SplitScreenEffect
    // object is active), the input adds setting.Weight to setting.Index instead
    // of clip.weight to clip.index. The alternate is a twin input that shares
    // the clip's timing; exactly one of the pair is live for a split state.
    var splitActive = false, splitTwins = new WeakMap();
    function splitGate(segment) {
      var primary = splitTwins.get(segment);
      if (primary) return splitActive && primary.splitUse !== false;
      if (Number.isInteger(segment.splitIndex) && segment.splitUse !== false) return !splitActive;
      return true;
    }
    function sampleSegment(segment, time) {
      var sample = sampledSegments.get(segment);
      if (!sample) { sample = {}; sampledSegments.set(segment, sample); }
      if (sample.revision !== sampleRevision) {
        var spec = getTiming(segment);
        sample.revision = sampleRevision;
        var rate = inputRate(segment);
        sample.weight = !splitGate(segment) ? 0 : maskMembers && maskMembers.has(segment) ? (maskWinner(segment.kind, time).event === segment ? 1 : 0) :
          rate === 1 ? weightWithTiming(segment, time, spec) : Math.fround(Math.fround(weightWithTiming(segment, time, spec)) * rate);
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
    function isNativeRendererTrack(track) {
      return track.sourceProperty === "Renderer.m_Enabled" && track.interpolation === "STEP" &&
        track.times && track.times.length && track.values && track.times.length === track.values.length;
    }
    if (restoreFace) {
      var sourceWhiteLines = new Set();
      clips.forEach(function (entry) {
        if (entry.sourceRole !== "facial" || entry.bindingComplete !== true || !/(?:^|_)LiveFacial_eye_\d+(?:__\d+)?$/.test(entry.sourceName || entry.name)) return;
        (entry.visibility || []).forEach(function (track) { if (isNativeRendererTrack(track)) sourceWhiteLines.add(String(track.node)); });
      });
      Object.keys(nodeByIndex).forEach(function (id) {
        var node = nodeByIndex[id], meshes = [];
        // The original display_OnOff leaves are flattened into the actor mesh
        // list. The source catalog also identifies them on older GLB exports.
        if (!/^(?:Left|Right)EyeWhiteLine$/.test(node.userData.originalName || node.name.replace(/__\d+$/, ""))) return;
        node.traverse(function (child) { if (child.isMesh) meshes.push(child); });
        if (!sourceWhiteLines.has(id) && !meshes.some(function (mesh) {
          var depth = mesh.geometry.userData.mvStageCameraDepth, bones = mesh.skeleton && mesh.skeleton.bones;
          return depth && depth.kind === "memberFace" && bones && bones.length === 1 &&
            bones[0] && bones[0].userData.originalName === "display_OnOff";
        })) return;
        nativeEyeMeshes.set(id, meshes);
        meshes.forEach(function (mesh) { nativeEyeVisibility.set(mesh, []); });
      });
    }
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
    function register(collection, clip, segment, staticPose, gazeOnly, eyePose) {
      var registered = 0;
      clip.tracks.forEach(function (track) {
        var key = track.name, group = collection[key], binding = group && group.binding || bindingsByName.get(key);
        if (!binding) { binding = THREE.PropertyBinding.create(root, key); binding.bind(); bindingsByName.set(key, binding); }
        if (gazeOnly && (!binding.node || !binding.node.isBone || !/^(?:Left|Right)Eye(?:[12]|_Root)$/.test(binding.node.userData.originalName || binding.node.name.replace(/__\d+$/, "")))) return;
        var base = new Array(track.getValueSize()); binding.getValue(base, 0);
        if (!denseFinite(base)) return;
        var node = binding.targetObject || binding.node;
        var morph = collection === facialGroups && binding.parsedPath && binding.parsedPath.propertyName === "morphTargetInfluences";
        var synchronized = morph && eyePose && nativeEyeVisibility.has(node);
        if (synchronized && eyePose.tracks.has(track)) { registered += 1; return; }
        var staticValue = null;
        if (staticPose && !synchronized) {
          var endpoints = staticSamples.get(track);
          if (!endpoints) { endpoints = new Map(); staticSamples.set(track, endpoints); }
          staticValue = endpoints.get(clip.duration);
          if (!staticValue) { staticValue = track.createInterpolant().evaluate(clip.duration); endpoints.set(clip.duration, staticValue); }
        }
        var record = { segment: segment, interpolant: !staticPose || synchronized ? track.createInterpolant() : null, staticValue: staticValue, duration: clip.duration, staticPose: !!staticPose,
          weightedSample: { value: null, weight: 0 } };
        if (morph) {
          var channel = binding.propertyIndex;
          if (!node || !node.morphTargetInfluences) return;
          var first = channel === undefined ? 0 : Number(channel), count = channel === undefined ? base.length : 1;
          if (!Number.isInteger(first) || !isFinite(node.morphTargetInfluences[first]) || (channel === undefined && count !== node.morphTargetInfluences.length)) return;
          if (synchronized) eyePose.tracks.add(track);
          for (var index = 0; index < count; index += 1) {
            var groupForMorph = morphGroup(node, first + index), row = { record: record, component: index };
            if (synchronized) {
              if (!groupForMorph.nativeEyeTracks) groupForMorph.nativeEyeTracks = [];
              row.pose = eyePose;
              groupForMorph.nativeEyeTracks.push(row);
            } else groupForMorph.tracks.push(row);
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
    var events = descriptor.facial && descriptor.facial.events || [], gazeEvents = [], cheekEvents = [];
    if (events.some(function (event) { return event.kind === "eyes" && Number.isInteger(event.splitIndex); })) {
      // Each twin directly follows its clip, so the eye mixer's per-index
      // insertion order (and the mask's last-index rule) stays the original.
      events = events.slice(0, 12000).reduce(function (list, event) {
        list.push(event);
        if (event.kind !== "eyes" || !Number.isInteger(event.splitIndex)) return list;
        var twin = Object.create(event, {
          index: { value: event.splitIndex, enumerable: true },
          weight: { get: function () { return Number.isFinite(event.splitWeight) ? event.splitWeight : 0; }, enumerable: true }
        });
        splitTwins.set(twin, event);
        list.push(twin);
        return list;
      }, []);
    }
    if (maskEvents) events.slice(0, 12000).forEach(function (event) {
      if (maskEvents[event.kind]) { maskEvents[event.kind].push(event); maskMembers.add(event); }
    });
    var modelGaze = info.expressionCatalog && info.expressionCatalog.gaze, retargetedGaze = !!(modelGaze && modelGaze.available &&
      Number.isInteger(modelGaze.owner) && Number.isInteger(descriptor.targetCharacter) && modelGaze.owner !== descriptor.targetCharacter);
    // LiveCoreMemberHead gives LiveMemberLipSync the face's own
    // MemberFaceData.animationTableMouth, and LiveMemberEyeAnimation and
    // LiveMemberEyeContact its animationTableEye (rig memberHead.facialTables,
    // rows in serialized order). A motion's explicit table for a kind wins.
    var faceTables = {};
    ["eyes", "mouth"].forEach(function (kind) {
      var rows = head.facialTables && head.facialTables[kind];
      if (!Array.isArray(rows) || (descriptor.facialClips || []).some(function (entry) { return entry.kind === kind; })) return;
      faceTables[kind] = rows.slice(0, 256).map(function (row) { return Object.assign({ kind: kind }, row); });
    });
    // Direction indices are the game's common six-pose semantics. When a
    // retained motion belongs to another character, use this face's verified
    // endpoints instead of writing the old character's absolute iris positions.
    var gaze = createGaze(root, animations, info, {
      aliases: retargetedGaze ? modelGaze.clips : (descriptor.facialClips || []).concat(faceTables.eyes || []), restorePose: restoreFace
    });
    // Live heads create playables only for MemberEyeClip / MemberLipSyncClip
    // AnimationIndex values (Initialize walks Enum.GetValues of that enum).
    function liveFacialId(kind, index) {
      return kind === "mouth" ? index >= 0 && index <= 20 || index === 101 || index === 102 || index === 999 :
        index >= 1 && index <= 5 || index >= 12 && index <= 25 || index === 101 || index === 102 || index === 900 || index === 999;
    }
    var silentEvents = new Set(), fallbackIndexes = new Map();
    function resolveFacial(event, kind) {
      if (descriptor.category === "mv" && !liveFacialId(event.kind, event.index)) return { none: true };
      var table = faceTables[event.kind], alias;
      if (table) {
        // CreateAnimationClip plays the first row with this index (FirstOrDefault),
        // whatever its customIndex; no row means no playable for the index.
        alias = table.filter(function (row) { return row.index === event.index; }).slice(0, 1);
        if (!alias.length) { warn("Some original facial indices are not in this face's animation table and are not played."); return { none: true }; }
      } else alias = (descriptor.facialClips || []).filter(function (entry) { return entry.kind === event.kind && entry.index === event.index; });
      // An original row whose clip is null creates no playable either.
      if (alias.length && alias.every(function (entry) { return !entry.sourceHash; })) return { none: true };
      var pattern = new RegExp("(?:^|_)LiveFacial_" + kind + "_0*" + event.index + "(?:__\\d+)?$");
      var matches = clips.filter(function (entry) {
        return animationByName[entry.name] && (alias.length ? alias.some(function (facial) { return facial.sourceHash === entry.sourceHash && facial.sourceName === entry.sourceName; }) : pattern.test(entry.sourceName || entry.name));
      });
      // Should the clip itself be unavailable, a shape fallback follows the
      // clip the row names (mouth 13 -> mouth_004), not the timeline index.
      var named = alias.length && /(?:^|_)LiveFacial_(?:eye|mouth)_0*(\d+)(?:__\d+)?$/.exec(alias[0].sourceName || "");
      return { matches: matches, index: named ? Number(named[1]) : event.index };
    }
    function getNativeEyePose(event, entry, identity) {
      if (!nativeEyeVisibility.size || event.kind !== "eyes" || typeof event.nativeEventId !== "string" ||
          entry.sourceRole !== "facial" || entry.bindingComplete !== true) return null;
      if (nativeEyePoses.has(identity)) return nativeEyePoses.get(identity);
      var pose = { duration: Math.fround(number(entry.duration, animationByName[entry.name].duration)),
        visibility: new Set(), tracks: new Set(), weight: 0, time: 0 };
      nativeEyePoses.set(identity, pose);
      (entry.visibility || []).forEach(function (track) {
        var meshes = nativeEyeMeshes.get(String(track.node));
        if (!meshes || !isNativeRendererTrack(track)) return;
        pose.visibility.add(track);
        var keys = track.sourceScalarKeys;
        if (!Array.isArray(keys) || !keys.length || !keys.every(function (key, index) {
          return Array.isArray(key) && key.length === 5 && denseFinite(key) && (!index || keys[index - 1][0] < key[0]);
        })) keys = null;
        meshes.forEach(function (mesh) {
          nativeEyeVisibility.get(mesh).push({ pose: pose, track: track, keys: keys });
        });
      });
      return pose;
    }
    function sampleNativeEyes(time) {
      if (!nativeEyeEvents.length || nativeEyeRevision === sampleRevision) return;
      nativeEyeRevision = sampleRevision;
      nativeEyePoses.forEach(function (pose) { pose.weight = 0; });
      timedRecords(nativeEyeEvents, time, visibilitySegment).forEach(function (row) {
        var pose = row.pose, amount = Math.fround(sampleWeight(row.event, time));
        if (amount > 0) pose.weight = Math.fround(pose.weight + amount);
      });
      // The native eye mixer uses the accumulated input for both its
      // playable weight and its absolute time within the source clip.
      nativeEyePoses.forEach(function (pose) { pose.time = Math.fround(pose.duration * pose.weight); });
    }
    function nativeRendererValue(row, time) {
      var index = 0;
      var keys = row.keys, track = row.track;
      if (keys) {
        var phase = clamp(time, 0, row.pose.duration);
        while (index + 1 < keys.length && keys[index + 1][0] <= phase) index += 1;
        var key = keys[index], delta = Math.fround(phase - key[0]);
        var value = Math.fround(Math.fround(key[1] * delta) + key[2]);
        value = Math.fround(Math.fround(value * delta) + key[3]);
        return Math.fround(Math.fround(value * delta) + key[4]);
      }
      while (index + 1 < track.times.length && track.times[index + 1] <= time) index += 1;
      return track.values[index] ? 1 : 0;
    }
    events.slice(0, 12000).forEach(function (event) {
      if (event.kind === "gaze") {
        gazeEvents.push(event);
        return;
      }
      if (event.kind === "cheek") {
        cheekEvents.push(event);
        return;
      }
      if (event.kind !== "eyes" && event.kind !== "mouth") return;
      var kind = event.kind === "eyes" ? "eye" : "mouth", identity = event.kind + ":" + event.index, resolution = facialMatches.get(identity);
      if (!resolution) facialMatches.set(identity, resolution = resolveFacial(event, kind));
      if (resolution.none) { silentEvents.add(event); return; }
      if (resolution.index !== event.index) fallbackIndexes.set(event, resolution.index);
      var matches = resolution.matches;
      var entry = matches.length === 1 ? matches[0] : null, eyePose = entry && getNativeEyePose(event, entry, identity);
      if (entry && register(facialGroups, animationByName[entry.name], event, true, false, eyePose)) {
        if (eyePose) nativeEyeEvents.push({ event: event, pose: eyePose });
        (entry.visibility || []).forEach(function (track) {
          if (!eyePose || !eyePose.visibility.has(track)) visibility.push({ event: event, track: track });
        });
        nativeEvents.add(event);
      } else {
        var preset = facePresets[(kind === "mouth" ? 10000 : 0) + resolution.index];
        var presetBound = preset && (preset.targets || []).some(function (target) { return !!faceChannels[target.node + ":" + target.index]; });
        var rawMatch = (expressions.rawChannels || []).some(function (channel) {
          var expected = (kind === "mouth" ? "MouthBlendShape.mouth_facial_" : "EyeBlendShape.eye_facial_") + ("00" + resolution.index).slice(-3);
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
    function evaluateGroups(collection, time, writes) {
      collection.forEach(function (group) {
        var values = group.values, total = 0; values.length = 0;
        timedRecords(group.tracks, time, trackSegment).forEach(function (record) {
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
        if (writes) writes.push(group);
      });
    }
    var fallbackTargets = {};
    function targetsFor(kind, index) {
      var semantic = (kind === "mouth" ? 10000 : 0) + index;
      if (fallbackTargets[semantic]) return fallbackTargets[semantic];
      var preset = facePresets[semantic];
      if (preset && preset.targets) return fallbackTargets[semantic] = preset.targets;
      var expected = ((kind === "mouth" ? "MouthBlendShape.mouth_facial_" : "EyeBlendShape.eye_facial_") + ("00" + index).slice(-3)).toLowerCase();
      var channels = (expressions.rawChannels || []).filter(function (channel) { return channel.group === kind; });
      // An index without a shape of its own is unresolved: it contributes
      // nothing, rather than a zero pose that closes every other channel.
      if (!channels.some(function (channel) { return channel.name.toLowerCase() === expected; })) return fallbackTargets[semantic] = [];
      return fallbackTargets[semantic] = channels.map(function (channel) {
        return { node: channel.node, index: channel.index, value: channel.name.toLowerCase() === expected ? 1 : 0 };
      });
    }
    function applyShapes(time) {
      var active = { eyes: [], mouth: [] }, contributions = {};
      sampleFrame += 1;
      sampleNativeEyes(time);
      shapeGroups.forEach(function (group) {
        var key = group.node.uuid + ":" + group.index;
        timedRecords(group.tracks, time, morphSegment).forEach(function (track) {
          var record = track.record, amount = sampleWeight(record.segment, time); if (amount <= 0) return;
          if (record.sampleFrame !== sampleFrame) { record.sample = record.staticValue; record.sampleFrame = sampleFrame; }
          if (!contributions[key]) contributions[key] = [];
          contributions[key].push({ value: record.sample[track.component], weight: amount });
        });
        if (group.nativeEyeTracks) group.nativeEyeTracks.forEach(function (track) {
          var pose = track.pose, record = track.record;
          if (pose.weight <= 0) return;
          if (record.sampleFrame !== sampleFrame) { record.sample = record.interpolant.evaluate(pose.time); record.sampleFrame = sampleFrame; }
          if (!contributions[key]) contributions[key] = [];
          contributions[key].push({ value: record.sample[track.component], weight: pose.weight, nativeEye: true });
        });
      });
      var activeEvents = timedRecords(events, time);
      activeEvents.forEach(function (event) { if (active[event.kind] && !nativeEvents.has(event) && !silentEvents.has(event)) { var w = sampleWeight(event, time); if (w > 0) active[event.kind].push({ event: event, weight: w }); } });
      // Navi speech follows decoded voice amplitude between authored mouth
      // poses. MV songs always use their original vowel timeline.
      var hasAuthoredMouth = (!indexTiming || descriptor.category !== "mv") && activeEvents.some(function (event) {
        return event.kind === "mouth" && sampleWeight(event, time) > 0;
      });
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
          var targets = targetsFor(kind, fallbackIndexes.has(record.event) ? fallbackIndexes.get(record.event) : record.event.index);
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
        var entries = contributions[key], nativeEye = group.nativeEyeTracks && entries.every(function (entry) { return entry.nativeEye; });
        entries.forEach(function (entry) {
          total = nativeEye ? Math.fround(total + entry.weight) : total + entry.weight;
          value = nativeEye ? Math.fround(value + Math.fround(entry.value * entry.weight)) : value + entry.value * entry.weight;
        });
        var remainder = Math.max(0, 1 - total);
        group.node.morphTargetInfluences[group.index] = nativeEye ? Math.fround(Math.fround(group.base * Math.fround(remainder)) + value) :
          (group.base * remainder + value) / Math.max(1, total);
        if (morphWrites) morphWrites.push(group);
      });
    }
    function evaluatePose(time, context) {
      splitActive = !!(context && context.split);
      beginSample(time, true);
      if (restoreFace) {
        faceWrites.forEach(function (group) { group.binding.setValue(group.base, 0); });
        morphWrites.forEach(function (group) { group.node.morphTargetInfluences[group.index] = group.base; });
        faceWrites.length = morphWrites.length = 0;
        gaze.restorePose();
      }
      // Reapply dance first because some body clips bind the same properties.
      evaluateGroups(bodyGroups, time);
      evaluateGroups(faceGroups, time, faceWrites);
      applyShapes(time);
    }
    function evaluateGaze(time, context) {
      context = context || (options.getGazeContext ? options.getGazeContext() : {});
      var requests = [];
      timedRecords(gazeEvents, time).forEach(function (event) {
        var alternate = context && context.split && Number.isInteger(event.splitTarget);
        var amount = alternate ? weightWithTiming(event, time, getTiming(event), event.splitWeight) : sampleWeight(event, time);
        if (amount > 0) requests.push({ target: alternate ? event.splitTarget : event.target, weight: amount });
      });
      gaze.evaluate(requests, context);
      gaze.warnings.forEach(warn);
      if (gaze.getState().missingTargets.length) warn(restoreFace ? "The original gaze target is unavailable in this preview." :
        "An original gaze target is unavailable in this single-model preview.");
    }
    return { warnings: warnings, compatibleSegments: used, compatibilityDetails: compatibilityDetails, invalidateTiming: invalidateTiming,
      evaluatePose: evaluatePose, evaluateGaze: evaluateGaze, eyePosition: gaze.eyePosition,
      animatedProperties: function (time) {
        beginSample(time, false);
        var owned = {};
        [bodyGroups, faceGroups, gazeTrackGroups].forEach(function (collection) {
          collection.forEach(function (group) {
            var binding = group.binding, property = binding.parsedPath && binding.parsedPath.propertyName;
            if (["position", "quaternion", "scale"].indexOf(property) < 0 ||
                !timedRecords(group.tracks, time, trackSegment).some(function (record) { return sampleWeight(record.segment, time) > 0; })) return;
            var node = binding.targetObject || binding.node, id = node && node.userData && node.userData.elichika_node;
            if (id === undefined) return;
            if (!owned[String(id)]) owned[String(id)] = {};
            owned[String(id)][property] = true;
          });
        });
        if (timedRecords(gazeEvents, time).some(function (event) { return sampleWeight(event, time) > 0; })) {
          var gazeProperties = gaze.properties(); Object.keys(gazeProperties).forEach(function (id) { owned[id] = Object.assign(owned[id] || {}, gazeProperties[id]); });
        }
        return owned;
      },
      duration: Math.max(number(descriptor.facial && descriptor.facial.duration, 0), number(descriptor.audio && descriptor.audio.duration, 0),
        (descriptor.audio && descriptor.audio.tracks || []).reduce(function (end, track) { return Math.max(end, number(track.startTime, 0) + Math.max(0, number(track.duration, 0))); }, 0),
        (descriptor.bodySegments || []).reduce(function (end, segment) { return Math.max(end, segment.start + segment.duration); }, 0)),
      evaluate: function (time) {
        evaluatePose(time);
        evaluateGaze(time);
      },
      // MemberCheekMixer.Process runs per active input: ApplyEnable(true), then
      // ApplyCheek(cheekType, intensity * weight) overwrites the material, so the
      // last active input wins. PostProcess only disables _CHEEK_ON when no input
      // ran; the floats keep the last applied values. During playback that is the
      // end of the latest finished clip, which is used here so a seek gives the
      // same values. Before any clip ResetAll's 0/0 stays (null).
      cheek: function (time) {
        beginSample(time, false);
        var state = null;
        function applied(event, amount, enabled) {
          return { index: event.index, intensity: Math.fround(Math.fround(number(event.intensity, 0)) * Math.fround(amount)), enabled: enabled };
        }
        timedRecords(cheekEvents, time).forEach(function (event) {
          var amount = sampleWeight(event, time);
          if (amount > 0) state = applied(event, amount, true);
        });
        if (state) return state;
        var latest = -Infinity;
        cheekEvents.forEach(function (event) {
          var end = event.start + event.duration;
          if (!(end <= time) || end < latest || !(number(event.weight, 1) > 0)) return;
          latest = end;
          state = applied(event, weightWithTiming(event, end, getTiming(event)), false);
        });
        return state;
      },
      getGazeState: function () { return Object.assign(gaze.getState(), { retargeted: retargetedGaze, sourceOwner: retargetedGaze ? modelGaze.owner : descriptor.targetCharacter || null }); },
      followsGazeTarget: function () { return gazeEvents.some(function (event) { return event.target === 21 || event.target >= 37; }); },
      applyVisibility: function (time) {
        beginSample(time, false);
        if (visibilityWrites) {
          visibilityWrites.forEach(function (shown, mesh) { mesh.visible = shown; });
          visibilityWrites.clear();
        }
        timedRecords(visibility, time, visibilitySegment).forEach(function (record) {
          if (sampleWeight(record.event, time) <= .5) return;
          var track = record.track, node = nodeByIndex[String(track.node)];
          if (!node || !track.values || !track.values.length) return;
          var value = track.values[track.values.length - 1];
          node.traverse(function (child) {
            if (!child.isMesh) return;
            if (visibilityWrites && !visibilityWrites.has(child)) visibilityWrites.set(child, child.visible);
            child.visible = value;
          });
        });
        sampleNativeEyes(time);
        nativeEyeVisibility.forEach(function (rows, mesh) {
          var value = 0;
          rows.forEach(function (row) {
            var pose = row.pose;
            if (pose.weight <= 0) return;
            value = Math.fround(value + Math.fround(nativeRendererValue(row, pose.time) * pose.weight));
          });
          // InitializeDefault disables display_OnOff before binding the eye
          // playables. An idle or unbound input contributes the disabled state.
          if (!visibilityWrites.has(mesh)) visibilityWrites.set(mesh, mesh.visible);
          mesh.visible = Math.abs(value) > rendererEnabledEpsilon;
        });
      }
    };
  }
  global.ViewerGaze = { create: createGaze, axes: gazeAxes };
  global.ViewerMotionTimeline = { create: create, weight: weight, curve: curve };
}(window));
