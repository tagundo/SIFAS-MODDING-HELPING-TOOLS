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

try:
    # Optional: only used to SHARE / PERSIST the language choice with the other
    # SIFAS tools. Translations are embedded below, so this file works fully
    # (English / 한국어 / 日本語) even when copied out on its own.
    import sifas_i18n as _shared_i18n
except Exception:  # noqa: BLE001
    _shared_i18n = None

# --- self-contained translations (English source = key; English fallback) -----
_LANG_NAMES = (("en", "English"), ("ko", "한국어"), ("ja", "日本語"))
_TRANSLATIONS = {
    "ko": {
        "Language": "언어",
        "SIFAS Texture File Renamer": "SIFAS 텍스처 파일 이름변경기",
        "Select files": "파일 선택",
        "Clear list": "목록 비우기",
        "Selected files: {n}": "선택된 파일: {n}개",
        "Rename options": "이름변경 옵션",
        "Include Costume ID (insert YYYY between character name and original filename)":
            "코스튬 ID 포함 (캐릭터 이름과 원본 파일명 사이에 YYYY 삽입)",
        "Remove special characters (remove all special characters like _, -)":
            "특수문자 제거 (_, - 같은 모든 특수문자 제거)",
        "Original filename length limit:": "원본 파일명 길이 제한:",
        "(0 = no limit, excluding extension)": "(0 = 제한 없음, 확장자 제외)",
        "File list and preview": "파일 목록 및 미리보기",
        "Original filename": "원본 파일명",
        "Texture name": "텍스처 이름",
        "New filename": "새 파일명",
        "Preview changes": "변경 미리보기",
        "Batch process (copy and rename files)": "일괄 처리 (파일 복사 후 이름변경)",
        "Ready": "준비됨",
        "Not scanned": "스캔 안 됨",
        "Texture not found": "텍스처를 찾을 수 없음",
        "Cannot change": "변경 불가",
        "Warning": "경고",
        "Error": "오류",
        "Please select files first!": "먼저 파일을 선택하세요!",
        "Previewing changes...": "변경 사항 미리보는 중...",
        "Preview complete ({n} files)": "미리보기 완료 ({n}개 파일)",
        "Processing files...": "파일 처리 중...",
        "Processing complete": "처리 완료",
        "Processing failed": "처리 실패",
        "Processing Failed: {err}": "처리 실패: {err}",
        "Processing complete: {ok} success, {fail} failed": "처리 완료: 성공 {ok}개, 실패 {fail}개",
        "Unity Asset Bundle Select files": "Unity 에셋 번들 파일 선택",
        "Select output folder (where renamed files will be saved)":
            "출력 폴더 선택 (이름이 변경된 파일이 저장될 위치)",
        "Language changed. Restart the tool to apply it.":
            "언어가 변경되었습니다. 적용하려면 도구를 다시 시작하세요.",
    },
    "ja": {
        "Language": "言語",
        "SIFAS Texture File Renamer": "SIFAS テクスチャファイル名変更ツール",
        "Select files": "ファイルを選択",
        "Clear list": "リストをクリア",
        "Selected files: {n}": "選択ファイル: {n}個",
        "Rename options": "リネームオプション",
        "Include Costume ID (insert YYYY between character name and original filename)":
            "衣装IDを含める（キャラ名と元のファイル名の間に YYYY を挿入）",
        "Remove special characters (remove all special characters like _, -)":
            "特殊文字を除去（_、- などの特殊文字をすべて除去）",
        "Original filename length limit:": "元のファイル名の長さ制限:",
        "(0 = no limit, excluding extension)": "(0 = 制限なし、拡張子を除く)",
        "File list and preview": "ファイル一覧とプレビュー",
        "Original filename": "元のファイル名",
        "Texture name": "テクスチャ名",
        "New filename": "新しいファイル名",
        "Preview changes": "変更をプレビュー",
        "Batch process (copy and rename files)": "一括処理（ファイルをコピーしてリネーム）",
        "Ready": "準備完了",
        "Not scanned": "未スキャン",
        "Texture not found": "テクスチャが見つかりません",
        "Cannot change": "変更できません",
        "Warning": "警告",
        "Error": "エラー",
        "Please select files first!": "先にファイルを選択してください！",
        "Previewing changes...": "変更をプレビュー中...",
        "Preview complete ({n} files)": "プレビュー完了（{n}個のファイル）",
        "Processing files...": "ファイルを処理中...",
        "Processing complete": "処理完了",
        "Processing failed": "処理失敗",
        "Processing Failed: {err}": "処理に失敗しました: {err}",
        "Processing complete: {ok} success, {fail} failed": "処理完了: 成功 {ok}個、失敗 {fail}個",
        "Unity Asset Bundle Select files": "Unity アセットバンドルのファイルを選択",
        "Select output folder (where renamed files will be saved)":
            "出力フォルダを選択（リネームしたファイルの保存先）",
        "Language changed. Restart the tool to apply it.":
            "言語を変更しました。適用するにはツールを再起動してください。",
    },
}


def _normalize_lang(code):
    c = str(code or "").strip().lower().replace("-", "_").split("_")[0].split(".")[0]
    if c in ("ko", "kr", "kor"):
        return "ko"
    if c in ("ja", "jp", "jpn"):
        return "ja"
    return "en"


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

def generate_new_filename(orig_filename, tex_name, include_costume_id=False, 
                         remove_special_chars=False, filename_length_limit=None):
    """
    Generate new filename based on texture name
    
    Args:
        orig_filename: Original filename
        tex_name: Texture name (chXXXX_coYYYY_body)
        include_costume_id: costume ID (YYYY) whether to include
        remove_special_chars: whether to remove special characters
        filename_length_limit: Original filename length limit
    
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
    
    # Build new filename
    if ch == '9999':
        new_name = f"209rinamasked{orig_filename}"
    else:
        ch_num = str(int(ch))  # Remove leading zeros
        costume_part = co if include_costume_id else ""
        new_name = f"{ch_num}{chara}{costume_part}{orig_filename}"
    
    # Apply filename length limit to original part
    if filename_length_limit and filename_length_limit > 0:
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
        self.root.title(_tr("SIFAS Texture File Renamer"))
        self.root.geometry("900x650")

        self.file_list = []

        self.setup_ui()

    def _change_language(self, code):
        _set_lang(code)
        messagebox.showinfo(_tr("Language"),
                            _tr("Language changed. Restart the tool to apply it."))

    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Language picker
        lang_frame = ttk.Frame(main_frame)
        lang_frame.grid(row=0, column=0, columnspan=2, sticky=tk.E)
        ttk.Label(lang_frame, text=_tr("Language")).pack(side=tk.LEFT)
        _names = [n for _c, n in _lang_opts()]
        _code_by_name = {n: c for c, n in _lang_opts()}
        _name_by_code = {c: n for c, n in _lang_opts()}
        self._lang_display = tk.StringVar(value=_name_by_code.get(_get_lang(), _names[0]))
        _cb = ttk.Combobox(lang_frame, textvariable=self._lang_display, values=_names,
                           state="readonly", width=10)
        _cb.pack(side=tk.LEFT, padx=5)
        _cb.bind("<<ComboboxSelected>>",
                 lambda e: self._change_language(_code_by_name[self._lang_display.get()]))

        # Title
        title_label = ttk.Label(main_frame, text=_tr("SIFAS Texture File Renamer"),
                               font=('Arial', 14, 'bold'))
        title_label.grid(row=1, column=0, columnspan=2, pady=10)
        
        # File selection
        file_frame = ttk.LabelFrame(main_frame, text=_tr("Select files"), padding="5")
        file_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Button(file_frame, text=_tr("Select files"), command=self.select_files).grid(row=0, column=0, padx=5)
        ttk.Button(file_frame, text=_tr("Clear list"), command=self.clear_files).grid(row=0, column=1, padx=5)
        self.file_count_label = ttk.Label(file_frame, text=_tr("Selected files: {n}", n=0))
        self.file_count_label.grid(row=0, column=2, padx=20)

        # Options frame
        options_frame = ttk.LabelFrame(main_frame, text=_tr("Rename options"), padding="5")
        options_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Include costume ID option
        self.include_costume_var = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text=_tr("Include Costume ID (insert YYYY between character name and original filename)"),
                       variable=self.include_costume_var, command=self.on_option_change).grid(row=0, column=0, sticky=tk.W, pady=2)

        # Remove special characters option
        self.remove_special_var = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text=_tr("Remove special characters (remove all special characters like _, -)"),
                       variable=self.remove_special_var, command=self.on_option_change).grid(row=1, column=0, sticky=tk.W, pady=2)

        # Filename length limit
        length_frame = ttk.Frame(options_frame)
        length_frame.grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Label(length_frame, text=_tr("Original filename length limit:")).pack(side=tk.LEFT)
        self.length_limit_var = tk.StringVar(value="0")
        length_entry = ttk.Entry(length_frame, textvariable=self.length_limit_var, width=10)
        length_entry.pack(side=tk.LEFT, padx=5)
        length_entry.bind('<KeyRelease>', lambda e: self.on_option_change())
        ttk.Label(length_frame, text=_tr("(0 = no limit, excluding extension)")).pack(side=tk.LEFT)

        # File list
        list_frame = ttk.LabelFrame(main_frame, text=_tr("File list and preview"), padding="5")
        list_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        # Treeview for file list (column identifiers stay constant; only headings are translated)
        columns = ("Original filename", "Texture name", "New filename")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)

        self.tree.heading("Original filename", text=_tr("Original filename"))
        self.tree.heading("Texture name", text=_tr("Texture name"))
        self.tree.heading("New filename", text=_tr("New filename"))

        self.tree.column("Original filename", width=250)
        self.tree.column("Texture name", width=200)
        self.tree.column("New filename", width=300)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=10)

        ttk.Button(button_frame, text=_tr("Preview changes"), command=self.preview_changes,
                  width=20).grid(row=0, column=0, padx=5)
        ttk.Button(button_frame, text=_tr("Batch process (copy and rename files)"), command=self.process_files,
                  width=30).grid(row=0, column=1, padx=5)

        # Progress bar
        self.progress = ttk.Progressbar(main_frame, length=500, mode='determinate')
        self.progress.grid(row=6, column=0, columnspan=2, pady=5)

        # Status label
        self.status_label = ttk.Label(main_frame, text=_tr("Ready"), font=('Arial', 10))
        self.status_label.grid(row=7, column=0, columnspan=2)

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
    
    def select_files(self):
        files = filedialog.askopenfilenames(
            title=_tr("Unity Asset Bundle Select files"),
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
        self.file_count_label.config(text=_tr("Selected files: {n}", n=len(self.file_list)))
    
    def update_file_list(self):
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Add files to tree
        for file_path in self.file_list:
            filename = os.path.basename(file_path)
            self.tree.insert("", "end", values=(filename, _tr("Not scanned"), ""))
    
    def on_option_change(self):
        """Preview automatically updates when options change"""
        if self.file_list:
            self.preview_changes()
    
    def preview_changes(self):
        if not self.file_list:
            messagebox.showwarning(_tr("Warning"), _tr("Please select files first!"))
            return
        
        self.status_label.config(text=_tr("Previewing changes..."))
        self.progress['maximum'] = len(self.file_list)
        self.progress['value'] = 0
        
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        for i, file_path in enumerate(self.file_list):
            filename = os.path.basename(file_path)
            
            # Extract texture name
            tex_name = extract_texture_name(file_path)
            tex_display = tex_name if tex_name else _tr("Texture not found")
            
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
                    filename_length_limit=length_limit
                )
            else:
                new_name = _tr("Cannot change")
            
            self.tree.insert("", "end", values=(filename, tex_display, new_name))
            
            self.progress['value'] = i + 1
            self.root.update_idletasks()
        
        self.status_label.config(text=_tr("Preview complete ({n} files)", n=len(self.file_list)))
    
    def process_files(self):
        if not self.file_list:
            messagebox.showwarning(_tr("Warning"), _tr("Please select files first!"))
            return
        
        # Ask for output directory
        output_dir = filedialog.askdirectory(title=_tr("Select output folder (where renamed files will be saved)"))
        if not output_dir:
            return
        
        def process_thread():
            try:
                self.status_label.config(text=_tr("Processing files..."))
                self.progress['maximum'] = len(self.file_list)
                self.progress['value'] = 0
                
                success_count = 0
                failed_files = []
                
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
                            filename_length_limit=length_limit
                        )
                        
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
                
                messagebox.showinfo(_tr("Processing complete"), result_msg)
                self.status_label.config(text=_tr("Processing complete: {ok} success, {fail} failed", ok=success_count, fail=len(failed_files)))
                
            except Exception as e:
                messagebox.showerror(_tr("Error"), _tr("Processing Failed: {err}", err=str(e)))
                self.status_label.config(text=_tr("Processing failed"))
        
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
