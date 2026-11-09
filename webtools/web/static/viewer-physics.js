/* Serialized SwingBone/SwingCollider controls with an optional spring preview. */
(function () {
  "use strict";
  function viewerHelper(object) { while (object) { if (object.userData && object.userData.viewerHelper) return true; object = object.parent; } return false; }
  var labels = {
    "Physics preview": ["물리 미리보기", "物理プレビュー"],
    "Apply SwingBone": ["스윙본 적용", "SwingBoneを適用"],
    "Apply SwingCollider": ["스윙 콜라이더 적용", "SwingColliderを適用"],
    "Show colliders": ["콜라이더 표시", "コライダーを表示"],
    "Show bones and colliders": ["본과 콜라이더 표시", "ボーンとコライダーを表示"],
    "Breast dynamics": ["가슴 Dynamic", "胸のダイナミクス"],
    "Thigh SwingCollider": ["허벅지 SwingCollider", "太もものSwingCollider"],
    "Other physics components": ["기타 물리 컴포넌트", "その他の物理コンポーネント"],
    "Tool recommendations": ["기존 도구 추천 값", "既存ツールの推奨値"],
    "Loaded values": ["불러온 값", "読み込み時の値"],
    "Softer": ["매우 부드럽게", "より柔らかく"], "Soft": ["부드럽게", "柔らかく"], "Firm": ["단단하게", "硬く"],
    "Undo physics edits": ["물리 편집 되돌리기", "物理編集を元に戻す"],
    "No compatible physics components.": ["호환되는 물리 컴포넌트가 없습니다.", "対応する物理コンポーネントがありません。"],
    "Physics preview is approximate. Play a motion to inspect it; saved copies retain the Unity physics values.": ["물리 미리보기는 근사 시뮬레이션입니다. 모션을 재생해 확인하세요. 저장한 복사본에는 Unity 물리 값이 적용됩니다.", "物理プレビューは近似です。モーションを再生して確認してください。保存したコピーにはUnityの物理値が適用されます。"],
    "Collider recommendations keep each original radius and offset; capsule ends can have different values.": ["콜라이더 권장 값은 각 원본의 반경과 오프셋입니다. 캡슐 양끝의 값은 서로 다를 수 있습니다.", "コライダーの推奨値は各原本の半径とオフセットです。カプセルの両端は異なる値を持つ場合があります。"],
    "Correct the invalid physics values before saving.": ["저장하기 전에 잘못된 물리 값을 수정하세요.", "保存する前に無効な物理値を修正してください。"]
  };
  // Position based angular constraints. Source quaternions are never baked;
  // every application begins from this frame's animation/authoring pose.
  function buildSolver(root, catalog, current) {
    var T = window.THREE, V = T.Vector3, Q = T.Quaternion, nodes = {}, springs = [], shapes = [], byId = {}, previousShapes = {}, stats = {};
    var eps = 1e-6, skin = .001, surfaceLimit = 32768, surfaceCount = 0;
    root.traverse(function (o) { if (!viewerHelper(o) && o.userData && o.userData.elichika_node !== undefined) nodes[String(o.userData.elichika_node)] = o; });
    function mirrored(a) { return new V(-a[0], a[1], a[2]); }
    function scaleOf(o) { var s = o.getWorldScale(new V()); return Math.max(Math.abs(s.x), Math.abs(s.y), Math.abs(s.z)); }
    function depth(o) { var n = 0; while (o.parent) { n++; o = o.parent; } return n; }
    (catalog.components || []).forEach(function (r) {
      var o = nodes[String(r.node)]; if (!o || !r.enabled) return;
      if (r.kind === 'collider') { shapes.push({ record: r, object: o }); return; }
      var sim = r.simulation || {}, child = nodes[String(sim.childNode)], local;
      if (child) local = o.worldToLocal(child.getWorldPosition(new V()));
      else if (sim.childOffset) local = mirrored(sim.childOffset);
      else { child = o.children.filter(function (c) { return !c.userData.viewerHelper && c.position.lengthSq() > eps * eps; })[0]; local = child ? child.position.clone() : mirrored(sim.boneAxis || [0, 1, 0]).multiplyScalar(.08); }
      if (local.lengthSq() < eps * eps) return;
      var s = { record: r, object: o, child: child, local: local, tip: null, previous: null, velocity: new V(), base: o.quaternion.clone(), supports: [], faces: [], contactAxes: {}, depth: depth(o) };
      springs.push(s); byId[r.id] = s;
    });
    // Parent-before-child is necessary even when serialized object order differs.
    springs.sort(function (a, b) { return a.depth - b.depth || ((a.record.simulation || {}).order || 0) - ((b.record.simulation || {}).order || 0); });
    function isBelow(o, ancestor) { while (o) { if (o === ancestor) return true; o = o.parent; } return false; }
    // The tip sphere alone does not cover a wide, blended skirt panel. Retain
    // actual skinned vertices as additional zero-thickness contact supports.
    root.traverse(function (mesh) {
      if (!mesh.isSkinnedMesh || !mesh.geometry || !mesh.skeleton || viewerHelper(mesh)) return;
      var attr = mesh.geometry.attributes, indices = attr.skinIndex, weights = attr.skinWeight;
      var clothBones = mesh.skeleton.bones.map(function (bone) { return springs.some(function (spring) { return /skirt/i.test(spring.record.name) && isBelow(bone, spring.object); }); });
      var visible = true, ancestor = mesh; while (ancestor) { if (ancestor.visible === false) visible = false; ancestor = ancestor.parent; }
      if (!attr.position || !indices || !weights || !visible) return;
      var rendered = {}, draw = mesh.geometry.drawRange, meshIndex = mesh.geometry.index;
      var drawStart = draw ? draw.start : 0, drawEnd = Math.min(meshIndex ? meshIndex.count : attr.position.count, drawStart + (draw ? draw.count : Infinity));
      for (var renderedIndex = drawStart; renderedIndex < drawEnd; renderedIndex++) rendered[meshIndex ? meshIndex.getX(renderedIndex) : renderedIndex] = true;
      springs.forEach(function (s) {
        if (!/skirt/i.test(s.record.name)) return;
        var influenced = mesh.skeleton.bones.map(function (bone) { return isBelow(bone, s.object); });
        if (!influenced.some(Boolean)) return;
        var candidates = [];
        for (var i = 0; i < attr.position.count; i++) {
          if (!rendered[i]) continue;
          var w = 0;
          for (var j = 0; j < 4; j++) if (influenced[indices.array[i * indices.itemSize + j]]) w += weights.array[i * weights.itemSize + j];
          if (w > .02) candidates.push(i);
        }
        var room = Math.max(0, surfaceLimit - surfaceCount), stride = Math.max(1, Math.ceil(candidates.length / Math.min(4096, room || 1)));
        var supportMap = {}, selectedSupports = {};
        function support(index) {
          if (supportMap[index] !== undefined) return supportMap[index];
          var slot = s.supports.length;
          var clothWeight = 0;
          for (var j = 0; j < 4; j++) if (clothBones[indices.array[index * indices.itemSize + j]]) clothWeight += weights.array[index * weights.itemSize + j];
          s.supports.push({ mesh: mesh, index: index, influenced: influenced, clothWeight: clothWeight }); supportMap[index] = slot; surfaceCount++; return slot;
        }
        candidates.forEach(function (index, ordinal) { if (ordinal % stride || surfaceCount >= surfaceLimit) return; support(index); selectedSupports[index] = true; });
        var indexAttribute = mesh.geometry.index, faceCount = indexAttribute ? indexAttribute.count : attr.position.count;
        for (var face = drawStart; face + 2 < Math.min(faceCount, drawEnd) && surfaceCount < surfaceLimit; face += 3) {
          var a = indexAttribute ? indexAttribute.getX(face) : face, b = indexAttribute ? indexAttribute.getX(face + 1) : face + 1, c = indexAttribute ? indexAttribute.getX(face + 2) : face + 2;
          if (!selectedSupports[a] && !selectedSupports[b] && !selectedSupports[c]) continue;
          s.faces.push([support(a), support(b), support(c)]);
        }
        if (stride > 1 || !room) stats.surfaceSampled = true;
      });
    });
    // A skirt is a coupled skin ring: the same visible triangle can be
    // weighted to two independent SwingBones. Escape together when a leg is
    // already through that panel (seek, enabled mid-song, or a large frame).
    var skirts = {};
    springs.forEach(function (spring) {
      var sim = spring.record.simulation || {}; if (!/skirt/i.test(spring.record.name) || sim.skirtSafeEnable === false) return;
      var key = sim.manager || String(spring.record.sourceIndex); (skirts[key] || (skirts[key] = { members: [], faces: [], attachedFaces: 0, seen: {} })).members.push(spring);
    });
    Object.keys(skirts).forEach(function (key) {
      var group = skirts[key];
      group.members.forEach(function (spring) { spring.faces.forEach(function (face) {
        var entries = face.map(function (i) { return spring.supports[i]; }), mesh = entries[0].mesh, ids = entries.map(function (p) { return p.index; }), ident = mesh.uuid + ':' + ids.join(',');
        if (group.seen[ident]) return; group.seen[ident] = true;
        var attr = mesh.geometry.attributes, mobile = ids.every(function (index) {
          var weight = 0;
          for (var i = 0; i < 4; i++) { var bone = mesh.skeleton.bones[attr.skinIndex.array[index * attr.skinIndex.itemSize + i]];
            if (group.members.some(function (s) { return isBelow(bone, s.object); })) weight += attr.skinWeight.array[index * attr.skinWeight.itemSize + i]; }
          return weight >= .5;
        });
        if (mobile) group.faces.push({ mesh: mesh, indices: ids }); else group.attachedFaces++;
      }); });
      delete group.seen;
    });
    function skirtClearance(group, frame) {
      var ids = {}, triangles = [], cache = {}, worst = 0, sum = 0;
      group.members.forEach(function (spring) { selected(spring, frame).forEach(function (c) { ids[c.id] = c; }); });
      group.faces.forEach(function (face) {
        var points = face.indices.map(function (index) { var key = face.mesh.uuid + ':' + index; if (!cache[key]) cache[key] = face.mesh.boneTransform(index, new V()).applyMatrix4(face.mesh.matrixWorld); return cache[key]; });
        triangles.push(new T.Triangle(points[0], points[1], points[2]));
      });
      triangles.forEach(function (triangle) {
        var center = triangle.a.clone().add(triangle.b).add(triangle.c).multiplyScalar(1 / 3), extent = Math.sqrt(Math.max(center.distanceToSquared(triangle.a), center.distanceToSquared(triangle.b), center.distanceToSquared(triangle.c)));
        Object.keys(ids).forEach(function (id) {
          var c = ids[id]; if (capsulePenetration(center, c, extent + skin) <= 0) return;
          var line = c.b.clone().sub(c.a), lo = 0, hi = 1;
          function gap(t) { var p = c.a.clone().addScaledVector(line, t); return triangle.closestPointToPoint(p, new V()).distanceTo(p) - c.ra - (c.rb - c.ra) * t; }
          if (line.lengthSq() > eps * eps) for (var n = 0; n < 18; n++) { var l = (2 * lo + hi) / 3, h = (lo + 2 * hi) / 3; if (gap(l) < gap(h)) hi = h; else lo = l; }
          var depth = Math.max(0, skin - gap((lo + hi) / 2)); worst = Math.max(worst, depth); sum += depth * depth;
        });
      });
      return { depth: worst, loss: worst * worst + sum / Math.max(1, triangles.length) };
    }
    function skirtSafety(frame) {
      stats.skirtSafety = 0; stats.skirtSafetyPanels = 0; stats.skirtSurfacePenetration = 0; stats.skirtGroups = Object.keys(skirts).map(function (key) { return { members: skirts[key].members.length, faces: skirts[key].faces.length, attachedFaces: skirts[key].attachedFaces }; });
      Object.keys(skirts).forEach(function (key) {
        var group = skirts[key]; if (!group.faces.length) return;
        var initial = group.members.map(function (s) { return s.object.quaternion.clone(); }), baseline = skirtClearance(group, frame);
        if (baseline.depth <= .001) return;
        var best = initial.map(function (q) { return q.clone(); }), bestLoss = baseline.loss, bestDepth = baseline.depth, bestFraction = 0, lower = 0;
        function pose(fraction) {
          group.members.forEach(function (s) {
            var v = current(s.record), y = v.lowRotationLimit[1] + (v.highRotationLimit[1] - v.lowRotationLimit[1]) * fraction;
            var x = Math.max(v.lowRotationLimit[0], Math.min(v.highRotationLimit[0], 0)), z = Math.max(v.lowRotationLimit[2], Math.min(v.highRotationLimit[2], 0));
            s.object.quaternion.copy(s.base).multiply(new Q().setFromEuler(new T.Euler(x * Math.PI / 180, -y * Math.PI / 180, -z * Math.PI / 180, 'YXZ')));
          }); root.updateMatrixWorld(true);
          return skirtClearance(group, frame);
        }
        [.25, .5, .75, 1].some(function (fraction) {
          var result = pose(fraction);
          if (result.loss < bestLoss) { bestLoss = result.loss; bestDepth = result.depth; bestFraction = fraction; best = group.members.map(function (s) { return s.object.quaternion.clone(); }); }
          if (result.depth <= .001) return true;
          lower = fraction; return false;
        });
        // Find the least common lift that keeps the whole mobile surface clear.
        // Original source rotation limits remain hard bounds throughout.
        if (bestFraction && bestDepth <= .001) {
          var upper = bestFraction;
          for (var n = 0; n < 3; n++) { var mid = (lower + upper) / 2, result = pose(mid); if (result.depth <= .001) { upper = mid; best = group.members.map(function (s) { return s.object.quaternion.clone(); }); bestDepth = result.depth; } else lower = mid; }
        }
        group.members.forEach(function (s, i) { s.object.quaternion.copy(best[i]); }); root.updateMatrixWorld(true);
        // Keep the escape local: return every unaffected panel to its previous
        // dynamic pose whenever the finished shared surface remains clear.
        var lifted = 0;
        if (bestFraction && bestDepth <= .001) group.members.forEach(function (s, i) {
          s.object.quaternion.copy(initial[i]); root.updateMatrixWorld(true);
          if (skirtClearance(group, frame).depth <= .001) best[i].copy(initial[i]);
          else { s.object.quaternion.copy(best[i]); root.updateMatrixWorld(true); lifted++; }
        });
        group.members.forEach(function (s) { s.tip = s.local.clone().applyMatrix4(s.object.matrixWorld); s.previous = s.tip.clone(); s.velocity.set(0, 0, 0); });
        if (bestFraction) { stats.skirtSafety++; stats.skirtSafetyPanels += lifted; }
        stats.skirtSurfacePenetration = Math.max(stats.skirtSurfacePenetration, bestDepth);
      });
    }
    function capsule(shape) {
      var r = shape.record, v = current(r), c = mirrored(v.offset).applyMatrix4(shape.object.matrixWorld);
      return { id: r.id, a: c, b: c.clone(), ra: v.radius * scaleOf(shape.object), rb: v.radius * scaleOf(shape.object) };
    }
    function shapeFrame() {
      var out = {}; shapes.forEach(function (s) { out[s.record.id] = capsule(s); });
      shapes.forEach(function (s) { var p = out[s.record.id], sibling = out[s.record.sibling]; if (sibling) { p.b.copy(sibling.a); p.rb = sibling.ra; } }); return out;
    }
    function capsulePenetration(point, c, extra) {
      // Allocation-free form of the same tapered-capsule minimum. Most loss
      // trials only need a signed distance, not a new center/normal vector.
      var x = c.b.x - c.a.x, y = c.b.y - c.a.y, z = c.b.z - c.a.z, length2 = x * x + y * y + z * z;
      var px = point.x - c.a.x, py = point.y - c.a.y, pz = point.z - c.a.z, projected = length2 ? (px * x + py * y + pz * z) / length2 : 0;
      var t = Math.max(0, Math.min(1, projected)), dr = c.rb - c.ra;
      if (length2 && Math.abs(dr) > eps) {
        var length = Math.sqrt(length2);
        if (Math.abs(dr) >= length) t = dr > 0 ? 1 : 0;
        else { var dx = px - projected * x, dy = py - projected * y, dz = pz - projected * z; t = Math.max(0, Math.min(1, projected + dr * Math.sqrt(dx * dx + dy * dy + dz * dz) / (length * Math.sqrt(length2 - dr * dr)))); }
      }
      px -= x * t; py -= y * t; pz -= z * t;
      return c.ra + dr * t + extra - Math.sqrt(px * px + py * py + pz * pz);
    }
    function nearest(point, c, extra) {
      var line = c.b.clone().sub(c.a), length = line.lengthSq(), t = length ? Math.max(0, Math.min(1, point.clone().sub(c.a).dot(line) / length)) : 0;
      // Minimize |point - (a+t*(b-a))| - lerp(ra,rb,t) analytically.
      if (length && Math.abs(c.rb - c.ra) > eps) {
        var axisLength = Math.sqrt(length), dr = c.rb - c.ra;
        if (Math.abs(dr) >= axisLength) t = dr > 0 ? 1 : 0;
        else {
          var projected = point.clone().sub(c.a).dot(line) / length;
          var perpendicular = point.distanceTo(c.a.clone().addScaledVector(line, projected));
          t = Math.max(0, Math.min(1, projected + dr * perpendicular / (axisLength * Math.sqrt(length - dr * dr))));
        }
      }
      var center = c.a.clone().addScaledVector(line, t), normal = point.clone().sub(center), d = normal.length(), radius = c.ra + (c.rb - c.ra) * t + extra;
      return { penetration: radius - d, normal: d > eps ? normal.divideScalar(d) : new V(), center: center };
    }
    function selected(s, frame) {
      var sim = s.record.simulation || {}, ids = sim.colliders;
      // Old/private fixture variants without membership use their own source;
      // an explicitly empty list means no body collisions (e.g. breasts).
      if (!Array.isArray(ids)) ids = shapes.filter(function (v) { return v.record.sourceIndex === s.record.sourceIndex; }).map(function (v) { return v.record.id; });
      var seen = {}, result = [];
      ids.forEach(function (id) { var c = frame[id]; if (!c) return; var key = c.a.toArray().join(',') + ':' + c.ra + '/' + c.b.toArray().join(',') + ':' + c.rb; var reverse = c.b.toArray().join(',') + ':' + c.rb + '/' + c.a.toArray().join(',') + ':' + c.ra; if (seen[key] || seen[reverse]) return; seen[key] = true; result.push(c); }); return result;
    }
    function clamp(s, worldQuaternion) {
      var o = s.object, local = worldQuaternion.clone();
      if (o.parent) local.premultiply(o.parent.getWorldQuaternion(new Q()).invert());
      var relative = s.base.clone().invert().multiply(local), e = new T.Euler().setFromQuaternion(relative, 'YXZ'), v = current(s.record);
      ['x', 'y', 'z'].forEach(function (axis, i) { var lo = v.lowRotationLimit[i] * Math.PI / 180, hi = v.highRotationLimit[i] * Math.PI / 180; if (i) { var a = lo; lo = -hi; hi = -a; } e[axis] = Math.max(lo, Math.min(hi, e[axis])); });
      o.quaternion.copy(s.base).multiply(new Q().setFromEuler(e)); o.updateMatrixWorld(true);
    }
    function skinSupport(s, support, origin, cache) {
      var mesh = support.mesh, attr = mesh.geometry.attributes, prepared = cache[mesh.uuid];
      if (!prepared) {
        var rendered = new T.Matrix4().multiplyMatrices(mesh.matrixWorld, mesh.bindMatrixInverse);
        prepared = cache[mesh.uuid] = { matrices: {}, rendered: rendered, linear: new T.Matrix3().setFromMatrix4(rendered) };
      }
      var v = new V().fromBufferAttribute(attr.position, support.index).applyMatrix4(mesh.bindMatrix), total = new V(), lever = new V(), mobility = 0;
      for (var i = 0; i < 4; i++) {
        var w = attr.skinWeight.array[support.index * attr.skinWeight.itemSize + i]; if (!w) continue;
        var j = attr.skinIndex.array[support.index * attr.skinIndex.itemSize + i], bone = mesh.skeleton.bones[j]; if (!bone) continue;
        var matrix = prepared.matrices[j];
        if (!matrix) matrix = prepared.matrices[j] = new T.Matrix4().multiplyMatrices(bone.matrixWorld, mesh.skeleton.boneInverses[j]);
        var point = v.clone().applyMatrix4(matrix); total.addScaledVector(point, w);
        if (support.influenced[j]) { lever.addScaledVector(point, w); mobility += w; }
      }
      // Cache each bone's skin matrix and renderer frame once per solve, not
      // once for every cloth vertex and every influence. Neighboring-joint
      // passes receive a fresh cache after that pose changes.
      lever.addScaledVector(origin, -mobility).applyMatrix3(prepared.linear);
      return { fixed: total.applyMatrix4(prepared.rendered).sub(lever), lever: lever, mobility: mobility, clothWeight: support.clothWeight };
    }
    function solve(s, colliders, target, iterations) {
      var o = s.object, origin = o.getWorldPosition(new V()), baseWorld = o.getWorldQuaternion(new Q()), rest = s.local.clone().applyMatrix4(o.matrixWorld), restDirection = rest.clone().sub(origin);
      var desired = new Q().setFromUnitVectors(restDirection.clone().normalize(), target.clone().sub(origin).normalize()).multiply(baseWorld);
      var skinCache = {}, supports = s.supports.map(function (p) { return skinSupport(s, p, origin, skinCache); });
      var measureOnly = iterations === 0;
      if (!measureOnly) clamp(s, desired);
      s.blocked = null;
      var radius = Math.max(0, Number((s.record.simulation || {}).radius) || 0) * scaleOf(o), max = 0;
      for (var iteration = 0; iteration < Math.max(1, iterations); iteration++) {
        var rotation = o.getWorldQuaternion(new Q()).multiply(baseWorld.clone().invert()), worst = null, contacts = [];
        function inspect(point, lever, extra, collider, fallbackNormal, mobility) {
          if (mobility !== undefined && mobility < .05) return;
          if (lever.lengthSq() < eps * eps) return;
          var hit = nearest(point, collider, extra);
          if (hit.penetration <= skin * .1) return;
          contacts.push({ point: point.clone(), lever: lever.clone(), extra: extra, collider: collider, penetration: hit.penetration, mobility: mobility === undefined ? 1 : mobility });
          if (worst && hit.penetration <= worst.hit.penetration) return;
          var degenerate = hit.normal.lengthSq() < eps;
          if (degenerate) { hit.normal.copy(fallbackNormal || point.clone().sub(origin)); if (hit.normal.lengthSq() < eps) hit.normal.set(0, 0, 1); hit.normal.normalize(); }
          var axis = lever.clone().cross(hit.normal), gradient = axis.length();
          if (degenerate && s.contactAxes[collider.id] && axis.dot(s.contactAxes[collider.id]) < 0) axis.negate();
          // A fixed anchor cannot be pushed out by rotating the bone. Report
          // truly infeasible contacts, never divide by a vanishing lever arm.
          if (gradient < eps) {
            if (s.contactAxes[collider.id]) axis.copy(s.contactAxes[collider.id]);
            else axis.crossVectors(lever, collider.a.clone().sub(origin));
            if (axis.lengthSq() < eps) axis.crossVectors(lever, new V(0, 0, 1));
            if (axis.lengthSq() < eps) axis.crossVectors(lever, new V(0, 1, 0));
            gradient = Math.max(eps, lever.length() * .1);
          }
          s.contactAxes[collider.id] = axis.clone().normalize();
          worst = { hit: hit, point: point.clone(), lever: lever.clone(), extra: extra, collider: collider, axis: axis.normalize(), angle: Math.min(.18, (hit.penetration + skin) / gradient) };
        }
        var lever = s.local.clone().applyMatrix4(o.matrixWorld).sub(origin);
        var points = supports.map(function (p) { var l = p.lever.clone().applyQuaternion(rotation); return { point: p.fixed.clone().add(l), lever: l, mobility: p.mobility, clothWeight: p.clothWeight }; });
        colliders.forEach(function (c) {
          // The entire rod is constrained, so a leg cannot pass through its
          // middle while both pivot and endpoint remain outside the capsule.
          var lo = 0, hi = 1;
          if (!/skirt/i.test(s.record.name)) {
          for (var search = 0; search < 18; search++) {
            var l = (2 * lo + hi) / 3, h = (lo + 2 * hi) / 3;
            if (capsulePenetration(origin.clone().addScaledVector(lever, l), c, radius) > capsulePenetration(origin.clone().addScaledVector(lever, h), c, radius)) hi = h; else lo = l;
          }
          var fraction = (lo + hi) / 2, rod = lever.clone().multiplyScalar(fraction);
          if (fraction > .02) inspect(origin.clone().add(rod), rod, radius, c);
          }
          inspect(origin.clone().add(lever), lever, radius, c);
          points.forEach(function (p) { if (p.clothWeight >= .5) inspect(p.point, p.lever, skin, c, null, p.mobility); });
        });
        // Vertex tests miss a leg crossing the interior of a wide triangle.
        // The minimum of point-to-triangle distance minus a linear radius is
        // convex along a capsule axis. Keep barycentric lever arms so blended
        // skinning, including fixed vertices, responds to the actual bone.
        if (measureOnly || !worst || worst.hit.penetration < .002) colliders.forEach(function (c) {
          s.faces.forEach(function (face) {
            var a = points[face[0]], b = points[face[1]], d = points[face[2]];
            if (a.clothWeight < .5 || b.clothWeight < .5 || d.clothWeight < .5) return;
            var center = a.point.clone().add(b.point).add(d.point).multiplyScalar(1 / 3);
            var extent = Math.sqrt(Math.max(center.distanceToSquared(a.point), center.distanceToSquared(b.point), center.distanceToSquared(d.point)));
            if (capsulePenetration(center, c, extent + skin) <= 0) return;
            var triangle = new T.Triangle(a.point, b.point, d.point), line = c.b.clone().sub(c.a), lo = 0, hi = 1;
            function gap(t) { var axisPoint = c.a.clone().addScaledVector(line, t); return triangle.closestPointToPoint(axisPoint, new V()).distanceTo(axisPoint) - c.ra - (c.rb - c.ra) * t; }
            if (line.lengthSq() > eps * eps) for (var k = 0; k < 18; k++) { var l = (2 * lo + hi) / 3, h = (lo + 2 * hi) / 3; if (gap(l) < gap(h)) hi = h; else lo = l; }
            var t = (lo + hi) / 2, axisPoint = c.a.clone().addScaledVector(line, t), point = triangle.closestPointToPoint(axisPoint, new V()), bary = triangle.getBarycoord(point, new V());
            var l = a.lever.clone().multiplyScalar(bary.x).addScaledVector(b.lever, bary.y).addScaledVector(d.lever, bary.z);
            inspect(point, l, skin, c, triangle.getNormal(new V()), a.mobility * bary.x + b.mobility * bary.y + d.mobility * bary.z);
          });
        });
        if (!worst) { max = 0; break; }
        max = worst.hit.penetration;
        if (measureOnly) break;
        var before = o.quaternion.clone(), beforeWorld = o.getWorldQuaternion(new Q()), q = new Q().setFromAxisAngle(worst.axis, worst.angle).multiply(beforeWorld);
        clamp(s, q);
        // Minimize all current contacts together. Optimizing only the
        // deepest point alternates between neighboring blended cloth panels.
        contacts.sort(function (a, b) { return b.penetration - a.penetration; }); contacts = contacts.slice(0, 256);
        function loss(quaternion) {
          o.quaternion.copy(quaternion); o.updateMatrixWorld(true);
          var step = o.getWorldQuaternion(new Q()).multiply(beforeWorld.clone().invert()), sum = 0;
          contacts.forEach(function (c) { var p = c.point.clone().add(c.lever.clone().applyQuaternion(step).sub(c.lever)), depth = Math.max(0, capsulePenetration(p, c.collider, c.extra)); sum += depth * depth * c.mobility * c.mobility; });
          return sum / Math.max(1, contacts.length);
        }
        var beforeLoss = loss(before), best = o.quaternion.clone();
        clamp(s, q); best.copy(o.quaternion); var bestLoss = loss(best);
        if (beforeLoss < bestLoss) { best.copy(before); bestLoss = beforeLoss; }
        var euler = new T.Euler().setFromQuaternion(s.base.clone().invert().multiply(before), 'YXZ'), v = current(s.record);
        ['x', 'y', 'z'].forEach(function (axis, ordinal) {
          var lo = v.lowRotationLimit[ordinal] * Math.PI / 180, hi = v.highRotationLimit[ordinal] * Math.PI / 180;
          if (ordinal) { var a = lo; lo = -hi; hi = -a; }
          [euler[axis] - .08, euler[axis] + .08, euler[axis] - .3, euler[axis] + .3, lo, hi].forEach(function (value) {
            var e = euler.clone(); e[axis] = Math.max(lo, Math.min(hi, value));
            var candidate = s.base.clone().multiply(new Q().setFromEuler(e)), candidateLoss = loss(candidate);
            if (candidateLoss < bestLoss - 1e-10) { bestLoss = candidateLoss; best.copy(candidate); }
          });
        });
        o.quaternion.copy(best); o.updateMatrixWorld(true);
        if (1 - Math.abs(before.dot(best)) < 1e-12 || bestLoss >= beforeLoss - 1e-12) {
          s.blocked = { point: worst.point.toArray(), lever: worst.lever.toArray(), normal: worst.hit.normal.toArray(), penetration: worst.hit.penetration, extra: worst.extra, collider: worst.collider.id, relative: new T.Euler().setFromQuaternion(s.base.clone().invert().multiply(before), 'YXZ').toArray().slice(0, 3) }; break;
        }
        s.blocked = null;
        stats.contacts++;
      }
      s.tip = s.local.clone().applyMatrix4(o.matrixWorld); s.radius = radius; s.residual = max;
      return s.tip;
    }
    function apply(delta, settings) {
      settings = settings || {}; stats.contacts = 0; stats.maxPenetration = 0; stats.unresolvedBones = 0; stats.surfaceSupports = surfaceCount; stats.surfaceTriangles = springs.reduce(function (n, spring) { return n + spring.faces.length; }, 0);
      root.updateMatrixWorld(true); var frame = shapeFrame();
      if (!settings.bones) { previousShapes = frame; return; }
      springs.forEach(function (s) { s.base.copy(s.object.quaternion); if (s.child) s.local.copy(s.object.worldToLocal(s.child.getWorldPosition(new V()))); });
      delta = Math.max(0, Math.min(.1, Number(delta) || 0));
      var steps = Math.max(1, Math.ceil(delta * 120)), movement = 0;
      shapes.forEach(function (shape) { var a = frame[shape.record.id], b = previousShapes[shape.record.id]; if (a && b) movement = Math.max(movement, a.a.distanceTo(b.a) / Math.max(.01, Math.min(a.ra, a.rb))); });
      steps = Math.min(24, Math.max(steps, Math.ceil(movement * 2))); stats.substeps = steps;
      var h = delta / steps;
      for (var step = 1; step <= steps; step++) {
        var interpolated = {}, alpha = step / steps;
        Object.keys(frame).forEach(function (id) { var c = frame[id], p = previousShapes[id] || c; interpolated[id] = { id: id, a: p.a.clone().lerp(c.a, alpha), b: p.b.clone().lerp(c.b, alpha), ra: p.ra + (c.ra - p.ra) * alpha, rb: p.rb + (c.rb - p.rb) * alpha }; });
        springs.forEach(function (s) { s.object.quaternion.copy(s.base); }); root.updateMatrixWorld(true);
        springs.forEach(function (s) {
          var o = s.object, origin = o.getWorldPosition(new V()), rest = s.local.clone().applyMatrix4(o.matrixWorld), value = current(s.record);
          if (!s.tip || !s.previous || !isFinite(s.tip.lengthSq())) { s.tip = rest.clone(); s.previous = rest.clone(); s.velocity.set(0, 0, 0); }
          var tip = s.tip.clone();
          if (h) {
            // Velocity is measured in world units/second, not displacement
            // per render frame. Spring and external forces are accelerations,
            // so 90/144/240Hz displays preserve the same physical equilibrium.
            s.velocity.multiplyScalar(Math.pow(Math.max(0, 1 - value.dragForce), h * 60));
            s.velocity.addScaledVector(rest.clone().sub(tip), value.stiffnessForce * h * 3600);
            var force = (s.record.simulation || {}).externalForce || (s.record.simulation || {}).gravity || [0, 0, 0]; s.velocity.addScaledVector(mirrored(force), h * 3600);
            tip.addScaledVector(s.velocity, h);
          }
          var old = s.tip.clone(), colliders = settings.colliders ? selected(s, interpolated) : [];
          solve(s, colliders, tip, colliders.length ? 24 : 1);
          if (h) { s.previous.copy(old); s.velocity.copy(s.tip).sub(old).divideScalar(h); } else { s.previous.copy(s.tip); s.velocity.set(0, 0, 0); }
        });
      }
      // Child springs and later contacts can change blended supports. A final
      // Gauss-Seidel pass evaluates the finished chain at the real new pose.
      if (settings.colliders) {
        for (var pass = 0; pass < 6; pass++) {
          var prior = stats.contacts;
          springs.forEach(function (s) { solve(s, selected(s, frame), s.tip.clone(), 6); });
          if (stats.contacts === prior) break;
        }
        skirtSafety(frame);
        springs.forEach(function (s) { solve(s, selected(s, frame), s.tip.clone(), 0); });
      }
      springs.forEach(function (s) { stats.maxPenetration = Math.max(stats.maxPenetration, s.residual || 0); if (s.residual > .002) stats.unresolvedBones++; });
      root.updateMatrixWorld(true); root.traverse(function (o) { if (o.isSkinnedMesh && !viewerHelper(o)) o.skeleton.update(); }); previousShapes = frame;
    }
    return { apply: apply, reset: function () { previousShapes = {}; springs.forEach(function (s) { s.tip = s.previous = null; s.velocity.set(0, 0, 0); s.contactAxes = {}; }); },
      getMetrics: function () { return Object.assign({}, stats); },
      getState: function () { var frame = shapeFrame(); return Object.assign({}, stats, { dynamicBones: springs.length, bones: springs.map(function (s) { return { id: s.record.id, node: s.record.node, childNode: (s.record.simulation || {}).childNode, origin: s.object.getWorldPosition(new V()).toArray(), tip: s.local.clone().applyMatrix4(s.object.matrixWorld).toArray(), radius: s.radius || 0, colliders: selected(s, frame).map(function (c) { return c.id; }), residual: s.residual || 0, blocked: s.blocked || null }; }), capsules: Object.keys(frame).map(function (id) { var c = frame[id]; return { id: id, a: c.a.toArray(), b: c.b.toArray(), ra: c.ra, rb: c.rb, radiusA: c.ra, radiusB: c.rb, sourceIds: [id] }; }) }); } };
  }

  function createSolver(root, catalog, current) {
    var solver = null, previous = null, revision = 0, samples = [], lastMs = 0;
    function visible(object) { while (object) { if (object.visible === false) return false; object = object.parent; } return true; }
    function signature() {
      var value = [];
      root.traverse(function (o) {
        if (!o.isSkinnedMesh || !o.geometry || viewerHelper(o)) return;
        var g = o.geometry, a = g.attributes;
        value.push(o, g, g.index, g.index && g.index.version, g.index && g.index.count, g.drawRange.start, g.drawRange.count, visible(o), o.skeleton && o.skeleton.bones);
        ['position', 'skinIndex', 'skinWeight'].forEach(function (name) { value.push(a[name], a[name] && a[name].version, a[name] && a[name].count); });
      }); return value;
    }
    function ensure() {
      var next = signature();
      if (!previous || next.length !== previous.length || next.some(function (v, i) { return v !== previous[i]; })) {
        solver = buildSolver(root, catalog, current); previous = next; revision++;
      }
    }
    function now() { return typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now(); }
    ensure();
    return {
      apply: function (delta, settings) { var start = now(); ensure(); solver.apply(delta, settings); lastMs = now() - start; if (settings && settings.bones) { samples.push(lastMs); if (samples.length > 128) samples.shift(); } },
      reset: function () { ensure(); solver.reset(); },
      getTimingState: function () { return Object.assign(solver.getMetrics(), { frameMs: lastMs }); },
      getState: function () { ensure(); var sorted = samples.slice().sort(function (a, b) { return a - b; }); return Object.assign(solver.getState(), { geometryRevision: revision, frameMs: lastMs, medianMs: sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0, maxMs: sorted.length ? sorted[sorted.length - 1] : 0 }); }
    };
  }

  function create(root, catalog, options) {
    var THREE = window.THREE, components = catalog && catalog.components || [], edits = {}, controls = [], regions = [];
    var nodes = {}, interactive = true, writable = true, disposed = false;
    var applyBones = false, applyColliders = false, showColliders = false, spheres = [], springs = [], helperGroup = new THREE.Group();
    var base = {}, lang = function () { return document.documentElement.lang || "en"; };
    helperGroup.userData.viewerHelper = true; root.add(helperGroup);
    root.traverse(function (object) { if (!viewerHelper(object) && object.userData && object.userData.elichika_node !== undefined) nodes[String(object.userData.elichika_node)] = object; });
    function t(key) { var pair = labels[key], index = lang() === "ko" ? 0 : lang() === "ja" ? 1 : -1; return pair && index >= 0 ? pair[index] : options.translate(key); }
    function element(tag, text, parent) { var el = document.createElement(tag); if (text) { el.textContent = t(text); el.dataset.physicsLabel = text; } if (parent) parent.appendChild(el); return el; }
    function region(parent, title) { if (!parent) return null; var box = element("details", null, parent); box.className = "viewer-save-advanced viewer-physics-region"; element("summary", title, box); regions.push(box); return box; }
    function current(record) { return Object.assign({}, record.values, edits[record.id] || {}); }
    function notify() { if (!disposed && options.onChange) options.onChange(); }
    function validField(record, name, value) {
      if (Array.isArray(record.values[name])) return Array.isArray(value) && value.length === 3 && value.every(function (v) { return typeof v === "number" && isFinite(v) && Math.abs(v) <= (name === "offset" ? 10 : 180); });
      return typeof value === "number" && isFinite(value) && value >= 0 && value <= (name === "dragForce" ? 1 : 10);
    }
    function validValues(record, values) {
      if (!values || typeof values !== "object" || Array.isArray(values) || !Object.keys(values).length || Object.keys(values).some(function (name) { return record.values[name] === undefined || !validField(record, name, values[name]); })) return false;
      var value = Object.assign({}, record.values, values);
      return record.kind !== "bone" || value.lowRotationLimit.every(function (v, i) { return v <= value.highRotationLimit[i]; });
    }
    function updateEdit(record, values) {
      var changed = {};
      Object.keys(values).forEach(function (name) { if (JSON.stringify(values[name]) !== JSON.stringify(record.values[name])) changed[name] = values[name]; });
      if (Object.keys(changed).length) edits[record.id] = changed; else delete edits[record.id];
    }
    function refreshFields(selected) {
      controls.forEach(function (row) { if (!row.record || selected && selected.indexOf(row.record.id) < 0) return; var value = current(row.record)[row.name]; row.input.value = row.axis === undefined ? String(value) : String(value[row.axis]); row.input.setCustomValidity(""); row.input.removeAttribute("aria-invalid"); delete row.input.dataset.physicsDirty; });
    }
    function field(record, name, axis, parent) {
      var label = element("label", null, parent), text = element("span", null, label);
      text.textContent = name + (axis === undefined ? "" : " " + "XYZ"[axis]);
      var input = element("input", null, label), bound = name === "offset" ? 10 : 180;
      input.type = "number"; input.step = "any"; input.required = true;
      input.min = axis === undefined ? "0" : String(-bound); input.max = axis === undefined ? name === "dragForce" ? "1" : "10" : String(bound);
      input.dataset.physicsComponent = record.id; input.dataset.physicsField = name; if (axis !== undefined) input.dataset.physicsAxis = String(axis);
      input.setAttribute("aria-label", record.name + " " + text.textContent);
      controls.push({ input: input, record: record, name: name, axis: axis, write: true });
      input.addEventListener("input", function () {
        input.dataset.physicsDirty = "true";
        var values = Object.assign({}, current(record)), number = input.value.trim() ? Number(input.value) : NaN;
        if (axis === undefined) values[name] = number; else { values[name] = values[name].slice(); values[name][axis] = number; }
        var valid = validValues(record, values);
        input.setCustomValidity(valid ? "" : t("Correct the invalid physics values before saving."));
        if (valid) { input.removeAttribute("aria-invalid"); updateEdit(record, values); } else input.setAttribute("aria-invalid", "true");
        notify();
      });
    }
    function componentEditor(record, parent) {
      var box = element("details", null, parent); box.className = "viewer-save-advanced";
      element("summary", null, box).textContent = record.name + " · " + record.kind + (record.sibling ? " · capsule" : "");
      var original = element("p", null, box); original.className = "viewer-render-note";
      original.textContent = t("Loaded values") + ": " + Object.keys(record.values).map(function (key) { return key + "=" + (Array.isArray(record.values[key]) ? record.values[key].join("/") : record.values[key]); }).join(" · ");
      Object.keys(record.values).forEach(function (name) { if (Array.isArray(record.values[name])) [0, 1, 2].forEach(function (axis) { field(record, name, axis, box); }); else field(record, name, undefined, box); });
    }
    function toggle(key, name, callback, available, parent) {
      var label = element("label", null, parent), input = element("input", null, label); input.type = "checkbox"; input.id = name;
      element("span", key, label); input.disabled = !available;
      controls.push({ input: input, available: available, write: false });
      input.addEventListener("change", function () { callback(input.checked); if (solver) solver.reset(); notify(); });
    }
    var pose = document.getElementById("viewer-adjustments"), preview = region(pose, "Physics preview");
    if (preview) {
      toggle("Apply SwingBone", "viewer-physics-bones", function (v) { applyBones = v; }, components.some(function (v) { return v.kind === "bone" && v.node !== null && v.enabled; }), preview);
      toggle("Apply SwingCollider", "viewer-physics-colliders", function (v) { applyColliders = v; }, components.some(function (v) { return v.kind === "collider" && v.node !== null && v.enabled; }), preview);
      toggle("Show bones and colliders", "viewer-physics-show-colliders", function (v) { showColliders = v; helperGroup.visible = v; }, components.some(function (v) { return v.kind === "collider" && v.node !== null; }), preview);
      var note = element("p", "Physics preview is approximate. Play a motion to inspect it; saved copies retain the Unity physics values.", preview); note.className = "viewer-render-note";
      if (!components.length) element("p", "No compatible physics components.", preview);
    }
    [["breast", "viewer-breast-card", "Breast dynamics"], ["thighs", "viewer-thighs-card", "Thigh SwingCollider"], ["other", "viewer-body-adjustments", "Other physics components"]].forEach(function (group) {
      var records = components.filter(function (r) { return r.group === group[0]; }); if (!records.length) return;
      var parent = document.getElementById(group[1]), container = region(parent && (parent.querySelector(".viewer-card-content") || parent), group[2]);
      if (!container) return;
      if (group[0] === "breast" && records.some(function (r) { return r.kind === "bone"; })) {
        var label = element("label", null, container); element("span", "Tool recommendations", label);
        var select = element("select", null, label); select.id = "viewer-physics-breast-preset";
        var original = element("option", "Loaded values", select); original.value = "";
        (catalog.presets || []).forEach(function (preset) { var option = element("option", null, select); option.value = preset.id; option.textContent = t(preset.label) + " (" + preset.stiffnessForce + " / " + preset.dragForce + ")"; });
        controls.push({ input: select, write: true });
        select.addEventListener("change", function () { var preset = (catalog.presets || []).filter(function (p) { return p.id === select.value; })[0]; var selected = records.filter(function (r) { return r.kind === "bone"; }); selected.forEach(function (r) { var v = current(r); ["stiffnessForce", "dragForce"].forEach(function (name) { v[name] = preset ? preset[name] : r.values[name]; }); updateEdit(r, v); }); refreshFields(selected.map(function (r) { return r.id; })); notify(); });
        element("p", null, container).textContent = "sifas_breast_tuner.py";
      }
      if (group[0] === "thighs") { var note = element("p", "Collider recommendations keep each original radius and offset; capsule ends can have different values.", container); note.className = "viewer-render-note"; }
      records.forEach(function (record) { componentEditor(record, container); });
      var reset = element("button", "Undo physics edits", container); reset.type = "button"; controls.push({ input: reset, write: true });
      reset.addEventListener("click", function () { records.forEach(function (r) { delete edits[r.id]; }); refreshFields(records.map(function (r) { return r.id; })); notify(); });
    });
    components.forEach(function (record) {
      var object = nodes[String(record.node)]; if (!object) return;
      base[record.id] = record;
      if (record.kind === "collider") {
        var geometry = new THREE.SphereGeometry(1, 12, 8), material = new THREE.MeshBasicMaterial({ color: 0x39a4dd, wireframe: true, depthTest: false, transparent: true, opacity: .5 });
        var helper = new THREE.Mesh(geometry, material); helper.userData.viewerHelper = true; helper.renderOrder = 1000; helperGroup.add(helper);
        spheres.push({ record: record, object: object, helper: helper });
      } else if (record.enabled) springs.push({ record: record, object: object, tip: null, previous: null, quaternion: object.quaternion.clone(), length: .08 });
    });
    helperGroup.visible = false; refreshFields();
    function colliderWorld(sphere) {
      var value = current(sphere.record), center = new THREE.Vector3(-value.offset[0], value.offset[1], value.offset[2]).applyMatrix4(sphere.object.matrixWorld);
      var scale = sphere.object.getWorldScale(new THREE.Vector3()), radius = value.radius * Math.max(Math.abs(scale.x), Math.abs(scale.y), Math.abs(scale.z));
      return { center: center, radius: radius };
    }
    var solver = createSolver(root, catalog, current), capsuleLines = {}, boneHelpers = {};
    function lineHelper(count, color) {
      var geometry = new THREE.BufferGeometry(); geometry.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(count * 3), 3));
      var line = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: color, depthTest: false, transparent: true, opacity: .7 }));
      line.userData.viewerHelper = true; line.renderOrder = 1001; line.frustumCulled = false; helperGroup.add(line); return line;
    }
    function setLine(line, points) {
      var attr = line.geometry.attributes.position;
      points.forEach(function (point, index) { var local = root.worldToLocal(point.clone()); attr.setXYZ(index, local.x, local.y, local.z); }); attr.needsUpdate = true;
    }
    function drawConstraints() {
      var state = solver.getState();
      state.capsules.forEach(function (capsule) {
        var a = new THREE.Vector3().fromArray(capsule.a), b = new THREE.Vector3().fromArray(capsule.b), axis = b.clone().sub(a);
        if (axis.lengthSq() < 1e-10) return;
        var line = capsuleLines[capsule.id] || (capsuleLines[capsule.id] = lineHelper(16, 0x39a4dd));
        axis.normalize(); var u = axis.clone().cross(new THREE.Vector3(0, 1, 0)); if (u.lengthSq() < 1e-8) u.crossVectors(axis, new THREE.Vector3(1, 0, 0)); u.normalize();
        var v = axis.clone().cross(u).normalize(), points = [];
        for (var i = 0; i < 8; i++) { var angle = i * Math.PI / 4, radial = u.clone().multiplyScalar(Math.cos(angle)).addScaledVector(v, Math.sin(angle)); points.push(a.clone().addScaledVector(radial, capsule.ra), b.clone().addScaledVector(radial, capsule.rb)); }
        setLine(line, points);
      });
      state.bones.forEach(function (bone) {
        var helper = boneHelpers[bone.id];
        if (!helper) {
          var dot = new THREE.Mesh(new THREE.SphereGeometry(1, 8, 6), new THREE.MeshBasicMaterial({ color: 0xf0b54c, wireframe: true, depthTest: false, transparent: true, opacity: .6 }));
          dot.userData.viewerHelper = true; dot.renderOrder = 1002; helperGroup.add(dot); helper = boneHelpers[bone.id] = { line: lineHelper(2, 0xf0b54c), dot: dot };
        }
        var origin = new THREE.Vector3().fromArray(bone.origin), tip = new THREE.Vector3().fromArray(bone.tip), scale = root.getWorldScale(new THREE.Vector3()); setLine(helper.line, [origin, tip]);
        helper.dot.position.copy(root.worldToLocal(tip)); var radius = Math.max(.002, bone.radius); helper.dot.scale.set(radius / Math.abs(scale.x || 1), radius / Math.abs(scale.y || 1), radius / Math.abs(scale.z || 1));
      });
    }
    function apply(delta) {
      if (disposed) return;
      solver.apply(delta, { bones: applyBones, colliders: applyColliders });
      if (showColliders) { drawConstraints(); spheres.forEach(function (sphere) {
        var value = colliderWorld(sphere); sphere.helper.position.copy(root.worldToLocal(value.center.clone()));
        var rs = root.getWorldScale(new THREE.Vector3()); sphere.helper.scale.set(value.radius / Math.abs(rs.x || 1), value.radius / Math.abs(rs.y || 1), value.radius / Math.abs(rs.z || 1));
      }); }
    }
    return {
      apply: apply,
      getTimingState: function () { return solver.getTimingState(); },
      getEdits: function () { return Object.keys(edits).sort().map(function (id) { return { id: id, values: JSON.parse(JSON.stringify(edits[id])) }; }); },
      invalid: function () { return controls.some(function (c) { return c.record && c.input.dataset.physicsDirty === "true" && !c.input.disabled && !c.input.checkValidity(); }); },
      restorePreviewState: function (state) {
        if (!state || typeof state !== "object") return;
        applyBones = !!state.swingBone; applyColliders = !!state.swingCollider; showColliders = !!state.showColliders;
        [["viewer-physics-bones", applyBones], ["viewer-physics-colliders", applyColliders], ["viewer-physics-show-colliders", showColliders]].forEach(function (row) { var input = document.getElementById(row[0]); if (input) input.checked = row[1]; });
        helperGroup.visible = showColliders; solver.reset();
      },
      restore: function (rows) { var next = {}; if (!Array.isArray(rows) || rows.length > components.length) throw new Error("The physics recipe is invalid."); rows.forEach(function (row) { var record = components.filter(function (r) { return r.id === row.id; })[0]; if (!record || next[row.id] || !validValues(record, row.values)) throw new Error("The physics recipe is invalid."); next[row.id] = JSON.parse(JSON.stringify(row.values)); }); edits = next; refreshFields(); },
      reset: function () { edits = {}; solver.reset(); refreshFields(); },
      setInteractive: function (value, authoring) { interactive = !!value; writable = !!authoring; controls.forEach(function (row) { row.input.disabled = !interactive || row.write && !writable || row.available === false; }); },
      updateLanguage: function () { regions.forEach(function (region) { region.querySelectorAll("[data-physics-label]").forEach(function (el) { el.textContent = t(el.dataset.physicsLabel); }); }); },
      getState: function () { return { available: components.length > 0, swingBone: applyBones, swingCollider: applyColliders, showColliders: showColliders, components: components.length, dynamicBones: springs.length, edited: Object.keys(edits).length, solver: solver.getState() }; },
      dispose: function () { disposed = true; regions.forEach(function (r) { r.remove(); }); root.remove(helperGroup); helperGroup.traverse(function (object) { if (object.geometry) object.geometry.dispose(); if (object.material) object.material.dispose(); }); }
    };
  }
  window.ViewerPhysics = { create: create, createSolver: createSolver };
}());
