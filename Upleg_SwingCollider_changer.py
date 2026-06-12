# pip install UnityPy

from pathlib import Path
import fnmatch
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
# ---------- helpers ----------

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

def set_in_tree_if_exists(tree, key, value):
    if isinstance(tree, dict):
        if key in tree:
            tree[key] = value; return True
        base = tree.get("Base")
        if isinstance(base, dict) and key in base:
            base[key] = value; return True
    return False

def ensure_dict(tree, key):
    v = get_from_tree(tree, key)
    return v if isinstance(v, dict) else None

def name_matches_ci(name, patterns):
    s = (name or "").lower()
    for p in patterns:
        if fnmatch.fnmatchcase(s, p.lower()):
            return True
    return False

def build_maps(env):
    # Index by both pathID and -pathID + GameObject name mapping
    obj_by_pid = {}
    go_name_by_pid = {}
    for o in env.objects:
        obj_by_pid[o.path_id] = o
        obj_by_pid[-o.path_id] = o
        if is_obj_type(o, ("GameObject", 1)):
            try:
                t, _, _ = read_tree_safe(o)
                nm = None
                if isinstance(t, dict):
                    nm = t.get("m_Name") if isinstance(t.get("m_Name"), str) else None
                    if not nm and isinstance(t.get("Base"), dict) and isinstance(t["Base"].get("m_Name"), str):
                        nm = t["Base"]["m_Name"]
                if nm:
                    go_name_by_pid[o.path_id] = nm
                    go_name_by_pid[-o.path_id] = nm
            except Exception:
                pass
    return obj_by_pid, go_name_by_pid

def try_get_script_class_with_index(obj_by_pid, mono_tree):
    p = get_from_tree(mono_tree, "m_Script")
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
            st, _, _ = read_tree_safe(sobj)
        except Exception:
            continue
        for key in ("m_ClassName","className","m_Name","name"):
            v = get_from_tree(st, key)
            if isinstance(v, str) and v:
                return v
    return None

def clamp(v, vmin, vmax):
    if v is None:
        return None
    if vmin is not None:
        v = max(vmin, v)
    if vmax is not None:
        v = min(vmax, v)
    return v

# ---------- core modify ----------

def modify_swingcolliders(
    in_path: Path,
    out_path: Path,
    target_name_patterns: list,   # Example: ["LeftUpLeg","RightUpLeg"]
    set_radius: float | None,
    add_radius: float | None,
    set_offset_xyz: tuple | None, # (x,y,z) or None
    add_offset_dxyz: tuple,       # (dx,dy,dz)
    radius_min: float | None = None,
    radius_max: float | None = None,
    offset_min: tuple | None = None,  # (min_x, min_y, min_z) or None
    offset_max: tuple | None = None,  # (max_x, max_y, max_z) or None
):
    env = UnityPy.load(str(in_path))
    obj_by_pid, go_name_by_pid = build_maps(env)

    scanned = 0
    changed = 0
    logs = []

    for obj in env.objects:
        if not is_obj_type(obj, ("MonoBehaviour", 114)):
            continue
        try:
            tree, data, where = read_tree_safe(obj)
        except Exception as e:
            logs.append(f"[READ_FAIL] pid={obj.path_id} err={e}")
            continue

        # SwingCollider determination: has radius and offset(Vector3f) + strengthen script name
        has_radius = (get_from_tree(tree, "radius") is not None)
        off = ensure_dict(tree, "offset")
        has_offset = isinstance(off, dict) and all(k in off for k in ("x","y","z"))
        if not (has_radius and has_offset):
            continue

        cls = try_get_script_class_with_index(obj_by_pid, tree) or ""
        if cls and ("swingcollider" not in cls.lower()):
            continue

        go_pptr = get_from_tree(tree, "m_GameObject")
        go_pid = go_pptr.get("m_PathID") or go_pptr.get("pathID") if isinstance(go_pptr, dict) else None
        go_name = go_name_by_pid.get(go_pid) or go_name_by_pid.get(-go_pid) if isinstance(go_pid, int) else None
        if not name_matches_ci(go_name or "", target_name_patterns):
            continue

        scanned += 1

        # original value
        orig_r = get_from_tree(tree, "radius")
        orig_x = off.get("x"); orig_y = off.get("y"); orig_z = off.get("z")

        any_change = False

        # 1) absolute radius specification
        if set_radius is not None and orig_r is not None:
            if set_in_tree_if_exists(tree, "radius", float(set_radius)):
                any_change = True

        # 2) radius additive + clamp (apply to additive only)
        if add_radius is not None and orig_r is not None:
            cur_r = get_from_tree(tree, "radius")
            cur_r = float(cur_r if cur_r is not None else orig_r)
            nr = cur_r + float(add_radius)
            nr = clamp(nr, radius_min, radius_max)
            if set_in_tree_if_exists(tree, "radius", nr):
                any_change = True

        # 3) absolute offset specification
        off = ensure_dict(tree, "offset") or {}
        if set_offset_xyz is not None:
            x, y, z = set_offset_xyz
            off["x"] = float(x); off["y"] = float(y); off["z"] = float(z)
            any_change = True

        # 4) offset additive + per-axis clamp (apply to additive only)
        dx, dy, dz = add_offset_dxyz
        if any(abs(v) > 0 for v in (dx, dy, dz)):
            nx = float(off.get("x") or 0.0) + float(dx)
            ny = float(off.get("y") or 0.0) + float(dy)
            nz = float(off.get("z") or 0.0) + float(dz)
            # apply clamp
            if offset_min is not None:
                nx = clamp(nx, offset_min[0], None)
                ny = clamp(ny, offset_min[1], None)
                nz = clamp(nz, offset_min[2], None)
            if offset_max is not None:
                nx = clamp(nx, None, offset_max[0])
                ny = clamp(ny, None, offset_max[1])
                nz = clamp(nz, None, offset_max[2])
            off["x"] = nx; off["y"] = ny; off["z"] = nz
            any_change = True

        if not any_change:
            logs.append(f"[SKIP_NO_CHANGE] pid={obj.path_id} go='{go_name}' cls='{cls}'")
            continue

        try:
            save_tree_safe(obj, data, tree, where)
            changed += 1
            logs.append(
                f"[OK] pid={obj.path_id} go='{go_name}' "
                f"radius: {orig_r} -> {get_from_tree(tree,'radius')} "
                f"offset: ({orig_x},{orig_y},{orig_z}) -> ({off.get('x')},{off.get('y')},{off.get('z')})"
            )
        except Exception as e:
            logs.append(f"[SAVE_FAIL] pid={obj.path_id} go='{go_name}' err={e}")

    # save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(env.file.save(packer="lz4"))

    # log
    hdr = [
        f"Scanned SwingColliders: {scanned}",
        f"Changed objects: {changed}",
        f"Targets: {', '.join(target_name_patterns)}",
        f"Set radius: {set_radius} | Add radius: {add_radius} | Clamp[min,max]=[{radius_min},{radius_max}]",
        f"Set offset: {set_offset_xyz} | Add dxyz: {add_offset_dxyz} | "
        f"Clamp x[min,max]=[{(offset_min or [None,None,None])[0]},{(offset_max or [None,None,None])[0]}], "
        f"y[min,max]=[{(offset_min or [None,None,None])[1]},{(offset_max or [None,None,None])[1]}], "
        f"z[min,max]=[{(offset_min or [None,None,None])[2]},{(offset_max or [None,None,None])[2]}]",
    ]
    (out_path.with_suffix(out_path.suffix + ".swingcollider_log.txt")).write_text("\n".join(hdr + logs), encoding="utf-8")
    return scanned, changed, logs

# ---------- GUI ----------

def name_transform_for_output(src_file: Path, out_root: Path, src_root: Path, prefix: str, suffix: str):
    rel = src_file.relative_to(src_root)
    return (out_root / rel.parent / f"{prefix}{src_file.stem}{suffix}{src_file.suffix}")

def run_gui():
    root = tk.Tk()
    root.title("SwingCollider Tweaker (radius + offset with clamps)")
    root.geometry("980x720")

    mode = tk.StringVar(value="single")

    in_file = tk.StringVar()
    out_file = tk.StringVar()

    in_dir = tk.StringVar()
    out_dir = tk.StringVar()
    out_prefix = tk.StringVar(value="")
    out_suffix = tk.StringVar(value="")

    target_names = tk.StringVar(value="LeftUpLeg, RightUpLeg")

    set_radius = tk.StringVar(value="")
    add_radius = tk.StringVar(value="0")
    radius_min_var = tk.StringVar(value="")
    radius_max_var = tk.StringVar(value="")

    set_off_x = tk.StringVar(value="")
    set_off_y = tk.StringVar(value="")
    set_off_z = tk.StringVar(value="")
    add_dx = tk.StringVar(value="0")
    add_dy = tk.StringVar(value="0")
    add_dz = tk.StringVar(value="0")

    off_min_x = tk.StringVar(value="")
    off_min_y = tk.StringVar(value="")
    off_min_z = tk.StringVar(value="")
    off_max_x = tk.StringVar(value="")
    off_max_y = tk.StringVar(value="")
    off_max_z = tk.StringVar(value="")

    def parse_float_opt(s):
        s = (s or "").strip()
        if s == "": return None
        try: return float(s)
        except: return None

    def parse_set_radius():
        return parse_float_opt(set_radius.get())

    def parse_add_radius():
        return parse_float_opt(add_radius.get()) or 0.0

    def parse_set_offset():
        sx, sy, sz = set_off_x.get().strip(), set_off_y.get().strip(), set_off_z.get().strip()
        if sx == "" and sy == "" and sz == "": return None
        try: return (float(sx), float(sy), float(sz))
        except: return None

    def parse_add_offset():
        try:
            return (float(add_dx.get() or 0), float(add_dy.get() or 0), float(add_dz.get() or 0))
        except:
            return (0.0, 0.0, 0.0)

    def parse_offset_min():
        x = parse_float_opt(off_min_x.get()); y = parse_float_opt(off_min_y.get()); z = parse_float_opt(off_min_z.get())
        if x is None and y is None and z is None: return None
        return (x, y, z)

    def parse_offset_max():
        x = parse_float_opt(off_max_x.get()); y = parse_float_opt(off_max_y.get()); z = parse_float_opt(off_max_z.get())
        if x is None and y is None and z is None: return None
        return (x, y, z)

    def parse_patterns():
        raw = target_names.get()
        return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]

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
        win = tk.Toplevel(root); win.title(title); win.geometry("1100x720")
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
        pats = parse_patterns()
        sr = parse_set_radius()
        ar = parse_add_radius()
        rmin = parse_float_opt(radius_min_var.get())
        rmax = parse_float_opt(radius_max_var.get())
        so = parse_set_offset()
        ao = parse_add_offset()
        omin = parse_offset_min()
        omax = parse_offset_max()
        scanned, changed, logs = modify_swingcolliders(
            Path(in_file.get()), Path(out_file.get()),
            pats, sr, ar, so, ao,
            radius_min=rmin, radius_max=rmax,
            offset_min=omin, offset_max=omax
        )
        show_log([f"[SINGLE] scanned={scanned} changed={changed}", *logs])

    def run_batch():
        if not in_dir.get():
            messagebox.showerror("Error","Please select input folder"); return
        if not out_dir.get():
            messagebox.showerror("Error","Please specify output folder"); return
        pats = parse_patterns()
        sr = parse_set_radius()
        ar = parse_add_radius()
        rmin = parse_float_opt(radius_min_var.get())
        rmax = parse_float_opt(radius_max_var.get())
        so = parse_set_offset()
        ao = parse_add_offset()
        omin = parse_offset_min()
        omax = parse_offset_max()
        files = 0; total_scanned = 0; total_changed = 0; failed = 0
        for p in Path(in_dir.get()).rglob("*"):
            if not p.is_file(): continue
            files += 1
            out_p = name_transform_for_output(p, Path(out_dir.get()), Path(in_dir.get()), out_prefix.get(), out_suffix.get())
            try:
                scanned, changed, _ = modify_swingcolliders(
                    p, out_p,
                    pats, sr, ar, so, ao,
                    radius_min=rmin, radius_max=rmax,
                    offset_min=omin, offset_max=omax
                )
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
    ttk.Label(b, text="Input dir").grid(row=0, column=0, sticky="w")
    ttk.Entry(b, textvariable=in_dir, width=60).grid(row=0, column=1, padx=6)
    ttk.Button(b, text="Browse", command=lambda: pick_dir(in_dir,"Select input folder")).grid(row=0, column=2)
    ttk.Label(b, text="Output dir").grid(row=1, column=0, sticky="w")
    ttk.Entry(b, textvariable=out_dir, width=60).grid(row=1, column=1, padx=6)
    ttk.Button(b, text="Browse", command=lambda: pick_dir(out_dir,"Select output folder")).grid(row=1, column=2)
    ttk.Label(b, text="Prefix").grid(row=2, column=0, sticky="w")
    ttk.Entry(b, textvariable=out_prefix, width=18).grid(row=2, column=1, sticky="w")
    ttk.Label(b, text="Suffix").grid(row=2, column=1, sticky="e")
    ttk.Entry(b, textvariable=out_suffix, width=18).grid(row=2, column=2, sticky="w")
    ttk.Button(b, text="Run (Batch)", command=run_batch).grid(row=3, column=0, columnspan=3, pady=6)

    # Options
    o = ttk.LabelFrame(frm, text="Options")
    o.grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
    ttk.Label(o, text="Target GameObject names (comma/space)").grid(row=0, column=0, sticky="w")
    ttk.Entry(o, textvariable=target_names, width=60).grid(row=0, column=1, padx=6)

    ttk.Label(o, text="Set radius").grid(row=1, column=0, sticky="w")
    ttk.Entry(o, textvariable=set_radius, width=10).grid(row=1, column=1, sticky="w")
    ttk.Label(o, text="Add Δradius").grid(row=1, column=1, sticky="w", padx=(100,0))
    ttk.Entry(o, textvariable=add_radius, width=10).grid(row=1, column=1, sticky="w", padx=(180,0))
    ttk.Label(o, text="Clamp radius [min, max]").grid(row=1, column=2, sticky="e")
    ttk.Entry(o, textvariable=radius_min_var, width=10).grid(row=1, column=3, sticky="w", padx=(6,0))
    ttk.Entry(o, textvariable=radius_max_var, width=10).grid(row=1, column=3, sticky="w", padx=(96,0))

    ttk.Label(o, text="Set offset (x,y,z)").grid(row=2, column=0, sticky="w")
    ttk.Entry(o, textvariable=set_off_x, width=10).grid(row=2, column=1, sticky="w")
    ttk.Entry(o, textvariable=set_off_y, width=10).grid(row=2, column=1, sticky="w", padx=(80,0))
    ttk.Entry(o, textvariable=set_off_z, width=10).grid(row=2, column=1, sticky="w", padx=(160,0))

    ttk.Label(o, text="Add Δoffset (dx,dy,dz)").grid(row=3, column=0, sticky="w")
    ttk.Entry(o, textvariable=add_dx, width=10).grid(row=3, column=1, sticky="w")
    ttk.Entry(o, textvariable=add_dy, width=10).grid(row=3, column=1, sticky="w", padx=(80,0))
    ttk.Entry(o, textvariable=add_dz, width=10).grid(row=3, column=1, sticky="w", padx=(160,0))

    ttk.Label(o, text="Clamp offset min (x,y,z)").grid(row=4, column=0, sticky="w")
    ttk.Entry(o, textvariable=off_min_x, width=10).grid(row=4, column=1, sticky="w")
    ttk.Entry(o, textvariable=off_min_y, width=10).grid(row=4, column=1, sticky="w", padx=(80,0))
    ttk.Entry(o, textvariable=off_min_z, width=10).grid(row=4, column=1, sticky="w", padx=(160,0))

    ttk.Label(o, text="Clamp offset max (x,y,z)").grid(row=5, column=0, sticky="w")
    ttk.Entry(o, textvariable=off_max_x, width=10).grid(row=5, column=1, sticky="w")
    ttk.Entry(o, textvariable=off_max_y, width=10).grid(row=5, column=1, sticky="w", padx=(80,0))
    ttk.Entry(o, textvariable=off_max_z, width=10).grid(row=5, column=1, sticky="w", padx=(160,0))

    for r in range(6):
        frm.rowconfigure(r, weight=0)
    frm.columnconfigure(1, weight=1)

    root.mainloop()

if __name__ == "__main__":
    run_gui()
