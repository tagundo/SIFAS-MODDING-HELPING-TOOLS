# pip install UnityPy
import re, traceback
from pathlib import Path
import UnityPy
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

RE_LAST_ID = re.compile(r"(-{1,2})(\d+)\.(?:txt|json)$", re.I)
RE_INDEX   = re.compile(r"\bint\s+index\s*(?:=\s*|\s+)(\d+)")
RE_WEIGHT  = re.compile(r"\bfloat\s+weight\s*(?:=\s*|\s+)([0-9]*\.?[0-9]+)")

def parse_pid_candidates(fname: str):
    m = RE_LAST_ID.search(fname)
    if not m:
        raise ValueError(f"PID not found in: {fname}")
    hy, dg = m.groups()
    pid = int(dg)
    return [pid, -pid]

def parse_clip_txt(p: Path):
    t = p.read_text(encoding="utf-8", errors="ignore")
    m1 = RE_INDEX.search(t); m2 = RE_WEIGHT.search(t)
    idx = int(m1.group(1)) if m1 else None
    w   = float(m2.group(1)) if m2 else None
    return idx, w

def show_log(root, title, lines):
    win = tk.Toplevel(root); win.title(title); win.geometry("1100x700")
    frm = ttk.Frame(win); frm.pack(fill="both", expand=True, padx=8, pady=8)
    txt = tk.Text(frm, wrap="none")
    xsb = ttk.Scrollbar(frm, orient="horizontal", command=txt.xview)
    ysb = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
    txt.configure(xscrollcommand=xsb.set, yscrollcommand=ysb.set)
    txt.grid(row=0, column=0, sticky="nsew"); ysb.grid(row=0, column=1, sticky="ns"); xsb.grid(row=1, column=0, sticky="ew")
    frm.rowconfigure(0, weight=1); frm.columnconfigure(0, weight=1)
    txt.insert("end", "\n".join(lines)); txt.configure(state="disabled")

def read_tree_safe(obj):
    data = obj.read()
    # 1) obj.read_typetree() 우선
    if hasattr(obj, "read_typetree"):
        try:
            tree = obj.read_typetree()
            return tree, data, "obj"
        except Exception:
            pass
    # 2) data.read_typetree() 폴백
    if hasattr(data, "read_typetree"):
        tree = data.read_typetree()
        return tree, data, "data"
    # 3) 모두 불가
    raise AttributeError("typetree unavailable on both obj and data")

def save_tree_safe(obj, data, tree, where):
    # obj 우선 저장
    if where == "obj" and hasattr(obj, "save_typetree"):
        obj.save_typetree(tree); return
    # data 폴백 저장
    if hasattr(data, "save_typetree"):
        data.save_typetree(tree); return
    # 최종 실패
    raise AttributeError("no save_typetree on obj or data")

def import_txts_into_bundle(bundle_in: Path, dumps_dir: Path, bundle_out: Path):
    env = UnityPy.load(str(bundle_in))
    # 동일 path_id 중복 대비: pid -> [objs]
    pid_map = {}
    for obj in env.objects:
        if obj.type.name == "MonoBehaviour":
            pid_map.setdefault(obj.path_id, []).append(obj)

    dump_files = sorted([p for p in dumps_dir.rglob("*") if p.suffix.lower() in (".txt",".json")])
    updated = 0; queued = len(dump_files); failed = []; ok_logs = []

    for fp in dump_files:
        try:
            idx, w = parse_clip_txt(fp)
        except Exception as e:
            failed.append((fp.name, None, f"PARSE_FAIL: {e}")); continue

        try:
            candidates = parse_pid_candidates(fp.name)
        except Exception as e:
            failed.append((fp.name, None, f"PID_PARSE_FAIL: {e}")); continue

        targets = []
        for pid in candidates:
            if pid in pid_map:
                targets.extend(pid_map[pid])

        if not targets:
            failed.append((fp.name, candidates[-1], "PID_NOT_FOUND in selected bundle")); continue

        any_applied = False
        for tobj in targets:
            try:
                tree, data, origin = read_tree_safe(tobj)
            except Exception as e:
                failed.append((fp.name, tobj.path_id, f"TYPETREE_FAIL: {e}")); continue

            has_field = False
            if idx is not None and "index" in tree:
                tree["index"] = int(idx); has_field = True
            if w is not None and "weight" in tree:
                tree["weight"] = float(w); has_field = True
            if not has_field:
                failed.append((fp.name, tobj.path_id, "NO_FIELDS: index/weight not found")); continue

            try:
                save_tree_safe(tobj, data, tree, origin)
                any_applied = True
            except Exception as e:
                failed.append((fp.name, tobj.path_id, f"SAVE_FAIL: {e}")); continue

        if any_applied:
            updated += 1
            ok_logs.append(f"[OK] {fp.name} → PIDs tried={candidates}, applied_count={len(targets)}")

    # 번들 저장
    try:
        with open(bundle_out, "wb") as f:
            f.write(env.file.save(packer="lz4"))
    except Exception as e:
        failed.append(("[WRITE_BUNDLE]", None, f"WRITE_FAIL: {e}"))

    return updated, queued, failed, ok_logs

def run_gui():
    root = tk.Tk()
    root.title("UnityPy LipsClip Importer")
    root.geometry("420x220")

    def run_flow():
        try:
            messagebox.showinfo("Step 1", "원본 assetbundle 선택")
            bundle_in = filedialog.askopenfilename(title="Select AssetBundle", filetypes=[("All files","*.*")])
            if not bundle_in: messagebox.showerror("오류","번들을 선택하세요"); return
            messagebox.showinfo("Step 2", "편집된 txt 폴더 선택")
            dumps_dir = filedialog.askdirectory(title="Select dumps folder")
            if not dumps_dir: messagebox.showerror("오류","덤프 폴더를 선택하세요"); return
            messagebox.showinfo("Step 3", "출력 번들 경로 지정")
            bundle_out = filedialog.asksaveasfilename(title="Save As", defaultextension=".ab", filetypes=[("All files","*.*")])
            if not bundle_out: messagebox.showerror("오류","출력 경로를 지정하세요"); return

            updated, queued, failed, ok_logs = import_txts_into_bundle(Path(bundle_in), Path(dumps_dir), Path(bundle_out))

            lines = []
            lines.append(f"Queued dumps: {queued}")
            lines.append(f"Updated objs: {updated}")
            lines += ok_logs
            lines.append(f"Failed: {len(failed)}")
            for name, pid, reason in failed:
                lines.append(f"- {name} (PID={pid}): {reason}")

            # 파일 로그 저장
            log_path = Path(bundle_out).with_suffix(".import_log.txt")
            log_path.write_text("\n".join(lines), encoding="utf-8")

            show_log(root, "Import Result", lines)
        except Exception:
            lines = ["FATAL_ERROR:", traceback.format_exc()]
            show_log(root, "Import Result (fatal)", lines)

    ttk.Button(root, text="Run Import", command=run_flow).pack(expand=True, padx=20, pady=20)
    root.mainloop()

if __name__ == "__main__":
    run_gui()
