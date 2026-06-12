# unity_costumemod_packer.py (modified)

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import zipfile
import io
import re
import threading
import subprocess
import sys

# -------- Dependency helpers --------
def ensure_module(mod_name: str, pip_name: str):
    try:
        return __import__(mod_name)
    except ImportError:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
            return __import__(mod_name)
        except Exception:
            return None

def ensure_unitypy():
    return ensure_module("UnityPy", "UnityPy")

def ensure_pillow():
    return ensure_module("PIL", "Pillow")

PIL = ensure_pillow()
UnityPy = ensure_unitypy()

# -------- Texture extraction (body only, safe) --------
def extract_body_texture_with_unitypy(bundle_path: str):
    if UnityPy is None:
        return None, None
    try:
        env = UnityPy.load(bundle_path)
        body_pat = re.compile(r"^ch\d{4}_co\d{4}_body$")
        def is_crunched(fmt):
            return "Crunched" in str(fmt)
        for obj in env.objects:
            if getattr(obj.type, "name", "") != "Texture2D":
                continue
            data = obj.read()
            name = getattr(data, "name", getattr(data, "m_Name", ""))
            if not body_pat.match(name):
                continue
            fmt = getattr(data, "m_TextureFormat", None)
            if is_crunched(fmt):
                continue
            img = getattr(data, "image", None)
            if img:
                bio = io.BytesIO()
                img.save(bio, format="PNG")
                return name, bio.getvalue()
    except Exception:
        pass
    return None, None

def extract_chara_id_from_texture_name(tex_name: str):
    if not tex_name:
        return None
    m = re.search(r"ch(\d{4})_", tex_name)
    if m:
        return int(m.group(1))
    return None

def extract_chara_id_from_filename(filename: str):
    m = re.match(r"^(\d+)", filename)
    if m:
        try:
            return int(m.group(1))
        except:
            pass
    return None

# -------- Image helpers --------
def make_placeholder_thumbnail_png(text="No Preview", size=256):
    if PIL is None:
        return None
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    try:
        draw.text((size//2, size//2), text, fill=(128, 128, 128), anchor="mm")
    except Exception:
        pass
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True, compress_level=6)
    return out.getvalue()

def make_thumbnail_png(image_bytes: bytes, target_size: int = 256):
    if PIL is None:
        return None
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True, compress_level=6)
        return out.getvalue()
    except Exception:
        return None

# -------- Packaging helpers --------
def generate_modinstall_txt(display_name: str, costume_file_name_with_ext: str, thumbnail_name: str, chara_id: int, unmask_filename: str = None):
    lines = []
    lines.append(f'costume_name_en = "{display_name}"')
    lines.append(f'costume_name_ko = "{display_name}"')
    lines.append(f'costume_name_zh = "{display_name}"')
    lines.append(f'costume_name_ja = "{display_name}"')
    lines.append(f'costume_description = "{display_name}"')
    lines.append('')
    lines.append(f'costume_file = "{costume_file_name_with_ext}"')
    lines.append(f'thumbnail_file = "{thumbnail_name}"')
    lines.append(f'chara_id = {chara_id}')
    lines.append('')

    if chara_id == 209 and unmask_filename:
        lines.append(f'rina_unmask_costume_file = "{unmask_filename}"')
    else:
        lines.append('# uncomment rina_unmask_costume_file if you going add rina costume')
        lines.append('# rina_unmask_costume_file = "your_rina_unmasked_file"')

    return "\n".join(lines)

def create_zip_package(output_zip_path: str, masked_bundle_path: str, thumbnail_bytes: bytes, thumbnail_name: str, modinstall_txt: str, unmasked_bundle_path: str = None):
    os.makedirs(os.path.dirname(output_zip_path), exist_ok=True)
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # masked (main) file
        zf.write(masked_bundle_path, os.path.basename(masked_bundle_path))
        
        # unmasked (paired) file if it exists
        if unmasked_bundle_path and os.path.isfile(unmasked_bundle_path):
            zf.write(unmasked_bundle_path, os.path.basename(unmasked_bundle_path))
            
        # thumbnail and modinstall
        zf.writestr(thumbnail_name, thumbnail_bytes)
        zf.writestr("modinstall.txt", modinstall_txt.encode("utf-8"))
    return True

# -------- GUI App --------
class UnityAssetBundleModPackerAutoCharaID:
    
    def normalize_rina_key(self, filename: str):
        """'209rinamasked...' or '209rinaunmasked...' to 'rina...' for pairing."""
        s = re.sub(r"^\d+", "", filename, count=1)
        s = s.lower()
        if s.startswith("rinamasked"):
            return s.replace("rinamasked", "rina", 1)
        if s.startswith("rinaunmasked"):
            return s.replace("rinaunmasked", "rina", 1)
        return s

    def __init__(self, root):
        self.root = root
        self.root.title("Unity Asset Bundle Mod Packer")
        self.root.geometry("1000x800")
        
        self.bundle_files = []
        self.output_dir = tk.StringVar(value=os.getcwd())
        self.thumbnail_size = tk.IntVar(value=256)
        self.chara_id = tk.IntVar(value=209) # Default for Rina
        self.auto_chara_id = tk.BooleanVar(value=True)
        self.batch_mode = tk.BooleanVar(value=True) # Default to batch
        self.output_to_bundle_location = tk.BooleanVar(value=False)
        self.is_processing = False
        self.current_file_index = 0
        self.total_files = 0
        
        self.rina_unmasked_map = {}
        
        self.setup_ui()

    def setup_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=0, sticky="nsew")

        title = "Unity Asset Bundle Mod Packer (Rina Auto-Pair)"
        if UnityPy is None:
            title += " [UnityPy installation required]"
        ttk.Label(main, text=title, font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=4, pady=(0, 20))
        
        st = ttk.Frame(main); st.grid(row=1, column=0, columnspan=4, sticky="w", pady=5)
        ttk.Label(st, text=f"UnityPy: {'OK' if UnityPy else 'Missing'}", foreground="green" if UnityPy else "red").grid(row=0, column=0, sticky="w", padx=(0,10))
        ttk.Label(st, text=f"Pillow: {'OK' if PIL else 'Missing'}", foreground="green" if PIL else "red").grid(row=0, column=1, sticky="w", padx=(0,10))
        if (UnityPy is None) or (PIL is None):
            ttk.Button(st, text="Install required modules", command=self.install_requirements).grid(row=0, column=2, padx=10)

        mode = ttk.LabelFrame(main, text="Processing Mode", padding=10)
        mode.grid(row=2, column=0, columnspan=4, sticky="ew", pady=5)
        ttk.Radiobutton(mode, text="Single File Mode", variable=self.batch_mode, value=False, command=self.toggle_mode).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mode, text="Batch Mode (Multiple Files)", variable=self.batch_mode, value=True, command=self.toggle_mode).grid(row=0, column=1, sticky="w")
        
        self.file_frame = ttk.LabelFrame(main, text="File Selection", padding=10)
        self.file_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=10)
        self.single_frame = ttk.Frame(self.file_frame)
        self.single_frame.grid(row=0, column=0, columnspan=4, sticky="ew")
        self.bundle_path = tk.StringVar()
        ttk.Label(self.single_frame, text="Asset Bundle File:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.single_frame, textvariable=self.bundle_path, width=60).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(self.single_frame, text="Browse", command=self.browse_single_bundle).grid(row=0, column=2, padx=5)
        self.batch_frame = ttk.Frame(self.file_frame)
        bbtn = ttk.Frame(self.batch_frame); bbtn.grid(row=0, column=0, columnspan=4, sticky="ew", pady=5)
        ttk.Button(bbtn, text="📁 Add Files", command=self.add_batch_files).grid(row=0, column=0, padx=5)
        ttk.Button(bbtn, text="📂 Add Folder", command=self.add_batch_folder).grid(row=0, column=1, padx=5)
        ttk.Button(bbtn, text="🗑️ Clear All", command=self.clear_batch_files).grid(row=0, column=2, padx=5)
        lst = ttk.Frame(self.batch_frame); lst.grid(row=1, column=0, columnspan=4, sticky="nsew")
        self.file_listbox = tk.Listbox(lst, height=8, selectmode=tk.EXTENDED)
        ysb = ttk.Scrollbar(lst, orient="vertical", command=self.file_listbox.yview)
        self.file_listbox.configure(yscrollcommand=ysb.set)
        self.file_listbox.grid(row=0, column=0, sticky="nsew"); ysb.grid(row=0, column=1, sticky="ns")
        lst.columnconfigure(0, weight=1); lst.rowconfigure(0, weight=1)
        ttk.Button(self.batch_frame, text="Remove Selected", command=self.remove_selected_files).grid(row=2, column=0, pady=5, sticky="w")
        
        out = ttk.LabelFrame(main, text="Output Settings", padding=10)
        out.grid(row=4, column=0, columnspan=4, sticky="ew", pady=10)
        ttk.Checkbutton(out, text="Output to location where target Bundle exists", variable=self.output_to_bundle_location, command=self.toggle_output_location_mode).grid(row=0, column=0, columnspan=3, sticky="w", pady=5)
        self.manual_output_frame = ttk.Frame(out); self.manual_output_frame.grid(row=1, column=0, columnspan=4, sticky="ew")
        ttk.Label(self.manual_output_frame, text="Output Directory:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.manual_output_frame, textvariable=self.output_dir, width=60).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(self.manual_output_frame, text="Browse", command=self.browse_output).grid(row=0, column=2, padx=5)
        
        settings = ttk.LabelFrame(main, text="Settings", padding=10)
        settings.grid(row=5, column=0, columnspan=4, sticky="ew", pady=10)
        ttk.Label(settings, text="Thumbnail Size:").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(settings, from_=64, to=512, textvariable=self.thumbnail_size, width=10).grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(settings, text="px").grid(row=0, column=2, sticky="w")
        cidf = ttk.Frame(settings); cidf.grid(row=1, column=0, columnspan=4, sticky="w", pady=5)
        ttk.Checkbutton(cidf, text="Auto-detect Character ID (texture/filename)", variable=self.auto_chara_id, command=self.toggle_chara_id_mode).grid(row=0, column=0, sticky="w")
        self.manual_chara_frame = ttk.Frame(cidf); self.manual_chara_frame.grid(row=1, column=0, sticky="w", pady=5)
        ttk.Label(self.manual_chara_frame, text="Manual Character ID:").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(self.manual_chara_frame, from_=1, to=999, textvariable=self.chara_id, width=10).grid(row=0, column=1, sticky="w", padx=5)
        
        ptxt = "🚀 Create Mod Package(s)" if UnityPy and PIL else "🚀 Create Mod Package(s) (UnityPy/Pillow required)"
        self.process_btn = ttk.Button(main, text=ptxt, command=self.start_processing, state=("normal" if (UnityPy and PIL) else "disabled"))
        self.process_btn.grid(row=6, column=0, columnspan=4, pady=20)

        prog = ttk.LabelFrame(main, text="Progress", padding=10); prog.grid(row=7, column=0, columnspan=4, sticky="ew", pady=5)
        ttk.Label(prog, text="Overall Progress:").grid(row=0, column=0, sticky="w")
        self.overall_progress = ttk.Progressbar(prog, mode="determinate"); self.overall_progress.grid(row=0, column=1, sticky="ew", padx=5)
        self.overall_label = ttk.Label(prog, text="0 / 0 files"); self.overall_label.grid(row=0, column=2, sticky="w", padx=5)
        ttk.Label(prog, text="Current File:").grid(row=1, column=0, sticky="w", pady=(5,0))
        self.current_progress = ttk.Progressbar(prog, mode="determinate"); self.current_progress.grid(row=1, column=1, sticky="ew", padx=5, pady=(5,0))
        self.current_label = ttk.Label(prog, text="Ready"); self.current_label.grid(row=1, column=2, sticky="w", padx=5, pady=(5,0))

        logf = ttk.LabelFrame(main, text="Processing Log", padding=5); logf.grid(row=8, column=0, columnspan=4, sticky="nsew", pady=10)
        tf = ttk.Frame(logf); tf.grid(row=0, column=0, sticky="nsew")
        self.log_text = tk.Text(tf, height=12, width=90, wrap="word")
        ysb2 = ttk.Scrollbar(tf, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=ysb2.set)
        self.log_text.grid(row=0, column=0, sticky="nsew"); ysb2.grid(row=0, column=1, sticky="ns")
        
        self.root.columnconfigure(0, weight=1); self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1); main.rowconfigure(8, weight=1)
        logf.columnconfigure(0, weight=1); logf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1); tf.rowconfigure(0, weight=1)
        self.file_frame.columnconfigure(1, weight=1)
        self.single_frame.columnconfigure(1, weight=1)
        self.batch_frame.columnconfigure(0, weight=1)
        
        self.toggle_mode()
        self.toggle_chara_id_mode()
        self.toggle_output_location_mode()

    def install_requirements(self):
        self.log("🔄 Installing UnityPy/Pillow...")
        global UnityPy, PIL
        if UnityPy is None: UnityPy = ensure_unitypy()
        if PIL is None: PIL = ensure_pillow()
        if UnityPy and PIL:
            self.log("✅ Installation complete! Enabling buttons")
            self.process_btn.configure(state="normal", text="🚀 Create Mod Package(s)")
        else:
            self.log("❌ Installation failed or some modules missing")

    def toggle_output_location_mode(self):
        state = "disabled" if self.output_to_bundle_location.get() else "normal"
        for child in self.manual_output_frame.winfo_children():
            child.configure(state=state)
        self.log(f"📍 Output location: {'location where each Bundle file exists' if self.output_to_bundle_location.get() else self.output_dir.get()}")

    def toggle_mode(self):
        is_batch = self.batch_mode.get()
        self.single_frame.grid_remove() if is_batch else self.single_frame.grid()
        self.batch_frame.grid() if is_batch else self.batch_frame.grid_remove()
        self.file_frame.config(text="Batch File Selection" if is_batch else "Single File Selection")
        self.process_btn.config(text=f"🚀 Create Mod Package{'s' if is_batch else ''}")

    def toggle_chara_id_mode(self):
        state = "disabled" if self.auto_chara_id.get() else "normal"
        for child in self.manual_chara_frame.winfo_children():
            child.configure(state=state)

    def browse_single_bundle(self):
        fn = filedialog.askopenfilename(title="Select Asset Bundle File", filetypes=[("All files", "*.*")])
        if fn: self.bundle_path.set(fn); self.log(f"Selected: {os.path.basename(fn)}")

    def add_batch_files(self):
        fns = filedialog.askopenfilenames(title="Select Asset Bundle Files", filetypes=[("All files", "*.*")])
        count = 0
        for fn in fns:
            if fn not in self.bundle_files:
                self.bundle_files.append(fn); self.file_listbox.insert(tk.END, os.path.basename(fn)); count += 1
        self.log(f"Added {count} files. Total: {len(self.bundle_files)}")

    def add_batch_folder(self):
        folder = filedialog.askdirectory(title="Select Folder")
        if not folder: return
        added = 0
        for root, _, files in os.walk(folder):
            for f in files:
                p = os.path.join(root, f)
                if p not in self.bundle_files:
                    self.bundle_files.append(p)
                    self.file_listbox.insert(tk.END, os.path.relpath(p, folder)); added += 1
        self.log(f"Added {added} files from folder. Total: {len(self.bundle_files)}")

    def clear_batch_files(self):
        self.bundle_files.clear(); self.file_listbox.delete(0, tk.END); self.log("Cleared batch list.")

    def remove_selected_files(self):
        sel = self.file_listbox.curselection()
        if not sel: return
        for i in reversed(sel):
            del self.bundle_files[i]; self.file_listbox.delete(i)
        self.log(f"Removed {len(sel)} files.")
        
    def browse_output(self):
        d = filedialog.askdirectory(title="Select Output Directory")
        if d: self.output_dir.set(d); self.log(f"Output directory set to: {d}")

    def log(self, msg):
        self.log_text.insert(tk.END, f"{msg}\n"); self.log_text.see(tk.END); self.root.update_idletasks()

    def update_current_status(self, msg):
        self.current_label.config(text=msg); self.root.update_idletasks()

    def update_overall_progress(self, current, total):
        val = (current / total) * 100 if total > 0 else 0
        self.overall_progress["value"] = val
        self.overall_label.config(text=f"{current} / {total}")
        self.root.update_idletasks()

    def update_current_progress(self, val):
        self.current_progress["value"] = val; self.root.update_idletasks()

    def start_processing(self):
        if self.is_processing: return
        if self.batch_mode.get():
            if not self.bundle_files: messagebox.showerror("Error", "Please add files."); return
            files = list(self.bundle_files)
        else:
            if not self.bundle_path.get() or not os.path.exists(self.bundle_path.get()):
                messagebox.showerror("Error", "Please select valid files."); return
            files = [self.bundle_path.get()]

        self.is_processing = True
        self.process_btn.config(state="disabled", text="🔄 Processing...")
        threading.Thread(target=self.process_files, args=(files,), daemon=True).start()

    def process_files(self, files):
        self.total_files = len(files)
        self.current_file_index = 0
        self.log("="*70 + f"\n🚀 Starting processing for {self.total_files} file(s).")
        
        # Pre-scan for Rina unmasked files
        self.rina_unmasked_map.clear()
        self.log("🔎 Pre-scanning for '209rinaunmasked' helper files...")
        unmasked_files = []
        masked_files_to_process = []
        
        for p in files:
            bn_no_ext = os.path.splitext(os.path.basename(p))[0].lower()
            if bn_no_ext.startswith("209rinaunmasked"):
                key = self.normalize_rina_key(bn_no_ext)
                self.rina_unmasked_map[key] = p
                unmasked_files.append(os.path.basename(p))
            else:
                 masked_files_to_process.append(p)

        if self.rina_unmasked_map:
            self.log(f"✅ Found {len(self.rina_unmasked_map)} unmasked files: {', '.join(unmasked_files)}")
        else:
            self.log("🟡 No '209rinaunmasked' files found.")

        success, fail, skip = 0, 0, 0
        
        # Process only non-unmasked files
        self.total_files = len(masked_files_to_process)
        self.update_overall_progress(0, self.total_files)

        for i, bundle_path in enumerate(masked_files_to_process):
            self.current_file_index = i + 1
            bn = os.path.basename(bundle_path)
            self.log(f"\n📦 Processing {self.current_file_index}/{self.total_files}: {bn}")
            self.update_overall_progress(self.current_file_index - 1, self.total_files)
            self.update_current_status(f"Processing: {bn}")
            
            try:
                result = self.process_single_file(bundle_path)
                if result: success += 1; self.log(f"✅ Success: {bn}")
                else: fail += 1; self.log(f"❌ Failed: {bn}")
            except Exception as e:
                fail += 1
                self.log(f"❌ CRITICAL ERROR processing {bn}: {e}")
        
        self.update_current_progress(0)
        self.update_overall_progress(self.total_files, self.total_files)
        self.update_current_status("Complete!")
        self.log("\n" + "="*70 + "\n🎉 PROCESSING COMPLETED!")
        self.log(f"✅ Successful: {success}, ❌ Failed: {fail}")
        
        self.root.after(0, lambda: self.show_completion_dialog(success, fail))
        self.is_processing = False
        self.root.after(0, lambda: self.process_btn.config(state="normal", text="🚀 Create Mod Package(s)"))

    def process_single_file(self, bundle_path: str):
        bn_with_ext = os.path.basename(bundle_path)
        bn_no_ext = os.path.splitext(bn_with_ext)[0]

        self.update_current_progress(20); self.update_current_status("Extracting texture...")
        tex_name, tex_png_bytes = extract_body_texture_with_unitypy(bundle_path)

        self.update_current_progress(40); self.update_current_status("Detecting chara ID...")
        cid = 0
        if self.auto_chara_id.get():
            cid_from_tex = extract_chara_id_from_texture_name(tex_name)
            cid_from_file = extract_chara_id_from_filename(bn_no_ext)
            cid = cid_from_tex or cid_from_file or self.chara_id.get()
            source = "texture" if cid_from_tex else "filename" if cid_from_file else "manual"
            self.log(f"🎯 Chara ID: {cid} (from {source})")
        else:
            cid = self.chara_id.get()
            self.log(f"👤 Manual Chara ID: {cid}")
        
        # Force chara_id to 209 if filename indicates a Rina pair
        if bn_no_ext.lower().startswith("209rinamasked"):
            if cid != 209:
                self.log(f"⚠️ Overriding chara_id to 209 for Rina file '{bn_with_ext}'")
                cid = 209

        self.update_current_progress(60); self.update_current_status("Creating thumbnail...")
        thumb_bytes = make_thumbnail_png(tex_png_bytes, self.thumbnail_size.get()) if tex_png_bytes else make_placeholder_thumbnail_png("No Body Texture", self.thumbnail_size.get())
        if not thumb_bytes: self.log("❌ Thumbnail creation failed."); return False
        thumb_name = f"im{bn_no_ext}.png"
        
        unmasked_bundle_path = None
        unmasked_filename = None
        
        if cid == 209 and bn_no_ext.lower().startswith("209rinamasked"):
            key = self.normalize_rina_key(bn_no_ext.lower())
            if key in self.rina_unmasked_map:
                unmasked_bundle_path = self.rina_unmasked_map[key]
                unmasked_filename = os.path.basename(unmasked_bundle_path)
                self.log(f"🎭 Paired '{bn_with_ext}' with '{unmasked_filename}'")
            else:
                self.log(f"⚠️ Could not find a matching 'unmasked' file for key: '{key}'")
        
        self.update_current_progress(80); self.update_current_status("Creating modinstall.txt...")
        modinstall = generate_modinstall_txt(bn_no_ext, bn_with_ext, thumb_name, cid, unmasked_filename)
        
        out_dir = os.path.dirname(os.path.abspath(bundle_path)) if self.output_to_bundle_location.get() else self.output_dir.get()
        out_zip = os.path.join(out_dir, f"{bn_no_ext}.zip")
        
        self.update_current_status("Creating ZIP package...")
        ok = create_zip_package(out_zip, bundle_path, thumb_bytes, thumb_name, modinstall, unmasked_bundle_path)
        
        if ok: self.update_current_progress(100)
        return ok

    def show_completion_dialog(self, succ, fail):
        if self.output_to_bundle_location.get():
            folder = os.path.dirname(os.path.abspath(self.bundle_files[0])) if self.bundle_files else os.getcwd()
            loc_txt = f"Saved to each Bundle file location."
        else:
            folder = self.output_dir.get()
            loc_txt = f"Output location: {folder}"
        
        msg = f"Processing completed:\n✅ Successful: {succ}\n❌ Failed: {fail}\n\n{loc_txt}\n\nOpen output folder?"
        icon = "info" if fail == 0 else "warning"
        
        if messagebox.askyesno("Processing Complete", msg, icon=icon):
            try:
                if os.name == 'nt': os.startfile(folder)
                elif sys.platform == "darwin": subprocess.Popen(["open", folder])
                else: subprocess.Popen(["xdg-open", folder])
            except Exception: pass

def main():
    root = tk.Tk()
    app = UnityAssetBundleModPackerAutoCharaID(root)
    root.mainloop()

if __name__ == "__main__":
    main()
