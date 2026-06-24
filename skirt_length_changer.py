#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skirt_length_changer.py
=======================
LiveCoreMemberNodeScaling scaler for skirt physics bones (skirt length/volume).

It scales the Transforms of the skirt dyna bones (SkirtA1_Dyna, LeftSkirtB1_Dyna,
...) via each character's LiveCoreMemberNodeScaling.scaleValues entry, exactly
like the original tool.

New in this version (the same "extracted -> modded" workflow as the asset
extractor / breast tuner):
  * Library mode (Termux text menu only): pick a decrypted asset bundle from
    <sukusta>/extracted (or <sukusta>/modded), scale its skirt bones, and export
    the result into <sukusta>/modded, mirroring the source sub-path. The original
    is never touched. Multi-select is supported.
  * Runs a GUI on desktop (Mac/Windows) or a text menu on Termux / headless,
    auto-detected. (tkinter is imported lazily so the script still runs where
    tkinter isn't installed, e.g. Termux.) The desktop GUI is just single/batch
    with direct file pickers - no Library tab, since the sukusta folders live on
    the Termux device.

Default paths (override the base with the SUKUSTA_DIR env var):
  Termux : ~/storage/downloads/sukusta/{extracted,modded}
  else   : ~/sukusta/{extracted,modded}
"""

import argparse
import os
import sys
from pathlib import Path

# Language choice is shared & persisted via a small JSON config (no extra
# module), so a single copied file still works and remembers the choice across
# all the SIFAS tools.
import os as _os
import json as _json


class _LangStore:
    @staticmethod
    def _path():
        if _os.name == "nt":
            base = _os.environ.get("APPDATA") or _os.path.join(_os.path.expanduser("~"), "AppData", "Roaming")
        else:
            base = _os.environ.get("XDG_CONFIG_HOME") or _os.path.join(_os.path.expanduser("~"), ".config")
        return _os.path.join(base, "sifas_modding_tools", "config.json")

    def get_language(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                return _json.load(f).get("language")
        except Exception:
            return None

    def set_language(self, code):
        try:
            p = self._path()
            _os.makedirs(_os.path.dirname(p), exist_ok=True)
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

# --- self-contained translations (English source = key; English fallback) -----
_LANG_NAMES = (("en", "English"), ("ko", "한국어"), ("ja", "日本語"))
_SKIRT_NOTE = ("Skirt length/volume usually scales uniformly, so x, y, z move "
               "together. Use the factor above; the per-axis fields are for fine cases.")
_TRANSLATIONS = {
    "ko": {
        "Language": "언어",
        "Skirt Length Changer": "치마 길이 변경기",
        "Single file": "단일 파일",
        "Batch (folder)": "일괄 (폴더)",
        "Input bundle": "입력 번들",
        "Output path": "출력 경로",
        "Input folder": "입력 폴더",
        "Output folder": "출력 폴더",
        "prefix": "접두사",
        "suffix": "접미사",
        "Browse": "찾아보기",
        "Run (single)": "실행 (단일)",
        "Run (batch)": "실행 (일괄)",
        "Append skirt length to filenames (e.g. _skirt085)": "파일명에 치마 길이 추가 (예: _skirt085)",
        "Skirt scale options": "치마 스케일 옵션",
        "Skirt GO name patterns (comma/space, contains match)": "치마 GameObject 이름 패턴 (쉼표/공백, 부분 일치)",
        "Uniform scale  (x = y = z - the usual skirt change)": "균일 스케일 (x = y = z - 일반적인 치마 변경)",
        "factor:": "배율:",
        "Apply": "적용",
        "Shorter 0.85": "짧게 0.85",
        "Longer 1.15": "길게 1.15",
        "Reset 1.0": "초기화 1.0",
        "Advanced - per-axis set (x, y, z)  -  blank = leave that axis": "고급 - 축별 설정 (x, y, z) - 비우면 해당 축 유지",
        "Advanced - add delta (dx, dy, dz)  -  added to current value": "고급 - 델타 추가 (dx, dy, dz) - 현재 값에 더함",
        _SKIRT_NOTE: "치마 길이/볼륨은 보통 균일하게 스케일되어 x, y, z가 함께 움직입니다. 위의 배율을 사용하세요. 축별 필드는 세밀한 조정용입니다.",
        "Result": "결과",
        "Error": "오류",
        "Select input bundle": "입력 번들 선택",
        "Save output bundle": "출력 번들 저장",
        "Select folder": "폴더 선택",
        "Please set input and output paths.": "입력 및 출력 경로를 설정하세요.",
        "Please set input and output folders.": "입력 및 출력 폴더를 설정하세요.",
    },
    "ja": {
        "Language": "言語",
        "Skirt Length Changer": "スカート丈チェンジャー",
        "Single file": "単一ファイル",
        "Batch (folder)": "一括（フォルダ）",
        "Input bundle": "入力バンドル",
        "Output path": "出力パス",
        "Input folder": "入力フォルダ",
        "Output folder": "出力フォルダ",
        "prefix": "接頭辞",
        "suffix": "接尾辞",
        "Browse": "参照",
        "Run (single)": "実行（単一）",
        "Run (batch)": "実行（一括）",
        "Append skirt length to filenames (e.g. _skirt085)": "ファイル名にスカート丈を付加（例: _skirt085）",
        "Skirt scale options": "スカートスケールオプション",
        "Skirt GO name patterns (comma/space, contains match)": "スカートGameObject名パターン（カンマ/空白、部分一致）",
        "Uniform scale  (x = y = z - the usual skirt change)": "均一スケール（x = y = z - 通常のスカート変更）",
        "factor:": "倍率:",
        "Apply": "適用",
        "Shorter 0.85": "短く 0.85",
        "Longer 1.15": "長く 1.15",
        "Reset 1.0": "リセット 1.0",
        "Advanced - per-axis set (x, y, z)  -  blank = leave that axis": "詳細 - 軸ごとに設定 (x, y, z) - 空欄ならその軸は維持",
        "Advanced - add delta (dx, dy, dz)  -  added to current value": "詳細 - デルタ加算 (dx, dy, dz) - 現在値に加算",
        _SKIRT_NOTE: "スカートの丈/ボリュームは通常均一にスケールし、x, y, z は一緒に動きます。上の倍率を使ってください。軸ごとのフィールドは細かい調整用です。",
        "Result": "結果",
        "Error": "エラー",
        "Select input bundle": "入力バンドルを選択",
        "Save output bundle": "出力バンドルを保存",
        "Select folder": "フォルダを選択",
        "Please set input and output paths.": "入力と出力のパスを設定してください。",
        "Please set input and output folders.": "入力と出力のフォルダを設定してください。",
    },
}


def _normalize_lang(code):
    c = str(code or "").strip().lower().replace("-", "_").split("_")[0].split(".")[0]
    if c in ("ko", "kr", "kor"):
        return "ko"
    if c in ("ja", "jp", "jpn"):
        return "ja"
    return "en"


# initial language: shared/persisted choice if available, else SIFAS_LANG, else English
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

# UnityPy is imported lazily so this file runs even before it's installed
# (and so headless/Termux startup doesn't require tkinter either).
UnityPy = None


def _run_cmd(cmd):
    """Run a command, returning True on success (silent on failure)."""
    import subprocess
    try:
        subprocess.check_call(cmd)
        return True
    except Exception:
        return False


def _pip_install(*pkgs):
    return _run_cmd([sys.executable, "-m", "pip", "install", *pkgs])


def _ensure_pillow_on_termux():
    """Install Termux's prebuilt Pillow so UnityPy (which imports PIL) installs.
    On Termux `pip install Pillow` fails to compile (no libjpeg)."""
    try:
        __import__("PIL")
        return True
    except Exception:
        pass
    print("[setup] Installing image library (Pillow) via Termux packages - "
          "one-time, no action needed...")
    ok = (_run_cmd(["pkg", "install", "-y", "python-pillow"])
          or _run_cmd(["apt", "install", "-y", "python-pillow"]))
    if not ok:
        _run_cmd(["apt", "update", "-y"])
        ok = (_run_cmd(["pkg", "install", "-y", "python-pillow"])
              or _run_cmd(["apt", "install", "-y", "python-pillow"]))
    try:
        __import__("PIL")
        return True
    except Exception:
        return False


def _unitypy_install_help():
    print("\n" + "=" * 64)
    print("Automatic setup couldn't finish installing UnityPy.")
    if is_termux():
        print(
            "On Termux, UnityPy needs the prebuilt Pillow package. Please run\n"
            "these two lines once, then start the tool again:\n"
            "\n"
            "    pkg install python-pillow\n"
            "    pip install UnityPy\n"
            "\n"
            "If it still fails, also run:  pkg install libjpeg-turbo zlib\n"
        )
    else:
        print("Please install it manually, then re-run:\n    pip install UnityPy\n")
    print("=" * 64)


def ensure_unitypy():
    """Load UnityPy, auto-installing it (and its prerequisites) on first run.
    'Just works' with no manual steps; on Termux it installs the prebuilt
    Pillow via pkg before pip-installing UnityPy. Falls back to clear guidance
    (instead of crashing) only if every automatic attempt fails."""
    global UnityPy
    if UnityPy is not None:
        return
    try:
        import UnityPy as _u
        UnityPy = _u
        return
    except ImportError:
        pass
    print("[setup] First-time setup: installing UnityPy. This can take a few "
          "minutes on the first run - please wait...")
    if is_termux():
        _ensure_pillow_on_termux()
    if not _pip_install("UnityPy"):
        if is_termux():
            _ensure_pillow_on_termux()
            _pip_install("UnityPy")
    try:
        import UnityPy as _u
        UnityPy = _u
        print("[setup] Done.")
        return
    except ImportError:
        _unitypy_install_help()
        raise SystemExit(1)


def is_termux():
    if "com.termux" in (os.environ.get("PREFIX", "") + os.environ.get("HOME", "")):
        return True
    return os.path.isdir("/data/data/com.termux")


def gui_available():
    if is_termux():
        return False
    try:
        import tkinter  # noqa: F401  (availability probe)
    except Exception:
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return False
    return True


# ==========================================================================
# Typetree helpers  (unchanged logic from the original)
# ==========================================================================
def read_tree_safe(obj):
    data = obj.read()
    if hasattr(obj, "read_typetree"):
        try:
            return obj.read_typetree(), data, "obj"
        except Exception:
            pass
    if hasattr(data, "read_typetree"):
        return data.read_typetree(), data, "data"
    raise AttributeError("typetree unavailable on both obj and data")


def save_tree_safe(obj, data, tree, where):
    if where == "obj" and hasattr(obj, "save_typetree"):
        obj.save_typetree(tree); return
    if hasattr(data, "save_typetree"):
        data.save_typetree(tree); return
    raise AttributeError("no save_typetree on obj or data")


def type_name(obj):
    t = getattr(obj, "type", None)
    return getattr(t, "name", str(t))


def type_id(obj):
    t = getattr(obj, "type", None)
    return getattr(t, "value", None)


def is_obj_type(obj, names_or_ids):
    tn = type_name(obj); ti = type_id(obj)
    for v in names_or_ids:
        if isinstance(v, str) and tn == v:
            return True
        if isinstance(v, int) and ti == v:
            return True
    return False


def get_from_tree(tree, key):
    if isinstance(tree, dict):
        if key in tree:
            return tree[key]
        base = tree.get("Base")
        if isinstance(base, dict) and key in base:
            return base[key]
    return None


def ensure_dict(tree, key):
    v = get_from_tree(tree, key)
    if v is None or not isinstance(v, dict):
        return None
    return v


def ensure_list(tree, key):
    v = get_from_tree(tree, key)
    if v is None or not isinstance(v, list):
        return None
    return v


def set_vec3(vec, x=None, y=None, z=None):
    if not isinstance(vec, dict):
        return False
    changed = False
    if x is not None:
        vec["x"] = float(x); changed = True
    if y is not None:
        vec["y"] = float(y); changed = True
    if z is not None:
        vec["z"] = float(z); changed = True
    return changed


def add_vec3(vec, dx=0.0, dy=0.0, dz=0.0):
    if not isinstance(vec, dict):
        return False
    vec["x"] = float(vec.get("x") or 0.0) + float(dx)
    vec["y"] = float(vec.get("y") or 0.0) + float(dy)
    vec["z"] = float(vec.get("z") or 0.0) + float(dz)
    return True


# ==========================================================================
# Index builders / LiveCore helpers  (unchanged logic from the original)
# ==========================================================================
def build_obj_index(env):
    obj_by_pid = {}
    for o in env.objects:
        obj_by_pid[o.path_id] = o
        obj_by_pid[-o.path_id] = o
    return obj_by_pid


def find_gameobject_by_patterns(env, patterns_ci):
    """Return [(name, go_obj), ...] for GameObjects whose name CONTAINS any of
    the lowercase patterns (substring match)."""
    out = []
    for o in env.objects:
        if not is_obj_type(o, ("GameObject", 1)):
            continue
        try:
            tree, _, _ = read_tree_safe(o)
        except Exception:
            continue
        nm = None
        if isinstance(tree, dict):
            if "m_Name" in tree and isinstance(tree["m_Name"], str):
                nm = tree["m_Name"]
            elif isinstance(tree.get("Base"), dict) and isinstance(tree["Base"].get("m_Name"), str):
                nm = tree["Base"]["m_Name"]
        if not nm:
            continue
        nml = nm.lower()
        if any(p in nml for p in patterns_ci):
            out.append((nm, o))
    return out


def list_components_pids(go_tree):
    comps = []
    if not isinstance(go_tree, dict):
        return comps
    arr = get_from_tree(go_tree, "m_Component")
    if isinstance(arr, list):
        for elem in arr:
            if isinstance(elem, dict):
                pair = elem.get("data") or elem
                if isinstance(pair, dict):
                    p = pair.get("component") or pair
                    if isinstance(p, dict):
                        pid = p.get("m_PathID") or p.get("pathID")
                        if isinstance(pid, int):
                            comps.append(pid)
    return comps


def get_transform_of_go(env, obj_by_pid, go_obj):
    try:
        go_tree, _, _ = read_tree_safe(go_obj)
    except Exception:
        return None
    for pid in list_components_pids(go_tree):
        tobj = obj_by_pid.get(pid) or obj_by_pid.get(-pid)
        if tobj and is_obj_type(tobj, ("Transform", 4)):
            return tobj
    return None


def is_livecore_scaling_tree(tree, obj_by_pid):
    if not isinstance(tree, dict):
        return False
    has_scale = isinstance(get_from_tree(tree, "scaleValues"), list)
    if not has_scale:
        return False
    p = get_from_tree(tree, "m_Script")
    if isinstance(p, dict):
        pid = p.get("m_PathID") or p.get("pathID")
        if isinstance(pid, int):
            sobj = obj_by_pid.get(pid) or obj_by_pid.get(-pid)
            if sobj:
                try:
                    st, _, _ = read_tree_safe(sobj)
                    for key in ("m_ClassName", "className", "m_Name", "name"):
                        v = get_from_tree(st, key)
                        if isinstance(v, str) and "LiveCoreMemberNodeScaling".lower() in v.lower():
                            return True
                except Exception:
                    pass
    return has_scale


def detect_entry_style(scale_list):
    for elem in scale_list:
        if isinstance(elem, dict) and "data" in elem and isinstance(elem["data"], dict):
            return "wrapped"
    return "raw"


def get_node_from_elem(elem):
    if isinstance(elem, dict) and "data" in elem and isinstance(elem["data"], dict):
        return elem["data"], "wrapped"
    return elem, "raw"


def make_elem_for_node(node, style):
    return {"data": node} if style == "wrapped" else node


def ensure_scale_entry(scale_list, target_pid):
    style = detect_entry_style(scale_list)
    for i, elem in enumerate(scale_list):
        node, estyle = get_node_from_elem(elem)
        tgt = node.get("target") or {}
        pid = tgt.get("m_PathID") or tgt.get("pathID")
        if isinstance(pid, int) and (pid == target_pid or pid == -target_pid):
            return node, i, estyle, False
    new_node = {
        "target": {"m_FileID": 0, "m_PathID": int(target_pid)},
        "originValue": {"x": 1.0, "y": 1.0, "z": 1.0},
        "scaledValue": {"x": 1.0, "y": 1.0, "z": 1.0},
    }
    scale_list.append(make_elem_for_node(new_node, style))
    return new_node, len(scale_list) - 1, style, True


# ==========================================================================
# Core modify  (original logic, + write_log_file flag + lazy UnityPy)
# ==========================================================================
def modify_skirt_scaling(
    in_path: Path,
    out_path: Path,
    target_go_patterns,   # e.g. ["skirta1_dyna", "leftskirtb1_dyna", ...]
    set_xyz,              # (x,y,z) absolute (each may be None to skip), or None
    add_dxyz,             # (dx,dy,dz) increment/decrement
    write_log_file=True,
):
    ensure_unitypy()
    env = UnityPy.load(str(in_path))
    obj_by_pid = build_obj_index(env)

    logs = []
    changed = 0
    scanned = 0

    targets = find_gameobject_by_patterns(env, [p.lower() for p in target_go_patterns])
    if not targets:
        logs.append(f"[MISS] No GameObjects matched: {target_go_patterns}")

    go_to_tr = []
    for nm, go in targets:
        tr = get_transform_of_go(env, obj_by_pid, go)
        if tr:
            go_to_tr.append((nm, tr))
    if targets and not go_to_tr:
        logs.append("[MISS] No Transforms found for matched GameObjects")

    tr_scale_cache = {}
    for nm, tr in go_to_tr:
        try:
            tr_tree, _, _ = read_tree_safe(tr)
            tr_scale_cache[tr.path_id] = get_from_tree(tr_tree, "m_LocalScale") or {"x": 1, "y": 1, "z": 1}
        except Exception:
            tr_scale_cache[tr.path_id] = {"x": 1, "y": 1, "z": 1}

    for obj in env.objects:
        if not is_obj_type(obj, ("MonoBehaviour", 114)):
            continue
        try:
            tree, data, where = read_tree_safe(obj)
        except Exception as e:
            logs.append(f"[READ_FAIL] pid={obj.path_id} err={e}")
            continue
        if not is_livecore_scaling_tree(tree, obj_by_pid):
            continue

        scale_list = ensure_list(tree, "scaleValues")
        if scale_list is None:
            continue

        for nm, tr in go_to_tr:
            target_pid = tr.path_id
            node, idx, style, created = ensure_scale_entry(scale_list, target_pid)

            if created:
                ov = ensure_dict(node, "originValue")
                if ov:
                    cur = tr_scale_cache.get(target_pid, {"x": 1, "y": 1, "z": 1})
                    set_vec3(ov, x=cur.get("x"), y=cur.get("y"), z=cur.get("z"))

            sv = ensure_dict(node, "scaledValue")
            if not sv:
                logs.append(f"[SKIP] livecore={obj.path_id} go='{nm}' no scaledValue")
                continue

            before = (sv.get("x"), sv.get("y"), sv.get("z"))

            if set_xyz is not None:
                set_vec3(sv, x=set_xyz[0], y=set_xyz[1], z=set_xyz[2])
            dx, dy, dz = add_dxyz
            if any(abs(v) > 0 for v in (dx, dy, dz)):
                add_vec3(sv, dx=dx, dy=dy, dz=dz)

            after = (sv.get("x"), sv.get("y"), sv.get("z"))

            # degenerate-scale guard: safe body-scale band is 0.2-2.5; <=0 collapses or
            # inverts the node (inside-out skirt). Warn, don't block.
            _bad = [round(a, 3) for a in after if a is not None and not (0.2 <= a <= 2.5)]
            if _bad:
                logs.append(f"[SCALE_WARN] livecore={obj.path_id} go='{nm}' scaledValue {after} has "
                            f"component(s) {_bad} outside the safe range 0.2-2.5 (<=0 collapses/inverts "
                            f"the node); skirt/skinning may break in-game.")

            try:
                scale_list[idx] = make_elem_for_node(node, style)
                save_tree_safe(obj, data, tree, where)
                changed += 1; scanned += 1
                logs.append(f"[OK] livecore={obj.path_id} go='{nm}' pid={target_pid} "
                            f"style={style} {before} -> {after}")
            except KeyError as e:
                alt_style = "wrapped" if style == "raw" else "raw"
                try:
                    scale_list[idx] = make_elem_for_node(node, alt_style)
                    save_tree_safe(obj, data, tree, where)
                    changed += 1; scanned += 1
                    logs.append(f"[OK-ALT] livecore={obj.path_id} go='{nm}' pid={target_pid} "
                                f"style={alt_style} {before} -> {after}")
                except Exception as e2:
                    logs.append(f"[SAVE_FAIL] livecore={obj.path_id} go='{nm}' pid={target_pid} err={e2} (alt after {e})")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(env.file.save(packer="lz4"))

    header = [
        f"Scanned pairs: {scanned}",
        f"Changed entries: {changed}",
        (f"Targets: {', '.join([nm for nm, _ in go_to_tr])}" if go_to_tr else "Targets: -"),
        f"Set xyz: {set_xyz}",
        f"Add dxyz: {add_dxyz}",
    ]
    if write_log_file:
        (out_path.with_suffix(out_path.suffix + ".skirt_log.txt")).write_text(
            "\n".join(header + logs), encoding="utf-8")

    return scanned, changed, header + logs


def name_transform_for_output(src_file: Path, out_root: Path, src_root: Path, prefix: str, suffix: str):
    rel = src_file.relative_to(src_root)
    return (out_root / rel.parent / f"{prefix}{src_file.stem}{suffix}{src_file.suffix}")


# ==========================================================================
# Library helpers (elichika sukusta: extracted -> modded)
# ==========================================================================
# Default skirt physics-bone GameObjects (LiveCore scale targets), contains-match.
DEFAULT_SKIRT_PATTERNS = [
    "SkirtA1_Dyna", "SkirtE1_Dyna",
    "LeftSkirtB1_Dyna", "RightSkirtB1_Dyna",
    "LeftSkirtC1_Dyna", "RightSkirtC1_Dyna",
    "LeftSkirtD1_Dyna", "RightSkirtD1_Dyna",
]


def default_sukusta_dir(name):
    """Default path for sukusta/<name> ('extracted' or 'modded').
    Override the base with the SUKUSTA_DIR env var. Termux uses shared Downloads."""
    base = os.environ.get("SUKUSTA_DIR")
    if base:
        return os.path.join(os.path.expanduser(base), name)
    if is_termux():
        return os.path.expanduser(f"~/storage/downloads/sukusta/{name}")
    return os.path.expanduser(f"~/sukusta/{name}")


def is_unity_bundle(path):
    """True if the file starts with the UnityFS magic (an asset bundle)."""
    try:
        with open(path, "rb") as f:
            return f.read(7) == b"UnityFS"
    except Exception:
        return False


def find_asset_bundles(root):
    """Recursively list asset bundles (UnityFS files) under root. Returns Paths."""
    root = Path(os.path.expanduser(str(root)))
    if not root.exists():
        return []
    return [p for p in sorted(root.rglob("*")) if p.is_file() and is_unity_bundle(p)]


def modded_output_path(src_path, src_root, modded_root, extra_suffix=""):
    """Output path under modded_root, mirroring src_path's sub-path relative to
    src_root (falls back to the bare filename if not under src_root)."""
    src_path = Path(os.path.expanduser(str(src_path)))
    modded_root = Path(os.path.expanduser(str(modded_root)))
    try:
        rel = src_path.resolve().relative_to(Path(os.path.expanduser(str(src_root))).resolve())
    except Exception:
        rel = Path(src_path.name)
    return modded_root / rel.parent / (rel.stem + extra_suffix + rel.suffix)


def _skirt_suffix(set_xyz, add_dxyz):
    """A short filename tag describing the skirt change, e.g. '_skirt085' for a
    0.85x (shorter) uniform scale, '_skirt115' for 1.15x (longer), '_skirt100'
    for reset. Non-uniform set -> per-axis '_skirt085_100_120'; add-delta mode
    -> '_skirtadd+10'. Returns '' when there's no meaningful change to encode."""
    def pct(v):
        return f"{int(round(float(v) * 100)):03d}"

    if set_xyz is not None:
        x, y, z = set_xyz
        vals = [v for v in (x, y, z) if v is not None]
        if not vals:
            pass  # all axes blank -> fall through to add-delta / empty
        elif len(vals) == 3 and abs(x - y) < 1e-6 and abs(y - z) < 1e-6:
            return f"_skirt{pct(x)}"                       # uniform (the usual case)
        else:
            parts = [pct(v) if v is not None else "x" for v in (x, y, z)]
            return "_skirt" + "_".join(parts)             # per-axis

    if add_dxyz and any(abs(float(v)) > 1e-9 for v in add_dxyz):
        dx, dy, dz = add_dxyz
        # vertical delta is the meaningful one for skirt length; tag it
        d = dy if abs(dy) > 1e-9 else (dx if abs(dx) > 1e-9 else dz)
        return f"_skirtadd{int(round(d * 100)):+d}"
    return ""


def run_library_mod_one(in_path, out_path, patterns, set_xyz, add_dxyz):
    """Apply skirt scaling to in_path and write to out_path. Handles in-place
    overwrite safely (temp + replace) and writes no .log sidecar. Returns a
    one-line summary."""
    in_path = Path(in_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    same = False
    try:
        same = in_path.resolve() == out_path.resolve()
    except Exception:
        pass
    write_path = out_path.with_name(out_path.name + ".tmp_mod") if same else out_path
    scanned, changed, _ = modify_skirt_scaling(
        in_path, write_path, patterns, set_xyz, add_dxyz, write_log_file=False)
    if same:
        os.replace(write_path, out_path)
    return f"scanned={scanned}, changed={changed}"


# ==========================================================================
# Text menu (Termux / headless)
# ==========================================================================
def _ask(prompt, default=""):
    s = input(f"{prompt} [{default}]: ").strip() if default != "" else input(f"{prompt}: ").strip()
    return s if s else default


def _ask_path(prompt, must_exist=False):
    while True:
        s = input(f"{prompt}: ").strip().strip('"').strip("'")
        if not s:
            return ""
        s = os.path.expanduser(s)
        if must_exist and not os.path.exists(s):
            print("  path does not exist, try again (blank to cancel).")
            continue
        return s


def _ask_yesno(prompt, default=True):
    d = "Y/n" if default else "y/N"
    s = input(f"{prompt} [{d}]: ").strip().lower()
    if s == "":
        return default
    return s in ("y", "yes")


def _ask_float(prompt, default, allow_blank=False):
    while True:
        s = input(f"{prompt} [{default}]: ").strip()
        if s == "":
            if allow_blank and default == "":
                return None
            s = default
        try:
            return float(s)
        except ValueError:
            print("  please enter a number.")


def _parse_multi_select(s, n):
    """Parse '3', '1,4-8', 'all' -> sorted 0-based indices (1..n)."""
    s = (s or "").strip().lower()
    if s in ("all", "*"):
        return list(range(n))
    out = set()
    for part in s.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                a, b = int(a), int(b)
            except ValueError:
                continue
            for k in range(min(a, b), max(a, b) + 1):
                if 1 <= k <= n:
                    out.add(k - 1)
        else:
            try:
                k = int(part)
            except ValueError:
                continue
            if 1 <= k <= n:
                out.add(k - 1)
    return sorted(out)


def _box(title):
    line = "=" * (len(title) + 8)
    return f"{line}\n==  {title}  ==\n{line}"


def _menu_choose_skirt_scale():
    """Return (set_xyz, add_dxyz). Skirt length/volume usually scales UNIFORMLY
    (x = y = z), so the default is a single factor applied to all three axes."""
    print("\nHow do you want to change the skirt scale?")
    print("  1) Uniform scale   (one factor for x, y, z - the usual way)")
    print("  2) Quick: shorter  (0.85, uniform)")
    print("  3) Quick: longer   (1.15, uniform)")
    print("  4) Per-axis set    (x, y, z; blank = leave that axis)")
    print("  5) Add delta       (dx, dy, dz)")
    kind = _ask("Select", "1")

    if kind == "2":
        return (0.85, 0.85, 0.85), (0.0, 0.0, 0.0)
    if kind == "3":
        return (1.15, 1.15, 1.15), (0.0, 0.0, 0.0)
    if kind == "4":
        def _one(axis):
            s = input(f"set {axis} (blank = leave): ").strip()
            if s == "":
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return (_one("X"), _one("Y"), _one("Z")), (0.0, 0.0, 0.0)
    if kind == "5":
        dx = _ask_float("add dX", "0")
        dy = _ask_float("add dY", "0")
        dz = _ask_float("add dZ", "0")
        return None, (dx, dy, dz)

    # default: uniform scale (x = y = z)
    s = _ask_float("Scale factor  (e.g. 0.85 shorter, 1.15 longer)", "0.9")
    return (s, s, s), (0.0, 0.0, 0.0)


def _menu_ask_patterns():
    raw = _ask("Skirt GO name patterns (contains match)", ", ".join(DEFAULT_SKIRT_PATTERNS))
    return [p.strip() for p in raw.replace(",", " ").split() if p.strip()]


def menu_single():
    print("\n" + _box("Skirt - single file"))
    in_file = _ask_path("Input bundle", must_exist=True)
    out_file = _ask_path("Output path")
    if not in_file or not out_file:
        print("Input/output paths are required."); return
    patterns = _menu_ask_patterns()
    setv, addv = _menu_choose_skirt_scale()
    print("\nWorking...\n")
    try:
        scanned, changed, logs = modify_skirt_scaling(Path(in_file), Path(out_file), patterns, setv, addv)
        print(f"Done. scanned={scanned} changed={changed}")
    except Exception as e:
        print(f"Error: {e}")


def menu_batch():
    print("\n" + _box("Skirt - batch (folder)"))
    in_dir = _ask_path("Input folder", must_exist=True)
    out_dir = _ask_path("Output folder")
    if not in_dir or not out_dir:
        print("Input/output folders are required."); return
    prefix = _ask("Output prefix", "")
    suffix = _ask("Output suffix", "")
    patterns = _menu_ask_patterns()
    setv, addv = _menu_choose_skirt_scale()
    skirt_sfx = _skirt_suffix(setv, addv)
    if skirt_sfx and _ask_yesno(
            f"Append the skirt length to the output filename? (e.g. {skirt_sfx})", True):
        suffix = suffix + skirt_sfx
    files = [p for p in Path(in_dir).rglob("*") if p.is_file()]
    total = len(files); ok = fail = tot_changed = 0
    print(f"\nWorking on {total} file(s)...\n")
    for i, p in enumerate(files, 1):
        out_p = name_transform_for_output(p, Path(out_dir), Path(in_dir), prefix, suffix)
        try:
            _, changed, _ = modify_skirt_scaling(p, out_p, patterns, setv, addv, write_log_file=False)
            tot_changed += changed; ok += 1
            print(f"  [{i}/{total}] OK   {p.name} (changed={changed})")
        except Exception as e:
            fail += 1
            print(f"  [{i}/{total}] FAIL {p.name}: {e}")
    print(f"\nDone. ok={ok} fail={fail} changed={tot_changed}")


def menu_library():
    print("\n" + _box("Skirt - library (extracted -> modded)"))
    extracted = default_sukusta_dir("extracted")
    modded = default_sukusta_dir("modded")
    print(f"  extracted: {extracted}")
    print(f"  modded   : {modded}")

    sc = _ask("Source  1) extracted   2) modded   3) custom path", "1")
    if sc == "2":
        src_root = modded
    elif sc == "3":
        src_root = _ask_path("Source folder", must_exist=True) or extracted
    else:
        src_root = extracted
    src_root = os.path.expanduser(src_root)

    print(f"\nScanning {src_root} ...")
    bundles = find_asset_bundles(src_root)
    if not bundles:
        print("No asset bundles (UnityFS files) found there.")
        print("Extract some first (the extractor's Mod Menu), or choose another folder.")
        return
    for i, b in enumerate(bundles, 1):
        try:
            rel = b.relative_to(src_root)
        except Exception:
            rel = b.name
        print(f"  {i:3d}) {rel}")
    chosen = _parse_multi_select(_ask("Select bundle(s)  (e.g. 3, 1,4-8, all)", "1"), len(bundles))
    if not chosen:
        print("Nothing selected."); return

    patterns = _menu_ask_patterns()
    setv, addv = _menu_choose_skirt_scale()
    skirt_sfx = _skirt_suffix(setv, addv)
    append_len = bool(skirt_sfx) and _ask_yesno(
        f"Append the skirt length to the output filename? (e.g. {skirt_sfx})", True)

    print(f"\nExporting to {modded} ...\n")
    ok = fail = 0
    for i in chosen:
        b = bundles[i]
        out_path = modded_output_path(b, src_root, modded,
                                      extra_suffix=skirt_sfx if append_len else "")
        try:
            summary = run_library_mod_one(b, out_path, patterns, setv, addv)
            ok += 1
            try:
                rel_out = out_path.relative_to(os.path.expanduser(modded))
            except Exception:
                rel_out = out_path.name
            print(f"  [ok]   {b.name} -> modded/{rel_out}  ({summary})")
        except Exception as e:
            fail += 1
            print(f"  [fail] {b.name}: {e}")
    print(f"\nDone. ok={ok}  fail={fail}   (output root: {modded})")


def run_menu():
    ensure_unitypy()
    try:
        import readline  # noqa: F401  (arrow-key editing / history)
    except Exception:
        pass
    print()
    print("==========================================")
    print("        Skirt Length Changer")
    print("      (Termux / headless text mode)")
    print("==========================================")
    while True:
        print("\nWhat would you like to do?")
        print("  1) Mod from library (extracted -> modded)")
        print("  2) Single file")
        print("  3) Batch (folder)")
        print("  q) Quit")
        choice = input("> ").strip().lower()
        if choice in ("q", "quit", "exit", "0"):
            print("Bye.")
            break
        elif choice == "1":
            menu_library()
        elif choice == "2":
            menu_single()
        elif choice == "3":
            menu_batch()
        else:
            print("Please choose 1, 2, 3, or q.")


# ==========================================================================
# GUI (desktop) - single window: single / batch + uniform scale options.
# The extracted->modded "Library" workflow lives only in the Termux text menu
# (where the sukusta folders are); on Mac/PC you just pick files directly.
# Deliberately plain (no notebook / no scroll canvas) so it stays snappy.
# ==========================================================================
def run_gui():
    ensure_unitypy()
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    PAD = dict(padx=6, pady=4)

    root = tk.Tk()
    root.title("Skirt Length Changer")
    root.geometry("820x600")
    root.minsize(620, 460)
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Run.TButton", font=("TkDefaultFont", 10, "bold"))
    except Exception:
        pass

    target_patterns = tk.StringVar(value=", ".join(DEFAULT_SKIRT_PATTERNS))
    uniform = tk.StringVar(value="0.9")
    set_x = tk.StringVar(value="")
    set_y = tk.StringVar(value="")
    set_z = tk.StringVar(value="")
    add_dx = tk.StringVar(value="0")
    add_dy = tk.StringVar(value="0")
    add_dz = tk.StringVar(value="0")
    in_file = tk.StringVar()
    out_file = tk.StringVar()
    in_dir = tk.StringVar()
    out_dir = tk.StringVar()
    out_prefix = tk.StringVar(value="")
    out_suffix = tk.StringVar(value="")
    append_len = tk.BooleanVar(value=True)

    def parse_set():
        s = (set_x.get().strip(), set_y.get().strip(), set_z.get().strip())
        if all(v == "" for v in s):
            return None

        def _f(v):
            if v == "":
                return None
            try:
                return float(v)
            except ValueError:
                return None
        return (_f(s[0]), _f(s[1]), _f(s[2]))

    def parse_add():
        try:
            return (float(add_dx.get() or 0), float(add_dy.get() or 0), float(add_dz.get() or 0))
        except Exception:
            return (0.0, 0.0, 0.0)

    def parse_patterns():
        return [t.strip() for t in target_patterns.get().replace(",", " ").split() if t.strip()]

    def set_quick(x, y, z):
        set_x.set("" if x is None else str(x))
        set_y.set("" if y is None else str(y))
        set_z.set("" if z is None else str(z))
        add_dx.set("0"); add_dy.set("0"); add_dz.set("0")

    def set_uniform(v):
        """Fill x = y = z = v (the usual uniform skirt scale)."""
        uniform.set(str(v))
        set_quick(v, v, v)

    def apply_uniform():
        try:
            v = float(uniform.get())
        except (ValueError, TypeError):
            return
        set_quick(v, v, v)

    def show_log(lines, title=None):
        win = tk.Toplevel(root); win.title(title or _tr("Result")); win.geometry("1000x640")
        frm = ttk.Frame(win); frm.pack(fill="both", expand=True, padx=8, pady=8)
        txt = tk.Text(frm, wrap="none")
        xsb = ttk.Scrollbar(frm, orient="horizontal", command=txt.xview)
        ysb = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
        txt.configure(xscrollcommand=xsb.set, yscrollcommand=ysb.set)
        txt.grid(row=0, column=0, sticky="nsew"); ysb.grid(row=0, column=1, sticky="ns"); xsb.grid(row=1, column=0, sticky="ew")
        frm.rowconfigure(0, weight=1); frm.columnconfigure(0, weight=1)
        txt.insert("end", "\n".join(lines)); txt.configure(state="disabled")

    def pick_file(var):
        p = filedialog.askopenfilename(title=_tr("Select input bundle"),
                                       initialdir=default_sukusta_dir("extracted"))
        if p:
            var.set(p)

    def pick_save(var):
        p = filedialog.asksaveasfilename(title=_tr("Save output bundle"), defaultextension=".unity",
                                         initialdir=default_sukusta_dir("modded"))
        if p:
            var.set(p)

    def pick_dir(var, initial=None):
        p = filedialog.askdirectory(title=_tr("Select folder"), initialdir=initial or os.path.expanduser("~"))
        if p:
            var.set(p)

    def run_single():
        if not in_file.get() or not out_file.get():
            messagebox.showerror(_tr("Error"), _tr("Please set input and output paths.")); return
        setv, addv, pats = parse_set(), parse_add(), parse_patterns()
        try:
            scanned, changed, logs = modify_skirt_scaling(
                Path(in_file.get()), Path(out_file.get()), pats, setv, addv)
            show_log([f"[SINGLE] scanned={scanned} changed={changed}", *logs])
        except Exception as e:
            messagebox.showerror(_tr("Error"), str(e))

    def run_batch():
        if not in_dir.get() or not out_dir.get():
            messagebox.showerror(_tr("Error"), _tr("Please set input and output folders.")); return
        setv, addv, pats = parse_set(), parse_add(), parse_patterns()
        eff_suffix = out_suffix.get() + (_skirt_suffix(setv, addv) if append_len.get() else "")
        files = [p for p in Path(in_dir.get()).rglob("*") if p.is_file()]
        ok = fail = tot_changed = 0
        for p in files:
            out_p = name_transform_for_output(p, Path(out_dir.get()), Path(in_dir.get()),
                                              out_prefix.get(), eff_suffix)
            try:
                _, changed, _ = modify_skirt_scaling(p, out_p, pats, setv, addv, write_log_file=False)
                tot_changed += changed; ok += 1
            except Exception:
                fail += 1
        show_log([f"[BATCH] files={len(files)} ok={ok} fail={fail} changed={tot_changed}"])

    # The window is rebuilt on a language change. The tk variables above live in
    # the outer scope, so anything the user already typed survives the rebuild.
    container = ttk.Frame(root)
    container.pack(fill="both", expand=True)

    def on_language(code):
        _set_lang(code)
        build()

    def build():
        for w in container.winfo_children():
            w.destroy()
        root.title(_tr("Skirt Length Changer"))

        frm = ttk.Frame(container, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)

        # ---------- language picker ----------
        lang_bar = ttk.Frame(frm); lang_bar.pack(fill="x")
        ttk.Label(lang_bar, text=_tr("Language")).pack(side="left")
        names = [name for _code, name in _lang_opts()]
        code_by_name = {name: code for code, name in _lang_opts()}
        name_by_code = {code: name for code, name in _lang_opts()}
        lang_display = tk.StringVar(value=name_by_code.get(_get_lang(), names[0]))
        cb = ttk.Combobox(lang_bar, textvariable=lang_display, values=names,
                          state="readonly", width=10)
        cb.pack(side="left", padx=(6, 0))
        cb.bind("<<ComboboxSelected>>",
                lambda e: on_language(code_by_name[lang_display.get()]))

        # ---------- Single ----------
        s = ttk.LabelFrame(frm, text=_tr("Single file"), padding=8)
        s.pack(fill="x", pady=(8, 0))
        s.columnconfigure(1, weight=1)
        ttk.Label(s, text=_tr("Input bundle")).grid(row=0, column=0, sticky="w", **PAD)
        ttk.Entry(s, textvariable=in_file).grid(row=0, column=1, sticky="ew", **PAD)
        ttk.Button(s, text=_tr("Browse"), command=lambda: pick_file(in_file)).grid(row=0, column=2, **PAD)
        ttk.Label(s, text=_tr("Output path")).grid(row=1, column=0, sticky="w", **PAD)
        ttk.Entry(s, textvariable=out_file).grid(row=1, column=1, sticky="ew", **PAD)
        ttk.Button(s, text=_tr("Browse"), command=lambda: pick_save(out_file)).grid(row=1, column=2, **PAD)
        ttk.Button(s, text=_tr("Run (single)"), style="Run.TButton",
                   command=run_single).grid(row=2, column=0, columnspan=3, pady=6)

        # ---------- Batch ----------
        b = ttk.LabelFrame(frm, text=_tr("Batch (folder)"), padding=8)
        b.pack(fill="x", pady=(8, 0))
        b.columnconfigure(1, weight=1)
        ttk.Label(b, text=_tr("Input folder")).grid(row=0, column=0, sticky="w", **PAD)
        ttk.Entry(b, textvariable=in_dir).grid(row=0, column=1, sticky="ew", **PAD)
        ttk.Button(b, text=_tr("Browse"), command=lambda: pick_dir(in_dir, default_sukusta_dir("extracted"))).grid(row=0, column=2, **PAD)
        ttk.Label(b, text=_tr("Output folder")).grid(row=1, column=0, sticky="w", **PAD)
        ttk.Entry(b, textvariable=out_dir).grid(row=1, column=1, sticky="ew", **PAD)
        ttk.Button(b, text=_tr("Browse"), command=lambda: pick_dir(out_dir, default_sukusta_dir("modded"))).grid(row=1, column=2, **PAD)
        ttk.Label(b, text=_tr("prefix")).grid(row=2, column=0, sticky="w", **PAD)
        ttk.Entry(b, textvariable=out_prefix, width=18).grid(row=2, column=1, sticky="w", **PAD)
        ttk.Label(b, text=_tr("suffix")).grid(row=3, column=0, sticky="w", **PAD)
        ttk.Entry(b, textvariable=out_suffix, width=18).grid(row=3, column=1, sticky="w", **PAD)
        ttk.Checkbutton(b, text=_tr("Append skirt length to filenames (e.g. _skirt085)"),
                        variable=append_len).grid(row=4, column=0, columnspan=3, sticky="w", **PAD)
        ttk.Button(b, text=_tr("Run (batch)"), style="Run.TButton",
                   command=run_batch).grid(row=5, column=0, columnspan=3, pady=6)

        # ---------- Scale options ----------
        o = ttk.LabelFrame(frm, text=_tr("Skirt scale options"), padding=8)
        o.pack(fill="x", pady=(8, 0))
        o.columnconfigure(1, weight=1)
        ttk.Label(o, text=_tr("Skirt GO name patterns (comma/space, contains match)"))\
            .grid(row=0, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Entry(o, textvariable=target_patterns).grid(row=1, column=0, columnspan=2, sticky="ew", **PAD)

        ttk.Label(o, text=_tr("Uniform scale  (x = y = z - the usual skirt change)"),
                  font=("TkDefaultFont", 9, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", **PAD)
        urow = ttk.Frame(o); urow.grid(row=3, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Label(urow, text=_tr("factor:")).pack(side="left")
        ttk.Entry(urow, textvariable=uniform, width=8).pack(side="left", padx=4)
        ttk.Button(urow, text=_tr("Apply"), command=apply_uniform).pack(side="left", padx=(0, 10))
        ttk.Button(urow, text=_tr("Shorter 0.85"), command=lambda: set_uniform(0.85)).pack(side="left", padx=2)
        ttk.Button(urow, text=_tr("Longer 1.15"), command=lambda: set_uniform(1.15)).pack(side="left", padx=2)
        ttk.Button(urow, text=_tr("Reset 1.0"), command=lambda: set_uniform(1.0)).pack(side="left", padx=2)

        ttk.Label(o, text=_tr("Advanced - per-axis set (x, y, z)  -  blank = leave that axis"))\
            .grid(row=4, column=0, columnspan=2, sticky="w", **PAD)
        srow = ttk.Frame(o); srow.grid(row=5, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Entry(srow, textvariable=set_x, width=10).pack(side="left", padx=2)
        ttk.Entry(srow, textvariable=set_y, width=10).pack(side="left", padx=2)
        ttk.Entry(srow, textvariable=set_z, width=10).pack(side="left", padx=2)

        ttk.Label(o, text=_tr("Advanced - add delta (dx, dy, dz)  -  added to current value"))\
            .grid(row=6, column=0, columnspan=2, sticky="w", **PAD)
        arow = ttk.Frame(o); arow.grid(row=7, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Entry(arow, textvariable=add_dx, width=10).pack(side="left", padx=2)
        ttk.Entry(arow, textvariable=add_dy, width=10).pack(side="left", padx=2)
        ttk.Entry(arow, textvariable=add_dz, width=10).pack(side="left", padx=2)

        ttk.Label(o, text=_tr("Skirt length/volume usually scales uniformly, so x, y, z move "
                              "together. Use the factor above; the per-axis fields are for fine cases."),
                  font=("TkDefaultFont", 8), foreground="#777", wraplength=560, justify="left")\
            .grid(row=8, column=0, columnspan=2, sticky="w", **PAD)

    build()
    root.mainloop()
# ==========================================================================
# Entry point
# ==========================================================================
def build_parser():
    p = argparse.ArgumentParser(description="Skirt length changer (skirt-bone LiveCore scaler).")
    p.add_argument("--gui", action="store_true", help="force the GUI")
    p.add_argument("--menu", "--cli", dest="menu", action="store_true",
                   help="force the Termux/headless text menu")
    return p


def main():
    args = build_parser().parse_args()
    if args.menu:
        return run_menu()
    if args.gui:
        return run_gui()
    if gui_available():
        return run_gui()
    return run_menu()


if __name__ == "__main__":
    main()
