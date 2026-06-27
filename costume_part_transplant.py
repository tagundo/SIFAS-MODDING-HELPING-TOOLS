#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS Costume Part Transplant — move ONE costume part (wings / tail / …)
=======================================================================
Where ``costume_transplant.py`` swaps a whole outfit, this tool moves a *single
part* of a costume — a pair of wings, a tail, a cape — from a DONOR model bundle
onto a TARGET model bundle, leaving everything else about the target (its body,
face, hair, its own clothes) untouched.

How SIFAS stores a "part"
-------------------------
In a SIFAS ``chXXXX_coYYYY_member`` bundle the costume is *baked into the single
Body SkinnedMeshRenderer* — body + clothing + any wings/tail are one mesh. A part
like a wing is therefore not a separate object you can copy wholesale; it is a
*region of vertices and triangles* inside the Body mesh that is skinned to its
own dedicated bones (e.g. ``Wing_L_00`` / ``Tail_01`` …). Those bones are
costume-specific: they exist in the donor's rig but not in a plain body rig.

So a part transplant is mesh surgery:

    1. pick the part's bones (a root bone + its descendants, or auto-detected as
       the donor body bones that the target does not have);
    2. select the vertices skinned to those bones, and the triangles that join
       them;
    3. inject the part's bones into the target rig (as real GameObjects /
       Transforms, with their SwingBone jiggle physics when present);
    4. append the part's vertices + triangles to the target Body mesh, remapping
       their bone indices to the target's (extended) bone list and their bind
       poses alongside;
    5. give the part its material/texture: if the part is its own sub-mesh in the
       donor it is copied as a new sub-mesh + material (clean); if it shares the
       body atlas you can optionally patch its UV region across so it keeps its
       look on the target's own body texture;
    6. world-space the result and re-anchor NodeScaling, exactly like
       costume_transplant, so swinging pieces render where they were modelled.

What is kept (target identity): the entire target Body mesh, its bones,
textures, face, hair — nothing of the target is replaced, the part is *added*.

Usage
-----
    # graphical interface (run with no arguments, or --gui):
    python3 costume_part_transplant.py

    # inspect a bundle: list renderers, sub-meshes and candidate parts
    python3 costume_part_transplant.py inspect --bundle DONOR.unity

    # transplant a part (root bone names what to take; --auto picks the biggest
    # costume-specific bone group):
    python3 costume_part_transplant.py transplant \
        --donor WINGS.unity --target ME.unity --out OUT.unity --part-root Wing_L_00
    python3 costume_part_transplant.py transplant \
        --donor WINGS.unity --target ME.unity --out OUT.unity --auto --dry-run

    # verify the pure mesh-surgery maths (no bundle needed):
    python3 costume_part_transplant.py selftest

``--dry-run`` reports exactly what would be copied (bones, vertices, triangles,
sub-meshes, UV bounds) and writes nothing — run it first on your real files.

Verified against the same Unity 2018.4 uncompressed SIFAS model bundles as the
other tools. This is an unofficial, fan-made tool; use at your own risk.
"""

import os
import sys
import zlib
import copy
import json as _json
import argparse
import importlib
import subprocess


# --------------------------------------------------------------------------
# self-contained multi-language support (English default; 한국어 / 日本語)
# Shares ~/.config/sifas_modding_tools/config.json with the other tools so the
# language picked in any one of them is remembered here too.
# --------------------------------------------------------------------------
class _LangStore:
    @staticmethod
    def _path():
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(base, "sifas_modding_tools", "config.json")

    def get_language(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                return _json.load(f).get("language")
        except Exception:
            return None

    def set_language(self, code):
        try:
            p = self._path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            data = {}
            try:
                with open(p, encoding="utf-8") as f:
                    data = _json.load(f)
            except Exception:
                pass
            data["language"] = code
            with open(p, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


_shared_i18n = _LangStore()
_LANG_NAMES = (("en", "English"), ("ko", "한국어"), ("ja", "日本語"))
_TRANSLATIONS = {
    "ko": {
        "Language": "언어",
        "SIFAS Costume Part Transplant": "SIFAS 코스튬 부위 이식",
        "Donor  (part source)": "공여 (부위 원본)",
        "Target (wearer / identity)": "대상 (착용자 / 정체성)",
        "Output bundle": "출력 번들",
        "Browse…": "찾아보기…",
        "Part to move": "옮길 부위",
        "Refresh part list": "부위 목록 새로고침",
        "Options": "옵션",
        "Preserve the part's jiggle physics (SwingBone)": "부위의 흔들림 물리(SwingBone) 유지",
        "Restore body collision for the part's bones": "부위 본의 바디 콜리전 복원",
        "Add the part as its own sub-mesh + material (keep its texture)":
            "부위를 별도 서브메시 + 머티리얼로 추가 (텍스처 유지)",
        "Patch the part's texture region onto the target body atlas":
            "부위 텍스처 영역을 대상 바디 아틀라스에 합성",
        "World-space the body mesh (so swinging parts render correctly)":
            "바디 메시를 월드 공간으로 (흔들리는 부위가 올바르게 렌더링되도록)",
        "Re-anchor NodeScaling to keep the wearer's body shape":
            "착용자 체형 유지를 위해 NodeScaling 재고정",
        "Preview only (dry-run) — report what would change, write nothing":
            "미리보기만 (dry-run) — 변경 내용만 보고하고 저장 안 함",
        "Transplant part": "부위 이식",
        "Save output bundle": "출력 번들 저장",
        "Select bundle": "번들 선택",
        "[error] choose donor, target, output and a part first.\n":
            "[오류] 먼저 공여·대상·출력과 부위를 선택하세요.\n",
        "\n[success] done — verified ✓\n": "\n[성공] 완료 — 검증됨 ✓\n",
        "\n[error] output has dangling references!\n": "\n[오류] 출력에 끊긴 참조가 있습니다!\n",
        "(load a donor bundle to list its parts)": "(공여 번들을 불러오면 부위가 표시됩니다)",
    },
    "ja": {
        "Language": "言語",
        "SIFAS Costume Part Transplant": "SIFAS 衣装パーツ移植",
        "Donor  (part source)": "提供元（パーツソース）",
        "Target (wearer / identity)": "対象（着用者 / アイデンティティ）",
        "Output bundle": "出力バンドル",
        "Browse…": "参照…",
        "Part to move": "移動するパーツ",
        "Refresh part list": "パーツ一覧を更新",
        "Options": "オプション",
        "Preserve the part's jiggle physics (SwingBone)": "パーツのジグル物理（SwingBone）を保持",
        "Restore body collision for the part's bones": "パーツボーンのボディコリジョンを復元",
        "Add the part as its own sub-mesh + material (keep its texture)":
            "パーツを独立したサブメッシュ + マテリアルとして追加（テクスチャを保持）",
        "Patch the part's texture region onto the target body atlas":
            "パーツのテクスチャ領域を対象ボディアトラスに合成",
        "World-space the body mesh (so swinging parts render correctly)":
            "ボディメッシュをワールド空間に（揺れるパーツが正しく描画されるよう）",
        "Re-anchor NodeScaling to keep the wearer's body shape":
            "着用者の体型を維持するためNodeScalingを再アンカー",
        "Preview only (dry-run) — report what would change, write nothing":
            "プレビューのみ（dry-run）— 変更内容を報告し保存しない",
        "Transplant part": "パーツ移植",
        "Save output bundle": "出力バンドルを保存",
        "Select bundle": "バンドルを選択",
        "[error] choose donor, target, output and a part first.\n":
            "[エラー] 先に提供元・対象・出力とパーツを選択してください。\n",
        "\n[success] done — verified ✓\n": "\n[成功] 完了 — 検証済み ✓\n",
        "\n[error] output has dangling references!\n": "\n[エラー] 出力に未解決の参照があります！\n",
        "(load a donor bundle to list its parts)": "(提供元バンドルを読み込むとパーツが表示されます)",
    },
}


def _normalize_lang(code):
    c = str(code or "").strip().lower().replace("-", "_").split("_")[0].split(".")[0]
    if c in ("ko", "kr", "kor"):
        return "ko"
    if c in ("ja", "jp", "jpn"):
        return "ja"
    return "en"


_LANG = _normalize_lang(
    (_shared_i18n.get_language() if _shared_i18n is not None else None)
    or os.environ.get("SIFAS_LANG", "en")
)


def _get_lang():
    return _LANG


def _set_lang(code, **_kw):
    global _LANG
    _LANG = _normalize_lang(code)
    if _shared_i18n is not None:
        try:
            _shared_i18n.set_language(_LANG)
        except Exception:
            pass
    return _LANG


def _lang_opts():
    return [tuple(x) for x in _LANG_NAMES]


def _tr(text, **kw):
    s = _TRANSLATIONS.get(_LANG, {}).get(text, text)
    return s.format(**kw) if kw else s


# --------------------------------------------------------------------------
# dependency bootstrap (mirrors the other tools so Termux works too).
# numpy is required up front; UnityPy is loaded lazily so the pure mesh-surgery
# maths (and `selftest`) work without it / before it is installed.
# --------------------------------------------------------------------------
def is_termux():
    if "com.termux" in (os.environ.get("PREFIX", "") + os.environ.get("HOME", "")):
        return True
    return os.path.isdir("/data/data/com.termux")


def _run(cmd):
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception:
        return False


def _pip_install(pip_name):
    cmd = [sys.executable, "-m", "pip", "install", pip_name]
    return _run(cmd + ["--break-system-packages", "-q"]) or _run(cmd + ["-q"])


def _pkg_install_termux(pkg):
    if _run(["pkg", "install", "-y", pkg]) or _run(["apt", "install", "-y", pkg]):
        return True
    _run(["apt", "update", "-y"])
    return _run(["pkg", "install", "-y", pkg]) or _run(["apt", "install", "-y", pkg])


_TERMUX_PKG = {"PIL": "python-pillow", "Pillow": "python-pillow"}


def ensure_module(import_name, pip_name=None, hard=True):
    try:
        return importlib.import_module(import_name)
    except ImportError:
        pass
    pip_name = pip_name or import_name
    print(f"[setup] installing '{pip_name}' ...")
    if is_termux():
        pkg = _TERMUX_PKG.get(pip_name) or _TERMUX_PKG.get(import_name)
        if pkg:
            _pkg_install_termux(pkg)
            try:
                return importlib.import_module(import_name)
            except ImportError:
                pass
    _pip_install(pip_name)
    try:
        return importlib.import_module(import_name)
    except ImportError:
        msg = f"[setup] could not install '{pip_name}'. Install it manually and re-run."
        if not hard:
            print(msg)
            return None
        print(msg)
        if is_termux():
            print("    pkg install -y python-pillow")
            print("    pip install UnityPy --break-system-packages")
        else:
            print(f"    pip install {pip_name}")
        sys.exit(1)


np = ensure_module("numpy")

UnityPy = None
try:                                   # let pure functions import without UnityPy
    import UnityPy as _UnityPy
    UnityPy = _UnityPy
except Exception:
    pass


def _require_unitypy():
    global UnityPy
    if UnityPy is None:
        if is_termux():
            ensure_module("PIL", "Pillow")
        UnityPy = ensure_module("UnityPy")
    return UnityPy


def _require_pil(hard=False):
    return ensure_module("PIL", "Pillow", hard=hard)


# ==========================================================================
# 1. SIFAS mesh-format primitives (vertex stream + index buffer)
#    Channel order matches Unity 2018.4: 0=pos 1=normal 2=tangent 3=color
#    4..11=UV0..7  12=BlendWeight  13=BlendIndices.
# ==========================================================================
FMT_BYTES = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}
ATTR_POS, ATTR_NORMAL, ATTR_TANGENT, ATTR_COLOR = 0, 1, 2, 3
ATTR_UV0 = 4
ATTR_BLENDWEIGHT, ATTR_BLENDINDICES = 12, 13


def _align16(x):
    return (x + 15) & ~15


def stream_layout(tree):
    """Return (vc, chans, stride{stream:int}, start{stream:int}, total_bytes)."""
    vd = tree["m_VertexData"]
    vc = vd["m_VertexCount"]
    chans = vd["m_Channels"]
    by_stream = {}
    for ch in chans:
        if ch.get("dimension", 0) == 0:
            continue
        by_stream.setdefault(ch["stream"], []).append(ch)
    stride, start, cur = {}, {}, 0
    for s in sorted(by_stream):
        stride[s] = max(c["offset"] + c["dimension"] * FMT_BYTES[c["format"]]
                        for c in by_stream[s])
    for s in sorted(by_stream):
        start[s] = cur
        cur = _align16(cur + vc * stride[s])
    return vc, chans, stride, start, cur


def _block(u8, s, stride, start, vc):
    return u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])


def read_attr(u8, attr, chans, stride, start, vc):
    """Read channel `attr` as float64 (or int64 for integer formats). None if absent."""
    if attr >= len(chans):
        return None
    ch = chans[attr]
    if ch.get("dimension", 0) == 0:
        return None
    s, off, dim, fmt = ch["stream"], ch["offset"], ch["dimension"], ch["format"]
    raw = _block(u8, s, stride, start, vc)[:, off:off + dim * FMT_BYTES[fmt]]
    if fmt == 0:
        return raw.copy().view("<f4").reshape(vc, dim).astype(np.float64)
    if fmt == 11:
        return raw.copy().view("<i4").reshape(vc, dim).astype(np.int64)
    if fmt == 10:
        return raw.copy().view("<u4").reshape(vc, dim).astype(np.int64)
    if fmt == 2:
        return raw.copy().reshape(vc, dim).astype(np.float64) / 255.0
    if fmt == 6:
        return raw.copy().reshape(vc, dim).astype(np.int64)
    raise NotImplementedError(f"vertex format {fmt} not supported (read)")


def write_attr(u8, arr, attr, chans, stride, start, vc):
    ch = chans[attr]
    s, off, dim, fmt = ch["stream"], ch["offset"], ch["dimension"], ch["format"]
    block = _block(u8, s, stride, start, vc)
    if fmt == 0:
        packed = np.ascontiguousarray(arr[:, :dim], "<f4").view(np.uint8)
        block[:, off:off + dim * 4] = packed.reshape(vc, dim * 4)
    elif fmt == 11:
        packed = np.ascontiguousarray(arr[:, :dim], "<i4").view(np.uint8)
        block[:, off:off + dim * 4] = packed.reshape(vc, dim * 4)
    elif fmt == 10:
        packed = np.ascontiguousarray(arr[:, :dim], "<u4").view(np.uint8)
        block[:, off:off + dim * 4] = packed.reshape(vc, dim * 4)
    elif fmt == 2:
        u = np.clip(arr[:, :dim] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        block[:, off:off + dim] = u
    elif fmt == 6:
        block[:, off:off + dim] = np.clip(arr[:, :dim], 0, 255).astype(np.uint8)
    else:
        raise NotImplementedError(f"vertex format {fmt} not supported (write)")


def read_indices(tree):
    fmt = tree.get("m_IndexFormat", 0)
    buf = bytes(tree["m_IndexBuffer"])
    return np.frombuffer(buf, "<u2" if fmt == 0 else "<u4").astype(np.int64)


def get_skin(u8, tree, chans, stride, start, vc):
    """(weights[vc,4] float, bone_indices[vc,4] int) from vertex channels or m_Skin."""
    w = read_attr(u8, ATTR_BLENDWEIGHT, chans, stride, start, vc)
    bi = read_attr(u8, ATTR_BLENDINDICES, chans, stride, start, vc)
    if w is not None and bi is not None:
        return w.astype(np.float64), bi.astype(np.int64)
    skin = tree.get("m_Skin", [])
    if skin:
        W = np.zeros((vc, 4)); B = np.zeros((vc, 4), int)
        for i, e in enumerate(skin):
            for k in range(4):
                B[i, k] = e.get(f"boneIndex[{k}]", 0)
                W[i, k] = e.get(f"weight[{k}]", 0.0)
        return W, B
    return None, None


# --- 4x4 matrix helpers (Unity Matrix4x4f eRC = row R, col C) ---
def mat_from(d):
    return np.array([[d["e00"], d["e01"], d["e02"], d["e03"]],
                     [d["e10"], d["e11"], d["e12"], d["e13"]],
                     [d["e20"], d["e21"], d["e22"], d["e23"]],
                     [d["e30"], d["e31"], d["e32"], d["e33"]]], float)


def mat_to(M, dst):
    for r in range(4):
        for c in range(4):
            dst["e%d%d" % (r, c)] = float(M[r, c])


def _mat_dict(M):
    d = {}
    mat_to(M, d)
    return d


def _quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 0],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x), 0],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y), 0],
                     [0, 0, 0, 1]], float)


def _trs(t, q, s):
    M = _quat_mat(q)
    M[:3, 0] *= s[0]; M[:3, 1] *= s[1]; M[:3, 2] *= s[2]
    M[0, 3], M[1, 3], M[2, 3] = t
    return M


# ==========================================================================
# 2. Pure mesh-surgery maths (numpy only — exercised by `selftest`)
#    These take plain typetree dicts + numpy arrays so they can be tested
#    without UnityPy or a real bundle.
# ==========================================================================
def bone_membership(n_bones, part_bone_ids):
    m = np.zeros(max(n_bones, 1), bool)
    for b in part_bone_ids:
        if 0 <= b < len(m):
            m[b] = True
    return m


def part_vertex_mask(W, BI, bone_is_part, threshold=0.5):
    """Boolean mask[vc]: a vertex belongs to the part when the weight summed over
    its part-bone influences reaches `threshold` (0.5 = "mostly the part")."""
    vc = W.shape[0]
    if vc == 0:
        return np.zeros(0, bool)
    idx = np.clip(BI, 0, len(bone_is_part) - 1)
    contrib = (W * bone_is_part[idx]).sum(axis=1)
    return contrib >= threshold


def part_triangles(tris, vmask, mode="all"):
    """Triangles to take. mode='all': every corner is a part vertex (clean seam);
    'any': at least one corner (greedier, may drag body verts)."""
    if len(tris) == 0:
        return tris.reshape(0, 3)
    m = vmask[tris]
    keep = m.all(axis=1) if mode == "all" else m.any(axis=1)
    return tris[keep]


def extract_subgeometry(part_tris):
    """used = sorted unique donor vertex ids referenced by the part triangles;
    local_tris = the same triangles renumbered to 0..len(used)-1."""
    if len(part_tris) == 0:
        return np.zeros(0, np.int64), part_tris.reshape(0, 3)
    used = np.unique(part_tris)
    local = np.searchsorted(used, part_tris)
    return used, local.astype(np.int64)


def build_bone_remap(donor_bone_names, target_bone_names, referenced_donor_ids):
    """Map each referenced donor bone id to a slot in the *combined* target bone
    list. Bones the target already has (by name) reuse that slot; the rest are
    appended after the target's bones. Returns (remap{donor_id:combined_idx},
    injected_donor_ids[in append order])."""
    tname2idx = {}
    for i, n in enumerate(target_bone_names):
        tname2idx.setdefault(n, i)
    remap, injected = {}, []
    nxt = len(target_bone_names)
    for di in sorted(int(x) for x in referenced_donor_ids):
        name = donor_bone_names[di] if di < len(donor_bone_names) else None
        if name is not None and name in tname2idx:
            remap[di] = tname2idx[name]
        else:
            remap[di] = nxt
            injected.append(di)
            nxt += 1
    return remap, injected


def remap_skin_indices(part_BI, remap, default_idx=0):
    """Translate donor bone indices on the part vertices to combined indices."""
    if len(part_BI) == 0:
        return part_BI.copy()
    mx = int(part_BI.max()) + 1 if part_BI.size else 1
    lut = np.full(max(mx, 1), default_idx, np.int64)
    for d, t in remap.items():
        if 0 <= d < len(lut):
            lut[d] = t
    return lut[np.clip(part_BI, 0, len(lut) - 1)]


def referenced_bone_ids(part_W, part_BI):
    """Donor bone ids that carry non-zero weight on the part vertices."""
    if len(part_BI) == 0:
        return []
    mask = part_W > 0
    return sorted({int(b) for b in part_BI[mask].ravel().tolist()})


def assemble_appended_buffer(tree, target_u8, append_attrs, new_vc):
    """Build a fresh vertex buffer for `new_vc` vertices: the existing target rows
    [0:tvc) copied verbatim per stream, then the appended rows filled from
    `append_attrs` {attr_index: ndarray(K, dim)}. Returns the new bytes.

    Assumes the channel layout is unchanged (only the count grows), which is true
    when donor and target share the SIFAS body vertex format."""
    tvc = tree["m_VertexData"]["m_VertexCount"]
    K = new_vc - tvc
    _, chans, ostride, ostart, _ = stream_layout(tree)
    # new layout for the larger count
    tree2 = {"m_VertexData": {"m_VertexCount": new_vc, "m_Channels": chans}}
    nvc, nchans, nstride, nstart, ntotal = stream_layout(tree2)
    buf = bytearray(ntotal)
    u8 = np.frombuffer(buf, np.uint8)
    # copy existing rows per stream (strides are identical, only the row count grew)
    for s in ostride:
        old_blk = target_u8[ostart[s]:ostart[s] + tvc * ostride[s]].reshape(tvc, ostride[s])
        new_blk = u8[nstart[s]:nstart[s] + nvc * nstride[s]].reshape(nvc, nstride[s])
        new_blk[:tvc, :] = old_blk
    # write appended rows channel by channel
    if K > 0:
        for attr, arr in append_attrs.items():
            ch = nchans[attr]
            if ch.get("dimension", 0) == 0:
                continue
            s, off, dim, fmt = ch["stream"], ch["offset"], ch["dimension"], ch["format"]
            blk = u8[nstart[s]:nstart[s] + nvc * nstride[s]].reshape(nvc, nstride[s])
            sub = blk[tvc:new_vc]
            a = np.asarray(arr, float)
            if a.shape[0] != K:
                raise ValueError(f"append channel {attr}: expected {K} rows, got {a.shape[0]}")
            if fmt == 0:
                sub[:, off:off + dim * 4] = np.ascontiguousarray(a[:, :dim], "<f4").view(np.uint8).reshape(K, dim * 4)
            elif fmt == 11:
                sub[:, off:off + dim * 4] = np.ascontiguousarray(a[:, :dim], "<i4").view(np.uint8).reshape(K, dim * 4)
            elif fmt == 10:
                sub[:, off:off + dim * 4] = np.ascontiguousarray(a[:, :dim], "<u4").view(np.uint8).reshape(K, dim * 4)
            elif fmt == 2:
                sub[:, off:off + dim] = np.clip(a[:, :dim] * 255.0 + 0.5, 0, 255).astype(np.uint8)
            elif fmt == 6:
                sub[:, off:off + dim] = np.clip(a[:, :dim], 0, 255).astype(np.uint8)
            else:
                raise NotImplementedError(f"vertex format {fmt} not supported (append)")
    return bytes(buf)


def collect_append_attrs(donor_tree, donor_u8, used, new_BI, new_W,
                         target_tree, mesh_root_delta=None):
    """Gather the per-channel values for the appended (part) vertices, sampled from
    the donor mesh at the `used` vertices. Skin channels (12/13) use the remapped
    new_BI / new_W. Positions/normals/tangents are moved by `mesh_root_delta`
    (4x4) so they land in the *target* mesh's space. Channels the target has but
    the donor lacks are zero-filled; channels the donor has but the target lacks
    are dropped."""
    dvc, dchans, dstride, dstart, _ = stream_layout(donor_tree)
    _, tchans, _, _, _ = stream_layout(target_tree)
    out = {}
    R = mesh_root_delta[:3, :3] if mesh_root_delta is not None else None
    for attr in range(len(tchans)):
        if tchans[attr].get("dimension", 0) == 0:
            continue
        if attr == ATTR_BLENDWEIGHT:
            out[attr] = new_W
            continue
        if attr == ATTR_BLENDINDICES:
            out[attr] = new_BI.astype(float)
            continue
        src = read_attr(donor_u8, attr, dchans, dstride, dstart, dvc)
        dim = tchans[attr]["dimension"]
        if src is None:
            out[attr] = np.zeros((len(used), dim))
            continue
        vals = src[used]
        if attr == ATTR_POS and mesh_root_delta is not None:
            h = np.c_[vals[:, :3], np.ones(len(vals))]
            vals = (h @ mesh_root_delta.T)[:, :3]
        elif attr in (ATTR_NORMAL, ATTR_TANGENT) and R is not None:
            v = vals.copy()
            v[:, :3] = vals[:, :3] @ R.T
            n = np.linalg.norm(v[:, :3], axis=1, keepdims=True)
            n[n == 0] = 1.0
            v[:, :3] = v[:, :3] / n
            vals = v
        out[attr] = vals
    return out


def splice_mesh(target_tree, donor_tree, part_tris_donor, used, new_BI, new_W,
                appended_bindposes, mesh_root_delta=None, new_submesh=False):
    """In-place splice of the part geometry into target_tree. Returns stats dict.

    target_tree / donor_tree are Unity Mesh typetrees. part_tris_donor are donor
    vertex-index triangles; `used` are the donor vertex ids to copy; new_BI/new_W
    are the part vertices' combined-index skin; appended_bindposes is the list of
    bind-pose matrices (4x4 numpy) for the newly injected bones, in append order.
    """
    tvc = target_tree["m_VertexData"]["m_VertexCount"]
    K = len(used)
    new_vc = tvc + K

    # donor vertex id -> appended target id
    order = {int(v): tvc + i for i, v in enumerate(used.tolist())}
    part_tris_target = np.vectorize(order.get)(part_tris_donor).astype(np.int64) \
        if len(part_tris_donor) else np.zeros((0, 3), np.int64)

    # 1) vertex buffer
    _, _, tstride, tstart, _ = stream_layout(target_tree)
    target_u8 = np.frombuffer(bytearray(target_tree["m_VertexData"]["m_DataSize"]), np.uint8)
    append_attrs = collect_append_attrs(donor_tree, np.frombuffer(
        bytearray(donor_tree["m_VertexData"]["m_DataSize"]), np.uint8),
        used, new_BI, new_W, target_tree, mesh_root_delta)
    new_buf = assemble_appended_buffer(target_tree, target_u8, append_attrs, new_vc)
    target_tree["m_VertexData"]["m_VertexCount"] = new_vc
    target_tree["m_VertexData"]["m_DataSize"] = new_buf

    # 2) skin: if the target stores skin in m_Skin (not channels), extend it too
    _, tchans, _, _, _ = stream_layout(target_tree)
    if tchans[ATTR_BLENDINDICES].get("dimension", 0) == 0 and target_tree.get("m_Skin"):
        skin = target_tree["m_Skin"]
        for i in range(K):
            e = {}
            for k in range(4):
                e[f"weight[{k}]"] = float(new_W[i, k])
                e[f"boneIndex[{k}]"] = int(new_BI[i, k])
            skin.append(e)

    # 3) index buffer + sub-meshes
    old_idx = read_indices(target_tree)
    idx_fmt = target_tree.get("m_IndexFormat", 0)
    if new_vc > 65535 and idx_fmt == 0:
        idx_fmt = 1
        target_tree["m_IndexFormat"] = 1
    dtype = "<u2" if idx_fmt == 0 else "<u4"
    part_flat = part_tris_target.reshape(-1)
    submeshes = target_tree.get("m_SubMeshes", [])
    if new_submesh and submeshes:
        combined = np.concatenate([old_idx, part_flat]).astype(dtype)
        target_tree["m_IndexBuffer"] = combined.tobytes()
        firstByte = len(old_idx) * (2 if idx_fmt == 0 else 4)
        sm = copy.deepcopy(submeshes[0])
        sm["firstByte"] = int(firstByte)
        sm["indexCount"] = int(part_flat.size)
        sm["firstVertex"] = int(tvc)
        sm["vertexCount"] = int(K)
        sm["baseVertex"] = 0
        sm["topology"] = submeshes[0].get("topology", 0)
        _set_submesh_aabb(sm, _part_positions_for_aabb(target_tree, tvc, new_vc))
        # widen earlier sub-meshes' vertexCount domain unchanged; just append ours
        submeshes.append(sm)
        target_tree["m_SubMeshes"] = submeshes
        added_submesh = len(submeshes) - 1
    else:
        # merge into the (last) body sub-mesh
        combined = np.concatenate([old_idx, part_flat]).astype(dtype)
        target_tree["m_IndexBuffer"] = combined.tobytes()
        if submeshes:
            sm = submeshes[-1]
            sm["indexCount"] = int(sm.get("indexCount", len(old_idx)) + part_flat.size)
            sm["vertexCount"] = int(sm.get("vertexCount", tvc) + K)
        added_submesh = None

    # 4) bind poses for the injected bones
    bp = target_tree.setdefault("m_BindPose", [])
    for M in appended_bindposes:
        bp.append(_mat_dict(M))

    # 5) bounds
    _recompute_local_aabb(target_tree)

    return {"new_vc": new_vc, "added_verts": K, "added_tris": len(part_tris_donor),
            "added_submesh": added_submesh, "index_format": idx_fmt}


def _part_positions_for_aabb(tree, lo, hi):
    vc, chans, stride, start, _ = stream_layout(tree)
    u8 = np.frombuffer(bytearray(tree["m_VertexData"]["m_DataSize"]), np.uint8)
    pos = read_attr(u8, ATTR_POS, chans, stride, start, vc)
    return pos[lo:hi] if pos is not None else None


def _set_submesh_aabb(sm, pos):
    box = sm.get("localAABB")
    if box is None or pos is None or len(pos) == 0:
        return
    mn, mx = pos.min(0), pos.max(0)
    c, e = (mn + mx) / 2, (mx - mn) / 2
    box["m_Center"] = {"x": float(c[0]), "y": float(c[1]), "z": float(c[2])}
    box["m_Extent"] = {"x": float(e[0]), "y": float(e[1]), "z": float(e[2])}


def _recompute_local_aabb(tree):
    vc, chans, stride, start, _ = stream_layout(tree)
    u8 = np.frombuffer(bytearray(tree["m_VertexData"]["m_DataSize"]), np.uint8)
    pos = read_attr(u8, ATTR_POS, chans, stride, start, vc)
    if pos is None:
        return
    mn, mx = pos.min(0), pos.max(0)
    c, e = (mn + mx) / 2, (mx - mn) / 2
    if tree.get("m_LocalAABB"):
        tree["m_LocalAABB"]["m_Center"] = {"x": float(c[0]), "y": float(c[1]), "z": float(c[2])}
        tree["m_LocalAABB"]["m_Extent"] = {"x": float(e[0]), "y": float(e[1]), "z": float(e[2])}


# ==========================================================================
# 3. bundle indexing / bone names / hierarchy / part detection
# ==========================================================================
def _index(env):
    objs = list(env.objects)
    return objs, {o.path_id: o for o in objs}


def _safe_tt(o):
    try:
        return o.read_typetree() if o is not None else None
    except Exception:
        return None


def _go_name(id2, go_pid):
    o = id2.get(go_pid)
    return o.read().m_Name if o else None


def _transform_goname(id2, tpid):
    o = id2.get(tpid)
    if not o:
        return None
    t = _safe_tt(o)
    return _go_name(id2, t.get("m_GameObject", {}).get("m_PathID")) if t else None


def _name2transform(id2):
    m = {}
    for pid, o in id2.items():
        if o.type.name == "Transform":
            n = _transform_goname(id2, pid)
            if n is not None and n not in m:
                m[n] = pid
    return m


def _transform_parent_byname(id2):
    out = {}
    for pid, o in id2.items():
        if o.type.name != "Transform":
            continue
        t = _safe_tt(o) or {}
        cn = _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))
        fp = t.get("m_Father", {}).get("m_PathID")
        pn = _transform_goname(id2, fp) if fp else None
        if cn is not None:
            out[cn] = pn
    return out


def _local_trs_byname(id2):
    out = {}
    for pid, o in id2.items():
        if o.type.name != "Transform":
            continue
        t = _safe_tt(o)
        if not t:
            continue
        n = _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))
        if n is not None:
            out[n] = (t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"])
    return out


def build_bone_name_map(env):
    """Avatar m_TOS: bone-name-hash -> transform path."""
    tos = {}
    for o in env.objects:
        if o.type.name == "Avatar":
            t = _safe_tt(o)
            if not t:
                continue
            for pair in t.get("m_TOS", []):
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    tos[int(pair[0]) & 0xFFFFFFFF] = pair[1]
    return tos


def _body_smr(objs):
    """The body SkinnedMeshRenderer: the skinned renderer with the most bones."""
    best, best_n = None, -1
    for o in objs:
        if o.type.name == "SkinnedMeshRenderer":
            n = len(_safe_tt(o).get("m_Bones", []))
            if n > best_n:
                best_n, best = n, o
    return best


def _smr_bone_names(id2, smr_tt):
    return [_transform_goname(id2, b["m_PathID"]) for b in smr_tt.get("m_Bones", [])]


def _bone_parent_array(id2, smr_tt):
    """Parent index within the SMR bone list (nearest ancestor that is also a
    bone), following Transform.m_Father. -1 = root."""
    pids = [b["m_PathID"] for b in smr_tt.get("m_Bones", [])]
    pid2idx = {p: i for i, p in enumerate(pids)}
    parent = []
    for p in pids:
        t = _safe_tt(id2.get(p)) or {}
        cur = (t.get("m_Father", {}).get("m_PathID") or 0)
        j, seen = -1, 0
        while cur and seen < 100000:
            if cur in pid2idx:
                j = pid2idx[cur]
                break
            ft = _safe_tt(id2.get(cur)) or {}
            cur = (ft.get("m_Father", {}).get("m_PathID") or 0)
            seen += 1
        parent.append(j)
    return parent


def _descendants(parent, root_idx):
    """All bone indices in the subtree rooted at root_idx (inclusive)."""
    children = {}
    for i, p in enumerate(parent):
        children.setdefault(p, []).append(i)
    out, stack = set(), [root_idx]
    while stack:
        i = stack.pop()
        if i in out:
            continue
        out.add(i)
        stack.extend(children.get(i, []))
    return out


def _bone_influence(donor_smr_tt, donor_mesh_tt):
    """vertex count weighted onto each bone index (length = len(m_Bones))."""
    nb = len(donor_smr_tt.get("m_Bones", []))
    infl = np.zeros(max(nb, 1))
    vc, chans, stride, start, _ = stream_layout(donor_mesh_tt)
    u8 = np.frombuffer(bytes(donor_mesh_tt["m_VertexData"]["m_DataSize"]), np.uint8)
    W, BI = get_skin(u8, donor_mesh_tt, chans, stride, start, vc)
    if W is None:
        return infl, 0
    BI = np.clip(BI, 0, nb - 1)
    cnt = np.zeros(max(nb, 1))
    for k in range(4):
        np.add.at(infl, BI[:, k], W[:, k])
        np.add.at(cnt, BI[:, k], (W[:, k] > 0).astype(float))
    return infl, cnt


def detect_parts(donor_objs, donor_id2, target_bone_names=None):
    """Group the donor body bones that are *costume-specific* (carry geometry and
    are not part of the shared base rig) into candidate parts, each a connected
    subtree. Returns [{root, root_idx, bones[names], bone_ids, verts, tris}]."""
    smr = _body_smr(donor_objs)
    if smr is None:
        return [], None
    smr_tt = _safe_tt(smr)
    mesh = donor_id2.get(smr_tt["m_Mesh"]["m_PathID"])
    mesh_tt = _safe_tt(mesh)
    names = _smr_bone_names(donor_id2, smr_tt)
    parent = _bone_parent_array(donor_id2, smr_tt)
    infl, cnt = _bone_influence(smr_tt, mesh_tt)

    base = set(target_bone_names) if target_bone_names else _BASE_RIG
    # a bone is "costume" if its name is not in the base rig
    is_costume = [bool(n) and n not in base for n in names]
    # candidate roots: costume bones whose parent is NOT costume (subtree tops)
    parts = []
    for i, n in enumerate(names):
        if not is_costume[i]:
            continue
        p = parent[i]
        if p >= 0 and is_costume[p]:
            continue
        sub = _descendants(parent, i)
        v = sum(int(cnt[j]) for j in sub if j < len(cnt))
        if v == 0:
            continue
        parts.append({
            "root": n, "root_idx": i,
            "bone_ids": sorted(sub),
            "bones": [names[j] for j in sorted(sub)],
            "verts": v,
        })
    # triangle counts per part (a triangle belongs to the part whose bones own all
    # 3 corners) — fill in via a single skin read
    _annotate_part_triangles(parts, smr_tt, mesh_tt)
    parts.sort(key=lambda d: -d["verts"])
    return parts, {"smr": smr, "smr_tt": smr_tt, "mesh": mesh, "mesh_tt": mesh_tt,
                   "names": names, "parent": parent}


def _annotate_part_triangles(parts, smr_tt, mesh_tt):
    if not parts:
        return
    nb = len(smr_tt.get("m_Bones", []))
    vc, chans, stride, start, _ = stream_layout(mesh_tt)
    u8 = np.frombuffer(bytes(mesh_tt["m_VertexData"]["m_DataSize"]), np.uint8)
    W, BI = get_skin(u8, mesh_tt, chans, stride, start, vc)
    tris = read_indices(mesh_tt).reshape(-1, 3)
    for part in parts:
        if W is None:
            part["tris"] = 0
            continue
        bis = bone_membership(nb, part["bone_ids"])
        vmask = part_vertex_mask(W, BI, bis, 0.5)
        part["tris"] = int(len(part_triangles(tris, vmask, "all")))


# A minimal shared SIFAS base-body rig. Used only as a fallback when no target
# bone list is supplied (e.g. `inspect` on a single bundle). Costume parts are
# bones *outside* this set. This does not need to be exhaustive — supplying the
# target's own bone list (which a transplant always does) is the precise check.
_BASE_RIG = {
    "Position", "Hips", "Spine", "Spine1", "Spine2", "Neck", "Head",
    "LeftShoulder", "RightShoulder", "LeftArm", "RightArm",
    "LeftForeArm", "RightForeArm", "LeftHand", "RightHand",
    "LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg", "LeftFoot", "RightFoot",
    "LeftToeBase", "RightToeBase", "Breast_L", "Breast_R", "Breast_Offset",
    "HipsSize", "Skirt", "Skirt_Offset",
}
# common costume-part name stems, used to label auto-detected groups
_PART_HINTS = ("wing", "tsubasa", "tail", "shippo", "cape", "manto", "ribbon",
               "feather", "horn", "tsuno", "ear", "mimi", "halo", "wear")


# ==========================================================================
# 4. object injection (recreate the part's bones — GameObject/Transform, plus
#    SwingBone physics when present — in the target bundle)
# ==========================================================================
def _serialized_file(env):
    bf = list(env.files.values())[0]
    sf = [v for v in bf.files.values() if type(v).__name__ == "SerializedFile"][0]
    return bf, sf


def _scriptname_map(objs):
    return {o.path_id: _safe_tt(o).get("m_ClassName")
            for o in objs if o.type.name == "MonoScript"}


def _rand_pids(n, used):
    import random
    out = []
    while len(out) < n:
        p = random.randint(10 ** 17, 9 * 10 ** 17)
        if p not in used and p not in out:
            out.append(p)
    return out


def _make_object(sf, template, new_pid, tree):
    """Append a brand-new object to a SerializedFile, reusing template's type info."""
    from UnityPy.files.ObjectReader import ObjectReader
    o = ObjectReader(
        assets_file=sf, reader=template.reader, path_id=new_pid,
        type_id=template.type_id, serialized_type=template.serialized_type,
        class_id=template.class_id, type=template.type,
        byte_start=template.byte_start, byte_size=template.byte_size,
        is_destroyed=getattr(template, "is_destroyed", 0),
        is_stripped=getattr(template, "is_stripped", 0),
    )
    sf.objects[new_pid] = o
    o.save_typetree(tree)
    return o


def _template(objs, cls, scriptnames=None, script_class=None):
    for o in objs:
        if o.type.name != cls:
            continue
        if script_class is None:
            return o
        if scriptnames.get(_safe_tt(o).get("m_Script", {}).get("m_PathID")) == script_class:
            return o
    return None


def _find_swingbone_manager(objs, scriptnames):
    for o in objs:
        if o.type.name == "MonoBehaviour" and \
                scriptnames.get(_safe_tt(o).get("m_Script", {}).get("m_PathID")) == "SwingBoneManager":
            return o
    return None


def _manager_colliders(objs, id2, scriptnames):
    mgr = _find_swingbone_manager(objs, scriptnames)
    out = []
    if not mgr:
        return out
    for c in _safe_tt(mgr).get("colliders", []):
        pid = c.get("m_PathID")
        co = id2.get(pid)
        bone = _go_name(id2, _safe_tt(co).get("m_GameObject", {}).get("m_PathID")) if co else None
        out.append((pid, bone))
    return out


def _swingbone_script_pid(objs, scriptnames):
    for pid, n in scriptnames.items():
        if n == "SwingBone":
            return pid
    return None


def _path_of_bone(id2, name2tf, name):
    """Slash path from a root to `name`, for the CRC32 m_BoneNameHashes entry."""
    parents = _transform_parent_byname(id2)
    chain, cur, seen = [], name, 0
    while cur is not None and seen < 1000:
        chain.append(cur)
        cur = parents.get(cur)
        seen += 1
    return "/".join(reversed(chain))


def _bone_name_hash(path):
    return zlib.crc32(path.encode("utf-8")) & 0xFFFFFFFF


def inject_bone_chain(donor, target, inject_names, name2tf_target,
                      preserve_physics=True, restore_collision=True, log=lambda *a: None):
    """Recreate donor bone chains (GameObject + Transform, plus SwingBone when the
    donor bone has one and the target has SwingBone infrastructure) inside the
    target. Returns ({donor_bone_name: new_target_transform_path_id}, child_adds).

    A degraded variant of costume_transplant.inject_appendage_bones: physics is
    optional, so a static part (no SwingBone) still transplants."""
    do, did = _index(donor)
    to, tid = _index(target)
    _, t_sf = _serialized_file(target)

    d_scripts = _scriptname_map(do)
    t_scripts = _scriptname_map(to)

    d_cols = _manager_colliders(do, did, d_scripts)
    t_cols = _manager_colliders(to, tid, t_scripts)
    d_colpid_to_bone = {pid: bone for pid, bone in d_cols}
    t_bone_to_colpid = {bone: pid for pid, bone in t_cols if bone}
    t_bone_to_colidx = {bone: i for i, (pid, bone) in enumerate(t_cols) if bone}

    d_go_by_name, d_tf_by_go, d_tfpid_to_goname = {}, {}, {}
    for o in do:
        if o.type.name == "GameObject":
            d_go_by_name[o.read().m_Name] = o
    for o in do:
        if o.type.name == "Transform":
            t = _safe_tt(o)
            gp = t.get("m_GameObject", {}).get("m_PathID")
            d_tf_by_go[gp] = o
            d_tfpid_to_goname[o.path_id] = _go_name(did, gp)
    d_swing_by_goname = {}
    for o in do:
        if o.type.name == "MonoBehaviour" and \
                d_scripts.get(_safe_tt(o).get("m_Script", {}).get("m_PathID")) == "SwingBone":
            t = _safe_tt(o)
            gn = _go_name(did, t.get("m_GameObject", {}).get("m_PathID"))
            if gn:
                d_swing_by_goname[gn] = t

    t_sb_script = _swingbone_script_pid(to, t_scripts)
    t_mgr = _find_swingbone_manager(to, t_scripts)
    go_tmpl = _template(to, "GameObject")
    tf_tmpl = _template(to, "Transform")
    mb_tmpl = _template(to, "MonoBehaviour", t_scripts, "SwingBone")
    have_phys = bool(t_mgr and mb_tmpl and t_sb_script)
    if not (go_tmpl and tf_tmpl):
        raise RuntimeError("target lacks GameObject/Transform templates; cannot inject bones")
    want_phys = preserve_physics and have_phys

    used = set(t_sf.objects.keys())
    inject_names = [n for n in inject_names if n in d_go_by_name]
    go_pid = dict(zip(inject_names, _rand_pids(len(inject_names), used)))
    used |= set(go_pid.values())
    tf_pid = dict(zip(inject_names, _rand_pids(len(inject_names), used)))
    used |= set(tf_pid.values())
    swing_owners = [n for n in inject_names if n in d_swing_by_goname] if want_phys else []
    mb_pid = dict(zip(swing_owners, _rand_pids(len(swing_owners), used)))
    used |= set(mb_pid.values())

    def tf_of(name):
        if name in tf_pid:
            return tf_pid[name]
        return name2tf_target.get(name)

    d_parent = _transform_parent_byname(did)
    new_swing_pids = []

    for name in inject_names:
        d_go = d_go_by_name[name]
        d_tf = d_tf_by_go[d_go.path_id]
        d_go_tt = _safe_tt(d_go)
        d_tf_tt = _safe_tt(d_tf)

        go_tt = copy.deepcopy(d_go_tt)
        comps = [{"component": {"m_FileID": 0, "m_PathID": tf_pid[name]}}]
        if name in mb_pid:
            comps.append({"component": {"m_FileID": 0, "m_PathID": mb_pid[name]}})
        go_tt["m_Component"] = comps
        _make_object(t_sf, go_tmpl, go_pid[name], go_tt)

        tf_tt = copy.deepcopy(d_tf_tt)
        tf_tt["m_GameObject"] = {"m_FileID": 0, "m_PathID": go_pid[name]}
        father_name = d_parent.get(name)
        tf_tt["m_Father"] = {"m_FileID": 0, "m_PathID": tf_of(father_name) or 0}
        children, seen_ch = [], set()
        for c in d_tf_tt.get("m_Children", []):
            cn = d_tfpid_to_goname.get(c["m_PathID"])
            cp = tf_pid.get(cn)
            if cp and cp not in seen_ch:
                children.append({"m_FileID": 0, "m_PathID": cp})
                seen_ch.add(cp)
        tf_tt["m_Children"] = children
        _make_object(t_sf, tf_tmpl, tf_pid[name], tf_tt)

    if swing_owners:
        d_mgr = _find_swingbone_manager(do, d_scripts)
        d_mgr_tt = _safe_tt(d_mgr) if d_mgr else {"bones": []}
        donor_idx_name = []
        for b in d_mgr_tt.get("bones", []):
            co = did.get(b["m_PathID"])
            donor_idx_name.append(_go_name(did, _safe_tt(co).get("m_GameObject", {}).get("m_PathID")) if co else None)
        t_existing_bones = _safe_tt(t_mgr).get("bones", [])
        base = len(t_existing_bones)
        target_name_idx = {}
        for i, b in enumerate(t_existing_bones):
            co = tid.get(b["m_PathID"])
            nm = _go_name(tid, _safe_tt(co).get("m_GameObject", {}).get("m_PathID")) if co else None
            if nm:
                target_name_idx[nm] = i
        inj_owner_newidx = {nm: base + k for k, nm in enumerate(swing_owners)}

        def remap_idx(idx):
            if idx is None or idx < 0 or idx >= len(donor_idx_name):
                return -1
            nm = donor_idx_name[idx]
            if nm in inj_owner_newidx:
                return inj_owner_newidx[nm]
            return target_name_idx.get(nm, -1)

        base_sb_tt = mb_tmpl.read_typetree()
        _skip = ("m_GameObject", "m_Script", "m_Name", "m_Enabled")
        for name in swing_owners:
            donor_sb = d_swing_by_goname[name]
            sb = copy.deepcopy(base_sb_tt)
            for k in sb:
                if k in donor_sb and k not in _skip:
                    sb[k] = copy.deepcopy(donor_sb[k])
            sb["m_GameObject"] = {"m_FileID": 0, "m_PathID": go_pid[name]}
            sb["m_Script"] = {"m_FileID": 0, "m_PathID": t_sb_script}
            child_goname = d_tfpid_to_goname.get(sb.get("child", {}).get("m_PathID"))
            sb["child"] = {"m_FileID": 0, "m_PathID": tf_of(child_goname) or 0}
            sib_goname = d_tfpid_to_goname.get(sb.get("sibling", {}).get("m_PathID"))
            sb["sibling"] = {"m_FileID": 0, "m_PathID": tf_of(sib_goname) or 0}
            for key in ("parentIndex", "childIndex", "siblingIndex"):
                if key in sb:
                    sb[key] = remap_idx(sb[key])
            new_cols, new_ids = [], []
            if restore_collision:
                for c in donor_sb.get("colliders", []):
                    bone = d_colpid_to_bone.get(c.get("m_PathID"))
                    if bone in t_bone_to_colpid:
                        new_cols.append({"m_FileID": 0, "m_PathID": t_bone_to_colpid[bone]})
                        new_ids.append(t_bone_to_colidx[bone] + 1)
            if "colliders" in sb:
                sb["colliders"] = new_cols
            if "colliderIds" in sb:
                sb["colliderIds"] = new_ids
            _make_object(t_sf, mb_tmpl, mb_pid[name], sb)
            new_swing_pids.append(mb_pid[name])

        if new_swing_pids:
            mtt = t_mgr.read_typetree()
            mtt.setdefault("bones", []).extend(
                {"m_FileID": 0, "m_PathID": p} for p in new_swing_pids)
            t_mgr.save_typetree(mtt)

    child_adds = {}
    for name in inject_names:
        father_name = d_parent.get(name)
        if father_name in tf_pid:
            continue
        if name2tf_target.get(father_name) is None:
            continue
        child_adds.setdefault(father_name, []).append(tf_pid[name])

    log(f"[ok] injected {len(inject_names)} bone(s)"
        + (f" with {len(new_swing_pids)} swing component(s)" if new_swing_pids else " (no physics)")
        + f": {', '.join(inject_names)}")
    return {n: tf_pid[n] for n in inject_names}, child_adds


def wire_child_adds(target_id2, child_adds, log=lambda *a: None):
    """Append injected appendage roots to their parent bone's m_Children."""
    if not child_adds:
        return
    t_tf = {}
    for pid, o in target_id2.items():
        if o.type.name == "Transform":
            n = _go_name(target_id2, _safe_tt(o).get("m_GameObject", {}).get("m_PathID"))
            if n is not None and n not in t_tf:
                t_tf[n] = o
    for name, cpids in child_adds.items():
        o = t_tf.get(name)
        if o is None:
            continue
        tt = o.read_typetree()
        existing = {c["m_PathID"] for c in tt.get("m_Children", [])}
        for cpid in cpids:
            if cpid not in existing:
                tt.setdefault("m_Children", []).append({"m_FileID": 0, "m_PathID": cpid})
                existing.add(cpid)
        o.save_typetree(tt)


# ==========================================================================
# 5. material / texture transplant (for the "own sub-mesh" path)
# ==========================================================================
_TEX_META = ("m_Width", "m_Height", "m_TextureFormat", "m_CompleteImageSize",
             "m_MipCount", "m_MipMap", "m_TextureSettings", "m_ColorSpace",
             "m_TextureDimension", "m_LightmapFormat", "m_IsReadable",
             "m_ImageCount", "m_ForcedFallbackFormat")


def copy_material_with_textures(donor, target, donor_mat_pid, log=lambda *a: None):
    """Deep-copy a donor Material (and every texture it references) into the target
    bundle as brand-new objects. Returns the new material path id, or None."""
    do, did = _index(donor)
    to, tid = _index(target)
    _, t_sf = _serialized_file(target)
    d_mat = did.get(donor_mat_pid)
    if not d_mat:
        return None
    mat_tmpl = _template(to, "Material")
    tex_tmpl = _template(to, "Texture2D")
    if not (mat_tmpl and tex_tmpl):
        log("[warn] target has no Material/Texture2D template; cannot copy part material")
        return None
    used = set(t_sf.objects.keys())

    def inject_tex(d_tex_pid):
        d_obj = did.get(d_tex_pid)
        if not d_obj:
            return 0
        dtt = copy.deepcopy(d_obj.read_typetree())
        try:
            dtt["image data"] = d_obj.read().get_image_data()
        except Exception:
            pass
        dtt["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        npid = _rand_pids(1, used)[0]
        used.add(npid)
        _make_object(t_sf, tex_tmpl, npid, dtt)
        return npid

    mtt = copy.deepcopy(d_mat.read_typetree())
    sp = mtt.get("m_SavedProperties", {})
    for entry in sp.get("m_TexEnvs", []):
        env = entry[1] if isinstance(entry, (list, tuple)) else entry.get("second")
        tex = env.get("m_Texture") if isinstance(env, dict) else None
        if tex and tex.get("m_PathID"):
            new_pid = inject_tex(tex["m_PathID"])
            if new_pid:
                tex["m_PathID"] = new_pid
                tex["m_FileID"] = 0
    new_mat_pid = _rand_pids(1, used)[0]
    used.add(new_mat_pid)
    _make_object(t_sf, mat_tmpl, new_mat_pid, mtt)
    log(f"[ok] copied part material + textures (new material pid {new_mat_pid})")
    return new_mat_pid


# ==========================================================================
# 6. world-space normalize + NodeScaling rebase (post-passes, ported from
#    costume_transplant.py so the grafted part renders where it was modelled)
# ==========================================================================
def _qmat(q):
    return _quat_mat(q)


def _trsmat(t, q, s):
    return _trs(t, q, s)


def _bp_mat(b):
    return mat_from(b)


def _mat_bp(M, dst):
    mat_to(M, dst)


def worldspace_normalize(path, verbose=True, body_only=True):
    """Bake the body renderer's mesh-root transform into its vertices and fold the
    inverse into the bind poses (mesh root -> identity). Body-only by default so
    only the (now grafted) body mesh is touched."""
    def log(*a):
        if verbose:
            print(*a)
    env = _require_unitypy().load(path)
    uid = {o.path_id: o for o in env.objects}
    body_pid = None
    if body_only:
        best = -1
        for o in env.objects:
            if o.type.name == "SkinnedMeshRenderer":
                nb = len(_safe_tt(o).get("m_Bones", []))
                if nb > best:
                    best, body_pid = nb, o.path_id
    tf = {}
    for o in env.objects:
        if o.type.name == "Transform":
            t = _safe_tt(o); g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
            n = g.read().m_Name if g else None
            lp, lr, ls = t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"]
            tf[o.path_id] = (n, ([lp['x'], lp['y'], lp['z']], [lr['x'], lr['y'], lr['z'], lr['w']],
                                 [ls['x'], ls['y'], ls['z']]), t.get('m_Father', {}).get('m_PathID'),
                            [c['m_PathID'] for c in t.get('m_Children', [])])
    world = {}

    def cw(pid, P):
        n, (lp, lr, ls), fa, ch = tf[pid]; M = P @ _trsmat(lp, lr, ls); world[n] = M
        for c in ch:
            if c in tf:
                cw(c, M)
    for pid, (n, _, fa, ch) in tf.items():
        if fa not in tf:
            cw(pid, np.eye(4))

    n_fixed = 0
    for o in env.objects:
        if o.type.name != "SkinnedMeshRenderer":
            continue
        if body_only and o.path_id != body_pid:
            continue
        smr = _safe_tt(o)
        if not smr.get("m_Bones"):
            continue
        mobj = uid.get(smr["m_Mesh"]["m_PathID"])
        if not mobj:
            continue
        tree = mobj.read_typetree()

        def bname(pid):
            x = uid.get(pid)
            if not x:
                return None
            g = uid.get(_safe_tt(x).get("m_GameObject", {}).get("m_PathID"))
            return g.read().m_Name if g else None
        bnames = [bname(b["m_PathID"]) for b in smr["m_Bones"]]
        BP = tree.get("m_BindPose")
        if not BP or len(BP) != len(bnames):
            continue
        cand = [world[bnames[i]] @ _bp_mat(BP[i]) for i in range(len(bnames))
                if bnames[i] in world][:4]
        if not cand:
            continue
        mr = cand[0]
        if max(np.abs(c - mr).max() for c in cand) > 1e-3 or np.abs(mr - np.eye(4)).max() < 1e-5:
            continue
        R, inv = mr[:3, :3], np.linalg.inv(mr)
        vc, chans, stride, start, _ = stream_layout(tree)
        buf = bytearray(tree["m_VertexData"]["m_DataSize"]); u8 = np.frombuffer(buf, np.uint8)
        pos = read_attr(u8, ATTR_POS, chans, stride, start, vc)
        if pos is None:
            continue
        write_attr(u8, (np.c_[pos, np.ones(len(pos))] @ mr.T)[:, :3], ATTR_POS, chans, stride, start, vc)
        if np.abs(R - np.eye(3)).max() > 1e-6:
            for attr in (ATTR_NORMAL, ATTR_TANGENT):
                a = read_attr(u8, attr, chans, stride, start, vc)
                if a is not None:
                    a2 = a.copy(); a2[:, :3] = a[:, :3] @ R.T
                    write_attr(u8, a2, attr, chans, stride, start, vc)
        tree["m_VertexData"]["m_DataSize"] = bytes(buf)
        for i in range(len(BP)):
            _mat_bp(_bp_mat(BP[i]) @ inv, BP[i])
        ab = tree.get("m_LocalAABB")
        if ab:
            c = ab["m_Center"]; nc = (mr @ np.array([c['x'], c['y'], c['z'], 1.0]))[:3]
            c['x'], c['y'], c['z'] = float(nc[0]), float(nc[1]), float(nc[2])
        mobj.save_typetree(tree)
        n_fixed += 1
        log(f"[ok] world-spaced mesh {tree.get('m_Name')!r} (mesh root {np.round(mr[:3,3],3)})")
    if n_fixed:
        bf = list(env.files.values())[0]; bf.mark_changed()
        with open(path, "wb") as f:
            f.write(bf.save(packer="lz4"))


def _is_node_scaling(mb):
    return "targetName" in mb and "scaleValues" in mb and "positionValues" in mb


def rebase_node_scaling(path, eps=1e-4, verbose=True):
    """Re-anchor every LiveCoreMemberNodeScaling entry whose originValue drifted
    from its bone, preserving the body-shape correction. (Ported verbatim from
    costume_transplant.py.)"""
    def log(*a):
        if verbose:
            print(*a)
    env = _require_unitypy().load(path)
    uid = {o.path_id: o for o in env.objects}

    def bone(pid):
        x = uid.get(pid)
        if not x:
            return None
        t = _safe_tt(x)
        g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
        return (g.read().m_Name if g else None, t)
    name2local = {}
    for o in env.objects:
        if o.type.name == "Transform":
            t = _safe_tt(o)
            g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
            n = g.read().m_Name if g else None
            if n:
                name2local[n] = t
    changed = 0
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        mb = _safe_tt(o)
        if not mb or not _is_node_scaling(mb):
            continue
        dirty = False
        for arr_key, comp_keys in (("positionValues", ("x", "y", "z")),
                                   ("scaleValues", ("x", "y", "z"))):
            for entry in mb.get(arr_key, []):
                nm = entry.get("targetName") or mb.get("targetName")
                tt = name2local.get(nm)
                if not tt:
                    continue
                loc = tt["m_LocalPosition"] if arr_key == "positionValues" else tt["m_LocalScale"]
                origin = entry.get("originValue", {})
                scaled = entry.get("scaledValue", {})
                if not origin or not scaled:
                    continue
                drift = max(abs(loc[c] - origin.get(c, loc[c])) for c in comp_keys)
                if drift <= eps:
                    continue
                if arr_key == "positionValues":
                    for c in comp_keys:
                        delta = scaled.get(c, 0.0) - origin.get(c, 0.0)
                        origin[c] = float(loc[c])
                        scaled[c] = float(loc[c] + delta)
                else:
                    for c in comp_keys:
                        o_v = origin.get(c, 1.0) or 1.0
                        ratio = scaled.get(c, o_v) / o_v
                        origin[c] = float(loc[c])
                        scaled[c] = float(loc[c] * ratio)
                dirty = True
        if dirty:
            o.save_typetree(mb)
            changed += 1
    if changed:
        bf = list(env.files.values())[0]; bf.mark_changed()
        with open(path, "wb") as f:
            f.write(bf.save(packer="lz4"))
        log(f"[ok] re-anchored NodeScaling on {changed} component(s)")


# ==========================================================================
# 7. mesh-root delta (donor part space -> target mesh space)
# ==========================================================================
def _mesh_root_world(env, smr_tt):
    """World matrix of a skinned mesh's root (bone[i].world @ bindpose[i], which is
    constant across bones at rest). Identity if it can't be determined."""
    objs, id2 = _index(env)
    # world transforms by transform pid
    tf = {}
    for o in objs:
        if o.type.name == "Transform":
            t = _safe_tt(o)
            lp, lr, ls = t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"]
            tf[o.path_id] = (([lp['x'], lp['y'], lp['z']], [lr['x'], lr['y'], lr['z'], lr['w']],
                              [ls['x'], ls['y'], ls['z']]),
                             t.get('m_Father', {}).get('m_PathID'),
                             [c['m_PathID'] for c in t.get('m_Children', [])])
    world = {}

    def cw(pid, P):
        (lp, lr, ls), fa, ch = tf[pid]
        M = P @ _trs(lp, lr, ls)
        world[pid] = M
        for c in ch:
            if c in tf:
                cw(c, M)
    for pid, (_, fa, ch) in tf.items():
        if fa not in tf:
            cw(pid, np.eye(4))
    mesh = id2.get(smr_tt["m_Mesh"]["m_PathID"])
    mesh_tt = _safe_tt(mesh)
    BP = mesh_tt.get("m_BindPose") or []
    bones = smr_tt.get("m_Bones", [])
    for i, b in enumerate(bones[:8]):
        if i >= len(BP):
            break
        wpid = b["m_PathID"]
        if wpid in world:
            return world[wpid] @ mat_from(BP[i])
    return np.eye(4)


# ==========================================================================
# 8. inspect
# ==========================================================================
def inspect(bundle_path, verbose=True):
    """List a bundle's skinned renderers, sub-meshes and candidate parts."""
    def log(*a):
        if verbose:
            print(*a)
    env = _require_unitypy().load(bundle_path)
    objs, id2 = _index(env)
    log(f"=== {os.path.basename(bundle_path)} ===")
    smrs = [o for o in objs if o.type.name == "SkinnedMeshRenderer"]
    log(f"skinned renderers: {len(smrs)}")
    for o in smrs:
        tt = _safe_tt(o)
        mesh = id2.get(tt["m_Mesh"]["m_PathID"])
        mtt = _safe_tt(mesh) if mesh else None
        nm = mtt.get("m_Name", "?") if mtt else "?"
        nb = len(tt.get("m_Bones", []))
        vc = mtt["m_VertexData"]["m_VertexCount"] if mtt else 0
        subs = mtt.get("m_SubMeshes", []) if mtt else []
        mats = tt.get("m_Materials", [])
        log(f"  - mesh {nm!r}: {vc} verts, {nb} bones, {len(subs)} sub-mesh(es), "
            f"{len(mats)} material(s)")
    parts, _meta = detect_parts(objs, id2, target_bone_names=None)
    log(f"\ncandidate parts (costume-specific bone groups): {len(parts)}")
    if not parts:
        log("  (none detected — every body bone is in the base rig; supply a "
            "target with --target so its exact rig is used as the baseline)")
    for p in parts:
        hint = next((h for h in _PART_HINTS if h in p["root"].lower()), None)
        tag = f"  [{hint}?]" if hint else ""
        log(f"  • {p['root']!r}: {p['verts']} verts, {p['tris']} tris, "
            f"{len(p['bones'])} bone(s){tag}")
        log(f"      bones: {', '.join(p['bones'][:12])}"
            + (" …" if len(p['bones']) > 12 else ""))
    return parts


# ==========================================================================
# 9. transplant a part
# ==========================================================================
def transplant_part(donor_path, target_path, out_path, part_root=None,
                    part_bones=None, auto=False, weight_threshold=0.5,
                    tri_mode="all", preserve_physics=True, restore_collision=True,
                    new_submesh="auto", patch_texture=False, worldspace=True,
                    fix_nodescaling=True, dry_run=False, verbose=True):
    """Move one costume part (the bones under `part_root`, or an explicit
    `part_bones` list, or the biggest auto-detected group) from donor to target."""
    def log(*a):
        if verbose:
            print(*a)
    UP = _require_unitypy()
    donor = UP.load(donor_path)
    target = UP.load(target_path)
    do, did = _index(donor)
    to, tid = _index(target)

    d_smr = _body_smr(do)
    t_smr = _body_smr(to)
    if d_smr is None or t_smr is None:
        raise RuntimeError("donor or target has no skinned body renderer")
    d_smr_tt = _safe_tt(d_smr)
    t_smr_tt = _safe_tt(t_smr)
    d_mesh = did.get(d_smr_tt["m_Mesh"]["m_PathID"])
    t_mesh = tid.get(t_smr_tt["m_Mesh"]["m_PathID"])
    d_mesh_tt = _safe_tt(d_mesh)
    t_mesh_tt = _safe_tt(t_mesh)

    d_names = _smr_bone_names(did, d_smr_tt)
    t_names = _smr_bone_names(tid, t_smr_tt)
    d_parent = _bone_parent_array(did, d_smr_tt)

    # ---- decide which donor bones make up the part ----
    parts, _meta = detect_parts(do, did, target_bone_names=t_names)
    chosen = None
    if part_bones:
        want = set(part_bones)
        ids = [i for i, n in enumerate(d_names) if n in want]
        if not ids:
            raise RuntimeError(f"none of --part-bones found in donor: {sorted(want)}")
        chosen = {"root": d_names[ids[0]], "bone_ids": sorted(set(ids)),
                  "bones": [d_names[i] for i in sorted(set(ids))]}
    elif part_root:
        if part_root not in d_names:
            raise RuntimeError(f"--part-root {part_root!r} not in donor bone list")
        ridx = d_names.index(part_root)
        sub = sorted(_descendants(d_parent, ridx))
        chosen = {"root": part_root, "bone_ids": sub,
                  "bones": [d_names[i] for i in sub]}
    elif auto:
        if not parts:
            raise RuntimeError("auto-detect found no costume-specific part in the donor")
        chosen = parts[0]
        log(f"[auto] selected part {chosen['root']!r} "
            f"({chosen['verts']} verts, {len(chosen['bones'])} bones)")
    else:
        raise RuntimeError("specify the part: --part-root NAME, --part-bones a,b,c, or --auto")

    part_bone_ids = chosen["bone_ids"]
    log(f"[info] part {chosen['root']!r}: bones {', '.join(chosen['bones'])}")

    # ---- select vertices + triangles in the donor body mesh ----
    vc, chans, stride, start, _ = stream_layout(d_mesh_tt)
    du8 = np.frombuffer(bytes(d_mesh_tt["m_VertexData"]["m_DataSize"]), np.uint8)
    W, BI = get_skin(du8, d_mesh_tt, chans, stride, start, vc)
    if W is None:
        raise RuntimeError("donor body mesh has no skin weights")
    bis = bone_membership(len(d_names), part_bone_ids)
    vmask = part_vertex_mask(W, BI, bis, weight_threshold)
    tris = read_indices(d_mesh_tt).reshape(-1, 3)
    ptris = part_triangles(tris, vmask, tri_mode)
    used, local_tris = extract_subgeometry(ptris)
    if len(used) == 0:
        raise RuntimeError("no part vertices selected — try a lower --weight-threshold "
                           "or --tri-mode any, or check the part bones with `inspect`")
    log(f"[info] selected {len(used)} vertices, {len(ptris)} triangles")

    part_W = W[used]
    part_BI = BI[used]

    # ---- which donor bones the part vertices reference; remap to target ----
    ref_ids = referenced_bone_ids(part_W, part_BI)
    remap, injected_ids = build_bone_remap(d_names, t_names, ref_ids)
    inject_names = [d_names[i] for i in injected_ids]
    new_BI = remap_skin_indices(part_BI, remap, default_idx=0)

    # appended bind poses (one per injected bone), copied from the donor mesh and
    # moved into the target mesh's space by the mesh-root delta below
    d_bp = d_mesh_tt.get("m_BindPose", [])
    delta = _mesh_root_delta(donor, target, d_smr_tt, t_smr_tt)
    if np.abs(delta - np.eye(4)).max() > 1e-6:
        log(f"[info] donor/target mesh-root differ; remapping part into target space "
            f"(translation {np.round(delta[:3,3],3)})")
    inv_delta = np.linalg.inv(delta)
    appended_bp = []
    for di in injected_ids:
        if di < len(d_bp):
            appended_bp.append(mat_from(d_bp[di]) @ inv_delta)
        else:
            appended_bp.append(np.eye(4))

    # ---- decide sub-mesh / material handling ----
    part_submesh = _which_submesh(d_mesh_tt, ptris)
    d_mats = d_smr_tt.get("m_Materials", [])
    own_material = (part_submesh is not None and part_submesh < len(d_mats)
                    and len(d_mats) > 1)
    if new_submesh == "auto":
        use_new_submesh = bool(own_material)
    else:
        use_new_submesh = bool(new_submesh)
    log(f"[info] part lives in donor sub-mesh {part_submesh}; "
        f"{'own material -> new sub-mesh' if use_new_submesh else 'merging into body sub-mesh'}")

    if dry_run:
        log("\n[dry-run] no file written. Summary:")
        log(f"  part root        : {chosen['root']}")
        log(f"  bones to inject  : {len(inject_names)} ({', '.join(inject_names) or 'none — all shared'})")
        log(f"  vertices added   : {len(used)}")
        log(f"  triangles added  : {len(ptris)}")
        log(f"  new sub-mesh     : {use_new_submesh}")
        log(f"  preserve physics : {preserve_physics}")
        bbox = _uv_bbox(d_mesh_tt, used)
        if bbox is not None:
            log(f"  UV bounds (UV0)  : x[{bbox[0]:.3f},{bbox[2]:.3f}] y[{bbox[1]:.3f},{bbox[3]:.3f}]")
        return None

    # ---- inject the part's bones into the target ----
    name2tf = _name2transform(tid)
    child_adds = {}
    if inject_names:
        new_map, child_adds = inject_bone_chain(
            donor, target, inject_names, name2tf,
            preserve_physics=preserve_physics, restore_collision=restore_collision, log=log)
        name2tf.update(new_map)

    # ---- splice geometry into the target body mesh ----
    stats = splice_mesh(t_mesh_tt, d_mesh_tt, ptris, used, new_BI, part_W,
                        appended_bp, mesh_root_delta=delta, new_submesh=use_new_submesh)
    t_mesh.save_typetree(t_mesh_tt)
    log(f"[ok] spliced part: body mesh now {stats['new_vc']} verts "
        f"(+{stats['added_verts']}), +{stats['added_tris']} tris")

    # ---- extend the target SMR bone list + bind-pose-aligned hashes ----
    new_bone_pids = []
    for di in injected_ids:
        nm = d_names[di]
        pid = name2tf.get(nm)
        new_bone_pids.append({"m_FileID": 0, "m_PathID": pid or 0})
    t_smr_tt = t_smr.read_typetree()
    t_smr_tt["m_Bones"] = t_smr_tt.get("m_Bones", []) + new_bone_pids
    # m_BoneNameHashes must stay aligned with m_BindPose if the mesh uses them
    bnh = t_mesh_tt.get("m_BoneNameHashes")
    if isinstance(bnh, list) and bnh:
        name2tf_target = _name2transform(tid)
        for di in injected_ids:
            nm = d_names[di]
            path = _path_of_bone(tid, name2tf_target, nm)
            bnh.append(_bone_name_hash(path))
        t_mesh_tt["m_BoneNameHashes"] = bnh
        t_mesh.save_typetree(t_mesh_tt)

    # add the part material to the SMR if a new sub-mesh was created
    if use_new_submesh:
        new_mat = None
        if part_submesh is not None and part_submesh < len(d_mats):
            new_mat = copy_material_with_textures(donor, target, d_mats[part_submesh]["m_PathID"], log)
        mats = t_smr_tt.get("m_Materials", [])
        mats.append({"m_FileID": 0, "m_PathID": new_mat or (mats[-1]["m_PathID"] if mats else 0)})
        t_smr_tt["m_Materials"] = mats
    # refresh the renderer bounds
    if t_mesh_tt.get("m_LocalAABB"):
        t_smr_tt["m_AABB"] = copy.deepcopy(t_mesh_tt["m_LocalAABB"])
    t_smr.save_typetree(t_smr_tt)

    # ---- wire injected roots into their parent bone's children ----
    wire_child_adds(tid, child_adds, log)

    # ---- optional: patch the part's texture region onto the target atlas ----
    if patch_texture and not use_new_submesh:
        try:
            _patch_uv_region(donor, target, d_smr_tt, t_smr_tt, used, d_mesh_tt, log)
        except Exception as e:  # noqa: BLE001
            log(f"[warn] texture patch skipped: {e}")

    # ---- write ----
    bf, _ = _serialized_file(target)
    bf.mark_changed()
    with open(out_path, "wb") as f:
        f.write(bf.save(packer="lz4"))
    log(f"[ok] wrote {out_path}")

    if worldspace:
        worldspace_normalize(out_path, verbose=verbose, body_only=True)
    if fix_nodescaling:
        rebase_node_scaling(out_path, verbose=verbose)
    log(f"[done] {out_path}")
    return out_path


def _mesh_root_delta(donor, target, d_smr_tt, t_smr_tt):
    """inv(target mesh root) @ (donor mesh root): maps donor mesh-space coords to
    target mesh-space. Identity for the common case of a shared base rig."""
    try:
        Dmr = _mesh_root_world(donor, d_smr_tt)
        Tmr = _mesh_root_world(target, t_smr_tt)
        return np.linalg.inv(Tmr) @ Dmr
    except Exception:
        return np.eye(4)


def _which_submesh(mesh_tt, part_tris):
    """Which donor sub-mesh the part's triangles fall in (by index range), or None."""
    subs = mesh_tt.get("m_SubMeshes", [])
    if len(subs) <= 1 or len(part_tris) == 0:
        return 0 if subs else None
    idx_fmt = mesh_tt.get("m_IndexFormat", 0)
    isz = 2 if idx_fmt == 0 else 4
    flat = read_indices(mesh_tt)
    # scan each sub-mesh's index range and pick the one holding the most part indices
    counts = {}
    for si, sm in enumerate(subs):
        first = sm.get("firstByte", 0) // isz
        cnt = sm.get("indexCount", 0)
        seg = flat[first:first + cnt]
        counts[si] = int(np.isin(seg, part_tris.reshape(-1)).sum())
    return max(counts, key=counts.get) if counts else 0


def _uv_bbox(mesh_tt, used, attr=ATTR_UV0):
    vc, chans, stride, start, _ = stream_layout(mesh_tt)
    u8 = np.frombuffer(bytes(mesh_tt["m_VertexData"]["m_DataSize"]), np.uint8)
    uv = read_attr(u8, attr, chans, stride, start, vc)
    if uv is None or len(used) == 0:
        return None
    sub = uv[used]
    return (float(sub[:, 0].min()), float(sub[:, 1].min()),
            float(sub[:, 0].max()), float(sub[:, 1].max()))


def _patch_uv_region(donor, target, d_smr_tt, t_smr_tt, used, d_mesh_tt, log):
    """Copy the part's UV-region pixels from the donor body atlas onto the target
    body atlas, so a merged (shared-atlas) part keeps its look. Best-effort."""
    PIL = _require_pil(hard=False)
    if PIL is None:
        log("[warn] Pillow not available; cannot patch texture region")
        return
    do, did = _index(donor)
    to, tid = _index(target)
    d_tex = _main_texture(did, d_smr_tt)
    t_tex = _main_texture(tid, t_smr_tt)
    if not (d_tex and t_tex):
        log("[warn] could not locate body _MainTex on donor/target")
        return
    bbox = _uv_bbox(d_mesh_tt, used)
    if bbox is None:
        return
    d_img = did.get(d_tex).read().image.convert("RGBA")
    t_img = tid.get(t_tex).read().image.convert("RGBA")
    dw, dh = d_img.size
    tw, th = t_img.size
    # UV (0,0) is bottom-left; image origin top-left
    x0 = max(0, int(bbox[0] * dw) - 2); x1 = min(dw, int(bbox[2] * dw) + 2)
    y0 = max(0, int((1 - bbox[3]) * dh) - 2); y1 = min(dh, int((1 - bbox[1]) * dh) + 2)
    if x1 <= x0 or y1 <= y0:
        return
    patch = d_img.crop((x0, y0, x1, y1))
    # paste at the same UV region on the target atlas (scaled to its size)
    tx0 = int(bbox[0] * tw); tx1 = int(bbox[2] * tw)
    ty0 = int((1 - bbox[3]) * th); ty1 = int((1 - bbox[1]) * th)
    if tx1 > tx0 and ty1 > ty0:
        patch = patch.resize((tx1 - tx0, ty1 - ty0))
        t_img.alpha_composite(patch, (tx0, ty0))
        t_obj = tid.get(t_tex)
        t_obj_data = t_obj.read()
        t_obj_data.image = t_img
        t_obj_data.save()
        log(f"[ok] patched part UV region onto target body atlas ({tx1-tx0}x{ty1-ty0}px)")


def _main_texture(id2, smr_tt):
    mats = smr_tt.get("m_Materials", [])
    if not mats:
        return None
    mat = id2.get(mats[0]["m_PathID"])
    if not mat:
        return None
    sp = _safe_tt(mat).get("m_SavedProperties", {})
    for entry in sp.get("m_TexEnvs", []):
        name = entry[0] if isinstance(entry, (list, tuple)) else entry.get("first")
        env = entry[1] if isinstance(entry, (list, tuple)) else entry.get("second")
        if name == "_MainTex" and isinstance(env, dict):
            pid = env.get("m_Texture", {}).get("m_PathID", 0)
            if pid:
                return pid
    return None


def validate(out_path, verbose=True):
    """Quick dangling-reference check on the written bundle."""
    env = _require_unitypy().load(out_path)
    objs, id2 = _index(env)
    dangling = 0
    for o in objs:
        if o.type.name != "SkinnedMeshRenderer":
            continue
        tt = _safe_tt(o)
        for b in tt.get("m_Bones", []):
            if b.get("m_PathID") and b["m_PathID"] not in id2:
                dangling += 1
        if tt.get("m_Mesh", {}).get("m_PathID") not in id2:
            dangling += 1
    if verbose:
        print(f"[validate] {'ok — no dangling references' if not dangling else f'{dangling} dangling reference(s)!'}")
    return dangling == 0


# ==========================================================================
# 10. self-test (pure mesh-surgery maths; no bundle / UnityPy needed)
# ==========================================================================
def _build_synth_mesh(vc, bones, tris, weights, bone_index):
    """Build a minimal Unity-like Mesh typetree: position(float3 @ stream0) +
    blendweight(float4) + blendindices(int4) in stream0, index buffer + one
    sub-mesh. Positions are vertex id encoded as (id, id*2, id*3)."""
    chans = [{"stream": 0, "offset": 0, "format": 0, "dimension": 3}]   # 0 pos
    chans += [{"stream": 0, "offset": 0, "format": 0, "dimension": 0}] * (ATTR_BLENDWEIGHT - 1)
    chans.append({"stream": 0, "offset": 12, "format": 0, "dimension": 4})  # 12 weight
    chans.append({"stream": 0, "offset": 28, "format": 11, "dimension": 4})  # 13 indices
    tree = {
        "m_Name": "synth",
        "m_VertexData": {"m_VertexCount": vc, "m_Channels": chans, "m_DataSize": b""},
        "m_IndexFormat": 0,
        "m_IndexBuffer": np.asarray(tris, "<u2").reshape(-1).tobytes(),
        "m_SubMeshes": [{"firstByte": 0, "indexCount": int(np.asarray(tris).size),
                         "firstVertex": 0, "vertexCount": vc, "baseVertex": 0,
                         "topology": 0, "localAABB": {"m_Center": {}, "m_Extent": {}}}],
        "m_BindPose": [_mat_dict(np.eye(4)) for _ in range(bones)],
        "m_LocalAABB": {"m_Center": {}, "m_Extent": {}},
    }
    _, ch, stride, start, total = stream_layout(tree)
    buf = bytearray(total); u8 = np.frombuffer(buf, np.uint8)
    pos = np.array([[i, i * 2, i * 3] for i in range(vc)], float)
    write_attr(u8, pos, ATTR_POS, ch, stride, start, vc)
    write_attr(u8, np.asarray(weights, float), ATTR_BLENDWEIGHT, ch, stride, start, vc)
    write_attr(u8, np.asarray(bone_index, float), ATTR_BLENDINDICES, ch, stride, start, vc)
    tree["m_VertexData"]["m_DataSize"] = bytes(buf)
    return tree


def selftest(verbose=True):
    def log(*a):
        if verbose:
            print(*a)
    fails = []

    def check(name, cond):
        log(f"  [{'ok ' if cond else 'FAIL'}] {name}")
        if not cond:
            fails.append(name)

    # donor: 4 body verts (bones 0,1) + 3 wing verts (bone 2). One wing triangle.
    dvc = 7
    dbones = 3
    d_w = [[1, 0, 0, 0]] * dvc
    d_bi = [[0, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0],
            [2, 0, 0, 0], [2, 0, 0, 0], [2, 0, 0, 0]]
    d_tris = [[0, 1, 2], [4, 5, 6]]          # body tri, wing tri
    donor = _build_synth_mesh(dvc, dbones, d_tris, d_w, d_bi)
    d_names = ["Hips", "Spine", "Wing_L"]

    # target: 5 body verts (bones Hips=0, Spine=1). No wing.
    tvc = 5
    t_w = [[1, 0, 0, 0]] * tvc
    t_bi = [[0, 0, 0, 0]] * tvc
    t_tris = [[0, 1, 2], [2, 3, 4]]
    target = _build_synth_mesh(tvc, 2, t_tris, t_w, t_bi)
    t_names = ["Hips", "Spine"]

    # --- part selection ---
    W = np.array(d_w, float); BI = np.array(d_bi, np.int64)
    part_ids = [2]
    bis = bone_membership(dbones, part_ids)
    vmask = part_vertex_mask(W, BI, bis, 0.5)
    check("wing vertices selected = 3", int(vmask.sum()) == 3)
    tris = read_indices(donor).reshape(-1, 3)
    ptris = part_triangles(tris, vmask, "all")
    check("wing triangles selected = 1", len(ptris) == 1)
    used, local = extract_subgeometry(ptris)
    check("unique wing verts = 3", len(used) == 3)
    check("local triangle renumbered to 0..2", set(local.ravel().tolist()) == {0, 1, 2})

    # --- bone remap ---
    ref = referenced_bone_ids(W[used], BI[used])
    check("referenced bone = [2]", ref == [2])
    remap, injected = build_bone_remap(d_names, t_names, ref)
    check("Wing_L injected at combined index 2", remap[2] == 2 and injected == [2])
    new_BI = remap_skin_indices(BI[used], remap)
    check("part skin indices remapped to 2", (new_BI[:, 0] == 2).all())

    # --- splice ---
    appended_bp = [np.eye(4)]
    stats = splice_mesh(target, donor, ptris, used, new_BI, W[used], appended_bp,
                        mesh_root_delta=np.eye(4), new_submesh=False)
    check("new vertex count = 8", stats["new_vc"] == tvc + len(used))
    # verify appended positions match donor wing positions
    vc2, ch2, st2, sa2, _ = stream_layout(target)
    u8 = np.frombuffer(bytes(target["m_VertexData"]["m_DataSize"]), np.uint8)
    pos2 = read_attr(u8, ATTR_POS, ch2, st2, sa2, vc2)
    donor_pos = np.array([[i, i * 2, i * 3] for i in used], float)
    check("appended positions match donor wing", np.allclose(pos2[tvc:tvc + len(used)], donor_pos))
    # verify appended skin indices
    W2, BI2 = get_skin(u8, target, ch2, st2, sa2, vc2)
    check("appended skin index = 2", (BI2[tvc:tvc + len(used), 0] == 2).all())
    # verify index buffer: last triangle references the new vertices
    new_tris = read_indices(target).reshape(-1, 3)
    check("wing triangle appended", len(new_tris) == len(t_tris) + 1)
    last = set(new_tris[-1].tolist())
    check("wing triangle references appended verts", last == {tvc, tvc + 1, tvc + 2})
    check("body sub-mesh vertexCount grew", target["m_SubMeshes"][-1]["vertexCount"] == tvc + len(used))
    check("bind pose appended", len(target["m_BindPose"]) == 3)

    # --- index-format upgrade path (force >65535 verts) ---
    big = _build_synth_mesh(3, 1, [[0, 1, 2]], [[1, 0, 0, 0]] * 3, [[0, 0, 0, 0]] * 3)
    big["m_VertexData"]["m_VertexCount"] = 65534    # +3 wing verts -> 65537 > 65535
    # rebuild buffer for the inflated count so layout is consistent
    _, bch, bst, bsa, btot = stream_layout(big)
    big["m_VertexData"]["m_DataSize"] = bytes(bytearray(btot))
    big["m_SubMeshes"][0]["vertexCount"] = 65534
    s2 = splice_mesh(big, donor, ptris, used, new_BI, W[used], [np.eye(4)],
                     mesh_root_delta=np.eye(4), new_submesh=False)
    check("index format upgraded to uint32 past 65535", s2["index_format"] == 1)

    log("")
    if fails:
        log(f"SELFTEST FAILED: {len(fails)} check(s): {', '.join(fails)}")
        return False
    log("SELFTEST PASSED — all mesh-surgery checks ok")
    return True


# ==========================================================================
# 11. CLI
# ==========================================================================
def build_parser():
    p = argparse.ArgumentParser(
        description="Move one costume part (wings/tail/…) from a donor SIFAS model "
                    "bundle onto a target, by mesh surgery on the body mesh.")
    sub = p.add_subparsers(dest="cmd")

    pi = sub.add_parser("inspect", help="list a bundle's renderers and candidate parts")
    pi.add_argument("--bundle", required=True)

    pt = sub.add_parser("transplant", help="transplant a part")
    pt.add_argument("--donor", required=True, help="bundle the part comes from")
    pt.add_argument("--target", required=True, help="bundle that keeps its identity")
    pt.add_argument("--out", required=True, help="output bundle")
    g = pt.add_mutually_exclusive_group()
    g.add_argument("--part-root", help="root bone of the part (takes it + all descendants)")
    g.add_argument("--part-bones", help="comma-separated explicit bone names")
    g.add_argument("--auto", action="store_true", help="pick the biggest costume-specific group")
    pt.add_argument("--weight-threshold", type=float, default=0.5,
                    help="min part-bone weight for a vertex to count (default 0.5)")
    pt.add_argument("--tri-mode", choices=("all", "any"), default="all",
                    help="'all' corners are part verts (clean) or 'any' (greedy)")
    pt.add_argument("--no-physics", action="store_true", help="don't copy SwingBone jiggle")
    pt.add_argument("--no-collision", action="store_true", help="don't restore body collision")
    pt.add_argument("--submesh", choices=("auto", "new", "merge"), default="auto",
                    help="add as its own sub-mesh+material, merge into body, or auto")
    pt.add_argument("--patch-texture", action="store_true",
                    help="copy the part's UV region onto the target body atlas (needs Pillow)")
    pt.add_argument("--no-worldspace", action="store_true")
    pt.add_argument("--no-nodescaling", action="store_true")
    pt.add_argument("--dry-run", action="store_true", help="report only; write nothing")

    sub.add_parser("selftest", help="run the pure mesh-surgery checks (no bundle needed)")
    p.add_argument("--gui", action="store_true", help="force the graphical interface")
    return p


def run_cli(args):
    if args.cmd == "inspect":
        inspect(args.bundle)
        return 0
    if args.cmd == "selftest":
        return 0 if selftest() else 1
    if args.cmd == "transplant":
        new_submesh = {"auto": "auto", "new": True, "merge": False}[args.submesh]
        out = transplant_part(
            args.donor, args.target, args.out,
            part_root=args.part_root,
            part_bones=[s.strip() for s in args.part_bones.split(",")] if args.part_bones else None,
            auto=args.auto,
            weight_threshold=args.weight_threshold, tri_mode=args.tri_mode,
            preserve_physics=not args.no_physics, restore_collision=not args.no_collision,
            new_submesh=new_submesh, patch_texture=args.patch_texture,
            worldspace=not args.no_worldspace, fix_nodescaling=not args.no_nodescaling,
            dry_run=args.dry_run)
        if out and not args.dry_run:
            validate(out)
        return 0
    return None


# ==========================================================================
# 12. GUI
# ==========================================================================
def gui_available():
    import importlib.util
    try:
        return importlib.util.find_spec("tkinter") is not None
    except Exception:
        return False


def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog
    import threading
    import queue

    root = tk.Tk()
    root.title(_tr("SIFAS Costume Part Transplant"))
    root.geometry("760x680")

    state = {"parts": []}
    q = queue.Queue()

    def browse(var):
        f = filedialog.askopenfilename(title=_tr("Select bundle"))
        if f:
            var.set(f)

    def browse_save(var):
        f = filedialog.asksaveasfilename(title=_tr("Save output bundle"))
        if f:
            var.set(f)

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    donor_v = tk.StringVar(); target_v = tk.StringVar(); out_v = tk.StringVar()

    def row(label, var, save=False):
        f = ttk.Frame(frm); f.pack(fill="x", pady=3)
        ttk.Label(f, text=_tr(label), width=24).pack(side="left")
        ttk.Entry(f, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(f, text=_tr("Browse…"),
                   command=(lambda: browse_save(var)) if save else (lambda: browse(var))).pack(side="left")

    row("Donor  (part source)", donor_v)
    row("Target (wearer / identity)", target_v)
    row("Output bundle", out_v, save=True)

    pf = ttk.Frame(frm); pf.pack(fill="x", pady=6)
    ttk.Label(pf, text=_tr("Part to move"), width=24).pack(side="left")
    part_v = tk.StringVar()
    part_cb = ttk.Combobox(pf, textvariable=part_v, state="readonly")
    part_cb.pack(side="left", fill="x", expand=True)

    def refresh_parts():
        try:
            parts = inspect(donor_v.get(), verbose=False) if donor_v.get() else []
        except Exception as e:  # noqa: BLE001
            parts = []
            log_write(f"[error] {e}\n")
        state["parts"] = parts
        labels = [f"{p['root']}  ({p['verts']} v, {p['tris']} t, {len(p['bones'])} bones)"
                  for p in parts]
        part_cb["values"] = labels or [_tr("(load a donor bundle to list its parts)")]
        if labels:
            part_cb.current(0)
    ttk.Button(pf, text=_tr("Refresh part list"), command=refresh_parts).pack(side="left")

    opt = ttk.LabelFrame(frm, text=_tr("Options"), padding=8)
    opt.pack(fill="x", pady=8)
    phys_v = tk.BooleanVar(value=True)
    coll_v = tk.BooleanVar(value=True)
    newsub_v = tk.BooleanVar(value=False)
    patch_v = tk.BooleanVar(value=False)
    ws_v = tk.BooleanVar(value=True)
    ns_v = tk.BooleanVar(value=True)
    dry_v = tk.BooleanVar(value=False)
    for var, label in (
        (phys_v, "Preserve the part's jiggle physics (SwingBone)"),
        (coll_v, "Restore body collision for the part's bones"),
        (newsub_v, "Add the part as its own sub-mesh + material (keep its texture)"),
        (patch_v, "Patch the part's texture region onto the target body atlas"),
        (ws_v, "World-space the body mesh (so swinging parts render correctly)"),
        (ns_v, "Re-anchor NodeScaling to keep the wearer's body shape"),
        (dry_v, "Preview only (dry-run) — report what would change, write nothing"),
    ):
        ttk.Checkbutton(opt, text=_tr(label), variable=var).pack(anchor="w")

    out_txt = tk.Text(frm, height=14, wrap="word")
    out_txt.pack(fill="both", expand=True, pady=6)

    def log_write(s):
        out_txt.insert("end", s); out_txt.see("end")

    def drain():
        try:
            while True:
                log_write(q.get_nowait())
        except queue.Empty:
            pass
        root.after(100, drain)

    def worker():
        idx = part_cb.current()
        parts = state["parts"]
        if not (donor_v.get() and target_v.get() and out_v.get() and parts and 0 <= idx < len(parts)):
            q.put(_tr("[error] choose donor, target, output and a part first.\n"))
            return

        class _W:
            def write(self, s):
                q.put(s)
            def flush(self):
                pass
        old = sys.stdout
        sys.stdout = _W()
        try:
            out = transplant_part(
                donor_v.get(), target_v.get(), out_v.get(),
                part_root=parts[idx]["root"],
                preserve_physics=phys_v.get(), restore_collision=coll_v.get(),
                new_submesh=(True if newsub_v.get() else "auto"),
                patch_texture=patch_v.get(),
                worldspace=ws_v.get(), fix_nodescaling=ns_v.get(),
                dry_run=dry_v.get())
            if out and not dry_v.get():
                ok = validate(out)
                q.put(_tr("\n[success] done — verified ✓\n") if ok
                      else _tr("\n[error] output has dangling references!\n"))
        except Exception as e:  # noqa: BLE001
            q.put(f"\n[error] {e}\n")
        finally:
            sys.stdout = old

    def go():
        out_txt.delete("1.0", "end")
        threading.Thread(target=worker, daemon=True).start()

    bf = ttk.Frame(frm); bf.pack(fill="x")
    ttk.Button(bf, text=_tr("Transplant part"), command=go).pack(side="right")

    drain()
    root.mainloop()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "cmd", None):
        rc = run_cli(args)
        if rc is not None:
            sys.exit(rc)
        return
    # no subcommand: GUI if available, else help
    if gui_available():
        run_gui()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
