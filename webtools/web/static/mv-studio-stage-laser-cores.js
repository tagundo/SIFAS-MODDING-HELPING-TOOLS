(function (global) {
  "use strict";

  const binding = "/EntryPoint/Live/Stages/MainStage/Effect/fx_par_so2056_05/root";
  const stageBinding = "/EntryPoint/Live/Stages/MainStage/Effect/";
  const residentEmitters = new WeakSet();
  const trackId = "-3114162657147975647";
  const f32 = Math.fround;
  const sites = new Map([
    [2111430243, [1610778772, f32(.8), "01/L"]],
    [1141226888, [1610778772, f32(.8), "01/R"]],
    [4082555264, [4178303278, f32(.6), "02/L"]],
    [3398089323, [4178303278, f32(.6), "02/R"]],
  ]);
  const clockFields = ["timeScale", "clipIn", "preExtrapolationMode", "postExtrapolationMode",
    "preExtrapolationTime", "postExtrapolationTime", "easeIn", "easeOut", "blendIn", "blendOut"];
  const same = (a, b) => Array.isArray(a) && a.length === b.length && b.every((value, index) => value === a[index]);
  const rgba = value => Array.isArray(value) && value.length === 4 && value.every(v => Number.isFinite(v) && v >= 0 && v <= 1);
  const matchesNativeId = (id, suffix) => typeof id === "string" && (id === suffix || id.endsWith(`:${suffix}`));

  function checked(source) {
    return source?.binding === binding && source.trackId === trackId && source.eventId === `${trackId}:0` &&
      source.seed === 2832184784 && source.burstPeriod === f32(.08) && source.lifetime === .25 && source.capacity === 20 &&
      source.maxViewportWidth === .5 && same(source.uv, [.125, .125, .75, .125]) &&
      same(source.rollRange, [0, f32(6.283185)]) && Array.isArray(source.texture) && source.texture.length === 10 &&
      source.texture.every(index => Number.isSafeInteger(index) && index >= 0) && new Set(source.texture).size === 10 &&
      Array.isArray(source.alphaKeys) && source.alphaKeys.length === 4 && [0,655,64880,65535].every((stamp, index) =>
        same(source.alphaKeys[index], [f32(stamp / 65535), index === 1 || index === 2 ? 255 : 0])) &&
      Array.isArray(source.emitters) && source.emitters.length === sites.size &&
      new Set(source.emitters.map(row => row?.path)).size === sites.size && source.emitters.every(row => {
        const site = sites.get(row?.path);
        return site && row.activationPath === site[0] && row.size === site[1] && rgba(row.color) &&
          same(row.animatedColor, [f32(.6), f32(.8), 1, f32(.6)]);
      });
  }

  function findCarriers(root) {
    const nodes = new Map();
    root.traverse(node => {
      const tag = node.userData?.mvStageNode;
      if (tag?.binding === binding && Number.isInteger(tag.path)) nodes.set(tag.path, nodes.has(tag.path) ? null : node);
    });
    return nodes;
  }

  function emitterPose(T, root, carrier, branch) {
    const chain = [];
    for (let node = carrier; node && node !== root; node = node.parent) chain.push(node);
    if (!chain.includes(branch) || !chain.every(node => node.userData?.mvStageNode?.active === true)) return null;
    const origin = new T.Vector3(), rotation = new T.Quaternion(), translated = new T.Vector3();
    // Local scaling mode keeps the source core position and rotation when an
    // animated parent scale collapses its beam. This stock rig has no pose keys
    // on any core ancestor, so retain its unscaled pose for all particle births.
    for (const node of chain.reverse()) {
      origin.add(translated.copy(node.position).applyQuaternion(rotation));
      rotation.multiply(node.quaternion);
    }
    const paths = chain.map(node => node.userData.mvStageNode.path).filter(Number.isInteger);
    return {origin, rotation, paths};
  }

  function scheduleFor(source, branches, stationaryPaths) {
    const motion = global.MVStudioStageMotion;
    const lighting = global.MVStudioLighting;
    let tracks, track, events, event, signature, cache;
    return function schedule(project, fps) {
      if (tracks !== project?.tracks) {
        tracks = project?.tracks;
        track = tracks?.find(row => row.binding === binding && row.nativeClass === "AnimationTrack" &&
          matchesNativeId(row.id, source.trackId));
      }
      if (events !== track?.events) {
        events = track?.events;
        event = events?.find(row => matchesNativeId(row.id, source.eventId));
      }
      const values = event?.values;
      const clip = project?.stageMotion?.clips?.[values?.animation];
      const mix = project?.stageMotion?.mix?.[event?.id];
      const state = [event, mix, clip, fps, track?.muted, event?.start, event?.duration,
        ...clockFields.map(field => values?.[field])];
      if (same(signature, state)) return cache;
      signature = state;
      cache = null;
      if (!values || !mix || clip?.sampleTimeF32 !== true || clip.start !== 0 || clip.duration !== 118.81666564941406 ||
          clip.loop || !matchesNativeId(values.animation, "-7002476404608242900") || !Array.isArray(clip.channels)) return null;
      if (clip.channels.some(channel => stationaryPaths.has(channel.path) &&
          (channel.kind === "translation" || channel.kind === "rotation" || channel.kind === "euler"))) return null;
      const curves = branches.map(path => clip.channels.find(channel =>
        channel.path === path && channel.kind === "visibility")?.curves?.[0]);
      if (!curves.every(motion.validCurve)) return null;
      const weighted = motion.weightedEvent(event, mix);
      const edges = curves.map(() => []);
      const muted = track.muted;
      let through = -1;
      function weightAt(time) {
        return muted ? 0 : lighting.nativeWeight(weighted, time);
      }
      function extend(frame) {
        while (through < frame) {
          const tick = ++through, time = tick / fps;
          const local = motion.clipTime(weighted, mix, time);
          const weight = local === null ? 0 : weightAt(time);
          const sample = weight > 0 ? motion.sampleTime(clip, local) : 0;
          const rest = Math.max(0, 1 - weight);
          for (let i = 0; i < edges.length; i++) {
            const active = motion.nativeActive((motion.evaluate(curves[i], sample) * weight + rest) / (weight + rest));
            if (active !== Boolean(edges[i].length % 2)) edges[i].push(tick);
          }
        }
      }
      cache = {
        weightAt,
        activeSince(frame, branch) {
          extend(frame);
          const ticks = edges[branches.indexOf(branch)];
          let left = 0, right = ticks.length;
          while (left < right) {
            const middle = (left + right) >> 1;
            if (ticks[middle] <= frame) left = middle + 1;
            else right = middle;
          }
          return left % 2 ? ticks[left - 1] : null;
        },
      };
      return cache;
    };
  }

  async function applyLegacy(T, root, parser) {
    const source = root?.userData?.mvStageLaserCores;
    const renderer = global.MVStudioDisplayLights;
    const simulation = global.MVStudioResidentCoreSimulation;
    if (!checked(source) || !renderer || !simulation || !global.MVStudioStageMotion || !global.MVStudioLighting) return null;
    const nodes = findCarriers(root), entries = [];
    const keys = source.alphaKeys.map(([time, alpha]) => [time, 255, 255, 255, alpha]);
    for (const row of source.emitters) {
      const pose = emitterPose(T, root, nodes.get(row.path), nodes.get(row.activationPath));
      const stream = simulation.create({seed: source.seed | 0, burstPeriod: source.burstPeriod,
        lifetime: source.lifetime, rollRange: source.rollRange, capacity: source.capacity, size: row.size,
        color: {start: [255,255,255,255], keys}});
      if (!pose || !stream) return null;
      entries.push({row, pose, stream});
    }
    let maps;
    try {
      maps = await Promise.all(source.texture.map(index => parser.getDependency("texture", index)));
    } catch {
      return null;
    }
    if (!maps.every((map, level) => map?.isTexture && map.image?.width === (512 >> level) &&
        map.image?.height === (512 >> level))) return null;
    const texture = maps[0].clone();
    texture.encoding = T.LinearEncoding;
    texture.wrapS = texture.wrapT = T.RepeatWrapping;
    texture.magFilter = T.LinearFilter;
    texture.minFilter = T.LinearMipmapNearestFilter;
    texture.anisotropy = 1;
    texture.generateMipmaps = false;
    texture.mipmaps = maps.map(map => map.image);
    texture.needsUpdate = true;

    for (const entry of entries) {
      const {row, pose} = entry;
      const data = renderer.localBillboards(T, {texture, rotation: pose.rotation, capacity: source.capacity,
        maxViewportWidth: source.maxViewportWidth, atlas: source.uv, name: "Native stage laser core",
        additive: true, rolling: true});
      const {mesh} = data;
      mesh.material.stencilFunc = T.AlwaysStencilFunc;
      mesh.material.stencilRef = 0;
      mesh.renderOrder = 3010;
      mesh.name = `Native stage laser core ${sites.get(row.path)[2]}`;
      mesh.position.copy(pose.origin);
      mesh.updateMatrix();
      root.add(mesh);
      entry.data = data;
    }
    const schedule = scheduleFor(source, [...new Set(source.emitters.map(row => row.activationPath))],
      new Set(entries.flatMap(({pose}) => pose.paths)));
    function update(time, project) {
      const fps = project?.quality?.values?.frame_rate_60fps === true ? 60 : 30;
      const frame = Math.floor(time * fps + 1e-9);
      const playback = Number.isFinite(frame) && frame >= 0 && frame <= 3600 * fps &&
        project?.quality?.values?.stage_control !== false ? schedule(project, fps) : null;
      for (const {row, data, stream} of entries) {
        const {mesh, centers, colors, sizes, rolls} = data;
        const rise = playback?.activeSince(frame, row.activationPath);
        let count = 0;
        if (rise != null) {
          // Activation starts the particle system before its first update on the
          // same rendered frame; deactivation clears it and resets the seed.
          const elapsed = (frame - rise + 1) / fps, epoch = (rise - 1) / fps;
          stream.sample(elapsed, fps, (width, height, roll, _r, _g, _b, _a, birth, gradient) => {
            if (gradient === 0) return;
            const weight = playback.weightAt(epoch + birth);
            const start = row.color.map((value, index) =>
              Math.round(f32(f32(value + (row.animatedColor[index] - value) * weight) * 255)));
            const alpha = Math.floor((start[3] * gradient + 127) / 255);
            if (alpha === 0) return;
            centers.setXYZW(count, 0, 0, 0, 0);
            sizes.setXY(count, width, height);
            colors.setXYZW(count, start[0], start[1], start[2], alpha);
            rolls.setX(count, roll);
            count++;
          });
        }
        mesh.visible = count > 0;
        mesh.geometry.instanceCount = count;
        if (count) centers.needsUpdate = sizes.needsUpdate = colors.needsUpdate = rolls.needsUpdate = true;
      }
    }
    let disposed = false;
    return {update, dispose() {
      if (disposed) return;
      disposed = true;
      for (const {data: {mesh}} of entries) {
        root.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      texture.dispose();
    }};
  }

  function residentChain(root, carrier, bindingRoot, sourceBinding) {
    const chain = [];
    for (let node = carrier; node && node !== root; node = node.parent) {
      const tag = node.userData?.mvStageNode;
      if (typeof tag?.active !== "boolean") return null;
      chain.push({node, active: tag.active, path: tag.binding === sourceBinding ? tag.path : undefined});
    }
    if (!chain.some(({node}) => node === bindingRoot)) return null;
    return chain.reverse();
  }

  function residentSchedule(source, entries) {
    const motion = global.MVStudioStageMotion, lighting = global.MVStudioLighting;
    let tracks, track, events, event, signature, cache;
    return function schedule(project, fps, stageMotion) {
      if (tracks !== project?.tracks) {
        tracks = project?.tracks;
        const matches = tracks?.filter(row => row.binding === source.binding && row.nativeClass === "AnimationTrack");
        track = matches?.length === 1 ? matches[0] : null;
        events = undefined;
      }
      if (events !== track?.events) {
        events = track?.events;
        event = events?.length === 1 ? events[0] : null;
      }
      const values = event?.values;
      const clip = project?.stageMotion?.clips?.[values?.animation], mix = project?.stageMotion?.mix?.[event?.id];
      const accepted = stageMotion?.accepts?.(event) === true;
      const state = [event, mix, clip, fps, accepted, track?.muted, event?.start, event?.duration,
        ...clockFields.map(field => values?.[field])];
      if (same(signature, state)) return cache;
      signature = state;
      cache = null;
      if (!accepted || mix?.materialScope !== "world" || clip?.sampleTimeF32 !== true ||
          !Array.isArray(clip.particleStartColors)) return null;
      const visibility = new Map(clip.channels.filter(channel => channel.kind === "visibility")
        .map(channel => [channel.path, channel.curves[0]]));
      const colors = new Map(clip.particleStartColors.map(row => [row.path, row.curves]));
      const weighted = motion.weightedEvent(event, mix);
      const muted = track.muted;
      const edges = entries.map(() => []);
      let through = -1;
      function phase(time) {
        const local = muted ? null : motion.clipTime(weighted, mix, time);
        const weight = local === null ? 0 : lighting.nativeWeight(weighted, time);
        return {weight, rest: Math.max(0, 1 - weight), time: weight > 0 ? motion.sampleTime(clip, local) : 0};
      }
      function mixValue(base, curve, sample) {
        if (!curve || !(sample.weight > 0)) return base;
        return (sample.weight * motion.evaluate(curve, sample.time) + sample.rest * base) / (sample.weight + sample.rest);
      }
      cache = {
        activeSince(frame, index) {
          while (through < frame) {
            const tick = ++through, sample = phase(tick / fps);
            entries.forEach(({chain}, i) => {
              const active = chain.every(({active, path}) => motion.nativeActive(mixValue(Number(active), visibility.get(path), sample)));
              if (active !== Boolean(edges[i].length % 2)) edges[i].push(tick);
            });
          }
          const ticks = edges[index];
          let left = 0, right = ticks.length;
          while (left < right) {
            const middle = (left + right) >> 1;
            if (ticks[middle] <= frame) left = middle + 1;
            else right = middle;
          }
          return left % 2 ? ticks[left - 1] : null;
        },
        colorAt(row, time) {
          const curves = colors.get(row.path), sample = phase(time);
          return row.color.map((base, index) => {
            const value = Math.min(1, Math.max(0, mixValue(base, curves?.[index], sample)));
            return Math.round(f32(f32(value) * 255));
          });
        },
      };
      return cache;
    };
  }

  async function applyResident(T, root, parser, options = {}) {
    const sources = root?.userData?.mvStageResidentCores, renderer = global.MVStudioDisplayLights;
    const simulation = global.MVStudioResidentCoreSimulation, material = global.MVStudioStageMaterial;
    if (!Array.isArray(sources) || sources.length < 1 || sources.length > 8 ||
        !renderer || !simulation || !material?.createTextureSampler || !global.MVStudioStageMotion || !global.MVStudioLighting) return null;
    const groups = [], sampler = material.createTextureSampler(T, parser, options);
    const {active = () => true} = options;
    const nodes = new Map();
    root.traverse(node => {
      sampler.retainOriginalMaterial(node.material);
      const tag = node.userData?.mvStageNode;
      if (!tag || typeof tag.binding !== "string" || !Number.isInteger(tag.path)) return;
      if (!nodes.has(tag.binding)) nodes.set(tag.binding, new Map());
      const paths = nodes.get(tag.binding);
      paths.set(tag.path, paths.has(tag.path) ? null : node);
    });
    if (new Set(sources.map(source => source?.binding)).size !== sources.length) return null;
    for (const source of sources) {
      if (!active()) break;
      const paths = nodes.get(source?.binding);
      if (!paths?.get(0) || !source.binding.startsWith(stageBinding) || !Array.isArray(source.emitters) ||
          !source.emitters.length || source.emitters.length > 32 ||
          new Set(source.emitters.map(row => row?.path)).size !== source.emitters.length) continue;
      const entries = [];
      for (const row of source.emitters) {
        if (!row || !Number.isInteger(row.path) || row.path <= 0 || row.path > 0xffffffff ||
            !rgba(row.color) || !Number.isSafeInteger(row.texture) || row.texture < 0 ||
            !Array.isArray(row.uv) || row.uv.length !== 4 || !row.uv.every(value => Number.isFinite(value) && value >= 0 && value <= 1) ||
            row.maxViewportWidth !== .5 || !Array.isArray(row.alphaKeys) || row.alphaKeys.length !== 4 ||
            ![0, 655, 64880, 65535].every((stamp, index) =>
              same(row.alphaKeys[index], [f32(stamp / 65535), index === 1 || index === 2 ? 255 : 0]))) break;
        const carrier = paths.get(row.path), chain = residentChain(root, carrier, paths.get(0), source.binding);
        const keys = row.alphaKeys.map(([time, alpha]) => [time, 255, 255, 255, alpha]);
        const stream = simulation.create({seed: row.seed | 0, burstPeriod: row.burstPeriod,
          lifetime: row.lifetime, rollRange: row.rollRange, capacity: row.capacity, size: row.size,
          color: {start: [255, 255, 255, 255], keys}});
        if (!chain || !stream || row.seed !== (row.seed >>> 0)) break;
        sampler.reserveBase(row.texture);
        entries.push({row, carrier, chain, stream});
      }
      if (entries.length !== source.emitters.length) continue;
      for (const entry of entries) {
        if (!active()) break;
        const {row} = entry;
        const texture = await sampler.sampledNativeTexture(row.texture, row.mainSampler);
        if (texture?.image?.width !== 512 || texture?.image?.height !== 512 || texture?.mipmaps?.length !== 10) break;
        entry.texture = texture;
      }
      if (!active()) break;
      if (!entries.every(({texture}) => texture)) continue;
      for (const entry of entries) {
        const {row, carrier, texture} = entry;
        entry.data = renderer.localBillboards(T, {texture, rotation: new T.Quaternion(), capacity: row.capacity,
          maxViewportWidth: row.maxViewportWidth, atlas: row.uv, name: "Native resident stage core",
          additive: true, rolling: true, stencilEqual: false});
        const {mesh} = entry.data;
        mesh.renderOrder = 3010;
        mesh.name = `Native resident stage core ${row.path}`;
        root.add(mesh);
        residentEmitters.add(carrier);
      }
      groups.push({entries, schedule: residentSchedule(source, entries)});
    }
    if (!groups.length) {
      sampler.dispose();
      return null;
    }
    const rotation = new T.Quaternion(), translated = new T.Vector3();
    let disposed = false;
    return {
      update(time, project, stageMotion) {
        if (disposed) return;
        const fps = project?.quality?.values?.frame_rate_60fps === true ? 60 : 30;
        const frame = Math.floor(time * fps + 1e-9);
        const active = Number.isFinite(frame) && frame >= 0 && frame <= 3600 * fps &&
          project?.quality?.values?.stage_control !== false;
        for (const {entries, schedule} of groups) {
          const playback = active ? schedule(project, fps, stageMotion) : null;
          entries.forEach(({row, data, stream, chain}, index) => {
            const {mesh, centers, colors, sizes, rolls} = data;
            const rise = playback?.activeSince(frame, index);
            let count = 0;
            if (rise != null) {
              const elapsed = (frame - rise + 1) / fps, epoch = (rise - 1) / fps;
              stream.sample(elapsed, fps, (width, height, roll, _r, _g, _b, _a, birth, gradient) => {
                if (gradient === 0) return;
                const [r, g, b, alpha] = playback.colorAt(row, epoch + birth);
                const a = Math.floor((alpha * gradient + 127) / 255);
                if (a === 0) return;
                centers.setXYZW(count, 0, 0, 0, 0);
                sizes.setXY(count, width, height);
                colors.setXYZW(count, r, g, b, a);
                rolls.setX(count++, roll);
              });
            }
            mesh.visible = count > 0;
            mesh.geometry.instanceCount = count;
            if (count) {
              // Local simulation keeps the particles in the current emitter
              // basis. Local scaling ignores the animated parent scale.
              mesh.position.set(0, 0, 0);
              rotation.identity();
              for (const {node} of chain) {
                mesh.position.add(translated.copy(node.position).applyQuaternion(rotation));
                rotation.multiply(node.quaternion);
              }
              mesh.updateMatrix();
              mesh.material.uniforms.uAxisX.value.set(1, 0, 0).applyQuaternion(rotation);
              mesh.material.uniforms.uAxisY.value.set(0, 1, 0).applyQuaternion(rotation);
              centers.needsUpdate = sizes.needsUpdate = colors.needsUpdate = rolls.needsUpdate = true;
            }
          });
        }
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        for (const {entries} of groups) for (const {carrier, data: {mesh}} of entries) {
          residentEmitters.delete(carrier);
          root.remove(mesh);
          mesh.geometry.dispose();
          mesh.material.dispose();
        }
        sampler.dispose();
      },
    };
  }

  async function apply(T, root, parser, options) {
    const legacy = await applyLegacy(T, root, parser);
    const resident = await applyResident(T, root, parser, options);
    if (!legacy || !resident) return legacy || resident;
    return {
      update(time, project, stageMotion) {
        legacy.update(time, project);
        resident.update(time, project, stageMotion);
      },
      dispose() { legacy.dispose(); resident.dispose(); },
    };
  }

  global.MVStudioStageLaserCores = {apply, hasEmitter: node => residentEmitters.has(node)};
})(typeof window !== "undefined" ? window : globalThis);
