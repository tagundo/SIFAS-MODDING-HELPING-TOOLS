#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS Breast Tuner (unified)
============================
Two Unity-bundle editing tools merged into one:

  * Physics (Dyna) : edits SwingBone physics on breast bones
                     (stiffnessForce / dragForce / low & high RotationLimit)
  * Size           : edits LiveCoreMemberNodeScaling.scaleValues on the
                     "BreastSize" node (absolute set or additive delta)

The frontend is chosen automatically by environment:
  * Desktop (Mac/Windows/Linux with a display) -> Tkinter GUI
  * Termux / headless                          -> interactive text menu

Single file, no data files required. UnityPy is the only hard dependency.

Usage:
  python sifas_breast_tuner.py            # auto (GUI if possible, else menu)
  python sifas_breast_tuner.py --menu     # force the interactive menu
  python sifas_breast_tuner.py --gui      # force the GUI
  python sifas_breast_tuner.py dyna ...   # one-shot CLI (see: dyna --help)
  python sifas_breast_tuner.py size ...   # one-shot CLI (see: size --help)
"""

import os
import sys
import argparse
import fnmatch
from pathlib import Path
from collections import Counter

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
_TRANSLATIONS = {
    "ko": {
        "Language": "언어",
        "SIFAS Breast Tuner - Physics / Size / Both": "SIFAS 가슴 튜너 - 물리 / 크기 / 둘 다",
        "Physics (Dyna)": "물리 (Dyna)",
        "Size": "크기",
        "Both": "둘 다",
        "Library": "라이브러리",
        "Progress / Log": "진행 / 로그",
        "Clear log": "로그 지우기",
        "Save log": "로그 저장",
        "Idle": "대기 중",
        "Single file": "단일 파일",
        "Batch (folder)": "일괄 (폴더)",
        "Run (single)": "실행 (단일)",
        "Run (batch)": "실행 (일괄)",
        "Physics parameters": "물리 매개변수",
        "Scale parameters": "스케일 매개변수",
        "Body & physics": "바디 & 물리",
        "1. Source — pick a bundle": "1. 소스 — 번들 선택",
        "2. Mod to apply": "2. 적용할 모드",
        "3. Output → modded": "3. 출력 → modded",
        "Mod selected → modded": "선택 항목 모드 적용 → modded",
        "Input bundle": "입력 번들",
        "Output path": "출력 경로",
        "Input folder": "입력 폴더",
        "Output folder": "출력 폴더",
        "Browse": "찾아보기",
        "Error": "오류",
        "Y must be a number.": "Y는 숫자여야 합니다.",
        "Saved": "저장됨",
        "Log saved:\n{p}": "로그가 저장되었습니다:\n{p}",
        "Busy": "사용 중",
        "A job is already running.": "이미 작업이 실행 중입니다.",
        "Please set input/output paths.": "입력/출력 경로를 설정하세요.",
        "Please set input/output folders.": "입력/출력 폴더를 설정하세요.",
        "Scan a source folder and pick a bundle first.": "먼저 소스 폴더를 스캔하고 번들을 선택하세요.",
        "Pick a bundle.": "번들을 선택하세요.",
        "Set the modded output folder.": "modded 출력 폴더를 설정하세요.",
        "Language changed. Restart the tool to apply it.": "언어가 변경되었습니다. 적용하려면 도구를 다시 시작하세요.",
    },
    "ja": {
        "Language": "言語",
        "SIFAS Breast Tuner - Physics / Size / Both": "SIFAS バストチューナー - 物理 / サイズ / 両方",
        "Physics (Dyna)": "物理 (Dyna)",
        "Size": "サイズ",
        "Both": "両方",
        "Library": "ライブラリ",
        "Progress / Log": "進捗 / ログ",
        "Clear log": "ログをクリア",
        "Save log": "ログを保存",
        "Idle": "待機中",
        "Single file": "単一ファイル",
        "Batch (folder)": "一括（フォルダ）",
        "Run (single)": "実行（単一）",
        "Run (batch)": "実行（一括）",
        "Physics parameters": "物理パラメータ",
        "Scale parameters": "スケールパラメータ",
        "Body & physics": "ボディ & 物理",
        "1. Source — pick a bundle": "1. ソース — バンドルを選択",
        "2. Mod to apply": "2. 適用するMOD",
        "3. Output → modded": "3. 出力 → modded",
        "Mod selected → modded": "選択をMOD適用 → modded",
        "Input bundle": "入力バンドル",
        "Output path": "出力パス",
        "Input folder": "入力フォルダ",
        "Output folder": "出力フォルダ",
        "Browse": "参照",
        "Error": "エラー",
        "Y must be a number.": "Y は数値である必要があります。",
        "Saved": "保存しました",
        "Log saved:\n{p}": "ログを保存しました:\n{p}",
        "Busy": "実行中",
        "A job is already running.": "すでにジョブが実行中です。",
        "Please set input/output paths.": "入力/出力パスを設定してください。",
        "Please set input/output folders.": "入力/出力フォルダを設定してください。",
        "Scan a source folder and pick a bundle first.": "先にソースフォルダをスキャンしてバンドルを選択してください。",
        "Pick a bundle.": "バンドルを選択してください。",
        "Set the modded output folder.": "modded 出力フォルダを設定してください。",
        "Language changed. Restart the tool to apply it.": "言語を変更しました。適用するにはツールを再起動してください。",
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

# UnityPy is loaded/installed lazily (only when actually needed) so that a
# plain `import` of this module never triggers pip and stays test-friendly.
UnityPy = None


# ==========================================================================
# 0. Environment detection & dependencies
# ==========================================================================
def is_termux() -> bool:
    """Best-effort guess at whether we're running inside Termux."""
    if "com.termux" in (os.environ.get("PREFIX", "") + os.environ.get("HOME", "")):
        return True
    return os.path.isdir("/data/data/com.termux")


def gui_available() -> bool:
    """Whether a Tkinter GUI can realistically be shown."""
    if is_termux():
        return False
    try:
        import tkinter  # noqa: F401  (import is the availability probe)
    except Exception:
        return False
    # On Linux we need an X display; Mac/Windows don't.
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return False
    return True


def _run_cmd(cmd):
    """Run a command, returning True on success. Silent on failure."""
    import subprocess
    try:
        subprocess.check_call(cmd)
        return True
    except Exception:
        return False


def _pip_install(*pkgs):
    return _run_cmd([sys.executable, "-m", "pip", "install", *pkgs])


def _ensure_pillow_on_termux():
    """Make Pillow importable on Termux WITHOUT the user doing anything.

    On Termux `pip install Pillow` builds from source and fails (no libjpeg),
    which is why `pip install UnityPy` (Pillow is a dependency) fails. So we
    install Termux's prebuilt python-pillow via pkg first. Returns True if PIL
    ends up importable."""
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
        # package lists may be stale - refresh once and retry
        _run_cmd(["apt", "update", "-y"])
        ok = (_run_cmd(["pkg", "install", "-y", "python-pillow"])
              or _run_cmd(["apt", "install", "-y", "python-pillow"]))
    try:
        __import__("PIL")
        return True
    except Exception:
        return False


def _unitypy_install_help():
    """Last-resort guidance if the automatic setup couldn't finish."""
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

    Designed to 'just work' with no manual steps: on Termux it installs the
    prebuilt Pillow via pkg before pip-installing UnityPy. Falls back to clear
    guidance (instead of crashing) only if every automatic attempt fails."""
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
        _ensure_pillow_on_termux()      # avoid the libjpeg source-build failure
    if not _pip_install("UnityPy"):
        if is_termux():                 # one more try after ensuring Pillow
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


# ==========================================================================
# 1. Shared typetree helpers (used by both tools)
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
        obj.save_typetree(tree)
        return
    if hasattr(data, "save_typetree"):
        data.save_typetree(tree)
        return
    raise AttributeError("no save_typetree on obj or data")


def type_name(obj):
    t = getattr(obj, "type", None)
    return getattr(t, "name", str(t))


def type_id(obj):
    t = getattr(obj, "type", None)
    return getattr(t, "value", None)


def is_obj_type(obj, names_or_ids):
    tn = type_name(obj)
    ti = type_id(obj)
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


def set_in_tree_if_exists(tree, key, value):
    if isinstance(tree, dict):
        if key in tree:
            tree[key] = value
            return True
        base = tree.get("Base")
        if isinstance(base, dict) and key in base:
            base[key] = value
            return True
    return False


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
        vec["x"] = float(x)
        changed = True
    if y is not None:
        vec["y"] = float(y)
        changed = True
    if z is not None:
        vec["z"] = float(z)
        changed = True
    return changed


def add_vec3(vec, dx=0.0, dy=0.0, dz=0.0):
    if not isinstance(vec, dict):
        return False
    vec["x"] = float(vec.get("x") or 0.0) + float(dx)
    vec["y"] = float(vec.get("y") or 0.0) + float(dy)
    vec["z"] = float(vec.get("z") or 0.0) + float(dz)
    return True


# ==========================================================================
# 2. Index / name helpers
# ==========================================================================
def build_obj_index(env):
    obj_by_pid = {}
    for o in env.objects:
        obj_by_pid[o.path_id] = o
        obj_by_pid[-o.path_id] = o
    return obj_by_pid


def try_get_go_name_from_tree(go_tree):
    if not isinstance(go_tree, dict):
        return None
    if "m_Name" in go_tree and isinstance(go_tree["m_Name"], str):
        return go_tree["m_Name"]
    base = go_tree.get("Base")
    if isinstance(base, dict) and isinstance(base.get("m_Name"), str):
        return base["m_Name"]
    return None


def build_maps(env):
    """Build obj_by_pid plus a GameObject path_id -> name map (Dyna needs GO names)."""
    obj_by_pid = {}
    go_name_by_pid = {}
    for obj in env.objects:
        obj_by_pid[obj.path_id] = obj
        obj_by_pid[-obj.path_id] = obj
        if is_obj_type(obj, ("GameObject", 1)):
            try:
                tree, _, _ = read_tree_safe(obj)
                nm = try_get_go_name_from_tree(tree)
                if nm:
                    pid = obj.path_id
                    go_name_by_pid[pid] = nm
                    go_name_by_pid[-pid] = nm
            except Exception:
                pass
    return obj_by_pid, go_name_by_pid


def find_gameobject_by_name(env, name_ci: str):
    for o in env.objects:
        if not is_obj_type(o, ("GameObject", 1)):
            continue
        try:
            tree, _, _ = read_tree_safe(o)
        except Exception:
            continue
        nm = try_get_go_name_from_tree(tree)
        if (nm or "").lower() == name_ci.lower():
            return o
    return None


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


def get_transform_for_breastsize(env, obj_by_pid, breast_go_name="BreastSize"):
    go = find_gameobject_by_name(env, breast_go_name)
    if not go:
        return None
    try:
        go_tree, _, _ = read_tree_safe(go)
    except Exception:
        return None
    for pid in list_components_pids(go_tree):
        tobj = obj_by_pid.get(pid) or obj_by_pid.get(-pid)
        if tobj and is_obj_type(tobj, ("Transform", 4)):
            return tobj
    return None


def name_matches_ci(name, patterns):
    if not patterns:
        return True
    s = (name or "").lower()
    for p in patterns:
        if fnmatch.fnmatchcase(s, p.lower()):
            return True
    return False


def try_get_script_class_with_index(obj_by_pid, mono_obj_tree):
    p = get_from_tree(mono_obj_tree, "m_Script")
    if not isinstance(p, dict):
        return None
    pid = p.get("m_PathID") or p.get("pathID")
    if not isinstance(pid, int):
        return None
    for k in (pid, -pid):
        sobj = obj_by_pid.get(k)
        if not sobj:
            continue
        try:
            stree, _, _ = read_tree_safe(sobj)
        except Exception:
            continue
        for key in ("m_ClassName", "className", "m_Name", "name"):
            v = get_from_tree(stree, key)
            if isinstance(v, str) and v:
                return v
    return None


def type_histogram(env):
    c = Counter()
    for o in env.objects:
        c[type_name(o)] += 1
    return c


# ==========================================================================
# 3. Character-ID mapping (Dyna auto mode)
# ==========================================================================
# n value -> list of character IDs
CHAR_ID_TO_N_MAPPING = {
    0: [9, 209, 9999],
    1: [5],
    2: [4, 109, 202],
    3: [1, 6, 106, 210],
    4: [3, 102, 104, 203, 212],
    5: [8, 101, 105, 201, 207],
    6: [2, 103, 107, 108, 205, 206, 211],
    7: [7, 204, 208],
}

# character ID -> name (SIFAS member IDs: 1-9 mu's, 101-109 Aqours, 201-212 Niji)
CHAR_ID_TO_NAME = {
    1: "Honoka", 2: "Eli", 3: "Kotori", 4: "Umi", 5: "Rin",
    6: "Maki", 7: "Nozomi", 8: "Hanayo", 9: "Nico",
    101: "Chika", 102: "Riko", 103: "Kanan", 104: "Dia", 105: "You",
    106: "Yoshiko", 107: "Hanamaru", 108: "Mari", 109: "Ruby",
    201: "Ayumu", 202: "Kasumi", 203: "Shizuku", 204: "Karin", 205: "Ai",
    206: "Kanata", 207: "Setsuna", 208: "Emma", 209: "Rina", 210: "Shioriko",
    211: "Mia", 212: "Lanzhu",
    9999: "Default",
}


def names_for_char_ids(ids):
    return ", ".join(CHAR_ID_TO_NAME.get(i, str(i)) for i in ids)


def jiggle_mapping_lines():
    """Human-readable 'jiggleN -> character names' lines."""
    return [f"jiggle{n}: {names_for_char_ids(ids)}" for n, ids in CHAR_ID_TO_N_MAPPING.items()]


def get_n_value_for_char_id(char_id):
    for n, char_ids in CHAR_ID_TO_N_MAPPING.items():
        if char_id in char_ids:
            return n
    return None


def extract_char_id_from_texture_name(texture_name):
    """Extract a character ID from a name like 'ch0107_co0001_body' (ch0107 -> 107)."""
    if not texture_name or not texture_name.startswith("ch"):
        return None
    start_idx = 2
    end_idx = texture_name.find("_", start_idx)
    if end_idx == -1:
        return None
    char_id_str = texture_name[start_idx:end_idx]
    if len(char_id_str) != 4 or not char_id_str.isdigit():
        return None
    return int(char_id_str)


def find_character_id_from_bundle(env):
    """Find a character ID via a 'ch####_co####_body' texture name in the bundle."""
    for obj in env.objects:
        if is_obj_type(obj, ("Texture2D", 28)):
            try:
                tree, _, _ = read_tree_safe(obj)
                name = get_from_tree(tree, "m_Name")
                if name and "_body" in name:
                    char_id = extract_char_id_from_texture_name(name)
                    if char_id is not None:
                        return char_id
            except Exception:
                continue
    return None


def generate_output_filename(input_path, prefix, suffix, use_character_specific, env=None):
    """In auto mode, append jiggleN to the filename when a character ID is found."""
    input_file = Path(input_path)
    if use_character_specific and env is not None:
        char_id = find_character_id_from_bundle(env)
        if char_id is not None:
            n_value = get_n_value_for_char_id(char_id)
            if n_value is not None:
                jiggle_suffix = f"jiggle{n_value}"
                full_suffix = f"{suffix}{jiggle_suffix}" if suffix else jiggle_suffix
                return f"{prefix}{input_file.stem}{full_suffix}{input_file.suffix}"
    return f"{prefix}{input_file.stem}{suffix}{input_file.suffix}"


# ==========================================================================
# 3b. Breast-size presets (derived from in-game scale data)
# ==========================================================================
# From the in-game scale table: for breast scales ABOVE 1.0 the three axes
# follow a single parameter Y (0 < Y < 1), where Y is the y-axis offset:
#
#       y = 1 + Y ,   x = z = 1 + 2Y
#
# (Holds for Eli Y=.08, Hanayo .04, Chika .02, Mari .10, Nozomi .15,
#  Karin .11, Hanamaru .06, Lanzhu .07, ...)
#
# Below 1.0 the values are irregular, so they are stored verbatim per character.

def breast_enlarge_xyz(y_offset):
    """Enlargement formula: y = 1 + Y ; x = z = 1 + 2Y."""
    y_offset = float(y_offset)
    return (round(1.0 + 2.0 * y_offset, 6),
            round(1.0 + y_offset, 6),
            round(1.0 + 2.0 * y_offset, 6))


# Enlarge presets: (label, (x, y, z), jiggle_n). Characters that share a size
# in-game are co-listed; every group also shares one jiggle (swing-bone) tier n,
# so a chosen size preset maps cleanly to a dyna n. Emma uses her in-game value
# 1.30/1.18/1.30 (the one row that doesn't follow the y=1+Y, x,z=1+2Y formula).
BREAST_ENLARGE_PRESETS = [
    ("Chika/You/Ayumu",  (1.04, 1.02, 1.04), 5),
    ("Hanayo/Setsuna",   (1.08, 1.04, 1.08), 5),
    ("Hanamaru/Ai",      (1.12, 1.06, 1.12), 6),
    ("Lanzhu",           (1.14, 1.07, 1.14), 4),
    ("Eli/Kanan/Kanata", (1.16, 1.08, 1.16), 6),
    ("Mari",             (1.20, 1.10, 1.20), 6),
    ("Karin",            (1.22, 1.11, 1.22), 7),
    ("Nozomi",           (1.30, 1.15, 1.30), 7),
    ("Emma",             (1.30, 1.18, 1.30), 7),
]

# Reduce presets: (label, (x, y, z), jiggle_n). Verbatim values, characters co-listed.
BREAST_REDUCE_PRESETS = [
    ("Yoshiko/Shioriko", (0.95, 0.99, 0.98), 3),
    ("Honoka/Maki",      (0.90, 0.98, 0.96), 3),
    ("Umi/Ruby/Kasumi",  (0.80, 0.96, 0.92), 2),
    ("Rin",              (0.72, 0.95, 0.90), 1),
    ("Nico",             (0.64, 0.94, 0.88), 0),
    ("Rina",             (0.61, 0.91, 0.85), 0),
]

# All presets sorted smallest -> largest (for the combined Dyna+Size picker).
BREAST_PRESETS_ALL = sorted(
    BREAST_REDUCE_PRESETS + BREAST_ENLARGE_PRESETS, key=lambda t: t[1][0]
)


def read_current_breast_size(env, breast_go_name="BreastSize"):
    """Return the LiveCore scaledValue (x, y, z) currently applied to the
    BreastSize node, or None when there is no explicit scaling entry (stock size).

    Lets the auto-jiggle follow a breast size that was *already* modified instead
    of blindly using the character's stock tier."""
    obj_by_pid = build_obj_index(env)
    breast_tr = get_transform_for_breastsize(env, obj_by_pid, breast_go_name=breast_go_name)
    if not breast_tr:
        return None
    target_pid = breast_tr.path_id
    for obj in env.objects:
        if not is_obj_type(obj, ("MonoBehaviour", 114)):
            continue
        try:
            tree, _data, _where = read_tree_safe(obj)
        except Exception:
            continue
        if not is_livecore_scaling_tree(tree, obj_by_pid):
            continue
        scale_list = get_from_tree(tree, "scaleValues")
        if not isinstance(scale_list, list):
            continue
        for elem in scale_list:
            node, _estyle = get_node_from_elem(elem)
            tgt = node.get("target") or {}
            pid = tgt.get("m_PathID") or tgt.get("pathID")
            if isinstance(pid, int) and (pid == target_pid or pid == -target_pid):
                sv = node.get("scaledValue") or {}
                try:
                    return (float(sv.get("x", 1.0)),
                            float(sv.get("y", 1.0)),
                            float(sv.get("z", 1.0)))
                except (TypeError, ValueError):
                    return None
    return None


def n_from_breast_size(size, tol=0.03):
    """Map a current breast scaledValue to the jiggle tier (n) of the nearest size
    preset. Returns None when the size is effectively stock (~1.0 on every axis),
    so the caller can fall back to the character-ID tier."""
    if not size:
        return None
    x, y, z = size
    if all(abs(v - 1.0) <= tol for v in (x, y, z)):
        return None  # unmodified -> use the stock (character-ID) jiggle
    best_n, best_d = None, None
    for _label, (sx, sy, sz), n in BREAST_PRESETS_ALL:
        d = (x - sx) ** 2 + (y - sy) ** 2 + (z - sz) ** 2
        if best_d is None or d < best_d:
            best_d, best_n = d, n
    return best_n


def _fmt_num(v):
    """Compact number formatting for labels (1.0 -> '1', 1.04 -> '1.04')."""
    return f"{v:g}"


# ==========================================================================
# 4. Core #1 - SwingBone physics (Dyna) editing
# ==========================================================================
def _save_env(env, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(env.file.save(packer="lz4"))


def modify_swingbones_in_bundle(
    in_path: Path,
    out_path: Path,
    target_name_patterns,
    stiff_value=None,
    drag_value=None,
    low_dy: float = 0.0,
    low_dz: float = 0.0,
    high_dy: float = 0.0,
    high_dz: float = 0.0,
    use_character_specific=False,
    write_log_file=True,
):
    """Load a bundle, edit swing-bone physics, save (thin load/save wrapper)."""
    env = UnityPy.load(str(in_path))
    scanned, changed, lines, n = _apply_swingbones(
        env, target_name_patterns, stiff_value, drag_value,
        low_dy, low_dz, high_dy, high_dz, use_character_specific,
    )
    _save_env(env, out_path)
    if write_log_file:
        (out_path.with_suffix(out_path.suffix + ".modify_log.txt")).write_text(
            "\n".join(lines), encoding="utf-8"
        )
    return scanned, changed, lines, n


def _apply_swingbones(
    env,
    target_name_patterns,
    stiff_value=None,
    drag_value=None,
    low_dy: float = 0.0,
    low_dz: float = 0.0,
    high_dy: float = 0.0,
    high_dz: float = 0.0,
    use_character_specific=False,
):
    """Edit swing-bone physics on an already-loaded env (no load/save)."""
    obj_by_pid, go_name_by_pid = build_maps(env)
    th = type_histogram(env)

    # auto mode: derive rotation-limit deltas from the breast size when it has
    # already been resized (so the physics match the *current* size), otherwise
    # fall back to the character's stock tier (by character ID).
    char_specific_n = None
    jiggle_source = None
    if use_character_specific:
        size_n = n_from_breast_size(read_current_breast_size(env))
        if size_n is not None:
            char_specific_n = size_n
            jiggle_source = "current breast size"
        else:
            char_id = find_character_id_from_bundle(env)
            if char_id is not None:
                char_specific_n = get_n_value_for_char_id(char_id)
                jiggle_source = f"character ID {char_id} (stock size)"
        if char_specific_n is not None:
            low_dy = -char_specific_n
            low_dz = -char_specific_n
            high_dy = char_specific_n
            high_dz = char_specific_n

    changed = 0
    scanned = 0
    logs = []
    seen_mono = 0
    field_match = 0
    name_resolved = 0
    name_matched = 0
    script_matched = 0

    for obj in env.objects:
        if not is_obj_type(obj, ("MonoBehaviour", 114)):
            continue
        seen_mono += 1

        try:
            tree, data, where = read_tree_safe(obj)
        except Exception as e:
            logs.append(f"[READ_FAIL] pid={obj.path_id} err={e}")
            continue

        has_stiff = get_from_tree(tree, "stiffnessForce") is not None
        has_drag = get_from_tree(tree, "dragForce") is not None
        low_vec = get_from_tree(tree, "lowRotationLimit")
        high_vec = get_from_tree(tree, "highRotationLimit")
        has_low = isinstance(low_vec, dict)
        has_high = isinstance(high_vec, dict)

        if not (has_stiff and has_drag and has_low and has_high):
            continue
        field_match += 1

        cls = try_get_script_class_with_index(obj_by_pid, tree) or ""
        if cls and ("swingbone" in cls.lower()):
            script_matched += 1

        go_pptr = get_from_tree(tree, "m_GameObject")
        go_pid = None
        if isinstance(go_pptr, dict):
            go_pid = go_pptr.get("m_PathID") or go_pptr.get("pathID")

        go_name = None
        if isinstance(go_pid, int):
            go_name = go_name_by_pid.get(go_pid) or go_name_by_pid.get(-go_pid)

        if go_name:
            name_resolved += 1

        if not name_matches_ci(go_name or "", target_name_patterns):
            continue
        name_matched += 1
        scanned += 1

        orig_stiff = get_from_tree(tree, "stiffnessForce")
        orig_drag = get_from_tree(tree, "dragForce")
        orig_low_y = low_vec.get("y") if isinstance(low_vec, dict) else None
        orig_low_z = low_vec.get("z") if isinstance(low_vec, dict) else None
        orig_high_y = high_vec.get("y") if isinstance(high_vec, dict) else None
        orig_high_z = high_vec.get("z") if isinstance(high_vec, dict) else None

        any_change = False

        if stiff_value is not None and orig_stiff is not None:
            if set_in_tree_if_exists(tree, "stiffnessForce", float(stiff_value)):
                any_change = True

        if drag_value is not None and orig_drag is not None:
            if set_in_tree_if_exists(tree, "dragForce", float(drag_value)):
                any_change = True

        if isinstance(low_vec, dict):
            if "y" in low_vec:
                low_vec["y"] = float(low_vec.get("y") or 0.0) + float(low_dy)
                any_change = True
            if "z" in low_vec:
                low_vec["z"] = float(low_vec.get("z") or 0.0) + float(low_dz)
                any_change = True

        if isinstance(high_vec, dict):
            if "y" in high_vec:
                high_vec["y"] = float(high_vec.get("y") or 0.0) + float(high_dy)
                any_change = True
            if "z" in high_vec:
                high_vec["z"] = float(high_vec.get("z") or 0.0) + float(high_dz)
                any_change = True

        if not any_change:
            continue

        try:
            save_tree_safe(obj, data, tree, where)
            changed += 1
            cur_low = get_from_tree(tree, "lowRotationLimit") or {}
            cur_high = get_from_tree(tree, "highRotationLimit") or {}
            logs.append(
                f"[OK] pid={obj.path_id} go='{go_name}' cls='{cls}' "
                f"stiff: {orig_stiff} -> {get_from_tree(tree,'stiffnessForce')} "
                f"drag: {orig_drag} -> {get_from_tree(tree,'dragForce')} "
                f"low(y,z): ({orig_low_y},{orig_low_z}) -> ({cur_low.get('y')},{cur_low.get('z')}) "
                f"high(y,z): ({orig_high_y},{orig_high_z}) -> ({cur_high.get('y')},{cur_high.get('z')})"
            )
        except Exception as e:
            logs.append(f"[SAVE_FAIL] pid={obj.path_id} go='{go_name}' cls='{cls}' err={e}")

    header = [
        f"Type histogram: {dict(th)}",
        f"MonoBehaviours seen: {seen_mono}",
        f"Field-matched: {field_match}",
        f"GO-name resolved: {name_resolved}",
        f"GO-name matched: {name_matched}",
        f"Script matched: {script_matched}",
        f"Scanned targets: {scanned}",
        f"Changed objects: {changed}",
        f"Character specific mode: {use_character_specific}",
    ]
    if use_character_specific and char_specific_n is not None:
        header.append(
            f"Auto jiggle from {jiggle_source}: n-value {char_specific_n}"
        )
    header.append(
        f"Input: stiff={stiff_value} drag={drag_value} "
        f"low(dy,dz)=({low_dy},{low_dz}) high(dy,dz)=({high_dy},{high_dz})"
    )
    return scanned, changed, header + logs, char_specific_n


# ==========================================================================
# 5. Core #2 - LiveCore scaling (Size) editing
# ==========================================================================
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
                    target_cls = "livecoremembernodescaling"  # "LiveCoreMemberNodeScaling".lower()
                    for key in ("m_ClassName", "className", "m_Name", "name"):
                        v = get_from_tree(st, key)
                        if isinstance(v, str) and target_cls in v.lower():
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
    """Find the scaleValues entry with target.m_PathID == target_pid, or create one."""
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


def modify_livecore_scaling(
    in_path: Path,
    out_path: Path,
    breast_go_name: str,
    set_xyz,    # (x,y,z) or None
    add_dxyz,   # (dx,dy,dz)
    write_log_file=True,
):
    """Load a bundle, edit LiveCore scale, save (thin load/save wrapper)."""
    env = UnityPy.load(str(in_path))
    scanned, changed, lines = _apply_livecore_scaling(env, breast_go_name, set_xyz, add_dxyz)
    _save_env(env, out_path)
    if write_log_file:
        (out_path.with_suffix(out_path.suffix + ".scale_log.txt")).write_text(
            "\n".join(lines), encoding="utf-8"
        )
    return scanned, changed, lines


def _apply_livecore_scaling(env, breast_go_name, set_xyz, add_dxyz):
    """Edit LiveCore scale on an already-loaded env (no load/save)."""
    obj_by_pid = build_obj_index(env)

    logs = []
    changed = 0
    scanned = 0

    breast_tr = get_transform_for_breastsize(env, obj_by_pid, breast_go_name=breast_go_name)
    if not breast_tr:
        logs.append(f"[MISS] BreastSize Transform not found (name={breast_go_name})")
    else:
        target_pid = breast_tr.path_id
        try:
            tr_tree, _, _ = read_tree_safe(breast_tr)
            cur_scale = get_from_tree(tr_tree, "m_LocalScale") or {"x": 1, "y": 1, "z": 1}
        except Exception:
            cur_scale = {"x": 1, "y": 1, "z": 1}

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

            scanned += 1
            node, idx, style, created = ensure_scale_entry(scale_list, target_pid)

            if created:
                ov = ensure_dict(node, "originValue")
                if ov:
                    set_vec3(ov, x=cur_scale.get("x"), y=cur_scale.get("y"), z=cur_scale.get("z"))

            sv = ensure_dict(node, "scaledValue")
            if not sv:
                logs.append(f"[SKIP] pid={obj.path_id} no scaledValue")
                continue

            before = (sv.get("x"), sv.get("y"), sv.get("z"))

            if set_xyz is not None:
                set_vec3(sv, x=set_xyz[0], y=set_xyz[1], z=set_xyz[2])
            dx, dy, dz = add_dxyz
            if any(abs(v) > 0 for v in (dx, dy, dz)):
                add_vec3(sv, dx=dx, dy=dy, dz=dz)

            after = (sv.get("x"), sv.get("y"), sv.get("z"))

            try:
                scale_list[idx] = make_elem_for_node(node, style)
                save_tree_safe(obj, data, tree, where)
                changed += 1
                logs.append(
                    f"[OK] LiveCore pid={obj.path_id} target={target_pid} "
                    f"style={style} created={created} {before} -> {after}"
                )
            except KeyError as e:
                alt_style = "wrapped" if style == "raw" else "raw"
                try:
                    scale_list[idx] = make_elem_for_node(node, alt_style)
                    save_tree_safe(obj, data, tree, where)
                    changed += 1
                    logs.append(
                        f"[OK-ALT] LiveCore pid={obj.path_id} target={target_pid} "
                        f"style={alt_style} created={created} {before} -> {after}"
                    )
                except Exception as e2:
                    logs.append(f"[SAVE_FAIL] pid={obj.path_id} err={e2} (alt after {e})")
            except Exception as e:
                logs.append(f"[SAVE_FAIL] pid={obj.path_id} err={e}")

    header = [
        f"Scanned LiveCore objs: {scanned}",
        f"Changed entries: {changed}",
        f"BreastSize name: {breast_go_name}",
        f"Set xyz: {set_xyz}",
        f"Add dxyz: {add_dxyz}",
    ]
    return scanned, changed, header + logs


def _resolve_both_jiggle(target_n, src_eff, jiggle_mode):
    """Pick the swing-bone jiggle tier for Both mode.

    Returns (effective_n, mode_desc). The rotation limits then move by
    low=-effective_n, high=+effective_n -- the same additive convention the
    standalone Dyna auto mode uses, so a tier maps cleanly to a 'jiggleN'
    (e.g. a "target"-mode Nozomi size yields jiggle7, matching `dyna --auto`).

      jiggle_mode (which size the jiggle follows):
        "target" (default) -> the NEW size:        effective_n = target_n
        "source"           -> the previous size:   effective_n = src_eff
        "sum"              -> both added together: effective_n = target_n + src_eff

    `target_n=None` means 'leave the rotation limits alone' (effective_n None).
    """
    if target_n is None:
        return None, "target tier unset -> no rotation-limit change"
    tgt, src = int(target_n), int(src_eff)
    mode = (jiggle_mode or "target").lower()
    if mode in ("source", "prev", "previous", "old"):
        return src, f"follow previous size -> jiggle{src}"
    if mode == "sum":
        return tgt + src, f"sum of both -> jiggle{tgt} + jiggle{src} = jiggle{tgt + src}"
    return tgt, f"follow new size -> jiggle{tgt}"   # "target"/"new"/default


def modify_both_in_bundle(
    in_path: Path,
    out_path: Path,
    patterns,
    stiff_value,
    drag_value,
    breast_go_name,
    set_xyz,
    target_n,
    source_n=None,
    jiggle_mode="target",
    write_log_file=True,
):
    """Apply BOTH swing-bone physics and LiveCore scale to one bundle, save once.

    The size is set absolutely to `set_xyz`. The jiggle delta applied to the
    rotation limits is chosen by `jiggle_mode` (see `_resolve_both_jiggle`):

      * "target" (default) -> jiggle follows the NEW size  (e.g. Nozomi -> jiggle7)
      * "source"           -> jiggle follows the previous/'before' size
      * "sum"              -> the two tiers added together

    The 'before' tier comes from `source_n`:
      * source_n is None  -> auto-detect from the bundle's character ID
                             (unknown -> 0, i.e. treat as a flat base).
      * source_n given    -> use that tier as the 'before' body.

    `target_n=None` skips the rotation-limit change entirely.
    """
    env = UnityPy.load(str(in_path))

    # resolve the source ('before') tier
    auto_cid = None
    if source_n is None:
        auto_cid = find_character_id_from_bundle(env)
        detected = get_n_value_for_char_id(auto_cid) if auto_cid is not None else None
        src_eff = detected if detected is not None else 0
        src_desc = (f"auto: character id {auto_cid} -> jiggle{detected}"
                    if detected is not None
                    else f"auto: character id {auto_cid} (unrecognized) -> treated as jiggle0")
    else:
        src_eff = int(source_n)
        src_desc = f"manual -> jiggle{source_n}"

    effective_n, mode_desc = _resolve_both_jiggle(target_n, src_eff, jiggle_mode)
    if effective_n is None:
        low = high = 0.0
    else:
        low = float(-effective_n)
        high = float(effective_n)

    d_scanned, d_changed, d_lines, _ = _apply_swingbones(
        env, patterns, stiff_value, drag_value,
        low, low, high, high, use_character_specific=False,
    )
    s_scanned, s_changed, s_lines = _apply_livecore_scaling(
        env, breast_go_name, set_xyz, (0.0, 0.0, 0.0)
    )
    _save_env(env, out_path)

    lines = (
        [f"Target body: jiggle{target_n},  scale = {set_xyz}",
         f"Source body: {src_desc}",
         f"Jiggle mode: {(jiggle_mode or 'target').lower()}  ({mode_desc})",
         f"Jiggle applied = {effective_n}  (rotation limits low={low}, high={high})",
         "", "=== Physics (Dyna) ==="]
        + d_lines + ["", "=== Size (LiveCore) ==="] + s_lines
    )
    if write_log_file:
        (out_path.with_suffix(out_path.suffix + ".both_log.txt")).write_text(
            "\n".join(lines), encoding="utf-8"
        )
    return d_scanned, d_changed, s_scanned, s_changed, target_n, effective_n, lines


# ==========================================================================
# 6. Batch runners (shared by GUI/CLI, callback-based)
# ==========================================================================
def _iter_files(in_dir):
    return [f for f in Path(in_dir).rglob("*") if f.is_file()]


def run_dyna_batch(in_dir, out_dir, prefix, suffix, patterns,
                   stiff, drag, ldy, ldz, hdy, hdz, use_auto,
                   on_log, on_progress, should_stop=None):
    files = _iter_files(in_dir)
    total = len(files)
    ok = fail = 0
    for i, file in enumerate(files, 1):
        if should_stop and should_stop():
            on_log("[stopped]")
            break
        rel = file.relative_to(in_dir)
        try:
            if use_auto:
                env_preview = UnityPy.load(str(file))
                out_name = generate_output_filename(file, prefix, suffix, True, env_preview)
            else:
                out_name = f"{prefix}{file.stem}{suffix}{file.suffix}"
            out_path = Path(out_dir) / rel.parent / out_name
            _, changed, _, n = modify_swingbones_in_bundle(
                file, out_path, patterns, stiff, drag, ldy, ldz, hdy, hdz,
                use_character_specific=use_auto,
            )
            ok += 1
            tag = f"(jiggle{n})" if (use_auto and n is not None) else ""
            on_log(f"OK   {file.name} -> {out_name} {tag}".rstrip())
        except Exception as e:
            fail += 1
            on_log(f"FAIL {file.name}: {e}")
        on_progress(i, total)
    on_log("")
    on_log(f"Done. total={total}  ok={ok}  fail={fail}")
    return total, ok, fail


def run_size_batch(in_dir, out_dir, prefix, suffix, breast_name, setv, addv,
                   on_log, on_progress, should_stop=None):
    files = _iter_files(in_dir)
    total = len(files)
    ok = fail = 0
    tot_scanned = tot_changed = 0
    for i, file in enumerate(files, 1):
        if should_stop and should_stop():
            on_log("[stopped]")
            break
        rel = file.relative_to(in_dir)
        out_name = f"{prefix}{file.stem}{suffix}{file.suffix}"
        out_path = Path(out_dir) / rel.parent / out_name
        try:
            scanned, changed, _ = modify_livecore_scaling(file, out_path, breast_name, setv, addv)
            tot_scanned += scanned
            tot_changed += changed
            ok += 1
            on_log(f"OK   {file.name} -> {out_name} (scanned={scanned}, changed={changed})")
        except Exception as e:
            fail += 1
            on_log(f"FAIL {file.name}: {e}")
        on_progress(i, total)
    on_log("")
    on_log(f"Done. total={total}  ok={ok}  fail={fail}  scanned={tot_scanned}  changed={tot_changed}")
    return total, ok, fail


def run_both_batch(in_dir, out_dir, prefix, suffix, patterns, stiff, drag,
                   breast_name, set_xyz, target_n, append_jiggle,
                   on_log, on_progress, should_stop=None, source_n=None, label="",
                   jiggle_mode="target"):
    files = _iter_files(in_dir)
    total = len(files)
    ok = fail = 0
    for i, file in enumerate(files, 1):
        if should_stop and should_stop():
            on_log("[stopped]")
            break
        rel = file.relative_to(in_dir)
        jig = _both_filename_suffix(label, target_n, append_jiggle)
        out_name = f"{prefix}{file.stem}{suffix}{jig}{file.suffix}"
        out_path = Path(out_dir) / rel.parent / out_name
        try:
            _, d_ch, _, s_ch, _, eff, _ = modify_both_in_bundle(
                file, out_path, patterns, stiff, drag, breast_name, set_xyz,
                target_n, source_n=source_n, jiggle_mode=jiggle_mode,
            )
            ok += 1
            d_tag = f"jiggle={eff}" if eff is not None else ""
            on_log(f"OK   {file.name} -> {out_name} (dyna={d_ch}, size={s_ch}) {d_tag}".rstrip())
        except Exception as e:
            fail += 1
            on_log(f"FAIL {file.name}: {e}")
        on_progress(i, total)
    on_log("")
    on_log(f"Done. total={total}  ok={ok}  fail={fail}")
    return total, ok, fail


# ==========================================================================
# 6b. Asset library helpers (elichika sukusta: extracted -> modded workflow)
# ==========================================================================
# Mirrors llas_asset_extractor.py, which decrypts game packs into
#   <sukusta>/extracted/<category>/...   (3D character models live in 3d_model/)
# This tool reads a bundle from there (or from <sukusta>/modded/), mods it, and
# writes the result into <sukusta>/modded/, preserving the sub-path.
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
    """True if the file starts with the UnityFS magic (i.e. an asset bundle)."""
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
    src_root (falls back to the bare filename if src_path isn't under src_root)."""
    src_path = Path(os.path.expanduser(str(src_path)))
    modded_root = Path(os.path.expanduser(str(modded_root)))
    try:
        rel = src_path.resolve().relative_to(Path(os.path.expanduser(str(src_root))).resolve())
    except Exception:
        rel = Path(src_path.name)
    out_name = rel.stem + extra_suffix + rel.suffix
    return modded_root / rel.parent / out_name


def _default_library_params():
    return {
        "patterns": ["LeftBreast_Dyna", "RightBreast_Dyna"],
        "breast_name": "BreastSize",
        "stiff": None, "drag": None,
        "set_xyz": None, "add_dxyz": (0.0, 0.0, 0.0),
        "target_n": None, "source_n": None, "jiggle_mode": "target",
        "ldy": 0.0, "ldz": 0.0, "hdy": 0.0, "hdz": 0.0, "use_auto": False,
    }


def run_library_mod(in_path, out_path, mode, params):
    """Apply the chosen mod ('both' | 'size' | 'dyna') to in_path and write the
    result to out_path. Handles in-place overwrite safely (temp + replace) and
    does not write the per-file .log sidecars (keeps the modded folder clean).
    Returns a one-line summary string."""
    p = params
    in_path = Path(in_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    same = False
    try:
        same = in_path.resolve() == out_path.resolve()
    except Exception:
        pass
    write_path = out_path.with_name(out_path.name + ".tmp_mod") if same else out_path

    if mode == "both":
        res = modify_both_in_bundle(
            in_path, write_path, p["patterns"], p["stiff"], p["drag"],
            p["breast_name"], p["set_xyz"], p["target_n"],
            source_n=p["source_n"], jiggle_mode=p.get("jiggle_mode", "target"),
            write_log_file=False)
        eff = res[5]
        summary = (f"both: dyna changed={res[1]}, size changed={res[3]}, "
                   f"jiggle={eff}" if eff is not None
                   else f"both: dyna changed={res[1]}, size changed={res[3]}")
    elif mode == "size":
        sc, ch, _ = modify_livecore_scaling(
            in_path, write_path, p["breast_name"], p["set_xyz"], p["add_dxyz"],
            write_log_file=False)
        summary = f"size: scanned={sc}, changed={ch}"
    else:  # dyna
        sc, ch, _, n = modify_swingbones_in_bundle(
            in_path, write_path, p["patterns"], p["stiff"], p["drag"],
            p["ldy"], p["ldz"], p["hdy"], p["hdz"],
            use_character_specific=p["use_auto"], write_log_file=False)
        summary = f"physics: scanned={sc}, changed={ch}" + (
            f", jiggle{n}" if (p["use_auto"] and n is not None) else "")

    if same:
        os.replace(write_path, out_path)
    return summary


def _menu_setup_readline():
    try:
        import readline  # noqa: F401  (enables arrow-key editing / history)
    except Exception:
        pass


def _box(title):
    line = "-" * (len(title) + 2)
    return f"+{line}+\n| {title} |\n+{line}+"


def _ask(label, default=None):
    suffix = f" [{default}]" if default not in (None, "") else ""
    val = input(f"{label}{suffix}: ").strip()
    if not val and default is not None:
        return str(default)
    return val


def _ask_path(label, default=None, must_exist=False):
    while True:
        v = _ask(label, default)
        if not v:
            return ""
        p = os.path.expanduser(v)
        if must_exist and not os.path.exists(p):
            print(f"  ! path not found: {p}\n")
            continue
        return p


def _ask_float(label, default=None, allow_blank=True):
    while True:
        v = _ask(label, default)
        if v == "" and allow_blank:
            return None
        try:
            return float(v)
        except ValueError:
            print("  ! please enter a number.\n")


def _ask_yesno(label, default=False):
    d = "Y/n" if default else "y/N"
    v = input(f"{label} [{d}]: ").strip().lower()
    if not v:
        return default
    return v in ("y", "yes")


def _pick_index(prompt, count, default=1):
    sel = _ask(prompt, str(default))
    try:
        i = int(sel)
        if 1 <= i <= count:
            return i - 1
    except ValueError:
        pass
    return default - 1


def _parse_multi_select(s, n):
    """Parse '3', '1,4-8', '1, 4-8, 14', 'all' -> sorted 0-based indices (1..n)."""
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


def _print_logs_paged(logs, head=40):
    if len(logs) <= head:
        print("\n".join(logs))
        return
    print("\n".join(logs[:head]))
    print(f"\n... ({len(logs) - head} more lines)")
    if _ask_yesno("Print full log?", default=False):
        print("\n".join(logs))


def _progress_bar(done, total):
    bar_w = 24
    filled = int(bar_w * done / total) if total else bar_w
    bar = "#" * filled + "-" * (bar_w - filled)
    print(f"\r  [{bar}] {done}/{total}", end="", flush=True)
    if done >= total:
        print()


def menu_dyna():
    print("\n" + _box("Physics (SwingBone Dyna)"))
    mode = _ask("Mode   1) Single file   2) Batch (folder)", "1")

    patterns = ["LeftBreast_Dyna", "RightBreast_Dyna"]  # standard SIFAS breast bones

    use_auto = _ask_yesno("Per-character auto mode? (rotation limits from char ID + jiggleN filename)",
                          default=False)

    stiff = _ask_float("stiffnessForce (blank = keep)", "0.02")
    drag = _ask_float("dragForce (blank = keep)", "0.3")

    if use_auto:
        ldy = ldz = hdy = hdz = 0.0   # decided inside the core from the character ID
        print("  . auto mode: rotation-limit deltas are derived from the character ID")
    else:
        ldy = _ask_float("low Y delta", "-1.0", allow_blank=False)
        ldz = _ask_float("low Z delta", "-1.0", allow_blank=False)
        hdy = _ask_float("high Y delta", "1.0", allow_blank=False)
        hdz = _ask_float("high Z delta", "1.0", allow_blank=False)

    def on_log(s):
        print(s)

    if mode == "2":
        in_dir = _ask_path("Input folder", must_exist=True)
        out_dir = _ask_path("Output folder")
        prefix = _ask("Output prefix", "")
        suffix = _ask("Output suffix", "")
        if not in_dir or not out_dir:
            print("Input/output folders are required."); return
        print("\nWorking...\n")
        run_dyna_batch(in_dir, out_dir, prefix, suffix, patterns,
                       stiff, drag, ldy, ldz, hdy, hdz, use_auto,
                       on_log, _progress_bar)
    else:
        in_file = _ask_path("Input bundle", must_exist=True)
        out_file = _ask_path("Output path")
        if not in_file or not out_file:
            print("Input/output paths are required."); return
        print("\nWorking...\n")
        try:
            scanned, changed, logs, n = modify_swingbones_in_bundle(
                Path(in_file), Path(out_file), patterns,
                stiff, drag, ldy, ldz, hdy, hdz,
                use_character_specific=use_auto,
            )
            print(f"Done. scanned={scanned} changed={changed}"
                  + (f" (jiggle{n})" if (use_auto and n is not None) else ""))
            if _ask_yesno("Show detailed log?", default=False):
                _print_logs_paged(logs)
        except Exception as e:
            print(f"Error: {e}")


def _menu_choose_breast_scale():
    """Return (set_xyz, add_dxyz) chosen interactively, or (None, (0,0,0))."""
    print("\nHow do you want to set scaledValue?")
    print("  1) Enlarge preset   (per-character; formula y=1+Y, x,z=1+2Y)")
    print("  2) Reduce preset    (per-character, irregular)")
    print("  3) Custom formula   (enter Y)")
    print("  4) Manual x, y, z")
    print("  5) Add delta (dx, dy, dz)")
    kind = _ask("Select", "1")

    if kind == "2":
        print("\nReduce presets:")
        for i, (nm, (x, y, z), _n) in enumerate(BREAST_REDUCE_PRESETS, 1):
            print(f"  {i:2d}) {nm:18s} -> ({_fmt_num(x)}, {_fmt_num(y)}, {_fmt_num(z)})")
        idx = _pick_index("Pick", len(BREAST_REDUCE_PRESETS))
        return BREAST_REDUCE_PRESETS[idx][1], (0.0, 0.0, 0.0)

    if kind == "3":
        Y = _ask_float("Enter Y (0 < Y < 1)", "0.05", allow_blank=False)
        return breast_enlarge_xyz(Y), (0.0, 0.0, 0.0)

    if kind == "4":
        x = _ask_float("set X", "1.0", allow_blank=False)
        y = _ask_float("set Y", "1.0", allow_blank=False)
        z = _ask_float("set Z", "1.0", allow_blank=False)
        return (x, y, z), (0.0, 0.0, 0.0)

    if kind == "5":
        dx = _ask_float("add dX", "0", allow_blank=False)
        dy = _ask_float("add dY", "0", allow_blank=False)
        dz = _ask_float("add dZ", "0", allow_blank=False)
        return None, (dx, dy, dz)

    # default: enlarge preset
    print("\nEnlarge presets (formula y=1+Y, x,z=1+2Y):")
    for i, (nm, (x, y, z), _n) in enumerate(BREAST_ENLARGE_PRESETS, 1):
        print(f"  {i:2d}) {nm:18s} -> ({_fmt_num(x)}, {_fmt_num(y)}, {_fmt_num(z)})")
    idx = _pick_index("Pick", len(BREAST_ENLARGE_PRESETS))
    return BREAST_ENLARGE_PRESETS[idx][1], (0.0, 0.0, 0.0)


def menu_size():
    print("\n" + _box("Size (LiveCore Scale)"))
    mode = _ask("Mode   1) Single file   2) Batch (folder)", "1")
    breast_name = "BreastSize"  # standard SIFAS scaling GameObject

    setv, addv = _menu_choose_breast_scale()

    def on_log(s):
        print(s)

    if mode == "2":
        in_dir = _ask_path("Input folder", must_exist=True)
        out_dir = _ask_path("Output folder")
        prefix = _ask("Output prefix", "")
        suffix = _ask("Output suffix", "")
        if not in_dir or not out_dir:
            print("Input/output folders are required."); return
        print("\nWorking...\n")
        run_size_batch(in_dir, out_dir, prefix, suffix, breast_name, setv, addv,
                       on_log, _progress_bar)
    else:
        in_file = _ask_path("Input bundle", must_exist=True)
        out_file = _ask_path("Output path")
        if not in_file or not out_file:
            print("Input/output paths are required."); return
        print("\nWorking...\n")
        try:
            scanned, changed, logs = modify_livecore_scaling(
                Path(in_file), Path(out_file), breast_name, setv, addv
            )
            print(f"Done. scanned={scanned} changed={changed}")
            if _ask_yesno("Show detailed log?", default=False):
                _print_logs_paged(logs)
        except Exception as e:
            print(f"Error: {e}")


def _safe_token(s):
    """Filename-safe token from a preset label (letters/digits only)."""
    return "".join(c for c in (s or "") if c.isalnum())


def _both_filename_suffix(label, target_n, want=True):
    """Optional '_<Size>_jiggleN' filename tag for Both mode (size + jiggle)."""
    if not want:
        return ""
    parts = []
    tok = _safe_token(label)
    if tok:
        parts.append(tok)
    if target_n is not None:
        parts.append(f"jiggle{target_n}")
    return ("_" + "_".join(parts)) if parts else ""


def _menu_pick_both_params():
    """Interactively choose target + source body and the jiggle mode.
    Returns (label, xyz, target_n, source_n, jiggle_mode)."""
    print("\nTarget body  (sets the new scale and the target jiggle tier):")
    for i, (nm, (x, y, z), n) in enumerate(BREAST_PRESETS_ALL, 1):
        print(f"  {i:2d}) {nm:18s} -> scale ({_fmt_num(x)}, {_fmt_num(y)}, {_fmt_num(z)})  jiggle{n}")
    idx = _pick_index("Pick target", len(BREAST_PRESETS_ALL))
    label, xyz, target_n = BREAST_PRESETS_ALL[idx]
    print(f"  target: {label}  scale={xyz}  jiggle{target_n}")

    print("\nSource body  (the 'before' body, used by the 'previous'/'sum' jiggle modes):")
    print("   0) Auto-detect from each bundle's character ID  (recommended)")
    for i, (snm, (x, y, z), sn) in enumerate(BREAST_PRESETS_ALL, 1):
        print(f"  {i:2d}) {snm:18s} (jiggle{sn})")
    sraw = _ask("Pick source", "0")
    source_n = None
    if sraw.strip() not in ("", "0"):
        try:
            si = int(sraw) - 1
            if 0 <= si < len(BREAST_PRESETS_ALL):
                source_n = BREAST_PRESETS_ALL[si][2]
        except ValueError:
            source_n = None
    print("  source: auto-detect" if source_n is None else f"  source: jiggle{source_n}")

    print("\nWhich size should the jiggle follow?")
    print(f"  1) New size       (jiggle = target tier, jiggle{target_n})   [default]")
    print("  2) Previous size  (jiggle = source tier)")
    print("  3) Sum of both    (jiggle = target + source)")
    jraw = _ask("Select", "1")
    jiggle_mode = {"2": "source", "3": "sum"}.get(jraw.strip(), "target")
    print(f"  jiggle mode: {jiggle_mode}")
    return label, xyz, target_n, source_n, jiggle_mode


def menu_both():
    print("\n" + _box("Both (Dyna + Size)"))
    mode = _ask("Mode   1) Single file   2) Batch (folder)", "1")

    label, xyz, target_n, source_n, jiggle_mode = _menu_pick_both_params()

    patterns = ["LeftBreast_Dyna", "RightBreast_Dyna"]  # standard SIFAS breast bones
    breast_name = "BreastSize"                            # standard scaling GameObject
    stiff = _ask_float("stiffnessForce (blank = keep)", "0.02")
    drag = _ask_float("dragForce (blank = keep)", "0.3")

    def on_log(s):
        print(s)

    if mode == "2":
        in_dir = _ask_path("Input folder", must_exist=True)
        out_dir = _ask_path("Output folder")
        prefix = _ask("Output prefix", "")
        suffix = _ask("Output suffix", "")
        append_jiggle = _ask_yesno("Append size + jiggle to output filename? (e.g. _Emma_jiggle6)",
                                   default=True)
        if not in_dir or not out_dir:
            print("Input/output folders are required."); return
        print("\nWorking...\n")
        run_both_batch(in_dir, out_dir, prefix, suffix, patterns, stiff, drag,
                       breast_name, xyz, target_n, append_jiggle, on_log, _progress_bar,
                       source_n=source_n, label=label, jiggle_mode=jiggle_mode)
    else:
        in_file = _ask_path("Input bundle", must_exist=True)
        out_file = _ask_path("Output path")
        if not in_file or not out_file:
            print("Input/output paths are required."); return
        print("\nWorking...\n")
        try:
            d_sc, d_ch, s_sc, s_ch, tn, eff, logs = modify_both_in_bundle(
                Path(in_file), Path(out_file), patterns, stiff, drag, breast_name, xyz,
                target_n, source_n=source_n, jiggle_mode=jiggle_mode
            )
            print(f"Done. dyna changed={d_ch}, size changed={s_ch}, "
                  f"jiggle={eff}" if eff is not None else
                  f"Done. dyna changed={d_ch}, size changed={s_ch}")
            if _ask_yesno("Show detailed log?", default=False):
                _print_logs_paged(logs)
        except Exception as e:
            print(f"Error: {e}")


def menu_library():
    print("\n" + _box("Mod from library (extracted -> modded)"))
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
        print("Extract some first (Mod Menu -> extract), or choose another folder.")
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

    mtype = _ask("\nMod   1) Both (size + jiggle)   2) Size only   3) Physics only", "1")
    params = _default_library_params()
    extra_suffix = ""

    if mtype == "2":
        mode = "size"
        setv, addv = _menu_choose_breast_scale()
        params["set_xyz"], params["add_dxyz"] = setv, addv
    elif mtype == "3":
        mode = "dyna"
        params["use_auto"] = _ask_yesno("Per-character auto mode (jiggle from char ID)?", default=True)
        params["stiff"] = _ask_float("stiffnessForce (blank = keep)", "0.02")
        params["drag"] = _ask_float("dragForce (blank = keep)", "0.3")
        if not params["use_auto"]:
            params["ldy"] = _ask_float("low Y delta", "-1.0", allow_blank=False)
            params["ldz"] = _ask_float("low Z delta", "-1.0", allow_blank=False)
            params["hdy"] = _ask_float("high Y delta", "1.0", allow_blank=False)
            params["hdz"] = _ask_float("high Z delta", "1.0", allow_blank=False)
    else:
        mode = "both"
        label, xyz, target_n, source_n, jiggle_mode = _menu_pick_both_params()
        params["set_xyz"], params["target_n"], params["source_n"] = xyz, target_n, source_n
        params["jiggle_mode"] = jiggle_mode
        params["stiff"] = _ask_float("stiffnessForce (blank = keep)", "0.02")
        params["drag"] = _ask_float("dragForce (blank = keep)", "0.3")
        if _ask_yesno("Append size + jiggle to output filename? (e.g. _Emma_jiggle6)", default=True):
            extra_suffix = _both_filename_suffix(label, target_n, True)

    # Bone/GameObject names use the standard SIFAS defaults
    # (LeftBreast_Dyna / RightBreast_Dyna, BreastSize) - no need to ask.

    print(f"\nExporting to {modded} ...\n")
    ok = fail = 0
    for i in chosen:
        b = bundles[i]
        out_path = modded_output_path(b, src_root, modded, extra_suffix=extra_suffix)
        try:
            summary = run_library_mod(b, out_path, mode, params)
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


def _menu_advanced():
    """Manual file/folder path modes (for power users)."""
    while True:
        print("\nAdvanced - manual file/folder paths")
        print("  1) Physics (SwingBone dynamics)")
        print("  2) Size (LiveCore scale)")
        print("  3) Both (Dyna + Size)")
        print("  b) Back")
        choice = input("> ").strip().lower()
        if choice in ("b", "back", "q", "0", ""):
            return
        elif choice == "1":
            menu_dyna()
        elif choice == "2":
            menu_size()
        elif choice == "3":
            menu_both()
        else:
            print("Please choose 1, 2, 3, or b.")


def run_menu():
    ensure_unitypy()
    _menu_setup_readline()
    print()
    print("==========================================")
    print("            SIFAS Breast Tuner")
    print("      (Termux / headless text mode)")
    print("==========================================")
    while True:
        print("\nWhat would you like to do?")
        print("  1) Mod costumes from your library   (recommended - just pick from a list)")
        print("  2) Advanced (type file/folder paths)")
        print("  q) Quit")
        choice = input("> ").strip().lower()
        if choice in ("q", "quit", "exit"):
            print("Bye.")
            break
        elif choice in ("1", ""):     # default = the easy, no-typing flow
            menu_library()
        elif choice == "2":
            _menu_advanced()
        else:
            print("Please choose 1, 2, or q.")


# ==========================================================================
# 8. Tkinter GUI (desktop)
# ==========================================================================
def run_gui():
    ensure_unitypy()
    import threading
    import queue
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    PAD = dict(padx=6, pady=4)

    class ScrollableFrame(ttk.Frame):
        """A vertically scrollable container. Put content into `.body`.

        Fixes the macOS issue where a tall tab overflowed the window and the
        bottom got clipped: content now scrolls inside the tab instead.
        """
        def __init__(self, parent):
            super().__init__(parent)
            self.canvas = tk.Canvas(self, highlightthickness=0)
            vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.canvas.configure(yscrollcommand=vsb.set)
            vsb.pack(side="right", fill="y")
            self.canvas.pack(side="left", fill="both", expand=True)

            self.body = ttk.Frame(self.canvas, padding=10)
            self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")

            # keep the scrollregion in sync with the content height
            self.body.bind(
                "<Configure>",
                lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
            )
            # make the inner frame track the canvas width (so fill='x' works)
            self.canvas.bind(
                "<Configure>",
                lambda e: self.canvas.itemconfigure(self._win, width=e.width),
            )

        def _on_wheel(self, e):
            delta = e.delta
            if delta == 0 and getattr(e, "num", 0) in (4, 5):
                delta = 120 if e.num == 4 else -120
            self.canvas.yview_scroll(-1 if delta > 0 else 1, "units")

        def bind_wheel(self):
            """Bind mouse-wheel / trackpad scroll on every child of this frame."""
            self._bind_tree(self)

        def _bind_tree(self, w):
            w.bind("<MouseWheel>", self._on_wheel, add="+")   # Win/macOS
            w.bind("<Button-4>", self._on_wheel, add="+")     # Linux up
            w.bind("<Button-5>", self._on_wheel, add="+")     # Linux down
            for c in w.winfo_children():
                self._bind_tree(c)

    class TunerGUI:
        def __init__(self, root):
            self.root = root
            self.q = queue.Queue()
            self.worker = None

            root.geometry("860x720")
            root.minsize(680, 480)

            try:
                style = ttk.Style()
                if "clam" in style.theme_names():
                    style.theme_use("clam")
                style.configure("Run.TButton", font=("TkDefaultFont", 10, "bold"))
            except Exception:
                pass

            self.outer = None
            self._build_ui()

        def _tkvar_snapshot(self):
            """Capture every tk variable on self so values survive a rebuild."""
            snap = {}
            for k, v in list(self.__dict__.items()):
                if isinstance(v, (tk.StringVar, tk.BooleanVar, tk.IntVar, tk.DoubleVar)):
                    try:
                        snap[k] = v.get()
                    except Exception:
                        pass
            return snap

        def _build_ui(self):
            # Rebuilds the whole UI; called once at start and again on a language
            # change so switching is instant (no restart). Entered values are
            # snapshotted and restored across the rebuild.
            snap = self._tkvar_snapshot() if getattr(self, "outer", None) else {}
            if getattr(self, "outer", None) is not None:
                self.outer.destroy()

            root = self.root
            root.title(_tr("SIFAS Breast Tuner - Physics / Size / Both"))

            outer = ttk.Frame(root, padding=(10, 10, 10, 8))
            outer.pack(fill="both", expand=True)
            self.outer = outer

            # ---- language picker (top) ----
            langbar = ttk.Frame(outer)
            langbar.pack(fill="x", pady=(0, 6))
            ttk.Label(langbar, text=_tr("Language")).pack(side="left")
            self._lang_names = [name for _c, name in _lang_opts()]
            self._lang_code_by_name = {name: code for code, name in _lang_opts()}
            name_by_code = {code: name for code, name in _lang_opts()}
            self._lang_display = tk.StringVar(
                value=name_by_code.get(_get_lang(), self._lang_names[0]))
            lang_cb = ttk.Combobox(langbar, textvariable=self._lang_display,
                                   values=self._lang_names, state="readonly", width=10)
            lang_cb.pack(side="left", padx=(6, 0))
            lang_cb.bind("<<ComboboxSelected>>", lambda e: self._on_language())

            # Notebook expands to fill available space; each tab scrolls so a
            # tall tab can never push the log panel off the bottom of the window.
            nb = ttk.Notebook(outer)
            nb.pack(fill="both", expand=True)

            phys_scroll = ScrollableFrame(nb)
            size_scroll = ScrollableFrame(nb)
            both_scroll = ScrollableFrame(nb)
            lib_scroll = ScrollableFrame(nb)
            nb.add(phys_scroll, text="  " + _tr("Physics (Dyna)") + "  ")
            nb.add(size_scroll, text="  " + _tr("Size") + "  ")
            nb.add(both_scroll, text="  " + _tr("Both") + "  ")
            nb.add(lib_scroll, text="  " + _tr("Library") + "  ")

            self._build_physics(phys_scroll.body)
            self._build_size(size_scroll.body)
            self._build_both(both_scroll.body)
            self._build_library(lib_scroll.body)
            phys_scroll.bind_wheel()
            size_scroll.bind_wheel()
            both_scroll.bind_wheel()
            lib_scroll.bind_wheel()

            # ---- shared bottom: progress + log (pinned, fixed height) ----
            bottom = ttk.LabelFrame(outer, text=_tr("Progress / Log"), padding=8)
            bottom.pack(fill="x", pady=(10, 0))   # fixed height, always visible

            self.progress = ttk.Progressbar(bottom, mode="determinate")
            self.progress.pack(fill="x", pady=(0, 6))

            logfrm = ttk.Frame(bottom)
            logfrm.pack(fill="both", expand=True)
            self.log = tk.Text(logfrm, height=7, wrap="none", state="disabled",
                               font=("TkFixedFont", 9))
            ysb = ttk.Scrollbar(logfrm, orient="vertical", command=self.log.yview)
            xsb = ttk.Scrollbar(logfrm, orient="horizontal", command=self.log.xview)
            self.log.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
            self.log.grid(row=0, column=0, sticky="nsew")
            ysb.grid(row=0, column=1, sticky="ns")
            xsb.grid(row=1, column=0, sticky="ew")
            logfrm.rowconfigure(0, weight=1)
            logfrm.columnconfigure(0, weight=1)

            btnbar = ttk.Frame(bottom)
            btnbar.pack(fill="x", pady=(6, 0))
            ttk.Button(btnbar, text=_tr("Clear log"), command=self._clear_log).pack(side="left")
            ttk.Button(btnbar, text=_tr("Save log"), command=self._save_log).pack(side="left", padx=6)
            self.status = ttk.Label(btnbar, text=_tr("Idle"))
            self.status.pack(side="right")

            # restore any values the user had typed before the rebuild
            for k, val in snap.items():
                var = getattr(self, k, None)
                if isinstance(var, (tk.StringVar, tk.BooleanVar, tk.IntVar, tk.DoubleVar)):
                    try:
                        var.set(val)
                    except Exception:
                        pass

        # ---------- language ----------
        def _on_language(self):
            """Switch the UI language immediately (no restart) and persist it."""
            code = self._lang_code_by_name.get(self._lang_display.get())
            if not code:
                return
            _set_lang(code)
            self._build_ui()

        # ---------- widget builders ----------
        def _file_row(self, parent, r, label, var, save=False, is_dir=False):
            ttk.Label(parent, text=_tr(label)).grid(row=r, column=0, sticky="w", **PAD)
            ttk.Entry(parent, textvariable=var).grid(row=r, column=1, sticky="ew", **PAD)
            if is_dir:
                cmd = lambda: self._pick_dir(var)
            elif save:
                cmd = lambda: self._pick_save(var)
            else:
                cmd = lambda: self._pick_open(var)
            ttk.Button(parent, text=_tr("Browse"), command=cmd).grid(row=r, column=2, **PAD)
            parent.columnconfigure(1, weight=1)

        def _build_physics(self, tab):
            self.p_in_file = tk.StringVar()
            self.p_out_file = tk.StringVar()
            self.p_in_dir = tk.StringVar()
            self.p_out_dir = tk.StringVar()
            self.p_prefix = tk.StringVar(value="")
            self.p_suffix = tk.StringVar(value="")

            self.p_patterns = tk.StringVar(value="LeftBreast_Dyna, RightBreast_Dyna")
            self.p_stiff = tk.StringVar(value="0.02")
            self.p_drag = tk.StringVar(value="0.3")
            self.p_ldy = tk.StringVar(value="-1.0")
            self.p_ldz = tk.StringVar(value="-1.0")
            self.p_hdy = tk.StringVar(value="1.0")
            self.p_hdz = tk.StringVar(value="1.0")
            self.p_auto = tk.BooleanVar(value=False)

            # single
            sf = ttk.LabelFrame(tab, text=_tr("Single file"), padding=8)
            sf.pack(fill="x")
            self._file_row(sf, 0, "Input bundle", self.p_in_file)
            self._file_row(sf, 1, "Output path", self.p_out_file, save=True)
            ttk.Button(sf, text=_tr("Run (single)"), style="Run.TButton",
                       command=self._run_physics_single).grid(row=2, column=0, columnspan=3, pady=6)

            # batch
            bf = ttk.LabelFrame(tab, text=_tr("Batch (folder)"), padding=8)
            bf.pack(fill="x", pady=(8, 0))
            self._file_row(bf, 0, "Input folder", self.p_in_dir, is_dir=True)
            self._file_row(bf, 1, "Output folder", self.p_out_dir, is_dir=True)
            ttk.Label(bf, text="prefix").grid(row=2, column=0, sticky="w", **PAD)
            ttk.Entry(bf, textvariable=self.p_prefix, width=18).grid(row=2, column=1, sticky="w", **PAD)
            ttk.Label(bf, text="suffix").grid(row=3, column=0, sticky="w", **PAD)
            ttk.Entry(bf, textvariable=self.p_suffix, width=18).grid(row=3, column=1, sticky="w", **PAD)
            ttk.Button(bf, text=_tr("Run (batch)"), style="Run.TButton",
                       command=self._run_physics_batch).grid(row=4, column=0, columnspan=3, pady=6)

            # parameters
            pf = ttk.LabelFrame(tab, text=_tr("Physics parameters"), padding=8)
            pf.pack(fill="x", pady=(8, 0))
            ttk.Label(pf, text="Target GO patterns (comma)").grid(row=0, column=0, sticky="w", **PAD)
            ttk.Entry(pf, textvariable=self.p_patterns).grid(row=0, column=1, columnspan=3, sticky="ew", **PAD)
            pf.columnconfigure(1, weight=1)

            ttk.Label(pf, text="Presets").grid(row=1, column=0, sticky="w", **PAD)
            preset = ttk.Frame(pf); preset.grid(row=1, column=1, columnspan=3, sticky="w", **PAD)
            ttk.Button(preset, text="Softer (0.01/0.2)", width=16,
                       command=lambda: self._set_phys(0.01, 0.2)).pack(side="left", padx=2)
            ttk.Button(preset, text="Soft (0.02/0.3)", width=16,
                       command=lambda: self._set_phys(0.02, 0.3)).pack(side="left", padx=2)
            ttk.Button(preset, text="Firm (0.05/0.5)", width=16,
                       command=lambda: self._set_phys(0.05, 0.5)).pack(side="left", padx=2)

            grid2 = ttk.Frame(pf); grid2.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
            ttk.Label(grid2, text="stiffnessForce").grid(row=0, column=0, sticky="w", **PAD)
            ttk.Entry(grid2, textvariable=self.p_stiff, width=10).grid(row=0, column=1, **PAD)
            ttk.Label(grid2, text="dragForce").grid(row=0, column=2, sticky="w", **PAD)
            ttk.Entry(grid2, textvariable=self.p_drag, width=10).grid(row=0, column=3, **PAD)

            self.p_auto_chk = ttk.Checkbutton(
                pf, text="Per-character auto (rotation limits from char ID + jiggleN filename)",
                variable=self.p_auto, command=self._toggle_auto)
            self.p_auto_chk.grid(row=3, column=0, columnspan=4, sticky="w", **PAD)

            mf = ttk.Frame(pf); mf.grid(row=4, column=0, columnspan=4, sticky="w")
            ttk.Label(mf, text="low Y/Z delta").grid(row=0, column=0, sticky="w", **PAD)
            self.e_ldy = ttk.Entry(mf, textvariable=self.p_ldy, width=8); self.e_ldy.grid(row=0, column=1, **PAD)
            self.e_ldz = ttk.Entry(mf, textvariable=self.p_ldz, width=8); self.e_ldz.grid(row=0, column=2, **PAD)
            ttk.Label(mf, text="high Y/Z delta").grid(row=1, column=0, sticky="w", **PAD)
            self.e_hdy = ttk.Entry(mf, textvariable=self.p_hdy, width=8); self.e_hdy.grid(row=1, column=1, **PAD)
            self.e_hdz = ttk.Entry(mf, textvariable=self.p_hdz, width=8); self.e_hdz.grid(row=1, column=2, **PAD)

            info = "Character -> jiggle mapping:\n" + "\n".join("  " + ln for ln in jiggle_mapping_lines())
            ttk.Label(pf, text=info, justify="left", font=("TkDefaultFont", 8),
                      foreground="#555").grid(row=5, column=0, columnspan=4, sticky="w", **PAD)

        def _build_size(self, tab):
            self.s_in_file = tk.StringVar()
            self.s_out_file = tk.StringVar()
            self.s_in_dir = tk.StringVar()
            self.s_out_dir = tk.StringVar()
            self.s_prefix = tk.StringVar(value="")
            self.s_suffix = tk.StringVar(value="")
            self.s_name = tk.StringVar(value="BreastSize")
            self.s_setx = tk.StringVar(value="")
            self.s_sety = tk.StringVar(value="")
            self.s_setz = tk.StringVar(value="")
            self.s_adx = tk.StringVar(value="0")
            self.s_ady = tk.StringVar(value="0")
            self.s_adz = tk.StringVar(value="0")
            self.s_customy = tk.StringVar(value="0.05")

            sf = ttk.LabelFrame(tab, text=_tr("Single file"), padding=8)
            sf.pack(fill="x")
            self._file_row(sf, 0, "Input bundle", self.s_in_file)
            self._file_row(sf, 1, "Output path", self.s_out_file, save=True)
            ttk.Button(sf, text=_tr("Run (single)"), style="Run.TButton",
                       command=self._run_size_single).grid(row=2, column=0, columnspan=3, pady=6)

            bf = ttk.LabelFrame(tab, text=_tr("Batch (folder)"), padding=8)
            bf.pack(fill="x", pady=(8, 0))
            self._file_row(bf, 0, "Input folder", self.s_in_dir, is_dir=True)
            self._file_row(bf, 1, "Output folder", self.s_out_dir, is_dir=True)
            ttk.Label(bf, text="prefix").grid(row=2, column=0, sticky="w", **PAD)
            ttk.Entry(bf, textvariable=self.s_prefix, width=18).grid(row=2, column=1, sticky="w", **PAD)
            ttk.Label(bf, text="suffix").grid(row=3, column=0, sticky="w", **PAD)
            ttk.Entry(bf, textvariable=self.s_suffix, width=18).grid(row=3, column=1, sticky="w", **PAD)
            ttk.Button(bf, text=_tr("Run (batch)"), style="Run.TButton",
                       command=self._run_size_batch).grid(row=4, column=0, columnspan=3, pady=6)

            of = ttk.LabelFrame(tab, text=_tr("Scale parameters"), padding=8)
            of.pack(fill="x", pady=(8, 0))
            of.columnconfigure(1, weight=1)

            ttk.Label(of, text="Breast GameObject name").grid(row=0, column=0, sticky="w", **PAD)
            ttk.Entry(of, textvariable=self.s_name, width=20).grid(row=0, column=1, sticky="w", **PAD)

            # Enlarge (formula)
            ttk.Label(of, text="Enlarge  (y = 1+Y,  x,z = 1+2Y)",
                      font=("TkDefaultFont", 9, "bold")).grid(row=1, column=0, columnspan=2, sticky="w", **PAD)
            erow = ttk.Frame(of); erow.grid(row=2, column=0, columnspan=2, sticky="w", **PAD)
            ttk.Label(erow, text="custom Y:").pack(side="left")
            ttk.Entry(erow, textvariable=self.s_customy, width=7).pack(side="left", padx=4)
            ttk.Button(erow, text="Apply Y", command=self._apply_custom_y).pack(side="left", padx=(0, 10))

            egrid = ttk.Frame(of); egrid.grid(row=3, column=0, columnspan=2, sticky="w", **PAD)
            for i, (nm, (x, y, z), _n) in enumerate(BREAST_ENLARGE_PRESETS):
                ttk.Button(
                    egrid, width=20,
                    text=f"{nm}\n({_fmt_num(x)}, {_fmt_num(y)}, {_fmt_num(z)})",
                    command=lambda xx=x, yy=y, zz=z: self._apply_set(xx, yy, zz),
                ).grid(row=i // 3, column=i % 3, padx=2, pady=2, sticky="ew")

            # Reduce (per-character)
            ttk.Label(of, text="Reduce  (per-character, irregular)",
                      font=("TkDefaultFont", 9, "bold")).grid(row=4, column=0, columnspan=2, sticky="w", **PAD)
            rgrid = ttk.Frame(of); rgrid.grid(row=5, column=0, columnspan=2, sticky="w", **PAD)
            for i, (nm, (x, y, z), _n) in enumerate(BREAST_REDUCE_PRESETS):
                ttk.Button(
                    rgrid, width=20,
                    text=f"{nm}\n({_fmt_num(x)}, {_fmt_num(y)}, {_fmt_num(z)})",
                    command=lambda xx=x, yy=y, zz=z: self._apply_set(xx, yy, zz),
                ).grid(row=i // 3, column=i % 3, padx=2, pady=2, sticky="ew")
            ttk.Button(of, text="Reset 1.0",
                       command=lambda: self._apply_set(1.0, 1.0, 1.0)).grid(row=6, column=0, sticky="w", **PAD)

            # raw set / add
            ttk.Label(of, text="set scaledValue (x, y, z)  -  blank = skip")\
                .grid(row=7, column=0, columnspan=2, sticky="w", **PAD)
            srow = ttk.Frame(of); srow.grid(row=8, column=0, columnspan=2, sticky="w", **PAD)
            ttk.Entry(srow, textvariable=self.s_setx, width=10).pack(side="left", padx=2)
            ttk.Entry(srow, textvariable=self.s_sety, width=10).pack(side="left", padx=2)
            ttk.Entry(srow, textvariable=self.s_setz, width=10).pack(side="left", padx=2)

            ttk.Label(of, text="add delta (dx, dy, dz)  -  added to current value")\
                .grid(row=9, column=0, columnspan=2, sticky="w", **PAD)
            arow = ttk.Frame(of); arow.grid(row=10, column=0, columnspan=2, sticky="w", **PAD)
            ttk.Entry(arow, textvariable=self.s_adx, width=10).pack(side="left", padx=2)
            ttk.Entry(arow, textvariable=self.s_ady, width=10).pack(side="left", padx=2)
            ttk.Entry(arow, textvariable=self.s_adz, width=10).pack(side="left", padx=2)

        def _build_both(self, tab):
            self.c_in_file = tk.StringVar()
            self.c_out_file = tk.StringVar()
            self.c_in_dir = tk.StringVar()
            self.c_out_dir = tk.StringVar()
            self.c_prefix = tk.StringVar(value="")
            self.c_suffix = tk.StringVar(value="")
            self.c_stiff = tk.StringVar(value="0.02")
            self.c_drag = tk.StringVar(value="0.3")
            self.c_patterns = tk.StringVar(value="LeftBreast_Dyna, RightBreast_Dyna")
            self.c_name = tk.StringVar(value="BreastSize")
            self.c_jiggle_fn = tk.BooleanVar(value=True)
            self.c_presets = list(BREAST_PRESETS_ALL)   # (label, (x,y,z), n) sorted

            sf = ttk.LabelFrame(tab, text=_tr("Single file"), padding=8)
            sf.pack(fill="x")
            self._file_row(sf, 0, "Input bundle", self.c_in_file)
            self._file_row(sf, 1, "Output path", self.c_out_file, save=True)
            ttk.Button(sf, text=_tr("Run (single)"), style="Run.TButton",
                       command=self._run_both_single).grid(row=2, column=0, columnspan=3, pady=6)

            bf = ttk.LabelFrame(tab, text=_tr("Batch (folder)"), padding=8)
            bf.pack(fill="x", pady=(8, 0))
            self._file_row(bf, 0, "Input folder", self.c_in_dir, is_dir=True)
            self._file_row(bf, 1, "Output folder", self.c_out_dir, is_dir=True)
            ttk.Label(bf, text="prefix").grid(row=2, column=0, sticky="w", **PAD)
            ttk.Entry(bf, textvariable=self.c_prefix, width=18).grid(row=2, column=1, sticky="w", **PAD)
            ttk.Label(bf, text="suffix").grid(row=3, column=0, sticky="w", **PAD)
            ttk.Entry(bf, textvariable=self.c_suffix, width=18).grid(row=3, column=1, sticky="w", **PAD)
            ttk.Checkbutton(bf, text="Append jiggleN to filename",
                            variable=self.c_jiggle_fn).grid(row=4, column=0, columnspan=2, sticky="w", **PAD)
            ttk.Button(bf, text=_tr("Run (batch)"), style="Run.TButton",
                       command=self._run_both_batch).grid(row=5, column=0, columnspan=3, pady=6)

            of = ttk.LabelFrame(tab, text=_tr("Body & physics"), padding=8)
            of.pack(fill="x", pady=(8, 0))
            of.columnconfigure(1, weight=1)

            ttk.Label(of, text="Target body  (the new scale + target jiggle tier)",
                      font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", **PAD)
            values = [f"{nm}   ({_fmt_num(x)}, {_fmt_num(y)}, {_fmt_num(z)})   jiggle{n}"
                      for nm, (x, y, z), n in self.c_presets]
            self.c_combo = ttk.Combobox(of, values=values, state="readonly")
            self.c_combo.grid(row=1, column=0, columnspan=2, sticky="ew", **PAD)
            default_idx = next((i for i, (nm, _, _) in enumerate(self.c_presets)
                                if nm.startswith("Eli")), 0)
            self.c_combo.current(default_idx)
            self.c_combo.bind("<<ComboboxSelected>>", lambda e: self._update_both_info())
            self.c_preset_info = ttk.Label(of, text="", foreground="#555")
            self.c_preset_info.grid(row=2, column=0, columnspan=2, sticky="w", **PAD)

            ttk.Label(of, text="Source body  (the 'before' body, used by Previous/Sum jiggle modes)",
                      font=("TkDefaultFont", 9, "bold")).grid(row=3, column=0, columnspan=2, sticky="w", **PAD)
            src_values = ["Auto-detect from bundle  (recommended)"] + [
                f"{nm}   (jiggle{n})" for nm, (x, y, z), n in self.c_presets]
            self.c_src_combo = ttk.Combobox(of, values=src_values, state="readonly")
            self.c_src_combo.grid(row=4, column=0, columnspan=2, sticky="ew", **PAD)
            self.c_src_combo.current(0)
            self.c_src_combo.bind("<<ComboboxSelected>>", lambda e: self._update_both_info())
            self.c_src_info = ttk.Label(of, text="", foreground="#555")
            self.c_src_info.grid(row=5, column=0, columnspan=2, sticky="w", **PAD)

            ttk.Label(of, text="Jiggle follows which size?",
                      font=("TkDefaultFont", 9, "bold")).grid(row=6, column=0, columnspan=2, sticky="w", **PAD)
            self.c_jmode = ttk.Combobox(
                of, state="readonly",
                values=["New size (jiggle = target tier)",
                        "Previous size (jiggle = source tier)",
                        "Sum of both (target + source)"])
            self.c_jmode.grid(row=7, column=0, columnspan=2, sticky="ew", **PAD)
            self.c_jmode.current(0)
            self.c_jmode.bind("<<ComboboxSelected>>", lambda e: self._update_both_info())

            grid2 = ttk.Frame(of); grid2.grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
            ttk.Label(grid2, text="stiffnessForce").grid(row=0, column=0, sticky="w", **PAD)
            ttk.Entry(grid2, textvariable=self.c_stiff, width=10).grid(row=0, column=1, **PAD)
            ttk.Label(grid2, text="dragForce").grid(row=0, column=2, sticky="w", **PAD)
            ttk.Entry(grid2, textvariable=self.c_drag, width=10).grid(row=0, column=3, **PAD)

            adv = ttk.Frame(of); adv.grid(row=9, column=0, columnspan=2, sticky="ew")
            adv.columnconfigure(1, weight=1)
            ttk.Label(adv, text="Dyna patterns").grid(row=0, column=0, sticky="w", **PAD)
            ttk.Entry(adv, textvariable=self.c_patterns).grid(row=0, column=1, sticky="ew", **PAD)
            ttk.Label(adv, text="BreastSize name").grid(row=1, column=0, sticky="w", **PAD)
            ttk.Entry(adv, textvariable=self.c_name, width=20).grid(row=1, column=1, sticky="w", **PAD)

            ttk.Label(of, text="New size: jiggle matches the size you picked (recommended). "
                               "Previous: keep the original body's jiggle. Sum: add both tiers.",
                      font=("TkDefaultFont", 8), foreground="#777", wraplength=520, justify="left")\
                .grid(row=10, column=0, columnspan=2, sticky="w", **PAD)

            self._update_both_info()

        def _build_library(self, tab):
            self.lib_src = tk.StringVar(value=default_sukusta_dir("extracted"))
            self.lib_out = tk.StringVar(value=default_sukusta_dir("modded"))
            self.lib_stiff = tk.StringVar(value="0.02")
            self.lib_drag = tk.StringVar(value="0.3")
            self.lib_patterns = tk.StringVar(value="LeftBreast_Dyna, RightBreast_Dyna")
            self.lib_name = tk.StringVar(value="BreastSize")
            self.lib_auto = tk.BooleanVar(value=True)
            self.lib_jiggle_fn = tk.BooleanVar(value=True)
            self.lib_presets = list(BREAST_PRESETS_ALL)
            self.lib_bundles = []

            # --- source / pick a bundle ---
            sf = ttk.LabelFrame(tab, text=_tr("1. Source — pick a bundle"), padding=8)
            sf.pack(fill="x")
            sf.columnconfigure(1, weight=1)
            ttk.Label(sf, text="Folder").grid(row=0, column=0, sticky="w", **PAD)
            ttk.Entry(sf, textvariable=self.lib_src).grid(row=0, column=1, sticky="ew", **PAD)
            ttk.Button(sf, text="Browse", command=lambda: self._pick_dir(self.lib_src)).grid(row=0, column=2, **PAD)
            qb = ttk.Frame(sf); qb.grid(row=1, column=1, sticky="w")
            ttk.Button(qb, text="extracted", width=10,
                       command=lambda: (self.lib_src.set(default_sukusta_dir("extracted")), self._lib_scan())).pack(side="left", padx=2)
            ttk.Button(qb, text="modded", width=10,
                       command=lambda: (self.lib_src.set(default_sukusta_dir("modded")), self._lib_scan())).pack(side="left", padx=2)
            ttk.Button(qb, text="Scan", width=10, command=self._lib_scan).pack(side="left", padx=8)
            ttk.Label(sf, text="Bundle").grid(row=2, column=0, sticky="w", **PAD)
            self.lib_combo = ttk.Combobox(sf, values=[], state="readonly")
            self.lib_combo.grid(row=2, column=1, columnspan=2, sticky="ew", **PAD)
            self.lib_count = ttk.Label(sf, text="(not scanned yet)", foreground="#777")
            self.lib_count.grid(row=3, column=1, sticky="w", **PAD)

            # --- what to apply ---
            mf = ttk.LabelFrame(tab, text=_tr("2. Mod to apply"), padding=8)
            mf.pack(fill="x", pady=(8, 0))
            mf.columnconfigure(1, weight=1)
            ttk.Label(mf, text="Mod type").grid(row=0, column=0, sticky="w", **PAD)
            self.lib_modtype = ttk.Combobox(
                mf, state="readonly",
                values=["Both (size + jiggle)", "Size only", "Physics only"])
            self.lib_modtype.grid(row=0, column=1, sticky="ew", **PAD)
            self.lib_modtype.current(0)

            ttk.Label(mf, text="Target body").grid(row=1, column=0, sticky="w", **PAD)
            self.lib_tgt = ttk.Combobox(
                mf, state="readonly",
                values=[f"{nm}   ({_fmt_num(x)}, {_fmt_num(y)}, {_fmt_num(z)})   jiggle{n}"
                        for nm, (x, y, z), n in self.lib_presets])
            self.lib_tgt.grid(row=1, column=1, sticky="ew", **PAD)
            self.lib_tgt.current(next((i for i, (nm, _, _) in enumerate(self.lib_presets)
                                       if nm.startswith("Eli")), 0))

            ttk.Label(mf, text="Source body (Both)").grid(row=2, column=0, sticky="w", **PAD)
            self.lib_src_combo = ttk.Combobox(
                mf, state="readonly",
                values=["Auto-detect from bundle"] + [
                    f"{nm}   (jiggle{n})" for nm, (x, y, z), n in self.lib_presets])
            self.lib_src_combo.grid(row=2, column=1, sticky="ew", **PAD)
            self.lib_src_combo.current(0)

            ttk.Label(mf, text="Jiggle follows (Both)").grid(row=3, column=0, sticky="w", **PAD)
            self.lib_jmode = ttk.Combobox(
                mf, state="readonly",
                values=["New size (target tier)", "Previous size (source tier)",
                        "Sum of both (target + source)"])
            self.lib_jmode.grid(row=3, column=1, sticky="ew", **PAD)
            self.lib_jmode.current(0)

            g = ttk.Frame(mf); g.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
            ttk.Label(g, text="stiffnessForce").grid(row=0, column=0, sticky="w", **PAD)
            ttk.Entry(g, textvariable=self.lib_stiff, width=9).grid(row=0, column=1, **PAD)
            ttk.Label(g, text="dragForce").grid(row=0, column=2, sticky="w", **PAD)
            ttk.Entry(g, textvariable=self.lib_drag, width=9).grid(row=0, column=3, **PAD)
            ttk.Checkbutton(g, text="Physics: per-character auto",
                            variable=self.lib_auto).grid(row=0, column=4, sticky="w", **PAD)

            adv = ttk.Frame(mf); adv.grid(row=5, column=0, columnspan=2, sticky="ew")
            adv.columnconfigure(1, weight=1)
            ttk.Label(adv, text="Dyna patterns").grid(row=0, column=0, sticky="w", **PAD)
            ttk.Entry(adv, textvariable=self.lib_patterns).grid(row=0, column=1, sticky="ew", **PAD)
            ttk.Label(adv, text="BreastSize name").grid(row=1, column=0, sticky="w", **PAD)
            ttk.Entry(adv, textvariable=self.lib_name, width=20).grid(row=1, column=1, sticky="w", **PAD)

            # --- output ---
            of = ttk.LabelFrame(tab, text=_tr("3. Output → modded"), padding=8)
            of.pack(fill="x", pady=(8, 0))
            of.columnconfigure(1, weight=1)
            ttk.Label(of, text="Modded folder").grid(row=0, column=0, sticky="w", **PAD)
            ttk.Entry(of, textvariable=self.lib_out).grid(row=0, column=1, sticky="ew", **PAD)
            ttk.Button(of, text="Browse", command=lambda: self._pick_dir(self.lib_out)).grid(row=0, column=2, **PAD)
            ttk.Checkbutton(of, text="Append jiggleN to filename (Both)",
                            variable=self.lib_jiggle_fn).grid(row=1, column=1, sticky="w", **PAD)
            ttk.Button(of, text=_tr("Mod selected → modded"), style="Run.TButton",
                       command=self._run_library).grid(row=2, column=0, columnspan=3, pady=6)
            ttk.Label(of, text="Output mirrors the source sub-path (e.g. 3d_model/…). "
                              "The original is never modified.",
                      font=("TkDefaultFont", 8), foreground="#777",
                      wraplength=520, justify="left").grid(row=3, column=0, columnspan=3, sticky="w", **PAD)

            self._lib_scan()

        # ---------- dialog helpers ----------
        def _pick_open(self, var):
            p = filedialog.askopenfilename(title="Select input bundle")
            if p: var.set(p)

        def _pick_save(self, var):
            p = filedialog.asksaveasfilename(title="Save output bundle", defaultextension=".bundle")
            if p: var.set(p)

        def _pick_dir(self, var):
            p = filedialog.askdirectory(title="Select folder")
            if p: var.set(p)

        # ---------- preset actions ----------
        def _set_phys(self, stiff, drag):
            self.p_stiff.set(str(stiff))
            self.p_drag.set(str(drag))

        def _apply_set(self, x, y, z):
            """Fill the 'set scaledValue' fields and zero out the 'add' fields."""
            self.s_setx.set(_fmt_num(x)); self.s_sety.set(_fmt_num(y)); self.s_setz.set(_fmt_num(z))
            self.s_adx.set("0"); self.s_ady.set("0"); self.s_adz.set("0")

        def _apply_custom_y(self):
            try:
                Y = float(self.s_customy.get())
            except ValueError:
                messagebox.showerror(_tr("Error"), _tr("Y must be a number.")); return
            self._apply_set(*breast_enlarge_xyz(Y))

        def _toggle_auto(self):
            state = "disabled" if self.p_auto.get() else "normal"
            for e in (self.e_ldy, self.e_ldz, self.e_hdy, self.e_hdz):
                e.configure(state=state)

        # ---------- log ----------
        def _log_line(self, s):
            self.log.configure(state="normal")
            self.log.insert("end", s + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")

        def _clear_log(self):
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.configure(state="disabled")

        def _save_log(self):
            p = filedialog.asksaveasfilename(title="Save log", defaultextension=".txt",
                                             filetypes=[("Text", "*.txt"), ("All", "*.*")])
            if not p:
                return
            try:
                Path(p).write_text(self.log.get("1.0", "end"), encoding="utf-8")
                messagebox.showinfo(_tr("Saved"), _tr("Log saved:\n{p}", p=p))
            except Exception as e:
                messagebox.showerror(_tr("Error"), str(e))

        # ---------- param parsing ----------
        def _parse_float(self, s, default=None):
            s = (s or "").strip()
            if s == "":
                return default
            try:
                return float(s)
            except ValueError:
                return default

        def _physics_params(self):
            patterns = [p.strip() for p in self.p_patterns.get().replace(",", " ").split() if p.strip()]
            stiff = self._parse_float(self.p_stiff.get(), None)
            drag = self._parse_float(self.p_drag.get(), None)
            if self.p_auto.get():
                ldy = ldz = hdy = hdz = 0.0
            else:
                ldy = self._parse_float(self.p_ldy.get(), 0.0)
                ldz = self._parse_float(self.p_ldz.get(), 0.0)
                hdy = self._parse_float(self.p_hdy.get(), 0.0)
                hdz = self._parse_float(self.p_hdz.get(), 0.0)
            return patterns, stiff, drag, ldy, ldz, hdy, hdz, self.p_auto.get()

        def _size_params(self):
            sx = self.s_setx.get().strip()
            sy = self.s_sety.get().strip()
            sz = self.s_setz.get().strip()
            setv = None
            if not (sx == "" and sy == "" and sz == ""):
                try:
                    setv = (float(sx or 0), float(sy or 0), float(sz or 0))
                except ValueError:
                    setv = None
            addv = (self._parse_float(self.s_adx.get(), 0.0),
                    self._parse_float(self.s_ady.get(), 0.0),
                    self._parse_float(self.s_adz.get(), 0.0))
            return self.s_name.get(), setv, addv

        # ---------- threaded execution ----------
        def _busy(self):
            return self.worker is not None and self.worker.is_alive()

        def _start(self, target):
            if self._busy():
                messagebox.showwarning(_tr("Busy"), _tr("A job is already running."))
                return
            self.progress.configure(value=0, maximum=100)
            self.status.configure(text="Working...")
            self.worker = threading.Thread(target=self._wrap, args=(target,), daemon=True)
            self.worker.start()
            self.root.after(80, self._poll)

        def _wrap(self, target):
            try:
                target()
                self.q.put(("status", "Done"))
            except Exception as e:
                self.q.put(("log", f"[Error] {e}"))
                self.q.put(("status", "Error"))

        def _poll(self):
            try:
                while True:
                    kind, *rest = self.q.get_nowait()
                    if kind == "log":
                        self._log_line(rest[0])
                    elif kind == "progress":
                        done, total = rest
                        self.progress.configure(maximum=max(total, 1), value=done)
                    elif kind == "status":
                        self.status.configure(text=rest[0])
            except Exception:
                pass
            if self._busy() or not self.q.empty():
                self.root.after(80, self._poll)

        def _cb_log(self, s):
            self.q.put(("log", s))

        def _cb_prog(self, done, total):
            self.q.put(("progress", done, total))

        def _run_physics_single(self):
            inf, outf = self.p_in_file.get(), self.p_out_file.get()
            if not inf or not outf:
                messagebox.showerror(_tr("Error"), _tr("Please set input/output paths.")); return
            patterns, stiff, drag, ldy, ldz, hdy, hdz, auto = self._physics_params()

            def job():
                self.q.put(("log", f"[single] processing {Path(inf).name} ..."))
                scanned, changed, logs, n = modify_swingbones_in_bundle(
                    Path(inf), Path(outf), patterns, stiff, drag, ldy, ldz, hdy, hdz,
                    use_character_specific=auto)
                for ln in logs:
                    self.q.put(("log", ln))
                self.q.put(("log", f"-> scanned={scanned} changed={changed}"
                            + (f" jiggle{n}" if (auto and n is not None) else "")))
            self._start(job)

        def _run_physics_batch(self):
            ind, outd = self.p_in_dir.get(), self.p_out_dir.get()
            if not ind or not outd:
                messagebox.showerror(_tr("Error"), _tr("Please set input/output folders.")); return
            patterns, stiff, drag, ldy, ldz, hdy, hdz, auto = self._physics_params()
            prefix, suffix = self.p_prefix.get(), self.p_suffix.get()

            def job():
                run_dyna_batch(ind, outd, prefix, suffix, patterns,
                               stiff, drag, ldy, ldz, hdy, hdz, auto,
                               self._cb_log, self._cb_prog)
            self._start(job)

        def _run_size_single(self):
            inf, outf = self.s_in_file.get(), self.s_out_file.get()
            if not inf or not outf:
                messagebox.showerror(_tr("Error"), _tr("Please set input/output paths.")); return
            name, setv, addv = self._size_params()

            def job():
                self.q.put(("log", f"[single] processing {Path(inf).name} ..."))
                scanned, changed, logs = modify_livecore_scaling(
                    Path(inf), Path(outf), name, setv, addv)
                for ln in logs:
                    self.q.put(("log", ln))
                self.q.put(("log", f"-> scanned={scanned} changed={changed}"))
            self._start(job)

        def _run_size_batch(self):
            ind, outd = self.s_in_dir.get(), self.s_out_dir.get()
            if not ind or not outd:
                messagebox.showerror(_tr("Error"), _tr("Please set input/output folders.")); return
            name, setv, addv = self._size_params()
            prefix, suffix = self.s_prefix.get(), self.s_suffix.get()

            def job():
                run_size_batch(ind, outd, prefix, suffix, name, setv, addv,
                               self._cb_log, self._cb_prog)
            self._start(job)

        # ---------- combined (Both) ----------
        def _update_both_info(self):
            ti = self.c_combo.current()
            if ti is None or ti < 0:
                ti = 0
            tnm, (tx, ty, tz), tn = self.c_presets[ti]
            self.c_preset_info.configure(
                text=f"target -> scale ({_fmt_num(tx)}, {_fmt_num(ty)}, {_fmt_num(tz)}),  jiggle{tn}"
            )
            si = self.c_src_combo.current()
            if si is None or si < 0:
                si = 0
            ji = self.c_jmode.current()
            if ji is None or ji < 0:
                ji = 0
            mode = ("target", "source", "sum")[ji]
            if si == 0:
                src_txt = "each bundle's detected tier"
                eff = {"target": f"jiggle{tn}",
                       "source": "detected tier (per file)",
                       "sum": f"jiggle{tn} + detected tier (per file)"}[mode]
            else:
                snm, _, sn = self.c_presets[si - 1]
                src_txt = f"jiggle{sn}"
                eff = {"target": f"jiggle{tn}",
                       "source": f"jiggle{sn}",
                       "sum": f"jiggle{tn + sn}"}[mode]
            self.c_src_info.configure(text=f"source: {src_txt}   ->   applied jiggle: {eff}")

        def _both_params(self):
            ti = self.c_combo.current()
            if ti is None or ti < 0:
                ti = 0
            tnm, xyz, tn = self.c_presets[ti]
            si = self.c_src_combo.current()
            if si is None or si < 0:
                si = 0
            source_n = None if si == 0 else self.c_presets[si - 1][2]
            ji = self.c_jmode.current()
            if ji is None or ji < 0:
                ji = 0
            jiggle_mode = ("target", "source", "sum")[ji]
            stiff = self._parse_float(self.c_stiff.get(), None)
            drag = self._parse_float(self.c_drag.get(), None)
            patterns = [p.strip() for p in self.c_patterns.get().replace(",", " ").split() if p.strip()]
            return self.c_name.get(), xyz, tn, source_n, stiff, drag, patterns, tnm, jiggle_mode

        def _run_both_single(self):
            inf, outf = self.c_in_file.get(), self.c_out_file.get()
            if not inf or not outf:
                messagebox.showerror(_tr("Error"), _tr("Please set input/output paths.")); return
            name, xyz, tn, source_n, stiff, drag, patterns, label, jiggle_mode = self._both_params()

            def job():
                src = "auto-detect" if source_n is None else f"jiggle{source_n}"
                self.q.put(("log", f"[both] -> {label}: scale={xyz}, target jiggle{tn}, "
                                   f"source {src}, jiggle mode {jiggle_mode}"))
                d_sc, d_ch, s_sc, s_ch, t_n, eff, logs = modify_both_in_bundle(
                    Path(inf), Path(outf), patterns, stiff, drag, name, xyz, tn,
                    source_n=source_n, jiggle_mode=jiggle_mode)
                for ln in logs:
                    self.q.put(("log", ln))
                self.q.put(("log", f"-> dyna changed={d_ch}, size changed={s_ch}, jiggle={eff}"))
            self._start(job)

        def _run_both_batch(self):
            ind, outd = self.c_in_dir.get(), self.c_out_dir.get()
            if not ind or not outd:
                messagebox.showerror(_tr("Error"), _tr("Please set input/output folders.")); return
            name, xyz, tn, source_n, stiff, drag, patterns, label, jiggle_mode = self._both_params()
            prefix, suffix = self.c_prefix.get(), self.c_suffix.get()
            append = self.c_jiggle_fn.get()

            def job():
                src = "auto-detect" if source_n is None else f"jiggle{source_n}"
                self.q.put(("log", f"[both] -> {label}: scale={xyz}, target jiggle{tn}, "
                                   f"source {src}, jiggle mode {jiggle_mode}"))
                run_both_batch(ind, outd, prefix, suffix, patterns, stiff, drag,
                               name, xyz, tn, append, self._cb_log, self._cb_prog,
                               source_n=source_n, label=label, jiggle_mode=jiggle_mode)
            self._start(job)

        # ---------- library (extracted -> modded) ----------
        def _lib_scan(self):
            root = self.lib_src.get().strip()
            try:
                self.lib_bundles = find_asset_bundles(root)
            except Exception as e:
                self.lib_bundles = []
                self._cb_log(f"[library] scan error: {e}")
            vals = []
            base = os.path.expanduser(root)
            for b in self.lib_bundles:
                try:
                    vals.append(str(b.relative_to(base)))
                except Exception:
                    vals.append(b.name)
            self.lib_combo.configure(values=vals)
            if vals:
                self.lib_combo.current(0)
            self.lib_count.configure(
                text=f"{len(vals)} bundle(s) found" if vals else "no asset bundles found here")

        def _run_library(self):
            if not self.lib_bundles:
                messagebox.showerror(_tr("Error"), _tr("Scan a source folder and pick a bundle first.")); return
            idx = self.lib_combo.current()
            if idx is None or idx < 0:
                messagebox.showerror(_tr("Error"), _tr("Pick a bundle.")); return
            in_path = self.lib_bundles[idx]
            src_root = self.lib_src.get().strip()
            modded = self.lib_out.get().strip()
            if not modded:
                messagebox.showerror(_tr("Error"), _tr("Set the modded output folder.")); return

            mt = self.lib_modtype.current()    # 0 both, 1 size, 2 physics
            params = _default_library_params()
            params["patterns"] = [p.strip() for p in
                                  self.lib_patterns.get().replace(",", " ").split() if p.strip()]
            params["breast_name"] = self.lib_name.get()
            extra_suffix = ""

            if mt == 1:           # size only
                mode = "size"
                ti = self.lib_tgt.current(); ti = 0 if (ti is None or ti < 0) else ti
                params["set_xyz"] = self.lib_presets[ti][1]
            elif mt == 2:         # physics only
                mode = "dyna"
                params["use_auto"] = self.lib_auto.get()
                params["stiff"] = self._parse_float(self.lib_stiff.get(), None)
                params["drag"] = self._parse_float(self.lib_drag.get(), None)
            else:                 # both
                mode = "both"
                ti = self.lib_tgt.current(); ti = 0 if (ti is None or ti < 0) else ti
                params["set_xyz"] = self.lib_presets[ti][1]
                params["target_n"] = self.lib_presets[ti][2]
                si = self.lib_src_combo.current(); si = 0 if (si is None or si < 0) else si
                params["source_n"] = None if si == 0 else self.lib_presets[si - 1][2]
                ji = self.lib_jmode.current(); ji = 0 if (ji is None or ji < 0) else ji
                params["jiggle_mode"] = ("target", "source", "sum")[ji]
                params["stiff"] = self._parse_float(self.lib_stiff.get(), None)
                params["drag"] = self._parse_float(self.lib_drag.get(), None)
                if self.lib_jiggle_fn.get() and params["target_n"] is not None:
                    extra_suffix = _both_filename_suffix(
                        self.lib_presets[ti][0], params["target_n"], True)

            out_path = modded_output_path(in_path, src_root, modded, extra_suffix=extra_suffix)

            def job():
                self.q.put(("log", f"[library] {Path(in_path).name}  ({mode})"))
                summary = run_library_mod(Path(in_path), out_path, mode, params)
                self.q.put(("log", f"-> {summary}"))
                self.q.put(("log", f"-> saved: {out_path}"))
            self._start(job)

    root = tk.Tk()
    TunerGUI(root)
    root.mainloop()


# ==========================================================================
# 9. One-shot CLI (for scripting / automation)
# ==========================================================================
def cli_dyna(args):
    ensure_unitypy()
    patterns = [p.strip() for p in args.patterns.replace(",", " ").split() if p.strip()]

    def on_log(s): print(s)

    def on_prog(done, total):
        print(f"  [{done}/{total}]", end="\r", flush=True)
        if done >= total:
            print()

    if args.in_dir:
        if not args.out_dir:
            print("--out-dir is required."); return 2
        run_dyna_batch(args.in_dir, args.out_dir, args.prefix, args.suffix, patterns,
                       args.stiff, args.drag, args.low_dy, args.low_dz,
                       args.high_dy, args.high_dz, args.auto, on_log, on_prog)
    else:
        if not args.infile or not args.outfile:
            print("--in and --out are required (or --in-dir/--out-dir)."); return 2
        scanned, changed, logs, n = modify_swingbones_in_bundle(
            Path(args.infile), Path(args.outfile), patterns,
            args.stiff, args.drag, args.low_dy, args.low_dz,
            args.high_dy, args.high_dz, use_character_specific=args.auto)
        print(f"scanned={scanned} changed={changed}"
              + (f" jiggle{n}" if (args.auto and n is not None) else ""))
        if args.verbose:
            print("\n".join(logs))
    return 0


def cli_size(args):
    ensure_unitypy()
    setv = None
    if args.enlarge_y is not None:
        setv = breast_enlarge_xyz(args.enlarge_y)
    elif args.set is not None:
        setv = (args.set[0], args.set[1], args.set[2])
    addv = tuple(args.add) if args.add is not None else (0.0, 0.0, 0.0)

    def on_log(s): print(s)

    def on_prog(done, total):
        print(f"  [{done}/{total}]", end="\r", flush=True)
        if done >= total:
            print()

    if args.in_dir:
        if not args.out_dir:
            print("--out-dir is required."); return 2
        run_size_batch(args.in_dir, args.out_dir, args.prefix, args.suffix,
                       args.name, setv, addv, on_log, on_prog)
    else:
        if not args.infile or not args.outfile:
            print("--in and --out are required (or --in-dir/--out-dir)."); return 2
        scanned, changed, logs = modify_livecore_scaling(
            Path(args.infile), Path(args.outfile), args.name, setv, addv)
        print(f"scanned={scanned} changed={changed}")
        if args.verbose:
            print("\n".join(logs))
    return 0


def resolve_preset(token):
    """Resolve a preset by 1-based index or by case-insensitive name substring.
    Returns (label, (x,y,z), n) or None."""
    token = (token or "").strip()
    if token.isdigit():
        i = int(token) - 1
        if 0 <= i < len(BREAST_PRESETS_ALL):
            return BREAST_PRESETS_ALL[i]
        return None
    tl = token.lower()
    matches = [p for p in BREAST_PRESETS_ALL if tl in p[0].lower()]
    return matches[0] if len(matches) == 1 else (matches[0] if matches else None)


def cli_both(args):
    ensure_unitypy()
    if not args.preset:
        print("--preset (target body) is required (name or index). Options:")
        for i, (nm, (x, y, z), n) in enumerate(BREAST_PRESETS_ALL, 1):
            print(f"  {i:2d}) {nm}  ({x}, {y}, {z})  jiggle{n}")
        return 2
    preset = resolve_preset(args.preset)
    if preset is None:
        print(f"Unknown target preset '{args.preset}'. Use index 1-{len(BREAST_PRESETS_ALL)} or a name.")
        return 2
    label, xyz, target_n = preset

    # source body: 'auto' (default) -> detect per bundle; else a preset name/index
    source_n = None
    src = (args.source or "auto").strip().lower()
    if src not in ("auto", ""):
        sp = resolve_preset(args.source)
        if sp is None:
            print(f"Unknown source preset '{args.source}'. Use 'auto', an index, or a name.")
            return 2
        source_n = sp[2]

    # jiggle mode: which size the swing-bone jiggle follows
    jiggle_mode = {"new": "target", "prev": "source"}.get(
        (args.jiggle or "target").lower(), (args.jiggle or "target").lower())

    patterns = [p.strip() for p in args.patterns.replace(",", " ").split() if p.strip()]

    def on_log(s): print(s)

    def on_prog(done, total):
        print(f"  [{done}/{total}]", end="\r", flush=True)
        if done >= total:
            print()

    print(f"target: {label}  scale={xyz}  jiggle{target_n}   "
          f"source: {'auto-detect' if source_n is None else 'jiggle' + str(source_n)}   "
          f"jiggle mode: {jiggle_mode}")
    if args.in_dir:
        if not args.out_dir:
            print("--out-dir is required."); return 2
        run_both_batch(args.in_dir, args.out_dir, args.prefix, args.suffix, patterns,
                       args.stiff, args.drag, args.name, xyz, target_n,
                       not args.no_jiggle_name, on_log, on_prog,
                       source_n=source_n, jiggle_mode=jiggle_mode)
    else:
        if not args.infile or not args.outfile:
            print("--in and --out are required (or --in-dir/--out-dir)."); return 2
        d_sc, d_ch, s_sc, s_ch, t_n, eff, logs = modify_both_in_bundle(
            Path(args.infile), Path(args.outfile), patterns,
            args.stiff, args.drag, args.name, xyz, target_n,
            source_n=source_n, jiggle_mode=jiggle_mode)
        print(f"dyna changed={d_ch}  size changed={s_ch}  jiggle={eff}")
        if args.verbose:
            print("\n".join(logs))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="sifas_breast_tuner",
        description="SIFAS breast-bone physics (Dyna) + scale (Size) unified editor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--gui", action="store_true", help="force the GUI")
    p.add_argument("--menu", "--cli", dest="menu", action="store_true",
                   help="force the interactive text menu")
    sub = p.add_subparsers(dest="cmd")

    # dyna
    d = sub.add_parser("dyna", help="edit SwingBone physics", aliases=["physics"],
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    d.add_argument("--in", dest="infile", help="input bundle")
    d.add_argument("--out", dest="outfile", help="output bundle")
    d.add_argument("--in-dir", dest="in_dir", help="input folder (batch)")
    d.add_argument("--out-dir", dest="out_dir", help="output folder (batch)")
    d.add_argument("--prefix", default="", help="batch output prefix")
    d.add_argument("--suffix", default="", help="batch output suffix")
    d.add_argument("--patterns", default="LeftBreast_Dyna, RightBreast_Dyna",
                   help="target GO patterns (comma-separated)")
    d.add_argument("--stiff", type=float, default=None, help="stiffnessForce (omit = keep)")
    d.add_argument("--drag", type=float, default=None, help="dragForce (omit = keep)")
    d.add_argument("--low-dy", type=float, default=-1.0)
    d.add_argument("--low-dz", type=float, default=-1.0)
    d.add_argument("--high-dy", type=float, default=1.0)
    d.add_argument("--high-dz", type=float, default=1.0)
    d.add_argument("--auto", action="store_true",
                   help="per-character auto (rotation limits + jiggleN filename)")
    d.add_argument("-v", "--verbose", action="store_true", help="print detailed log")

    # size
    s = sub.add_parser("size", help="edit LiveCore scale",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    s.add_argument("--in", dest="infile", help="input bundle")
    s.add_argument("--out", dest="outfile", help="output bundle")
    s.add_argument("--in-dir", dest="in_dir", help="input folder (batch)")
    s.add_argument("--out-dir", dest="out_dir", help="output folder (batch)")
    s.add_argument("--prefix", default="", help="batch output prefix")
    s.add_argument("--suffix", default="", help="batch output suffix")
    s.add_argument("--name", default="BreastSize", help="Breast GameObject name")
    s.add_argument("--enlarge-y", "--enlarge-x", dest="enlarge_y", type=float, metavar="Y",
                   help="enlarge via formula  y = 1+Y ,  x,z = 1+2Y")
    s.add_argument("--set", nargs=3, type=float, metavar=("X", "Y", "Z"),
                   help="set scaledValue absolute")
    s.add_argument("--add", nargs=3, type=float, metavar=("DX", "DY", "DZ"),
                   help="add delta to scaledValue")
    s.add_argument("-v", "--verbose", action="store_true", help="print detailed log")

    # both
    bo = sub.add_parser("both", help="edit physics + scale together (preset-driven)",
                        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    bo.add_argument("--in", dest="infile", help="input bundle")
    bo.add_argument("--out", dest="outfile", help="output bundle")
    bo.add_argument("--in-dir", dest="in_dir", help="input folder (batch)")
    bo.add_argument("--out-dir", dest="out_dir", help="output folder (batch)")
    bo.add_argument("--prefix", default="", help="batch output prefix")
    bo.add_argument("--suffix", default="", help="batch output suffix")
    bo.add_argument("--preset", help="TARGET body by name (e.g. Eli) or 1-based index; "
                                     "sets the new scale AND the target jiggle tier")
    bo.add_argument("--source", default="auto",
                    help="SOURCE ('before') body: 'auto' to detect each bundle's tier, "
                         "or a preset name/index; used by --jiggle source/sum")
    bo.add_argument("--jiggle", default="target",
                    choices=["target", "new", "source", "prev", "sum"],
                    help="which size the jiggle follows: target/new = new size (default), "
                         "source/prev = previous size, sum = both tiers added")
    bo.add_argument("--stiff", type=float, default=0.02, help="stiffnessForce")
    bo.add_argument("--drag", type=float, default=0.3, help="dragForce")
    bo.add_argument("--patterns", default="LeftBreast_Dyna, RightBreast_Dyna",
                    help="dyna target GO patterns (comma-separated)")
    bo.add_argument("--name", default="BreastSize", help="Breast GameObject name")
    bo.add_argument("--no-jiggle-name", action="store_true",
                    help="do NOT append jiggleN to batch output filenames")
    bo.add_argument("-v", "--verbose", action="store_true", help="print detailed log")
    return p


# ==========================================================================
# 10. Entry point - automatic environment detection
# ==========================================================================
def main():
    parser = build_parser()
    args = parser.parse_args()

    # 1) subcommand -> one-shot CLI
    if args.cmd in ("dyna", "physics"):
        return cli_dyna(args)
    if args.cmd == "size":
        return cli_size(args)
    if args.cmd == "both":
        return cli_both(args)

    # 2) explicit flags
    if args.gui:
        return run_gui()
    if args.menu:
        return run_menu()

    # 3) auto: GUI if possible, otherwise (e.g. Termux) the text menu
    if gui_available():
        return run_gui()
    else:
        return run_menu()


if __name__ == "__main__":
    sys.exit(main() or 0)
