(function (global) {
  "use strict";

  const atlasAlias = "speedBackCenterStars";
  const atlasUV = [.25, .25, .75, 0];
  const planeScale = Math.fround(Math.SQRT1_2);
  const id = value => typeof value === "string" && value.length > 0 && value.length <= 128;

  async function apply(T, root, source, atlases) {
    const title = global.MVStudioTitle, particles = global.MVStudioStageParticles;
    const billboards = global.MVStudioDisplayLights?.localBillboards, simulation = global.MVStudioFinaleFloorSimulation;
    if (!root?.isObject3D || !source || !title || !particles || !billboards || !simulation ||
        !id(source.trackId) || !id(source.eventId) || !Array.isArray(source.textures) || source.textures.length !== 1 ||
        !Array.isArray(source.uv) || source.uv.length !== 4 ||
        !source.uv.every((value, index) => value === atlasUV[index]) || source.maxViewportWidth !== 2) return null;
    const stream = simulation.create(source);
    if (!stream?.sample) return null;

    const [reference] = source.textures;
    const data = reference === atlasAlias ? atlases?.[atlasAlias] : reference;
    const borrowed = reference === atlasAlias && data?.isTexture;
    let texture;
    try {
      if (borrowed) texture = data;
      else if (title.validMipChain(data) && data[0].width === 512) {
        texture = await title.loadTexture(T, new T.TextureLoader(), data);
      } else return null;
    } catch {
      return null;
    }

    const rotation = new T.Quaternion().setFromAxisAngle(new T.Vector3(1, 0, 0), Math.PI / 2);
    // Horizontal mode scales both the plane and its cap by the same factor.
    const capacity = Math.ceil(source.rate * source.lifetime) + Math.ceil(source.rate * particles.nativeStep);
    const {mesh, centers, sizes, colors} = billboards(T, {
      texture, rotation, capacity, maxViewportWidth: source.maxViewportWidth * planeScale, atlas: source.uv,
      name: "Native finale floor particles", additive: true,
    });
    mesh.name = "Native stage finale floor";
    mesh.renderOrder = 3000;
    mesh.material.stencilFunc = T.AlwaysStencilFunc;
    // Native bounds cover the box's full +Z sweep during one particle life.
    // Anchor the renderer at that center, and store particle positions relative to it.
    const center = new T.Vector3().fromArray(source.position);
    center.z += source.speedRange[1] * source.lifetime / 2;
    mesh.position.copy(center);
    mesh.updateMatrix();
    root.add(mesh);
    let tracks, track, lastFrame = -1, disposed = false;

    function hide() {
      mesh.visible = false;
      mesh.geometry.instanceCount = 0;
      lastFrame = -1;
    }

    return {
      invalidate() { tracks = null; },
      update(time, project) {
        if (disposed) return;
        if (tracks !== project?.tracks) {
          tracks = project?.tracks;
          const matches = (tracks || []).filter(row => row.id === source.trackId && row.nativeClass === "CustomControlTrack");
          track = matches.length === 1 ? matches[0] : null;
        }
        const event = !track?.muted && track?.events.find(row => row.id === source.eventId);
        const offset = project?.quality?.values?.stage_control !== false && particles.activeOffset(event, time);
        if (!offset) {
          hide();
          return;
        }
        const elapsed = time - event.start;
        const fps = project?.quality?.values?.frame_rate_60fps === true ? 60 : 30;
        const frame = particles.nativeFrame(elapsed, fps);
        if (frame < 0) {
          hide();
          return;
        }
        const x = center.x + offset[0], y = center.y + offset[1], z = center.z + offset[2];
        if (mesh.position.x !== x || mesh.position.y !== y || mesh.position.z !== z) {
          mesh.position.set(x, y, z);
          mesh.updateMatrix();
        }
        if (lastFrame === frame) return;
        lastFrame = frame;

        let count = 0;
        stream.sample(elapsed, fps, (px, py, pz, _speedZ, width, height, _depth, r, g, b, a) => {
          if (a <= 0 || width <= 0 || height <= 0 || count >= capacity) return;
          centers.setXYZW(count, px - center.x, py - center.y, pz - center.z, 0);
          sizes.setXY(count, width * planeScale, height * planeScale);
          colors.setXYZW(count, r, g, b, a);
          count++;
        });
        mesh.geometry.instanceCount = count;
        mesh.visible = count > 0;
        if (count) {
          for (const attribute of [centers, sizes, colors]) {
            attribute.updateRange.count = count * attribute.itemSize;
            attribute.needsUpdate = true;
          }
        }
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        root.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
        if (!borrowed) texture.dispose();
      },
    };
  }

  global.MVStudioFinaleFloor = {apply};
})(typeof window !== "undefined" ? window : globalThis);
