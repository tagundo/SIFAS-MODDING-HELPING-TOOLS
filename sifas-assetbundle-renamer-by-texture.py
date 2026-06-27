#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS Texture File Renamer
GUI tool to automatically rename files by extracting ch texture names from Unity asset bundle files
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import re
import threading
import subprocess
import sys

# Dependency helper for UnityPy
def ensure_unitypy():
    try:
        return __import__("UnityPy")
    except ImportError:
        try:
            print("Installing UnityPy...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "UnityPy"])
            return __import__("UnityPy")
        except Exception as e:
            print(f"Failed to install UnityPy: {e}")
            return None

# Character mapping dictionary (Character code -> name)
CHARA_MAP = {
    '0001': 'honoka', '0002': 'eli', '0003': 'kotori', '0004': 'umi', '0005': 'rin',
    '0006': 'maki', '0007': 'nozomi', '0008': 'hanayo', '0009': 'nico',
    '0101': 'chika', '0102': 'riko', '0103': 'kanan', '0104': 'dia', '0105': 'you',
    '0106': 'yoshiko', '0107': 'hanamaru', '0108': 'mari', '0109': 'ruby',
    '0201': 'ayumu', '0202': 'kasumi', '0203': 'shizuku', '0204': 'karin', '0205': 'ai', 
    '0206': 'kanata', '0207': 'setsuna', '0208': 'emma', '0209': 'rinaunmasked',
    '9999': 'rinaunmasked','0210': 'shioriko','0211': 'lanzhu','0212': 'mia'
}

def extract_texture_name(bundle_path):
    """Extract ch texture name from Unity asset bundle"""
    UnityPy = ensure_unitypy()
    if UnityPy is None:
        return None
    
    try:
        env = UnityPy.load(bundle_path)
        body_pat = re.compile(r"^ch\d{4}_co\d{4}_body$")
        
        for obj in env.objects:
            if getattr(obj.type, "name", "") != "Texture2D":
                continue
            data = obj.read()
            name = getattr(data, "name", getattr(data, "m_Name", ""))
            if body_pat.match(name):
                return name
    except Exception as e:
        print(f"Error extracting texture from {bundle_path}: {e}")
        return None
    return None

def make_unique_filename(name, used_names, sep="_"):
    """
    Ensure ``name`` is unique within ``used_names``.

    When the original filename is dropped, many bundles collapse to the same
    character-based name and would otherwise overwrite each other. This appends
    ``sep`` + a counter (e.g. ``_2``, ``_3``) before the extension until the
    name is unique. ``used_names`` is mutated to record the chosen name.

    Args:
        name: Desired filename
        used_names: Set of names already taken
        sep: Separator placed before the counter ("" keeps it special-char free)

    Returns:
        A filename guaranteed not to be in the original ``used_names``
    """
    if name not in used_names:
        used_names.add(name)
        return name

    base, ext = os.path.splitext(name)
    i = 2
    while True:
        candidate = f"{base}{sep}{i}{ext}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        i += 1


def generate_new_filename(orig_filename, tex_name, include_costume_id=False,
                         remove_special_chars=False, filename_length_limit=None,
                         remove_original_name=False):
    """
    Generate new filename based on texture name

    Args:
        orig_filename: Original filename
        tex_name: Texture name (chXXXX_coYYYY_body)
        include_costume_id: costume ID (YYYY) whether to include
        remove_special_chars: whether to remove special characters
        filename_length_limit: Original filename length limit
        remove_original_name: if True, drop the original filename entirely and
            keep only the character-based name (the original extension, if any,
            is preserved). filename_length_limit is ignored in this mode.

    Returns:
        new filename
    """
    if not tex_name:
        return orig_filename

    # Parse chXXXX_coYYYY_body
    m = re.match(r'ch(\d{4})_co(\d{4})_body', tex_name)
    if not m:
        return orig_filename

    ch, co = m.group(1), m.group(2)
    chara = CHARA_MAP.get(ch, ch)

    # Decide how much of the original filename to keep
    if remove_original_name:
        # Keep nothing from the original name except its extension (if any)
        _, orig_part = os.path.splitext(orig_filename)
    else:
        orig_part = orig_filename

    # Build new filename
    if ch == '9999':
        new_name = f"209rinamasked{orig_part}"
    else:
        ch_num = str(int(ch))  # Remove leading zeros
        costume_part = co if include_costume_id else ""
        new_name = f"{ch_num}{chara}{costume_part}{orig_part}"

    # Apply filename length limit to original part
    # (skipped when the original name is removed - there is nothing to trim)
    if filename_length_limit and filename_length_limit > 0 and not remove_original_name:
        # Extract the original filename part (after character info)
        if ch == '9999':
            prefix = "209rinamasked"
            orig_part = new_name[len(prefix):]
            if len(orig_part) > filename_length_limit:
                # Keep extension intact
                name_without_ext, ext = os.path.splitext(orig_part)
                if len(name_without_ext) > filename_length_limit:
                    name_without_ext = name_without_ext[:filename_length_limit]
                orig_part = name_without_ext + ext
            new_name = prefix + orig_part
        else:
            prefix = f"{ch_num}{chara}{costume_part}"
            orig_part = new_name[len(prefix):]
            if len(orig_part) > filename_length_limit:
                # Keep extension intact
                name_without_ext, ext = os.path.splitext(orig_part)
                if len(name_without_ext) > filename_length_limit:
                    name_without_ext = name_without_ext[:filename_length_limit]
                orig_part = name_without_ext + ext
            new_name = prefix + orig_part
    
    # Remove special characters if requested
    if remove_special_chars:
        # Keep only alphanumeric characters and dots (for file extensions)
        new_name = re.sub(r'[^a-zA-Z0-9.]', '', new_name)
    
    return new_name

class TextureFileRenamerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SIFAS Texture File Renamer")
        self.root.geometry("900x650")
        
        self.file_list = []
        
        self.setup_ui()
    
    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="SIFAS Texture File Renamer", 
                               font=('Arial', 14, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=10)
        
        # File selection
        file_frame = ttk.LabelFrame(main_frame, text="Select files", padding="5")
        file_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Button(file_frame, text="Select files", command=self.select_files).grid(row=0, column=0, padx=5)
        ttk.Button(file_frame, text="Clear list", command=self.clear_files).grid(row=0, column=1, padx=5)
        self.file_count_label = ttk.Label(file_frame, text="Selected files: 0")
        self.file_count_label.grid(row=0, column=2, padx=20)
        
        # Options frame
        options_frame = ttk.LabelFrame(main_frame, text="Rename options", padding="5")
        options_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # Include costume ID option
        self.include_costume_var = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="Include Costume ID (insert YYYY between character name and original filename)",
                       variable=self.include_costume_var, command=self.on_option_change).grid(row=0, column=0, sticky=tk.W, pady=2)
        
        # Remove special characters option
        self.remove_special_var = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="Remove special characters (remove all special characters like _, -)",
                       variable=self.remove_special_var, command=self.on_option_change).grid(row=1, column=0, sticky=tk.W, pady=2)

        # Remove original filename completely option
        self.remove_original_var = tk.BooleanVar()
        ttk.Checkbutton(options_frame,
                       text="Remove original filename completely (keep only the character name; a _2, _3... suffix is added to avoid collisions)",
                       variable=self.remove_original_var, command=self.on_option_change).grid(row=2, column=0, sticky=tk.W, pady=2)

        # Filename length limit
        length_frame = ttk.Frame(options_frame)
        length_frame.grid(row=3, column=0, sticky=tk.W, pady=2)
        ttk.Label(length_frame, text="Original filename length limit:").pack(side=tk.LEFT)
        self.length_limit_var = tk.StringVar(value="0")
        length_entry = ttk.Entry(length_frame, textvariable=self.length_limit_var, width=10)
        length_entry.pack(side=tk.LEFT, padx=5)
        length_entry.bind('<KeyRelease>', lambda e: self.on_option_change())
        ttk.Label(length_frame, text="(0 = no limit, excluding extension)").pack(side=tk.LEFT)
        
        # File list
        list_frame = ttk.LabelFrame(main_frame, text="File list and preview", padding="5")
        list_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        # Treeview for file list
        columns = ("Original filename", "Texture name", "New filename")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        
        self.tree.heading("Original filename", text="Original filename")
        self.tree.heading("Texture name", text="Texture name")
        self.tree.heading("New filename", text="New filename")
        
        self.tree.column("Original filename", width=250)
        self.tree.column("Texture name", width=200)
        self.tree.column("New filename", width=300)
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=10)
        
        ttk.Button(button_frame, text="Preview changes", command=self.preview_changes, 
                  width=20).grid(row=0, column=0, padx=5)
        ttk.Button(button_frame, text="Batch process (copy and rename files)", command=self.process_files,
                  width=30).grid(row=0, column=1, padx=5)
        
        # Progress bar
        self.progress = ttk.Progressbar(main_frame, length=500, mode='determinate')
        self.progress.grid(row=5, column=0, columnspan=2, pady=5)
        
        # Status label
        self.status_label = ttk.Label(main_frame, text="Ready", font=('Arial', 10))
        self.status_label.grid(row=6, column=0, columnspan=2)
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
    
    def select_files(self):
        files = filedialog.askopenfilenames(
            title="Unity Asset Bundle Select files",
            filetypes=[("Unity files", "*.unity"), ("All files", "*.*")]
        )
        
        if files:
            # Avoid duplicates
            for f in files:
                if f not in self.file_list:
                    self.file_list.append(f)
            self.update_file_count()
            self.update_file_list()
    
    def clear_files(self):
        self.file_list.clear()
        self.update_file_count()
        self.update_file_list()
    
    def update_file_count(self):
        self.file_count_label.config(text=f"Selected files: {len(self.file_list)}")
    
    def update_file_list(self):
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Add files to tree
        for file_path in self.file_list:
            filename = os.path.basename(file_path)
            self.tree.insert("", "end", values=(filename, "Not scanned", ""))
    
    def on_option_change(self):
        """Preview automatically updates when options change"""
        if self.file_list:
            self.preview_changes()
    
    def preview_changes(self):
        if not self.file_list:
            messagebox.showwarning("Warning", "Please select files first!")
            return
        
        self.status_label.config(text="Previewing changes...")
        self.progress['maximum'] = len(self.file_list)
        self.progress['value'] = 0
        
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Track names already produced so the preview matches what will be
        # written (the same collision handling is used during processing).
        used_names = set()
        sep = "" if self.remove_special_var.get() else "_"

        for i, file_path in enumerate(self.file_list):
            filename = os.path.basename(file_path)

            # Extract texture name
            tex_name = extract_texture_name(file_path)
            tex_display = tex_name if tex_name else "Texture not found"

            # Generate new filename
            if tex_name:
                try:
                    length_limit = int(self.length_limit_var.get()) if self.length_limit_var.get() else None
                except ValueError:
                    length_limit = None

                new_name = generate_new_filename(
                    filename, tex_name,
                    include_costume_id=self.include_costume_var.get(),
                    remove_special_chars=self.remove_special_var.get(),
                    filename_length_limit=length_limit,
                    remove_original_name=self.remove_original_var.get()
                )
                new_name = make_unique_filename(new_name, used_names, sep=sep)
            else:
                new_name = "Cannot change"

            self.tree.insert("", "end", values=(filename, tex_display, new_name))
            
            self.progress['value'] = i + 1
            self.root.update_idletasks()
        
        self.status_label.config(text=f"Preview complete ({len(self.file_list)}files)")
    
    def process_files(self):
        if not self.file_list:
            messagebox.showwarning("Warning", "Please select files first!")
            return
        
        # Ask for output directory
        output_dir = filedialog.askdirectory(title="Select output folder (where renamed files will be saved)")
        if not output_dir:
            return
        
        def process_thread():
            try:
                self.status_label.config(text="Processing files...")
                self.progress['maximum'] = len(self.file_list)
                self.progress['value'] = 0
                
                success_count = 0
                failed_files = []

                # Track output names so two inputs never overwrite each other
                # (essential when the original name is removed).
                used_names = set()
                sep = "" if self.remove_special_var.get() else "_"

                for i, file_path in enumerate(self.file_list):
                    filename = os.path.basename(file_path)

                    # Extract texture name
                    tex_name = extract_texture_name(file_path)

                    if tex_name:
                        try:
                            length_limit = int(self.length_limit_var.get()) if self.length_limit_var.get() else None
                        except ValueError:
                            length_limit = None

                        new_name = generate_new_filename(
                            filename, tex_name,
                            include_costume_id=self.include_costume_var.get(),
                            remove_special_chars=self.remove_special_var.get(),
                            filename_length_limit=length_limit,
                            remove_original_name=self.remove_original_var.get()
                        )
                        new_name = make_unique_filename(new_name, used_names, sep=sep)

                        # Copy file with new name
                        try:
                            import shutil
                            new_path = os.path.join(output_dir, new_name)
                            shutil.copy2(file_path, new_path)
                            success_count += 1
                        except Exception as e:
                            failed_files.append(f"{filename}: {str(e)}")
                    else:
                        failed_files.append(f"{filename}: Texture not found")
                    
                    self.progress['value'] = i + 1
                    self.root.update_idletasks()
                
                # Show results
                result_msg = f"Processing complete!\nSuccess: {success_count} files"
                if failed_files:
                    result_msg += f"\nFailed: {len(failed_files)}files"
                    if len(failed_files) <= 5:
                        result_msg += "\n\nFailed files:\n" + "\n".join(failed_files)
                    else:
                        result_msg += f"\n\nFirst 5 failed files:\n" + "\n".join(failed_files[:5])
                
                result_msg += f"\n\nOutput location: {output_dir}"
                
                messagebox.showinfo("Processing complete", result_msg)
                self.status_label.config(text=f"Processing complete: {success_count} success, {len(failed_files)} failed")
                
            except Exception as e:
                messagebox.showerror("Error", f"Processing Failed: {str(e)}")
                self.status_label.config(text="Processing failed")
        
        # Run processing in separate thread
        thread = threading.Thread(target=process_thread)
        thread.daemon = True
        thread.start()

def main():
    root = tk.Tk()
    app = TextureFileRenamerGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
