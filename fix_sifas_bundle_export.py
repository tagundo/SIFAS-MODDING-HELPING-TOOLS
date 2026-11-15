#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS bundle mesh normalizer — fix wrong FBX exports at the source
==================================================================
SIFAS body model bundles store the body mesh in a *local* space (vertices
centred on the origin, ~0.7 m below where the character stands) and lift it at
runtime through the skin bind poses. Tools like AssetStudio mis-handle that
offset when exporting to FBX, so the body sinks into the floor in Blender while
the head/hair (which are already authored in world space) look correct.

Instead of patching every exported FBX, this normalizes the BUNDLE so any
exporter produces a correct file: it bakes each skinned mesh's "mesh root"
transform (meshRoot = boneWorld · bindPose, constant per mesh) into the vertex
positions and folds its inverse into the bind poses. After this meshRoot == I,
i.e. the body mesh is in world space exactly like the hair/face meshes that
already export correctly.

Rigid mesh-root normalization preserves the posed geometry in-game:
        vertex_world = Σ boneWorld[b] · bindPose[b] · v
    new vertices  v' = meshRoot · v
    new bindPose  B'[b] = bindPose[b] · meshRoot⁻¹
    ⇒ boneWorld[b] · B'[b] · v' = boneWorld[b] · bindPose[b] · v   (unchanged)

Positions are transformed by meshRoot; normals/tangents by its rotation (a pure
translation, the common SIFAS case, leaves them untouched). Verified on Unity
2018.4 uncompressed SIFAS model bundles (float vertex streams).

Scaled/sheared roots are skipped. Although inverse bind-pose compensation can
preserve vertex positions mathematically, the game rejects non-unit bind-pose
columns and can hide the entire character. Skipped mesh bytes stay unchanged.

Usage:
    python3 fix_sifas_bundle_export.py --in model.unity --out fixed.unity
"""

import os
import sys
import copy
import argparse
import importlib
import subprocess
import tempfile

# --- self-contained multi-language support (English default; 한국어 / 日本語) ---
# Translations are embedded so this single file works on its own. The chosen
# language is remembered (and shared with the other SIFAS tools) via a small
# JSON config — no extra module required.
import json as _json


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
        "SIFAS Bundle Mesh Normalizer": "SIFAS 번들 메시 노멀라이저",
        "Single": "단일",
        "Batch": "일괄",
        "Input .unity bundle": "입력 .unity 번들",
        "Output (fixed) bundle": "출력(수정된) 번들",
        "Browse…": "찾아보기…",
        "Normalize": "노멀라이즈",
        "Bundles (Add files… or Add folder…):": "번들 (파일 추가… 또는 폴더 추가…):",
        "Add files…": "파일 추가…",
        "Add folder…": "폴더 추가…",
        "Remove selected": "선택 항목 제거",
        "Clear": "비우기",
        "Output folder:": "출력 폴더:",
        "Normalize all": "전체 노멀라이즈",
        "Bakes body meshes into world space so AssetStudio/Blender export correctly. In-game rendering is unchanged.":
            "바디 메시를 월드 공간으로 베이크해 AssetStudio/Blender에서 올바르게 익스포트되게 합니다. 게임 내 렌더링은 변하지 않습니다.",
        "Save fixed bundle": "수정된 번들 저장",
        "Select bundle": "번들 선택",
        "Select bundles": "번들 선택",
        "Select a folder of bundles": "번들 폴더 선택",
        "Output folder": "출력 폴더",
        "[error] choose an input bundle and an output path.\n": "[오류] 입력 번들과 출력 경로를 선택하세요.\n",
        "[error] add at least one bundle and choose an output folder.\n": "[오류] 번들을 하나 이상 추가하고 출력 폴더를 선택하세요.\n",
        "\n[success] normalized — in-game render unchanged ✓\n": "\n[성공] 노멀라이즈 완료 — 게임 내 렌더링 변화 없음 ✓\n",
        "\n[warn] validation reported drift — inspect before use\n": "\n[경고] 검증에서 drift 감지 — 사용 전 확인하세요\n",
    },
    "ja": {
        "Language": "言語",
        "SIFAS Bundle Mesh Normalizer": "SIFAS バンドルメッシュ正規化ツール",
        "Single": "単一",
        "Batch": "一括",
        "Input .unity bundle": "入力 .unity バンドル",
        "Output (fixed) bundle": "出力（修正済み）バンドル",
        "Browse…": "参照…",
        "Normalize": "正規化",
        "Bundles (Add files… or Add folder…):": "バンドル（ファイル追加… またはフォルダ追加…）:",
        "Add files…": "ファイル追加…",
        "Add folder…": "フォルダ追加…",
        "Remove selected": "選択を削除",
        "Clear": "クリア",
        "Output folder:": "出力フォルダ:",
        "Normalize all": "すべて正規化",
        "Bakes body meshes into world space so AssetStudio/Blender export correctly. In-game rendering is unchanged.":
            "ボディメッシュをワールド空間にベイクし、AssetStudio/Blender で正しくエクスポートできるようにします。ゲーム内の描画は変わりません。",
        "Save fixed bundle": "修正済みバンドルを保存",
        "Select bundle": "バンドルを選択",
        "Select bundles": "バンドルを選択",
        "Select a folder of bundles": "バンドルのフォルダを選択",
        "Output folder": "出力フォルダ",
        "[error] choose an input bundle and an output path.\n": "[エラー] 入力バンドルと出力パスを選択してください。\n",
        "[error] add at least one bundle and choose an output folder.\n": "[エラー] バンドルを1つ以上追加し、出力フォルダを選択してください。\n",
        "\n[success] normalized — in-game render unchanged ✓\n": "\n[成功] 正規化完了 — ゲーム内描画は不変 ✓\n",
        "\n[warn] validation reported drift — inspect before use\n": "\n[警告] 検証で drift を検出 — 使用前に確認してください\n",
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


def _pip(p):
    for extra in (["--break-system-packages", "-q"], ["-q"]):
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", p] + extra, check=True)
            return True
        except Exception:
            pass
    return False


def ensure(mod, pip=None):
    try:
        return importlib.import_module(mod)
    except ImportError:
        _pip(pip or mod)
        return importlib.import_module(mod)


np = ensure("numpy")
UnityPy = ensure("UnityPy")

# vertex format -> bytes per component (Unity 2018 ChannelInfo formats)
FMT_BYTES = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}
ATTR_POSITION, ATTR_NORMAL, ATTR_TANGENT = 0, 1, 2


# --------------------------------------------------------------------------
# vertex stream IO (same layout logic as sifas_mesh_baker.py)
# --------------------------------------------------------------------------
def _align16(x):
    return (x + 15) & ~15


def _stream_layout(tree):
    vd = tree["m_VertexData"]
    vc = vd["m_VertexCount"]
    chans = vd["m_Channels"]
    by_stream = {}
    for ch in chans:
        if ch.get("dimension", 0):
            by_stream.setdefault(ch["stream"], []).append(ch)
    stride, start, cur = {}, {}, 0
    for s in sorted(by_stream):
        stride[s] = max(c["offset"] + c["dimension"] * FMT_BYTES[c["format"]]
                        for c in by_stream[s])
    for s in sorted(by_stream):
        start[s] = cur
        cur = _align16(cur + vc * stride[s])
    return vc, chans, stride, start


def _view(buf_u8, s, stride, start, vc):
    return buf_u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])


def _read_float_attr(buf_u8, chans, attr, stride, start, vc):
    ch = chans[attr]
    if ch.get("dimension", 0) == 0 or ch["format"] != 0:
        return None
    s, off, dim = ch["stream"], ch["offset"], ch["dimension"]
    raw = _view(buf_u8, s, stride, start, vc)[:, off:off + dim * 4]
    return raw.copy().view("<f4").reshape(vc, dim).astype(np.float64)


def _write_float_attr(buf_u8, arr, chans, attr, stride, start, vc):
    ch = chans[attr]
    s, off, dim = ch["stream"], ch["offset"], ch["dimension"]
    block = _view(buf_u8, s, stride, start, vc)
    packed = np.ascontiguousarray(arr[:, :dim], dtype="<f4").view(np.uint8)
    block[:, off:off + dim * 4] = packed.reshape(vc, dim * 4)


# --------------------------------------------------------------------------
# bone world transforms + bind poses
# --------------------------------------------------------------------------
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


def _bone_worlds(env):
    uid = {o.path_id: o for o in env.objects}
    tf = {}
    for o in env.objects:
        if o.type.name == "Transform":
            t = o.read_typetree()
            g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
            n = g.read().m_Name if g else None
            lp, lr, ls = t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"]
            tf[o.path_id] = (n,
                             ([lp['x'], lp['y'], lp['z']],
                              [lr['x'], lr['y'], lr['z'], lr['w']],
                              [ls['x'], ls['y'], ls['z']]),
                             t.get('m_Father', {}).get('m_PathID'),
                             [c['m_PathID'] for c in t.get('m_Children', [])])
    world = {}

    def cw(pid, P):
        n, (lp, lr, ls), fa, ch = tf[pid]
        M = P @ _trs(lp, lr, ls)
        world[n] = M
        for c in ch:
            if c in tf:
                cw(c, M)
    for pid, (n, _, fa, ch) in tf.items():
        if fa not in tf:
            cw(pid, np.eye(4))
    return world, uid


def _bindpose_to_mat(b):
    return np.array([[b['e00'], b['e01'], b['e02'], b['e03']],
                     [b['e10'], b['e11'], b['e12'], b['e13']],
                     [b['e20'], b['e21'], b['e22'], b['e23']],
                     [b['e30'], b['e31'], b['e32'], b['e33']]], float)


def _mat_to_bindpose(M, dst):
    for r in range(4):
        for c in range(4):
            dst["e%d%d" % (r, c)] = float(M[r, c])


def _approximately_one(value):
    # Match the native game's Mathf.Approximately(value, 1) check. The game
    # checks Vector4.sqrMagnitude, not magnitude, on serialized float32 data.
    value = float(value)
    return np.isfinite(value) and abs(value - 1.0) < 1e-6 * max(abs(value), 1.0)


def _native_bindpose_issue(bindposes):
    """Detect the game's binding rejection before changing any mesh bytes."""
    for index, pose in enumerate(bindposes):
        matrix = np.asarray(_bindpose_to_mat(pose), dtype=np.float32)
        if not np.isfinite(matrix).all():
            return f"bind pose {index} contains non-finite values"
        for column in range(3):
            squared = np.sum(matrix[:, column] * matrix[:, column], dtype=np.float32)
            if not _approximately_one(squared):
                return (f"bind pose {index}, column {column} has squared length {float(squared):.9g}; "
                        "the game requires approximately 1")
        if not _approximately_one(matrix[3, 3]):
            return f"bind pose {index} has an invalid homogeneous translation value"
        translation_squared = np.sum(matrix[:3, 3] * matrix[:3, 3], dtype=np.float32)
        if translation_squared > 12:
            return f"bind pose {index} has translation squared length {float(translation_squared):.9g}, above the game's limit 12"
    return None


def _mesh_root_issue(matrix):
    if not np.isfinite(matrix).all() or np.max(np.abs(matrix[3] - [0, 0, 0, 1])) > 1e-6:
        return "the mesh root is not a finite affine transform"
    rotation = matrix[:3, :3]
    scales = np.linalg.norm(rotation, axis=0)
    if (not all(_approximately_one(value * value) for value in scales)
            or np.max(np.abs(rotation.T @ rotation - np.eye(3))) > 1e-6
            or np.linalg.det(rotation) <= 0):
        return (f"mesh-root scale [{', '.join(f'{value:.9g}' for value in scales)}] or shear/reflection "
                "cannot be baked while preserving the game's unit bind-pose columns")
    return None


def _publish_bytes(path, raw):
    """An exception must not truncate an existing user output."""
    output = os.path.abspath(os.fspath(path))
    fd, temporary = tempfile.mkstemp(prefix=".sifas-normalize-", dir=os.path.dirname(output))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------
# core
# --------------------------------------------------------------------------
def normalize(in_path, out_path, verbose=True, *, report=None):
    def log(*a):
        if verbose:
            print(*a)

    env = UnityPy.load(os.fspath(in_path))
    world, uid = _bone_worlds(env)

    n_fixed, unchanged, skipped = 0, 0, []

    def skip(tree, reason):
        name = str(tree.get("m_Name", "Mesh"))[:256]
        skipped.append({"mesh": name, "reason": reason})
        log(f"[SKIPPED] {name!r}: {reason}. Original mesh bytes were kept.")

    for o in env.objects:
        if o.type.name != "SkinnedMeshRenderer":
            continue
        smr = o.read_typetree()
        bones = smr.get("m_Bones")
        if not bones:
            continue
        mesh_obj = uid.get(smr["m_Mesh"]["m_PathID"])
        if not mesh_obj:
            continue
        tree = mesh_obj.read_typetree()

        def bone_name(pid):
            x = uid.get(pid)
            if not x:
                return None
            tt = x.read_typetree()
            g = uid.get(tt.get("m_GameObject", {}).get("m_PathID"))
            return g.read().m_Name if g else None
        bnames = [bone_name(b["m_PathID"]) for b in bones]
        BP = tree.get("m_BindPose")
        if not BP or len(BP) != len(bnames):
            continue
        issue = _native_bindpose_issue(BP)
        if issue:
            skip(tree, "the original mesh already fails native binding validation: " + issue)
            continue

        # meshRoot = boneWorld · bindPose (constant per mesh); verify a few
        cand = []
        for i, nm in enumerate(bnames):
            if nm in world:
                cand.append(world[nm] @ _bindpose_to_mat(BP[i]))
            if len(cand) >= 4:
                break
        if not cand:
            continue
        meshRoot = cand[0]
        if max(np.abs(c - meshRoot).max() for c in cand) > 1e-3:
            skip(tree, "the mesh root differs between bones; this rig cannot be normalized safely")
            continue
        if np.abs(meshRoot - np.eye(4)).max() < 1e-5:
            unchanged += 1
            continue  # already world-space (e.g. hair/face)
        issue = _mesh_root_issue(meshRoot)
        if issue:
            skip(tree, issue)
            continue

        R = meshRoot[:3, :3]
        t = meshRoot[:3, 3]
        invMR = np.linalg.inv(meshRoot)
        planned_bindposes = copy.deepcopy(BP)
        for i, pose in enumerate(BP):
            # Validate the exact float32 values that will be serialized.
            planned = np.asarray(_bindpose_to_mat(pose) @ invMR, dtype=np.float32)
            _mat_to_bindpose(planned, planned_bindposes[i])
        issue = _native_bindpose_issue(planned_bindposes)
        if issue:
            skip(tree, "the planned normalized mesh would fail native binding validation: " + issue)
            continue

        # --- transform vertices ---
        vc, chans, stride, start = _stream_layout(tree)
        buf = bytearray(tree["m_VertexData"]["m_DataSize"])
        u8 = np.frombuffer(buf, np.uint8)
        pos = _read_float_attr(u8, chans, ATTR_POSITION, stride, start, vc)
        if pos is None:
            skip(tree, "position data is not a supported inline float vertex stream")
            continue
        pos_h = np.c_[pos, np.ones(len(pos))]
        _write_float_attr(u8, (pos_h @ meshRoot.T)[:, :3], chans, ATTR_POSITION, stride, start, vc)
        rotates = np.abs(R - np.eye(3)).max() > 1e-6
        if rotates:
            for attr in (ATTR_NORMAL, ATTR_TANGENT):
                a = _read_float_attr(u8, chans, attr, stride, start, vc)
                if a is None:
                    continue
                a2 = a.copy()
                a2[:, :3] = a[:, :3] @ R.T
                _write_float_attr(u8, a2, chans, attr, stride, start, vc)
        tree["m_VertexData"]["m_DataSize"] = bytes(buf)

        # --- fold meshRoot⁻¹ into bind poses ---
        tree["m_BindPose"] = planned_bindposes

        # --- shift local bounds ---
        ab = tree.get("m_LocalAABB")
        if ab:
            c = ab["m_Center"]
            nc = (meshRoot @ np.array([c['x'], c['y'], c['z'], 1.0]))[:3]
            c['x'], c['y'], c['z'] = float(nc[0]), float(nc[1]), float(nc[2])

        mesh_obj.save_typetree(tree)
        n_fixed += 1
        log(f"[ok] {tree.get('m_Name')!r}: baked mesh root {np.round(t,4)} into "
            f"{vc} verts; mesh now world-space")

    if n_fixed == 0:
        log(f"[NO CHANGES] original bundle kept unchanged; {len(skipped)} mesh(es) skipped."
            if skipped else "[info] nothing to normalize (all supported skinned meshes already world-space)")
        with open(in_path, "rb") as stream:
            output = stream.read()
    else:
        bf = list(env.files.values())[0]
        bf.mark_changed()
        output = bf.save(packer="original")
    _publish_bytes(out_path, output)
    if report is not None:
        report.clear()
        report.update(fixed=n_fixed, skipped=skipped, already_world_space=unchanged, changed=bool(n_fixed))
    log(f"[done] wrote {out_path} ({n_fixed} normalized; {len(skipped)} skipped)")
    return n_fixed


def validate(in_path, out_path, verbose=True):
    """Confirm in-game rendering is unchanged (a vertex's skinned world position
    is identical). Unchanged skipped meshes keep their original native data."""
    def world_of(path):
        env = UnityPy.load(os.fspath(path))
        world, uid = _bone_worlds(env)
        out = {}
        for o in env.objects:
            if o.type.name != "SkinnedMeshRenderer":
                continue
            smr = o.read_typetree()
            if not smr.get("m_Bones"):
                continue
            mesh = uid[smr["m_Mesh"]["m_PathID"]].read_typetree()
            BP = mesh.get("m_BindPose")
            if not BP:
                continue

            def bn(pid):
                x = uid.get(pid); tt = x.read_typetree()
                g = uid.get(tt.get("m_GameObject", {}).get("m_PathID"))
                return g.read().m_Name if g else None
            names = [bn(b["m_PathID"]) for b in smr["m_Bones"]]
            vc, chans, stride, start = _stream_layout(mesh)
            u8 = np.frombuffer(bytearray(mesh["m_VertexData"]["m_DataSize"]), np.uint8)
            pos = _read_float_attr(u8, chans, ATTR_POSITION, stride, start, vc)
            mr = world[names[0]] @ _bindpose_to_mat(BP[0])
            # rigid rest position = meshRoot · vertex (skinning collapses to this at rest)
            sample = pos[:50]
            rest = (np.c_[sample, np.ones(len(sample))] @ mr.T)[:, :3]
            mesh_obj = uid[smr["m_Mesh"]["m_PathID"]]
            out[mesh_obj.path_id] = (rest, np.abs(mr - np.eye(4)).max(),
                mesh_obj.get_raw_data(), mesh.get("m_Name"))
        return out
    a, b = world_of(in_path), world_of(out_path)
    ok = True
    for name in a:
        if name not in b:
            ok = False
            continue
        rest_err = np.abs(a[name][0] - b[name][0]).max()
        mr_after = b[name][1]
        unchanged = a[name][2] == b[name][2]
        good = rest_err < 1e-3 and (mr_after < 1e-4 or unchanged)
        ok = ok and good
        if verbose:
            print(f"[validate] {a[name][3]!r}: rest-position drift={rest_err:.2e}, "
                  f"meshRoot deviation after={mr_after:.2e} {'UNCHANGED' if unchanged else 'OK' if good else 'FAIL'}")
    return ok


def build_parser():
    p = argparse.ArgumentParser(
        description="Normalize a SIFAS model bundle so its meshes are in world space "
                    "and export to FBX correctly (in-game rendering unchanged).")
    p.add_argument("--in", dest="infile",
                   help="input .unity bundle (or a folder of bundles for batch)")
    p.add_argument("--out", help="output bundle (or output folder when --in is a folder)")
    p.add_argument("--gui", action="store_true", help="force the graphical interface")
    p.add_argument("-q", "--quiet", action="store_true")
    return p


# --------------------------------------------------------------------------
# GUI (optional; falls back to the CLI on Termux/headless)
# --------------------------------------------------------------------------
def gui_available():
    if os.path.isdir("/data/data/com.termux"):
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") \
            and not os.environ.get("WAYLAND_DISPLAY"):
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def normalize_batch(paths, out_dir, verbose=True):
    """Normalize many bundles into out_dir as <name>_fixed.unity. Returns (ok, fail)."""
    os.makedirs(out_dir, exist_ok=True)
    ok = fail = 0
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        out = os.path.join(out_dir, name + "_fixed.unity")
        if verbose:
            print(f"\n=== {os.path.basename(p)} ===")
        try:
            report = {}
            normalize(p, out, verbose=verbose, report=report)
            good = validate(p, out, verbose=verbose)
            if not report["changed"] and report["skipped"]:
                if verbose:
                    print(f"[SKIPPED] {os.path.basename(p)}: no safe mesh changes; original bundle copied unchanged")
                continue
            ok += 1 if good else 0
            fail += 0 if good else 1
        except Exception as ex:
            import traceback
            print("[error] " + "".join(traceback.format_exception(ex)))
            fail += 1
    if verbose:
        print(f"\n[batch] done: {ok} ok, {fail} failed -> {out_dir}")
    return ok, fail


def run_gui():
    import threading
    import queue
    import tkinter as tk
    from tkinter import ttk, filedialog, scrolledtext

    root = tk.Tk()
    root.geometry("760x600")

    # live language switching (no rebuild; just re-apply registered widget texts)
    _i18n_widgets = []   # (widget, key, kind)
    _tab_setters = []    # callables that re-set notebook tab labels

    def _reg(widget, key, kind="text"):
        _i18n_widgets.append((widget, key, kind))
        return widget

    def _apply_i18n():
        root.title(_tr("SIFAS Bundle Mesh Normalizer"))
        for w, key, kind in _i18n_widgets:
            try:
                w.configure(**{kind: _tr(key)})
            except Exception:
                pass
        for s in _tab_setters:
            try:
                s()
            except Exception:
                pass

    # language picker (top-right)
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

    msgq = queue.Queue()
    busy = {"n": 0}

    class _W:
        def write(self, s):
            if s:
                msgq.put(s)
        def flush(self):
            pass

    def run_thread(fn):
        busy["n"] += 1
        single_btn.configure(state="disabled"); batch_btn.configure(state="disabled")

        def wrap():
            old = sys.stdout
            sys.stdout = _W()
            try:
                fn()
            except Exception as ex:
                import traceback
                print("\n[error] " + "".join(traceback.format_exception(ex)))
            finally:
                sys.stdout = old

                def done():
                    busy["n"] -= 1
                    if busy["n"] == 0:
                        single_btn.configure(state="normal"); batch_btn.configure(state="normal")
                root.after(0, done)
        threading.Thread(target=wrap, daemon=True).start()

    nb = ttk.Notebook(root)
    nb.pack(fill="x", padx=10, pady=(10, 4))

    # ---------------- Single tab ----------------
    single = ttk.Frame(nb, padding=8); nb.add(single, text=_tr("Single"))
    _tab_setters.append(lambda: nb.tab(single, text=_tr("Single")))
    in_v, out_v = tk.StringVar(), tk.StringVar()

    def suggest_out(*_):
        if not out_v.get() and in_v.get():
            base, ext = os.path.splitext(in_v.get())
            out_v.set(base + "_fixed" + (ext or ".unity"))

    def pick(var, save=False):
        ft = [("Unity bundle", "*.unity *.unity3d"), ("All files", "*.*")]
        path = (filedialog.asksaveasfilename(title=_tr("Save fixed bundle"),
                                             defaultextension=".unity", filetypes=ft) if save
                else filedialog.askopenfilename(title=_tr("Select bundle"), filetypes=ft))
        if path:
            var.set(path); suggest_out()

    for i, (label, var, save) in enumerate(
            [("Input .unity bundle", in_v, False), ("Output (fixed) bundle", out_v, True)]):
        _reg(ttk.Label(single, text=_tr(label), width=20), label).grid(row=i, column=0, sticky="w", pady=3)
        ttk.Entry(single, textvariable=var, width=58).grid(row=i, column=1, padx=4)
        _reg(ttk.Button(single, text=_tr("Browse…"),
                        command=lambda v=var, s=save: pick(v, s)), "Browse…").grid(row=i, column=2)

    def single_go():
        s, o = in_v.get().strip(), out_v.get().strip()
        if not (s and o):
            msgq.put(_tr("[error] choose an input bundle and an output path.\n")); return
        log_box.delete("1.0", "end")

        def job():
            report = {}
            normalize(s, o, verbose=True, report=report)
            ok = validate(s, o, verbose=True)
            if not report["changed"] and report["skipped"]:
                print("[SKIPPED] No safe mesh changes; the original bundle was copied unchanged.")
            elif report["skipped"]:
                print(f"[done] normalized {report['fixed']} mesh(es); skipped {len(report['skipped'])}. Read the specific skip reasons above.")
            else:
                print(_tr("\n[success] normalized — in-game render unchanged ✓\n") if ok
                      else _tr("\n[warn] validation reported drift — inspect before use\n"))
        run_thread(job)

    single_btn = _reg(ttk.Button(single, text=_tr("Normalize"), command=single_go), "Normalize")
    single_btn.grid(row=2, column=1, sticky="e", pady=6)

    # ---------------- Batch tab ----------------
    batch = ttk.Frame(nb, padding=8); nb.add(batch, text=_tr("Batch"))
    _tab_setters.append(lambda: nb.tab(batch, text=_tr("Batch")))
    _reg(ttk.Label(batch, text=_tr("Bundles (Add files… or Add folder…):")),
         "Bundles (Add files… or Add folder…):").grid(row=0, column=0, columnspan=4, sticky="w")
    lb = tk.Listbox(batch, height=8, width=74, selectmode="extended")
    lb.grid(row=1, column=0, columnspan=4, sticky="we", pady=3)

    def add_paths(paths):
        cur = set(lb.get(0, "end"))
        for p in paths:
            if os.path.isdir(p):
                for fn in sorted(os.listdir(p)):
                    full = os.path.join(p, fn)
                    if fn.lower().endswith((".unity", ".unity3d")) and full not in cur:
                        lb.insert("end", full); cur.add(full)
            elif p not in cur:
                lb.insert("end", p); cur.add(p)

    def add_files():
        add_paths(filedialog.askopenfilenames(
            title=_tr("Select bundles"),
            filetypes=[("Unity bundle", "*.unity *.unity3d"), ("All files", "*.*")]))

    def add_folder():
        d = filedialog.askdirectory(title=_tr("Select a folder of bundles"))
        if d:
            add_paths([d])

    _reg(ttk.Button(batch, text=_tr("Add files…"), command=add_files), "Add files…").grid(row=2, column=0, sticky="w")
    _reg(ttk.Button(batch, text=_tr("Add folder…"), command=add_folder), "Add folder…").grid(row=2, column=1, sticky="w")
    _reg(ttk.Button(batch, text=_tr("Remove selected"),
                    command=lambda: [lb.delete(i) for i in reversed(lb.curselection())]), "Remove selected").grid(row=2, column=2, sticky="w")
    _reg(ttk.Button(batch, text=_tr("Clear"), command=lambda: lb.delete(0, "end")), "Clear").grid(row=2, column=3, sticky="w")

    bout_v = tk.StringVar()
    _reg(ttk.Label(batch, text=_tr("Output folder:"), width=20), "Output folder:").grid(row=3, column=0, sticky="w", pady=(8, 3))
    ttk.Entry(batch, textvariable=bout_v, width=58).grid(row=3, column=1, columnspan=2, padx=4, sticky="we")
    _reg(ttk.Button(batch, text=_tr("Browse…"),
                    command=lambda: bout_v.set(filedialog.askdirectory(title=_tr("Output folder")) or bout_v.get())
                    ), "Browse…").grid(row=3, column=3)

    def batch_go():
        files = list(lb.get(0, "end"))
        outdir = bout_v.get().strip()
        if not files or not outdir:
            msgq.put(_tr("[error] add at least one bundle and choose an output folder.\n")); return
        log_box.delete("1.0", "end")
        run_thread(lambda: normalize_batch(files, outdir, verbose=True))

    batch_btn = _reg(ttk.Button(batch, text=_tr("Normalize all"), command=batch_go), "Normalize all")
    batch_btn.grid(row=4, column=1, sticky="e", pady=6)

    # ---------------- shared log ----------------
    _reg(ttk.Label(root, padding=(10, 0), foreground="#555",
                   text=_tr("Bakes body meshes into world space so AssetStudio/Blender export "
                            "correctly. In-game rendering is unchanged.")),
         "Bakes body meshes into world space so AssetStudio/Blender export correctly. In-game rendering is unchanged.").pack(anchor="w")
    log_box = scrolledtext.ScrolledText(root, height=16, wrap="word", font=("TkFixedFont", 9))
    log_box.pack(fill="both", expand=True, padx=10, pady=8)

    def drain():
        try:
            while True:
                log_box.insert("end", msgq.get_nowait()); log_box.see("end")
        except queue.Empty:
            pass
        root.after(80, drain)

    drain()
    root.mainloop()


def main(argv=None):
    a = build_parser().parse_args(argv)
    want_gui = a.gui or not (a.infile or a.out)
    if want_gui and gui_available():
        run_gui()
        return
    if a.gui:
        print("[info] no graphical display available; using CLI.")
    if not (a.infile and a.out):
        build_parser().error("--in and --out are required "
                             "(or run with no arguments for the GUI)")
    # batch: --in is a directory -> normalize every bundle into the --out directory
    if os.path.isdir(a.infile):
        files = [os.path.join(a.infile, f) for f in sorted(os.listdir(a.infile))
                 if f.lower().endswith((".unity", ".unity3d"))]
        normalize_batch(files, a.out, verbose=not a.quiet)
        return
    report = {}
    normalize(a.infile, a.out, verbose=not a.quiet, report=report)
    if not validate(a.infile, a.out, verbose=not a.quiet):
        print("[warn] validation reported drift; inspect before use", file=sys.stderr)
    elif not report["changed"] and report["skipped"]:
        print("[SKIPPED] No safe mesh changes; the original bundle was copied unchanged.")
    elif report["skipped"]:
        print(f"[done] normalized {report['fixed']} mesh(es); skipped {len(report['skipped'])}. Read the specific skip reasons above.")
    else:
        print("[success] bundle normalized; in-game render unchanged, exports world-space")


if __name__ == "__main__":
    main()
