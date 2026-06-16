#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS Mesh Baker — 스킨드 메시 포즈 베이킹 도구  (v3)
=====================================================
Blender의 "포즈 모드에서 본 변형 → Armature modifier Apply"와 똑같은 동작을
Unity 에셋번들에 직접 수행한다. 본에 변형(스케일/회전/이동)을 주면 스키닝
가중치대로 정점이 움직이고, 그 결과를 메시 정점 데이터에 영구히 굽는다(bake).

기능
----
- 모든 스킨드 메시 인식(이름 무관). foot_shadow_Plane / Hair / Face 는 기본 숨김.
- 본 계층 전파(Blender식): 부모 본 변형이 자식에도 전파(기본 ON).
- 자식 본 역보정: 부모만 키우고 그 아래는 원래 크기 유지(스케일 역수 자동).
- 허벅지 프리셋(Thigh Scale): 체형 slim/default/thick 간 전환 단축 버튼.

원리
----
  각 본 i 스키닝 행렬:  M_i = posedWorld_i · bindpose_i   (계층 전파 ON)
                  또는  M_i = inv(bindpose_i) · D_i · bindpose_i (전파 OFF)
  각 정점 v:  v' = ( Σ_k w_k · M_{b_k} ) · v
  노멀/탄젠트도 같은 블렌드 행렬로 변환 후 재정규화.

UI 언어는 영어. 실행 환경 자동 감지: 데스크톱 → Tkinter GUI / Termux·헤드리스 → 텍스트 메뉴(+CLI).
의존성: UnityPy, numpy. 검증: Unity 2018.4 비압축 메시(SIFAS 모델팩). 압축 메시 미지원.
"""

import os
import sys
import math
import argparse
import importlib
import subprocess
from pathlib import Path


# 기본 숨김 메시(이름 기준). 체크/--include-hidden 시 표시·처리.
DEFAULT_HIDDEN = {"foot_shadow_Plane", "Hair", "Face"}


# ==========================================================================
# 0. 의존성 자동 설치 (Termux 포함)
# ==========================================================================
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
    # prebuilt Termux package: try pkg, then apt, then refresh repos and retry.
    if _run(["pkg", "install", "-y", pkg]) or _run(["apt", "install", "-y", pkg]):
        return True
    _run(["apt", "update", "-y"])
    return _run(["pkg", "install", "-y", pkg]) or _run(["apt", "install", "-y", pkg])


# These have C extensions that pip can't reliably build on Termux, so install the
# prebuilt Termux package instead. Maps the import/pip name -> Termux package name.
_TERMUX_PKG = {"numpy": "python-numpy", "PIL": "python-pillow", "Pillow": "python-pillow"}


def _install_guidance_and_exit(import_name, pip_name):
    print(f"[setup] could not install '{pip_name}' automatically.")
    if is_termux():
        print("  On Termux, install the dependencies manually, then re-run:")
        print("    pkg install -y python-numpy python-pillow")
        print("    pip install UnityPy --break-system-packages")
    else:
        print(f"    pip install {pip_name}")
    sys.exit(1)


def ensure_module(import_name, pip_name=None):
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
    else:
        _pip_install(pip_name)
    try:
        return importlib.import_module(import_name)
    except ImportError:
        _install_guidance_and_exit(import_name, pip_name)


# UnityPy hard-imports PIL at import time; on Termux PIL must come from the
# prebuilt package (pip can't build Pillow there), so make sure it's present
# BEFORE importing UnityPy.
if is_termux():
    ensure_module("PIL", "Pillow")
UnityPy = ensure_module("UnityPy")
np = ensure_module("numpy")


# ==========================================================================
# 1. 수학 / 포즈
# ==========================================================================
def mat_from(d):
    """Unity Matrix4x4f(eRC = row R, col C) → numpy 4x4."""
    return np.array([
        [d["e00"], d["e01"], d["e02"], d["e03"]],
        [d["e10"], d["e11"], d["e12"], d["e13"]],
        [d["e20"], d["e21"], d["e22"], d["e23"]],
        [d["e30"], d["e31"], d["e32"], d["e33"]],
    ], dtype=np.float64)


def euler_zxy_matrix(x, y, z):
    """Unity Quaternion.Euler 순서(Z→X→Y) 회전행렬. 인자는 도(degree)."""
    rx, ry, rz = map(math.radians, (x, y, z))
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    M = np.eye(4)
    M[:3, :3] = Ry @ Rx @ Rz
    return M


def trs(translate=(0, 0, 0), rotate=(0, 0, 0), scale=(1, 1, 1)):
    """본 로컬 변형 델타 D = T · R · S."""
    T = np.eye(4); T[:3, 3] = translate
    R = euler_zxy_matrix(*rotate)
    S = np.eye(4); S[0, 0], S[1, 1], S[2, 2] = scale
    return T @ R @ S


class Target:
    """포즈 1개 = (본 이름, 이동, 회전(도), 스케일, 자식역보정, 보정대상본)."""
    __slots__ = ("bone", "translate", "rotate", "scale", "compensate", "comp_bones")

    def __init__(self, bone, translate=(0, 0, 0), rotate=(0, 0, 0),
                 scale=(1, 1, 1), compensate=False, comp_bones=None):
        self.bone = bone
        self.translate = tuple(map(float, translate))
        self.rotate = tuple(map(float, rotate))
        self.scale = tuple(map(float, scale))
        self.compensate = bool(compensate)
        # None = 자동(바로 아래 자식). 리스트 = 그 본들을 역보정(자손인 것만 적용).
        self.comp_bones = list(comp_bones) if comp_bones else None

    def delta(self):
        return trs(self.translate, self.rotate, self.scale)

    def is_identity(self):
        return (self.translate == (0, 0, 0) and self.rotate == (0, 0, 0)
                and self.scale == (1, 1, 1))

    def describe(self):
        c = "  +child-comp" if self.compensate else ""
        return (f"{self.bone}  scale={self.scale}  rot={self.rotate}  "
                f"move={self.translate}{c}")


# ==========================================================================
# 0.5 바디 프리셋 / 본 주석
# ==========================================================================
# [Thigh Scale] 게임 내 캐릭터 체형별 허벅지 스케일(LeftUpLeg/RightUpLeg, 기본=1).
#   slim  : Nico, Ruby, Rina, Lanzhu   = (1.0, 0.941748, 0.932695)
#   thick : Nozomi, Mari, Karin, Emma  = (1.0, 1.03884,  1.0577)
#   default(표준 체형)                  = (1.0, 1.0,      1.0)
# 상태 A→B 전환 배율 = B/A(성분별). X는 1.0 고정(다리 길이 유지), Y/Z가 굵기.
THIGH_STATES = {
    "slim":    (1.0, 0.941748, 0.932695),
    "default": (1.0, 1.0, 1.0),
    "thick":   (1.0, 1.03884, 1.0577),
}
THIGH_BONES = ("LeftUpLeg", "RightUpLeg")
THIGH_TRANSITIONS = [("slim", "default"), ("slim", "thick"),
                     ("default", "slim"), ("default", "thick"),
                     ("thick", "slim"), ("thick", "default")]


def thigh_factor(src, dst):
    """허벅지 상태 src→dst 전환 배율(성분별 B/A)."""
    return tuple(b / a for a, b in zip(THIGH_STATES[src], THIGH_STATES[dst]))


def thigh_targets(src, dst, compensate=True):
    """src→dst 허벅지 프리셋을 양쪽 UpLeg 타깃으로."""
    f = thigh_factor(src, dst)
    return [Target(b, scale=f, compensate=compensate) for b in THIGH_BONES]


def default_compensate(bone):
    """자식 역보정을 기본으로 켤 본(허벅지·허리 계열)."""
    return (bone in THIGH_BONES) or bone.startswith("Spine")


# [Spine 주석] Spine / Spine1 / Spine2 = 허리·몸통.
#   검증 결과 이 본들의 '로컬 X'가 키(세로) 방향이다. 즉 ScaleX 를 바꾸면 키가
#   변해서 머리·헤어와 높이가 어긋나 이상해진다. 허리 굵기를 바꾸고 싶다면
#   X 는 1.0 으로 두고 Y(좌우 폭)·Z(앞뒤 두께)만 조절하는 것을 권장한다.
SPINE_NOTE = ("Spine / Spine1 / Spine2 are the waist/torso. This bone's ScaleX is "
              "the HEIGHT (vertical) axis: changing X changes the character's height, "
              "so the head/hair stop lining up. To resize the waist, keep X=1.0 and "
              "adjust only Y (width) and Z (depth).")


def target_notes(targets):
    """주의가 필요한 본(현재 Spine 계열)에 대한 참고/주의 메시지."""
    out, seen = [], set()

    def add(m):
        if m not in seen:
            seen.add(m); out.append(m)

    for tg in targets:
        if tg.bone.startswith("Spine"):
            add(f"[note] {SPINE_NOTE}")
            if abs(tg.scale[0] - 1.0) > 1e-9:
                add(f"[warning] {tg.bone} ScaleX={tg.scale[0]} will change height. Keep X=1.0.")
    return out


# 스파인 보정 대상 선택지: 어떤 본을 역보정할지에 따라 굵어지는 범위가 달라진다.
#   spine2(기본) = Spine2 보정 → 굵어지는 범위가 Spine+Spine1 까지 넓다
#   spine1       = Spine1 보정 → Spine 만 굵어진다(좁다)
#   both         = Spine1+Spine2 둘 다 보정
#   auto         = 대상 본의 바로 아래 자식(기존 자동 동작)
SPINE_COMP_CHOICES = {
    "spine2": ["Spine2"],
    "spine1": ["Spine1"],
    "both": ["Spine1", "Spine2"],
    "auto": None,
}


def apply_spine_comp(targets, choice):
    """보정이 켜진 Spine 계열 타깃에 보정 대상 본(comp_bones)을 지정."""
    bones = SPINE_COMP_CHOICES.get((choice or "spine2").lower(), ["Spine2"])
    for tg in targets:
        if tg.bone.startswith("Spine") and tg.compensate:
            tg.comp_bones = list(bones) if bones else None
    return targets


# ==========================================================================
# 2. 정점 버퍼(비압축) 파싱 / 읽기 / 쓰기  — 벡터화
# ==========================================================================
FMT_BYTES = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1,
             8: 2, 9: 2, 10: 4, 11: 4}
ATTR_POS, ATTR_NORMAL, ATTR_TANGENT = 0, 1, 2
ATTR_BLENDWEIGHT, ATTR_BLENDINDICES = 12, 13


def _align16(x):
    return (x + 15) & ~15


def stream_layout(tree):
    vd = tree["m_VertexData"]
    vc = vd["m_VertexCount"]
    chans = vd["m_Channels"]
    by_stream = {}
    for ci, ch in enumerate(chans):
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


def _stream_view(buf_u8, s, stride, start, vc):
    return buf_u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])


def read_attr(buf_u8, attr, chans, stride, start, vc):
    ch = chans[attr]
    if ch.get("dimension", 0) == 0:
        return None
    s, off, dim, fmt = ch["stream"], ch["offset"], ch["dimension"], ch["format"]
    block = _stream_view(buf_u8, s, stride, start, vc)
    raw = block[:, off:off + dim * FMT_BYTES[fmt]]
    if fmt == 0:
        return raw.copy().view("<f4").reshape(vc, dim).astype(np.float64)
    if fmt == 11:
        return raw.copy().view("<i4").reshape(vc, dim).astype(np.int64)
    if fmt == 10:
        return raw.copy().view("<u4").reshape(vc, dim).astype(np.int64)
    if fmt == 2:
        return raw.astype(np.float64) / 255.0
    if fmt == 6:
        return raw.astype(np.int64)
    raise NotImplementedError(f"vertex format {fmt} not supported (read)")


def write_attr(buf_u8, arr, attr, chans, stride, start, vc):
    ch = chans[attr]
    s, off, dim, fmt = ch["stream"], ch["offset"], ch["dimension"], ch["format"]
    block = _stream_view(buf_u8, s, stride, start, vc)
    if fmt == 0:
        packed = np.ascontiguousarray(arr[:, :dim], dtype="<f4").view(np.uint8)
        block[:, off:off + dim * 4] = packed.reshape(vc, dim * 4)
    elif fmt == 2:
        clamped = np.clip(arr[:, :dim] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        block[:, off:off + dim] = clamped
    else:
        raise NotImplementedError(f"vertex format {fmt} not supported (write)")


# ==========================================================================
# 3. 본 이름(Avatar.m_TOS) / 스킨 웨이트 / 계층
# ==========================================================================
def build_bone_name_map(env):
    tos = {}
    for o in env.objects:
        if o.type.name == "Avatar":
            try:
                t = o.read_typetree()
            except Exception:
                continue
            for pair in t.get("m_TOS", []):
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    tos[int(pair[0]) & 0xFFFFFFFF] = pair[1]
    return tos


def hash_to_path(tos, h):
    return tos.get(int(h) & 0xFFFFFFFF)


def hash_to_leaf(tos, h):
    p = hash_to_path(tos, h)
    return p.split("/")[-1] if p else f"<hash:{int(h) & 0xFFFFFFFF}>"


def get_skin(buf_u8, tree, chans, stride, start, vc):
    w = read_attr(buf_u8, ATTR_BLENDWEIGHT, chans, stride, start, vc)
    bi = read_attr(buf_u8, ATTR_BLENDINDICES, chans, stride, start, vc)
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


def build_parent_map(tos, hashes):
    """본 경로(TOS)로 부모 인덱스 배열 구성. 부모 = 같은 메시 본 중 최근접 조상."""
    paths = [hash_to_path(tos, h) or f"<{int(h) & 0xFFFFFFFF}>" for h in hashes]
    p2i = {}
    for i, p in enumerate(paths):
        p2i.setdefault(p, i)
    parent = []
    for p in paths:
        pi, q = -1, p
        while "/" in q:
            q = q.rsplit("/", 1)[0]
            if q in p2i:
                pi = p2i[q]
                break
        parent.append(pi)
    return parent, paths


# --- Transform/GameObject 기반 본 이름·계층 (m_BoneNameHashes 가 비거나 TOS 미스일 때) ---
def _safe_tt(o):
    try:
        return o.read_typetree() if o is not None else None
    except Exception:
        return None


def build_id_map(env):
    """path_id -> object."""
    return {o.path_id: o for o in env.objects}


def _gameobject_name(id2obj, transform_pid):
    """Transform path_id -> 그 Transform 이 붙은 GameObject 의 이름."""
    tr = _safe_tt(id2obj.get(transform_pid))
    if not tr:
        return None
    go = id2obj.get(tr.get("m_GameObject", {}).get("m_PathID"))
    g = _safe_tt(go)
    return g.get("m_Name") if g else None


def smr_bone_pids(env, id2obj):
    """mesh path_id -> [bone Transform path_id ...]  (SkinnedMeshRenderer.m_Bones 순서)."""
    out = {}
    for o in env.objects:
        if o.type.name != "SkinnedMeshRenderer":
            continue
        t = _safe_tt(o)
        if not t:
            continue
        mp = t.get("m_Mesh", {}).get("m_PathID")
        bones = [b.get("m_PathID") for b in t.get("m_Bones", [])]
        if mp is not None and bones:
            out[mp] = bones
    return out


def parents_from_transforms(id2obj, bone_pids):
    """본 Transform 들의 m_Father 사슬을 따라 본 집합 내 최근접 조상 인덱스."""
    pid2idx = {pid: i for i, pid in enumerate(bone_pids)}
    parent = []
    for pid in bone_pids:
        tr = _safe_tt(id2obj.get(pid))
        cur = (tr.get("m_Father", {}).get("m_PathID") if tr else 0) or 0
        j, seen = -1, 0
        while cur and seen < 100000:
            if cur in pid2idx:
                j = pid2idx[cur]; break
            ftr = _safe_tt(id2obj.get(cur))
            cur = (ftr.get("m_Father", {}).get("m_PathID") if ftr else 0) or 0
            seen += 1
        parent.append(j)
    return parent


def resolve_bones(env, id2obj, tos, mesh_obj, tree, smr_map=None):
    """본 이름 리스트와 부모 인덱스 반환 (길이 = m_BindPose 수).

    1) m_BoneNameHashes 가 있고 TOS 로 충분히 풀리면 기존 방식 사용(이전 파일 무회귀).
    2) 아니면 SkinnedMeshRenderer.m_Bones → Transform → GameObject 이름/계층 사용.
    3) 둘 다 안되면 가능한 정보로 폴백.
    """
    nb = len(tree.get("m_BindPose", []))
    if nb == 0:
        return [], []
    hashes = tree.get("m_BoneNameHashes", [])

    if hashes and len(hashes) == nb:
        resolved = sum(1 for h in hashes if (int(h) & 0xFFFFFFFF) in tos)
        if resolved >= nb * 0.5:                       # 기존 해시+TOS 경로
            names = [hash_to_leaf(tos, h) for h in hashes]
            parent, _ = build_parent_map(tos, hashes)
            return names, parent

    smr_map = smr_map if smr_map is not None else smr_bone_pids(env, id2obj)
    pids = smr_map.get(mesh_obj.path_id)
    if pids and len(pids) == nb:                        # Transform 경로
        names = [(_gameobject_name(id2obj, p) or f"<bone:{i}>") for i, p in enumerate(pids)]
        if sum(1 for n in names if not n.startswith("<bone:")) >= nb * 0.5:
            return names, parents_from_transforms(id2obj, pids)

    if hashes and len(hashes) == nb:                    # 마지막 폴백
        names = [hash_to_leaf(tos, h) for h in hashes]
        parent, _ = build_parent_map(tos, hashes)
        return names, parent
    return [f"<bone:{i}>" for i in range(nb)], [-1] * nb


def _depth_order(parent):
    nb = len(parent)
    depth = [0] * nb
    for i in range(nb):
        d, j, seen = 0, parent[i], 0
        while j >= 0 and seen < nb:
            d += 1; j = parent[j]; seen += 1
        depth[i] = d
    return sorted(range(nb), key=lambda i: depth[i])


# ==========================================================================
# 4. 스키닝 행렬 / 메시 베이킹
# ==========================================================================
def independent_skin_matrices(bps, deltas):
    nb = len(bps)
    M = np.repeat(np.eye(4)[None], nb, axis=0)
    for i, D in deltas.items():
        M[i] = np.linalg.inv(bps[i]) @ D @ bps[i]
    return M


def hierarchical_skin_matrices(bps, parent, deltas):
    nb = len(bps)
    restW = [np.linalg.inv(b) for b in bps]
    restLocal = [restW[i] if parent[i] < 0
                 else np.linalg.inv(restW[parent[i]]) @ restW[i]
                 for i in range(nb)]
    posedW = [None] * nb
    for i in _depth_order(parent):
        D = deltas.get(i, np.eye(4))
        pl = restLocal[i] @ D
        posedW[i] = pl if parent[i] < 0 else posedW[parent[i]] @ pl
    return np.array([posedW[i] @ bps[i] for i in range(nb)])


def _is_descendant(parent, node, ancestor):
    """node 의 부모 사슬을 올라가 ancestor 를 만나면 True(진성 자손)."""
    j, seen = node, 0
    while j >= 0 and seen < 100000:
        j = parent[j]
        if j == ancestor:
            return True
        seen += 1
    return False


def expand_targets(targets, parent, name2idx, idx2leaf):
    """targets → deltas{bone_idx:4x4}. 보정 본은 스케일 역수 추가.
    comp_bones 지정 시 그 본(자손인 것만)을 보정, 없으면 바로 아래 자식을 자동 보정."""
    explicit, missing = {}, []
    for tg in targets:
        if tg.is_identity():
            continue
        i = name2idx.get(tg.bone)
        if i is None:
            missing.append(tg.bone)
            continue
        explicit[i] = tg
    deltas, applied, comp = {}, [], []
    for i, tg in explicit.items():
        deltas[i] = tg.delta()
        applied.append(idx2leaf[i])
    for i, tg in explicit.items():
        if not tg.compensate:
            continue
        sx, sy, sz = tg.scale
        if (sx, sy, sz) == (1, 1, 1):
            continue
        inv = trs(scale=(1.0 / sx, 1.0 / sy, 1.0 / sz))

        if tg.comp_bones:                       # 명시적 보정 대상(자손인 것만)
            used = False
            for bn in tg.comp_bones:
                j = name2idx.get(bn)
                if j is None or j in explicit or j in deltas:
                    continue
                if not _is_descendant(parent, j, i):   # 대상 본 아래에 있어야 의미가 있음
                    continue
                deltas[j] = inv; comp.append(idx2leaf[j]); used = True
            if used:
                continue                        # 명시 대상 처리 완료
            # 유효한 명시 대상이 없으면 자동 폴백

        for j in range(len(parent)):            # 자동: 바로 아래 자식
            if parent[j] == i and j not in explicit and j not in deltas:
                deltas[j] = inv
                comp.append(idx2leaf[j])
    return deltas, applied, comp, missing


class MeshInfo:
    def __init__(self, obj, tree):
        self.obj = obj
        self.tree = tree
        self.name = tree.get("m_Name", "?")
        self.vc = tree["m_VertexData"]["m_VertexCount"]
        self.bind_count = len(tree.get("m_BindPose", []))
        self.skinned = self.bind_count > 0


def list_meshes(env):
    out = []
    for o in env.objects:
        if o.type.name == "Mesh":
            try:
                t = o.read_typetree()
            except Exception:
                continue
            out.append(MeshInfo(o, t))
    return out


def bone_table(bone_names, tree, buf_u8=None):
    """[(idx, name, weighted_influence)] 영향도 내림차순."""
    nb = len(bone_names)
    infl = np.zeros(nb)
    if buf_u8 is not None and nb:
        vc, chans, stride, start, _ = stream_layout(tree)
        w, bi = get_skin(buf_u8, tree, chans, stride, start, vc)
        if w is not None:
            bi = np.clip(bi, 0, nb - 1)
            for k in range(4):
                np.add.at(infl, bi[:, k], w[:, k])
    rows = [(i, bone_names[i], float(infl[i])) for i in range(nb)]
    rows.sort(key=lambda r: -r[2])
    return rows


def bake_mesh(tree, bone_names, parent, targets, recompute_normals=True, hierarchical=True):
    """제자리에서 tree 의 m_VertexData/m_LocalAABB 수정. stats 반환.
    bone_names/parent 는 resolve_bones() 결과(길이 = m_BindPose 수)."""
    bps_raw = tree.get("m_BindPose", [])
    if not bps_raw or not bone_names:
        return {"skinned": False, "applied": [], "compensated": [],
                "influenced": 0, "max_disp": 0.0}

    idx2leaf = bone_names
    name2idx = {}
    for i, n in enumerate(idx2leaf):
        name2idx.setdefault(n, i)

    deltas, applied, comp, missing = expand_targets(targets, parent, name2idx, idx2leaf)
    if not deltas:
        return {"skinned": True, "applied": [], "compensated": [],
                "influenced": 0, "max_disp": 0.0, "missing": missing}

    vc, chans, stride, start, _ = stream_layout(tree)
    buf = bytearray(tree["m_VertexData"]["m_DataSize"])
    u8 = np.frombuffer(buf, dtype=np.uint8)

    bps = [mat_from(b) for b in bps_raw]
    nb = len(bps)
    M = (hierarchical_skin_matrices(bps, parent, deltas) if hierarchical
         else independent_skin_matrices(bps, deltas))

    pos = read_attr(u8, ATTR_POS, chans, stride, start, vc)
    w, bidx = get_skin(u8, tree, chans, stride, start, vc)
    if pos is None or w is None:
        return {"skinned": True, "applied": [], "compensated": [],
                "influenced": 0, "max_disp": 0.0,
                "error": "could not read vertex/skin data"}
    bidx = np.clip(bidx, 0, nb - 1)

    Mb = M[bidx]
    Bv = (Mb * w[..., None, None]).sum(axis=1)

    ph = np.concatenate([pos, np.ones((vc, 1))], axis=1)
    newpos = np.einsum("vij,vj->vi", Bv, ph)[:, :3]
    write_attr(u8, newpos, ATTR_POS, chans, stride, start, vc)

    moved_idx = set(deltas.keys())
    infl_mask = np.zeros(vc, bool)
    for k in range(4):
        infl_mask |= np.isin(bidx[:, k], list(moved_idx)) & (w[:, k] > 0)
    disp = np.linalg.norm(newpos - pos, axis=1)

    if recompute_normals:
        R3 = Bv[:, :3, :3]
        n = read_attr(u8, ATTR_NORMAL, chans, stride, start, vc)
        if n is not None:
            try:
                NIT = np.linalg.inv(R3).transpose(0, 2, 1)
            except np.linalg.LinAlgError:
                NIT = R3.copy()
                dets = np.linalg.det(R3)
                ok = np.abs(dets) > 1e-12
                NIT[ok] = np.linalg.inv(R3[ok]).transpose(0, 2, 1)
            newn = np.einsum("vij,vj->vi", NIT, n)
            ln = np.linalg.norm(newn, axis=1, keepdims=True); ln[ln == 0] = 1
            write_attr(u8, newn / ln, ATTR_NORMAL, chans, stride, start, vc)
        t = read_attr(u8, ATTR_TANGENT, chans, stride, start, vc)
        if t is not None:
            txyz = np.einsum("vij,vj->vi", R3, t[:, :3])
            lt = np.linalg.norm(txyz, axis=1, keepdims=True); lt[lt == 0] = 1
            t[:, :3] = txyz / lt
            write_attr(u8, t, ATTR_TANGENT, chans, stride, start, vc)

    mn, mx = newpos.min(0), newpos.max(0)
    c, e = (mn + mx) / 2, (mx - mn) / 2
    old = tree["m_LocalAABB"]
    tree["m_LocalAABB"] = {
        "m_Center": {"x": float(c[0]), "y": float(c[1]), "z": float(c[2])},
        "m_Extent": {"x": float(e[0]), "y": float(e[1]), "z": float(e[2])},
    }
    tree["m_VertexData"]["m_DataSize"] = bytes(buf)

    return {
        "skinned": True, "applied": applied, "compensated": comp, "missing": missing,
        "influenced": int(infl_mask.sum()),
        "max_disp": float(disp[infl_mask].max()) if infl_mask.any() else 0.0,
        "max_disp_other": float(disp[~infl_mask].max()) if (~infl_mask).any() else 0.0,
        "old_extent": (old["m_Extent"]["x"], old["m_Extent"]["y"], old["m_Extent"]["z"]),
        "new_extent": (float(e[0]), float(e[1]), float(e[2])),
    }


# ==========================================================================
# 5. 번들 / 폴더 처리
# ==========================================================================
def process_bundle(in_path, out_path, targets, recompute_normals=True,
                   packer="original", mesh_filter=None, hierarchical=True,
                   include_hidden=False, log=print, dry_run=False):
    env = UnityPy.load(str(in_path))
    tos = build_bone_name_map(env)
    id2obj = build_id_map(env)
    smr_map = smr_bone_pids(env, id2obj)
    results, any_change = [], False

    for mi in list_meshes(env):
        if not mi.skinned:
            continue
        if mesh_filter is not None:
            if mi.name not in mesh_filter:
                continue
        elif (not include_hidden) and mi.name in DEFAULT_HIDDEN:
            continue

        bone_names, parent = resolve_bones(env, id2obj, tos, mi.obj, mi.tree, smr_map)
        stats = bake_mesh(mi.tree, bone_names, parent, targets,
                          recompute_normals=recompute_normals, hierarchical=hierarchical)
        stats["mesh"] = mi.name
        results.append(stats)
        if stats.get("missing"):
            log(f"  [{mi.name}] bones not in this mesh (skipped): {', '.join(stats['missing'])}")
        if stats.get("applied"):
            any_change = True
            extra = (f"  | child-comp: {', '.join(stats['compensated'])}"
                     if stats.get("compensated") else "")
            log(f"  [{mi.name}] applied: {', '.join(stats['applied'])}{extra}")
            log(f"        affected verts {stats['influenced']} | max move "
                f"{stats['max_disp']:.4f} | off-target {stats.get('max_disp_other', 0):.2e}")
            log(f"        AABB extent {tuple(round(x,4) for x in stats['old_extent'])}"
                f" -> {tuple(round(x,4) for x in stats['new_extent'])}")
            if not dry_run:
                mi.obj.save_typetree(mi.tree)
        else:
            log(f"  [{mi.name}] no matching bone — skipped")

    if dry_run:
        log("  (preview only: not saved)")
        return results
    if not any_change:
        log("  no changes — nothing saved")
        return results

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    blob = env.file.save(packer=packer)
    with open(out_path, "wb") as f:
        f.write(blob)
    log(f"  saved: {out_path}  ({len(blob):,} bytes, packer={packer})")
    return results


def process_folder(in_dir, out_dir, targets, prefix="", suffix="_baked",
                   recompute_normals=True, packer="original", mesh_filter=None,
                   hierarchical=True, include_hidden=False,
                   patterns=("*.unity",), log=print, dry_run=False):
    in_dir, out_dir = Path(in_dir), Path(out_dir)
    files = []
    for pat in patterns:
        files += sorted(in_dir.glob(pat))
    files = [f for f in files if f.is_file()]
    if not files:
        log(f"no matching files in input folder: {in_dir}")
        return
    log(f"processing {len(files)} file(s)\n")
    for f in files:
        out_name = f"{prefix}{f.stem}{suffix}{f.suffix}"
        log(f"• {f.name} -> {out_name}")
        try:
            process_bundle(f, out_dir / out_name, targets,
                           recompute_normals=recompute_normals, packer=packer,
                           mesh_filter=mesh_filter, hierarchical=hierarchical,
                           include_hidden=include_hidden, log=log, dry_run=dry_run)
        except Exception as e:
            log(f"  ! failed: {e}")
        log("")
    log("batch done.")


# ==========================================================================
# 6. CLI
# ==========================================================================
def parse_target_spec(spec):
    """'Bone;s=1.4,1.4,1.4;r=0,0,0;t=0,0,0;comp=1'  (s/r/t/comp 선택)."""
    parts = spec.split(";")
    bone = parts[0].strip()
    s, r, t, comp = (1, 1, 1), (0, 0, 0), (0, 0, 0), None

    def triple(v):
        nums = [float(x) for x in v.split(",")]
        if len(nums) == 1:
            nums *= 3
        return tuple(nums[:3])

    for p in parts[1:]:
        p = p.strip()
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip().lower()
        if k in ("s", "scale"):
            s = triple(v)
        elif k in ("r", "rot", "rotate"):
            r = triple(v)
        elif k in ("t", "move", "translate"):
            t = triple(v)
        elif k in ("c", "comp", "compensate"):
            comp = v.strip().lower() in ("1", "true", "y", "yes", "on")
    if comp is None:                       # 미지정이면 본 종류로 기본값
        comp = default_compensate(bone)
    return Target(bone, translate=t, rotate=r, scale=s, compensate=comp)


def run_cli(args):
    targets = [parse_target_spec(s) for s in (args.target or [])]
    if getattr(args, "thigh", None):
        try:
            src, dst = args.thigh.lower().split(":")
            targets += thigh_targets(src, dst)
        except (ValueError, KeyError):
            print("--thigh format: FROM:TO (slim/default/thick). e.g. --thigh slim:thick")
            return 2

    if args.list_bones:
        env = UnityPy.load(args.infile)
        tos = build_bone_name_map(env)
        id2obj = build_id_map(env)
        smr_map = smr_bone_pids(env, id2obj)
        for mi in list_meshes(env):
            tag = "" if mi.skinned else "  (no skin · cannot bake)"
            hide = "  [hidden by default]" if mi.name in DEFAULT_HIDDEN else ""
            print(f"\n[{mi.name}] verts {mi.vc}, bones {mi.bind_count}{tag}{hide}")
            if not mi.skinned:
                continue
            bone_names, _ = resolve_bones(env, id2obj, tos, mi.obj, mi.tree, smr_map)
            u8 = np.frombuffer(bytearray(mi.tree["m_VertexData"]["m_DataSize"]), np.uint8)
            for idx, name, infl in bone_table(bone_names, mi.tree, u8):
                if infl > 0.01:
                    print(f"   idx {idx:3d}  w={infl:8.1f}  {name}")
        return 0

    if not targets:
        print("No bones to apply. Use --target / --thigh / --list-bones.")
        return 2

    apply_spine_comp(targets, getattr(args, "spine_comp", "spine2"))

    for m in target_notes(targets):
        print(m)

    mesh_filter = set(args.mesh) if args.mesh else None
    common = dict(recompute_normals=not args.no_normals, packer=args.packer,
                  mesh_filter=mesh_filter, hierarchical=not args.independent,
                  include_hidden=args.include_hidden, dry_run=args.dry_run)
    if args.in_dir:
        if not args.out_dir:
            print("--in-dir requires --out-dir."); return 2
        process_folder(args.in_dir, args.out_dir, targets,
                       prefix=args.prefix, suffix=args.suffix, **common)
    else:
        if not args.infile or not args.outfile:
            print("--in and --out are required."); return 2
        process_bundle(args.infile, args.outfile, targets, **common)
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="sifas_mesh_baker",
        description="Unity skinned-mesh pose baking (equivalent to Blender Apply-Armature)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--gui", action="store_true", help="force GUI")
    p.add_argument("--menu", "--cli", dest="menu", action="store_true", help="force text menu")
    p.add_argument("--in", dest="infile", help="input bundle")
    p.add_argument("--out", dest="outfile", help="output bundle")
    p.add_argument("--in-dir", dest="in_dir", help="input folder (batch)")
    p.add_argument("--out-dir", dest="out_dir", help="output folder (batch)")
    p.add_argument("--prefix", default="", help="batch output filename prefix")
    p.add_argument("--suffix", default="_baked", help="batch output filename suffix")
    p.add_argument("--target", action="append",
                   help="'Bone;s=1.4,1.4,1.4;r=0,0,0;t=0,0,0;comp=1' (repeatable)")
    p.add_argument("--thigh", metavar="FROM:TO",
                   help="thigh preset transition (slim/default/thick). "
                        "e.g. --thigh slim:thick -> both UpLeg + child compensation")
    p.add_argument("--spine-comp", dest="spine_comp", default="spine2",
                   choices=["spine2", "spine1", "both", "auto"],
                   help="which bone the spine child-compensation inverse-scales "
                        "(spine2 widens Spine+Spine1; spine1 widens only Spine)")
    p.add_argument("--mesh", action="append",
                   help="restrict to mesh name(s) (repeatable). default: all skinned except hidden.")
    p.add_argument("--include-hidden", action="store_true",
                   help="also process hidden meshes (foot_shadow_Plane/Hair/Face)")
    p.add_argument("--independent", action="store_true",
                   help="disable bone-hierarchy propagation (apply each bone independently)")
    p.add_argument("--packer", default="original",
                   choices=["original", "lz4", "lzma", "none"], help="save compression")
    p.add_argument("--no-normals", action="store_true", help="skip normal/tangent recompute")
    p.add_argument("--list-bones", action="store_true", help="list bones then exit")
    p.add_argument("--dry-run", action="store_true", help="preview only (no save)")
    return p


# ==========================================================================
# 7. 대화형 텍스트 메뉴 (Termux/헤드리스)
# ==========================================================================
def _ask(prompt, default=None):
    s = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
    return s if s else (default if default is not None else "")


def _ask_triple(prompt, default):
    s = _ask(prompt, ",".join(str(x) for x in default))
    try:
        nums = [float(x) for x in s.replace(" ", "").split(",")]
        if len(nums) == 1:
            nums *= 3
        return tuple(nums[:3])
    except Exception:
        return default


def _ask_yn(prompt, default="n"):
    return _ask(prompt + " (y/n)", default).lower().startswith("y")


def default_sukusta_dir(name):
    base = os.environ.get("SUKUSTA_DIR")
    if base:
        return os.path.join(os.path.expanduser(base), name)
    if is_termux():
        return os.path.expanduser(f"~/storage/downloads/sukusta/{name}")
    return os.path.expanduser(f"~/sukusta/{name}")


def find_asset_bundles(root):
    """Recursively collect Unity asset bundles under root (.unity files and any
    file whose header is UnityFS)."""
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            if fn.lower().endswith(".unity"):
                found.append(p)
                continue
            try:
                with open(p, "rb") as fh:
                    if fh.read(8).startswith(b"UnityFS"):
                        found.append(p)
            except Exception:
                pass
    return sorted(found)


def _parse_multi_select(s, n):
    """Parse a selection like '3', '1,4-8', 'all' into 0-based indices."""
    s = (s or "").strip().lower()
    if not s or s == "all":
        return list(range(n))
    out = []
    for part in s.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-"); a, b = int(a), int(b)
            except ValueError:
                continue
            for k in range(min(a, b), max(a, b) + 1):
                if 1 <= k <= n:
                    out.append(k - 1)
        else:
            try:
                k = int(part)
            except ValueError:
                continue
            if 1 <= k <= n:
                out.append(k - 1)
    seen, res = set(), []
    for i in out:
        if i not in seen:
            seen.add(i); res.append(i)
    return res


def _baked_output_path(src, src_root, modded_root):
    """modded_root/<sub-path of src under src_root>/<stem>_baked<ext>."""
    src = Path(os.path.expanduser(str(src)))
    modded_root = Path(os.path.expanduser(str(modded_root)))
    try:
        rel = src.resolve().relative_to(Path(os.path.expanduser(str(src_root))).resolve())
    except Exception:
        rel = Path(src.name)
    return modded_root / rel.parent / (rel.stem + "_baked" + rel.suffix)


def _menu_meshes_and_bones(env, id2obj, tos, smr_map):
    """List meshes, ask whether to include hidden ones, and print each mesh's
    most-influential bones (to help choose bone names). Returns (include_hidden,
    targetable_meshes), or None if there's nothing to bake."""
    all_meshes = list_meshes(env)
    skinned = [m for m in all_meshes if m.skinned]
    if not skinned:
        print("No skinned mesh found."); return None
    print("\nMeshes:")
    for m in all_meshes:
        flag = "" if m.skinned else "  (no skin · cannot bake)"
        hide = "  [hidden by default]" if m.name in DEFAULT_HIDDEN else ""
        print(f"  - {m.name}  (verts {m.vc}, bones {m.bind_count}){flag}{hide}")
    inc = _ask_yn("Also process hidden meshes (Hair/Face/...)?", "n")
    targetable = [m for m in skinned if inc or m.name not in DEFAULT_HIDDEN]
    print("\nMeshes to process:", ", ".join(m.name for m in targetable))
    for m in targetable:
        bone_names, _ = resolve_bones(env, id2obj, tos, m.obj, m.tree, smr_map)
        u8 = np.frombuffer(bytearray(m.tree["m_VertexData"]["m_DataSize"]), np.uint8)
        print(f"\n[{m.name}] top bones by influence:")
        shown = 0
        for idx, name, infl in bone_table(bone_names, m.tree, u8):
            if infl > 0.01:
                print(f"   {name}  (w={infl:.1f})"); shown += 1
            if shown >= 25:
                print("   ..."); break
    return inc, targetable


def _collect_targets_interactive():
    """Collect the pose (thigh preset + bones + spine comp) and save options.
    Returns (targets, hierarchical, packer, recompute_normals), or None if no
    poses were added."""
    hierarchical = not _ask_yn("Disable bone-hierarchy propagation? (each bone independent)", "n")
    targets = []
    tp = _ask("Thigh preset ('FROM:TO' = slim/default/thick, blank to skip)", "")
    if tp:
        try:
            a, b = tp.lower().split(":")
            targets += thigh_targets(a, b)
            print(f"  + thigh {a}->{b} (both UpLeg, child-comp ON)")
        except (ValueError, KeyError):
            print("  (bad preset format, skipped)")
    print("\nAdd poses. Empty bone name + Enter to finish.")
    while True:
        bone = _ask("\nBone name")
        if not bone:
            break
        scale = _ask_triple("  scale x,y,z", (1, 1, 1))
        rot = _ask_triple("  rotate(deg) x,y,z", (0, 0, 0))
        move = _ask_triple("  move x,y,z", (0, 0, 0))
        comp = _ask_yn("  child compensation?", "y" if default_compensate(bone) else "n")
        targets.append(Target(bone, translate=move, rotate=rot, scale=scale, compensate=comp))
        print(f"  + {targets[-1].describe()}")
    if not targets:
        return None
    packer = _ask("Compression (original/lz4/lzma/none)", "original")
    norm = _ask_yn("Recompute normals?", "y")
    if any(t.bone.startswith("Spine") and t.compensate for t in targets):
        sc = _ask("Spine comp target (spine2/spine1/both/auto)", "spine2")
        apply_spine_comp(targets, sc)
    return targets, hierarchical, packer, norm


def _run_menu_library():
    """Scan a folder (default sukusta/extracted), pick bundles from a list, set
    one pose, and bake them all into sukusta/modded - no long paths to type."""
    extracted = default_sukusta_dir("extracted")
    modded = default_sukusta_dir("modded")
    print(f"  extracted: {extracted}")
    print(f"  modded   : {modded}")
    sc = _ask("Source  1) extracted   2) modded   3) custom path", "1").strip()
    if sc == "2":
        src_root = modded
    elif sc == "3":
        src_root = _ask("Source folder") or extracted
    else:
        src_root = extracted
    src_root = os.path.expanduser(src_root)

    print(f"\nScanning {src_root} ...")
    bundles = find_asset_bundles(src_root)
    if not bundles:
        print("No .unity bundles found there. Extract some first, or choose another folder.")
        return
    for i, b in enumerate(bundles, 1):
        try:
            rel = os.path.relpath(b, src_root)
        except Exception:
            rel = os.path.basename(b)
        print(f"  {i:3d}) {rel}")
    chosen = _parse_multi_select(_ask("Select bundle(s)  (e.g. 3, 1,4-8, all)", "1"), len(bundles))
    if not chosen:
        print("Nothing selected."); return
    selected = [bundles[i] for i in chosen]

    # Use the first selected bundle as a reference to show mesh/bone names.
    ref = selected[0]
    print(f"\nReference bundle (for mesh/bone names): {os.path.basename(ref)}")
    env = UnityPy.load(str(ref))
    tos = build_bone_name_map(env)
    id2obj = build_id_map(env)
    smr_map = smr_bone_pids(env, id2obj)
    mb = _menu_meshes_and_bones(env, id2obj, tos, smr_map)
    if not mb:
        return
    inc, _ = mb

    cfg = _collect_targets_interactive()
    if not cfg:
        print("No poses added."); return
    targets, hierarchical, packer, norm = cfg

    modded = os.path.expanduser(modded)
    for note in target_notes(targets):
        print(note)
    out0 = _baked_output_path(ref, src_root, modded)
    print(f"\nPreview ({os.path.basename(ref)} -> {out0}):")
    process_bundle(ref, out0, targets, recompute_normals=norm, packer=packer,
                   include_hidden=inc, hierarchical=hierarchical, log=print, dry_run=True)
    if not _ask_yn(f"\nApply to all {len(selected)} selected bundle(s) and save?", "y"):
        print("Cancelled."); return

    ok = fail = 0
    for b in selected:
        out = _baked_output_path(b, src_root, modded)
        print(f"\n[{os.path.basename(b)}] -> {out}")
        try:
            process_bundle(b, out, targets, recompute_normals=norm, packer=packer,
                           include_hidden=inc, hierarchical=hierarchical, log=print)
            ok += 1
        except Exception as e:
            print(f"  ! error: {e}"); fail += 1
    print(f"\nDone. ok={ok} fail={fail}   (output root: {modded})")


def run_menu():
    print("\n=== SIFAS Mesh Baker (text menu) ===")
    m = _ask("Pick input:  1) library (scan a folder, choose from a list)   "
             "2) single file (type a path)", "1")
    if m.strip() == "2":
        return _run_menu_single()
    return _run_menu_library()


def _run_menu_single():
    infile = _ask("Input bundle path")
    if not infile or not os.path.exists(infile):
        print("File not found."); return

    env = UnityPy.load(infile)
    tos = build_bone_name_map(env)
    id2obj = build_id_map(env)
    smr_map = smr_bone_pids(env, id2obj)
    all_meshes = list_meshes(env)
    skinned = [m for m in all_meshes if m.skinned]
    if not skinned:
        print("No skinned mesh found."); return

    print("\nMeshes:")
    for m in all_meshes:
        flag = "" if m.skinned else "  (no skin · cannot bake)"
        hide = "  [hidden by default]" if m.name in DEFAULT_HIDDEN else ""
        print(f"  - {m.name}  (verts {m.vc}, bones {m.bind_count}){flag}{hide}")

    inc = _ask_yn("Also process hidden meshes (Hair/Face/...)?", "n")
    targetable = [m for m in skinned if inc or m.name not in DEFAULT_HIDDEN]
    print("\nMeshes to process:", ", ".join(m.name for m in targetable))

    for m in targetable:
        bone_names, _ = resolve_bones(env, id2obj, tos, m.obj, m.tree, smr_map)
        u8 = np.frombuffer(bytearray(m.tree["m_VertexData"]["m_DataSize"]), np.uint8)
        print(f"\n[{m.name}] top bones by influence:")
        shown = 0
        for idx, name, infl in bone_table(bone_names, m.tree, u8):
            if infl > 0.01:
                print(f"   {name}  (w={infl:.1f})"); shown += 1
            if shown >= 25:
                print("   ..."); break

    hierarchical = not _ask_yn("Disable bone-hierarchy propagation? (each bone independent)", "n")
    targets = []
    tp = _ask("Thigh preset ('FROM:TO' = slim/default/thick, blank to skip)", "")
    if tp:
        try:
            a, b = tp.lower().split(":")
            targets += thigh_targets(a, b)
            print(f"  + thigh {a}->{b} (both UpLeg, child-comp ON)")
        except (ValueError, KeyError):
            print("  (bad preset format, skipped)")
    print("\nAdd poses. Empty bone name + Enter to finish.")
    while True:
        bone = _ask("\nBone name")
        if not bone:
            break
        scale = _ask_triple("  scale x,y,z", (1, 1, 1))
        rot = _ask_triple("  rotate(deg) x,y,z", (0, 0, 0))
        move = _ask_triple("  move x,y,z", (0, 0, 0))
        comp = _ask_yn("  child compensation?", "y" if default_compensate(bone) else "n")
        targets.append(Target(bone, translate=move, rotate=rot, scale=scale, compensate=comp))
        print(f"  + {targets[-1].describe()}")

    if not targets:
        print("No poses added."); return

    packer = _ask("Compression (original/lz4/lzma/none)", "original")
    norm = _ask_yn("Recompute normals?", "y")
    default_out = str(Path(infile).with_name(Path(infile).stem + "_baked" + Path(infile).suffix))
    outfile = _ask("Output path", default_out)
    mesh_filter = {m.name for m in targetable}

    if any(t.bone.startswith("Spine") and t.compensate for t in targets):
        sc = _ask("Spine comp target (spine2/spine1/both/auto)", "spine2")
        apply_spine_comp(targets, sc)

    for m in target_notes(targets):
        print(m)
    print("\nPreview:")
    process_bundle(infile, outfile, targets, recompute_normals=norm, packer=packer,
                   mesh_filter=mesh_filter, hierarchical=hierarchical, log=print, dry_run=True)
    if _ask_yn("\nSave?", "y"):
        process_bundle(infile, outfile, targets, recompute_normals=norm, packer=packer,
                       mesh_filter=mesh_filter, hierarchical=hierarchical, log=print)
    else:
        print("Cancelled.")


# ==========================================================================
# 8. Tkinter GUI
# ==========================================================================
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    state = {"env": None, "tos": {}, "id2obj": {}, "smr": {},
             "all_meshes": [], "bones": {}, "src": None}
    mesh_vars = {}     # name -> {"var":BooleanVar, "info":MeshInfo}
    target_rows = []   # [{bone, s[3], r[3], t[3], comp, widgets...}]

    root = tk.Tk()
    root.title("SIFAS Mesh Baker — Pose Baking")
    root.geometry("1200x880")
    root.minsize(1040, 640)
    PAD = 8
    main = ttk.Frame(root, padding=PAD)
    main.pack(fill="both", expand=True)

    # ---------- TOP: target ----------
    src = ttk.LabelFrame(main, text="Target", padding=PAD)
    src.pack(side="top", fill="x")
    mode = tk.StringVar(value="file")
    ttk.Radiobutton(src, text="Single file", variable=mode, value="file").grid(row=0, column=0, sticky="w")
    ttk.Radiobutton(src, text="Folder (batch)", variable=mode, value="dir").grid(row=0, column=1, sticky="w")
    in_var, out_var, suffix_var = tk.StringVar(), tk.StringVar(), tk.StringVar(value="_baked")
    ttk.Label(src, text="Input").grid(row=1, column=0, sticky="e")
    ttk.Entry(src, textvariable=in_var, width=80).grid(row=1, column=1, columnspan=3, sticky="we", padx=4)
    ttk.Label(src, text="Output").grid(row=2, column=0, sticky="e")
    ttk.Entry(src, textvariable=out_var, width=80).grid(row=2, column=1, columnspan=3, sticky="we", padx=4)
    ttk.Label(src, text="Batch suffix").grid(row=3, column=0, sticky="e")
    ttk.Entry(src, textvariable=suffix_var, width=16).grid(row=3, column=1, sticky="w", padx=4)
    src.columnconfigure(1, weight=1)

    def browse_in():
        p = (filedialog.askopenfilename(title="Input bundle",
             filetypes=[("Unity bundle", "*.unity *.bundle *.ab"), ("All", "*.*")])
             if mode.get() == "file" else filedialog.askdirectory(title="Input folder"))
        if p:
            in_var.set(p)

    def browse_out():
        p = (filedialog.asksaveasfilename(title="Output bundle", defaultextension=".unity")
             if mode.get() == "file" else filedialog.askdirectory(title="Output folder"))
        if p:
            out_var.set(p)

    ttk.Button(src, text="Browse", command=lambda: browse_in()).grid(row=1, column=4, padx=4)
    ttk.Button(src, text="Browse", command=lambda: browse_out()).grid(row=2, column=4, padx=4)

    # ---------- TOP: meshes ----------
    mesh_frame = ttk.LabelFrame(main, text="Meshes (only checked are processed)", padding=PAD)
    mesh_frame.pack(side="top", fill="x", pady=(PAD, 0))
    show_hidden = tk.BooleanVar(value=False)
    top_mesh = ttk.Frame(mesh_frame); top_mesh.pack(fill="x")
    ttk.Checkbutton(top_mesh, text="Show hidden meshes (foot_shadow_Plane · Hair · Face)",
                    variable=show_hidden, command=lambda: render_mesh_checks()).pack(side="left")
    ttk.Button(top_mesh, text="Scan", command=lambda: scan()).pack(side="right")
    mesh_checks = ttk.Frame(mesh_frame); mesh_checks.pack(fill="x", pady=(4, 0))

    # ---------- TOP: thigh presets ----------
    preset = ttk.LabelFrame(main, text="Thigh presets (Thigh Scale · both UpLeg + child compensation)", padding=PAD)
    preset.pack(side="top", fill="x", pady=(PAD, 0))
    pbtns = ttk.Frame(preset); pbtns.pack(fill="x")
    for a, b in THIGH_TRANSITIONS:
        ttk.Button(pbtns, text=f"{a} \u2192 {b}", width=15,
                   command=lambda a=a, b=b: apply_thigh_preset(a, b)).pack(side="left", padx=2)
    ttk.Label(preset, foreground="#a33",
              text="Note — Spine (waist): ScaleX is the HEIGHT axis; changing X changes height "
                   "and the head no longer lines up. Resize the waist with Y/Z only (keep X=1.0).").pack(anchor="w", pady=(4, 0))
    spine_row = ttk.Frame(preset); spine_row.pack(anchor="w", pady=(4, 0))
    ttk.Label(spine_row, text="Spine compensation target:").pack(side="left")
    spine_comp_label = tk.StringVar(value="Spine2 (widens Spine+Spine1)")
    _SPINE_LABEL2KEY = {
        "Spine2 (widens Spine+Spine1)": "spine2",
        "Spine1 (widens Spine only)": "spine1",
        "Both (Spine1 + Spine2)": "both",
        "Auto (immediate child)": "auto",
    }
    ttk.Combobox(spine_row, textvariable=spine_comp_label, width=26, state="readonly",
                 values=list(_SPINE_LABEL2KEY.keys())).pack(side="left", padx=(6, 0))
    ttk.Label(spine_row, foreground="#666",
              text="(only affects Spine targets with Child on)").pack(side="left", padx=(8, 0))

    # ---------- BOTTOM (pinned): run / log / options ----------
    run_btns = ttk.Frame(main)
    run_btns.pack(side="bottom", fill="x", pady=(PAD, 0))
    ttk.Button(run_btns, text="Preview", command=lambda: do_run(True)).pack(side="left")
    ttk.Button(run_btns, text="Bake + Save", command=lambda: do_run(False)).pack(side="left", padx=6)
    ttk.Label(run_btns, text="Transforms are in bone-local space · child-comp suits 1:1 chains (legs)").pack(side="right")

    log_frame = ttk.LabelFrame(main, text="Log", padding=4)
    log_frame.pack(side="bottom", fill="x")
    log_text = tk.Text(log_frame, height=7, wrap="word")
    log_text.pack(side="left", fill="both", expand=True)
    lsb = ttk.Scrollbar(log_frame, command=log_text.yview); lsb.pack(side="right", fill="y")
    log_text.configure(yscrollcommand=lsb.set)

    opt = ttk.Frame(main)
    opt.pack(side="bottom", fill="x", pady=(PAD, 0))
    hier_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(opt, text="Bone-hierarchy propagation (Blender-style, parent\u2192child)",
                    variable=hier_var).pack(side="left")
    norm_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(opt, text="Recompute normals/tangents", variable=norm_var).pack(side="left", padx=(16, 0))
    ttk.Label(opt, text="Compression").pack(side="left", padx=(16, 4))
    packer_var = tk.StringVar(value="original")
    ttk.Combobox(opt, textvariable=packer_var, width=10,
                 values=["original", "lz4", "lzma", "none"], state="readonly").pack(side="left")

    # ---------- MIDDLE (expands): bones + poses ----------
    mid = ttk.Frame(main)
    mid.pack(side="top", fill="both", expand=True, pady=PAD)

    bones_frame = ttk.LabelFrame(mid, text="Bones (by influence, checked meshes)", padding=PAD)
    bones_frame.pack(side="left", fill="y")
    tree = ttk.Treeview(bones_frame, columns=("mesh", "bone", "infl"), show="headings", height=12)
    for c, w, txt in (("mesh", 70, "Mesh"), ("bone", 160, "Bone"), ("infl", 60, "Influence")):
        tree.heading(c, text=txt); tree.column(c, width=w, anchor="w")
    tree.pack(side="left", fill="both", expand=True)
    sb = ttk.Scrollbar(bones_frame, orient="vertical", command=tree.yview); sb.pack(side="right", fill="y")
    tree.configure(yscrollcommand=sb.set)

    pose_frame = ttk.LabelFrame(mid, text="Pose (bone-local transform)", padding=PAD)
    pose_frame.pack(side="right", fill="both", expand=True, padx=(PAD, 0))
    pose_canvas = tk.Canvas(pose_frame, highlightthickness=0, width=640)
    pose_inner = ttk.Frame(pose_canvas)
    psb = ttk.Scrollbar(pose_frame, orient="vertical", command=pose_canvas.yview)
    psb_h = ttk.Scrollbar(pose_frame, orient="horizontal", command=pose_canvas.xview)
    pose_canvas.configure(yscrollcommand=psb.set, xscrollcommand=psb_h.set)
    pose_canvas.grid(row=0, column=0, sticky="nsew")
    psb.grid(row=0, column=1, sticky="ns")
    psb_h.grid(row=1, column=0, sticky="ew")
    pose_frame.rowconfigure(0, weight=1)
    pose_frame.columnconfigure(0, weight=1)
    pose_canvas.create_window((0, 0), window=pose_inner, anchor="nw")
    pose_inner.bind("<Configure>", lambda e: pose_canvas.configure(scrollregion=pose_canvas.bbox("all")))

    # 헤더와 모든 행을 같은 grid·동일 컬럼(minsize)로 → 정확히 정렬. 폭 부족 시 가로 스크롤.
    COLW = [120, 52, 52, 52, 50, 50, 50, 50, 50, 50, 56, 30]
    for c, wd in enumerate(COLW):
        pose_inner.columnconfigure(c, minsize=wd, weight=0)

    def build_pose_header():
        ttk.Label(pose_inner, text="Bone").grid(row=0, column=0, sticky="w", padx=2, pady=(0, 2))
        ttk.Label(pose_inner, text="Scale (X Y Z)", anchor="center").grid(row=0, column=1, columnspan=3, sticky="ew", pady=(0, 2))
        ttk.Label(pose_inner, text="Rotate\u00b0 (X Y Z)", anchor="center").grid(row=0, column=4, columnspan=3, sticky="ew", pady=(0, 2))
        ttk.Label(pose_inner, text="Move (X Y Z)", anchor="center").grid(row=0, column=7, columnspan=3, sticky="ew", pady=(0, 2))
        ttk.Label(pose_inner, text="Child", anchor="center").grid(row=0, column=10, sticky="ew", pady=(0, 2))

    def regrid_rows():
        for i, row in enumerate(target_rows):
            r = i + 1
            row["w_bone"].grid(row=r, column=0, sticky="ew", padx=2, pady=1)
            for k in range(3):
                row["w_s"][k].grid(row=r, column=1 + k, sticky="ew", padx=1, pady=1)
                row["w_r"][k].grid(row=r, column=4 + k, sticky="ew", padx=1, pady=1)
                row["w_t"][k].grid(row=r, column=7 + k, sticky="ew", padx=1, pady=1)
            row["w_comp"].grid(row=r, column=10)
            row["w_del"].grid(row=r, column=11, padx=(2, 0))
        pose_canvas.configure(scrollregion=pose_canvas.bbox("all"))

    def remove_row(row):
        for w in ([row["w_bone"], row["w_comp"], row["w_del"]] + row["w_s"] + row["w_r"] + row["w_t"]):
            w.destroy()
        target_rows.remove(row)
        regrid_rows()

    def add_target_row(bone=""):
        bv = tk.StringVar(value=bone)
        w_bone = ttk.Entry(pose_inner, textvariable=bv, width=14)
        sv = [tk.StringVar(value="1") for _ in range(3)]
        rv = [tk.StringVar(value="0") for _ in range(3)]
        tv = [tk.StringVar(value="0") for _ in range(3)]
        w_s = [ttk.Entry(pose_inner, textvariable=v, width=5) for v in sv]
        w_r = [ttk.Entry(pose_inner, textvariable=v, width=5) for v in rv]
        w_t = [ttk.Entry(pose_inner, textvariable=v, width=5) for v in tv]
        cv = tk.BooleanVar(value=default_compensate(bone.strip()))
        w_comp = ttk.Checkbutton(pose_inner, variable=cv)
        row = {"bone": bv, "s": sv, "r": rv, "t": tv, "comp": cv,
               "w_bone": w_bone, "w_s": w_s, "w_r": w_r, "w_t": w_t, "w_comp": w_comp}
        row["w_del"] = ttk.Button(pose_inner, text="\u2715", width=2, command=lambda: remove_row(row))
        target_rows.append(row)
        regrid_rows()

    def add_selected():
        sel = tree.selection()
        if not sel:
            add_target_row(); return
        for s in sel:
            add_target_row(bone=tree.item(s, "values")[1])

    pb = ttk.Frame(pose_frame); pb.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    ttk.Button(pb, text="Add selected bone", command=lambda: add_selected()).pack(side="left")
    ttk.Button(pb, text="Add empty row", command=lambda: add_target_row()).pack(side="left", padx=4)

    # ---------- logic ----------
    def log(msg=""):
        log_text.insert("end", str(msg) + "\n"); log_text.see("end"); root.update_idletasks()

    def apply_thigh_preset(src_state, dst_state):
        f = thigh_factor(src_state, dst_state)
        for r in list(target_rows):
            if r["bone"].get().strip() in THIGH_BONES:
                remove_row(r)
        for bone in THIGH_BONES:
            add_target_row(bone=bone)
            row = target_rows[-1]
            for k in range(3):
                row["s"][k].set(f"{round(f[k], 6)}")
            row["comp"].set(True)
        log(f"Thigh preset: {src_state} -> {dst_state}  factor(Y,Z)=({round(f[1],5)}, {round(f[2],5)}) "
            f"· both UpLeg · child-comp ON")
        log("  -> click 'Preview' or 'Bake + Save'.")

    def render_mesh_checks():
        for w in mesh_checks.winfo_children():
            w.destroy()
        col = 0
        for mi in state["all_meshes"]:
            hidden = mi.name in DEFAULT_HIDDEN
            if hidden and not show_hidden.get():
                continue
            if mi.name not in mesh_vars:
                mesh_vars[mi.name] = {"var": tk.BooleanVar(value=mi.skinned and not hidden), "info": mi}
            v = mesh_vars[mi.name]["var"]
            label = f"{mi.name}  (verts {mi.vc}, bones {mi.bind_count})"
            if not mi.skinned:
                label += "  ·no skin"
            ttk.Checkbutton(mesh_checks, text=label, variable=v, command=refresh_bone_tree,
                            state=("disabled" if not mi.skinned else "normal")
                            ).grid(row=col // 2, column=col % 2, sticky="w", padx=4, pady=1)
            col += 1
        refresh_bone_tree()

    def checked_mesh_names():
        return {n for n, d in mesh_vars.items() if d["var"].get() and d["info"].skinned}

    def refresh_bone_tree():
        tree.delete(*tree.get_children())
        if not state["env"]:
            return
        names = checked_mesh_names()
        for mi in state["all_meshes"]:
            if mi.name not in names:
                continue
            bone_names = state["bones"].get(mi.name)
            if bone_names is None:
                bone_names, _ = resolve_bones(state["env"], state["id2obj"], state["tos"],
                                              mi.obj, mi.tree, state["smr"])
                state["bones"][mi.name] = bone_names
            u8 = np.frombuffer(bytearray(mi.tree["m_VertexData"]["m_DataSize"]), np.uint8)
            for idx, name, infl in bone_table(bone_names, mi.tree, u8):
                if infl > 0.01:
                    tree.insert("", "end", values=(mi.name, name, f"{infl:.1f}"))

    def scan():
        path = in_var.get().strip()
        if mode.get() == "dir":
            files = sorted(Path(path).glob("*.unity"))
            if not files:
                messagebox.showwarning("Scan", "No .unity files in the folder."); return
            path = str(files[0]); log(f"Scanning first file in folder: {Path(path).name}")
        if not path or not os.path.exists(path):
            messagebox.showwarning("Scan", "Check the input path."); return
        try:
            env = UnityPy.load(path)
            id2obj = build_id_map(env)
            state.update(env=env, tos=build_bone_name_map(env), id2obj=id2obj,
                         smr=smr_bone_pids(env, id2obj),
                         all_meshes=list_meshes(env), bones={}, src=path)
            mesh_vars.clear()
            render_mesh_checks()
            sk = sum(1 for m in state["all_meshes"] if m.skinned)
            log(f"Scan done: {len(state['all_meshes'])} meshes ({sk} skinned)")
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))

    def collect_targets():
        out = []
        for r in target_rows:
            bone = r["bone"].get().strip()
            if not bone:
                continue
            try:
                s = tuple(float(v.get() or 1) for v in r["s"])
                rr = tuple(float(v.get() or 0) for v in r["r"])
                t = tuple(float(v.get() or 0) for v in r["t"])
            except ValueError:
                raise ValueError(f"Check the numbers for bone '{bone}'.")
            out.append(Target(bone, translate=t, rotate=rr, scale=s, compensate=r["comp"].get()))
        return out

    def do_run(dry):
        try:
            targets = collect_targets()
        except ValueError as e:
            messagebox.showerror("Input error", str(e)); return
        if not targets:
            messagebox.showwarning("No pose", "Add at least one pose."); return
        apply_spine_comp(targets, _SPINE_LABEL2KEY.get(spine_comp_label.get(), "spine2"))
        inp, outp = in_var.get().strip(), out_var.get().strip()
        if not inp:
            messagebox.showwarning("Path", "Set the input path."); return
        mf = checked_mesh_names() if mesh_vars else None
        if mesh_vars and not mf:
            messagebox.showwarning("Meshes", "Check at least one mesh to process."); return
        log("=" * 62)
        for m in target_notes(targets):
            log(m)
        try:
            if mode.get() == "dir":
                if not outp:
                    messagebox.showwarning("Path", "Set the output folder."); return
                process_folder(inp, outp, targets, suffix=suffix_var.get(),
                               recompute_normals=norm_var.get(), packer=packer_var.get(),
                               mesh_filter=mf, hierarchical=hier_var.get(), log=log, dry_run=dry)
            else:
                if not outp:
                    outp = str(Path(inp).with_name(Path(inp).stem + suffix_var.get() + Path(inp).suffix))
                    out_var.set(outp)
                log(f"• {Path(inp).name} -> {Path(outp).name}")
                process_bundle(inp, outp, targets, recompute_normals=norm_var.get(),
                               packer=packer_var.get(), mesh_filter=mf,
                               hierarchical=hier_var.get(), log=log, dry_run=dry)
            log("Preview done." if dry else "Done.")
        except Exception as e:
            log(f"! error: {e}"); messagebox.showerror("Failed", str(e))

    build_pose_header()
    log("Select an input bundle -> 'Scan' -> check meshes -> select a bone and 'Add selected bone' "
        "-> set values / child-comp -> 'Bake + Save'.")
    root.mainloop()


# ==========================================================================
# 9. 진입점
# ==========================================================================
def has_display_gui():
    if is_termux():
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return False
    try:
        import tkinter  # noqa
        return True
    except Exception:
        return False


def main():
    args = build_parser().parse_args()
    if args.menu:
        return run_menu()
    if args.gui:
        return run_gui()
    if args.list_bones or args.target or getattr(args, "thigh", None) or args.in_dir or args.infile:
        return run_cli(args)
    return run_gui() if has_display_gui() else run_menu()


if __name__ == "__main__":
    sys.exit(main() or 0)
