(function (global) {
  "use strict";

  // Pure, read-only helpers for MVStudioScene.assetDump(), the editor half of
  // the runtime value dump (schema sifas-mv-runtime-dump/1). Every value is
  // copied into plain arrays in the editor's own space ("three-rh-mirror-x");
  // the comparator (tests/mv_runtime_compare.py) owns every conversion.
  // Nothing here writes to a scene object, a matrix or a uniform, and textures
  // are identified from their dimensions only: pixels are never read.

  const SCHEMA = "sifas-mv-runtime-dump/1";
  const CONVENTIONS = Object.freeze({ space: "three-rh-mirror-x", matrixLayout: "column-major", angles: "degrees",
    quaternion: "xyzw", color: "raw", time: "director-seconds" });

  // Editor-only uniforms that have no Unity material property.
  const EDITOR_ONLY = new Set(["uResolutionRatio", "uOutlineScale", "uOutlineEdited", "uOutlineQuantized", "uBeat"]);

  // MVStudioStageMaterial uniforms (schema 1.4). Unmapped uniforms are reported, never guessed.
  const STAGE_TABLE = {
    tint: { name: "_TintColor", t: "color" },
    ambient: { name: "_AmbientColor", t: "color" },
    blendColor: { name: "_BlendColor", t: "color" },
    mainUVTransform: { name: "_MainTex", t: "st" },
    mainMap: { name: "_MainTex", t: "tex" },
    emissiveColor: { name: "_EmissiveColor", t: "color" },
    emissiveIntensity: { name: "_EmissiveIntensity", t: "float" },
    mipBias: { name: "_MainTexMipmapBias", t: "float" },
    alphaCutoff: { name: "_Cutoff", t: "float" },
  };
  // MVStudioStageColoring uniforms, checked against the AS/Coloring/* shader property lists.
  const COLORING_TABLE = {
    uTint: { name: "_TintColor", t: "color" },
    uShift: { name: "_Shift", t: "float" },
    uSpeed: { name: "_Speed", t: "float" },
    uMain: { name: "_MainTex", t: "tex" },
  };
  // Uniforms that carry a Unity shader global rather than a material property.
  const GLOBAL_UNIFORMS = { uSelfTime: "_SelfTime", uMusicTime: "_MusicTime", _MusicTime: "_MusicTime" };

  const MATRIX_KEYS = new Set(["projection", "worldToCamera"]);
  const PRECISE_SECTIONS = new Set(["cameras", "correctors", "cameraWork", "anchors", "stageNodes", "members", "springs", "renderers",
    "transform", "position", "rotation", "lossyScale", "localPosition", "localRotation", "rig"]);
  const EXACT_KEYS = new Set(["clock"]);

  function finiteArray(value) {
    return Array.from(value, (item) => Number.isFinite(item) ? item : NaN);
  }

  // Matrix4.decompose only reads the matrix; the temporaries hold the result.
  function decompose(matrix, temp) {
    matrix.decompose(temp.position, temp.quaternion, temp.scale);
    return { position: temp.position.toArray(), rotation: temp.quaternion.toArray(), lossyScale: temp.scale.toArray() };
  }

  function temporaries(T) {
    return { position: new T.Vector3(), quaternion: new T.Quaternion(), scale: new T.Vector3(),
      matrix: new T.Matrix4(), inverse: new T.Matrix4(), point: new T.Vector3() };
  }

  function worldPosition(node, temp) {
    return temp.point.setFromMatrixPosition(node.matrixWorld).toArray();
  }

  function effectiveVisible(node) {
    for (let current = node; current; current = current.parent) if (!current.visible) return false;
    return true;
  }

  function nodeName(node) {
    return typeof node?.userData?.name === "string" ? node.userData.name : node?.name ?? "";
  }

  function materialName(material) {
    const name = material?.name || "";
    // SifasMaterial names its shader copy "<Unity name> (<shader>)".
    return material?.userData?.sifas ? name.replace(/ \([^()]*\)$/, "") : name;
  }

  // A 1x1 DataTexture is a constant the editor binds where a material has no
  // texture of its own (sifas-material.js constantTexture, display/overlay
  // white): it has no Unity counterpart, so the comparator reports it as a
  // note instead of an exact texture mismatch.
  function placeholderTexture(texture, image) {
    return texture.userData?.placeholder === true || (texture.isDataTexture === true && image?.width === 1 && image?.height === 1);
  }

  // Name (the Unity asset name the importer exported, e.g. "ch0212_co0002_head_rim";
  // an array slice keeps its array's name and reports arrayLayer), size and
  // mip level count (authored levels uploaded with the texture, else 1).
  // Three.js (r128 WebGLTextures.textureNeedsGenerateMipmaps) builds the chain
  // on the GPU when no level is uploaded, generateMipmaps is on and the minifying
  // filter samples mips. Such a chain is not the authored one: report it as
  // generated so a comparison never reads it as the asset's mip count.
  function generatedMips(texture, width, height) {
    if (texture.isCompressedTexture || !texture.generateMipmaps) return 0;
    // THREE.NearestFilter 1003, THREE.LinearFilter 1006 sample only level 0.
    if (texture.minFilter === 1003 || texture.minFilter === 1006) return 0;
    if (!(width > 0 && height > 0)) return 0;
    return Math.floor(Math.log2(Math.max(width, height))) + 1;
  }

  function textureIdentity(texture) {
    if (!texture || !texture.isTexture) return null;
    const image = Array.isArray(texture.image) ? texture.image[0] : texture.image;
    const identity = texture.userData?.viewerTexture;
    const width = Number.isFinite(image?.width) ? image.width : null, height = Number.isFinite(image?.height) ? image.height : null;
    const authored = Array.isArray(texture.mipmaps) ? texture.mipmaps.length : 0;
    const generated = authored ? 0 : generatedMips(texture, width, height);
    const result = { name: texture.name || (typeof identity?.id === "string" ? identity.id : null),
      width, height, mips: authored || generated || 1 };
    if (generated) result.mipsGenerated = true;
    if (Number.isInteger(texture.userData?.sifasArrayLayer)) result.arrayLayer = texture.userData.sifasArrayLayer;
    if (placeholderTexture(texture, image)) result.placeholder = true;
    return result;
  }

  // The compiled Hidden/AS/Member/Main variant keywords the editor reproduces
  // with SifasMaterial defines. Every variant evaluates the rim (no keyword).
  const MEMBER_VARIANTS = { SIFAS_CHEEK: "_CHEEK_ON", SIFAS_MATCAP: "_MATCAP_ON", SIFAS_EMISSIVE: "_EMISSIVE_ON" };

  // Effective Unity keywords of an AS/Member material: the authored keywords
  // with each variant keyword replaced by the state the editor draws, as
  // Material.shaderKeywords reads in the game (the runtime only toggles
  // _CHEEK_ON there; the legacy _RIMLIGHT_ON is left as authored).
  function memberKeywords(material) {
    const authored = Array.isArray(material.userData?.sifas?.keywords) ? material.userData.sifas.keywords : [];
    const variants = new Set(Object.values(MEMBER_VARIANTS));
    const result = authored.filter((keyword) => typeof keyword === "string" && !variants.has(keyword));
    for (const [define, keyword] of Object.entries(MEMBER_VARIANTS)) if (material.defines?.[define]) result.push(keyword);
    return result.sort();
  }

  function uniformValue(value) {
    if (value === null || value === undefined) return { t: "null", v: null };
    if (typeof value === "number") return { t: "float", v: value };
    if (typeof value === "boolean") return { t: "bool", v: value };
    if (value.isTexture) return { t: "tex", v: textureIdentity(value) };
    if (value.isVector4 || value.isQuaternion) return { t: "vector", v: [value.x, value.y, value.z, value.w] };
    if (value.isVector3) return { t: "vector", v: [value.x, value.y, value.z] };
    if (value.isVector2) return { t: "vector", v: [value.x, value.y] };
    if (value.isColor) return { t: "color", v: [value.r, value.g, value.b] };
    if (value.isMatrix4 || value.isMatrix3) return { t: "matrix", v: Array.from(value.elements) };
    if (Array.isArray(value)) return { t: "array", v: value.length };
    return { t: "other", v: null };
  }

  function tableUniforms(material, table, kind) {
    const properties = {}, unmapped = [], editorOnly = [], globals = {};
    for (const [uniform, holder] of Object.entries(material.uniforms || {})) {
      if (GLOBAL_UNIFORMS[uniform]) { globals[GLOBAL_UNIFORMS[uniform]] = uniformValue(holder?.value).v; continue; }
      if (EDITOR_ONLY.has(uniform)) { editorOnly.push(uniform); continue; }
      const entry = table[uniform];
      if (!entry) { unmapped.push(uniform); continue; }
      const read = uniformValue(holder?.value);
      const property = properties[entry.name] || (properties[entry.name] = { from: uniform });
      if (entry.t === "st") {
        property.st = read.v;
        property.stFrom = uniform;
        if (!property.t) property.t = "tex";
      } else {
        property.t = entry.t === "color" && read.t === "vector" ? "color" : read.t === "tex" ? "tex" : entry.t;
        property.v = read.v;
        property.from = uniform;
      }
    }
    return { kind, properties, unmapped: unmapped.sort(), editorOnly: editorOnly.sort(), globals };
  }

  // AS/Member (SifasMaterial): u<X> -> _<X>.
  function memberUniforms(material) {
    const properties = {}, unmapped = [], editorOnly = [], globals = {};
    for (const [uniform, holder] of Object.entries(material.uniforms || {})) {
      if (EDITOR_ONLY.has(uniform)) { editorOnly.push(uniform); continue; }
      if (!/^u[A-Z]/.test(uniform)) { unmapped.push(uniform); continue; }
      const name = "_" + uniform.slice(1);
      const read = uniformValue(holder?.value);
      const color = read.t === "vector" && /Color|Col$/.test(name);
      properties[name] = { t: color ? "color" : read.t, v: read.v, from: uniform };
    }
    // The OUTLINE pass stencil comparison (LiveCoreMemberRimlight.ApplyEnable).
    const stencil = material.userData?.sifasRuntime?.outlineStencilComp;
    if (Number.isInteger(stencil)) properties._OutlineStencilComp = { t: "float", v: stencil, from: "outline stencilFunc" };
    return { kind: "member", properties, unmapped: unmapped.sort(), editorOnly: editorOnly.sort(), globals,
      keywords: memberKeywords(material), rimlightEvaluated: !!material.defines?.SIFAS_RIMLIGHT };
  }

  function stageUniforms(material) {
    return tableUniforms(material, STAGE_TABLE, "stage");
  }

  function coloringUniforms(material) {
    return tableUniforms(material, COLORING_TABLE, "coloring");
  }

  // Standard three.js materials from the glTF have no Unity property mapping.
  function genericProperties(material) {
    const properties = {}, unmapped = [];
    if (material.map) unmapped.push("map");
    if (material.color?.isColor) unmapped.push("color");
    const values = {};
    if (material.color?.isColor) values.color = [material.color.r, material.color.g, material.color.b];
    if (material.map) values.map = textureIdentity(material.map);
    if (Number.isFinite(material.opacity)) values.opacity = material.opacity;
    return { kind: material.isShaderMaterial ? "shader" : "gltf", properties, unmapped, editorOnly: [], globals: {}, values };
  }

  function materialProperties(material) {
    if (!material) return { kind: "none", properties: {}, unmapped: [], editorOnly: [], globals: {} };
    if (material.userData?.sifas && material.uniforms) return memberUniforms(material);
    const uniforms = material.uniforms || {};
    if (uniforms.tint && (uniforms.mainUVTransform || uniforms.ambient || !uniforms.uTint)) return stageUniforms(material);
    if (uniforms.uShift && uniforms.uSpeed && uniforms.uSelfTime) return coloringUniforms(material);
    if (material.isShaderMaterial) {
      const values = {}, unmapped = [];
      for (const [uniform, holder] of Object.entries(uniforms)) {
        unmapped.push(uniform);
        const read = uniformValue(holder?.value);
        if (read.t !== "other" && read.t !== "matrix") values[uniform] = read;
      }
      const globals = {};
      for (const [uniform, name] of Object.entries(GLOBAL_UNIFORMS)) {
        if (uniforms[uniform]) globals[name] = uniformValue(uniforms[uniform].value).v;
      }
      return { kind: "shader", properties: {}, unmapped: unmapped.sort(), editorOnly: [], globals, values };
    }
    return genericProperties(material);
  }

  function rendererScope(record, actorsGroup) {
    if (record.group === actorsGroup) return Number.isInteger(record.position) ? `member${record.position}` : "other";
    if (record.role === "stage") return "stage";
    if (record.role === "stage-effects" || record.role === "effect") return "effect";
    return "other";
  }

  function skipMesh(mesh) {
    return !mesh.isMesh || mesh.userData?.sifasOutline || mesh.userData?.viewerHelper;
  }

  // Renderers of one record root: a glTF node with a mesh, or the node that
  // groups the primitives of one multi-material Unity renderer.
  function renderersOf(root) {
    const owners = new Map();
    root.traverse((node) => {
      if (skipMesh(node)) return;
      let owner = node;
      if (typeof node.userData?.name !== "string" && node.parent && !node.parent.isMesh &&
          typeof node.parent.userData?.name === "string") owner = node.parent;
      if (!owners.has(owner)) owners.set(owner, []);
      owners.get(owner).push(node);
    });
    return owners;
  }

  // Unity GameObject path of a renderer relative to its record root, read from
  // the glTF node name chain (schema 1.5, "path"). The server keeps the
  // original prefab hierarchy only for animated stage renderers: each of those
  // GameObjects is a node tagged extras.mvStageNode (userData.name is the
  // GameObject name) and the mesh node, named after the Mesh asset, is a child
  // of its GameObject node. Every other renderer is a flattened mesh node
  // (stage/effect root, or the performer rig's "Character" root), which holds
  // no GameObject names at all: its path is null and only the mesh name joins.
  function gameObjectPath(owner, root) {
    const tagged = (node) => node?.userData && typeof node.userData.mvStageNode === "object" && node.userData.mvStageNode !== null;
    const gameObject = tagged(owner) ? owner : owner?.parent;
    if (!tagged(gameObject)) return { path: null, pathSource: "flattened" };
    const names = [];
    for (let node = gameObject; node && node !== root; node = node.parent) {
      if (tagged(node)) names.push(nodeName(node));
      // Editor-made wrappers carry no glTF name; any other glTF node breaks the GameObject chain.
      else if (typeof node.userData?.name === "string") return { path: null, pathSource: "flattened" };
    }
    return { path: names.reverse().join("/"), pathSource: "stageNodes" };
  }

  // Keys follow schema 1.5. Duplicate mesh names in one scope get "#n".
  function keyFor(kind, parts) {
    if (kind === "renderer") return `renderer:${parts.scope}:${parts.mesh}${parts.index > 1 ? "#" + parts.index : ""}`;
    if (kind === "material") return `material:${parts.renderer}#${parts.slot}`;
    if (kind === "stageNode") return `stageNode:${parts.binding}#${parts.path}`;
    if (kind === "bone") return `member:${parts.slot}:${parts.path}`;
    if (kind === "anchor") return parts.slot === undefined ? `anchor:${parts.name}` : `anchor:member${parts.slot}:${parts.name}`;
    if (kind === "track") return `track:${parts.nativeClass}@${parts.binding}`;
    if (kind === "camera") return `camera:${parts.role}`;
    throw new Error(`Unknown dump key family ${kind}`);
  }

  function round(value, digits) {
    if (Number.isInteger(value)) return value;
    const rounded = Number(value.toPrecision(digits));
    return Object.is(rounded, -0) ? 0 : rounded;
  }

  // Serializes like the game producer: non-finite numbers become null and are
  // listed by dotted path; cameras, matrices and transforms keep 9 significant
  // digits and everything else 7. The clock keeps full precision (join key).
  function finalize(value, nonFinite, path = "", precise = false, exact = false) {
    if (typeof value === "number") {
      if (!Number.isFinite(value)) { nonFinite.push(path); return null; }
      return exact ? value : round(value, precise ? 9 : 7);
    }
    if (Array.isArray(value)) return value.map((item, index) => finalize(item, nonFinite, `${path}.${index}`, precise, exact));
    if (value && typeof value === "object") {
      const result = {};
      for (const [key, item] of Object.entries(value)) {
        result[key] = finalize(item, nonFinite, path ? `${path}.${key}` : key,
          precise || PRECISE_SECTIONS.has(key) || MATRIX_KEYS.has(key), exact || EXACT_KEYS.has(key));
      }
      return result;
    }
    return value;
  }

  function aspectCorrection(aspect, bounds) {
    const min = bounds?.min ?? 0.75, max = bounds?.max ?? 1;
    return Math.min(max, Math.max(min, aspect / (16 / 9)));
  }

  global.MVStudioAssetDump = { SCHEMA, CONVENTIONS, STAGE_TABLE, COLORING_TABLE, EDITOR_ONLY: Array.from(EDITOR_ONLY),
    temporaries, decompose, worldPosition, effectiveVisible, nodeName, materialName, textureIdentity, memberKeywords, uniformValue,
    memberUniforms, stageUniforms, coloringUniforms, materialProperties, rendererScope, renderersOf, gameObjectPath, keyFor, round,
    finalize, finiteArray, aspectCorrection };
})(typeof window !== "undefined" ? window : globalThis);
