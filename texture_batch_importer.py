
# unitypy_batch_texture_importer_v2.py
# Requirements: pip install UnityPy Pillow
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image

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

SUPPORTED_IMG_EXTS = [".png", ".jpg", ".jpeg", ".bmp", ".tga"]
SUPPORTED_BUNDLE_EXTS = [".bundle", ".unity3d", ".ab", ".assets", ""]

def find_image_by_name(img_root, name):
    for ext in SUPPORTED_IMG_EXTS:
        p = os.path.join(img_root, name + ext)
        if os.path.exists(p):
            return p
    return None

def safe_make_dir(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)

def process_single_bundle(bundle_path, img_folder, out_path, selected_format_name, status_cb=None):
    env = UnityPy.load(bundle_path)
    imported_count = 0

    for obj in env.objects:
        if obj.type.name == "Texture2D":
            data = obj.read()
            tex_name = data.m_Name
            img_path = find_image_by_name(img_folder, tex_name)
            if img_path:
                pil = Image.open(img_path)
                # Apply selected format (except Keep Original)
                if selected_format_name and selected_format_name != "Keep Original":
                    fmt = getattr(TextureFormat, selected_format_name, None)
                    if fmt is not None:
                        data.m_TextureFormat = fmt
                # Replace image and save
                data.image = pil
                data.save()
                imported_count += 1
                if status_cb:
                    status_cb(f"Importing {os.path.basename(bundle_path)} :: {tex_name}")

    # save bundle
    safe_make_dir(out_path)
    with open(out_path, "wb") as f:
        f.write(env.file.save())

    return imported_count

def iter_bundle_files(input_root, recursive):
    if os.path.isfile(input_root):
        yield input_root
        return
    if recursive:
        for root, _, files in os.walk(input_root):
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext in SUPPORTED_BUNDLE_EXTS or ext == "":
                    yield os.path.join(root, fn)
    else:
        for fn in os.listdir(input_root):
            fp = os.path.join(input_root, fn)
            if os.path.isfile(fp):
                ext = os.path.splitext(fn)[1].lower()
                if ext in SUPPORTED_BUNDLE_EXTS or ext == "":
                    yield fp

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("UnityPy Texture Importer (Single/Batch)")
        self.root.geometry("1000x700")

        self.mode = tk.StringVar(value="single")

        # Single
        self.single_bundle = tk.StringVar()
        self.single_images = tk.StringVar()
        self.single_output = tk.StringVar()

        # Batch
        self.batch_bundles = []  # store multiple bundle files
        self.batch_images = tk.StringVar()
        self.batch_output = tk.StringVar()
        self.batch_recursive = tk.BooleanVar(value=True)
        self.batch_preserve_tree = tk.BooleanVar(value=False)
        self.batch_out_suffix = tk.StringVar(value="")

        # Common
        self.texture_format = tk.StringVar(value="Keep Original")

        self._build_ui()

    def _build_ui(self):
        # Common top frame (Texture Format)
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(top, text="Texture Format:").pack(side="left")
        formats = [
            "Keep Original",
            "RGB24", "RGBA32", "ARGB32", "RGB565", "RGBA4444", "Alpha8",
            "DXT1", "DXT5",
            "BC4", "BC5", "BC6H", "BC7",
            "ETC_RGB4", "ETC2_RGB", "ETC2_RGBA1", "ETC2_RGBA8",
            "EAC_R", "EAC_RG",
            "ASTC_4x4", "ASTC_5x5", "ASTC_6x6", "ASTC_8x8", "ASTC_10x10", "ASTC_12x12",
            "RHalf", "RGHalf", "RGBAHalf",
            "RFloat", "RGFloat", "RGBAFloat"
        ]
        ttk.Combobox(top, textvariable=self.texture_format, values=formats, state="readonly", width=18)            .pack(side="left", padx=6)

        # Notebook
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        # ==================== Single Tab ====================
        single = ttk.Frame(nb)
        nb.add(single, text="Single")

        self._add_file_row(single, "Bundle File:", self.single_bundle, self._browse_single_file)
        self._add_file_row(single, "Image Folder:", self.single_images, self._browse_folder)
        self._add_file_row(single, "Output Bundle:", self.single_output, self._browse_save_file)

        ttk.Button(single, text="Load Textures (Preview)", command=self._preview_single, width=24)            .pack(pady=8)

        list_frame = ttk.Frame(single)
        list_frame.pack(fill="both", expand=True, padx=4, pady=4)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.single_list = tk.Listbox(list_frame, height=14, yscrollcommand=scrollbar.set)
        self.single_list.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.config(command=self.single_list.yview)

        ttk.Button(single, text="Import (Single)", command=self._run_single, width=20)            .pack(pady=8)

        # ==================== Batch Tab ====================
        batch = ttk.Frame(nb)
        nb.add(batch, text="Batch")

        # bundle file/folder selection area
        bundle_section = ttk.LabelFrame(batch, text="Bundle Selection", padding=10)
        bundle_section.pack(fill="both", expand=True, padx=6, pady=6)

        btn_frame = ttk.Frame(bundle_section)
        btn_frame.pack(fill="x", pady=(0, 6))

        ttk.Button(btn_frame, text="Add Bundle Files", command=self._add_bundle_files, width=18)            .pack(side="left", padx=3)
        ttk.Button(btn_frame, text="Add Folder", command=self._add_bundle_folder, width=18)            .pack(side="left", padx=3)
        ttk.Button(btn_frame, text="Clear All", command=self._clear_bundles, width=15)            .pack(side="left", padx=3)

        # bundle list
        list_frame2 = ttk.Frame(bundle_section)
        list_frame2.pack(fill="both", expand=True)

        scrollbar2 = ttk.Scrollbar(list_frame2)
        scrollbar2.pack(side=tk.RIGHT, fill=tk.Y)

        self.batch_list = tk.Listbox(list_frame2, height=12, yscrollcommand=scrollbar2.set)
        self.batch_list.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar2.config(command=self.batch_list.yview)

        # image folder and output folder
        self._add_file_row(batch, "Image Root:", self.batch_images, self._browse_folder)
        self._add_file_row(batch, "Output Folder:", self.batch_output, self._browse_folder)

        # options
        opt = ttk.Frame(batch)
        opt.pack(fill="x", padx=6, pady=4)
        ttk.Checkbutton(opt, text="Recursive (folder scan)", variable=self.batch_recursive).pack(side="left", padx=8)
        ttk.Checkbutton(opt, text="Preserve input tree", variable=self.batch_preserve_tree).pack(side="left", padx=8)
        ttk.Label(opt, text="Output suffix:").pack(side="left", padx=8)
        ttk.Entry(opt, textvariable=self.batch_out_suffix, width=12).pack(side="left")

        ttk.Button(batch, text="Import (Batch)", command=self._run_batch, width=20)            .pack(pady=8)

        # Status bar
        self.status = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor="w")
        self.status.pack(fill="x", padx=10, pady=(0, 8))

    def _add_file_row(self, parent, label, var, browse_fn):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text=label, width=18).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Browse", command=lambda: browse_fn(var)).pack(side="left")

    # ==================== Browse Functions ====================
    def _browse_single_file(self, var):
        fp = filedialog.askopenfilename(
            title="Select Bundle File",
            filetypes=[("All Files", "*.*"), ("Bundle", "*.bundle"), ("Unity3D", "*.unity3d")]
        )
        if fp:
            var.set(fp)

    def _browse_folder(self, var):
        d = filedialog.askdirectory(title="Select Folder")
        if d:
            var.set(d)

    def _browse_save_file(self, var):
        fp = filedialog.asksaveasfilename(
            title="Save Output Bundle",
            defaultextension=".*",
            filetypes=[("All Files", "*.*")]
        )
        if fp:
            var.set(fp)

    def _add_bundle_files(self):
        """Select multiple bundle files at once"""
        files = filedialog.askopenfilenames(
            title="Select Bundle Files (Multiple)",
            filetypes=[("All Files", "*.*"), ("Bundle", "*.bundle"), ("Unity3D", "*.unity3d")]
        )
        if files:
            for f in files:
                if f not in self.batch_bundles:
                    self.batch_bundles.append(f)
                    self.batch_list.insert(tk.END, f)
            self._set_status(f"Added {len(files)} file(s). Total: {len(self.batch_bundles)}")

    def _add_bundle_folder(self):
        """Select folder and add bundle files inside"""
        folder = filedialog.askdirectory(title="Select Folder containing bundles")
        if folder:
            rec = self.batch_recursive.get()
            found = list(iter_bundle_files(folder, rec))
            added = 0
            for f in found:
                if f not in self.batch_bundles:
                    self.batch_bundles.append(f)
                    self.batch_list.insert(tk.END, f)
                    added += 1
            self._set_status(f"Added {added} bundle(s) from folder. Total: {len(self.batch_bundles)}")

    def _clear_bundles(self):
        """Clear bundle list"""
        self.batch_bundles.clear()
        self.batch_list.delete(0, tk.END)
        self._set_status("Bundle list cleared")

    def _set_status(self, text):
        self.status.config(text=text)
        self.root.update_idletasks()

    # ==================== Single Preview ====================
    def _preview_single(self):
        path = self.single_bundle.get()
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", "Select a valid bundle file")
            return
        try:
            env = UnityPy.load(path)
            self.single_list.delete(0, tk.END)
            count = 0
            for obj in env.objects:
                if obj.type.name == "Texture2D":
                    data = obj.read()
                    fmt = str(data.m_TextureFormat).split(".")[-1]
                    self.single_list.insert(tk.END, f"{data.m_Name} ({data.m_Width}x{data.m_Height}, {fmt})")
                    count += 1
            self._set_status(f"Found {count} textures")
        except Exception as e:
            messagebox.showerror("Error", f"Preview failed: {e}")

    # ==================== Runners ====================
    def _run_single(self):
        bundle = self.single_bundle.get()
        imgs = self.single_images.get()
        outp = self.single_output.get()
        fmt = self.texture_format.get()

        if not bundle or not os.path.exists(bundle):
            messagebox.showerror("Error", "Select a valid bundle file")
            return
        if not imgs or not os.path.isdir(imgs):
            messagebox.showerror("Error", "Select a valid image folder")
            return
        if not outp:
            messagebox.showerror("Error", "Select output bundle path")
            return

        def job():
            try:
                self._set_status("Importing (single)...")
                cnt = process_single_bundle(bundle, imgs, outp, fmt, self._set_status)
                self._set_status(f"Done. Imported {cnt} textures")
                messagebox.showinfo("Done", f"Imported {cnt} textures\nSaved: {outp}")
            except Exception as e:
                self._set_status("Error")
                messagebox.showerror("Error", str(e))

        threading.Thread(target=job, daemon=True).start()

    def _run_batch(self):
        if not self.batch_bundles:
            messagebox.showerror("Error", "No bundle files selected. Use Add Bundle Files or Add Folder.")
            return

        imgs = self.batch_images.get()
        outdir = self.batch_output.get()

        if not imgs or not os.path.isdir(imgs):
            messagebox.showerror("Error", "Select a valid image root folder")
            return
        if not outdir:
            messagebox.showerror("Error", "Select an output folder")
            return

        keep_tree = self.batch_preserve_tree.get()
        suffix = self.batch_out_suffix.get() or "_new"
        fmt = self.texture_format.get()

        def job():
            total_textures = 0
            processed = 0
            self._set_status("Importing (batch)...")
            try:
                for bundle_path in self.batch_bundles:
                    bn = os.path.basename(bundle_path)

                    # determine output path
                    if keep_tree:
                        # preserve original folder structure (based on parent folder of first bundle)
                        base = os.path.dirname(self.batch_bundles[0])
                        rel = os.path.relpath(bundle_path, start=base)
                        name, ext = os.path.splitext(rel)
                        outp = os.path.join(outdir, name + suffix + ext)
                    else:
                        name, ext = os.path.splitext(bn)
                        outp = os.path.join(outdir, name + suffix + ext)

                    safe_make_dir(outp)
                    cnt = process_single_bundle(bundle_path, imgs, outp, fmt, self._set_status)
                    total_textures += cnt
                    processed += 1
                    self._set_status(f"[{processed}/{len(self.batch_bundles)}] Saved: {outp} (imported {cnt})")

                self._set_status(f"Batch done. Bundles: {processed}, Imported textures: {total_textures}")
                messagebox.showinfo("Done", f"Bundles: {processed}\nImported textures: {total_textures}\nOutput: {outdir}")
            except Exception as e:
                self._set_status("Error")
                messagebox.showerror("Error", str(e))

        threading.Thread(target=job, daemon=True).start()

def main():
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
