(function (global) {
  "use strict";

  // The non-particle content of the original CustomControl prefabs
  // (core/mv_studio_control_prefabs.py has the client evidence):
  //  * each clip owns one clone of its prefab, at the world root plus the clip
  //    offset, shown from the clip start to its end (PrefabControlPlayable);
  //  * MeshRenderers and SkinnedMeshRenderers draw AS/General/Transparent:
  //    _MainTex(uv * _MainTex_ST) * _TintColor (* vertex color), plus the
  //    _SATURATE_ON term, with the material's blend, cull, depth and stencil;
  //  * an Animator plays its default state from the activation on the player
  //    clock: the state time is the time since the clone was activated
  //    (display frames counted as MVStudioParticleSystems.activeFrames does),
  //    wrapped by m_LoopTime or held at the end. clipIn does not reach it.
  // Unity space is mirrored along X like the rest of the stage.

  const eulerOrders = ["ZYX", "YZX", "XZY", "ZXY", "YXZ", "XYZ"]; // as mv-studio-stage-motion.js
  const radians = Math.PI / 180;
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(finite);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 256;
  const base64 = /^[A-Za-z0-9+/]*={0,2}$/;
  const transformKinds = new Set(["translation", "rotation", "euler", "scale", "active"]);
  const rendererKinds = new Set(["enabled", "tint", "uv"]);

  function motion() {
    const stage = global.MVStudioStageMotion;
    return stage?.evaluate && stage.validCurve && stage.nativeActive ? stage : null;
  }

  function bytes(text) {
    if (typeof atob === "function") {
      const binary = atob(text), out = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
      return out;
    }
    return new Uint8Array(Buffer.from(text, "base64"));
  }

  function decode(text, Type) {
    const raw = bytes(text);
    if (raw.byteLength % Type.BYTES_PER_ELEMENT) throw new Error("misaligned array");
    // Copy into an aligned buffer; the payload is little-endian like the editor host.
    return new Type(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength));
  }

  // ---------------------------------------------------------------- validation
  function validMaterial(material, textures) {
    return !!material && vector(material.tint, 4) && vector(material.st, 4) && vector(material.blend, 2) &&
      vector(material.stencil, 4) && Number.isInteger(material.cull) && Number.isInteger(material.zTest) &&
      Number.isInteger(material.zWrite) && Number.isInteger(material.queue) &&
      (material.texture === null || (Number.isInteger(material.texture) && !!textures[material.texture]));
  }

  function validChannel(row, template, stage) {
    if (!row || !Array.isArray(row.curves) || !row.curves.every(stage.validCurve)) return false;
    if (transformKinds.has(row.kind)) {
      const width = {translation: 3, rotation: 4, euler: 3, scale: 3, active: 1}[row.kind];
      return Number.isInteger(row.target) && !!template.nodes[row.target] && row.curves.length === width &&
        (row.kind !== "euler" || row.rotationOrder === undefined || !!eulerOrders[row.rotationOrder]);
    }
    return rendererKinds.has(row.kind) && Number.isInteger(row.target) && !!template.renderers[row.target] &&
      row.curves.length === (row.kind === "enabled" ? 1 : 4);
  }

  function validDescriptor(source) {
    const stage = motion();
    const {textures, meshes, templates, cues} = source || {};
    if (!stage || source?.schema !== 1 || !Array.isArray(textures) || !Array.isArray(meshes) ||
        !Array.isArray(templates) || !Array.isArray(cues) || cues.length > 512 || templates.length > 64) return false;
    if (!textures.every(texture => Array.isArray(texture?.levels) && texture.levels.length >= 1 &&
      texture.levels.every((level, index) => typeof level?.png === "string" &&
        level.width === Math.max(1, texture.levels[0].width >> index) &&
        level.height === Math.max(1, texture.levels[0].height >> index)))) return false;
    if (!meshes.every(mesh => Number.isInteger(mesh?.vertexCount) && mesh.vertexCount > 0 &&
      typeof mesh.positions === "string" && base64.test(mesh.positions) &&
      (mesh.uv === null || typeof mesh.uv === "string") && (mesh.colors === null || typeof mesh.colors === "string") &&
      Array.isArray(mesh.submeshes) && mesh.submeshes.length > 0 && mesh.submeshes.every(row => typeof row === "string") &&
      (mesh.joints === undefined || (typeof mesh.joints === "string" && typeof mesh.weights === "string")))) return false;
    return templates.every(template => Array.isArray(template?.nodes) && template.nodes.length > 0 &&
      template.nodes.every((node, index) => vector(node?.position, 3) && vector(node.rotation, 4) &&
        vector(node.scale, 3) && typeof node.active === "boolean" &&
        (node.parent === null ? index === 0 : Number.isInteger(node.parent) && node.parent < index)) &&
      Array.isArray(template.renderers) && template.renderers.every(renderer => Number.isInteger(renderer?.node) &&
        !!template.nodes[renderer.node] && Number.isInteger(renderer.mesh) && !!meshes[renderer.mesh] &&
        Array.isArray(renderer.materials) && renderer.materials.every(material => validMaterial(material, textures)) &&
        Array.isArray(renderer.draws) && renderer.draws.every(draw => vector(draw, 2) &&
          !!renderer.materials[draw[1]] && draw[0] >= 0 && draw[0] < meshes[renderer.mesh].submeshes.length) &&
        (renderer.skin === undefined || (meshes[renderer.mesh].joints !== undefined &&
          Array.isArray(renderer.skin.bones) && renderer.skin.bones.every(bone => !!template.nodes[bone]) &&
          Array.isArray(renderer.skin.bindPoses) && renderer.skin.bindPoses.length === renderer.skin.bones.length &&
          renderer.skin.bindPoses.every(pose => vector(pose, 16)))) &&
        (renderer.sortCenter === undefined || vector(renderer.sortCenter, 3))) &&
      Array.isArray(template.animators) && template.animators.every(animator => !!template.nodes[animator?.node] &&
        finite(animator.clip?.start) && finite(animator.clip.duration) && animator.clip.duration >= 0 &&
        typeof animator.clip.loop === "boolean" && Array.isArray(animator.channels) &&
        animator.channels.every(row => validChannel(row, template, stage)))) &&
      cues.every(cue => id(cue?.trackId) && id(cue.eventId) && Number.isInteger(cue.template) &&
        !!templates[cue.template] && vector(cue.offset, 3) && typeof cue.quality === "string");
  }

  // State time of an Animator whose clone was activated `frames` display frames ago
  // (shared with the particle runtime's prefab Animator curves).
  const stateTime = (clip, frames, fps) => global.MVStudioParticleSystems.animatorTime(clip, frames, fps);

  // ---------------------------------------------------------------- rendering
  const vertexShader = `
    attribute vec2 unityUV;
    #ifdef VERTEX_COLOR
    attribute vec4 unityColor;
    #endif
    uniform vec4 uMainST;
    varying vec2 vMainUV;
    varying vec4 vColor;
    void main() {
      // Unity UV, then _MainTex_ST, then the flipped V of the loaded texture.
      vec2 unity = unityUV * uMainST.xy + uMainST.zw;
      vMainUV = vec2(unity.x, 1.0 - unity.y);
      #ifdef VERTEX_COLOR
      vColor = unityColor;
      #else
      vColor = vec4(1.0);
      #endif
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `;
  // AS/General/Transparent, as the particle runtime draws it.
  const fragmentShader = `
    uniform sampler2D uTexture;
    uniform vec4 uTint;
    varying vec2 vMainUV;
    varying vec4 vColor;
    void main() {
      vec4 texel = texture2D(uTexture, vMainUV);
      vec4 color = texel * uTint * vColor;
      #ifdef SATURATE
      vec3 square = texel.rgb * texel.rgb;
      color.rgb = square * square + color.rgb;
      #endif
      gl_FragColor = color;
    }
  `;

  function materialFor(T, systems, material, texture, colored) {
    const defines = {};
    // Unity feeds opaque white to COLOR when the mesh has no color stream.
    if (material.vertexColor && colored) defines.VERTEX_COLOR = 1;
    if (material.saturate) defines.SATURATE = 1;
    return new T.ShaderMaterial({
      name: `Original prefab ${material.name}`, vertexShader, fragmentShader, defines,
      ...systems.renderState(T, material),
      uniforms: {
        uTexture: {value: texture}, uTint: {value: new T.Vector4().fromArray(material.tint)},
        uMainST: {value: new T.Vector4().fromArray(material.st)},
      },
    });
  }

  // The vertex streams of one renderer, shared by its submesh draws (a skinned
  // renderer writes its positions once per frame).
  function streamsOf(T, mesh, skinned, center) {
    const rest = decode(mesh.positions, Float32Array);
    if (center) for (let i = 0; i < rest.length; i++) rest[i] -= center[i % 3];
    const position = new T.BufferAttribute(skinned ? new Float32Array(rest) : rest, 3);
    if (skinned) position.setUsage(T.DynamicDrawUsage);
    return {rest, position, uv: new T.BufferAttribute(mesh.uv ? decode(mesh.uv, Float32Array) :
      new Float32Array(mesh.vertexCount * 2), 2),
    color: mesh.colors ? new T.BufferAttribute(decode(mesh.colors, Float32Array), 4) : null};
  }

  function geometryOf(T, mesh, submesh, streams) {
    const geometry = new T.BufferGeometry();
    geometry.setAttribute("position", streams.position);
    geometry.setAttribute("unityUV", streams.uv);
    if (streams.color) geometry.setAttribute("unityColor", streams.color);
    geometry.setIndex(new T.BufferAttribute(decode(mesh.submeshes[submesh], Uint32Array), 1));
    return geometry;
  }

  async function apply(T, root, descriptor) {
    const systems = global.MVStudioParticleSystems, stage = motion();
    if (!root?.isObject3D || !systems?.loadTexture || !systems.renderState || !systems.activeFrames ||
        !systems.animatorTime || !stage ||
        !global.MVStudioTitle?.loadTexture || !validDescriptor(descriptor)) return null;
    const textures = [];
    try {
      for (const source of descriptor.textures) textures.push(await systems.loadTexture(T, global.MVStudioTitle, source));
      textures.push(await systems.loadTexture(T, global.MVStudioTitle, null));
    } catch {
      for (const texture of textures) texture.dispose();
      return null;
    }
    const white = textures[textures.length - 1];
    const group = new T.Group();
    group.name = "Original control prefabs";
    root.add(group);
    const euler = new T.Euler(), quaternion = new T.Quaternion();
    const point = new T.Vector3(), center = new T.Vector3();
    const entries = descriptor.cues.map(cue => ({cue, template: descriptor.templates[cue.template], clone: null,
      frames: 0, fps: 0, event: null}));
    const geometries = [];
    let tracks, disposed = false;

    function instantiate(entry) {
      const {template, cue} = entry;
      const nodes = template.nodes.map(node => {
        const object = new T.Object3D();
        object.name = node.path;
        return object;
      });
      template.nodes.forEach((node, index) => {
        const object = nodes[index];
        const position = index === 0 ? node.position.map((value, axis) => value + cue.offset[axis]) : node.position;
        object.position.set(-position[0], position[1], position[2]);
        object.quaternion.set(node.rotation[0], -node.rotation[1], -node.rotation[2], node.rotation[3]).normalize();
        object.scale.fromArray(node.scale);
        object.userData.rest = {position: object.position.clone(), quaternion: object.quaternion.clone(),
          scale: object.scale.clone(), active: node.active};
        object.visible = node.active;
        (node.parent === null ? group : nodes[node.parent]).add(object);
      });
      const renderers = template.renderers.map(renderer => {
        const mesh = descriptor.meshes[renderer.mesh], skinned = renderer.skin !== undefined;
        // three.js sorts transparent meshes by their origin; Unity by the renderer
        // bounds center. Static vertices are stored around that center.
        const sort = skinned ? null : renderer.sortCenter || [0, 0, 0];
        const streams = streamsOf(T, mesh, skinned, sort);
        const parts = renderer.draws.map(([submesh, index]) => {
          const material = renderer.materials[index];
          const texture = material.texture === null ? white : textures[material.texture];
          const geometry = geometryOf(T, mesh, submesh, streams);
          geometries.push(geometry);
          const object = new T.Mesh(geometry, materialFor(T, systems, material, texture, !!mesh.colors));
          object.name = `Original prefab ${template.name}/${renderer.path || ""}`;
          object.renderOrder = material.queue;
          object.frustumCulled = false;
          object.userData.material = material;
          return object;
        });
        const holder = new T.Object3D();
        if (skinned) {
          // Skinned vertices are written in world space around the bounds center.
          group.add(holder);
        } else {
          for (const part of parts) part.position.fromArray(sort);
          nodes[renderer.node].add(holder);
        }
        for (const part of parts) holder.add(part);
        const joints = skinned ? decode(mesh.joints, Uint16Array) : null;
        const weights = skinned ? decode(mesh.weights, Float32Array) : null;
        const poses = skinned ? renderer.skin.bindPoses.map(pose => new T.Matrix4().fromArray(pose)) : null;
        return {renderer, holder, parts, streams, enabled: renderer.enabled, joints, weights, poses,
          boneMatrices: skinned ? renderer.skin.bones.map(() => new T.Matrix4()) : null};
      });
      entry.clone = {root: nodes[0], nodes, renderers};
      nodes[0].visible = false;
    }

    function animate(entry, frames, fps) {
      const {template, clone} = entry;
      for (const [index, object] of clone.nodes.entries()) {
        const rest = object.userData.rest;
        object.position.copy(rest.position);
        object.quaternion.copy(rest.quaternion);
        object.scale.copy(rest.scale);
        object.visible = index === 0 || rest.active;
      }
      for (const state of clone.renderers) {
        state.enabled = state.renderer.enabled;
        for (const part of state.parts) {
          part.material.uniforms.uTint.value.fromArray(part.userData.material.tint);
          part.material.uniforms.uMainST.value.fromArray(part.userData.material.st);
        }
      }
      const values = [0, 0, 0, 0];
      for (const animator of template.animators) {
        // Every channel targets the Animator's own subtree, so a deactivated Animator's
        // values are never drawn. The clone root stays active (PrefabControlPlayable owns it).
        const time = stateTime(animator.clip, frames, fps);
        for (const row of animator.channels) {
          for (let lane = 0; lane < row.curves.length; lane++) values[lane] = stage.evaluate(row.curves[lane], time);
          if (transformKinds.has(row.kind)) {
            const object = clone.nodes[row.target];
            if (row.kind === "translation") object.position.set(-values[0], values[1], values[2]);
            else if (row.kind === "scale") object.scale.set(values[0], values[1], values[2]);
            else if (row.kind === "active") object.visible = row.target === 0 ? object.visible : stage.nativeActive(values[0]);
            else if (row.kind === "euler") {
              object.quaternion.setFromEuler(euler.set(values[0] * radians, -values[1] * radians, -values[2] * radians,
                eulerOrders[row.rotationOrder ?? 4]));
            } else {
              quaternion.set(values[0], -values[1], -values[2], values[3]);
              if (quaternion.lengthSq() > 0) object.quaternion.copy(quaternion.normalize());
            }
          } else {
            const state = clone.renderers[row.target];
            if (row.kind === "enabled") state.enabled = stage.nativeActive(values[0]);
            else for (const part of state.parts) {
              (row.kind === "tint" ? part.material.uniforms.uTint : part.material.uniforms.uMainST).value
                .set(values[0], values[1], values[2], values[3]);
            }
          }
        }
      }
      clone.root.updateMatrixWorld(true);
      for (const state of clone.renderers) {
        let shown = state.enabled;
        for (let node = state.renderer.node; shown && node !== null; node = template.nodes[node].parent) {
          shown = clone.nodes[node].visible;
        }
        state.holder.visible = shown;
        if (shown && state.poses) skin(state, clone);
      }
    }

    // Unity's linear blend skinning on the CPU: bone world * bind pose, per vertex weights.
    function skin(state, clone) {
      const {renderer, parts, streams, joints, weights, poses, boneMatrices} = state;
      renderer.skin.bones.forEach((bone, index) => boneMatrices[index].multiplyMatrices(clone.nodes[bone].matrixWorld, poses[index]));
      const root = renderer.skin.root ?? renderer.skin.bones[0];
      center.fromArray(renderer.skin.rootCenter || [0, 0, 0]).applyMatrix4(clone.nodes[root].matrixWorld);
      state.holder.position.copy(center);
      state.holder.updateMatrixWorld(true);
      {
        const rest = streams.rest, output = streams.position;
        const array = output.array;
        for (let vertex = 0; vertex < output.count; vertex++) {
          let x = 0, y = 0, z = 0, total = 0;
          for (let lane = 0; lane < 4; lane++) {
            const weight = weights[vertex * 4 + lane];
            if (!(weight > 0)) continue;
            const bone = boneMatrices[joints[vertex * 4 + lane]];
            if (!bone) continue;
            point.set(rest[vertex * 3], rest[vertex * 3 + 1], rest[vertex * 3 + 2]).applyMatrix4(bone);
            x += point.x * weight;
            y += point.y * weight;
            z += point.z * weight;
            total += weight;
          }
          if (total > 0) {
            array[vertex * 3] = x / total - center.x;
            array[vertex * 3 + 1] = y / total - center.y;
            array[vertex * 3 + 2] = z / total - center.z;
          }
        }
        output.needsUpdate = true;
        for (const part of parts) part.geometry.computeBoundingSphere();
      }
    }

    function hide(entry) {
      if (entry.clone) {
        entry.clone.root.visible = false;
        for (const state of entry.clone.renderers) if (state.poses) state.holder.visible = false;
      }
      entry.frames = 0;
    }

    return {
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          const byId = new Map((tracks || []).map(track => [track.id, track]));
          for (const entry of entries) {
            const track = byId.get(entry.cue.trackId);
            entry.track = track;
            entry.event = track?.events?.find(row => row.id === entry.cue.eventId) || null;
          }
        }
        const quality = project?.quality?.values;
        const fps = quality?.frame_rate_60fps === true ? 60 : 30;
        for (const entry of entries) {
          const {track, event, cue} = entry;
          const frames = track && !track.muted && event && quality?.[cue.quality] !== false ?
            systems.activeFrames(event, time, fps) : 0;
          if (!frames) {
            hide(entry);
            continue;
          }
          if (!entry.clone) {
            instantiate(entry);
            entry.clone.template = entry.template;
          }
          entry.clone.root.visible = true;
          if (entry.frames === frames && entry.fps === fps) continue;
          entry.frames = frames;
          entry.fps = fps;
          animate(entry, frames, fps);
        }
      },
      inspect(limit = 4) {
        const result = [];
        for (const entry of entries) {
          if (!entry.frames || !entry.clone) continue;
          result.push({cue: entry.cue.eventId, track: entry.cue.trackId, template: entry.template.name,
            frames: entry.frames, animatorTimes: entry.template.animators.map(animator =>
              Math.round(stateTime(animator.clip, entry.frames, entry.fps) * 1e4) / 1e4),
            renderers: entry.clone.renderers.slice(0, 64).map(state => ({path: state.renderer.path,
              visible: state.holder.visible,
              center: (state.parts[0] || state.holder).getWorldPosition(new T.Vector3()).toArray()
                .map(value => Math.round(value * 1e4) / 1e4),
              tint: state.parts[0]?.material.uniforms.uTint.value.toArray().map(value => Math.round(value * 1e4) / 1e4)}))
              .slice(0, limit * 16)});
        }
        return result;
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        root.remove(group);
        for (const geometry of geometries) geometry.dispose();
        group.traverse(object => object.material?.dispose?.());
        for (const texture of textures) texture.dispose();
      },
    };
  }

  global.MVStudioControlPrefabs = {apply, validDescriptor, stateTime, decode};
})(typeof window !== "undefined" ? window : globalThis);
