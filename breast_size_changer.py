from pathlib import Path
from collections import Counter
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import UnityPy
    from UnityPy.enums import TextureFormat
except ImportError:
    import subprocess
    import sys
    print("UnityPy is not installed. Installing...")
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

def get_transform_for_breastsize(env, obj_by_pid, breast_go_name="BreastSize"):
    go = find_gameobject_by_name(env, breast_go_name)
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
    # wrapped if any element has 'data' dict
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
    """
    Find target.m_PathID == target_pid entry in scaleValues, or create new entry matching existing style (raw/wrapped).
    """
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
    breast_go_name: str,
    set_xyz: tuple | None,   # (x,y,z) or None
    add_dxyz: tuple,         # (dx,dy,dz)
):
    env = UnityPy.load(str(in_path))
    obj_by_pid = build_obj_index(env)

    logs = []
    changed = 0
    scanned = 0

    breast_tr = get_transform_for_breastsize(env, obj_by_pid, breast_go_name=breast_go_name)
    if not breast_tr:
        logs.append(f"[MISS] BreastSize Transform not found (name={breast_go_name})")
    else:
        target_pid = breast_tr.path_id
        # current Transform scale (used for new originValue initialization)
        try:
            tr_tree, _, _ = read_tree_safe(breast_tr)
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

            # originValue initialize (when creating)
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

            # save attempt: save with default style first
            try:
                # Reflect current node in scale_list[idx] according to style (ensure referential integrity)
                scale_list[idx] = make_elem_for_node(node, style)
                save_tree_safe(obj, data, tree, where)
                changed += 1
                logs.append(f"[OK] LiveCore pid={obj.path_id} target={target_pid} style={style} created={created} {before} -> {after}")
            except KeyError as e:
                # Retry with style reversal (wrapped<->raw) on key error such as 'target'
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
        f"BreastSize name: {breast_go_name}",
        f"Set xyz: {set_xyz}",
        f"Add dxyz: {add_dxyz}",
    ]
    (out_path.with_suffix(out_path.suffix + ".scale_log.txt")).write_text("\n".join(header + logs), encoding="utf-8")

    return scanned, changed, logs

# ---------- GUI (single/batch with naming) ----------

def name_transform_for_output(src_file: Path, out_root: Path, src_root: Path, prefix: str, suffix: str):
    rel = src_file.relative_to(src_root)
    return (out_root / rel.parent / f"{prefix}{src_file.stem}{suffix}{src_file.suffix}")

def run_gui():
    root = tk.Tk()
    root.title("SIFAS Breasts Size Changer.py")
    root.geometry("860x620")

    mode = tk.StringVar(value="single")

    in_file = tk.StringVar()
    out_file = tk.StringVar()

    in_dir = tk.StringVar()
    out_dir = tk.StringVar()
    out_prefix = tk.StringVar(value="")
    out_suffix = tk.StringVar(value="")

    breast_name = tk.StringVar(value="BreastSize")

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

    def show_log(lines, title="Result"):
        win = tk.Toplevel(root); win.title(title); win.geometry("1100x700")
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
            messagebox.showerror("Error","Please select input bundle"); return
        if not out_file.get():
            messagebox.showerror("Error","Please specify output path"); return
        setv = parse_set(); addv = parse_add()
        scanned, changed, logs = modify_livecore_scaling(
            Path(in_file.get()), Path(out_file.get()),
            breast_name.get(), setv, addv
        )
        show_log([f"[SINGLE] scanned={scanned} changed={changed}", *logs])

    def run_batch():
        if not in_dir.get():
            messagebox.showerror("Error","Please select input folder"); return
        if not out_dir.get():
            messagebox.showerror("Error","Please specify output folder"); return
        setv = parse_set(); addv = parse_add()
        files = 0; total_scanned = 0; total_changed = 0; failed = 0
        for p in Path(in_dir.get()).rglob("*"):
            if not p.is_file(): continue
            files += 1
            out_p = name_transform_for_output(p, Path(out_dir.get()), Path(in_dir.get()), out_prefix.get(), out_suffix.get())
            try:
                scanned, changed, logs = modify_livecore_scaling(p, out_p, breast_name.get(), setv, addv)
                total_scanned += scanned; total_changed += changed
            except Exception:
                failed += 1
        show_log([f"[BATCH] files={files} scanned={total_scanned} changed={total_changed} failed={failed}"])

    frm = ttk.Frame(root); frm.pack(fill="both", expand=True, padx=12, pady=12)

    # Single
    s = ttk.LabelFrame(frm, text="Single")
    s.grid(row=0, column=0, columnspan=3, sticky="ew", pady=6)
    ttk.Label(s, text="Input bundle").grid(row=0, column=0, sticky="w")
    ttk.Entry(s, textvariable=in_file, width=60).grid(row=0, column=1, padx=6)
    ttk.Button(s, text="Browse", command=lambda: pick_file(in_file,"Select input bundle")).grid(row=0, column=2)
    ttk.Label(s, text="Output path").grid(row=1, column=0, sticky="w")
    ttk.Entry(s, textvariable=out_file, width=60).grid(row=1, column=1, padx=6)
    ttk.Button(s, text="Browse", command=lambda: pick_save_file(out_file,"Save output bundle")).grid(row=1, column=2)
    ttk.Button(s, text="Run (Single)", command=run_single).grid(row=2, column=0, columnspan=3, pady=6)

    # Batch
    b = ttk.LabelFrame(frm, text="Batch")
    b.grid(row=1, column=0, columnspan=3, sticky="ew", pady=6)
    in_dir_var = in_dir; out_dir_var = out_dir
    ttk.Label(b, text="Input dir").grid(row=0, column=0, sticky="w")
    ttk.Entry(b, textvariable=in_dir_var, width=60).grid(row=0, column=1, padx=6)
    ttk.Button(b, text="Browse", command=lambda: pick_dir(in_dir_var,"Select input folder")).grid(row=0, column=2)
    ttk.Label(b, text="Output dir").grid(row=1, column=0, sticky="w")
    ttk.Entry(b, textvariable=out_dir_var, width=60).grid(row=1, column=1, padx=6)
    ttk.Button(b, text="Browse", command=lambda: pick_dir(out_dir_var,"Select output folder")).grid(row=1, column=2)
    ttk.Label(b, text="Prefix").grid(row=2, column=0, sticky="w")
    ttk.Entry(b, textvariable=out_prefix, width=18).grid(row=2, column=1, sticky="w")
    ttk.Label(b, text="Suffix").grid(row=2, column=1, sticky="e")
    ttk.Entry(b, textvariable=out_suffix, width=18).grid(row=2, column=2, sticky="w")
    ttk.Button(b, text="Run (Batch)", command=run_batch).grid(row=3, column=0, columnspan=3, pady=6)

    # Options
    o = ttk.LabelFrame(frm, text="Options")
    o.grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
    ttk.Label(o, text="Breast GameObject name").grid(row=0, column=0, sticky="w")
    ttk.Entry(o, textvariable=breast_name, width=24).grid(row=0, column=1, sticky="w")

    ttk.Label(o, text="Set scaledValue (x,y,z)").grid(row=1, column=0, sticky="w")
    ttk.Entry(o, textvariable=set_x, width=10).grid(row=1, column=1, sticky="w")
    ttk.Entry(o, textvariable=set_y, width=10).grid(row=1, column=1, sticky="w", padx=(80,0))
    ttk.Entry(o, textvariable=set_z, width=10).grid(row=1, column=1, sticky="w", padx=(160,0))
    ttk.Label(o, text="Add Δ (dx,dy,dz)").grid(row=2, column=0, sticky="w")
    ttk.Entry(o, textvariable=add_dx, width=10).grid(row=2, column=1, sticky="w")
    ttk.Entry(o, textvariable=add_dy, width=10).grid(row=2, column=1, sticky="w", padx=(80,0))
    ttk.Entry(o, textvariable=add_dz, width=10).grid(row=2, column=1, sticky="w", padx=(160,0))

    for r in range(3):
        frm.rowconfigure(r, weight=0)
    frm.columnconfigure(1, weight=1)

    root.mainloop()

if __name__ == "__main__":
    run_gui()
