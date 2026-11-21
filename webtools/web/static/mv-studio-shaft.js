(function (global) {
  "use strict";

  const colorChange = Math.fround(1e-5), visibleAlpha = Math.fround(.01);
  const vertexShader = [
    "attribute vec4 shaftColor;",
    "varying vec4 vColor;",
    "void main() {",
    "  vColor = shaftColor;",
    "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
    "}"
  ].join("\n");
  const fragmentShader = [
    "uniform vec4 uTint;",
    "varying vec4 vColor;",
    "void main() { gl_FragColor = vColor * uTint; }"
  ].join("\n");

  async function prepare(T, gltf) {
    const sources = gltf.scene.userData.mvShaftTemplates;
    if (!Array.isArray(sources) || !gltf.parser) return null;
    const templates = new Map();
    function dispose() {
      for (const template of templates.values()) template.geometry.dispose();
      templates.clear();
    }
    try {
      for (const source of sources) {
        if (!source || !source.nodes?.length || templates.has(source.index)) continue;
        const layout = source.geometry;
        const [position, color, index] = await Promise.all([layout.position, layout.color, layout.index]
          .map(id => gltf.parser.getDependency("accessor", id)));
        if (position.itemSize !== 3 || color.itemSize !== 4 || color.count !== position.count || index.itemSize !== 1) {
          throw new Error("Invalid native spotlight shaft geometry.");
        }
        const geometry = new T.BufferGeometry();
        geometry.setAttribute("position", position);
        geometry.setAttribute("shaftColor", color);
        geometry.setIndex(index);
        templates.set(source.index, { ...source, geometry });
      }
    } catch (error) {
      dispose();
      throw error;
    }
    return templates.size ? { templates, dispose } : null;
  }

  function restoreNode(node, source) {
    node.position.fromArray(source.translation);
    node.quaternion.fromArray(source.rotation);
    node.scale.fromArray(source.scale);
  }

  function instance(T, template, memberRoot) {
    const chain = template.nodes.map(source => {
      const node = new T.Group();
      node.name = source.name;
      restoreNode(node, source);
      return node;
    });
    for (let i = 1; i < chain.length; i++) chain[i - 1].add(chain[i]);
    const tint = new T.Vector4().fromArray(template.material.tint);
    const material = new T.ShaderMaterial({
      vertexShader, fragmentShader, transparent: true, depthTest: false, depthWrite: false,
      toneMapped: false, side: T.DoubleSide, blending: T.CustomBlending,
      blendSrc: T.SrcAlphaFactor, blendDst: T.OneFactor, blendSrcAlpha: T.SrcAlphaFactor, blendDstAlpha: T.OneFactor,
      uniforms: { uTint: { value: tint } }
    });
    material.name = "Native member spotlight shaft";
    const mesh = new T.Mesh(template.geometry, material);
    mesh.name = "Native member spotlight shaft";
    mesh.renderOrder = template.material.queue;
    mesh.visible = false;
    // The mesh is the AxisBillboard rotation target. Its parent preserves the
    // serialized renderer transform, even when it is also the prefab root.
    chain[chain.length - 1].add(mesh);
    memberRoot.add(chain[0]);
    return { template, chain, root: chain[0], mesh, material, tint };
  }

  function mix(events, time, project, parameters, previousIndex) {
    const lighting = global.MVStudioLighting;
    const { color, scale } = parameters;
    color.set(0, 0, 0, 0);
    scale.set(1, 1, 1);
    parameters.height = 0;
    parameters.smoothTime = 0;
    parameters.index = previousIndex;
    for (const event of events) {
      const value = event.values;
      if (value?.playableClass !== "LiveMemberSpotLightShaftClip") continue;
      const weight = lighting.nativeWeight(event, time);
      if (weight <= 0) continue;
      const rgba = lighting.memberColor(project, value.colorSpecifiedType, value.memberPosition, value.color);
      if (rgba) {
        color.x += weight * rgba[0];
        color.y += weight * rgba[1];
        color.z += weight * rgba[2];
        color.w += weight * rgba[3];
      }
      const source = value.scale;
      if (source && Number.isFinite(source.x) && Number.isFinite(source.y) && Number.isFinite(source.z)) {
        scale.x += weight * source.x;
        scale.y += weight * source.y;
        scale.z += weight * source.z;
      }
      if (Number.isFinite(value.offsetHeight)) parameters.height += weight * value.offsetHeight;
      if (Number.isFinite(value.smoothTime)) parameters.smoothTime += weight * value.smoothTime;
      if (Number.isInteger(value.drawObjectIndex)) parameters.index = value.drawObjectIndex;
    }
  }

  // Unity Vector3.SmoothDamp with the stock unlimited max speed.
  function smoothDamp(position, target, velocity, smoothTime, deltaTime, change, impulse) {
    const omega = 2 / Math.max(.0001, smoothTime);
    const x = omega * deltaTime;
    const attenuation = 1 / (1 + x + .48 * x * x + .235 * x * x * x);
    change.subVectors(position, target);
    impulse.copy(velocity).addScaledVector(change, omega).multiplyScalar(deltaTime);
    velocity.addScaledVector(impulse, -omega).multiplyScalar(attenuation);
    position.copy(change).add(impulse).multiplyScalar(attenuation);
    if (change.dot(position) < 0) {
      position.set(0, 0, 0);
      velocity.set(0, 0, 0);
    }
    position.add(target);
  }

  function worldRotation(object, target) {
    target.identity();
    for (let node = object; node; node = node.parent) target.premultiply(node.quaternion);
    return target;
  }

  function create(T, prepared, memberRoot, moveNode) {
    if (!prepared?.templates.size || !memberRoot?.isObject3D || !moveNode?.isObject3D || !global.MVStudioLighting) return null;
    const variants = new Map();
    for (const template of prepared.templates.values()) variants.set(template.index, instance(T, template, memberRoot));
    const parameters = { color: new T.Vector4(), scale: new T.Vector3() };
    const colorCache = new T.Vector4(), lastPosition = new T.Vector3(), moveVelocity = new T.Vector3();
    const position = new T.Vector3(), target = new T.Vector3(), change = new T.Vector3(), impulse = new T.Vector3();
    const up = new T.Vector3(), worldUp = new T.Vector3(0, 1, 0);
    const right = new T.Vector3(), forward = new T.Vector3(), basis = new T.Matrix4(), rotation = new T.Quaternion();
    const parentRotation = new T.Quaternion(), cacheDifference = new T.Vector4();
    let selected = variants.get(0), index = 0, force = false, cacheValid = false;

    function reset() {
      for (const variant of variants.values()) {
        variant.mesh.visible = false;
        variant.mesh.quaternion.identity();
        variant.tint.fromArray(variant.template.material.tint);
        variant.chain.forEach((node, i) => restoreNode(node, variant.template.nodes[i]));
      }
      selected = variants.get(0);
      index = 0;
      force = false;
      cacheValid = false;
      lastPosition.set(0, 0, 0);
      moveVelocity.set(0, 0, 0);
    }

    function point(object, direction, vertical) {
      right.crossVectors(vertical, direction);
      if (right.lengthSq() <= 1e-12) return;
      right.normalize();
      forward.crossVectors(right, vertical).normalize();
      rotation.setFromRotationMatrix(basis.makeBasis(right, vertical, forward));
      // Unity Transform.rotation composes quaternions independently of parent scale.
      worldRotation(object.parent, parentRotation);
      object.quaternion.copy(parentRotation.invert()).multiply(rotation);
    }

    function frame(events, time, deltaTime, mainCamera, project, resetClock = false) {
      if (resetClock) reset();
      if (!events?.length) {
        if (selected) selected.mesh.visible = false;
        force = false;
        cacheValid = false;
        return false;
      }
      mix(events, time, project, parameters, index);
      if (parameters.index !== index) {
        if (selected) selected.mesh.visible = false;
        force = false;
        const next = variants.get(parameters.index);
        if (next) {
          index = parameters.index;
          selected = next;
          force = true;
          selected.mesh.visible = true;
        }
      }
      if (!selected) return false;
      const { color, scale, height, smoothTime } = parameters;
      if (!cacheValid || cacheDifference.copy(color).sub(colorCache).lengthSq() >= colorChange) {
        cacheValid = true;
        colorCache.copy(color);
        selected.tint.copy(color);
        force = Math.fround(color.w) >= visibleAlpha;
        selected.mesh.visible = force;
      }
      const shaft = selected.root;
      shaft.position.y = height;
      shaft.scale.copy(scale);
      if (!selected.mesh.visible) return false;

      shaft.getWorldPosition(position);
      if (mainCamera) {
        mainCamera.getWorldPosition(target).sub(position);
        target.y = 0;
        point(shaft, target, worldUp);
      }
      moveNode.getWorldPosition(target);
      target.y = position.y;
      if (force || lastPosition.distanceToSquared(target) >= 1) {
        position.copy(target);
        force = false;
      } else if (Number.isFinite(deltaTime) && deltaTime > 0) {
        smoothDamp(position, target, moveVelocity, smoothTime, deltaTime, change, impulse);
      }
      lastPosition.copy(position);
      shaft.position.copy(memberRoot.worldToLocal(position));
      return true;
    }

    return {
      frame,
      billboard(camera) {
        if (!selected?.mesh.visible || !camera) return;
        const mesh = selected.mesh;
        mesh.getWorldPosition(position);
        up.copy(worldUp).applyQuaternion(worldRotation(mesh, rotation)).normalize();
        camera.getWorldPosition(target).sub(position);
        point(mesh, target, up);
      },
      dispose() {
        for (const { root, material } of variants.values()) {
          memberRoot.remove(root);
          material.dispose();
        }
        variants.clear();
        selected = null;
      }
    };
  }

  global.MVStudioShaft = { prepare, create };
})(typeof window !== "undefined" ? window : globalThis);
