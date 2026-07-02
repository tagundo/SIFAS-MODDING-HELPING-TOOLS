#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS Costume Transplant — cross-character outfit swap
======================================================
Takes the *outfit* (body mesh + body textures + costume-specific bones) from a
DONOR character model bundle and grafts it onto a TARGET character model bundle,
while keeping the TARGET's identity (face mesh, hair mesh, head texture, body
skeleton/proportions). The result is "the target character wearing the donor's
costume".

Why this works for SIFAS models
-------------------------------
Every SIFAS `chXXXX_coYYYY_member` model packs the whole character in one bundle:

    Body  SkinnedMeshRenderer : body + clothing geometry  -> ch_co_body texture
    Hair  SkinnedMeshRenderer : hairstyle                 -> identity
    Face  SkinnedMeshRenderer : face                      -> ch_co_head texture

The costume IS the Body mesh + the `*_body` material/textures. The body skeleton
is a shared base rig (Hips...Skirt) that is byte-for-byte the same bone names and
order across characters, except a costume may add a few *appendage* dynamic bones
(a sailor collar `SailorA_*`, a cape, ribbons...). Those extra bones do not exist
in the target rig.

Instead of creating brand-new bone GameObjects in the target (fragile), every
costume-specific donor bone is re-bound to the nearest ancestor bone that DOES
exist in the target (its dynamic-bone parent, e.g. `Spine2`), and its bind pose
is replaced with that ancestor's bind pose. Geometrically:

    at rest:  bone.localToWorld * bindpose == renderer.localToWorld   (identity map)

so copying the ancestor's bind pose into the appendage slots keeps every costume
vertex exactly where it was modelled; the appendage just moves rigidly with that
ancestor instead of having its own jiggle physics. Nothing in the file dangles.

What is transplanted
--------------------
    * Body mesh (geometry, skin weights, bind poses, index buffer)  donor -> target
    * Body SkinnedMeshRenderer bone list + bounds                    donor -> target
    * `*_body` and `*_body_rim` textures (raw, lossless byte copy)   donor -> target

What is kept (target identity)
------------------------------
    * Face mesh, Hair mesh and their bones
    * `*_head` / `*_head_rim` textures and head material
    * AssetBundle name + container path (so it still installs as the TARGET costume)

Limitations
-----------
    * Costume appendage bones lose independent physics (they follow their anchor
      bone rigidly). Placement is exact; only the sway is gone.
    * Body proportions stay the target's; a wildly different donor silhouette may
      clip. SIFAS base bodies are close enough that this is rarely visible.
    * Verified on Unity 2018.4 uncompressed SIFAS model bundles. Compressed meshes
      are not handled.

Masked / board-face models (e.g. Tennoji Rina's "Rina-chan board", ch9999_co0035)
---------------------------------------------------------------------------------
A few members do not use the standard "Body + Hair + Face" 3-renderer layout: the
face is a screen made of dozens of *static* MeshRenderer parts (eye_*/mouth_*/Mask/
HeadSet_*) hung off an accessory head hierarchy (Head -> Head_All -> Head_Face) and
driven by MemberFace / BodyPartManager. The whole mask is parented under the body
`Head` bone, and the body-shape bones ship already at their LiveCoreMemberNodeScaling
`scaledValue` (Head localScale ~1.077). Realigning `Head` to the donor and re-anchoring
node-scaling against the usual `bone == originValue` invariant would warp the mask and
double-apply the body shape, which makes the model fail to load in-game. When such a
target is detected (or `--mask-handling on`), the head accessory-anchor bone is left
out of the realign and its node-scaling is kept intact. Use `--mask-handling off` to
force the plain behaviour.

Usage
-----
    # graphical interface (run with no arguments, or --gui):
    python3 costume_transplant.py

    # command line:
    python3 costume_transplant.py --donor YOU.unity --target MAKI.unity --out OUT.unity \
            [--physics] [--no-collision] [--no-realign] [--no-textures]

`--no-textures` grafts the costume mesh + bones but leaves the wearer's own body
textures/material in place (off by default; handy if you'll paint your own texture).

On a desktop with tkinter the GUI opens automatically; on Termux/headless it
falls back to the CLI. The output replaces the target's model file 1:1 (same
bundle/container name), so you can either swap it in directly or feed it to
unity_costumemod_packer.py to build an installable mod package.
"""

import os
import re
import sys
import copy
import argparse
import importlib
import subprocess

# --- self-contained multi-language support (English default; 한국어 / 日本語) ---
# Translations are embedded so this single file works on its own; the chosen
# language is remembered/shared via ~/.config/sifas_modding_tools/config.json.
import json as _json


# SwingColliderId enum from the SIFAS 3.12.0 decompile: colliderIds entries are a
# STABLE body-region identity, not a positional index into the manager's collider
# list. Mapping the owning body-bone name -> this value is order-independent and
# matches what the engine actually reads.
SWING_COLLIDER_ID = {
    "Hips": 1, "LeftUpLeg": 2, "LeftLeg": 3, "LeftFoot": 4,
    "RightUpLeg": 5, "RightLeg": 6, "RightFoot": 7, "Spine1": 8, "Spine2": 9,
    "LeftShoulder": 10, "LeftArm": 11, "LeftForeArm": 12, "LeftHand": 13,
    "Neck": 14, "RightShoulder": 15, "RightArm": 16, "RightForeArm": 17,
    "RightHand": 18,
}

# Runtime mesh-combine hard limits the engine enforces in MergeAndCombineBodyMesh
# (SIFAS 3.12.0 decompile). A transplant can load fine in Blender/AssetStudio yet
# fail CombineBody in-game if it blows past these.
COMBINE_BONE_MAX = 256      # bones in one combined SkinnedMeshRenderer
COMBINE_SKIN_MAX = 8        # bone influences per vertex
COMBINE_SAFE_SCALE = (0.2, 2.5)  # body-shape scale clamp range


def _collider_id_for_bone(bone, fallback_index):
    """colliderIds value for a collider sitting on `bone`. Uses the engine's
    SwingColliderId enum when the bone is a known body region, else falls back to
    the old 1-based manager index (no regression for unrecognised bones)."""
    return SWING_COLLIDER_ID.get(bone, fallback_index + 1)


def check_combine_limits(path, verbose=True):
    """Warn (never modifies) if the written bundle exceeds the runtime mesh-combine
    limits. Read-only sanity pass; safe to run on any output bundle."""
    def log(*a):
        if verbose:
            print(*a)
    try:
        env = UnityPy.load(path)
    except Exception as e:
        log(f"[limits] skipped ({e})")
        return True
    ok = True
    for o in env.objects:
        if o.type.name != "SkinnedMeshRenderer":
            continue
        t = o.read_typetree()
        nbones = len(t.get("m_Bones", []))
        if nbones > COMBINE_BONE_MAX:
            ok = False
            log(f"[limits] WARNING: SkinnedMeshRenderer has {nbones} bones "
                f"(> {COMBINE_BONE_MAX}); CombineBody may fail in-game. Reduce the "
                f"merged bone count (e.g. drop unused costume-appendage bones).")
    if ok and verbose:
        log(f"[limits] OK: bone counts within the {COMBINE_BONE_MAX}-bone combine limit "
            f"(note: per-vertex influences must stay <= {COMBINE_SKIN_MAX} and body "
            f"scale within {COMBINE_SAFE_SCALE[0]}-{COMBINE_SAFE_SCALE[1]}, which the "
            f"engine trims/clamps silently).")
    return ok


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
        "SIFAS Costume Transplant": "SIFAS 코스튬 이식",
        "Donor  (costume source)": "공여 (코스튬 원본)",
        "Target (wearer / identity)": "대상 (착용자 / 정체성)",
        "Output bundle": "출력 번들",
        "Browse…": "찾아보기…",
        "Options": "옵션",
        "Preserve appendage jiggle physics (collar / tie / wings)": "부속물 흔들림 물리 유지 (옷깃 / 넥타이 / 날개)",
        "Restore body collision for those bones": "해당 본의 바디 콜리전 복원",
        "Realign body bones to the costume's rest pose (fixes offset ribbon/skirt)":
            "바디 본을 코스튬의 기본 포즈에 재정렬 (어긋난 리본/치마 보정)",
        "World-space the body mesh (so swinging ribbon/skirt render correctly)":
            "바디 메시를 월드 공간으로 (흔들리는 리본/치마가 올바르게 렌더링되도록)",
        "Re-anchor NodeScaling to realigned bones (keeps body shaping; stops the in-game ribbon dropping to the chest)":
            "재정렬된 본에 NodeScaling 재고정 (체형 유지; 게임 내 리본이 가슴으로 처지는 현상 방지)",
        "Use the donor's swing physics for shared costume parts (skirt / ribbon) — the bust always stays the wearer's":
            "공유 코스튬 부위(치마 / 리본)에 공여의 스윙 물리 사용 — 가슴은 항상 착용자 것 유지",
        "Special handling for masked / board-face models (Rina-chan board): auto-detect, protect head + body-shape scaling":
            "마스크 / 보드 얼굴 모델(리나쨩 보드) 특수 처리: 자동 감지, 머리 + 체형 스케일링 보호",
        "Transplant without the body textures (keep the wearer's own texture; only the costume mesh + bones are grafted)":
            "바디 텍스처 없이 이식 (착용자의 텍스처 유지; 코스튬 메시 + 본만 이식)",
        "Scale swing physics to a body-scaled target (keeps skirt/ribbon/wing/tail proportions on the Rina board; no-op on normal targets)":
            "체형 스케일된 대상에 스윙 물리 스케일 (리나 보드에서 치마/리본/날개/꼬리 비율 유지; 일반 대상엔 영향 없음)",
        "Transplant": "이식",
        "Save output bundle": "출력 번들 저장",
        "Select bundle": "번들 선택",
        "[error] choose donor, target and output first.\n": "[오류] 먼저 공여·대상·출력을 선택하세요.\n",
        "\n[success] done — verified ✓\n": "\n[성공] 완료 — 검증됨 ✓\n",
        "\n[error] output has dangling references!\n": "\n[오류] 출력에 끊긴 참조가 있습니다!\n",
        "standard model — no special handling needed": "표준 모델 — 특수 처리 불필요",
    },
    "ja": {
        "Language": "言語",
        "SIFAS Costume Transplant": "SIFAS 衣装移植",
        "Donor  (costume source)": "提供元（衣装ソース）",
        "Target (wearer / identity)": "対象（着用者 / アイデンティティ）",
        "Output bundle": "出力バンドル",
        "Browse…": "参照…",
        "Options": "オプション",
        "Preserve appendage jiggle physics (collar / tie / wings)": "付属物のジグル物理を保持（襟 / タイ / 翼）",
        "Restore body collision for those bones": "該当ボーンのボディコリジョンを復元",
        "Realign body bones to the costume's rest pose (fixes offset ribbon/skirt)":
            "ボディボーンを衣装の基本ポーズに再整列（ずれたリボン/スカートを補正）",
        "World-space the body mesh (so swinging ribbon/skirt render correctly)":
            "ボディメッシュをワールド空間に（揺れるリボン/スカートが正しく描画されるよう）",
        "Re-anchor NodeScaling to realigned bones (keeps body shaping; stops the in-game ribbon dropping to the chest)":
            "再整列したボーンにNodeScalingを再アンカー（体型を維持; ゲーム内でリボンが胸に落ちるのを防止）",
        "Use the donor's swing physics for shared costume parts (skirt / ribbon) — the bust always stays the wearer's":
            "共有衣装パーツ（スカート / リボン）に提供元のスイング物理を使用 — バストは常に着用者のもの",
        "Special handling for masked / board-face models (Rina-chan board): auto-detect, protect head + body-shape scaling":
            "マスク / ボードフェイスモデル（りなちゃんボード）の特別処理: 自動検出、頭部 + 体型スケーリングを保護",
        "Transplant without the body textures (keep the wearer's own texture; only the costume mesh + bones are grafted)":
            "ボディテクスチャなしで移植（着用者のテクスチャを保持; 衣装メッシュ + ボーンのみ移植）",
        "Scale swing physics to a body-scaled target (keeps skirt/ribbon/wing/tail proportions on the Rina board; no-op on normal targets)":
            "ボディスケールされた対象にスイング物理をスケール（りなボードでスカート/リボン/翼/尻尾の比率を維持; 通常対象では無効）",
        "Transplant": "移植",
        "Save output bundle": "出力バンドルを保存",
        "Select bundle": "バンドルを選択",
        "[error] choose donor, target and output first.\n": "[エラー] 先に提供元・対象・出力を選択してください。\n",
        "\n[success] done — verified ✓\n": "\n[成功] 完了 — 検証済み ✓\n",
        "\n[error] output has dangling references!\n": "\n[エラー] 出力に未解決の参照があります！\n",
        "standard model — no special handling needed": "標準モデル — 特別な処理は不要",
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
        except Exception:  # noqa: BLE001
            pass
    return _LANG


def _lang_opts():
    return [tuple(x) for x in _LANG_NAMES]


def _tr(text, **kw):
    s = _TRANSLATIONS.get(_LANG, {}).get(text, text)
    return s.format(**kw) if kw else s


# --------------------------------------------------------------------------
# dependency bootstrap (mirrors sifas_mesh_baker.py so Termux works too)
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
    try:
        return importlib.import_module(import_name)
    except ImportError:
        print(f"[setup] could not install '{pip_name}'. Install it manually and re-run.")
        if is_termux():
            print("    pkg install -y python-pillow")
            print("    pip install UnityPy --break-system-packages")
        else:
            print(f"    pip install {pip_name}")
        sys.exit(1)


if is_termux():
    ensure_module("PIL", "Pillow")
UnityPy = ensure_module("UnityPy")
np = ensure_module("numpy")


# --------------------------------------------------------------------------
# world-space normalization (so SwingBone physics — ribbon/skirt — renders
# correctly; a costume mesh left in the donor's local space makes the *swinging*
# verts shift by the mesh-root offset at runtime). Same baking as
# fix_sifas_bundle_export.py, run on the written output (re-read avoids the
# save_typetree staleness from the graft).
# --------------------------------------------------------------------------
_FMT_BYTES = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}


def _stream_layout(tree):
    vd = tree["m_VertexData"]; vc = vd["m_VertexCount"]; chans = vd["m_Channels"]
    by = {}
    for ch in chans:
        if ch.get("dimension", 0):
            by.setdefault(ch["stream"], []).append(ch)
    stride, start, cur = {}, {}, 0
    for s in sorted(by):
        stride[s] = max(c["offset"] + c["dimension"] * _FMT_BYTES[c["format"]] for c in by[s])
    for s in sorted(by):
        start[s] = cur
        cur = (cur + vc * stride[s] + 15) & ~15
    return vc, chans, stride, start


def _read_f(u8, chans, attr, stride, start, vc):
    ch = chans[attr]
    if ch.get("dimension", 0) == 0 or ch["format"] != 0:
        return None
    s, off, dim = ch["stream"], ch["offset"], ch["dimension"]
    blk = u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])
    return blk[:, off:off + dim * 4].copy().view("<f4").reshape(vc, dim).astype(np.float64)


def _write_f(u8, arr, chans, attr, stride, start, vc):
    ch = chans[attr]; s, off, dim = ch["stream"], ch["offset"], ch["dimension"]
    blk = u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])
    blk[:, off:off + dim * 4] = np.ascontiguousarray(arr[:, :dim], "<f4").view(np.uint8).reshape(vc, dim * 4)


def _qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 0],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x), 0],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y), 0],
                     [0, 0, 0, 1]], float)


def _trsmat(t, q, s):
    M = _qmat(q); M[:3, 0] *= s[0]; M[:3, 1] *= s[1]; M[:3, 2] *= s[2]
    M[0, 3], M[1, 3], M[2, 3] = t
    return M


def _bp_mat(b):
    return np.array([[b['e00'], b['e01'], b['e02'], b['e03']], [b['e10'], b['e11'], b['e12'], b['e13']],
                     [b['e20'], b['e21'], b['e22'], b['e23']], [b['e30'], b['e31'], b['e32'], b['e33']]], float)


def _mat_bp(M, dst):
    for r in range(4):
        for c in range(4):
            dst["e%d%d" % (r, c)] = float(M[r, c])


def worldspace_normalize(path, verbose=True, body_only=False):
    """Bake each skinned mesh's mesh-root transform into its vertices and fold the
    inverse into the bind poses, so meshRoot == I (world space). In-game render is
    unchanged, but SwingBone-driven pieces (ribbon/skirt) no longer shift.

    body_only restricts the bake to the body (costume) renderer and leaves the head
    meshes (Face/Hair/EyeBrow) untouched. NOTE: this was an earlier, INCOMPLETE attempt
    at board-face handling. Baking the body alone still desyncs it from a board's
    offset-space head/expression meshes and hangs the load in-game, so board-face targets
    now skip this bake ENTIRELY in transplant() and never pass body_only. The flag is kept
    only for completeness; on a standard model meshRoot is ~identity so the bake no-ops on
    the head meshes anyway (see the per-mesh identity skip below)."""
    def log(*a):
        if verbose:
            print(*a)
    env = UnityPy.load(path)
    uid = {o.path_id: o for o in env.objects}
    # body renderer (most bones) — the only mesh we touch when body_only is set
    body_pid = None
    if body_only:
        best = -1
        for o in env.objects:
            if o.type.name == "SkinnedMeshRenderer":
                nb = len(o.read_typetree().get("m_Bones", []))
                if nb > best:
                    best, body_pid = nb, o.path_id
    tf = {}
    for o in env.objects:
        if o.type.name == "Transform":
            t = o.read_typetree(); g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
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
        smr = o.read_typetree()
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
            g = uid.get(x.read_typetree().get("m_GameObject", {}).get("m_PathID"))
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
        vc, chans, stride, start = _stream_layout(tree)
        buf = bytearray(tree["m_VertexData"]["m_DataSize"]); u8 = np.frombuffer(buf, np.uint8)
        pos = _read_f(u8, chans, 0, stride, start, vc)
        if pos is None:
            continue
        _write_f(u8, (np.c_[pos, np.ones(len(pos))] @ mr.T)[:, :3], chans, 0, stride, start, vc)
        if np.abs(R - np.eye(3)).max() > 1e-6:
            for attr in (1, 2):
                a = _read_f(u8, chans, attr, stride, start, vc)
                if a is not None:
                    a2 = a.copy(); a2[:, :3] = a[:, :3] @ R.T
                    _write_f(u8, a2, chans, attr, stride, start, vc)
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




# --------------------------------------------------------------------------
# LiveCoreMemberNodeScaling consistency
# --------------------------------------------------------------------------
# `LiveCoreMemberNodeScaling` (LLAS.Scene.Live.Components) overrides selected
# bones' local position / scale with a per-character body-shape `scaledValue`
# when the member spawns in a live, and stores `originValue` = the bone's
# *shipped* (unscaled) local value. The healthy invariant is therefore
#
#       bone.localPosition == positionValue.originValue
#       bone.localScale    == scaleValue.originValue
#
# Realigning the shared body bones to the donor's rest pose (apply_bone_edits)
# moves some of those bones, which breaks the invariant: at runtime the
# component then forces `scaledValue` and *teleports* the bone — e.g. it drags
# `Breast_Offset` (parent of the ribbon bones) down to the chest.
#
# We must NOT just zero the override — that throws away the character's body
# shaping. Instead we *re-anchor* it: keep the correction the entry encoded
# (the position delta `scaled - origin`, or the scale ratio `scaled / origin`)
# and rebuild it around the bone's new local value, so the same body-shape
# adjustment is reapplied on top of the costume's rest pose.
# --------------------------------------------------------------------------
def _is_node_scaling(mb):
    return "targetName" in mb and "scaleValues" in mb and "positionValues" in mb


def rebase_node_scaling(path, eps=1e-4, verbose=True):
    """Re-anchor every NodeScaling entry whose originValue drifted from its bone
    after a realign, preserving the body-shape correction. Runs on the written
    output (re-read avoids save_typetree staleness)."""
    def log(*a):
        if verbose:
            print(*a)

    env = UnityPy.load(path)
    objs = list(env.objects)
    uid = {o.path_id: o for o in objs}
    go = {o.path_id: o.read_typetree().get("m_Name") for o in objs if o.type.name == "GameObject"}

    def bone(pid):
        o = uid.get(pid)
        if not o or o.type.name != "Transform":
            return None, None
        t = o.read_typetree()
        return t, go.get(t.get("m_GameObject", {}).get("m_PathID"))

    total = 0
    skipped_total = 0
    rot_warn_total = 0
    for o in objs:
        if o.type.name != "MonoBehaviour":
            continue
        mb = o.read_typetree()
        if not _is_node_scaling(mb):
            continue
        changed = 0
        for pv in mb.get("positionValues", []):
            t, bn = bone(pv["target"]["m_PathID"])
            if t is None:
                continue
            lp = t["m_LocalPosition"]; ov = pv["originValue"]; sv = pv["scaledValue"]
            d_origin = max(abs(lp[k] - ov[k]) for k in "xyz")
            if d_origin <= eps:
                continue                       # healthy: bone already at originValue
            if max(abs(lp[k] - sv[k]) for k in "xyz") <= eps:
                # bone already AT scaledValue: this model SHIPS with the body shape
                # baked into the rest pose (e.g. the Rina-chan board), so the entry is
                # already consistent. Re-anchoring here would double-apply the offset.
                skipped_total += 1
                continue
            # additive body-shape offset, re-anchored to the new rest pose
            delta = {k: sv[k] - ov[k] for k in "xyz"}
            pv["originValue"] = {k: lp[k] for k in "xyz"}
            pv["scaledValue"] = {k: lp[k] + delta[k] for k in "xyz"}
            changed += 1
            log(f"   [rebase] POS  {bn}: origin -> {tuple(round(lp[k],4) for k in 'xyz')} "
                f"(kept offset {tuple(round(delta[k],4) for k in 'xyz')})")
        for sv in mb.get("scaleValues", []):
            t, bn = bone(sv["target"]["m_PathID"])
            if t is None:
                continue
            ls = t["m_LocalScale"]; ov = sv["originValue"]; sd = sv["scaledValue"]
            d_origin = max(abs(ls[k] - ov[k]) for k in "xyz")
            if d_origin <= eps:
                continue                       # healthy: bone already at originValue
            if max(abs(ls[k] - sd[k]) for k in "xyz") <= eps:
                # bone already AT scaledValue (model ships body-shape-applied): the
                # entry is already consistent, so re-anchoring would double the scale.
                skipped_total += 1
                continue
            # multiplicative body-shape ratio, re-anchored to the new scale
            ratio = {k: (sd[k] / ov[k] if abs(ov[k]) > 1e-9 else 1.0) for k in "xyz"}
            sv["originValue"] = {k: ls[k] for k in "xyz"}
            sv["scaledValue"] = {k: ls[k] * ratio[k] for k in "xyz"}
            changed += 1
            log(f"   [rebase] SCALE {bn}: origin -> {tuple(round(ls[k],4) for k in 'xyz')} "
                f"(kept ratio {tuple(round(ratio[k],3) for k in 'xyz')})")
        # rotationValues exist on NodeScaling too (verified in the 3.12.0 decompile),
        # but are deliberately NOT auto-rebased: the stored Vector3 is Euler in Unity's
        # ZXY convention and the engine's rotation invariant can't be confirmed from the
        # stripped decompile, so silently rewriting them could warp a working costume.
        # Surface them so they can be checked by hand if a donor actually uses them.
        nrot = len(mb.get("rotationValues", []))
        if nrot:
            rot_warn_total += nrot
        if changed:
            o.save_typetree(mb)
            total += changed
    if total:
        bf = list(env.files.values())[0]; bf.mark_changed()
        with open(path, "wb") as f:
            f.write(bf.save(packer="lz4"))
        log(f"[ok] re-anchored {total} NodeScaling entr{'y' if total == 1 else 'ies'} to the costume rest pose")
    if skipped_total:
        log(f"[mask] kept {skipped_total} NodeScaling entr{'y' if skipped_total == 1 else 'ies'} "
            f"intact (bone already at scaledValue — model ships body-shape-applied)")
    if rot_warn_total:
        log(f"[rot] NOTE: {rot_warn_total} NodeScaling rotationValues entr"
            f"{'y was' if rot_warn_total == 1 else 'ies were'} left un-rebased "
            f"(rotation rebasing is manual — if the costume rotates oddly in-game, "
            f"check these by hand).")
    return total


# --------------------------------------------------------------------------
# bundle helpers
# --------------------------------------------------------------------------
def _index(env):
    objs = list(env.objects)
    return objs, {o.path_id: o for o in objs}


def _go_name(id2, go_pid):
    o = id2.get(go_pid)
    return o.read().m_Name if o else None


def _transform_goname(id2, tpid):
    o = id2.get(tpid)
    if not o:
        return None
    t = o.read_typetree()
    return _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))


def _name2transform(id2):
    m = {}
    for pid, o in id2.items():
        if o.type.name == "Transform":
            n = _transform_goname(id2, pid)
            if n is not None:
                m[n] = pid
    return m


def _transform_parent_byname(id2):
    """child GO name -> parent GO name (via Transform.m_Father)."""
    out = {}
    for pid, o in id2.items():
        if o.type.name != "Transform":
            continue
        t = o.read_typetree()
        cn = _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))
        fp = t.get("m_Father", {}).get("m_PathID")
        pn = _transform_goname(id2, fp) if fp else None
        if cn is not None:
            out[cn] = pn
    return out


def _accumulated_scale_byname(id2):
    """GO name -> accumulated WORLD (uniform) scale: the product of the averaged local
    scale of every Transform from the bone up to the root.

    SIFAS body-shape nodes (Move, Head, *Size) scale ~uniformly, so averaging x/y/z is
    a faithful scalar. This is what lets the tool tell that a board target scales its
    whole body (Move ~0.927) while a head-anchored piece nets back to ~1.0 (Head 1.077
    cancels Move) — the per-bone ratio comes out right for every appendage."""
    tf = {}
    for pid, o in id2.items():
        if o.type.name != "Transform":
            continue
        t = o.read_typetree()
        ls = t.get("m_LocalScale", {}) or {}
        avg = (float(ls.get("x", 1.0)) + float(ls.get("y", 1.0)) + float(ls.get("z", 1.0))) / 3.0
        father = t.get("m_Father", {}).get("m_PathID", 0)
        nm = _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))
        tf[pid] = (avg, father, nm)
    out = {}
    for pid, (avg, father, nm) in tf.items():
        if nm is None:
            continue
        s, cur, guard = 1.0, pid, 0
        while cur in tf and guard < 512:       # guard against a malformed parent cycle
            a, f, _ = tf[cur]
            s *= a
            cur = f
            guard += 1
        out[nm] = s
    return out


def _local_trs_byname(id2):
    """GO name -> (m_LocalPosition, m_LocalRotation, m_LocalScale) dicts."""
    out = {}
    for pid, o in id2.items():
        if o.type.name != "Transform":
            continue
        t = o.read_typetree()
        n = _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))
        if n is not None:
            out[n] = (t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"])
    return out


def apply_bone_edits(donor_id2, target_id2, bone_names, child_adds=None,
                     realign_alias=None, log=lambda *a: None):
    """Apply both kinds of per-bone edit in ONE save_typetree per object.

    1. realign: copy the donor's rest (local) transform onto each bone in
       `bone_names`. A costume's body mesh is authored against the donor's
       skeleton rest pose, so binding it to the wearer's slightly different bone
       positions shifts attached pieces (e.g. the chest ribbon floats high).
       Snapping the shared body bones to the donor's rest pose makes mesh + bind
       poses + bones self-consistent and the costume sits exactly as designed.
       Head/hair/face bones are not in this list, so identity is preserved.
       `realign_alias` {target_name: donor_name} lets a target bone take its rest
       pose from a differently-named donor bone (used for bust-offset aliasing).
    2. child_adds: append injected appendage roots to their parent bone's
       m_Children. Merged here because read_typetree() does not reflect a prior
       save on the same object, so a parent that is also realigned would lose one
       edit if the two were saved separately.
    """
    child_adds = child_adds or {}
    realign_alias = realign_alias or {}
    d_local = _local_trs_byname(donor_id2) if (bone_names or realign_alias) else {}
    realign_set = set(bone_names)
    # target name -> Transform ObjectReader
    t_tf = {}
    for pid, o in target_id2.items():
        if o.type.name == "Transform":
            n = _go_name(target_id2, o.read_typetree().get("m_GameObject", {}).get("m_PathID"))
            if n is not None:
                t_tf[n] = o
    n_re = 0
    for name in (realign_set | set(child_adds)):
        o = t_tf.get(name)
        if o is None:
            continue
        tt = o.read_typetree()
        _src = realign_alias.get(name, name)
        if name in realign_set and _src in d_local:
            lp, lr, ls = d_local[_src]
            tt["m_LocalPosition"] = copy.deepcopy(lp)
            tt["m_LocalRotation"] = copy.deepcopy(lr)
            tt["m_LocalScale"] = copy.deepcopy(ls)
            n_re += 1
        existing = {c["m_PathID"] for c in tt.get("m_Children", [])}
        for cpid in child_adds.get(name, []):
            if cpid not in existing:   # never list a child twice (AssetStudio dup-key)
                tt.setdefault("m_Children", []).append({"m_FileID": 0, "m_PathID": cpid})
                existing.add(cpid)
        o.save_typetree(tt)
    if bone_names:
        log(f"[ok] realigned {n_re} body bone(s) to the costume's rest pose")
    return n_re


def _body_smr(objs):
    """The body SkinnedMeshRenderer: the skinned renderer with the most bones."""
    best = None
    best_n = -1
    for o in objs:
        if o.type.name == "SkinnedMeshRenderer":
            n = len(o.read_typetree().get("m_Bones", []))
            if n > best_n:
                best_n, best = n, o
    return best


def _mesh_by_pid(id2, pid):
    o = id2.get(pid)
    return o, (o.read_typetree() if o else None)


def _mesh_name_pid(objs, name):
    for o in objs:
        if o.type.name == "Mesh" and o.read_typetree().get("m_Name") == name:
            return o
    return None


def _material_textures(id2, mat_pid):
    """body material -> {'main': tex_pid, 'rim': tex_pid} from its _MainTex/_RimlightTex."""
    o = id2.get(mat_pid)
    out = {}
    if not o:
        return out
    sp = o.read_typetree().get("m_SavedProperties", {})
    for name, env in sp.get("m_TexEnvs", []):
        pid = env.get("m_Texture", {}).get("m_PathID", 0)
        if name == "_MainTex" and pid:
            out["main"] = pid
        elif name == "_RimlightTex" and pid:
            out["rim"] = pid
    return out


def _texname(id2, pid):
    o = id2.get(pid)
    return o.read().m_Name if o else None


def _raw_tex(id2, pid):
    o = id2.get(pid)
    return o.read().get_image_data() if o else None


def _chara_costume_id(env):
    """Pull chXXXX_coYYYY from the AssetBundle name."""
    for o in env.objects:
        if o.type.name == "AssetBundle":
            m = re.search(r"(ch\d{4})_(co\d{4})", o.read_typetree().get("m_Name", ""))
            if m:
                return m.group(1), m.group(2)
    return None, None


# --------------------------------------------------------------------------
# special-case detection: masked / "board-face" models (e.g. Rina-chan board)
# --------------------------------------------------------------------------
# A few SIFAS members are not the standard "Body + Hair + Face" 3-renderer model.
# Tennoji Rina's "Rina-chan board" (ch9999_co0035) renders her face as a screen:
# dozens of *static* MeshRenderer parts (eye_*/mouth_*/Mask/HeadSet_*) hang off an
# accessory head hierarchy (Head -> Head_All -> Head_Face) driven by MemberFace /
# BodyPartManager and a second Animator. Two things about such a model break the
# realign / node-scaling passes:
#   1. the whole mask is parented under a *body-skeleton* bone (Head), so realigning
#      that bone to the donor's rest pose drags/rescales the entire mask, and
#   2. the body-shape bones ship already at their LiveCoreMemberNodeScaling
#      `scaledValue` (Head localScale ~1.077, Move 0.927, ...), the opposite of the
#      `bone.local == originValue` invariant rebase_node_scaling expects, so the
#      re-anchor pass would double-apply the body shape.
# detect_board_face_model() spots these so transplant() can take the exceptional path.
def detect_board_face_model(objs, id2):
    """Return None for a standard model, else a dict describing the masked/board model:

        {"kind": "board-face",
         "face_parts": int,          # static face/mask MeshRenderers
         "anchor_bones": set[str],   # body bones carrying the mask subtree (e.g. {"Head"})
         "markers": list[str]}       # which signatures matched
    """
    body = _body_smr(objs)
    if body is None:
        return None

    # skeleton bone names = union of every skinned renderer's bone list, plus the
    # body renderer's bones on their own (so we can tell a real bone child from an
    # accessory child).
    skeleton, body_bones = set(), set()
    for o in objs:
        if o.type.name == "SkinnedMeshRenderer":
            for b in o.read_typetree().get("m_Bones", []):
                n = _transform_goname(id2, b["m_PathID"])
                if n:
                    skeleton.add(n)
    for b in body.read_typetree().get("m_Bones", []):
        n = _transform_goname(id2, b["m_PathID"])
        if n:
            body_bones.add(n)

    # which GameObjects own a MeshRenderer, and the transform graph
    go_with_mr = {o.read_typetree().get("m_GameObject", {}).get("m_PathID")
                  for o in objs if o.type.name == "MeshRenderer"}
    tf_children, tf_goname, tf_gopid, name2tfpid = {}, {}, {}, {}
    for o in objs:
        if o.type.name == "Transform":
            t = o.read_typetree()
            gp = t.get("m_GameObject", {}).get("m_PathID")
            tf_gopid[o.path_id] = gp
            nm = _go_name(id2, gp)
            tf_goname[o.path_id] = nm
            tf_children[o.path_id] = [c["m_PathID"] for c in t.get("m_Children", [])]
            if nm and nm not in name2tfpid:
                name2tfpid[nm] = o.path_id

    def subtree_has_mr(tpid):
        stack, seen = [tpid], set()
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            if tf_gopid.get(p) in go_with_mr:
                return True
            stack.extend(tf_children.get(p, []))
        return False

    # a body bone is an accessory anchor if it has a NON-skeletal child whose subtree
    # contains static mesh parts (the mask / face board)
    anchor_bones = set()
    for bn in body_bones:
        tpid = name2tfpid.get(bn)
        if tpid is None:
            continue
        for cpid in tf_children.get(tpid, []):
            if tf_goname.get(cpid) in skeleton:
                continue
            if subtree_has_mr(cpid):
                anchor_bones.add(bn)
                break

    have = set(_scriptname_map(objs).values())
    face_parts = sum(1 for gp in go_with_mr
                     if not (_go_name(id2, gp) or "").startswith("Shadow"))

    # a board-face model has a body bone carrying mesh accessories AND either the
    # dedicated face component or a meaningful number of static face parts.
    if not anchor_bones or not ("MemberFace" in have or face_parts >= 4):
        return None
    markers = [m for m in ("MemberFace", "BodyPartManager") if m in have]
    markers.append("anchor:" + ",".join(sorted(anchor_bones)))
    return {"kind": "board-face", "face_parts": face_parts,
            "anchor_bones": anchor_bones, "markers": markers}


def detect_board_face_model_path(path):
    """Convenience wrapper: load a bundle and run detect_board_face_model on it."""
    objs, id2 = _index(UnityPy.load(path))
    return detect_board_face_model(objs, id2)


# --------------------------------------------------------------------------
# object injection (used to preserve costume jiggle physics)
# --------------------------------------------------------------------------
def _serialized_file(env):
    bf = list(env.files.values())[0]
    sf = [v for v in bf.files.values() if type(v).__name__ == "SerializedFile"][0]
    return bf, sf


def _scriptname_map(objs):
    return {o.path_id: o.read_typetree().get("m_ClassName")
            for o in objs if o.type.name == "MonoScript"}


def _find_swingbone_manager(objs, scriptnames):
    for o in objs:
        if o.type.name == "MonoBehaviour" and \
                scriptnames.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == "SwingBoneManager":
            return o
    return None


def _manager_colliders(objs, id2, scriptnames):
    """Ordered manager collider list as [(collider_path_id, owning_bone_name), ...].

    A SwingBone references colliders both by PPtr (`colliders`) and by 1-based
    index into this list (`colliderIds`, where 0 means none)."""
    mgr = _find_swingbone_manager(objs, scriptnames)
    out = []
    if not mgr:
        return out
    for c in mgr.read_typetree().get("colliders", []):
        pid = c.get("m_PathID")
        co = id2.get(pid)
        bone = None
        if co:
            bone = _go_name(id2, co.read_typetree().get("m_GameObject", {}).get("m_PathID"))
        out.append((pid, bone))
    return out


def _swingbone_script_pid(objs, scriptnames):
    for pid, n in scriptnames.items():
        if n == "SwingBone":
            return pid
    return None


def _template(objs, cls, scriptnames=None, script_class=None):
    for o in objs:
        if o.type.name != cls:
            continue
        if script_class is None:
            return o
        if scriptnames.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == script_class:
            return o
    return None


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


def _rand_pids(n, used):
    import random
    out = []
    while len(out) < n:
        p = random.randint(10 ** 17, 9 * 10 ** 17)
        if p not in used and p not in out:
            out.append(p)
    return out


def inject_appendage_bones(donor, target, inject_names, name2tf_target,
                           restore_collision=True, log=lambda *a: None):
    """Recreate donor costume-appendage bone chains (GameObject + Transform + their
    SwingBone components) inside the target bundle so the jiggle physics survives.

    With restore_collision, each injected SwingBone's body-collision references are
    remapped from the donor's SwingColliders to the target's equivalent colliders
    (matched by the bone they sit on), so the appendage still collides with the body
    instead of clipping through it.

    Returns ({donor_bone_name: new_target_transform_path_id}, child_adds).
    """
    do, did = _index(donor)
    to, tid = _index(target)
    _, t_sf = _serialized_file(target)

    d_scripts = _scriptname_map(do)
    t_scripts = _scriptname_map(to)

    # collider remap tables (donor collider pid -> bone; target bone -> pid/index) --
    d_cols = _manager_colliders(do, did, d_scripts)
    t_cols = _manager_colliders(to, tid, t_scripts)
    d_colpid_to_bone = {pid: bone for pid, bone in d_cols}
    t_bone_to_colpid = {bone: pid for pid, bone in t_cols if bone}
    t_bone_to_colidx = {bone: i for i, (pid, bone) in enumerate(t_cols) if bone}

    # donor lookups -----------------------------------------------------------
    d_go_by_name, d_tf_by_go, d_tfpid_to_goname = {}, {}, {}
    for o in do:
        if o.type.name == "GameObject":
            d_go_by_name[o.read().m_Name] = o
    for o in do:
        if o.type.name == "Transform":
            t = o.read_typetree()
            gp = t.get("m_GameObject", {}).get("m_PathID")
            d_tf_by_go[gp] = o
            d_tfpid_to_goname[o.path_id] = _go_name(did, gp)
    d_goname_to_pid = {n: g.path_id for n, g in d_go_by_name.items()}
    # SwingBone component(s) keyed by owning GameObject name
    d_swing_by_goname = {}
    for o in do:
        if o.type.name == "MonoBehaviour" and \
                d_scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == "SwingBone":
            t = o.read_typetree()
            gn = _go_name(did, t.get("m_GameObject", {}).get("m_PathID"))
            if gn:
                d_swing_by_goname[gn] = t

    # target infrastructure ---------------------------------------------------
    t_sb_script = _swingbone_script_pid(to, t_scripts)
    t_mgr = _find_swingbone_manager(to, t_scripts)
    go_tmpl = _template(to, "GameObject")
    tf_tmpl = _template(to, "Transform")
    mb_tmpl = _template(to, "MonoBehaviour", t_scripts, "SwingBone")
    if not (t_mgr and go_tmpl and tf_tmpl and mb_tmpl and t_sb_script):
        raise RuntimeError("target lacks SwingBone infrastructure; cannot preserve physics")

    used = set(t_sf.objects.keys())
    # allocate new path ids: GO + TF per bone, MB per swingbone
    inject_names = [n for n in inject_names if n in d_go_by_name]
    go_pid = dict(zip(inject_names, _rand_pids(len(inject_names), used)))
    used |= set(go_pid.values())
    tf_pid = dict(zip(inject_names, _rand_pids(len(inject_names), used)))
    used |= set(tf_pid.values())
    swing_owners = [n for n in inject_names if n in d_swing_by_goname]
    mb_pid = dict(zip(swing_owners, _rand_pids(len(swing_owners), used)))
    used |= set(mb_pid.values())

    def tf_of(name):
        """target transform pid for a bone name: injected -> new, else existing rig."""
        if name in tf_pid:
            return tf_pid[name]
        return name2tf_target.get(name)

    new_swing_pids = []
    d_parent = _transform_parent_byname(did)

    for name in inject_names:
        d_go = d_go_by_name[name]
        d_tf = d_tf_by_go[d_go.path_id]
        d_go_tt = d_go.read_typetree()
        d_tf_tt = d_tf.read_typetree()

        # ---- GameObject ----
        go_tt = copy.deepcopy(d_go_tt)
        comps = [{"component": {"m_FileID": 0, "m_PathID": tf_pid[name]}}]
        if name in mb_pid:
            comps.append({"component": {"m_FileID": 0, "m_PathID": mb_pid[name]}})
        go_tt["m_Component"] = comps
        _make_object(t_sf, go_tmpl, go_pid[name], go_tt)

        # ---- Transform ----
        tf_tt = copy.deepcopy(d_tf_tt)
        tf_tt["m_GameObject"] = {"m_FileID": 0, "m_PathID": go_pid[name]}
        father_name = d_parent.get(name)
        tf_tt["m_Father"] = {"m_FileID": 0, "m_PathID": tf_of(father_name) or 0}
        # children: ONLY other injected appendage bones. Never list a native
        # target bone here — that bone already has its own parent, and claiming
        # it would give it two parents, which makes AssetStudio's model export
        # throw "An item with the same key has already been added".
        children, seen_ch = [], set()
        for c in d_tf_tt.get("m_Children", []):
            cn = d_tfpid_to_goname.get(c["m_PathID"])
            cp = tf_pid.get(cn)
            if cp and cp not in seen_ch:
                children.append({"m_FileID": 0, "m_PathID": cp})
                seen_ch.add(cp)
        tf_tt["m_Children"] = children
        _make_object(t_sf, tf_tmpl, tf_pid[name], tf_tt)

    # ---- SwingBone components ----
    # SwingBones in a chain (e.g. a 4-bone necktie) reference each other by
    # *integer index* into SwingBoneManager.bones (parent/child/siblingIndex,
    # -1 = none). Those indices are donor-relative, so they must be rewritten to
    # the injected bones' new positions in the target manager (appended after the
    # target's existing bones, in swing_owners order). References to a shared bone
    # already present in the target keep that bone's index; anything unresolved
    # becomes -1.
    d_mgr_tt = _find_swingbone_manager(do, d_scripts).read_typetree()
    donor_idx_name = []
    for b in d_mgr_tt.get("bones", []):
        co = did.get(b["m_PathID"])
        donor_idx_name.append(_go_name(did, co.read_typetree().get("m_GameObject", {}).get("m_PathID")) if co else None)
    t_existing_bones = t_mgr.read_typetree().get("bones", [])
    base = len(t_existing_bones)
    target_name_idx = {}
    for i, b in enumerate(t_existing_bones):
        co = tid.get(b["m_PathID"])
        nm = _go_name(tid, co.read_typetree().get("m_GameObject", {}).get("m_PathID")) if co else None
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

    # Base the injected components on a REAL target SwingBone typetree, then
    # overlay the donor's values for shared fields. The donor and target bundles
    # can carry different SwingBone script schemas (e.g. the target adds
    # kneeSpaceOffsetMax); writing the donor tree against the target type would
    # KeyError on the missing field. Starting from the target's own instance
    # guarantees every field the target schema expects is present.
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
        # rewrite the chain indices to the target manager's numbering
        for key in ("parentIndex", "childIndex", "siblingIndex"):
            if key in sb:
                sb[key] = remap_idx(sb[key])
        # body colliders are bundle-specific objects: remap the PPtr to the target's
        # collider on the same bone, and set colliderIds to the engine's
        # SwingColliderId body-region enum (NOT a positional index). Drop refs whose
        # bone is absent.
        new_cols, new_ids = [], []
        if restore_collision:
            for c in donor_sb.get("colliders", []):
                bone = d_colpid_to_bone.get(c.get("m_PathID"))
                if bone in t_bone_to_colpid:
                    new_cols.append({"m_FileID": 0, "m_PathID": t_bone_to_colpid[bone]})
                    new_ids.append(_collider_id_for_bone(bone, t_bone_to_colidx[bone]))
        if "colliders" in sb:
            sb["colliders"] = new_cols
        if "colliderIds" in sb:
            sb["colliderIds"] = new_ids
        _make_object(t_sf, mb_tmpl, mb_pid[name], sb)
        new_swing_pids.append(mb_pid[name])

    # ---- roots to attach to an existing target bone's child list ----
    # Returned (not saved here) so it can be merged with the bone-realign pass:
    # read_typetree does not see a prior save_typetree on the same object, so a
    # parent bone that is ALSO realigned must receive both edits in one save.
    child_adds = {}   # target parent bone name -> [new child transform pids]
    for name in inject_names:
        father_name = d_parent.get(name)
        if father_name in tf_pid:          # parent is itself injected; already wired
            continue
        if name2tf_target.get(father_name) is None:
            continue
        child_adds.setdefault(father_name, []).append(tf_pid[name])

    # ---- register new swing bones with the manager ----
    if new_swing_pids:
        mtt = t_mgr.read_typetree()
        mtt.setdefault("bones", []).extend(
            {"m_FileID": 0, "m_PathID": p} for p in new_swing_pids)
        t_mgr.save_typetree(mtt)

    log(f"[ok] injected {len(inject_names)} bone(s) with {len(new_swing_pids)} swing "
        f"component(s): {', '.join(inject_names)}")
    return {n: tf_pid[n] for n in inject_names}, child_adds


def sync_body_material(donor, target, d_mat_pid, t_mat_pid, log=lambda *a: None):
    """Replace the wearer's body material properties + textures with the costume's.

    Overwriting only the _MainTex/_RimlightTex pixel bytes (the old approach)
    breaks when the costume's textures differ in size/format (the body header and
    payload disagree -> garbled) and silently drops costume-only effects such as a
    matcap (the donor sets _MATCAP=1 with _MatcapTex/_MatcapMaskTex the wearer
    lacks). This copies the donor body material's saved properties (floats/colors)
    and, for every texture slot, writes the donor texture's FULL metadata + pixels:
    reusing the wearer's same-slot texture object where it has one, or injecting a
    brand-new Texture2D (matcap/emissive) where it does not. The wearer's body
    shader is kept (SIFAS bodies share one shader); head textures stay untouched.
    """
    do, did = _index(donor)
    to, tid = _index(target)
    _, t_sf = _serialized_file(target)
    d_mat, t_mat = did.get(d_mat_pid), tid.get(t_mat_pid)
    if not d_mat or not t_mat:
        return
    d_mat_tt, t_mat_tt = d_mat.read_typetree(), t_mat.read_typetree()
    d_tex = {o.path_id: o for o in do if o.type.name == "Texture2D"}
    tex_tmpl = next((o for o in to if o.type.name == "Texture2D"), None)
    used = set(t_sf.objects.keys())
    # texture metadata fields to carry over (everything but name + payload)
    META = ("m_ForcedFallbackFormat", "m_DownscaleFallback", "m_Width", "m_Height",
            "m_CompleteImageSize", "m_TextureFormat", "m_MipCount", "m_IsReadable",
            "m_StreamingMipmaps", "m_StreamingMipmapsPriority", "m_ImageCount",
            "m_TextureDimension", "m_TextureSettings", "m_LightmapFormat", "m_ColorSpace")

    def overwrite_tex(t_obj, d_obj):
        dtt = d_obj.read_typetree()
        ttt = t_obj.read_typetree()
        for k in META:
            if k in dtt:
                ttt[k] = copy.deepcopy(dtt[k])
        ttt["image data"] = d_obj.read().get_image_data()
        ttt["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        t_obj.save_typetree(ttt)

    def inject_tex(d_obj):
        dtt = copy.deepcopy(d_obj.read_typetree())
        dtt["image data"] = d_obj.read().get_image_data()
        dtt["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        npid = _rand_pids(1, used)[0]
        used.add(npid)
        _make_object(t_sf, tex_tmpl, npid, dtt)
        return npid

    # wearer's current texture per material slot (so we reuse its texture objects)
    t_slot_pid = {}
    for pair in t_mat_tt.get("m_SavedProperties", {}).get("m_TexEnvs", []):
        t_slot_pid[pair[0]] = pair[1].get("m_Texture", {}).get("m_PathID", 0)

    sp = copy.deepcopy(d_mat_tt.get("m_SavedProperties", {}))
    injected_by_name = {}
    n_over = n_inj = 0
    for pair in sp.get("m_TexEnvs", []):
        slot, env = pair[0], pair[1]
        tex = env.get("m_Texture", {})
        dpid = tex.get("m_PathID", 0)
        if not dpid or dpid not in d_tex:
            tex["m_PathID"], tex["m_FileID"] = 0, 0   # never leak a donor path id
            continue
        d_obj = d_tex[dpid]
        existing = t_slot_pid.get(slot, 0)
        if existing and existing in tid:
            overwrite_tex(tid[existing], d_obj)
            tpid = existing
            n_over += 1
        else:
            dname = d_obj.read_typetree()["m_Name"]
            if dname in injected_by_name:
                tpid = injected_by_name[dname]
            else:
                tpid = inject_tex(d_obj)
                injected_by_name[dname] = tpid
                n_inj += 1
        tex["m_PathID"], tex["m_FileID"] = tpid, 0
    # carry the donor material's shader KEYWORDS too. Copying only m_SavedProperties
    # drops keyword-gated variants (e.g. _MATCAP), so the injected matcap textures and
    # the _MATCAP float would be present but the variant would never activate in-game.
    # Copy whichever keyword field this Unity version uses (2020: m_ShaderKeywords;
    # 2021+: m_ValidKeywords / m_InvalidKeywords).
    n_kw = 0
    for kw_field in ("m_ShaderKeywords", "m_ValidKeywords", "m_InvalidKeywords"):
        if kw_field in d_mat_tt:
            t_mat_tt[kw_field] = copy.deepcopy(d_mat_tt[kw_field])
            n_kw += 1
    # keep wearer's shader + material name; swap in the costume's properties
    t_mat_tt["m_SavedProperties"] = sp
    t_mat.save_typetree(t_mat_tt)
    log(f"[ok] body material synced: {n_over} texture(s) overwritten, "
        f"{n_inj} injected (matcap/emissive), properties + {n_kw} keyword field(s) copied")


# --------------------------------------------------------------------------
# costume swing-physics ownership (skirt / shared ribbon)
# --------------------------------------------------------------------------
# The skirt — and sometimes a ribbon — is part of the DONOR's costume, but its
# bones share names with the wearer's own skirt (the base skirt rig is identical
# across characters). The bone resolver therefore reuses the wearer's existing
# skirt bones, which still carry the *wearer's old-costume* SwingBone tuning and
# body colliders. realign already snaps those bones to the donor's rest pose (so
# the skirt LENGTH/shape becomes the donor's), but the sway feel + collision stay
# the wearer's, so a long donor skirt may swing like the wearer's short one or
# clip. Since "the outfit is the donor's", the donor should win the physics too.
#
# We do NOT re-create the bones (the chain is identical); we overwrite only the
# SwingBone *tuning* fields + colliders on the shared bone with the donor's, and
# keep the wearer's structural pointers (child/sibling/chain indices) which
# already address the correct shared bones. Body-identity dynamics (the bust) are
# excluded — the wearer keeps its own shape/jiggle.
def _is_body_identity_bone(name):
    """Dynamic bones that belong to the wearer's BODY, not the costume."""
    return name is not None and "Breast" in name


def sync_costume_swing_physics(donor, target, costume_bone_names,
                               restore_collision=True, log=lambda *a: None):
    """Overwrite the wearer's SwingBone tuning + body-collision with the donor's on
    every costume dynamic bone the wearer also has (same name; typically the skirt).
    Structural pointers stay the wearer's. Returns the number of SwingBones updated."""
    do, did = _index(donor)
    to, tid = _index(target)
    d_scripts = _scriptname_map(do)
    t_scripts = _scriptname_map(to)

    def swing_by_name(objs, id2, scripts):
        out = {}
        for o in objs:
            if o.type.name == "MonoBehaviour" and \
                    scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == "SwingBone":
                t = o.read_typetree()
                nm = _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))
                if nm:
                    out[nm] = (o, t)
        return out
    d_swing = swing_by_name(do, did, d_scripts)
    t_swing = swing_by_name(to, tid, t_scripts)

    # collider remap (donor collider pid -> bone; target bone -> pid / 1-based idx)
    d_colpid_to_bone = {pid: bone for pid, bone in _manager_colliders(do, did, d_scripts)}
    t_cols = _manager_colliders(to, tid, t_scripts)
    t_bone_to_colpid = {bone: pid for pid, bone in t_cols if bone}
    t_bone_to_colidx = {bone: i for i, (pid, bone) in enumerate(t_cols) if bone}

    # keep the wearer's identity + structure; copy only the donor's physics tuning
    _KEEP_TARGET = {"m_GameObject", "m_Script", "m_Name", "m_Enabled",
                    "child", "sibling", "parentIndex", "childIndex", "siblingIndex",
                    "colliders", "colliderIds"}
    n = 0
    for name in dict.fromkeys(costume_bone_names):
        if name not in d_swing or name not in t_swing:
            continue
        donor_sb = d_swing[name][1]
        t_obj, t_sb = t_swing[name]
        for k in list(t_sb.keys()):
            if k in donor_sb and k not in _KEEP_TARGET:
                t_sb[k] = copy.deepcopy(donor_sb[k])
        if restore_collision:
            new_cols, new_ids = [], []
            for c in donor_sb.get("colliders", []):
                bone = d_colpid_to_bone.get(c.get("m_PathID"))
                if bone in t_bone_to_colpid:
                    new_cols.append({"m_FileID": 0, "m_PathID": t_bone_to_colpid[bone]})
                    new_ids.append(_collider_id_for_bone(bone, t_bone_to_colidx[bone]))
            if "colliders" in t_sb:
                t_sb["colliders"] = new_cols
            if "colliderIds" in t_sb:
                t_sb["colliderIds"] = new_ids
        t_obj.save_typetree(t_sb)
        n += 1
    if n:
        log(f"[costume] applied donor swing physics to {n} shared costume bone(s) "
            f"(skirt/ribbon); body (bust) kept the wearer's")
    return n


# --------------------------------------------------------------------------
# swing-physics length rescale for body-scaled targets (e.g. the Rina board)
# --------------------------------------------------------------------------
# A SwingBone's radius / knee-space offsets are absolute distances in the rig's
# units. The donor tuned them at the donor's body scale (normally 1.0). A masked /
# board-face target (Rina board) shrinks its whole body via the `Move` node
# (~0.927): the grafted donor appendage bones inherit that scale through the
# hierarchy, but their tuning *fields* do not — so a skirt / ribbon / wing / tail
# collides and swings as if it were still on a full-size body and splays out.
#
# The fix is general and part-agnostic: multiply each costume dynamic bone's
# length fields by  S_bone = target_world_scale / donor_world_scale, computed
# per bone from the accumulated hierarchy scale. Body pieces (under Move) get
# ~0.927; head-anchored pieces (Head 1.077 cancels Move) net ~1.0 and are left
# alone automatically. Forces / angles / dot-limits are scale-invariant and kept.
# Only the SwingBone MonoBehaviours change — no mesh / bind pose is touched, so a
# board target still loads (mesh edits are what hang the board, not these).
#
# No-op on a standard target, where donor and target body scales both = 1.0.
_SWING_LENGTH_FIELDS = ("radius", "kneeSpaceOffsetFront", "kneeSpaceOffsetOther")


def scale_costume_swing_lengths(out_path, donor_path, costume_bone_names, verbose=True):
    """Rescale donor-authored SwingBone length tuning on every costume dynamic bone by
    the target/donor body-scale ratio, so donor pieces keep their proportions when the
    target scales the body. Re-opens the written bundle (so it sees the final realigned
    rig) and the donor. Returns the number of bones rescaled (0 = scales matched)."""
    def log(*a):
        if verbose:
            print(*a)
    env = UnityPy.load(out_path)
    objs, id2 = _index(env)
    scripts = _scriptname_map(objs)
    donor = UnityPy.load(donor_path)
    do, did = _index(donor)

    t_scale = _accumulated_scale_byname(id2)
    d_scale = _accumulated_scale_byname(did)
    names = {n for n in costume_bone_names if n}

    n_scaled, ratios = 0, {}
    for o in objs:
        if o.type.name != "MonoBehaviour" or \
                scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) != "SwingBone":
            continue
        tt = o.read_typetree()
        name = _go_name(id2, tt.get("m_GameObject", {}).get("m_PathID"))
        if name not in names:
            continue
        ts, ds = t_scale.get(name), d_scale.get(name)
        if not ts or not ds:
            continue
        s = ts / ds
        if abs(s - 1.0) < 1e-3:               # scales agree -> nothing to do
            continue
        for k in _SWING_LENGTH_FIELDS:
            if isinstance(tt.get(k), (int, float)):
                tt[k] = tt[k] * s
        o.save_typetree(tt)
        n_scaled += 1
        ratios[name] = s
    if n_scaled:
        bf = list(env.files.values())[0]
        bf.mark_changed()
        with open(out_path, "wb") as f:
            f.write(bf.save(packer="lz4"))
        avg = sum(ratios.values()) / len(ratios)
        log(f"[scale] body-scaled target: rescaled swing-physics lengths on {n_scaled} "
            f"costume bone(s) by ~{avg:.3f} (target/donor body-scale ratio) so the donor's "
            f"skirt/ribbon/wing/tail keeps its proportions; mesh untouched (load-safe)")
    else:
        log("[scale] target and donor body scales match — swing-physics lengths unchanged")
    return n_scaled


# --------------------------------------------------------------------------
# costume swing-chain repair (donor skirt deeper than the wearer's)
# --------------------------------------------------------------------------
# A SwingBone chain links parent->child by both an integer childIndex (into
# SwingBoneManager.bones) and a `child` PPtr<Transform>. When the donor costume's
# skirt is a DEEPER chain than the wearer's (donor 2-segment B1->B2->End vs a
# 1-segment wearer B1->End), --physics injects the donor's extra segment bones
# (B2/C2/D2) and points each one's parentIndex at its parent — but the PARENT bone
# is a native wearer bone kept by sync_costume_swing_physics, so its childIndex /
# child still skip straight to the End as the 1-segment wearer chain did. The
# injected lower segment is therefore orphaned: it never simulates, the lower skirt
# stays rigid, and the legs clip through it (most visible on whichever leg lifts).
#
# This re-derives each costume bone's downward link from the DONOR: if the donor's
# bone chains to a child that is itself a costume bone, the output bone's child /
# childIndex are set to that same bone (remapped to the output's pids/indices),
# inserting the deeper segment back into the chain. Sibling links are left alone
# (the root-level sibling ring already includes wearer-only bones like SkirtE1).
# No-op when the donor and output chains already agree.
def repair_costume_swing_chain(out_path, donor_path, costume_bone_names, verbose=True):
    """Insert donor-only deeper swing segments back into the chain by fixing each
    costume bone's child / childIndex to match the donor's topology. Returns the
    number of links repaired (0 = chains already agree)."""
    def log(*a):
        if verbose:
            print(*a)
    env = UnityPy.load(out_path)
    objs, id2 = _index(env)
    scripts = _scriptname_map(objs)
    donor = UnityPy.load(donor_path)
    do, did = _index(donor)
    d_scripts = _scriptname_map(do)
    names = {n for n in costume_bone_names if n}

    def go_name(idx, go_pid):
        o = idx.get(go_pid)
        return o.read().m_Name if o else None

    def resolve_to_bonename(idx, pid):
        """A child/sibling PPtr points at the bone's Transform -> resolve to GO name."""
        o = idx.get(pid)
        if not o:
            return None
        if o.type.name in ("Transform", "MonoBehaviour"):
            return go_name(idx, o.read_typetree().get("m_GameObject", {}).get("m_PathID"))
        if o.type.name == "GameObject":
            return o.read().m_Name
        return None

    # output: bone name -> SwingBone object + transform pid + manager index
    out_swing, out_tf_pid = {}, {}
    for o in objs:
        if o.type.name == "MonoBehaviour" and \
                scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == "SwingBone":
            out_swing[go_name(id2, o.read_typetree().get("m_GameObject", {}).get("m_PathID"))] = o
    for pid, o in id2.items():
        if o.type.name == "Transform":
            nm = go_name(id2, o.read_typetree().get("m_GameObject", {}).get("m_PathID"))
            if nm:
                out_tf_pid[nm] = pid
    out_mgr = _find_swingbone_manager(objs, scripts)
    out_idx_of = {}
    if out_mgr:
        for i, b in enumerate(out_mgr.read_typetree().get("bones", [])):
            co = id2.get(b["m_PathID"])
            nm = go_name(id2, co.read_typetree().get("m_GameObject", {}).get("m_PathID")) if co else None
            if nm:
                out_idx_of[nm] = i

    # donor: bone name -> its child bone's name (downward swing link)
    donor_child = {}
    for o in do:
        if o.type.name == "MonoBehaviour" and \
                d_scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == "SwingBone":
            tt = o.read_typetree()
            nm = go_name(did, tt.get("m_GameObject", {}).get("m_PathID"))
            cp = tt.get("child", {}).get("m_PathID", 0)
            donor_child[nm] = resolve_to_bonename(did, cp) if cp else None

    n_fixed = 0
    for name, o in out_swing.items():
        if name not in names:
            continue
        desired_child = donor_child.get(name)
        # only act when the donor chains DOWN into another costume bone present here
        if not desired_child or desired_child not in names or desired_child not in out_swing:
            continue
        tt = o.read_typetree()
        cur_child = resolve_to_bonename(id2, tt.get("child", {}).get("m_PathID", 0))
        if cur_child == desired_child:
            continue                                   # already wired correctly
        tt["child"] = {"m_FileID": 0, "m_PathID": out_tf_pid.get(desired_child, 0)}
        if "childIndex" in tt:
            tt["childIndex"] = out_idx_of.get(desired_child, -1)
        o.save_typetree(tt)
        n_fixed += 1

    # --- transform-hierarchy repair (the other half of the chain) ---
    # Fixing the SwingBone child link above is not enough: when the donor's deeper
    # segment (B2) is injected as a child of the shallow wearer bone (B1), the
    # pre-existing leaf TIP (B_End) is left hanging off B1 instead of being moved
    # under B2. The SIMULATION then runs B1->B2->B_End while the TRANSFORM/skinning
    # tree is still B1->{B_End, B2}, so when B2 swings the tip mesh (parented to B1)
    # does not follow it and the tip detaches / flails (~21 cm off). Reparent every
    # costume bone whose donor transform-parent differs from the output's so the
    # skinning tree matches the donor (B1->B2->B_End). Edits are batched per object
    # (m_Father + m_Children together) so a parent that also moves keeps both edits.
    donor_tparent = {}
    for o in do:
        if o.type.name == "Transform":
            t = o.read_typetree()
            nm = go_name(did, t.get("m_GameObject", {}).get("m_PathID"))
            fo = did.get(t.get("m_Father", {}).get("m_PathID", 0))
            donor_tparent[nm] = go_name(did, fo.read_typetree().get("m_GameObject", {}).get("m_PathID")) if fo else None

    def out_parent_name(pid):
        o = id2.get(pid)
        fo = id2.get(o.read_typetree().get("m_Father", {}).get("m_PathID", 0)) if o else None
        return go_name(id2, fo.read_typetree().get("m_GameObject", {}).get("m_PathID")) if fo else None

    reparents = []
    for nm in names:
        pid = out_tf_pid.get(nm)
        want = donor_tparent.get(nm)
        if pid is None or not want or want not in out_tf_pid:
            continue
        if out_parent_name(pid) != want:
            reparents.append((nm, pid, want))

    if reparents:
        edits = {}   # pid -> {'father': pid, 'rm': set(child pids), 'add': set(child pids)}
        for nm, pid, want in reparents:
            cur = out_parent_name(pid)
            edits.setdefault(pid, {})["father"] = out_tf_pid[want]
            if cur in out_tf_pid:
                edits.setdefault(out_tf_pid[cur], {}).setdefault("rm", set()).add(pid)
            edits.setdefault(out_tf_pid[want], {}).setdefault("add", set()).add(pid)
        for pid, ch in edits.items():
            t = id2[pid].read_typetree()
            if "father" in ch:
                t["m_Father"] = {"m_FileID": 0, "m_PathID": ch["father"]}
            if "rm" in ch or "add" in ch:
                kids = [c for c in t.get("m_Children", []) if c["m_PathID"] not in ch.get("rm", set())]
                seen = {c["m_PathID"] for c in kids}
                for cpid in ch.get("add", set()):
                    if cpid not in seen:
                        kids.append({"m_FileID": 0, "m_PathID": cpid})
                        seen.add(cpid)
                t["m_Children"] = kids
            id2[pid].save_typetree(t)

    if n_fixed or reparents:
        bf = list(env.files.values())[0]
        bf.mark_changed()
        with open(out_path, "wb") as f:
            f.write(bf.save(packer="lz4"))
        if n_fixed:
            log(f"[chain] repaired {n_fixed} costume swing-chain link(s): the donor's deeper "
                f"skirt/appendage segments now sit IN the chain (parent->child restored) so the "
                f"lower pieces simulate and collide instead of staying rigid")
        if reparents:
            log(f"[chain] reparented {len(reparents)} costume tip/segment bone(s) to match the "
                f"donor skinning tree ({', '.join(n for n, _, _ in reparents[:6])}"
                f"{'...' if len(reparents) > 6 else ''}) so the tips follow the last swing "
                f"segment instead of detaching")
    else:
        log("[chain] costume swing chains already match the donor — no repair needed")
    return n_fixed + len(reparents)


# --------------------------------------------------------------------------
# adopt the donor's body colliders (the grafted body is the donor's)
# --------------------------------------------------------------------------
# transplant() grafts the DONOR's body MESH but keeps the WEARER's body COLLIDERS.
# A SwingCollider's geometry (radius/offset) and capsule link (`sibling`, which forms
# a capsule with the collider it points at) were authored for the WEARER's body and
# its old costume — so the donor skirt/ribbon/wing now collides with a body shape it
# was never authored for. The wearer's per-leg capsule chains are often ASYMMETRIC
# (e.g. one leg has a groin/hip capsule the other lacks); when that side differs from
# what the donor outfit expects, that leg clips through the skirt while the matching
# side is fine — i.e. a one-sided clip that has nothing to do with the bones (those
# were realigned to the donor and are symmetric).
#
# Since the grafted body IS the donor's, its colliders should be the donor's too. The
# collider POSITIONS already match (bones were realigned to the donor), so we copy the
# donor collider's radius / offset / sibling capsule link onto the wearer's same-named
# collider, remapping the sibling to the wearer's collider of that name. Body identity
# is unaffected (the wearer keeps its head/face; the body was already the donor's).
def adopt_donor_body_colliders(out_path, donor_path, verbose=True):
    """Copy each donor body collider's geometry + capsule sibling onto the wearer's
    same-named collider so the transplanted outfit collides with the body it was
    authored for. Returns the number of colliders updated."""
    def log(*a):
        if verbose:
            print(*a)
    env = UnityPy.load(out_path)
    objs, id2 = _index(env)
    scripts = _scriptname_map(objs)
    donor = UnityPy.load(donor_path)
    do, did = _index(donor)
    d_scripts = _scriptname_map(do)

    def go_name(idx, go_pid):
        o = idx.get(go_pid)
        return o.read().m_Name if o else None

    def collider_name(idx, o):
        return go_name(idx, o.read_typetree().get("m_GameObject", {}).get("m_PathID"))

    out_col, out_idx_of = {}, {}
    for o in objs:
        if o.type.name == "MonoBehaviour" and \
                scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == "SwingCollider":
            nm = collider_name(id2, o)
            if nm:
                out_col[nm] = o
    out_mgr = _find_swingbone_manager(objs, scripts)
    if out_mgr:
        for i, c in enumerate(out_mgr.read_typetree().get("colliders", [])):
            co = id2.get(c["m_PathID"])
            nm = collider_name(id2, co) if co else None
            if nm:
                out_idx_of[nm] = i

    # donor: name -> (radius, offset, sibling collider name)
    donor_cfg = {}
    for o in do:
        if o.type.name == "MonoBehaviour" and \
                d_scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == "SwingCollider":
            tt = o.read_typetree()
            nm = collider_name(did, o)
            sp = tt.get("sibling", {}).get("m_PathID", 0)
            sib = None
            if sp:
                sco = did.get(sp)
                sib = collider_name(did, sco) if sco and sco.type.name == "MonoBehaviour" else \
                    go_name(did, did.get(sp).read_typetree().get("m_GameObject", {}).get("m_PathID")) if sp in did else None
            donor_cfg[nm] = (tt.get("radius"), tt.get("offset"), sib)

    n = 0
    for nm, o in out_col.items():
        if nm not in donor_cfg:
            continue
        rad, off, sib = donor_cfg[nm]
        tt = o.read_typetree()
        changed = False
        if rad is not None and tt.get("radius") != rad:
            tt["radius"] = rad
            changed = True
        if off is not None and tt.get("offset") != off:
            tt["offset"] = copy.deepcopy(off)
            changed = True
        # capsule link: point at the wearer's collider of the donor's sibling name
        if "sibling" in tt:
            want_pid = out_col[sib].path_id if (sib and sib in out_col) else 0
            if tt.get("sibling", {}).get("m_PathID", 0) != want_pid:
                tt["sibling"] = {"m_FileID": 0, "m_PathID": want_pid}
                if "siblingIndex" in tt:
                    tt["siblingIndex"] = out_idx_of.get(sib, -1)
                changed = True
        if changed:
            o.save_typetree(tt)
            n += 1
    if n:
        bf = list(env.files.values())[0]
        bf.mark_changed()
        with open(out_path, "wb") as f:
            f.write(bf.save(packer="lz4"))
        log(f"[collider] adopted the donor's body collider geometry + capsule links on "
            f"{n} collider(s) (the grafted body is the donor's) so the transplanted outfit "
            f"collides with the body it was authored for, not the wearer's old shape")
    return n


# --------------------------------------------------------------------------
# core
# --------------------------------------------------------------------------
def transplant(donor_path, target_path, out_path, verbose=True,
               preserve_physics=False, realign=True, restore_collision=True,
               worldspace=True, fix_nodescaling=True, mask_handling="auto",
               costume_physics="donor", sync_textures=True,
               scale_swing_physics=True):
    def log(*a):
        if verbose:
            print(*a)

    donor = UnityPy.load(donor_path)
    target = UnityPy.load(target_path)
    do, did = _index(donor)
    to, tid = _index(target)

    dch, dco = _chara_costume_id(donor)
    tch, tco = _chara_costume_id(target)
    log(f"[info] donor (costume) : {dch}_{dco}")
    log(f"[info] target (wearer) : {tch}_{tco}")

    # ---- special-case masked / board-face targets (e.g. Rina-chan board) ----
    # mask_handling: "auto" detect, "on" force, "off" disable. When active, the head
    # accessory-anchor bone is kept out of the realign so the mask is not warped; its
    # node-scaling is preserved by rebase_node_scaling's scaledValue guard.
    board = detect_board_face_model(to, tid) if mask_handling != "off" else None
    if mask_handling == "on" and board is None:
        board = {"kind": "board-face(forced)", "face_parts": 0,
                 "anchor_bones": {"Head"}, "markers": ["forced"]}
    if board:
        log(f"[mask] masked / board-face target detected: {board['face_parts']} face "
            f"part(s); markers: {', '.join(board['markers'])}. Exceptional handling ON — "
            f"keeping accessory-anchor bone(s) {sorted(board['anchor_bones'])} out of the "
            f"realign and preserving their node-scaling.")

    # ---- donor body renderer / mesh ----
    d_smr = _body_smr(do)
    d_smr_tt = d_smr.read_typetree()
    d_bone_names = [_transform_goname(did, b["m_PathID"]) for b in d_smr_tt["m_Bones"]]
    d_mesh_obj, d_mesh_tt = _mesh_by_pid(did, d_smr_tt["m_Mesh"]["m_PathID"])
    d_mesh_name = d_mesh_tt.get("m_Name")

    # ---- target body renderer / mesh ----
    t_smr = _body_smr(to)
    t_smr_tt = t_smr.read_typetree()
    t_mesh_obj = _mesh_name_pid(to, d_mesh_name) or _mesh_by_pid(tid, t_smr_tt["m_Mesh"]["m_PathID"])[0]

    name2tf = _name2transform(tid)
    native_target_bones = set(name2tf)   # before any appendage injection
    d_parent = _transform_parent_byname(did)
    d_name_to_idx = {n: i for i, n in enumerate(d_bone_names)}

    # ---- bust-offset bone aliasing --------------------------------------------
    # Characters / costumes name the chest-offset bone differently (a donor may use
    # a BreastA_Offset[->BreastB_Offset] chain, the target a single Breast_Offset) —
    # the same skeletal role: the bone the bust and the chest ribbon hang off, and
    # the one the target's Avatar/animation actually drives. Map the donor's
    # bust-offset bones onto the target's existing one so the costume REUSES that
    # Avatar-known bone instead of injecting a dead duplicate — which would leave the
    # ribbon anchored to a bone the runtime never moves and orphan the target's real
    # bust. The target bone is realigned to the donor's bust rest pose so the grafted
    # mesh's bind poses stay consistent.
    bust_alias, realign_alias = {}, {}
    _BUST_RE = re.compile(r"^Breast[A-Za-z0-9]*_Offset$")
    _donor_bust = [n for n in dict.fromkeys(d_bone_names) if n and _BUST_RE.match(n)]
    _target_bust = [n for n in native_target_bones if _BUST_RE.match(n)]
    if _donor_bust and _target_bust and not set(_donor_bust) <= native_target_bones:
        def _bust_root(names, parent):
            roots = [n for n in names if not _BUST_RE.match(parent.get(n) or "")]
            return (roots or names)[0]
        t_anchor = _bust_root(_target_bust, _transform_parent_byname(tid))
        d_root = _bust_root(_donor_bust, d_parent)
        for dn in _donor_bust:
            if dn not in native_target_bones:
                bust_alias[dn] = t_anchor
                name2tf[dn] = name2tf[t_anchor]
        if bust_alias:
            realign_alias[t_anchor] = d_root
            log(f"[bust] donor bust bone(s) {sorted(bust_alias)} -> target "
                f"'{t_anchor}' (reuse the Avatar-known bone; rest pose from '{d_root}')")

    # ---- optionally recreate costume-appendage bones (with their jiggle physics) ----
    # When enabled, the donor's costume-only bones are injected into the target as
    # real GameObjects/Transforms + SwingBone components, so they keep their sway.
    # The injected transforms then resolve via name2tf like any native bone and use
    # the donor mesh's original bind poses (no rigid override).
    child_adds = {}
    if preserve_physics:
        inject_names = [n for n in dict.fromkeys(d_bone_names)
                        if n is not None and n not in name2tf]
        if inject_names:
            new_map, child_adds = inject_appendage_bones(
                donor, target, inject_names, name2tf,
                restore_collision=restore_collision, log=log)
            name2tf.update(new_map)
            # An injected appendage whose donor parent is an aliased bust bone (e.g.
            # buttons under BreastB_Offset) must attach to the alias TARGET, since no
            # target transform carries the donor bust name. Its m_Father is already
            # correct (via the aliased name2tf); remap the parent's m_Children key too.
            if bust_alias and child_adds:
                remapped = {}
                for pn, kids in child_adds.items():
                    remapped.setdefault(bust_alias.get(pn, pn), []).extend(kids)
                child_adds = remapped

    # ---- resolve every donor body bone to a target transform ----
    # costume-specific bones still absent in target re-bind to the nearest ancestor
    # that exists in the target AND in the donor bone list (for its bind pose).
    bone_pids = []
    bindpose_override = {}   # donor bone index -> donor bone index whose bindpose to copy
    rebinds = []
    for i, n in enumerate(d_bone_names):
        if n in name2tf:
            bone_pids.append(name2tf[n])
            continue
        anc = d_parent.get(n)
        while anc is not None and not (anc in name2tf and anc in d_name_to_idx):
            anc = d_parent.get(anc)
        if anc is None:
            anc = "Hips"  # last-resort anchor
        bone_pids.append(name2tf[anc])
        if anc in d_name_to_idx:
            bindpose_override[i] = d_name_to_idx[anc]
        rebinds.append((n, anc))
    if rebinds:
        log(f"[info] costume bones rigidly re-bound to wearer rig: "
            + ", ".join(f"{n}->{a}" for n, a in rebinds))

    missing = [n for n, _ in rebinds if n is None]
    if missing:
        raise RuntimeError("unnamed donor bones; unexpected rig")

    # ---- 1) graft donor body mesh into target mesh object (keep target pid/name) ----
    new_mesh_tt = copy.deepcopy(d_mesh_tt)
    bp = new_mesh_tt.get("m_BindPose", [])
    for slot, src_idx in bindpose_override.items():
        bp[slot] = copy.deepcopy(bp[src_idx])
    new_mesh_tt["m_Name"] = t_mesh_obj.read_typetree().get("m_Name", new_mesh_tt.get("m_Name"))
    t_mesh_obj.save_typetree(new_mesh_tt)
    log(f"[ok] body mesh grafted: {new_mesh_tt['m_VertexData']['m_VertexCount']} verts, "
        f"{len(bp)} bind poses")

    # ---- 2) rewrite target body SMR bone list + bounds ----
    t_smr_tt["m_Bones"] = [{"m_FileID": 0, "m_PathID": pid} for pid in bone_pids]
    t_smr_tt["m_AABB"] = copy.deepcopy(d_smr_tt["m_AABB"])
    # match submesh/material count (SIFAS body = single submesh; guard anyway)
    n_sub = len(new_mesh_tt.get("m_SubMeshes", [])) or 1
    mats = t_smr_tt.get("m_Materials", [])
    if mats:
        body_mat = mats[0]
        t_smr_tt["m_Materials"] = [copy.deepcopy(body_mat) for _ in range(n_sub)]
    t_smr.save_typetree(t_smr_tt)
    log(f"[ok] body renderer rewired: {len(bone_pids)} bones, {n_sub} submesh(es)")

    # ---- 3) sync body material: properties + every texture slot (incl. matcap) ----
    #         When sync_textures is False this whole step is skipped, so the wearer
    #         keeps its own body material (textures + shader properties) and only the
    #         costume's geometry/bones are transplanted. Skipping the step entirely
    #         (rather than copying the donor material's properties but not its textures)
    #         avoids leaving dangling donor texture references such as a matcap slot the
    #         wearer's material does not have.
    if sync_textures:
        d_body_mat = d_smr_tt.get("m_Materials", [{}])[0].get("m_PathID")
        t_body_mat = t_smr_tt.get("m_Materials", [{}])[0].get("m_PathID")
        sync_body_material(donor, target, d_body_mat, t_body_mat, log)
    else:
        log("[skip] body textures not transplanted: the wearer keeps its own body "
            "material and textures (costume geometry/bones still grafted)")

    # ---- 4) snap the wearer's body bones to the costume's rest pose, and wire
    #         any injected appendage roots into their parent (one save per bone) ----
    align_names = ([n for n in dict.fromkeys(d_bone_names) if n in native_target_bones]
                   if realign else [])
    # the aliased bust anchor is a target-only name (not in d_bone_names), so add it
    # explicitly so it is realigned to the donor bust rest pose via realign_alias.
    if realign and realign_alias:
        align_names = align_names + [a for a in realign_alias if a not in align_names]
    if board and align_names:
        # never snap an accessory-anchor bone (e.g. Head, which carries the whole
        # mask) to the donor's rest pose — that would drag/rescale the mask.
        protected = [n for n in align_names if n in board["anchor_bones"]]
        align_names = [n for n in align_names if n not in board["anchor_bones"]]
        if protected:
            log(f"[mask] excluded {protected} from realign (mask anchor)")
    if align_names or child_adds:
        apply_bone_edits(did, tid, align_names, child_adds, realign_alias=realign_alias, log=log)

    # ---- 4b) costume dynamic bones the wearer also has (skirt / shared ribbon):
    #          take the donor's swing physics + collision so the donor outfit sways
    #          as designed. Body-identity dynamics (the bust) stay the wearer's. ----
    costume_dyn = []
    if costume_physics == "donor":
        costume_dyn = [n for n in dict.fromkeys(d_bone_names)
                       if n is not None and not _is_body_identity_bone(n)]
        sync_costume_swing_physics(donor, target, costume_dyn,
                                   restore_collision=restore_collision, log=log)

    # ---- write ----
    bf, _ = _serialized_file(target)
    bf.mark_changed()
    with open(out_path, "wb") as f:
        f.write(bf.save(packer="lz4"))

    # ---- 6) bake the grafted body mesh into world space (re-read so it reflects the
    #         graft; needed so SwingBone-driven pieces like the ribbon render in the
    #         right place on a STANDARD model whose body sits under a non-identity mesh
    #         root). ----
    #
    #         BOARD-FACE EXCEPTION: a masked / board-face model (Rina-chan board, ch9999)
    #         is authored entirely in its OWN offset coordinate space — body, Face, Hair,
    #         EyeBrow and the 30+ expression meshes all share that offset. World-spacing
    #         forces the body's mesh root to identity, which DESYNCS the body from the
    #         (untouched) head/expression meshes; the board's runtime model assembly then
    #         never completes and the game hangs on an infinite load. The shipped board is
    #         not world-spaced, so the correct handling is to leave the WHOLE board in its
    #         native space and bake nothing. (The earlier body_only bake was incomplete:
    #         baking the body is itself the problem, not just baking the head meshes.)
    #         Verified in-game: skipping the bake loads, baking hangs.
    if worldspace and not board:
        worldspace_normalize(out_path, verbose=verbose)
    elif worldspace and board:
        log("[mask] board-face target: skipping the world-space bake — the board is "
            "authored in its own offset space; forcing the body to world space (meshRoot"
            "=I) desyncs it from the untouched face/expression meshes and hangs the load.")

    # ---- 7) keep LiveCoreMemberNodeScaling consistent with the realigned bones
    #         so the runtime body-shape pass doesn't teleport ribbon/skirt pieces
    #         (the correction is preserved, only re-anchored to the new rest) ----
    if fix_nodescaling and realign:
        rebase_node_scaling(out_path, verbose=verbose)

    # ---- 7a) repair the costume swing chain when the donor skirt/appendage is a
    #          DEEPER chain than the wearer's (e.g. donor 2-segment skirt onto a
    #          1-segment wearer): re-insert the donor's lower segments so they
    #          simulate instead of staying rigid (legs would otherwise clip through). ----
    if costume_physics == "donor" and costume_dyn:
        repair_costume_swing_chain(out_path, donor_path, costume_dyn, verbose=verbose)

    # ---- 7a2) the grafted body is the donor's, so adopt the donor's body colliders
    #           (geometry + capsule links) onto the wearer's same-named colliders. Fixes
    #           one-sided skirt clipping where the wearer's leg capsule chain differs from
    #           what the donor outfit was authored for. Positions already match (realign). ----
    adopt_donor_body_colliders(out_path, donor_path, verbose=verbose)

    # ---- 7b) if the target scales the whole body (e.g. the Rina board's Move~0.927),
    #          rescale the donor's swing-physics lengths so the grafted skirt/ribbon/
    #          wing/tail keeps its proportions instead of splaying on the smaller body.
    #          No-op on a standard target (scales match). Mesh untouched -> load-safe. ----
    if scale_swing_physics and costume_physics == "donor" and costume_dyn:
        scale_costume_swing_lengths(out_path, donor_path, costume_dyn, verbose=verbose)

    # ---- 8) warn (read-only) if the result blows past the runtime combine limits
    check_combine_limits(out_path, verbose=verbose)

    log(f"[done] wrote {out_path}")
    return out_path


def validate(out_path, verbose=True):
    """Re-load the output and assert no dangling references remain in the bits we
    touched: SkinnedMeshRenderer bones/mesh, SwingBoneManager bones and the
    SwingBone child/sibling pointers of any injected appendage bones."""
    env = UnityPy.load(out_path)
    objs, id2 = _index(env)
    scripts = _scriptname_map(objs)
    dangling = 0
    # hierarchy must stay a clean tree: every Transform listed under exactly one
    # parent, once. Otherwise AssetStudio's export throws a duplicate-key error.
    child_parents = {}
    hier_problems = 0
    for o in objs:
        if o.type.name == "Transform":
            seen = set()
            for c in o.read_typetree().get("m_Children", []):
                cp = c["m_PathID"]
                if cp in seen:
                    hier_problems += 1
                seen.add(cp)
                child_parents.setdefault(cp, 0)
                child_parents[cp] += 1
    hier_problems += sum(1 for n in child_parents.values() if n > 1)
    if hier_problems and verbose:
        print(f"[validate] WARNING: {hier_problems} transform(s) with multiple/duplicate "
              f"parents — run fix_unity_hierarchy.py before exporting in AssetStudio")
    for o in objs:
        if o.type.name == "SkinnedMeshRenderer":
            t = o.read_typetree()
            for b in t.get("m_Bones", []):
                if b["m_PathID"] not in id2:
                    dangling += 1
            mp = t.get("m_Mesh", {}).get("m_PathID")
            if mp and mp not in id2:
                dangling += 1
        elif o.type.name == "MonoBehaviour":
            cls = scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID"))
            t = o.read_typetree()
            if cls == "SwingBoneManager":
                for b in t.get("bones", []):
                    if b["m_PathID"] not in id2:
                        dangling += 1
            elif cls == "SwingBone":
                for key in ("child", "sibling"):
                    pid = t.get(key, {}).get("m_PathID", 0)
                    if pid and pid not in id2:
                        dangling += 1
    if verbose:
        print(f"[validate] dangling references: {dangling}")
    return dangling == 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Transplant a SIFAS costume from a donor model bundle onto a target "
                    "character's model bundle (target keeps its face/hair/identity).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--donor", help="bundle whose COSTUME you want (second character)")
    p.add_argument("--target",
                   help="bundle of the character that should WEAR it (first character)")
    p.add_argument("--out", help="output bundle path")
    p.add_argument("--physics", action="store_true",
                   help="recreate costume-appendage bones (collar/cape/ribbon) as real "
                        "bones with their SwingBone jiggle physics, instead of rigidly "
                        "anchoring them. Body collision is remapped to the wearer's "
                        "colliders (use --no-collision to drop it instead)")
    p.add_argument("--no-collision", action="store_true",
                   help="with --physics, do not remap body collision for injected bones")
    p.add_argument("--no-realign", action="store_true",
                   help="do NOT snap the wearer's body bones to the costume's rest pose "
                        "(keeps the wearer's exact body proportions, but costume pieces "
                        "such as the chest ribbon may sit offset)")
    p.add_argument("--no-worldspace", action="store_true",
                   help="do NOT bake the body mesh into world space (leave it in the "
                        "donor's local space; swinging pieces like the ribbon may shift)")
    p.add_argument("--no-nodescaling-fix", action="store_true",
                   help="do NOT re-anchor LiveCoreMemberNodeScaling to the realigned bones "
                        "(the runtime body-shape pass may then teleport ribbon/skirt pieces "
                        "to the chest). The character's body shaping is preserved either way)")
    p.add_argument("--mask-handling", choices=["auto", "on", "off"], default="auto",
                   help="special handling for masked / board-face targets (e.g. Tennoji "
                        "Rina's Rina-chan board): keep the head accessory-anchor bone out of "
                        "the realign and never double-apply node-scaling. 'auto' (default) "
                        "detects the model, 'on' forces it, 'off' uses the plain behaviour.")
    p.add_argument("--costume-physics", choices=["donor", "target"], default="donor",
                   help="for costume dynamic bones the wearer also has (the skirt, a shared "
                        "ribbon): whose SwingBone tuning + body collision to use. 'donor' "
                        "(default) makes the donor outfit sway/collide as designed; 'target' "
                        "keeps the wearer's old-costume physics. Body bones (the bust) always "
                        "stay the wearer's either way.")
    p.add_argument("--no-textures", action="store_true",
                   help="transplant the costume mesh + bones but do NOT copy the donor's "
                        "body textures/material; the wearer keeps its own body texture. "
                        "Useful when you intend to paint your own texture afterwards. "
                        "Off by default (textures are transplanted).")
    p.add_argument("--no-swing-scale", action="store_true",
                   help="do NOT rescale the donor's swing-physics lengths to a body-scaled "
                        "target. By default, when the target shrinks the body (e.g. the Rina "
                        "board's Move~0.927), the grafted skirt/ribbon/wing/tail's radius and "
                        "knee-space offsets are scaled by the target/donor body ratio so the "
                        "pieces keep their proportions instead of splaying. No-op on a normal "
                        "target. Mesh is never touched, so loading is unaffected.")
    p.add_argument("--gui", action="store_true", help="force the graphical interface")
    p.add_argument("-q", "--quiet", action="store_true", help="less logging")
    return p


def run_cli(args):
    if not (args.donor and args.target and args.out):
        build_parser().error("--donor, --target and --out are required "
                             "(or run with no arguments for the GUI)")
    transplant(args.donor, args.target, args.out,
               verbose=not args.quiet, preserve_physics=args.physics,
               realign=not args.no_realign, restore_collision=not args.no_collision,
               worldspace=not args.no_worldspace,
               fix_nodescaling=not args.no_nodescaling_fix,
               mask_handling=args.mask_handling,
               costume_physics=args.costume_physics,
               sync_textures=not args.no_textures,
               scale_swing_physics=not args.no_swing_scale)
    ok = validate(args.out, verbose=not args.quiet)
    if not ok:
        print("[error] output has dangling references; aborting", file=sys.stderr)
        sys.exit(2)
    print("[success] costume transplant complete and verified")


# --------------------------------------------------------------------------
# GUI (optional; falls back to the CLI where tkinter/$DISPLAY is unavailable)
# --------------------------------------------------------------------------
def gui_available():
    if is_termux():
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") \
            and not os.environ.get("WAYLAND_DISPLAY"):
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def run_gui():
    import threading
    import queue
    import tkinter as tk
    from tkinter import ttk, filedialog, scrolledtext

    root = tk.Tk()
    root.geometry("760x560")

    # live language switching (re-apply registered widget texts; no rebuild)
    _i18n_widgets = []

    def _reg(widget, key, kind="text"):
        _i18n_widgets.append((widget, key, kind))
        return widget

    def _apply_i18n():
        root.title(_tr("SIFAS Costume Transplant"))
        for w, key, kind in _i18n_widgets:
            try:
                w.configure(**{kind: _tr(key)})
            except Exception:
                pass

    topbar = ttk.Frame(root)
    topbar.pack(fill="x", padx=10, pady=(8, 0))
    _names = [n for _c, n in _lang_opts()]
    _code_by_name = {n: c for c, n in _lang_opts()}
    _name_by_code = {c: n for c, n in _lang_opts()}
    _lang_var = tk.StringVar(value=_name_by_code.get(_get_lang(), _names[0]))
    _reg(ttk.Label(topbar, text=_tr("Language")), "Language").pack(side="left")
    _lang_cb = ttk.Combobox(topbar, textvariable=_lang_var, values=_names, state="readonly", width=10)
    _lang_cb.pack(side="left", padx=(6, 0))
    _lang_cb.bind("<<ComboboxSelected>>",
                  lambda e: (_set_lang(_code_by_name[_lang_var.get()]), _apply_i18n()))

    donor_v = tk.StringVar()
    target_v = tk.StringVar()
    out_v = tk.StringVar()
    physics_v = tk.BooleanVar(value=True)
    collision_v = tk.BooleanVar(value=True)
    realign_v = tk.BooleanVar(value=True)
    _auto = {"val": ""}   # last auto-suggested output; lets us tell auto from manual

    def suggest_out(*_):
        # keep the output name following the target until the user edits it by hand
        cur = out_v.get()
        if target_v.get() and (cur == "" or cur == _auto["val"]):
            base, ext = os.path.splitext(target_v.get())
            nv = base + "_modded" + (ext or ".unity")
            _auto["val"] = nv
            out_v.set(nv)

    target_v.trace_add("write", suggest_out)

    def pick(var, save=False):
        if save:
            path = filedialog.asksaveasfilename(
                title=_tr("Save output bundle"), defaultextension=".unity",
                filetypes=[("Unity bundle", "*.unity *.unity3d"), ("All files", "*.*")])
        else:
            path = filedialog.askopenfilename(
                title=_tr("Select bundle"),
                filetypes=[("Unity bundle", "*.unity *.unity3d"), ("All files", "*.*")])
        if path:
            var.set(path)

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="x")
    frm.columnconfigure(1, weight=1)
    rows = [
        ("Donor  (costume source)", donor_v, False),
        ("Target (wearer / identity)", target_v, False),
        ("Output bundle", out_v, True),
    ]
    for i, (label, var, save) in enumerate(rows):
        _reg(ttk.Label(frm, text=_tr(label), width=24), label).grid(row=i, column=0, sticky="w", pady=3)
        ent = ttk.Entry(frm, textvariable=var, width=62)
        ent.grid(row=i, column=1, padx=4, sticky="we")

        # show the END of the path (the filename) when it's longer than the box
        def _show_end(*_, e=ent):
            e.after_idle(lambda: e.xview_moveto(1.0))
        var.trace_add("write", _show_end)

        _reg(ttk.Button(frm, text=_tr("Browse…"),
                        command=lambda v=var, s=save: pick(v, s)), "Browse…").grid(row=i, column=2)

    opts = _reg(ttk.LabelFrame(root, text=_tr("Options"), padding=10), "Options")
    opts.pack(fill="x", padx=10, pady=(4, 0))
    _CB_PHYS = "Preserve appendage jiggle physics (collar / tie / wings)"
    _CB_COL = "Restore body collision for those bones"
    _CB_REALIGN = "Realign body bones to the costume's rest pose (fixes offset ribbon/skirt)"
    _CB_WORLD = "World-space the body mesh (so swinging ribbon/skirt render correctly)"
    _CB_NODE = ("Re-anchor NodeScaling to realigned bones (keeps body shaping; "
                "stops the in-game ribbon dropping to the chest)")
    _CB_CPHYS = ("Use the donor's swing physics for shared costume parts (skirt / "
                 "ribbon) — the bust always stays the wearer's")
    _CB_MASK = ("Special handling for masked / board-face models (Rina-chan board): "
                "auto-detect, protect head + body-shape scaling")
    _CB_NOTEX = ("Transplant without the body textures (keep the wearer's own texture; "
                 "only the costume mesh + bones are grafted)")
    _CB_SWSCALE = ("Scale swing physics to a body-scaled target (keeps skirt/ribbon/wing/"
                   "tail proportions on the Rina board; no-op on normal targets)")
    cb_phys = _reg(ttk.Checkbutton(opts, variable=physics_v, text=_tr(_CB_PHYS)), _CB_PHYS)
    cb_phys.grid(row=0, column=0, sticky="w", columnspan=2)
    cb_col = _reg(ttk.Checkbutton(opts, variable=collision_v, text=_tr(_CB_COL)), _CB_COL)
    cb_col.grid(row=1, column=0, sticky="w", padx=(22, 0))
    _reg(ttk.Checkbutton(opts, variable=realign_v, text=_tr(_CB_REALIGN)), _CB_REALIGN
         ).grid(row=2, column=0, sticky="w", columnspan=2)
    worldspace_v = tk.BooleanVar(value=True)
    _reg(ttk.Checkbutton(opts, variable=worldspace_v, text=_tr(_CB_WORLD)), _CB_WORLD
         ).grid(row=3, column=0, sticky="w", columnspan=2)
    nodescale_v = tk.BooleanVar(value=True)
    _reg(ttk.Checkbutton(opts, variable=nodescale_v, text=_tr(_CB_NODE)), _CB_NODE
         ).grid(row=4, column=0, sticky="w", columnspan=2)
    costume_phys_v = tk.BooleanVar(value=True)
    _reg(ttk.Checkbutton(opts, variable=costume_phys_v, text=_tr(_CB_CPHYS)), _CB_CPHYS
         ).grid(row=5, column=0, sticky="w", columnspan=2)
    mask_v = tk.BooleanVar(value=True)
    _reg(ttk.Checkbutton(opts, variable=mask_v, text=_tr(_CB_MASK)), _CB_MASK
         ).grid(row=6, column=0, sticky="w", columnspan=2)
    mask_status = ttk.Label(opts, text="", foreground="#207a3c")
    mask_status.grid(row=7, column=0, sticky="w", columnspan=2, padx=(22, 0))
    # Off by default: textures are transplanted unless the user opts out.
    no_textures_v = tk.BooleanVar(value=False)
    _reg(ttk.Checkbutton(opts, variable=no_textures_v, text=_tr(_CB_NOTEX)), _CB_NOTEX
         ).grid(row=8, column=0, sticky="w", columnspan=2)
    swing_scale_v = tk.BooleanVar(value=True)
    _reg(ttk.Checkbutton(opts, variable=swing_scale_v, text=_tr(_CB_SWSCALE)), _CB_SWSCALE
         ).grid(row=9, column=0, sticky="w", columnspan=2)

    def sync_collision_state(*_):
        cb_col.configure(state=("normal" if physics_v.get() else "disabled"))
    physics_v.trace_add("write", sync_collision_state)
    sync_collision_state()

    log_box = scrolledtext.ScrolledText(root, height=18, wrap="word",
                                        font=("TkFixedFont", 9))
    log_box.pack(fill="both", expand=True, padx=10, pady=8)

    msgq = queue.Queue()

    def drain():
        try:
            while True:
                item = msgq.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__mask_status__":
                    mask_status.configure(text=item[1])
                else:
                    log_box.insert("end", item)
                    log_box.see("end")
        except queue.Empty:
            pass
        root.after(80, drain)

    # auto-detect a masked / board-face target and report it in the status label
    def detect_target_model(*_):
        path = target_v.get().strip()
        if not path or not os.path.isfile(path):
            msgq.put(("__mask_status__", ""))
            return

        def _probe():
            try:
                info = detect_board_face_model_path(path)
            except Exception:
                info = None
            if info:
                msgq.put(("__mask_status__",
                          f"detected masked / board-face model "
                          f"({info['face_parts']} face parts, anchor "
                          f"{sorted(info['anchor_bones'])}) — special handling applies when checked"))
            else:
                msgq.put(("__mask_status__", _tr("standard model — no special handling needed")))
        threading.Thread(target=_probe, daemon=True).start()
    target_v.trace_add("write", detect_target_model)

    class _QWriter:
        def write(self, s):
            if s:
                msgq.put(s)
        def flush(self):
            pass

    run_btn = _reg(ttk.Button(frm, text=_tr("Transplant")), "Transplant")

    def worker(d, t, o, phys, col, realign, wspace, nscale, maskh, cphys, notex, swscale):
        old = sys.stdout
        sys.stdout = _QWriter()
        try:
            transplant(d, t, o, verbose=True, preserve_physics=phys,
                       realign=realign, restore_collision=col, worldspace=wspace,
                       fix_nodescaling=nscale, mask_handling=maskh,
                       costume_physics=cphys, sync_textures=not notex,
                       scale_swing_physics=swscale)
            ok = validate(o, verbose=True)
            print(_tr("\n[success] done — verified ✓\n") if ok
                  else _tr("\n[error] output has dangling references!\n"))
        except Exception as ex:
            import traceback
            print("\n[error] " + "".join(traceback.format_exception(ex)))
        finally:
            sys.stdout = old
            root.after(0, lambda: run_btn.configure(state="normal"))

    def go():
        d, t, o = donor_v.get().strip(), target_v.get().strip(), out_v.get().strip()
        if not (d and t and o):
            msgq.put(_tr("[error] choose donor, target and output first.\n"))
            return
        log_box.delete("1.0", "end")
        run_btn.configure(state="disabled")
        threading.Thread(target=worker, daemon=True,
                         args=(d, t, o, physics_v.get(), collision_v.get(),
                               realign_v.get(), worldspace_v.get(),
                               nodescale_v.get(),
                               "auto" if mask_v.get() else "off",
                               "donor" if costume_phys_v.get() else "target",
                               no_textures_v.get(), swing_scale_v.get())).start()

    run_btn.configure(command=go)
    run_btn.grid(row=len(rows), column=1, sticky="e", pady=8)

    drain()
    root.mainloop()


def main(argv=None):
    args = build_parser().parse_args(argv)
    want_gui = args.gui or not (args.donor or args.target or args.out)
    if want_gui and gui_available():
        run_gui()
        return
    if args.gui and not gui_available():
        print("[info] no graphical display available; falling back to CLI.")
    run_cli(args)


if __name__ == "__main__":
    main()
