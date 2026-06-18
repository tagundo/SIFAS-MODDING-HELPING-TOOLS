# pip install UnityPy

import re, fnmatch, traceback, copy
from pathlib import Path
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
# ========== Core helpers ==========

def read_tree_safe(obj):
    data = obj.read()
    if hasattr(obj, "read_typetree"):
        try:
            tree = obj.read_typetree()
            return tree, data, "obj"
        except Exception:
            pass
    if hasattr(data, "read_typetree"):
        tree = data.read_typetree()
        return tree, data, "data"
    raise AttributeError("typetree unavailable on both obj and data")

def save_tree_safe(obj, data, tree, where):
    if where == "obj" and hasattr(obj, "save_typetree"):
        obj.save_typetree(tree); return
    if hasattr(data, "save_typetree"):
        data.save_typetree(tree); return
    raise AttributeError("no save_typetree on obj or data")

def try_get_name(obj):
    try:
        data = obj.read()
        for attr in ("name", "m_Name"):
            if hasattr(data, attr):
                nm = getattr(data, attr, None)
                if isinstance(nm, str) and nm:
                    return nm
    except Exception:
        pass
    try:
        tree, _, _ = read_tree_safe(obj)
        if isinstance(tree, dict):
            if "m_Name" in tree and isinstance(tree["m_Name"], str):
                return tree["m_Name"]
            if "Base" in tree and isinstance(tree["Base"], dict) and isinstance(tree["Base"].get("m_Name"), str):
                return tree["Base"]["m_Name"]
    except Exception:
        pass
    return None

def _parse_id_list(s: str):
    out = set()
    for tok in s.replace(",", " ").split():
        try:
            out.add(int(tok.strip()))
        except Exception:
            pass
    return out

def _parse_type_list(s: str):
    return set(t.strip() for t in s.replace(",", " ").split() if t.strip())

# ========== Name/Script pattern utilities ==========

def compile_name_patterns(raw_patterns: str, mode: str = "glob", digit_agnostic: bool = False):
    pats = [p.strip() for p in raw_patterns.replace(",", " ").split() if p.strip()]
    matchers = []
    if mode == "glob":
        for p in pats:
            if not digit_agnostic:
                def mker(glob_pat):
                    return lambda s: fnmatch.fnmatchcase(s or "", glob_pat)
                matchers.append((mker(p), p))
            else:
                regex = fnmatch.translate(p)
                regex = re.sub(r"([0-9]+)", r"\\d+", regex)
                try:
                    r = re.compile(regex)
                    matchers.append((lambda s, r=r: bool(r.match(s or "")), p))
                except Exception:
                    matchers.append((lambda s: False, p))
    else:
        for p in pats:
            pat = re.sub(r"([0-9]+)", r"\\d+", p) if digit_agnostic else p
            try:
                r = re.compile(pat)
                matchers.append((lambda s, r=r: bool(r.search(s or "")), p))
            except Exception:
                matchers.append((lambda s: False, p))
    return matchers

def name_is_excluded(name: str, matchers) -> bool:
    for mf, _ in matchers:
        try:
            if mf(name):
                return True
        except Exception:
            continue
    return False

def name_is_included(name: str, matchers) -> bool:
    if not matchers:
        return True
    for mf, _ in matchers:
        try:
            if mf(name):
                return True
        except Exception:
            continue
    return False

# ========== Script class name resolver ==========

def build_pid_index(env):
    pid_index = {}
    for o in env.objects:
        pid_index[o.path_id] = o
        pid_index[-o.path_id] = o
    return pid_index

def get_script_class_name(obj, env, pid_index=None):
    try:
        tree, _, _ = read_tree_safe(obj)
    except Exception:
        return None
    p = None
    if isinstance(tree, dict):
        p = tree.get("m_Script")
        if not isinstance(p, dict) and isinstance(tree.get("Base"), dict):
            p = tree["Base"].get("m_Script")
    if not isinstance(p, dict):
        return None
    spid = p.get("m_PathID") or p.get("pathID")
    if not isinstance(spid, int):
        return None
    if pid_index is None:
        pid_index = build_pid_index(env)
    sobj = pid_index.get(spid) or pid_index.get(-spid)
    if not sobj:
        return None
    try:
        stree, _, _ = read_tree_safe(sobj)
    except Exception:
        return None
    def _find_name(t):
        if not isinstance(t, dict):
            return None
        for key in ("m_ClassName", "className", "m_Name", "name"):
            v = t.get(key)
            if isinstance(v, str) and v:
                return v
        base = t.get("Base")
        if isinstance(base, dict):
            for key in ("m_ClassName", "className", "m_Name", "name"):
                v = base.get(key)
                if isinstance(v, str) and v:
                    return v
        return None
    return _find_name(stree)

# ========== pathID utilities ==========

def get_path_ids(bundle_path: Path, sample_limit: int = 0):
    env = UnityPy.load(str(bundle_path))
    ids = []
    for obj in env.objects:
        ids.append(obj.path_id)
        if sample_limit and len(ids) >= sample_limit:
            break
    return set(ids)

# ========== Object injection (for costume_transplant.py bundles) ==========
# costume_transplant.py grafts a costume by ADDING brand-new objects to the bundle
# (appendage jiggle bones as GameObject + Transform + SwingBone, and matcap/emissive
# Texture2Ds), each with a fresh random path_id that does not exist in the original
# bundle. The plain path_id-matched copy below only patches objects the target already
# has, so those donor-only objects are silently dropped and the grafted body's bone
# list / SwingBoneManager / material end up pointing at objects that aren't there.
# Re-creating the donor-only objects in the target (keeping their path_ids) makes every
# reference resolvable. For a normal iOS<->APK pair the two bundles share every path_id,
# so this pass finds nothing to inject and is a harmless no-op.

def _get_bundle_and_sf(env):
    """Return (BundleFile, SerializedFile) for a single-file bundle."""
    bf = list(env.files.values())[0]
    sub = getattr(bf, "files", None)
    if sub:
        for v in sub.values():
            if type(v).__name__ == "SerializedFile":
                return bf, v
    if type(bf).__name__ == "SerializedFile":
        return bf, bf
    raise RuntimeError("could not locate a SerializedFile in the bundle")

def _make_object(sf, template, new_pid, tree):
    """Append a brand-new object to a SerializedFile, reusing template's type info
    (so the recreated object's type is already registered in the target file)."""
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
    try:
        o.save_typetree(tree)
    except Exception:
        sf.objects.pop(new_pid, None)   # roll back a partial insert
        raise
    return o

# ========== Selective copy for a paired bundle ==========

def copy_selective_from_pair(
    donor_bundle: Path,
    target_bundle: Path,
    export_bundle: Path,
    include_ids: set,
    exclude_ids: set,
    include_types: set,
    exclude_types: set,
    name_include_matchers: list,
    name_exclude_matchers: list,
    script_class_ex_matchers: list,
    import_new_objects: bool = True,
):
    donor_env = UnityPy.load(str(donor_bundle))
    target_env = UnityPy.load(str(target_bundle))

    donor_map = {o.path_id: o for o in donor_env.objects}
    target_pid_index = build_pid_index(target_env)

    candidates = 0
    applied = 0
    skipped = 0
    injected = 0
    failed = []

    for t in target_env.objects:
        s = donor_map.get(t.path_id)
        if not s:
            continue

        tname_tgt = str(getattr(t, "type", ""))
        tname_src = str(getattr(s, "type", ""))

        if include_ids and t.path_id not in include_ids:
            skipped += 1; failed.append((t.path_id, tname_tgt, "SKIP_NOT_INCLUDED")); continue
        if t.path_id in exclude_ids:
            skipped += 1; failed.append((t.path_id, tname_tgt, "SKIP_EXCLUDED")); continue
        if include_types and tname_tgt not in include_types:
            skipped += 1; failed.append((t.path_id, tname_tgt, "SKIP_TYPE_NOT_INCLUDED")); continue
        if tname_tgt in exclude_types:
            skipped += 1; failed.append((t.path_id, tname_tgt, "SKIP_TYPE_EXCLUDED")); continue

        nm_tgt = try_get_name(t)
        if name_include_matchers and not name_is_included(nm_tgt or "", name_include_matchers):
            skipped += 1; failed.append((t.path_id, tname_tgt, f"SKIP_NAME_NOT_INCLUDED: {nm_tgt}")); continue
        if name_exclude_matchers and name_is_excluded(nm_tgt or "", name_exclude_matchers):
            skipped += 1; failed.append((t.path_id, tname_tgt, f"SKIP_NAME_EXCLUDED: {nm_tgt}")); continue

        is_mb = ("MonoBehaviour" in tname_tgt) or (getattr(getattr(t, "type", None), "value", None) == 114)
        if is_mb and script_class_ex_matchers:
            cls_name = get_script_class_name(t, target_env, pid_index=target_pid_index) or ""
            if name_is_excluded(cls_name, script_class_ex_matchers):
                skipped += 1; failed.append((t.path_id, tname_tgt, f"SKIP_SCRIPT_EXCLUDED: {cls_name}")); continue

        candidates += 1

        if tname_src != tname_tgt:
            failed.append((t.path_id, tname_tgt, f"TYPE_MISMATCH: src={tname_src} dst={tname_tgt}")); continue

        try:
            s_tree, _, _ = read_tree_safe(s)
        except Exception as e:
            failed.append((t.path_id, tname_tgt, f"READ_FAIL: {e}")); continue

        try:
            _, t_data, t_where = read_tree_safe(t)
            save_tree_safe(t, t_data, s_tree, t_where)
            applied += 1
        except Exception as e:
            failed.append((t.path_id, tname_tgt, f"SAVE_FAIL: {e}"))

    # ---- Injection pass: recreate donor-only objects (path_ids the target lacks) ----
    # Additive and platform-safe: a normal iOS<->APK pair shares every path_id, so this
    # is a no-op there; a costume_transplant.py donor carries injected appendage bones /
    # swing components / matcap textures that would otherwise be lost. It honors only the
    # explicit "keep this out" filters (exclude ids/types/names); the include_* and
    # script-class-exclude filters only narrow the overwrite set and never block an add.
    if import_new_objects:
        try:
            target_pids = {o.path_id for o in target_env.objects}
            tmpl_by_type = {}
            for o in target_env.objects:
                tmpl_by_type.setdefault(o.type.name, o)
            mb_tmpl_by_class = {}

            def _target_mb_template(cls_name):
                if cls_name in mb_tmpl_by_class:
                    return mb_tmpl_by_class[cls_name]
                found = None
                for o in target_env.objects:
                    if o.type.name != "MonoBehaviour":
                        continue
                    if (get_script_class_name(o, target_env, pid_index=target_pid_index) or "") == cls_name:
                        found = o; break
                mb_tmpl_by_class[cls_name] = found
                return found

            bf_t, sf_t = _get_bundle_and_sf(target_env)
            donor_pid_index = None
            for s in donor_env.objects:
                if s.path_id in target_pids:
                    continue
                type_name = s.type.name
                if s.path_id in exclude_ids:
                    failed.append((s.path_id, type_name, "INJECT_SKIP_EXCLUDED")); continue
                if type_name in exclude_types:
                    failed.append((s.path_id, type_name, "INJECT_SKIP_TYPE_EXCLUDED")); continue
                nm_src = try_get_name(s)
                if name_exclude_matchers and name_is_excluded(nm_src or "", name_exclude_matchers):
                    failed.append((s.path_id, type_name, f"INJECT_SKIP_NAME_EXCLUDED: {nm_src}")); continue

                if type_name == "MonoBehaviour":
                    if donor_pid_index is None:
                        donor_pid_index = build_pid_index(donor_env)
                    cls_name = get_script_class_name(s, donor_env, pid_index=donor_pid_index) or ""
                    template = _target_mb_template(cls_name) or tmpl_by_type.get("MonoBehaviour")
                else:
                    template = tmpl_by_type.get(type_name)
                if template is None:
                    failed.append((s.path_id, type_name, "INJECT_NO_TEMPLATE")); continue

                try:
                    s_tree, _, _ = read_tree_safe(s)
                except Exception as e:
                    failed.append((s.path_id, type_name, f"INJECT_READ_FAIL: {e}")); continue

                if type_name == "Texture2D":
                    # inline the pixels so the recreated texture is self-contained (its
                    # m_StreamData would otherwise point at a .resS that isn't carried over)
                    try:
                        img = s.read().get_image_data()
                        if img:
                            s_tree = copy.deepcopy(s_tree)
                            s_tree["image data"] = img
                            s_tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
                    except Exception:
                        pass

                try:
                    _make_object(sf_t, template, s.path_id, s_tree)
                    injected += 1
                except Exception as e:
                    failed.append((s.path_id, type_name, f"INJECT_FAIL: {e}"))

            if injected:
                try:
                    bf_t.mark_changed()
                except Exception:
                    pass
        except Exception as e:
            failed.append(("[INJECT]", "N/A", f"INJECT_PASS_FATAL: {e}"))

    try:
        export_bundle.parent.mkdir(parents=True, exist_ok=True)
        with open(export_bundle, "wb") as f:
            f.write(target_env.file.save(packer="lz4"))
    except Exception as e:
        failed.append(("[WRITE_BUNDLE]", "N/A", f"WRITE_FAIL: {e}"))

    return candidates, applied, skipped, injected, failed

# ========== Batch pairing by pathID intersection ==========

def build_target_index(target_dir: Path, exts=None, sample_limit=0):
    idx = {}
    for p in target_dir.rglob("*"):
        if not p.is_file():
            continue
        if exts and p.suffix.lower() not in exts:
            continue
        try:
            ids = get_path_ids(p, sample_limit=sample_limit)
            rel = str(p.relative_to(target_dir))
            idx[rel] = {"file": p, "ids": ids}
        except Exception:
            continue
    return idx

def pair_by_pid_intersection(donor_file: Path, target_dir: Path, tgt_index: dict, coverage_threshold: float = 0.8):
    try:
        d_ids = get_path_ids(donor_file, sample_limit=0)
    except Exception as e:
        return None, {"error": f"DONOR_INDEX_FAIL: {e}", "coverage": 0.0, "best": None}
    if not d_ids:
        return None, {"error": "DONOR_IDS_EMPTY", "coverage": 0.0, "best": None}

    best_rel = None
    best_cov = -1.0
    second_cov = -1.0

    for rel, rec in tgt_index.items():
        t_ids = rec["ids"]
        if not t_ids:
            continue
        inter = len(d_ids & t_ids)
        cov = inter / max(1, len(d_ids))
        if cov > best_cov:
            second_cov = best_cov
            best_cov = cov
            best_rel = rel
        elif cov > second_cov:
            second_cov = cov

    if best_rel is None:
        return None, {"error": "NO_CANDIDATE", "coverage": 0.0, "best": None}

    margin = 0.01
    if best_cov < coverage_threshold:
        return None, {"error": "LOW_COVERAGE", "coverage": best_cov, "best": best_rel}
    if second_cov >= best_cov - margin:
        return None, {"error": "AMBIGUOUS", "coverage": best_cov, "best": best_rel}

    return target_dir / best_rel, {"coverage": best_cov, "best": best_rel}

# ========== Batch runner ==========

def name_transform_for_output(donor_file: Path, export_root: Path, donor_root: Path, prefix: str, suffix: str):
    rel = donor_file.relative_to(donor_root)
    stem = donor_file.stem
    ext = donor_file.suffix
    new_name = f"{prefix}{stem}{suffix}{ext}"
    return (export_root / rel.parent / new_name)

def batch_by_pid(
    donor_dir: Path,
    target_dir: Path,
    export_dir: Path,
    include_ids: set,
    exclude_ids: set,
    include_types: set,
    exclude_types: set,
    name_include_matchers: list,
    name_exclude_matchers: list,
    script_class_ex_matchers: list,
    coverage_threshold: float = 0.8,
    exts=None,
    sample_limit_index: int = 0,
    out_prefix: str = "",
    out_suffix: str = "",
    import_new_objects: bool = True,
):
    tgt_index = build_target_index(target_dir, exts=exts, sample_limit=sample_limit_index)

    total_files = 0
    paired = 0
    total_candidates = 0
    total_applied = 0
    total_skipped = 0
    total_injected = 0
    failed_global = []

    for d in donor_dir.rglob("*"):
        if not d.is_file():
            continue
        if exts and d.suffix.lower() not in exts:
            continue

        total_files += 1

        t_path, diag = pair_by_pid_intersection(d, target_dir, tgt_index, coverage_threshold=coverage_threshold)
        if t_path is None:
            pair_log = export_dir / d.relative_to(donor_dir)
            pair_log = pair_log.with_suffix(pair_log.suffix + ".pair_log.txt")
            pair_log.parent.mkdir(parents=True, exist_ok=True)
            lines = []
            lines.append(f"[PAIR_FAIL] donor={d.name}")
            lines.append(f"PAIR_METHOD=PID error={diag.get('error')} coverage={diag.get('coverage')}")
            pair_log.write_text("\n".join(lines), encoding="utf-8")

            failed_global.append((str(d.relative_to(donor_dir)), "PAIR", "N/A", f"PAIR_FAIL: {diag.get('error')} ({diag.get('coverage')})"))
            continue

        out_path = name_transform_for_output(d, export_dir, donor_dir, out_prefix, out_suffix)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            cand, appl, skipd, injd, failed = copy_selective_from_pair(
                d, t_path, out_path,
                include_ids, exclude_ids, include_types, exclude_types,
                name_include_matchers,
                name_exclude_matchers,
                script_class_ex_matchers,
                import_new_objects=import_new_objects,
            )
            paired += 1
            total_candidates += cand
            total_applied += appl
            total_skipped += skipd
            total_injected += injd

            lines = []
            lines.append(f"[PAIR] donor={d.name} target={t_path.name}")
            lines.append(f"PAIR_METHOD=PID coverage={diag.get('coverage'):.4f} best={diag.get('best')}")
            lines.append(f"EXPORT_FILE={out_path.name}")
            lines.append(f"Candidates(after filters): {cand}")
            lines.append(f"Applied: {appl}")
            lines.append(f"Injected(new donor-only objects): {injd}")
            lines.append(f"Skipped(by filter): {skipd}")
            lines.append(f"Failed: {len(failed)}")
            for pid, typ, reason in failed:
                lines.append(f"- PID={pid} Type={typ} -> {reason}")
            (out_path.with_suffix(out_path.suffix + ".copy_log.txt")).write_text("\n".join(lines), encoding="utf-8")

            for it in failed:
                failed_global.append((str(d.relative_to(donor_dir)),) + it)
        except Exception:
            failed_global.append((str(d.relative_to(donor_dir)), "[PAIR_APPLY]", "N/A", "PAIR_APPLY_FATAL"))
            continue

    summary = []
    summary.append(f"Donor files scanned: {total_files}")
    summary.append(f"Paired(by PID): {paired}")
    summary.append(f"Candidates(after filters): {total_candidates}")
    summary.append(f"Applied: {total_applied}")
    summary.append(f"Injected(new donor-only objects): {total_injected}")
    summary.append(f"Skipped(by filter): {total_skipped}")
    summary.append(f"Failed entries: {len(failed_global)}")
    for rel, pid, typ, reason in failed_global:
        summary.append(f"- {rel} | PID={pid} Type={typ} -> {reason}")
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "_batch_summary.copy_log.txt").write_text("\n".join(summary), encoding="utf-8")

    return total_files, paired, total_candidates, total_applied, total_skipped, total_injected, failed_global

# ========== GUI ==========

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
    root.title("PID Pair Patch (Import Donor → Patch Target → Export Result)")
    root.geometry("1000x800")

    donor_dir_var = tk.StringVar()
    target_dir_var = tk.StringVar()
    export_dir_var = tk.StringVar()

    include_ids_var = tk.StringVar()
    exclude_ids_var = tk.StringVar()
    include_types_var = tk.StringVar()
    exclude_types_var = tk.StringVar()

    name_include_patterns_var = tk.StringVar(value="")
    name_exclude_patterns_var = tk.StringVar(value="ch*_co*_head, ch*_co*_head_rim, dropshadow, foot_shadow_Plane")
    name_mode_var = tk.StringVar(value="glob")
    digit_agnostic_var = tk.BooleanVar(value=True)

    script_patterns_var = tk.StringVar(value="SwingBone, SwingCollider")

    coverage_var = tk.StringVar(value="0.80")
    sample_limit_var = tk.StringVar(value="0")

    out_prefix_var = tk.StringVar(value="")
    out_suffix_var = tk.StringVar(value="ios")

    import_new_objects_var = tk.BooleanVar(value=True)

    def pick_dir(var, title):
        p = filedialog.askdirectory(title=title)
        if p: var.set(p)

    def do_run():
        try:
            if not donor_dir_var.get():
                messagebox.showerror("Error", "Please select Import From (Donor) folder"); return
            if not target_dir_var.get():
                messagebox.showerror("Error", "Please select Patch Target (Base) folder"); return
            if not export_dir_var.get():
                messagebox.showerror("Error", "Please specify Export Result folder"); return

            include_ids = _parse_id_list(include_ids_var.get())
            exclude_ids = _parse_id_list(exclude_ids_var.get())
            include_types = _parse_type_list(include_types_var.get())
            exclude_types = _parse_type_list(exclude_types_var.get())

            name_include_matchers = compile_name_patterns(
                name_include_patterns_var.get(), mode=name_mode_var.get(), digit_agnostic=digit_agnostic_var.get()
            )
            name_exclude_matchers = compile_name_patterns(
                name_exclude_patterns_var.get(), mode=name_mode_var.get(), digit_agnostic=digit_agnostic_var.get()
            )
            script_class_ex_matchers = compile_name_patterns(
                script_patterns_var.get(), mode=name_mode_var.get(), digit_agnostic=digit_agnostic_var.get()
            )

            try:
                coverage_threshold = float(coverage_var.get())
            except Exception:
                coverage_threshold = 0.8
            try:
                sample_limit_index = int(sample_limit_var.get())
            except Exception:
                sample_limit_index = 0

            files, paired, cand, appl, skipd, injd, failed = batch_by_pid(
                Path(donor_dir_var.get()),
                Path(target_dir_var.get()),
                Path(export_dir_var.get()),
                include_ids, exclude_ids, include_types, exclude_types,
                name_include_matchers,
                name_exclude_matchers,
                script_class_ex_matchers,
                coverage_threshold=coverage_threshold,
                exts=None,
                sample_limit_index=sample_limit_index,
                out_prefix=out_prefix_var.get(),
                out_suffix=out_suffix_var.get(),
                import_new_objects=import_new_objects_var.get(),
            )

            lines = []
            lines.append(f"[BATCH] Donor scanned={files} Paired={paired} Candidates={cand} Applied={appl} Injected={injd} Skipped={skipd} Failed={len(failed)}")
            show_log_window(root, "Batch Result", lines)

        except Exception:
            lines = ["FATAL_ERROR:", traceback.format_exc()]
            show_log_window(root, "Batch Result (fatal)", lines)

    frm = ttk.Frame(root)
    frm.pack(fill="both", expand=True, padx=12, pady=12)

    # Folders
    pf = ttk.LabelFrame(frm, text="Folders")
    pf.grid(row=0, column=0, columnspan=4, sticky="ew", pady=6)
    ttk.Label(pf, text="Import From (Donor) folder").grid(row=0, column=0, sticky="w")
    ttk.Entry(pf, textvariable=donor_dir_var, width=70).grid(row=0, column=1, padx=6)
    ttk.Button(pf, text="Browse", command=lambda: pick_dir(donor_dir_var, "Select Donor Folder")).grid(row=0, column=2)

    ttk.Label(pf, text="Patch Target (Base) folder").grid(row=1, column=0, sticky="w")
    ttk.Entry(pf, textvariable=target_dir_var, width=70).grid(row=1, column=1, padx=6)
    ttk.Button(pf, text="Browse", command=lambda: pick_dir(target_dir_var, "Select Target Folder")).grid(row=1, column=2)

    ttk.Label(pf, text="Export Result folder").grid(row=2, column=0, sticky="w")
    ttk.Entry(pf, textvariable=export_dir_var, width=70).grid(row=2, column=1, padx=6)
    ttk.Button(pf, text="Browse", command=lambda: pick_dir(export_dir_var, "Select Export Folder")).grid(row=2, column=2)

    # Pairing
    pr = ttk.LabelFrame(frm, text="Pairing (pathID intersection)")
    pr.grid(row=1, column=0, columnspan=4, sticky="ew", pady=6)
    ttk.Label(pr, text="Coverage threshold (0~1)").grid(row=0, column=0, sticky="w")
    ttk.Entry(pr, textvariable=coverage_var, width=10).grid(row=0, column=1, sticky="w")
    ttk.Label(pr, text="Index sample_limit (0=full)").grid(row=0, column=2, sticky="w")
    ttk.Entry(pr, textvariable=sample_limit_var, width=10).grid(row=0, column=3, sticky="w")
    ttk.Checkbutton(
        pr, variable=import_new_objects_var,
        text="Import donor-only objects (needed for costume_transplant.py bundles: "
             "appendage bones / swing physics / matcap textures)"
    ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

    # Naming
    nm = ttk.LabelFrame(frm, text="Output naming")
    nm.grid(row=2, column=0, columnspan=4, sticky="ew", pady=6)
    ttk.Label(nm, text="Prefix").grid(row=0, column=0, sticky="w")
    ttk.Entry(nm, textvariable=out_prefix_var, width=25).grid(row=0, column=1, sticky="w", padx=6)
    ttk.Label(nm, text="Suffix").grid(row=0, column=2, sticky="w")
    ttk.Entry(nm, textvariable=out_suffix_var, width=25).grid(row=0, column=3, sticky="w", padx=6)
    ttk.Label(nm, text="Result = prefix + donor.stem + suffix + donor.ext").grid(row=1, column=0, columnspan=4, sticky="w")

    # Filters
    ff = ttk.LabelFrame(frm, text="Filters (optional)")
    ff.grid(row=3, column=0, columnspan=4, sticky="ew", pady=6)
    ttk.Label(ff, text="Include pathIDs").grid(row=0, column=0, sticky="w")
    ttk.Entry(ff, textvariable=include_ids_var, width=70).grid(row=0, column=1, padx=6)
    ttk.Label(ff, text="Exclude pathIDs").grid(row=1, column=0, sticky="w")
    ttk.Entry(ff, textvariable=exclude_ids_var, width=70).grid(row=1, column=1, padx=6)
    ttk.Label(ff, text="Include types").grid(row=2, column=0, sticky="w")
    ttk.Entry(ff, textvariable=include_types_var, width=70).grid(row=2, column=1, padx=6)
    ttk.Label(ff, text="Exclude types").grid(row=3, column=0, sticky="w")
    ttk.Entry(ff, textvariable=exclude_types_var, width=70).grid(row=3, column=1, padx=6)

    # Name include/exclude
    ni = ttk.LabelFrame(frm, text="Name-based include (m_Name)")
    ni.grid(row=4, column=0, columnspan=4, sticky="ew", pady=6)
    ttk.Label(ni, text="Patterns").grid(row=0, column=0, sticky="w")
    ttk.Entry(ni, textvariable=name_include_patterns_var, width=70).grid(row=0, column=1, padx=6)
    ttk.Label(ni, text="Example: ch*_co*_body, *Skirt*_Dyna or ^ch\\d+_co\\d+_body$").grid(row=0, column=2, sticky="w")

    ne = ttk.LabelFrame(frm, text="Name-based exclude (m_Name)")
    ne.grid(row=5, column=0, columnspan=4, sticky="ew", pady=6)
    ttk.Label(ne, text="Patterns").grid(row=0, column=0, sticky="w")
    ttk.Entry(ne, textvariable=name_exclude_patterns_var, width=70).grid(row=0, column=1, padx=6)
    ttk.Label(ne, text="Example: ch*_co*_head, ch*_co*_head_rim or ^ch\\d+_co\\d+_head(?:_rim)?$").grid(row=0, column=2, sticky="w")

    # Script-class exclude
    sf = ttk.LabelFrame(frm, text="Script-class exclude (MonoBehaviour.m_Script)")
    sf.grid(row=6, column=0, columnspan=4, sticky="ew", pady=6)
    ttk.Label(sf, text="Patterns").grid(row=0, column=0, sticky="w")
    ttk.Entry(sf, textvariable=script_patterns_var, width=70).grid(row=0, column=1, padx=6)
    ttk.Label(sf, text="Example: SwingBone, SwingCollider, ^Swing.*$").grid(row=0, column=2, sticky="w")

    ttk.Separator(frm).grid(row=7, column=0, columnspan=4, sticky="ew", pady=8)
    ttk.Button(frm, text="Run (Import Donor → Patch Target → Export)", command=do_run).grid(row=8, column=0, columnspan=4, pady=8)

    for r in range(9):
        frm.rowconfigure(r, weight=0)
    frm.columnconfigure(1, weight=1)

    root.mainloop()

if __name__ == "__main__":
    run_gui()
