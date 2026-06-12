# breast_dyna_changer_complete.py

# pip install UnityPy

import fnmatch
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from collections import Counter

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

def try_get_go_name_from_tree(go_tree):
    if not isinstance(go_tree, dict):
        return None
    if "m_Name" in go_tree and isinstance(go_tree["m_Name"], str):
        return go_tree["m_Name"]
    base = go_tree.get("Base")
    if isinstance(base, dict) and isinstance(base.get("m_Name"), str):
        return base["m_Name"]
    return None

def name_matches_ci(name, patterns):
    if not patterns:
        return True
    s = (name or "").lower()
    for p in patterns:
        if fnmatch.fnmatchcase(s, p.lower()):
            return True
    return False

def build_maps(env):
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

# ---------- Character ID related functions ----------

# n-value mapping by character ID
CHAR_ID_TO_N_MAPPING = {
    # n : charID mapping
    0: [9, 209, 9999],
    1: [5],
    2: [4, 109, 202],
    3: [1, 6, 106, 210],
    4: [3, 102, 104, 203, 212],
    5: [8, 101, 105, 201, 207],
    6: [2, 103, 107, 108, 205, 206, 211],
    7: [7, 204, 208]
}

def get_n_value_for_char_id(char_id):
    """Find corresponding n value from character ID"""
    for n, char_ids in CHAR_ID_TO_N_MAPPING.items():
        if char_id in char_ids:
            return n
    return None

def extract_char_id_from_texture_name(texture_name):
    """
    'ch0107_co0001_body' extract character ID from format
    'ch'and '_' digits from 4-digit number between, excluding leading zeros
    Example: ch0001 -> 1, ch0212 -> 212
    """
    if not texture_name or not texture_name.startswith('ch'):
        return None

    start_idx = 2  # 'ch' from next
    end_idx = texture_name.find('_', start_idx)

    if end_idx == -1:
        return None

    char_id_str = texture_name[start_idx:end_idx]

    # Check if it's a 4-digit number
    if len(char_id_str) != 4 or not char_id_str.isdigit():
        return None

    # Remove leading zeros and convert to integer
    char_id = int(char_id_str)
    return char_id

def find_character_id_from_bundle(env):
    """
    Find character ID from bundle from textures 'ch####_co####_body' Find names with format and extract character ID
    """
    for obj in env.objects:
        if is_obj_type(obj, ("Texture2D", 28)):
            try:
                tree, _, _ = read_tree_safe(obj)
                name = get_from_tree(tree, "m_Name")
                if name and '_body' in name:
                    char_id = extract_char_id_from_texture_name(name)
                    if char_id is not None:
                        return char_id
            except Exception:
                continue
    return None

def generate_output_filename(input_path, prefix, suffix, use_character_specific, env=None):
    """
    Generate output filename
    if use_character_specific is True and character ID is found, add jigglen
    """
    input_file = Path(input_path)

    if use_character_specific and env:
        char_id = find_character_id_from_bundle(env)
        if char_id is not None:
            n_value = get_n_value_for_char_id(char_id)
            if n_value is not None:
                # add in jigglen format
                jiggle_suffix = f"jiggle{n_value}"
                full_suffix = f"{suffix}{jiggle_suffix}" if suffix else jiggle_suffix
                return f"{prefix}{input_file.stem}{full_suffix}{input_file.suffix}"

    # generate default filename
    return f"{prefix}{input_file.stem}{suffix}{input_file.suffix}"

# ---------- core function ----------

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
    use_character_specific=False,  # new parameter
):
    env = UnityPy.load(str(in_path))
    obj_by_pid, go_name_by_pid = build_maps(env)
    th = type_histogram(env)

    # Find character ID when using character-specific settings
    char_specific_n = None
    if use_character_specific:
        char_id = find_character_id_from_bundle(env)
        if char_id is not None:
            char_specific_n = get_n_value_for_char_id(char_id)
            if char_specific_n is not None:
                # apply additive values according to n value
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

        # Breast-specific filtering
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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(env.file.save(packer="lz4"))

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
        header.append(f"Character ID found: {find_character_id_from_bundle(env)}, n-value: {char_specific_n}")

    header.append(f"Input: stiff={stiff_value} drag={drag_value} low(dy,dz)=({low_dy},{low_dz}) high(dy,dz)=({high_dy},{high_dz})")

    (out_path.with_suffix(out_path.suffix + ".modify_log.txt")).write_text(
        "\n".join(header + logs), encoding="utf-8"
    )

    return scanned, changed, header + logs, char_specific_n

# ---------- GUI ----------

def show_log_window(root, title, lines):
    win = tk.Toplevel(root)
    win.title(title)
    win.geometry("1100x700")
    frm = ttk.Frame(win)
    frm.pack(fill="both", expand=True, padx=8, pady=8)
    txt = tk.Text(frm, wrap="none")
    xsb = ttk.Scrollbar(frm, orient="horizontal", command=txt.xview)
    ysb = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
    txt.configure(xscrollcommand=xsb.set, yscrollcommand=ysb.set)
    txt.grid(row=0, column=0, sticky="nsew")
    ysb.grid(row=0, column=1, sticky="ns")
    xsb.grid(row=1, column=0, sticky="ew")
    frm.rowconfigure(0, weight=1)
    frm.columnconfigure(0, weight=1)
    txt.insert("end", "\n".join(lines))
    txt.configure(state="disabled")

def run_gui():
    root = tk.Tk()
    root.title("Breast Dyna Changer (SwingBone Modifier)")
    root.geometry("900x700")  # increase height

    # single variables
    in_file = tk.StringVar()
    out_file = tk.StringVar()

    # batch variables
    in_dir = tk.StringVar()
    out_dir = tk.StringVar()
    out_prefix = tk.StringVar(value="")
    out_suffix = tk.StringVar(value="")

    # common variables
    target_patterns = tk.StringVar(value="LeftBreast_Dyna, RightBreast_Dyna")
    stiff_val = tk.StringVar(value="0.02")
    drag_val = tk.StringVar(value="0.3")
    low_dy_val = tk.StringVar(value="-1.0")
    low_dz_val = tk.StringVar(value="-1.0")
    high_dy_val = tk.StringVar(value="1.0")
    high_dz_val = tk.StringVar(value="1.0")

    # New variable: Whether to use character-specific settings
    use_char_specific = tk.BooleanVar(value=False)

    def pick_in():
        p = filedialog.askopenfilename(title="Select input bundle")
        if p:
            in_file.set(p)

    def pick_out():
        p = filedialog.asksaveasfilename(title="Save output bundle", defaultextension=".bundle")
        if p:
            out_file.set(p)

    def pick_in_dir():
        p = filedialog.askdirectory(title="Select input folder")
        if p:
            in_dir.set(p)

    def pick_out_dir():
        p = filedialog.askdirectory(title="Select output folder")
        if p:
            out_dir.set(p)

    def parse_params():
        patterns = [p.strip() for p in target_patterns.get().replace(",", " ").split() if p.strip()]
        try:
            stiff = float(stiff_val.get()) if stiff_val.get().strip() else None
        except:
            stiff = None
        try:
            drag = float(drag_val.get()) if drag_val.get().strip() else None
        except:
            drag = None

        # use manual settings values only when not using character-specific settings
        if use_char_specific.get():
            ldy, ldz, hdy, hdz = 0, 0, 0, 0  # automatically set within function
        else:
            ldy = float(low_dy_val.get() or 0)
            ldz = float(low_dz_val.get() or 0)
            hdy = float(high_dy_val.get() or 0)
            hdz = float(high_dz_val.get() or 0)

        return patterns, stiff, drag, ldy, ldz, hdy, hdz

    def run_single():
        if not in_file.get():
            messagebox.showerror("Error", "Please select input bundle")
            return
        if not out_file.get():
            messagebox.showerror("Error", "Please specify output path")
            return

        patterns, stiff, drag, ldy, ldz, hdy, hdz = parse_params()
        try:
            _, _, logs, n_value = modify_swingbones_in_bundle(
                Path(in_file.get()),
                Path(out_file.get()),
                patterns, stiff, drag, ldy, ldz, hdy, hdz,
                use_character_specific=use_char_specific.get()
            )
            show_log_window(root, "Single processing complete", logs)
        except Exception as e:
            messagebox.showerror("Error", f"Error occurred during processing:\n{e}")

    def run_batch():
        if not in_dir.get():
            messagebox.showerror("Error", "Please select input folder")
            return
        if not out_dir.get():
            messagebox.showerror("Error", "Please specify output folder")
            return

        patterns, stiff, drag, ldy, ldz, hdy, hdz = parse_params()
        total = 0
        success = 0
        failed = 0
        in_path = Path(in_dir.get())
        out_path = Path(out_dir.get())
        prefix = out_prefix.get()
        suffix = out_suffix.get()

        batch_logs = []

        for file in in_path.rglob("*"):
            if not file.is_file():
                continue
            total += 1
            rel = file.relative_to(in_path)

            try:
                # add jiggle to filename when using character-specific settings
                if use_char_specific.get():
                    env_preview = UnityPy.load(str(file))
                    out_filename = generate_output_filename(file, prefix, suffix, use_char_specific.get(), env_preview)
                else:
                    out_filename = f"{prefix}{file.stem}{suffix}{file.suffix}"

                out_file_path = out_path / rel.parent / out_filename

                _, _, file_logs, n_value = modify_swingbones_in_bundle(
                    file, out_file_path,
                    patterns, stiff, drag, ldy, ldz, hdy, hdz,
                    use_character_specific=use_char_specific.get()
                )
                success += 1

                if use_char_specific.get() and n_value is not None:
                    batch_logs.append(f"✓ {file.name} -> {out_filename} (jiggle{n_value})")
                else:
                    batch_logs.append(f"✓ {file.name} -> {out_filename}")

            except Exception as e:
                failed += 1
                batch_logs.append(f"✗ {file.name}: {str(e)}")

        result_summary = [
            f"Total files: {total}",
            f"Success: {success}",
            f"Failed: {failed}",
            "",
            "Processing results per file:"
        ] + batch_logs

        show_log_window(root, "Batch processing complete", result_summary)

    def on_char_specific_toggle():
        """Change state of manual input fields when toggling character-specific settings"""
        if use_char_specific.get():
            # disable manual input when using character-specific settings
            for entry in [low_dy_entry, low_dz_entry, high_dy_entry, high_dz_entry]:
                entry.configure(state="disabled")
        else:
            # enable input fields when using manual settings
            for entry in [low_dy_entry, low_dz_entry, high_dy_entry, high_dz_entry]:
                entry.configure(state="normal")

    # create tabs
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=10, pady=10)

    # Single tab
    single_frame = ttk.Frame(notebook, padding=10)
    notebook.add(single_frame, text="Single file")

    ttk.Label(single_frame, text="Input bundle").grid(row=0, column=0, sticky="w", pady=5)
    ttk.Entry(single_frame, textvariable=in_file, width=50).grid(row=0, column=1, padx=5)
    ttk.Button(single_frame, text="Find", command=pick_in).grid(row=0, column=2)

    ttk.Label(single_frame, text="Output path").grid(row=1, column=0, sticky="w", pady=5)
    ttk.Entry(single_frame, textvariable=out_file, width=50).grid(row=1, column=1, padx=5)
    ttk.Button(single_frame, text="Find", command=pick_out).grid(row=1, column=2)

    ttk.Button(single_frame, text="Run", command=run_single, width=20).grid(row=2, column=0, columnspan=3, pady=20)

    # Batch tab
    batch_frame = ttk.Frame(notebook, padding=10)
    notebook.add(batch_frame, text="Batch processing")

    ttk.Label(batch_frame, text="Input folder").grid(row=0, column=0, sticky="w", pady=5)
    ttk.Entry(batch_frame, textvariable=in_dir, width=50).grid(row=0, column=1, padx=5)
    ttk.Button(batch_frame, text="Find", command=pick_in_dir).grid(row=0, column=2)

    ttk.Label(batch_frame, text="Output folder").grid(row=1, column=0, sticky="w", pady=5)
    ttk.Entry(batch_frame, textvariable=out_dir, width=50).grid(row=1, column=1, padx=5)
    ttk.Button(batch_frame, text="Find", command=pick_out_dir).grid(row=1, column=2)

    ttk.Label(batch_frame, text="Output prefix").grid(row=2, column=0, sticky="w", pady=5)
    ttk.Entry(batch_frame, textvariable=out_prefix, width=20).grid(row=2, column=1, sticky="w", padx=5)

    ttk.Label(batch_frame, text="Output suffix").grid(row=3, column=0, sticky="w", pady=5)
    ttk.Entry(batch_frame, textvariable=out_suffix, width=20).grid(row=3, column=1, sticky="w", padx=5)

    ttk.Label(batch_frame, text="※ When using character-specific settings, jigglen is automatically added", 
              font=("TkDefaultFont", 8), foreground="blue").grid(row=4, column=0, columnspan=3, sticky="w", pady=5)

    ttk.Button(batch_frame, text="Run", command=run_batch, width=20).grid(row=5, column=0, columnspan=3, pady=20)

    # Settings tab
    settings_frame = ttk.Frame(notebook, padding=10)
    notebook.add(settings_frame, text="Settings")

    ttk.Label(settings_frame, text="Target GO patterns (comma-separated)").grid(row=0, column=0, sticky="w", pady=5)
    ttk.Entry(settings_frame, textvariable=target_patterns, width=50).grid(row=0, column=1, columnspan=2, padx=5)

    ttk.Label(settings_frame, text="stiffnessForce").grid(row=1, column=0, sticky="w", pady=5)
    ttk.Entry(settings_frame, textvariable=stiff_val, width=15).grid(row=1, column=1, sticky="w", padx=5)

    ttk.Label(settings_frame, text="dragForce").grid(row=2, column=0, sticky="w", pady=5)
    ttk.Entry(settings_frame, textvariable=drag_val, width=15).grid(row=2, column=1, sticky="w", padx=5)

    # Add character-specific settings checkbox
    ttk.Checkbutton(settings_frame, text="Apply automatic additive values by character ID + jigglen filename", 
                   variable=use_char_specific, command=on_char_specific_toggle).grid(row=3, column=0, columnspan=2, sticky="w", pady=10)

    ttk.Label(settings_frame, text="Low Y additive").grid(row=4, column=0, sticky="w", pady=5)
    low_dy_entry = ttk.Entry(settings_frame, textvariable=low_dy_val, width=15)
    low_dy_entry.grid(row=4, column=1, sticky="w", padx=5)

    ttk.Label(settings_frame, text="Low Z additive").grid(row=5, column=0, sticky="w", pady=5)
    low_dz_entry = ttk.Entry(settings_frame, textvariable=low_dz_val, width=15)
    low_dz_entry.grid(row=5, column=1, sticky="w", padx=5)

    ttk.Label(settings_frame, text="High Y additive").grid(row=6, column=0, sticky="w", pady=5)
    high_dy_entry = ttk.Entry(settings_frame, textvariable=high_dy_val, width=15)
    high_dy_entry.grid(row=6, column=1, sticky="w", padx=5)

    ttk.Label(settings_frame, text="High Z additive").grid(row=7, column=0, sticky="w", pady=5)
    high_dz_entry = ttk.Entry(settings_frame, textvariable=high_dz_val, width=15)
    high_dz_entry.grid(row=7, column=1, sticky="w", padx=5)

    # Display character ID mapping information
    mapping_info = "n-value mapping by character ID (n value in jigglen):\n"
    for n, char_ids in CHAR_ID_TO_N_MAPPING.items():
        mapping_info += f"n={n}: {', '.join(map(str, char_ids))}\n"

    mapping_info += "\nExample: Character ID 107 -> n=6 -> add jiggle6 to filename"

    ttk.Label(settings_frame, text=mapping_info, justify="left", 
              font=("TkDefaultFont", 8)).grid(row=8, column=0, columnspan=2, sticky="w", pady=10)

    root.mainloop()

if __name__ == "__main__":
    run_gui()
