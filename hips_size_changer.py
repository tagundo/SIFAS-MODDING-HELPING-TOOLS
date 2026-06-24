# pip install UnityPy

from pathlib import Path
from collections import Counter
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

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
        "LiveCoreMemberNodeScaling scaler (HipsSize)": "LiveCoreMemberNodeScaling 스케일러 (HipsSize)",
        "Single": "단일",
        "Batch": "일괄",
        "Options": "옵션",
        "Input bundle": "입력 번들",
        "Output path": "출력 경로",
        "Input dir": "입력 폴더",
        "Output dir": "출력 폴더",
        "Prefix": "접두사",
        "Suffix": "접미사",
        "Browse": "찾아보기",
        "Run (Single)": "실행 (단일)",
        "Run (Batch)": "실행 (일괄)",
        "Target GameObject name": "대상 GameObject 이름",
        "Set scaledValue (x,y,z)": "scaledValue 설정 (x,y,z)",
        "Add Δ (dx,dy,dz)": "Δ 추가 (dx,dy,dz)",
        "Result": "결과",
        "Error": "오류",
        "Select input bundle": "입력 번들 선택",
        "Save output bundle": "출력 번들 저장",
        "Select input folder": "입력 폴더 선택",
        "Select output folder": "출력 폴더 선택",
        "Please select input bundle": "입력 번들을 선택하세요",
        "Please specify output path": "출력 경로를 지정하세요",
        "Please select input folder": "입력 폴더를 선택하세요",
        "Please specify output folder": "출력 폴더를 지정하세요",
    },
    "ja": {
        "Language": "言語",
        "LiveCoreMemberNodeScaling scaler (HipsSize)": "LiveCoreMemberNodeScaling スケーラー (HipsSize)",
        "Single": "単一",
        "Batch": "一括",
        "Options": "オプション",
        "Input bundle": "入力バンドル",
        "Output path": "出力パス",
        "Input dir": "入力フォルダ",
        "Output dir": "出力フォルダ",
        "Prefix": "接頭辞",
        "Suffix": "接尾辞",
        "Browse": "参照",
        "Run (Single)": "実行（単一）",
        "Run (Batch)": "実行（一括）",
        "Target GameObject name": "対象GameObject名",
        "Set scaledValue (x,y,z)": "scaledValue設定 (x,y,z)",
        "Add Δ (dx,dy,dz)": "Δ加算 (dx,dy,dz)",
        "Result": "結果",
        "Error": "エラー",
        "Select input bundle": "入力バンドルを選択",
        "Save output bundle": "出力バンドルを保存",
        "Select input folder": "入力フォルダを選択",
        "Select output folder": "出力フォルダを選択",
        "Please select input bundle": "入力バンドルを選択してください",
        "Please specify output path": "出力パスを指定してください",
        "Please select input folder": "入力フォルダを選択してください",
        "Please specify output folder": "出力フォルダを指定してください",
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
    or _os.environ.get("SIFAS_LANG", "en")
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
try:
    import UnityPy
    from UnityPy.enums import TextureFormat
except ImportError:
    import subprocess
    import sys
    print("UnityPy is not installed. Installing..")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "UnityPy"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])  # Pillow is also a required module, installing
    import UnityPy
    from UnityPy.enums import TextureFormat
# ---------- Typetree helpers ----------

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
        if isinstance(v, str) and tn == v: return True
        if isinstance(v, int) and ti == v: return True
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
    if not isinstance(vec, dict): return False
    changed = False
    if x is not None: vec["x"] = float(x); changed = True
    if y is not None: vec["y"] = float(y); changed = True
    if z is not None: vec["z"] = float(z); changed = True
    return changed

def add_vec3(vec, dx=0.0, dy=0.0, dz=0.0):
    if not isinstance(vec, dict): return False
    vec["x"] = float(vec.get("x") or 0.0) + float(dx)
    vec["y"] = float(vec.get("y") or 0.0) + float(dy)
    vec["z"] = float(vec.get("z") or 0.0) + float(dz)
    return True

# ---------- Index builders ----------

def build_obj_index(env):
    obj_by_pid = {}
    for o in env.objects:
        obj_by_pid[o.path_id] = o
        obj_by_pid[-o.path_id] = o
    return obj_by_pid

def find_gameobject_by_name(env, name_ci: str):
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
        if (nm or "").lower() == name_ci.lower():
            return o
    return None

def list_components_pids(go_tree):
    comps = []
    if not isinstance(go_tree, dict): return comps
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

def get_transform_for_target_go(env, obj_by_pid, go_name="HipsSize"):
    go = find_gameobject_by_name(env, go_name)
    if not go: return None
    try:
        go_tree, _, _ = read_tree_safe(go)
    except Exception:
        return None
    for pid in list_components_pids(go_tree):
        tobj = obj_by_pid.get(pid) or obj_by_pid.get(-pid)
        if tobj and is_obj_type(tobj, ("Transform", 4)):
            return tobj
    return None

# ---------- LiveCore helpers ----------

def is_livecore_scaling_tree(tree, obj_by_pid):
    if not isinstance(tree, dict): return False
    has_scale = isinstance(get_from_tree(tree, "scaleValues"), list)
    if not has_scale: return False
    # Strengthen when script name verification is possible
    p = get_from_tree(tree, "m_Script")
    if isinstance(p, dict):
        pid = p.get("m_PathID") or p.get("pathID")
        if isinstance(pid, int):
            sobj = obj_by_pid.get(pid) or obj_by_pid.get(-pid)
            if sobj:
                try:
                    st, _, _ = read_tree_safe(sobj)
                    for key in ("m_ClassName","className","m_Name","name"):
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
    # Find
    for i, elem in enumerate(scale_list):
        node, estyle = get_node_from_elem(elem)
        tgt = node.get("target") or {}
        pid = tgt.get("m_PathID") or tgt.get("pathID")
        if isinstance(pid, int) and (pid == target_pid or pid == -target_pid):
            return node, i, estyle, False
    # Create
    new_node = {
        "target": {"m_FileID": 0, "m_PathID": int(target_pid)},
        "originValue": {"x": 1.0, "y": 1.0, "z": 1.0},
        "scaledValue": {"x": 1.0, "y": 1.0, "z": 1.0},
    }
    scale_list.append(make_elem_for_node(new_node, style))
    return new_node, len(scale_list)-1, style, True

def modify_livecore_scaling(
    in_path: Path,
    out_path: Path,
    target_go_name: str,      # default "HipsSize"
    set_xyz: tuple | None,    # (x,y,z) or None
    add_dxyz: tuple,          # (dx,dy,dz)
):
    env = UnityPy.load(str(in_path))
    obj_by_pid = build_obj_index(env)

    logs = []
    changed = 0
    scanned = 0

    target_tr = get_transform_for_target_go(env, obj_by_pid, go_name=target_go_name)
    if not target_tr:
        logs.append(f"[MISS] Transform not found (name={target_go_name})")
    else:
        target_pid = target_tr.path_id
        # current Transform scale (used for new originValue initialization)
        try:
            tr_tree, _, _ = read_tree_safe(target_tr)
            cur_scale = get_from_tree(tr_tree, "m_LocalScale") or {"x":1,"y":1,"z":1}
        except Exception:
            cur_scale = {"x":1,"y":1,"z":1}

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

            # originValue initialization (when creating)
            if created:
                ov = ensure_dict(node, "originValue")
                if ov:
                    set_vec3(ov, x=cur_scale.get("x"), y=cur_scale.get("y"), z=cur_scale.get("z"))

            sv = ensure_dict(node, "scaledValue")
            if not sv:
                logs.append(f"[SKIP] pid={obj.path_id} no scaledValue"); continue

            before = (sv.get("x"), sv.get("y"), sv.get("z"))

            if set_xyz is not None:
                set_vec3(sv, x=set_xyz[0], y=set_xyz[1], z=set_xyz[2])
            dx,dy,dz = add_dxyz
            if any(abs(v) > 0 for v in (dx,dy,dz)):
                add_vec3(sv, dx=dx, dy=dy, dz=dz)

            after = (sv.get("x"), sv.get("y"), sv.get("z"))

            # degenerate-scale guard: the engine's safe body-scale band is 0.2-2.5
            # (MergeAndCombineBodyMesh SafeScaleMin/Max). Values <=0 collapse or invert
            # the node (broken/inside-out skinning). Warn, don't block.
            _bad = [round(a, 3) for a in after if a is not None and not (0.2 <= a <= 2.5)]
            if _bad:
                logs.append(f"[SCALE_WARN] pid={obj.path_id} scaledValue {after} has component(s) "
                            f"{_bad} outside the safe range 0.2-2.5 (<=0 collapses/inverts the node); "
                            f"hips/skinning may break in-game.")

            # save attempt: save with default style first, fallback to opposite style on failure
            try:
                scale_list[idx] = make_elem_for_node(node, style)
                save_tree_safe(obj, data, tree, where)
                changed += 1
                logs.append(f"[OK] LiveCore pid={obj.path_id} target={target_pid} style={style} created={created} {before} -> {after}")
            except KeyError as e:
                alt_style = "wrapped" if style == "raw" else "raw"
                try:
                    scale_list[idx] = make_elem_for_node(node, alt_style)
                    save_tree_safe(obj, data, tree, where)
                    changed += 1
                    logs.append(f"[OK-ALT] LiveCore pid={obj.path_id} target={target_pid} style={alt_style} created={created} {before} -> {after}")
                except Exception as e2:
                    logs.append(f"[SAVE_FAIL] pid={obj.path_id} err={e2} (alt after {e})")
            except Exception as e:
                logs.append(f"[SAVE_FAIL] pid={obj.path_id} err={e}")

    # save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(env.file.save(packer="lz4"))

    # log
    header = [
        f"Scanned LiveCore objs: {scanned}",
        f"Changed entries: {changed}",
        f"Target name: {target_go_name}",
        f"Set xyz: {set_xyz}",
        f"Add dxyz: {add_dxyz}",
    ]
    (out_path.with_suffix(out_path.suffix + ".hips_log.txt")).write_text("\n".join(header + logs), encoding="utf-8")

    return scanned, changed, logs

# ---------- GUI (single/batch with naming) ----------

def name_transform_for_output(src_file: Path, out_root: Path, src_root: Path, prefix: str, suffix: str):
    rel = src_file.relative_to(src_root)
    return (out_root / rel.parent / f"{prefix}{src_file.stem}{suffix}{src_file.suffix}")

def run_gui():
    root = tk.Tk()
    root.geometry("860x620")

    mode = tk.StringVar(value="single")

    in_file = tk.StringVar()
    out_file = tk.StringVar()

    in_dir = tk.StringVar()
    out_dir = tk.StringVar()
    out_prefix = tk.StringVar(value="")
    out_suffix = tk.StringVar(value="")

    target_name = tk.StringVar(value="HipsSize")

    set_x = tk.StringVar(value="")
    set_y = tk.StringVar(value="")
    set_z = tk.StringVar(value="")
    add_dx = tk.StringVar(value="0")
    add_dy = tk.StringVar(value="0")
    add_dz = tk.StringVar(value="0")

    def parse_set():
        s = (set_x.get().strip(), set_y.get().strip(), set_z.get().strip())
        if all(v == "" for v in s): return None
        try: return (float(s[0]), float(s[1]), float(s[2]))
        except Exception: return None

    def parse_add():
        try: return (float(add_dx.get() or 0), float(add_dy.get() or 0), float(add_dz.get() or 0))
        except Exception: return (0.0, 0.0, 0.0)

    def pick_file(var, title):
        p = filedialog.askopenfilename(title=title, filetypes=[("All files","*.*")])
        if p: var.set(p)
    def pick_save_file(var, title):
        p = filedialog.asksaveasfilename(title=title, defaultextension=".ab", filetypes=[("All files","*.*")])
        if p: var.set(p)
    def pick_dir(var, title):
        p = filedialog.askdirectory(title=title)
        if p: var.set(p)

    def show_log(lines, title=None):
        win = tk.Toplevel(root); win.title(title or _tr("Result")); win.geometry("1100x700")
        frm = ttk.Frame(win); frm.pack(fill="both", expand=True, padx=8, pady=8)
        txt = tk.Text(frm, wrap="none")
        xsb = ttk.Scrollbar(frm, orient="horizontal", command=txt.xview)
        ysb = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
        txt.configure(xscrollcommand=xsb.set, yscrollcommand=ysb.set)
        txt.grid(row=0, column=0, sticky="nsew"); ysb.grid(row=0, column=1, sticky="ns"); xsb.grid(row=1, column=0, sticky="ew")
        frm.rowconfigure(0, weight=1); frm.columnconfigure(0, weight=1)
        txt.insert("end", "\n".join(lines)); txt.configure(state="disabled")

    def run_single():
        if not in_file.get():
            messagebox.showerror(_tr("Error"), _tr("Please select input bundle")); return
        if not out_file.get():
            messagebox.showerror(_tr("Error"), _tr("Please specify output path")); return
        setv = parse_set(); addv = parse_add()
        scanned, changed, logs = modify_livecore_scaling(
            Path(in_file.get()), Path(out_file.get()),
            target_name.get(), setv, addv
        )
        show_log([f"[SINGLE] scanned={scanned} changed={changed}", *logs])

    def run_batch():
        if not in_dir.get():
            messagebox.showerror(_tr("Error"), _tr("Please select input folder")); return
        if not out_dir.get():
            messagebox.showerror(_tr("Error"), _tr("Please specify output folder")); return
        setv = parse_set(); addv = parse_add()
        files = 0; total_scanned = 0; total_changed = 0; failed = 0
        for p in Path(in_dir.get()).rglob("*"):
            if not p.is_file(): continue
            files += 1
            out_p = name_transform_for_output(p, Path(out_dir.get()), Path(in_dir.get()), out_prefix.get(), out_suffix.get())
            try:
                scanned, changed, logs = modify_livecore_scaling(p, out_p, target_name.get(), setv, addv)
                total_scanned += scanned; total_changed += changed
            except Exception:
                failed += 1
        show_log([f"[BATCH] files={files} scanned={total_scanned} changed={total_changed} failed={failed}"])

    # The whole window is rebuilt when the language changes; the tk variables
    # above live in this outer scope, so any text the user already typed is kept.
    container = ttk.Frame(root); container.pack(fill="both", expand=True)

    def on_language(code):
        _set_lang(code)
        build()

    def build():
        for w in container.winfo_children():
            w.destroy()
        root.title(_tr("LiveCoreMemberNodeScaling scaler (HipsSize)"))

        # language picker
        bar = ttk.Frame(container); bar.pack(fill="x", padx=12, pady=(10, 0))
        ttk.Label(bar, text=_tr("Language")).pack(side="left")
        names = [name for _code, name in _lang_opts()]
        code_by_name = {name: code for code, name in _lang_opts()}
        name_by_code = {code: name for code, name in _lang_opts()}
        lang_display = tk.StringVar(value=name_by_code.get(_get_lang(), names[0]))
        cb = ttk.Combobox(bar, textvariable=lang_display, values=names,
                          state="readonly", width=10)
        cb.pack(side="left", padx=(6, 0))
        cb.bind("<<ComboboxSelected>>",
                lambda e: on_language(code_by_name[lang_display.get()]))

        frm = ttk.Frame(container); frm.pack(fill="both", expand=True, padx=12, pady=12)

        # Single
        s = ttk.LabelFrame(frm, text=_tr("Single"))
        s.grid(row=0, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(s, text=_tr("Input bundle")).grid(row=0, column=0, sticky="w")
        ttk.Entry(s, textvariable=in_file, width=60).grid(row=0, column=1, padx=6)
        ttk.Button(s, text=_tr("Browse"), command=lambda: pick_file(in_file, _tr("Select input bundle"))).grid(row=0, column=2)
        ttk.Label(s, text=_tr("Output path")).grid(row=1, column=0, sticky="w")
        ttk.Entry(s, textvariable=out_file, width=60).grid(row=1, column=1, padx=6)
        ttk.Button(s, text=_tr("Browse"), command=lambda: pick_save_file(out_file, _tr("Save output bundle"))).grid(row=1, column=2)
        ttk.Button(s, text=_tr("Run (Single)"), command=run_single).grid(row=2, column=0, columnspan=3, pady=6)

        # Batch
        b = ttk.LabelFrame(frm, text=_tr("Batch"))
        b.grid(row=1, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(b, text=_tr("Input dir")).grid(row=0, column=0, sticky="w")
        ttk.Entry(b, textvariable=in_dir, width=60).grid(row=0, column=1, padx=6)
        ttk.Button(b, text=_tr("Browse"), command=lambda: pick_dir(in_dir, _tr("Select input folder"))).grid(row=0, column=2)
        ttk.Label(b, text=_tr("Output dir")).grid(row=1, column=0, sticky="w")
        ttk.Entry(b, textvariable=out_dir, width=60).grid(row=1, column=1, padx=6)
        ttk.Button(b, text=_tr("Browse"), command=lambda: pick_dir(out_dir, _tr("Select output folder"))).grid(row=1, column=2)
        ttk.Label(b, text=_tr("Prefix")).grid(row=2, column=0, sticky="w")
        ttk.Entry(b, textvariable=out_prefix, width=18).grid(row=2, column=1, sticky="w")
        ttk.Label(b, text=_tr("Suffix")).grid(row=2, column=1, sticky="e")
        ttk.Entry(b, textvariable=out_suffix, width=18).grid(row=2, column=2, sticky="w")
        ttk.Button(b, text=_tr("Run (Batch)"), command=run_batch).grid(row=3, column=0, columnspan=3, pady=6)

        # Options
        o = ttk.LabelFrame(frm, text=_tr("Options"))
        o.grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(o, text=_tr("Target GameObject name")).grid(row=0, column=0, sticky="w")
        ttk.Entry(o, textvariable=target_name, width=24).grid(row=0, column=1, sticky="w")

        ttk.Label(o, text=_tr("Set scaledValue (x,y,z)")).grid(row=1, column=0, sticky="w")
        ttk.Entry(o, textvariable=set_x, width=10).grid(row=1, column=1, sticky="w")
        ttk.Entry(o, textvariable=set_y, width=10).grid(row=1, column=1, sticky="w", padx=(80,0))
        ttk.Entry(o, textvariable=set_z, width=10).grid(row=1, column=1, sticky="w", padx=(160,0))
        ttk.Label(o, text=_tr("Add Δ (dx,dy,dz)")).grid(row=2, column=0, sticky="w")
        ttk.Entry(o, textvariable=add_dx, width=10).grid(row=2, column=1, sticky="w")
        ttk.Entry(o, textvariable=add_dy, width=10).grid(row=2, column=1, sticky="w", padx=(80,0))
        ttk.Entry(o, textvariable=add_dz, width=10).grid(row=2, column=1, sticky="w", padx=(160,0))

        for r in range(3):
            frm.rowconfigure(r, weight=0)
        frm.columnconfigure(1, weight=1)

    build()
    root.mainloop()

if __name__ == "__main__":
    run_gui()
